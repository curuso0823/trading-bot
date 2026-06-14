"""
notebooks/capped_backtest.py
忠實重現 LIVE 的『top-N 並倉上限』策略並掃 max_positions（回測從不設上限 → live 3 檔是未驗證的集中版）。
邏輯對齊 live：每日依 chip_score 由高到低填補空位；vol-sizing 對『剩餘現金』收 size_pct；
ATR per-position 移動停損；max_hold 交易日；T+1 同日不可賣；訊號T→開盤T+1執行（含滑價+費稅）。
與 vectorbt 無上限版對照（後者=已驗證 Sharpe 0.90 的『廣度分散』版）。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from src.backtest.signal_builder import HistoricalSignalBuilder
from src.backtest.backtester import TaiwanBacktester
from src.utils.helpers import load_config

U = ["2330","2454","2303","2308","2379","3034","3711","2337","6415","3008","2317","2382",
     "2357","2376","3231","4938","2356","2353","2881","2882","2891","2886","2884","2885",
     "2892","5880","1301","1303","1326","2002","1101","2207","2603","2609","2615","2412","2912","1216"]
START, END = "2018-01-01", "2025-12-31"
SLIP, LOT = 0.0015, 1
COST = load_config()["cost"]


def _buyfee(amt):
    return max(round(amt * COST["buy_fee_rate"]), COST.get("min_fee_odd", 1))


def _sellcost(amt):
    return max(round(amt * COST["sell_fee_rate"]), COST.get("min_fee_odd", 1)) + round(amt * COST["sell_tax_rate"])


def panels():
    b = HistoricalSignalBuilder()
    b.selection_cfg = {"sector_cap_enabled": False}
    b.cap_cfg = {**load_config().get("capitulation", {})}
    price_df, sig = b.build(U, START, END)
    close = price_df.pivot(index="date", columns="stock_id", values="close").sort_index().ffill().bfill()
    op = price_df.pivot(index="date", columns="stock_id", values="open").reindex_like(close).ffill().bfill()
    hi = price_df.pivot(index="date", columns="stock_id", values="high").reindex_like(close).ffill().bfill()
    lo = price_df.pivot(index="date", columns="stock_id", values="low").reindex_like(close).ffill().bfill()
    entry = sig.pivot(index="date", columns="stock_id", values="entry_signal").reindex(index=close.index, columns=close.columns).fillna(False)
    score = sig.pivot(index="date", columns="stock_id", values="score").reindex(index=close.index, columns=close.columns).fillna(0.0)
    vol20 = close.pct_change().rolling(20).std()
    size_pct = (0.30 * 0.02 / vol20).clip(0.10, 0.30)
    pc = close.shift(1)
    trng = np.maximum.reduce([(hi - lo).values, (hi - pc).abs().values, (lo - pc).abs().values])
    atr_pct = pd.DataFrame(trng, index=close.index, columns=close.columns).rolling(14).mean() / close
    trail = (4.5 * atr_pct).clip(0.08, 0.09)
    return close, op, entry, score, size_pct, trail, price_df, sig


def simulate(close, op, entry, score, size_pct, trail, max_pos, cap):
    C, O, E, SC = close.values, op.values, entry.values, score.values
    SZ, TR = size_pct.values, trail.values
    n, m = C.shape
    cash, held, eq, trades = float(cap), {}, np.empty(n), 0
    for i in range(n):
        eq[i] = cash + sum(h["qty"] * C[i, c] * LOT for c, h in held.items())
        if i + 1 >= n:
            continue
        ni = i + 1
        for c, h in held.items():
            if C[i, c] > h["peak"]:
                h["peak"] = C[i, c]
        for c in [c for c, h in held.items()
                  if (i - h["entry_i"]) >= 1 and (C[i, c] <= h["peak"] * (1 - h["trail"]) or (i - h["entry_i"]) >= 60)]:
            h = held.pop(c)
            amt = O[ni, c] * (1 - SLIP) * h["qty"] * LOT
            cash += amt - _sellcost(amt)
            trades += 1
        free = max_pos - len(held)
        if free > 0:
            cands = sorted([(c, SC[i, c]) for c in range(m) if E[i, c] and c not in held],
                           key=lambda x: -x[1])[:free]
            for c, _ in cands:
                sp = SZ[i, c] if np.isfinite(SZ[i, c]) else 0.30
                fill = O[ni, c] * (1 + SLIP)
                if not np.isfinite(fill) or fill <= 0:
                    continue
                qty = int((cash * sp) / (fill * LOT))
                while qty >= 1 and fill * qty * LOT + _buyfee(fill * qty * LOT) > cash:
                    qty -= 1
                if qty < 1:
                    continue
                amt = fill * qty * LOT
                cash -= amt + _buyfee(amt)
                held[c] = {"qty": qty, "peak": fill, "entry_i": ni,
                           "trail": TR[i, c] if np.isfinite(TR[i, c]) else 0.09}
    s = pd.Series(eq, index=close.index)
    r = s.pct_change().dropna()
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0
    cagr = (s.iloc[-1] / s.iloc[0]) ** (252 / len(s)) - 1 if s.iloc[0] > 0 else 0.0
    dd = (s / s.cummax() - 1).min()
    return cagr, sharpe, dd, trades, s


def _year_stats(s, yr):
    sy = s[s.index.year == yr]
    if len(sy) < 5:
        return None
    r = sy.pct_change().dropna()
    return (sy.iloc[-1] / sy.iloc[0] - 1, r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0,
            (sy / sy.cummax() - 1).min())


def main():
    close, op, entry, score, size_pct, trail, price_df, sig = panels()
    print("LIVE 集中版（top-N 並倉上限）max_positions 掃描，70k 零股 block_only：")
    print(f"{'max_pos':>9}{'年化':>8}{'Sharpe':>8}{'回撤':>8}{'交易':>7}")
    eqs = {}
    for mp in [3, 4, 5, 6, 8, 12, 38]:
        cagr, sh, dd, tr, s = simulate(close, op, entry, score, size_pct, trail, mp, 70_000)
        eqs[mp] = s
        tag = "  ← 現行live" if mp == 3 else ("  ← Sharpe峰" if mp == 5 else ("  ≈無上限(回測)" if mp == 38 else ""))
        print(f"{mp:>9}{cagr*100:>7.1f}%{sh:>8.2f}{dd*100:>7.1f}%{tr:>7}{tag}")
    bt = TaiwanBacktester()
    st = bt.run(price_df, sig, initial_capital=70_000)["stats"]
    print(f"\n  [對照] vectorbt 無上限：年化 {st['annual_return']*100:.1f}%、Sharpe {st['sharpe_ratio']:.2f}、"
          f"DD {st['max_drawdown']*100:.1f}%（廣度分散版=已驗證 0.90）")

    print("\n分年穩健度（年化% / Sharpe）— 確認 mp=5 非單一年僥倖：")
    print(f"{'年':>6}{'mp=3':>16}{'mp=4':>16}{'mp=5':>16}")
    for yr in range(2018, 2026):
        cells = []
        for mp in [3, 4, 5]:
            st_y = _year_stats(eqs[mp], yr)
            cells.append(f"{st_y[0]*100:>7.1f}%/{st_y[1]:>5.2f}" if st_y else f"{'—':>13}")
        print(f"{yr:>6}" + "".join(f"{c:>16}" for c in cells))


if __name__ == "__main__":
    main()

"""
notebooks/benchmark_backtest.py
0050「波動目標 + 部分現金」對照組回測（2018-01-01 ~ 2025-12-31）。

目的：用最低複雜度（單標的 + 波動目標曝險 + 月度/偏離再平衡）逼近/超越現行策略的風險調整報酬。
與「現行 active 策略」「0050 買進持有」並列比較，並掃 target_daily_vol 與 regime overlay 變體。

資料：直接讀『已快取』的 0050 原始日線 + 除權息 pickle，沿用 FinMindFetcher 的還原邏輯做反向還原
     —— 不打任何 API（與 capped_sim 同一份還原口徑，避免重抓爆額度）。
模擬：純 pandas/numpy（無 vectorbt），風格對齊 src/backtest/capped_sim.py：
     訊號 T → 開盤 T+1 執行、買進 +slip / 賣出 −slip、台股費稅（買賣 0.1425% + 賣稅 0.3%）。
     再平衡：每月第一個交易日或曝險偏離 > rebalance_band 才調倉。現金利息以 0 計。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from src.data.fetcher import FinMindFetcher
from src.utils.helpers import load_config
from src.strategy_engines.benchmark_engine import (
    vol_target_exposure, is_month_first_trading_day,
)

SYMBOL = "0050"
START, END = "2018-01-01", "2025-12-31"
CACHE = "data/raw/finmind_cache"
INITIAL = 100_000.0
SLIP = float(load_config()["trading"].get("odd_lot_slippage", 0.0015))   # 零股滑價，與 live 對齊
LOT = 1                                                                  # 零股，每股
COST = load_config()["cost"]
BAND = 0.05            # 曝險偏離 > 5pp 才調倉
LOOKBACK = 20


# ── 成本（與 capped_sim bf/sc 同口徑；零股最低手續費 1 元）────────────────────────
def _buyfee(amt):
    return max(round(amt * COST["buy_fee_rate"]), COST.get("min_fee_odd", 1))


def _sellcost(amt):
    return max(round(amt * COST["sell_fee_rate"]), COST.get("min_fee_odd", 1)) + round(amt * COST["sell_tax_rate"])


# ── 載入『快取』0050 還原日線（不打 API）─────────────────────────────────────────
def load_adjusted_0050() -> pd.DataFrame:
    """讀 2016-01-01~2025-12-31 的快取 pickle，沿用 fetcher 還原邏輯反向還原 OHLC。"""
    px = pd.read_pickle(f"{CACHE}/TaiwanStockPrice__{SYMBOL}__2016-01-01__2025-12-31.pkl")
    div = pd.read_pickle(f"{CACHE}/TaiwanStockDividendResult__{SYMBOL}__2016-01-01__2025-12-31.pkl")
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values("date").reset_index(drop=True)
    px = px.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    px = px[(px["close"] > 0) & (px["open"] > 0)].reset_index(drop=True)
    px["adj_close"] = px["close"]
    px = px[["date", "open", "high", "low", "close", "volume", "adj_close"]]
    div["date"] = pd.to_datetime(div["date"])
    for c in ["before_price", "after_price"]:
        div[c] = pd.to_numeric(div[c], errors="coerce")
    adj = FinMindFetcher._apply_back_adjust(px, div)
    # warm-up：MA200 需要 ~1 年前置，故從 2016 載入、回測只截 2018+（exposure/MA 已有足夠暖身）
    return adj.reset_index(drop=True)


# ── 統計（與 capped_sim._stats 同公式）──────────────────────────────────────────
def _stats(eq: pd.Series, trades: list, label: str) -> dict:
    r = eq.pct_change().dropna()
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0
    yrs = len(eq) / 252
    cagr = float((eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1) if eq.iloc[0] > 0 and yrs > 0 else 0.0
    dd = float((eq / eq.cummax() - 1).min())
    wins = [t for t in trades if t > 0]
    loss = [t for t in trades if t <= 0]
    pf = float(sum(wins) / abs(sum(loss))) if loss and sum(loss) != 0 else (999.0 if wins else 0.0)
    return {"label": label, "annual": cagr, "sharpe": sharpe, "dd": dd, "pf": pf,
            "total_return": float(eq.iloc[-1] / eq.iloc[0] - 1), "n_trades": len(trades),
            "final": float(eq.iloc[-1]), "equity": eq}


def _per_year(eq: pd.Series) -> dict:
    out = {}
    for yr in sorted(set(eq.index.year)):
        sy = eq[eq.index.year == yr]
        if len(sy) < 5:
            continue
        ry = sy.pct_change().dropna()
        out[int(yr)] = (float(sy.iloc[-1] / sy.iloc[0] - 1),
                        float(ry.mean() / ry.std() * np.sqrt(252)) if ry.std() > 0 else 0.0,
                        float((sy / sy.cummax() - 1).min()))
    return out


# ── 對照組模擬（波動目標 + 月度/偏離再平衡）─────────────────────────────────────
def simulate_benchmark(adj: pd.DataFrame, target_vol: float, *, overlay=False,
                       regime_ma=200, regime_action="half") -> dict:
    """單標的 0050 波動目標再平衡。訊號 T（用收盤算曝險）→ 開盤 T+1 成交（+/-滑價+費稅）。
    每月第一個交易日 或 |現曝險−目標| > BAND 才調倉。回傳 stats（含權益曲線）。"""
    df = adj[(adj["date"] >= pd.Timestamp(START)) & (adj["date"] <= pd.Timestamp(END))].copy()
    df = df.reset_index(drop=True)
    dates = pd.DatetimeIndex(df["date"])
    close = df["close"].to_numpy(float)
    opn = df["open"].to_numpy(float)

    # 目標曝險用『全段含暖身』close 算（從 2016），再對齊到回測窗 → MA200/vol20 暖身充足
    full_close = adj.set_index("date")["close"]
    exp_full = vol_target_exposure(full_close, target_daily_vol=target_vol, lookback=LOOKBACK,
                                   exposure_cap=1.0, regime_overlay=overlay,
                                   regime_ma=regime_ma, regime_action=regime_action)
    target_exp = exp_full.reindex(dates).to_numpy(float)
    month_first = is_month_first_trading_day(dates).to_numpy(bool)

    n = len(df)
    cash, qty = INITIAL, 0
    eq = np.empty(n)
    trades = []
    avg_cost = 0.0          # 持倉每股均成本（含買費攤計）→ 賣出時結算該批已實現損益
    for i in range(n):
        eq[i] = cash + qty * close[i] * LOT
        if i + 1 >= n:
            continue
        te = target_exp[i]
        if not np.isfinite(te):
            continue
        equity_now = eq[i]
        cur_value = qty * close[i] * LOT
        cur_exp = cur_value / equity_now if equity_now > 0 else 0.0
        drift = abs(cur_exp - te)
        if not (month_first[i] or drift > BAND):
            continue
        # 開盤 T+1 成交價（買 +slip / 賣 −slip）
        fill_buy = opn[i + 1] * (1 + SLIP)
        fill_sell = opn[i + 1] * (1 - SLIP)
        # 目標股數以「成交價 + 目標曝險」反推（用權益估，成交後再受現金約束）
        target_qty = int((equity_now * te) / (fill_buy * LOT)) if fill_buy > 0 else 0
        delta = target_qty - qty
        if delta > 0:        # 加碼（現金約束）
            buyable = delta
            while buyable >= 1:
                amt = fill_buy * buyable * LOT
                if amt + _buyfee(amt) <= cash:
                    break
                buyable -= 1
            if buyable < 1:
                continue
            amt = fill_buy * buyable * LOT
            cash -= amt + _buyfee(amt)
            # 更新均成本（含買費攤計）
            new_qty = qty + buyable
            avg_cost = (avg_cost * qty + (amt + _buyfee(amt))) / new_qty
            qty = new_qty
        elif delta < 0:      # 減碼（賣出，結算已實現損益）
            sell_qty = -delta
            amt = fill_sell * sell_qty * LOT
            proceeds = amt - _sellcost(amt)
            cash += proceeds
            pnl = proceeds - avg_cost * sell_qty   # avg_cost 已含買費 → pnl 為淨已實現
            trades.append(pnl)
            qty -= sell_qty
            if qty == 0:
                avg_cost = 0.0
    eq_s = pd.Series(eq, index=dates)
    ov = (f"+MA{regime_ma}{'歸零' if regime_action == 'zero' else '減半'}" if overlay else "")
    return _stats(eq_s, trades, f"BM vol{target_vol:.3f}{ov}")


# ── 0050 買進持有（含 1 次買進費；用還原淨值報酬）────────────────────────────────
def simulate_buyhold(adj: pd.DataFrame) -> dict:
    df = adj[(adj["date"] >= pd.Timestamp(START)) & (adj["date"] <= pd.Timestamp(END))].copy().reset_index(drop=True)
    dates = pd.DatetimeIndex(df["date"])
    close = df["close"].to_numpy(float)
    opn = df["open"].to_numpy(float)
    fill = opn[1] * (1 + SLIP) if len(opn) > 1 else close[0]
    qty = int(INITIAL / (fill * LOT))
    cash = INITIAL - (fill * qty * LOT + _buyfee(fill * qty * LOT))
    eq = cash + qty * close * LOT
    return _stats(pd.Series(eq, index=dates), [], "0050 買進持有")


# ── 主流程 ──────────────────────────────────────────────────────────────────────
def main():
    adj = load_adjusted_0050()
    print(f"0050 還原日線（快取，無 API）：{len(adj)} 列，{adj['date'].min().date()} ~ {adj['date'].max().date()}")
    print(f"回測窗 {START} ~ {END}｜初始 {INITIAL:,.0f}｜零股滑價 {SLIP}｜再平衡帶 {BAND*100:.0f}pp｜月度再平衡 ON\n")

    bh = simulate_buyhold(adj)

    variants = []
    # target_daily_vol 變體（規格建議 0.011，另測 0.009 / 0.013；
    #   實證：0050 長期日波動中位僅 ~0.0095(≈15%年化) < 17.5% 目標 → cap 常綁滿、去風險有限。
    #   故另加 0.006 / 0.008 兩個「較低目標」探索去風險前緣，看能否提升風險調整報酬）。
    for tv in [0.006, 0.008, 0.009, 0.011, 0.013]:
        variants.append(simulate_benchmark(adj, tv, overlay=False))
    # overlay 變體（以建議 0.011 為基準，比較有/無 overlay；MA200 與 MA60、half 與 zero）
    variants.append(simulate_benchmark(adj, 0.011, overlay=True, regime_ma=200, regime_action="half"))
    variants.append(simulate_benchmark(adj, 0.011, overlay=True, regime_ma=200, regime_action="zero"))
    variants.append(simulate_benchmark(adj, 0.011, overlay=True, regime_ma=60, regime_action="half"))
    # 低目標 + overlay 組合（去風險前緣的右下角：最大化 Sharpe/壓 DD）
    variants.append(simulate_benchmark(adj, 0.008, overlay=True, regime_ma=200, regime_action="half"))

    # 現行 active 策略（任務給定的已驗證數字；非本腳本重算）
    active = {"label": "現行 active 策略", "annual": 0.127, "sharpe": 1.16, "dd": -0.16,
              "pf": None, "total_return": None, "n_trades": None}

    # ── 主比較表 ──
    print("=" * 78)
    print("主比較表（2018-2025，初始 100k，含台股費稅）")
    print("-" * 78)
    hdr = f"{'策略':<26}{'年化':>8}{'Sharpe':>8}{'最大回撤':>10}{'PF':>7}{'總報酬':>9}{'交易':>6}"
    print(hdr)
    print("-" * 78)

    def _row(s):
        ann = f"{s['annual']*100:>6.1f}%" if s.get("annual") is not None else f"{'—':>7}"
        sh = f"{s['sharpe']:>8.2f}" if s.get("sharpe") is not None else f"{'—':>8}"
        dd = f"{s['dd']*100:>8.1f}%" if s.get("dd") is not None else f"{'—':>9}"
        pf = f"{s['pf']:>7.2f}" if s.get("pf") not in (None, 999.0) else (f"{'∞':>7}" if s.get('pf') == 999.0 else f"{'—':>7}")
        tot = f"{s['total_return']*100:>7.0f}%" if s.get("total_return") is not None else f"{'—':>8}"
        nt = f"{s['n_trades']:>6}" if s.get("n_trades") is not None else f"{'—':>6}"
        print(f"{s['label']:<26}{ann}{sh}{dd}{pf} {tot}{nt}")

    _row(active)
    _row(bh)
    print("-" * 78)
    for s in variants:
        _row(s)
    print("=" * 78)

    # ── 分年穩健度（建議基準 vol0.011 無 overlay vs 0050 買進持有）──
    base = next(s for s in variants if s["label"] == "BM vol0.011")
    print("\n分年穩健度：對照組(vol0.011,無overlay) vs 0050買進持有（年化% / Sharpe / 回撤%）")
    print(f"{'年':>6}{'對照組 vol0.011':>26}{'0050 買進持有':>26}")
    py_b, py_h = _per_year(base["equity"]), _per_year(bh["equity"])
    for yr in range(2018, 2026):
        b = py_b.get(yr)
        h = py_h.get(yr)
        bc = f"{b[0]*100:>7.1f}% /{b[1]:>5.2f} /{b[2]*100:>6.1f}%" if b else f"{'—':>22}"
        hc = f"{h[0]*100:>7.1f}% /{h[1]:>5.2f} /{h[2]*100:>6.1f}%" if h else f"{'—':>22}"
        print(f"{yr:>6}{bc:>26}{hc:>26}")

    # ── 一句話結論 ──
    print("\n" + "=" * 78)
    best = max(variants, key=lambda s: s["sharpe"])
    print(f"結論：最佳對照組變體 = {best['label']}，"
          f"年化 {best['annual']*100:.1f}% / Sharpe {best['sharpe']:.2f} / DD {best['dd']*100:.1f}%。")
    print(f"      vs 現行 active（12.7%/1.16/-16%）與 0050 買進持有"
          f"（{bh['annual']*100:.1f}%/{bh['sharpe']:.2f}/{bh['dd']*100:.1f}%）。")


if __name__ == "__main__":
    main()

"""
notebooks/r6_retreat_sweep.py
R6 最後防線「退場深度」分年掃描：MA200 跌破時保留曝險 mult ∈ {0, 0.25, 0.5, 0.75}（0=全退現金=現committed zero、
0.5=half、0.75=輕修）。base＝0050 vol-managed(target_vol 0.011)。純快取、0 API、不改引擎。
引擎僅支援 zero/half → 本腳本在 notebook 端用數值 mult 複製 simulate_benchmark 的「同成本/再平衡」交易迴圈
（重用 bm._buyfee/_sellcost/_stats/_per_year/SLIP/LOT/BAND…），與引擎口徑一致；mult=0 與引擎 action=zero 對照核驗。

⚠️ 描述性特徵化（非證實超額；R5 已定無顯著 alpha）。0050 無 survivorship；單期 power 有限。
用法：.venv/bin/python notebooks/r6_retreat_sweep.py
"""
import os
import sys
import importlib.util

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
NB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(NB_DIR)
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

_spec = importlib.util.spec_from_file_location("bm", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

SQRT252 = np.sqrt(252)
FWD = [2022, 2023, 2024, 2025]
TARGET_VOL, MA = 0.011, 200


def exp_mult(close_full, mult):
    """vol-target(0.011) 曝險，MA200 跌破時 ×mult（0=全退、1=不退）。在 full close 算（含2016暖身）。"""
    c = close_full.astype(float)
    rv = c.pct_change().rolling(bm.LOOKBACK).std()
    exp = (TARGET_VOL / rv).clip(lower=0.0, upper=1.0).where(rv > 0, 0.0).fillna(0.0)
    below = (c < c.rolling(MA).mean()).fillna(False)
    return exp.where(~below, exp * float(mult))


def sim_from_exp(adj, exp_full, label):
    """複製 simulate_benchmark 交易迴圈（同滑價/費稅/月度+5pp帶再平衡），但餵入自訂 exposure。"""
    df = adj[(adj["date"] >= pd.Timestamp(bm.START)) & (adj["date"] <= pd.Timestamp(bm.END))].reset_index(drop=True)
    dates = pd.DatetimeIndex(df["date"])
    close = df["close"].to_numpy(float)
    opn = df["open"].to_numpy(float)
    target_exp = exp_full.reindex(dates).to_numpy(float)
    month_first = bm.is_month_first_trading_day(dates).to_numpy(bool)
    n = len(df)
    cash, qty, avg_cost = bm.INITIAL, 0, 0.0
    eq = np.empty(n)
    trades = []
    for i in range(n):
        eq[i] = cash + qty * close[i] * bm.LOT
        if i + 1 >= n:
            continue
        te = target_exp[i]
        if not np.isfinite(te):
            continue
        equity_now = eq[i]
        cur_exp = (qty * close[i] * bm.LOT) / equity_now if equity_now > 0 else 0.0
        if not (month_first[i] or abs(cur_exp - te) > bm.BAND):
            continue
        fill_buy, fill_sell = opn[i + 1] * (1 + bm.SLIP), opn[i + 1] * (1 - bm.SLIP)
        target_qty = int((equity_now * te) / (fill_buy * bm.LOT)) if fill_buy > 0 else 0
        delta = target_qty - qty
        if delta > 0:
            buyable = delta
            while buyable >= 1:
                amt = fill_buy * buyable * bm.LOT
                if amt + bm._buyfee(amt) <= cash:
                    break
                buyable -= 1
            if buyable < 1:
                continue
            amt = fill_buy * buyable * bm.LOT
            cash -= amt + bm._buyfee(amt)
            new_qty = qty + buyable
            avg_cost = (avg_cost * qty + (amt + bm._buyfee(amt))) / new_qty
            qty = new_qty
        elif delta < 0:
            sell_qty = -delta
            amt = fill_sell * sell_qty * bm.LOT
            proceeds = amt - bm._sellcost(amt)
            cash += proceeds
            trades.append(proceeds - avg_cost * sell_qty)
            qty -= sell_qty
            if qty == 0:
                avg_cost = 0.0
    return bm._stats(pd.Series(eq, index=dates), trades, label)


def agg(eq, oos=False):
    e = eq[eq.index.year.isin(FWD)] if oos else eq
    r = e.pct_change().dropna()
    sh = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    ann = float((e.iloc[-1] / e.iloc[0]) ** (252 / len(e)) - 1)
    dd = float((e / e.cummax() - 1).min())
    return ann, sh, dd, (ann / abs(dd) if abs(dd) > 1e-9 else float("nan"))


print("R6 退場深度掃描 | 載入快取 0050（0 API）…")
adj = bm.load_adjusted_0050()
close_full = adj.set_index("date")["close"].sort_index().astype(float)

# 參考端點
bh = bm.simulate_buyhold(adj)
benb = bm.simulate_benchmark(adj, TARGET_VOL, overlay=False)        # 無防線（≈mult 1）
# 退場深度
MULTS = [0.0, 0.25, 0.5, 0.75]
sims = {m: sim_from_exp(adj, exp_mult(close_full, m), f"mult{m}") for m in MULTS}

# 核驗：mult=0 ≈ 引擎 action=zero
eng_zero = bm.simulate_benchmark(adj, TARGET_VOL, overlay=True, regime_ma=MA, regime_action="zero")
d_ann = abs(agg(sims[0.0]["equity"])[0] - agg(eng_zero["equity"])[0])
print(f"[核驗] mult=0 複製 vs 引擎 action=zero：全期年化差 {d_ann*100:.3f}pp（應≈0）")

LAB = {0.0: "防線mult0(全退,現)", 0.25: "防線mult0.25", 0.5: "防線mult0.5(half)", 0.75: "防線mult0.75"}
PY = {m: bm._per_year(sims[m]["equity"]) for m in MULTS}
PY0050 = bm._per_year(bh["equity"])


def cell(t):
    return f"{t[0]*100:>6.1f}%/{t[1]:>5.2f}/{t[2]*100:>6.1f}%" if t else f"{'—':>20}"


print("\n" + "=" * 110)
print("分年（報酬%/Sharpe/年內maxDD%）｜base=0050 vol-mgd(0.011)，MA200 跌破時保留 mult 曝險")
print("=" * 110)
print(f"{'年':>5}{'0050買持':>21}{'mult0.25':>21}{'mult0.5(half)':>21}{'mult0.75':>21}")
for y in range(2018, 2026):
    print(f"{y:>5}{cell(PY0050.get(y)):>21}{cell(PY[0.25].get(y)):>21}{cell(PY[0.5].get(y)):>21}{cell(PY[0.75].get(y)):>21}")
print("關鍵年：2018＝盤整(whipsaw 反傷年) / 2022＝大熊(防線最有利)。退得越深(mult→0)＝2022 越保護、2018 越被洗。")

print("\n" + "=" * 110)
print("整體（全期2018-25 ｜ OOS2022-25）：年化%/Sharpe/maxDD%/Calmar")
print("=" * 110)
print(f"{'策略':<22}{'全期年化':>9}{'Sh':>6}{'maxDD':>8}{'Cal':>6}{'｜OOS年化':>10}{'Sh':>6}{'maxDD':>8}{'Cal':>6}")
rows = [("0050純買持", bh["equity"]), ("基準B(無防線≈m1)", benb["equity"])]
rows = [("0050純買持", bh["equity"])] + [(LAB[m], sims[m]["equity"]) for m in MULTS] + [("基準B(無防線≈m1)", benb["equity"])]
for name, eq in rows:
    f, o = agg(eq), agg(eq, oos=True)
    print(f"{name:<22}{f[0]*100:>9.1f}{f[1]:>6.2f}{f[2]*100:>8.1f}{f[3]:>6.2f}{o[0]*100:>10.1f}{o[1]:>6.2f}{o[2]*100:>8.1f}{o[3]:>6.2f}")

print("\n讀法：mult 越小（退越深）→ 2022 熊市/全期 maxDD 越淺，但 2018 盤整 whipsaw 越傷、牛市讓利越多。")
print("引擎現支援 zero(=mult0)/half(=mult0.5)；若選 0.25/0.75 需小改 BenchmarkEngine 讓 regime_action 收數值。")
print("⚠️ 描述性；R5 已定無顯著 alpha、全期 0050 買持仍勝；單期 power 有限。")
print("\n[done] R6 退場深度掃描完成（純快取）。")

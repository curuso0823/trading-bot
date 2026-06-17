"""
notebooks/r6_bh_half_backtest.py
R6 變體分年回測：**拔掉 vol-cap**（base＝100% 0050 純買持，無 vol-target）＋ 只留「跌破 MA200 → 半倉(50%)」。
＝平時滿倉跟 0050；唯 0050 跌破 MA200 砍半、漲回 MA200 回滿。純快取、0 API、不改引擎（用同一交易/成本迴圈）。

對照：0050 純買持、現committed(vol-mgd0.011+MA200 zero)、BH+MA200 zero、基準B(無防線)。
⚠️ 描述性（R5 已定無顯著 alpha）；0050 無 survivorship；單期 power 有限；MA200 為結構性選參。
live 實作：引擎用高 target_daily_vol（如 1.0）使 vol-cap 失效＝base 100%，regime_action=half → 零 code 改動。
用法：.venv/bin/python notebooks/r6_bh_half_backtest.py
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
MA = 200


def exp_bh(close_full, mult_below):
    """base 100%（無 vol-cap）；0050 跌破 MA200 當日 → mult_below。"""
    below = (close_full < close_full.rolling(MA).mean()).fillna(False)
    return pd.Series(1.0, index=close_full.index).where(~below, float(mult_below))


def exp_volmgd(close_full, mult_below):
    """vol-target 0.011 base（現committed 口徑）；跌破 MA200 → ×mult_below。"""
    rv = close_full.pct_change().rolling(bm.LOOKBACK).std()
    exp = (0.011 / rv).clip(lower=0.0, upper=1.0).where(rv > 0, 0.0).fillna(0.0)
    below = (close_full < close_full.rolling(MA).mean()).fillna(False)
    return exp.where(~below, exp * float(mult_below))


def sim_from_exp(adj, exp_full, label):
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
            cash += amt - bm._sellcost(amt)
            trades.append((amt - bm._sellcost(amt)) - avg_cost * sell_qty)
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


print("R6 BH+MA200half（拔 vol-cap）分年回測 | 載入快取 0050（0 API）…")
adj = bm.load_adjusted_0050()
cf = adj.set_index("date")["close"].sort_index().astype(float)

S = {
    "0050純買持": bm.simulate_buyhold(adj)["equity"],
    "BH+MA200half(新)": sim_from_exp(adj, exp_bh(cf, 0.5), "bh_half")["equity"],
    "BH+MA200zero": sim_from_exp(adj, exp_bh(cf, 0.0), "bh_zero")["equity"],
    "vol-mgd+MA200zero(現)": sim_from_exp(adj, exp_volmgd(cf, 0.0), "volmgd_zero")["equity"],
    "基準B(無防線)": bm.simulate_benchmark(adj, 0.011, overlay=False)["equity"],
}
PY = {k: bm._per_year(v) for k, v in S.items()}


def cell(t):
    return f"{t[0]*100:>6.1f}%/{t[1]:>5.2f}/{t[2]*100:>6.1f}%" if t else f"{'—':>20}"


print("\n" + "=" * 92)
print("分年（報酬%/Sharpe/年內maxDD%）｜BH+MA200half＝平時滿倉跟0050、跌破MA200砍半、漲回回滿")
print("=" * 92)
print(f"{'年':>5}{'0050純買持':>22}{'BH+MA200half(新)':>22}{'vol-mgd+zero(現)':>22}")
for y in range(2018, 2026):
    print(f"{y:>5}{cell(PY['0050純買持'].get(y)):>22}{cell(PY['BH+MA200half(新)'].get(y)):>22}{cell(PY['vol-mgd+MA200zero(現)'].get(y)):>22}")

print("\n" + "=" * 92)
print("整體（全期2018-25 ｜ OOS2022-25）：年化%/Sharpe/maxDD%/Calmar")
print("=" * 92)
print(f"{'策略':<24}{'全期年化':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}{'｜OOS年化':>9}{'Sh':>6}{'maxDD':>8}{'Cal':>6}")
for name, eq in S.items():
    f, o = agg(eq), agg(eq, oos=True)
    print(f"{name:<24}{f[0]*100:>8.1f}{f[1]:>6.2f}{f[2]*100:>8.1f}{f[3]:>6.2f}{o[0]*100:>9.1f}{o[1]:>6.2f}{o[2]*100:>8.1f}{o[3]:>6.2f}")

below = (cf < cf.rolling(MA).mean()).fillna(False)
print("\nMA200 半倉觸發（per year，BH+MA200half）：該年半倉天數 / 是否曾跌破")
for y in range(2018, 2026):
    m = cf.index.year == y
    if m.sum() < 5:
        continue
    by = below[m]
    print(f"{y:>6}  半倉天數 {int(by.sum()):>4}  曾跌破MA200 {'是' if bool(by.any()) else '否'}")

print("\n讀法：base 拔掉 vol-cap → 平時 100% 跟 0050（牛市不再讓利）；唯跌破 MA200 砍半。")
print("⚠️ 描述性；全期 0050 純買持仍是報酬王；此變體＝以『跌破半倉』換較淺 DD。R5 無顯著 alpha、單期 power 有限。")
print("[done] R6 BH+MA200half 分年回測完成（純快取）。")

"""
notebooks/r6_retreat_finegrid.py
R6 最後防線「留倉比例」細網格掃描：base＝100% 0050（無 vol-cap）；0050 跌破 MA200 當日保留 mult 曝險，
mult ∈ {0%, 5%, …, 100%}（21 點）。mult=100%＝純 0050 買持；mult=0%＝跌破全退現金；mult=50%＝前一輪的 BH+half。
純快取、0 API、不改引擎（同一交易/成本迴圈）。

⚠️ 風險偏好旋鈕、非「找最佳 mult」（鐵則#7：別用 sample 峰值挑＝curve-fit）。R5 已定無顯著 alpha；
   0050 無 survivorship；單期 power 有限；MA200 為結構性選參。全期 0050 純買持仍是報酬王。
用法：.venv/bin/python notebooks/r6_retreat_finegrid.py
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
    below = (close_full < close_full.rolling(MA).mean()).fillna(False)
    return pd.Series(1.0, index=close_full.index).where(~below, float(mult_below))


def sim_from_exp(adj, exp_full):
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
    return pd.Series(eq, index=dates)


def agg(eq, oos=False):
    e = eq[eq.index.year.isin(FWD)] if oos else eq
    r = e.pct_change().dropna()
    sh = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    ann = float((e.iloc[-1] / e.iloc[0]) ** (252 / len(e)) - 1)
    dd = float((e / e.cummax() - 1).min())
    return ann, sh, dd, (ann / abs(dd) if abs(dd) > 1e-9 else float("nan"))


print("R6 留倉比例細網格（0~100% / 5%）| 載入快取 0050（0 API）…")
adj = bm.load_adjusted_0050()
cf = adj.set_index("date")["close"].sort_index().astype(float)
below = (cf < cf.rolling(MA).mean()).fillna(False)
f_below = float(below[cf.index.year >= 2018].mean())

MULTS = [round(0.05 * i, 2) for i in range(21)]
rows = []
for m in MULTS:
    eq = sim_from_exp(adj, exp_bh(cf, m))
    f, o = agg(eq), agg(eq, oos=True)
    py = bm._per_year(eq)
    y22 = py.get(2022, (float("nan"),) * 3)
    y18 = py.get(2018, (float("nan"),) * 3)
    avg_exp = (1 - f_below) + f_below * m
    rows.append((m, avg_exp, f, o, y22, y18))

print("\n" + "=" * 124)
print("留倉比例細網格｜base 100% 0050、跌破 MA200 保留『留倉%』曝險（漲回 MA200 回滿）｜2018-25 跌破MA200佔比 "
      f"{f_below*100:.0f}%")
print("=" * 124)
print(f"{'留倉%':>5}{'平均曝險%':>9}｜{'全期ann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜"
      f"{'OOSann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜{'2022年DD':>9}{'2018年報酬':>11}")
print("-" * 124)
for m, ae, f, o, y22, y18 in rows:
    star = "  ←純0050" if m == 1.0 else ("  ←前輪half" if m == 0.5 else ("  ←現committed類比(全退)" if m == 0.0 else ""))
    print(f"{m*100:>5.0f}{ae*100:>9.0f}｜{f[0]*100:>8.1f}{f[1]:>6.2f}{f[2]*100:>8.1f}{f[3]:>6.2f}｜"
          f"{o[0]*100:>8.1f}{o[1]:>6.2f}{o[2]*100:>8.1f}{o[3]:>6.2f}｜{y22[2]*100:>9.1f}{y18[0]*100:>9.1f}%{star}")
print("-" * 124)

# 趨勢摘要（不挑峰值；只報結構性單調/轉折）
full_dd = [r[2][2] for r in rows]
best_full_cal = max(rows, key=lambda r: (r[2][3] if r[2][3] == r[2][3] else -9))
best_full_dd = max(rows, key=lambda r: r[2][2])  # least negative
print(f"趨勢：留倉↑（退越淺）→ 全期報酬單調↑（{rows[0][2][0]*100:.0f}%→{rows[-1][2][0]*100:.0f}%）、2022 保護↓、2018 whipsaw↓。")
print(f"  全期 maxDD 最淺出現在 留倉≈{best_full_dd[0]*100:.0f}%（{best_full_dd[2][2]*100:.1f}%）；全期 Calmar 最高在 留倉≈{best_full_cal[0]*100:.0f}%（{best_full_cal[2][3]:.2f}）。")
print("  ⚠️ 上述峰值＝此 8 年 sample 的，**勿據以挑 mult（curve-fit）**；這是風險偏好旋鈕。R5 無顯著 alpha、全期 0050 仍報酬最高。")
print("\n[done] 留倉比例細網格完成（純快取）。")

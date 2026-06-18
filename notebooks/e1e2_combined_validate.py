"""
notebooks/e1e2_combined_validate.py
落地前驗證：把 E1（N 日確認）與 E2（對稱緩衝帶）整併成**單一統一 overlay**，對候選 live 參數做固定配置回測。
此處的 exp_combined() 就是預定要加進引擎的邏輯（additive：confirm_days + band_pct；預設 1/0.0 = 現行行為）。

統一狀態機（generalises 兩者；(n=1,band=0)＝current-live）：
  exit  full→reduced(0.85)：close < MA200×(1−band) 連續 confirm 日。
  reentry reduced→full(1.0)：close > MA200×(1+band) 連續 confirm 日。
  中間（死區或未滿足確認）維持現態。

目的：在「分別調成穩健參數」後，驗證 combined 是否仍過 §5 結構 Gate（DD 不惡化 + whipsaw↓ + 牛市不犧牲），
     並特別檢查 **2020 V 型急崩是否被雙重確認 over-lag**（過度確認→出場太慢→失去崩盤保護）。
參數非 in-sample 峰（鐵則#7）：N=3＝Alvarez SPY/QQQ 文獻甜蜜點 N=2-3、高原內；band=1%≈台股 0050 一日移動、SMA-envelope 慣例。

⚠️ 描述性、survivorship 上界；純快取、0 API、不改任何既有檔。
用法：.venv/bin/python notebooks/e1e2_combined_validate.py
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
REDUCED, FULL = 0.85, 1.0


def sharpe_of(dr):
    sd = dr.std()
    return float(dr.mean() / sd * SQRT252) if sd > 0 else 0.0


def year_dr(eq, y):
    return eq[eq.index.year == y].pct_change().dropna()


def agg(eq, oos=False):
    e = eq[eq.index.year.isin(FWD)] if oos else eq
    r = e.pct_change().dropna()
    sh = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    ann = float((e.iloc[-1] / e.iloc[0]) ** (252 / len(e)) - 1)
    dd = float((e / e.cummax() - 1).min())
    return ann, sh, dd, (ann / abs(dd) if abs(dd) > 1e-9 else float("nan"))


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
    n_exec = 0
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
            n_exec += 1
        elif delta < 0:
            sell_qty = -delta
            amt = fill_sell * sell_qty * bm.LOT
            cash += amt - bm._sellcost(amt)
            qty -= sell_qty
            if qty == 0:
                avg_cost = 0.0
            n_exec += 1
    return pd.Series(eq, index=dates), n_exec


# ════════════════════════════════════════════════════════════════════════════════
# 統一 overlay 狀態機（= 預定加進引擎的 additive 邏輯）
# ════════════════════════════════════════════════════════════════════════════════
def exp_combined(close_full, confirm_days=1, band_pct=0.0):
    """E1∩E2 統一：close<MA×(1−band) 連續 confirm 日→reduced；close>MA×(1+band) 連續 confirm 日→full。
    (confirm_days=1, band_pct=0.0) 逐位重現 current-live。暖身 NaN→未跌破→維持 full（與基線一致）。"""
    cf = close_full.astype(float)
    ma = cf.rolling(MA).mean()
    c = cf.to_numpy(float)
    m = ma.to_numpy(float)
    n = len(cf)
    out = np.empty(n, dtype=float)
    state = FULL
    run_below = run_above = 0
    for i in range(n):
        if np.isfinite(m[i]):
            lo, hi = m[i] * (1.0 - band_pct), m[i] * (1.0 + band_pct)
            below_band, above_band = (c[i] < lo), (c[i] > hi)
        else:
            below_band = above_band = False
        run_below = run_below + 1 if below_band else 0
        run_above = run_above + 1 if above_band else 0
        if state == FULL:
            if run_below >= confirm_days:
                state = REDUCED
        else:
            if run_above >= confirm_days:
                state = FULL
        out[i] = state
    return pd.Series(out, index=cf.index)


def flips_in_year(exp_series, year):
    s = exp_series[exp_series.index.year == year]
    if len(s) < 2:
        return 0
    b = np.isclose(s.to_numpy(float), REDUCED).astype(int)
    return int((np.diff(b) != 0).sum())


# ── 載入 + 對照 ──────────────────────────────────────────────────────────────────
print("=" * 122)
print("E1+E2 整併 候選 live 配置 落地前驗證 | 載入快取 0050（0 API / cache-only）…")
print("=" * 122)
adj = bm.load_adjusted_0050()
cf = adj.set_index("date")["close"].sort_index().astype(float)
bh_eq = bm.simulate_buyhold(adj)["equity"]
bb_eq = bm.simulate_benchmark(adj, 0.011, overlay=False)["equity"]

# 退化點 sanity：exp_combined(1,0.0) ≡ current-live
live_eq, live_nx = sim_from_exp(adj, exp_combined(cf, 1, 0.0))
eng = bm.simulate_benchmark(adj, 1.0, overlay=True, regime_ma=MA, regime_action=0.85)["equity"]
assert float((live_eq - eng).abs().max()) < 1e-3, "exp_combined(1,0.0) 未重現 current-live！"
print(f"[sanity] exp_combined(1,0.0) ≡ current-live（max|Δ|<1e-3 元）；current-live 交易數={live_nx}；0 API/cache-only。")

# δ（雜訊尺度）
live_oos = pd.concat([year_dr(live_eq, Y) for Y in FWD])
SR_d = float(live_oos.mean() / live_oos.std())
DELTA = float(np.sqrt((1 + 0.5 * SR_d ** 2) / len(live_oos)) * SQRT252)

# 固定對照基準 worst-fwd-DD / 2020 DD / 牛市
def worst_fwd_dd(eq):
    return min(bm._per_year(eq).get(Y, (0, 0, 0))[2] for Y in FWD)


def py3(eq, y):
    return bm._per_year(eq).get(y, (float("nan"),) * 3)   # (ret, sharpe, dd)


LIVE_WFD = worst_fwd_dd(live_eq)
LIVE_2020DD = py3(live_eq, 2020)[2]
LIVE_OOS_ANN = agg(live_eq, oos=True)[0]
LIVE_FL22 = flips_in_year(exp_combined(cf, 1, 0.0), 2022)
BH_WFD, BB_WFD = worst_fwd_dd(bh_eq), worst_fwd_dd(bb_eq)
S0 = sharpe_of(pd.concat([year_dr(bh_eq, Y) for Y in FWD]))
SB = sharpe_of(pd.concat([year_dr(bb_eq, Y) for Y in FWD]))

# ── 候選配置 ─────────────────────────────────────────────────────────────────────
CONFIGS = [
    ("current-live(N=1,band=0)", 1, 0.0),
    ("E1-only N=3", 3, 0.0),
    ("E2-only band=1.0%", 1, 0.010),
    ("combined N=3 + 1.0%", 3, 0.010),
    ("combined 保守 N=4 + 1.25%", 4, 0.0125),
    ("combined 輕 N=2 + 0.5%", 2, 0.005),
]
res = []
for name, nd, bd in CONFIGS:
    e = exp_combined(cf, nd, bd)
    eq, nx = sim_from_exp(adj, e)
    f, o = agg(eq), agg(eq, oos=True)
    res.append(dict(name=name, nd=nd, bd=bd, eq=eq, exp=e, nx=nx,
                    f_ann=f[0], f_sh=f[1], f_dd=f[2], f_cal=f[3],
                    o_ann=o[0], o_sh=o[1], o_dd=o[2], wfd=worst_fwd_dd(eq),
                    r18=py3(eq, 2018), r20=py3(eq, 2020), r22=py3(eq, 2022),
                    a23=py3(eq, 2023)[0], a24=py3(eq, 2024)[0], a25=py3(eq, 2025)[0],
                    fl18=flips_in_year(e, 2018), fl20=flips_in_year(e, 2020), fl22=flips_in_year(e, 2022)))

# ── 主表 ─────────────────────────────────────────────────────────────────────────
print(f"\nδ(OOS Sharpe 1SE)={DELTA:.3f}｜固定對照：0050 worstFwdDD {BH_WFD*100:.1f}% / 基準B {BB_WFD*100:.1f}%｜"
      f"OOS Sharpe 0050 {S0:.2f} / 基準B {SB:.2f}")
print("=" * 122)
print(f"{'配置':<26}｜{'全期ann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜{'OOSann':>8}{'Sh':>6}{'worstFwd':>9}｜"
      f"{'fl22':>5}{'fl18':>5}{'交易':>5}")
print("-" * 122)
for r in res:
    print(f"{r['name']:<26}｜{r['f_ann']*100:>8.1f}{r['f_sh']:>6.2f}{r['f_dd']*100:>8.1f}{r['f_cal']:>6.2f}｜"
          f"{r['o_ann']*100:>8.1f}{r['o_sh']:>6.2f}{r['wfd']*100:>9.1f}｜{r['fl22']:>5}{r['fl18']:>5}{r['nx']:>5}")
print("-" * 122)

# ── 2018 / 2020 / 2022 stress 焦點（含 over-lag 檢查）─────────────────────────────
print("\n" + "=" * 122)
print("stress 年焦點：2018(in-sample chop) / 2020(V急崩→over-lag 檢查) / 2022(OOS熊市) — 報酬/Sharpe/DD/flips")
print("=" * 122)
print(f"{'配置':<26}｜{'18報酬':>7}{'18Sh':>6}{'fl18':>5}｜{'20報酬':>7}{'20DD':>7}{'fl20':>5}｜"
      f"{'22報酬':>7}{'22Sh':>6}{'22DD':>7}{'fl22':>5}")
print("-" * 122)
for nm, eq in [("0050 買持", bh_eq), ("基準B", bb_eq)]:
    a, c, b = py3(eq, 2018), py3(eq, 2020), py3(eq, 2022)
    print(f"{nm:<26}｜{a[0]*100:>6.1f}%{a[1]:>6.2f}{'—':>5}｜{c[0]*100:>6.1f}%{c[2]*100:>6.1f}%{'—':>5}｜"
          f"{b[0]*100:>6.1f}%{b[1]:>6.2f}{b[2]*100:>6.1f}%{'—':>5}")
for r in res:
    a, c, b = r["r18"], r["r20"], r["r22"]
    print(f"{r['name']:<26}｜{a[0]*100:>6.1f}%{a[1]:>6.2f}{r['fl18']:>5}｜{c[0]*100:>6.1f}%{c[2]*100:>6.1f}%{r['fl20']:>5}｜"
          f"{b[0]*100:>6.1f}%{b[1]:>6.2f}{b[2]*100:>6.1f}%{r['fl22']:>5}")
print("-" * 122)

# ── 結構 Gate 逐配置裁決（vs current-live）+ over-lag 檢查 ──────────────────────────
print("\n" + "=" * 122)
print("結構 Gate 逐配置（vs current-live；§5：DD 不惡化 + whipsaw↓ + 牛市不犧牲 + 2020 不 over-lag）")
print("=" * 122)
for r in res:
    if r["nd"] == 1 and r["bd"] == 0.0:
        continue
    g_dd = (r["wfd"] >= LIVE_WFD - 1e-9) and (r["wfd"] > BB_WFD) and (r["wfd"] > BH_WFD)
    g_sh = r["o_sh"] >= sharpe_of(live_oos) - DELTA
    g_whip = r["fl22"] < LIVE_FL22
    g_bull = r["o_ann"] >= LIVE_OOS_ANN - 0.01
    overlag = r["r20"][2] - LIVE_2020DD          # 2020 DD 相對 live 的變化（負＝更深＝over-lag）
    g_2020 = overlag > -0.015                     # 2020 DD 惡化 ≤1.5pp 才算可接受
    allp = g_dd and g_sh and g_whip and g_bull and g_2020
    print(f"{r['name']:<26}：DD不惡化{'✓' if g_dd else '✗'}({r['wfd']*100:.1f}% vs live {LIVE_WFD*100:.1f}%) | "
          f"OOSsh{'✓' if g_sh else '✗'}({r['o_sh']:.2f}) | whip{'✓' if g_whip else '✗'}(22flips {r['fl22']}<{LIVE_FL22}) | "
          f"牛市{'✓' if g_bull else '✗'}(OOSann {r['o_ann']*100:.1f}%) | "
          f"2020{'✓' if g_2020 else '✗'}(DD {r['r20'][2]*100:.1f}%, Δ{overlag*100:+.1f}pp) → "
          f"{'結構 Gate PASS' if allp else '注意'}")
print("-" * 122)
print("讀法：所有 combined/single 候選都應 DD 不惡化 + whip↓ + 牛市不犧牲；關鍵差異在 2020 over-lag（confirm 越大越可能）。")
print("參數＝穩健高原值（非 in-sample 峰，鐵則#7）：N=3＝Alvarez 文獻、band=1%≈一日移動。最終由使用者拍板。")
print("[done] 落地前驗證完成（純快取、0 API、未改任何既有檔）。alpha 仍 FAIL（R5）；定位＝結構性降 whipsaw 微調。")

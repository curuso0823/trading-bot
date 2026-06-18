"""
notebooks/e1_nday_confirm.py
E1 — N 日連續確認 overlay（沙盒研究；純快取、0 API、不改任何既有檔）。

機制（狀態機，支援非對稱）：base＝100% 0050（無 vol-cap，等價 target_daily_vol=1.0），
  - full(1.0) → reduced(0.85)：需連續 N_exit 日 close < MA200 才成立。
  - reduced(0.85) → full(1.0)：需連續 N_reentry 日 close >= MA200 才成立。
  - 中間（未滿足轉態條件）維持現態。初始態＝full。
退化點 N_exit=N_reentry=1 ＝每日 MA200 規則，逐位重現 current-live 基線
  （bm.simulate_benchmark(adj,1.0,overlay=True,regime_ma=200,regime_action=0.85)）。

⚠️ 描述性、非證實：R5 已定誠實池無顯著 alpha；此 overlay 定位＝結構性降回撤/降 whipsaw 規則、非 outperformer。
   FinMind 無下市股 → 所有結果是上界（survivorship）。細網格＝特徵化/找線索，結論只綁 OOS + plateau 穩定度。
用法：.venv/bin/python notebooks/e1_nday_confirm.py
"""
import os
import sys
import importlib.util

# ── importlib 區塊（逐字複製自 r6_retreat_finegrid.py L11-28，把 benchmark_backtest.py 載為 bm）────
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
REDUCED = 0.85          # 出 15%
FULL = 1.0


# ── sim_from_exp（逐字複製自 r6_retreat_finegrid.py L40-87，擴充：另回傳實際成交再平衡筆數）──────
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
    n_exec = 0          # 擴充：實際成交（delta!=0 的買或賣）次數
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
            n_exec += 1                       # 擴充：成交一次買
        elif delta < 0:
            sell_qty = -delta
            amt = fill_sell * sell_qty * bm.LOT
            cash += amt - bm._sellcost(amt)
            trades.append((amt - bm._sellcost(amt)) - avg_cost * sell_qty)
            qty -= sell_qty
            if qty == 0:
                avg_cost = 0.0
            n_exec += 1                       # 擴充：成交一次賣
    return pd.Series(eq, index=dates), n_exec


# ── agg（逐字複製自 r6_retreat_finegrid.py L90-96）────────────────────────────────────────────
def agg(eq, oos=False):
    e = eq[eq.index.year.isin(FWD)] if oos else eq
    r = e.pct_change().dropna()
    sh = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    ann = float((e.iloc[-1] / e.iloc[0]) ** (252 / len(e)) - 1)
    dd = float((e / e.cummax() - 1).min())
    return ann, sh, dd, (ann / abs(dd) if abs(dd) > 1e-9 else float("nan"))


# ── E1 狀態機目標曝險 Series（cf.index 全段，含 2016 暖身）────────────────────────────────────
def exp_nday(close_full, ma_series, raw_below, n_exit, n_reentry):
    """N 日連續確認狀態機。回傳每日目標曝險（FULL/REDUCED）Series（close_full.index 全段）。
    full→reduced：連續 n_exit 日 below；reduced→full：連續 n_reentry 日 (not below)。初始 full。
    MA200 暖身不足（below=False, NaN→False 已處理）期間恆 full（與基線一致）。"""
    rb = raw_below.to_numpy(bool)
    n = len(rb)
    out = np.empty(n)
    state = FULL
    run_below = 0       # 連續 below 天數
    run_above = 0       # 連續 not-below 天數
    for i in range(n):
        if rb[i]:
            run_below += 1
            run_above = 0
        else:
            run_above += 1
            run_below = 0
        if state == FULL:
            if run_below >= n_exit:
                state = REDUCED
        else:  # REDUCED
            if run_above >= n_reentry:
                state = FULL
        out[i] = state
    return pd.Series(out, index=close_full.index)


def flips_in_year(exp_series, year):
    """某年內『態轉折』次數：曝險二值化(是否==REDUCED)，年內 diff!=0 次數。"""
    s = exp_series[exp_series.index.year == year]
    if len(s) < 2:
        return 0
    b = (s.values == REDUCED).astype(int)
    return int((np.diff(b) != 0).sum())


def per_year_metrics(eq, year):
    """回傳該年 (報酬, 年內maxDD)；無資料回 (nan, nan)。"""
    py = bm._per_year(eq)
    t = py.get(year)
    if t is None:
        return float("nan"), float("nan")
    return t[0], t[2]   # (return, in-year maxDD)


# ════════════════════════════════════════════════════════════════════════════════════════════
print("=" * 100)
print("E1 — N 日連續確認 overlay 細網格 | 載入快取 0050（0 API / cache-only）…")
print("=" * 100)

adj = bm.load_adjusted_0050()
cf = adj.set_index("date")["close"].sort_index().astype(float)
ma200 = cf.rolling(MA).mean()
raw_below = (cf < ma200).fillna(False)

print(f"[sanity] 0050 還原日線（快取，無 API）：{len(cf)} 列，{cf.index.min().date()} ~ {cf.index.max().date()}")
print(f"[sanity] 回測窗 {bm.START} ~ {bm.END}｜初始 {bm.INITIAL:,.0f}｜slip {bm.SLIP}｜band {bm.BAND}｜MA{MA} overlay")
print(f"[sanity] 2018-25 跌破 MA200 佔比（每日 raw）：{float(raw_below[cf.index.year >= 2018].mean())*100:.0f}%")
print("[sanity] 0 API / cache-only：僅 bm.load_adjusted_0050() 讀本地 pickle，無任何 fetcher.get_* 網路呼叫。")

# ── 固定預先指定對照（compute once）────────────────────────────────────────────────────────────
bh = bm.simulate_buyhold(adj)                                   # 0050 買持
bench_b = bm.simulate_benchmark(adj, 0.011, overlay=False)      # 基準B（vol0.011、無 overlay）
live_stats = bm.simulate_benchmark(adj, 1.0, overlay=True, regime_ma=MA, regime_action=0.85)  # current-live
bh_eq, bb_eq, live_eq = bh["equity"], bench_b["equity"], live_stats["equity"]


def comp_row(name, eq):
    f, o = agg(eq), agg(eq, oos=True)
    wfd = min(per_year_metrics(eq, Y)[1] for Y in FWD)
    return name, f, o, wfd


print("\n" + "-" * 100)
print("固定對照（全期2018-25 / OOS2022-25）：年化%/Sharpe/maxDD%/Calmar ｜ 最差前進年DD%")
print("-" * 100)
print(f"{'對照':<22}{'全期ann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜{'OOSann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜{'最差年DD':>9}")
for name, eq in [("current-live(MA200-85)", live_eq), ("基準B(vol0.011)", bb_eq), ("0050 買持", bh_eq)]:
    _, f, o, wfd = comp_row(name, eq)
    print(f"{name:<22}{f[0]*100:>8.1f}{f[1]:>6.2f}{f[2]*100:>8.1f}{f[3]:>6.2f}｜"
          f"{o[0]*100:>8.1f}{o[1]:>6.2f}{o[2]*100:>8.1f}{o[3]:>6.2f}｜{wfd*100:>9.1f}")

# 各對照分年（牛市代價對照用）
PY_BH = bm._per_year(bh_eq)
PY_LIVE = bm._per_year(live_eq)

# ── 退化點 sanity：N_exit=N_reentry=1 必須逐位重現 current-live 基線 ──────────────────────────
exp_deg = exp_nday(cf, ma200, raw_below, 1, 1)
deg_eq, deg_nexec = sim_from_exp(adj, exp_deg)
fd, od = agg(deg_eq), agg(deg_eq, oos=True)
fl, ol = agg(live_eq), agg(live_eq, oos=True)
# 直接比對等價基線 exp_bh(cf,0.85)（pd.Series(1.0).where(~raw_below, 0.85)）
exp_bh85 = pd.Series(FULL, index=cf.index).where(~raw_below, REDUCED)
bh85_eq, _ = sim_from_exp(adj, exp_bh85)

d_ann, d_sh, d_dd = abs(fd[0] - fl[0]), abs(fd[1] - fl[1]), abs(fd[2] - fl[2])
eq_max_abs = float((deg_eq - live_eq).abs().max())
eq_vs_bh85 = float((deg_eq - bh85_eq).abs().max())
# 退化態曝險應逐位等於 raw_below 映射（N=1 → 立即轉態 = 每日規則）
exp_match = bool((exp_deg.values == exp_bh85.values).all())

print("\n" + "-" * 100)
print("退化點 sanity：E1(N_exit=N_reentry=1) vs current-live 基線 [simulate_benchmark(1.0,overlay,MA200,0.85)]")
print("-" * 100)
print(f"  全期年化 diff={d_ann:.2e} | Sharpe diff={d_sh:.2e} | maxDD diff={d_dd:.2e}")
print(f"  equity 曲線 max|Δ| vs current-live = {eq_max_abs:.3e}（元）")
print(f"  equity 曲線 max|Δ| vs exp_bh(cf,0.85) = {eq_vs_bh85:.3e}（元）")
print(f"  退化態曝險 Series 逐位 == exp_bh(cf,0.85)：{exp_match}")
assert exp_match, "退化態曝險 Series 未逐位重現 exp_bh(cf,0.85)"
assert d_ann < 1e-6 and d_sh < 1e-6 and d_dd < 1e-6, \
    f"退化點未重現 current-live 基線：ann={d_ann}, sh={d_sh}, dd={d_dd}"
assert eq_max_abs < 1e-3, f"退化點 equity 曲線與 current-live 偏離過大：{eq_max_abs}"
print("  [PASS] 退化點逐位重現 current-live 基線（全期指標 diff<1e-6、equity max|Δ|<1e-3 元）。")

# δ（OOS 年化 Sharpe 的 1 SE，Lo 2002）— 用 current-live OOS pooled 算（plateau 判準的雜訊尺度）
pooled_live = pd.concat([live_eq[live_eq.index.year == Y].pct_change().dropna() for Y in FWD])
SR_d = float(pooled_live.mean() / pooled_live.std())
n_pool = len(pooled_live)
DELTA = float(np.sqrt((1 + 0.5 * SR_d ** 2) / n_pool) * SQRT252)
print(f"\n[plateau scale] δ（OOS 年化 Sharpe 1 SE, Lo-2002, 基於 current-live OOS pooled n={n_pool}）= {DELTA:.3f}")


# ── 細網格掃描 ─────────────────────────────────────────────────────────────────────────────────
def run_point(mode, n_exit, n_reentry):
    exp = exp_nday(cf, ma200, raw_below, n_exit, n_reentry)
    eq, n_exec = sim_from_exp(adj, exp)
    f, o = agg(eq), agg(eq, oos=True)
    wfd = min(per_year_metrics(eq, Y)[1] for Y in FWD)
    fl22, fl18 = flips_in_year(exp, 2022), flips_in_year(exp, 2018)
    r20, dd20 = per_year_metrics(eq, 2020)
    r23 = per_year_metrics(eq, 2023)[0]
    r24 = per_year_metrics(eq, 2024)[0]
    r25 = per_year_metrics(eq, 2025)[0]
    return {
        "mode": mode, "N_exit": n_exit, "N_reentry": n_reentry,
        "full_ann": f[0], "full_sharpe": f[1], "full_dd": f[2], "full_calmar": f[3],
        "oos_ann": o[0], "oos_sharpe": o[1], "oos_dd": o[2], "oos_calmar": o[3],
        "worst_fwd_dd": wfd, "flips_2022": fl22, "flips_2018": fl18, "n_trades": n_exec,
        "ret_2020": r20, "dd_2020": dd20, "ret_2023": r23, "ret_2024": r24, "ret_2025": r25,
    }


# 對稱掃描 N ∈ {1,2,3,4,5,7,10}（7 點；N=1＝退化基線）
SYM_NS = [1, 2, 3, 4, 5, 7, 10]
# 非對稱掃描（涵蓋『出快/補慢』與『出慢/補快』兩翼；≥6 點）
ASYM = [(2, 1), (3, 1), (5, 1), (2, 3), (3, 5), (3, 3), (5, 3), (1, 3)]

rows = []
for n in SYM_NS:
    rows.append(run_point("sym", n, n))
for ne, nr in ASYM:
    rows.append(run_point("asym", ne, nr))

df_out = pd.DataFrame(rows, columns=[
    "mode", "N_exit", "N_reentry", "full_ann", "full_sharpe", "full_dd", "full_calmar",
    "oos_ann", "oos_sharpe", "oos_dd", "oos_calmar", "worst_fwd_dd",
    "flips_2022", "flips_2018", "n_trades", "ret_2020", "dd_2020", "ret_2023", "ret_2024", "ret_2025"])

OUT_CSV = os.path.join(ROOT, "data", "processed", "e1_nday_results.csv")
df_out.to_csv(OUT_CSV, index=False)

# ── 列印對稱網格 ──
print("\n" + "=" * 124)
print("E1 對稱網格（N_exit=N_reentry=N）｜base 100%、連續 N 日跌破 MA200→留 85%、連續 N 日站回→回滿")
print("=" * 124)
print(f"{'N':>3}｜{'全期ann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜{'OOSann':>8}{'Sh':>6}{'OOSmDD':>8}{'Cal':>6}｜"
      f"{'最差年DD':>8}{'fl22':>5}{'fl18':>5}{'交易':>5}｜{'2020報酬':>9}{'2020DD':>8}")
print("-" * 124)
for r in rows:
    if r["mode"] != "sym":
        continue
    star = "  ←退化=基線" if r["N_exit"] == 1 else ""
    print(f"{r['N_exit']:>3}｜{r['full_ann']*100:>8.1f}{r['full_sharpe']:>6.2f}{r['full_dd']*100:>8.1f}{r['full_calmar']:>6.2f}｜"
          f"{r['oos_ann']*100:>8.1f}{r['oos_sharpe']:>6.2f}{r['oos_dd']*100:>8.1f}{r['oos_calmar']:>6.2f}｜"
          f"{r['worst_fwd_dd']*100:>8.1f}{r['flips_2022']:>5}{r['flips_2018']:>5}{r['n_trades']:>5}｜"
          f"{r['ret_2020']*100:>9.1f}{r['dd_2020']*100:>8.1f}{star}")
print("-" * 124)

# ── 列印非對稱網格 ──
print("\n" + "=" * 124)
print("E1 非對稱網格（N_exit, N_reentry）｜出場/回補速度不對稱")
print("=" * 124)
print(f"{'Nex':>4}{'Nre':>4}｜{'全期ann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜{'OOSann':>8}{'Sh':>6}{'OOSmDD':>8}{'Cal':>6}｜"
      f"{'最差年DD':>8}{'fl22':>5}{'fl18':>5}{'交易':>5}｜{'2020報酬':>9}{'2020DD':>8}")
print("-" * 124)
for r in rows:
    if r["mode"] != "asym":
        continue
    print(f"{r['N_exit']:>4}{r['N_reentry']:>4}｜{r['full_ann']*100:>8.1f}{r['full_sharpe']:>6.2f}{r['full_dd']*100:>8.1f}{r['full_calmar']:>6.2f}｜"
          f"{r['oos_ann']*100:>8.1f}{r['oos_sharpe']:>6.2f}{r['oos_dd']*100:>8.1f}{r['oos_calmar']:>6.2f}｜"
          f"{r['worst_fwd_dd']*100:>8.1f}{r['flips_2022']:>5}{r['flips_2018']:>5}{r['n_trades']:>5}｜"
          f"{r['ret_2020']*100:>9.1f}{r['dd_2020']*100:>8.1f}")
print("-" * 124)

# ── 牛市代價：2023/24/25 各年報酬 vs 0050 買持（對稱網格） ──
print("\n" + "=" * 100)
print("牛市代價：對稱網格各年報酬 vs 0050 買持（overlay 在牛市少賺多少）")
print("=" * 100)
print(f"{'N':>3}｜{'2023':>8}{'vs0050':>9}｜{'2024':>8}{'vs0050':>9}｜{'2025':>8}{'vs0050':>9}")
bh23, bh24, bh25 = PY_BH.get(2023, (float('nan'),))[0], PY_BH.get(2024, (float('nan'),))[0], PY_BH.get(2025, (float('nan'),))[0]
print("-" * 100)
for r in rows:
    if r["mode"] != "sym":
        continue
    print(f"{r['N_exit']:>3}｜{r['ret_2023']*100:>8.1f}{(r['ret_2023']-bh23)*100:>9.1f}｜"
          f"{r['ret_2024']*100:>8.1f}{(r['ret_2024']-bh24)*100:>9.1f}｜"
          f"{r['ret_2025']*100:>8.1f}{(r['ret_2025']-bh25)*100:>9.1f}")
print("-" * 100)
print(f"  0050 買持各年：2023 {bh23*100:.1f}% / 2024 {bh24*100:.1f}% / 2025 {bh25*100:.1f}%")

# ── plateau 摘要（OOS Sharpe vs δ；不挑峰、整條報）──
oos_sh = np.array([r["oos_sharpe"] for r in rows])
peak = float(oos_sh.max())
in_band = int((oos_sh >= peak - DELTA).sum())
print("\n" + "=" * 100)
print("plateau 判讀（描述性，不挑峰）")
print("=" * 100)
print(f"  OOS Sharpe 全格範圍 [{oos_sh.min():.3f}, {oos_sh.max():.3f}]，中位 {np.median(oos_sh):.3f}；δ={DELTA:.3f}")
print(f"  落在『峰−δ』帶內格數 = {in_band}/{len(oos_sh)}（多格在帶內＝平滑高原；僅 1~2 格突出＝鋸齒孤峰＝雜訊）")
print(f"  current-live(N=1) OOS Sharpe = {ol[1]:.3f}；OOS maxDD = {ol[2]*100:.1f}%；最差前進年 DD = {comp_row('live', live_eq)[3]*100:.1f}%")

print(f"\n[done] E1 細網格完成（純快取）。CSV → {OUT_CSV}")

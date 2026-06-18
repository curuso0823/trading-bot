"""
notebooks/e2_hysteresis_band.py
E2 — 對稱緩衝帶（Hysteresis Band / SMA Envelope）細網格沙盒。

機制：狀態機 + 死區（symmetric α=β）。初始態＝full(1.0)。
  - full   → reduced(0.85)：close < MA200×(1−α)。
  - reduced→ full(1.0)    ：close > MA200×(1+β)。
  - 介於 MA200×(1−α) 與 MA200×(1+β)＝死區 → 維持現態。
本實驗對稱 α=β ∈ {0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5}%（12 點）。
退化點 α=β=0 ＝每日 MA200（無死區）→ 必須逐位重現 current-live 基線 exp_bh(cf,0.85)（assert）。

定位（CLAUDE.md / R5）：**結構性降回撤規則、非 outperformer**；不宣稱 alpha。FinMind 無下市股 →
survivorship 上界。純快取、0 API、不改任何既有檔（引擎 byte-identical；曝險邏輯本檔本地複製/擴充）。
用法：.venv/bin/python notebooks/e2_hysteresis_band.py
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
REDUCED = 0.85   # 跌破態曝險（current live＝出 15%）
FULL = 1.0


# ── baseline exposure（current live，逐位重現用）─────────────────────────────────
def exp_bh(close_full, mult_below):
    """base 100%（無 vol-cap）；close < MA200 當日 → mult_below。＝current-live 基線口徑。"""
    below = (close_full < close_full.rolling(MA).mean()).fillna(False)
    return pd.Series(1.0, index=close_full.index).where(~below, float(mult_below))


# ── sim_from_exp（逐字複製 r6_retreat_finegrid.py L40-87，唯一擴充＝回傳執行交易數）──────
def sim_from_exp(adj, exp_full):
    """同一交易/成本迴圈（byte-identical 邏輯）；擴充回傳 (eq_series, n_exec_trades)。
    n_exec_trades＝每次實際成交（buy delta>0 fill 或 sell delta<0）的次數（買+賣各算一筆）。"""
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
    n_exec = 0   # 實際成交筆數（買或賣，delta!=0 且真的有 fill）
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
            trades.append((amt - bm._sellcost(amt)) - avg_cost * sell_qty)
            qty -= sell_qty
            if qty == 0:
                avg_cost = 0.0
            n_exec += 1
    return pd.Series(eq, index=dates), n_exec


# ── agg（逐字複製 r6_retreat_finegrid.py L90-96）────────────────────────────────
def agg(eq, oos=False):
    e = eq[eq.index.year.isin(FWD)] if oos else eq
    r = e.pct_change().dropna()
    sh = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    ann = float((e.iloc[-1] / e.iloc[0]) ** (252 / len(e)) - 1)
    dd = float((e / e.cummax() - 1).min())
    return ann, sh, dd, (ann / abs(dd) if abs(dd) > 1e-9 else float("nan"))


# ── E2 hysteresis 目標曝險 Series（狀態機 + 對稱死區）──────────────────────────────
def exp_hysteresis(close_full, alpha, beta):
    """逐日走全段（含暖身），維護 state∈{full,reduced}，輸出每日目標曝險 Series。
    full→reduced：close < MA×(1−α)；reduced→full：close > MA×(1+β)；否則維持現態。
    MA200 暖身不足（NaN）→ 視為『未跌破』、維持 full（與 baseline fillna(False) 一致）。"""
    cf = close_full.astype(float)
    ma = cf.rolling(MA).mean()
    cvals = cf.to_numpy(float)
    mvals = ma.to_numpy(float)
    n = len(cf)
    out = np.empty(n, dtype=float)
    state = FULL   # 初始態＝full
    for i in range(n):
        m = mvals[i]
        if np.isfinite(m):
            lo = m * (1.0 - alpha)   # 觸發 reduced 的下界
            hi = m * (1.0 + beta)    # 觸發 full 的上界
            c = cvals[i]
            if state == FULL:
                if c < lo:
                    state = REDUCED
            else:  # state == REDUCED
                if c > hi:
                    state = FULL
        # NaN(暖身)：維持現態（初始 full）；等同 baseline 視為未跌破
        out[i] = state
    return pd.Series(out, index=cf.index)


# ── flips（態轉折次數，按年）＋暴露態 helper ─────────────────────────────────────
def flips_per_year(exp_series, year):
    """某年內 reduced↔full 態轉折次數（曝險二值化＝是否=reduced，年內 diff!=0 計數）。"""
    s = exp_series[exp_series.index.year == year]
    if len(s) < 2:
        return 0
    is_reduced = (np.isclose(s.to_numpy(float), REDUCED)).astype(int)
    return int((np.diff(is_reduced) != 0).sum())


def per_year_ret_dd(eq):
    py = bm._per_year(eq)
    return py


# ════════════════════════════════════════════════════════════════════════════════
print("=" * 92)
print("E2 — 對稱緩衝帶（Hysteresis Band）細網格 | 載入快取 0050…")
print("=" * 92)
adj = bm.load_adjusted_0050()
cf = adj.set_index("date")["close"].sort_index().astype(float)
print(f"[sanity] 0050 還原日線：{len(adj)} 列，{adj['date'].min().date()} ~ {adj['date'].max().date()}")
print(f"[sanity] 回測窗 {bm.START} ~ {bm.END}｜INITIAL {bm.INITIAL:,.0f}｜SLIP {bm.SLIP}｜BAND {bm.BAND}｜LOT {bm.LOT}")
print("[sanity] 0 API / cache-only：僅 bm.load_adjusted_0050() 讀本地 pickle，無任何網路/FinMind 呼叫。")

raw_below = (cf < cf.rolling(MA).mean()).fillna(False)
f_below = float(raw_below[cf.index.year >= 2018].mean())
print(f"[sanity] 2018-25 raw close<MA200 佔比 {f_below*100:.1f}%")

# ── 退化點 sanity：α=β=0 必須逐位重現 current-live 基線 exp_bh(cf,0.85) ──────────────
base_exp = exp_bh(cf, REDUCED)
hyst0 = exp_hysteresis(cf, 0.0, 0.0)
# 比對：α=β=0 時死區塌縮，state 機制應等同每日 MA200（close<MA→reduced, close>=MA→full）
diff_mask = ~np.isclose(base_exp.to_numpy(float), hyst0.to_numpy(float))
n_diff = int(diff_mask.sum())
if n_diff:
    # 列出差異日（用於診斷 close==MA200 邊界 tie）
    didx = base_exp.index[diff_mask]
    print(f"[assert-debug] α=β=0 vs baseline 差異 {n_diff} 日，前 5 個：")
    for d in didx[:5]:
        m = cf.rolling(MA).mean().loc[d]
        print(f"    {d.date()}  close={cf.loc[d]:.4f}  MA200={m:.4f}  base={base_exp.loc[d]:.2f}  hyst={hyst0.loc[d]:.2f}")
assert n_diff == 0, (
    f"退化點重現失敗：α=β=0 應逐位等於 current-live 基線，但有 {n_diff} 日不符。")
print(f"[ASSERT PASS] 退化點 α=β=0 逐位重現 current-live 基線（exp_bh(cf,0.85)）：{len(base_exp)} 日全等。")

# 額外 sanity：基線曝險 Series 在回測窗(2018+)的 reduced 佔比應＝f_below（旋鈕＝每日 MA200）
base_red_frac = float(np.isclose(base_exp[base_exp.index.year >= 2018].to_numpy(float), REDUCED).mean())
print(f"[sanity] 基線(α=0) 2018-25 reduced 態佔比 {base_red_frac*100:.1f}%（應≈raw below {f_below*100:.1f}%）")

# ── 固定預先指定對照（compute once）────────────────────────────────────────────────
bh = bm.simulate_buyhold(adj)              # 0050 買持
benchB = bm.simulate_benchmark(adj, 0.011, overlay=False)   # 基準B vol0.011 無 overlay
live_eq, live_nx = sim_from_exp(adj, base_exp)             # current-live = α=0 基線
# 等價驗證：與引擎 overlay 路徑(simulate_benchmark vol1.0 overlay regime_action0.85) 對照（描述性 sanity）
live_eng = bm.simulate_benchmark(adj, 1.0, overlay=True, regime_ma=200, regime_action=0.85)

COMP = {}
for nm, eq in [("live_ma200_85", live_eq), ("benchmark_b_vol011", benchB["equity"]),
               ("buyhold_0050", bh["equity"])]:
    f, o = agg(eq), agg(eq, oos=True)
    py = bm._per_year(eq)
    worst = min(py[Y][2] for Y in FWD if Y in py)
    COMP[nm] = dict(full_ann=f[0], full_sharpe=f[1], full_dd=f[2], full_calmar=f[3],
                    oos_ann=o[0], oos_sharpe=o[1], oos_dd=o[2], worst_fwd_dd=worst)

print("\n" + "=" * 92)
print("固定預先指定對照（全期2018-25 ｜ OOS2022-25）：年化%/Sharpe/maxDD%/Calmar ｜ 最差前進年DD%")
print("=" * 92)
print(f"{'對照':<22}{'全期ann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜{'OOSann':>8}{'Sh':>6}{'maxDD':>8}{'worstFwdDD':>11}")
for nm, c in COMP.items():
    print(f"{nm:<22}{c['full_ann']*100:>8.1f}{c['full_sharpe']:>6.2f}{c['full_dd']*100:>8.1f}"
          f"{c['full_calmar']:>6.2f}｜{c['oos_ann']*100:>8.1f}{c['oos_sharpe']:>6.2f}{c['oos_dd']*100:>8.1f}"
          f"{c['worst_fwd_dd']*100:>11.1f}")
# 引擎等價 sanity（live_eq 應≈ engine overlay 路徑）
le_f = agg(live_eng["equity"])
print(f"[sanity] 引擎 overlay 路徑(vol1.0,overlay,ma200,act0.85) 全期 ann/Sh/DD = "
      f"{le_f[0]*100:.1f}%/{le_f[1]:.2f}/{le_f[2]*100:.1f}%  vs live_eq "
      f"{COMP['live_ma200_85']['full_ann']*100:.1f}%/{COMP['live_ma200_85']['full_sharpe']:.2f}/"
      f"{COMP['live_ma200_85']['full_dd']*100:.1f}%（應同量級）")
print(f"[sanity] current-live 執行再平衡交易數（全期）= {live_nx}")

# ── E2 細網格掃描 ──────────────────────────────────────────────────────────────────
BANDS = [0.0, 0.0025, 0.005, 0.0075, 0.010, 0.0125, 0.015, 0.0175, 0.020, 0.025, 0.030, 0.035]
rows = []
for b in BANDS:
    exp_s = exp_hysteresis(cf, b, b)   # 對稱 α=β=b
    eq, nx = sim_from_exp(adj, exp_s)
    f, o = agg(eq), agg(eq, oos=True)
    py = bm._per_year(eq)
    worst = min(py[Y][2] for Y in FWD if Y in py)
    # pooled OOS（口徑：FWD 年份日報酬串接）
    pooled = pd.concat([eq[eq.index.year == Y].pct_change().dropna() for Y in FWD])
    oos_sh = float(pooled.mean() / pooled.std() * SQRT252) if pooled.std() > 0 else 0.0
    oos_ann = float((1 + pooled).prod() ** (252 / len(pooled)) - 1)
    # OOS maxDD：FWD 年份切片串接的 eq
    oos_eq = eq[eq.index.year.isin(FWD)]
    oos_dd = float((oos_eq / oos_eq.cummax() - 1).min())
    oos_cal = (oos_ann / abs(oos_dd)) if abs(oos_dd) > 1e-9 else float("nan")
    rows.append(dict(
        band_pct=b, full_ann=f[0], full_sharpe=f[1], full_dd=f[2], full_calmar=f[3],
        oos_ann=oos_ann, oos_sharpe=oos_sh, oos_dd=oos_dd, oos_calmar=oos_cal,
        worst_fwd_dd=worst,
        flips_2022=flips_per_year(exp_s, 2022), flips_2018=flips_per_year(exp_s, 2018),
        flips_2020=flips_per_year(exp_s, 2020), n_trades=nx,
        ret_2020=py.get(2020, (float("nan"),) * 3)[0], dd_2020=py.get(2020, (float("nan"),) * 3)[2],
        ret_2023=py.get(2023, (float("nan"),) * 3)[0], ret_2024=py.get(2024, (float("nan"),) * 3)[0],
        ret_2025=py.get(2025, (float("nan"),) * 3)[0],
        reduced_frac=float(np.isclose(exp_s[exp_s.index.year >= 2018].to_numpy(float), REDUCED).mean()),
    ))

df_out = pd.DataFrame(rows)

# ── δ（OOS 年化 Sharpe 的 1 SE，Lo 2002）：用基線(α=0) pooled 計 ──────────────────────
base_pooled = pd.concat([live_eq[live_eq.index.year == Y].pct_change().dropna() for Y in FWD])
SR_d = base_pooled.mean() / base_pooled.std()
n_pool = len(base_pooled)
delta = float(np.sqrt((1 + 0.5 * SR_d ** 2) / n_pool) * SQRT252)

# ── 列印細網格 ─────────────────────────────────────────────────────────────────────
print("\n" + "=" * 132)
print("E2 對稱緩衝帶細網格（α=β）｜base 100%、跌破帶下界→0.85、漲回帶上界→1.0｜死區維持現態")
print(f"  δ(OOS年化Sharpe 1SE, Lo2002, 基線pooled n={n_pool})= {delta:.3f}")
print("=" * 132)
hdr = (f"{'帶%':>5}{'redFr':>6}｜{'全期ann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜"
       f"{'OOSann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜{'worstFwd':>9}｜"
       f"{'fl22':>5}{'fl20':>5}{'fl18':>5}{'交易':>5}｜{'r20':>7}{'dd20':>7}｜{'r23':>6}{'r24':>6}{'r25':>6}")
print(hdr)
print("-" * 132)
oos_sh_max = df_out["oos_sharpe"].max()
for _, r in df_out.iterrows():
    tag = " ←退化=基線" if r["band_pct"] == 0.0 else (" ←OOS峰" if r["oos_sharpe"] == oos_sh_max else "")
    print(f"{r['band_pct']*100:>5.2f}{r['reduced_frac']*100:>6.1f}｜{r['full_ann']*100:>8.1f}{r['full_sharpe']:>6.2f}"
          f"{r['full_dd']*100:>8.1f}{r['full_calmar']:>6.2f}｜{r['oos_ann']*100:>8.1f}{r['oos_sharpe']:>6.2f}"
          f"{r['oos_dd']*100:>8.1f}{r['oos_calmar']:>6.2f}｜{r['worst_fwd_dd']*100:>9.1f}｜"
          f"{int(r['flips_2022']):>5}{int(r['flips_2020']):>5}{int(r['flips_2018']):>5}{int(r['n_trades']):>5}｜"
          f"{r['ret_2020']*100:>7.1f}{r['dd_2020']*100:>7.1f}｜{r['ret_2023']*100:>6.1f}{r['ret_2024']*100:>6.1f}"
          f"{r['ret_2025']*100:>6.1f}{tag}")
print("-" * 132)

# ── plateau 判讀（δ 帶內幾格、峰是否孤立）──────────────────────────────────────────
peak = df_out.loc[df_out["oos_sharpe"].idxmax()]
within = df_out[df_out["oos_sharpe"] >= (peak["oos_sharpe"] - delta)]
print(f"[plateau] OOS Sharpe 峰 = {peak['oos_sharpe']:.3f} @ 帶 {peak['band_pct']*100:.2f}%；"
      f"落在 [峰−δ={peak['oos_sharpe']-delta:.3f}] 內的格數 = {len(within)}/{len(df_out)}。")
print(f"[plateau] OOS Sharpe 全距 = [{df_out['oos_sharpe'].min():.3f}, {df_out['oos_sharpe'].max():.3f}]"
      f"（跨度 {df_out['oos_sharpe'].max()-df_out['oos_sharpe'].min():.3f}；δ={delta:.3f}）。")

# ── 0050 牛市各年報酬（對照 overlay 牛市少賺）─────────────────────────────────────
py_h = bm._per_year(bh["equity"])
print(f"[bull] 0050買持 2023/24/25 報酬 = {py_h.get(2023,(np.nan,))[0]*100:.1f}% / "
      f"{py_h.get(2024,(np.nan,))[0]*100:.1f}% / {py_h.get(2025,(np.nan,))[0]*100:.1f}%；"
      f"2020 報酬/DD = {py_h.get(2020,(np.nan,np.nan,np.nan))[0]*100:.1f}% / {py_h.get(2020,(np.nan,np.nan,np.nan))[2]*100:.1f}%")

# ── 寫 CSV ─────────────────────────────────────────────────────────────────────────
CSV = os.path.join(ROOT, "data", "processed", "e2_band_results.csv")
csv_cols = ["band_pct", "full_ann", "full_sharpe", "full_dd", "full_calmar",
            "oos_ann", "oos_sharpe", "oos_dd", "oos_calmar", "worst_fwd_dd",
            "flips_2022", "flips_2018", "flips_2020", "n_trades",
            "ret_2020", "dd_2020", "ret_2023", "ret_2024", "ret_2025", "reduced_frac"]
df_out[csv_cols].to_csv(CSV, index=False)
print(f"\n[done] 寫出 {CSV}（{len(df_out)} 列細網格）。純快取、0 API。")
print("⚠️ 描述性沙盒：FinMind 無下市股 → 全為上界(survivorship)；R5 已定誠實池無顯著 alpha；"
      "此 overlay＝結構性降回撤規則、非 outperformer。決策仍須未來 walk-forward；總 Gate 未過前 live 不動。")

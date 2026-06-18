"""
notebooks/e3_atr_band.py
E3 — ATR 動態帶（沙盒實驗，純快取、0 API、不改任何既有檔）。

機制：MA200 ± K×ATR(22) 的雙閾值死區狀態機。
  - True Range = max(high-low, |high-prev_close|, |low-prev_close|)；
    ATR = TR 的 rolling(22).mean()（**簡單均值 SMA-ATR**，非 Wilder EMA）。全段含 2016 暖身後再對齊。
  - lower = MA200 - K*ATR；upper = MA200 + K*ATR。
  - 狀態機：full(1.0) -> reduced(0.85) 當 close < lower；reduced -> full 當 close > upper；
    死區（lower..upper）維持現態。需 state 變數 + for 迴圈，輸出每日目標曝險 Series。
  - 退化點：K=0 -> 帶寬 0 = 每日 MA200，**必須逐位重現 current-live 基線**（exp_bh(cf,0.85)）。

定位（鐵則#5）：結構性降回撤規則、**非 outperformer**（R5 已定誠實池無顯著 alpha；survivorship 上界）。
細網格只做特徵化/找線索；結論只綁 OOS + plateau；**永不**用 sample 峰值挑 K。

用法：.venv/bin/python notebooks/e3_atr_band.py
"""
import os
import sys
import importlib.util

# ── importlib 區塊（逐字複製自 r6_retreat_finegrid.py 第 11-28 行）────────────────
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
ATR_N = 22
REDUCED = 0.85          # 出 15%
FULL = 1.0


# ── exp_bh（基線；逐字自 r6_retreat_finegrid.py 第 35-37 行）─────────────────────
def exp_bh(close_full, mult_below):
    below = (close_full < close_full.rolling(MA).mean()).fillna(False)
    return pd.Series(1.0, index=close_full.index).where(~below, float(mult_below))


# ── sim_from_exp（逐字自 r6_retreat_finegrid.py 第 40-87 行；唯一擴充：另計 n_exec_trades）──
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
    n_exec = 0          # 擴充：實際成交（買或賣 delta!=0）次數計數
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
            n_exec += 1                                    # 擴充：一次實際買入
        elif delta < 0:
            sell_qty = -delta
            amt = fill_sell * sell_qty * bm.LOT
            cash += amt - bm._sellcost(amt)
            trades.append((amt - bm._sellcost(amt)) - avg_cost * sell_qty)
            qty -= sell_qty
            if qty == 0:
                avg_cost = 0.0
            n_exec += 1                                    # 擴充：一次實際賣出
    return pd.Series(eq, index=dates), n_exec


# ── agg（逐字自 r6_retreat_finegrid.py 第 90-96 行）──────────────────────────────
def agg(eq, oos=False):
    e = eq[eq.index.year.isin(FWD)] if oos else eq
    r = e.pct_change().dropna()
    sh = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    ann = float((e.iloc[-1] / e.iloc[0]) ** (252 / len(e)) - 1)
    dd = float((e / e.cummax() - 1).min())
    return ann, sh, dd, (ann / abs(dd) if abs(dd) > 1e-9 else float("nan"))


# ── ATR 動態帶：每日目標曝險（state 機 for 迴圈；全段 cf.index 計再切）────────────
def exp_atr_band(adj, K):
    """MA200 ± K*ATR(22) 雙閾值死區狀態機（SMA-ATR）。回傳全段 cf.index 上的目標曝險 Series。"""
    a = adj.sort_values("date").reset_index(drop=True)
    idx = pd.DatetimeIndex(a["date"])
    high = a["high"].to_numpy(float)
    low = a["low"].to_numpy(float)
    close = a["close"].to_numpy(float)
    prev_close = np.concatenate([[np.nan], close[:-1]])
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
    atr = pd.Series(tr, index=idx).rolling(ATR_N).mean()          # SMA-ATR
    ma = pd.Series(close, index=idx).rolling(MA).mean()
    lower = (ma - K * atr).to_numpy(float)
    upper = (ma + K * atr).to_numpy(float)
    cl = close

    exp = np.empty(len(idx))
    state = FULL                                                   # 初始 full（暖身段 NaN 閾值 -> 維持 full）
    for i in range(len(idx)):
        lo, up = lower[i], upper[i]
        if np.isfinite(lo) and np.isfinite(up):
            if state == FULL and cl[i] < lo:
                state = REDUCED
            elif state == REDUCED and cl[i] > up:
                state = FULL
            # 死區（lo..up）或邊界等號：維持現態
        exp[i] = state
    return pd.Series(exp, index=idx)


def flips_per_year(target_exp, year):
    """目標曝險二值化(是否=reduced)後，某年內 diff!=0 的次數（態轉折）。"""
    binr = (target_exp == REDUCED).astype(int)
    y = binr[binr.index.year == year]
    return int((y.diff().fillna(0) != 0).sum())


def per_year_ret_dd(eq, year):
    py = bm._per_year(eq)
    t = py.get(year, (float("nan"), float("nan"), float("nan")))
    return t[0], t[2]          # (年報酬, 年內maxDD)


# ── 主流程 ──────────────────────────────────────────────────────────────────────
print("E3 ATR 動態帶（MA200 ± K*ATR22, SMA-ATR）｜載入快取 0050 …")
adj = bm.load_adjusted_0050()
cf = adj.set_index("date")["close"].sort_index().astype(float)
print(f"[sanity] 載入 {len(adj)} 列，{adj['date'].min().date()} ~ {adj['date'].max().date()}｜0 API / cache-only")
print(f"[sanity] 欄位含 OHLC：{[c for c in ['open','high','low','close'] if c in adj.columns]}")

# ── 退化點 sanity：K=0 必須逐位重現 current-live 基線 exp_bh(cf,0.85) ─────────────
exp_k0 = exp_atr_band(adj, 0.0)
exp_base = exp_bh(cf, REDUCED)
# 對齊到同 index（exp_base 在 cf.index；exp_k0 在 adj 排序 index，皆全段 2016+）
exp_k0_a = exp_k0.reindex(cf.index)
# 逐位比對目標曝險 Series（暖身段：基線 below.fillna(False)->full；K=0 帶寬0、閾值=MA200，NaN段維持 full -> 一致）
ser_match = bool((exp_k0_a.fillna(-1).round(6) == exp_base.fillna(-1).round(6)).all())
# 同時驗權益曲線逐位一致
eq_k0, ntr_k0 = sim_from_exp(adj, exp_k0)
eq_base, ntr_base = sim_from_exp(adj, exp_base)
eq_match = bool(np.allclose(eq_k0.to_numpy(float), eq_base.to_numpy(float), rtol=0, atol=1e-6))
assert ser_match, "K=0 目標曝險 Series 未逐位重現 current-live 基線！"
assert eq_match, "K=0 權益曲線未逐位重現 current-live 基線！"
print(f"[sanity] 退化點 K=0 逐位重現 current-live 基線：曝險Series={ser_match}, 權益曲線={eq_match}, n_trades {ntr_k0}=={ntr_base}")

# ── 固定預先指定對照（compute once）──────────────────────────────────────────────
bh = bm.simulate_buyhold(adj)
benchB = bm.simulate_benchmark(adj, 0.011, overlay=False)
eq_live, ntr_live = sim_from_exp(adj, exp_bh(cf, REDUCED))   # current-live = base100% + 跌破MA200->0.85


def worst_fwd_dd(eq):
    return min(bm._per_year(eq).get(Y, (0, 0, float("nan")))[2] for Y in FWD)


def comparator_row(eq):
    f, o = agg(eq), agg(eq, oos=True)
    return {
        "full_ann": f[0], "full_sharpe": f[1], "full_dd": f[2], "full_calmar": f[3],
        "oos_ann": o[0], "oos_sharpe": o[1], "oos_dd": o[2], "oos_calmar": o[3],
        "worst_fwd_dd": worst_fwd_dd(eq),
    }


cmp_live = comparator_row(eq_live)
cmp_B = comparator_row(benchB["equity"])
cmp_0050 = comparator_row(bh["equity"])

print("\n" + "=" * 100)
print("固定對照（全期2018-25｜OOS2022-25）：年化/Sharpe/maxDD/Calmar｜最差前進年DD")
print("=" * 100)
for nm, c in [("current-live(MA200,0.85)", cmp_live), ("基準B(vol0.011,無overlay)", cmp_B), ("0050買持", cmp_0050)]:
    print(f"{nm:<26} full {c['full_ann']*100:6.1f}% Sh{c['full_sharpe']:5.2f} DD{c['full_dd']*100:6.1f}% "
          f"Cal{c['full_calmar']:5.2f}｜OOS {c['oos_ann']*100:6.1f}% Sh{c['oos_sharpe']:5.2f} "
          f"DD{c['oos_dd']*100:6.1f}% Cal{c['oos_calmar']:5.2f}｜worstFwdDD {c['worst_fwd_dd']*100:6.1f}%")

# ── 細網格（鐵則#7，8 點 + 退化 sanity K=0）─────────────────────────────────────
KS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
rows = []

# 退化 sanity 列（標註；不列入主結論）
f0, o0 = agg(eq_k0), agg(eq_k0, oos=True)
rows.append({
    "K": 0.0, "param_label": "K=0(退化=每日MA200 sanity)",
    "full_ann": f0[0], "full_sharpe": f0[1], "full_dd": f0[2], "full_calmar": f0[3],
    "oos_ann": o0[0], "oos_sharpe": o0[1], "oos_dd": o0[2], "oos_calmar": o0[3],
    "worst_fwd_dd": worst_fwd_dd(eq_k0),
    "flips_2022": flips_per_year(exp_k0, 2022), "flips_2018": flips_per_year(exp_k0, 2018),
    "n_trades": ntr_k0,
    "ret_2020": per_year_ret_dd(eq_k0, 2020)[0], "dd_2020": per_year_ret_dd(eq_k0, 2020)[1],
    "ret_2023": per_year_ret_dd(eq_k0, 2023)[0], "ret_2024": per_year_ret_dd(eq_k0, 2024)[0],
    "ret_2025": per_year_ret_dd(eq_k0, 2025)[0],
})

# δ（OOS 年化 Sharpe 的 1 SE, Lo 2002）——用 current-live OOS pooled（口徑一致參考）
pooled_ref = pd.concat([eq_live[eq_live.index.year == Y].pct_change().dropna() for Y in FWD])
SR_d_ref = pooled_ref.mean() / pooled_ref.std()
delta_ref = float(np.sqrt((1 + 0.5 * SR_d_ref ** 2) / len(pooled_ref)) * SQRT252)

oos_sharpes = []
for K in KS:
    exp_full = exp_atr_band(adj, K)
    eq, ntr = sim_from_exp(adj, exp_full)
    f, o = agg(eq), agg(eq, oos=True)
    r20, d20 = per_year_ret_dd(eq, 2020)
    rows.append({
        "K": K, "param_label": f"K={K}",
        "full_ann": f[0], "full_sharpe": f[1], "full_dd": f[2], "full_calmar": f[3],
        "oos_ann": o[0], "oos_sharpe": o[1], "oos_dd": o[2], "oos_calmar": o[3],
        "worst_fwd_dd": worst_fwd_dd(eq),
        "flips_2022": flips_per_year(exp_full, 2022), "flips_2018": flips_per_year(exp_full, 2018),
        "n_trades": ntr,
        "ret_2020": r20, "dd_2020": d20,
        "ret_2023": per_year_ret_dd(eq, 2023)[0], "ret_2024": per_year_ret_dd(eq, 2024)[0],
        "ret_2025": per_year_ret_dd(eq, 2025)[0],
    })
    oos_sharpes.append(o[1])

# δ per-K（每個 K 自己的 pooled）也算一遍，取中位作報告穩健參考
deltas_perK = []
for K in KS:
    exp_full = exp_atr_band(adj, K)
    eq, _ = sim_from_exp(adj, exp_full)
    pooled = pd.concat([eq[eq.index.year == Y].pct_change().dropna() for Y in FWD])
    SR_d = pooled.mean() / pooled.std()
    deltas_perK.append(float(np.sqrt((1 + 0.5 * SR_d ** 2) / len(pooled)) * SQRT252))
delta_med = float(np.median(deltas_perK))

df_out = pd.DataFrame(rows)[[
    "K", "full_ann", "full_sharpe", "full_dd", "full_calmar",
    "oos_ann", "oos_sharpe", "oos_dd", "oos_calmar", "worst_fwd_dd",
    "flips_2022", "flips_2018", "n_trades", "ret_2020", "dd_2020",
    "ret_2023", "ret_2024", "ret_2025",
]]
CSV = os.path.join(ROOT, "data", "processed", "e3_atr_results.csv")
df_out.to_csv(CSV, index=False)

# ── 列印細網格 ──
print("\n" + "=" * 132)
print("E3 ATR 動態帶細網格｜MA200 ± K*ATR22（SMA-ATR）｜reduced=0.85, full=1.0｜full=全期2018-25, OOS=2022-25")
print("=" * 132)
print(f"{'K':>5}｜{'full_ann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜{'OOSann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}"
      f"｜{'worstFwd':>9}｜{'fl22':>5}{'fl18':>5}{'nTr':>5}｜{'r2020':>7}{'dd2020':>8}｜{'r23':>6}{'r24':>6}{'r25':>6}")
print("-" * 132)
for r in rows:
    tag = "  ←sanity(=基線)" if r["K"] == 0.0 else ""
    print(f"{r['K']:>5.2f}｜{r['full_ann']*100:>8.1f}{r['full_sharpe']:>6.2f}{r['full_dd']*100:>8.1f}{r['full_calmar']:>6.2f}"
          f"｜{r['oos_ann']*100:>8.1f}{r['oos_sharpe']:>6.2f}{r['oos_dd']*100:>8.1f}{r['oos_calmar']:>6.2f}"
          f"｜{r['worst_fwd_dd']*100:>9.1f}｜{r['flips_2022']:>5}{r['flips_2018']:>5}{r['n_trades']:>5}"
          f"｜{r['ret_2020']*100:>7.1f}{r['dd_2020']*100:>8.1f}｜{r['ret_2023']*100:>6.1f}{r['ret_2024']*100:>6.1f}{r['ret_2025']*100:>6.1f}{tag}")
print("-" * 132)

# ── plateau 評估（δ 帶內）──
peak = max(oos_sharpes)
peak_K = KS[int(np.argmax(oos_sharpes))]
in_band = [KS[i] for i, s in enumerate(oos_sharpes) if s >= peak - delta_med]
print(f"\n[plateau] OOS Sharpe over K(8點): {[round(s,3) for s in oos_sharpes]}")
print(f"[plateau] 峰 OOS Sharpe={peak:.3f}@K={peak_K}；δ(中位,perK Lo2002)={delta_med:.3f}（current-live參考 δ={delta_ref:.3f}）")
print(f"[plateau] 落在 峰−δ 內的 K：{in_band}（{len(in_band)}/8）→ {'平滑高原' if len(in_band)>=4 else '鋸齒/孤峰傾向'}")

# ── whipsaw / 牛市 / 2020 初跌保護退化 摘要 ──
fl22 = [r["flips_2022"] for r in rows if r["K"] in KS]
fl18 = [r["flips_2018"] for r in rows if r["K"] in KS]
ntrs = [r["n_trades"] for r in rows if r["K"] in KS]
base22, base18, basen = rows[0]["flips_2022"], rows[0]["flips_2018"], rows[0]["n_trades"]
print(f"\n[whipsaw] 基線(K=0): 2022 flips={base22}, 2018 flips={base18}, 全期交易={basen}")
print(f"[whipsaw] K∈{KS}: 2022 flips={fl22}, 2018 flips={fl18}, 全期交易={ntrs}")
bh_py = bm._per_year(bh["equity"])
print(f"[牛市] 0050買持 2023/24/25 = {bh_py[2023][0]*100:.1f}% / {bh_py[2024][0]*100:.1f}% / {bh_py[2025][0]*100:.1f}%")
print(f"[牛市] current-live  2023/24/25 = {per_year_ret_dd(eq_live,2023)[0]*100:.1f}% / "
      f"{per_year_ret_dd(eq_live,2024)[0]*100:.1f}% / {per_year_ret_dd(eq_live,2025)[0]*100:.1f}%")
d20_list = [r["dd_2020"] for r in rows if r["K"] in KS]
base_d20 = rows[0]["dd_2020"]
print(f"[2020初跌] 基線(K=0) 2020年內maxDD={base_d20*100:.1f}%；K∈{KS}: {[round(x*100,1) for x in d20_list]} "
      f"→ K增大保護退化={'是' if d20_list[-1] < base_d20 else '否/持平'}（更負=更差）")

print(f"\n[done] CSV -> {CSV}")
print("⚠️ 描述性、survivorship 上界、非 alpha（R5 已定誠實池無顯著 alpha）；結論只綁 OOS+plateau，勿挑峰。")

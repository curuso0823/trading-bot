"""
notebooks/e4_second_line.py
E4 — 第二道防線：早期出場 overlay（沙盒研究；純快取、0 API、不改任何既有檔）。

【E4 機制】在 current-live MA200 overlay（連 3 日跌破 ×0.99 才砍 85%、連 3 日站回 ×1.01 才回滿、
  action 0.85）之上，**疊加第二道防線**——當「快訊號」先於 MA200 觸發即砍至 85%（補初跌盲區）。
  不改 MA200 本體；早期觸發 early_below = (5d vol-spike) OR (from-peak 速度停損)。最終態 by 狀態機：
    進入 reduced：base_below OR early_below 任一立即觸發（早期訊號立即拉進 reduced，不等 N 日）；
    回滿 full：須 base 已回滿 且 early 清除 連續 R_hold 日。
  exposure = base vol-target(live target_daily_vol=1.0 ⇒ 100%) × (0.85 if final_below else 1.0)。

【⚠️ 最重要·方法論誠實點（貫穿全檔，頭尾醒目標示）】
  walk-forward FWD=[2022,2023,2024,2025]＝expanding window，2018-2021 永遠在 in-sample 訓練段。
  → 2018 Q4 崩盤 [IS]、2020 COVID V 崩 [IS]、2022 慢熊 [唯一 OOS 崩盤]、2023-25 牛 [OOS]。
  E4 主打要補的「2020 初跌盲區」落在 in-sample，**此窗結構上無法 OOS 驗證**！
  2018/2020 的「改善」只能是 descriptive/ex-post in-sample 觀察、**不得當 OOS 證據**。
  walk-forward OOS 實際只能檢定「加 E4 是否惡化 2022 + 牛市(2023-25) 的 OOS 表現」。

【定位】R0-R5 已證誠實/被動池無穩健前瞻 alpha；此 overlay＝結構性降回撤/降 whipsaw 規則、非 outperformer。
  FinMind 無下市股 → 所有結果是上界（survivorship）。**總 Gate 未過前 live（MA200+0.85+confirm3/band1%）不動。**
用法：.venv/bin/python notebooks/e4_second_line.py
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

# importlib 載 benchmark_backtest.py 為 bm（它有 __main__ guard、安全；不執行 main()）
_spec = importlib.util.spec_from_file_location("bm", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

SQRT252 = np.sqrt(252)
FWD = [2022, 2023, 2024, 2025]      # OOS 前進窗（同 R0/R1/E1-E3）
MA = 200
REDUCED, FULL = 0.85, 1.0           # 主版輕量檔位（出 15%）
DEEP = 0.70                         # 深砍變體檔位（雙確認；仍 ≤30% 出倉）
DD_BAND = 0.022                     # path-dependence 容差（同 R1/E1-E2；相對同族基線 floor 用）
# current-live overlay 參數（寫死、絕不掃）= E4 所 augment 的生產 overlay
LIVE_CONFIRM, LIVE_BAND, LIVE_ACTION = 3, 0.01, 0.85


# ───────────────────────── helpers（逐字 COPY 自 e1e2_walkforward / e1e2_combined_validate）─────────────────────────
def sharpe_of(dr):
    sd = dr.std()
    return float(dr.mean() / sd * SQRT252) if sd > 0 else 0.0


def ann_of(dr):
    n = len(dr)
    return float((1 + dr).prod() ** (252 / n) - 1) if n > 0 else float("nan")


def year_dr(eq, y):
    return eq[eq.index.year == y].pct_change().dropna()


def dd_of_window(eq, start, end):
    s = eq[(eq.index >= pd.Timestamp(start)) & (eq.index <= pd.Timestamp(end))]
    return float((s / s.cummax() - 1).min()) if len(s) else float("nan")


def calmar(a, dd):
    return a / abs(dd) if dd and abs(dd) > 1e-9 else float("nan")


def window_metrics(eq, start, end):
    """[start,end] 內：年化 / Sharpe / maxDD / Calmar（DD 相對窗內 cummax）。"""
    s = eq[(eq.index >= pd.Timestamp(start)) & (eq.index <= pd.Timestamp(end))]
    r = s.pct_change().dropna()
    ann = float((s.iloc[-1] / s.iloc[0]) ** (252 / len(s)) - 1) if len(s) > 1 and s.iloc[0] > 0 else float("nan")
    dd = float((s / s.cummax() - 1).min()) if len(s) else float("nan")
    return ann, sharpe_of(r), dd, calmar(ann, dd)


def sharpe_se_ann(dr):
    """年化 Sharpe 1 SE（Lo 2002）＝plateau 雜訊尺度 δ。"""
    n = len(dr)
    sd = dr.std()
    if n < 30 or sd == 0:
        return float("nan")
    srd = dr.mean() / sd
    return float(np.sqrt((1 + 0.5 * srd ** 2) / n) * SQRT252)


def agg(eq, oos=False):
    e = eq[eq.index.year.isin(FWD)] if oos else eq
    r = e.pct_change().dropna()
    sh = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    ann = float((e.iloc[-1] / e.iloc[0]) ** (252 / len(e)) - 1)
    dd = float((e / e.cummax() - 1).min())
    return ann, sh, dd, (ann / abs(dd) if abs(dd) > 1e-9 else float("nan"))


def py3(eq, y):
    return bm._per_year(eq).get(y, (float("nan"),) * 3)   # (ret, sharpe, dd)


def worst_fwd_dd(eq):
    return min(bm._per_year(eq).get(Y, (0, 0, 0))[2] for Y in FWD)


def ir_vs(pooled, ref_oos):
    d = pd.concat([pooled.rename("s"), ref_oos.rename("b")], axis=1).dropna()
    return sharpe_of(d["s"] - d["b"])


# ── sim_from_exp（逐字 COPY 自 e1e2_walkforward；回傳 (eq, n_exec)）────────────────────────
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


# ── exp_combined（逐字 COPY 自 e1e2_combined_validate；current-live overlay 精確邏輯）────────────
def exp_combined(close_full, confirm_days=1, band_pct=0.0):
    """E1∩E2 統一 overlay：close<MA×(1−band) 連 confirm 日→reduced；close>MA×(1+band) 連 confirm 日→full。
    (confirm_days=3, band_pct=0.01) ＝ current-live（action 0.85 內建於下游，這裡回 1.0/0.85 exposure）。
    暖身 NaN→未跌破→維持 full。"""
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
    """某年內『態轉折』次數：曝險二值化(是否處於 reduced<full)，年內 diff!=0 次數。
    （E4 含 0.70 深砍檔位時，凡 <FULL 視為 reduced 態，以量測『進出 reduced』whipsaw）。"""
    s = exp_series[exp_series.index.year == year]
    if len(s) < 2:
        return 0
    b = (s.to_numpy(float) < FULL - 1e-9).astype(int)
    return int((np.diff(b) != 0).sum())


# ════════════════════════════════════════════════════════════════════════════════
# E4 早期訊號 + 狀態機（新增；不改任何既有碼）
# ════════════════════════════════════════════════════════════════════════════════
def early_signals(cf, M, X, N_win, rv5_lb=5, rv60_lb=60):
    """回傳 (vs_below, fp_below, early_below) 三個布林 Series（向量化、因果、NaN→False 保守）。
      (a) 5d 已實現 vol-spike：rv5 > M × rv60（M=None → 關閉 vs）。
      (b) from-peak 速度停損：close 自 trailing N_win 日峰跌破 −X（X=None → 關閉 fp）。
      early_below = vs_below OR fp_below。所有訊號只用 ≤ 當日資料（rolling、cummax 皆 trailing）。"""
    if M is None:
        vs_below = pd.Series(False, index=cf.index)
    else:
        rv5 = cf.pct_change().rolling(rv5_lb).std()
        rv60 = cf.pct_change().rolling(rv60_lb).std()
        vs_below = (rv5 > M * rv60).fillna(False)
    if X is None:
        fp_below = pd.Series(False, index=cf.index)
    else:
        peak = cf.rolling(N_win, min_periods=1).max()
        fp = cf / peak - 1.0
        fp_below = (fp <= -X).fillna(False)
    early_below = (vs_below | fp_below)
    return vs_below, fp_below, early_below


def _early_state(early_below, R_hold):
    """早期訊號**獨立**狀態機（逐日因果）：early_below True→立即進 reduced 態；
    退出 reduced 須 early_below=False 連 R_hold 日。回傳 bool Series（是否處於 early-reduced 態）。
    ⚠️ 設計關鍵：early 全 False ⇒ 此態恆 False ⇒ 下游 final_below≡base_below（additive 行為中性鐵證）。"""
    eb = early_below.to_numpy(bool)
    n = len(eb)
    out = np.zeros(n, dtype=bool)
    in_red = False
    run_clear = 0
    for i in range(n):
        if not in_red:
            if eb[i]:
                in_red = True
                run_clear = 0
        else:
            if not eb[i]:
                run_clear += 1
            else:
                run_clear = 0
            if run_clear >= R_hold:
                in_red = False
                run_clear = 0
        out[i] = in_red
    return pd.Series(out, index=early_below.index)


def exp_e4(base_below, early_below, R_hold, reduced=REDUCED):
    """E4 主版（態層 OR 合成；不重跑 base 狀態機，避免雙重 hysteresis 偏離）：
      final_below = base_below(current-live 已解析的 reduced 態) OR early_state(早期訊號獨立狀態機)。
      早期訊號『立即』拉進 reduced（補初跌盲區），退出須 early 清除連 R_hold 日；base 態原樣沿用。
      → early 全關 ⇒ early_state 恆 False ⇒ final_below ≡ base_below ≡ current-live（逐位）。
    回傳 exposure Series（FULL / reduced）。"""
    es = _early_state(early_below, R_hold).to_numpy(bool)
    bb = base_below.to_numpy(bool)
    final_below = bb | es
    out = np.where(final_below, reduced, FULL)
    return pd.Series(out, index=base_below.index)


def exp_e4_deep(base_below, early_below, R_hold, shallow=REDUCED, deep=DEEP):
    """E4 深砍變體（態層合成）：final_below = base_below OR early_state；reduced 檔位依
      「base_below 且 early_state 同時成立→deep(0.70)（雙確認＝真崩盤加碼防禦）else shallow(0.85)」。
      early 全關 ⇒ early_state 恆 False ⇒ 逐位＝current-live（base_below→0.85、否則 1.0）。"""
    es = _early_state(early_below, R_hold).to_numpy(bool)
    bb = base_below.to_numpy(bool)
    n = len(bb)
    out = np.empty(n, dtype=float)
    for i in range(n):
        if not (bb[i] or es[i]):
            out[i] = FULL
        else:
            out[i] = deep if (bb[i] and es[i]) else shallow   # 雙確認(base 與 early 同時 reduced)→更深 0.70
    return pd.Series(out, index=base_below.index)


# ════════════════════════════════════════════════════════════════════════════════
print("=" * 124)
print("E4 — 第二道防線（早期出場）疊加 MA200 overlay | 載入快取 0050（0 API / cache-only）…")
print("=" * 124)
adj = bm.load_adjusted_0050()
cf = adj.set_index("date")["close"].sort_index().astype(float)
print(f"[cache-proof] 0050 還原日線（快取，無 API）：{len(cf)} 列，{cf.index.min().date()} ~ {cf.index.max().date()}")
print(f"[cache-proof] 含 pre-2018 暖身（rv60/MA200 在 2018-01 即 finite）；回測窗 {bm.START} ~ {bm.END}")
print("[cache-proof] 0 API / cache-only：僅 bm.load_adjusted_0050() 讀本地 pickle，無任何 fetcher/.get()/.fetch() 網路呼叫。")
print(f"[cache-proof] base overlay 寫死＝current-live exp_combined(confirm={LIVE_CONFIRM}, band={LIVE_BAND}, action={LIVE_ACTION})；E4 只疊加早期訊號。")

# base 態（current-live overlay）：態層布林
base_exp = exp_combined(cf, LIVE_CONFIRM, LIVE_BAND)          # 1.0 / 0.85
base_below = np.isclose(base_exp.to_numpy(float), REDUCED)    # reduced 態布林（態層 OR 合成用，避免 0.85×0.85 疊乘）
base_below = pd.Series(base_below, index=cf.index)

print("\n" + "=" * 124)
print("【方法論誠實標示（務必讀）】walk-forward FWD=[2022,2023,2024,2025]＝expanding window，2018-2021 永遠在 in-sample。")
print("  2018Q4 崩盤 [IS] ｜ 2020 COVID V 崩 [IS] ｜ 2022 慢熊 [唯一 OOS 崩盤] ｜ 2023-25 牛 [OOS]")
print("  → E4 主打補的『2020 初跌盲區』落在 in-sample，**此窗結構上無法 OOS 驗證**；2018/2020 的改善僅 descriptive/ex-post。")
print("  → walk-forward OOS 實際只能檢定『加 E4 是否惡化 2022 + 牛市(2023-25) 的 OOS 表現』。")
print("=" * 124)


# ── 固定預先指定對照（compute once；絕不 best-of-sweep；絕不引用污染 12.7%/1.16/-16%）────────────
bh = bm.simulate_buyhold(adj)                                # (1) 0050 買持＝報酬王/同-beta alpha 對照
benchB = bm.simulate_benchmark(adj, 0.011, overlay=False)    # (2) 基準B vol0.011 無 overlay＝去風險參考(低 beta)
bh_eq, bb_eq = bh["equity"], benchB["equity"]
live_eq, live_nx = sim_from_exp(adj, base_exp)              # (3) current-live＝E4 base overlay
live_exp = base_exp

benB_oos = pd.concat([year_dr(bb_eq, Y) for Y in FWD])
bh_oos = pd.concat([year_dr(bh_eq, Y) for Y in FWD])
live_oos = pd.concat([year_dr(live_eq, Y) for Y in FWD])
SB, S0, SL = sharpe_of(benB_oos), sharpe_of(bh_oos), sharpe_of(live_oos)
BENB_WDD, BH_WDD, LIVE_WDD = worst_fwd_dd(bb_eq), worst_fwd_dd(bh_eq), worst_fwd_dd(live_eq)
DELTA = sharpe_se_ann(live_oos)                              # plateau 雜訊尺度 δ≈0.513
BH_IRB = ir_vs(bh_oos, benB_oos)                            # 0050 自身 IRvs基準B（純 beta、零技巧）＝beta 參考線
LIVE_OOS_ANN = ann_of(live_oos)
LIVE_2020DD = py3(live_eq, 2020)[2]
LIVE_FL22 = flips_in_year(live_exp, 2022)

print(f"\n[fixed baselines] current-live 全期交易數={live_nx}｜δ(OOS 年化 Sharpe 1SE, Lo-2002, n={len(live_oos)})={DELTA:.3f}")
print(f"[fixed baselines] OOS Sharpe: current-live {SL:.3f} / 基準B {SB:.3f} / 0050 {S0:.3f}")
print(f"[fixed baselines] 最差前進年DD: current-live {LIVE_WDD*100:.1f}% / 基準B {BENB_WDD*100:.1f}% / 0050 {BH_WDD*100:.1f}%")
print(f"[fixed baselines] BETA 參考線：0050 自身 IRvs基準B = {BH_IRB:+.3f}（純 beta、零技巧；用來證明高 IRvsB 只是 beta）")


# ── 退化/中性 sanity：early 全關 ⇒ eq 逐位＝current-live ────────────────────────────────────────
_, _, eb_off = early_signals(cf, None, None, 10)             # M=None & X=None ⇒ early_below 全 False
assert not eb_off.any(), "退化 early_below 非全 False！"
deg_exp = exp_e4(base_below, eb_off, R_hold=LIVE_CONFIRM)    # 早期關 ⇒ final_below ≡ base_below
deg_eq, _ = sim_from_exp(adj, deg_exp)
d_max = float((deg_eq - live_eq).abs().max())
exp_match = bool(np.isclose(deg_exp.to_numpy(float), base_exp.to_numpy(float)).all())
print("\n" + "-" * 124)
print("退化/中性 sanity（E4 additive 行為中性鐵證）：early 全關（M=None,X=None）⇒ final_below ≡ base_below ≡ current-live")
print("-" * 124)
print(f"  exp_e4(early全關) 逐位 == base_exp(current-live)：{exp_match}")
print(f"  equity 曲線 max|Δ| vs current-live = {d_max:.3e}（元）")
assert exp_match, "退化態曝險未逐位重現 base_exp(current-live)！"
assert d_max < 1e-6, f"退化點 equity 偏離過大：{d_max}"
print("  [PASS] E4 additive 行為中性：early 全關逐位重現 current-live（max|Δ|<1e-6 元）。")


# ════════════════════════════════════════════════════════════════════════════════
# Part A — 一維細網格（鐵則#7：單參 ≥12-18 點；固定其他訊號中性；δ 帶判平滑高原 vs 鋸齒孤峰）
# ════════════════════════════════════════════════════════════════════════════════
def run_e4(M, X, N_win, R_hold=LIVE_CONFIRM, rv5_lb=5, rv60_lb=60, deep=False):
    """跑一個 E4 config，回傳 metrics dict + exp_series + 三訊號（lead-time 用）。"""
    vs_b, fp_b, eb = early_signals(cf, M, X, N_win, rv5_lb, rv60_lb)
    e = exp_e4_deep(base_below, eb, R_hold) if deep else exp_e4(base_below, eb, R_hold)
    eq, nx = sim_from_exp(adj, e)
    f, o = agg(eq), agg(eq, oos=True)
    pooled = pd.concat([year_dr(eq, Y) for Y in FWD])
    return {
        "M": M, "X": X, "N_win": N_win, "R_hold": R_hold,
        "full_ann": f[0], "full_sh": f[1], "full_dd": f[2], "full_cal": f[3],
        "oos_ann": o[0], "oos_sh": o[1], "oos_dd": o[2], "oos_cal": o[3],
        "wfd": worst_fwd_dd(eq), "fl22": flips_in_year(e, 2022), "fl18": flips_in_year(e, 2018),
        "fl20": flips_in_year(e, 2020), "nx": nx,
        "ret23": py3(eq, 2023)[0], "ret24": py3(eq, 2024)[0], "ret25": py3(eq, 2025)[0],
        "ret20": py3(eq, 2020)[0], "dd20": py3(eq, 2020)[2],
        "ir_b": ir_vs(pooled, benB_oos), "ir_0": ir_vs(pooled, bh_oos),
        "eq": eq, "exp": e, "vs_b": vs_b, "fp_b": fp_b, "eb": eb,
    }


bh23, bh24, bh25 = py3(bh_eq, 2023)[0], py3(bh_eq, 2024)[0], py3(bh_eq, 2025)[0]

# 一維細網格定義（核心區步長小）
M_GRID = [1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0]              # 14 點（vs；fp 關）
X_GRID = [0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.17, 0.20]  # 14 點（fp X；N_win=10、vs 關）
NWIN_GRID = [3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 21, 25]                                 # 14 點（fp N_win；X=-0.08、vs 關）
RHOLD_GRID = [1, 2, 3, 4, 5]                                                                  # 5 點 sanity（輔助平滑參數）


def print_1d(title, key, rows, fmt_key, current_live_row=True):
    """印一維掃描表 + δ 帶 plateau 判讀。"""
    print("\n" + "=" * 124)
    print(title)
    print("  （全期 Sharpe/maxDD＝in-sample 線索；OOS Sharpe＝主裁雜訊參考；2022flips＝whipsaw；牛市OOSann；2020 lead-time 見 Part B）")
    print("=" * 124)
    print(f"{fmt_key:>8}｜{'全期ann':>8}{'Sh':>6}{'maxDD':>8}{'Cal':>6}｜{'OOSann':>8}{'Sh':>6}{'OOSmDD':>8}｜"
          f"{'最差年DD':>8}{'fl22':>5}｜{'IRvsB':>7}{'IRvs0050':>9}{'交易':>5}")
    print("-" * 124)
    if current_live_row:
        lf, lo = agg(live_eq), agg(live_eq, oos=True)
        print(f"{'live':>8}｜{lf[0]*100:>8.1f}{lf[1]:>6.2f}{lf[2]*100:>8.1f}{lf[3]:>6.2f}｜"
              f"{lo[0]*100:>8.1f}{lo[1]:>6.2f}{lo[2]*100:>8.1f}｜{LIVE_WDD*100:>8.1f}{LIVE_FL22:>5}｜"
              f"{ir_vs(live_oos,benB_oos):>+7.2f}{ir_vs(live_oos,bh_oos):>+9.2f}{live_nx:>5}  ←current-live")
    for r in rows:
        kv = r[key]
        ks = f"{kv}" if key in ("N_win", "R_hold") else f"{kv:.2f}"
        print(f"{ks:>8}｜{r['full_ann']*100:>8.1f}{r['full_sh']:>6.2f}{r['full_dd']*100:>8.1f}{r['full_cal']:>6.2f}｜"
              f"{r['oos_ann']*100:>8.1f}{r['oos_sh']:>6.2f}{r['oos_dd']*100:>8.1f}｜{r['wfd']*100:>8.1f}{r['fl22']:>5}｜"
              f"{r['ir_b']:>+7.2f}{r['ir_0']:>+9.2f}{r['nx']:>5}")
    print("-" * 124)
    oos = np.array([r["oos_sh"] for r in rows])
    peak = float(oos.max())
    in_band = int((oos >= peak - DELTA).sum())
    print(f"  plateau: OOS Sharpe 範圍 [{oos.min():.3f}, {oos.max():.3f}]、中位 {np.median(oos):.3f}；δ={DELTA:.3f}；"
          f"落『峰−δ』帶內 {in_band}/{len(oos)} 格（多格在帶內＝平滑高原；僅 1-2 格突出＝鋸齒孤峰＝雜訊）")


print("\n\n" + "#" * 124)
print("# Part A — 一維細網格（特徵化找平滑高原 vs 鋸齒孤峰；決策只綁 walk-forward OOS、絕不挑 in-sample 峰）")
print("#" * 124)

rows_M = [run_e4(M, None, 10) for M in M_GRID]                 # vs only（fp 關）
print_1d("Part A1 — vol-spike M 掃描（fp 關閉；rv 5/60；early_below = rv5 > M×rv60）", "M", rows_M, "M")

rows_X = [run_e4(None, X, 10) for X in X_GRID]                 # fp only（vs 關，N_win=10）
print_1d("Part A2 — from-peak X% 掃描（vs 關閉；N_win=10；early_below = close 自 trailing-10d 峰 ≤ −X）", "X", rows_X, "X(跌幅)")

rows_N = [run_e4(None, 0.08, N) for N in NWIN_GRID]            # fp only（vs 關，X=-0.08）
print_1d("Part A3 — from-peak N_win 掃描（vs 關閉；X=−0.08；trailing N_win 日峰窗）", "N_win", rows_N, "N_win")

# R_hold sanity（固定 C5 主力 OR 組合 M=1.5+fp(-0.08,10)；只報方向影響）
rows_R = [run_e4(1.5, 0.08, 10, R_hold=R) for R in RHOLD_GRID]
print_1d("Part A4 — R_hold（回補嚴格度）sanity（固定 M=1.5 + fp(−0.08,10)；主版 R_hold=3）", "R_hold", rows_R, "R_hold")

# vol-spike lookback sanity（M=1.5 固定，換 rv lookback）
print("\n" + "-" * 124)
print("Part A5 — vol-spike lookback sanity（M=1.5、fp 關；換 (rv5_lb, rv60_lb) 看穩健性，非主掃）")
print("-" * 124)
print(f"{'(rv5,rv60)':>12}｜{'全期Sh':>7}{'maxDD':>8}｜{'OOSann':>8}{'OOSSh':>7}{'最差年DD':>9}{'fl22':>5}{'IRvs0050':>9}")
for lb in [(5, 60), (5, 40), (10, 60)]:
    r = run_e4(1.5, None, 10, rv5_lb=lb[0], rv60_lb=lb[1])
    print(f"{str(lb):>12}｜{r['full_sh']:>7.2f}{r['full_dd']*100:>8.1f}｜{r['oos_ann']*100:>8.1f}{r['oos_sh']:>7.2f}"
          f"{r['wfd']*100:>9.1f}{r['fl22']:>5}{r['ir_0']:>+9.2f}")


# ════════════════════════════════════════════════════════════════════════════════
# Part B — 2020 / 2018 lead-time 專段（[IS-descriptive / NOT OOS evidence]）
# ════════════════════════════════════════════════════════════════════════════════
PEAK_2020 = 20.635      # 已驗證：2020 全期峰 2020-01-14 close（DRAWDOWN_EVENT_STUDY）
PEAK_2018 = None        # 2018 峰由程式找（次要）
idx_list = list(cf.index)


def first_true_date(bool_series, after=None, year=None):
    s = bool_series
    if after is not None:
        s = s[s.index >= pd.Timestamp(after)]
    if year is not None:
        s = s[s.index.year == year]
    hits = s[s]
    return hits.index[0] if len(hits) else None


def lead_time_days(d_ma, d_early):
    """交易日根數＝MA200 首破 idx − early 首觸 idx（正＝早於 MA200）。"""
    if d_ma is None or d_early is None:
        return None
    return idx_list.index(d_ma) - idx_list.index(d_early)


# 兩個 MA200 首破錨點：
#   (a) base 態＝current-live overlay（連 3 日+1% 帶）首入 reduced 日＝E4 實際 augment 的態 → lead-time 主錨
#   (b) raw 每日 MA200（close<MA200 當日）首破日＝DRAWDOWN_EVENT_STUDY 文獻「−14% 盲區」基準（03-12）→ 附錨
raw_below_daily = (cf < cf.rolling(MA).mean()).fillna(False)
d_ma_2020 = first_true_date(base_below, year=2020)              # base 態（current-live）首破（預期 ~03-16，連3日確認後）
d_ma_2020_raw = first_true_date(raw_below_daily, year=2020)     # raw 每日 MA200 首破（預期 03-12、−14%＝文獻盲區）
# 2018 峰、MA200 首破（次要）
sl2018 = cf[cf.index.year == 2018]
d_peak_2018 = sl2018.idxmax()
peak_2018_val = float(sl2018.max())
d_ma_2018 = first_true_date(base_below, year=2018)

print("\n\n" + "#" * 124)
print("# Part B — 2020 / 2018 lead-time（[IS-descriptive / NOT OOS evidence]）：early 比 MA200 早幾個交易日 + 早觸時自峰跌幅")
print("#" * 124)
print(f"  ⚠️ 2020/2018 皆 in-sample；lead-time 是 ex-post 描述、**非 OOS 證明**（n=1/event，統計力低，不可外推）。")
print(f"  主錨(base 態)：2020 峰 2020-01-14 close={PEAK_2020}；current-live overlay(連3日+1%帶) 首入 reduced = "
      f"{d_ma_2020.date()}（close={float(cf[d_ma_2020]):.3f}、自峰 {(float(cf[d_ma_2020])/PEAK_2020-1)*100:+.1f}%）")
print(f"  附錨(raw 每日 MA200)：close<MA200 首破 = {d_ma_2020_raw.date()}（close={float(cf[d_ma_2020_raw]):.3f}、"
      f"自峰 {(float(cf[d_ma_2020_raw])/PEAK_2020-1)*100:+.1f}%）＝DRAWDOWN_EVENT_STUDY『−14% 盲區』基準")
print(f"          2018 峰 {d_peak_2018.date()} close={peak_2018_val:.3f}；2018 MA200(base) 首破日 = {d_ma_2018.date() if d_ma_2018 is not None else 'N/A'}")

# 代表參數列表（含主力 C5/C6）算各訊號 lead-time
LEAD_CFGS = [
    ("vs M=1.5", 1.5, None, 10),
    ("vs M=2.0", 2.0, None, 10),
    ("fp -8% N=10", None, 0.08, 10),
    ("fp -10% N=10", None, 0.10, 10),
    ("fp -8% N=7", None, 0.08, 7),
    ("C5: M1.5+fp(-8%,10)", 1.5, 0.08, 10),
    ("C6: M2.0+fp(-10%,10)", 2.0, 0.10, 10),
]
print("\n  ── 2020 COVID（峰 01-14）lead-time（交易日；正＝早於『base 態』MA200 主錨 03-16）+ early 首觸時自峰跌幅 ──")
print(f"  {'config':<24}{'vs首觸':>11}{'vs lead':>8}{'vs自峰%':>9}｜{'fp首觸':>11}{'fp lead':>8}{'fp自峰%':>9}｜"
      f"{'early首觸':>11}{'early lead':>11}{'early自峰%':>11}")
for nm, M, X, N in LEAD_CFGS:
    vs_b, fp_b, eb = early_signals(cf, M, X, N)
    dvs = first_true_date(vs_b, after="2020-01-14", year=2020)
    dfp = first_true_date(fp_b, after="2020-01-14", year=2020)
    deb = first_true_date(eb, after="2020-01-14", year=2020)

    def cell(d):
        if d is None:
            return f"{'—':>11}{'—':>8}{'—':>9}"
        return f"{d.date()!s:>11}{lead_time_days(d_ma_2020, d):>8}{(float(cf[d])/PEAK_2020-1)*100:>+8.1f}%"
    print(f"  {nm:<24}{cell(dvs)}｜{cell(dfp)}｜{cell(deb)}")
print(f"  （附錨對照：early 首觸 vs raw 每日 MA200 03-12[−14% 盲區] 的 lead = early_lead_base + "
      f"{lead_time_days(d_ma_2020, d_ma_2020_raw):+d}；fp(−8%) 03-12 恰與 raw 每日 MA200 同日＝lead 0、補的是 base 態的 3 日確認延遲）")

print("\n  ── 2018 Q4（峰 {} ）lead-time（[IS-descriptive]、次要）──".format(d_peak_2018.date()))
print(f"  {'config':<24}{'early首觸':>11}{'early lead':>11}{'early自峰%':>11}")
for nm, M, X, N in LEAD_CFGS:
    _, _, eb = early_signals(cf, M, X, N)
    deb = first_true_date(eb, after=d_peak_2018, year=2018)
    if deb is None:
        print(f"  {nm:<24}{'—':>11}{'—':>11}{'—':>11}")
    else:
        print(f"  {nm:<24}{deb.date()!s:>11}{str(lead_time_days(d_ma_2018, deb)):>11}{(float(cf[deb])/peak_2018_val-1)*100:>+10.1f}%")


# ════════════════════════════════════════════════════════════════════════════════
# Part C — walk-forward（candidate config 清單；per-fold 選參 + 穩健高原 pick）
# ════════════════════════════════════════════════════════════════════════════════
# candidate config 清單（取一維掃高原中段代表值，刻意非 in-sample 峰）：(label, M, X, N_win, R_hold, deep)
CANDIDATES = [
    ("C0 current-live(early全關)", None, None, 10, LIVE_CONFIRM, False),
    ("C1 vs M=1.5", 1.5, None, 10, LIVE_CONFIRM, False),
    ("C2 vs M=2.0", 2.0, None, 10, LIVE_CONFIRM, False),
    ("C3 fp -8% N=10", None, 0.08, 10, LIVE_CONFIRM, False),
    ("C4 fp -10% N=10", None, 0.10, 10, LIVE_CONFIRM, False),
    ("C5 M1.5+fp(-8%,10)", 1.5, 0.08, 10, LIVE_CONFIRM, False),
    ("C6 M2.0+fp(-10%,10)", 2.0, 0.10, 10, LIVE_CONFIRM, False),
    ("C7 M1.7+fp(-8%,7)", 1.7, 0.08, 7, LIVE_CONFIRM, False),
    ("C8 M2.0+fp(-12%,14)", 2.0, 0.12, 14, LIVE_CONFIRM, False),
    ("C5b M1.5+fp(-8%,10) R=1", 1.5, 0.08, 10, 1, False),
    ("C6b M2.0+fp(-10%,10) R=1", 2.0, 0.10, 10, 1, False),
]
# 預跑每個 candidate 的全期 eq（一次、重用；causal sim → 切窗＝重跑到該窗等價）
CAND_EQ = {}     # label -> dict(eq, exp, nx, M, X, N, R, deep)
for label, M, X, N, R, deep in CANDIDATES:
    _, _, eb = early_signals(cf, M, X, N)
    e = exp_e4_deep(base_below, eb, R) if deep else exp_e4(base_below, eb, R)
    eq, nx = sim_from_exp(adj, e)
    CAND_EQ[label] = dict(eq=eq, exp=e, nx=nx, M=M, X=X, N=N, R=R, deep=deep)
CAND_LABELS = [c[0] for c in CANDIDATES]


def select_config(train_end_year, objective="calmar"):
    """擴張窗 [2018, train_end_year] 內，對每 candidate 算 window_metrics；Calmar(或Sharpe) argmax；
    DD floor 重錨『同族基線 current-live(C0) 同窗 DD − DD_BAND』（鐵則#8）；永不固定 fallback（空集→放寬全格+flag）。"""
    start, end = "2018-01-01", f"{train_end_year}-12-31"
    live_dd = dd_of_window(live_eq, start, end)
    floor_thr = live_dd - DD_BAND
    mets = {}
    for label in CAND_LABELS:
        ann, sh, dd, cal = window_metrics(CAND_EQ[label]["eq"], start, end)
        mets[label] = dict(label=label, ann=ann, sh=sh, dd=dd, cal=cal)
    passers = [m for m in mets.values() if m["dd"] >= floor_thr]
    empty = len(passers) == 0
    pool = passers if passers else list(mets.values())
    key = (lambda m: (m["cal"], m["sh"])) if objective == "calmar" else (lambda m: (m["sh"], m["cal"]))
    best = max(pool, key=key)
    return best["label"], len(passers), empty, floor_thr


def walk_forward(objective="calmar"):
    rows, strat_daily, ddby = [], [], {}
    for Y in FWD:
        lbl, npass, empty, floor_thr = select_config(Y - 1, objective)
        eqp = CAND_EQ[lbl]["eq"]
        pyy = bm._per_year(eqp).get(Y, (float("nan"),) * 3)
        ddby[Y] = pyy[2]
        strat_daily.append(year_dr(eqp, Y))
        rows.append(dict(Y=Y, label=lbl, npass=npass, empty=empty, floor=floor_thr,
                         ret=pyy[0], sh=pyy[1], dd=pyy[2], flips=flips_in_year(CAND_EQ[lbl]["exp"], Y)))
    pooled = pd.concat(strat_daily)
    return dict(rows=rows, pooled=pooled, pooled_sharpe=sharpe_of(pooled), pooled_ann=ann_of(pooled),
                worst_fwd_dd=min(ddby.values()), ir=ir_vs(pooled, benB_oos), ir0=ir_vs(pooled, bh_oos),
                labels=[r["label"] for r in rows])


print("\n\n" + "#" * 124)
print("# Part C — walk-forward（擴張窗 [2018,Y-1]→Y；candidate 清單 per-fold 選參；Calmar 主規則 + Sharpe robustness）")
print("#" * 124)
print(f"  candidate 清單（{len(CANDIDATES)} 個，取一維掃高原中段代表值，非 in-sample 峰）：")
for label, M, X, N, R, deep in CANDIDATES:
    print(f"    {label:<28} M={M} X={X} N_win={N} R_hold={R} deep={deep}")

WF = {}
for obj in ("calmar", "sharpe"):
    wf = walk_forward(obj)
    WF[obj] = wf
    ls = " ".join(f"{Y}:{r['label'].split()[0]}" for Y, r in zip(FWD, wf["rows"]))
    uniq = len(set(wf["labels"]))
    fe = sum(r["empty"] for r in wf["rows"])
    print(f"\n  [{obj:>6}·相對-live] per-fold 選 {ls}")
    print(f"      pooled OOS Sharpe {wf['pooled_sharpe']:.3f} | OOS 年化 {wf['pooled_ann']*100:.1f}% | "
          f"IRvs基準B[beta] {wf['ir']:+.3f} | IRvs0050[alpha] {wf['ir0']:+.3f} | "
          f"最差前進年DD {wf['worst_fwd_dd']*100:.1f}% | 相異選參 {uniq} 個"
          f"{'（floor 空集 '+str(fe)+' fold→放寬全格）' if fe else ''}")

# 每 fold 細節（主規則 Calmar）
print("\n" + "-" * 124)
print("每 fold 細節（主規則 Calmar·相對-live）：前進年 報酬/Sharpe/年內DD/flips ｜ 選到 config ｜ 訓練窗過 floor 數")
print("-" * 124)
print(f"{'前進年':>7}{'選到config':>30}{'報酬':>9}{'Sharpe':>8}{'年內DD':>8}{'flips':>6}{'過floor':>9}")
for r in WF["calmar"]["rows"]:
    tag = "[OOS]" if r["Y"] in FWD else ""
    print(f"{r['Y']:>7}{r['label']:>30}{r['ret']*100:>8.1f}%{r['sh']:>8.2f}{r['dd']*100:>7.1f}%{r['flips']:>6}"
          f"{r['npass']:>6}/{len(CANDIDATES)} {tag}")

# 穩健高原 pick：直接把 C5 套全 OOS（非 in-sample 峰、非 per-fold 重選）
C5_eq = CAND_EQ["C5 M1.5+fp(-8%,10)"]["eq"]
C5_exp = CAND_EQ["C5 M1.5+fp(-8%,10)"]["exp"]
C5_pooled = pd.concat([year_dr(C5_eq, Y) for Y in FWD])
print("\n  ── 穩健高原 pick：C5 (M=1.5+fp(-8%,10), R_hold=3) 直接套全 OOS（高原中段共識值、非 per-fold 重選）──")
print(f"     C5 pooled OOS Sharpe {sharpe_of(C5_pooled):.3f} | OOS 年化 {ann_of(C5_pooled)*100:.1f}% | "
      f"最差前進年DD {worst_fwd_dd(C5_eq)*100:.1f}% | IRvs基準B[beta] {ir_vs(C5_pooled,benB_oos):+.3f} | "
      f"IRvs0050[alpha] {ir_vs(C5_pooled,bh_oos):+.3f}")
print(f"     讀法：若 walk-forward 選到的 ≈ C5 高原 pick → 穩；若高原 pick 遠優於 walk-forward → per-fold 選擇不穩(雜訊)。")


# ════════════════════════════════════════════════════════════════════════════════
# Part D — 彙總表（current-live / walk-fwd-E4(Calmar/Sharpe) / 高原pick C5 / E4-deep / 基準B / 0050）
# ════════════════════════════════════════════════════════════════════════════════
# E4-deep 變體（用 C5 參數的深砍版）
_, _, eb_c5 = early_signals(cf, 1.5, 0.08, 10)
deep_exp = exp_e4_deep(base_below, eb_c5, LIVE_CONFIRM)
deep_eq, deep_nx = sim_from_exp(adj, deep_exp)
deep_pooled = pd.concat([year_dr(deep_eq, Y) for Y in FWD])

print("\n\n" + "#" * 124)
print("# Part D — pooled OOS 彙總表 vs 固定預先指定對照（IRvs基準B＝BETA、IRvs0050＝真 ALPHA）")
print("#" * 124)
print(f"{'策略':<30}{'OOS Sharpe':>11}{'OOS年化':>9}{'最差前進年DD':>13}{'IRvsB[beta]':>12}{'IRvs0050[alpha]':>16}{'交易':>6}")
print("-" * 124)
print(f"{'current-live(MA200-85+c3/b1%)':<30}{SL:>11.3f}{LIVE_OOS_ANN*100:>8.1f}%{LIVE_WDD*100:>12.1f}%"
      f"{ir_vs(live_oos,benB_oos):>+12.3f}{ir_vs(live_oos,bh_oos):>+16.3f}{live_nx:>6}")
for obj in ("calmar", "sharpe"):
    wf = WF[obj]
    print(f"{'walk-fwd-E4('+obj+')':<30}{wf['pooled_sharpe']:>11.3f}{wf['pooled_ann']*100:>8.1f}%"
          f"{wf['worst_fwd_dd']*100:>12.1f}%{wf['ir']:>+12.3f}{wf['ir0']:>+16.3f}{'—':>6}")
print(f"{'穩健高原pick C5':<30}{sharpe_of(C5_pooled):>11.3f}{ann_of(C5_pooled)*100:>8.1f}%{worst_fwd_dd(C5_eq)*100:>12.1f}%"
      f"{ir_vs(C5_pooled,benB_oos):>+12.3f}{ir_vs(C5_pooled,bh_oos):>+16.3f}{CAND_EQ['C5 M1.5+fp(-8%,10)']['nx']:>6}")
print(f"{'E4-deep(C5參數,雙確認→70%)':<30}{sharpe_of(deep_pooled):>11.3f}{ann_of(deep_pooled)*100:>8.1f}%{worst_fwd_dd(deep_eq)*100:>12.1f}%"
      f"{ir_vs(deep_pooled,benB_oos):>+12.3f}{ir_vs(deep_pooled,bh_oos):>+16.3f}{deep_nx:>6}")
print("-" * 124)
print(f"{'基準B(vol0.011,無overlay)':<30}{SB:>11.3f}{ann_of(benB_oos)*100:>8.1f}%{BENB_WDD*100:>12.1f}%{0.0:>+12.3f}{ir_vs(benB_oos,bh_oos):>+16.3f}{'—':>6}")
print(f"{'0050 買進持有':<30}{S0:>11.3f}{ann_of(bh_oos)*100:>8.1f}%{BH_WDD*100:>12.1f}%{BH_IRB:>+12.3f}{0.0:>+16.3f}{'—':>6}")
print(f"\n  * δ(OOS Sharpe 1SE)={DELTA:.3f}；OOS Sharpe 差須以此雜訊尺度判讀。")
print(f"  * IRvs基準B＝**BETA 非 alpha**（基準B 為 de-risked 低曝險）：0050 自身 IRvsB={BH_IRB:+.3f}（純 beta、零技巧）為鐵證參考線。")
print(f"    真 alpha 檢定＝**同 beta 的 IRvs0050**（預期 ≈0/負＝無顯著 alpha，與 R0-R5 一致）。")


# ════════════════════════════════════════════════════════════════════════════════
# Part E — 四事件 stress 表（2018[IS] / 2020[IS] / 2022[OOS] / 2023-25[OOS]）
# ════════════════════════════════════════════════════════════════════════════════
STRESS = [
    ("current-live", live_eq, live_exp),
    ("C5 M1.5+fp(-8%,10)", C5_eq, C5_exp),
    ("C6 M2.0+fp(-10%,10)", CAND_EQ["C6 M2.0+fp(-10%,10)"]["eq"], CAND_EQ["C6 M2.0+fp(-10%,10)"]["exp"]),
    ("E4-deep(C5,→70%)", deep_eq, deep_exp),
]
print("\n\n" + "#" * 124)
print("# Part E — 四事件 stress 表：2018Q4[IS] / 2020COVID[IS] / 2022熊[OOS] / 2023-25牛[OOS]（報酬/Sharpe/年內DD/flips）")
print("#" * 124)
print("  ⚠️ 2018/2020＝in-sample（descriptive）；2022/2023-25＝OOS（前進窗）。")
print(f"{'設定':<22}｜{'18報酬':>7}{'18Sh':>6}{'18DD':>7}{'fl18':>5}｜{'20報酬':>7}{'20Sh':>6}{'20DD':>7}{'fl20':>5}｜"
      f"{'22報酬':>7}{'22Sh':>6}{'22DD':>7}{'fl22':>5}")
print("-" * 124)
for nm, eq in [("0050 買持", bh_eq), ("基準B", bb_eq)]:
    a, c, b = py3(eq, 2018), py3(eq, 2020), py3(eq, 2022)
    print(f"{nm:<22}｜{a[0]*100:>6.1f}%{a[1]:>6.2f}{a[2]*100:>6.1f}%{'—':>5}｜{c[0]*100:>6.1f}%{c[1]:>6.2f}{c[2]*100:>6.1f}%{'—':>5}｜"
          f"{b[0]*100:>6.1f}%{b[1]:>6.2f}{b[2]*100:>6.1f}%{'—':>5}")
for nm, eq, e in STRESS:
    a, c, b = py3(eq, 2018), py3(eq, 2020), py3(eq, 2022)
    print(f"{nm:<22}｜{a[0]*100:>6.1f}%{a[1]:>6.2f}{a[2]*100:>6.1f}%{flips_in_year(e,2018):>5}｜"
          f"{c[0]*100:>6.1f}%{c[1]:>6.2f}{c[2]*100:>6.1f}%{flips_in_year(e,2020):>5}｜"
          f"{b[0]*100:>6.1f}%{b[1]:>6.2f}{b[2]*100:>6.1f}%{flips_in_year(e,2022):>5}")
print("-" * 124)
# 牛市代價（2023/24/25 各年 vs 0050 同年）
print("\n  ── 牛市代價 [OOS]：2023/24/25 各年報酬 vs 0050 同年（早期防禦在牛市少賺多少）──")
print(f"  {'設定':<22}｜{'23報酬':>8}{'vs0050':>9}｜{'24報酬':>8}{'vs0050':>9}｜{'25報酬':>8}{'vs0050':>9}")
print(f"  {'0050 買持':<22}｜{bh23*100:>7.1f}%{0.0:>9.1f}｜{bh24*100:>7.1f}%{0.0:>9.1f}｜{bh25*100:>7.1f}%{0.0:>9.1f}")
for nm, eq, e in STRESS:
    r23, r24, r25 = py3(eq, 2023)[0], py3(eq, 2024)[0], py3(eq, 2025)[0]
    print(f"  {nm:<22}｜{r23*100:>7.1f}%{(r23-bh23)*100:>9.1f}｜{r24*100:>7.1f}%{(r24-bh24)*100:>9.1f}｜"
          f"{r25*100:>7.1f}%{(r25-bh25)*100:>9.1f}")


# ════════════════════════════════════════════════════════════════════════════════
# Part F — E4 特有 Gate：2022 假觸發量化（research §4 E4「須證 2022 額外假觸發代價可控」）
# ════════════════════════════════════════════════════════════════════════════════
def trading_days_in_year(series_bool, year):
    s = series_bool[series_bool.index.year == year]
    return int(s.sum())


def n_events(bool_series, year):
    """某年 False→True 轉折次數（觸發『事件』數）。"""
    s = bool_series[bool_series.index.year == year]
    if len(s) < 2:
        return int(s.iloc[0]) if len(s) == 1 and bool(s.iloc[0]) else 0
    b = s.to_numpy(bool).astype(int)
    rises = int(((np.diff(b) == 1)).sum()) + int(b[0])    # 含開年即 True
    return rises


# 估算 round-trip 出 15% 成本（台股費稅 + T+1 跳空滑價，2 邊）
RT_COST = (bm.COST["buy_fee_rate"] + bm.COST["sell_fee_rate"] + bm.COST["sell_tax_rate"]) + 2 * bm.SLIP

print("\n\n" + "#" * 124)
print("# Part F — E4 特有 Gate（research §4 E4）：2022[OOS] 額外假觸發代價 + 牛市假觸發 + 淨判定")
print("#" * 124)
print(f"  估算：一次『出 15% 再補回』round-trip 成本 ≈ 15% × (台股費稅 {(bm.COST['buy_fee_rate']+bm.COST['sell_fee_rate']+bm.COST['sell_tax_rate'])*100:.4f}% + 2×slip {2*bm.SLIP*100:.2f}%) "
      f"= {0.15*RT_COST*100:.3f}pp/次")
print("-" * 124)
print(f"{'config':<22}｜{'22 early觸發日':>14}{'22 vs事件':>10}{'22 fp事件':>10}｜{'22多砍天':>10}{'22多RT':>8}{'全期nexec增':>12}{'22估成本pp':>11}")
print("-" * 124)
# base early-trigger 天數（current-live early 為 0）作對照；多 RT＝2022 因 early 多出的 round-trip（每 2 flips≈1 RT）
for nm, M, X, N in [("C5 M1.5+fp(-8%,10)", 1.5, 0.08, 10), ("C6 M2.0+fp(-10%,10)", 2.0, 0.10, 10)]:
    vs_b, fp_b, eb = early_signals(cf, M, X, N)
    e_full = exp_e4(base_below, eb, LIVE_CONFIRM)
    eq_full, nx_full = sim_from_exp(adj, e_full)
    # 「因 early 而非 base 多砍」的 2022 天數 = (final reduced 且 base 未 reduced) 的天數
    final_red = pd.Series((e_full.to_numpy(float) < FULL - 1e-9), index=cf.index)
    early_only_red = final_red & (~base_below)
    extra_days_22 = trading_days_in_year(early_only_red, 2022)
    vs_evt, fp_evt = n_events(vs_b, 2022), n_events(fp_b, 2022)
    nexec_delta = nx_full - live_nx                              # 全期交易增量（E4 vs current-live）
    rt_22 = max((flips_in_year(e_full, 2022) - LIVE_FL22) / 2.0, 0)   # 2022 多出的 round-trip 數
    est_cost_pp = rt_22 * 0.15 * RT_COST * 100                  # 出 15% × round-trip 成本 × 多 RT 數
    print(f"{nm:<22}｜{trading_days_in_year(eb,2022):>14}{vs_evt:>10}{fp_evt:>10}｜{extra_days_22:>10}{rt_22:>8.1f}{nexec_delta:>+12}{est_cost_pp:>11.3f}")
print("-" * 124)

# 淨效益：2022 全年報酬/DD（E4 vs current-live）= 早期保護收益 − 假觸發成本（已內含於回測 PnL）
print("\n  ── E4c 淨判定（2022[OOS]：E4 全年報酬/DD vs current-live；淨效益已內含於回測 PnL）──")
print(f"  {'config':<22}｜{'2022報酬':>9}{'Δvs live':>9}｜{'2022年內DD':>10}{'Δvs live':>9}｜判定")
live22_ret, live22_dd = py3(live_eq, 2022)[0], py3(live_eq, 2022)[2]
print(f"  {'current-live':<22}｜{live22_ret*100:>8.1f}%{0.0:>9.1f}｜{live22_dd*100:>9.1f}%{0.0:>9.1f}｜(基線)")
for nm, eq, e in STRESS[1:]:
    r22, dd22 = py3(eq, 2022)[0], py3(eq, 2022)[2]
    dret, ddd = (r22 - live22_ret) * 100, (dd22 - live22_dd) * 100
    # 淨效益判定：報酬不顯著惡化(Δret≥-0.5pp 寬鬆帶) 且 DD 不惡化(Δdd≥0)
    net_ok = (dret >= -0.5) and (ddd >= -1e-9)
    print(f"  {nm:<22}｜{r22*100:>8.1f}%{dret:>+9.2f}｜{dd22*100:>9.1f}%{ddd:>+9.2f}｜"
          f"{'淨效益 ≥0 (可控)' if net_ok else '淨效益<0 或 DD 惡化 (代價不可控)'}")

# E4b 牛市假觸發（2023-25）
print("\n  ── E4b 牛市假觸發 [OOS]：2023-25 early 觸發事件數 + 少賺（vs 0050）──")
print(f"  {'config':<22}｜{'23early事件':>12}{'24early事件':>12}{'25early事件':>12}｜{'牛市3年 vs0050 累計少賺pp':>26}")
for nm, M, X, N in [("C5 M1.5+fp(-8%,10)", 1.5, 0.08, 10), ("C6 M2.0+fp(-10%,10)", 2.0, 0.10, 10)]:
    vs_b, fp_b, eb = early_signals(cf, M, X, N)
    e_full = exp_e4(base_below, eb, LIVE_CONFIRM)
    eq_full, _ = sim_from_exp(adj, e_full)
    miss = sum((py3(eq_full, y)[0] - py3(bh_eq, y)[0]) for y in (2023, 2024, 2025)) * 100
    print(f"  {nm:<22}｜{n_events(eb,2023):>12}{n_events(eb,2024):>12}{n_events(eb,2025):>12}｜{miss:>26.1f}")


# ════════════════════════════════════════════════════════════════════════════════
# Part G — §5 Gate 逐項裁決（①-⑧ + E4 特有）對 walk-forward 主規則
# ════════════════════════════════════════════════════════════════════════════════
print("\n\n" + "#" * 124)
print("# Part G — §5 Gate 逐項裁決（walk-forward 主規則 Calmar；①-⑧ + E4 特有；總 Gate 未過前 live 不動）")
print("#" * 124)
wf = WF["calmar"]
wfs = WF["sharpe"]
uniq = len(set(wf["labels"]))
wf_fl22 = next(r["flips"] for r in wf["rows"] if r["Y"] == 2022)

g_dd = (wf["worst_fwd_dd"] >= LIVE_WDD - 1e-9) and (wf["worst_fwd_dd"] > BENB_WDD) and (wf["worst_fwd_dd"] > BH_WDD)
g_sharpe_noworse = wf["pooled_sharpe"] >= SL - DELTA
sharpe_edge_0050 = wf["pooled_sharpe"] - S0
g_alpha = (wf["ir0"] > 0) and (sharpe_edge_0050 > DELTA)
g_whip = wf_fl22 <= LIVE_FL22                          # E4 加早期訊號天然增 flips → 此項 E4 最易踩雷
g_bull = wf["pooled_ann"] >= LIVE_OOS_ANN - 0.01
robust = abs(wf["pooled_sharpe"] - wfs["pooled_sharpe"]) <= 0.2
# E4 特有：2022 早期保護淨效益（C5 為主力）
c5_22ret, c5_22dd = py3(C5_eq, 2022)[0], py3(C5_eq, 2022)[2]
e4_net22 = (c5_22ret - live22_ret >= -0.005) and (c5_22dd - live22_dd >= -1e-9)
e4_bull = all((py3(C5_eq, y)[0] - py3(live_eq, y)[0]) >= -0.01 for y in (2023, 2024, 2025))
e4_ctrl = e4_net22 and e4_bull
struct_pass = g_dd and g_sharpe_noworse and g_whip and g_bull and robust

print(f"  ① 對照固定預先指定（基準B+0050 買持，compute once）：✔（結構性滿足）")
print(f"  ② walk-forward OOS（FWD={FWD} pooled 主裁）：✔")
print(f"  ③ 降-DD 不惡化且優於兩被動：最差前進年DD {wf['worst_fwd_dd']*100:.1f}% "
      f"(live {LIVE_WDD*100:.1f}% / B {BENB_WDD*100:.1f}% / 0050 {BH_WDD*100:.1f}%) → {'✓' if g_dd else '✗'}")
print(f"  ④ OOS Sharpe 不顯著差於 current-live（δ={DELTA:.2f} 帶內）：{wf['pooled_sharpe']:.3f} vs live {SL:.3f} → {'✓' if g_sharpe_noworse else '✗'}")
print(f"  ⑤ whipsaw/換手不惡化（2022 flips {wf_fl22} ≤ current-live {LIVE_FL22}）→ {'✓' if g_whip else '✗'}"
      f"（E4 加早期訊號天然增 flips＝最易踩雷處）")
print(f"  ⑥ 牛市不顯著犧牲（OOS 年化 {wf['pooled_ann']*100:.1f}% vs live {LIVE_OOS_ANN*100:.1f}%）→ {'✓' if g_bull else '✗'}")
print(f"  ⑦ 選參穩定（plateau）：相異選參 {uniq} 個；robustness(Calmar↔Sharpe pooled 差 {abs(wf['pooled_sharpe']-wfs['pooled_sharpe']):.3f}≤0.2) → {'✓' if robust else '✗'}")
print(f"  ⑧ 真 alpha（同 beta vs 0050）：IRvs0050 {wf['ir0']:+.3f}、OOS Sharpe 邊際 {sharpe_edge_0050:+.3f} vs δ {DELTA:.2f} → "
      f"{'✓ 有顯著 alpha' if g_alpha else '✗ 無（預期 FAIL）'}；註：IRvs基準B {wf['ir']:+.2f}＝beta（0050 自身 IRvsB={BH_IRB:+.2f}）")
print(f"\n  【E4 特有 Gate（research §4）】2022 額外假觸發代價可控？")
print(f"    E4a 2022 淨效益（C5：報酬 Δ{(c5_22ret-live22_ret)*100:+.2f}pp、DD Δ{(c5_22dd-live22_dd)*100:+.2f}pp）→ {'✓ 可控' if e4_net22 else '✗ 代價不可控'}")
print(f"    E4b 牛市代價（C5 2023-25 各年 vs live 皆 ≥ −1pp）→ {'✓' if e4_bull else '✗'}")
print(f"    E4c 淨判定 → {'✓ 假觸發代價可控' if e4_ctrl else '✗ 早期假觸發代價不可控→不採'}")

struct_verdict = ("結構 Gate PASS（DD 不惡化 + whipsaw 不惡化 + 牛市不犧牲 + 選參穩）" if struct_pass
                  else ("結構 Gate FAIL" if not (g_dd and g_whip) else "結構 Gate MARGINAL"))
print(f"\n  ▶ 結構 Gate 裁決：{struct_verdict}")
print(f"  ▶ alpha Gate 裁決：{'PASS（有顯著超額）' if g_alpha else 'FAIL（無顯著 alpha；IRvs0050≈0、Sharpe 邊際<δ）'}（預期 FAIL）")
print(f"  ▶ E4 特有 Gate 裁決：{'PASS（2022 假觸發代價可控）' if e4_ctrl else 'FAIL（早期假觸發代價不可控）'}")

print("\n" + "=" * 124)
print("結論口徑（重申方法論誠實點）：")
print("  • 本窗 2018/2020 永在 in-sample → E4 主打補的『2020 初跌盲區』**結構上無法 OOS 驗證**；2018/2020 改善僅 descriptive/ex-post。")
print("  • walk-forward OOS 實際只檢定『加 E4 是否惡化 2022 + 牛市(2023-25)』；2020 lead-time 標 [IS-descriptive / NOT OOS evidence]。")
print("  • alpha 預期且確認 FAIL（IRvs0050≈0、與 R0-R5 一致）；IRvs基準B 是 beta（0050 自身 IRvsB≈+1.0）。")
print("  • survivorship（FinMind 無下市）→ 全為**上界**。")
print("  • **總 Gate（R5：對 0050 buy-hold 無顯著 alpha + 無 mandate）未翻案 → live（MA200 + 0.85 + confirm3/band1%）一律不動。**")
print("  • E4 即使結構/E4 特有 Gate PASS，也僅是『現行防禦 overlay 的早期偵測候選微調』、非 alpha、非 outperformer。")
print("[done] E4 第二道防線 walk-forward 完成（純快取、0 API、未改任何既有檔）。")

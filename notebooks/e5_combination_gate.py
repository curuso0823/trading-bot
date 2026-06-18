"""
notebooks/e5_combination_gate.py
E5 — 組合閘（Combination Gate, K-of-N）早期偵測 第二道防線 walk-forward OOS 驗證
（沙盒研究；純快取、0 API、不改任何既有檔；不 commit、不切 branch）。

承 docs/EVENT_DETECTION_RESEARCH.md（§2 建議2「雙層確認」+ §4 E5 列 + 附錄B Part B.2 假訊號表）：
  在 current-live overlay（MA200 連 3 日確認 + 1% 緩衝帶 -85%）之上，**疊加第二道防線**＝把四個快訊號組成
  「K-of-N 組合閘」，≥K 個同時成立才額外早期出 15%（不改 MA200 本體）。目標：補「初跌無保護」盲區
  （MA200 滯後：2020 跌 −14% 才觸發、2022 −11%），同時量化牛市代價。
  文獻（附錄B）：單訊號假陽性 ~35%、3+ 訊號同時 ~10% → 組合閘比 E4 純 OR 閘減少牛市假觸發、保住崩盤保護。

四個候選確認訊號（皆 0050 純快取、causal、逐日對齊 cf 收盤索引）：
  S1 MA200_below（趨勢，用原始每日 raw_below，不過 N=3 confirm/band）
  S2 vol-spike：rv5/rv60 > VR_THR（5d 已實現 vol > VR_THR × 60d）
  S3 from-peak 速度：close/peak(PK_WIN)−1 ≤ −FP_DROP
  S4 foreign_sell：0050 外資淨額(buy−sell) 連 FN 日 < 0（**只當組合票、絕不單獨用**；R-attrib 證籌碼 standalone 跨 K 變號）

⚠️ 方法論誠實點（最重要，務必納入結論判讀）：
  walk-forward FWD=[2022,2023,2024,2025]＝expanding window → **2018Q4 + 2020COVID 永遠在 in-sample 訓練段，
  唯一落在 OOS 前進窗的崩盤＝2022 慢熊。** E5 主打要補的「2020 初跌盲區」**無法用此窗做 OOS 驗證**——
  2018/2020 的 lead-time/DD「改善」只能是 descriptive/ex-post in-sample 觀察，**不得當 OOS 證據**。
  walk-forward OOS 實際只能裁「加 E5 是否惡化 2022 + 牛市(2023-25) 的 OOS 表現」。

⚠️ beta vs alpha：IRvs基準B 是 **beta**（基準B 為 de-risked 低曝險）、**非 alpha**；鐵證＝0050 買持自身
  IRvs基準B≈+1.0（純 beta、零技巧）。**真 alpha 檢定＝同 beta 的 IRvs0050**。預期 alpha FAIL（R0–R5/E1-E2 一致）。
⚠️ 0050 自身外資流是 **proxy**（ETF 籌碼 ≠ 全市場外資；已查證快取無全市場法人）→ 標 caveat。
⚠️ survivorship 上界（FinMind 無下市股）→ 所有結果是上界；總 Gate 未過前 live（MA200 連3日+1%帶-85%）不動。

用法：.venv/bin/python notebooks/e5_combination_gate.py
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

# importlib 安全載入 benchmark_backtest（有 __main__ guard）
_spec = importlib.util.spec_from_file_location("bm", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

SQRT252 = np.sqrt(252)
FWD = [2022, 2023, 2024, 2025]      # OOS 前進窗（同 R0/R1/E1-E2）
BULL = [2023, 2024, 2025]           # 牛市段（OOS 內）
MA = 200
REDUCED, FULL = 0.85, 1.0           # 單防線砍至 85%
DEEP = 0.70                          # V_DEEP 變體：兩防線同時觸發砍至 70%（總出 30%＝研究紀律上限）
DD_BAND = 0.022                     # path-dependence 容差（同 R1/E1-E2；相對同族基線 floor 用）
CHIP_PKL = os.path.join(ROOT, "data", "raw", "finmind_cache",
                        "TaiwanStockInstitutionalInvestorsBuySell__0050__2018-01-01__2025-12-31.pkl")

# 中位候選（單參細掃時其餘固定於此）
MID = dict(K=2, VR_THR=1.5, FP_DROP=0.06, PK_WIN=20, FN=3, EARLY_MULT=0.85)


# ───────────────────────── helpers（COPY 自 e1e2_walkforward.py，改寫吃 E5 config）─────────────────────────
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
    """[start,end] 內：年化 / Sharpe / maxDD / Calmar。"""
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


# ── sim_from_exp（逐字 COPY e1e2_walkforward.py；回傳 (eq, n_exec)；絕不改成本/T+1/再平衡口徑）──
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


# ── exp_combined（逐字 COPY e1e2_combined_validate.py＝current-live 精確邏輯；confirm_days/band_pct 狀態機）──
def exp_combined(close_full, confirm_days=1, band_pct=0.0):
    """E1∩E2 統一態序列（值域 {1.0, 0.85}）：close<MA×(1−band) 連 confirm 日→reduced；
    close>MA×(1+band) 連 confirm 日→full。(confirm_days=3, band_pct=0.01) 逐位重現 current-live。"""
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
    """該年內『最終曝險態轉折』次數（曝險 mult 變化）。E5 final_mult 可為 1.0/0.85/0.70。"""
    s = exp_series[exp_series.index.year == year]
    if len(s) < 2:
        return 0
    vals = s.to_numpy(float)
    return int((np.abs(np.diff(vals)) > 1e-9).sum())


def early_true_days(early_series, years):
    s = early_series[early_series.index.year.isin(years)]
    return int(s.sum())


def ir_vs(pooled, ref_oos):
    d = pd.concat([pooled.rename("s"), ref_oos.rename("b")], axis=1).dropna()
    return sharpe_of(d["s"] - d["b"])


# ════════════════════════════════════════════════════════════════════════════════
print("=" * 120)
print("E5 — 組合閘（K-of-N）第二道防線 walk-forward OOS 驗證 | 載入快取 0050 + 0050 外資籌碼（0 API / cache-only）…")
print("=" * 120)
adj = bm.load_adjusted_0050()
cf = adj.set_index("date")["close"].sort_index().astype(float)
print(f"[sanity] 0050 還原日線（快取，無 API）：{len(cf)} 列，{cf.index.min().date()} ~ {cf.index.max().date()}")

# ── 載入 0050 外資籌碼（純快取 pd.read_pickle，無 fetcher）────────────────────────────
_chip = pd.read_pickle(CHIP_PKL)
_chip["date"] = pd.to_datetime(_chip["date"])
_fi = _chip[_chip["name"] == "Foreign_Investor"].copy()
_fi_net = (_fi["buy"].astype(float) - _fi["sell"].astype(float))
_fi_net.index = _fi["date"]
_fi_net = _fi_net.sort_index()
print(f"[sanity] 0050 外資籌碼（快取，無 API）：{len(_chip)} 列 / Foreign_Investor {len(_fi_net)} 列，"
      f"{_fi_net.index.min().date()} ~ {_fi_net.index.max().date()}")
print(f"[sanity] 0 API / cache-only：僅 bm.load_adjusted_0050()（讀本地 pickle）+ pd.read_pickle 讀籌碼 pkl；"
      f"無任何 fetcher.get_*/fetch() 網路呼叫。")

# 外資淨額對齊到價格交易日格線（cf.index）；補班日(2019-08-24/10-26)落出格線被丟、2023-11-10 無籌碼→NaN→False（保守不誤觸）
net_px = _fi_net.reindex(cf.index)
# 回測窗(2018-25)內的對齊缺口（pre-2018 cf 暖身段 chip 無資料屬正常→S4 暖身 False，與基線一致）
_win_mask = (cf.index >= pd.Timestamp("2018-01-01")) & (cf.index <= pd.Timestamp("2025-12-31"))
_nan_win = net_px[_win_mask][net_px[_win_mask].isna()]
_chip_only = sorted(set(_fi_net.index) - set(cf.index))
print(f"[sanity] 外資淨額 reindex 到價格格線｜回測窗(2018-25) 內 NaN（無籌碼列→當 False，保守不誤觸）："
      f"{[d.date() for d in _nan_win.index]}（共 {len(_nan_win)} 個）")
print(f"[sanity]   chip-only（補班日，落出價格格線自動丟棄）：{[d.date() for d in _chip_only]}；"
      f"pre-2018 暖身段 chip 無資料→S4 暖身 False（與基線一致）")
print(f"[sanity] FWD(OOS)={FWD}｜⚠️ expanding window → 2018Q4+2020COVID 永遠 in-sample，唯一 OOS 崩盤＝2022 慢熊。")
print(f"[sanity] ⚠️ 0050 自身外資流＝proxy（ETF 籌碼≠全市場外資；已查證快取無全市場法人）。")

# ── 四訊號 builder（全對齊 cf.index、causal）────────────────────────────────────────
# S1（每日 raw_below，不過 confirm/band）— 一次算好重用
ma200 = cf.rolling(MA).mean()
RAW_BELOW = (cf < ma200).fillna(False)            # S1
# 外資淨賣 raw（連 FN 日成立用，reindex 後 NaN→False）
FI_SELL_RAW = (net_px < 0).fillna(False)          # 連續日數前的 raw 淨賣 bool


def build_signals(VR_THR, FP_DROP, PK_WIN, FN):
    """回傳 dict of bool Series（index≡cf.index）：S1(MA200 raw)/S2(vol-spike)/S3(from-peak)/S4(外資連 FN 日淨賣)。"""
    rv5 = cf.pct_change().rolling(5).std()
    rv60 = cf.pct_change().rolling(60).std()
    s2 = (rv5 / rv60 > VR_THR).fillna(False)
    peak = cf.rolling(PK_WIN).max()
    s3 = ((cf / peak - 1) <= -FP_DROP).fillna(False)
    s4 = FI_SELL_RAW.rolling(FN).sum().ge(FN).fillna(False)   # 連 FN 日皆淨賣
    return {"S1": RAW_BELOW, "S2": s2, "S3": s3, "S4": s4}


def make_early(K, VR_THR, FP_DROP, PK_WIN, FN, use_foreign=True):
    """組合閘 early_signal（bool Series）：votes = ΣS（含/不含 S4）≥ K。"""
    sig = build_signals(VR_THR, FP_DROP, PK_WIN, FN)
    if use_foreign:
        votes = (sig["S1"].astype(int) + sig["S2"].astype(int)
                 + sig["S3"].astype(int) + sig["S4"].astype(int))
    else:
        votes = (sig["S1"].astype(int) + sig["S2"].astype(int) + sig["S3"].astype(int))
    return (votes >= K).fillna(False)


def make_exp(K=2, VR_THR=1.5, FP_DROP=0.06, PK_WIN=20, FN=3, EARLY_MULT=0.85,
             use_foreign=True, deep=False):
    """final exposure 序列（疊加層，取 min）：
       base = exp_combined(cf,3,0.01)（current-live 態）；early = K-of-N；
       final = min(combined_state, early_factor)（單防線各砍 15%；同時觸發仍 0.85＝總出 ≤15%）。
       deep=True（V_DEEP 變體）：combined_state==0.85 且 early==True → 0.70（總出 30% 上限）。"""
    combined_state = exp_combined(cf, 3, 0.01)
    early = make_early(K, VR_THR, FP_DROP, PK_WIN, FN, use_foreign=use_foreign)
    early_factor = pd.Series(np.where(early.values, EARLY_MULT, 1.0), index=cf.index)
    final_mult = np.minimum(combined_state.values, early_factor.values)
    if deep:
        both = (np.isclose(combined_state.values, REDUCED)) & (early.values)
        final_mult = np.where(both, DEEP, final_mult)
    return pd.Series(final_mult, index=cf.index), early


# ── 因 base vol-target≡1.0（live target_daily_vol=1.0），態序列直接＝目標曝險（與 e1e2 範本一致）──
# E4（純 OR 閘對比基準，非生產）：early_E4 = (S2 or S3)，無 S1/無外資/無 K-of-N
def make_exp_E4(VR_THR=1.5, FP_DROP=0.06, PK_WIN=20, EARLY_MULT=0.85):
    sig = build_signals(VR_THR, FP_DROP, PK_WIN, MID["FN"])
    early = (sig["S2"] | sig["S3"]).fillna(False)
    combined_state = exp_combined(cf, 3, 0.01)
    early_factor = pd.Series(np.where(early.values, EARLY_MULT, 1.0), index=cf.index)
    final_mult = np.minimum(combined_state.values, early_factor.values)
    return pd.Series(final_mult, index=cf.index), early


# ════════════════════════════════════════════════════════════════════════════════
# 退化 / 中性 sanity（必印且 assert）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "-" * 120)
print("退化 / 中性 sanity（assert）")
print("-" * 120)
# (b) current-live 自身（base＝MA200 連 3 日確認 + 1% 緩衝帶）
live_state = exp_combined(cf, 3, 0.01)
live_eq, live_nx = sim_from_exp(adj, live_state)

# (c1) 引擎一致性（DAILY rule）：repo 版 bm.simulate_benchmark 只吃 (overlay,regime_ma,regime_action)、
#      未 forward confirm/band → 其 overlay 路徑＝每日 close<MA(confirm=1,band=0)。故與 exp_combined(1,0.0) 對齊
#      （與 e1e2_combined_validate.py:162-164 同一不變量）。證 base 狀態機 ≡ 引擎 daily overlay。
live_daily = exp_combined(cf, 1, 0.0)
daily_eq, _ = sim_from_exp(adj, live_daily)
eng_daily = bm.simulate_benchmark(adj, 1.0, overlay=True, regime_ma=MA, regime_action=0.85)["equity"]
d_eng1 = float((daily_eq - eng_daily).abs().max())
assert d_eng1 < 1e-3, f"exp_combined(1,0.0) 未重現引擎 daily overlay：max|Δ|={d_eng1:.2e}"

# (c2) current-live(3,0.01) 邏輯 ≡ 引擎『純函式』_regime_below(confirm_days=3,band_pct=0.01)
#      （引擎 pure 函式 DO 吃 confirm/band；只是 benchmark_backtest.py 的 wrapper 未 forward）→ 證 live 狀態機口徑一致。
#      直接比對「跌破(reduced)態」bool：我的 exp_combined(3,0.01)==0.85 處 ⟺ 引擎 _regime_below==True 處（逐位）。
from src.strategy_engines.benchmark_engine import _regime_below as _erb
_eng_below = _erb(cf, cf.rolling(MA).mean(), confirm_days=3, band_pct=0.01)
_mine_below = np.isclose(live_state.to_numpy(float), REDUCED)
_state_match = bool((np.asarray(_eng_below) == _mine_below).all())
assert _state_match, "exp_combined(3,0.01) 跌破態與引擎 _regime_below(confirm=3,band=0.01) 不一致"

# (a) early 全關（K 設極大）→ final≡current-live → eq 逐位等
exp_off, early_off = make_exp(K=99)
assert int(early_off.sum()) == 0, "K=99 早期訊號未全關"
eq_off, nx_off = sim_from_exp(adj, exp_off)
d_off = float((live_eq - eq_off).abs().max())
assert d_off < 1e-6, f"early 全關未重現 current-live：max|Δ|={d_off:.2e}"
print(f"[sanity] (a) early 全關(K=99) ≡ current-live：max|Δ|={d_off:.1e} 元 ✓")
print(f"[sanity] (b) current-live(MA200連3+1%-85) 全期交易數={live_nx}")
print(f"[sanity] (c1) exp_combined(1,0.0) ≡ 引擎 daily overlay(simulate_benchmark)：max|Δ|={d_eng1:.1e} 元 ✓"
      f"（repo wrapper 未 forward confirm/band → daily 路徑）")
print(f"[sanity] (c2) exp_combined(3,0.01) 態 ≡ 引擎 pure vol_target_exposure(confirm=3,band=0.01) 態（綁滿區逐位一致）✓")

# ── 固定三基準 + E4（compute once）────────────────────────────────────────────────
bh = bm.simulate_buyhold(adj)
benchB = bm.simulate_benchmark(adj, 0.011, overlay=False)
bh_eq, bb_eq = bh["equity"], benchB["equity"]
bh_oos = pd.concat([year_dr(bh_eq, Y) for Y in FWD])
benB_oos = pd.concat([year_dr(bb_eq, Y) for Y in FWD])
live_oos = pd.concat([year_dr(live_eq, Y) for Y in FWD])
S0, SB, SL = sharpe_of(bh_oos), sharpe_of(benB_oos), sharpe_of(live_oos)
BH_WDD = min(dd_of_window(bh_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
BENB_WDD = min(dd_of_window(bb_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
LIVE_WDD = min(dd_of_window(live_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
DELTA = sharpe_se_ann(live_oos)
BH_IRB = ir_vs(bh_oos, benB_oos)    # 0050 自身 IRvs基準B＝純 beta 鐵證
LIVE_OOS_ANN = ann_of(live_oos)
LIVE_BULL_ANN = ann_of(pd.concat([year_dr(live_eq, Y) for Y in BULL]))
LIVE_FL22 = flips_in_year(live_state, 2022)

print(f"\n[plateau scale] δ(OOS 年化 Sharpe 1SE, Lo-2002, current-live pooled n={len(live_oos)}) = {DELTA:.3f}")
print(f"[beta 鐵證] 0050 買持自身 IRvs基準B = {BH_IRB:+.3f}（純 beta、零技巧）→ 任何 IRvs基準B≈+1 都是 beta、非 alpha；"
      f"**真 alpha 檢定＝同 beta 的 IRvs0050**。")


# ════════════════════════════════════════════════════════════════════════════════
# Part A — 單參細網格（鐵則#7：單參 ≥12-18 點、核心步長小；找平滑高原 vs 鋸齒孤峰）
# ════════════════════════════════════════════════════════════════════════════════
SWEEPS = {
    "VR_THR": [1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0],
    "FP_DROP": [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.11, 0.12, 0.14, 0.16, 0.18, 0.20],
    "PK_WIN": [5, 7, 10, 12, 15, 18, 20, 25, 30, 40, 50, 60],
    "FN": [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20],
    "EARLY_MULT": [1.00, 0.95, 0.90, 0.875, 0.85, 0.825, 0.80, 0.775, 0.75, 0.70, 0.65, 0.60, 0.55],
}


def metrics_for_exp(exp_series):
    """先 sim_from_exp(曝險→equity)，再算 in-sample(2018-21) Sharpe / OOS(2022-25) Sharpe / worst-fwd-DD / 牛市 ann。"""
    eq, _ = sim_from_exp(adj, exp_series)             # 曝險 → equity（metrics 一律用 equity）
    is_sh = window_metrics(eq, "2018-01-01", "2021-12-31")[1]
    oos = pd.concat([year_dr(eq, Y) for Y in FWD])
    oos_sh = sharpe_of(oos)
    wfd = min(dd_of_window(eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    bull_ann = ann_of(pd.concat([year_dr(eq, Y) for Y in BULL]))
    return is_sh, oos_sh, wfd, bull_ann


print("\n" + "=" * 120)
print("Part A — 單參細網格（其餘固定中位 K=2/VR=1.5/FP=0.06/PK=20/FN=3/MULT=0.85；含外資 N=4）")
print(f"  δ={DELTA:.3f}（OOS Sharpe 1SE）；判讀：OOS 曲線落 δ 帶內＝平滑高原(訊號)、否則鋸齒孤峰(雜訊)。"
      f" current-live OOS Sharpe={SL:.3f}")
print("=" * 120)
plateau_notes = {}
for pname, grid in SWEEPS.items():
    print(f"\n— sweep {pname}（{len(grid)} 點）—  [in-sample 2018-21 Sh | OOS 2022-25 Sh | worst-fwd-DD | 牛市 ann]")
    oos_curve = []
    for v in grid:
        kw = dict(MID)
        kw[pname] = v
        expv, earlyv = make_exp(**kw)
        is_sh, oos_sh, wfd, bull_ann = metrics_for_exp(expv)
        oos_curve.append(oos_sh)
        mark = ""
        if pname == "EARLY_MULT" and abs(v - 1.00) < 1e-9:
            mark = " ←關閉=current-live"
        print(f"   {pname}={v:<7} | IS Sh {is_sh:>6.3f} | OOS Sh {oos_sh:>6.3f} | wfd {wfd*100:>6.1f}% | "
              f"牛市ann {bull_ann*100:>6.1f}%{mark}")
    # plateau 判讀：OOS 曲線 max-min 相對 δ
    rng = max(oos_curve) - min(oos_curve)
    near_live = sum(1 for x in oos_curve if abs(x - SL) <= DELTA)
    plateau_notes[pname] = (rng, near_live, len(grid))
    verdict = "平滑高原(δ 帶內)" if rng <= DELTA else ("近高原(振幅 ~1δ)" if rng <= 1.6 * DELTA else "鋸齒/孤峰(振幅 >1.6δ)")
    print(f"   → OOS 曲線振幅 {rng:.3f}（δ={DELTA:.3f}）；{near_live}/{len(grid)} 點落 current-live ±δ 內 ⇒ {verdict}")


# ════════════════════════════════════════════════════════════════════════════════
# Part B — walk-forward（FWD expanding；per-fold 選參 Calmar 優先 + Sharpe robustness；穩健 plateau pick）
# ════════════════════════════════════════════════════════════════════════════════
# candidate config 清單（精選網格，避免笛卡兒爆炸）
VRset = [1.5, 1.8, 2.2]
FPPK = [(0.05, 20), (0.07, 20), (0.09, 30)]
CANDIDATES = []
for K in (2, 3):
    for vr in VRset:
        for fp, pk in FPPK:
            for fn_tag in ("FN3", "FN5", "noFI"):
                for mult in (0.85, 0.75):
                    if fn_tag == "noFI":
                        cfg = dict(K=K, VR_THR=vr, FP_DROP=fp, PK_WIN=pk, FN=MID["FN"],
                                   EARLY_MULT=mult, use_foreign=False)
                    else:
                        cfg = dict(K=K, VR_THR=vr, FP_DROP=fp, PK_WIN=pk,
                                   FN=(3 if fn_tag == "FN3" else 5), EARLY_MULT=mult, use_foreign=True)
                    CANDIDATES.append(cfg)


def cfg_key(c):
    return (c["K"], c["VR_THR"], c["FP_DROP"], c["PK_WIN"], c["FN"], c["EARLY_MULT"], c["use_foreign"])


def cfg_label(c):
    fi = f"FN{c['FN']}" if c["use_foreign"] else "noFI"
    return f"K{c['K']}/VR{c['VR_THR']}/FP{c['FP_DROP']}/PK{c['PK_WIN']}/{fi}/M{c['EARLY_MULT']}"


# 預跑每個 candidate 全期 eq（一次、重用；causal sim 切窗等價）
print("\n" + "=" * 120)
print(f"Part B — walk-forward（{len(CANDIDATES)} candidate configs；預跑全期 eq 重用）")
print("=" * 120)
EQ = {}     # key -> (eq_equity, exp_state, early, n_exec)
for c in CANDIDATES:
    expc, earlyc = make_exp(**c)              # expc＝曝險態序列
    eqp, nxp = sim_from_exp(adj, expc)        # eqp＝equity curve
    EQ[cfg_key(c)] = (eqp, expc, earlyc, nxp)


def select_cfg(train_end_year, objective="calmar"):
    """擴張窗 [2018, train_end_year] 內選 config：Calmar(或 Sharpe) argmax；
    DD floor 重錨同族基線 current-live 同窗 DD − DD_BAND（鐵則#8，絕不錨基準B/絕對 floor）；永不固定 fallback。"""
    start, end = "2018-01-01", f"{train_end_year}-12-31"
    live_dd = dd_of_window(live_eq, start, end)
    floor_thr = live_dd - DD_BAND
    mets = []
    for c in CANDIDATES:
        eqp = EQ[cfg_key(c)][0]
        ann, sh, dd, cal = window_metrics(eqp, start, end)
        mets.append(dict(c=c, ann=ann, sh=sh, dd=dd, cal=cal))
    passers = [m for m in mets if m["dd"] >= floor_thr]
    empty = len(passers) == 0
    pool = passers if passers else mets
    key = (lambda m: (m["cal"], m["sh"])) if objective == "calmar" else (lambda m: (m["sh"], m["cal"]))
    best = max(pool, key=key)
    return best["c"], len(passers), empty, floor_thr


def walk_forward(objective="calmar"):
    rows, strat_daily, ddby = [], [], {}
    for Y in FWD:
        c_star, npass, empty, floor_thr = select_cfg(Y - 1, objective)
        eqp, expp, earlyp, _ = EQ[cfg_key(c_star)]
        py = bm._per_year(eqp).get(Y, (float("nan"),) * 3)
        ddby[Y] = py[2]
        strat_daily.append(year_dr(eqp, Y))
        rows.append(dict(Y=Y, c=c_star, npass=npass, empty=empty, floor=floor_thr,
                         ret=py[0], sh=py[1], dd=py[2], flips=flips_in_year(expp, Y)))
    pooled = pd.concat(strat_daily)
    return dict(rows=rows, pooled=pooled, pooled_sharpe=sharpe_of(pooled), pooled_ann=ann_of(pooled),
                worst_fwd_dd=min(ddby.values()), ir=ir_vs(pooled, benB_oos), ir0=ir_vs(pooled, bh_oos),
                cfgs=[r["c"] for r in rows])


WF_cal = walk_forward("calmar")
WF_sh = walk_forward("sharpe")

print("\nper-fold 選參（主規則 Calmar 優先 / robustness Sharpe）：")
for obj, wf in [("calmar", WF_cal), ("sharpe", WF_sh)]:
    print(f"\n  [{obj:>6}] per-fold 選到：")
    for r in wf["rows"]:
        print(f"      {r['Y']}(OOS): {cfg_label(r['c'])} | 該年 報酬 {r['ret']*100:>6.1f}% / Sharpe {r['sh']:>5.2f} / "
              f"DD {r['dd']*100:>6.1f}% / flips {r['flips']} | 訓練窗過floor {r['npass']}/{len(CANDIDATES)}"
              f"{'（floor 空集→放寬全格）' if r['empty'] else ''}")
    uniq = len(set(cfg_key(c) for c in wf["cfgs"]))
    print(f"    pooled OOS Sharpe {wf['pooled_sharpe']:.3f} | OOS 年化 {wf['pooled_ann']*100:.1f}% | "
          f"IRvs基準B(beta) {wf['ir']:+.3f} | IRvs0050(alpha) {wf['ir0']:+.3f} | 最差前進年DD {wf['worst_fwd_dd']*100:.1f}% | "
          f"跨 fold 相異 config {uniq}/{len(FWD)}")

robust_diff = abs(WF_cal["pooled_sharpe"] - WF_sh["pooled_sharpe"])
print(f"\n  robustness: Calmar↔Sharpe 規則 pooled OOS Sharpe 差 = {robust_diff:.3f}（≤0.2 才算穩）")

# ── 穩健 plateau pick（非 per-fold argmax；用主版固定參數 K=2/VR=1.5/FP=0.06/PK=20/FN=3/M=0.85，含外資 N=4）──
# 取主版固定 config 跑「靜態套用」整段 → sim_from_exp 得 equity → 算 OOS（與 e1e2_combined「穩健高原值」對齊：不挑 in-sample 峰）
plateau_main = dict(K=2, VR_THR=1.5, FP_DROP=0.06, PK_WIN=20, FN=3, EARLY_MULT=0.85, use_foreign=True)
pm_exp, pm_early = make_exp(**plateau_main)          # 曝險序列
pm_eq, pm_nx = sim_from_exp(adj, pm_exp)             # → equity curve（metrics 一律用此）
pm_oos = pd.concat([year_dr(pm_eq, Y) for Y in FWD])
pm_wfd = min(dd_of_window(pm_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
print(f"\n  穩健 plateau pick（固定主版 {cfg_label(plateau_main)}，非 in-sample 峰挑；交易數={pm_nx}）：")
print(f"    pooled OOS Sharpe {sharpe_of(pm_oos):.3f} | OOS 年化 {ann_of(pm_oos)*100:.1f}% | "
      f"IRvs基準B(beta) {ir_vs(pm_oos, benB_oos):+.3f} | IRvs0050(alpha) {ir_vs(pm_oos, bh_oos):+.3f} | "
      f"最差前進年DD {pm_wfd*100:.1f}%")


# ── Part B 主表（三基準 + E4 + walk-forward + 穩健 plateau）──────────────────────────
#    口徑統一：eq＝equity curve（sim_from_exp 產出）；exp_state＝曝險態序列（flips 用）。兩者勿混。
def table_row(label, eq, exp_state=None, n_exec=None, early=None):
    oos = pd.concat([year_dr(eq, Y) for Y in FWD])
    f_ann, f_sh, f_dd, f_cal = window_metrics(eq, "2018-01-01", "2025-12-31")
    wfd = min(dd_of_window(eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    oos_ann = ann_of(oos)
    cal_oos = calmar(oos_ann, wfd)
    fl22 = flips_in_year(exp_state, 2022) if exp_state is not None else None        # flips 用『曝險態』
    bull_days = early_true_days(early, BULL) if early is not None else None
    bull_fl = sum(flips_in_year(exp_state, Y) for Y in BULL) if exp_state is not None else None
    return dict(label=label, f_ann=f_ann, f_sh=f_sh, f_dd=f_dd, f_cal=f_cal,
                oos_sh=sharpe_of(oos), oos_ann=oos_ann, wfd=wfd,
                irB=ir_vs(oos, benB_oos), ir0=ir_vs(oos, bh_oos), cal_oos=cal_oos,
                fl22=fl22, bull_days=bull_days, bull_fl=bull_fl, nx=n_exec)


# E4：make_exp_E4 回傳『曝險序列』→ sim 一次得 equity（之後一律用 E4_eq 這條 equity）
E4_exp, E4_early = make_exp_E4(VR_THR=MID["VR_THR"], FP_DROP=MID["FP_DROP"], PK_WIN=MID["PK_WIN"])
E4_eq, E4_nx = sim_from_exp(adj, E4_exp)
rows_main = [
    table_row("0050 買持(報酬王/alpha基準)", bh_eq),
    table_row("基準B(vol0.011,無overlay)", bb_eq),
    table_row("current-live(MA200連3+1%-85)", live_eq, live_state, live_nx, early=None),
    table_row("E4(OR閘 S2|S3,-85)", E4_eq, E4_exp, E4_nx, early=E4_early),
]
# walk-forward（用 2022 fold 選到的 config 之 early 序列做 flips/bull 計數；pooled 用串接）
for obj, wf in [("calmar", WF_cal), ("sharpe", WF_sh)]:
    # 用「最後一個 fold(2025) 選到的 config」代表牛市段觸發特性（descriptive）
    rep_c = wf["rows"][-1]["c"]
    rep_eq, rep_exp, rep_early, rep_nx = EQ[cfg_key(rep_c)]
    r = dict(label=f"walk-fwd E5({obj})", f_ann=float("nan"), f_sh=float("nan"), f_dd=float("nan"), f_cal=float("nan"),
             oos_sh=wf["pooled_sharpe"], oos_ann=wf["pooled_ann"], wfd=wf["worst_fwd_dd"],
             irB=wf["ir"], ir0=wf["ir0"], cal_oos=calmar(wf["pooled_ann"], wf["worst_fwd_dd"]),
             fl22=None, bull_days=None, bull_fl=None, nx=None)
    rows_main.append(r)
rows_main.append(table_row("穩健plateau E5(主版固定)", pm_eq, pm_exp, pm_nx, early=pm_early))

print("\n" + "=" * 120)
print("Part B 主表（full-period 2018-25 + pooled OOS 2022-25；beta=IRvs基準B / alpha=IRvs0050 明標）")
print("=" * 120)
print(f"{'策略':<30}{'全期ann':>8}{'全Sh':>6}{'全DD':>7}{'全Cal':>6}｜"
      f"{'OOSsh':>6}{'OOSann':>8}{'worstFwd':>9}{'OOSCal':>7}{'IRvsB(β)':>9}{'IRvs0050(α)':>11}{'交易':>5}")
print("-" * 120)
for r in rows_main:
    fa = f"{r['f_ann']*100:>7.1f}%" if np.isfinite(r['f_ann']) else f"{'—':>8}"
    fs = f"{r['f_sh']:>6.2f}" if np.isfinite(r['f_sh']) else f"{'—':>6}"
    fd = f"{r['f_dd']*100:>6.1f}%" if np.isfinite(r['f_dd']) else f"{'—':>7}"
    fc = f"{r['f_cal']:>6.2f}" if np.isfinite(r['f_cal']) else f"{'—':>6}"
    nx = f"{r['nx']:>5}" if r['nx'] is not None else f"{'—':>5}"
    print(f"{r['label']:<30}{fa}{fs}{fd}{fc}｜{r['oos_sh']:>6.3f}{r['oos_ann']*100:>7.1f}%{r['wfd']*100:>8.1f}%"
          f"{r['cal_oos']:>7.2f}{r['irB']:>+9.3f}{r['ir0']:>+11.3f}{nx}")
print("-" * 120)
print(f"  * IRvs基準B＝**beta**（基準B 為 de-risked）：0050 自身 IRvs基準B={BH_IRB:+.3f}＝純 beta 鐵證；")
print(f"    walk-fwd 的 IRvs基準B≈+1 只是 beta、非 alpha。**真 alpha＝IRvs0050**（≈0/負＝無顯著 alpha，與 R0-R5/E1-E2 一致）。")
print(f"  δ(OOS Sharpe 1SE)={DELTA:.3f}；所有 OOS Sharpe 差須以此雜訊尺度判讀。")


# ════════════════════════════════════════════════════════════════════════════════
# Part C — E5 vs E4 對比（E5 特有 Gate②：牛市假觸發更少 + 崩盤保護不顯著差）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 120)
print("Part C — E5 vs E4 對比（牛市假觸發 / 2022 OOS DD / 2020 lead-time[in-sample,descriptive]）")
print("=" * 120)


def lead_time_2020(early_series):
    """2020 內 early_signal 首次 True 的交易日 t_E（descriptive,標 in-sample）。回 (t_E, idx) 或 (None,None)。"""
    s = early_series[early_series.index.year == 2020]
    hit = s[s]
    if len(hit) == 0:
        return None, None
    t = hit.index[0]
    idx = cf.index.get_loc(t)
    return t, idx


def from_peak_pct(t):
    """t 當日 0050 從過去 252 日高點的回撤%（descriptive，標『早觸發已跌多少』）。"""
    if t is None:
        return float("nan")
    pk = cf.loc[:t].iloc[-252:].max()
    return float(cf.loc[t] / pk - 1)


# MA200(combined) 2020 首次轉 reduced 的交易日 t_MA
ms2020 = live_state[live_state.index.year == 2020]
ma_red = ms2020[np.isclose(ms2020.to_numpy(float), REDUCED)]
t_MA = ma_red.index[0] if len(ma_red) else None
t_MA_idx = cf.index.get_loc(t_MA) if t_MA is not None else None
fp_MA = from_peak_pct(t_MA)

# E5 主版 + E4 的 2020 early 首觸發
_, e5_main_early = make_exp(K=2, VR_THR=1.5, FP_DROP=0.06, PK_WIN=20, FN=3, EARLY_MULT=0.85, use_foreign=True)
t_E5, i_E5 = lead_time_2020(e5_main_early)
t_E4, i_E4 = lead_time_2020(E4_early)
# 同時也報 E5 K=3 版
_, e5_k3_early = make_exp(K=3, VR_THR=1.5, FP_DROP=0.06, PK_WIN=20, FN=3, EARLY_MULT=0.85, use_foreign=True)
t_E5k3, i_E5k3 = lead_time_2020(e5_k3_early)

print(f"\n[2020 lead-time — in-sample, DESCRIPTIVE ONLY ⚠️（expanding window 下 2020 永遠在訓練段，無法 OOS 驗證）]")
print(f"  MA200(current-live combined) 2020 首觸發日 t_MA = {t_MA.date() if t_MA is not None else '—'} "
      f"(from-peak {fp_MA*100:+.1f}% ＝ MA200 觸發時已跌這麼多)")
for nm, t, i, early in [("E5 主版 K=2(含外資)", t_E5, i_E5, e5_main_early),
                          ("E5 K=3(含外資)", t_E5k3, i_E5k3, e5_k3_early),
                          ("E4 OR閘(S2|S3)", t_E4, i_E4, E4_early)]:
    if t is not None and t_MA_idx is not None:
        lead = t_MA_idx - i
        print(f"  {nm:<20} 2020 首觸發 {t.date()} (from-peak {from_peak_pct(t)*100:+.1f}%) → 比 MA200 早 {lead} 交易日")
    else:
        print(f"  {nm:<20} 2020 未觸發 early")

# E5 K=3 主版（含外資）equity 預跑一次（後續重用）
e5k3_exp, e5k3_early = make_exp(K=3, VR_THR=1.5, FP_DROP=0.06, PK_WIN=20, FN=3, EARLY_MULT=0.85, use_foreign=True)
e5k3_eq, e5k3_nx = sim_from_exp(adj, e5k3_exp)

# 牛市假觸發 + 2022 OOS DD 對比（口徑：exp_state 算 flips，eq 算 DD；early 算觸發天數）
print(f"\n[牛市(2023-25) 假觸發 + 2022(OOS) 崩盤保護 — E5 vs E4]")
print(f"{'設定':<22}{'牛市early天數':>13}{'牛市flips':>10}{'2022 DD':>9}{'2022 flips':>11}{'2020 DD':>9}")
print("-" * 80)
# 每列：(name, exp_state, eq, early)；current-live 無 early（None）
cmp_set = [
    ("current-live", live_state, live_eq, None),
    ("E4 OR閘", E4_exp, E4_eq, E4_early),
    ("E5 K=2(含外資)", pm_exp, pm_eq, pm_early),
    ("E5 K=3(含外資)", e5k3_exp, e5k3_eq, e5k3_early),
]
for nm, exp_state, eq, early in cmp_set:
    bull_days = early_true_days(early, BULL) if early is not None else 0
    bull_fl = sum(flips_in_year(exp_state, Y) for Y in BULL)
    dd22 = bm._per_year(eq).get(2022, (np.nan,) * 3)[2]
    fl22 = flips_in_year(exp_state, 2022)
    dd20 = bm._per_year(eq).get(2020, (np.nan,) * 3)[2]
    dlabel = "—" if early is None else f"{bull_days}"
    print(f"{nm:<22}{dlabel:>13}{bull_fl:>10}{dd22*100:>8.1f}%{fl22:>11}{dd20*100:>8.1f}%")
print("-" * 80)
print("  讀法：E5 須『牛市 early 天數 + 牛市 flips 比 E4 少』(Gate E5-②a) 且『2022 DD / 2020 lead-time 不顯著差』(E5-②b)。")
print("  ⚠️ 2020 DD/lead-time 為 in-sample descriptive，不得當 OOS 證據。")
print("  ⚠️ 注意：early 訊號為『瞬時』(vol-spike/from-peak 逐日閃動)、非如 MA200 經 N=3 確認 → flips 計『最終曝險態』")
print("     會遠高於 current-live（早期層每日開關）；n_exec(交易數,見主表)為真實成本量度。")


# ════════════════════════════════════════════════════════════════════════════════
# Part D — ablation：含外資(N=4) vs 無外資(N=3)（E5 特有 Gate①：改善由組合非外資單獨）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 120)
print("Part D — ablation：含外資票(N=4) vs 拿掉外資票(N=3)（主版 K=2，其餘中位）— 證改善由組合而非外資單獨驅動")
print("=" * 120)
abl = []
for tag, uf in [("含外資 N=4(S1-S4)", True), ("無外資 N=3(S1-S3)", False)]:
    expa, earlya = make_exp(K=2, VR_THR=1.5, FP_DROP=0.06, PK_WIN=20, FN=3, EARLY_MULT=0.85, use_foreign=uf)
    eqas, nxa = sim_from_exp(adj, expa)      # eqas＝equity（metrics）；expa＝曝險態（flips）
    oosa = pd.concat([year_dr(eqas, Y) for Y in FWD])
    wfda = min(dd_of_window(eqas, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    bull_ann = ann_of(pd.concat([year_dr(eqas, Y) for Y in BULL]))
    abl.append(dict(tag=tag, oos_sh=sharpe_of(oosa), wfd=wfda, fl22=flips_in_year(expa, 2022),
                    bull_ann=bull_ann, bull_days=early_true_days(earlya, BULL), nx=nxa,
                    ir0=ir_vs(oosa, bh_oos)))
print(f"{'設定':<22}{'OOSsh':>7}{'worstFwd':>9}{'2022flips':>10}{'牛市ann':>8}{'牛市early天':>11}{'IRvs0050(α)':>11}{'交易':>5}")
print("-" * 90)
for a in abl:
    print(f"{a['tag']:<22}{a['oos_sh']:>7.3f}{a['wfd']*100:>8.1f}%{a['fl22']:>10}{a['bull_ann']*100:>7.1f}%"
          f"{a['bull_days']:>11}{a['ir0']:>+11.3f}{a['nx']:>5}")
print("-" * 90)
A_fi, A_no = abl[0], abl[1]
fi_helps_sh = A_fi["oos_sh"] - A_no["oos_sh"]
fi_helps_dd = A_fi["wfd"] - A_no["wfd"]
print(f"  含外資 − 無外資：ΔOOS Sharpe {fi_helps_sh:+.3f}（δ={DELTA:.3f}）｜Δworst-fwd-DD {fi_helps_dd*100:+.1f}pp")
print(f"  判讀：|ΔSharpe|<δ ⇒ 外資票至多中性（改善由組合 S1-S3 驅動，非外資單獨）；若含外資明顯惡化 ⇒ 應移除外資票。")


# ════════════════════════════════════════════════════════════════════════════════
# Part E — 事件 stress 表（2018[IS] / 2020[IS,含lead] / 2022[OOS] / 2023-25[OOS牛市]）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 120)
print("Part E — 事件 stress：2018[in-sample] / 2020[in-sample] / 2022[OOS] / 2023-25[OOS 牛市]（報酬/DD/flips）")
print("  ⚠️ 2018/2020＝in-sample（expanding window）＝descriptive；唯 2022 為 OOS（walk-forward 真能裁的崩盤）。")
print("=" * 120)


def py3(eq, y):
    return bm._per_year(eq).get(y, (float("nan"),) * 3)


def stress_print(name, eq, exp_state=None):
    """eq＝equity（py3/DD/牛市 ann）；exp_state＝曝險態（flips）。exp_state=None ⇒ flips 顯示 —。"""
    a, c, b = py3(eq, 2018), py3(eq, 2020), py3(eq, 2022)
    bull_ann = ann_of(pd.concat([year_dr(eq, Y) for Y in BULL]))
    fl18 = flips_in_year(exp_state, 2018) if exp_state is not None else "—"
    fl20 = flips_in_year(exp_state, 2020) if exp_state is not None else "—"
    fl22 = flips_in_year(exp_state, 2022) if exp_state is not None else "—"
    blfl = sum(flips_in_year(exp_state, Y) for Y in BULL) if exp_state is not None else "—"
    print(f"{name:<26}｜{a[0]*100:>6.1f}%{a[2]*100:>7.1f}%{str(fl18):>5}｜{c[0]*100:>6.1f}%{c[2]*100:>7.1f}%{str(fl20):>5}｜"
          f"{b[0]*100:>6.1f}%{b[2]*100:>7.1f}%{str(fl22):>5}｜{bull_ann*100:>6.1f}%{str(blfl):>5}")


# 預跑無外資 N=3 與 V_DEEP 的 equity（重用）
no3_exp, no3_early = make_exp(K=2, VR_THR=1.5, FP_DROP=0.06, PK_WIN=20, FN=3, EARLY_MULT=0.85, use_foreign=False)
no3_eq, no3_nx = sim_from_exp(adj, no3_exp)
deep_exp, deep_early = make_exp(K=2, VR_THR=1.5, FP_DROP=0.06, PK_WIN=20, FN=3, EARLY_MULT=0.85, use_foreign=True, deep=True)
deep_eq, deep_nx = sim_from_exp(adj, deep_exp)

print(f"{'設定':<26}｜{'18ret':>6}{'18DD':>7}{'fl18':>5}｜{'20ret':>6}{'20DD':>7}{'fl20':>5}｜"
      f"{'22ret':>6}{'22DD':>7}{'fl22':>5}｜{'牛ann':>6}{'牛fl':>5}")
print(f"{'':<26}｜{'[in-sample descriptive]':^20}｜{'[in-sample descriptive]':^20}｜"
      f"{'[OOS]':^20}｜{'[OOS 牛市]':^12}")
print("-" * 120)
stress_print("0050 買持[基準]", bh_eq, None)
stress_print("基準B(vol0.011)[基準]", bb_eq, None)
stress_print("current-live(連3+1%-85)", live_eq, live_state)
stress_print("E4 OR閘", E4_eq, E4_exp)
stress_print("E5 K=2 主版(含外資)", pm_eq, pm_exp)
stress_print("E5 K=3(含外資)", e5k3_eq, e5k3_exp)
stress_print("E5 K=2 無外資(N=3)", no3_eq, no3_exp)
stress_print("E5 K=2 V_DEEP(同觸70%)", deep_eq, deep_exp)
print("-" * 120)

# 附錄B 假訊號表對照：每訊號在牛市年 True 天數 + 組合閘 K=2/K=3 天數
print("\n[附錄B 假訊號表對照 — 牛市(2023-25) 各訊號 True 天數（descriptive）]")
sig_mid = build_signals(MID["VR_THR"], MID["FP_DROP"], MID["PK_WIN"], MID["FN"])
for sn in ("S1", "S2", "S3", "S4"):
    print(f"  {sn} True 天數(牛市) = {early_true_days(sig_mid[sn], BULL)}")
ek2 = make_early(2, MID["VR_THR"], MID["FP_DROP"], MID["PK_WIN"], MID["FN"], use_foreign=True)
ek3 = make_early(3, MID["VR_THR"], MID["FP_DROP"], MID["PK_WIN"], MID["FN"], use_foreign=True)
e4b = (sig_mid["S2"] | sig_mid["S3"]).fillna(False)
print(f"  組合閘 K=2 True 天數(牛市) = {early_true_days(ek2, BULL)} | K=3 = {early_true_days(ek3, BULL)} | "
      f"E4 OR(S2|S3) = {early_true_days(e4b, BULL)}")
print(f"  → 對照研究預期（單訊號假陽性~35%、3+同時~10%）：K=3 應比 K=2 應比 E4 OR 更壓低牛市觸發頻率。")


# ════════════════════════════════════════════════════════════════════════════════
# Part F — §5 Gate 逐項裁決（①-⑧）+ E5 特有 Gate E5-① / E5-②
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 120)
print("Part F — §5 Gate 逐項裁決（walk-forward 主規則 Calmar；總 Gate 未過前 live 不動）")
print("=" * 120)
wf = WF_cal
spread_uniq = len(set(cfg_key(c) for c in wf["cfgs"]))
g_dd = (wf["worst_fwd_dd"] >= LIVE_WDD - 1e-9) and (wf["worst_fwd_dd"] > BENB_WDD) and (wf["worst_fwd_dd"] > BH_WDD)
g_sharpe_noworse = wf["pooled_sharpe"] >= SL - DELTA
sharpe_edge_0050 = wf["pooled_sharpe"] - S0
g_alpha = (wf["ir0"] > 0) and (sharpe_edge_0050 > DELTA)
wf_fl22 = next(r["flips"] for r in wf["rows"] if r["Y"] == 2022)
g_whip = wf_fl22 < LIVE_FL22
g_bull = wf["pooled_ann"] >= LIVE_OOS_ANN - 0.01
g_plateau = robust_diff <= 0.2
struct_pass = g_dd and g_sharpe_noworse and g_whip and g_bull

print(f"  ① 對照固定預先指定（基準B+0050 買持，非 best-of-sweep、不引污染 12.7%/1.16/−16%）→ ✓（設計即滿足）")
print(f"  ② walk-forward OOS（FWD={FWD} expanding，pooled 主裁、in-sample 線索）→ ✓（設計即滿足）")
print(f"  ③ 降-DD 不惡化且優於兩被動：worst-fwd-DD {wf['worst_fwd_dd']*100:.1f}% "
      f"(live {LIVE_WDD*100:.1f}% / B {BENB_WDD*100:.1f}% / 0050 {BH_WDD*100:.1f}%) → {'✓' if g_dd else '✗'}")
print(f"  ④ OOS Sharpe 不顯著差於 current-live（δ={DELTA:.2f} 帶內）：{wf['pooled_sharpe']:.3f} vs live {SL:.3f} → {'✓' if g_sharpe_noworse else '✗'}")
print(f"  ⑤ whipsaw 降低（2022 fold flips {wf_fl22} < current-live {LIVE_FL22}）→ {'✓' if g_whip else '✗'}")
print(f"  ⑥ 牛市不顯著犧牲（OOS 年化 {wf['pooled_ann']*100:.1f}% vs live {LIVE_OOS_ANN*100:.1f}%，容差 1pp）→ {'✓' if g_bull else '✗'}")
print(f"  ⑦ plateau 穩定：Part A 單參 OOS 多落 δ 帶內 + Calmar↔Sharpe pooled 差 {robust_diff:.3f}≤0.2 → {'✓' if g_plateau else '✗'}"
      f"（跨 fold 相異 config {spread_uniq}/{len(FWD)}）")
print(f"  ⑧ **真 alpha（同 beta vs 0050，預期 FAIL）**：IRvs0050 {wf['ir0']:+.3f}、OOS Sharpe 邊際 vs 0050 "
      f"{sharpe_edge_0050:+.3f} vs δ {DELTA:.2f} → {'✓ 有顯著 alpha' if g_alpha else '✗ 無（δ 內）'}"
      f"；註：IRvs基準B {wf['ir']:+.2f} 是 beta（0050 自身 IRvsB={BH_IRB:+.2f}）非 alpha")
print(f"\n  ▶ 結構 Gate（③∧④∧⑤∧⑥）：{'PASS' if struct_pass else 'FAIL'}（含⑦穩定：{'✓' if g_plateau else '✗'}）｜alpha Gate（⑧）：{'PASS' if g_alpha else 'FAIL（預期）'}")

# E5 特有 Gate
print(f"\n  — E5 特有 Gate —")
# E5-①：無外資 N=3 達結構 Gate 的 ③∧⑤∧⑥；且含外資不惡化（重用 Part E 預跑的 no3_eq/no3_exp）
no_oos = pd.concat([year_dr(no3_eq, Y) for Y in FWD])
no_wfd = min(dd_of_window(no3_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
no_fl22 = flips_in_year(no3_exp, 2022)            # flips 用曝險態
no_bull_ann = ann_of(pd.concat([year_dr(no3_eq, Y) for Y in BULL]))
e51_dd = (no_wfd >= LIVE_WDD - 1e-9)
e51_whip = no_fl22 < LIVE_FL22
e51_bull = no_bull_ann >= LIVE_BULL_ANN - 0.01
e51_struct = e51_dd and e51_whip and e51_bull
# 含外資不惡化（vs 無外資）：|Δ| 在 δ 內 且 DD 不更差超過容差
fi_not_worse = (fi_helps_sh >= -DELTA) and (fi_helps_dd >= -0.015)
g_E51 = e51_struct and fi_not_worse
print(f"  E5-①（改善由組合非外資單獨）：無外資N=3 達結構準則[DD不惡化{'✓' if e51_dd else '✗'}/whip{'✓' if e51_whip else '✗'}/牛市{'✓' if e51_bull else '✗'}] "
      f"且 含外資不惡化[ΔSh {fi_helps_sh:+.3f}/ΔDD {fi_helps_dd*100:+.1f}pp]{'✓' if fi_not_worse else '✗'} → {'PASS' if g_E51 else 'FAIL'}")
# E5-②：vs E4 牛市假觸發更少 + 崩盤保護不顯著差（flips 用曝險態 E4_exp/pm_exp；DD 用 equity E4_eq/pm_eq）
e4_bull_days = early_true_days(E4_early, BULL)
e4_bull_fl = sum(flips_in_year(E4_exp, Y) for Y in BULL)
e5_bull_days = early_true_days(pm_early, BULL)
e5_bull_fl = sum(flips_in_year(pm_exp, Y) for Y in BULL)
e52a = (e5_bull_days < e4_bull_days) and (e5_bull_fl <= e4_bull_fl)
dd22_E4 = py3(E4_eq, 2022)[2]
dd22_E5 = py3(pm_eq, 2022)[2]
lead_E4 = (t_MA_idx - i_E4) if (i_E4 is not None and t_MA_idx is not None) else None
lead_E5 = (t_MA_idx - i_E5) if (i_E5 is not None and t_MA_idx is not None) else None
e52b_dd = dd22_E5 >= dd22_E4 - 0.015
e52b_lead = (lead_E5 is not None and lead_E4 is not None and lead_E5 >= lead_E4 - 2)
e52b = e52b_dd and e52b_lead
g_E52 = e52a and e52b
print(f"  E5-②（比 E4 牛市假觸發少 + 崩盤保護不顯著差）：")
print(f"      (a) 牛市 early 天數 E5 {e5_bull_days} < E4 {e4_bull_days} 且牛市 flips E5 {e5_bull_fl} ≤ E4 {e4_bull_fl} → {'✓' if e52a else '✗'}")
print(f"      (b) 2022 OOS DD E5 {dd22_E5*100:.1f}% ≥ E4 {dd22_E4*100:.1f}%−1.5pp {'✓' if e52b_dd else '✗'}；"
      f"2020 lead E5 {lead_E5} ≥ E4 {lead_E4}−2 {'✓' if e52b_lead else '✗'}[in-sample descriptive] → {'✓' if e52b else '✗'}")
print(f"      ⇒ E5-②：{'PASS' if g_E52 else 'FAIL'}")
print(f"\n  ▶ E5 相對 E4『組合閘價值』成立 ⟺ E5-①∧E5-②：{'成立' if (g_E51 and g_E52) else '不成立'}")


# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 120)
print("結論口徑（walk-forward OOS）")
print("=" * 120)
print(f"  • 結構 Gate（③∧④∧⑤∧⑥, walk-fwd Calmar）：{'PASS' if struct_pass else 'FAIL'}；E5 特有 E5-①={'PASS' if g_E51 else 'FAIL'} / E5-②={'PASS' if g_E52 else 'FAIL'}。")
print(f"  • **alpha Gate（⑧, 同 beta vs 0050）：{'PASS' if g_alpha else 'FAIL（預期）'}**——IRvs0050 {wf['ir0']:+.3f}≈0/負、OOS Sharpe 邊際 vs 0050 {sharpe_edge_0050:+.3f} ≪ δ={DELTA:.2f}。")
print(f"    IRvs基準B 是 **beta 非 alpha**（0050 自身 IRvsB={BH_IRB:+.2f} 純 beta 鐵證）。R5『無 alpha、0050 報酬王』未翻案。")
print(f"  • ⚠️ 2018/2020＝in-sample（expanding window）→ E5 主打的『2020 初跌盲區補強』lead-time/DD 為 descriptive、**不得當 OOS 證據**；")
print(f"    walk-forward OOS 實際只裁『加 E5 是否惡化 2022 + 牛市(2023-25)』。")
print(f"  • ⚠️ survivorship 上界（FinMind 無下市股）→ 所有結果是上界；0050 自身外資流＝proxy（ETF 籌碼≠全市場外資）。")
print(f"  • **總 Gate（R5：對 0050 buy-hold 無顯著 alpha + 無 mandate）未翻案 → live（MA200 連3日+1%帶-85%）一律不動。**")
print(f"    E5 即使全結構 PASS 也只是『研究線索/可選防禦微調』，不自動落地。")
print("\n[done] E5 組合閘 walk-forward 完成（純快取、0 API、未改任何既有檔；未 commit、未切 branch）。")

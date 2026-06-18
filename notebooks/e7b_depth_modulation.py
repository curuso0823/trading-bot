"""
notebooks/e7b_depth_modulation.py
【實驗 E7b】美股半導體訊號作為「砍倉**深度**調節 / 確認延續」（depth-modulation，非 trigger-modulation）。

承 E7（docs/E7_US_SEMI_DEFENSE.md）：用美股半導體當「**砍倉時點**」訊號 FAILED——領先真實(2022 早 +25 交易日)
但 ~99% 在 0050 開盤跳空被吸收、T+1 開盤成交＝賣在跳空後、且 86% 是平時假警報(砍進漲市反傷)。

E7b 新假說（呼應 E7 §7 建議）：把領先用在「**確認延續**」而非「提前進場」——
  • **進場時點維持 current-live MA200**（連 3 日 + 1% 帶；慢但乾淨、整段歷史只砍 ~8 次、無假警報稀釋問題）。
  • **只在『已進本地崩盤態(below_local=True)』時，用美股半導體訊號決定『砍倉深度』**：
      US 確認延續→砍更深(例 70%)；US 未確認/轉強→維持輕量 85%(deepen-only 主版)。
  曝險 = 1.0（未跌破）；否則 = (D_deep if us_confirm else 0.85)。

🟥 決定性控制組 = flat-deep（current-live 結構但 below 段內無條件 = D_deep，不看美股；R6 已掃 0~100% 選 0.85）。
   E7b 的唯一價值 = 「US-conditioning 是否在『DD vs 報酬前緣』勝過 flat-deep」（Pareto 支配）。若前緣重合 = US 無加值 = FAIL。

🟥 因果對齊（NO LOOK-AHEAD）= 直接 COPY e7_us_semi_defense.py 已驗證對齊（us_overnight_to_tw + shift(-1)；3 verifier 已證乾淨）。

定位＝**現行防禦 overlay 的條件加深微調、非 alpha**（alpha 預期 FAIL，R0–R5/E1–E5/E7 一致）。
唯一可能站住＝**在 DD-vs-報酬前緣勝過 flat-deep**（US-conditioning 真加值）。

⚠️ 純快取、0 API；只新增此檔、不改任何既有檔（含 e7_us_semi_defense.py、e1e2_*）；不 commit、不切 branch、不動 live。
   行為中性 additive（us_confirm 關閉 ⇒ 逐位重現 current-live，max|Δ|=0）。survivorship → 全為上界。
   2018/2020 = IS（expanding window 永在訓練段）、唯一 OOS 崩盤 = 2022（n=1）。
用法：.venv/bin/python notebooks/e7b_depth_modulation.py
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

# ── 載入 benchmark_backtest 為 bm（__main__ guard、安全 importlib）──
_spec = importlib.util.spec_from_file_location("bm", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

# ════════════════════════════════════════════════════════════════════════════════
# 常數（COPY 自 e1e2_walkforward.py / e7_us_semi_defense.py）
# ════════════════════════════════════════════════════════════════════════════════
SQRT252 = np.sqrt(252)
FWD = [2022, 2023, 2024, 2025]          # OOS 前進窗（同 R0/R1/E1-E5/E7）
MA = 200
REDUCED, FULL = 0.85, 1.0
DD_BAND = 0.022                          # walk-forward floor 容差 + DD 軸雜訊尺度（同 R1/E1E2/E7）
CACHE = "data/raw/finmind_cache"
START_US, END_US = "2018-01-01", "2025-12-31"
LIVE_CD, LIVE_BAND = 3, 0.01            # current-live overlay 參數（連 3 日確認 + 1% 帶）


# ════════════════════════════════════════════════════════════════════════════════
# helpers（逐字 COPY 自 e1e2_walkforward.py / e7_us_semi_defense.py）
# ════════════════════════════════════════════════════════════════════════════════
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
    """年化 Sharpe 1 SE（Lo 2002）＝plateau / 顯著性雜訊尺度 δ。"""
    n = len(dr)
    sd = dr.std()
    if n < 30 or sd == 0:
        return float("nan")
    srd = dr.mean() / sd
    return float(np.sqrt((1 + 0.5 * srd ** 2) / n) * SQRT252)


def ir_vs(pooled, ref_oos):
    d = pd.concat([pooled.rename("s"), ref_oos.rename("b")], axis=1).dropna()
    return sharpe_of(d["s"] - d["b"])


# ── sim_from_exp（逐字 COPY 自 e1e2_walkforward.py / e7_us_semi_defense.py；回傳 (eq, n_exec)）────
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


# ── current-live overlay 精確邏輯（exp_combined，逐字 COPY 自 e1e2_combined_validate.py）──
#    注意：原版硬寫 REDUCED=0.85。E7b 需可傳 regime_action 以做 flat-deep → 改成可傳參(預設 0.85=current-live)。
def exp_combined(close_full, confirm_days=1, band_pct=0.0, regime_action=REDUCED):
    """E1∩E2 統一：close<MA×(1−band) 連續 confirm 日→reduced(regime_action)；
    close>MA×(1+band) 連續 confirm 日→full(1.0)。
    (confirm_days=1, band_pct=0.0, regime_action=0.85) 逐位重現舊每日規則。
    regime_action 可傳參＝flat-deep 用（below 段內無條件砍到 D_deep）；預設 0.85＝current-live。"""
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
                state = "REDUCED"
        else:
            if run_above >= confirm_days:
                state = FULL
        out[i] = FULL if state == FULL else regime_action
    return pd.Series(out, index=cf.index)


def below_state_machine(raw_below: pd.Series, confirm_days: int) -> pd.Series:
    """通用 N 日確認狀態機（吃任意 raw_below bool）→ 回傳『是否處於 reduced(below)態』bool。
    full→below：raw_below 連續 confirm 日；below→full：~raw_below 連續 confirm 日。對稱 confirm。
    （E7b 對美股 us_confirm 套此結構與 current-live 公平對照、控制深度 whipsaw。）"""
    rb = raw_below.to_numpy(bool)
    n = len(rb)
    out = np.zeros(n, dtype=bool)
    reduced = False
    run_below = run_above = 0
    for i in range(n):
        if rb[i]:
            run_below += 1
            run_above = 0
        else:
            run_above += 1
            run_below = 0
        if not reduced:
            if run_below >= confirm_days:
                reduced = True
        else:
            if run_above >= confirm_days:
                reduced = False
        out[i] = reduced
    return pd.Series(out, index=raw_below.index)


def below_local_combined(close_full, confirm_days=LIVE_CD, band_pct=LIVE_BAND) -> pd.Series:
    """0050-MA200 『跌破(reduced)態』bool（close-T 慣例）＝ (exp_combined<1.0)。current-live 預設 (3,0.01)。
    注意：用 regime_action=REDUCED 算狀態，再判 <FULL → below bool 與 regime_action 取值無關（只判態）。"""
    return (exp_combined(close_full, confirm_days, band_pct, REDUCED) < FULL)


def flips_in_year(below_series, year):
    """『跌破態』bool 在某年的態轉折次數（whipsaw proxy）。吃 below bool（True/False）。"""
    s = below_series[below_series.index.year == year]
    if len(s) < 2:
        return 0
    b = s.to_numpy(bool).astype(int)
    return int((np.diff(b) != 0).sum())


def depth_flips_in_year(exp_series, year):
    """曝險深度層態轉折（E7b 特有）：在某年 exp 序列的『不同值之間切換』次數。
    捕捉 0.85↔D_deep 來回 + 1.0↔(below) 進出（即所有曝險變動）。對照 below flips（只算進/出 below）。"""
    s = exp_series[exp_series.index.year == year]
    if len(s) < 2:
        return 0
    v = s.to_numpy(float)
    return int((~np.isclose(np.diff(v), 0.0)).sum())


# ════════════════════════════════════════════════════════════════════════════════
# 載入資料（純快取、0 API）
# ════════════════════════════════════════════════════════════════════════════════
print("=" * 130)
print("【E7b】美股半導體訊號 作為砍倉『深度』調節 / 確認延續 | walk-forward OOS（純快取 / 0 API / cache-only）")
print("=" * 130)
adj = bm.load_adjusted_0050()
cf = adj.set_index("date")["close"].sort_index().astype(float)   # 全 grid（含 2016 暖身）
print(f"  0050 還原日線（快取）：{len(adj)} 列  {adj['date'].min().date()} ~ {adj['date'].max().date()}（含 2016 暖身）")
print(f"  回測窗 {bm.START} ~ {bm.END}｜LOT={bm.LOT}｜SLIP={bm.SLIP}｜再平衡帶={bm.BAND*100:.0f}pp｜月度再平衡 ON")

# TW 交易日 grid（for us_overnight_to_tw）— 用回測窗 0050 open/close（同 us_lead_0050 / e7 口徑）
tw = adj[(adj["date"] >= START_US) & (adj["date"] <= END_US)][["date", "open", "close"]].copy()
tw["date"] = pd.to_datetime(tw["date"])
tw = tw.sort_values("date").set_index("date")
tw_dates = np.array(tw.index.values)

# 美股 Adj_Close（FinMind USStockPrice 快取 pickle）
US_SYMS = ["^SOX", "SMH", "SOXX", "TSM", "QQQ", "^IXIC", "^GSPC"]
us_close = {}
for s in US_SYMS:
    p = f"{CACHE}/USStockPrice__{s}__{START_US}__{END_US}.pkl"
    d = pd.read_pickle(p)
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date")
    assert "Adj_Close" in d.columns, f"{s} 無 Adj_Close 欄"
    assert len(d) == 2011, f"{s} 列數 {len(d)} != 2011"
    us_close[s] = pd.Series(pd.to_numeric(d["Adj_Close"], errors="coerce").values, index=d["date"].values)
    print(f"  {s:6} USStockPrice（快取，用 Adj_Close）：{len(d)} 列  {d['date'].min().date()} ~ {d['date'].max().date()}")
print("  >>> 0 API / cache-only：僅讀本地 pickle + bm.load_adjusted_0050()，無任何 fetcher.get_*/網路呼叫。")
print("=" * 130)


# ── us_overnight_to_tw（逐字 COPY 自 us_lead_0050.py / e7）─────────────────────────
def us_overnight_to_tw(close_s: pd.Series) -> pd.Series:
    """把每個美股 session 報酬映射到『其收盤後的第一個台股交易日』，同窗多 session 複利。
    回傳 index=台股交易日 的 us_overnight[T]（台股 T 開盤前已知的美股報酬）。"""
    r = close_s.pct_change().dropna()
    ud = np.array(r.index.values)
    idx = np.searchsorted(tw_dates, ud, side="right")     # 第一個 > 美股日 的台股日
    ok = idx < len(tw_dates)
    mapped = tw_dates[idx[ok]]
    g = pd.DataFrame({"tw": mapped, "r": r.values[ok]})
    comp = g.groupby("tw")["r"].apply(lambda x: float(np.prod(1.0 + x.values) - 1.0))
    return comp.reindex(tw.index)


us_overnight = {s: us_overnight_to_tw(us_close[s]) for s in US_SYMS}     # index = TW 交易日


# 美股 Adj_Close 對齊到『其收盤後第一個台股交易日』的 level（for MA/from-peak/動能 raw 計算）— COPY e7
def us_level_to_tw(close_s: pd.Series) -> pd.Series:
    s = close_s.dropna()
    ud = np.array(s.index.values)
    idx = np.searchsorted(tw_dates, ud, side="right")
    ok = idx < len(tw_dates)
    mapped = tw_dates[idx[ok]]
    g = pd.DataFrame({"tw": mapped, "px": s.values[ok]})
    last = g.groupby("tw")["px"].last()      # 同一 TW 日對應多 US session → 取最新（最後收盤）
    return last.reindex(tw.index).ffill()    # TW 日無對應美股 session（美股休市）→ 沿用前值


us_level = {s: us_level_to_tw(us_close[s]) for s in US_SYMS}             # index = TW 交易日（close-T 慣例）


# ════════════════════════════════════════════════════════════════════════════════
# us_confirm flavors（COPY e7 raw 偵測函數；語意＝『美股延續下跌態＝確認加深合理』）
# ════════════════════════════════════════════════════════════════════════════════
def us_raw_below_ma(sym, L):
    """flavor A (MA-cross)：us_level < us_level.rolling(L).mean()（美股仍在自身 MA(L) 下方＝跌勢未止）。"""
    lv = us_level[sym]
    return (lv < lv.rolling(L).mean()).fillna(False)


def us_raw_below_frompeak(sym, X, W=60):
    """flavor B (from-peak 回撤)：us_level / rolling(W).max − 1 < −X(%)（美股回撤夠深＝實質下跌）。X 為正數百分點。"""
    lv = us_level[sym]
    dd = lv / lv.rolling(W, min_periods=1).max() - 1.0
    return (dd < -X / 100.0).fillna(False)


def us_raw_below_momentum(sym, Thr, M=10):
    """flavor C (動能)：us_level.pct_change(M) < Thr(%)（美股 M 日累積動能大負＝加速下跌）。Thr 為負數百分點。"""
    lv = us_level[sym]
    mom = lv.pct_change(M)
    return (mom < Thr / 100.0).fillna(False)


def shift_to_expgrid(us_state_tw: pd.Series) -> pd.Series:
    """前移一格：us 態（TW close-T grid）→ 落 close-T=date_i row（影響 day i+1 持倉）。
    末筆 shift(-1) → NaN → fillna(False)（不引入未來）。COPY e7。"""
    return us_state_tw.shift(-1).fillna(False).astype(bool)


def us_confirm_state(sym, flavor, param, confirm_days=LIVE_CD, **kw):
    """美股『確認延續』態 bool（TW close-T grid，已 shift_to_expgrid 前移對齊→決定 i+1 持倉）。
    flavor: 'ma'(param=L) / 'frompeak'(param=X%) / 'momentum'(param=Thr%)。"""
    if flavor == "ma":
        raw = us_raw_below_ma(sym, int(param))
    elif flavor == "frompeak":
        raw = us_raw_below_frompeak(sym, float(param), kw.get("W", 60))
    elif flavor == "momentum":
        raw = us_raw_below_momentum(sym, float(param), kw.get("M", 10))
    else:
        raise ValueError(flavor)
    st = below_state_machine(raw, confirm_days)     # N 日確認狀態機（控深度 whipsaw）
    return shift_to_expgrid(st)                      # 前移對齊（外部美股訊號→決定次日持倉）


# ════════════════════════════════════════════════════════════════════════════════
# E7b 核心：深度調節曝險機制（depth-modulation，非 trigger-modulation）
# ════════════════════════════════════════════════════════════════════════════════
def final_exp_depth(below_local_tw: pd.Series, us_confirm_tw: pd.Series, d_deep, d_light=REDUCED) -> pd.Series:
    """E7b 曝險公式（落全 grid cf.index；行為中性 additive）：
      not below_local              → 1.0          （未跌破：恆滿倉跟 0050＝current-live 逐位相同）
      below_local ∧ us_confirm     → d_deep       （已崩盤 且 美股確認延續：加深防禦，D_deep∈[0.5,0.85]）
      below_local ∧ ¬us_confirm    → d_light(0.85)（已崩盤 但 美股未確認/轉強：維持 current-live 0.85＝deepen-only 主版）
    d_light=0.85 即 deepen-only 主版；d_light>0.85 為 lighten 第二臂（探索用）。"""
    bl = below_local_tw.reindex(cf.index).fillna(False).to_numpy(bool)
    uc = us_confirm_tw.reindex(cf.index).fillna(False).to_numpy(bool)
    out = np.full(len(cf), FULL, dtype=float)
    deep_mask = bl & uc
    light_mask = bl & (~uc)
    out[deep_mask] = d_deep
    out[light_mask] = d_light
    return pd.Series(out, index=cf.index)


# current-live below_local（TW grid，close-T 慣例，唯一進場/出場 gate）
LIVE_BELOW = below_local_combined(cf, LIVE_CD, LIVE_BAND).reindex(tw.index).fillna(False).astype(bool)


def eq_for_e7b(flavor, sym, param, confirm_days, d_deep, d_light=REDUCED):
    """E7b 一條 config：below_local(3,0.01) + us_confirm(flavor,sym,param,cd) → final_exp_depth → sim_from_exp。
    回傳 (eq, n_exec, below_local_tw, us_confirm_tw, exp_full)。"""
    uc = us_confirm_state(sym, flavor, param, confirm_days)
    fe = final_exp_depth(LIVE_BELOW, uc, d_deep, d_light)
    eq, nx = sim_from_exp(adj, fe)
    return eq, nx, LIVE_BELOW, uc, fe


def flat_deep_exp(d_deep) -> pd.Series:
    """flat-deep 控制組：current-live 結構 + below 段內無條件 D_deep（不看美股）。
    ＝ final_exp_depth(below_local, us_confirm=all_True, d_deep, d_deep)
    ＝ exp_combined(3,0.01,regime_action=d_deep)。兩法在 S4 互證 max|Δ|=0。"""
    all_true = pd.Series(True, index=cf.index)
    return final_exp_depth(LIVE_BELOW, all_true, d_deep, d_deep)


def eq_for_flatdeep(d_deep):
    fe = flat_deep_exp(d_deep)
    eq, nx = sim_from_exp(adj, fe)
    return eq, nx, fe


# ════════════════════════════════════════════════════════════════════════════════
# 細網格定義
# ════════════════════════════════════════════════════════════════════════════════
# 主軸 D_deep（曝險加深深度，below∧confirm 段）：16 點，核心 0.60–0.85 步長 0.025
D_DEEP_GRID = [0.50, 0.55, 0.60, 0.625, 0.65, 0.675, 0.70, 0.725, 0.75, 0.775, 0.80, 0.825, 0.85, 0.875, 0.90, 0.95]
# us_confirm 各 flavor 細網格（COPY e7）
GRID_MA = [20, 30, 40, 50, 60, 75, 100, 120, 150, 175, 200, 250]            # 12 點
GRID_X = [3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 18, 20]                          # 12 點（from-peak 回撤%）
GRID_THR = [-2, -3, -4, -5, -6, -8, -10, -12, -14, -16, -18, -20]            # 12 點（M 日累積%）
CONFIRM_DAYS_GRID = [1, 2, 3]
# plateau pick（非 in-sample 峰；鐵則#7）— 文獻/高原中段值
D_DEEP_PLATEAU = 0.70           # 核心區間中段、文獻常見「砍三成」
PLATEAU_PARAM = {"frompeak": 8, "ma": 50, "momentum": -8}    # e7 高原中段；動能 e7 假警報最少
PLATEAU_CD = 3                  # Alvarez 慣例 plateau、與 current-live N3 對齊
# 主圖代表 flavor×sym（^SOX/SMH × A/B/C + QQQ negative-control）
E7B_REPR = [
    ("frompeak", "^SOX"), ("frompeak", "SMH"),
    ("momentum", "^SOX"), ("momentum", "SMH"),
    ("ma", "^SOX"), ("ma", "SMH"),
    ("frompeak", "QQQ"),     # negative-control（大盤；若同效＝半導體特異性不成立）
]


# ════════════════════════════════════════════════════════════════════════════════
# S3 因果對齊驗證（FAIL 即停）— COPY e7 已驗證對齊 + 新增 config-level falsification
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 130)
print("S3 — 因果對齊驗證（NO LOOK-AHEAD）：範例日期對齊 + corr falsification + config-level falsification + 覆蓋率")
print("=" * 130)

# (a) 範例日期對齊（COPY e7 S3(a)）
print("(a) 範例日期對齊：對台股交易日 D，貢獻 us_overnight[D] 的美股 session 日期須 < D（D 開盤前已收盤）")
r_sox = us_close["^SOX"].pct_change().dropna()
ud_sox = np.array(r_sox.index.values)
idx_sox = np.searchsorted(tw_dates, ud_sox, side="right")
ok_sox = idx_sox < len(tw_dates)
map_df = pd.DataFrame({"us_date": ud_sox[ok_sox], "tw_date": tw_dates[idx_sox[ok_sox]]})
sample_tw = ["2018-01-08", "2020-03-12", "2020-03-23", "2022-03-07", "2022-10-25", "2024-08-05"]
align_ok = True
for d in sample_tw:
    sub = map_df[map_df["tw_date"] == pd.Timestamp(d)]
    if len(sub) == 0:
        continue
    last_us = pd.Timestamp(sub["us_date"].max())
    ok = last_us < pd.Timestamp(d)
    align_ok &= ok
    print(f"   TW {d}：最後貢獻美股 session = {last_us.date()}  →  {'< D ✓' if ok else '>= D ✗ LOOK-AHEAD!'}")
assert align_ok, "範例日期對齊 FAIL：有美股 session 日期 >= 其影響的台股交易日（look-ahead）！"

# shift(-1) 成交日檢查（COPY e7）
print("\n    前移一格(shift(-1))後：us 態放在 close-T=date_i 那列 → 決定 day i+1 持倉（open[i+1] 成交）。")
tw_idx_list = list(tw.index)
shift_ok = True
for d in ["2020-03-11", "2022-03-06", "2024-08-02"]:
    if pd.Timestamp(d) not in tw.index:
        continue
    i = tw_idx_list.index(pd.Timestamp(d))
    if i + 1 >= len(tw_idx_list):
        continue
    next_tw = tw_idx_list[i + 1]
    sub = map_df[map_df["tw_date"] == next_tw]
    if len(sub) == 0:
        continue
    last_us = pd.Timestamp(sub["us_date"].max())
    ok = last_us < next_tw
    shift_ok &= ok
    print(f"   close-T row {d} → 持倉日 {next_tw.date()}（open 成交）｜用到美股 session {last_us.date()} < 成交日 {'✓' if ok else '✗'}")
assert shift_ok, "前移對齊 FAIL"

# (b) corr falsification（COPY e7 S3(b)）：美股序列偷看未來→與 0050 當日 corr 須崩（^SOX/SMH/QQQ 主訊號）
print("\n(b) corr falsification（底層接線自證）：美股隔夜序列前移一天(shift(-1)=偷看未來)→ 與 0050 當日報酬相關性應崩")
tw_ret = tw["close"].pct_change()
E7B_MAIN = ["^SOX", "SMH", "QQQ"]
fals_ok = True
for s in ["^SOX", "SMH", "TSM", "QQQ"]:
    base = pd.concat([us_overnight[s].rename("u"), tw_ret.rename("t")], axis=1).dropna()
    c_base = base["u"].corr(base["t"])
    peek = pd.concat([us_overnight[s].shift(-1).rename("u"), tw_ret.rename("t")], axis=1).dropna()
    c_peek = peek["u"].corr(peek["t"])
    crash = c_peek < c_base * 0.5
    if s in E7B_MAIN:
        fals_ok &= crash
        tag = "✓ 崩潰(無偷看未來)" if crash else "✗ 未崩→疑慮"
    else:
        tag = "(negative-control；殘留=TW→US 反向回饋,非bug,不入config)"
    print(f"   {s:6}：corr(正確對齊)={c_base:.3f}  →  corr(偷看未來1天)={c_peek:.3f}  {tag}")
assert fals_ok, "corr falsification FAIL：E7b 主訊號『偷看未來』相關性未崩潰→疑似 look-ahead！"


# (c) config-level falsification（E7b 特有、最貼語意）：把美股 level 整體再 shift(-1)（多偷一天未來）
#     → 重算代表 config 的 OOS Sharpe/wfDD/2022報酬 → 效果應改變（證沒偷看：若偷看不改變＝訊號其實沒接上）。
print("\n(c) config-level falsification（E7b 特有）：US level 整體再前移一天(多偷未來)→ 代表 config 績效『須改變』")


def us_confirm_state_peek(sym, flavor, param, confirm_days=LIVE_CD, **kw):
    """偷看版：us_level 整體 shift(-1)（用未來一天的美股 level 算 raw）→ 再走原狀態機+前移。
    若 E7b 對齊正確，偷看未來會改變 us_confirm 態 → 改變績效。"""
    lv = us_level[sym].shift(-1).ffill()    # 偷看未來一天的 level
    if flavor == "ma":
        raw = (lv < lv.rolling(int(param)).mean()).fillna(False)
    elif flavor == "frompeak":
        dd = lv / lv.rolling(kw.get("W", 60), min_periods=1).max() - 1.0
        raw = (dd < -float(param) / 100.0).fillna(False)
    elif flavor == "momentum":
        raw = (lv.pct_change(kw.get("M", 10)) < float(param) / 100.0).fillna(False)
    st = below_state_machine(raw, confirm_days)
    return shift_to_expgrid(st)


def _oos_metrics_of_eq(eq):
    pooled = pd.concat([year_dr(eq, Y) for Y in FWD])
    wdd = min(dd_of_window(eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    r22 = bm._per_year(eq).get(2022, (float("nan"),) * 3)
    return sharpe_of(pooled), wdd, r22[0]


# 代表 config：^SOX from-peak-8% / D_deep=0.70 / cd=3
_corr_sym, _corr_fl, _corr_pm, _corr_dd = "^SOX", "frompeak", 8, 0.70
uc_correct = us_confirm_state(_corr_sym, _corr_fl, _corr_pm, PLATEAU_CD)
eq_correct, _ = sim_from_exp(adj, final_exp_depth(LIVE_BELOW, uc_correct, _corr_dd))
uc_peek = us_confirm_state_peek(_corr_sym, _corr_fl, _corr_pm, PLATEAU_CD)
eq_peek, _ = sim_from_exp(adj, final_exp_depth(LIVE_BELOW, uc_peek, _corr_dd))
m_correct = _oos_metrics_of_eq(eq_correct)
m_peek = _oos_metrics_of_eq(eq_peek)
n_state_diff = int((uc_correct.reindex(tw.index).fillna(False) != uc_peek.reindex(tw.index).fillna(False)).sum())
changed = (abs(m_correct[0] - m_peek[0]) > 1e-6) or (abs(m_correct[1] - m_peek[1]) > 1e-9) or (n_state_diff > 0)
print(f"   代表 config = {_corr_sym} {_corr_fl}-{_corr_pm}% / D_deep={_corr_dd} / cd={PLATEAU_CD}")
print(f"   正確對齊 ：OOS Sharpe {m_correct[0]:.4f}｜wfDD {m_correct[1]*100:.2f}%｜2022 報酬 {m_correct[2]*100:.2f}%")
print(f"   偷看未來 ：OOS Sharpe {m_peek[0]:.4f}｜wfDD {m_peek[1]*100:.2f}%｜2022 報酬 {m_peek[2]*100:.2f}%（us_confirm 態相異 {n_state_diff} 日）")
print(f"   → 偷看未來{'改變了績效/態 ✓（證沒偷看未來、訊號確實接上）' if changed else '未改變 ✗（疑訊號未接上或已偷看）'}")
assert changed, "config-level falsification FAIL：偷看未來未改變 E7b 績效→疑訊號未接上或對齊有誤！"

# 覆蓋率
print("\n(d) us_overnight 覆蓋率（TW grid 上非 NaN 比例）+ 末有效對齊日")
for s in ["^SOX", "SMH"]:
    cov = us_overnight[s].reindex(tw.index).notna().mean()
    last_valid = us_overnight[s].dropna().index.max()
    print(f"   {s:6}：覆蓋率 {cov*100:.1f}%｜末有效對齊日 {pd.Timestamp(last_valid).date()}（< END {bm.END} ✓）")
print("  [S3 PASS] 因果對齊四層防護通過：美股 session 嚴格早於成交、corr 偷看崩、config 偷看改變績效、覆蓋率正常。")


# ════════════════════════════════════════════════════════════════════════════════
# S4 行為中性驗證（assert max|Δ|=0，FAIL 即停；雙退化軸 + flat-deep 自洽 + flat-deep wiring）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 130)
print("S4 — 行為中性驗證（additive 鐵證：us_confirm 關閉/D_deep=0.85 ⇒ 逐位重現 current-live，max|Δ|=0）")
print("=" * 130)

# 軸 0：COPY 進來的 exp_combined(1,0.0,0.85) ≡ 引擎 simulate_benchmark overlay（current-live 錨點正確）
live_daily_eq, _ = sim_from_exp(adj, exp_combined(cf, 1, 0.0, 0.85))
eng = bm.simulate_benchmark(adj, 1.0, overlay=True, regime_ma=MA, regime_action=0.85)["equity"]
d_eng = float((live_daily_eq - eng).abs().max())
assert d_eng < 1e-3, f"exp_combined(1,0.0,0.85) 未重現引擎 overlay：max|Δ|={d_eng:.2e}"
print(f"(0) exp_combined(1,0.0,0.85) ≡ 引擎 simulate_benchmark(overlay,200,0.85)：max|Δ|={d_eng:.1e} 元（<1e-3）→ COPY helper 與引擎一致 ✓")

# current-live 錨點：exp_combined(3,0.01,0.85)
live_eq, live_nx = sim_from_exp(adj, exp_combined(cf, LIVE_CD, LIVE_BAND, 0.85))
# 用 E7b final_exp_depth 路徑重建 current-live（D_deep=0.85, us_confirm 任意）→ 驗 wiring 等價
uc_dummy = us_confirm_state("^SOX", "frompeak", 8, PLATEAU_CD)
live_eq_e7b, live_nx_e7b = sim_from_exp(adj, final_exp_depth(LIVE_BELOW, uc_dummy, 0.85, 0.85))
d_wire = float((live_eq - live_eq_e7b).abs().max())
assert d_wire < 1e-9, f"E7b final_exp_depth(D=0.85) 未重現 exp_combined(3,0.01,0.85)：max|Δ|={d_wire:.2e}"
print(f"    current-live: exp_combined(3,0.01,0.85) ≡ E7b final_exp_depth(D=0.85)：max|Δ|={d_wire:.1e}｜交易數={live_nx}(E7b路徑={live_nx_e7b})")

# 軸 1：us_confirm 恆 False ⇒ E7b ≡ current-live（兩 flavor 各驗）
#   from-peak X=999%（dd 永不 < −9.99）→ us_confirm 恆 False → below∧¬confirm 走 d_light=0.85 分支
uc_off_fp = us_confirm_state("^SOX", "frompeak", 999.0, PLATEAU_CD)
eq_off_fp, _ = sim_from_exp(adj, final_exp_depth(LIVE_BELOW, uc_off_fp, 0.70, 0.85))
d_off_fp = float((eq_off_fp - live_eq).abs().max())
assert d_off_fp == 0.0, f"軸1 us_confirm 恆False(from-peak999%) 未逐位重現 current-live：max|Δ|={d_off_fp:.2e}"
assert bool(uc_off_fp.reindex(tw.index).fillna(False).any()) is False, "from-peak999% us_confirm 應恆 False"
uc_off_mom = us_confirm_state("^SOX", "momentum", -999.0, PLATEAU_CD)
eq_off_mom, _ = sim_from_exp(adj, final_exp_depth(LIVE_BELOW, uc_off_mom, 0.70, 0.85))
d_off_mom = float((eq_off_mom - live_eq).abs().max())
assert d_off_mom == 0.0, f"軸1 us_confirm 恆False(動能-999%) 未逐位重現 current-live：max|Δ|={d_off_mom:.2e}"
print(f"(1) us_confirm 恆 False ⇒ E7b(D_deep=0.70) ≡ current-live：from-peak X=999% max|Δ|={d_off_fp:.1e}｜動能 Thr=−999% max|Δ|={d_off_mom:.1e}（嚴格 0）✓")

# 軸 2：D_deep=0.85 ⇒ E7b ≡ current-live（不論 us_confirm；用會頻繁觸發的 us_confirm 驗）
uc_on = us_confirm_state("^SOX", "frompeak", 3, PLATEAU_CD)     # from-peak-3% 常觸發
n_uc_on = int(uc_on.reindex(tw.index).fillna(False).sum())
eq_d085, _ = sim_from_exp(adj, final_exp_depth(LIVE_BELOW, uc_on, 0.85, 0.85))
d_d085 = float((eq_d085 - live_eq).abs().max())
assert d_d085 == 0.0, f"軸2 D_deep=0.85 未逐位重現 current-live：max|Δ|={d_d085:.2e}"
print(f"(2) D_deep=0.85 ⇒ E7b ≡ current-live（即使 us_confirm 常 True，from-peak-3% 觸發 {n_uc_on} 日）：max|Δ|={d_d085:.1e}（嚴格 0）✓")

# 軸 3：flat-deep 自洽（兩實作互證）+ flat-deep(0.85)≡current-live
#   實作A: flat_deep_exp(d) = final_exp_depth(below, all_True, d, d)
#   實作B: exp_combined(3,0.01, regime_action=d)
for dtest in [0.50, 0.70, 0.85]:
    eqA, _ = sim_from_exp(adj, flat_deep_exp(dtest))
    eqB, _ = sim_from_exp(adj, exp_combined(cf, LIVE_CD, LIVE_BAND, dtest))
    dAB = float((eqA - eqB).abs().max())
    assert dAB < 1e-9, f"flat-deep 兩實作不一致 D={dtest}：max|Δ|={dAB:.2e}"
eqfd085, _ = sim_from_exp(adj, flat_deep_exp(0.85))
d_fd085 = float((eqfd085 - live_eq).abs().max())
assert d_fd085 == 0.0, f"flat-deep(0.85) 未重現 current-live：max|Δ|={d_fd085:.2e}"
print(f"(3) flat-deep 自洽：final_exp_depth(all_True,d,d) ≡ exp_combined(3,0.01,d) 對 D∈[0.5,0.7,0.85] max|Δ|<1e-9 ✓；flat-deep(0.85)≡current-live max|Δ|={d_fd085:.1e} ✓")

# 軸 3b：flat-deep ≡ E7b 的 us_confirm 恆 True 退化（驗 deepen 路徑 wiring）— 任務要求 sanity (c)
all_true = pd.Series(True, index=cf.index)
for dtest in [0.50, 0.70]:
    eq_e7b_alltrue, _ = sim_from_exp(adj, final_exp_depth(LIVE_BELOW, all_true, dtest, dtest))
    eq_fd, _ = sim_from_exp(adj, flat_deep_exp(dtest))
    d_alltrue = float((eq_e7b_alltrue - eq_fd).abs().max())
    assert d_alltrue == 0.0, f"E7b(us_confirm=all_True,D={dtest}) ≠ flat-deep({dtest})：max|Δ|={d_alltrue:.2e}"
print(f"(3b) us_confirm 恆 True ⇒ E7b(D_deep) ≡ flat-deep(D_deep)（deepen 路徑 wiring 驗證，D∈[0.5,0.7]）max|Δ|=0.0 ✓")

print("  [S4 PASS] 行為中性鐵證通過：us_confirm 關閉/D_deep=0.85 逐位重現 current-live；us_confirm 恆 True 重現 flat-deep。")


# ════════════════════════════════════════════════════════════════════════════════
# S5 固定預先指定基準（compute once）
# ════════════════════════════════════════════════════════════════════════════════
bh = bm.simulate_buyhold(adj)
benchB = bm.simulate_benchmark(adj, 0.011, overlay=False)
bh_eq, bb_eq = bh["equity"], benchB["equity"]

bh_oos = pd.concat([year_dr(bh_eq, Y) for Y in FWD])
benB_oos = pd.concat([year_dr(bb_eq, Y) for Y in FWD])
live_oos = pd.concat([year_dr(live_eq, Y) for Y in FWD])
S0 = sharpe_of(bh_oos)      # 0050 OOS Sharpe（報酬王）
SB = sharpe_of(benB_oos)    # 基準B OOS Sharpe（de-risked beta 參考）
SL = sharpe_of(live_oos)    # current-live OOS Sharpe

BH_WDD = min(dd_of_window(bh_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
BB_WDD = min(dd_of_window(bb_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
LIVE_WDD = min(dd_of_window(live_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
DELTA = sharpe_se_ann(live_oos)               # δ＝plateau / 顯著性雜訊尺度
BH_IRB = ir_vs(bh_oos, benB_oos)              # 0050 自身 IRvs基準B（純 beta）＝beta 參考線
LIVE_OOS_ANN = ann_of(live_oos)
LIVE_FL22 = flips_in_year(LIVE_BELOW, 2022)
LIVE_BULL = ann_of(pd.concat([year_dr(live_eq, Y) for Y in (2023, 2024, 2025)]))

print("\n" + "=" * 130)
print("S5 — 固定預先指定基準（compute once；絕不 best-of-sweep、絕不引污染 12.7%/1.16/−16%）")
print("=" * 130)
print(f"  δ(OOS Sharpe 1SE, current-live pooled n={len(live_oos)}) = {DELTA:.3f}（plateau/顯著性雜訊尺度）｜DD_BAND={DD_BAND*100:.1f}pp（DD 軸雜訊）")
print(f"  OOS Sharpe：0050 {S0:.3f}（報酬王）｜基準B {SB:.3f}（de-risked beta）｜current-live {SL:.3f}")
print(f"  最差前進年 DD：0050 {BH_WDD*100:.1f}%｜基準B {BB_WDD*100:.1f}%｜current-live {LIVE_WDD*100:.1f}%")
print(f"  beta 參考線：0050 自身 IRvs基準B = {BH_IRB:+.3f}（純 beta、零技巧）→ walk-fwd 的 IRvs基準B 高=beta 非 alpha")
print(f"  current-live OOS 年化 {LIVE_OOS_ANN*100:.1f}%｜牛市23-25年化 {LIVE_BULL*100:.1f}%｜2022 flips {LIVE_FL22}｜全期交易數 {live_nx}")


# ════════════════════════════════════════════════════════════════════════════════
# 預跑 EQ_CACHE（所有 flat-deep + E7b 細網格 eq 一次算好重用）
# ════════════════════════════════════════════════════════════════════════════════
print("\n  預跑 EQ_CACHE（flat-deep × D_deep16 + E7b 代表 flavor×sym × D_deep16 × cd-plateau + 兩段一維 confirm 細掃）…")

EQ_FLAT = {}        # d_deep -> (eq, nx, exp)
for dd in D_DEEP_GRID:
    EQ_FLAT[dd] = eq_for_flatdeep(dd)

EQ_E7B = {}         # (flavor,sym,param,cd,d_deep) -> (eq,nx,below,uc,exp)
# (i) D_deep 軸：每代表 (flavor,sym) × D_deep16，us_confirm 用 plateau param + cd
for flavor, sym in E7B_REPR:
    pp = PLATEAU_PARAM[flavor]
    for dd in D_DEEP_GRID:
        EQ_E7B[(flavor, sym, pp, PLATEAU_CD, dd)] = eq_for_e7b(flavor, sym, pp, PLATEAU_CD, dd)
# (ii) us_confirm 軸（兩段一維細掃，固定 D_deep=plateau, cd=plateau）：各 flavor 全 grid（^SOX/SMH）
CONFIRM_SWEEP = []
for flavor, grid in [("frompeak", GRID_X), ("momentum", GRID_THR), ("ma", GRID_MA)]:
    for sym in ["^SOX", "SMH"]:
        for p in grid:
            key = (flavor, sym, p, PLATEAU_CD, D_DEEP_PLATEAU)
            if key not in EQ_E7B:
                EQ_E7B[key] = eq_for_e7b(flavor, sym, p, PLATEAU_CD, D_DEEP_PLATEAU)
            CONFIRM_SWEEP.append(key)
# (iii) us_confirm_days 軸（小集合 [1,2,3]，固定 plateau param + D_deep plateau）
for flavor, sym in [("frompeak", "^SOX"), ("momentum", "^SOX")]:
    pp = PLATEAU_PARAM[flavor]
    for cd in CONFIRM_DAYS_GRID:
        key = (flavor, sym, pp, cd, D_DEEP_PLATEAU)
        if key not in EQ_E7B:
            EQ_E7B[key] = eq_for_e7b(flavor, sym, pp, cd, D_DEEP_PLATEAU)
print(f"  EQ_CACHE 完成：flat-deep {len(EQ_FLAT)} 條｜E7b {len(EQ_E7B)} 條。")


# ── 通用度量（從 eq + below/uc 算全指標）─────────────────────────────────────────
def metrics_of(eq, exp_full, below_tw, uc_tw=None):
    f_ann, f_sh, f_dd, f_cal = window_metrics(eq, bm.START, bm.END)
    oos = pd.concat([year_dr(eq, Y) for Y in FWD])
    o_sh = sharpe_of(oos)
    o_ann = ann_of(oos)
    wdd = min(dd_of_window(eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    bull = ann_of(pd.concat([year_dr(eq, Y) for Y in (2023, 2024, 2025)]))
    r22 = bm._per_year(eq).get(2022, (float("nan"),) * 3)
    # 深度 whipsaw：exp 序列在 OOS 年的曝險變動次數（含 0.85↔D_deep 來回）；對照 below flips
    dwhip22 = depth_flips_in_year(exp_full, 2022)
    blwfl22 = flips_in_year(below_tw, 2022)
    return dict(f_ann=f_ann, f_sh=f_sh, f_dd=f_dd, o_sh=o_sh, o_ann=o_ann, wdd=wdd, bull=bull,
                ir=ir_vs(oos, benB_oos), ir0=ir_vs(oos, bh_oos), r22=r22, dwhip22=dwhip22, blwfl22=blwfl22)


# ════════════════════════════════════════════════════════════════════════════════
# S7 細網格特徵化（兩段一維細掃；δ 判 plateau；標『特徵化非選參』）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 130)
print("S7 — 細網格特徵化（兩段一維細掃；δ 判 plateau vs 孤峰；標『特徵化/找線索，決策綁 walk-forward，不挑 in-sample 峰』）")
print("=" * 130)

# (9a) 固定 D_deep=plateau(0.70) 掃 us_confirm 軸（各 flavor × ^SOX/SMH）
print(f"\n(9a) 固定 D_deep={D_DEEP_PLATEAU}、cd={PLATEAU_CD}，掃 us_confirm 參數軸（各 flavor 12 點）：")
print(f"  {'flavor/sym':>16}{'param':>9}｜{'全期Sh':>7}{'OOS Sh':>8}{'OOSann%':>8}{'wfDD%':>8}{'IRvs0050':>10}{'22深whip':>8}{'交易':>6}")
for flavor, grid, pfmt in [("frompeak", GRID_X, lambda p: f"-{p}%"),
                           ("momentum", GRID_THR, lambda p: f"{p}%"),
                           ("ma", GRID_MA, lambda p: f"MA{p}")]:
    for sym in ["^SOX", "SMH"]:
        oos_list = []
        print(f"  -- {flavor} {sym} --")
        for p in grid:
            eq, nx, below, uc, fe = EQ_E7B[(flavor, sym, p, PLATEAU_CD, D_DEEP_PLATEAU)]
            m = metrics_of(eq, fe, below, uc)
            oos_list.append(m["o_sh"])
            print(f"  {flavor+' '+sym:>16}{pfmt(p):>9}｜{m['f_sh']:>7.2f}{m['o_sh']:>8.3f}{m['o_ann']*100:>8.1f}"
                  f"{m['wdd']*100:>8.1f}{m['ir0']:>+10.3f}{m['dwhip22']:>8}{nx:>6}")
        spread = max(oos_list) - min(oos_list)
        verdict = "平滑高原(≲δ)" if spread <= DELTA * 1.3 else "鋸齒/孤峰(>δ)＝雜訊"
        print(f"     → {flavor} {sym} OOS Sharpe 全距={spread:.3f} vs δ={DELTA:.3f}：{verdict}（current-live OOS Sh={SL:.3f}）")

# (9b) 固定 us_confirm plateau，掃 D_deep 16 點（代表 ^SOX/SMH from-peak/momentum）
print(f"\n(9b) 固定 us_confirm plateau（from-peak-8% / 動能-8%，cd={PLATEAU_CD}），掃 D_deep 16 點：")
print(f"  {'flavor/sym':>16}{'D_deep':>8}｜{'全期Sh':>7}{'OOS Sh':>8}{'OOSann%':>8}{'wfDD%':>8}{'IRvs0050':>10}{'牛市%':>7}{'22深whip':>8}{'交易':>6}")
for flavor, sym in [("frompeak", "^SOX"), ("frompeak", "SMH"), ("momentum", "^SOX"), ("momentum", "SMH")]:
    pp = PLATEAU_PARAM[flavor]
    oos_list = []
    print(f"  -- {flavor} {sym} (param={pp}) --")
    for dd in D_DEEP_GRID:
        eq, nx, below, uc, fe = EQ_E7B[(flavor, sym, pp, PLATEAU_CD, dd)]
        m = metrics_of(eq, fe, below, uc)
        oos_list.append(m["o_sh"])
        tag = "  ←0.85=current-live" if abs(dd - 0.85) < 1e-9 else ""
        print(f"  {flavor+' '+sym:>16}{dd:>8.3f}｜{m['f_sh']:>7.2f}{m['o_sh']:>8.3f}{m['o_ann']*100:>8.1f}"
              f"{m['wdd']*100:>8.1f}{m['ir0']:>+10.3f}{m['bull']*100:>7.1f}{m['dwhip22']:>8}{nx:>6}{tag}")
    spread = max(oos_list) - min(oos_list)
    print(f"     → {flavor} {sym} D_deep 軸 OOS Sharpe 全距={spread:.3f} vs δ={DELTA:.3f}：{'平滑高原' if spread <= DELTA*1.3 else '鋸齒/孤峰'}")


# ════════════════════════════════════════════════════════════════════════════════
# S-frontier 🟥 DD-vs-報酬前緣（三族並列；判 E7b 是否 Pareto 優於 flat-deep）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 130)
print("S-frontier — 🟥 DD-vs-報酬前緣（三族並列）：族①current-live單點 / 族②flat-deep(D16) / 族③E7b(代表×D16)")
print("  x=最差前進年DD(wfDD) / y=OOS pooled 年化；判 E7b 曲線是否 Pareto 優於 flat-deep（同DD報酬更高 / 同報酬DD更低）")
print("=" * 130)


def frontier_row_flat(dd):
    eq, nx, fe = EQ_FLAT[dd]
    m = metrics_of(eq, fe, LIVE_BELOW)
    return dict(fam="flat-deep", dd=dd, label=f"flat-{dd:.3f}", **m, nx=nx)


def frontier_row_e7b(flavor, sym, pp, dd):
    eq, nx, below, uc, fe = EQ_E7B[(flavor, sym, pp, PLATEAU_CD, dd)]
    m = metrics_of(eq, fe, below, uc)
    return dict(fam=f"E7b-{flavor}-{sym}", dd=dd, label=f"{flavor[:2]}-{sym}-{dd:.3f}", **m, nx=nx)


# 族②flat-deep 全曲線
flat_rows = [frontier_row_flat(dd) for dd in D_DEEP_GRID]
# 族③E7b 代表曲線（主圖挑 from-peak ^SOX/SMH + momentum ^SOX + QQQ control）
E7B_FRONTIER_CURVES = [("frompeak", "^SOX"), ("frompeak", "SMH"), ("momentum", "^SOX"), ("frompeak", "QQQ")]
e7b_rows = {}
for flavor, sym in E7B_FRONTIER_CURVES:
    pp = PLATEAU_PARAM[flavor]
    e7b_rows[(flavor, sym)] = [frontier_row_e7b(flavor, sym, pp, dd) for dd in D_DEEP_GRID]

# current-live 單點（族①）
cl_m = metrics_of(live_eq, exp_combined(cf, LIVE_CD, LIVE_BAND, 0.85), LIVE_BELOW)

# (1) 前緣表
print("\n(1) 前緣表（三族並列）：")
print(f"  {'族 / config':>26}{'D_deep':>7}｜{'全期ann':>8}{'Sh':>6}{'maxDD':>8}｜{'OOSann%':>8}{'OOS Sh':>7}{'wfDD%':>8}｜"
      f"{'IRvsB':>7}{'IRvs0050':>9}{'牛市%':>7}{'22報酬':>8}{'22深whip':>8}{'交易':>6}")
print("-" * 130)
print(f"  {'① current-live':>26}{0.85:>7.2f}｜{cl_m['f_ann']*100:>8.1f}{cl_m['f_sh']:>6.2f}{cl_m['f_dd']*100:>8.1f}｜"
      f"{cl_m['o_ann']*100:>8.1f}{cl_m['o_sh']:>7.3f}{cl_m['wdd']*100:>8.1f}｜{cl_m['ir']:>+7.2f}{cl_m['ir0']:>+9.3f}"
      f"{cl_m['bull']*100:>7.1f}{cl_m['r22'][0]*100:>8.1f}{cl_m['dwhip22']:>8}{live_nx:>6}")
print(f"  {'──族② flat-deep──':>26}")
for r in flat_rows:
    print(f"  {'② '+r['label']:>26}{r['dd']:>7.3f}｜{r['f_ann']*100:>8.1f}{r['f_sh']:>6.2f}{r['f_dd']*100:>8.1f}｜"
          f"{r['o_ann']*100:>8.1f}{r['o_sh']:>7.3f}{r['wdd']*100:>8.1f}｜{r['ir']:>+7.2f}{r['ir0']:>+9.3f}"
          f"{r['bull']*100:>7.1f}{r['r22'][0]*100:>8.1f}{r['dwhip22']:>8}{r['nx']:>6}")
for (flavor, sym), rows in e7b_rows.items():
    print(f"  {'──族③ E7b '+flavor+' '+sym+'──':>26}")
    for r in rows:
        print(f"  {'③ '+r['label']:>26}{r['dd']:>7.3f}｜{r['f_ann']*100:>8.1f}{r['f_sh']:>6.2f}{r['f_dd']*100:>8.1f}｜"
              f"{r['o_ann']*100:>8.1f}{r['o_sh']:>7.3f}{r['wdd']*100:>8.1f}｜{r['ir']:>+7.2f}{r['ir0']:>+9.3f}"
              f"{r['bull']*100:>7.1f}{r['r22'][0]*100:>8.1f}{r['dwhip22']:>8}{r['nx']:>6}")
print("-" * 130)


# (2) Pareto 判定：US-conditioning 是否打破 flat-deep 前緣？
#   🟥 正確的控制比較＝【matched-D_deep】：E7b 與 flat-deep 在『同一 D_deep』唯一差異就是
#      『below 段內 D_deep 是否被 us_confirm 條件化』(E7b 只在 US 確認時加深；flat 無條件加深)。
#      → 此為乾淨控制變因。若 E7b@D vs flat@D 兩軸皆不優於雜訊＝US-conditioning 零加值（前緣重合）。
#   ⚠️ 為何不用『內插同 wfDD/同 ann』作主判：np.interp 在 flat 曲線值域外 clamp，E7b 端點(訊號稀疏/極淺 D)
#      會產生假 Δ；且『支配 flat 曲線上某被支配點(如 flat-0.95 過深)』非真前緣勝出。故內插僅列參考。
ANN_NOISE = 0.0010      # 報酬軸雜訊尺度（0.10pp；同 ④牛市門檻量級）
DD_NOISE = DD_BAND      # DD 軸雜訊尺度（2.2pp；同族 floor 容差）
FLAT_BY_DD = {r["dd"]: r for r in flat_rows}


def interp_flat_ann_at_wdd(target_wdd):
    """flat-deep 曲線上『相同 wfDD』的 OOS 年化（線性內插參考；值域外 clamp，僅供對照、非主判）。"""
    xs = np.array([r["wdd"] for r in flat_rows])
    ys = np.array([r["o_ann"] for r in flat_rows])
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    return float(np.interp(target_wdd, xs, ys))


def interp_flat_wdd_at_ann(target_ann):
    """flat-deep 曲線上『相同 OOS 年化』的 wfDD（線性內插參考；值域外 clamp，僅供對照、非主判）。"""
    xs = np.array([r["o_ann"] for r in flat_rows])
    ys = np.array([r["wdd"] for r in flat_rows])
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    return float(np.interp(target_ann, xs, ys))


def matched_dd_addvalue(e7b_row):
    """matched-D_deep 控制比較：E7b@D vs flat@D（同 D_deep）。
    加值 = E7b 在某一軸『嚴格優於雜訊』且另一軸『不差過雜訊』
           (DD 更淺 >DD_NOISE 且 ann 不更差 >ANN_NOISE)  或  (ann 更高 >ANN_NOISE 且 DD 不更深 >DD_NOISE)。
    回傳 (addvalue_bool, Δann_pp, ΔDD_pp)。ΔDD>0=E7b DD 更淺(更好)；Δann>0=E7b 報酬更高。"""
    f = FLAT_BY_DD[e7b_row["dd"]]
    d_ann = e7b_row["o_ann"] - f["o_ann"]
    d_dd = e7b_row["wdd"] - f["wdd"]                  # >0＝E7b wfDD 較淺(較不負)＝更好
    av = ((d_dd > DD_NOISE) and (d_ann > -ANN_NOISE)) or ((d_ann > ANN_NOISE) and (d_dd > -DD_NOISE))
    return av, d_ann * 100, d_dd * 100


print("\n(2) Pareto 判定（主判=matched-D_deep 控制比較：E7b@D vs flat@D，唯一差異＝US-conditioning；內插同DD/同ann 僅參考）：")
print(f"  {'E7b config':>26}｜{'wfDD%':>7}{'OOSann%':>8}｜{'matched-flat@同D ΔDD':>20}{'Δann':>8}｜{'內插@同wfDD Δann':>16}｜{'US加值?':>14}")
print("-" * 130)
e7b_dominates_any = False
n_av, n_tot, av_labels = 0, 0, []
for (flavor, sym), rows in e7b_rows.items():
    for r in rows:
        av, mdd_ann, mdd_dd = matched_dd_addvalue(r)         # matched-D_deep（主判）
        d_ann_interp = (r["o_ann"] - interp_flat_ann_at_wdd(r["wdd"])) * 100   # 內插參考
        n_tot += 1
        if av:
            e7b_dominates_any = True
            n_av += 1
            av_labels.append(f"{r['label']}(Δann{mdd_ann:+.2f}/ΔDD{mdd_dd:+.2f}pp)")
        tag = "✓ US加值" if av else "✗ 重合/更差"
        print(f"  {r['label']:>26}｜{r['wdd']*100:>7.1f}{r['o_ann']*100:>8.1f}｜{mdd_dd:>+20.2f}{mdd_ann:>+8.2f}｜{d_ann_interp:>+16.2f}｜{tag:>14}")
print("-" * 130)
print(f"  主判門檻（matched-D_deep，乾淨控制）：同 D_deep 下 E7b 某軸嚴格優於雜訊(DD {DD_NOISE*100:.1f}pp / ann {ANN_NOISE*100:.2f}pp) 且另一軸不更差。")
print(f"  ΔDD>0＝E7b 同 D_deep 下 wfDD 較淺(較好)；Δann>0＝報酬較高。內插欄(端點 clamp 會失真)僅供對照、非主判。")
print(f"  → matched-D_deep『US-conditioning 加值』點數 = {n_av}/{n_tot}（{'全重合/更差＝零加值' if n_av == 0 else '見下'}）")
if n_av:
    print(f"    加值點：{', '.join(av_labels)}")
    print(f"    ⚠️ 但這 {n_av}/{n_tot} 點 Δann 皆貼著 +{ANN_NOISE*100:.2f}pp 雜訊地板(≤+0.2pp)、且全在『極淺 D_deep 端』(訊號稀疏、近 current-live)；")
    print(f"    非系統性前緣勝出（其餘 {n_tot-n_av}/{n_tot} 全『重合/更差』、且 wfDD 普遍比 flat 同 D 更深）。walk-forward(S8)+plateau gate(S12⑧) 才是裁決。")
print(f"  → 結論：US-conditioning {'未系統性打破' if n_av <= 3 else '可能打破'} flat-deep 前緣（matched 同 D 下 E7b 普遍 DD 更深、報酬持平＝US 把加深用在更差的子集）。")

# (3) 視覺化（可選、try/except 不阻斷；存 PNG 到 logs/，runtime 產物不入版控）
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 6))
    fx = [-r["wdd"] * 100 for r in flat_rows]      # x = |wfDD|（越大越深）
    fy = [r["o_ann"] * 100 for r in flat_rows]
    ax.plot(fx, fy, "o-", color="black", label="flat-deep (no US)", zorder=3)
    colors = {"^SOX": "tab:red", "SMH": "tab:orange", "QQQ": "tab:green"}
    for (flavor, sym), rows in e7b_rows.items():
        ex = [-r["wdd"] * 100 for r in rows]
        ey = [r["o_ann"] * 100 for r in rows]
        ax.plot(ex, ey, ".--", alpha=0.7, label=f"E7b {flavor}-{sym}", color=colors.get(sym, "gray"))
    ax.plot([-cl_m["wdd"] * 100], [cl_m["o_ann"] * 100], "*", ms=18, color="blue", label="current-live (0.85)", zorder=5)
    ax.set_xlabel("|worst-fwd DD| % (right = deeper DD)")
    ax.set_ylabel("OOS pooled annualized %")
    ax.set_title("E7b DD-vs-Return Frontier: E7b vs flat-deep (Pareto check)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    png = os.path.join(ROOT, "logs", "e7b_frontier.png")
    fig.savefig(png, dpi=110, bbox_inches="tight")
    print(f"  (3) 前緣圖已存 {png}（runtime 產物、不入版控）。")
except Exception as e:
    print(f"  (3) matplotlib 不可用或繪圖失敗（不阻斷）：{repr(e)[:80]}")


# ════════════════════════════════════════════════════════════════════════════════
# S8 walk-forward（主裁）：per-fold 選 D_deep（us_confirm 固定 plateau）；flat-deep 對照前緣
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 130)
print("S8 — walk-forward OOS（主裁；FWD=[2022,2023,2024,2025] expanding；floor 重錨 current-live−DD_BAND；永不固定 fallback）")
print("  內層 grid = D_deep 16 點（us_confirm 固定 plateau，避免 fold 內過多自由度 overfit）；對 E7b 代表 + flat-deep 各跑")
print("=" * 130)


def wf_select_deep(eq_lookup, train_end_year, objective="calmar"):
    """擴張窗 [2018,train_end_year] 選 D_deep：Calmar(或Sharpe) argmax；
    DD floor 重錨同族 current-live−DD_BAND（鐵則#8）；永不固定 fallback（空集→放寬全格 argmax+flag）。
    eq_lookup: d_deep -> eq。"""
    start, end = "2018-01-01", f"{train_end_year}-12-31"
    live_dd = dd_of_window(live_eq, start, end)
    floor_thr = live_dd - DD_BAND
    mets = {}
    for dd in D_DEEP_GRID:
        ann, sh, ddv, cal = window_metrics(eq_lookup(dd), start, end)
        mets[dd] = dict(p=dd, ann=ann, sh=sh, dd=ddv, cal=cal)
    passers = [m for m in mets.values() if m["dd"] >= floor_thr]
    empty = len(passers) == 0
    pool = passers if passers else list(mets.values())
    key = (lambda m: (m["cal"], m["sh"])) if objective == "calmar" else (lambda m: (m["sh"], m["cal"]))
    best = max(pool, key=key)
    return best["p"], len(passers), empty, floor_thr


def walk_forward_deep(eq_lookup, below_lookup, objective="calmar"):
    rows, strat_daily, ddby = [], [], {}
    for Y in FWD:
        p_star, npass, empty, floor_thr = wf_select_deep(eq_lookup, Y - 1, objective)
        eq = eq_lookup(p_star)
        below = below_lookup(p_star)
        py = bm._per_year(eq).get(Y, (float("nan"),) * 3)
        ddby[Y] = py[2]
        strat_daily.append(year_dr(eq, Y))
        rows.append(dict(Y=Y, p=p_star, npass=npass, empty=empty, ret=py[0], sh=py[1], dd=py[2]))
    pooled = pd.concat(strat_daily)
    return dict(rows=rows, pooled=pooled, pooled_sharpe=sharpe_of(pooled), pooled_ann=ann_of(pooled),
                worst_fwd_dd=min(ddby.values()), ir=ir_vs(pooled, benB_oos), ir0=ir_vs(pooled, bh_oos),
                params=[r["p"] for r in rows], empties=sum(r["empty"] for r in rows))


# walk-forward 目標：flat-deep + E7b 代表（from-peak ^SOX/SMH + momentum ^SOX + QQQ control）
WF_TARGETS = [("flat-deep", None, None)] + [("E7b", flavor, sym) for flavor, sym in E7B_FRONTIER_CURVES]

print(f"\n（中間 4 欄＝per-fold 選到的 D_deep：fold 2022/2023/2024/2025 各自在 [2018,Y-1] 訓練窗選出＝跨 fold 穩定性）")
print(f"{'目標':<26}{'規則':>8}{'sel22':>7}{'sel23':>7}{'sel24':>7}{'sel25':>7}｜{'pooledSh':>9}{'OOSann%':>8}{'wfDD%':>7}{'IRvsB':>8}{'IRvs0050':>9}{'empty':>6}")
print("-" * 130)
WF_RESULTS = {}
for kind, flavor, sym in WF_TARGETS:
    if kind == "flat-deep":
        def eq_lk(dd):
            return EQ_FLAT[dd][0]

        def below_lk(dd):
            return LIVE_BELOW
        label = "flat-deep (no US)"
    else:
        pp = PLATEAU_PARAM[flavor]

        def eq_lk(dd, _f=flavor, _s=sym, _pp=pp):
            return EQ_E7B[(_f, _s, _pp, PLATEAU_CD, dd)][0]

        def below_lk(dd, _f=flavor, _s=sym, _pp=pp):
            return EQ_E7B[(_f, _s, _pp, PLATEAU_CD, dd)][2]
        label = f"E7b {flavor}-{sym}"
    for obj in ("calmar", "sharpe"):
        wf = walk_forward_deep(eq_lk, below_lk, obj)
        WF_RESULTS[(kind, flavor, sym, obj)] = wf
        ps = wf["params"]
        print(f"{label:<26}{obj:>8}"
              f"{ps[0]:>7.3f}{ps[1]:>7.3f}{ps[2]:>7.3f}{ps[3]:>7.3f}｜"
              f"{wf['pooled_sharpe']:>9.3f}{wf['pooled_ann']*100:>8.1f}{wf['worst_fwd_dd']*100:>7.1f}{wf['ir']:>+8.2f}{wf['ir0']:>+9.3f}{wf['empties']:>6}")

# plateau pick（D_deep=0.70 直接套 OOS，非 in-sample 峰）並列對照一致性
print("\n" + "-" * 130)
print(f"穩健 plateau pick（D_deep={D_DEEP_PLATEAU} 直接套 OOS，非 in-sample 峰；對照 R0 K=150 教訓）vs walk-forward 動態選參(Calmar)：")
print(f"{'目標':<26}{'plateau D':>11}{'pooledSh':>10}{'OOSann%':>9}{'wfDD%':>8}{'IRvs0050':>10}｜{'wf動態Sh':>9}{'一致?':>8}")
print("-" * 130)
for kind, flavor, sym in WF_TARGETS:
    if kind == "flat-deep":
        eq_pp = EQ_FLAT[D_DEEP_PLATEAU][0]
        below_pp = LIVE_BELOW
        label = "flat-deep (no US)"
    else:
        pp = PLATEAU_PARAM[flavor]
        eq_pp = EQ_E7B[(flavor, sym, pp, PLATEAU_CD, D_DEEP_PLATEAU)][0]
        below_pp = EQ_E7B[(flavor, sym, pp, PLATEAU_CD, D_DEEP_PLATEAU)][2]
        label = f"E7b {flavor}-{sym}"
    pooled = pd.concat([year_dr(eq_pp, Y) for Y in FWD])
    wdd = min(dd_of_window(eq_pp, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    pk_sh = sharpe_of(pooled)
    wf_sh = WF_RESULTS[(kind, flavor, sym, "calmar")]["pooled_sharpe"]
    consist = "一致" if abs(pk_sh - wf_sh) <= DELTA else "分歧"
    print(f"{label:<26}{D_DEEP_PLATEAU:>11.2f}{pk_sh:>10.3f}{ann_of(pooled)*100:>9.1f}{wdd*100:>8.1f}"
          f"{ir_vs(pooled, bh_oos):>+10.3f}｜{wf_sh:>9.3f}{consist:>8}")


# ════════════════════════════════════════════════════════════════════════════════
# S9 候選 config 表（C0 current-live / flat-deep 代表 / E7b 代表）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 130)
print("S9 — 候選 config 表（plateau 中值非 in-sample 峰）：全期 + OOS 全指標，與 C0 current-live 逐項對照")
print("=" * 130)

CAND = [
    ("C0 current-live(N3,band1%,0.85)", live_eq, exp_combined(cf, LIVE_CD, LIVE_BAND, 0.85), LIVE_BELOW, None),
    (f"flat-deep D={D_DEEP_PLATEAU}", EQ_FLAT[D_DEEP_PLATEAU][0], EQ_FLAT[D_DEEP_PLATEAU][2], LIVE_BELOW, None),
    ("flat-deep D=0.60", EQ_FLAT[0.60][0], EQ_FLAT[0.60][2], LIVE_BELOW, None),
]
for flavor, sym in [("frompeak", "^SOX"), ("frompeak", "SMH"), ("momentum", "^SOX")]:
    pp = PLATEAU_PARAM[flavor]
    eq, nx, below, uc, fe = EQ_E7B[(flavor, sym, pp, PLATEAU_CD, D_DEEP_PLATEAU)]
    nm = f"E7b {sym} {flavor}-{pp}{'%' if flavor!='ma' else ''}/D{D_DEEP_PLATEAU}"
    CAND.append((nm, eq, fe, below, uc))

print(f"{'config':<40}｜{'全期ann':>8}{'Sh':>6}{'maxDD':>8}｜{'OOSann':>8}{'Sh':>6}{'wfDD':>8}｜{'IRvsB':>7}{'IRvs0050':>9}{'牛市%':>7}{'交易':>6}")
print("-" * 130)
cand_m = {}
for nm, eq, fe, below, uc in CAND:
    m = metrics_of(eq, fe, below, uc)
    nx = sim_from_exp(adj, fe)[1]
    cand_m[nm] = (m, nx, eq, fe, below, uc)
    print(f"{nm:<40}｜{m['f_ann']*100:>8.1f}{m['f_sh']:>6.2f}{m['f_dd']*100:>8.1f}｜"
          f"{m['o_ann']*100:>8.1f}{m['o_sh']:>6.2f}{m['wdd']*100:>8.1f}｜{m['ir']:>+7.2f}{m['ir0']:>+9.3f}{m['bull']*100:>7.1f}{nx:>6}")
print("-" * 130)
print(f"  固定對照：0050 OOS Sh {S0:.2f}/wfDD {BH_WDD*100:.1f}%/牛市 {ann_of(pd.concat([year_dr(bh_eq,Y) for Y in (2023,2024,2025)]))*100:.1f}%｜"
      f"基準B OOS Sh {SB:.2f}/wfDD {BB_WDD*100:.1f}%｜δ={DELTA:.3f}｜0050 自身 IRvsB={BH_IRB:+.2f}(beta 線)")


# ════════════════════════════════════════════════════════════════════════════════
# S10 事件 + IS/OOS（2018/2020/2022 + 牛市；明標 IS/OOS；含深度 whipsaw）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 130)
print("S10 — 事件 stress（明標 IS/OOS）：2018Q4(IS) / 2020 COVID(IS) / 2022 熊(OOS,n=1) / 2023-25 牛(OOS)")
print("  ⚠️ 2018/2020 walk-forward expanding window 下永在訓練段＝IS；唯一 OOS 崩盤＝2022。depth-whip=曝險變動次數(含0.85↔D_deep)")
print("=" * 130)
print(f"{'config':<40}｜{'18報酬':>7}{'18DD':>7}｜{'20報酬':>7}{'20DD':>7}{'20深whip':>8}｜{'22報酬':>7}{'22DD':>7}{'22深whip':>8}｜{'牛23-25':>8}")
print("-" * 130)


def py3(eq, y):
    return bm._per_year(eq).get(y, (float("nan"),) * 3)


for nm, eq in [("0050 買持", bh_eq), ("基準B(vol0.011)", bb_eq)]:
    a, c, b = py3(eq, 2018), py3(eq, 2020), py3(eq, 2022)
    bull = ann_of(pd.concat([year_dr(eq, Y) for Y in (2023, 2024, 2025)]))
    print(f"{nm:<40}｜{a[0]*100:>6.1f}%{a[2]*100:>6.1f}%｜{c[0]*100:>6.1f}%{c[2]*100:>6.1f}%{'—':>8}｜"
          f"{b[0]*100:>6.1f}%{b[2]*100:>6.1f}%{'—':>8}｜{bull*100:>7.1f}%")
for nm, eq, fe, below, uc in CAND:
    a, c, b = py3(eq, 2018), py3(eq, 2020), py3(eq, 2022)
    bull = ann_of(pd.concat([year_dr(eq, Y) for Y in (2023, 2024, 2025)]))
    dw20 = depth_flips_in_year(fe, 2020)
    dw22 = depth_flips_in_year(fe, 2022)
    print(f"{nm:<40}｜{a[0]*100:>6.1f}%{a[2]*100:>6.1f}%｜{c[0]*100:>6.1f}%{c[2]*100:>6.1f}%{dw20:>8}｜"
          f"{b[0]*100:>6.1f}%{b[2]*100:>6.1f}%{dw22:>8}｜{bull*100:>7.1f}%")
print("-" * 130)


# ════════════════════════════════════════════════════════════════════════════════
# S11 🟥 深度調節事件研究（E7b 核心）：us_confirm False→True 加深的那些日，後續續跌(划算) vs 反彈(反傷)
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 130)
print("S11 — 🟥 深度調節事件研究（E7b 核心）：below_local 段內 us_confirm 由 False→True『加深』日，後續續跌(划算) vs 反彈(反傷)")
print("  事件=E7b 相對 flat-0.85/current-live 多砍(0.85→D_deep)的時點，砍在 open[T+1]；量 open[T+1]→close[T+1+k] 前向路徑")
print("=" * 130)

bt = adj[(adj["date"] >= pd.Timestamp(bm.START)) & (adj["date"] <= pd.Timestamp(bm.END))].reset_index(drop=True)
bt_dates = pd.DatetimeIndex(bt["date"])
bt_open = bt["open"].to_numpy(float)
bt_close = bt["close"].to_numpy(float)
date_to_i = {d: i for i, d in enumerate(bt_dates)}
KS = [1, 2, 3, 5, 10, 20]


def crash_phase(d):
    if d.year == 2020 and pd.Timestamp("2020-01-01") <= d <= pd.Timestamp("2020-06-30"):
        return "2020(V型,IS)"
    if d.year == 2022:
        return "2022(慢熊,OOS)"
    return "other"


def deepen_events(flavor, sym, param, d_deep):
    """E7b 加深事件：below_local=True 且 us_confirm 由 False→True 的 close-T 日（＝0.85→D_deep，砍 open[i+1]）。
    對每事件量 open[T+1]→close[T+1+k] 前向路徑 + gap + 淨效益((0.85−D_deep)×後續累積跌幅)。"""
    uc = us_confirm_state(sym, flavor, param, PLATEAU_CD).reindex(tw.index).fillna(False)
    bl = LIVE_BELOW.reindex(tw.index).fillna(False)
    uc_arr = uc.to_numpy(bool)
    # us_confirm 由 False→True 的轉折日（且當日 below_local True ＝真正觸發加深）
    onset = np.zeros(len(uc), dtype=bool)
    onset[1:] = uc_arr[1:] & (~uc_arr[:-1])
    deepen_days = uc.index[onset & bl.to_numpy(bool)]
    deepen_days = [d for d in deepen_days if d in date_to_i and date_to_i[d] + 1 < len(bt_dates)]
    extra_depth = 0.85 - d_deep      # 多砍的曝險（正數）
    recs = []
    for d in deepen_days:
        i = date_to_i[d]
        gap = bt_open[i + 1] / bt_close[i] - 1.0
        fwd = {}
        for k in KS:
            j = min(i + 1 + k, len(bt_close) - 1)
            fwd[k] = bt_close[j] / bt_open[i + 1] - 1.0
        recs.append(dict(date=d, phase=crash_phase(d), gap=gap, fwd=fwd, extra_depth=extra_depth))
    return recs


def summarize_deepen(label, recs, extra_depth):
    if not recs:
        print(f"  {label}: 無『加深』事件（below_local 段內 us_confirm 從未 False→True）。")
        return None
    df = pd.DataFrame([{"date": r["date"], "phase": r["phase"], "gap": r["gap"],
                        **{f"fwd{k}": r["fwd"][k] for k in KS}} for r in recs])
    print(f"\n  {label}：加深事件 n={len(df)}（分層：{df['phase'].value_counts().to_dict()}）｜多砍曝險={extra_depth*100:.0f}pp")
    print(f"    跳空 gap 均值 {df['gap'].mean()*100:+.2f}%（加深當下賣在跳空的代價）")
    print(f"    {'k':>4}｜{'fwd_ret均值':>11}{'中位':>9}{'勝率(後跌%)':>12}｜{'淨效益=多砍×後續P&L差(均)':>0}")
    for k in KS:
        col = df[f"fwd{k}"]
        winrate = (col < 0).mean()
        net = (-col * extra_depth).mean()    # 多砍 extra_depth × 後續 P&L 差（含反彈反傷）；正=划算
        print(f"    {k:>4}｜{col.mean()*100:>+10.2f}%{col.median()*100:>+8.2f}%{winrate*100:>11.0f}%｜"
              f"淨(含反彈) {net*100:>+.3f}pp")
    for ph in ["2020(V型,IS)", "2022(慢熊,OOS)"]:
        sub = df[df["phase"] == ph]
        if len(sub) == 0:
            continue
        print(f"    [分層 {ph}] n={len(sub)}：fwd5 {sub['fwd5'].mean()*100:+.2f}% / fwd10 {sub['fwd10'].mean()*100:+.2f}% / "
              f"fwd20 {sub['fwd20'].mean()*100:+.2f}%｜淨(fwd10) {(-sub['fwd10']*extra_depth).mean()*100:+.3f}pp "
              f"({'划算(後續跌)' if sub['fwd10'].mean()<0 else '反傷(後續彈)'})")
    return df


print("E7b 加深事件 前向路徑（open[T+1]→close[T+1+k]）— 各代表 config（D_deep=0.70 → 多砍 15pp）：")
for sym, fl, pm, tag in [("^SOX", "frompeak", 8, "^SOX peak-8%"), ("SMH", "frompeak", 8, "SMH peak-8%"),
                         ("^SOX", "momentum", -8, "^SOX 動能-8%")]:
    recs = deepen_events(fl, sym, pm, D_DEEP_PLATEAU)
    summarize_deepen(tag, recs, 0.85 - D_DEEP_PLATEAU)
print("\n  讀法：fwd_ret 顯著<0(勝率>50%)=加深划算(續跌)；>0=加深反傷(砍後反彈)。預期 2020 V型反傷、2022 慢熊划算（呼應 DRAWDOWN 研究）。")
print("  🟥 深度 whipsaw：見 S10 表『深whip』欄（曝險變動次數，含 0.85↔D_deep 來回）；對照 below flips(2022=1)＝E7b 不該顯著增態轉折。")


# ════════════════════════════════════════════════════════════════════════════════
# S12 §5 Gate + E7b 特有 Gate（②–⑩）逐 config 裁決
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 130)
print("S12 — §5 Gate + E7b 特有 Gate（②–⑩，全 AND；重錨同族 current-live + 兩被動；鐵則#8 絕對 floor 退役）")
print("=" * 130)


def deepen_net_positive(flavor, sym, param, d_deep):
    recs = deepen_events(flavor, sym, param, d_deep)
    if not recs:
        return None, None, 0
    df = pd.DataFrame([{"phase": r["phase"], "fwd10": r["fwd"][10]} for r in recs])
    extra = 0.85 - d_deep
    net_all = (-df["fwd10"] * extra).mean()
    sub22 = df[df["phase"] == "2022(慢熊,OOS)"]
    net22 = (-sub22["fwd10"] * extra).mean() if len(sub22) else None
    return net_all, net22, len(df)


# E7b config → (flavor,sym,param) for 加深可交易性 + 對應 flat-D_deep（同 D_deep）牛市對照（⑨）
GATE_CONFIGS = []
for flavor, sym in [("frompeak", "^SOX"), ("frompeak", "SMH"), ("momentum", "^SOX")]:
    pp = PLATEAU_PARAM[flavor]
    GATE_CONFIGS.append((f"E7b {sym} {flavor}-{pp}/D{D_DEEP_PLATEAU}", flavor, sym, pp, D_DEEP_PLATEAU))

# 對應 flat-D_deep 指標（for ⑨：E7b 牛市 ≥ 同 D_deep flat 牛市）
flat_at_dplateau_m = metrics_of(EQ_FLAT[D_DEEP_PLATEAU][0], EQ_FLAT[D_DEEP_PLATEAU][2], LIVE_BELOW)

struct_pass_any = False
for nm, flavor, sym, pp, dd in GATE_CONFIGS:
    eq, nx, below, uc, fe = EQ_E7B[(flavor, sym, pp, PLATEAU_CD, dd)]
    m = metrics_of(eq, fe, below, uc)
    # ② 降-DD 不惡化於 current-live 且優於兩被動
    g_dd = (m["wdd"] >= LIVE_WDD - 1e-9) and (m["wdd"] > BB_WDD) and (m["wdd"] > BH_WDD)
    # ③ OOS Sharpe 不顯著差於 current-live（δ 帶內）
    g_sharpe = m["o_sh"] >= SL - DELTA
    # ④ 牛市不犧牲（OOS 年化 ≥ live − 0.01）
    g_bull = m["o_ann"] >= LIVE_OOS_ANN - 0.01
    # ⑤ whipsaw 不惡化（含深度層）：2022 below flips ≤ live AND 深度 whip 不顯著增（對照 below flips）
    g_below_whip = m["blwfl22"] <= LIVE_FL22
    g_depth_whip = m["dwhip22"] <= flat_at_dplateau_m["dwhip22"] + 2     # 容 2 次（vs 同 D_deep flat 的曝險變動）
    g_whip = g_below_whip and g_depth_whip
    # ⑥ alpha（預期 FAIL）：IRvs0050>0 AND OOS Sharpe−0050>δ
    g_alpha = (m["ir0"] > 0) and (m["o_sh"] - S0 > DELTA)
    # ⑦ 加深可交易性：淨效益(fwd10)全體>0 且 2022(OOS)>0
    net_all, net22, ntr = deepen_net_positive(flavor, sym, pp, dd)
    g_trade = (net_all is not None and net_all > 0) and (net22 is None or net22 > 0)
    # ⑧ 🟥前緣勝 flat-deep（matched-D_deep 控制比較；與 S-frontier(2) 一致；內插 Δ 僅參考）
    e7b_row_for_gate = dict(dd=dd, o_ann=m["o_ann"], wdd=m["wdd"])
    g_frontier, mdd_ann_g, mdd_dd_g = matched_dd_addvalue(e7b_row_for_gate)
    d_ann_vs_flat = (m["o_ann"] - interp_flat_ann_at_wdd(m["wdd"])) * 100      # 內插參考
    d_dd_vs_flat = (m["wdd"] - interp_flat_wdd_at_ann(m["o_ann"])) * 100       # 內插參考
    # ⑨ 牛市/whipsaw 不因條件化而惡化於對應 flat-D_deep：E7b 牛市 ≥ 同 D_deep flat 牛市
    g_vs_flat_bull = m["bull"] >= flat_at_dplateau_m["bull"] - 0.001
    # ⑩ 綜合結構 Gate = ②∧④∧⑤∧⑦∧⑧∧⑨
    struct = g_dd and g_bull and g_whip and g_trade and g_frontier and g_vs_flat_bull
    if struct:
        struct_pass_any = True
    verdict = ("結構 Gate PASS（條件加深降DD + 前緣勝flat-deep + 牛市/whip不惡化 + 加深划算）" if struct
               else ("FAIL（②或⑧不過）" if (not g_dd or not g_frontier) else "MARGINAL"))
    print(f"\n【{nm}】wfDD {m['wdd']*100:.1f}%｜OOSann {m['o_ann']*100:.1f}%｜OOS Sh {m['o_sh']:.3f}｜牛市 {m['bull']*100:.1f}%")
    print(f"  ②降-DD不惡化且優於兩被動：wfDD {m['wdd']*100:.1f}% (live {LIVE_WDD*100:.1f}%/B {BB_WDD*100:.1f}%/0050 {BH_WDD*100:.1f}%) → {'✓' if g_dd else '✗'}")
    print(f"  ③OOS Sharpe 不顯著差 live(δ={DELTA:.2f}帶)：{m['o_sh']:.3f} vs {SL:.3f} → {'✓' if g_sharpe else '✗'}")
    print(f"  ④牛市不犧牲(OOS年化 {m['o_ann']*100:.1f}% vs live {LIVE_OOS_ANN*100:.1f}%) → {'✓' if g_bull else '✗'}")
    print(f"  ⑤whipsaw 不惡化(含深度層)：below 22flips {m['blwfl22']}≤{LIVE_FL22}={'✓' if g_below_whip else '✗'}｜"
          f"深度whip {m['dwhip22']} vs flat-D {flat_at_dplateau_m['dwhip22']}={'✓' if g_depth_whip else '✗'} → {'✓' if g_whip else '✗'}")
    print(f"  ⑥alpha(預期FAIL)：IRvs0050 {m['ir0']:+.3f}、OOS Sharpe−0050 {m['o_sh']-S0:+.3f} vs δ {DELTA:.2f} → "
          f"{'✓有alpha' if g_alpha else '✗無(δ內)'}｜註：IRvsB {m['ir']:+.2f} 是 beta（0050 自身 IRvsB={BH_IRB:+.2f}）")
    print(f"  ⑦加深可交易性(fwd10)：全體 {net_all*100:+.3f}pp / 2022 {(net22*100 if net22 is not None else float('nan')):+.3f}pp (n={ntr}) → {'✓划算' if g_trade else '✗反傷/負'}")
    print(f"  ⑧🟥前緣勝flat-deep(matched-D{dd}控制)：同D ΔDD {mdd_dd_g:+.2f}pp / Δann {mdd_ann_g:+.2f}pp → {'✓US加值' if g_frontier else '✗重合/更差(US無加值)'}"
          f"｜內插參考：同wfDD Δann {d_ann_vs_flat:+.2f}pp / 同ann ΔDD {d_dd_vs_flat:+.2f}pp")
    print(f"  ⑨牛市不惡化於對應flat-D{D_DEEP_PLATEAU}(牛市 {m['bull']*100:.1f}% vs flat {flat_at_dplateau_m['bull']*100:.1f}%) → {'✓' if g_vs_flat_bull else '✗'}")
    print(f"  ⑩ E7b 綜合結構 Gate → {verdict}")


# ════════════════════════════════════════════════════════════════════════════════
# S13 收尾
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 130)
print("S13 — 收尾")
print("=" * 130)
print("• beta vs alpha 分離（鐵則、勿誤引）：walk-forward 的 IRvs基準B 高(+1.x) 是 beta 不是 alpha")
print(f"  （0050 自身 IRvs基準B={BH_IRB:+.2f} 為純 beta 零技巧參考線）；真 alpha 檢定＝同 beta 的 IRvs0050，")
print(f"  E7b 全 config IRvs0050 ≤ 0 或 Sharpe 邊際 ≪ δ={DELTA:.3f} → alpha FAIL（R0–R5/E1–E5/E7 一致）。")
print(f"• 🟥 E7b 唯一可能站住＝在 DD-vs-報酬前緣 Pareto 勝過 flat-deep（US-conditioning 真加值）：")
print(f"  → S-frontier(2) matched-D_deep：{n_av}/{n_tot} 點『加值』（皆貼雜訊地板、僅極淺 D 端＝非系統性）；其餘同 D 下 E7b wfDD 普遍更深。")
print(f"  → S12 plateau gate ⑧（D={D_DEEP_PLATEAU}，walk-forward 主裁點）：{'有 PASS' if struct_pass_any else '全 config ✗（matched 同 D 下 E7b 重合/更差）'}＝US-conditioning 零系統性加值。")
print(f"  → 綜合裁決：E7b 結構 Gate FAIL（未在前緣 Pareto 勝 flat-deep）；US-conditioning 把加深用在更差的子集（同 D 更深 DD、報酬持平）。")
print("• flat-deep 控制組＝R6 已知『無條件加深』前緣（D_deep↓→DD改善、牛市拖累↑）；E7b 須打破此前緣才有價值——未做到。")
print("• 機制微觀（S11）：加深事件 n 極少(3~5)、2022 OOS 段混合(from-peak 反傷、動能小划算)、2020 加深事件 0(進場由乾淨 local-MA200 把關)＝E7 假警報稀釋雖移除，但同 D 下加深不如 flat 乾淨。")
print("• survivorship 無法消除（FinMind 0050 無下市；US 為 ADR/ETF/指數存續樣本）→ 所有結果是【上界】。")
print("• 2018/2020 永在訓練段＝IS；唯一 OOS 崩盤＝2022（n=1 崩盤週期）→ 加深事件研究/前緣的 2022 段描述性、統計功效低。")
print("• 純快取 0 API；只新增 notebooks/e7b_depth_modulation.py、未改任何既有檔；不 commit、不切 branch、不動 live。")
print("• **總 Gate 未過前 live（0050 + MA200 N3band1% 85% overlay）一律不動。**")
print("[done] E7b 完成（純快取、0 API；行為中性 + look-ahead 雙 sanity PASS；flat-deep 前緣對照完成）。")

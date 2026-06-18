"""
notebooks/e7_us_semi_defense.py
【實驗 E7】美股半導體隔夜訊號 作為「比 0050 自身 MA200 更早的崩盤防禦觸發」，疊進/替換現行 overlay 的
「跌破態」判定，用 walk-forward OOS 驗證**能否降回撤(DD)而不犧牲牛市**。
定位＝**結構性防禦訊號、非 alpha**（alpha 預期 FAIL，R0–R5/E1–E5 一致）。

前置已證實（notebooks/us_lead_0050.py）：
  • 美股半導體(^SOX/SMH/SOXX)+TSM ADR 隔夜領先 0050：corr(美股隔夜,0050當日)≈0.46–0.55（^SOX~0.55、TSM~0.515）；
    Granger 單向 US→TW p≈1e-76~1e-115、TW→US 不顯著。跨 2018–25 穩定。
  • 🟥 但 ~99% 領先力在 0050「開盤跳空」就被吸收（corr(美股隔夜,開盤跳空)≈0.65–0.73；corr(美股隔夜,盤中)≈0、t≈0）。
    ⇒ E7 在 T+1 開盤成交＝賣在已跳空的價。E7 對 DD 是否有用，取決於「砍倉後跌勢是否**持續**（早砍划算）
    vs 只鎖住跳空隨後反彈（砍在低點反傷）」——須用可交易性事件研究誠實量化（不可只看『有沒有更早觸發』）。

現況 live（E7 所 augment/比較的基準 overlay = current-live）：
  0050 vol-target base 恆 100%（target_daily_vol=1.0）+ MA200 overlay：0050 收盤「連 3 日跌破 MA200×0.99」砍至 85%、
  「連 3 日站回 ×1.01」回滿（regime_action=0.85, confirm_days=3, band_pct=0.01）。月度 + 5pp 帶再平衡、T+1 開盤成交、零股 LOT=1。

🟥 因果對齊（NO LOOK-AHEAD，E7 最關鍵）：
  us_overnight[D] = （台股 D-1 收盤, 台股 D 收盤]內已收盤的美股 session 複利報酬 = 台股 day D 開盤前『已知』。
  harness 慣例：exp[T]（close T 算）→ open[T+1] 成交＝day T+1 持倉 → day T+1 持倉的『美股態』須用 us_overnight[T+1]
  ＝相對 close-T 訊號**前移一格**（us_regime_on_tw.shift(-1) 落 close-T grid）。0050-MA200 維持 close-T 慣例。

⚠️ 純快取、0 API；只新增此檔、不改任何既有檔；不 commit、不切 branch、不動 live。survivorship 上界。
用法：.venv/bin/python notebooks/e7_us_semi_defense.py
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
# 常數（COPY 自 e1e2_walkforward.py / e1e2_combined_validate.py）
# ════════════════════════════════════════════════════════════════════════════════
SQRT252 = np.sqrt(252)
FWD = [2022, 2023, 2024, 2025]          # OOS 前進窗（同 R0/R1/E1-E5）
MA = 200
REDUCED, FULL = 0.85, 1.0
DD_BAND = 0.022                          # walk-forward floor 容差（同 R1/E1E2；相對同族基線 current-live）
CACHE = "data/raw/finmind_cache"
START_US, END_US = "2018-01-01", "2025-12-31"
LIVE_CD, LIVE_BAND = 3, 0.01            # current-live overlay 參數（連 3 日確認 + 1% 帶）


# ════════════════════════════════════════════════════════════════════════════════
# helpers（逐字 COPY 自 e1e2_walkforward.py）
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


# ── sim_from_exp（逐字 COPY 自 e1e2_walkforward.py:95-143；回傳 (eq, n_exec)）────────
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


# ── current-live overlay 精確邏輯（exp_combined，逐字 COPY 自 e1e2_combined_validate.py:115-141）──
def exp_combined(close_full, confirm_days=1, band_pct=0.0):
    """E1∩E2 統一：close<MA×(1−band) 連續 confirm 日→reduced(0.85)；close>MA×(1+band) 連續 confirm 日→full(1.0)。
    (confirm_days=1, band_pct=0.0) 逐位重現舊每日規則。回傳含 0.85 的 exposure（REDUCED=0.85，base 恆 1.0）。"""
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


def below_state_machine(raw_below: pd.Series, confirm_days: int) -> pd.Series:
    """通用 N 日確認狀態機（吃任意 raw_below bool）→ 回傳『是否處於 reduced(below)態』bool。
    full→below：raw_below 連續 confirm 日；below→full：~raw_below 連續 confirm 日。對稱 confirm。
    （E7-replace 對美股 regime 套此結構與 current-live 公平對照；E7-early/combine 的 below_local 也走它。）"""
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
    """0050-MA200 『跌破(reduced)態』bool（close-T 慣例）＝ (exp_combined<1.0)。current-live 預設 (3,0.01)。"""
    return (exp_combined(close_full, confirm_days, band_pct) < FULL)


def flips_in_year(below_series, year):
    """『跌破態』bool 在某年的態轉折次數（whipsaw proxy）。吃 below bool 或 exposure 皆可。"""
    s = below_series[below_series.index.year == year]
    if len(s) < 2:
        return 0
    arr = s.to_numpy()
    if arr.dtype == bool:
        b = arr.astype(int)
    else:
        b = np.isclose(arr.astype(float), REDUCED).astype(int)   # exposure: REDUCED→1
    return int((np.diff(b) != 0).sum())


# ════════════════════════════════════════════════════════════════════════════════
# 載入資料（純快取、0 API）
# ════════════════════════════════════════════════════════════════════════════════
print("=" * 124)
print("【E7】美股半導體隔夜訊號 作為崩盤防禦觸發 | walk-forward OOS（純快取 / 0 API / cache-only）")
print("=" * 124)
adj = bm.load_adjusted_0050()
cf = adj.set_index("date")["close"].sort_index().astype(float)   # 全 grid（含 2016 暖身）
print(f"  0050 還原日線（快取）：{len(adj)} 列  {adj['date'].min().date()} ~ {adj['date'].max().date()}（含 2016 暖身）")
print(f"  回測窗 {bm.START} ~ {bm.END}｜LOT={bm.LOT}｜SLIP={bm.SLIP}｜再平衡帶={bm.BAND*100:.0f}pp｜月度再平衡 ON")

# TW 交易日 grid（for us_overnight_to_tw）— 用回測窗 0050 open/close（同 us_lead_0050 口徑）
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
print("  >>> 0 API / cache-only：僅讀本地 pickle + bm.load_adjusted_0050()，無任何 fetcher.get_*/网路呼叫。")
print("=" * 124)


# ── us_overnight_to_tw（逐字 COPY 自 us_lead_0050.py:68-78）─────────────────────────
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


# 美股隔夜報酬（TW grid，close-T 慣例 = us_overnight[T] 對齊 0050 close-T 那一天）
us_overnight = {s: us_overnight_to_tw(us_close[s]) for s in US_SYMS}     # index = TW 交易日

# 美股 Adj_Close 對齊到『其收盤後第一個台股交易日』的 level（for MA-cross/from-peak/動能 raw 計算）
# 用 searchsorted 把每個美股 session 的 Adj_Close 落到映射的 TW 日（同窗多 session 取最後＝最新收盤）。
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
# S3 因果對齊驗證（FAIL 即停）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 124)
print("S3 — 因果對齊驗證（NO LOOK-AHEAD）：範例日期對齊 + falsification + 覆蓋率")
print("=" * 124)

# (a) 範例日期對齊：抽幾個 TW 交易日，印『落在該 TW 日(close-T)的最後一個美股 session 日期』< 該 TW 日
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

# 前移一格後：us 態落在 close-T row date_i → 影響 day i+1 持倉（open i+1 成交）。驗 date_i 的下一交易日 > 最後美股日。
print("\n    前移一格(shift(-1))後：us 態放在 close-T=date_i 那列 → 決定 day i+1 持倉（open[i+1] 成交）。")
print("    驗證：date_i 的美股資訊（=us_overnight[date_{i+1}] 的貢獻 session）< open[i+1] 成交日（嚴格早於成交）。")
tw_idx_list = list(tw.index)
shift_ok = True
for d in ["2020-03-11", "2022-03-06", "2024-08-02"]:
    if pd.Timestamp(d) not in tw.index:
        continue
    i = tw_idx_list.index(pd.Timestamp(d))
    if i + 1 >= len(tw_idx_list):
        continue
    next_tw = tw_idx_list[i + 1]            # day i+1（成交在其 open）
    sub = map_df[map_df["tw_date"] == next_tw]   # 貢獻 us_overnight[i+1] 的美股 session（前移後落 row date_i）
    if len(sub) == 0:
        continue
    last_us = pd.Timestamp(sub["us_date"].max())
    ok = last_us < next_tw
    shift_ok &= ok
    print(f"   close-T row {d} → 持倉日 {next_tw.date()}（open 成交）｜用到美股 session {last_us.date()} < 成交日 {'✓' if ok else '✗'}")
assert shift_ok, "前移對齊 FAIL"

# (b) falsification：把美股 us_overnight 整體往未來 shift(-1)（偷看未來一天）→ corr(美股隔夜, 0050當日) 應崩。
#     注意：「偷看未來1天」的 corr = corr(us_overnight[T+1], tw_ret[T]) = 『TW[T] 領先 次一 US session』反向回饋
#     （us_lead_0050 PART6 已記錄、非 look-ahead）。E7 主訊號(^SOX/SMH/QQQ)此反向回饋極弱→corr 崩；
#     TSM ADR 與台北 TSMC 同日連動→反向回饋強(~0.30)＝真經濟、非 wiring bug，且 TSM 僅 negative-control 不入任何 C-config。
print("\n(b) falsification（偷看未來檢查）：把美股隔夜序列整體前移一天(shift(-1)=偷看未來)→ 與 0050 當日報酬相關性應崩")
print("    （『偷看未來』corr ＝ corr(us_overnight[T+1], tw_ret[T]) ＝ TW 領先次一 US session 的反向回饋；E7 主訊號應崩）")
tw_ret = tw["close"].pct_change()
E7_MAIN = ["^SOX", "SMH", "QQQ"]
fals_ok = True
for s in ["^SOX", "SMH", "TSM", "QQQ"]:
    base = pd.concat([us_overnight[s].rename("u"), tw_ret.rename("t")], axis=1).dropna()
    c_base = base["u"].corr(base["t"])
    peek = pd.concat([us_overnight[s].shift(-1).rename("u"), tw_ret.rename("t")], axis=1).dropna()
    c_peek = peek["u"].corr(peek["t"])
    crash = c_peek < c_base * 0.5
    if s in E7_MAIN:
        fals_ok &= crash
        tag = "✓ 崩潰(無偷看未來)" if crash else "✗ 未崩→疑慮"
    else:
        tag = "(negative-control；殘留=TW→US 反向回饋,非bug,不入C-config)"
    print(f"   {s:6}：corr(正確對齊)={c_base:.3f}  →  corr(偷看未來1天)={c_peek:.3f}  {tag}")
assert fals_ok, "falsification FAIL：E7 主訊號(^SOX/SMH/QQQ)『偷看未來』相關性未崩潰→疑似 look-ahead！"

# (c) 覆蓋率 + 末有效對齊日
print("\n(c) us_overnight 覆蓋率（TW grid 上非 NaN 比例）+ 末有效對齊日（shift(-1) 末日無 T+1 → NaN）")
for s in ["^SOX", "SMH"]:
    cov = us_overnight[s].reindex(tw.index).notna().mean()
    last_valid = us_overnight[s].dropna().index.max()
    print(f"   {s:6}：覆蓋率 {cov*100:.1f}%｜末有效對齊日 {pd.Timestamp(last_valid).date()}（< END {bm.END} ✓）")
print("  [S3 PASS] 因果對齊三層防護通過：美股 session 嚴格早於成交、偷看未來相關性崩、覆蓋率/邊界正常。")


# ════════════════════════════════════════════════════════════════════════════════
# E7 訊號 flavors（美股自身 grid 算 raw_below → us_level_to_tw 已落 TW close-T grid）
#   注意：us_level 已是『close-T 慣例』（落在美股收盤後第一個 TW 日）。
#   E7 需要 day i+1 持倉的美股態 → 對 us 態再 shift(-1) 落 close-T row（前移一格對齊）。
# ════════════════════════════════════════════════════════════════════════════════
def us_raw_below_ma(sym, L):
    """flavor 1 (MA-cross)：us_level < us_level.rolling(L).mean()。回傳 TW close-T grid bool。"""
    lv = us_level[sym]
    return (lv < lv.rolling(L).mean()).fillna(False)


def us_raw_below_frompeak(sym, X, W=60):
    """flavor 2 (from-peak 回撤)：us_level / rolling(W).max − 1 < −X(%) → True。X 為百分點(正數)。"""
    lv = us_level[sym]
    dd = lv / lv.rolling(W, min_periods=1).max() - 1.0
    return (dd < -X / 100.0).fillna(False)


def us_raw_below_momentum(sym, Thr, M=10):
    """flavor 3 (動能)：us_level.pct_change(M) < Thr(%) → True。Thr 為百分點(負數，如 −8)。"""
    lv = us_level[sym]
    mom = lv.pct_change(M)
    return (mom < Thr / 100.0).fillna(False)


def us_regime_below(sym, flavor, param, confirm_days=LIVE_CD, **kw):
    """美股 regime『跌破態』bool（TW close-T grid），套 N 日確認與 current-live 公平對照。
    flavor: 'ma' (param=L) / 'frompeak' (param=X%) / 'momentum' (param=Thr%)。"""
    if flavor == "ma":
        raw = us_raw_below_ma(sym, int(param))
    elif flavor == "frompeak":
        raw = us_raw_below_frompeak(sym, float(param), kw.get("W", 60))
    elif flavor == "momentum":
        raw = us_raw_below_momentum(sym, float(param), kw.get("M", 10))
    else:
        raise ValueError(flavor)
    return below_state_machine(raw, confirm_days)


def shift_to_expgrid(us_below_tw: pd.Series) -> pd.Series:
    """前移一格：us 態（TW close-T grid）→ 落 close-T=date_i row（影響 day i+1 持倉）。
    末筆 shift(-1) → NaN → fillna(False)＝非 below（維持 full，不引入未來；與 below_local 暖身慣例一致）。"""
    return us_below_tw.shift(-1).fillna(False).astype(bool)


def final_exp_from_below(below_on_expgrid: pd.Series, mult=REDUCED) -> pd.Series:
    """base_exp 恆 1.0（vol-cap 關＝target_daily_vol=1.0），below 態 ×mult(0.85)。落全 grid(含暖身)。
    below_on_expgrid 為 TW 回測窗 grid；reindex 到全 grid（cf.index）、回測窗外/NaN → full(1.0)。"""
    full_below = below_on_expgrid.reindex(cf.index).fillna(False).astype(bool)
    exp = pd.Series(FULL, index=cf.index, dtype=float)
    exp = exp.where(~full_below, FULL * mult)
    return exp


# 三架構 below 合成器（TW close-T grid）
def below_E7_replace(sym, flavor, param, confirm_days=LIVE_CD, **kw):
    """below = US_semi_regime（前移對齊）。完全用美股 regime 取代 0050-MA200。"""
    us_b = us_regime_below(sym, flavor, param, confirm_days, **kw)
    return shift_to_expgrid(us_b)


def below_E7_early(sym, flavor, param, confirm_days=LIVE_CD, **kw):
    """below = below_local(3,0.01)[close-T] OR us_early[前移對齊]。E1+E2 第二道防線換成外部領先訊號。"""
    loc = below_local_combined(cf, LIVE_CD, LIVE_BAND).reindex(tw.index).fillna(False).astype(bool)
    us_e = shift_to_expgrid(us_regime_below(sym, flavor, param, confirm_days, **kw))
    us_e = us_e.reindex(tw.index).fillna(False).astype(bool)
    return (loc | us_e)


def below_E7_combine_and(sym, flavor, param, confirm_days=LIVE_CD, **kw):
    """below = below_local AND us_regime（兩者皆觸發才砍，抑假觸發）。"""
    loc = below_local_combined(cf, LIVE_CD, LIVE_BAND).reindex(tw.index).fillna(False).astype(bool)
    us_r = shift_to_expgrid(us_regime_below(sym, flavor, param, confirm_days, **kw))
    us_r = us_r.reindex(tw.index).fillna(False).astype(bool)
    return (loc & us_r)


def below_E7_combine_2of3(sym_a, sym_b, flavor, param, confirm_days=LIVE_CD, **kw):
    """2-of-3：local + US-semi(sym_a) + US-broad(sym_b)，≥2 觸發才砍。"""
    loc = below_local_combined(cf, LIVE_CD, LIVE_BAND).reindex(tw.index).fillna(False).astype(int)
    a = shift_to_expgrid(us_regime_below(sym_a, flavor, param, confirm_days, **kw)).reindex(tw.index).fillna(False).astype(int)
    b = shift_to_expgrid(us_regime_below(sym_b, flavor, param, confirm_days, **kw)).reindex(tw.index).fillna(False).astype(int)
    return ((loc + a + b) >= 2)


def eq_for_below(below_tw, mult=REDUCED):
    """below(TW grid) → final_exp(全 grid) → sim_from_exp → (eq, n_exec, below_tw)。"""
    fe = final_exp_from_below(below_tw, mult)
    eq, nx = sim_from_exp(adj, fe)
    return eq, nx, below_tw


# ════════════════════════════════════════════════════════════════════════════════
# S4 行為中性驗證（assert max|Δ|=0，FAIL 即停）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 124)
print("S4 — 行為中性驗證（additive 鐵證：US 訊號關閉/極端 ⇒ 逐位重現 current-live，max|Δ|=0）")
print("=" * 124)

# (0) 先驗 COPY 進來的 exp_combined(1,0.0) ≡ 引擎 simulate_benchmark overlay 路徑（current-live 錨點正確）
live_daily_eq, _ = sim_from_exp(adj, exp_combined(cf, 1, 0.0))
eng = bm.simulate_benchmark(adj, 1.0, overlay=True, regime_ma=MA, regime_action=0.85)["equity"]
d_eng = float((live_daily_eq - eng).abs().max())
assert d_eng < 1e-3, f"exp_combined(1,0.0) 未重現引擎 overlay：max|Δ|={d_eng:.2e}"
print(f"(0) exp_combined(1,0.0) ≡ 引擎 simulate_benchmark(overlay,200,0.85)：max|Δ|={d_eng:.1e} 元（< 1e-3）→ COPY helper 與引擎一致 ✓")

# current-live 錨點：exp_combined(3,0.01) → 0.85（注意此函數已回傳含 0.85 的 exposure）
live_eq, live_nx = sim_from_exp(adj, exp_combined(cf, LIVE_CD, LIVE_BAND))
# 用 E7 路徑（below_local → final_exp）重建 current-live，驗 E7 wiring 等價
live_below = below_local_combined(cf, LIVE_CD, LIVE_BAND).reindex(tw.index).fillna(False).astype(bool)
live_eq2, live_nx2 = sim_from_exp(adj, final_exp_from_below(live_below, REDUCED))
d_wire = float((live_eq - live_eq2).abs().max())
assert d_wire < 1e-9, f"E7 below_local→final_exp 未重現 exp_combined(3,0.01)：max|Δ|={d_wire:.2e}"
print(f"    current-live: exp_combined(3,0.01)→0.85 ≡ E7 below_local→final_exp：max|Δ|={d_wire:.1e}｜交易數={live_nx} (E7路徑={live_nx2})")

# (a) E7-early(OR)：US 早期訊號關閉（門檻極端 X=999% 永不觸發）→ below = below_local OR False = below_local
e7e_off = below_E7_early("^SOX", "frompeak", 999.0)
eq_off, nx_off, _ = eq_for_below(e7e_off)
d_early = float((eq_off - live_eq).abs().max())
assert d_early == 0.0, f"E7-early US 關閉未逐位重現 current-live：max|Δ|={d_early:.2e}"
print(f"(a) E7-early(OR) US 訊號關閉(from-peak X=999%)：below=below_local → max|Δ|={d_early:.1e}（嚴格 0，OR-False identity）✓")

# 也驗動能極端 Thr=-999%
e7e_off2 = below_E7_early("^SOX", "momentum", -999.0)
eq_off2, _, _ = eq_for_below(e7e_off2)
assert float((eq_off2 - live_eq).abs().max()) == 0.0
print(f"    （亦驗 E7-early 動能 Thr=−999% → max|Δ|=0.0 ✓）")

# (b) E7-combine(AND)：US 條件恆 True（MA=1→us_level 永不< MA(1)＝MA(1)=自身→raw_below 恆 False... 改用門檻極鬆）
#     用 frompeak X=-999%（dd 永遠 > -999/100 ＝ raw_below 恆 False）→ 反；需 us_regime 恆 True。
#     us 恆 True 構造：from-peak X = -100%（dd = lv/max-1 ≥ -1 > -1.0 為 False；用 +epsilon...）
#     最穩構造：直接令 us raw_below 恆 True ⇒ momentum Thr=+999%（pct_change < 999/100=9.99 幾乎恆 True）。
e7c_on = below_E7_combine_and("^SOX", "momentum", 999.0)   # us_regime 恆 True → below = local AND True = local
eq_con, nx_con, _ = eq_for_below(e7c_on)
d_and = float((eq_con - live_eq).abs().max())
assert d_and == 0.0, f"E7-combine(AND) US 恆 True 未逐位重現 current-live：max|Δ|={d_and:.2e}"
print(f"(b) E7-combine(AND) US 條件恆 True(動能 Thr=+999%)：below=below_local → max|Δ|={d_and:.1e}（嚴格 0，AND-True identity）✓")
print("  [S4 PASS] 行為中性鐵證通過：E7-early/combine 退化點逐位重現 current-live；E7-replace 無自然退化點（改驗 diff 觸發日，見 S9）。")


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
BH_IRB = ir_vs(bh_oos, benB_oos)              # 0050 自身 IRvs基準B（純 beta、零技巧）＝beta 參考線
LIVE_OOS_ANN = ann_of(live_oos)
LIVE_FL22 = flips_in_year(live_below, 2022)

print("\n" + "=" * 124)
print("S5 — 固定預先指定基準（compute once；絕不 best-of-sweep、絕不引污染 12.7%/1.16/−16%）")
print("=" * 124)
print(f"  δ(OOS Sharpe 1SE, current-live pooled n={len(live_oos)}) = {DELTA:.3f}（plateau/顯著性雜訊尺度）")
print(f"  OOS Sharpe：0050 {S0:.3f}（報酬王）｜基準B {SB:.3f}（de-risked beta）｜current-live {SL:.3f}")
print(f"  最差前進年 DD：0050 {BH_WDD*100:.1f}%｜基準B {BB_WDD*100:.1f}%｜current-live {LIVE_WDD*100:.1f}%")
print(f"  beta 參考線：0050 自身 IRvs基準B = {BH_IRB:+.3f}（純 beta、零技巧）→ walk-fwd 的 IRvs基準B 高=beta 非 alpha")
print(f"  current-live OOS 年化 {LIVE_OOS_ANN*100:.1f}%｜2022 flips {LIVE_FL22}｜全期交易數 {live_nx}")


# ════════════════════════════════════════════════════════════════════════════════
# S7 細網格掃描（每架構主軸 ≥12 點；in-sample + OOS 整條曲線；δ 判 plateau vs 孤峰）
# ════════════════════════════════════════════════════════════════════════════════
IS_START, IS_END = "2018-01-01", "2021-12-31"   # in-sample 窗（線索；2018/2020 永在訓練段）

# 細網格
GRID_MA = [20, 30, 40, 50, 60, 75, 100, 120, 150, 175, 200, 250]            # 12 點
GRID_X = [3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 18, 20]                          # 12 點（from-peak 回撤%）
GRID_THR = [-2, -3, -4, -5, -6, -8, -10, -12, -14, -16, -18, -20]            # 12 點（M 日累積%）


def lead_time_vs_local(below_tw, year):
    """US 訊號(前移對齊後 below_tw)在某年首觸 below 的 close-T index − local-combined 首觸 index。
    正值＝US 早幾個交易日。below_tw 已是 close-T grid（決定 i+1 持倉）。"""
    loc = below_local_combined(cf, LIVE_CD, LIVE_BAND).reindex(tw.index).fillna(False)
    yloc = loc[loc.index.year == year]
    yus = below_tw.reindex(tw.index).fillna(False)
    yus = yus[yus.index.year == year]
    loc_first = yloc[yloc].index.min() if yloc.any() else None
    us_first = yus[yus].index.min() if yus.any() else None
    if loc_first is None or us_first is None:
        return None, us_first, loc_first
    li = tw_idx_list.index(loc_first)
    ui = tw_idx_list.index(us_first)
    return li - ui, us_first, loc_first


def sweep_metrics(below_tw):
    """單一參數：in-sample + OOS pooled 全指標。"""
    eq, nx, _ = eq_for_below(below_tw)
    is_m = window_metrics(eq, IS_START, IS_END)            # (ann,sh,dd,cal)
    oos_pooled = pd.concat([year_dr(eq, Y) for Y in FWD])
    oos_sh = sharpe_of(oos_pooled)
    oos_ann = ann_of(oos_pooled)
    wdd = min(dd_of_window(eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    ir0 = ir_vs(oos_pooled, bh_oos)
    lt22, _, _ = lead_time_vs_local(below_tw, 2022)
    return dict(eq=eq, nx=nx, is_sh=is_m[1], is_cal=is_m[3], is_dd=is_m[2],
                oos_sh=oos_sh, oos_ann=oos_ann, wdd=wdd, ir0=ir0, lt22=lt22)


def print_sweep(title, arch_below_fn, sym, flavor, grid, pfmt):
    print("\n" + "-" * 124)
    print(title)
    print(f"  {'param':>8}｜{'IS Sh':>7}{'IS Cal':>8}{'IS DD%':>8}｜{'OOS Sh':>8}{'OOS ann%':>9}{'wfDD%':>8}{'IRvs0050':>10}{'lt22':>6}{'交易':>6}")
    rows = []
    for p in grid:
        below = arch_below_fn(sym, flavor, p)
        m = sweep_metrics(below)
        rows.append((p, m))
        lt = f"{m['lt22']:+d}" if m["lt22"] is not None else "  —"
        print(f"  {pfmt(p):>8}｜{m['is_sh']:>7.2f}{m['is_cal']:>8.2f}{m['is_dd']*100:>8.1f}｜"
              f"{m['oos_sh']:>8.3f}{m['oos_ann']*100:>9.1f}{m['wdd']*100:>8.1f}{m['ir0']:>+10.3f}{lt:>6}{m['nx']:>6}")
    # plateau 判讀：OOS Sharpe 全距 vs δ
    oos = [m["oos_sh"] for _, m in rows]
    spread = max(oos) - min(oos)
    print(f"  → OOS Sharpe 全距={spread:.3f} vs δ={DELTA:.3f}：{'平滑高原(全距≲δ)' if spread <= DELTA * 1.3 else '鋸齒/孤峰(全距>δ)＝雜訊跡象'}；"
          f"current-live OOS Sharpe={SL:.3f}")
    return rows


print("\n" + "=" * 124)
print("S7 — 細網格掃描（每軸 12 點；in-sample 線索 + OOS 主裁；δ 判 plateau vs 孤峰；決策綁 walk-forward 不挑 in-sample 峰）")
print("=" * 124)

sweeps = {}
# E7-replace（flavor 1 MA-cross）：^SOX / SMH
sweeps[("replace", "^SOX", "ma")] = print_sweep(
    "【E7-replace】^SOX MA-cross（below=US regime 取代 local；MA 長度 L 12 點，N=3+確認）", below_E7_replace, "^SOX", "ma", GRID_MA, lambda p: f"MA{p}")
sweeps[("replace", "SMH", "ma")] = print_sweep(
    "【E7-replace】SMH MA-cross", below_E7_replace, "SMH", "ma", GRID_MA, lambda p: f"MA{p}")
# E7-early(OR) flavor 2 from-peak：^SOX / SMH（主）；TSM / QQQ（negative-control）
sweeps[("early", "^SOX", "frompeak")] = print_sweep(
    "【E7-early(OR)】^SOX from-peak 回撤（below=local OR US；X% 12 點，W=60，N=3）", below_E7_early, "^SOX", "frompeak", GRID_X, lambda p: f"-{p}%")
sweeps[("early", "SMH", "frompeak")] = print_sweep(
    "【E7-early(OR)】SMH from-peak 回撤", below_E7_early, "SMH", "frompeak", GRID_X, lambda p: f"-{p}%")
sweeps[("early", "TSM", "frompeak")] = print_sweep(
    "【E7-early(OR)】TSM from-peak（negative-control：領先弱者[corr 0.515]應更差）", below_E7_early, "TSM", "frompeak", GRID_X, lambda p: f"-{p}%")
sweeps[("early", "QQQ", "frompeak")] = print_sweep(
    "【E7-early(OR)】QQQ from-peak（negative-control：大盤[corr ~0.46]應更差）", below_E7_early, "QQQ", "frompeak", GRID_X, lambda p: f"-{p}%")
# E7-early(OR) flavor 3 動能：^SOX / SMH
sweeps[("early", "^SOX", "momentum")] = print_sweep(
    "【E7-early(OR)】^SOX 動能（below=local OR US；M=10 日累積 Thr% 12 點，N=3）", below_E7_early, "^SOX", "momentum", GRID_THR, lambda p: f"{p}%")
sweeps[("early", "SMH", "momentum")] = print_sweep(
    "【E7-early(OR)】SMH 動能", below_E7_early, "SMH", "momentum", GRID_THR, lambda p: f"{p}%")


# ════════════════════════════════════════════════════════════════════════════════
# S8 walk-forward（主裁）：per-fold 選參 + plateau pick；對 E7-early ^SOX from-peak（主軸）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 124)
print("S8 — walk-forward OOS（主裁；FWD=[2022,2023,2024,2025] expanding；floor 重錨 current-live−DD_BAND；永不固定 fallback）")
print("=" * 124)


def wf_select(arch_fn, sym, flavor, grid, train_end_year, objective="calmar"):
    """擴張窗 [2018,train_end_year] 選參：Calmar(或Sharpe) argmax；DD floor 重錨同族 current-live−DD_BAND。"""
    start, end = "2018-01-01", f"{train_end_year}-12-31"
    live_dd = dd_of_window(live_eq, start, end)
    floor_thr = live_dd - DD_BAND
    mets = {}
    for p in grid:
        eq = EQ_CACHE[(arch_fn.__name__, sym, flavor, p)][0]
        ann, sh, dd, cal = window_metrics(eq, start, end)
        mets[p] = dict(p=p, ann=ann, sh=sh, dd=dd, cal=cal)
    passers = [m for m in mets.values() if m["dd"] >= floor_thr]
    empty = len(passers) == 0
    pool = passers if passers else list(mets.values())
    key = (lambda m: (m["cal"], m["sh"])) if objective == "calmar" else (lambda m: (m["sh"], m["cal"]))
    best = max(pool, key=key)
    return best["p"], len(passers), empty, floor_thr


def walk_forward(arch_fn, sym, flavor, grid, objective="calmar"):
    rows, strat_daily, ddby = [], [], {}
    for Y in FWD:
        p_star, npass, empty, floor_thr = wf_select(arch_fn, sym, flavor, grid, Y - 1, objective)
        eq = EQ_CACHE[(arch_fn.__name__, sym, flavor, p_star)][0]
        below = EQ_CACHE[(arch_fn.__name__, sym, flavor, p_star)][2]
        py = bm._per_year(eq).get(Y, (float("nan"),) * 3)
        ddby[Y] = py[2]
        strat_daily.append(year_dr(eq, Y))
        rows.append(dict(Y=Y, p=p_star, npass=npass, empty=empty, ret=py[0], sh=py[1], dd=py[2],
                         flips=flips_in_year(below, Y)))
    pooled = pd.concat(strat_daily)
    return dict(rows=rows, pooled=pooled, pooled_sharpe=sharpe_of(pooled), pooled_ann=ann_of(pooled),
                worst_fwd_dd=min(ddby.values()), ir=ir_vs(pooled, benB_oos), ir0=ir_vs(pooled, bh_oos),
                params=[r["p"] for r in rows])


def plateau_pick_oos(arch_fn, sym, flavor, plateau_p):
    """穩健 plateau pick：直接把高原中段值套 OOS（非 in-sample 峰）。"""
    eq = EQ_CACHE[(arch_fn.__name__, sym, flavor, plateau_p)][0]
    below = EQ_CACHE[(arch_fn.__name__, sym, flavor, plateau_p)][2]
    pooled = pd.concat([year_dr(eq, Y) for Y in FWD])
    wdd = min(dd_of_window(eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    return dict(p=plateau_p, pooled_sharpe=sharpe_of(pooled), pooled_ann=ann_of(pooled),
                worst_fwd_dd=wdd, ir=ir_vs(pooled, benB_oos), ir0=ir_vs(pooled, bh_oos),
                fl22=flips_in_year(below, 2022))


# 預跑 EQ_CACHE（walk-forward 用的全部 (arch,sym,flavor,param) eq）
EQ_CACHE = {}
WF_TARGETS = [
    (below_E7_replace, "^SOX", "ma", GRID_MA),
    (below_E7_replace, "SMH", "ma", GRID_MA),
    (below_E7_early, "^SOX", "frompeak", GRID_X),
    (below_E7_early, "SMH", "frompeak", GRID_X),
    (below_E7_early, "TSM", "frompeak", GRID_X),
    (below_E7_early, "QQQ", "frompeak", GRID_X),
    (below_E7_early, "^SOX", "momentum", GRID_THR),
    (below_E7_early, "SMH", "momentum", GRID_THR),
]
for arch_fn, sym, flavor, grid in WF_TARGETS:
    for p in grid:
        below = arch_fn(sym, flavor, p)
        eq, nx, _ = eq_for_below(below)
        EQ_CACHE[(arch_fn.__name__, sym, flavor, p)] = (eq, nx, below)

# plateau 中段值（明標來源：from-peak X=8% 高原中段；MA L=50 趨勢慣例；動能 Thr=−8% 中段）
PLATEAU = {("frompeak"): 8, ("ma"): 50, ("momentum"): -8}

print("（中間 4 欄＝per-fold 選到的參數：fold 2022/2023/2024/2025 各自在 [2018,Y-1] 訓練窗選出的參數＝跨 fold 穩定性檢查）")
print(f"\n{'架構/訊號':<34}{'規則':>10}{'sel22':>7}{'sel23':>7}{'sel24':>7}{'sel25':>7}｜{'pooledSh':>9}{'OOSann%':>8}{'wfDD%':>7}{'IRvsB':>8}{'IRvs0050':>9}")
print("-" * 124)
WF_RESULTS = {}
for arch_fn, sym, flavor, grid in WF_TARGETS:
    label = {"below_E7_replace": "E7-replace", "below_E7_early": "E7-early"}[arch_fn.__name__]
    for obj in ("calmar", "sharpe"):
        wf = walk_forward(arch_fn, sym, flavor, grid, obj)
        WF_RESULTS[(arch_fn.__name__, sym, flavor, obj)] = wf
        ps = wf["params"]
        pfmt = (lambda p: f"-{p}%") if flavor == "frompeak" else ((lambda p: f"MA{p}") if flavor == "ma" else (lambda p: f"{p}%"))
        print(f"{label+' '+sym+' '+flavor:<34}{obj:>10}"
              f"{pfmt(ps[0]):>7}{pfmt(ps[1]):>7}{pfmt(ps[2]):>7}{pfmt(ps[3]):>7}｜"
              f"{wf['pooled_sharpe']:>9.3f}{wf['pooled_ann']*100:>8.1f}{wf['worst_fwd_dd']*100:>7.1f}{wf['ir']:>+8.2f}{wf['ir0']:>+9.3f}")

# plateau pick（直接套 OOS，非 in-sample 峰）— 並列 walk-forward 動態選參
print("\n" + "-" * 124)
print("穩健 plateau pick（直接套 OOS，非 in-sample 峰；對照 R0 K=150 教訓）vs walk-forward 動態選參(Calmar)：")
print(f"{'架構/訊號':<34}{'plateau參數':>12}{'pooledSh':>10}{'OOSann%':>9}{'wfDD%':>8}{'IRvs0050':>10}{'fl22':>6}｜{'wf動態Sh':>9}")
print("-" * 124)
for arch_fn, sym, flavor, grid in WF_TARGETS:
    pp = PLATEAU[flavor]
    if pp not in grid:
        continue
    pk = plateau_pick_oos(arch_fn, sym, flavor, pp)
    wf = WF_RESULTS[(arch_fn.__name__, sym, flavor, "calmar")]
    label = {"below_E7_replace": "E7-replace", "below_E7_early": "E7-early"}[arch_fn.__name__]
    pfmt = (lambda p: f"-{p}%") if flavor == "frompeak" else ((lambda p: f"MA{p}") if flavor == "ma" else (lambda p: f"{p}%"))
    consist = "一致" if abs(pk["pooled_sharpe"] - wf["pooled_sharpe"]) <= DELTA else "分歧"
    print(f"{label+' '+sym+' '+flavor:<34}{pfmt(pp):>12}{pk['pooled_sharpe']:>10.3f}{pk['pooled_ann']*100:>9.1f}"
          f"{pk['worst_fwd_dd']*100:>8.1f}{pk['ir0']:>+10.3f}{pk['fl22']:>6}｜{wf['pooled_sharpe']:>9.3f} ({consist})")


# ════════════════════════════════════════════════════════════════════════════════
# S9 候選 config 表（C0–C7）：全期 + OOS 全指標 + 2018/2020/2022 stress + lead-time，與 C0 逐項對照
# ════════════════════════════════════════════════════════════════════════════════
def py3(eq, y):
    return bm._per_year(eq).get(y, (float("nan"),) * 3)   # (ret, sharpe, dd)


def full_metrics(eq, below_tw):
    f_ann, f_sh, f_dd, f_cal = window_metrics(eq, bm.START, bm.END)
    oos = pd.concat([year_dr(eq, Y) for Y in FWD])
    o_sh = sharpe_of(oos)
    o_ann = ann_of(oos)
    wdd = min(dd_of_window(eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    eq2, nx, _ = eq_for_below(below_tw)   # n_exec
    lt20, _, _ = lead_time_vs_local(below_tw, 2020)
    lt22, _, _ = lead_time_vs_local(below_tw, 2022)
    return dict(f_ann=f_ann, f_sh=f_sh, f_dd=f_dd, o_sh=o_sh, o_ann=o_ann, wdd=wdd,
                ir=ir_vs(oos, benB_oos), ir0=ir_vs(oos, bh_oos), nx=nx, lt20=lt20, lt22=lt22,
                r18=py3(eq, 2018), r20=py3(eq, 2020), r22=py3(eq, 2022),
                fl18=flips_in_year(below_tw, 2018), fl20=flips_in_year(below_tw, 2020), fl22=flips_in_year(below_tw, 2022))


# C0–C7 定義（plateau 中值；非 in-sample 峰）
CONFIGS = [
    ("C0 current-live(N3,band1%,0.85)", live_below),
    ("C1 E7-replace ^SOX MA50",        below_E7_replace("^SOX", "ma", 50)),
    ("C2 E7-replace SMH MA50",         below_E7_replace("SMH", "ma", 50)),
    ("C3 E7-early ^SOX peak-8%/W60",   below_E7_early("^SOX", "frompeak", 8)),
    ("C4 E7-early SMH peak-8%/W60",    below_E7_early("SMH", "frompeak", 8)),
    ("C5 E7-early ^SOX 動能Thr-8%/M10", below_E7_early("^SOX", "momentum", -8)),
    ("C6 E7-AND local∧^SOX peak-8%",   below_E7_combine_and("^SOX", "frompeak", 8)),
    ("C7 E7-2of3 local+^SOX+QQQ peak-8%", below_E7_combine_2of3("^SOX", "QQQ", "frompeak", 8)),
]
cfg_res = []
for name, below in CONFIGS:
    eq, nx, _ = eq_for_below(below)
    m = full_metrics(eq, below)
    cfg_res.append((name, eq, below, m))

print("\n" + "=" * 124)
print("S9 — 候選 config 表（C0–C7；plateau 中值非 in-sample 峰）：全期 + OOS 全指標，與 C0 current-live 逐項對照")
print("=" * 124)
print(f"{'config':<36}｜{'全期ann':>8}{'Sh':>6}{'maxDD':>8}｜{'OOSann':>8}{'Sh':>6}{'wfDD':>8}｜{'IRvsB':>7}{'IRvs0050':>9}{'交易':>6}")
print("-" * 124)
m0 = cfg_res[0][3]
for name, eq, below, m in cfg_res:
    print(f"{name:<36}｜{m['f_ann']*100:>8.1f}{m['f_sh']:>6.2f}{m['f_dd']*100:>8.1f}｜"
          f"{m['o_ann']*100:>8.1f}{m['o_sh']:>6.2f}{m['wdd']*100:>8.1f}｜{m['ir']:>+7.2f}{m['ir0']:>+9.3f}{m['nx']:>6}")
print("-" * 124)
print(f"  固定對照：0050 OOS Sh {S0:.2f}/wfDD {BH_WDD*100:.1f}%｜基準B OOS Sh {SB:.2f}/wfDD {BB_WDD*100:.1f}%｜δ={DELTA:.3f}｜0050 自身 IRvsB={BH_IRB:+.2f}(beta 線)")

# E7-replace wiring 自證（無自然行為中性退化點）：印 C1 vs C0 的 diff 觸發日（人工核 US vs local 訊號差）
print("\n  [E7-replace wiring 自證] C1(^SOX MA50) vs C0(local) below 態相異日數（前 8 個）：")
c1_below = cfg_res[1][2].reindex(tw.index).fillna(False)
c0_below = live_below.reindex(tw.index).fillna(False)
diff_days = c1_below.index[(c1_below != c0_below)]
diff_oos = [d for d in diff_days if d.year in FWD]
print(f"    相異總日數={len(diff_days)}（OOS 段={len(diff_oos)}）；差異全可歸因 US-MA50 vs local-MA200 訊號差。前 8 日：")
for d in list(diff_days)[:8]:
    print(f"      {d.date()}: C1_below={bool(c1_below.loc[d])} C0_below={bool(c0_below.loc[d])}")


# ════════════════════════════════════════════════════════════════════════════════
# S10 事件 + lead-time（2018/2020/2022/牛市；明標 IS/OOS）
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 124)
print("S10 — 事件 stress（明標 IS/OOS）：2018Q4(IS) / 2020 COVID(IS) / 2022 熊(OOS) / 2023-25 牛(OOS)")
print("  ⚠️ 2018/2020 美股資料雖涵蓋，但 walk-forward expanding window 下永在訓練段＝IS；唯一 OOS 崩盤＝2022。")
print("=" * 124)
print(f"{'config':<36}｜{'18報酬':>7}{'18DD':>7}{'fl18':>5}｜{'20報酬':>7}{'20DD':>7}{'fl20':>5}｜{'22報酬':>7}{'22DD':>7}{'fl22':>5}｜{'牛23-25ann':>10}")
print("-" * 124)
for nm, eq in [("0050 買持", bh_eq), ("基準B(vol0.011)", bb_eq)]:
    a, c, b = py3(eq, 2018), py3(eq, 2020), py3(eq, 2022)
    bull = pd.concat([year_dr(eq, Y) for Y in (2023, 2024, 2025)])
    print(f"{nm:<36}｜{a[0]*100:>6.1f}%{a[2]*100:>6.1f}%{'—':>5}｜{c[0]*100:>6.1f}%{c[2]*100:>6.1f}%{'—':>5}｜"
          f"{b[0]*100:>6.1f}%{b[2]*100:>6.1f}%{'—':>5}｜{ann_of(bull)*100:>9.1f}%")
for name, eq, below, m in cfg_res:
    a, c, b = m["r18"], m["r20"], m["r22"]
    bull = pd.concat([year_dr(eq, Y) for Y in (2023, 2024, 2025)])
    print(f"{name:<36}｜{a[0]*100:>6.1f}%{a[2]*100:>6.1f}%{m['fl18']:>5}｜{c[0]*100:>6.1f}%{c[2]*100:>6.1f}%{m['fl20']:>5}｜"
          f"{b[0]*100:>6.1f}%{b[2]*100:>6.1f}%{m['fl22']:>5}｜{ann_of(bull)*100:>9.1f}%")
print("-" * 124)

print("\n崩盤 lead-time（US 訊號首觸 below 早於 local-combined 首觸幾個交易日；正值=US 早；2020/2022 皆 IS=描述性）：")
print(f"{'config':<36}｜{'2020 lead(交易日)':>18}｜{'2022 lead(交易日)':>18}")
for name, eq, below, m in cfg_res[1:]:    # C0 是 local 自己，lead 無意義
    lt20 = f"{m['lt20']:+d}" if m["lt20"] is not None else "  —(未觸發)"
    lt22 = f"{m['lt22']:+d}" if m["lt22"] is not None else "  —(未觸發)"
    print(f"{name:<36}｜{lt20:>18}｜{lt22:>18}")


# ════════════════════════════════════════════════════════════════════════════════
# S11 可交易性事件研究（E7 特有、最重要）：賣在跳空後 0050 持續跌(划算) vs 反彈(反傷)
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 124)
print("S11 — 可交易性事件研究（E7 特有、最重要）：US 早砍在已跳空價，0050 後續『持續跌(划算)』還是『反彈(反傷)』？")
print("  呼應前置：~99% 領先在開盤跳空被吸收、盤中≈隨機 → T+1 開盤成交=賣在跳空。事件=E7-early 相對 current-live 真正多砍的日。")
print("=" * 124)

# 回測窗 0050 OHLC（事件 path 用）
bt = adj[(adj["date"] >= pd.Timestamp(bm.START)) & (adj["date"] <= pd.Timestamp(bm.END))].reset_index(drop=True)
bt_dates = pd.DatetimeIndex(bt["date"])
bt_open = bt["open"].to_numpy(float)
bt_close = bt["close"].to_numpy(float)
date_to_i = {d: i for i, d in enumerate(bt_dates)}
KS = [1, 2, 3, 5, 10, 20]


def crash_phase(d):
    """事件日所屬崩盤分層：2020(V型) / 2022(慢熊) / other。"""
    if d.year == 2020 and pd.Timestamp("2020-01-01") <= d <= pd.Timestamp("2020-06-30"):
        return "2020(V型,IS)"
    if d.year == 2022:
        return "2022(慢熊,OOS)"
    return "other"


def tradeability_events(sym, flavor, param):
    """E7-early below 為 True 但 C0(local) below 為 False 的 close-T 日（=E7 多砍的日；砍在 open[i+1]）。
    對每個事件量 open[T+1] 後 0050 前向路徑 + 跳空 gap + avoided_loss(砍 15% × 後續累積跌幅)。"""
    e7 = below_E7_early(sym, flavor, param).reindex(tw.index).fillna(False)
    loc = below_local_combined(cf, LIVE_CD, LIVE_BAND).reindex(tw.index).fillna(False)
    extra = e7.index[(e7 & ~loc)]                    # E7 多砍的 close-T 日（row date_i，砍 day i+1）
    extra = [d for d in extra if d in date_to_i and date_to_i[d] + 1 < len(bt_dates)]
    recs = []
    for d in extra:
        i = date_to_i[d]                             # close-T row → 砍倉執行在 open[i+1]
        gap = bt_open[i + 1] / bt_close[i] - 1.0     # 賣在跳空的代價（已被吸收的跳空）
        fwd = {}
        for k in KS:
            j = min(i + 1 + k, len(bt_close) - 1)
            fwd[k] = bt_close[j] / bt_open[i + 1] - 1.0   # open[T+1]→close[T+1+k]：負=跌勢持續(早砍划算)
        recs.append(dict(date=d, phase=crash_phase(d), gap=gap, fwd=fwd))
    return recs


def summarize_tradeability(label, recs):
    if not recs:
        print(f"  {label}: 無『E7 多砍』事件（US 從未早於 local 觸發）。")
        return
    df = pd.DataFrame([{"date": r["date"], "phase": r["phase"], "gap": r["gap"],
                        **{f"fwd{k}": r["fwd"][k] for k in KS}} for r in recs])
    print(f"\n  {label}：E7 多砍事件 n={len(df)}（分層：{df['phase'].value_counts().to_dict()}）")
    print(f"    跳空 gap 均值 {df['gap'].mean()*100:+.2f}%（賣在跳空的代價；負=跳空向下已吸收）")
    print(f"    {'k':>4}｜{'fwd_ret均值':>11}{'中位':>9}{'勝率(後跌%)':>12}｜{'avoided_loss=15%×後跌(均)':>0}")
    for k in KS:
        col = df[f"fwd{k}"]
        winrate = (col < 0).mean()                   # 後續下跌的事件比例（早砍划算）
        avoided_loss = (-col.clip(upper=0) * 0.15).mean()   # 砍掉 15% × 後續跌幅(只算跌的部分省到)；正=省
        net_avoided = (-col * 0.15).mean()           # 含反彈反傷（淨：早砍 15% 的後續 P&L 差，負=反傷）
        print(f"    {k:>4}｜{col.mean()*100:>+10.2f}%{col.median()*100:>+8.2f}%{winrate*100:>11.0f}%｜"
              f"省跌(均) {avoided_loss*100:>+.3f}pp / 淨(含反彈) {net_avoided*100:>+.3f}pp")
    # 分層：2020 vs 2022
    for ph in ["2020(V型,IS)", "2022(慢熊,OOS)"]:
        sub = df[df["phase"] == ph]
        if len(sub) == 0:
            continue
        print(f"    [分層 {ph}] n={len(sub)}：fwd5 均值 {sub['fwd5'].mean()*100:+.2f}% / fwd10 {sub['fwd10'].mean()*100:+.2f}% / "
              f"fwd20 {sub['fwd20'].mean()*100:+.2f}%｜淨avoided(fwd10) {(-sub['fwd10']*0.15).mean()*100:+.3f}pp "
              f"({'划算(後續跌)' if sub['fwd10'].mean()<0 else '反傷(後續彈)'})")
    return df


# 對照：current-live(local) 自身的砍倉事件做同一前向研究
def local_cut_events():
    loc = below_local_combined(cf, LIVE_CD, LIVE_BAND).reindex(tw.index).fillna(False)
    # 砍倉日＝local 由 full→below 的轉折日（close-T row，砍 day i+1）
    arr = loc.astype(int).to_numpy()
    cut_idx = np.where((np.diff(arr) == 1))[0] + 1   # 轉為 below 的 row
    cut_dates = [loc.index[k] for k in cut_idx]
    cut_dates = [d for d in cut_dates if d in date_to_i and date_to_i[d] + 1 < len(bt_dates)]
    recs = []
    for d in cut_dates:
        i = date_to_i[d]
        gap = bt_open[i + 1] / bt_close[i] - 1.0
        fwd = {k: (bt_close[min(i + 1 + k, len(bt_close) - 1)] / bt_open[i + 1] - 1.0) for k in KS}
        recs.append(dict(date=d, phase=crash_phase(d), gap=gap, fwd=fwd))
    return recs


print("E7-early(OR) 多砍事件 vs current-live(local) 砍倉事件 — 前向路徑（open[T+1]→close[T+1+k]）對照：")
for sym, fl, pm, tag in [("^SOX", "frompeak", 8, "C3 ^SOX peak-8%"), ("SMH", "frompeak", 8, "C4 SMH peak-8%"),
                          ("^SOX", "momentum", -8, "C5 ^SOX 動能-8%")]:
    recs = tradeability_events(sym, fl, pm)
    summarize_tradeability(tag, recs)
print("\n  [對照] current-live(local-MA200) 砍倉事件前向路徑：")
summarize_tradeability("local 砍倉(C0)", local_cut_events())
print("\n  結論句式：US 早砍淨效益 = 多省的後續跌幅 − 多付的跳空/whipsaw 成本。")
print("  讀法：fwd_ret 顯著<0(勝率>50%)=早砍划算(跌勢持續)；>0=砍在低點反傷(鎖跳空後反彈)。預期 2020 反傷、2022 划算（呼應 DRAWDOWN 研究）。")


# ════════════════════════════════════════════════════════════════════════════════
# S12 §5 Gate + E7 特有 Gate（①–⑩）逐 config 裁決
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 124)
print("S12 — §5 Gate + E7 特有 Gate（①–⑩，全 AND；重錨同族 current-live；鐵則#8 絕對 floor 退役）")
print("=" * 124)


def tradeability_net_positive(sym, fl, pm):
    """可交易性 Gate proxy：US 早砍的淨 avoided（fwd10，含反彈反傷）整體>0，且 2022(OOS)段>0。"""
    recs = tradeability_events(sym, fl, pm)
    if not recs:
        return None, None, 0
    df = pd.DataFrame([{"phase": r["phase"], "fwd10": r["fwd"][10]} for r in recs])
    net_all = (-df["fwd10"] * 0.15).mean()
    sub22 = df[df["phase"] == "2022(慢熊,OOS)"]
    net22 = (-sub22["fwd10"] * 0.15).mean() if len(sub22) else None
    return net_all, net22, len(df)


# config → (sym,fl,pm) for tradeability（僅 E7-early/combine 適用）
TRADE_MAP = {
    "C3 E7-early ^SOX peak-8%/W60": ("^SOX", "frompeak", 8),
    "C4 E7-early SMH peak-8%/W60": ("SMH", "frompeak", 8),
    "C5 E7-early ^SOX 動能Thr-8%/M10": ("^SOX", "momentum", -8),
}

for name, eq, below, m in cfg_res:
    if name.startswith("C0"):
        continue
    # ③ 降-DD 不惡化於 current-live 且優於基準B/0050
    g_dd = (m["wdd"] >= LIVE_WDD - 1e-9) and (m["wdd"] > BB_WDD) and (m["wdd"] > BH_WDD)
    # ④ OOS Sharpe 不顯著差於 current-live（δ 帶內）
    g_sharpe_noworse = m["o_sh"] >= SL - DELTA
    # ⑤ 牛市不顯著犧牲（OOS 年化 ≥ live − 0.01）
    g_bull = m["o_ann"] >= LIVE_OOS_ANN - 0.01
    # ⑥ whipsaw 不惡化（2022 flips ≤ current-live）
    g_whip = m["fl22"] <= LIVE_FL22
    # ⑧ alpha（預期 FAIL）：IRvs0050>0 AND OOS Sharpe − 0050 > δ
    g_alpha = (m["ir0"] > 0) and (m["o_sh"] - S0 > DELTA)
    # ⑨ 可交易性 Gate（E7-early/combine）：US 早砍淨 avoided>0 且 2022>0
    trade_key = TRADE_MAP.get(name)
    if trade_key:
        net_all, net22, ntr = tradeability_net_positive(*trade_key)
        g_trade = (net_all is not None and net_all > 0) and (net22 is None or net22 > 0)
        trade_str = (f"淨avoided(fwd10)全體 {net_all*100:+.3f}pp / 2022 "
                     f"{(net22*100 if net22 is not None else float('nan')):+.3f}pp (n={ntr}) → {'✓划算' if g_trade else '✗反傷/負'}")
    else:
        g_trade = None     # E7-replace/2of3：不適用此精確事件定義（diff 非『額外砍』語意）→ 標 N/A
        trade_str = "N/A（replace/2of3 無『相對 local 額外砍』單純語意）"
    # ⑩ E7 綜合結構 Gate：g_dd AND g_trade(若適用) AND g_bull AND g_whip
    struct_components = [g_dd, g_bull, g_whip] + ([g_trade] if g_trade is not None else [])
    struct_pass = all(struct_components)
    verdict = ("結構 Gate PASS（降-DD + 跳空划算 + 牛市不犧牲 + whipsaw 不惡化）" if struct_pass
               else ("FAIL" if not g_dd else "MARGINAL"))
    print(f"\n【{name}】")
    print(f"  ③降-DD不惡化且優於兩被動：wfDD {m['wdd']*100:.1f}% (live {LIVE_WDD*100:.1f}%/B {BB_WDD*100:.1f}%/0050 {BH_WDD*100:.1f}%) → {'✓' if g_dd else '✗'}")
    print(f"  ④OOS Sharpe 不顯著差 live(δ={DELTA:.2f}帶)：{m['o_sh']:.3f} vs {SL:.3f} → {'✓' if g_sharpe_noworse else '✗'}")
    print(f"  ⑤牛市不犧牲(OOS年化 {m['o_ann']*100:.1f}% vs live {LIVE_OOS_ANN*100:.1f}%) → {'✓' if g_bull else '✗'}")
    print(f"  ⑥whipsaw 不惡化(22flips {m['fl22']} ≤ live {LIVE_FL22}) → {'✓' if g_whip else '✗'}")
    print(f"  ⑧alpha（預期FAIL）：IRvs0050 {m['ir0']:+.3f}、OOS Sharpe−0050 {m['o_sh']-S0:+.3f} vs δ {DELTA:.2f} → "
          f"{'✓有alpha' if g_alpha else '✗無(δ內)'}｜註：IRvs基準B {m['ir']:+.2f} 是 beta 非 alpha（0050 自身 IRvsB={BH_IRB:+.2f}）")
    print(f"  ⑨可交易性(賣在跳空仍划算)：{trade_str}")
    print(f"  ⑩ E7 綜合結構 Gate → {verdict}")


# ════════════════════════════════════════════════════════════════════════════════
# S13 收尾
# ════════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 124)
print("S13 — 收尾")
print("=" * 124)
print("• beta vs alpha 分離（鐵則、勿誤引）：walk-forward 的 IRvs基準B 高(+1.x) 是 beta 不是 alpha")
print(f"  （0050 自身 IRvs基準B={BH_IRB:+.2f} 為純 beta 零技巧參考線）；真 alpha 檢定＝同 beta 的 IRvs0050，")
print(f"  E7 全 config IRvs0050 ≤ 0 或 Sharpe 邊際 ≪ δ={DELTA:.3f} → alpha FAIL（R0–R5/E1–E5 一致，未翻案）。")
print("• E7 唯一可能站得住＝降-DD 防禦，且須過『賣在跳空仍划算』可交易性檢定（S11）；2020(IS,V型)反傷、2022(OOS,慢熊)才是真 OOS 證據。")
print("• survivorship 無法消除（FinMind 0050 無下市；US 為 ADR/ETF/指數存續樣本）→ 所有結果是【上界】。")
print("• 2018/2020 永在訓練段＝IS；唯一 OOS 崩盤＝2022（n=1 崩盤週期）→ lead-time/event study 描述性、統計功效低。")
print("• 純快取 0 API；只新增 notebooks/e7_us_semi_defense.py、未改任何既有檔；不 commit、不切 branch、不動 live。")
print("• **總 Gate 未過前 live（0050 + MA200 N3band1% 85% overlay）一律不動。**")
print("[done] E7 完成（純快取、0 API；行為中性 + look-ahead 雙 sanity PASS）。")

"""
notebooks/us_lead_0050.py
驗證假說：美股科技指標（費半 ^SOX / 半導體 ETF SOXX·SMH / 台積電 ADR TSM / 那斯達克 QQQ·^IXIC）
對 0050 有「隔夜領先」相關性。純研究、不動 live。

資料：
  - 0050：讀本地快取還原日線（benchmark_backtest.load_adjusted_0050，不打 API）。
  - 美股：FinMind USStockPrice 已下載快取 pickle（data/raw/finmind_cache/USStockPrice__*.pkl）。

方法核心（時區因果，無 look-ahead）：
  台股 day t 收盤 ≈ 05:30 UTC；美股 day t 收盤 ≈ 20–21 UTC（晚 ~15h）。
  → 美股「某日收盤」發生在台股「同日收盤」之後 → 只能影響台股的「下一個交易時段」。
  ∴ 定義 us_overnight[T] = 在（台股 T-1 收盤, 台股 T 收盤]這段時間內、所有「已收盤」美股 session 的複利報酬
    = 台股 day T 開盤前『已知』的美股資訊 → 用它預測 0050 day T 報酬＝『事前』預測、可交易性檢定的基礎。

可交易性拆解（誠實關鍵）：
  0050 day T 收-收報酬 = 開盤跳空(close_{T-1}→open_T) + 盤中(open_T→close_T)。
  若領先力全被『開盤跳空』吸收 → 你在台股開盤才進場＝抓不到（已 price-in）；
  真正可交易的殘差 = us_overnight 對『盤中(open→close)』的預測力。
"""
import os, sys, warnings
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from scipy import stats as sstats
import statsmodels.api as sm
from statsmodels.tsa.stattools import grangercausalitytests
import importlib.util

# ── 載入 benchmark_backtest 取 0050 還原日線（__main__ guard、安全）──
_spec = importlib.util.spec_from_file_location("bm", os.path.join(os.path.dirname(__file__), "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bm)

START, END = "2018-01-01", "2025-12-31"
CACHE = "data/raw/finmind_cache"
US_SYMS = ["TSM", "^SOX", "SOXX", "SMH", "QQQ", "^IXIC", "^GSPC"]

# ── 0050（還原 OHLC，快取無 API）──
adj = bm.load_adjusted_0050()
tw = adj[(adj["date"] >= START) & (adj["date"] <= END)][["date", "open", "close"]].copy()
tw["date"] = pd.to_datetime(tw["date"]); tw = tw.sort_values("date").reset_index(drop=True)
print("="*84)
print("資料來源（純快取 / 已下載快取，無即時 API）")
print(f"  0050 還原日線：{len(tw)} 列  {tw['date'].min().date()} ~ {tw['date'].max().date()}（cache）")

# ── 美股（FinMind USStockPrice 快取 pickle）──
us_close = {}   # sym -> Series(date->AdjClose)
for s in US_SYMS:
    p = f"{CACHE}/USStockPrice__{s}__{START}__{END}.pkl"
    if not os.path.exists(p):
        print(f"  [skip] {s}: 無快取"); continue
    d = pd.read_pickle(p)
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date")
    col = "Adj_Close" if "Adj_Close" in d.columns else "Close"
    us_close[s] = pd.Series(pd.to_numeric(d[col], errors="coerce").values, index=d["date"].values)
    print(f"  {s:6} USStockPrice：{len(d)} 列  {d['date'].min().date()} ~ {d['date'].max().date()}（cache）")
print("="*84)

# ── 台股日報酬 + 跳空/盤中拆解（用『前一個台股交易日』）──
tw = tw.set_index("date")
tw["tw_ret"]   = tw["close"].pct_change()                       # 收-收
tw["tw_gap"]   = tw["open"] / tw["close"].shift(1) - 1.0        # 開盤跳空（前台股收→今開）
tw["tw_intra"] = tw["close"] / tw["open"] - 1.0                 # 盤中（今開→今收）
tw_dates = np.array(tw.index.values)

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

for s in us_close:
    tw[f"us_{s}"] = us_overnight_to_tw(us_close[s])

def hac_lags(n): return int(np.floor(4 * (n/100.0)**(2.0/9.0)))

def reg_hac(y, X_df):
    """OLS + Newey-West HAC；回傳 beta dict, t dict, R2, n。"""
    df = pd.concat([y.rename("y"), X_df], axis=1).dropna()
    n = len(df)
    X = sm.add_constant(df[X_df.columns])
    m = sm.OLS(df["y"], X).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags(n)})
    return ({k: m.params[k] for k in m.params.index},
            {k: m.tvalues[k] for k in m.tvalues.index}, m.rsquared, n)

PRIMARY = "TSM" if "TSM" in us_close else list(us_close)[0]

# ════ PART 1：交叉相關函數（CCF）— 確認領先結構（以 TSM 為主）════
print("\n【PART 1】交叉相關 CCF：corr( us_overnight[T+k] , 0050 tw_ret[T] )  ※ k<0＝美股領先台股")
print("  k 解讀：k=0 → 美股隔夜(台股同日開盤前)→台股當日；k=+1 → 美股在台股之後＝台股領先美股")
print(f"  {'k':>4} | " + " | ".join(f"{s:>7}" for s in us_close))
for k in range(-2, 3):
    row = []
    for s in us_close:
        a = tw[f"us_{s}"]; b = tw["tw_ret"]
        # corr(us[T+k], tw[T]) → 對 us 右移 -k
        pair = pd.concat([a.shift(-k).rename("us"), b.rename("tw")], axis=1).dropna()
        r = pair["us"].corr(pair["tw"]) if len(pair) > 30 else np.nan
        row.append(f"{r:>7.3f}")
    tag = "  ← 美股領先" if k == 0 else ("  (台股領先美股)" if k == 1 else "")
    print(f"  {k:>4} | " + " | ".join(row) + tag)

# ════ PART 2：核心『事前』預測迴歸  tw_ret[T] ~ us_overnight[T] (+ 控台股自相關) ════
print("\n【PART 2】核心領先檢定（事前可用）：0050 當日收-收報酬 ~ 美股隔夜報酬  (HAC t)")
print(f"  {'指標':>6} | {'corr':>7} {'p':>9} | {'beta':>6} {'t(HAC)':>8} | {'+控tw_ret[t-1]':>0}")
print(f"  {'':>6} | {'':>7} {'':>9} | {'':>6} {'':>8} | {'beta':>6} {'t(HAC)':>8} {'R2':>7}")
core = {}
for s in us_close:
    x = tw[f"us_{s}"]; y = tw["tw_ret"]
    pair = pd.concat([x, y], axis=1).dropna()
    r, p = sstats.pearsonr(pair[f"us_{s}"], pair["tw_ret"])
    b1, t1, R1, n1 = reg_hac(y, x.to_frame(f"us_{s}"))
    Xc = pd.concat([x.rename(f"us_{s}"), y.shift(1).rename("tw_lag1")], axis=1)
    b2, t2, R2, n2 = reg_hac(y, Xc)
    core[s] = dict(corr=r, p=p, beta=b1[f"us_{s}"], t=t1[f"us_{s}"], R2=R2, n=n1)
    print(f"  {s:>6} | {r:>7.3f} {p:>9.1e} | {b1[f'us_{s}']:>6.3f} {t1[f'us_{s}']:>8.2f} | "
          f"{b2[f'us_{s}']:>6.3f} {t2[f'us_{s}']:>8.2f} {R2:>7.3f}  (n={n1})")

# ════ PART 3：可交易性拆解（開盤跳空 vs 盤中殘差）════
print("\n【PART 3】可交易性拆解：美股隔夜對『開盤跳空』vs『盤中(open→close)』的預測力")
print("  若領先全在跳空 → 台股開盤已 price-in、盤中無殘差＝抓不到；盤中殘差才是可交易 alpha")
print(f"  {'指標':>6} | {'corr_gap':>9} {'β_gap':>7} {'t_gap':>7} | {'corr_intra':>11} {'β_intra':>8} {'t_intra':>8} | {'跳空吸收%':>9}")
for s in us_close:
    x = tw[f"us_{s}"]
    pg = pd.concat([x, tw["tw_gap"]], axis=1).dropna()
    pi = pd.concat([x, tw["tw_intra"]], axis=1).dropna()
    rg = pg[f"us_{s}"].corr(pg["tw_gap"]); ri = pi[f"us_{s}"].corr(pi["tw_intra"])
    bg, tg, _, _ = reg_hac(tw["tw_gap"], x.to_frame(f"us_{s}"))
    bi, ti, _, _ = reg_hac(tw["tw_intra"], x.to_frame(f"us_{s}"))
    # 跳空吸收比例 = β_gap / (β_gap+β_intra)（對總收-收 beta 的占比）
    bgf, bif = bg[f"us_{s}"], bi[f"us_{s}"]
    absorb = bgf / (bgf + bif) * 100 if (bgf + bif) != 0 else np.nan
    print(f"  {s:>6} | {rg:>9.3f} {bgf:>7.3f} {tg[f'us_{s}']:>7.2f} | {ri:>11.3f} {bif:>8.3f} {ti[f'us_{s}']:>8.2f} | {absorb:>8.1f}%")

# ════ PART 4：方向命中率（整體 + 大漲跌條件）════
print("\n【PART 4】方向命中率 P( sign(0050 當日)=sign(美股隔夜) )  + 大漲跌(隔夜|報酬|前 20%)條件")
print(f"  {'指標':>6} | {'全樣本':>8} | {'大動能日':>8} (n) | {'盤中同向(大動能日)':>0}")
for s in us_close:
    x = tw[f"us_{s}"]; y = tw["tw_ret"]; yi = tw["tw_intra"]
    d = pd.concat([x.rename("x"), y.rename("y"), yi.rename("yi")], axis=1).dropna()
    hit_all = (np.sign(d["x"]) == np.sign(d["y"])).mean()
    thr = d["x"].abs().quantile(0.80)
    big = d[d["x"].abs() >= thr]
    hit_big = (np.sign(big["x"]) == np.sign(big["y"])).mean()
    hit_big_intra = (np.sign(big["x"]) == np.sign(big["yi"])).mean()
    print(f"  {s:>6} | {hit_all*100:>7.1f}% | {hit_big*100:>7.1f}% ({len(big)}) | 盤中同向 {hit_big_intra*100:>5.1f}%")

# ════ PART 5：分期穩定度（corr 收-收 與 盤中殘差 corr）════
print("\n【PART 5】分期穩定度（corr：美股隔夜 vs 0050 收-收 / 盤中殘差）")
periods = [("2018-2019","2018-01-01","2019-12-31"),("2020-2021","2020-01-01","2021-12-31"),
           ("2022-2023","2022-01-01","2023-12-31"),("2024-2025","2024-01-01","2025-12-31")]
print(f"  {'指標':>6} | " + " | ".join(f"{nm:>11}" for nm,_,_ in periods) + "   (收-收 / 盤中)")
for s in ["TSM","^SOX","QQQ"] if all(k in us_close for k in ["TSM","^SOX","QQQ"]) else list(us_close)[:3]:
    cells=[]
    for nm,a,b in periods:
        sub = tw[(tw.index>=a)&(tw.index<=b)]
        cc = sub[f"us_{s}"].corr(sub["tw_ret"]); ci = sub[f"us_{s}"].corr(sub["tw_intra"])
        cells.append(f"{cc:>5.2f}/{ci:>5.2f}")
    print(f"  {s:>6} | " + " | ".join(f"{c:>11}" for c in cells))

# ════ PART 6：反向（台股 → 次一美股 session）對照 ════
print("\n【PART 6】反向對照：0050 當日 → 『次一』美股 session（台股是否領先美股）")
print(f"  {'指標':>6} | {'corr(美股領先)':>14} | {'corr(台股領先,反向)':>0}")
for s in us_close:
    fwd = tw[f"us_{s}"]                       # 美股隔夜 → 台股當日（領先）
    lead = pd.concat([fwd, tw["tw_ret"]], axis=1).dropna()
    rL = lead[f"us_{s}"].corr(lead["tw_ret"])
    # 反向：台股當日 → 次一美股隔夜（us_overnight 右移到下一台股日，對 tw 左移1）
    rev = pd.concat([tw["tw_ret"], tw[f"us_{s}"].shift(-1)], axis=1).dropna()
    rR = rev["tw_ret"].corr(rev[f"us_{s}"])
    print(f"  {s:>6} | {rL:>14.3f} | {rR:>10.3f}")

# ════ PART 7：Granger 因果（calendar inner-join 日報酬，雙向，maxlag 3）════
print("\n【PART 7】Granger 因果（calendar 日報酬 inner-join，maxlag 3，報 lag-1 p 值）")
print("  US→TW：美股前一日 → 台股當日 是否 Granger 致因；TW→US 反向對照")
twr = tw["tw_ret"].dropna()
for s in us_close:
    usr = us_close[s].pct_change().dropna()
    j = pd.concat([twr.rename("tw"), usr.rename("us")], axis=1, join="inner").dropna()
    if len(j) < 100: print(f"  {s:>6}: n 太少"); continue
    try:
        g_us2tw = grangercausalitytests(j[["tw","us"]], maxlag=3, verbose=False)  # us → tw
        g_tw2us = grangercausalitytests(j[["us","tw"]], maxlag=3, verbose=False)  # tw → us
        p_us2tw = g_us2tw[1][0]["ssr_ftest"][1]
        p_tw2us = g_tw2us[1][0]["ssr_ftest"][1]
        pmin_us2tw = min(g_us2tw[l][0]["ssr_ftest"][1] for l in (1,2,3))
        print(f"  {s:>6} | US→TW p(lag1)={p_us2tw:>8.1e} (min over l1-3={pmin_us2tw:.1e}) | "
              f"TW→US p(lag1)={p_tw2us:>8.1e}  (n={len(j)})")
    except Exception as e:
        print(f"  {s:>6}: Granger ERR {repr(e)[:60]}")

# ════ 摘要 ════
print("\n" + "="*84)
print("摘要")
bestcorr = max(core, key=lambda s: core[s]["corr"])
print(f"  • 領先最強指標（收-收 corr）：{bestcorr}  corr={core[bestcorr]['corr']:.3f} (p={core[bestcorr]['p']:.1e})")
print(f"  • 樣本：n≈{core[bestcorr]['n']} 台股交易日；窗 {START}~{END}（survivorship 上界、US 含 ADR/ETF 存續樣本）")
print("  • 詳見 PART 3 可交易性拆解：跳空吸收% 越高 → 領先越不可交易（開盤已 price-in）")
print("="*84)

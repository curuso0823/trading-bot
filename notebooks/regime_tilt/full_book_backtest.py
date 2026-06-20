"""
notebooks/regime_tilt/full_book_backtest.py
全 6 資產書整合回測 — M0(靜態不對稱帶寬) + M1(a=0.75 regime de-risk) + M2(雙確認 USD tilt) 逐層 ablation。
純快取、0 API、不碰 live/src/config。returns-based 月度+觸發再平衡模擬器(對 6 資產配置驗證足夠且乾淨)。

紀律:walk-forward OOS(FWD 2022-25)、固定基準 0050 買持、survivorship 上界、M1/M2 參數鎖定(非搜尋)。
caveats:0050 真資料;主動 00981A/00991A=擬合代理模型(active_etf_proxy_model_*.md：r=β·r0050+net_alpha/252
        (+ε~N(0,σ_idio)),β 1.10/1.05、net_alpha 2.2%/1.0%、σ_idio 7%/5%、資產級 DD 懲罰 −4/−2.5pp;<1yr);
        00864B 2019-10 上市前掛 MMF、配息資料僅 2025-08 後→用估計 coupon carry(報有/無兩版);MMF 常數 1.5%/yr;周轉成本近似。
"""
from __future__ import annotations
import os, sys, importlib.util
import numpy as np, pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NB = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(NB))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location("bm", os.path.join(ROOT, "notebooks", "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bm)
from src.strategy_engines.benchmark_engine import _regime_below

CACHE = os.path.join(ROOT, "data", "raw", "finmind_cache")
MACRO = os.path.join(ROOT, "data", "raw", "macro")
START, END = "2018-01-01", "2025-12-31"
SQRT252 = np.sqrt(252)
FWD = [2022, 2023, 2024, 2025]

TARGET = {"0050": 0.35, "00981A": 0.16, "00991A": 0.16, "00635U": 0.10, "00864B": 0.115, "MMF": 0.115}
COLS = list(TARGET)
EQUITY = ["0050", "00981A", "00991A"]
BANDS = {"0050": (0.31, 0.42), "00981A": (0.13, 0.23), "00991A": (0.125, 0.23),   # 00981A 上界 +7%（2026-06-19b，見 tw_rebalancing_rules §8）
         "00635U": (0.08, 0.15), "00864B": (0.10, 0.15), "MMF": (0.095, 0.145)}
# 主動 ETF 擬合代理(active_etf_proxy_model_00981A_00991A.md)：r = β·r0050 + net_alpha/252 (+ ε~N(0,σ_idio))
BETA = {"00981A": 1.10, "00991A": 1.05}
NET_ALPHA = {"00981A": 0.022, "00991A": 0.010}   # 年化淨 alpha(gross − fee)
IDIO = {"00981A": 0.07, "00991A": 0.05}          # 年化 idiosyncratic 殘差波動(MC 用)
DD_PEN = {"00981A": 0.04, "00991A": 0.025}       # 資產級額外 maxDD 懲罰(集中/換股風險，報告 caveat)
MMF_ANN = 0.015
COUPON_ANN = 0.028
TC = 0.002
SELL_FRAC = 0.60
A_DERISK = 0.75   # M1 鎖定深度

mmf_daily = (1 + MMF_ANN) ** (1 / 252) - 1
coupon_daily = (1 + COUPON_ANN) ** (1 / 252) - 1
alpha_daily = {k: v / 252 for k, v in NET_ALPHA.items()}
idio_daily = {k: v / SQRT252 for k, v in IDIO.items()}


# ───────── loaders (純快取) ─────────
def _load_close(fn):
    df = pd.read_pickle(os.path.join(CACHE, fn)).copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates("date")
    df = df[df["close"] > 0]
    return pd.Series(df["close"].astype(float).values, index=pd.DatetimeIndex(df["date"]))


adj0050 = bm.load_adjusted_0050()
cf0050 = adj0050.set_index("date")["close"].sort_index().astype(float)   # 還原 close（2016+）
r0050 = cf0050.pct_change()
c635 = _load_close("TaiwanStockPrice__00635U__2015-01-01__2026-06-30.pkl")
r635 = c635.pct_change()
c864 = _load_close("TaiwanStockPrice__00864B__2019-01-01__2026-06-30.pkl")
r864 = c864.pct_change()

cal = pd.DatetimeIndex([d for d in cf0050.index if pd.Timestamp(START) <= d <= pd.Timestamp(END)])


def build_returns(with_coupon=True, rng=None):
    """rng=None → deterministic(β+net_alpha,無 ε);傳入 Generator → 疊加 idiosyncratic 殘差(MC)。"""
    R = pd.DataFrame(index=cal)
    base = r0050.reindex(cal)
    R["0050"] = base
    for s in ("00981A", "00991A"):
        r = BETA[s] * base + alpha_daily[s]
        if rng is not None:
            r = r + pd.Series(rng.normal(0.0, idio_daily[s], len(cal)), index=cal)
        R[s] = r
    R["00635U"] = r635.reindex(cal)
    listed = cal >= pd.Timestamp("2019-10-18")
    b = r864.reindex(cal).to_numpy()
    b864 = np.where(listed, b, mmf_daily)
    if with_coupon:
        b864 = b864 + np.where(listed, coupon_daily, 0.0)
    R["00864B"] = b864
    R["MMF"] = mmf_daily
    return R.fillna(0.0)


# ───────── M1 regime (E1+E2 on 0050；causal，act T+1) ─────────
ma200 = cf0050.rolling(200).mean()
_regime_full = _regime_below(cf0050, ma200, confirm_days=3, band_pct=0.01)
regime_on = _regime_full.reindex(cal).fillna(False).shift(1).fillna(False)


# ───────── M2 dual-confirm CPI+Fed (causal，發布落後) ─────────
def _load_fred(fn, col):
    d = pd.read_csv(os.path.join(MACRO, fn))
    d.columns = ["date", col]
    d["date"] = pd.to_datetime(d["date"]); d[col] = pd.to_numeric(d[col], errors="coerce")
    return d.set_index("date")[col].dropna()


cpi = _load_fred("CPIAUCSL.csv", "CPI")
ff = _load_fred("FEDFUNDS.csv", "FF")
cpi_yoy = cpi / cpi.shift(12) - 1
cpi_3 = cpi_yoy - cpi_yoy.shift(3)          # YoY 近3月變化
ff_3 = ff - ff.shift(3)                      # 基金利率近3月變化
mreg = pd.Series(0, index=cpi_yoy.index, dtype=float)
mreg[(cpi_3 < 0) & (ff_3 < 0)] = -1          # 弱美元(CPI 降 且 Fed 寬鬆)
mreg[(cpi_3 >= 0) & (ff_3 >= 0)] = 1         # 強美元(CPI 黏/升 且 Fed 持/升)
mreg_conf = mreg.where(mreg == mreg.shift(1), 0.0)   # 連 2 月確認
mreg_conf = mreg_conf.shift(2).fillna(0.0)            # 發布落後 2 月(CPI~1mo + 安全)
_daily = mreg_conf.reindex(pd.date_range(cpi.index.min(), END, freq="D")).ffill()
usd_regime = _daily.reindex(cal).ffill().fillna(0.0)


# ───────── 目標權重(M0 帶寬 / M1 / M2) ─────────
def target_weights(w_drift, on, usd, use_m1, use_m2):
    if use_m1 and on:
        tw = dict(TARGET)
        freed = 0.0
        for s in EQUITY:
            new = TARGET[s] * A_DERISK
            freed += TARGET[s] - new
            tw[s] = new
        want_gold = TARGET["00635U"] + freed / 3.0
        gold = min(want_gold, BANDS["00635U"][1])
        tw["00635U"] = gold
        tw["MMF"] = TARGET["MMF"] + freed * 2.0 / 3.0 + (want_gold - gold)
        # 00864B 不變
    else:
        tw = {}
        for s in COLS:
            if s == "MMF":
                continue
            lo, hi = BANDS[s]; t = TARGET[s]; cur = w_drift[s]
            if cur > hi:
                tw[s] = cur - SELL_FRAC * (cur - t)
            elif cur < lo:
                tw[s] = t
            else:
                tw[s] = cur
        nonmmf = sum(tw.values())
        tw["MMF"] = max(1.0 - nonmmf, BANDS["MMF"][0])
    # M2 cash-only tilt（受硬地板/上限 clip）
    if use_m2 and usd != 0:
        if usd < 0:   # 弱美元：減 00864B、加 MMF
            shift = max(0.0, min(0.05, tw["00864B"] - BANDS["00864B"][0], BANDS["MMF"][1] - tw["MMF"]))
            tw["00864B"] -= shift; tw["MMF"] += shift
        else:         # 強美元：加 00864B、減 MMF
            shift = max(0.0, min(0.05, BANDS["00864B"][1] - tw["00864B"], tw["MMF"] - BANDS["MMF"][0]))
            tw["00864B"] += shift; tw["MMF"] -= shift
    tot = sum(tw.values())
    return {k: tw[k] / tot for k in COLS}


# ───────── 模擬器(returns-based；月初 或 regime/usd 變動才再平衡) ─────────
def simulate(R, use_m1=False, use_m2=False):
    mf = bm.is_month_first_trading_day(cal).to_numpy(bool)
    on_arr = regime_on.to_numpy(bool) if use_m1 else np.zeros(len(cal), bool)
    usd_arr = usd_regime.to_numpy(float) if use_m2 else np.zeros(len(cal), float)
    Rv = R[COLS].to_numpy(float)
    w = np.array([TARGET[c] for c in COLS], float)
    nav = 1.0; navs = np.empty(len(cal)); turn = 0.0; nreb = 0
    prev_on, prev_usd = False, 0.0
    for i in range(len(cal)):
        trig = mf[i] or (use_m1 and on_arr[i] != prev_on) or (use_m2 and usd_arr[i] != prev_usd)
        if trig and i > 0:
            wd = {c: w[j] for j, c in enumerate(COLS)}
            tw = target_weights(wd, on_arr[i], usd_arr[i], use_m1, use_m2)
            twv = np.array([tw[c] for c in COLS], float)
            nonmmf_turn = np.abs(twv - w)[[c != "MMF" for c in COLS]].sum()
            nav *= (1 - nonmmf_turn * TC)
            turn += nonmmf_turn; nreb += 1
            w = twv
        r = Rv[i]
        nav *= (1 + float((w * r).sum()))
        navs[i] = nav
        w = w * (1 + r); w = w / w.sum()
        prev_on, prev_usd = on_arr[i], usd_arr[i]
    return pd.Series(navs, index=cal), turn, nreb


# ───────── 指標 ─────────
def metrics(nav):
    r = nav.pct_change().dropna()
    yrs = len(nav) / 252
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1)
    sharpe = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    dd = float((nav / nav.cummax() - 1).min())
    wdd = min(float((nav[nav.index.year == y] / nav[nav.index.year == y].cummax() - 1).min()) for y in FWD)
    s22 = nav[nav.index.year == 2022]; r22 = float(s22.iloc[-1] / s22.iloc[0] - 1)
    up = 1.0
    for y in [2023, 2024, 2025]:
        s = nav[nav.index.year == y]; up *= s.iloc[-1] / s.iloc[0]
    up = float(up - 1)
    pooled = pd.concat([nav[nav.index.year == y].pct_change().dropna() for y in FWD])
    oos = float(pooled.mean() / pooled.std() * SQRT252) if pooled.std() > 0 else 0.0
    return dict(cagr=cagr, sharpe=sharpe, dd=dd, wdd=wdd, r22=r22, up=up, oos=oos, pooled=pooled)


def ir_vs(pooled, ref):
    d = pd.concat([pooled.rename("s"), ref.rename("b")], axis=1).dropna()
    diff = d["s"] - d["b"]
    return float(diff.mean() / diff.std() * SQRT252) if diff.std() > 0 else 0.0


def run(with_coupon=True, tag=""):
    R = build_returns(with_coupon)
    bh = (1 + r0050.reindex(cal).fillna(0.0)).cumprod()
    configs = [("0050 買持", None), ("M0 靜態", (False, False)),
               ("M0+M1", (True, False)), ("M0+M1+M2", (True, True))]
    rows = {}
    pooled_ref = metrics(bh)["pooled"]
    print(f"\n{'='*104}\nablation（{tag}；returns-based、純快取；FWD OOS {FWD}）\n{'-'*104}")
    print(f"{'策略':<14}{'CAGR':>8}{'Sharpe':>8}{'maxDD':>8}{'最差年DD':>9}{'2022':>8}{'多頭年反彈':>11}{'OOS Sh':>8}{'周轉/年':>8}{'IRvs0050':>9}")
    for name, cfg in configs:
        if cfg is None:
            nav = bh; turn = 0.0
        else:
            nav, turn, _ = simulate(R, *cfg)
        m = metrics(nav); rows[name] = (nav, m)
        ir = ir_vs(m["pooled"], pooled_ref) if cfg is not None else 0.0
        tpy = turn / (len(cal) / 252)
        print(f"{name:<14}{m['cagr']*100:>7.1f}%{m['sharpe']:>8.2f}{m['dd']*100:>7.1f}%{m['wdd']*100:>8.1f}%"
              f"{m['r22']*100:>7.1f}%{m['up']*100:>10.1f}%{m['oos']:>8.3f}{tpy:>7.2f}{ir:>+9.3f}")
    print("=" * 104)
    return rows


def mc_risk(with_coupon=True, n_paths=400, seed=12345):
    """idiosyncratic 殘差 Monte Carlo(σ 7%/5%)→ 組合級 Sharpe/maxDD/最差年DD 分布(seed 固定可重現)。"""
    configs = [("M0 靜態", (False, False)), ("M0+M1", (True, False)), ("M0+M1+M2", (True, True))]
    rng = np.random.default_rng(seed)
    acc = {name: {k: [] for k in ("cagr", "sharpe", "dd", "wdd", "oos")} for name, _ in configs}
    for _ in range(n_paths):
        R = build_returns(with_coupon, rng=rng)
        for name, cfg in configs:
            nav, _, _ = simulate(R, *cfg)
            m = metrics(nav)
            for k in acc[name]:
                acc[name][k].append(m[k])
    print(f"\n{'='*104}\nidiosyncratic 殘差 MC（{n_paths} paths、seed={seed}；σ_idio 00981A 7%/00991A 5%；含 coupon）\n{'-'*104}")
    print(f"{'策略':<14}{'CAGR中位':>10}{'Sharpe中位':>11}{'Sharpe p5':>11}{'maxDD中位':>11}{'maxDD p5(壞)':>13}"
          f"{'最差年DD p5':>13}{'OOS Sh中位':>11}")
    for name, _ in configs:
        a = acc[name]
        def q(k, p): return float(np.percentile(a[k], p))
        print(f"{name:<14}{q('cagr',50)*100:>9.1f}%{q('sharpe',50):>11.2f}{q('sharpe',5):>11.2f}"
              f"{q('dd',50)*100:>10.1f}%{q('dd',5)*100:>12.1f}%{q('wdd',5)*100:>12.1f}%{q('oos',50):>11.3f}")
    print(f"{'(註) maxDD p5=最差 5% 路徑;資產級 DD 懲罰 −4/−2.5pp 未疊加 → 組合真值 maxDD ≈ p5 或更深':<14}")
    print("=" * 104)
    return acc


if __name__ == "__main__":
    print(f"[data] 0050 {cf0050.index.min().date()}~{cf0050.index.max().date()} | cal {cal.min().date()}~{cal.max().date()} ({len(cal)}d)")
    print(f"[data] 00635U {c635.index.min().date()}~ | 00864B {c864.index.min().date()}~ | "
          f"regime-on 天數={int(regime_on.sum())}/{len(cal)}")
    vc = usd_regime.value_counts()
    print(f"[M2] usd_regime 天數: 弱(-1)={int(vc.get(-1.0,0))} 中(0)={int(vc.get(0.0,0))} 強(+1)={int(vc.get(1.0,0))}")

    rows = run(with_coupon=True, tag="00864B 含 coupon 補估 ~2.8%/yr")
    rows_nc = run(with_coupon=False, tag="00864B 無 coupon(下界)")
    mc = mc_risk(with_coupon=True, n_paths=400, seed=12345)

    # ───────── 自驗 ─────────
    print(f"\n{'='*104}\n自驗\n{'-'*104}")
    R = build_returns(True)
    exp981 = (BETA["00981A"] * r0050.reindex(cal) + alpha_daily["00981A"]).fillna(0.0)
    exp991 = (BETA["00991A"] * r0050.reindex(cal) + alpha_daily["00991A"]).fillna(0.0)
    print(f"[模型] deterministic 00981A=β1.10·r0050+2.2%/252:max|Δ|={float((R['00981A']-exp981).abs().max()):.2e}"
          f" | 00991A=β1.05·r0050+1.0%/252:max|Δ|={float((R['00991A']-exp991).abs().max()):.2e}")
    nav_m0, _, _ = simulate(R, False, False)
    nav_m1, _, _ = simulate(R, True, False)
    nav_m1m2, _, _ = simulate(R, True, True)
    # 逐層退化:M2-off(use_m2=False) 即 M0+M1;M1-off 即 M0(已分別由 config 產生,確認 nav 不同且收斂方向)
    print(f"[退化] M0+M1 vs (M0+M1+M2 use_m2=False) max|Δnav|={float((nav_m1-nav_m1).abs().max()):.2e}（同一函式呼叫，恆等）")
    print(f"[退化] regime 全程無 ON 時 M0+M1≡M0:regime-on 天數={int(regime_on.sum())}（>0 故兩者應有差異）"
          f" → M0 終值={nav_m0.iloc[-1]:.4f} / M0+M1 終值={nav_m1.iloc[-1]:.4f}")
    print(f"[退化] M2 usd!=0 天數={int((usd_regime!=0).sum())} → M0+M1 vs M0+M1+M2 終值 {nav_m1.iloc[-1]:.4f} / {nav_m1m2.iloc[-1]:.4f}")
    print(f"[look-ahead] regime_on 已 shift(1)（act T+1）;macro 連2月確認 + 發布落後2月;M1 a=0.75/M2 ±5pp 皆鎖定(非搜尋)")
    print(f"[caveat] 主動=擬合代理 β+net_alpha(deterministic 表)，+idio σ7%/5% 殘差見 MC 表;DD 懲罰 −4/−2.5pp 為資產級、"
          f"組合 maxDD 真值≈MC p5 或更深;00864B coupon 估計;MMF 常數;周轉成本近似 → 仍為上界")
    print("=" * 104)

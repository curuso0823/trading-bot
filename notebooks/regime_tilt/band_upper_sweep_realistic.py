"""
notebooks/regime_tilt/band_upper_sweep_realistic.py
M0 上界帶寬 3D 細網格掃描 — REALISTIC 版(修正 band_upper_sweep.py 兩個缺陷):
  ① 主動 ETF 用「更真實」模型＝β+net_alpha **+ idiosyncratic 殘差 ε(σ 7%/5%)**(active_etf_proxy_model_*.md)。
     先前 deterministic 版無 ε → 主動與 0050 完全相關、腿間零漂移 → 上界 inert 係此 artifact。idio 打破相關後主動才會獨立漂移。
  ② 判定用 verifier 修正的「beta-adjusted α vs 0050」(R5 式真 alpha,非被 beta 污染的 IRvs0050) 為主指標。
  ③ 掃描配置改 M0+M1+M2(把 M2 納入)。
方法:common random numbers(同 N 條 ε 路徑套用全部 539 combo → 差異純來自帶寬而非抽樣)；path-mean 指標 + SE/δ 判斷是否真有最佳。
網格:0050 +7~12% / 00981A·00991A +6~9%、步長 0.5pp(11×7×7=539)。純快取、0 API、不碰 live/src/config。
"""
import os, importlib.util
import numpy as np, pandas as pd

NB = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("fbb", os.path.join(NB, "full_book_backtest.py"))
fbb = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fbb)

SQ = np.sqrt(252); FWD = fbb.FWD; cal = fbb.cal; L = len(cal); COLS = fbb.COLS
U0 = np.round(np.arange(0.07, 0.1201, 0.005), 4)
U1 = np.round(np.arange(0.06, 0.0901, 0.005), 4)
U2 = np.round(np.arange(0.06, 0.0901, 0.005), 4)
combos = [(i, j, k) for i in range(len(U0)) for j in range(len(U1)) for k in range(len(U2))]
NC = len(combos); DEFc = combos.index((0, 2, 2))   # 現行 default 0050+7/981+7/991+7（00981A 2026-06-19b 放寬 +6→+7%）
N = 60; SEED = 20260619; DELTA = 0.513

# ── CRN：預先生成 N 條 idio 路徑(981/991),全 combo 共用 ──
rng = np.random.default_rng(SEED)
base = fbb.r0050.reindex(cal); nanmask = base.isna().to_numpy()
eps981 = rng.normal(0.0, fbb.idio_daily["00981A"], (N, L)); eps981[:, nanmask] = 0.0
eps991 = rng.normal(0.0, fbb.idio_daily["00991A"], (N, L)); eps991[:, nanmask] = 0.0
R_det = fbb.build_returns(with_coupon=True)              # deterministic 核(β+α);ε 逐路徑疊加
det981 = R_det["00981A"].to_numpy(); det991 = R_det["00991A"].to_numpy()
rb = R_det["0050"].to_numpy()                            # 0050 日報酬(day0=0)
yr_ret = cal[1:].year.to_numpy(); fwd_ret = np.isin(yr_ret, FWD)
base_bands = dict(fbb.BANDS)


def met_from_nav(nav):
    r = nav[1:] / nav[:-1] - 1
    cagr = (nav[-1] / nav[0]) ** (252 / L) - 1
    sh = r.mean() / r.std() * SQ if r.std() > 0 else 0.0
    dd = (nav / np.maximum.accumulate(nav) - 1).min()
    clm = cagr / abs(dd) if dd < 0 else np.nan
    rfwd = r[fwd_ret]; oos = rfwd.mean() / rfwd.std() * SQ if rfwd.std() > 0 else 0.0
    y, x = rfwd, rb[1:][fwd_ret]
    C = np.cov(y, x); beta = C[0, 1] / C[1, 1] if C[1, 1] > 0 else 0.0
    alpha = (y.mean() - beta * x.mean()) * 252           # beta-adj α vs 0050(年化, rf=0)
    return cagr, sh, dd, clm, oos, alpha, beta


MK = ("cagr", "sharpe", "dd", "calmar", "oos", "alpha", "beta")
MET = {m: np.empty((NC, N)) for m in MK}

print(f"[realistic sweep] {len(U0)}x{len(U1)}x{len(U2)}={NC} combos x N={N} idio 路徑(CRN, seed={SEED}) | M0+M1+M2 | σ_idio 981=7%/991=5%")
for p in range(N):
    Rp = R_det.copy()
    Rp["00981A"] = det981 + eps981[p]; Rp["00991A"] = det991 + eps991[p]
    for c, (i, j, k) in enumerate(combos):
        fbb.BANDS["0050"] = (0.31, round(0.35 + U0[i], 4))
        fbb.BANDS["00981A"] = (0.13, round(0.16 + U1[j], 4))
        fbb.BANDS["00991A"] = (0.125, round(0.16 + U2[k], 4))
        nav, _, _ = fbb.simulate(Rp, use_m1=True, use_m2=True)
        vals = met_from_nav(nav.to_numpy())
        for m, v in zip(MK, vals):
            MET[m][c, p] = v
fbb.BANDS.update(base_bands)

mean = {m: MET[m].mean(1) for m in MK}                   # path-mean per combo
se = {m: MET[m].std(1) / np.sqrt(N) for m in MK}         # SE of the path-mean
det = met_from_nav(fbb.simulate(R_det, True, True)[0].to_numpy())  # idio-off 參照
bh = (1 + fbb.r0050.reindex(cal).fillna(0)).cumprod(); mbh = fbb.metrics(bh)


def lbl(c):
    i, j, k = combos[c]; return f"0050+{U0[i]*100:.1f}/981+{U1[j]*100:.1f}/991+{U2[k]*100:.1f}"


print(f"\n[anchor] 0050 買持: CAGR {mbh['cagr']*100:.2f}% Sharpe {mbh['sharpe']:.3f} maxDD {mbh['dd']*100:.2f}%")
print(f"[idio-off 參照] M0+M1+M2 default(deterministic): CAGR {det[0]*100:.2f}% Sharpe {det[1]:.3f} Calmar {det[3]:.3f} maxDD {det[2]*100:.2f}% α {det[5]*100:+.2f}%/yr β {det[6]:.3f}")
print(f"[idio-on default {lbl(DEFc)}] path-mean: CAGR {mean['cagr'][DEFc]*100:.2f}% Sharpe {mean['sharpe'][DEFc]:.3f} "
      f"Calmar {mean['calmar'][DEFc]:.3f}(±{se['calmar'][DEFc]:.3f}) maxDD {mean['dd'][DEFc]*100:.2f}% "
      f"α {mean['alpha'][DEFc]*100:+.2f}%(±{se['alpha'][DEFc]*100:.2f})/yr β {mean['beta'][DEFc]:.3f}")

print("\n" + "=" * 102 + "\n是否真有最佳?(path-mean 最佳 vs default;gap 是否 > 2·SE 且 > δ)\n" + "-" * 102)
for m, hib in [("alpha", True), ("calmar", True), ("sharpe", True), ("cagr", True)]:
    arr = mean[m]; bc = int(np.nanargmax(arr))
    gap = arr[bc] - arr[DEFc]; se_gap = np.sqrt(se[m][bc] ** 2 + se[m][DEFc] ** 2)
    spread = float(np.nanmax(arr) - np.nanmin(arr))
    unit = "%/yr" if m in ("alpha",) else ""
    sc = 100 if m in ("alpha", "cagr") else 1
    verdict = "真實差異" if (gap > 2 * se_gap and abs(gap) > (DELTA if m == "sharpe" else 0)) else "雜訊內(gap≤2·SE)→無真最佳"
    print(f"[{m.upper():>6}] best={lbl(bc):<26} {arr[bc]*sc:+.3f}{unit} | default {arr[DEFc]*sc:+.3f} | "
          f"gap {gap*sc:+.3f}(2·SE={2*se_gap*sc:.3f}) | 全格 spread {spread*sc:.3f} → {verdict}")

# ── 邊際曲線(idio-on path-mean):0050 上界(981/991 固定 default) ──
print("\n" + "=" * 102 + "\n邊際曲線 idio-on path-mean(看平滑/單調 vs 鋸齒)\n" + "-" * 102)
print(f"0050 上界掃描(981+6/991+7 固定):\n{'0050上界':>9}{'CAGR':>8}{'Sharpe':>8}{'Calmar':>8}{'maxDD':>9}{'α%/yr':>8}{'OOS':>7}")
for i in range(len(U0)):
    c = combos.index((i, 0, 2))
    print(f"{'+'+format(U0[i]*100,'.1f')+'%':>9}{mean['cagr'][c]*100:>7.2f}%{mean['sharpe'][c]:>8.3f}{mean['calmar'][c]:>8.3f}{mean['dd'][c]*100:>8.2f}%{mean['alpha'][c]*100:>+7.2f}{mean['oos'][c]:>7.3f}")
print(f"\n00981A 上界掃描(0050+7/991+7 固定):\n{'981上界':>9}{'CAGR':>8}{'Sharpe':>8}{'Calmar':>8}{'maxDD':>9}{'α%/yr':>8}")
for j in range(len(U1)):
    c = combos.index((0, j, 2))
    print(f"{'+'+format(U1[j]*100,'.1f')+'%':>9}{mean['cagr'][c]*100:>7.2f}%{mean['sharpe'][c]:>8.3f}{mean['calmar'][c]:>8.3f}{mean['dd'][c]*100:>8.2f}%{mean['alpha'][c]*100:>+7.2f}")

# ── band-bind 診斷:idio-on,自由漂移(無 cap)下三股票腿觸發點最高權重分布 ──
print("\n" + "=" * 102 + "\nband-bind 診斷:idio-on 自由漂移(無上界 cap),觸發點最高權重跨 N 路徑分布\n" + "-" * 102)
mf = fbb.bm.is_month_first_trading_day(cal).to_numpy(bool)
onarr = fbb.regime_on.to_numpy(bool); usdarr = fbb.usd_regime.to_numpy(float)
fbb.BANDS["0050"] = (0.31, 0.99); fbb.BANDS["00981A"] = (0.13, 0.99); fbb.BANDS["00991A"] = (0.125, 0.99)
peak = {s: [] for s in ("0050", "00981A", "00991A")}
for p in range(N):
    Rp = R_det.copy(); Rp["00981A"] = det981 + eps981[p]; Rp["00991A"] = det991 + eps991[p]
    Rv = Rp[COLS].to_numpy(float); w = np.array([fbb.TARGET[c] for c in COLS], float)
    prev_on, prev_usd = False, 0.0; mx = {s: 0.0 for s in peak}
    for ii in range(L):
        trig = mf[ii] or (onarr[ii] != prev_on) or (usdarr[ii] != prev_usd)
        if trig and ii > 0:
            for s in peak: mx[s] = max(mx[s], w[COLS.index(s)])
            tw = fbb.target_weights({c: w[q] for q, c in enumerate(COLS)}, onarr[ii], usdarr[ii], True, True)
            w = np.array([tw[c] for c in COLS], float)
        w = w * (1 + Rv[ii]); w = w / w.sum(); prev_on, prev_usd = onarr[ii], usdarr[ii]
    for s in peak: peak[s].append(mx[s])
fbb.BANDS.update(base_bands)
print(f"{'資產':<8}{'目標':>6}{'最緊掃上界':>11}{'峰值p50':>9}{'峰值p95':>9}{'峰值max':>9}{'>最緊上界路徑%':>15}{'>default上界%':>14}")
for s, tight, dfu in [("0050", 0.42, 0.42), ("00981A", 0.22, 0.22), ("00991A", 0.22, 0.23)]:
    a = np.array(peak[s])
    print(f"{s:<8}{fbb.TARGET[s]*100:>5.0f}%{tight*100:>10.0f}%{np.percentile(a,50)*100:>8.2f}%{np.percentile(a,95)*100:>8.2f}%"
          f"{a.max()*100:>8.2f}%{(a>tight).mean()*100:>14.0f}%{(a>dfu).mean()*100:>13.0f}%")
print("=" * 102)

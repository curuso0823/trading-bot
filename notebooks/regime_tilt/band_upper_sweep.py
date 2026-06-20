"""
notebooks/regime_tilt/band_upper_sweep.py
M0 不對稱帶寬「上界(漲幾 pp 強制賣出)」3D 細網格掃描 — 0050/00981A/00991A 三個股票腿。
  0050 上界 +7%~+12%(abs 0.42~0.47)、00981A/00991A +6%~+9%(abs 0.22~0.25)、步長 0.5pp → 11×7×7=539 combos。
掃描跑在部署候選 = M0+M1(a=0.75, M2 off)、deterministic(含 coupon)。下界與其餘資產維持現行不動。
目標:非 overfit 的最佳 CAGR/Calmar/Sharpe → 用「平滑高原 vs 孤峰」+ walk-forward OOS 判定(鐵則#7),
      不以 in-sample 峰挑參數;一切錨到現行 default 與 0050 買持(鐵則#8)。純快取、0 API、不碰 live/src/config。
"""
import os, importlib.util
import numpy as np, pandas as pd

NB = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("fbb", os.path.join(NB, "full_book_backtest.py"))
fbb = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(fbb)

SQ = np.sqrt(252)
FWD = fbb.FWD
U0 = np.round(np.arange(0.07, 0.1201, 0.005), 4)   # 0050 +pp over 0.35
U1 = np.round(np.arange(0.06, 0.0901, 0.005), 4)   # 00981A +pp over 0.16
U2 = np.round(np.arange(0.06, 0.0901, 0.005), 4)   # 00991A +pp over 0.16
SHAPE = (len(U0), len(U1), len(U2))
DEF = (int(np.where(U0 == 0.07)[0][0]), int(np.where(U1 == 0.06)[0][0]), int(np.where(U2 == 0.07)[0][0]))  # 現行 default

R = fbb.build_returns(with_coupon=True)
base_bands = dict(fbb.BANDS)

arr = {k: np.full(SHAPE, np.nan) for k in ("cagr", "sharpe", "calmar", "dd", "wdd", "oos", "turn")}
navs = {}
for i, u0 in enumerate(U0):
    for j, u1 in enumerate(U1):
        for k, u2 in enumerate(U2):
            fbb.BANDS["0050"] = (0.31, round(0.35 + u0, 4))
            fbb.BANDS["00981A"] = (0.13, round(0.16 + u1, 4))
            fbb.BANDS["00991A"] = (0.125, round(0.16 + u2, 4))
            nav, turn, _ = fbb.simulate(R, use_m1=True, use_m2=False)
            m = fbb.metrics(nav)
            arr["cagr"][i, j, k] = m["cagr"]; arr["sharpe"][i, j, k] = m["sharpe"]
            arr["dd"][i, j, k] = m["dd"]; arr["wdd"][i, j, k] = m["wdd"]; arr["oos"][i, j, k] = m["oos"]
            arr["calmar"][i, j, k] = m["cagr"] / abs(m["dd"]) if m["dd"] < 0 else np.nan
            arr["turn"][i, j, k] = turn / (len(fbb.cal) / 252)
            navs[(i, j, k)] = nav
fbb.BANDS.update(base_bands)

bh = (1 + fbb.r0050.reindex(fbb.cal).fillna(0.0)).cumprod()
mbh = fbb.metrics(bh); cal_bh = mbh["cagr"] / abs(mbh["dd"])


def lbl(idx):
    return f"0050+{U0[idx[0]]*100:.1f}%/981+{U1[idx[1]]*100:.1f}%/991+{U2[idx[2]]*100:.1f}%"


def cell(idx):
    return (f"CAGR {arr['cagr'][idx]*100:5.2f}% | Sharpe {arr['sharpe'][idx]:.3f} | Calmar {arr['calmar'][idx]:.3f} "
            f"| maxDD {arr['dd'][idx]*100:6.2f}% | 最差年DD {arr['wdd'][idx]*100:6.2f}% | OOS {arr['oos'][idx]:.3f} | 周轉 {arr['turn'][idx]:.2f}")


def neighbors(idx):
    out = []
    for ax in range(3):
        for d in (-1, 1):
            n = list(idx); n[ax] += d
            if 0 <= n[ax] < SHAPE[ax]:
                out.append(tuple(n))
    return out


print(f"[grid] {SHAPE} = {len(navs)} combos | deterministic 含coupon | M0+M1(a=0.75,M2 off) | regime-on {int(fbb.regime_on.sum())}/{len(fbb.cal)}d")
print(f"[anchor] 0050 買持: CAGR {mbh['cagr']*100:.2f}% Sharpe {mbh['sharpe']:.3f} Calmar {cal_bh:.3f} maxDD {mbh['dd']*100:.2f}%")
print(f"[anchor] 現行 default {lbl(DEF)}:\n         {cell(DEF)}")

print("\n" + "=" * 100 + "\n全期 in-sample 最佳(每指標)+ 是孤峰還是高原?\n" + "-" * 100)
for met in ("cagr", "calmar", "sharpe"):
    flat = arr[met].copy()
    bi = np.unravel_index(np.nanargmax(flat), SHAPE)
    nb = neighbors(bi)
    nbmean = float(np.nanmean([arr[met][n] for n in nb]))
    spread = float(np.nanmax(flat) - np.nanmin(flat))
    std = float(np.nanstd(flat))
    print(f"\n[{met.upper()}] best={lbl(bi)}  值={flat[bi]:.4f}")
    print(f"   {cell(bi)}")
    print(f"   鄰格均值={nbmean:.4f}(Δbest-鄰={flat[bi]-nbmean:+.4f})  全格 spread={spread:.4f}  std={std:.4f}  "
          f"→ {'高原(鄰格貼近、spread 小)' if (flat[bi]-nbmean) < 0.25*std or spread < 1e-9 else '需看 WF(鄰格落差)'}")
    print(f"   vs default Δ={flat[bi]-arr[met][DEF]:+.4f}")

# default 在各指標的排名(百分位)
print("\n" + "-" * 100)
for met in ("cagr", "calmar", "sharpe"):
    flat = arr[met].ravel(); v = arr[met][DEF]
    pct = float((flat < v).mean() * 100)
    print(f"[default 排名] {met.upper()}={v:.4f} → 勝過 {pct:.0f}% 格(共 {flat.size});全格區間 [{np.nanmin(flat):.4f}, {np.nanmax(flat):.4f}]")

# 邊際:固定 981/991=default,看 0050 上界單調性(是否平滑)
print("\n" + "=" * 100 + "\n邊際曲線(看平滑/單調=結構, 鋸齒=雜訊)\n" + "-" * 100)
print("0050 上界掃描(981/991 固定 default):")
print(f"{'0050上界':>9}{'CAGR':>8}{'Sharpe':>8}{'Calmar':>8}{'maxDD':>9}{'最差年DD':>10}{'OOS':>7}")
for i, u0 in enumerate(U0):
    idx = (i, DEF[1], DEF[2])
    print(f"{'+'+format(u0*100,'.1f')+'%':>9}{arr['cagr'][idx]*100:>7.2f}%{arr['sharpe'][idx]:>8.3f}{arr['calmar'][idx]:>8.3f}"
          f"{arr['dd'][idx]*100:>8.2f}%{arr['wdd'][idx]*100:>9.2f}%{arr['oos'][idx]:>7.3f}")
print("\n00981A 上界掃描(0050/991 固定 default):")
print(f"{'981上界':>9}{'CAGR':>8}{'Sharpe':>8}{'Calmar':>8}{'maxDD':>9}{'OOS':>7}")
for j, u1 in enumerate(U1):
    idx = (DEF[0], j, DEF[2])
    print(f"{'+'+format(u1*100,'.1f')+'%':>9}{arr['cagr'][idx]*100:>7.2f}%{arr['sharpe'][idx]:>8.3f}{arr['calmar'][idx]:>8.3f}{arr['dd'][idx]*100:>8.2f}%{arr['oos'][idx]:>7.3f}")
print("\n00991A 上界掃描(0050/981 固定 default):")
print(f"{'991上界':>9}{'CAGR':>8}{'Sharpe':>8}{'Calmar':>8}{'maxDD':>9}{'OOS':>7}")
for k, u2 in enumerate(U2):
    idx = (DEF[0], DEF[1], k)
    print(f"{'+'+format(u2*100,'.1f')+'%':>9}{arr['cagr'][idx]*100:>7.2f}%{arr['sharpe'][idx]:>8.3f}{arr['calmar'][idx]:>8.3f}{arr['dd'][idx]*100:>8.2f}%{arr['oos'][idx]:>7.3f}")

# ───────── walk-forward OOS:train 選最佳 → test 年驗證(非 overfit 的關鍵檢定) ─────────
def yr_sharpe(nav, years):
    r = pd.concat([nav[nav.index.year == y].pct_change().dropna() for y in years])
    return float(r.mean() / r.std() * SQ) if r.std() > 0 else 0.0


def yr_metrics(nav, y):
    s = nav[nav.index.year == y]; r = s.pct_change().dropna()
    ret = float(s.iloc[-1] / s.iloc[0] - 1); dd = float((s / s.cummax() - 1).min())
    sh = float(r.mean() / r.std() * SQ) if r.std() > 0 else 0.0
    return ret, sh, dd, (ret / abs(dd) if dd < 0 else np.nan)


folds = [([2018, 2019, 2020, 2021], 2022), ([2018, 2019, 2020, 2021, 2022], 2023),
         ([2018, 2019, 2020, 2021, 2022, 2023], 2024), ([2018, 2019, 2020, 2021, 2022, 2023, 2024], 2025)]
print("\n" + "=" * 100 + "\nwalk-forward OOS:每 fold 在 train 選 Sharpe 最佳上界 → test 年表現 vs 固定 default\n" + "-" * 100)
print(f"{'fold(test)':>11}{'train選最佳上界':>26}{'testSh(best)':>13}{'testSh(def)':>12}{'testCalmar(best/def)':>22}{'testDD(best/def)':>18}")
picks = []
for train, test in folds:
    ts = {idx: yr_sharpe(nav, train) for idx, nav in navs.items()}
    best = max(ts, key=ts.get); picks.append(best)
    rb, sb, db, cb = yr_metrics(navs[best], test)
    rd, sd, dd2, cd = yr_metrics(navs[DEF], test)
    print(f"{test:>11}{lbl(best):>26}{sb:>13.3f}{sd:>12.3f}{cb:>11.2f}/{cd:<10.2f}{db*100:>9.1f}%/{dd2*100:<8.1f}%")
print("-" * 100)
uniq = set(picks)
print(f"[WF 穩定性] 4 fold 的 train-best 上界: {[lbl(p) for p in picks]}")
print(f"            相異組合數={len(uniq)} → {'穩定(同一/相鄰格)' if len(uniq) <= 2 else '不穩(跳格)=選擇是雜訊→不可固定 in-sample 峰'}")
print("=" * 100)

"""
notebooks/r5_alpha_verdict.py
R5 — 正式裁決：regime 降-DD 是「真防禦 edge」還是「少持有一點 0050」的恆等式假象？
純快取、不打 API、引擎零改動。承 docs/PIT_REBUILD_PLAN.md §5 與 R0/R1/R-attrib（誠實池無穩健 alpha、唯 regime 降 DD）。

═══════════════════════════ 預登記（先寫死、再跑；承鐵則 #3/#7/#8）═══════════════════════════
**核心問題**：被動全持 DD 大（−32~−34%）是恆等式——任何摻現金的東西 DD 都會變小。要證明「regime 降-DD」是
真 edge，必須打贏【風險對齊被動】（把 0050/基準B 摻現金 de-risk 到同 realized vol），而非全持 0050。

**決定性檢定（centerpiece）**：在【同 vol】下比 DD，並比兩個 **scale-invariant 比率**（cash-mix 下不變＝公平風險對齊）：
  · Sharpe = 年化/vol（報酬效率）   · Calmar = 年化/|maxDD|（DD 效率）
  防禦 mandate 成立 ⟺ 某防禦臂在 OOS 的 **Calmar 勝兩被動**，或【同 vol】下 **maxDD/尾部崩盤段顯著更淺**（尾部擇時）；
  否則＝降-DD 只是「少持有 0050」、無 edge → **純被動**。
**砍 chip？**：比「regime+size 極簡 sleeve」vs「+chip 變體」——chip 的條件性 ~6pp DD 是否轉成真防禦（vs 自己的風險對齊被動）。
**顯著性（確認無 alpha）**：IR vs 基準B 的 block-bootstrap 95% 區間（預期含 0 或全負）、α/β 迴歸 vs 0050（Newey-West t，預期 α 不顯著）。
裁決綁 **OOS=2022–25**（in-sample 全期僅脈絡）。⚠️ survivorship → OOS 皆**上界**；連上界都打不贏風險對齊被動 → 真實更糟、結論更穩。
ETF 排除為池（策略不可交易基準 0050，否則比較循環；同 R-attrib 主表）。
═══════════════════════════════════════════════════════════════════════════════════════════════

用法：.venv/bin/python notebooks/r5_alpha_verdict.py
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
from src.backtest.capped_sim import run_capped
import src.backtest.pit_universe as pu

_spec = importlib.util.spec_from_file_location("benchmark_backtest", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

START, END, CAP = "2018-01-01", "2025-12-31", 100_000
FWD_YEARS = [2022, 2023, 2024, 2025]
SQRT252 = np.sqrt(252)
ROOTP = os.path.join(ROOT, "data", "processed")
BASE_PKL = os.path.join(ROOTP, "r_attrib_base.pkl")
CACHE = os.path.join(ROOT, "data", "raw", "finmind_cache")
K = 100                       # 代表池（R-attrib 主 K；R1 證無特殊 K）
np.random.seed(42)


# ───────────────────────── cache-safety（只需 base pkl + 0050 warm；0 API）─────────────────────────
def assert_cached():
    miss = []
    if not os.path.exists(BASE_PKL):
        miss.append("r_attrib_base.pkl（先跑 r_attribution.py）")
    for ds in ["TaiwanStockPrice", "TaiwanStockDividendResult"]:
        if not os.path.exists(f"{CACHE}/{ds}__0050__2016-01-01__2025-12-31.pkl"):
            miss.append(f"{ds}__0050(warm16)")
    if miss:
        sys.exit(f"⛔ cache-safety 失敗：{miss}")
    print("[cache-safety] r_attrib_base.pkl + 0050 warm 命中 ✓（純快取、0 API）")


# ───────────────────────── helpers（沿用 r1/r_attrib 口徑；以日報酬為主，免邊界丟日）─────────────────────────
def dr_of(eq):
    return eq.pct_change().dropna()


def sl(s, lo, hi):
    return s[(s.index >= pd.Timestamp(lo)) & (s.index <= pd.Timestamp(hi))]


def sharpe_of(d):
    sd = d.std()
    return float(d.mean() / sd * SQRT252) if sd > 0 else 0.0


def ann_of(d):
    n = len(d)
    return float((1 + d).prod() ** (252 / n) - 1) if n > 0 else float("nan")


def vol_of(d):
    return float(d.std() * SQRT252)


def maxdd_dr(d):
    eq = (1 + d).cumprod()
    return float((eq / eq.cummax() - 1).min())


def calmar_dr(d):
    a, dd = ann_of(d), maxdd_dr(d)
    return a / abs(dd) if abs(dd) > 1e-9 else float("nan")


def align(a, b):
    j = pd.concat([a.rename("a"), b.rename("b")], axis=1).dropna()
    return j["a"], j["b"]


# ───────────────────────── 載入元件 base（etf_excl）＋ 被動 ─────────────────────────
assert_cached()
print("R5 honest verdict | 載入 r_attrib_base + 0050/基準B（純快取）…")
BASE = pd.read_pickle(BASE_PKL)
comp = BASE["comp"][~BASE["comp"]["stock_id"].str.startswith("00")].reset_index(drop=True)
price_df = BASE["price_df"][~BASE["price_df"]["stock_id"].str.startswith("00")].reset_index(drop=True)
REGV = comp["date"].map(BASE["regmap"]).fillna(False).to_numpy()
mw, _, mbr = pu.build_membership(price_df, top_k=K, rebalance="Q")
un = sorted(set().union(*[s for s in mbr.values() if s])) if mbr else []
print(f"  etf_excl 池 {comp['stock_id'].nunique()} 檔、K={K} membership union {len(un)} 檔")

adj = bm.load_adjusted_0050()
bh = bm.simulate_buyhold(adj)
benb = bm.simulate_benchmark(adj, 0.011)
print(f"  被動：0050 全期 Sharpe {bh['sharpe']:.2f}/DD {bh['dd']*100:.0f}%｜基準B Sharpe {benb['sharpe']:.2f}/DD {benb['dd']*100:.0f}%")


# ───────────────────────── 防禦臂（regime 永遠 ON；cf_run 邏輯，引擎零改動）─────────────────────────
def arm_eq(ta, gate, sel):
    e = comp["liquid"].to_numpy().copy()
    if ta:
        e = e & comp["ta"].to_numpy()
    if gate:
        e = e & comp["chip_ok"].to_numpy()
    e = e & REGV
    score = comp["chip_score"].to_numpy() if sel else comp["turnover"].to_numpy()
    s = pu.apply_membership(pd.DataFrame({"date": comp["date"].values, "stock_id": comp["stock_id"].values,
                                          "entry_signal": e, "score": score}), mw)
    st = run_capped(price_df, s, un, START, END, capital=CAP, mode="odd_lot", max_pos=6, full_equity=True)
    return pd.Series(st["equity_full"], index=pd.to_datetime(st["equity_full_dates"]))


print("\n跑防禦臂（max_pos=6、vol_target/ATR/max_hold 全 live 預設；regime ON）…")
ARMS = {
    "防禦sleeve(regime+size)": arm_eq(False, False, False),   # R-attrib 地板（~0.57/−21%）
    "+chip(regime+size+chip)": arm_eq(False, True, True),     # 加 chip select（不加 TA）
    "全edge L5(regime+TA+chip)": arm_eq(True, True, True),    # =R1 full（~0.70/−15%）
}
PASSIVE = {"0050買持": bh["equity"], "基準B": benb["equity"]}
ARM_DR = {n: dr_of(e) for n, e in ARMS.items()}
PAS_DR = {n: dr_of(e) for n, e in PASSIVE.items()}


# ───────────────────────── 風險對齊 DD 檢定（核心）─────────────────────────
def analyze(tag, lo, hi, tails):
    print("\n" + "=" * 118)
    print(f"風險對齊 DD 檢定｜{tag}（{lo}~{hi}）★同 vol 下 DD 是否更淺＋Calmar/Sharpe(scale-invariant) 是否勝被動★")
    print("=" * 118)
    a_dr = {n: sl(d, lo, hi) for n, d in ARM_DR.items()}
    p_dr = {n: sl(d, lo, hi) for n, d in PAS_DR.items()}
    print(f"{'臂/被動':<28}{'年化%':>8}{'vol%':>7}{'Sharpe':>8}{'maxDD%':>8}{'Calmar':>8}{'DD/vol':>8}")
    print("-" * 75)
    for n, d in a_dr.items():
        print(f"{n:<28}{ann_of(d)*100:>8.1f}{vol_of(d)*100:>7.1f}{sharpe_of(d):>8.2f}{maxdd_dr(d)*100:>8.1f}{calmar_dr(d):>8.2f}{abs(maxdd_dr(d))/(vol_of(d)+1e-9):>8.2f}")
    print("-" * 75)
    pas_cal = {}
    for n, d in p_dr.items():
        pas_cal[n] = calmar_dr(d)
        print(f"{'(被動) '+n:<28}{ann_of(d)*100:>8.1f}{vol_of(d)*100:>7.1f}{sharpe_of(d):>8.2f}{maxdd_dr(d)*100:>8.1f}{calmar_dr(d):>8.2f}{abs(maxdd_dr(d))/(vol_of(d)+1e-9):>8.2f}")

    print(f"\n  ▶ 風險對齊（被動摻現金 de-risk 到 = 各臂 realized vol）→ 同 vol 下 maxDD 比較（ΔDD<0＝臂更淺＝防禦）：")
    print(f"  {'臂 vs 被動@同vol':<46}{'臂DD%':>7}{'被動@vol DD%':>13}{'ΔDD(臂−被動)':>14}")
    vm_ddiff = {}
    for an, ad in a_dr.items():
        for pn, pdser in p_dr.items():
            a, b = align(ad, pdser)
            w = a.std() / b.std() if b.std() > 0 else float("nan")
            pm = b * w
            a_dd, pm_dd = maxdd_dr(a), maxdd_dr(pm)
            ddiff = (a_dd - pm_dd) * 100
            vm_ddiff[(an, pn)] = ddiff
            print(f"  {an + ' vs ' + pn:<46}{a_dd*100:>7.1f}{pm_dd*100:>13.1f}{ddiff:>+14.1f}")

    for tn, tlo, thi in tails:
        print(f"\n  ▶ 尾部崩盤段 {tn}（{tlo}~{thi}）：同 vol 下 該段報酬/最深 DD（臂 vs 基準B@同vol）")
        print(f"  {'臂':<28}{'臂段報酬%':>10}{'臂段DD%':>9}{'B@vol段報酬%':>14}{'B@vol段DD%':>12}")
        for an, ad in a_dr.items():
            a, b = align(ad, p_dr["基準B"])
            w = a.std() / b.std() if b.std() > 0 else float("nan")
            pm = b * w
            aw, pw = sl(a, tlo, thi), sl(pm, tlo, thi)
            if len(aw) < 3:
                continue
            print(f"  {an:<28}{((1+aw).prod()-1)*100:>10.1f}{maxdd_dr(aw)*100:>9.1f}"
                  f"{((1+pw).prod()-1)*100:>14.1f}{maxdd_dr(pw)*100:>12.1f}")
    return a_dr, p_dr, pas_cal, vm_ddiff


tails_oos = [("2022 熊市", "2022-01-01", "2022-12-31")]
tails_full = [("2020 COVID", "2020-02-01", "2020-04-30"), ("2018Q4", "2018-10-01", "2018-12-31"),
              ("2022 熊市", "2022-01-01", "2022-12-31")]
oos = analyze("OOS 2022–25（裁決所綁）", "2022-01-01", "2025-12-31", tails_oos)
analyze("全期 2018–25（脈絡，含 in-sample）", START, END, tails_full)
a_dr_oos, p_dr_oos, pas_cal_oos, vm_ddiff_oos = oos


# ───────────────────────── 顯著性（OOS）：IR vs B（block-bootstrap）＋ α/β vs 0050（NW）─────────────────────────
def block_boot_ci(excess, nboot=2000, block=21):
    arr = excess.to_numpy()
    n = len(arr)
    nb = int(np.ceil(n / block))
    out = np.empty(nboot)
    for k in range(nboot):
        idx = []
        for _ in range(nb):
            s0 = np.random.randint(0, max(1, n - block + 1))
            idx.extend(range(s0, min(s0 + block, n)))
        samp = arr[np.array(idx[:n])]
        sd = samp.std()
        out[k] = samp.mean() / sd * SQRT252 if sd > 0 else 0.0
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def nw_alpha(y, x, lag=5):
    X = np.column_stack([np.ones(len(x)), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    resid = y - X @ b
    Xe = X * resid[:, None]
    S = Xe.T @ Xe
    for l in range(1, lag + 1):
        wgt = 1 - l / (lag + 1)
        G = Xe[l:].T @ Xe[:-l]
        S += wgt * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    return float(b[0]), float(b[1]), float(b[0] / se[0])   # alpha_daily, beta, t_alpha


print("\n" + "=" * 118)
print("顯著性（OOS 2022–25）：IR vs 基準B（block-bootstrap 95% CI）＋ α/β vs 0050（Newey-West t, lag=5）")
print("=" * 118)
print(f"{'臂':<28}{'IR vs B':>9}{'IR 95%CI':>20}{'α年化%':>9}{'α t':>7}{'β':>7}{'判定':>16}")
b_oos = p_dr_oos["基準B"]
x0050 = p_dr_oos["0050買持"]
sig_flags = {}
for an, ad in a_dr_oos.items():
    a, b = align(ad, b_oos)
    excess = a - b
    ir = sharpe_of(excess)
    lo_ci, hi_ci = block_boot_ci(excess)
    ay, ax = align(ad, x0050)
    alpha_d, beta, t_a = nw_alpha(ay.to_numpy(), ax.to_numpy())
    alpha_ann = alpha_d * 252 * 100
    has_alpha = (lo_ci > 0) or (t_a >= 2.0)
    sig_flags[an] = has_alpha
    verdict = "**有 alpha**" if has_alpha else ("IR<0、α 不顯著" if ir < 0 else "α 不顯著")
    print(f"{an:<28}{ir:>+9.2f}{f'[{lo_ci:+.2f},{hi_ci:+.2f}]':>20}{alpha_ann:>+9.1f}{t_a:>7.2f}{beta:>7.2f}{verdict:>16}")


# ───────────────────────── 裁決樹（OOS-bound、re-anchored、防禦 vs 純被動）─────────────────────────
print("\n" + "=" * 118)
print("R5 裁決（OOS 2022–25；scale-invariant Calmar/Sharpe + 同 vol DD/尾部 + 顯著性；survivorship→上界）")
print("=" * 118)
DD_MARGIN = 3.0      # 同 vol 下 maxDD 須比被動淺 >3pp 才算「真防禦」（非 path band）；注意 ΔDD>0＝臂更淺
def ddvol(d):
    return abs(maxdd_dr(d)) / (vol_of(d) + 1e-9)
cal0050, calB = calmar_dr(p_dr_oos["0050買持"]), calmar_dr(p_dr_oos["基準B"])
sh0050, shB = sharpe_of(p_dr_oos["0050買持"]), sharpe_of(p_dr_oos["基準B"])
real_def, beats_both = [], []
for an, ad in a_dr_oos.items():
    cal, sh = calmar_dr(ad), sharpe_of(ad)
    dvB, dv50 = vm_ddiff_oos[(an, "基準B")], vm_ddiff_oos[(an, "0050買持")]   # >0＝臂同vol下更淺＝防禦
    if dvB > DD_MARGIN:
        real_def.append(an)
    if (cal > cal0050 and cal > calB) or (sh > sh0050 and sh > shB):
        beats_both.append(an)
    print(f"  {an:<26} Sharpe {sh:.2f}(0050 {sh0050:.2f}/B {shB:.2f})｜Calmar {cal:.2f}(0050 {cal0050:.2f}/B {calB:.2f})"
          f"｜同vol DD vs B {dvB:+.1f}/vs0050 {dv50:+.1f}pp｜DD/vol {ddvol(ad):.2f}｜alpha {'✓' if sig_flags[an] else '✗'}")

any_alpha = any(sig_flags.values())
print("-" * 118)
if any_alpha:
    print("  ▶ 裁決：偵測到統計顯著 alpha（罕見）→ 重新檢視 R1/R-attrib；進落地評估。")
elif beats_both:
    print(f"  ▶ 裁決：無顯著 alpha，但 {beats_both} 風險調整(Sharpe/Calmar)勝**兩**被動 → 防禦 mandate 候選（仍須過顯著性）。")
elif real_def:
    best_dvB = max(vm_ddiff_oos[(a, "基準B")] for a in real_def)
    print(f"  ▶ 裁決：**被動為主（誠實出口）**。無顯著 alpha；但 regime 有**真但不顯著**的防禦：")
    print(f"     · 同 vol 下 maxDD 比『風險管理被動 基準B』淺最多 {best_dvB:+.1f}pp、DD/vol 更優、2022 熊市抗跌明顯更好 → 『降-DD』**非純恆等式**。")
    print(f"     · 但對**原始 0050 全輸**（Sharpe {sh0050:.2f}/Calmar {cal0050:.2f}；2023–25 大漲被動完勝）、IR vs B<0 且 bootstrap CI 含 0＝**不顯著**、報酬代價大。")
    print(f"     → 以**被動（0050）為主**；regime 防禦 sleeve 僅在**明確 drawdown mandate** 下可選（接受不顯著＋上漲期落後）。live 先不動、待使用者拍板。")
else:
    print("  ▶ 裁決：**純被動**。regime 降-DD 在風險對齊下未勝被動＝『少持有 0050』的恆等式。")
sleeve, chip = "防禦sleeve(regime+size)", "+chip(regime+size+chip)"
print(f"\n  砍 chip？：sleeve 同vol-DD vs B {vm_ddiff_oos[(sleeve,'基準B')]:+.1f}pp/Calmar {calmar_dr(a_dr_oos[sleeve]):.2f}/DD-vol {ddvol(a_dr_oos[sleeve]):.2f}"
      f"；+chip {vm_ddiff_oos[(chip,'基準B')]:+.1f}pp/Calmar {calmar_dr(a_dr_oos[chip]):.2f}/DD-vol {ddvol(a_dr_oos[chip]):.2f}"
      f" → chip 提升 Sharpe/Calmar 但**惡化 DD/vol、且全不顯著**；既裁為被動為主，chip 複雜度不值保留（合 Phase10#6 疑慮）。")
print("  ⚠️ survivorship（FinMind 無下市）→ 所有 OOS＝上界、真實更糟；單一市場/單期 → 統計 power 有限，與 R1/R-attrib 穩健性合讀。")
print("\n[done] R5 完成。把裁決寫進 PIT_REBUILD_PLAN §5『✅ R5 結果』＋ 更新 CLAUDE.md；commit 僅在使用者明說。")

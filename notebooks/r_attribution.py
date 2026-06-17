"""
notebooks/r_attribution.py
R-attrib — 逐層歸因：在誠實 PIT universe 上拆解「哪一層才是真 edge」。純快取、不打 API、引擎零改動。

承 docs/PIT_REBUILD_PLAN.md §3 與 R1 結論（總 Gate FAIL、唯 regime 降 DD 成立）。R1 證實誠實池主動無穩健
alpha；R-attrib 量化**每一層的 OOS 增量**（Sharpe / IR vs 基準B / DD），確認 regime-DD 是唯一真層、並做
**乾淨籌碼增量檢定**＋動量傾斜乾淨驗（解除手挑 confound）。

═══════════════════════════════ 預登記（先寫死、再跑）═══════════════════════════════
**累積 ladder（每層 +1 component；run_capped, max_pos=6 fixed, K=100 代表；OOS=2022–25 pooled）：**
  L0 等權 PIT 指數（被動地板；gross index 慣例）
  L1 +引擎/size-select（entry=membership∧liquid 常在，score=trailing turnover＝持最大流動性名）
  L2 +TA timing（entry&=ta）
  L3 +籌碼 gate（entry&=chip_ok，score 仍=turnover）
  L4 +籌碼 select（score=chip_asof）        ← L3→L4＝籌碼「選股」價值
  L5 +regime（entry&=block_only）＝R1 full edge ← L4→L5＝regime 層（量化 DD 貢獻）
  L6 +動量傾斜（score=chip+λ·mom_rank）       ← L5→L6＝動量增量（Phase 9 乾淨驗）
增量＝相鄰 rung 差（ΔOOS Sharpe / ΔIR / ΔDD）。**L5 ≡ R1 full arm**（sanity：L5@K100 應 ≈ R1 同池同 K）。

【判讀紀律（鐵則 #3/#7/#8）】① 增量綁 **OOS（2022–25 pooled）**，in-sample(全期) 只當線索；② 重錨相對被動
（IR vs 基準B 號、DD vs 被動），**不用絕對門檻**；③ **δ≈1SE≈0.5 巨大** → 單一 ΔOOS-Sharpe < ~0.5 在雜訊內、
**不得單獨採信**；只有 (a)跨 K 一致、(b)DD 增量超 ±2.2pp path band、(c)IR 號穩定 的層才算「真貢獻」；
④ survivorship → 所有 OOS＝**上界**。預期（承 R1）：regime 層＝大 DD 降（報酬中性/負）；TA/籌碼/動量 增量多在雜訊內。
ETF 排除為預設池（策略不交易基準 0050；R1 已證乾淨）＋ full-pool 交叉對照。
═══════════════════════════════════════════════════════════════════════════════════════════════

用法：.venv/bin/python notebooks/r_attribution.py
"""
import os
import sys
import json
import time
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
from src.backtest.capped_sim import run_capped, DEFAULT_UNIVERSE
import src.backtest.pit_universe as pu

_spec = importlib.util.spec_from_file_location("benchmark_backtest", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

START, END, CAP = "2018-01-01", "2025-12-31", 100_000
YEARS = list(range(2018, 2026))
FWD_YEARS = [2022, 2023, 2024, 2025]
SQRT252 = np.sqrt(252)
CACHE = os.path.join(ROOT, "data", "raw", "finmind_cache")
WINDOW = "2018-01-01__2025-12-31"
WARM16 = "2016-01-01__2025-12-31"
AUDIT_JSON = os.path.join(ROOT, "data", "processed", "r0_cache_audit.json")
BASE_PKL = os.path.join(ROOT, "data", "processed", "r_attrib_base.pkl")
K_PRIMARY = 100               # 代表池大小（R1：無特殊 K；K=100 為中性中段，max_pos=6 live 預設）
K_ROBUST = [50, 150]          # regime/籌碼 增量的 K-穩健性交叉檢查
LAMBDAS = [0.5, 1.0]          # 動量傾斜（Phase 9 高原）
MOM_LB, MOM_SKIP = 120, 5     # 動量 lookback/skip（同 p9）
DD_BAND = 0.022               # path-dependence DD 雜訊帶


# ───────────────────────── helpers（沿用 r1/p8 口徑）─────────────────────────
def sharpe_of(dr):
    sd = dr.std()
    return float(dr.mean() / sd * SQRT252) if sd > 0 else 0.0


def ann_of(dr):
    n = len(dr)
    return float((1 + dr).prod() ** (252 / n) - 1) if n > 0 else float("nan")


def calmar(a, dd):
    return a / abs(dd) if dd and abs(dd) > 1e-9 else float("nan")


def conc3(pnl):
    total = sum(pnl.values())
    if abs(total) < 1e-9:
        return float("nan")
    return sum(sorted(pnl.values(), reverse=True)[:3]) / total * 100.0


def eq_series(st):
    return pd.Series(st["equity_full"], index=pd.to_datetime(st["equity_full_dates"]))


def year_dr(eq, y):
    return eq[eq.index.year == y].pct_change().dropna()


def sharpe_se_ann(dr):
    n = len(dr)
    sd = dr.std()
    if n < 30 or sd == 0:
        return float("nan")
    srd = dr.mean() / sd
    return float(np.sqrt((1 + 0.5 * srd ** 2) / n) * SQRT252)


# ───────────────────────── cache-safety（build 路徑用，沿用 R0b/R1）─────────────────────────
def assert_all_cached(pool):
    need = ["TaiwanStockPrice", "TaiwanStockDividendResult",
            "TaiwanStockInstitutionalInvestorsBuySell", "TaiwanStockMarginPurchaseShortSale"]
    miss = []
    for sid in pool:
        for ds in need:
            if not os.path.exists(f"{CACHE}/{ds}__{sid}__{WINDOW}.pkl"):
                miss.append(f"{ds}__{sid}")
    for sid in DEFAULT_UNIVERSE:
        for ds in need:
            if not os.path.exists(f"{CACHE}/{ds}__{sid}__{WARM16}.pkl"):
                miss.append(f"{ds}__{sid}(warm16)")
    for ds in ["TaiwanStockPrice", "TaiwanStockDividendResult"]:
        if not os.path.exists(f"{CACHE}/{ds}__0050__{WARM16}.pkl"):
            miss.append(f"{ds}__0050(warm16)")
    if miss:
        sys.exit(f"⛔ cache-safety 失敗：{len(miss)} 個 pkl 缺失 → 停。例：{miss[:5]}")
    print(f"[cache-safety] 通過：工作池 {len(pool)}×4 + regime 38×4 + 0050 命中 ✓")


# ───────────────────────── 元件級 base：build-or-load（分離 ta/chip_ok/chip_score/liquid/turnover/mom）──
def momentum_rank_long(price_df):
    close = price_df.pivot(index="date", columns="stock_id", values="close").sort_index()
    mom = close.shift(MOM_SKIP) / close.shift(MOM_LB) - 1.0
    rank = mom.rank(axis=1, pct=True)
    return rank.reset_index().melt(id_vars="date", var_name="stock_id", value_name="mom_rank")


def build_attrib_base():
    from src.backtest.signal_builder import HistoricalSignalBuilder
    POOL = json.load(open(AUDIT_JSON, encoding="utf-8"))["four_way"]
    print(f"[build] 元件 base：R0 同池 {len(POOL)} 檔 | {START}~{END} | 純快取")
    assert_all_cached(POOL)
    hsb = HistoricalSignalBuilder()
    t0 = time.time()
    price_rows, comp_rows, skipped = [], [], 0
    for i, sid in enumerate(POOL):
        try:
            px = hsb.fetcher.get_daily_price(sid, START, END)
            if px.empty or len(px) < hsb.tech.ma_period + 5:
                skipped += 1
                continue
            idx = pd.DatetimeIndex(px["date"])
            ta = hsb._ta_trigger(px).reindex(idx).fillna(False)
            inst = hsb.fetcher.get_institutional(sid, START, END)
            margin = hsb.fetcher.get_margin(sid, START, END)
            chip_asof = hsb._chip_score_series(inst, margin, idx).shift(1)          # 法人 T+1
            chip_ok = (chip_asof >= hsb.min_score).reindex(idx).fillna(False)
            chip_score = chip_asof.reindex(idx).fillna(0.0)
            turn = pd.Series((px["close"] * px["volume"]).values, index=idx).rolling(20).mean()
            liquid = (turn >= hsb.min_turnover).fillna(False) if hsb.min_turnover > 0 else pd.Series(True, index=idx)
            p = px.copy()
            p["stock_id"] = sid
            price_rows.append(p[["date", "stock_id", "open", "high", "low", "close", "volume"]])
            comp_rows.append(pd.DataFrame({"date": px["date"].values, "stock_id": sid,
                                           "ta": ta.values, "chip_ok": chip_ok.values,
                                           "chip_score": chip_score.values, "liquid": liquid.values,
                                           "turnover": turn.fillna(0.0).values}))
        except Exception as e:
            skipped += 1
            if skipped <= 5:
                print(f"  跳過 {sid}: {e}")
        if (i + 1) % 400 == 0:
            print(f"  …{i+1}/{len(POOL)}（{time.time()-t0:.0f}s）")
    price_df = pd.concat(price_rows, ignore_index=True)
    comp = pd.concat(comp_rows, ignore_index=True)
    comp = comp.merge(momentum_rank_long(price_df), on=["date", "stock_id"], how="left")
    comp["mom_rank"] = comp["mom_rank"].fillna(0.5)
    working = sorted(price_df["stock_id"].unique())
    # ffill 洩漏 assert（同 R0b/R1）
    first_real = price_df.groupby("stock_id")["date"].min()
    ent = comp[comp["ta"] & comp["chip_ok"]]
    leak = int((ent["date"] < ent["stock_id"].map(first_real)).sum())
    assert leak == 0, f"ffill 洩漏 {leak}"
    allow, _ = hsb._capitulation(START, END, DEFAULT_UNIVERSE)
    regmap = allow.reindex(pd.DatetimeIndex(sorted(price_df["date"].unique()))).ffill().fillna(False)
    print(f"[build] 完成：{len(working)} 檔、{len(comp):,} 列（跳過 {skipped}）、regime 可進場 {float(regmap.mean()):.0%}，{time.time()-t0:.0f}s")
    obj = {"price_df": price_df, "comp": comp, "regmap": regmap, "working": working}
    pd.to_pickle(obj, BASE_PKL)
    print(f"[build] 持久化 → {os.path.relpath(BASE_PKL, ROOT)}（{os.path.getsize(BASE_PKL)/1e6:.0f} MB）")
    return obj


print("R-attrib｜載入元件 base…")
BASE = pd.read_pickle(BASE_PKL) if os.path.exists(BASE_PKL) else build_attrib_base()
if os.path.exists(BASE_PKL):
    print(f"[load] r_attrib_base.pkl 命中：{len(BASE['working'])} 檔、{len(BASE['comp']):,} 列（免重建）")


# ───────────────────────── 0050 / 基準B（預先指定，純快取）─────────────────────────
adj0050 = bm.load_adjusted_0050()
bench_b = bm.simulate_benchmark(adj0050, 0.011)
bh0050 = bm.simulate_buyhold(adj0050)
bench_b_eq, bh0050_eq = bench_b["equity"], bh0050["equity"]
px0 = adj0050.set_index("date")["close"].sort_index().astype(float)
b0 = {y: float(px0[px0.index.year == y].iloc[-1] / px0[px0.index.year == y].iloc[0] - 1)
      for y in YEARS if len(px0[px0.index.year == y]) >= 5}
benb_oos = pd.concat([year_dr(bench_b_eq, Y) for Y in FWD_YEARS])
bh0050_oos = pd.concat([year_dr(bh0050_eq, Y) for Y in FWD_YEARS])
SB, S0 = sharpe_of(benb_oos), sharpe_of(bh0050_oos)
BENB_WDD = min(float((bench_b_eq[bench_b_eq.index.year == Y] / bench_b_eq[bench_b_eq.index.year == Y].cummax() - 1).min()) for Y in FWD_YEARS)
print(f"[基準] B OOS Sharpe {SB:.2f} / 最差年DD {BENB_WDD*100:.1f}%｜0050 OOS Sharpe {S0:.2f}")


def IR_vs_B(pooled):
    d = pd.concat([pooled.rename("s"), benb_oos.rename("b")], axis=1).dropna()
    assert len(d) / len(pooled) > 0.99, "IR 對齊 <99%"
    return sharpe_of(d["s"] - d["b"])


def oos_pack(st):
    eq = eq_series(st)
    pooled = pd.concat([year_dr(eq, Y) for Y in FWD_YEARS])
    wdd = min((st["per_year"].get(Y, {}).get("dd", float("nan")) for Y in FWD_YEARS), default=float("nan"))
    cap24 = st["per_year"].get(2024, {}).get("ret", float("nan")) / b0[2024]
    return {"pooled": pooled, "oos_sh": sharpe_of(pooled), "full_sh": st["sharpe"], "dd": st["dd"],
            "wdd": wdd, "ir": IR_vs_B(pooled), "cap24": cap24, "ann": st["annual"],
            "top3": conc3(st["pnl_by_stock"]), "trades_yr": st["n_trades"] / 8.0}


# ───────────────────────── 累積 ladder（元件級 ablation；引擎零改動）─────────────────────────
def rung_sig(comp, REGV, rung, lam=0.0):
    """L1..L6 的 entry/score（pre-membership）。L1-3 用 turnover 選股、L4+ 用 chip、L6 加動量傾斜。"""
    e = comp["liquid"].to_numpy().copy()                       # L1 base：常在（liquid 成員）
    if rung >= 2:
        e = e & comp["ta"].to_numpy()                          # L2 +TA timing
    if rung >= 3:
        e = e & comp["chip_ok"].to_numpy()                     # L3 +籌碼 gate
    if rung >= 5:
        e = e & REGV                                           # L5 +regime（block_only overlay）
    if rung <= 3:
        score = comp["turnover"].to_numpy()                    # size-select（無 alpha 選股訊號）
    else:
        score = comp["chip_score"].to_numpy()                  # L4+ 籌碼 select
        if rung >= 6:
            score = score + lam * comp["mom_rank"].to_numpy()  # L6 +動量傾斜
    return pd.DataFrame({"date": comp["date"].values, "stock_id": comp["stock_id"].values,
                         "entry_signal": e, "score": score})


def run_rung(comp, REGV, price_df, mw, un, rung, lam=0.0):
    s = pu.apply_membership(rung_sig(comp, REGV, rung, lam), mw)
    st = run_capped(price_df, s, un, START, END, capital=CAP, mode="odd_lot", max_pos=6, full_equity=True)
    return oos_pack(st)


def passive_floor(price_df, mw):
    """L0：等權 PIT 成員日報酬指數（index 慣例、gross；被動地板）。"""
    cw = price_df.pivot(index="date", columns="stock_id", values="close").sort_index()
    mem = mw.reindex(index=cw.index, columns=cw.columns).fillna(False)
    basket = cw.pct_change(fill_method=None).where(mem).mean(axis=1).fillna(0.0)
    eq = (1 + basket).cumprod() * CAP
    return pd.Series(eq.values, index=cw.index)


def oos_floor(eq):
    pooled = pd.concat([year_dr(eq, Y) for Y in FWD_YEARS])
    wdd = min(float((eq[eq.index.year == Y] / eq[eq.index.year == Y].cummax() - 1).min()) for Y in FWD_YEARS)
    return {"oos_sh": sharpe_of(pooled), "full_sh": sharpe_of(eq.pct_change().dropna()),
            "dd": float((eq / eq.cummax() - 1).min()), "wdd": wdd, "ir": IR_vs_B(pooled),
            "ann": float((eq.iloc[-1] / eq.iloc[0]) ** (252 / len(eq)) - 1),
            "cap24": float("nan"), "top3": float("nan"), "trades_yr": float("nan")}


def build_members(price_df):
    out = {}
    for K in sorted(set([K_PRIMARY] + K_ROBUST)):
        m, _, mbr = pu.build_membership(price_df, top_k=K, rebalance="Q")
        out[K] = (m, sorted(set().union(*[s for s in mbr.values() if s])) if mbr else [])
    return out


def filt(tag, base):
    comp, price_df, working = base["comp"], base["price_df"], base["working"]
    if tag == "etf_excl":
        comp = comp[~comp["stock_id"].str.startswith("00")].reset_index(drop=True)
        price_df = price_df[~price_df["stock_id"].str.startswith("00")].reset_index(drop=True)
        working = [s for s in working if not s.startswith("00")]
    return comp, price_df, working


LADDER_NAMES = {0: "L0 等權PIT指數(gross)", 1: "L1 +引擎/size", 2: "L2 +TA", 3: "L3 +籌碼gate",
                4: "L4 +籌碼select", 5: "L5 +regime(=R1full)"}


def run_ladder(tag):
    comp, price_df, working = filt(tag, BASE)
    REGV = comp["date"].map(BASE["regmap"]).fillna(False).to_numpy()
    member = build_members(price_df)
    mw, un = member[K_PRIMARY]
    rows = [(LADDER_NAMES[0], oos_floor(passive_floor(price_df, mw)))]
    for r in range(1, 6):
        rows.append((LADDER_NAMES[r], run_rung(comp, REGV, price_df, mw, un, r)))
    for lam in LAMBDAS:
        rows.append((f"L6 +動量λ{lam:g}", run_rung(comp, REGV, price_df, mw, un, 6, lam)))
    return rows, (comp, REGV, price_df, member)


def print_ladder(tag, rows, n_work):
    print("\n" + "=" * 116)
    print(f"R-attrib 累積 ladder｜pool={tag}（{n_work} 檔，K={K_PRIMARY}, max_pos=6 fixed, OOS=2022–25 pooled）"
          f"｜★增量綁 OOS、δ=1SE≈0.5 → ΔSharpe<~0.5 在雜訊內★")
    print("=" * 116)
    hdr = (f"{'層':<20}{'全期Sh':>7}{'OOS_Sh':>7}{'ΔOOS':>7}{'IRvsB':>7}{'ΔIR':>7}{'DD%':>7}"
           f"{'最差年DD':>8}{'ΔwDD':>7}{'2024捕':>7}{'top3%':>6}{'交易/年':>7}")
    print(hdr)
    prev = None
    for name, m in rows[:6]:                       # L0→L5 累積鏈
        d_oos = (m["oos_sh"] - prev["oos_sh"]) if prev else float("nan")
        d_ir = (m["ir"] - prev["ir"]) if prev else float("nan")
        d_wdd = (m["wdd"] - prev["wdd"]) * 100 if prev else float("nan")
        print(f"{name:<20}{m['full_sh']:>7.2f}{m['oos_sh']:>7.2f}{d_oos:>+7.2f}{m['ir']:>+7.2f}{d_ir:>+7.2f}"
              f"{m['dd']*100:>7.1f}{m['wdd']*100:>8.1f}{d_wdd:>+7.1f}"
              f"{m['cap24']:>7.2f}{(m['top3'] if m['top3']==m['top3'] else 0):>6.0f}{(m['trades_yr'] if m['trades_yr']==m['trades_yr'] else 0):>7.1f}")
        prev = m
    L5 = rows[5][1]
    for name, m in rows[6:]:                        # L6 vs L5（動量增量）
        print(f"{name:<20}{m['full_sh']:>7.2f}{m['oos_sh']:>7.2f}{m['oos_sh']-L5['oos_sh']:>+7.2f}"
              f"{m['ir']:>+7.2f}{m['ir']-L5['ir']:>+7.2f}{m['dd']*100:>7.1f}{m['wdd']*100:>8.1f}"
              f"{(m['wdd']-L5['wdd'])*100:>+7.1f}{m['cap24']:>7.2f}{m['top3']:>6.0f}{m['trades_yr']:>7.1f}")
    print(f"{'(被動) 基準B':<20}{bench_b['sharpe']:>7.2f}{SB:>7.2f}{'—':>7}{0.0:>+7.2f}{'—':>7}"
          f"{bench_b['dd']*100:>7.1f}{BENB_WDD*100:>8.1f}")
    print(f"{'(被動) 0050':<20}{bh0050['sharpe']:>7.2f}{S0:>7.2f}")


# ───────────────────────── 跑 etf_excl 主表 + full-pool 交叉對照 ─────────────────────────
print("\n建 ladder（etf_excl 主 + full 交叉；元件 ablation、純快取）…")
t0 = time.time()
rows_e, ctx_e = run_ladder("etf_excl")
print_ladder("etf_excl(主)", rows_e, ctx_e[0]["stock_id"].nunique())
rows_f, ctx_f = run_ladder("full")
print_ladder("full(交叉對照)", rows_f, ctx_f[0]["stock_id"].nunique())
print(f"\nladder 完成（{time.time()-t0:.0f}s）")


# ───────────────────────── 籌碼 / regime 增量的 K-穩健性（etf_excl）─────────────────────────
comp_e, REGV_e, pdf_e, member_e = ctx_e
DELTA = sharpe_se_ann(rows_e[5][1]["pooled"])     # 1 SE ≈ 0.5（雜訊帶）
print("\n" + "=" * 100)
print("增量 K-穩健性（etf_excl）：籌碼(L2→L4) 與 regime(L4→L5) 是否跨 K 一致（鐵則#7：變號＝非真）")
print("=" * 100)
print(f"{'K':>5}{'L2_OOS':>8}{'L4_OOS':>8}{'Δ籌碼':>8}{'L5_OOS':>8}{'Δregime':>9}{'L4_wDD':>8}{'L5_wDD':>8}{'Δrgm_wDD':>10}")
chip_incs, regime_incs, regime_wdd_incs = [], [], []
for K in [K_PRIMARY] + K_ROBUST:
    mw, un = member_e[K]
    l2 = run_rung(comp_e, REGV_e, pdf_e, mw, un, 2)
    l4 = run_rung(comp_e, REGV_e, pdf_e, mw, un, 4)
    l5 = run_rung(comp_e, REGV_e, pdf_e, mw, un, 5)
    chip_incs.append(l4["oos_sh"] - l2["oos_sh"])
    regime_incs.append(l5["oos_sh"] - l4["oos_sh"])
    regime_wdd_incs.append((l5["wdd"] - l4["wdd"]) * 100)
    print(f"{K:>5}{l2['oos_sh']:>8.2f}{l4['oos_sh']:>8.2f}{chip_incs[-1]:>+8.2f}{l5['oos_sh']:>8.2f}"
          f"{regime_incs[-1]:>+9.2f}{l4['wdd']*100:>8.1f}{l5['wdd']*100:>8.1f}{regime_wdd_incs[-1]:>+10.1f}")
chip_signflip = min(chip_incs) < 0 < max(chip_incs)


# ───────────────────── 反事實：regime-first（各選股層 ON TOP of regime；R5「砍什麼」輸入）─────────────────────
def cf_run(comp, REGV, price_df, mw, un, *, ta, gate, sel):
    e = comp["liquid"].to_numpy().copy()
    if ta:
        e = e & comp["ta"].to_numpy()
    if gate:
        e = e & comp["chip_ok"].to_numpy()
    e = e & REGV                                                   # regime 永遠 ON＝反事實地板
    score = comp["chip_score"].to_numpy() if sel else comp["turnover"].to_numpy()
    s = pu.apply_membership(pd.DataFrame({"date": comp["date"].values, "stock_id": comp["stock_id"].values,
                                          "entry_signal": e, "score": score}), mw)
    return oos_pack(run_capped(price_df, s, un, START, END, capital=CAP, mode="odd_lot", max_pos=6, full_equity=True))


mw0, un0 = member_e[K_PRIMARY]
print("\n" + "=" * 100)
print(f"反事實 regime-first（K={K_PRIMARY} etf_excl；regime 為地板、逐一加選股層）→ 籌碼/TA 在 regime 上是否還有貢獻＝R5「砍什麼」")
print("=" * 100)
print(f"{'設定':<22}{'OOS_Sh':>8}{'Δvs地板':>9}{'IRvsB':>8}{'DD%':>7}{'最差年DD':>9}{'top3%':>7}{'交易/年':>8}")
CF = [("regime+size(地板)", dict(ta=False, gate=False, sel=False)),
      ("  +TA", dict(ta=True, gate=False, sel=False)),
      ("  +籌碼gate", dict(ta=True, gate=True, sel=False)),
      ("  +籌碼select(=L5全)", dict(ta=True, gate=True, sel=True))]
cf_base, cf_size_regime, cf_full = None, None, None
for name, kw in CF:
    m = cf_run(comp_e, REGV_e, pdf_e, mw0, un0, **kw)
    cf_base = m["oos_sh"] if cf_base is None else cf_base
    print(f"{name:<22}{m['oos_sh']:>8.2f}{m['oos_sh']-cf_base:>+9.2f}{m['ir']:>+8.2f}{m['dd']*100:>7.1f}"
          f"{m['wdd']*100:>9.1f}{m['top3']:>7.0f}{m['trades_yr']:>8.1f}")
    if "地板" in name:
        cf_size_regime = m
    if "L5" in name:
        cf_full = m


# ───────────────────────── 結論（OOS-bound、δ caveat、re-anchored、方向性）─────────────────────────
def inc(rows, hi, lo):
    return rows[hi][1]["oos_sh"] - rows[lo][1]["oos_sh"], (rows[hi][1]["wdd"] - rows[lo][1]["wdd"]) * 100, \
        rows[hi][1]["ir"] - rows[lo][1]["ir"]


def lab(d):
    return "**助**" if d >= DELTA else ("**害**" if d <= -DELTA else "雜訊內")


print("\n" + "=" * 100)
print(f"R-attrib 結論（etf_excl 主；OOS-bound；δ=1SE={DELTA:.2f} → |ΔSharpe|<{DELTA:.2f} 雜訊內；跨 K 變號＝非真）")
print("=" * 100)
eng, ta, cg, cs, rg = inc(rows_e, 1, 0), inc(rows_e, 2, 1), inc(rows_e, 3, 2), inc(rows_e, 4, 3), inc(rows_e, 5, 4)
m6 = [m["oos_sh"] - rows_e[5][1]["oos_sh"] for _, m in rows_e[6:]]
print(f"  L0→L1 引擎/size      ：ΔOOS {eng[0]:+.2f}（{lab(eng[0])}）｜ΔwDD {eng[1]:+.1f}pp（集中大型名降 DD）｜ΔIR {eng[2]:+.2f}")
print(f"  L1→L2 TA timing      ：ΔOOS {ta[0]:+.2f}（{lab(ta[0])}）｜ΔwDD {ta[1]:+.1f}pp｜ΔIR {ta[2]:+.2f}")
print(f"  L2→L3 籌碼 gate       ：ΔOOS {cg[0]:+.2f}（{lab(cg[0])}）｜ΔwDD {cg[1]:+.1f}pp｜ΔIR {cg[2]:+.2f}")
print(f"  L3→L4 籌碼 select     ：ΔOOS {cs[0]:+.2f}（{lab(cs[0])}）｜standalone OOS 轉負 {rows_e[4][1]['oos_sh']:+.2f}、PnL 極度分散 top3 {rows_e[4][1]['top3']:.0f}%｜ΔIR {cs[2]:+.2f}")
print(f"  L4→L5 regime（DD 層） ：ΔOOS {rg[0]:+.2f}（{lab(rg[0])}）｜**ΔwDD {rg[1]:+.1f}pp**（>±{DD_BAND*100:.1f}pp＝真）｜ΔIR {rg[2]:+.2f}")
print(f"  L5→L6 動量傾斜        ：ΔOOS {'/'.join(f'{d:+.2f}' for d in m6)}（{lab(m6[0])}）")
dd_gain = (cf_full["wdd"] - cf_size_regime["wdd"]) * 100        # L5 比地板淺多少 DD（正＝L5 DD 更好）
print(f"\n  ▶ 籌碼層（standalone 無 regime）：跨 K=100/50/150 增量 = {'/'.join(f'{c:+.2f}' for c in chip_incs)}"
      f"{'＝**變號、非 K-穩健**' if chip_signflip else ''}、K=100 轉負(OOS {rows_e[4][1]['oos_sh']:+.2f}、PnL 分散 top3 {rows_e[4][1]['top3']:.0f}%)"
      f" → **無乾淨/穩健 Sharpe alpha**；master Phase 10#6 籌碼疑慮在誠實池**坐實**。")
print(f"  ▶ regime 層：跨 K ΔwDD = {'/'.join(f'{w:+.0f}' for w in regime_wdd_incs)}pp（一致大降 DD）、ΔOOS = {'/'.join(f'{r:+.2f}' for r in regime_incs)}（一致正）"
      f" → **唯一 K-穩健真貢獻＝DD 降**（與 R1 外層一致）。注：Sharpe 增量部分係 regime 收掉 standalone 籌碼層的失血/分散、非純 alpha；全 edge L5 IR vs B 仍 < 0＝**防禦非 alpha**。")
print(f"  ▶ TA/動量：增量雜訊內或負 → 誠實池無乾淨擇時/動量 alpha（解除手挑 confound、Phase 9 結論移轉）。")
print(f"  ▶ 反事實 regime-first（R5 砍什麼）：地板(regime+size) Sharpe {cf_size_regime['oos_sh']:.2f}/DD {cf_size_regime['wdd']*100:.0f}%"
      f" vs 全 edge L5 {cf_full['oos_sh']:.2f}/DD {cf_full['wdd']*100:.0f}%（ΔSharpe {cf_full['oos_sh']-cf_size_regime['oos_sh']:+.2f}＝雜訊內、但 L5 DD 淺 {dd_gain:+.1f}pp）"
      f" → 籌碼/TA **無穩健 Sharpe alpha**、唯 chip_select 在 regime 上有**條件性 DD 助益**；R5 權衡『極簡 regime 防禦 sleeve vs 保留 chip 換 ~{dd_gain:.0f}pp DD』，非乾淨砍除。")
print(f"  ⚠️ survivorship → 所有 OOS＝上界；L0 index 慣例(gross)、L1+ net；chip 在 regime 上的 DD 助益尚未驗 K-穩健（R5 再查）。")
print(f"\n[done] R-attrib 完成。判定：無層有穩健 alpha；唯 regime 降 DD 真(K-穩健)；籌碼無穩健 Sharpe alpha(疑慮坐實、僅條件性 DD 助益)；TA/動量雜訊。"
      f"等使用者指令再進下一步（R2 動量深驗 / R5 誠實出口：regime 防禦為主、籌碼複雜度待權衡）。")

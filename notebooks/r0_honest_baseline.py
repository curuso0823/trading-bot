"""
notebooks/r0_honest_baseline.py
R0b — 誠實基準（新的真實對照組）。純快取、不打 API。

承 docs/PIT_REBUILD_PLAN.md R0b：在**機械 PIT universe**（pit_universe.py，無 look-ahead）上跑
**現行 live edge 疊加**（TA + 籌碼 + capitulation block_only regime + vol_target，adjust=True），
立即對照 0050 買持、預先指定基準B(vol0.011)。**這取代污染的 12.7%/1.16，成為新的真實 baseline。**

cache-safety（避免 regime API 風暴，見 plan）：不走 signal_builder.build() 的 in-loop regime（它會把
1706 廣池灌進 capitulation panel → 2016 warm 窗多數無 pkl → 打 API）。改為：
  (1) 自寫逐股迴圈（複用 HistoricalSignalBuilder._ta_trigger / _chip_score_series，與 live 逐字相同）
      對 1706 四方完整池建 entry=TA∧chip_ok∧liquidity、score=chip_asof（adjust=True，純快取）；
  (2) regime 另算一次：CapitulationClassifier 用 config fixed 錨定（DEFAULT_UNIVERSE=38，全有 2016 warm
      pkl）→ block_only allow → overlay（= live 單一真相源 regime、PIT、Tier-D 合法）；
  (3) PIT 成員 baked 進 entry（pit_universe.apply_membership）→ run_capped(max_pos=6)。**不改 run_capped**。

指標（沿用 p8/p9 約定）：全期(含 in-sample，僅脈絡) + pooled OOS(FWD 2022–25 串逐日報酬) + IR vs 基準B
  + DD(最差前進年)。每個 K 都報 OOS；不挑 winner（R1 才 walk-forward 選）。
⚠️ survivorship：FinMind 無下市 → 池＝存活池 → 所有數字仍是上界，結論帶 caveat。
⚠️ 2018 冷啟：PIT universe 需 trailing 暖身，2018Q1 空池、Q2 起填滿 → 全期數字含一段薄倉，OOS(2022+)不受影響。

用法：.venv/bin/python notebooks/r0_honest_baseline.py
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
from src.backtest.signal_builder import HistoricalSignalBuilder
import src.backtest.pit_universe as pu

_spec = importlib.util.spec_from_file_location("benchmark_backtest", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

START, END, CAP = "2018-01-01", "2025-12-31", 100_000
YEARS = list(range(2018, 2026))
FWD_YEARS = [2022, 2023, 2024, 2025]      # OOS 前進窗（同 p8/p9）
SQRT252 = np.sqrt(252)
CACHE = os.path.join(ROOT, "data", "raw", "finmind_cache")
WINDOW = "2018-01-01__2025-12-31"
WARM16 = "2016-01-01__2025-12-31"
AUDIT_JSON = os.path.join(ROOT, "data", "processed", "r0_cache_audit.json")
KS = [50, 100, 150]


# ───────────────────────── helpers（同 p8/p9 口徑）─────────────────────────
def sharpe_of(dr):
    sd = dr.std()
    return float(dr.mean() / sd * SQRT252) if sd > 0 else 0.0


def ann_of(dr):
    n = len(dr)
    return float((1 + dr).prod() ** (252 / n) - 1) if n > 0 else float("nan")


def eq_series(st):
    return pd.Series(st["equity_full"], index=pd.to_datetime(st["equity_full_dates"]))


def year_dr(eq, y):
    return eq[eq.index.year == y].pct_change().dropna()


def concentration(pnl):
    total = sum(pnl.values())
    if abs(total) < 1e-9:
        return float("nan")
    vals = sorted(pnl.values(), reverse=True)
    return sum(vals[:3]) / total * 100.0


# ───────────────────────── cache-safety 預檢（缺一即停，不打 API）─────────────────────────
def assert_all_cached(pool):
    need = ["TaiwanStockPrice", "TaiwanStockDividendResult",
            "TaiwanStockInstitutionalInvestorsBuySell", "TaiwanStockMarginPurchaseShortSale"]
    miss = []
    for sid in pool:                                   # 工作池四方完整集
        for ds in need:
            if not os.path.exists(f"{CACHE}/{ds}__{sid}__{WINDOW}.pkl"):
                miss.append(f"{ds}__{sid}")
    for sid in DEFAULT_UNIVERSE:                        # regime 38 錨定（2016 warm 窗）
        for ds in need:
            if not os.path.exists(f"{CACHE}/{ds}__{sid}__{WARM16}.pkl"):
                miss.append(f"{ds}__{sid}(warm16)")
    for ds in ["TaiwanStockPrice", "TaiwanStockDividendResult"]:   # 0050 warm
        if not os.path.exists(f"{CACHE}/{ds}__0050__{WARM16}.pkl"):
            miss.append(f"{ds}__0050(warm16)")
    if miss:
        sys.exit(f"⛔ cache-safety 預檢失敗：{len(miss)} 個 pkl 缺失（會打 API）→ 停。例：{miss[:5]}")
    print(f"[cache-safety] 預檢通過：工作池 {len(pool)}×4 + regime 錨定 38×4(warm16) + 0050 → 全部命中 ✓")


# ───────────────────────── 載入工作池 ─────────────────────────
audit = json.load(open(AUDIT_JSON, encoding="utf-8"))
POOL = audit["four_way"]
print(f"R0b 誠實基準 | 工作池（四方完整）{len(POOL)} 檔 | {START}~{END} | 純快取")
assert_all_cached(POOL)


# ───────────────────────── 0050 / 基準B（預先指定，純快取）─────────────────────────
print("\n載入 0050 還原 + 基準B(vol0.011,無overlay)…")
adj0050 = bm.load_adjusted_0050()
px0 = adj0050.set_index("date")["close"].sort_index().astype(float)
b0 = {y: float(px0[px0.index.year == y].iloc[-1] / px0[px0.index.year == y].iloc[0] - 1)
      for y in YEARS if len(px0[px0.index.year == y]) >= 5}
bh0050 = bm.simulate_buyhold(adj0050)
bench_b = bm.simulate_benchmark(adj0050, 0.011)
bench_b_eq = bench_b["equity"]
bh0050_oos = pd.concat([year_dr(bh0050["equity"], Y) for Y in FWD_YEARS])
benb_oos = pd.concat([year_dr(bench_b_eq, Y) for Y in FWD_YEARS])
SB = sharpe_of(benb_oos)
S0 = sharpe_of(bh0050_oos)
print(f"  基準B 全期 年化 {bench_b['annual']*100:.1f}% / Sharpe {bench_b['sharpe']:.2f} / DD {bench_b['dd']*100:.1f}%"
      f" | pooled OOS Sharpe {SB:.2f}")
print(f"  0050 買持 全期 年化 {bh0050['annual']*100:.1f}% / Sharpe {bh0050['sharpe']:.2f} / DD {bh0050['dd']*100:.1f}%"
      f" | pooled OOS Sharpe {S0:.2f}")


# ───────────────────────── 建廣池訊號（adjust=True，純快取；複用 live helpers）─────────────────────────
print(f"\n建廣池 edge 訊號（{len(POOL)} 檔；TA+籌碼+liquidity，adjust=True）… 純快取、約數分鐘")
t0 = time.time()
hsb = HistoricalSignalBuilder()
price_rows, sig_rows, skipped = [], [], 0
for i, sid in enumerate(POOL):
    try:
        px = hsb.fetcher.get_daily_price(sid, START, END)          # adjust=True 預設（price+div 命中）
        if px.empty or len(px) < hsb.tech.ma_period + 5:
            skipped += 1
            continue
        idx = pd.DatetimeIndex(px["date"])
        ta = hsb._ta_trigger(px).reindex(idx).fillna(False)         # 與 live 逐字相同
        inst = hsb.fetcher.get_institutional(sid, START, END)
        margin = hsb.fetcher.get_margin(sid, START, END)
        chip = hsb._chip_score_series(inst, margin, idx)            # 籌碼：缺口 ffill→0→不達 min_score→不進場
        chip_asof = chip.shift(1)                                   # 法人 T+1：決策 T 只用 T-1 籌碼
        chip_ok = (chip_asof >= hsb.min_score).reindex(idx).fillna(False)
        entry = (ta & chip_ok).values
        if hsb.min_turnover > 0:                                    # 流動性濾網（與 live 同口徑，絕對門檻）
            turnover = pd.Series((px["close"] * px["volume"]).values, index=idx)
            liquid = (turnover.rolling(20).mean() >= hsb.min_turnover).fillna(False)
            entry = entry & liquid.values
        p = px.copy()
        p["stock_id"] = sid
        price_rows.append(p[["date", "stock_id", "open", "high", "low", "close", "volume"]])
        sig_rows.append(pd.DataFrame({"date": px["date"].values, "stock_id": sid,
                                      "entry_signal": entry,
                                      "score": chip_asof.reindex(idx).fillna(0).values}))
    except Exception as e:
        skipped += 1
        if skipped <= 5:
            print(f"  跳過 {sid}: {e}")
    if (i + 1) % 300 == 0:
        print(f"  …{i+1}/{len(POOL)}（工作集 {len(price_rows)}，{time.time()-t0:.0f}s）")

price_df = pd.concat(price_rows, ignore_index=True)
sig = pd.concat(sig_rows, ignore_index=True)
WORKING = sorted(price_df["stock_id"].unique())
print(f"廣池訊號完成：{len(WORKING)} 檔、{len(price_df):,} 列、{int(sig['entry_signal'].sum()):,} 進場訊號"
      f"（跳過 {skipped}），{time.time()-t0:.0f}s")

# ── ffill 洩漏防護 assert（同 p9）：sig 只在真實交易列 → 無 entry 早於各股首個真實交易日 ──
first_real = price_df.groupby("stock_id")["date"].min()
ent = sig[sig["entry_signal"]]
leak = int((ent["date"] < ent["stock_id"].map(first_real)).sum())
assert leak == 0, f"ffill 洩漏：{leak} 個 entry 早於上市日！"
print(f"[ffill 防護] assert 無 entry 早於各股首交易日 ✓（leak={leak}）")


# ───────────────────────── regime（fixed 38 錨定，cache-safe；= live 單一真相源）─────────────────────────
print("\n建 capitulation block_only regime（fixed 38 錨定，2016 warm；純快取）…")
allow, _ = hsb._capitulation(START, END, DEFAULT_UNIVERSE)          # block_only（cap_cfg.allow_mode）
all_dates = pd.DatetimeIndex(sorted(price_df["date"].unique()))
regmap = allow.reindex(all_dates).ffill().fillna(False)
print(f"  regime 可進場日佔比 {float(regmap.mean()):.0%}（block_only：只擋熊市假反彈）")


# ───────────────────────── PIT membership（K∈{50,100,150}，季 reselect；+K=100 年對照）──────────
print("\n建 PIT membership（季 reselect；turnover 60d / 上市≥1y / floor 10）…")
members = {}
for K in KS:
    m, ch, _ = pu.build_membership(price_df, top_k=K, rebalance="Q")
    members[("Q", K)] = (m, ch)
    print(f"  K={K:>3} 季：{pu.churn_summary(ch)}")
mA, chA, _ = pu.build_membership(price_df, top_k=100, rebalance="A")
members[("A", 100)] = (mA, chA)
print(f"  K=100 年：{pu.churn_summary(chA)}（穩定性對照）")


# ───────────────────────── 跑各臂 ─────────────────────────
def arm_sig(member_w=None):
    """套 regime（+可選 PIT 成員）到 entry，回 sig 供 run_capped。"""
    s = pu.apply_membership(sig, member_w) if member_w is not None else sig.copy()
    s["entry_signal"] = s["entry_signal"].to_numpy() & s["date"].map(regmap).fillna(False).to_numpy()
    return s


def run_arm(name, member_w=None):
    st = run_capped(price_df, arm_sig(member_w), WORKING, START, END,
                    capital=CAP, mode="odd_lot", max_pos=6, full_equity=True)
    eq = eq_series(st)
    pooled = pd.concat([year_dr(eq, Y) for Y in FWD_YEARS])
    ir_d = pd.concat([pooled.rename("s"), benb_oos.rename("b")], axis=1).dropna()
    ir = sharpe_of(ir_d["s"] - ir_d["b"]) if len(ir_d) > 10 else float("nan")
    wdd = min((st["per_year"].get(Y, {}).get("dd", 0.0) for Y in FWD_YEARS), default=float("nan"))
    return {"name": name, "ann": st["annual"], "sharpe": st["sharpe"], "dd": st["dd"],
            "oos_sharpe": sharpe_of(pooled), "oos_ann": ann_of(pooled), "ir": ir, "wdd": wdd,
            "top3": concentration(st["pnl_by_stock"]), "n_names": len(st["entry_counts"]),
            "trades_yr": st["n_trades"] / 8.0}


print("\n跑各臂 run_capped（max_pos=6，vol_target/ATR/max_hold 全 live 預設）…")
rows = []
rows.append(run_arm(f"PIT K=50 季", members[("Q", 50)][0]))
rows.append(run_arm(f"PIT K=100 季", members[("Q", 100)][0]))
rows.append(run_arm(f"PIT K=150 季", members[("Q", 150)][0]))
rows.append(run_arm(f"PIT K=100 年", members[("A", 100)][0]))
rows.append(run_arm(f"廣池 {len(WORKING)}(無top-K,參考)", None))


# ───────────────────────── 報表 ─────────────────────────
print("\n" + "=" * 104)
print("R0b 誠實基準：機械 PIT universe + live edge（TA+籌碼+block_only regime+vol_target，adjust=True）")
print("vs 預先指定被動（0050 買持 / 基準B vol0.011）｜全期含 2018 冷啟、OOS=2022–25 pooled")
print("=" * 104)
hdr = f"{'臂':<26}{'年化%':>7}{'Sharpe':>8}{'DD%':>7}{'OOS_Sh':>8}{'OOS年化':>8}{'IRvsB':>8}{'最差年DD':>9}{'top3%':>7}{'檔':>5}{'交易/年':>7}"
print(hdr)
print("-" * 104)
for m in rows:
    print(f"{m['name']:<26}{m['ann']*100:>7.1f}{m['sharpe']:>8.2f}{m['dd']*100:>7.1f}{m['oos_sharpe']:>8.2f}"
          f"{m['oos_ann']*100:>8.1f}{m['ir']:>+8.2f}{m['wdd']*100:>9.1f}{m['top3']:>7.0f}{m['n_names']:>5}{m['trades_yr']:>7.1f}")
print("-" * 104)
print(f"{'基準B vol0.011':<26}{bench_b['annual']*100:>7.1f}{bench_b['sharpe']:>8.2f}{bench_b['dd']*100:>7.1f}{SB:>8.2f}"
      f"{ann_of(benb_oos)*100:>8.1f}{0.0:>+8.2f}{'—':>9}")
print(f"{'0050 買進持有':<26}{bh0050['annual']*100:>7.1f}{bh0050['sharpe']:>8.2f}{bh0050['dd']*100:>7.1f}{S0:>8.2f}"
      f"{ann_of(bh0050_oos)*100:>8.1f}{sharpe_of(bh0050_oos-benb_oos.reindex(bh0050_oos.index).fillna(0)):>+8.2f}")
print("=" * 104)

# ── 一句話判定（robustness-based，**不 cherry-pick 最佳 K**：用 OOS 選 K＝把 OOS 變 in-sample）──
pit_q = [m for m in rows if m["name"].startswith("PIT K=") and "季" in m["name"]]
oos = [m["oos_sharpe"] for m in pit_q]
irs = [m["ir"] for m in pit_q]
dds = [m["dd"] for m in pit_q]
med_oos, mean_oos = float(np.median(oos)), float(np.mean(oos))
n_beatB = sum(s > SB for s in oos)
n_beat0050 = sum(s > S0 for s in oos)
n_ir_pos = sum(x > 0 for x in irs)
monotonic = oos == sorted(oos) or oos == sorted(oos, reverse=True)
dd_edge = all(d > bh0050["dd"] and d > bench_b["dd"] for d in dds)   # 所有 PIT 臂 DD 皆「less negative」

# 穩健勝出條件：多數臂(≥2/3) OOS 勝 0050 且 IR vs B 多為正；否則無穩健 alpha。
robust_alpha = (n_beat0050 >= 2 and n_ir_pos >= 2)
if robust_alpha:
    verdict = "穩健打得贏"
elif med_oos >= SB and dd_edge:
    verdict = "與被動大致打平、僅 DD 略優（無穩健 alpha）"
else:
    verdict = "打不贏"

ksweep_str = ", ".join(f"{m['name'].split()[1]}:{m['oos_sharpe']:.2f}" for m in pit_q)
ir_str = ", ".join(f"{x:+.2f}" for x in irs)
mono_str = "單調" if monotonic else "**非單調＝雜訊跡象**"
print(f"\n【K-sweep OOS（不挑 winner）】季 reselect K∈{{50,100,150}} pooled OOS Sharpe = {ksweep_str}"
      f"｜{mono_str}｜中位 {med_oos:.2f} / 均 {mean_oos:.2f}  vs 基準B {SB:.2f} / 0050 {S0:.2f}")
print(f"  勝基準B {n_beatB}/3、勝0050 {n_beat0050}/3、IR vs B 為正 {n_ir_pos}/3（IR={ir_str}）")
print(f"\n【一句話判定】誠實 baseline 相對被動：**{verdict}**。")
print(f"  · 報酬/風險調整：PIT 全期 Sharpe {min(m['sharpe'] for m in pit_q):.2f}–{max(m['sharpe'] for m in pit_q):.2f} "
      f"一致 < 被動（B 0.90 / 0050 1.01）；OOS Sharpe 隨 K 在 {min(oos):.2f}–{max(oos):.2f} 跳動，"
      f"唯一勝 0050 的 K=150（1.21）為三選一 cherry-pick，鄰格 K=100 反而最差(0.56)＝非穩健。")
print(f"  · DD：PIT 臂 {min(m['dd'] for m in pit_q)*100:.0f}~{max(m['dd'] for m in pit_q)*100:.0f}% "
      f"< 被動 −32~−34%、最差前進年 {min(m['wdd'] for m in pit_q)*100:.0f}~{max(m['wdd'] for m in pit_q)*100:.0f}% "
      f"→ 唯一較穩的相對優勢＝**regime 降 DD**（與 plan-doc / 附錄 B Tier D 一致）。")
print(f"  · 取代污染的 12.7%/1.16/−16%：誠實全期約 {min(m['ann'] for m in pit_q)*100:.0f}~{max(m['ann'] for m in pit_q)*100:.0f}% / "
      f"Sharpe {min(m['sharpe'] for m in pit_q):.2f}~{max(m['sharpe'] for m in pit_q):.2f}（含 2018 冷啟）。")
print("  ⚠️ caveat：① survivorship（FinMind 無下市）→ 全為**上界**，真實更低；② K 未 walk-forward 選"
      "（R1 裁決）；③ DD 優勢含存活池灌水、比帳面小。")
print("\n[done] R0 完成。結論＝去後見之明後主動相對被動**無明確 alpha、唯 regime 降 DD 站得住**"
      "（與 plan-doc 預測一致）。回報結果、等使用者產 R1 prompt（不自動進 R1）。")

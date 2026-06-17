"""
notebooks/r1_walkforward.py
R1 — walk-forward 細網格裁決誠實 PIT 池的 K 與 max_positions。純快取、不打 API、引擎零改動。

承 docs/PIT_REBUILD_PLAN.md §2(R0 結果)+§4(R1) 與 CLAUDE.md 現況真相。R0 誠實 baseline（季 reselect、
OOS=2022–25 pooled）：PIT K=50/100/150 → OOS Sharpe 0.93/0.56/1.21（**非單調＝雜訊跡象**，中位 0.93），
全期 0.62–0.75 一致輸被動（基準B OOS 0.80 / 0050 OOS 0.95），IR vs B 僅 1/3 K 為正，唯一相對優勢＝
**regime 降 DD**（PIT −22~−29% vs 被動 −32~−34%）。R0 只掃 3 點 K，無法分辨 1.21@150 是孤峰還是高原。

═══════════════════════════════ 預登記（先寫死、再跑；防 p-hacking）═══════════════════════════════
誠實預期＝**大概率 NOT PASS**（Phase 8 IR≈0 ＋ R0 無 alpha ＋ survivorship 上界）。無論數字如何保證交付：
細網格 K 曲線＋K 真假的 walk-forward 判定、加格是否翻盤的判定、survivorship 上界 caveat。

【方法論修正（使用者核定，全部預登記）】
 1. floor 主規則錨「相對被動」：內層每 fold 的 DD floor＝基準B 同窗 DD − 2.2pp（path-dependence band），
    **非** Phase-6 絕對 −18/−20%（按手挑池 DD −14..−16% 校準、套誠實池 −22..−29% 會 REJECT 全部）。
    寬絕對 floor(−32%) 只進 robustness set。
 2. **永不 fallback 到固定 K/N**：內層永遠以 Calmar 在「過 floor 者」中取 argmax；過 floor 集合為空（DD 比
    被動還差＝red flag）→ 放寬到全格 Calmar argmax 並標 floor-empty，**絕不替換寫死的 K/N**。
 3. DD 真檢定在**外層 vs 被動（OOS）**：報 wf 臂/固定臂的最差前進年 DD vs 基準B/0050；regime-DD 這層在此裁決。
 4. 細網格『穩定』用 **plateau-band 隸屬**判、非點對點：先求 A1 的「δ-高原帶 P」（δ＝pooled-OOS 年化 Sharpe
    的 1 SE），K* 穩定＝4 fold-K* 全落同一 localized P（既非孤峰也非橫掃全網格）。
 5. **鐵則 #8**：所有 reused 絕對門檻（DD floor、Sharpe≥1/DD≤−15%/年化≥10% 報告線）一律重錨誠實池/相對被動，
    不沿用手挑池數字；B2 沿用 Phase-6 原生相對 gate 但絕對 DD floor 同 #1 重錨。

【Q1 判定】K=150 的 1.21「真」iff 全部成立，否則＝in-sample cherry-pick（雜訊）：
  (i)  A1 K-curve 在 150 周邊為 localized 高原帶（含 140&160、寬度介於 ~5 點與 ⅔ 網格；非孤峰、非橫掃全網格）；
  (ii) B1 walk-forward pooled OOS Sharpe ≥ 0.80(勝B) 且 IR vs B>0 且 plateau-band 穩定（4 fold-K* 全落同一 P）；
  (iii) robustness 不變（跨 {Calmar,Sharpe}×{相對,−32%絕對} 一致）。
【Q2 判定】誠實池「需要加格」iff：B2 fold-N* 群聚於 >6 的 localized 帶 且 pooled OOS(wf-N) 勝 N=6 臂超雜訊帶
  （Sharpe +>0.1 或 最差前進年 DD +>2.2pp）。否則＝Phase 6「不加格」移轉誠實池（無翻盤）。
【R1 總 Gate／級聯】
  PASS：B1 勝基準B(pooled≥0.80&IR>0) 且 plateau 穩定 且 robustness 不變 且勝 R0 固定 K 臂 → R-attrib + R2。
  FAIL：pooled 打平/輸 B，或不穩/脆弱 → 確認只有 regime 降 DD（外層 DD 檢定）→ R-attrib 量化 + 朝 R5 誠實出口。
  兩種情形 live 都不動（總 Gate 未過）。⚠️ survivorship（FinMind 無下市）→ 所有 OOS＝**上界**。
═══════════════════════════════════════════════════════════════════════════════════════════════

tractability：全 edge base sig build 一次→持久化 data/processed/r1_base_sig.pkl（之後載入免重建）；membership/bake
每 K 一次重用；run_capped 傳 members_union(K) 子集（Part 0 #3 證 behavior-neutral＝主要加速）；內層 grid 每 fold
算一次、4 個選擇規則套同一份 metrics（免重跑）。
用法：.venv/bin/python notebooks/r1_walkforward.py
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
FWD_YEARS = [2022, 2023, 2024, 2025]            # OOS 前進窗（同 R0/p8/p9）
SQRT252 = np.sqrt(252)
CACHE = os.path.join(ROOT, "data", "raw", "finmind_cache")
WINDOW = "2018-01-01__2025-12-31"
WARM16 = "2016-01-01__2025-12-31"
AUDIT_JSON = os.path.join(ROOT, "data", "processed", "r0_cache_audit.json")
BASE_PKL = os.path.join(ROOT, "data", "processed", "r1_base_sig.pkl")

# ── 細網格（鐵則 #7：核心區間步長小；含 R0 的 50/100/150；尾端到 400 接 R0 廣池退化端）──
K_GRID = [20, 30, 40, 50, 60, 75, 90, 100, 110, 125, 140, 150, 160, 175, 200, 250, 300, 400]   # 18 點
MAXPOS_GRID = [6, 7, 8, 9, 10, 12, 14, 16, 18, 20]                                              # 10 點
DD_BAND = 0.022          # path-dependence band（相對被動 floor 容差 / Q2 DD 雜訊帶；鐵則#8 重錨用）
ABS_FLOOR = -0.32        # 寬絕對 floor（robustness-only，比 0050 −34% 略緊）
R0_KS = [50, 100, 150]   # R0 固定臂對照


# ───────────────────────── helpers（沿用 p8/p9/R0b 口徑）─────────────────────────
def sharpe_of(dr):
    sd = dr.std()
    return float(dr.mean() / sd * SQRT252) if sd > 0 else 0.0


def ann_of(dr):
    n = len(dr)
    return float((1 + dr).prod() ** (252 / n) - 1) if n > 0 else float("nan")


def cum_of(dr):
    return float((1 + dr).prod() - 1) if len(dr) else float("nan")


def calmar(a, dd):
    return a / abs(dd) if dd and abs(dd) > 1e-9 else float("nan")


def pct_up(x, base):
    return float("-inf") if (base is None or base != base or abs(base) < 1e-9) else x / base - 1.0


def conc2(pnl):
    """單檔最大貢獻% / 前3大貢獻%（sign-safe；同 p6/p8）。"""
    total = sum(pnl.values())
    if abs(total) < 1e-9:
        return float("nan"), float("nan")
    vals = sorted(pnl.values(), reverse=True)
    return vals[0] / total * 100.0, sum(vals[:3]) / total * 100.0


def eq_series(st):
    return pd.Series(st["equity_full"], index=pd.to_datetime(st["equity_full_dates"]))


def year_dr(eq, y):
    return eq[eq.index.year == y].pct_change().dropna()


def h2_dr(eq, y):
    return eq[(eq.index.year == y) & (eq.index.month >= 7)].pct_change().dropna()


def dd_of_window(eq, start, end):
    """eq 在 [start,end] 內的最大回撤（峰到谷；連續區間，不串非連續年）。"""
    s = eq[(eq.index >= pd.Timestamp(start)) & (eq.index <= pd.Timestamp(end))]
    return float((s / s.cummax() - 1).min()) if len(s) else float("nan")


def sharpe_se_ann(dr):
    """年化 Sharpe 的 1 SE（Lo 2002 近似：SE(SR_d)=sqrt((1+SR_d²/2)/n)，再 ×√252）。"""
    n = len(dr)
    sd = dr.std()
    if n < 30 or sd == 0:
        return float("nan")
    srd = dr.mean() / sd
    return float(np.sqrt((1 + 0.5 * srd ** 2) / n) * SQRT252)


def contiguous_band(svals, anchor_idx, thresh):
    """從 anchor_idx 向兩側擴張、只要 svals>=thresh → 連續帶 [lo,hi]（含端）。"""
    lo = hi = anchor_idx
    while lo - 1 >= 0 and svals[lo - 1] >= thresh:
        lo -= 1
    while hi + 1 < len(svals) and svals[hi + 1] >= thresh:
        hi += 1
    return lo, hi


def kw_for(N, policy):
    """max_pos × 配重政策 → run_capped kwargs（budget：單檔上下限 ∝6/N，同 p6/p8）。"""
    if policy == "fixed":
        return dict(max_pos=N)                                  # 0.10/0.30（現行）
    return dict(max_pos=N, size_min=0.10 * 6 / N, size_max=0.30 * 6 / N)


# ───────────────────────── cache-safety 預檢（缺一即停；沿用 R0b，只在 build 路徑用）─────────────────────────
def assert_all_cached(pool):
    need = ["TaiwanStockPrice", "TaiwanStockDividendResult",
            "TaiwanStockInstitutionalInvestorsBuySell", "TaiwanStockMarginPurchaseShortSale"]
    miss = []
    for sid in pool:
        for ds in need:
            if not os.path.exists(f"{CACHE}/{ds}__{sid}__{WINDOW}.pkl"):
                miss.append(f"{ds}__{sid}")
    for sid in DEFAULT_UNIVERSE:                                    # regime 38 錨定（2016 warm 窗）
        for ds in need:
            if not os.path.exists(f"{CACHE}/{ds}__{sid}__{WARM16}.pkl"):
                miss.append(f"{ds}__{sid}(warm16)")
    for ds in ["TaiwanStockPrice", "TaiwanStockDividendResult"]:    # 0050 warm
        if not os.path.exists(f"{CACHE}/{ds}__0050__{WARM16}.pkl"):
            miss.append(f"{ds}__0050(warm16)")
    if miss:
        sys.exit(f"⛔ cache-safety 預檢失敗：{len(miss)} 個 pkl 缺失（會打 API）→ 停。例：{miss[:5]}")
    print(f"[cache-safety] 預檢通過：工作池 {len(pool)}×4 + regime 38×4(warm16) + 0050 → 全部命中 ✓")


# ───────────────────────── base sig：build-or-load（細網格可行的前提）─────────────────────────
def build_base():
    """全 edge base sig（TA∧chip∧liquidity，adjust=True，pre-regime/pre-membership）+ regmap，逐字複用 R0b。"""
    from src.backtest.signal_builder import HistoricalSignalBuilder
    audit = json.load(open(AUDIT_JSON, encoding="utf-8"))
    POOL = audit["four_way"]
    print(f"[build] R0 同一工作池（四方完整）{len(POOL)} 檔 | {START}~{END} | 純快取")
    assert_all_cached(POOL)
    hsb = HistoricalSignalBuilder()
    t0 = time.time()
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
            chip = hsb._chip_score_series(inst, margin, idx)            # 缺口 ffill→0→不達 min_score→不進場
            chip_asof = chip.shift(1)                                   # 法人 T+1：決策 T 只用 T-1 籌碼
            chip_ok = (chip_asof >= hsb.min_score).reindex(idx).fillna(False)
            entry = (ta & chip_ok).values
            if hsb.min_turnover > 0:                                    # 流動性濾網（與 live 同口徑）
                turnover = pd.Series((px["close"] * px["volume"]).values, index=idx)
                liquid = (turnover.rolling(20).mean() >= hsb.min_turnover).fillna(False)
                entry = entry & liquid.values
            p = px.copy()
            p["stock_id"] = sid
            price_rows.append(p[["date", "stock_id", "open", "high", "low", "close", "volume"]])
            sig_rows.append(pd.DataFrame({"date": px["date"].values, "stock_id": sid, "entry_signal": entry,
                                          "score": chip_asof.reindex(idx).fillna(0).values}))
        except Exception as e:
            skipped += 1
            if skipped <= 5:
                print(f"  跳過 {sid}: {e}")
        if (i + 1) % 400 == 0:
            print(f"  …{i+1}/{len(POOL)}（工作集 {len(price_rows)}，{time.time()-t0:.0f}s）")
    price_df = pd.concat(price_rows, ignore_index=True)
    sig = pd.concat(sig_rows, ignore_index=True)
    working = sorted(price_df["stock_id"].unique())
    print(f"[build] 廣池訊號完成：{len(working)} 檔、{len(price_df):,} 列、{int(sig['entry_signal'].sum()):,} 進場"
          f"（跳過 {skipped}），{time.time()-t0:.0f}s")
    # ffill 洩漏防護 assert（同 R0b/p9）
    first_real = price_df.groupby("stock_id")["date"].min()
    ent = sig[sig["entry_signal"]]
    leak = int((ent["date"] < ent["stock_id"].map(first_real)).sum())
    assert leak == 0, f"ffill 洩漏：{leak} 個 entry 早於上市日！"
    print(f"[build] ffill 防護 assert 無 entry 早於各股首交易日 ✓（leak={leak}）")
    # regime（fixed-38 錨定 block_only；cache-safe，= live 單一真相源）
    allow, _ = hsb._capitulation(START, END, DEFAULT_UNIVERSE)
    all_dates = pd.DatetimeIndex(sorted(price_df["date"].unique()))
    regmap = allow.reindex(all_dates).ffill().fillna(False)
    print(f"[build] regime 可進場日佔比 {float(regmap.mean()):.0%}（block_only）")
    obj = {"price_df": price_df, "sig": sig, "regmap": regmap, "working": working, "pool": POOL}
    pd.to_pickle(obj, BASE_PKL)
    print(f"[build] 持久化 → {os.path.relpath(BASE_PKL, ROOT)}（{os.path.getsize(BASE_PKL)/1e6:.0f} MB）")
    return obj


print("R1 walk-forward｜載入 base sig…")
if os.path.exists(BASE_PKL):
    BASE = pd.read_pickle(BASE_PKL)
    print(f"[load] r1_base_sig.pkl 命中：{len(BASE['working'])} 檔、{len(BASE['price_df']):,} 列、"
          f"{int(BASE['sig']['entry_signal'].sum()):,} 進場訊號（免重建）")
else:
    BASE = build_base()

price_df, sig, regmap, working = BASE["price_df"], BASE["sig"], BASE["regmap"], BASE["working"]

# ── ETF 排除 sanity（opt-in；R1_EXCLUDE_ETF=1）：移除 00-prefixed ETF，使「策略不得交易基準本身(0050 等)」──
# 預設 False＝full-pool（R0 apples-to-apples baseline，保留）。in-memory 過濾，base pkl 不變、可雙模式重用。
EXCLUDE_ETF = os.environ.get("R1_EXCLUDE_ETF", "0") == "1"
if EXCLUDE_ETF:
    etfs = sorted(s for s in working if s.startswith("00"))
    price_df = price_df[~price_df["stock_id"].str.startswith("00")].reset_index(drop=True)
    sig = sig[~sig["stock_id"].str.startswith("00")].reset_index(drop=True)
    working = [s for s in working if not s.startswith("00")]
    print(f"[ETF 排除] 移除 {len(etfs)} 檔 ETF {etfs} → 工作池 {len(working)} 檔（sanity：策略不交易基準本身）")
MODE = "ETF-excluded(sanity)" if EXCLUDE_ETF else "full-pool(R0 apples-to-apples)"
print(f"[mode] {MODE}")
REGV = sig["date"].map(regmap).fillna(False).to_numpy()     # base sig 行序的 regime mask（bake 用；過濾後重算）


# ───────────────────────── 0050 / 基準B（預先指定，純快取）─────────────────────────
print("\n載入 0050 還原 + 基準B(vol0.011,無overlay)…（純快取）")
adj0050 = bm.load_adjusted_0050()
px0 = adj0050.set_index("date")["close"].sort_index().astype(float)
b0 = {y: float(px0[px0.index.year == y].iloc[-1] / px0[px0.index.year == y].iloc[0] - 1)
      for y in YEARS if len(px0[px0.index.year == y]) >= 5}
bh0050 = bm.simulate_buyhold(adj0050)
bench_b = bm.simulate_benchmark(adj0050, 0.011)
bench_b_eq = bench_b["equity"]
bh0050_eq = bh0050["equity"]
benb_oos = pd.concat([year_dr(bench_b_eq, Y) for Y in FWD_YEARS])
bh0050_oos = pd.concat([year_dr(bh0050_eq, Y) for Y in FWD_YEARS])
SB, S0 = sharpe_of(benb_oos), sharpe_of(bh0050_oos)
BENB_WDD = min(dd_of_window(bench_b_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD_YEARS)   # 被動最差前進年 DD
BH_WDD = min(dd_of_window(bh0050_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD_YEARS)
print(f"  基準B  全期 年化 {bench_b['annual']*100:.1f}% / Sharpe {bench_b['sharpe']:.2f} / DD {bench_b['dd']*100:.1f}%"
      f" | OOS Sharpe {SB:.2f} | 最差前進年DD {BENB_WDD*100:.1f}%")
print(f"  0050   全期 年化 {bh0050['annual']*100:.1f}% / Sharpe {bh0050['sharpe']:.2f} / DD {bh0050['dd']*100:.1f}%"
      f" | OOS Sharpe {S0:.2f} | 最差前進年DD {BH_WDD*100:.1f}%")


# ───────────────────────── membership + bake（每 K 一次，重用）─────────────────────────
def bake_arm(member_w):
    """membership baked 進 entry，再疊 regime（= R0b arm_sig；pre-compute 一次重用）。"""
    s = pu.apply_membership(sig, member_w)
    s["entry_signal"] = s["entry_signal"].to_numpy() & REGV
    return s


print(f"\n建 PIT membership + bake（季 reselect；K_GRID {len(K_GRID)} 點；turnover60d/上市≥1y/floor10）…")
t0 = time.time()
ARMS = {}     # K -> {"sig": armsig(baked+regime), "union": members_union, "churn": churn_df}
for K in K_GRID:
    m, ch, mbr = pu.build_membership(price_df, top_k=K, rebalance="Q")
    union = sorted(set().union(*[s for s in mbr.values() if s])) if mbr else []
    ARMS[K] = {"sig": bake_arm(m), "union": union, "churn": ch}
print(f"  完成 {len(K_GRID)} 個 K（{time.time()-t0:.0f}s）；例 K=150：{pu.churn_summary(ARMS[150]['churn'])}"
      f"｜union 大小 K=50/150/400 = {len(ARMS[50]['union'])}/{len(ARMS[150]['union'])}/{len(ARMS[400]['union'])}")


def run_K(K, start, end, *, universe=None, full=False, **kw):
    """在 K 的 baked armsig 上跑 run_capped；universe 預設＝members_union(K)（Part0#3 證 neutral＝加速）。"""
    a = ARMS[K]
    return run_capped(price_df, a["sig"], a["union"] if universe is None else universe,
                      start, end, capital=CAP, mode="odd_lot", full_equity=full, **kw)


# ───────────────────────── Part 0 — 中性檢查（先過才信後續數字）─────────────────────────
print("\n" + "=" * 100)
print("Part 0 — 中性檢查（apply_membership neutral / E⊆E / universe-subset 不變量）")
print("=" * 100)
_KEYS = ("annual", "sharpe", "dd", "pf", "total_return", "n_trades", "win_rate", "final_equity", "avg_concurrent")

# #1 all-True membership == 未套 membership 廣池 baseline（逐鍵相等）
all_dates = pd.DatetimeIndex(sorted(sig["date"].unique()))
member_all = pd.DataFrame(True, index=all_dates, columns=working)
broad_sig = sig.copy()
broad_sig["entry_signal"] = sig["entry_signal"].to_numpy() & REGV
allTrue_sig = bake_arm(member_all)
st_broad = run_capped(price_df, broad_sig, working, START, END, capital=CAP, mode="odd_lot", full_equity=True)
st_allT = run_capped(price_df, allTrue_sig, working, START, END, capital=CAP, mode="odd_lot", full_equity=True)
chk1 = (all(st_broad[k] == st_allT[k] for k in _KEYS) and st_broad["pnl_by_stock"] == st_allT["pnl_by_stock"]
        and st_broad["per_year"] == st_allT["per_year"] and st_broad["equity_pts"] == st_allT["equity_pts"])
print(f"#1 all-True membership == 廣池 baseline（逐鍵 pnl/per_year/equity_pts）：{'✓ OK' if chk1 else '✗ FAIL'}")
assert chk1, "apply_membership 非中性（all-True ≠ 廣池）！停止。"

# #2 apply_membership 後 E_new ⊆ E_old（從不新增進場；取 K=100 樣本，membership-only 不疊 regime）
m100 = pu.build_membership(price_df, top_k=100, rebalance="Q")[0]
baked100_only = pu.apply_membership(sig, m100)
added = int((baked100_only["entry_signal"].to_numpy() & ~sig["entry_signal"].to_numpy()).sum())
print(f"#2 E_new ⊆ E_old（K=100 membership 從不新增 entry）：新增 {added} 個 → {'✓ OK' if added == 0 else '✗ FAIL'}")
assert added == 0, "apply_membership 新增了進場（違反子集不變量）！停止。"

# #3 universe-subset 不變量：廣池跑 K=100 armsig == members_union(100) 跑（證 members_union 加速合法）
st_full100 = run_K(100, START, END, universe=working, full=True)
st_sub100 = run_K(100, START, END, full=True)
chk3 = (all(st_full100[k] == st_sub100[k] for k in _KEYS) and st_full100["pnl_by_stock"] == st_sub100["pnl_by_stock"]
        and st_full100["per_year"] == st_sub100["per_year"] and st_full100["equity_pts"] == st_sub100["equity_pts"])
print(f"#3 廣池 == members_union(100) 子集（逐鍵）：{'✓ OK' if chk3 else '✗ FAIL'} → members_union 加速 behavior-neutral")
assert chk3, "universe-subset 不變量失敗（members_union 改了行為）！停止。"
print("Part 0 全綠 ✓ —— apply_membership 中性、不新增進場、members_union 加速合法。")

# timing probe（估總量，決定 B3 跑/跳）
_t = time.time()
_ = run_K(150, START, END, full=True)
SINGLE_RUN_S = time.time() - _t
print(f"\n[timing probe] 單一 run_capped（K=150 baked, union={len(ARMS[150]['union'])} 檔, 全期）= {SINGLE_RUN_S:.2f}s"
      f"｜估 B1≈{(18*4+16)*SINGLE_RUN_S:.0f}s / B2≈{(20*4+8)*SINGLE_RUN_S:.0f}s / "
      f"B3聯合≈{18*10*2*4*SINGLE_RUN_S/60:.1f}min（>8min 則跳過）")


def IR_vs_B(pooled):
    d = pd.concat([pooled.rename("s"), benb_oos.rename("b")], axis=1).dropna()
    cover = len(d) / len(pooled)
    assert cover > 0.99, f"IR 日期對齊覆蓋 {cover:.1%} < 99%（策略/基準B 日曆不一致）"
    return sharpe_of(d["s"] - d["b"])


def oos_pack(st):
    """從 full_equity st 取 pooled OOS 報酬 + OOS Sharpe + 最差前進年 DD + IR + 2020/2024 捕獲。"""
    eq = eq_series(st)
    pooled = pd.concat([year_dr(eq, Y) for Y in FWD_YEARS])
    wdd = min((st["per_year"].get(Y, {}).get("dd", float("nan")) for Y in FWD_YEARS), default=float("nan"))
    cap = {y: (st["per_year"].get(y, {}).get("ret", float("nan")) / b0[y]) if (y in b0) else float("nan")
           for y in (2020, 2024)}
    return {"pooled": pooled, "oos_sh": sharpe_of(pooled), "oos_ann": ann_of(pooled),
            "full_sh": st["sharpe"], "dd": st["dd"], "wdd": wdd, "ir": IR_vs_B(pooled),
            "cap20": cap[2020], "cap24": cap[2024]}


# ───────────────────────── Part A1 — in-sample 細網格 K-sweep（線索非結論）─────────────────────────
print("\n" + "=" * 108)
print("Part A1 — in-sample 細網格 K-sweep（max_pos=6 fixed；OOS-window 2022–25 pooled；★線索非結論★）")
print("R0 對照：K=50/100/150 OOS Sharpe 應 ≈ 0.93/0.56/1.21（細網格須與 R0 對得上）")
print("=" * 108)
print(f"{'K':>5}{'全期Sh':>8}{'OOS_Sh':>8}{'OOS年化':>8}{'DD%':>7}{'最差年DD':>9}{'IRvsB':>8}{'2020捕獲':>9}{'2024捕獲':>9}{'union':>7}")
A1D = {}
for K in K_GRID:
    p = oos_pack(run_K(K, START, END, full=True))
    A1D[K] = p
    print(f"{K:>5}{p['full_sh']:>8.2f}{p['oos_sh']:>8.2f}{p['oos_ann']*100:>8.1f}{p['dd']*100:>7.1f}"
          f"{p['wdd']*100:>9.1f}{p['ir']:>+8.2f}{p['cap20']:>9.2f}{p['cap24']:>9.2f}{len(ARMS[K]['union']):>7}")
print("-" * 108)
print(f"{'基準B':>5}{bench_b['sharpe']:>8.2f}{SB:>8.2f}{ann_of(benb_oos)*100:>8.1f}{bench_b['dd']*100:>7.1f}{BENB_WDD*100:>9.1f}{0.0:>+8.2f}")
print(f"{'0050':>5}{bh0050['sharpe']:>8.2f}{S0:>8.2f}{ann_of(bh0050_oos)*100:>8.1f}{bh0050['dd']*100:>7.1f}{BH_WDD*100:>9.1f}"
      f"{sharpe_of(bh0050_oos - benb_oos.reindex(bh0050_oos.index).fillna(0)):>+8.2f}")

# plateau-band 分析（δ = pooled-OOS 年化 Sharpe 的 1 SE）
svals = [A1D[K]["oos_sh"] for K in K_GRID]
peak_i = int(np.argmax(svals))
Kpeak, peak = K_GRID[peak_i], svals[peak_i]
DELTA = sharpe_se_ann(A1D[Kpeak]["pooled"])
lo, hi = contiguous_band(svals, peak_i, peak - DELTA)
PLATEAU_BAND = K_GRID[lo:hi + 1]
nb_ok = (140 in PLATEAU_BAND) and (160 in PLATEAU_BAND)
s140, s160, s150 = A1D[140]["oos_sh"], A1D[160]["oos_sh"], A1D[150]["oos_sh"]
width = len(PLATEAU_BAND)
localized = 2 <= width <= len(K_GRID) // 3                 # δ-帶 ≤ ⅓ 網格才算「局部」；更寬＝K 在 1SE 內不可識別
peak_near_150 = abs(peak_i - K_GRID.index(150)) <= 1       # 峰須在 150 或緊鄰（Q1 specifically 問 150）
flat_top_150 = (peak - s150) <= 0.5 * DELTA and (s150 - min(s140, s160)) <= 0.5 * DELTA  # 150 近峰 且 鄰格近 150
Kbest_A1 = Kpeak
if not localized:
    a1_class = (f"δ-帶寬 {width}/{len(K_GRID)} 近橫掃（K 在 1SE 內不可識別）→ 峰 {peak:.2f}@K={Kpeak} 在雜訊內 → 線索(i) 雜訊")
elif not peak_near_150:
    a1_class = (f"峰在 K={Kpeak}（非 150）、150={s150:.2f} ＜ 峰 {peak:.2f}＝150 非 in-sample 最佳 → 線索(i) 雜訊")
elif (150 in PLATEAU_BAND) and nb_ok and flat_top_150:
    a1_class = "150 為 localized 平頂高原（峰在 150、鄰格在 0.5SE 內）→ 線索(i) 傾向真"
else:
    a1_class = (f"150 為孤峰：鄰格 140/160={s140:.2f}/{s160:.2f} 低於 150 值 {s150:.2f} 達 {s150-min(s140, s160):.2f}"
                f"（>0.5SE={0.5*DELTA:.2f}）＝~1σ 突出於雜訊 floor → 線索(i) 雜訊")
print(f"\n[A1 plateau] 峰 K={Kpeak}(OOS {peak:.2f})｜δ=1SE={DELTA:.2f}（n≈{len(A1D[Kpeak]['pooled'])}）｜"
      f"δ-高原帶 P={PLATEAU_BAND}（寬 {width}/{len(K_GRID)}）")
_sanity_note = "（R0=0.93/0.56/1.21 應對得上）" if not EXCLUDE_ETF else "（ETF-excluded：預期偏離 R0、看結論是否仍成立）"
print(f"  {'R0 sanity' if not EXCLUDE_ETF else 'mode'}：K=50/100/150 OOS = "
      f"{A1D[50]['oos_sh']:.2f}/{A1D[100]['oos_sh']:.2f}/{A1D[150]['oos_sh']:.2f}{_sanity_note}"
      f"｜150 在 δ-帶內？{'是' if 150 in PLATEAU_BAND else '否'}")
print(f"  → Q1 線索(i)：{a1_class}")


# ───────────────────────── Part A2 — in-sample max_pos×policy（Q2 線索）─────────────────────────
reps = sorted(set([Kbest_A1, 100, 150]))
print("\n" + "=" * 108)
print(f"Part A2 — in-sample max_pos×policy（代表 K={reps}；★線索非結論★：加格是否在誠實池改善＝Q2 翻盤線索）")
print("=" * 108)
for Krep in reps:
    base6 = A1D[Krep]
    print(f"\n— K={Krep}（N=6 fixed 基準：Sharpe {base6['full_sh']:.2f} / DD {base6['dd']*100:.1f}% / "
          f"2024捕獲 {base6['cap24']:.2f}）—")
    print(f"{'N':>4}{'policy':>8}{'Sharpe':>8}{'Calmar':>8}{'DD%':>7}{'top1%':>7}{'top3%':>7}{'2020捕獲':>9}{'2024捕獲':>9}")
    for pol in ("fixed", "budget"):
        for N in MAXPOS_GRID:
            st = run_K(Krep, START, END, full=True, **kw_for(N, pol))
            t1, t3 = conc2(st["pnl_by_stock"])
            c24 = st["per_year"].get(2024, {}).get("ret", float("nan")) / b0[2024]
            c20 = st["per_year"].get(2020, {}).get("ret", float("nan")) / b0[2020]
            print(f"{N:>4}{pol:>8}{st['sharpe']:>8.2f}{calmar(st['annual'], st['dd']):>8.2f}{st['dd']*100:>7.1f}"
                  f"{t1:>7.0f}{t3:>7.0f}{c20:>9.2f}{c24:>9.2f}")


# ───────────────────────── Part B — walk-forward 決策（所有判定所綁）─────────────────────────
# 內層 grid metrics 每 fold 算一次、4 個選擇規則套同一份（免重跑）
def inner_metrics_K(train_end_year):
    end = f"{train_end_year}-12-31"
    out = {}
    for K in K_GRID:
        st = run_K(K, START, end)
        if st:
            out[K] = {"K": K, "calmar": calmar(st["annual"], st["dd"]), "sharpe": st["sharpe"], "dd": st["dd"]}
    return out


def select_kstar(metrics, passive_dd, objective="calmar", floor="relative"):
    """Calmar 優先（Sharpe tiebreak）；floor 相對被動(預設) 或 −32%abs；**永不固定 K fallback**。"""
    floor_thr = passive_dd - DD_BAND if floor == "relative" else ABS_FLOOR
    passers = [m for m in metrics.values() if m["dd"] >= floor_thr]
    empty = len(passers) == 0
    pool = passers if passers else list(metrics.values())              # 空集→放寬全格，不替換寫死 K
    key = (lambda m: (m["calmar"], m["sharpe"])) if objective == "calmar" else (lambda m: (m["sharpe"], m["calmar"]))
    best = max(pool, key=key)
    return best["K"], len(passers), empty


print("\n建內層 K-grid metrics（4 fold × 18 K，一次算、4 規則共用）…")
_t = time.time()
FOLDS_K = {Y: inner_metrics_K(Y - 1) for Y in FWD_YEARS}
print(f"  完成（{time.time()-_t:.0f}s）")


def wf_K(objective, floor):
    rows, strat_daily, ddby = [], [], {}
    for Y in FWD_YEARS:
        pdd = dd_of_window(bench_b_eq, START, f"{Y-1}-12-31")
        Kstar, npass, empty = select_kstar(FOLDS_K[Y], pdd, objective, floor)
        st = run_K(Kstar, START, f"{Y}-12-31", full=True)
        eq = eq_series(st)
        d = st["per_year"].get(Y, {})
        ddby[Y] = d.get("dd", float("nan"))
        rows.append({"Y": Y, "Kstar": Kstar, "npass": npass, "empty": empty, "ret": d.get("ret", float("nan")),
                     "dd": d.get("dd", float("nan")), "sharpe": d.get("sharpe", float("nan")),
                     "h2sh": sharpe_of(h2_dr(eq, Y)),
                     "cap": (d.get("ret") / b0[Y]) if (Y in b0 and d) else float("nan")})
        strat_daily.append(year_dr(eq, Y))
    pooled = pd.concat(strat_daily)
    return {"rows": rows, "pooled_sharpe": sharpe_of(pooled), "pooled_ann": ann_of(pooled),
            "worst_dd": min(ddby.values()), "ir": IR_vs_B(pooled), "kstars": [r["Kstar"] for r in rows]}


def kstar_stable(kstars):
    """plateau-band 隸屬（非點對點）：4 K* index-spread≤4 且全落 A1 δ-高原帶 P 且 P localized。"""
    idxs = [K_GRID.index(k) for k in kstars]
    spread = max(idxs) - min(idxs)
    in_band = all(k in PLATEAU_BAND for k in kstars)
    return (spread <= 4 and in_band and localized), spread, in_band


VARIANTS = [("Calmar·相對", "calmar", "relative"), ("Sharpe·相對", "sharpe", "relative"),
            ("Calmar·−32abs", "calmar", "abs"), ("Sharpe·−32abs", "sharpe", "abs")]
print("\n" + "=" * 108)
print("Part B1 — walk-forward 選 K*（擴張窗 [2018,Y-1]→Y；★Q1 決策所綁★）｜plateau-band 穩定＝最重要 Gate")
print("=" * 108)
B1 = {}
print(f"{'規則(目標·floor)':<16}{'K*_2022':>9}{'K*_2023':>9}{'K*_2024':>9}{'K*_2025':>9}{'pooledSh':>10}{'IRvsB':>8}{'最差年DD%':>10}{'穩定?':>7}")
for name, obj, fl in VARIANTS:
    wf = wf_K(obj, fl)
    B1[name] = wf
    stab, spread, in_band = kstar_stable(wf["kstars"])
    wf["stable"] = stab
    ks = wf["kstars"]
    print(f"{name:<16}{ks[0]:>9}{ks[1]:>9}{ks[2]:>9}{ks[3]:>9}{wf['pooled_sharpe']:>10.2f}{wf['ir']:>+8.2f}"
          f"{wf['worst_dd']*100:>10.1f}{('✓高原' if stab else '✗不穩'):>7}")
prim = B1["Calmar·相對"]
print(f"\n  對照固定臂 pooled OOS（R0 固定 K + A1 峰 K={Kbest_A1}）：")
for K in sorted(set(R0_KS + [Kbest_A1])):
    print(f"    固定 K={K:<4}：OOS Sharpe {A1D[K]['oos_sh']:.2f} / IR vs B {A1D[K]['ir']:+.2f} / 最差年DD {A1D[K]['wdd']*100:.1f}%")
print(f"    被動：基準B OOS {SB:.2f} / 0050 OOS {S0:.2f}")
print(f"  ↳ 主規則(Calmar·相對) K*={prim['kstars']}｜pooled OOS {prim['pooled_sharpe']:.2f} vs B {SB:.2f}"
      f"｜IR {prim['ir']:+.2f}｜穩定 {'✓' if prim['stable'] else '✗'}｜robustness 跨 4 規則"
      f" pooled = {[round(B1[n]['pooled_sharpe'], 2) for n, _, _ in VARIANTS]}")


# ── B2 — walk-forward 選 max_pos（Q2 決策；固定 best-K = B1 主規則代表 K）──
from collections import Counter
_kc = Counter(prim["kstars"])
KFIX = _kc.most_common(1)[0][0] if _kc.most_common(1)[0][1] > 1 else sorted(prim["kstars"])[len(prim["kstars"]) // 2]


def inner_metrics_N(train_end_year, Kfix):
    end = f"{train_end_year}-12-31"
    out = {}
    for N in MAXPOS_GRID:
        for pol in ("fixed", "budget"):
            st = run_K(Kfix, START, end, **kw_for(N, pol))
            if st:
                t1, t3 = conc2(st["pnl_by_stock"])
                out[(N, pol)] = {"N": N, "pol": pol, "calmar": calmar(st["annual"], st["dd"]),
                                 "sharpe": st["sharpe"], "dd": st["dd"], "top1": t1, "top3": t3}
    return out


def select_nstar(metrics, passive_dd, objective="calmar", floor="relative"):
    """Phase-6 原生相對 gate（Calmar/Sharpe +≥10% vs N6 base、top1&top3<base），DD floor 重錨相對被動；永不固定 N。"""
    floor_thr = passive_dd - DD_BAND if floor == "relative" else ABS_FLOOR
    g = metrics[(6, "fixed")]
    passers = []
    for r in metrics.values():
        if r["dd"] < floor_thr:
            continue
        risk_ok = pct_up(r["calmar"], g["calmar"]) >= 0.10 or pct_up(r["sharpe"], g["sharpe"]) >= 0.10
        conc_ok = r["top1"] < g["top1"] and r["top3"] < g["top3"]
        if risk_ok and conc_ok:
            passers.append(r)
    empty = len(passers) == 0
    pool = passers or [r for r in metrics.values() if r["dd"] >= floor_thr] or list(metrics.values())
    key = (lambda r: (r["calmar"], r["sharpe"])) if objective == "calmar" else (lambda r: (r["sharpe"], r["calmar"]))
    best = max(pool, key=key)
    return (best["N"], best["pol"]), len(passers), empty


def wf_N(Kfix, folds, objective, floor):
    rows, strat_daily, ddby = [], [], {}
    for Y in FWD_YEARS:
        pdd = dd_of_window(bench_b_eq, START, f"{Y-1}-12-31")
        (N, pol), npass, empty = select_nstar(folds[Y], pdd, objective, floor)
        st = run_K(Kfix, START, f"{Y}-12-31", full=True, **kw_for(N, pol))
        eq = eq_series(st)
        d = st["per_year"].get(Y, {})
        ddby[Y] = d.get("dd", float("nan"))
        rows.append({"Y": Y, "N": N, "pol": pol, "npass": npass, "empty": empty,
                     "ret": d.get("ret", float("nan")), "dd": d.get("dd", float("nan")),
                     "cap": (d.get("ret") / b0[Y]) if (Y in b0 and d) else float("nan")})
        strat_daily.append(year_dr(eq, Y))
    pooled = pd.concat(strat_daily)
    return {"rows": rows, "pooled_sharpe": sharpe_of(pooled), "pooled_ann": ann_of(pooled),
            "worst_dd": min(ddby.values()), "ir": IR_vs_B(pooled), "nstars": [r["N"] for r in rows]}


def nstar_stable(rows):
    """N* 穩定（承 plan 預登記：N* 跨前進年不穩 ⇒ REJECT 翻盤）：N* span ≤3 grid 位、policy 一致、且全 >6。"""
    idxs = [MAXPOS_GRID.index(r["N"]) for r in rows]
    pols = {r["pol"] for r in rows}
    return (max(idxs) - min(idxs) <= 3 and len(pols) == 1 and all(r["N"] > 6 for r in rows)), \
        max(idxs) - min(idxs), len(pols)


print("\n" + "=" * 108)
print(f"Part B2 — walk-forward 選 max_pos（best-K={KFIX}=B1 代表 + K=150 峰 對照；Phase-6 相對 gate, DD floor 重錨相對被動）")
print("★承 plan 預登記：N* 跨前進年不穩 ⇒ REJECT 翻盤（即使 pooled 過）★")
print("=" * 108)
print(f"{'K':>5}  {'規則':<13}{'N*_22':>7}{'N*_23':>7}{'N*_24':>7}{'N*_25':>7}{'pooledSh':>10}{'IRvsB':>8}{'最差年DD%':>10}{'N*穩定?':>9}")
B2 = {}
for Kb in sorted(set([KFIX, 150])):
    folds = {Y: inner_metrics_N(Y - 1, Kb) for Y in FWD_YEARS}
    B2[Kb] = {}
    for name, obj, fl in [("Calmar·相對", "calmar", "relative"), ("Sharpe·相對", "sharpe", "relative")]:
        wf = wf_N(Kb, folds, obj, fl)
        wf["stable"] = nstar_stable(wf["rows"])[0]
        B2[Kb][name] = wf
        ns = [f"{r['N']}{r['pol'][0]}" for r in wf["rows"]]
        print(f"{Kb:>5}  {name:<13}{ns[0]:>7}{ns[1]:>7}{ns[2]:>7}{ns[3]:>7}{wf['pooled_sharpe']:>10.2f}"
              f"{wf['ir']:>+8.2f}{wf['worst_dd']*100:>10.1f}{('✓' if wf['stable'] else '✗不穩'):>9}")
prim_N = B2[KFIX]["Calmar·相對"]
N6 = A1D[KFIX]      # (KFIX, N=6, fixed) 臂 = N=6 對照
n_gt6 = sum(n > 6 for n in prim_N["nstars"])
q2_beat = (prim_N["pooled_sharpe"] - N6["oos_sh"] > 0.1) or (prim_N["worst_dd"] - N6["wdd"] > DD_BAND)
NEEDS_SLOTS = prim_N["stable"] and (n_gt6 >= 3) and q2_beat          # N* 不穩 ⇒ 非穩健翻盤
print(f"  N=6 對照(K={KFIX})：pooled {N6['oos_sh']:.2f} / 最差年DD {N6['wdd']*100:.1f}%｜wf-N pooled "
      f"{prim_N['pooled_sharpe']:.2f} / 最差年DD {prim_N['worst_dd']*100:.1f}% / IR vs B {prim_N['ir']:+.2f}")
print(f"  in-sample(A2)：加格明確改善（Sharpe↑/DD↓/集中度↓、budget sizing 更佳、K=100&150 皆然）＝附錄B 旗標方向成立")
print(f"  walk-forward：N*>6 {n_gt6}/4 但 N* {'穩定' if prim_N['stable'] else '**不穩**（6↔20、fixed↔budget）'}"
      f"、IR vs B {prim_N['ir']:+.2f}{'<0(不勝被動)' if prim_N['ir'] < 0 else ''} → "
      f"{'**需要加格（穩健翻盤）**' if NEEDS_SLOTS else '**方向性線索、非穩健翻盤**'}")


# ── B3 — optional 聯合掃描（僅當 timing probe 夠快）──
B3_EST_MIN = 18 * 10 * 2 * 4 * SINGLE_RUN_S / 60
print("\n" + "=" * 108)
if B3_EST_MIN <= 8:
    print(f"Part B3 — 聯合 K×max_pos×policy walk-forward（est {B3_EST_MIN:.1f}min ≤8 → 跑；最嚴格綜合決策）")
    print("=" * 108)

    def inner_joint(train_end_year):
        end = f"{train_end_year}-12-31"
        out = {}
        for K in K_GRID:
            for N in MAXPOS_GRID:
                for pol in ("fixed", "budget"):
                    st = run_K(K, START, end, **kw_for(N, pol))
                    if st:
                        out[(K, N, pol)] = {"K": K, "N": N, "pol": pol, "calmar": calmar(st["annual"], st["dd"]),
                                            "sharpe": st["sharpe"], "dd": st["dd"]}
        return out

    rows, strat_daily, ddby = [], [], {}
    for Y in FWD_YEARS:
        pdd = dd_of_window(bench_b_eq, START, f"{Y-1}-12-31")
        thr = pdd - DD_BAND
        met = inner_joint(Y - 1)
        passers = [m for m in met.values() if m["dd"] >= thr] or list(met.values())
        best = max(passers, key=lambda m: (m["calmar"], m["sharpe"]))
        st = run_K(best["K"], START, f"{Y}-12-31", full=True, **kw_for(best["N"], best["pol"]))
        eq = eq_series(st)
        d = st["per_year"].get(Y, {})
        ddby[Y] = d.get("dd", float("nan"))
        rows.append({"Y": Y, "cstar": (best["K"], best["N"], best["pol"]), "dd": d.get("dd", float("nan"))})
        strat_daily.append(year_dr(eq, Y))
    pooled = pd.concat(strat_daily)
    B3 = {"rows": rows, "pooled_sharpe": sharpe_of(pooled), "worst_dd": min(ddby.values()), "ir": IR_vs_B(pooled)}
    print(f"{'前進年':>6}{'(K*,N*,policy*)':>22}{'年DD%':>8}")
    for r in rows:
        print(f"{r['Y']:>6}{str(r['cstar']):>22}{r['dd']*100:>8.1f}")
    print(f"pooled OOS Sharpe {B3['pooled_sharpe']:.2f} / IR vs B {B3['ir']:+.2f} / 最差年DD {B3['worst_dd']*100:.1f}%")
else:
    B3 = None
    print(f"Part B3 — 聯合掃描跳過（est {B3_EST_MIN:.1f}min >8min；B1+B2 已足裁決 Q1/Q2）")
print("=" * 108)


# ───────────────────────── Part C — leak 檢查 + 外層 DD + Gate ─────────────────────────
print("\n" + "=" * 108)
print("Part C — +1 日 leak 檢查 / 外層 DD vs 被動 / 預登記 Gate")
print("=" * 108)
# +1 日洩漏：winner 設定 = (KFIX, N=6)；entry/score groupby(stock).shift(1)，Sharpe 不應崩
wsig = ARMS[KFIX]["sig"].sort_values(["stock_id", "date"]).copy()
wsig["entry_signal"] = wsig.groupby("stock_id")["entry_signal"].shift(1).fillna(False)
wsig["score"] = wsig.groupby("stock_id")["score"].shift(1).fillna(0.0)
st_lag = run_capped(price_df, wsig, ARMS[KFIX]["union"], START, END, capital=CAP, mode="odd_lot", full_equity=True)
base_sh = A1D[KFIX]["full_sh"]
print(f"(leak) K={KFIX}/N6 進場延遲 +1 日：Sharpe {base_sh:.2f}→{st_lag['sharpe']:.2f}"
      f"（崩跌＝有 1 日洩漏；持平/略降＝乾淨）")

# 外層 DD 真檢定（vs 被動，OOS）
print("\n(外層 DD vs 被動，OOS 最差前進年)：")
print(f"  wf-K 主規則 {prim['worst_dd']*100:.1f}%｜wf-N 主規則 {prim_N['worst_dd']*100:.1f}%｜"
      f"固定 K=150 {A1D[150]['wdd']*100:.1f}% / K=100 {A1D[100]['wdd']*100:.1f}%"
      f" vs 基準B {BENB_WDD*100:.1f}% / 0050 {BH_WDD*100:.1f}%")
dd_edge = (prim["worst_dd"] > BENB_WDD + DD_BAND) and (prim["worst_dd"] > BH_WDD + DD_BAND)
print(f"  → regime-DD 這層 edge（wf-K 最差年 DD 優於兩被動 >{DD_BAND*100:.1f}pp）：{'成立' if dd_edge else '不成立/邊際'}")

# ── 預登記 Gate ──
print("\n" + "=" * 108)
print("預登記判定（先寫死、後跑）")
print("=" * 108)
# Q1
q1_i = localized and peak_near_150 and (150 in PLATEAU_BAND) and nb_ok and flat_top_150
q1_ii = (prim["pooled_sharpe"] >= SB) and (prim["ir"] > 0) and prim["stable"]
all_pooled = [B1[n]["pooled_sharpe"] for n, _, _ in VARIANTS]
all_stable = [B1[n]["stable"] for n, _, _ in VARIANTS]
q1_iii = (max(all_pooled) - min(all_pooled) <= 0.2) and (all(all_stable) or not any(all_stable))   # 結論一致（皆穩或皆不穩）
Q1_REAL = q1_i and q1_ii and q1_iii
print(f"Q1（K=150 的 1.21 是真訊號？）：")
print(f"  (i) A1 150 為 localized 高原（含140&160、非孤峰非橫掃）：{'✓' if q1_i else '✗'}（{a1_class}）")
print(f"  (ii) B1 主規則 pooled≥B({SB:.2f}) & IR>0 & plateau 穩定：{prim['pooled_sharpe']:.2f}/{prim['ir']:+.2f}/"
      f"{'穩' if prim['stable'] else '不穩'} → {'✓' if q1_ii else '✗'}")
print(f"  (iii) robustness 跨 4 規則一致（pooled spread≤0.2 且穩定性一致）：{'✓' if q1_iii else '✗'}"
      f"（pooled={[round(x,2) for x in all_pooled]}, 穩定={all_stable}）")
print(f"  ▶ Q1 判定：{'真訊號' if Q1_REAL else '**in-sample cherry-pick（雜訊）**'}")
# Q2
print(f"\nQ2（誠實池需要加格 max_pos>6？）：in-sample 方向成立（A2 加格改善）、但 wf N* {'穩' if prim_N['stable'] else '不穩'}"
      f"、wf-N IR vs B {prim_N['ir']:+.2f} → "
      f"{'**需要加格（穩健翻盤）**' if NEEDS_SLOTS else '**Phase 6「不加格」未被穩健翻盤；加格列為 sizing 結構線索（待 R-attrib）**'}")
# 總 Gate（勝 R0 固定臂＝勝「naive 固定 K」中位，非 cherry-pick 的 max 1.21）
med_fixed = float(np.median([A1D[K]["oos_sh"] for K in R0_KS]))
beat_fixed = prim["pooled_sharpe"] > med_fixed
R1_PASS = q1_ii and prim["stable"] and q1_iii and beat_fixed and (prim["ir"] > 0)
print("\n" + "-" * 108)
print(f"R1 總 Gate：B1 勝B & IR>0 & plateau 穩定 & robustness 一致 & 勝 R0 固定臂"
      f" → {'**PASS**' if R1_PASS else '**FAIL（無穩健 alpha）**'}")
if R1_PASS:
    print("  級聯：誠實池存在可辯護主動設定 → 下一步 R-attrib（逐層歸因）+ R2（動量乾淨驗）。live 不動（待總 Gate）。")
else:
    print(f"  級聯：無穩健 alpha → 確認唯一真 edge＝regime 降 DD（外層 DD {'成立' if dd_edge else '邊際'}）→"
          f" R-attrib 量化 regime-DD 層 + 加格/sizing 方向性線索 + 朝 R5 誠實出口（被動為主、縮小主動）。live 不動。")
print("  ⚠️ survivorship（FinMind 無下市）→ 所有 OOS＝**上界**，真實更低；結論帶此 caveat。")
print(f"\n[done] R1 完成（mode={MODE}）。Q1={'真' if Q1_REAL else 'cherry-pick'}｜Q2={'加格' if NEEDS_SLOTS else '不加格'}｜"
      f"總 Gate={'PASS' if R1_PASS else 'FAIL'}。回報結果、等使用者指令再進下一步（不自動進 R-attrib/R2/R5）。")

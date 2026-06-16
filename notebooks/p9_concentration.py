"""
notebooks/p9_concentration.py
Phase 9 · Part 1 — #4 槓桿：規則化「集中到當期動量龍頭」（純快取、不打 API、零引擎改動）。

問題（缺失#4）：趨勢策略在大多頭年慘敗。Phase 7/8 已證真因是**結構性集中度**——
  資金攤在 6 格的「非龍頭籃子」、無法集中／輪動到當年真正 +49% 的少數龍頭（2024 捕獲僅 0.29）；
  放寬/拉長出場（Phase 7）反而更糟、加大並倉（Phase 6）walk-forward 被否決。

本檔測「**往下集中（max_pos↓）＋動量傾斜排序**」能否修 2024/2020 捕獲——這是 Phase 6 沒測過的方向
  （Phase 6 只往上掃 6→20＝更分散；此處要更集中）。

兩條槓桿（皆零引擎改動：集中＝既有 max_pos/size_*；動量＝只改 sig 的 score 欄＝引擎 :159 排序鍵）：
  (A) 集中度反向掃 max_pos∈{3,4,5,6} × {C1 固定上限 0.10/0.30, C2 守恆∝6/N（資金真灌龍頭）}。
  (B) 動量傾斜排序 score'=chip + λ·mom_rank，λ∈{0,.5,1,2,4} × N∈{4,6} × {C1,C2}。

⚠️ 紀律：以下全是 **in-sample 單期數字＝線索，非結論**；決策只綁 Phase 3 walk-forward（p9 Part 3）。
   本檔**不預期、也不追求 PASS**；目的是畫出「集中度/動量 vs 捕獲/風險」的曲線、挑出值得 walk-forward 的候選。
   PIT：動量用 close[T-skip]/close[T-lookback]-1（只用過去、決策日 T 已知、執行 T+1），不雙 shift（chip 已在 build 端 shift）。
本檔不改 live config/引擎。用法：.venv/bin/python notebooks/p9_concentration.py
"""
import os
import sys
import importlib.util

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
NB_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(NB_DIR))

import numpy as np
import pandas as pd
from src.backtest.capped_sim import build_signals, run_capped, LIVE_UNIVERSE

# 重用 benchmark_backtest 的 0050 還原日線（importlib；有 __main__ guard，import 不觸發 main）
_spec = importlib.util.spec_from_file_location("benchmark_backtest", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

START, END, CAP = "2018-01-01", "2025-12-31", 100_000
N_YEARS = 8
LOOKBACK, SKIP = 120, 5     # 動量：過去 ~6 個月、略過最近 1 週（避短期反轉污染）；PIT


# ───────────────────────── helpers（複用 p6/p8 idiom）─────────────────────────
def concentration(pnl):
    total = sum(pnl.values())
    if abs(total) < 1e-9:
        return float("nan"), float("nan")
    vals = sorted(pnl.values(), reverse=True)
    return vals[0] / total * 100.0, sum(vals[:3]) / total * 100.0


def calmar(a, dd):
    return a / abs(dd) if dd and abs(dd) > 1e-9 else float("nan")


def momentum_rank_long(price_df, lookback=LOOKBACK, skip=SKIP):
    """PIT 動量的每日橫斷面百分位 rank（long 格式 date,stock_id,mom_rank）。
    mom[T]=close[T-skip]/close[T-lookback]-1（只用 T-skip 以前的收盤 → 決策日 T 必然已知，無前視）。"""
    close = price_df.pivot(index="date", columns="stock_id", values="close").sort_index()
    mom = close.shift(skip) / close.shift(lookback) - 1.0
    rank = mom.rank(axis=1, pct=True)   # 每個 date 跨檔百分位（無時序正規化＝無前視）
    return rank.reset_index().melt(id_vars="date", var_name="stock_id", value_name="mom_rank")


def tilt_score(base_sig, mom_long, lam):
    """score'=chip + λ·mom_rank（只改排序鍵，不碰 entry_signal）。λ=0→原 sig（exact passthrough）。"""
    if lam == 0:
        return base_sig
    out = base_sig.merge(mom_long, on=["date", "stock_id"], how="left")
    out["mom_rank"] = out["mom_rank"].fillna(0.5)   # 歷史不足→中性名次，不偏不倚
    out["score"] = out["score"] + lam * out["mom_rank"]
    return out.drop(columns=["mom_rank"])


def cap_for(N, arm):
    """C1 固定上限（size 預設 0.10/0.30）；C2 守恆集中（size ∝6/N，資金真灌進少數龍頭）。"""
    kw = {"max_pos": N}
    if arm == "C2":
        kw["size_min"], kw["size_max"] = 0.10 * 6 / N, 0.30 * 6 / N
    return kw


# ───────────────────────── 0050 逐年（捕獲分母）+ build signals ONCE ─────────────────────────
print("載入 0050 還原日線（純快取）…")
px0 = bm.load_adjusted_0050().set_index("date")["close"].sort_index().astype(float)
b0 = {}
for y in range(2018, 2026):
    sy = px0[px0.index.year == y]
    if len(sy) >= 5:
        b0[y] = float(sy.iloc[-1] / sy.iloc[0] - 1)
print("0050 逐年：" + "  ".join(f"{y} {b0.get(y, float('nan'))*100:+.0f}%" for y in range(2018, 2026)))

print(f"\n建訊號（{len(LIVE_UNIVERSE)} 檔 LIVE_UNIVERSE，{START}~{END}，純快取）…")
SIG_PRICE_DF, SIG = build_signals(LIVE_UNIVERSE, START, END)
MOM = momentum_rank_long(SIG_PRICE_DF)


def run(start, end, *, sig=None, **kw):
    return run_capped(SIG_PRICE_DF, SIG if sig is None else sig, LIVE_UNIVERSE,
                      start, end, capital=CAP, mode="odd_lot", **kw)


def cap(st, y):
    d = st["per_year"].get(y, {})
    return (d.get("ret") / b0[y]) if (y in b0 and abs(b0[y]) > 1e-9 and d) else float("nan")


def row_metrics(st):
    _, t3 = concentration(st["pnl_by_stock"])
    return dict(sharpe=st["sharpe"], calmar=calmar(st["annual"], st["dd"]), dd=st["dd"],
                ann=st["annual"], cap24=cap(st, 2024), cap20=cap(st, 2020),
                top3=t3, trades_yr=st["n_trades"] / N_YEARS)


# ───────────────────────── Part 0 — 中性檢查（過了才信任後續）─────────────────────────
# (1) 動量 merge 不得改動 entry_signal / score 對齊；(2) λ=0 經引擎逐鍵＝原 sig。
chk = SIG.merge(MOM, on=["date", "stock_id"], how="left")
chk["mom_rank"] = chk["mom_rank"].fillna(0.5)
merge_ok = (chk["entry_signal"].equals(SIG["entry_signal"])
            and np.allclose(chk["score"].to_numpy(), SIG["score"].to_numpy()))
sig_merge0 = chk.drop(columns=["mom_rank"])          # 經 merge 路徑、score 未變
a = run(START, END, max_pos=6)
b = run(START, END, max_pos=6, sig=sig_merge0)
engine_ok = (a["pnl_by_stock"] == b["pnl_by_stock"] and a["per_year"] == b["per_year"]
             and a["n_trades"] == b["n_trades"] and a["sharpe"] == b["sharpe"])
neutral = merge_ok and engine_ok
print(f"\n[中性檢查] 動量 merge 不動 entry/score：{'✓' if merge_ok else '✗'}｜"
      f"λ=0 經引擎逐鍵==原 sig：{'✓' if engine_ok else '✗'} → {'NEUTRAL OK' if neutral else '✗ FAILED'}")
assert neutral, "動量傾斜非行為中性（merge 或 pivot 路徑污染）！停止。"

BASE = run(START, END, **cap_for(6, "C1"))           # live-aligned 基準：6 格 / 0.10–0.30
bm0 = row_metrics(BASE)
print(f"[doc-sanity] live 基準 6/C1：年化 {bm0['ann']*100:.1f}% / Sharpe {bm0['sharpe']:.2f} / "
      f"DD {bm0['dd']*100:.1f}% / 2024捕獲 {bm0['cap24']:.2f} / 2020捕獲 {bm0['cap20']:.2f} / "
      f"top3 {bm0['top3']:.0f}% / 交易 {bm0['trades_yr']:.0f}/年")
print("（0050：2024 +49% / 2020 +30%；Phase 7 已知 2024 捕獲 ~0.29）")


def _print_grid(title, rows):
    print("\n" + "=" * 104)
    print(title)
    print("=" * 104)
    print(f"{'設定':<16}{'年化%':>7}{'Sharpe':>8}{'Calmar':>8}{'DD%':>7}{'2024捕獲':>9}{'2020捕獲':>9}{'top3%':>7}{'交易/年':>8}")
    for label, m in rows:
        print(f"{label:<16}{m['ann']*100:>7.1f}{m['sharpe']:>8.2f}{m['calmar']:>8.2f}{m['dd']*100:>7.1f}"
              f"{m['cap24']:>9.2f}{m['cap20']:>9.2f}{m['top3']:>7.0f}{m['trades_yr']:>8.1f}")


# ───────────────────────── Part 1A — 集中度反向掃（無動量；純集中效果）─────────────────────────
rowsA, candidates = [], []
for N in (6, 5, 4, 3):
    for arm in ("C1", "C2"):
        st = run(START, END, **cap_for(N, arm))
        m = row_metrics(st)
        rowsA.append((f"N{N}·{arm}", m))
        candidates.append((f"A:N{N}·{arm}", N, arm, 0.0, m))
_print_grid("Part 1A — 集中度反向掃（max_pos↓；C1 固定上限 / C2 守恆∝6/N；無動量傾斜）", rowsA)
print("（N=3·C2 單檔上限達 0.60 → 路徑依賴/DD 脆弱，需 N=4/5 也好[高原]才採信）")

# ───────────────────────── Part 1B — 動量傾斜排序（× 集中度）─────────────────────────
rowsB = []
for lam in (0.0, 0.5, 1.0, 2.0, 4.0):
    sig_t = tilt_score(SIG, MOM, lam)
    for N in (6, 4):
        for arm in ("C1", "C2"):
            st = run(START, END, sig=sig_t, **cap_for(N, arm))
            m = row_metrics(st)
            rowsB.append((f"λ{lam:g}·N{N}·{arm}", m))
            candidates.append((f"B:λ{lam:g}·N{N}·{arm}", N, arm, lam, m))
_print_grid(f"Part 1B — 動量傾斜 score'=chip+λ·mom_rank（lookback={LOOKBACK}/skip={SKIP}；λ0=純集中對照）", rowsB)


# ───────────────────────── 摘要 — 挑出值得 walk-forward 的候選 ─────────────────────────
print("\n" + "-" * 104)
print("摘要（in-sample 線索；決策綁 Part 3 walk-forward）：")
print(f"  live 基準 6/C1：2024 捕獲 {bm0['cap24']:.2f} / Sharpe {bm0['sharpe']:.2f} / DD {bm0['dd']*100:.1f}% / top3 {bm0['top3']:.0f}%")
# 候選＝「2024 捕獲較基準 +≥0.15」且「DD 不破 -0.20」（軟性線索門檻，非決策 Gate）
flagged = [(lbl, N, arm, lam, m) for (lbl, N, arm, lam, m) in candidates
           if (m["cap24"] == m["cap24"]) and (m["cap24"] - bm0["cap24"] >= 0.15) and (m["dd"] >= -0.20)]
flagged.sort(key=lambda t: -t[4]["cap24"])
if flagged:
    print(f"  → 2024 捕獲 +≥0.15 且 DD≥-20% 的候選（{len(flagged)} 個，前 8）：")
    for lbl, N, arm, lam, m in flagged[:8]:
        print(f"     {lbl:<16} 2024 {m['cap24']:.2f}(Δ{m['cap24']-bm0['cap24']:+.2f}) / 2020 {m['cap20']:.2f} / "
              f"Sharpe {m['sharpe']:.2f} / Calmar {m['calmar']:.2f} / DD {m['dd']*100:.1f}% / top3 {m['top3']:.0f}%")
else:
    print("  → 無任何集中/動量組合使 2024 捕獲較基準 +≥0.15（in-sample）→ #4 結構修復線索薄弱，Part 3 仍須驗。")
# 另記「全面不劣於基準」的穩健候選（Sharpe 與 DD 都不差 + 2024 有改善）
solid = [(lbl, m) for (lbl, N, arm, lam, m) in candidates
         if m["sharpe"] >= bm0["sharpe"] and m["dd"] >= bm0["dd"] - 0.02 and m["cap24"] >= bm0["cap24"] + 0.05]
solid.sort(key=lambda t: -t[1]["sharpe"])
print(f"  → 風險不劣化且 2024 有改善（Sharpe≥基準 ＆ DD 不差>2pp ＆ 2024+≥0.05）：{len(solid)} 個"
      + ("" if not solid else "，前 5："))
for lbl, m in solid[:5]:
    print(f"     {lbl:<16} Sharpe {m['sharpe']:.2f} / DD {m['dd']*100:.1f}% / 2024 {m['cap24']:.2f} / Calmar {m['calmar']:.2f}")
print("\n[done] 下一步：把最有希望的 (λ,N,arm) 帶進 p9 Part 3 walk-forward（決策所綁）。")

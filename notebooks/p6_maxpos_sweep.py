"""
notebooks/p6_maxpos_sweep.py
Phase 6 核心：並倉上限 × 風險預算配重 的「頻率 vs 風險調整報酬」權衡曲線（純快取，不打 API）。

問題：加大 max_positions 能拉高交易頻率（6→20：交易/年 27.8→73.8），但單純加大並未改善 Sharpe、
      還惡化 DD。本檔畫出權衡曲線、套 Phase 6 Gate，找「DD 不破線前提下 Calmar/Sharpe 的轉折點」。

grid = max_pos ∈ {6,8,10,12,15,20} × sizing ∈ {現行固定(0.10/0.30), 風險預算守恆(∝6/N)}
  風險預算守恆 = 加倉位時把單檔配重上下限 ∝ 6/N 縮小，使 N×單檔配重 ≈ 常數（配套A，複用 size_min/size_max）。

Gate（基準＝固定 N=6）：
  · DD ≤ -18%（軟線）；DD > -20% 一律 REJECT
  · Calmar 或 Sharpe 相對基準 +≥10%
  · 單檔最大貢獻% 與 top3% 皆 < 基準（分散度真的改善）

注意：本檔僅產出曲線與「有條件建議」，不改 live config；真正調 max_positions 須等 Phase 8 walk-forward。
用法：.venv/bin/python notebooks/p6_maxpos_sweep.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest.capped_sim import build_signals, run_capped, LIVE_UNIVERSE

START, END, CAP = "2018-01-01", "2025-12-31", 100_000
N_YEARS = 8
MAXPOS_GRID = [6, 8, 10, 12, 15, 20]


def concentration(pnl_by_stock):
    """單檔最大貢獻% / 前3大貢獻佔比%（分母＝總淨損益，sign-safe）。"""
    total = sum(pnl_by_stock.values())
    if abs(total) < 1e-9:
        return float("nan"), float("nan")
    vals = sorted(pnl_by_stock.values(), reverse=True)
    return vals[0] / total * 100.0, sum(vals[:3]) / total * 100.0


def calmar(annual, dd):
    return annual / abs(dd) if dd and abs(dd) > 1e-9 else float("nan")


def pct_up(x, base):
    """x 相對 base 的提升比例；base 非有限則回 -inf（視為未提升）。"""
    if base is None or base != base or abs(base) < 1e-9:
        return float("-inf")
    return x / base - 1.0


# ───────────────────────── build signals ONCE ─────────────────────────
print(f"建訊號（{len(LIVE_UNIVERSE)} 檔 LIVE_UNIVERSE，{START}~{END}，純快取）…")
price_df, sig = build_signals(LIVE_UNIVERSE, START, END)
print(f"price_df {len(price_df)} 列；entry 訊號合計 {int(sig['entry_signal'].sum())}")


# ───────────────────── 行為中性檢查（過了才信任後續數字）─────────────────────
a = run_capped(price_df, sig, LIVE_UNIVERSE, START, END, capital=CAP)
b = run_capped(price_df, sig, LIVE_UNIVERSE, START, END, capital=CAP,
               atr_mult=4.5, atr_lo=0.08, atr_hi=0.09, max_hold=60, target_vol=0.02)
_keys = ("annual", "sharpe", "dd", "pf", "total_return", "n_trades",
         "win_rate", "final_equity", "avg_concurrent")
neutral = (all(a[k] == b[k] for k in _keys)
           and a["pnl_by_stock"] == b["pnl_by_stock"]
           and a["equity_pts"] == b["equity_pts"])
print(f"\n[中性檢查] no-arg == 顯式字面值(4.5/0.08/0.09/60/0.02)：{'NEUTRAL OK' if neutral else '✗ FAILED'}")
assert neutral, "參數化非行為中性！停止。"
print(f"[doc-sanity] 基準 年化{a['annual']*100:.1f}% Sharpe{a['sharpe']:.2f} DD{a['dd']*100:.1f}% "
      f"PF{a['pf']:.2f} 交易{a['n_trades']}（master 6.2 ≈12.7/1.16/-16.0/1.97/222；±2.2pp DD 漂移為已知 6.5#3）")


# ───────────────────────── sweep：max_pos × sizing ─────────────────────────
def run_cell(max_pos, policy):
    if policy == "fixed":
        smin, smax = None, None                  # 0.10 / 0.30（現行）
    else:                                        # budget：單檔上下限 ∝ 6/N
        smin, smax = 0.10 * 6 / max_pos, 0.30 * 6 / max_pos
    st = run_capped(price_df, sig, LIVE_UNIVERSE, START, END,
                    capital=CAP, max_pos=max_pos, size_min=smin, size_max=smax)
    top1, top3 = concentration(st["pnl_by_stock"])
    return {
        "_N": max_pos, "_policy": policy,
        "_label": f"{'固定' if policy == 'fixed' else '守恆'}N={max_pos}",
        "_smax": 0.30 if policy == "fixed" else smax,
        "trades_yr": st["n_trades"] / N_YEARS, "annual": st["annual"],
        "sharpe": st["sharpe"], "calmar": calmar(st["annual"], st["dd"]),
        "dd": st["dd"], "avg_conc": st["avg_concurrent"],
        "top1": top1, "top3": top3,
    }


rows = [run_cell(mp, pol) for pol in ("fixed", "budget") for mp in MAXPOS_GRID]
base = next(r for r in rows if r["_policy"] == "fixed" and r["_N"] == 6)


def gate(r):
    if r["dd"] < -0.20:
        return "REJECT"
    dd_ok = r["dd"] >= -0.18
    risk_ok = (pct_up(r["calmar"], base["calmar"]) >= 0.10
               or pct_up(r["sharpe"], base["sharpe"]) >= 0.10)
    conc_ok = (r["top1"] < base["top1"]) and (r["top3"] < base["top3"])
    return "PASS" if (dd_ok and risk_ok and conc_ok) else "fail"


for r in rows:
    r["_gate"] = gate(r)


# ───────────────────────── 輸出表 ─────────────────────────
print("\n" + "=" * 104)
print("Phase 6 權衡曲線 — max_pos × 配重（LIVE 35檔, 100k, 零股, 2018–25）")
print(f"基準=固定N=6：Sharpe {base['sharpe']:.2f} / Calmar {base['calmar']:.2f} / "
      f"top1 {base['top1']:.0f}% / top3 {base['top3']:.0f}% / DD {base['dd']*100:.1f}%")
print("Gate：DD≤-18%軟線(>-20%一律REJECT) ＆ Calmar或Sharpe vs基準+≥10% ＆ top1&top3<基準")
print("=" * 104)
print(f"{'設定':<12}{'單檔上限':>9}{'交易/年':>8}{'年化%':>8}{'Sharpe':>8}{'Calmar':>8}"
      f"{'回撤%':>8}{'avg並倉':>8}{'單檔最大%':>11}{'top3%':>9}{'Gate':>8}")
for r in rows:
    if r["_N"] == 6 and r["_policy"] == "budget":
        print("-" * 104)  # 兩政策間分隔（守恆 N=6 == 固定 N=6，列出便於對照）
    print(f"{r['_label']:<12}{r['_smax']*100:>8.0f}%{r['trades_yr']:>8.1f}{r['annual']*100:>8.1f}"
          f"{r['sharpe']:>8.2f}{r['calmar']:>8.2f}{r['dd']*100:>8.1f}{r['avg_conc']:>8.1f}"
          f"{r['top1']:>11.0f}{r['top3']:>9.0f}{r['_gate']:>8}")

# ───────────────────────── 轉折點 / 建議摘要 ─────────────────────────
passed = [r for r in rows if r["_gate"] == "PASS"]
print("\n" + "-" * 104)
if passed:
    best = max(passed, key=lambda r: (r["calmar"], r["sharpe"]))
    print(f"通過 Gate 的格：{', '.join(r['_label'] for r in passed)}")
    print(f"→ 最佳（Calmar 優先）：{best['_label']}  "
          f"Calmar {best['calmar']:.2f}（基準 {base['calmar']:.2f}，+{pct_up(best['calmar'], base['calmar'])*100:.0f}%）/ "
          f"Sharpe {best['sharpe']:.2f} / DD {best['dd']*100:.1f}% / 交易{best['trades_yr']:.0f}/年")
else:
    print("無任何格通過 Phase 6 Gate → 證實『單純加大並倉（含配套A）不足』，max_positions 維持 6；"
          "出場連動見 p6_exit_linkage.py，跨期驗證見 Phase 8。")
print("（提醒：in-sample 勝出不算數，最終建議須 Phase 8 walk-forward 確認後才動 live config。）")
print("\n[done]")

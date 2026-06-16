"""
notebooks/p8_walkforward.py
Phase 8 — 抗過擬合：walk-forward 驗證（缺失#3）。純快取、不打 API。

問題：Phase 6 在 in-sample（2018–25 全期）找到一個明顯優於現行的候選——
  守恆 N=15 / max_hold=90 / atr_hi=0.15（Sharpe 1.14→1.36、Calmar 0.91→1.31、DD -13.8→-9.9%、top3 49→28%、45 交易/年），
  但那是 36 格僅 4 格通過的「單期峰值」。本檔把它放到「沒見過的前進窗」重新評分，決定能否落地 live。

設計（Plan agent 校正後）：
  · Part 1  in-sample 脈絡（基準 + 4 高原候選全期；僅線索）。
  · Part 2a 固定候選 OOS 一致性（贏家逐前進年；勝果穩定 vs 靠 1–2 年？）。
  · Part 2b 真·再優化 walk-forward（決策所綁）：擴張訓練窗 [2018,Y-1]→前進年 Y∈{2022..25}；
            每窗跑 36 格、用 Phase 6 Gate 選 C*_Y（選擇穩定度＝過擬合 tell）；C*_Y 連續跑取 Y 年逐日報酬。
            carry-in 洩漏 → 另報 Y 年 H2(7–12月)。pooled OOS：串「逐日報酬」算 Sharpe/年化；
            DD 用「最差前進年」（絕不串非連續年權益算 DD，會捏造跨年回撤）。
  · Part 2c 滾動 4 年訓練窗變體（訓練窗 cold-start 已知；只作結論穩健交叉檢查）。
  · Part 3  高原/敏感度（贏家鄰域；平坦高原 vs 尖峰）。
  · Part 4  穩健性：slip_scale{1,2,3}、進場延遲+1日、leave-one-out 前3大貢獻股 + K=50 無放回子集(size28)。
  · 對照：live 基準 OOS、預先指定基準B(0050+vol-target, vol0.011 無overlay)、0050 買進持有；IR=excess 日報酬年化。

決策閘（為 n=4 前進年/僅1熊年重設計，相對優先＋分 regime）：
  PRIMARY 全過才 PASS：① pooled OOS Sharpe 勝 live 基準；② 最差前進年 DD 不比基準差過 ~2pp；
    ③ 選擇穩定（C*_Y 全落高原區）；④ IR vs 基準B > 0；⑤ 穩健性健康（子集中位/5th-pct 不崩、左尾不長）。
  分 regime（報告軟性）：2022 OOS DD 優於 0050 的 -21.9%；絕對門檻(Sharpe≥1/DD≤-15%/年化≥10%)＝報告目標非自動否決。
  FAIL 僅由 2022 → 標「熊年 n=1 inconclusive」，不全盤否決。

用法：.venv/bin/python notebooks/p8_walkforward.py
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

# 重用既有「預先指定基準B（0050+vol-target）」+「0050 買進持有」（importlib，避免重複 ~70 行模擬；
# benchmark_backtest.py 有 __main__ guard，import 不會觸發 main()）。
_spec = importlib.util.spec_from_file_location("benchmark_backtest", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

START, END, CAP = "2018-01-01", "2025-12-31", 100_000
YEARS = list(range(2018, 2026))
FWD_YEARS = [2022, 2023, 2024, 2025]   # 前進窗（擴張訓練窗 ≥4 年）
SQRT252 = np.sqrt(252)

# Phase 6 WF 選擇格（同 p6_exit_linkage）：3 sizing × 4 max_hold × 3 atr_hi = 36 格
SIZING = [("固定N6", 6, "fixed"), ("守恆N15", 15, "budget"), ("守恆N20", 20, "budget")]
MAXHOLD_GRID = [40, 60, 90, 99999]
ATRHI_GRID = [0.09, 0.12, 0.15]
PLATEAU = {(15, 90, 0.12), (15, 90, 0.15), (20, 90, 0.12), (20, 90, 0.15)}  # Phase 6 通過高原
WINNER = (15, 90, 0.15, "budget")     # Phase 6 最佳 in-sample


def kw_for(N, mh, ah, sz):
    """候選 → run_capped kwargs（守恆＝單檔上下限 ∝6/N，同 p6_exit_linkage）。"""
    smin, smax = (None, None) if sz == "fixed" else (0.10 * 6 / N, 0.30 * 6 / N)
    return dict(max_pos=N, size_min=smin, size_max=smax, max_hold=mh, atr_hi=ah)


def calmar(a, dd):
    return a / abs(dd) if dd and abs(dd) > 1e-9 else float("nan")


def pct_up(x, base):
    return float("-inf") if (base is None or base != base or abs(base) < 1e-9) else x / base - 1.0


def concentration(pnl):
    total = sum(pnl.values())
    if abs(total) < 1e-9:
        return float("nan"), float("nan")
    vals = sorted(pnl.values(), reverse=True)
    return vals[0] / total * 100.0, sum(vals[:3]) / total * 100.0


def sharpe_of(dr):
    sd = dr.std()
    return float(dr.mean() / sd * SQRT252) if sd > 0 else 0.0


def ann_of(dr):
    n = len(dr)
    return float((1 + dr).prod() ** (252 / n) - 1) if n > 0 else float("nan")


def cum_of(dr):
    return float((1 + dr).prod() - 1) if len(dr) else float("nan")


# ───────────────────────── 0050 / 基準B（純快取）─────────────────────────
print("載入 0050 還原日線 + 預先指定基準B（vol0.011 無 overlay）…（純快取，不打 API）")
adj0050 = bm.load_adjusted_0050()
px0 = adj0050.set_index("date")["close"].sort_index().astype(float)
b0 = {}      # 0050 逐年買進持有報酬（捕獲分母 / 熊年相對標準）
for y in YEARS:
    sy = px0[px0.index.year == y]
    if len(sy) >= 5:
        b0[y] = float(sy.iloc[-1] / sy.iloc[0] - 1)
print("0050 逐年：" + "  ".join(f"{y} {b0.get(y, float('nan'))*100:+.0f}%" for y in YEARS))

bench_b = bm.simulate_benchmark(adj0050, 0.011)            # 預先指定 B：不可 best-of-sweep
bench_b_eq = bench_b["equity"]
print(f"基準B(vol0.011,無overlay) 全期：年化 {bench_b['annual']*100:.1f}% / Sharpe {bench_b['sharpe']:.2f} / DD {bench_b['dd']*100:.1f}%")


# ───────────────────────── build signals ONCE ─────────────────────────
print(f"\n建訊號（{len(LIVE_UNIVERSE)} 檔 LIVE_UNIVERSE，{START}~{END}，純快取）…")
price_df, sig = build_signals(LIVE_UNIVERSE, START, END)


def run(start, end, *, full=False, universe=None, sigframe=None, **kw):
    return run_capped(price_df, sig if sigframe is None else sigframe,
                      LIVE_UNIVERSE if universe is None else universe,
                      start, end, capital=CAP, full_equity=full, **kw)


def eq_series(st):
    return pd.Series(st["equity_full"], index=pd.to_datetime(st["equity_full_dates"]))


def year_dr(eq, y):
    return eq[eq.index.year == y].pct_change().dropna()


def h2_dr(eq, y):
    return eq[(eq.index.year == y) & (eq.index.month >= 7)].pct_change().dropna()


# ───────────────────── 中性檢查（補既有檢查漏掉的 per_year + full_equity 新鍵）─────────────────────
a = run(START, END, max_pos=6)
b = run(START, END, max_pos=6, atr_mult=4.5, atr_lo=0.08, atr_hi=0.09, max_hold=60, target_vol=0.02)
c = run(START, END, max_pos=6, full=True)
_keys = ("annual", "sharpe", "dd", "pf", "total_return", "n_trades", "win_rate", "final_equity", "avg_concurrent")
neutral = (all(a[k] == b[k] for k in _keys) and a["pnl_by_stock"] == b["pnl_by_stock"]
           and a["per_year"] == b["per_year"] and a["equity_pts"] == b["equity_pts"] and "equity_full" not in a
           and all(c[k] == a[k] for k in _keys) and c["per_year"] == a["per_year"]
           and c["equity_pts"] == a["equity_pts"] and "equity_full" in c
           and len(c["equity_full"]) == len(c["equity_full_dates"]) == len(a["equity_dates"]) * 0 + len(eq_series(c)))
print(f"\n[中性檢查] no-arg==顯式字面值(4.5/.08/.09/60/.02) 且 full_equity additive：{'NEUTRAL OK' if neutral else '✗ FAILED'}")
assert neutral, "full_equity 參數化非行為中性！停止。"
print(f"[doc-sanity] 基準 年化{a['annual']*100:.1f}% Sharpe{a['sharpe']:.2f} DD{a['dd']*100:.1f}% 交易{a['n_trades']}"
      f"（master 6.2≈12.7/1.16/-16.0/222；35-檔自建訊號路徑 DD≈-13.8，±2.2pp 為 6.5#3 已知 path-dependence）")

base_full = run(START, END, full=True)        # live 基準 6/60/.09（OOS 對照 + per_year）
base_eq = eq_series(base_full)


# ───────────────────────── Part 1 — in-sample 全期脈絡 ─────────────────────────
CANDS = [
    ("live基準 6/60/.09", dict(max_pos=6)),
    ("守恆N15·90·.15★", kw_for(15, 90, 0.15, "budget")),
    ("守恆N20·90·.15", kw_for(20, 90, 0.15, "budget")),
    ("守恆N20·90·.12", kw_for(20, 90, 0.12, "budget")),
    ("守恆N15·90·.12", kw_for(15, 90, 0.12, "budget")),
]
print("\n" + "=" * 100)
print("Part 1 — in-sample 全期脈絡（2018–25；★＝Phase 6 最佳；★/守恆皆 in-sample 線索，非結論）")
print("=" * 100)
print(f"{'候選':<20}{'年化%':>7}{'Sharpe':>8}{'Calmar':>8}{'DD%':>7}{'交易/年':>8}{'top3%':>7}")
p1 = {}
for label, kw in CANDS:
    st = run(START, END, **kw)
    p1[label] = st
    _, t3 = concentration(st["pnl_by_stock"])
    print(f"{label:<20}{st['annual']*100:>7.1f}{st['sharpe']:>8.2f}{calmar(st['annual'], st['dd']):>8.2f}"
          f"{st['dd']*100:>7.1f}{st['n_trades']/8:>8.1f}{t3:>7.0f}")
win_is = p1["守恆N15·90·.15★"]


# ───────────────────────── Part 2a — 固定贏家逐前進年 OOS 一致性 ─────────────────────────
win_full = run(START, END, full=True, **kw_for(*WINNER))
print("\n" + "=" * 100)
print("Part 2a — 固定贏家(守恆N15·90·.15) 逐前進年（固定候選；勝果穩定跨年 vs 靠 1–2 年？）")
print("=" * 100)
print(f"{'年':>6}{'策略%':>8}{'Sharpe':>8}{'DD%':>7}{'0050%':>8}{'捕獲':>7}")
for y in FWD_YEARS:
    d = win_full["per_year"].get(y, {})
    cap = (d.get("ret") / b0[y]) if (y in b0 and abs(b0[y]) > 1e-9 and d) else float("nan")
    print(f"{y:>6}{d.get('ret', float('nan'))*100:>8.1f}{d.get('sharpe', float('nan')):>8.2f}"
          f"{d.get('dd', float('nan'))*100:>7.1f}{b0.get(y, float('nan'))*100:>8.1f}{cap:>7.2f}")


# ───────────────────────── Part 2b/2c — 真·再優化 walk-forward ─────────────────────────
def select_cstar(train_end_year, train_start):
    """在 [train_start, train_end_year-12-31] 跑 36 格、用 Phase 6 Gate 選 C*（Calmar 優先）；無 PASS→落回基準。"""
    end = f"{train_end_year}-12-31"
    rows = {}
    for sname, N, sz in SIZING:
        for mh in MAXHOLD_GRID:
            for ah in ATRHI_GRID:
                st = run(train_start, end, **kw_for(N, mh, ah, sz))
                if not st:
                    continue
                t1, t3 = concentration(st["pnl_by_stock"])
                rows[(N, mh, ah, sz)] = {"sharpe": st["sharpe"], "calmar": calmar(st["annual"], st["dd"]),
                                         "dd": st["dd"], "top1": t1, "top3": t3, "N": N, "mh": mh, "ah": ah, "sz": sz}
    gbase = rows[(6, 60, 0.09, "fixed")]
    passed = []
    for r in rows.values():
        if r["dd"] < -0.20:
            continue
        dd_ok = r["dd"] >= -0.18
        risk_ok = pct_up(r["calmar"], gbase["calmar"]) >= 0.10 or pct_up(r["sharpe"], gbase["sharpe"]) >= 0.10
        conc_ok = r["top1"] < gbase["top1"] and r["top3"] < gbase["top3"]
        if dd_ok and risk_ok and conc_ok:
            passed.append(r)
    if passed:
        best = max(passed, key=lambda r: (r["calmar"], r["sharpe"]))
        return (best["N"], best["mh"], best["ah"], best["sz"]), len(passed)
    return (6, 60, 0.09, "fixed"), 0


def _cs_label(cs):
    N, mh, ah, sz = cs
    return f"{'固定' if sz == 'fixed' else '守恆'}N{N}·{'off' if mh >= 99999 else mh}·{ah:g}"


def wf_run(train_fn):
    rows, strat_daily, dd_by_year = [], [], {}
    for Y in FWD_YEARS:
        cstar, n_pass = select_cstar(Y - 1, train_fn(Y))
        st = run(START, f"{Y}-12-31", full=True, **kw_for(*cstar))
        eq = eq_series(st)
        d = st["per_year"].get(Y, {})
        dd_by_year[Y] = d.get("dd", float("nan"))
        dr = year_dr(eq, Y)
        h2 = h2_dr(eq, Y)
        rows.append({"Y": Y, "cstar": cstar, "n_pass": n_pass,
                     "ret": d.get("ret", float("nan")), "dd": d.get("dd", float("nan")),
                     "sharpe": d.get("sharpe", float("nan")), "h2_ret": cum_of(h2), "h2_sharpe": sharpe_of(h2),
                     "in_plat": (cstar[0], cstar[1], cstar[2]) in PLATEAU,
                     "cap": (d.get("ret") / b0[Y]) if (Y in b0 and abs(b0[Y]) > 1e-9 and d) else float("nan")})
        strat_daily.append(dr)
    pooled = pd.concat(strat_daily)
    return {"rows": rows, "pooled": pooled, "pooled_sharpe": sharpe_of(pooled),
            "pooled_ann": ann_of(pooled), "worst_dd": min(dd_by_year.values()), "dd_by_year": dd_by_year}


def _print_wf(title, wf):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)
    print(f"{'前進年':>6}{'選到的 C*_Y':>18}{'通過數':>7}{'高原':>5}{'OOS%':>7}{'Sharpe':>8}{'DD%':>7}{'H2%':>7}{'H2Sh':>7}{'捕獲':>7}")
    for r in wf["rows"]:
        print(f"{r['Y']:>6}{_cs_label(r['cstar']):>18}{r['n_pass']:>7}{('✓' if r['in_plat'] else '·'):>5}"
              f"{r['ret']*100:>7.1f}{r['sharpe']:>8.2f}{r['dd']*100:>7.1f}{r['h2_ret']*100:>7.1f}{r['h2_sharpe']:>7.2f}{r['cap']:>7.2f}")
    print(f"pooled OOS：Sharpe {wf['pooled_sharpe']:.2f} / 年化 {wf['pooled_ann']*100:.1f}% / 最差前進年DD {wf['worst_dd']*100:.1f}%")


exp_wf = wf_run(lambda Y: "2018-01-01")
_print_wf("Part 2b — 真·再優化 walk-forward（擴張訓練窗 [2018,Y-1]→Y；決策所綁）", exp_wf)

# 對照：live 基準 OOS（固定，同前進年）+ 基準B OOS + IR
base_oos = pd.concat([year_dr(base_eq, Y) for Y in FWD_YEARS])
base_worst_dd = min(base_full["per_year"][Y]["dd"] for Y in FWD_YEARS if Y in base_full["per_year"])
base_pooled_sharpe = sharpe_of(base_oos)
benb_oos = pd.concat([year_dr(bench_b_eq, Y) for Y in FWD_YEARS])
ir_df = pd.concat([exp_wf["pooled"].rename("s"), benb_oos.rename("b")], axis=1).dropna()
cover = len(ir_df) / len(exp_wf["pooled"])
assert cover > 0.99, f"IR 日期對齊覆蓋 {cover:.1%} < 99%（策略/基準B 日曆不一致）"
IR = sharpe_of(ir_df["s"] - ir_df["b"])
print(f"  ↳ 對照同前進年 pooled OOS：")
print(f"     live 基準 6/60/.09 ：Sharpe {base_pooled_sharpe:.2f} / 年化 {ann_of(base_oos)*100:.1f}% / 最差前進年DD {base_worst_dd*100:.1f}%")
print(f"     基準B vol0.011     ：Sharpe {sharpe_of(benb_oos):.2f} / 年化 {ann_of(benb_oos)*100:.1f}%")
print(f"     IR(策略−基準B, 年化)：{IR:+.2f}（日期對齊覆蓋 {cover:.1%}）")

roll_wf = wf_run(lambda Y: f"{Y-4}-01-01")
_print_wf("Part 2c — 滾動 4 年訓練窗變體（訓練窗 cold-start 已知；結論穩健交叉檢查）", roll_wf)


# ───────────────────────── Part 3 — 高原/敏感度（贏家鄰域，in-sample）─────────────────────────
print("\n" + "=" * 100)
print("Part 3 — 高原/敏感度（贏家鄰域；in-sample 全期；平坦高原 vs 尖峰）")
print("=" * 100)
win_sharpe, win_calmar = win_is["sharpe"], calmar(win_is["annual"], win_is["dd"])
neigh = [("N 12", kw_for(12, 90, 0.15, "budget")), ("N 20", kw_for(20, 90, 0.15, "budget")),
         ("hold 60", kw_for(15, 60, 0.15, "budget")), ("hold 120", kw_for(15, 120, 0.15, "budget")),
         ("atr .12", kw_for(15, 90, 0.12, "budget")), ("atr .18", kw_for(15, 90, 0.18, "budget"))]
print(f"贏家 守恆N15·90·.15：Sharpe {win_sharpe:.2f} / Calmar {win_calmar:.2f}")
print(f"{'鄰格':<10}{'Sharpe':>8}{'ΔSh%':>8}{'Calmar':>8}{'ΔCal%':>8}")
worst_deg = 0.0
for label, kw in neigh:
    st = run(START, END, **kw)
    cal = calmar(st["annual"], st["dd"])
    dsh, dcal = pct_up(st["sharpe"], win_sharpe) * 100, pct_up(cal, win_calmar) * 100
    worst_deg = min(worst_deg, dsh, dcal)
    print(f"{label:<10}{st['sharpe']:>8.2f}{dsh:>+8.0f}{cal:>8.2f}{dcal:>+8.0f}")
plateau_ok = worst_deg > -15.0
print(f"→ 鄰域最差退化 {worst_deg:+.0f}%（門檻 -15%）：{'平坦高原' if plateau_ok else '偏尖峰（過擬合疑慮）'}")


# ───────────────────────── Part 4 — 穩健性（贏家，in-sample 擾動）─────────────────────────
print("\n" + "=" * 100)
print("Part 4 — 穩健性（贏家守恆N15·90·.15；in-sample 全期擾動）")
print("=" * 100)
print("(a) 滑價壓力 slip_scale：")
for ss in (1, 2, 3):
    st = run(START, END, slip_scale=ss, **kw_for(*WINNER))
    print(f"    ×{ss}: 年化 {st['annual']*100:>5.1f}% / Sharpe {st['sharpe']:.2f} / DD {st['dd']*100:.1f}%")

sig_j = sig.sort_values(["stock_id", "date"]).copy()
sig_j["entry_signal"] = sig_j.groupby("stock_id")["entry_signal"].shift(1).fillna(False)
sig_j["score"] = sig_j.groupby("stock_id")["score"].shift(1).fillna(0.0)
stj = run(START, END, sigframe=sig_j, **kw_for(*WINNER))
print(f"(b) 進場延遲 +1 交易日：Sharpe {win_is['sharpe']:.2f}→{stj['sharpe']:.2f} / "
      f"年化 {win_is['annual']*100:.1f}→{stj['annual']*100:.1f}% / DD {win_is['dd']*100:.1f}→{stj['dd']*100:.1f}%")

pnl = win_is["pnl_by_stock"]
top3 = [s for s, _ in sorted(pnl.items(), key=lambda x: -x[1])[:3]]
print(f"(c) leave-one-out 前3大貢獻股 {top3}：")
loo_min = win_is["sharpe"]
for s in top3:
    st = run(START, END, universe=[x for x in LIVE_UNIVERSE if x != s], **kw_for(*WINNER))
    loo_min = min(loo_min, st["sharpe"])
    print(f"    −{s}: Sharpe {st['sharpe']:.2f} / 年化 {st['annual']*100:.1f}% / DD {st['dd']*100:.1f}%")
rng = np.random.default_rng(42)
subs_sh, subs_dd = [], []
for _ in range(50):
    st = run(START, END, universe=list(rng.choice(LIVE_UNIVERSE, size=28, replace=False)), **kw_for(*WINNER))
    if st:
        subs_sh.append(st["sharpe"])
        subs_dd.append(st["dd"])
subs_sh, subs_dd = np.array(subs_sh), np.array(subs_dd)
print(f"    K={len(subs_sh)} 無放回子集(size28) Sharpe：點估 {win_is['sharpe']:.2f}｜中位 {np.median(subs_sh):.2f}｜"
      f"5th-pct {np.percentile(subs_sh, 5):.2f}｜min {subs_sh.min():.2f}")
print(f"                              DD：中位 {np.median(subs_dd)*100:.1f}%｜5th-pct(較差) {np.percentile(subs_dd, 5)*100:.1f}%｜worst {subs_dd.min()*100:.1f}%")
robust_ok = (np.median(subs_sh) >= 0.85 * win_is["sharpe"]) and (np.percentile(subs_sh, 5) > 0.0) and (loo_min > 0.85 * win_is["sharpe"])


# ───────────────────────── 決策閘 ─────────────────────────
print("\n" + "=" * 100)
print("決策閘（綁 Part 2b 擴張窗；相對優先＋分 regime；in-sample 線索不參與否決）")
print("=" * 100)
c1 = exp_wf["pooled_sharpe"] > base_pooled_sharpe
c2 = exp_wf["worst_dd"] >= base_worst_dd - 0.02
in_plat_flags = [r["in_plat"] for r in exp_wf["rows"]]
c3 = all(in_plat_flags)
c4 = IR > 0
c5 = robust_ok
print(f"① pooled OOS Sharpe 勝 live 基準：{exp_wf['pooled_sharpe']:.2f} vs {base_pooled_sharpe:.2f} → {'✓' if c1 else '✗'}")
print(f"② 最差前進年 DD 不比基準差>2pp：{exp_wf['worst_dd']*100:.1f}% vs {base_worst_dd*100:.1f}% → {'✓' if c2 else '✗'}")
print(f"③ 選擇穩定（C*_Y 全落高原區）：{[('✓' if f else '✗') for f in in_plat_flags]}（{FWD_YEARS}）→ {'✓' if c3 else '✗'}")
print(f"④ IR vs 基準B > 0：{IR:+.2f} → {'✓' if c4 else '✗'}")
print(f"⑤ 穩健性健康（子集中位≥85%點估 ＆ 5th-pct>0 ＆ LOO 不崩）：{'✓' if c5 else '✗'}")
PASS = c1 and c2 and c3 and c4 and c5
print(f"\n>>> PRIMARY 全過 → {'PASS（落地 live config）' if PASS else 'FAIL（不動 live）'} <<<")

bear22 = exp_wf["dd_by_year"].get(2022, float("nan"))
print("\n分 regime（報告，不自動否決）：")
print(f"  2022 OOS DD {bear22*100:.1f}% vs 0050 {b0.get(2022, float('nan'))*100:.1f}% → "
      f"{'優於被動' if (bear22 == bear22 and bear22 > b0.get(2022, -1)) else '劣於被動'}")
print(f"  絕對門檻（報告目標非否決）：Sharpe≥1.0 {'✓' if exp_wf['pooled_sharpe'] >= 1.0 else '✗'}｜"
      f"最差年DD≤-15% {'✓' if exp_wf['worst_dd'] >= -0.15 else '✗'}｜年化≥10% {'✓' if exp_wf['pooled_ann'] >= 0.10 else '✗'}")
if not PASS:
    fails = [n for n, ok in zip(["①Sharpe", "②DD", "③穩定", "④IR", "⑤穩健"], [c1, c2, c3, c4, c5]) if not ok]
    print(f"  FAIL 來源：{fails}（若僅②、且由 2022 主導 → 熊年 n=1 inconclusive，勿全盤否決；找最大可驗證子改動 reroute）")
print("\n[done]")

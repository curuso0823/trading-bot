"""
notebooks/p9_walkforward.py
Phase 9 · Part 3 — walk-forward 驗證「動量傾斜選龍頭」候選（決策所綁；純快取、不打 API）。

Part 1（p9_concentration.py）in-sample 發現：純集中（max_pos↓）反而傷 Sharpe/捕獲；
  但**動量傾斜排序** score'=chip+λ·mom_rank（λ≈0.5–1、N=6）in-sample 全面改善
  （Sharpe 1.14→1.23、Calmar 0.91→1.05、DD -13.8→-13.2%、2024 捕獲 0.29→0.39、top3 49→44%）。
  ⚠️ 但 Phase 8 的教訓是「in-sample 峰值會在 OOS 蒸發」。本檔把它放到前進窗重新評分。

設計（逐字複用 p8_walkforward.py 的 harness，只把內層 grid 從 exit-grid 換成 (λ,N)）：
  · 真·再優化 walk-forward：擴張訓練窗 [2018,Y-1]→前進年 Y∈{2022..25}；每窗在 (λ,N) grid 上
    用 Phase 6 Gate 選 C*_Y（Calmar 優先），記錄選擇穩定度（λ* 跨年是否穩＝過擬合 tell）。
  · pooled OOS：串「逐日報酬」算 Sharpe/年化；DD 用「最差前進年」（絕不串非連續年權益）。
  · 對照：live 基準（λ0/N6）OOS、預先指定基準B（0050+vol-target, vol0.011 無 overlay）、IR。
決策閘（同 p8，相對優先）：① pooled OOS Sharpe 勝 live 基準；② 最差前進年 DD 不差>2pp；
  ③ 選擇穩定（λ* 不亂跳，移動>1 grid step ⇒ REJECT）；④ IR vs 基準B>0；⑤ 穩健（+1日延遲不崩）。
用法：.venv/bin/python notebooks/p9_walkforward.py
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

_spec = importlib.util.spec_from_file_location("benchmark_backtest", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

START, END, CAP = "2018-01-01", "2025-12-31", 100_000
FWD_YEARS = [2022, 2023, 2024, 2025]
SQRT252 = np.sqrt(252)
LOOKBACK, SKIP = 120, 5
LAMBDA_GRID = [0.0, 0.5, 1.0, 2.0]      # 0=純集中對照；Part1 高原在 0.5–1；2=退化點
N_GRID = [4, 5, 6]
STABLE_LAM = {0.5, 1.0}                  # Part1 in-sample 高原（穩定帶；λ* 落此＝穩）


# ───────────────────────── helpers（逐字複用 p8）─────────────────────────
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


def eq_series(st):
    return pd.Series(st["equity_full"], index=pd.to_datetime(st["equity_full_dates"]))


def year_dr(eq, y):
    return eq[eq.index.year == y].pct_change().dropna()


def h2_dr(eq, y):
    return eq[(eq.index.year == y) & (eq.index.month >= 7)].pct_change().dropna()


def momentum_rank_long(price_df, lookback=LOOKBACK, skip=SKIP):
    close = price_df.pivot(index="date", columns="stock_id", values="close").sort_index()
    mom = close.shift(skip) / close.shift(lookback) - 1.0
    rank = mom.rank(axis=1, pct=True)
    return rank.reset_index().melt(id_vars="date", var_name="stock_id", value_name="mom_rank")


def tilt_score(base_sig, mom_long, lam):
    if lam == 0:
        return base_sig
    out = base_sig.merge(mom_long, on=["date", "stock_id"], how="left")
    out["mom_rank"] = out["mom_rank"].fillna(0.5)
    out["score"] = out["score"] + lam * out["mom_rank"]
    return out.drop(columns=["mom_rank"])


# ───────────────────────── 0050 / 基準B + build signals ONCE ─────────────────────────
print("載入 0050 + 預先指定基準B（vol0.011 無 overlay；純快取）…")
adj0050 = bm.load_adjusted_0050()
px0 = adj0050.set_index("date")["close"].sort_index().astype(float)
b0 = {}
for y in range(2018, 2026):
    sy = px0[px0.index.year == y]
    if len(sy) >= 5:
        b0[y] = float(sy.iloc[-1] / sy.iloc[0] - 1)
bench_b = bm.simulate_benchmark(adj0050, 0.011)
bench_b_eq = bench_b["equity"]
print(f"基準B 全期：年化 {bench_b['annual']*100:.1f}% / Sharpe {bench_b['sharpe']:.2f} / DD {bench_b['dd']*100:.1f}%")

print(f"\n建訊號（{len(LIVE_UNIVERSE)} 檔 LIVE_UNIVERSE，{START}~{END}，純快取）…")
price_df, SIG = build_signals(LIVE_UNIVERSE, START, END)
MOM = momentum_rank_long(price_df)
SIGS = {lam: tilt_score(SIG, MOM, lam) for lam in LAMBDA_GRID}   # 每 λ 的傾斜 sig 建一次


def cap_for(N):
    return {"max_pos": N}      # C1 固定上限（0.10/0.30）；WF 用 C1，避 N=3·C2 60% 單檔脆弱


def run(start, end, lam, N, *, full=False):
    return run_capped(price_df, SIGS[lam], LIVE_UNIVERSE, start, end,
                      capital=CAP, mode="odd_lot", full_equity=full, **cap_for(N))


# ───────────────────── 中性檢查（λ0/N6 == live 基準）─────────────────────
a = run(START, END, 0.0, 6)
b = run_capped(price_df, SIG, LIVE_UNIVERSE, START, END, capital=CAP, mode="odd_lot", max_pos=6)
neutral = (a["pnl_by_stock"] == b["pnl_by_stock"] and a["per_year"] == b["per_year"]
           and a["sharpe"] == b["sharpe"] and a["n_trades"] == b["n_trades"])
print(f"\n[中性檢查] λ0/N6 == live 基準逐鍵：{'NEUTRAL OK' if neutral else '✗ FAILED'}")
assert neutral, "λ0/N6 非 live 基準！停止。"

base_full = run(START, END, 0.0, 6, full=True)
base_eq = eq_series(base_full)
print(f"[doc-sanity] live 基準 6/λ0：年化 {base_full['annual']*100:.1f}% / Sharpe {base_full['sharpe']:.2f} / "
      f"DD {base_full['dd']*100:.1f}% / 交易 {base_full['n_trades']}")


# ───────────────────── 真·再優化 walk-forward（決策所綁）─────────────────────
def select_cstar(train_end_year, train_start):
    """在 [train_start, train_end-12-31] 跑 (λ,N) grid、Phase 6 Gate 選 C*（Calmar 優先）；無 PASS→落回 λ0/N6。"""
    end = f"{train_end_year}-12-31"
    rows = {}
    for lam in LAMBDA_GRID:
        for N in N_GRID:
            st = run(train_start, end, lam, N)
            if not st:
                continue
            t1, t3 = concentration(st["pnl_by_stock"])
            rows[(lam, N)] = {"sharpe": st["sharpe"], "calmar": calmar(st["annual"], st["dd"]),
                              "dd": st["dd"], "top1": t1, "top3": t3, "lam": lam, "N": N}
    gbase = rows[(0.0, 6)]
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
        return (best["lam"], best["N"]), len(passed)
    return (0.0, 6), 0


def wf_run(train_fn):
    rows, strat_daily, dd_by_year = [], [], {}
    for Y in FWD_YEARS:
        (lam, N), n_pass = select_cstar(Y - 1, train_fn(Y))
        st = run(START, f"{Y}-12-31", lam, N, full=True)
        eq = eq_series(st)
        d = st["per_year"].get(Y, {})
        dd_by_year[Y] = d.get("dd", float("nan"))
        dr, h2 = year_dr(eq, Y), h2_dr(eq, Y)
        rows.append({"Y": Y, "lam": lam, "N": N, "n_pass": n_pass,
                     "ret": d.get("ret", float("nan")), "dd": d.get("dd", float("nan")),
                     "sharpe": d.get("sharpe", float("nan")), "h2_sharpe": sharpe_of(h2),
                     "stable": lam in STABLE_LAM,
                     "cap": (d.get("ret") / b0[Y]) if (Y in b0 and abs(b0[Y]) > 1e-9 and d) else float("nan")})
        strat_daily.append(dr)
    pooled = pd.concat(strat_daily)
    return {"rows": rows, "pooled": pooled, "pooled_sharpe": sharpe_of(pooled),
            "pooled_ann": ann_of(pooled), "worst_dd": min(dd_by_year.values()), "dd_by_year": dd_by_year}


def _print_wf(title, wf):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)
    print(f"{'前進年':>6}{'選到 C*_Y(λ·N)':>16}{'通過數':>7}{'穩定':>5}{'OOS%':>7}{'Sharpe':>8}{'DD%':>7}{'H2Sh':>7}{'2024捕獲':>9}")
    for r in wf["rows"]:
        lbl = f"λ{r['lam']:g}·N{r['N']}"
        print(f"{r['Y']:>6}{lbl:>16}{r['n_pass']:>7}{('✓' if r['stable'] else '·'):>5}"
              f"{r['ret']*100:>7.1f}{r['sharpe']:>8.2f}{r['dd']*100:>7.1f}{r['h2_sharpe']:>7.2f}{r['cap']:>9.2f}")
    print(f"pooled OOS：Sharpe {wf['pooled_sharpe']:.2f} / 年化 {wf['pooled_ann']*100:.1f}% / 最差前進年DD {wf['worst_dd']*100:.1f}%")


exp_wf = wf_run(lambda Y: "2018-01-01")
_print_wf("真·再優化 walk-forward（擴張訓練窗 [2018,Y-1]→Y；(λ,N) grid；Phase 6 Gate 選 C*）", exp_wf)

base_oos = pd.concat([year_dr(base_eq, Y) for Y in FWD_YEARS])
base_worst_dd = min(base_full["per_year"][Y]["dd"] for Y in FWD_YEARS if Y in base_full["per_year"])
base_pooled_sharpe = sharpe_of(base_oos)
benb_oos = pd.concat([year_dr(bench_b_eq, Y) for Y in FWD_YEARS])
ir_df = pd.concat([exp_wf["pooled"].rename("s"), benb_oos.rename("b")], axis=1).dropna()
cover = len(ir_df) / len(exp_wf["pooled"])
assert cover > 0.99, f"IR 日期對齊覆蓋 {cover:.1%} < 99%"
IR = sharpe_of(ir_df["s"] - ir_df["b"])
print(f"  ↳ 對照同前進年 pooled OOS：")
print(f"     live 基準 λ0/N6 ：Sharpe {base_pooled_sharpe:.2f} / 年化 {ann_of(base_oos)*100:.1f}% / 最差前進年DD {base_worst_dd*100:.1f}%")
print(f"     基準B vol0.011  ：Sharpe {sharpe_of(benb_oos):.2f} / 年化 {ann_of(benb_oos)*100:.1f}%")
print(f"     IR(策略−基準B)  ：{IR:+.2f}（日期對齊 {cover:.1%}）")


# ───────────────────── 固定 λ pooled OOS（λ＝結構性 config 參數、production 不逐年重調）─────────────────────
# 不同於上面的「再優化選擇」：λ 在 live 是固定設計選擇。問：committed 一個固定 λ 是否 OOS 勝 λ0？
def fixed_oos(lam, N):
    st = run(START, END, lam, N, full=True)
    eq = eq_series(st)
    pooled = pd.concat([year_dr(eq, Y) for Y in FWD_YEARS])
    dd_by = {Y: st["per_year"].get(Y, {}).get("dd", float("nan")) for Y in FWD_YEARS}
    ir_d = pd.concat([pooled.rename("s"), benb_oos.rename("b")], axis=1).dropna()
    d24 = st["per_year"].get(2024, {})
    return {"sharpe": sharpe_of(pooled), "ann": ann_of(pooled), "worst_dd": min(dd_by.values()),
            "ir": sharpe_of(ir_d["s"] - ir_d["b"]),
            "cap24": (d24.get("ret") / b0[2024]) if d24 else float("nan")}


print("\n" + "=" * 100)
print("固定 λ pooled OOS（λ 為固定 config 參數、非逐年重選；λ0/N6＝live 基準）")
print("=" * 100)
print(f"{'固定設定':<12}{'pooledSh':>9}{'年化%':>7}{'最差年DD%':>10}{'IR vs B':>9}{'2024捕獲':>9}{'勝基準?':>8}")
for N in (6, 4):
    for lam in LAMBDA_GRID:
        m = fixed_oos(lam, N)
        win = "✓" if (m["sharpe"] > base_pooled_sharpe and m["ir"] > 0) else "·"
        print(f"{'λ'+format(lam,'g')+'·N'+str(N):<12}{m['sharpe']:>9.2f}{m['ann']*100:>7.1f}"
              f"{m['worst_dd']*100:>10.1f}{m['ir']:>+9.2f}{m['cap24']:>9.2f}{win:>8}")
print(f"（對照 live 基準 λ0/N6：pooledSh {base_pooled_sharpe:.2f} / IR vs B 需 >0 才算勝風險匹配被動）")


# ───────────────────── 固定 Part1 贏家（λ0.5/N6）逐前進年 OOS 一致性 ─────────────────────
win_full = run(START, END, 0.5, 6, full=True)
print("\n" + "=" * 100)
print("固定 Part1 候選（λ0.5/N6）逐前進年（勝果穩定跨年 vs 靠 1–2 年？）")
print("=" * 100)
print(f"{'年':>6}{'策略%':>8}{'Sharpe':>8}{'DD%':>7}{'0050%':>8}{'捕獲':>7}")
for Y in FWD_YEARS:
    d = win_full["per_year"].get(Y, {})
    c = (d.get("ret") / b0[Y]) if (Y in b0 and abs(b0[Y]) > 1e-9 and d) else float("nan")
    print(f"{Y:>6}{d.get('ret', float('nan'))*100:>8.1f}{d.get('sharpe', float('nan')):>8.2f}"
          f"{d.get('dd', float('nan'))*100:>7.1f}{b0.get(Y, float('nan'))*100:>8.1f}{c:>7.2f}")

# +1 日延遲 leak 偵測（複用 p8）
sig_j = SIGS[0.5].sort_values(["stock_id", "date"]).copy()
sig_j["entry_signal"] = sig_j.groupby("stock_id")["entry_signal"].shift(1).fillna(False)
sig_j["score"] = sig_j.groupby("stock_id")["score"].shift(1).fillna(0.0)
stj = run_capped(price_df, sig_j, LIVE_UNIVERSE, START, END, capital=CAP, mode="odd_lot", max_pos=6)
print(f"\n[leak 偵測] λ0.5/N6 進場延遲 +1 日：Sharpe {win_full['sharpe']:.2f}→{stj['sharpe']:.2f}"
      f"（崩跌＝動量有 1 日洩漏；持平＝乾淨）")


# ───────────────────────── 決策閘 ─────────────────────────
print("\n" + "=" * 100)
print("決策閘（綁再優化 walk-forward；相對優先；in-sample 不參與否決）")
print("=" * 100)
lam_stars = [r["lam"] for r in exp_wf["rows"]]
c1 = exp_wf["pooled_sharpe"] > base_pooled_sharpe
c2 = exp_wf["worst_dd"] >= base_worst_dd - 0.02
c3 = all(r["stable"] for r in exp_wf["rows"])      # λ* 全落穩定帶
c4 = IR > 0
delay_ok = stj["sharpe"] >= 0.85 * win_full["sharpe"]
c5 = delay_ok
print(f"① pooled OOS Sharpe 勝 live 基準：{exp_wf['pooled_sharpe']:.2f} vs {base_pooled_sharpe:.2f} → {'✓' if c1 else '✗'}")
print(f"② 最差前進年 DD 不比基準差>2pp：{exp_wf['worst_dd']*100:.1f}% vs {base_worst_dd*100:.1f}% → {'✓' if c2 else '✗'}")
print(f"③ 選擇穩定（λ* 全落 {STABLE_LAM}）：λ*={lam_stars} → {'✓' if c3 else '✗'}")
print(f"④ IR vs 基準B > 0：{IR:+.2f} → {'✓' if c4 else '✗'}")
print(f"⑤ 穩健（+1日延遲 Sharpe≥85%點估）：{stj['sharpe']:.2f} vs {win_full['sharpe']:.2f} → {'✓' if c5 else '✗'}")
PASS = c1 and c2 and c3 and c4 and c5
print(f"\n>>> PRIMARY 全過 → {'PASS（候選可提案落地，gated config-only）' if PASS else 'FAIL（不動 live）'} <<<")
bear22 = exp_wf["dd_by_year"].get(2022, float("nan"))
print(f"\n分 regime（報告）：2022 OOS DD {bear22*100:.1f}% vs 0050 {b0.get(2022, float('nan'))*100:.1f}% → "
      f"{'優於被動' if (bear22 == bear22 and bear22 > b0.get(2022, -1)) else '劣於被動'}")
print(f"絕對門檻（報告）：Sharpe≥1 {'✓' if exp_wf['pooled_sharpe'] >= 1.0 else '✗'}｜"
      f"最差年DD≤-15% {'✓' if exp_wf['worst_dd'] >= -0.15 else '✗'}｜年化≥10% {'✓' if exp_wf['pooled_ann'] >= 0.10 else '✗'}")
if not PASS:
    fails = [n for n, ok in zip(["①Sharpe", "②DD", "③穩定", "④IR", "⑤穩健"], [c1, c2, c3, c4, c5]) if not ok]
    print(f"FAIL 來源：{fails}")
print("\n[done]")

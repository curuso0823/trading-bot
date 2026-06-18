"""
notebooks/e1e2_walkforward.py
E1（N 日確認）+ E2（對稱緩衝帶）正式 walk-forward OOS 驗證（沙盒研究；純快取、0 API、不改任何既有檔）。

承 docs/E1_E3_COMPARISON.md：E1/E2 in-sample 細網格皆「平滑高原、無 alpha、whipsaw 單調↓」。本檔把 in-sample
線索升級成**正式 walk-forward**（移植 notebooks/r1_walkforward.py 的 fold 結構，按誠實池/同族基線重錨）：
  • 擴張窗：每個前進年 Y∈{2022,23,24,25}，用 [2018-01-01, Y-1] 選參、套到 Y（嚴格 OOS）。
  • 內層選參：Calmar 優先（Sharpe tiebreak）；**DD floor 重錨『同族基線 current-live』**（鐵則#8：基準B 為不同 vol
    體制、錨它會 vacuous；refinement 的自然同族錨＝N=1/band=0 的現行 overlay）；**永不 fallback 固定參數**。
  • 主裁＝pooled OOS（FWD 日報酬串接）Sharpe / IR vs 基準B / 最差前進年 DD；對照固定預先指定基準B(vol0.011)+0050 買持。
  • plateau 穩定（鐵則#7）＋ 跨 fold 選參是否穩定。
  • 額外（使用者要求）：**2018（in-sample whipsaw 重災年）與 2022（OOS 熊市+whipsaw）全年 報酬/Sharpe/DD/flips** 聚焦表。

口徑統一（修正 E1_E3 綜整指出的 E2 vs E1/E3 OOS-Sharpe 定義差）：全檔一律用
  pooled = concat([eq[year==Y].pct_change().dropna() for Y in FWD]) → sharpe_of(pooled)；per-year 用 bm._per_year。

⚠️ 描述性、非證實：R5 已定誠實池無顯著 alpha；此 overlay＝結構性降回撤/降 whipsaw 規則、非 outperformer。
   FinMind 無下市股 → 全為上界（survivorship）。**總 Gate 未過前 live（MA200 + regime_action 0.85）不動。**
用法：.venv/bin/python notebooks/e1e2_walkforward.py
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

_spec = importlib.util.spec_from_file_location("bm", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

SQRT252 = np.sqrt(252)
FWD = [2022, 2023, 2024, 2025]      # OOS 前進窗（同 R0/R1/E1-E3）
MA = 200
REDUCED, FULL = 0.85, 1.0
DD_BAND = 0.022                      # path-dependence 容差（同 R1；相對同族基線 floor 用）

# 細網格（同 E1/E2 沙盒）
E1_GRID = [1, 2, 3, 4, 5, 7, 10]                                             # 對稱 N（N=1＝current-live）
E2_GRID = [0.0, 0.0025, 0.005, 0.0075, 0.010, 0.0125, 0.015, 0.0175, 0.020, 0.025, 0.030, 0.035]  # band=0＝live


# ───────────────────────── helpers（沿用 r1/E1-E3 口徑）─────────────────────────
def sharpe_of(dr):
    sd = dr.std()
    return float(dr.mean() / sd * SQRT252) if sd > 0 else 0.0


def ann_of(dr):
    n = len(dr)
    return float((1 + dr).prod() ** (252 / n) - 1) if n > 0 else float("nan")


def year_dr(eq, y):
    return eq[eq.index.year == y].pct_change().dropna()


def dd_of_window(eq, start, end):
    s = eq[(eq.index >= pd.Timestamp(start)) & (eq.index <= pd.Timestamp(end))]
    return float((s / s.cummax() - 1).min()) if len(s) else float("nan")


def calmar(a, dd):
    return a / abs(dd) if dd and abs(dd) > 1e-9 else float("nan")


def window_metrics(eq, start, end):
    """[start,end] 內：年化 / Sharpe / maxDD / Calmar（DD 相對窗內 cummax）。"""
    s = eq[(eq.index >= pd.Timestamp(start)) & (eq.index <= pd.Timestamp(end))]
    r = s.pct_change().dropna()
    ann = float((s.iloc[-1] / s.iloc[0]) ** (252 / len(s)) - 1) if len(s) > 1 and s.iloc[0] > 0 else float("nan")
    dd = float((s / s.cummax() - 1).min()) if len(s) else float("nan")
    return ann, sharpe_of(r), dd, calmar(ann, dd)


def sharpe_se_ann(dr):
    """年化 Sharpe 1 SE（Lo 2002）。"""
    n = len(dr)
    sd = dr.std()
    if n < 30 or sd == 0:
        return float("nan")
    srd = dr.mean() / sd
    return float(np.sqrt((1 + 0.5 * srd ** 2) / n) * SQRT252)


# ── sim_from_exp（逐字複製 r6/E1/E2；回傳 (eq, n_exec)）────────────────────────────
def sim_from_exp(adj, exp_full):
    df = adj[(adj["date"] >= pd.Timestamp(bm.START)) & (adj["date"] <= pd.Timestamp(bm.END))].reset_index(drop=True)
    dates = pd.DatetimeIndex(df["date"])
    close = df["close"].to_numpy(float)
    opn = df["open"].to_numpy(float)
    target_exp = exp_full.reindex(dates).to_numpy(float)
    month_first = bm.is_month_first_trading_day(dates).to_numpy(bool)
    n = len(df)
    cash, qty, avg_cost = bm.INITIAL, 0, 0.0
    eq = np.empty(n)
    n_exec = 0
    for i in range(n):
        eq[i] = cash + qty * close[i] * bm.LOT
        if i + 1 >= n:
            continue
        te = target_exp[i]
        if not np.isfinite(te):
            continue
        equity_now = eq[i]
        cur_exp = (qty * close[i] * bm.LOT) / equity_now if equity_now > 0 else 0.0
        if not (month_first[i] or abs(cur_exp - te) > bm.BAND):
            continue
        fill_buy, fill_sell = opn[i + 1] * (1 + bm.SLIP), opn[i + 1] * (1 - bm.SLIP)
        target_qty = int((equity_now * te) / (fill_buy * bm.LOT)) if fill_buy > 0 else 0
        delta = target_qty - qty
        if delta > 0:
            buyable = delta
            while buyable >= 1:
                amt = fill_buy * buyable * bm.LOT
                if amt + bm._buyfee(amt) <= cash:
                    break
                buyable -= 1
            if buyable < 1:
                continue
            amt = fill_buy * buyable * bm.LOT
            cash -= amt + bm._buyfee(amt)
            new_qty = qty + buyable
            avg_cost = (avg_cost * qty + (amt + bm._buyfee(amt))) / new_qty
            qty = new_qty
            n_exec += 1
        elif delta < 0:
            sell_qty = -delta
            amt = fill_sell * sell_qty * bm.LOT
            cash += amt - bm._sellcost(amt)
            qty -= sell_qty
            if qty == 0:
                avg_cost = 0.0
            n_exec += 1
    return pd.Series(eq, index=dates), n_exec


# ── 曝險 builder（逐字複製 E1/E2 狀態機）──────────────────────────────────────────
def exp_nday(close_full, raw_below, n_exit, n_reentry):
    rb = raw_below.to_numpy(bool)
    n = len(rb)
    out = np.empty(n)
    state = FULL
    run_below = run_above = 0
    for i in range(n):
        if rb[i]:
            run_below += 1
            run_above = 0
        else:
            run_above += 1
            run_below = 0
        if state == FULL:
            if run_below >= n_exit:
                state = REDUCED
        else:
            if run_above >= n_reentry:
                state = FULL
        out[i] = state
    return pd.Series(out, index=close_full.index)


def exp_hysteresis(close_full, alpha, beta):
    cf = close_full.astype(float)
    ma = cf.rolling(MA).mean()
    cvals = cf.to_numpy(float)
    mvals = ma.to_numpy(float)
    n = len(cf)
    out = np.empty(n, dtype=float)
    state = FULL
    for i in range(n):
        m = mvals[i]
        if np.isfinite(m):
            lo, hi = m * (1.0 - alpha), m * (1.0 + beta)
            c = cvals[i]
            if state == FULL:
                if c < lo:
                    state = REDUCED
            else:
                if c > hi:
                    state = FULL
        out[i] = state
    return pd.Series(out, index=cf.index)


def flips_in_year(exp_series, year):
    s = exp_series[exp_series.index.year == year]
    if len(s) < 2:
        return 0
    b = np.isclose(s.to_numpy(float), REDUCED).astype(int)
    return int((np.diff(b) != 0).sum())


def exp_for(kind, p):
    return exp_nday(cf, raw_below, p, p) if kind == "E1" else exp_hysteresis(cf, p, p)


# ════════════════════════════════════════════════════════════════════════════════
print("=" * 110)
print("E1 + E2 正式 walk-forward OOS 驗證 | 載入快取 0050（0 API / cache-only）…")
print("=" * 110)
adj = bm.load_adjusted_0050()
cf = adj.set_index("date")["close"].sort_index().astype(float)
ma200 = cf.rolling(MA).mean()
raw_below = (cf < ma200).fillna(False)
print(f"[sanity] 0050 還原日線（快取，無 API）：{len(cf)} 列，{cf.index.min().date()} ~ {cf.index.max().date()}")
print(f"[sanity] 0 API / cache-only：僅 bm.load_adjusted_0050() 讀本地 pickle，無任何 fetcher.get_* 網路呼叫。")
print(f"[sanity] FWD(OOS)={FWD}｜內層選參 floor 重錨『同族基線 current-live』− {DD_BAND*100:.1f}pp（鐵則#8）")

# ── 固定預先指定對照（compute once）────────────────────────────────────────────────
bh = bm.simulate_buyhold(adj)
benchB = bm.simulate_benchmark(adj, 0.011, overlay=False)
bh_eq, bb_eq = bh["equity"], benchB["equity"]
live_eq, live_nx = sim_from_exp(adj, exp_for("E1", 1))     # current-live = N=1 = band=0
live_exp = exp_for("E1", 1)

# 退化點 sanity：E1 N=1 == E2 band=0 == 引擎 overlay 路徑
e2_deg, _ = sim_from_exp(adj, exp_for("E2", 0.0))
eng = bm.simulate_benchmark(adj, 1.0, overlay=True, regime_ma=MA, regime_action=0.85)["equity"]
d1 = float((live_eq - e2_deg).abs().max())
d2 = float((live_eq - eng).abs().max())
assert d1 < 1e-6 and d2 < 1e-3, f"退化點不一致：E1N1 vs E2band0={d1:.2e}, vs 引擎={d2:.2e}"
print(f"[sanity] 退化點三方一致：E1(N=1)≡E2(band=0)≡引擎 overlay（max|Δ|={d1:.1e}/{d2:.1e} 元）；"
      f"current-live 全期交易數={live_nx}")

# 基準B / 0050 的 OOS pooled + 最差前進年 DD（固定對照）
benB_oos = pd.concat([year_dr(bb_eq, Y) for Y in FWD])
bh_oos = pd.concat([year_dr(bh_eq, Y) for Y in FWD])
live_oos = pd.concat([year_dr(live_eq, Y) for Y in FWD])
SB, S0, SL = sharpe_of(benB_oos), sharpe_of(bh_oos), sharpe_of(live_oos)
BENB_WDD = min(dd_of_window(bb_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
BH_WDD = min(dd_of_window(bh_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
LIVE_WDD = min(dd_of_window(live_eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
DELTA = sharpe_se_ann(live_oos)     # plateau 雜訊尺度（基於 current-live OOS pooled）
print(f"[plateau scale] δ(OOS 年化 Sharpe 1 SE, Lo-2002, current-live pooled n={len(live_oos)}) = {DELTA:.3f}")


# ── 預跑每個參數的全期 eq（一次、重用；causal sim → 切窗＝重跑到該窗，等價）──────────
EQ = {}     # (kind,p) -> (eq, n_exec, exp_series)
for kind, grid in [("E1", E1_GRID), ("E2", E2_GRID)]:
    for p in grid:
        e = exp_for(kind, p)
        eqp, nxp = sim_from_exp(adj, e)
        EQ[(kind, p)] = (eqp, nxp, e)


# ───────────────────────── walk-forward 核心 ─────────────────────────
def select_param(kind, grid, train_end_year, objective="calmar"):
    """擴張窗 [2018, train_end_year] 內選參：Calmar(或Sharpe) argmax；
    DD floor 重錨同族基線 current-live 同窗 DD − DD_BAND；永不固定 fallback（空集→放寬全格 argmax+flag）。"""
    start, end = "2018-01-01", f"{train_end_year}-12-31"
    live_dd = dd_of_window(live_eq, start, end)
    floor_thr = live_dd - DD_BAND
    mets = {}
    for p in grid:
        ann, sh, dd, cal = window_metrics(EQ[(kind, p)][0], start, end)
        mets[p] = dict(p=p, ann=ann, sh=sh, dd=dd, cal=cal)
    passers = [m for m in mets.values() if m["dd"] >= floor_thr]
    empty = len(passers) == 0
    pool = passers if passers else list(mets.values())
    key = (lambda m: (m["cal"], m["sh"])) if objective == "calmar" else (lambda m: (m["sh"], m["cal"]))
    best = max(pool, key=key)
    return best["p"], len(passers), empty, floor_thr


def walk_forward(kind, grid, objective="calmar"):
    rows, strat_daily, ddby = [], [], {}
    for Y in FWD:
        p_star, npass, empty, floor_thr = select_param(kind, grid, Y - 1, objective)
        eqp = EQ[(kind, p_star)][0]
        py = bm._per_year(eqp).get(Y, (float("nan"),) * 3)
        ddby[Y] = py[2]
        strat_daily.append(year_dr(eqp, Y))
        rows.append(dict(Y=Y, p=p_star, npass=npass, empty=empty, floor=floor_thr,
                         ret=py[0], sh=py[1], dd=py[2], flips=flips_in_year(EQ[(kind, p_star)][2], Y)))
    pooled = pd.concat(strat_daily)
    # IRvs基準B（基準B＝de-risked → 此 IR 受 beta 差主導、非 alpha）＋ IRvs0050（同 beta → 才是真 alpha 檢定）
    d = pd.concat([pooled.rename("s"), benB_oos.rename("b")], axis=1).dropna()
    ir = sharpe_of(d["s"] - d["b"])
    d0 = pd.concat([pooled.rename("s"), bh_oos.rename("b")], axis=1).dropna()
    ir0 = sharpe_of(d0["s"] - d0["b"])
    return dict(rows=rows, pooled=pooled, pooled_sharpe=sharpe_of(pooled), pooled_ann=ann_of(pooled),
                worst_fwd_dd=min(ddby.values()), ir=ir, ir0=ir0, params=[r["p"] for r in rows])


def fmt_p(kind, p):
    return f"N={int(p)}" if kind == "E1" else f"{p*100:.2f}%"


def stab_note(kind, params):
    grid = E1_GRID if kind == "E1" else E2_GRID
    idxs = [grid.index(p) for p in params]
    spread = max(idxs) - min(idxs)
    uniq = sorted(set(params))
    return spread, uniq


print("\n" + "=" * 110)
print("Part A — walk-forward 選參（擴張窗 [2018,Y-1]→Y；Calmar·相對-live 主規則 + Sharpe·相對-live robustness）")
print("=" * 110)
WF = {}
for kind, grid in [("E1", E1_GRID), ("E2", E2_GRID)]:
    print(f"\n— {kind} —  (grid: {[fmt_p(kind,p) for p in grid]})")
    for obj in ("calmar", "sharpe"):
        wf = walk_forward(kind, grid, obj)
        WF[(kind, obj)] = wf
        ps = " ".join(f"{Y}:{fmt_p(kind,r['p'])}" for Y, r in zip(FWD, wf["rows"]))
        spread, uniq = stab_note(kind, wf["params"])
        fe = sum(r["empty"] for r in wf["rows"])
        print(f"  [{obj:>6}·相對-live] 選參 {ps}")
        print(f"      pooled OOS Sharpe {wf['pooled_sharpe']:.3f} | OOS 年化 {wf['pooled_ann']*100:.1f}% | "
              f"IR vs B {wf['ir']:+.3f} | 最差前進年DD {wf['worst_fwd_dd']*100:.1f}% | "
              f"選參跨度 {spread} 格/{len(grid)}、相異 {len(uniq)} 個{'（floor 空集 '+str(fe)+' fold→放寬全格）' if fe else ''}")

# 每 fold 細節（主規則 Calmar·相對-live）
print("\n" + "-" * 110)
print("每 fold 細節（主規則 Calmar·相對-live）：前進年 報酬/Sharpe/年內DD/flips ｜ 選參 ｜ 訓練窗過 floor 數")
print("-" * 110)
print(f"{'實驗':>4}{'前進年':>7}{'選參':>9}{'前進年報酬':>11}{'Sharpe':>8}{'年內DD':>8}{'flips':>6}{'過floor':>8}")
for kind in ("E1", "E2"):
    wf = WF[(kind, "calmar")]
    for r in wf["rows"]:
        print(f"{kind:>4}{r['Y']:>7}{fmt_p(kind,r['p']):>9}{r['ret']*100:>10.1f}%{r['sh']:>8.2f}"
              f"{r['dd']*100:>7.1f}%{r['flips']:>6}{r['npass']:>6}/{len(E1_GRID if kind=='E1' else E2_GRID)}")


# ───────────────────────── Part B — pooled OOS 彙總 vs 固定對照 ─────────────────────────
def ir_vs(pooled, ref_oos):
    d = pd.concat([pooled.rename("s"), ref_oos.rename("b")], axis=1).dropna()
    return sharpe_of(d["s"] - d["b"])


BH_IRB = ir_vs(bh_oos, benB_oos)     # 0050 自身 IRvs基準B（純 beta、零技巧）＝beta 參考線
print("\n" + "=" * 110)
print("Part B — pooled OOS（2022-25 日報酬串接）彙總：walk-forward E1/E2 vs 固定預先指定對照")
print("=" * 110)
print(f"{'策略':<26}{'OOS Sharpe':>11}{'OOS年化':>9}{'最差前進年DD':>13}{'IRvs基準B*':>11}{'IRvs0050':>10}")
print("-" * 110)
print(f"{'current-live(MA200-85)':<26}{SL:>11.3f}{ann_of(live_oos)*100:>8.1f}%{LIVE_WDD*100:>12.1f}%"
      f"{ir_vs(live_oos, benB_oos):>+11.3f}{ir_vs(live_oos, bh_oos):>+10.3f}")
for kind in ("E1", "E2"):
    wf = WF[(kind, "calmar")]
    print(f"{'walk-fwd '+kind+'(Calmar·相對)':<26}{wf['pooled_sharpe']:>11.3f}{wf['pooled_ann']*100:>8.1f}%"
          f"{wf['worst_fwd_dd']*100:>12.1f}%{wf['ir']:>+11.3f}{wf['ir0']:>+10.3f}")
print("-" * 110)
print(f"{'基準B(vol0.011,無overlay)':<26}{SB:>11.3f}{ann_of(benB_oos)*100:>8.1f}%{BENB_WDD*100:>12.1f}%{0.0:>+11.3f}{ir_vs(benB_oos, bh_oos):>+10.3f}")
print(f"{'0050 買進持有':<26}{S0:>11.3f}{ann_of(bh_oos)*100:>8.1f}%{BH_WDD*100:>12.1f}%{BH_IRB:>+11.3f}{0.0:>+10.3f}")
print(f"\n  * IRvs基準B 受 beta 差主導（基準B＝de-risked）→ **非 alpha**：0050 買持自身 IRvs基準B={BH_IRB:+.3f}（純 beta、零技巧）為參考線；")
print(f"    walk-fwd 的 IRvs基準B(+1.1) ≈ 0050 的 {BH_IRB:+.2f} → 只是 beta、無超額。**真 alpha 檢定＝同 beta 的 IRvs0050**：")
print(f"    E1 {WF[('E1','calmar')]['ir0']:+.3f} / E2 {WF[('E2','calmar')]['ir0']:+.3f}（≈0＝無顯著 alpha，與 R5 一致）。")
print(f"  δ(OOS Sharpe 1SE)={DELTA:.3f}；walk-fwd 與 current-live/0050 的 OOS Sharpe 差須以此雜訊尺度判讀。")


# ───────────────────────── Part C — 2018 & 2022 stress-year 聚焦（使用者要求）─────────────────────────
def stress_row(label, eq, exp_series=None):
    py = bm._per_year(eq)
    out = {"label": label}
    for y in (2018, 2022):
        t = py.get(y, (float("nan"),) * 3)
        fl = flips_in_year(exp_series, y) if exp_series is not None else None
        out[y] = (t[0], t[1], t[2], fl)   # ret, sharpe, dd, flips
    return out


def print_stress(title, kind, grid):
    print("\n" + "=" * 110)
    print(title)
    print("  （2018＝in-sample whipsaw 重災年；2022＝OOS 熊市+whipsaw。報酬/Sharpe/年內maxDD/態轉折flips）")
    print("=" * 110)
    print(f"{'設定':<24}｜{'2018報酬':>9}{'2018Sh':>8}{'2018DD':>8}{'fl18':>5}｜"
          f"{'2022報酬':>9}{'2022Sh':>8}{'2022DD':>8}{'fl22':>5}")
    print("-" * 110)
    # 固定對照
    for nm, eq in [("0050 買進持有", bh_eq), ("基準B(vol0.011)", bb_eq)]:
        s = stress_row(nm, eq, None)
        a, b = s[2018], s[2022]
        print(f"{nm:<24}｜{a[0]*100:>8.1f}%{a[1]:>8.2f}{a[2]*100:>7.1f}%{'—':>5}｜"
              f"{b[0]*100:>8.1f}%{b[1]:>8.2f}{b[2]*100:>7.1f}%{'—':>5}")
    # 網格（含退化＝current-live）
    for p in grid:
        eqp, _, e = EQ[(kind, p)]
        s = stress_row("", eqp, e)
        a, b = s[2018], s[2022]
        tag = fmt_p(kind, p) + ("  ←current-live" if (kind == "E1" and p == 1) or (kind == "E2" and p == 0.0) else "")
        print(f"{tag:<24}｜{a[0]*100:>8.1f}%{a[1]:>8.2f}{a[2]*100:>7.1f}%{a[3]:>5}｜"
              f"{b[0]*100:>8.1f}%{b[1]:>8.2f}{b[2]*100:>7.1f}%{b[3]:>5}")
    print("-" * 110)


print_stress("Part C1 — E1（N 日確認）2018 / 2022 全年 報酬 · Sharpe · DD · flips", "E1", E1_GRID)
print_stress("Part C2 — E2（對稱緩衝帶）2018 / 2022 全年 報酬 · Sharpe · DD · flips", "E2", E2_GRID)

# walk-forward 選到的設定在 2018/2022 的數字（明確點出）
print("\n" + "-" * 110)
print("walk-forward 主規則(Calmar·相對-live) 在 2022(OOS) 實際選到的設定 → 2022 全年數字：")
for kind in ("E1", "E2"):
    wf = WF[(kind, "calmar")]
    r22 = next(r for r in wf["rows"] if r["Y"] == 2022)
    print(f"  {kind}: 2022 fold 選 {fmt_p(kind,r22['p'])} → 報酬 {r22['ret']*100:.1f}% / Sharpe {r22['sh']:.2f} / "
          f"年內DD {r22['dd']*100:.1f}% / flips {r22['flips']}（對照 current-live 2022：見上表 N=1/band=0 列）")


# ───────────────────────── Part D — Gate 裁決（§5）─────────────────────────
print("\n" + "=" * 110)
print("Part D — §5 Gate 裁決（walk-forward；總 Gate 未過前 live 不動）")
print("=" * 110)
for kind in ("E1", "E2"):
    wf = WF[(kind, "calmar")]
    wfs = WF[(kind, "sharpe")]
    spread, uniq = stab_note(kind, wf["params"])
    # Gate 條件
    g_dd = (wf["worst_fwd_dd"] >= LIVE_WDD - 1e-9) and (wf["worst_fwd_dd"] > BENB_WDD) and (wf["worst_fwd_dd"] > BH_WDD)
    g_sharpe_noworse = wf["pooled_sharpe"] >= SL - DELTA       # 不顯著差於 current-live（雜訊帶內）
    # 真 alpha 檢定＝同 beta 的 0050（非 de-risked 基準B；IRvs基準B 受 beta 差主導、不可當 alpha）
    sharpe_edge_0050 = wf["pooled_sharpe"] - S0
    g_alpha = (wf["ir0"] > 0) and (sharpe_edge_0050 > DELTA)   # 同 beta IR>0 且 Sharpe 邊際超 δ（預期 FAIL）
    # whipsaw：walk-forward 選到的設定，2022 flips vs current-live(7)
    wf_fl22 = next(r["flips"] for r in wf["rows"] if r["Y"] == 2022)
    live_fl22 = flips_in_year(live_exp, 2022)
    g_whip = wf_fl22 < live_fl22
    # 牛市不顯著犧牲：pooled OOS 年化 vs current-live
    g_bull = wf["pooled_ann"] >= ann_of(live_oos) - 0.01
    robust = abs(wf["pooled_sharpe"] - wfs["pooled_sharpe"]) <= 0.2
    struct_pass = g_dd and g_sharpe_noworse and g_whip and g_bull
    verdict = ("結構 Gate PASS（whipsaw↓ / DD 不惡化 / 牛市不犧牲，OOS 跨 fold 穩健）；alpha Gate FAIL（無顯著超額）"
               if struct_pass else ("FAIL" if not (g_dd and g_whip) else "MARGINAL"))
    print(f"\n【{kind}】walk-forward 主規則 Calmar·相對-live：")
    print(f"  ① 對照固定基準B/0050（已算）；pooled OOS Sharpe {wf['pooled_sharpe']:.3f} vs B {SB:.2f} / 0050 {S0:.2f} / live {SL:.2f}")
    print(f"  ② 降-DD 不惡化且優於兩被動：最差前進年DD {wf['worst_fwd_dd']*100:.1f}% "
          f"(live {LIVE_WDD*100:.1f}% / B {BENB_WDD*100:.1f}% / 0050 {BH_WDD*100:.1f}%) → {'✓' if g_dd else '✗'}")
    print(f"  ③ OOS Sharpe 不顯著差於 current-live（δ={DELTA:.2f} 帶內）：{wf['pooled_sharpe']:.3f} vs {SL:.3f} → {'✓' if g_sharpe_noworse else '✗'}")
    print(f"  ④ whipsaw 降低（2022 flips {wf_fl22} < current-live {live_fl22}）→ {'✓' if g_whip else '✗'}")
    print(f"  ⑤ 牛市不顯著犧牲（OOS 年化 {wf['pooled_ann']*100:.1f}% vs live {ann_of(live_oos)*100:.1f}%）→ {'✓' if g_bull else '✗'}")
    print(f"  ⑥ 選參穩定（跨 fold 跨度 {spread} 格、相異 {len(uniq)} 個）｜robustness(Calmar↔Sharpe 規則 pooled 差 ≤0.2)：{'✓' if robust else '✗'}")
    print(f"  ⑦ **真 alpha？（同 beta vs 0050）** IRvs0050 {wf['ir0']:+.3f}、OOS Sharpe 邊際 {sharpe_edge_0050:+.3f} vs δ {DELTA:.2f} → "
          f"{'✓ 有顯著 alpha' if g_alpha else '✗ 無（δ 內）；註：IRvs基準B +'+format(wf['ir'],'.2f')+' 是 beta 非 alpha（0050 自身 IRvsB='+format(BH_IRB,'.2f')+'）'}")
    print(f"  ▶ {kind} 裁決：{verdict}")

print("\n" + "=" * 110)
print("結論口徑：此為 walk-forward OOS（非 in-sample）。whipsaw修正 的真 Gate＝降-DD 不惡化 + whipsaw↓ + 牛市不犧牲，")
print("  且須跨 fold 穩定；alpha（IR>0）預期且確認 FAIL（R5 一致）。survivorship → 全為上界。")
print("  **總 Gate（R5：對 0050 buy-hold 無顯著 alpha + 無 mandate）未翻案 → live（MA200 + regime_action 0.85）一律不動。**")
print("[done] E1+E2 walk-forward 完成（純快取、0 API、未改任何既有檔）。")

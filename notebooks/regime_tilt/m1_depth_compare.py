"""
notebooks/regime_tilt/m1_depth_compare.py
  —  M1 regime de-risk「深度」比較研究（沙盒；純快取 0 API、不改任何 live/src/config 檔）。

【任務】讓使用者在「溫和 flat 深度（V1）」vs「分層深砸（V2，依回撤遞增）」之間，依
   ① 壓回撤效果（vs 0050 買持）② 反彈獲利犧牲（vs 0050 買持）做取捨。本研究跑在
   **0050 股票 sleeve + 現金** 上（M1 ＝ 把現行 live 的 regime de-risk「深度」當旋鈕掃）。

【共同設定】
  - 股票 sleeve ＝ 0050 還原日線（2018-01-01~2025-12-31；_lab loader 純快取 0 API）。
  - regime 訊號 ＝ **既有 E1+E2 MA200**（連 3 日 < MA200×0.99、±1% 帶）＝ 直接用 L.below_live
    （引擎 _regime_below，N=3+1%）。**不改訊號、不改時點**；本研究只動「跌破態砍多深」。
  - de-risk 下來的 (1−exposure) 部位 **賺現金 ~1.5%/年（日化複利）**＝ 台幣 MMF/活存代理。
  - 每變體建一條逐日曝險路徑 exp_full∈[0,1]（regime OFF＝base≈滿倉 1.0；regime ON＝砍深），
    用 sim 跑權益曲線。

【★ M0×M1 接縫（suspend-dip-buy）— 明確點出】
  本 sleeve-vs-cash 研究中，曝險完全由 regime 決定：**跌破態內曝險被壓低、且在態內不回補股票**
  （exposure 維持在砍後水位直到站回 MA200 確認）＝ 已**內含「下行時暫停買跌」的精神**：de-risk
  期間多出的現金留在現金、不逢低承接 0050。完整 6 資產帶寬系統的「M0 dip-buy 在 M1 de-risk 期間
  暫停」是日後（多 sleeve、帶寬再平衡）的事；本腳本只在單一 0050 sleeve 上驗證「深度」取捨，
  接縫處的 dip-buy 暫停以本研究的「態內不回補」近似表達。

【兩個深度變體】（regime ON 時才作用；OFF＝滿倉 base）
  V1 溫和 flat：regime ON → mult = a（常數）。細網格 a∈{0.975..0.70} 步長 0.025（12 點）。
                a=0.85 ＝ 現行 live（退化錨）。
  V2 分層深砸：regime ON → mult 依「**因果**距高點回撤」分層遞減（stress_drawdown(cf,252)，
                rolling-高點只用到當日為止＝無 look-ahead）。淺檔 0.90 / 中檔 0.80 / 深檔 = floor。
                細網格掃「最深檔位 floor」與「分層門檻 (t1,t2)」，特徵化曲面（避免孤峰/cherry-pick）。

【現金建模（wiring 先 0、再 1.5%）】
  sim_from_exp 把未曝險部位停在 cash 賺 0%。本檔 sim_cash() ＝ **逐字複製 _lab.sim_from_exp**
  ＋ 唯一一行「每日對 idle cash 計息（日化複利）」：
    - annual_cash=0.0 → **必逐位重現 _lab.sim**（assert max|Δ|=0）＝ wiring 證明。
    - annual_cash=0.015 → 報實際數字（de-risk 期間現金生息）。
  兩者都列。walk-forward 選參邏輯（Calmar 主、DD-floor 重錨 current-live−2.2pp、Sharpe tiebreak）
  與 _lab.walk_forward **完全一致**，僅把內部 sim 換成 sim_cash → correct-by-construction。

【自驗（寫進 stdout，供主控）】
  - 行為中性：degenerate（mult≡1.0、cash=0）逐位重現 sim(base)；又因 base≈1.0、sim(base) ≈ 0050
    買持（OOS Sharpe 0.942 vs 0.947、WDD −33.8% vs −34.0%，差＝月度再平衡摩擦，非 bug）。
    V1 a=0.85、cash=0 → **逐位重現 current-live**（≡ L.live_eq，max|Δ|=0；對齊 SL≈1.003/LIVE_WDD≈−30.5%）。
  - 無 look-ahead：MA200 與回撤皆 backward/因果；選參只用 in-sample 擴張窗；pooled OOS。
  - 細網格：V1 12 點步長 0.025；V2 floor/門檻各數點 → 判 plateau vs 孤峰（鐵則#7）。

【固定預先指定基準（不得事後挑）】① 0050 買持（S0/BH_WDD）；② current-live（E1+E2 flat 0.85，SL/LIVE_WDD）。

【紀律】鐵則#3 walk-forward OOS；#4 純快取 0 API；#7 細網格；#8 DD floor 重錨同族 current-live。
   survivorship（FinMind 無下市股）→ 所有 OOS 為上界。沙盒：不碰 src/config/main/live、不 commit。
"""
from __future__ import annotations
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exit_upgrade"))

import numpy as np
import pandas as pd

from _lab import (
    Lab, stress_drawdown, year_dr, sharpe_of, ann_of, dd_of_window,
    window_metrics, calmar, flips_in_year, FWD, DD_BAND,
)
import _lab as lab
bm = lab.bm

CASH_ANNUAL = 0.015                       # 現金 sleeve 年化（台幣 MMF/活存代理；日化複利）
DD_LOOKBACK = 252                         # 因果回撤 rolling 高點窗（1y）

L = Lab()

# 共同：base（vol-target，暖身 NaN，≈1.0）/ below（E1+E2 N=3+1% 跌破態）/ 因果回撤
base = L.base.reindex(L.cf.index)
below = L.below_live.reindex(L.cf.index).fillna(False)
ddh = stress_drawdown(L.cf, DD_LOOKBACK).reindex(L.cf.index)   # ≤0；距 rolling-252 高點回撤（因果）


# ════════════════════════════════════════════════════════════════════════════════════
# sim_cash ＝ 逐字複製 _lab.sim_from_exp ＋ idle cash 日化計息（annual_cash=0 → ≡ _lab.sim）
# ════════════════════════════════════════════════════════════════════════════════════
def sim_cash(adj: pd.DataFrame, exp_full: pd.Series, annual_cash: float = 0.0):
    """與 _lab.sim_from_exp 完全相同的成交/費稅/再平衡邏輯，唯一差異＝每個 bar 對「持有到下一個
    eq 標記點之間的 idle cash」計息（日化複利 daily=(1+annual)^(1/252)−1）。
    annual_cash=0.0 時 daily=0 → 計息項恆 0 → 逐位重現 _lab.sim_from_exp（assert 把關）。
    回傳 (eq Series, n_exec)。"""
    daily = (1.0 + annual_cash) ** (1.0 / 252.0) - 1.0
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
        # ── 計息：把前一日標記後到今日之間，idle cash 生息（i=0 無前段→不計）──────────────
        if i > 0 and daily != 0.0 and cash > 0.0:
            cash *= (1.0 + daily)
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


# ════════════════════════════════════════════════════════════════════════════════════
# 變體 exp_builders（合約：回 L.cf.index 上 Series＝base×mult；mult 預設 1.0 僅跌破態調整）
# ════════════════════════════════════════════════════════════════════════════════════
def build_v1(a: float) -> pd.Series:
    """V1 溫和 flat：跌破態 mult=a（常數），其餘 1.0。a=0.85 ≡ current-live。"""
    mult = pd.Series(1.0, index=L.cf.index)
    mult[below] = a
    return base * mult


def build_v2(floor: float, t1: float, t2: float) -> pd.Series:
    """V2 分層深砸（依**因果**距高點回撤遞增）：跌破態內依 ddh 分層 ——
        DD ∈ (−t1, 0]        → 0.90（淺；剛跌破、回撤淺）
        DD ∈ (−t2, −t1]      → 0.80（中）
        DD ≤ −t2             → floor（深；深回撤砍最重）
      非跌破態 → 1.0。回撤 ddh 為 rolling-252 高點（只用到當日，無 look-ahead）。
      退化：floor=0.90,t1 極大（永遠落淺檔 0.90）≠ live；本變體不設「≡live」退化點，wiring 改由
      sim_cash(annual=0) ≡ _lab.sim 與 V1 a=0.85 ≡ live 共同把關（V2 與 V1 共用同一 base×mult×sim 管線）。"""
    SHALLOW, MID = 0.90, 0.80
    dd = ddh.to_numpy(float)
    m = np.where(dd <= -t2, floor, np.where(dd <= -t1, MID, SHALLOW))   # 深→中→淺
    mult = pd.Series(1.0, index=L.cf.index)
    bmask = below.to_numpy(bool)
    mult_vals = mult.to_numpy(float).copy()
    mult_vals[bmask] = m[bmask]
    mult = pd.Series(mult_vals, index=L.cf.index)
    return base * mult


# ════════════════════════════════════════════════════════════════════════════════════
# 評估 helpers（cash-aware；選參邏輯逐字對齊 _lab.walk_forward）
# ════════════════════════════════════════════════════════════════════════════════════
def metrics_block(eq: pd.Series, exp: pd.Series, nx: int) -> dict:
    """變體在 OOS（2022-25 pooled 日報酬）+ 全期 + 多/空頭年的標準指標包。"""
    oos = pd.concat([year_dr(eq, Y) for Y in FWD])
    worst = min(dd_of_window(eq, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    # 全期 maxDD（2018-25）
    full = eq[(eq.index >= pd.Timestamp("2018-01-01")) & (eq.index <= pd.Timestamp("2025-12-31"))]
    maxdd_full = float((full / full.cummax() - 1).min())
    py = bm._per_year(eq)
    ret22 = py.get(2022, (float("nan"),) * 3)[0]
    dd22 = py.get(2022, (float("nan"),) * 3)[2]
    bull = sum(py.get(Y, (0.0,))[0] for Y in (2023, 2024, 2025))   # 多頭年報酬合計＝反彈代理
    fl22 = flips_in_year(exp, base, 2022)
    return dict(oos_sharpe=sharpe_of(oos), oos_ann=ann_of(oos), maxdd_full=maxdd_full,
                worst_fwd_dd=worst, ret22=ret22, dd22=dd22, bull=bull, n_exec=nx, fl22=fl22,
                ir0=L._ir(oos, L.bh_oos))


def walk_forward_cash(grid, exp_builder, annual_cash: float, objective="calmar"):
    """逐字對齊 _lab.walk_forward 的擴張窗選參（Calmar 主、DD-floor 重錨 current-live−DD_BAND、
    Sharpe tiebreak），但內部 sim 換成 sim_cash(annual_cash) → 報含現金生息的 OOS。
    selection 用的 EQ 與 live floor 都用同一現金率（一致比較）。"""
    EQ = {}
    for p in grid:
        e = exp_builder(*p) if isinstance(p, tuple) else exp_builder(p)
        eqp, nxp = sim_cash(L.adj, e, annual_cash)
        EQ[p] = (eqp, nxp, e)
    # current-live 在同一現金率下的曲線（floor 重錨用；annual_cash 一致）
    live_eq_c, _ = sim_cash(L.adj, L.live_exp, annual_cash)

    def select_param(train_end_year):
        start, end = "2018-01-01", f"{train_end_year}-12-31"
        live_dd = dd_of_window(live_eq_c, start, end)
        floor_thr = live_dd - DD_BAND
        mets = {}
        for p in grid:
            ann, sh, dd, cal = window_metrics(EQ[p][0], start, end)
            mets[p] = dict(p=p, ann=ann, sh=sh, dd=dd, cal=cal)
        passers = [m for m in mets.values() if m["dd"] >= floor_thr]
        pool = passers if passers else list(mets.values())
        key = (lambda m: (m["cal"], m["sh"])) if objective == "calmar" else (lambda m: (m["sh"], m["cal"]))
        best = max(pool, key=key)
        return best["p"], len(passers), floor_thr

    rows, strat_daily, ddby = [], [], {}
    for Y in FWD:
        p_star, npass, floor_thr = select_param(Y - 1)
        eqp, _, e = EQ[p_star]
        py = bm._per_year(eqp).get(Y, (float("nan"),) * 3)
        ddby[Y] = py[2]
        strat_daily.append(year_dr(eqp, Y))
        rows.append(dict(Y=Y, p=p_star, npass=npass, ret=py[0], sh=py[1], dd=py[2],
                         flips=flips_in_year(e, base, Y)))
    pooled = pd.concat(strat_daily)
    # 用「每 fold 選到的參數」重組整條 OOS 權益（接 fold 段）→ 取代表參數做指標
    sel_params = [r["p"] for r in rows]
    return dict(rows=rows, pooled=pooled, EQ=EQ, live_eq_c=live_eq_c,
                pooled_sharpe=sharpe_of(pooled), pooled_ann=ann_of(pooled),
                worst_fwd_dd=min(ddby.values()), sel_params=sel_params,
                ir0=L._ir(pooled, pd.concat([year_dr(L.bh_eq, Y) for Y in FWD])))


def fmt_v1(a):
    return f"{a:.3f}" + ("←live" if abs(a - 0.85) < 1e-9 else "")


def fmt_v2(p):
    return f"f{p[0]:.2f}/t1{p[1]:.2f}/t2{p[2]:.2f}"


# ════════════════════════════════════════════════════════════════════════════════════
# 細網格定義
# ════════════════════════════════════════════════════════════════════════════════════
# V1：a∈{0.975,0.95,...,0.70} 步長 0.025（12 點；含 0.85=live、0.70=規格最深）
GRID_V1 = [round(0.975 - 0.025 * k, 3) for k in range(12)]   # 0.975..0.700

# V2：掃「最深檔位 floor」× 「分層門檻 (t1,t2)」。
#   floor ∈ {0.85,0.80,0.75,0.70,0.65}（5 點；淺/中固定 0.90/0.80，floor 控深檔斜率）
#   門檻組 (t1,t2)：以回撤分界，數組（淺→中界 t1、中→深界 t2）：
GRID_V2_FLOOR = [0.85, 0.80, 0.75, 0.70, 0.65]
GRID_V2_THRESH = [(0.08, 0.16), (0.10, 0.20), (0.12, 0.24), (0.15, 0.25)]   # (t1,t2)


# ════════════════════════════════════════════════════════════════════════════════════
# 自驗（行為中性 / wiring）
# ════════════════════════════════════════════════════════════════════════════════════
def self_validation():
    print("=" * 110)
    print("[自驗 1：sim_cash(annual=0) ≡ _lab.sim_from_exp]（現金率 0 → 計息項恆 0 → 逐位重現）")
    for tag, e in [("base", base), ("live_exp", L.live_exp), ("V1 a=0.85", build_v1(0.85)),
                   ("V2 f0.70/t1.10/t2.20", build_v2(0.70, 0.10, 0.20))]:
        eqc, nxc = sim_cash(L.adj, e, 0.0)
        eql, nxl = L.sim(e)
        d = float((eqc - eql).abs().max())
        print(f"  {tag:<24} max|Δ權益|={d:.3e}  n_exec cash/lab={nxc}/{nxl}  → {'✓' if d < 1e-9 and nxc == nxl else '✗'}")

    print("-" * 110)
    print("[自驗 2：degenerate mult≡1.0（regime OFF、cash=0）≡ sim(base)；且 sim(base) ≈ 0050 買持]")
    eq_off, _ = sim_cash(L.adj, base, 0.0)            # mult≡1.0 ＝ base
    eq_simbase, _ = L.sim(base)
    d_off = float((eq_off - eq_simbase).abs().max())
    base_oos = pd.concat([year_dr(eq_simbase, Y) for Y in FWD])
    base_wdd = min(dd_of_window(eq_simbase, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    print(f"  degenerate(cash=0) vs sim(base) max|Δ|={d_off:.3e} → {'✓' if d_off < 1e-9 else '✗'}")
    print(f"  sim(base) OOS Sharpe={sharpe_of(base_oos):.4f} vs 0050買持 S0={L.S0:.4f}｜"
          f"worst-fwd-DD={base_wdd*100:.2f}% vs BH_WDD={L.BH_WDD*100:.2f}%")
    print(f"    （差異＝sim 月度再平衡 vs 買持 buy-once 的微摩擦，非 bug；故『exp≡1 逐位＝買持』在此 harness "
          f"不成立，真正恆等錨＝下面 V1 a=0.85≡live）")

    print("-" * 110)
    print("[自驗 3：V1 a=0.85、cash=0 ≡ current-live（引擎 live_exp 經 sim）＝additive 行為中性恆等錨]")
    eqv, nxv = sim_cash(L.adj, build_v1(0.85), 0.0)
    d_live = float((eqv - L.live_eq).abs().max())
    v_oos = pd.concat([year_dr(eqv, Y) for Y in FWD])
    v_wdd = min(dd_of_window(eqv, f"{Y}-01-01", f"{Y}-12-31") for Y in FWD)
    print(f"  V1 a=0.85(cash=0) vs L.live_eq max|Δ|={d_live:.3e} n_exec={nxv}（live={L._live_nx}）→ "
          f"{'✓' if d_live < 1e-9 else '✗'}")
    print(f"  → OOS Sharpe={sharpe_of(v_oos):.4f}（對齊 SL={L.SL:.4f}）｜worst-fwd-DD={v_wdd*100:.2f}%"
          f"（對齊 LIVE_WDD={L.LIVE_WDD*100:.2f}%）")
    print("=" * 110)


# ════════════════════════════════════════════════════════════════════════════════════
# 全格特徵化（描述性，非選參；plateau vs 孤峰；cash=1.5%）
# ════════════════════════════════════════════════════════════════════════════════════
def characterize():
    print("\n" + "=" * 110)
    print(f"全格特徵化（cash={CASH_ANNUAL*100:.1f}%；描述性、非選參）：2018-25 全期 + OOS pooled 指標（鐵則#7 判平滑 vs 鋸齒）")

    print("-" * 110)
    print("V1 溫和 flat（mult=a 常數；a=0.85=live）｜a↓＝砍越深")
    print(f"{'a':>8}{'OOSshrp':>9}{'OOS年化':>9}{'全期DD':>9}{'最差年DD':>10}{'22報酬':>9}{'22DD':>9}{'反彈':>9}{'交易':>6}{'22flip':>7}")
    v1_chars = {}
    for a in GRID_V1:
        e = build_v1(a)
        eq, nx = sim_cash(L.adj, e, CASH_ANNUAL)
        m = metrics_block(eq, e, nx)
        v1_chars[a] = m
        tag = fmt_v1(a)
        print(f"{tag:>8}{m['oos_sharpe']:>9.3f}{m['oos_ann']*100:>8.1f}%{m['maxdd_full']*100:>8.1f}%"
              f"{m['worst_fwd_dd']*100:>9.1f}%{m['ret22']*100:>8.1f}%{m['dd22']*100:>8.1f}%"
              f"{m['bull']*100:>8.1f}%{m['n_exec']:>6}{m['fl22']:>7}")

    print("-" * 110)
    print("V2 分層深砸（淺0.90/中0.80/深=floor；依因果回撤分層）｜掃 floor × (t1,t2)")
    print(f"{'floor/t1/t2':>18}{'OOSshrp':>9}{'OOS年化':>9}{'全期DD':>9}{'最差年DD':>10}{'22報酬':>9}{'22DD':>9}{'反彈':>9}{'交易':>6}")
    v2_chars = {}
    for fl in GRID_V2_FLOOR:
        for (t1, t2) in GRID_V2_THRESH:
            p = (fl, t1, t2)
            e = build_v2(*p)
            eq, nx = sim_cash(L.adj, e, CASH_ANNUAL)
            m = metrics_block(eq, e, nx)
            v2_chars[p] = m
            print(f"{fmt_v2(p):>18}{m['oos_sharpe']:>9.3f}{m['oos_ann']*100:>8.1f}%{m['maxdd_full']*100:>8.1f}%"
                  f"{m['worst_fwd_dd']*100:>9.1f}%{m['ret22']*100:>8.1f}%{m['dd22']*100:>8.1f}%"
                  f"{m['bull']*100:>8.1f}%{m['n_exec']:>6}")
    return v1_chars, v2_chars


# ════════════════════════════════════════════════════════════════════════════════════
# walk-forward 選參（cash=0 wiring + cash=1.5% 實際）→ 代表參數 → 取捨對照表
# ════════════════════════════════════════════════════════════════════════════════════
def represent(name, grid, builder, fmt, annual_cash):
    """跑 cash-aware walk-forward，回 (wf, 代表參數的完整 metrics_block)。代表參數＝walk-forward
    各 fold 選參的眾數（最常被選到的 p）＝ deployable 單一參數。"""
    wf = walk_forward_cash(grid, builder, annual_cash, objective="calmar")
    from collections import Counter
    rep = Counter(wf["sel_params"]).most_common(1)[0][0]
    e = builder(*rep) if isinstance(rep, tuple) else builder(rep)
    eq, nx = sim_cash(L.adj, e, annual_cash)
    m = metrics_block(eq, e, nx)
    return wf, rep, m, eq


def print_wf(name, wf, fmt):
    ps = "  ".join(f"{r['Y']}:{fmt(r['p'])}" for r in wf["rows"])
    print(f"[{name}] walk-forward 選參（擴張窗 [2018,Y-1]→Y；Calmar 主·DD-floor 重錨 current-live−{DD_BAND*100:.1f}pp·Sharpe tiebreak）")
    print(f"  逐 fold：{ps}")
    print(f"  pooled OOS Sharpe={wf['pooled_sharpe']:.3f}  OOS年化={wf['pooled_ann']*100:.1f}%  "
          f"最差前進年DD={wf['worst_fwd_dd']*100:.1f}%  IRvs0050={wf['ir0']:+.3f}")


if __name__ == "__main__":
    self_validation()
    v1_chars, v2_chars = characterize()

    # ── 基準（cash=1.5%；0050 買持本身無 de-risk→現金=0，故買持/live 都用各自既有口徑）──────
    # 0050 買持：滿倉、無現金 sleeve → 直接用 L.bh_eq（cash 概念不適用，曝險恆≈1）
    bh_oos = pd.concat([year_dr(L.bh_eq, Y) for Y in FWD])
    bh_block = dict(oos_sharpe=L.S0, oos_ann=ann_of(bh_oos),
                    maxdd_full=float((L.bh_eq[(L.bh_eq.index >= '2018-01-01')] /
                                      L.bh_eq[(L.bh_eq.index >= '2018-01-01')].cummax() - 1).min()),
                    worst_fwd_dd=L.BH_WDD,
                    ret22=bm._per_year(L.bh_eq).get(2022, (float('nan'),) * 3)[0],
                    dd22=bm._per_year(L.bh_eq).get(2022, (float('nan'),) * 3)[2],
                    bull=sum(bm._per_year(L.bh_eq).get(Y, (0.0,))[0] for Y in (2023, 2024, 2025)),
                    n_exec=1, fl22=0)
    # current-live（E1+E2 flat 0.85）：de-risk 期間現金生息 → 用 cash=1.5% 重算（與變體同口徑公平比）
    live_eq_c, live_nx_c = sim_cash(L.adj, L.live_exp, CASH_ANNUAL)
    live_block = metrics_block(live_eq_c, L.live_exp, live_nx_c)

    # ── 代表參數（cash=1.5% 實際；另列 cash=0 確認選參不因現金率漂移）──────────────────────
    print("\n" + "=" * 110)
    print(f"walk-forward 選參（cash={CASH_ANNUAL*100:.1f}% 實際）")
    wf1, rep1, m1, eq1 = represent("V1 mild", GRID_V1, build_v1, fmt_v1, CASH_ANNUAL)
    print_wf("V1 溫和 flat", wf1, fmt_v1)
    wf2, rep2, m2, eq2 = represent("V2 graduated", [(fl, t1, t2) for fl in GRID_V2_FLOOR for (t1, t2) in GRID_V2_THRESH],
                                   build_v2, fmt_v2, CASH_ANNUAL)
    print_wf("V2 分層深砸", wf2, fmt_v2)

    print("-" * 110)
    print(f"[選參穩定度交叉檢（cash=0 vs cash={CASH_ANNUAL*100:.1f}%）]")
    wf1_0, rep1_0, _, _ = represent("V1", GRID_V1, build_v1, fmt_v1, 0.0)
    wf2_0, rep2_0, _, _ = represent("V2", [(fl, t1, t2) for fl in GRID_V2_FLOOR for (t1, t2) in GRID_V2_THRESH],
                                    build_v2, fmt_v2, 0.0)
    print(f"  V1 逐fold(cash0)={[fmt_v1(r['p']) for r in wf1_0['rows']]}  代表={fmt_v1(rep1_0)}  ｜ "
          f"(cash1.5%)代表={fmt_v1(rep1)}")
    print(f"  V2 逐fold(cash0)={[fmt_v2(r['p']) for r in wf2_0['rows']]}  代表={fmt_v2(rep2_0)}  ｜ "
          f"(cash1.5%)代表={fmt_v2(rep2)}")

    # ════════════════════════════════════════════════════════════════════════════════
    # ★ 核心交付：取捨對照表（mild-best vs graduated-best；各取 walk-forward 代表參數）
    # ════════════════════════════════════════════════════════════════════════════════
    print("\n" + "#" * 110)
    print(f"★ 核心取捨對照表（cash={CASH_ANNUAL*100:.1f}%；mild-best vs graduated-best；代表參數＝walk-forward 選參眾數）")
    print("#" * 110)
    hdr = f"{'變體':<26}{'OOSshrp':>9}{'OOS年化':>9}{'maxDD':>9}{'最差年DD':>10}{'22報酬':>9}{'反彈(多頭和)':>12}{'交易':>6}"
    print(hdr)
    print("-" * 110)

    def row(label, m):
        print(f"{label:<26}{m['oos_sharpe']:>9.3f}{m['oos_ann']*100:>8.1f}%{m['maxdd_full']*100:>8.1f}%"
              f"{m['worst_fwd_dd']*100:>9.1f}%{m['ret22']*100:>8.1f}%{m['bull']*100:>11.1f}%{m['n_exec']:>6}")

    row("0050 買持（基準①）", bh_block)
    row("current-live 0.85（基準②）", live_block)
    row(f"V1 mild  a={fmt_v1(rep1)}", m1)
    row(f"V2 grad  {fmt_v2(rep2)}", m2)
    print("-" * 110)

    # ── 每變體一句「DD 買到 / 反彈犧牲」（皆 vs 0050 買持）────────────────────────────────
    def tradeoff_line(label, m):
        dd_buy = (m["worst_fwd_dd"] - bh_block["worst_fwd_dd"]) * 100      # 正＝最差年 DD 比買持淺幾 pp
        dd_buy_full = (m["maxdd_full"] - bh_block["maxdd_full"]) * 100     # 正＝全期 maxDD 淺幾 pp
        bull_sac = (bh_block["bull"] - m["bull"]) * 100                    # 正＝多頭年報酬比買持少幾 pp
        r22 = (m["ret22"] - bh_block["ret22"]) * 100                      # 2022 報酬 vs 買持
        print(f"  {label}：壓回撤＝最差年 DD 比 0050 買持淺 {dd_buy:+.1f}pp（全期 maxDD {dd_buy_full:+.1f}pp、"
              f"2022 報酬 {r22:+.1f}pp）｜犧牲反彈＝多頭年(23/24/25)報酬比 0050 買持少 {bull_sac:+.1f}pp")

    print("每變體取捨（全部對照 0050 買持）：")
    tradeoff_line(f"V1 mild a={fmt_v1(rep1)}", m1)
    tradeoff_line(f"V2 grad {fmt_v2(rep2)}", m2)
    tradeoff_line("（參考）current-live 0.85", live_block)
    print("#" * 110)

    # ── caveats ──
    print("\n誠實 caveats：")
    print("  • 0050-only：真實 live 還含主動 sleeve（β≈1.2 代理）→ DD 與反彈皆放大 ~1.2×，但取捨『比例』近似不變。")
    print("  • 黃金/債 sleeve 未快取（本機僅 0050）→ 本研究排除，無法評估多 sleeve 帶寬互動。")
    print("  • survivorship（FinMind 無下市股）→ 所有 OOS 為上界。")
    print(f"  • 現金 {CASH_ANNUAL*100:.1f}%/年為假設（台幣 MMF/活存代理）；de-risk 越深、現金占比越高，此假設影響越大。")
    print("  • M0×M1 接縫：de-risk 態內不回補股票＝已內含『下行暫停買跌』；完整 6 資產 dip-buy 暫停為日後工作。")

"""
notebooks/dca_compare.py
三方回測：定期定額(DCA) vs 本策略(0050 + 跌破 MA200 出 15%) vs 0050 買進持有。
2018-2025、初始 10 萬、含台股費稅、T+1 開盤成交。純快取、0 API（複用 benchmark_backtest 的還原載入）。

目的：量化「本策略 vs 定期定額」差別到底是多少。三條曲線同起點 10 萬 → 指標完全可比。
本策略 live 口徑 = base 100%(target_vol=1.0) + 跌破 MA200 留 85%(regime_action=0.85)。

⚠️ 描述性、非證實超額：R5 已定無顯著 alpha；0050 無 survivorship 但單一市場/單期 power 有限。
用法：.venv/bin/python notebooks/dca_compare.py
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

# 複用 benchmark_backtest.py（快取載入 + 統計 + 買持 + 波動目標再平衡）
_spec = importlib.util.spec_from_file_location("bm", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

SQRT252 = np.sqrt(252)
FWD = [2022, 2023, 2024, 2025]   # R5 OOS 窗


# ── 定期定額（每月固定投入、只買不賣）─────────────────────────────────────────────
def simulate_dca(adj: pd.DataFrame) -> dict:
    """起始 10 萬現金，每月第一個交易日把『10萬 / 總月數』投入 0050（T+1 開盤+滑價、含買費、
    受現金約束），永不賣。equity = 閒置現金 + 持倉市值。
    回 stats（含 invested 實際投入、cashflows 供 IRR）。"""
    df = adj[(adj["date"] >= pd.Timestamp(bm.START)) & (adj["date"] <= pd.Timestamp(bm.END))].reset_index(drop=True)
    dates = pd.DatetimeIndex(df["date"])
    close = df["close"].to_numpy(float)
    opn = df["open"].to_numpy(float)
    month_first = bm.is_month_first_trading_day(dates).to_numpy(bool)
    n = len(df)
    n_months = int(month_first.sum())
    contribution = bm.INITIAL / n_months   # 把 10 萬平均分到每個月投入

    cash, qty = bm.INITIAL, 0
    eq = np.empty(n)
    cashflows = []        # (投入日, 投入額)；供 money-weighted IRR
    invested = 0.0
    for i in range(n):
        eq[i] = cash + qty * close[i] * bm.LOT
        if i + 1 >= n:
            continue
        if not month_first[i]:
            continue
        budget = min(contribution, cash)
        if budget <= 0:
            continue
        fill_buy = opn[i + 1] * (1 + bm.SLIP)
        if fill_buy <= 0:
            continue
        buyable = int(budget / (fill_buy * bm.LOT))
        while buyable >= 1:                     # 受現金約束（含買費）
            amt = fill_buy * buyable * bm.LOT
            if amt + bm._buyfee(amt) <= cash:
                break
            buyable -= 1
        if buyable < 1:
            continue
        amt = fill_buy * buyable * bm.LOT
        spent = amt + bm._buyfee(amt)
        cash -= spent
        qty += buyable
        invested += spent
        cashflows.append((dates[i + 1], spent))

    eq_s = pd.Series(eq, index=dates)
    st = bm._stats(eq_s, [], "定期定額 0050(每月)")
    st["invested"] = invested
    st["cashflows"] = cashflows
    st["terminal_pos"] = float(qty * close[-1] * bm.LOT)   # 期末純持倉市值（salary-DCA 用）
    st["terminal_date"] = dates[-1]
    st["n_months"] = n_months
    st["contribution"] = contribution
    return st


def xirr(cashflows, terminal_date, terminal_value) -> float:
    """money-weighted 年化報酬（投入為負現金流、期末持倉為正）。簡易 bisection 解 NPV=0。"""
    flows = [(d, -float(amt)) for (d, amt) in cashflows]   # 投入＝流出（負）
    flows.append((terminal_date, float(terminal_value)))   # 期末＝流入（正）
    t0 = flows[0][0]
    times = np.array([(pd.Timestamp(d) - pd.Timestamp(t0)).days / 365.25 for (d, _) in flows])
    amts = np.array([a for (_, a) in flows])

    def npv(r):
        return float(np.sum(amts / (1.0 + r) ** times))

    lo, hi = -0.9999, 10.0
    for _ in range(200):                # npv 對 r 單調遞減 → bisection
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-4:
            return mid
        if fm > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ── 區間統計（年化 / Sharpe / maxDD / Calmar）────────────────────────────────────
def agg(eq: pd.Series, oos: bool = False):
    e = eq[eq.index.year.isin(FWD)] if oos else eq
    r = e.pct_change().dropna()
    sh = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    ann = float((e.iloc[-1] / e.iloc[0]) ** (252 / len(e)) - 1) if len(e) > 0 and e.iloc[0] > 0 else 0.0
    dd = float((e / e.cummax() - 1).min())
    cal = (ann / abs(dd)) if abs(dd) > 1e-9 else float("nan")
    return ann, sh, dd, cal


# ── 主流程 ──────────────────────────────────────────────────────────────────────
def main():
    print("三方回測：DCA vs 本策略 vs 0050買持 | 載入快取 0050（0 API）…")
    adj = bm.load_adjusted_0050()
    print(f"0050 還原日線（快取）：{len(adj)} 列，{adj['date'].min().date()} ~ {adj['date'].max().date()}")
    print(f"回測窗 {bm.START} ~ {bm.END}｜初始 {bm.INITIAL:,.0f}｜零股滑價 {bm.SLIP}｜含買賣費0.1425%+賣稅0.3%\n")

    bh = bm.simulate_buyhold(adj)
    strat = bm.simulate_benchmark(adj, 1.0, overlay=True, regime_ma=200, regime_action=0.85)
    strat["label"] = "本策略(0050+跌破MA200出15%)"
    dca = simulate_dca(adj)

    rows = [
        ("0050 買進持有", bh),
        (strat["label"], strat),
        ("定期定額(把10萬分月投入)", dca),
    ]

    # ── 主表（全期 2018-2025，同起點 10 萬，完全可比）──
    print("=" * 92)
    print("主比較表｜全期 2018-2025｜同起點 10 萬、同費稅（指標完全可比）")
    print("-" * 92)
    print(f"{'策略':<30}{'最終淨值':>12}{'總報酬':>9}{'年化':>8}{'Sharpe':>8}{'最大回撤':>10}{'Calmar':>8}")
    print("-" * 92)
    for label, s in rows:
        eq = s["equity"]
        ann, sh, dd, cal = agg(eq)
        tot = float(eq.iloc[-1] / eq.iloc[0] - 1)
        print(f"{label:<30}{eq.iloc[-1]:>12,.0f}{tot*100:>8.0f}%{ann*100:>7.1f}%{sh:>8.2f}{dd*100:>9.1f}%{cal:>8.2f}")
    print("=" * 92)

    # ── OOS 2022-2025（含 2022 大跌，三者差最大）──
    print("\nOOS 2022-2025（含 2022 熊市）：年化 / Sharpe / 最大回撤 / Calmar")
    print("-" * 72)
    for label, s in rows:
        ann, sh, dd, cal = agg(s["equity"], oos=True)
        print(f"{label:<30}{ann*100:>8.1f}%{sh:>8.2f}{dd*100:>9.1f}%{cal:>8.2f}")
    print("-" * 72)

    # ── DCA 兩種讀法 ──
    irr = xirr(dca["cashflows"], dca["terminal_date"], dca["terminal_pos"])
    dca_ann_budget = agg(dca["equity"])[0]
    print("\n定期定額的兩種讀法（同一條投入軌跡，視角不同）：")
    print(f"  ① 可比版(budget)：你『現在就有 10 萬』分 {dca['n_months']} 月投入、未投入閒置(0利息)")
    print(f"       → 上表年化 {dca_ann_budget*100:.1f}%（牛市現金拖累、但早期回撤小）")
    print(f"  ② 寫實版(salary)：每月薪水投入、無閒置現金 → money-weighted IRR ≈ {irr*100:.1f}%/年")
    print(f"       （實際投入 {dca['invested']:,.0f}、期末持倉 {dca['terminal_pos']:,.0f}；此才是『每月定額』的真實報酬率）")

    # ── 分年表（報酬% / Sharpe / 年內 maxDD）──
    print("\n" + "=" * 92)
    print("分年（每格＝報酬% / Sharpe / 年內最大回撤%）")
    print("=" * 92)
    PY = {label: bm._per_year(s["equity"]) for label, s in rows}
    print(f"{'年':>5}{'0050買持':>24}{'本策略(出15%)':>24}{'定期定額':>24}")

    def cell(t):
        return f"{t[0]*100:>6.1f}%/{t[1]:>5.2f}/{t[2]*100:>6.1f}%" if t else f"{'—':>20}"

    for y in range(2018, 2026):
        c0 = cell(PY["0050 買進持有"].get(y))
        c1 = cell(PY[strat["label"]].get(y))
        c2 = cell(PY["定期定額(把10萬分月投入)"].get(y))
        print(f"{y:>5}{c0:>24}{c1:>24}{c2:>24}")

    # ── 解讀 ──
    print("\n" + "=" * 92)
    print("解讀：")
    print("  • 0050 買進持有＝全程吃 beta，牛市報酬最高、但回撤最深（2022 全砸）。")
    print("  • 本策略＝平時 100% 跟 0050，唯跌破 MA200 減碼 15%→留現金；換到較淺回撤，代價是 whipsaw + 牛市偶爾少賺。")
    print("  • 定期定額＝危機時『加碼買便宜』(與本策略減碼方向相反)；可比版受閒置現金拖累、寫實版(IRR)接近 time-in-market。")
    print("  ⚠️ 描述性、非證實超額：R5 已定無顯著 alpha；單一市場/單期 power 有限；0050 無 survivorship。")
    print("\n[done] 三方回測完成（純快取、0 API、未動 live）。")


if __name__ == "__main__":
    main()

"""
notebooks/ai_window_analysis.py
AI 窗(2023-25) + 100k + 新選單35：兩抉擇分析。
抉擇1 交易單位：odd_lot / round_lot / hybrid → 獲利對照 + 滑價壓力(×2/×3)測止損成本敏感度。
抉擇2 選股策略適切性：vs 0050 買進持有、進場族群/損益分布、mp 5/6/7、size_max 0.40 變體。
純分析，不動 config。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from src.backtest.capped_sim import build_signals, run_capped, DEFAULT_UNIVERSE, AI_CANDIDATES, LIVE_UNIVERSE
from src.utils.sectors import get_sector
from src.data.fetcher import FinMindFetcher

CAP = 100_000
W_AI = ("2023-01-01", "2025-12-31")
W_2425 = ("2024-01-01", "2025-12-31")


def row(tag, r):
    print(f"{tag:<18}{r['annual']*100:>7.1f}%{r['sharpe']:>7.2f}{r['dd']*100:>8.1f}%{r['pf']:>7.2f}"
          f"{r['win_rate']*100:>5.0f}%{r['n_trades']:>5}{r['avg_concurrent']:>6.1f}{'PASS' if r['gate_pass'] else 'fail':>6}")


def main():
    price_df, sig = build_signals(DEFAULT_UNIVERSE + AI_CANDIDATES, "2018-01-01", "2025-12-31")
    hdr = f"{'變體':<18}{'年化':>8}{'Sharpe':>7}{'MaxDD':>9}{'PF':>7}{'勝率':>6}{'交易':>5}{'並倉':>6}{'Gate':>6}"

    # ── 抉擇1：交易單位 ──
    for wname, (s, e) in [("AI窗23-25", W_AI), ("近兩年24-25", W_2425)]:
        print(f"\n=== 抉擇1 交易單位（{wname}, 35檔, 100k, mp5）===\n{hdr}")
        for m in ["odd_lot", "round_lot", "hybrid"]:
            r = run_capped(price_df, sig, LIVE_UNIVERSE, s, e, capital=CAP, max_pos=5, mode=m)
            row(m, r)
        # round_lot 可成交標的診斷
        r = run_capped(price_df, sig, LIVE_UNIVERSE, s, e, capital=CAP, max_pos=5, mode="round_lot")
        ec = sorted(r["entry_counts"].items(), key=lambda x: -x[1])
        print(f"  round_lot 實際成交標的：{'、'.join(f'{k}×{v}' for k, v in ec) or '無'}")

    print(f"\n=== 抉擇1b 零股滑價壓力（急跌簿薄情境，AI窗）===\n{hdr}")
    for sc in [1.0, 2.0, 3.0]:
        r = run_capped(price_df, sig, LIVE_UNIVERSE, *W_AI, capital=CAP, max_pos=5, mode="odd_lot", slip_scale=sc)
        row(f"odd_lot 滑價×{sc:.0f}", r)

    # ── 抉擇2：選股策略適切性 ──
    f = FinMindFetcher()
    px = f.get_daily_price("0050", W_AI[0], W_AI[1], adjust=True)
    p0 = px.set_index("date")["adj_close"].astype(float)
    r0 = p0.pct_change().dropna()
    yrs = len(p0) / 252
    print(f"\n=== 抉擇2 基準：0050 買進持有（23-25）===")
    print(f"  總報酬 {p0.iloc[-1]/p0.iloc[0]-1:+.1%} / CAGR {(p0.iloc[-1]/p0.iloc[0])**(1/yrs)-1:.1%}"
          f" / Sharpe {r0.mean()/r0.std()*np.sqrt(252):.2f} / MaxDD {(p0/p0.cummax()-1).min():.1%}")

    base = run_capped(price_df, sig, LIVE_UNIVERSE, *W_AI, capital=CAP, max_pos=5, mode="odd_lot")
    print(f"\n策略(35檔) AI窗：總報酬 {base['total_return']:+.1%} / 年化 {base['annual']:.1%}"
          f" / Sharpe {base['sharpe']:.2f} / DD {base['dd']:.1%}")

    bys_n, bys_p = {}, {}
    for sid, c in base["entry_counts"].items():
        sec = get_sector(sid)
        bys_n[sec] = bys_n.get(sec, 0) + c
        bys_p[sec] = bys_p.get(sec, 0.0) + base["pnl_by_stock"].get(sid, 0.0)
    tot = sum(bys_n.values())
    print(f"\n進場族群分布與損益（AI窗，共 {tot} 次進場）：")
    for sec in sorted(bys_n, key=lambda k: -bys_p[k]):
        print(f"  {sec:<10}{bys_n[sec]:>3} 次({bys_n[sec]/tot*100:>3.0f}%)  {bys_p[sec]:>+10,.0f} 元")
    top = sorted(base["pnl_by_stock"].items(), key=lambda x: -x[1])
    print("  個股損益 Top5：" + "｜".join(f"{k}{v:+,.0f}" for k, v in top[:5]))
    print("  個股損益 Bot5：" + "｜".join(f"{k}{v:+,.0f}" for k, v in top[-5:]))

    print(f"\n=== 抉擇2b 結構變體（AI窗）===\n{hdr}")
    for mp in [5, 6, 7]:
        r = run_capped(price_df, sig, LIVE_UNIVERSE, *W_AI, capital=CAP, max_pos=mp, mode="odd_lot")
        row(f"mp={mp}", r)
    r = run_capped(price_df, sig, LIVE_UNIVERSE, *W_AI, capital=CAP, max_pos=5, mode="odd_lot", size_max=0.40)
    row("mp=5 size_max.40", r)
    r = run_capped(price_df, sig, LIVE_UNIVERSE, *W_AI, capital=CAP, max_pos=6, mode="odd_lot", size_max=0.40)
    row("mp=6 size_max.40", r)


if __name__ == "__main__":
    main()

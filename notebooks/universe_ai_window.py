"""
notebooks/universe_ai_window.py
分窗驗證：38 vs +8精選 vs +4制勝（B變體中 per-stock 損益最高的奇鋐/群聯/京元電/勤誠），
windows = 全期 2018-25 / AI 時代 2023-25 / 近兩年 2024-25。100k mp=5 零股。
決策規則（事先聲明）：採用「最小新增集」需同時 (i) 全期不破 Gate（Sharpe≥1.0 且 DD≥-15%）
(ii) AI 窗(2023-25) 年化與 Sharpe 皆 ≥ 38 基準。否則維持 38，AI 股僅留 GUI。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest.capped_sim import build_signals, run_capped, DEFAULT_UNIVERSE, AI_CANDIDATES

PICK8 = ["2449", "8299", "2408", "2383", "3017", "2368", "2345", "3037"]
PICK4 = ["3017", "8299", "2449", "8210"]   # 奇鋐/群聯/京元電/勤誠
VARIANTS = {"A 38現行": DEFAULT_UNIVERSE,
            "C 38+8精選": DEFAULT_UNIVERSE + PICK8,
            "E 38+4制勝": DEFAULT_UNIVERSE + PICK4}
WINDOWS = [("全期18-25", "2018-01-01", "2025-12-31"),
           ("AI窗23-25", "2023-01-01", "2025-12-31"),
           ("近兩年24-25", "2024-01-01", "2025-12-31")]


def main():
    price_df, sig = build_signals(DEFAULT_UNIVERSE + AI_CANDIDATES, "2018-01-01", "2025-12-31")
    for wname, s, e in WINDOWS:
        print(f"\n=== {wname} ===")
        print(f"{'變體':<14}{'年化':>8}{'Sharpe':>8}{'MaxDD':>8}{'PF':>7}{'勝率':>6}{'交易':>5}{'Gate':>6}")
        for vname, uni in VARIANTS.items():
            r = run_capped(price_df, sig, uni, s, e, capital=100_000, max_pos=5, mode="odd_lot")
            print(f"{vname:<14}{r['annual']*100:>7.1f}%{r['sharpe']:>8.2f}{r['dd']*100:>7.1f}%"
                  f"{r['pf']:>7.2f}{r['win_rate']*100:>5.0f}%{r['n_trades']:>5}{'PASS' if r['gate_pass'] else 'fail':>6}")
        # E 變體在此窗的新增股貢獻
        r = run_capped(price_df, sig, VARIANTS["E 38+4制勝"], s, e, capital=100_000, max_pos=5, mode="odd_lot")
        pnl = r["pnl_by_stock"]
        cnt = r["entry_counts"]
        line = "｜".join(f"{x}:{cnt.get(x,0)}次{pnl.get(x,0.0):+,.0f}" for x in PICK4)
        print(f"  E新增4檔貢獻：{line}")


if __name__ == "__main__":
    main()

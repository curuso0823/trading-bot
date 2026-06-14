"""
notebooks/universe_trim_check.py
任務3 驗證：新 live 選單 F(35=38−7拖後腿+4 AI) vs 舊基準 A(38) vs 上一版 E(42)，三窗對照。
除名是前瞻性決策（非回測擇優）——此處只記錄歷史代價/收益，供誠實留檔。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest.capped_sim import (build_signals, run_capped, DEFAULT_UNIVERSE,
                                     AI_CANDIDATES, AI_ADOPTED, LIVE_UNIVERSE)

VARIANTS = {"A 舊基準38": DEFAULT_UNIVERSE,
            "E 42(38+4)": DEFAULT_UNIVERSE + AI_ADOPTED,
            "F 新選單35": LIVE_UNIVERSE}
WINDOWS = [("全期18-25", "2018-01-01", "2025-12-31"),
           ("AI窗23-25", "2023-01-01", "2025-12-31"),
           ("近兩年24-25", "2024-01-01", "2025-12-31")]


def main():
    print(f"LIVE_UNIVERSE = {len(LIVE_UNIVERSE)} 檔")
    price_df, sig = build_signals(DEFAULT_UNIVERSE + AI_CANDIDATES, "2018-01-01", "2025-12-31")
    for wname, s, e in WINDOWS:
        print(f"\n=== {wname} ===")
        print(f"{'變體':<12}{'年化':>8}{'Sharpe':>8}{'MaxDD':>8}{'PF':>7}{'勝率':>6}{'交易':>5}{'Gate':>6}")
        for vname, uni in VARIANTS.items():
            r = run_capped(price_df, sig, uni, s, e, capital=100_000, max_pos=5, mode="odd_lot")
            print(f"{vname:<12}{r['annual']*100:>7.1f}%{r['sharpe']:>8.2f}{r['dd']*100:>7.1f}%"
                  f"{r['pf']:>7.2f}{r['win_rate']*100:>5.0f}%{r['n_trades']:>5}{'PASS' if r['gate_pass'] else 'fail':>6}")


if __name__ == "__main__":
    main()

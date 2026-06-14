"""被除名 7 檔在『舊基準38、AI窗23-25』策略中的實際貢獻（burst 交易 vs 買進持有弱勢的分歧檢查）。"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest.capped_sim import build_signals, run_capped, DEFAULT_UNIVERSE, AI_CANDIDATES, REMOVED_LAGGARDS

N = {"3008": "大立光", "2379": "瑞昱", "6415": "矽力", "3034": "聯詠", "2353": "宏碁", "4938": "和碩", "2376": "技嘉"}

price_df, sig = build_signals(DEFAULT_UNIVERSE + AI_CANDIDATES, "2018-01-01", "2025-12-31")
for wname, s, e in [("AI窗23-25", "2023-01-01", "2025-12-31"), ("全期18-25", "2018-01-01", "2025-12-31")]:
    r = run_capped(price_df, sig, DEFAULT_UNIVERSE, s, e, capital=100_000, max_pos=5, mode="odd_lot")
    tot = sum(r["pnl_by_stock"].get(x, 0.0) for x in REMOVED_LAGGARDS)
    print(f"\n{wname}（舊基準38）：7 檔被除名股 進場/損益")
    for x in REMOVED_LAGGARDS:
        print(f"  {x} {N[x]:<4} {r['entry_counts'].get(x,0):>2} 次 {r['pnl_by_stock'].get(x,0.0):>+10,.0f}")
    print(f"  合計 {tot:+,.0f}（窗內總交易 {r['n_trades']} 筆）")

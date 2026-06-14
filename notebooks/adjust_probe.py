"""還原價探針：0050/2330 原始 close vs adj_close 在關鍵日期的對照，定位掃描數字異常來源。"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.data.fetcher import FinMindFetcher

f = FinMindFetcher()
for sid in ["0050", "2330", "2383"]:
    raw = f.get_daily_price(sid, "2022-11-01", "2026-06-10", adjust=False)
    adj = f.get_daily_price(sid, "2022-11-01", "2026-06-10", adjust=True)
    print(f"\n=== {sid} ===  rows={len(raw)}")
    for d in ["2023-06-12", "2024-06-10", "2025-06-10", "2025-12-30"]:
        r = raw[raw["date"] == d]
        a = adj[adj["date"] == d]
        if not r.empty:
            print(f"  {d}: raw close={float(r['close'].iloc[0]):>9.2f}   adj={float(a['adj_close'].iloc[0]):>9.2f}")
    print(f"  最新 {raw['date'].iloc[-1].date()}: raw={float(raw['close'].iloc[-1]):>9.2f}   adj={float(adj['adj_close'].iloc[-1]):>9.2f}")
    div = f.get_dividend_result(sid, "2022-11-01", "2026-06-10")
    if div is not None and not div.empty:
        cols = [c for c in ["date", "before_price", "after_price", "stock_and_cache_dividend"] if c in div.columns]
        print(f"  除權息事件 {len(div)} 筆：")
        print(div[cols].to_string(index=False) if cols else div.head().to_string(index=False))

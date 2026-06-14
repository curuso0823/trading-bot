"""
notebooks/p0_validate.py
Phase 0 資料驗證：確認 FinMind 抓得到乾淨、對齊的資料。
用法（在專案根目錄）：  .venv\\Scripts\\python.exe notebooks\\p0_validate.py [stock_id]
"""
import os
import sys
# 讓腳本不論從哪執行都能 import src（把專案根目錄放上 sys.path）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from src.data.fetcher import FinMindFetcher

STOCK = sys.argv[1] if len(sys.argv) > 1 else "2330"
START = "2023-01-01"

pd.set_option("display.width", 160)
pd.set_option("display.max_columns", 30)


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    return cond


def main():
    f = FinMindFetcher()
    all_ok = True

    # ---------- 1. 還原日K ----------
    print(f"\n=== 1. 還原日K（{STOCK}, from {START}）===")
    px = f.get_daily_price(STOCK, START)
    if px.empty:
        print("  [FAIL] 日K 為空 — token 無效或 API 額度用盡？")
        sys.exit(1)
    cols = {"date", "open", "high", "low", "close", "volume", "adj_close"}
    all_ok &= check(f"欄位齊全 {sorted(cols)}", cols.issubset(px.columns))
    all_ok &= check("date 嚴格遞增（已排序）", px["date"].is_monotonic_increasing)
    all_ok &= check("date 無重複", not px["date"].duplicated().any())
    all_ok &= check("close 無缺值", not px["close"].isna().any())
    all_ok &= check("volume 無缺值", not px["volume"].isna().any())
    all_ok &= check("close 全為正", (px["close"] > 0).all())
    print(f"  → {len(px)} 列，日期範圍 {px['date'].min().date()} ~ {px['date'].max().date()}")
    print(px.tail(3).to_string(index=False))

    # ---------- 2. 三大法人 ----------
    print(f"\n=== 2. 三大法人買賣超（{STOCK}）===")
    inst = f.get_institutional(STOCK, START)
    if inst.empty:
        all_ok &= check("法人資料非空", False)
    else:
        names = set(inst["name"].unique()) if "name" in inst.columns else set()
        print(f"  欄位：{list(inst.columns)}")
        print(f"  法人類別：{names}")
        all_ok &= check("含 Foreign_Investor（外資）", "Foreign_Investor" in names)
        all_ok &= check("含 Investment_Trust（投信）", "Investment_Trust" in names)
        all_ok &= check("有 diff 欄（fetcher 計算 buy-sell）", "diff" in inst.columns)
        print(inst.tail(4).to_string(index=False))

    # ---------- 3. 融資融券 ----------
    print(f"\n=== 3. 融資融券（{STOCK}）===")
    margin = f.get_margin(STOCK, START)
    if margin.empty:
        all_ok &= check("融資券資料非空", False)
    else:
        print(f"  欄位：{list(margin.columns)}")
        need = {"MarginPurchaseBuy", "MarginPurchaseLimit", "ShortSaleBuy"}
        all_ok &= check(f"含評分所需欄位 {sorted(need)}", need.issubset(margin.columns))
        print(margin.tail(2).to_string(index=False))

    # ---------- 4. 時間軸對齊 ----------
    print("\n=== 4. 時間軸對齊（日K vs 法人）===")
    if not inst.empty:
        px_dates = set(px["date"])
        inst_dates = set(inst["date"])
        overlap = px_dates & inst_dates
        all_ok &= check("日K 與法人日期有大量重疊", len(overlap) > 100)
        print(f"  日K {len(px_dates)} 個交易日 / 法人 {len(inst_dates)} 個 / 重疊 {len(overlap)} 個")

    print("\n" + ("=" * 40))
    print("P0 資料驗證：全部 PASS ✅" if all_ok else "P0 資料驗證：有 FAIL ❌（見上）")
    print("=" * 40)
    sys.exit(0 if all_ok else 2)


if __name__ == "__main__":
    main()

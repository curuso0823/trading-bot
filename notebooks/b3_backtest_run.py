"""
notebooks/b3_backtest_run.py
B3：小範圍真實回測。建構 ~38 檔流動股的歷史訊號 → 跑 backtester → 看 stats / Gate。
首次執行會抓資料進快取（約 150 次請求，<600/日），之後重跑走快取。
用法：.venv\\Scripts\\python.exe notebooks\\b3_backtest_run.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from src.backtest.signal_builder import HistoricalSignalBuilder
from src.backtest.backtester import TaiwanBacktester

UNIVERSE = [
    "2330", "2454", "2303", "2308", "2379", "3034", "3711", "2337", "6415", "3008",
    "2317", "2382", "2357", "2376", "3231", "4938", "2356", "2353",
    "2881", "2882", "2891", "2886", "2884", "2885", "2892", "5880",
    "1301", "1303", "1326", "2002", "1101", "2207",
    "2603", "2609", "2615", "2412", "2912", "1216",
]
START, END = "2022-09-01", "2025-12-31"

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)


def main():
    builder = HistoricalSignalBuilder()
    price_df, signal_df = builder.build(UNIVERSE, START, END)
    if price_df.empty:
        print("無資料")
        sys.exit(1)

    n_sig = int(signal_df["entry_signal"].sum())
    per_stock = signal_df[signal_df["entry_signal"]].groupby("stock_id").size().sort_values(ascending=False)
    print(f"\n=== 訊號統計 ===")
    print(f"價格列數: {len(price_df)} | 標的: {signal_df['stock_id'].nunique()} | "
          f"日期: {price_df['date'].min().date()} ~ {price_df['date'].max().date()}")
    print(f"進場訊號總數: {n_sig}")
    print(f"有訊號的標的數: {per_stock.shape[0]}（前5: {dict(per_stock.head().astype(int))}）")

    if n_sig == 0:
        print("無進場訊號 → 無法回測（檢查條件是否過嚴）")
        sys.exit(2)

    bt = TaiwanBacktester()
    res = bt.run(price_df, signal_df)
    stats = res["stats"]
    print(f"\n=== 績效 stats ===")
    for k, v in stats.items():
        print(f"  {k:16} {v:.4f}" if isinstance(v, float) else f"  {k:16} {v}")

    print(f"\n=== Gate 檢查 ===")
    gate = bt._check_gate(stats)
    for k, v in gate.items():
        print(f"  {k:14} {v}")

    tr = res["trades"]
    print(f"\n=== 交易筆數: {len(tr)} ===")
    if not tr.empty:
        cols = [c for c in ["Column", "Entry Index", "Avg Entry Price",
                            "Exit Index", "Avg Exit Price", "PnL", "Return"] if c in tr.columns]
        print("前 8 筆：")
        print(tr[cols].head(8).to_string(index=False))

    # 原始 stats（核對 vectorbt 1.0 的 key，尤其 Annualized Return）
    print(f"\n=== 原始 portfolio.stats() ===")
    print(res["portfolio"].stats())


if __name__ == "__main__":
    main()

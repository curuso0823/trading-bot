"""
notebooks/b4_consistency.py
B4：分年一致性檢查。用同一套策略，把回測切成各年度分別跑，看 edge 是否每年都在
（而非單一年度運氣）。資料已快取。
用法：.venv\\Scripts\\python.exe notebooks\\b4_consistency.py
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
PERIODS = [
    ("2023", "2023-01-01", "2023-12-31"),
    ("2024", "2024-01-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
    ("全期", "2022-09-01", "2025-12-31"),
]


def slice_run(bt, price_df, signal_df, lo, hi):
    lo, hi = pd.Timestamp(lo), pd.Timestamp(hi)
    p = price_df[(price_df["date"] >= lo) & (price_df["date"] <= hi)]
    s = signal_df[(signal_df["date"] >= lo) & (signal_df["date"] <= hi)]
    if p.empty or int(s["entry_signal"].sum()) == 0:
        return None
    return bt.run(p, s)["stats"]


def main():
    builder = HistoricalSignalBuilder()
    price_df, signal_df = builder.build(UNIVERSE, START, END)
    bt = TaiwanBacktester()

    print(f"\n{'期間':<6}{'報酬':>9}{'年化':>9}{'Sharpe':>9}{'最大回撤':>10}{'勝率':>8}{'交易':>7}{'PF':>7}")
    print("-" * 66)
    for name, lo, hi in PERIODS:
        st = slice_run(bt, price_df, signal_df, lo, hi)
        if not st:
            print(f"{name:<6}  (無交易)")
            continue
        print(f"{name:<6}{st['total_return']*100:>8.1f}%{st['annual_return']*100:>8.1f}%"
              f"{st['sharpe_ratio']:>9.2f}{st['max_drawdown']*100:>9.1f}%"
              f"{st['win_rate']*100:>7.0f}%{st['total_trades']:>7d}{st['profit_factor']:>7.2f}")

    print("\n判讀：各年 Sharpe 是否都 > 0／報酬是否都為正 → edge 是否穩定（非單年運氣）")


if __name__ == "__main__":
    main()

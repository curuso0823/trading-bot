"""
notebooks/hybrid_capital_contrast.py
hybrid 計價的資金敏感度：不同資金下「整股/零股」比例與 Gate 表現。
說明 hybrid 的好處與資金大小高度相關（資金小→幾乎全零股→高滑價）。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest.signal_builder import HistoricalSignalBuilder
from src.backtest.backtester import TaiwanBacktester

UNIVERSE = [
    "2330", "2454", "2303", "2308", "2379", "3034", "3711", "2337", "6415", "3008",
    "2317", "2382", "2357", "2376", "3231", "4938", "2356", "2353",
    "2881", "2882", "2891", "2886", "2884", "2885", "2892", "5880",
    "1301", "1303", "1326", "2002", "1101", "2207",
    "2603", "2609", "2615", "2412", "2912", "1216",
]


def main():
    price_df, signal_df = HistoricalSignalBuilder().build(UNIVERSE, "2022-09-01", "2025-12-31")
    bt = TaiwanBacktester()
    print(f"\n{'資金':>10}{'年化':>9}{'Sharpe':>9}{'回撤':>9}{'總報酬':>9}{'Gate':>7}")
    print("-" * 54)
    for cap in [50_000, 200_000, 500_000, 1_000_000, 5_000_000]:
        st = bt.run(price_df, signal_df, initial_capital=cap)["stats"]
        gate = bt._check_gate(st)["all_pass"]
        print(f"{cap:>10,}{st['annual_return']*100:>8.1f}%{st['sharpe_ratio']:>9.2f}"
              f"{st['max_drawdown']*100:>8.1f}%{st['total_return']*100:>8.1f}%"
              f"{'  PASS' if gate else '  FAIL':>7}")
    print("\n說明：資金越小 → 買得起整張的股票越少 → 越多零股(高滑價) → edge 越被侵蝕")


if __name__ == "__main__":
    main()

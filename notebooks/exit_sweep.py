"""
notebooks/exit_sweep.py
在 50k 資金下掃描移動停損(trailing_stop_pct)，看 回撤/Sharpe/報酬 tradeoff，
找能把 maxDD 壓進 -15% 又維持 Sharpe≥1 的設定。
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
CAP = 50_000


def main():
    price_df, signal_df = HistoricalSignalBuilder().build(UNIVERSE, "2022-09-01", "2025-12-31")
    bt = TaiwanBacktester()
    print(f"\n{'trail':>7}{'年化':>9}{'Sharpe':>9}{'回撤':>9}{'總報酬':>9}{'交易':>7}{'過Gate':>8}")
    print("-" * 58)
    for trail in [0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.15]:
        bt.exit_cfg["trailing_stop_pct"] = trail   # 直接覆寫(run 讀取時生效)
        st = bt.run(price_df, signal_df, initial_capital=CAP)["stats"]
        g = bt._check_gate(st)
        ok = "ALL" if g["all_pass"] else ("DD缺" if (g["sharpe_ok"] and g["return_ok"] and not g["drawdown_ok"]) else "多缺")
        print(f"{trail:>7.2f}{st['annual_return']*100:>8.1f}%{st['sharpe_ratio']:>9.2f}"
              f"{st['max_drawdown']*100:>8.1f}%{st['total_return']*100:>8.1f}%"
              f"{st['total_trades']:>7d}{ok:>8}")


if __name__ == "__main__":
    main()

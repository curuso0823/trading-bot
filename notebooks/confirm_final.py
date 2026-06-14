"""
notebooks/confirm_final.py
最終權威確認（全期，無 A2）：baseline(fixed12%) vs 採用的 A1(atr max0.10) vs 略保守(max0.11)。
輸出完整 _extract_stats + Gate，作為定案數字。
用法：.venv\\Scripts\\python.exe notebooks\\confirm_final.py
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
START, END = "2022-09-01", "2025-12-31"
CAPS = [50_000, 300_000]


def row(bt, price_df, sig, cap, label):
    st = bt.run(price_df, sig, initial_capital=cap)["stats"]
    g = bt._check_gate(st)
    ok = "ALL" if g["all_pass"] else ("DD-" if (g["sharpe_ok"] and g["return_ok"]) else "x")
    print(f"{label:>16}{st['annual_return']*100:>8.1f}%{st['sharpe_ratio']:>9.2f}"
          f"{st['max_drawdown']*100:>8.1f}%{st['total_return']*100:>9.1f}%"
          f"{st['profit_factor']:>7.2f}{st['total_trades']:>7d}{ok:>7}")


def main():
    builder = HistoricalSignalBuilder()
    builder.selection_cfg = {"sector_cap_enabled": False}
    price_df, sig = builder.build(UNIVERSE, START, END)
    bt = TaiwanBacktester()
    base_exit = dict(bt.exit_cfg)

    for cap in CAPS:
        print(f"\n===== 資金 {cap:,} =====")
        print(f"{'設定':>16}{'年化':>9}{'Sharpe':>9}{'回撤':>9}{'總報酬':>10}{'PF':>7}{'交易':>7}{'Gate':>7}")
        print("-" * 76)
        bt.exit_cfg = {**base_exit, "trailing_mode": "fixed"}
        row(bt, price_df, sig, cap, "baseline fixed")
        bt.exit_cfg = {**base_exit, "trailing_mode": "atr", "atr_mult": 4.5,
                       "atr_trail_min": 0.08, "atr_trail_max": 0.10}
        row(bt, price_df, sig, cap, "A1 atr max0.10")
        bt.exit_cfg = {**base_exit, "trailing_mode": "atr", "atr_mult": 4.5,
                       "atr_trail_min": 0.08, "atr_trail_max": 0.11}
        row(bt, price_df, sig, cap, "A1 atr max0.11")


if __name__ == "__main__":
    main()

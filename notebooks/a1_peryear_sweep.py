"""
notebooks/a1_peryear_sweep.py
A1 真實效果隔離：全期 DD 幾乎全來自 2025 全市場修正(market-beta)，會掩蓋 A1 的停損寬度效果。
→ 把各年單獨切出來回測，掃 ATR 停損上限(max)，看「乾淨趨勢年(2023/2024)」裡 A1 的真實貢獻，
   並與「崩盤年 2025」對照。據此決定 max 與是否採用。
無 A2。用法：.venv\\Scripts\\python.exe notebooks\\a1_peryear_sweep.py
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
CAP = 50_000
YEARS = {"2023(趨勢)": ("2023-01-01", "2023-12-31"),
         "2024(趨勢)": ("2024-01-01", "2024-12-31"),
         "2025(崩盤)": ("2025-01-01", "2025-12-31")}
MAXES = [0.10, 0.11, 0.12, 0.13, 0.14, 0.16, 0.18, 0.22]


def stat(bt, pdf, sdf, label):
    st = bt.run(pdf, sdf, initial_capital=CAP)["stats"]
    print(f"{label:>16}{st['total_return']*100:>9.1f}%{st['sharpe_ratio']:>9.2f}"
          f"{st['max_drawdown']*100:>9.1f}%{st['profit_factor']:>7.2f}{st['total_trades']:>7d}")


def main():
    builder = HistoricalSignalBuilder()
    builder.selection_cfg = {"sector_cap_enabled": False}
    price_df, sig = builder.build(UNIVERSE, START, END)
    bt = TaiwanBacktester()
    base_exit = dict(bt.exit_cfg)

    for yname, (s, e) in YEARS.items():
        s, e = pd.Timestamp(s), pd.Timestamp(e)
        pdf = price_df[(price_df["date"] >= s) & (price_df["date"] <= e)]
        sdf = sig[(sig["date"] >= s) & (sig["date"] <= e)]
        print(f"\n===== {yname}  資金 {CAP:,} =====")
        print(f"{'設定':>16}{'年報酬':>10}{'Sharpe':>9}{'回撤':>10}{'PF':>7}{'交易':>7}")
        print("-" * 60)
        bt.exit_cfg = {**base_exit, "trailing_mode": "fixed"}
        stat(bt, pdf, sdf, "fixed 12%")
        for mx in MAXES:
            bt.exit_cfg = {**base_exit, "trailing_mode": "atr", "atr_mult": 4.5,
                           "atr_trail_min": 0.08, "atr_trail_max": mx}
            stat(bt, pdf, sdf, f"ATR max={mx}")


if __name__ == "__main__":
    main()

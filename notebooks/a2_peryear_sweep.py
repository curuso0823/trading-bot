"""
notebooks/a2_peryear_sweep.py
A2 分年重測（base 已採用 A1：trailing_mode=atr max0.10）。
全期看 A2 會被 2025 全市場修正蓋掉 → 分年看「乾淨趨勢年(2023/2024)」裡 A2(類股分散)是否
真的有貢獻，還是連乾淨年都輸 = 真的不行。掃 max_per_sector ∈ {1,2}。
用法：.venv\\Scripts\\python.exe notebooks\\a2_peryear_sweep.py
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
         "2025(崩盤)": ("2025-01-01", "2025-12-31"),
         "全期": (START, END)}


def stat(bt, pdf, sdf, label):
    st = bt.run(pdf, sdf, initial_capital=CAP)["stats"]
    g = bt._check_gate(st)
    print(f"{label:>14}{st['total_return']*100:>9.1f}%{st['sharpe_ratio']:>9.2f}"
          f"{st['max_drawdown']*100:>9.1f}%{st['profit_factor']:>7.2f}{st['total_trades']:>7d}")


def main():
    builder = HistoricalSignalBuilder()
    builder.selection_cfg = {"sector_cap_enabled": False}
    price_df, sig0 = builder.build(UNIVERSE, START, END)
    builder.selection_cfg = {"sector_cap_enabled": True, "max_per_sector": 2}
    _, sig2 = builder.build(UNIVERSE, START, END)
    builder.selection_cfg = {"sector_cap_enabled": True, "max_per_sector": 1}
    _, sig1 = builder.build(UNIVERSE, START, END)

    bt = TaiwanBacktester()  # 讀 config：trailing_mode=atr max0.10（= A1 已採用）
    sets = [("A1 only", sig0), ("A1+A2 cap2", sig2), ("A1+A2 cap1", sig1)]

    for yname, (s, e) in YEARS.items():
        s, e = pd.Timestamp(s), pd.Timestamp(e)
        print(f"\n===== {yname}  資金 {CAP:,}（base=A1 atr max0.10）=====")
        print(f"{'設定':>14}{'年報酬':>10}{'Sharpe':>9}{'回撤':>10}{'PF':>7}{'交易':>7}")
        print("-" * 58)
        for label, sig in sets:
            pdf = price_df[(price_df["date"] >= s) & (price_df["date"] <= e)]
            sdf = sig[(sig["date"] >= s) & (sig["date"] <= e)]
            stat(bt, pdf, sdf, label)


if __name__ == "__main__":
    main()

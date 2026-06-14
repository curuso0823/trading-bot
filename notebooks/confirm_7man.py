"""
notebooks/confirm_7man.py
Task1：初始資金 7 萬下的分年回測（隔離 2025 系統性回撤）+ ATR 停損上限微調。
1) 分年(2023/2024/2025/全期) 比 baseline(fixed12%) vs 採用(ATR max0.10)
2) 7萬下 atr_trail_max 掃描（全期 + 2024乾淨年），看最佳點是否隨資金移動
用法：.venv\\Scripts\\python.exe notebooks\\confirm_7man.py
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
CAP = 70_000
YEARS = {"2023(趨勢)": ("2023-01-01", "2023-12-31"),
         "2024(趨勢)": ("2024-01-01", "2024-12-31"),
         "2025(崩盤)": ("2025-01-01", "2025-12-31"),
         "全期": (START, END)}


def run(bt, pdf, sdf, label):
    st = bt.run(pdf, sdf, initial_capital=CAP)["stats"]
    g = bt._check_gate(st)
    ok = "ALL" if g["all_pass"] else ("DD-" if (g["sharpe_ok"] and g["return_ok"]) else "x")
    print(f"{label:>16}{st['total_return']*100:>9.1f}%{st['sharpe_ratio']:>9.2f}"
          f"{st['max_drawdown']*100:>9.1f}%{st['profit_factor']:>7.2f}{st['total_trades']:>7d}{ok:>6}")


def main():
    builder = HistoricalSignalBuilder()
    builder.selection_cfg = {"sector_cap_enabled": False}
    price_df, sig = builder.build(UNIVERSE, START, END)
    bt = TaiwanBacktester()
    base_exit = dict(bt.exit_cfg)
    fixed = {"trailing_mode": "fixed"}
    atr10 = {"trailing_mode": "atr", "atr_mult": 4.5, "atr_trail_min": 0.08, "atr_trail_max": 0.10}

    print(f"\n########## 資金 {CAP:,}：分年 baseline vs 採用(ATR max0.10) ##########")
    for yname, (s, e) in YEARS.items():
        s, e = pd.Timestamp(s), pd.Timestamp(e)
        pdf = price_df[(price_df["date"] >= s) & (price_df["date"] <= e)]
        sdf = sig[(sig["date"] >= s) & (sig["date"] <= e)]
        print(f"\n--- {yname} ---")
        print(f"{'設定':>16}{'總報酬':>10}{'Sharpe':>9}{'回撤':>10}{'PF':>7}{'交易':>7}{'Gate':>6}")
        bt.exit_cfg = {**base_exit, **fixed}
        run(bt, pdf, sdf, "fixed 12%")
        bt.exit_cfg = {**base_exit, **atr10}
        run(bt, pdf, sdf, "ATR max0.10")

    print(f"\n########## 資金 {CAP:,}：atr_trail_max 微調 ##########")
    for yname in ["全期", "2024(趨勢)"]:
        s, e = pd.Timestamp(YEARS[yname][0]), pd.Timestamp(YEARS[yname][1])
        pdf = price_df[(price_df["date"] >= s) & (price_df["date"] <= e)]
        sdf = sig[(sig["date"] >= s) & (sig["date"] <= e)]
        print(f"\n--- {yname} ---")
        print(f"{'設定':>16}{'總報酬':>10}{'Sharpe':>9}{'回撤':>10}{'PF':>7}{'交易':>7}{'Gate':>6}")
        bt.exit_cfg = {**base_exit, **fixed}
        run(bt, pdf, sdf, "fixed 12%")
        for mx in [0.08, 0.09, 0.10, 0.11, 0.12]:
            bt.exit_cfg = {**base_exit, "trailing_mode": "atr", "atr_mult": 4.5,
                           "atr_trail_min": 0.08, "atr_trail_max": mx}
            run(bt, pdf, sdf, f"ATR max={mx}")


if __name__ == "__main__":
    main()

"""
notebooks/strategy_b_300k.py
任務4：策略 B（資金 30 萬）設計驗證。
沿用已驗證核心（block_only regime + vol-sizing + ATR trail），比較：
  A) 70k 純零股（現行 paper，對照）
  B) 300k 純零股（資金規模效應）
  C) 300k hybrid（高價零股/可負擔整股 → 整股滑價低 0.1%）
分年 2018-2025 輸出 年化/Sharpe/DD/PF。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from src.backtest.signal_builder import HistoricalSignalBuilder
from src.backtest.backtester import TaiwanBacktester
from src.utils.helpers import load_config

U = ["2330","2454","2303","2308","2379","3034","3711","2337","6415","3008","2317","2382",
     "2357","2376","3231","4938","2356","2353","2881","2882","2891","2886","2884","2885",
     "2892","5880","1301","1303","1326","2002","1101","2207","2603","2609","2615","2412","2912","1216"]
START, END = "2018-01-01", "2025-12-31"
YEARS = {"2018": ("2018-01-01","2018-12-31"), "2019": ("2019-01-01","2019-12-31"),
         "2020": ("2020-01-01","2020-12-31"), "2021": ("2021-01-01","2021-12-31"),
         "2022": ("2022-01-01","2022-12-31"), "2023": ("2023-01-01","2023-12-31"),
         "2024": ("2024-01-01","2024-12-31"), "2025": ("2025-01-01","2025-12-31"),
         "全期": (START, END)}


def main():
    b = HistoricalSignalBuilder()
    b.selection_cfg = {"sector_cap_enabled": False}
    b.cap_cfg = {**load_config().get("capitulation", {})}   # 現行採用值（block_only）
    print("建立訊號（一次，所有變體共用）…")
    price_df, sig = b.build(U, START, END)

    variants = {"A 70k零股": (70_000, "odd_lot"), "B 300k零股": (300_000, "odd_lot"),
                "C 300k混合": (300_000, "hybrid")}
    bts = {}
    for name, (cap, mode) in variants.items():
        bt = TaiwanBacktester()
        bt.trading_cfg = {**bt.trading_cfg, "mode": mode}
        bts[name] = (bt, cap)

    hdr = f"{'年化':>7}{'Shrp':>6}{'回撤':>7}{'PF':>6}{'筆':>5}"
    print(f"\n{'年':>6} │" + "│".join(f" {n:^31} " for n in variants))
    print(f"{'':>6} │" + "│".join(f" {hdr} " for _ in variants))
    print("  " + "─" * 110)
    for yname, (s, e) in YEARS.items():
        s, e = pd.Timestamp(s), pd.Timestamp(e)
        pdf = price_df[(price_df["date"] >= s) & (price_df["date"] <= e)]
        sdf = sig[(sig["date"] >= s) & (sig["date"] <= e)]
        cells = []
        for name, (bt, cap) in bts.items():
            if sdf.empty or int(sdf["entry_signal"].sum()) == 0:
                cells.append(f"{'(0進場)':>31} "); continue
            st = bt.run(pdf, sdf, initial_capital=cap)["stats"]
            cells.append(f"{st['annual_return']*100:>6.1f}%{st['sharpe_ratio']:>6.2f}"
                          f"{st['max_drawdown']*100:>6.1f}%{st['profit_factor']:>6.2f}{st['total_trades']:>5d} ")
        sep = "" if yname != "全期" else "  " + "─" * 110 + "\n"
        print(f"{sep}{yname:>6} │" + "│".join(cells))


if __name__ == "__main__":
    main()

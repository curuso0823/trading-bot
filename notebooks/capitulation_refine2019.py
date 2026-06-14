"""
notebooks/capitulation_refine2019.py
task2：block_only 的 2019 誤殺精修 — 「持續站上 MA60 連 N 日豁免擋單」。
掃 reclaim_exempt_days N ∈ {0,10,15,20,25}，看 2019 救回多少 vs 2022 是否回吐(re-break)。
硬底線：2022 不可顯著惡化(>-18%)、2023/24 不受傷。

用法：.venv\\Scripts\\python.exe notebooks\\capitulation_refine2019.py
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
CAP = 70_000
YEARS = {"2018": ("2018-01-01","2018-12-31"), "2019": ("2019-01-01","2019-12-31"),
         "2020": ("2020-01-01","2020-12-31"), "2021": ("2021-01-01","2021-12-31"),
         "2022": ("2022-01-01","2022-12-31"), "2023": ("2023-01-01","2023-12-31"),
         "2024": ("2024-01-01","2024-12-31"), "2025": ("2025-01-01","2025-12-31"),
         "全期": (START, END)}
EXEMPT = [0, 16, 18, 20, 22, 24, 30]   # 0 = 現行 block_only；查 N=20 是高原還是刀鋒


def build(exempt_n):
    b = HistoricalSignalBuilder()
    b.selection_cfg = {"sector_cap_enabled": False}
    b.cap_cfg = {**load_config().get("capitulation", {}), "enabled": True,
                 "allow_mode": "block_only", "failed_bottom_exit": False,
                 "reclaim_exempt_days": exempt_n}
    return b.build(U, START, END)


def stats_for(bt, price_df, sig, s, e):
    s, e = pd.Timestamp(s), pd.Timestamp(e)
    pdf = price_df[(price_df["date"] >= s) & (price_df["date"] <= e)]
    sdf = sig[(sig["date"] >= s) & (sig["date"] <= e)]
    if sdf.empty or int(sdf["entry_signal"].sum()) == 0:
        return None
    return bt.run(pdf, sdf, initial_capital=CAP)["stats"]


def main():
    bt = TaiwanBacktester()
    print(f"資金 {CAP:,}｜block_only + 持穩豁免 reclaim_exempt_days 掃描")
    built = {}
    for n in EXEMPT:
        print(f"  建立訊號：exempt={n}…")
        built[n] = build(n)

    # 年化表
    print(f"\n年化(%)     " + "".join(f"{('N='+str(n)) if n else 'base':>9}" for n in EXEMPT))
    for yname, (s, e) in YEARS.items():
        row = []
        for n in EXEMPT:
            st = stats_for(bt, *built[n], s, e)
            row.append("   (0)" if st is None else f"{st['annual_return']*100:>8.1f}")
        print(f"  {yname:<8}" + "".join(f"{v:>9}" for v in row))

    # 全期 Sharpe / DD
    print(f"\n全期Sharpe  " + "".join(f"{('N='+str(n)) if n else 'base':>9}" for n in EXEMPT))
    srow, drow = [], []
    for n in EXEMPT:
        st = stats_for(bt, *built[n], *YEARS["全期"])
        srow.append(f"{st['sharpe_ratio']:>8.2f}")
        drow.append(f"{st['max_drawdown']*100:>8.1f}")
    print("  Sharpe  " + "".join(f"{v:>9}" for v in srow))
    print("  DD%     " + "".join(f"{v:>9}" for v in drow))
    print("\n  判讀：N>0 救回 2019 多少？2022 是否回吐(re-break)？全期 Sharpe/DD 淨效果？")


if __name__ == "__main__":
    main()

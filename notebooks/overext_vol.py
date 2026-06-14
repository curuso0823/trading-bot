"""
notebooks/overext_vol.py
task3 變體：波動上限 max_vol_pct（20日已實現日波動）疊在 block_only 之上分年回測。
直接攻 2021 航運拋物線高波動名。掃 {off,0.025,0.030,0.035,0.040}。
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
VOL = [None, 0.025, 0.030, 0.035, 0.040]


def build(max_vol):
    b = HistoricalSignalBuilder()
    b.selection_cfg = {"sector_cap_enabled": False}
    b.cap_cfg = {**load_config().get("capitulation", {}), "enabled": True,
                 "allow_mode": "block_only", "failed_bottom_exit": False, "reclaim_exempt_days": 0}
    b.tech.max_vol_pct = max_vol
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
    print(f"資金 {CAP:,}｜block_only + 波動上限 max_vol_pct 掃描")
    built = {x: build(x) for x in VOL}
    cols = "".join(f"{('v'+str(x)) if x else 'off':>9}" for x in VOL)
    print(f"\n年化(%)     {cols}")
    for yname, (s, e) in YEARS.items():
        row = [("   (0)" if (st := stats_for(bt, *built[x], s, e)) is None
                else f"{st['annual_return']*100:>8.1f}") for x in VOL]
        print(f"  {yname:<8}" + "".join(f"{v:>9}" for v in row))
    print(f"\n全期        {cols}")
    for key, lab, mul in [("sharpe_ratio","Sharpe",1), ("max_drawdown","DD%",100), ("total_trades","筆",1)]:
        vals = []
        for x in VOL:
            st = stats_for(bt, *built[x], *YEARS["全期"])
            vals.append(f"{int(st[key]):>8d}" if key == "total_trades" else f"{st[key]*mul:>8.2f}")
        print(f"  {lab:<8}" + "".join(f"{v:>9}" for v in vals))
    print("\n  判讀：2021 改善？2023/2024 被砍多少？全期淨效果？")


if __name__ == "__main__":
    main()

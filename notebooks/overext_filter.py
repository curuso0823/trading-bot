"""
notebooks/overext_filter.py
task3：過度延伸濾鏡（離 MA20 乖離上限 max_ext_pct）疊在 block_only 之上分年回測。
攻 2021 少年股神泡沫(追航運拋物線)/2018 箱型；硬底線：2023/2024 大牛不可被砍太多。
掃 max_ext_pct ∈ {off, 0.10, 0.15, 0.20, 0.25}。

用法：.venv\\Scripts\\python.exe notebooks\\overext_filter.py
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
EXT = [None, 0.10, 0.15, 0.20, 0.25]   # None = 現行 block_only（無乖離上限）


def build(max_ext):
    b = HistoricalSignalBuilder()
    b.selection_cfg = {"sector_cap_enabled": False}
    b.cap_cfg = {**load_config().get("capitulation", {}), "enabled": True,
                 "allow_mode": "block_only", "failed_bottom_exit": False, "reclaim_exempt_days": 0}
    b.tech.max_ext_pct = max_ext        # 疊上過度延伸濾鏡
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
    print(f"資金 {CAP:,}｜block_only + 過度延伸濾鏡 max_ext_pct 掃描")
    built = {}
    for x in EXT:
        print(f"  建立訊號：max_ext={x}…")
        built[x] = build(x)

    cols = "".join(f"{('ext'+str(x)) if x else 'off':>9}" for x in EXT)
    print(f"\n年化(%)     {cols}")
    for yname, (s, e) in YEARS.items():
        row = []
        for x in EXT:
            st = stats_for(bt, *built[x], s, e)
            row.append("   (0)" if st is None else f"{st['annual_return']*100:>8.1f}")
        print(f"  {yname:<8}" + "".join(f"{v:>9}" for v in row))

    print(f"\n全期        {cols}")
    for key, lab, mul in [("sharpe_ratio","Sharpe",1), ("max_drawdown","DD%",100),
                          ("profit_factor","PF",1), ("total_trades","筆",1)]:
        vals = []
        for x in EXT:
            st = stats_for(bt, *built[x], *YEARS["全期"])
            v = st[key] * mul
            vals.append(f"{v:>8.2f}" if key != "total_trades" else f"{int(v):>8d}")
        print(f"  {lab:<8}" + "".join(f"{v:>9}" for v in vals))
    print("\n  判讀：2021/2018 改善？2023/2024 被砍多少？全期 Sharpe/DD 淨效果？")


if __name__ == "__main__":
    main()

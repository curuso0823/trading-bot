"""快速量化 #5：全期(2018-2025)同日出場(進場日=出場日)筆數。資料已快取。"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from src.backtest.signal_builder import HistoricalSignalBuilder
from src.backtest.backtester import TaiwanBacktester
U = ["2330","2454","2303","2308","2379","3034","3711","2337","6415","3008","2317","2382",
     "2357","2376","3231","4938","2356","2353","2881","2882","2891","2886","2884","2885",
     "2892","5880","1301","1303","1326","2002","1101","2207","2603","2609","2615","2412","2912","1216"]
b = HistoricalSignalBuilder(); b.selection_cfg = {"sector_cap_enabled": False}
p, s = b.build(U, "2018-01-01", "2025-12-31")
tr = TaiwanBacktester().run(p, s, initial_capital=70_000)["portfolio"].trades.records_readable
print("欄位:", tr.columns.tolist())
ec = next((c for c in tr.columns if "Entry" in c and ("Index" in c or "Timestamp" in c)), None)
xc = next((c for c in tr.columns if "Exit" in c and ("Index" in c or "Timestamp" in c)), None)
if ec and xc:
    same = int((pd.to_datetime(tr[ec]) == pd.to_datetime(tr[xc])).sum())
    print(f"#5 同日出場: {same}/{len(tr)} ({same/max(len(tr),1)*100:.2f}%) → "
          f"{'可忽略' if same/max(len(tr),1) < 0.03 else '需注意'}")

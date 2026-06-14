"""B3 debug：逐項隔離 from_signals 的 order.price 錯誤來源。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, pandas as pd, vectorbt as vbt
from src.backtest.signal_builder import HistoricalSignalBuilder

UNIVERSE = ["2330","2454","2303","2308","2379","3034","3711","2337","6415","3008",
            "2317","2382","2357","2376","3231","4938","2356","2353",
            "2881","2882","2891","2886","2884","2885","2892","5880",
            "1301","1303","1326","2002","1101","2207",
            "2603","2609","2615","2412","2912","1216"]

b = HistoricalSignalBuilder()
price_df, signal_df = b.build(UNIVERSE, "2022-09-01", "2025-12-31")

close_px = price_df.pivot(index="date", columns="stock_id", values="close").sort_index().ffill().bfill()
open_px = price_df.pivot(index="date", columns="stock_id", values="open").reindex_like(close_px).ffill().bfill()
entries = (signal_df.pivot(index="date", columns="stock_id", values="entry_signal")
           .reindex(index=close_px.index, columns=close_px.columns)
           .fillna(False).astype(bool).shift(1).fillna(False).astype(bool))

print("close NaN", int(close_px.isna().sum().sum()), "min", float(np.nanmin(close_px.values)))
print("open  NaN", int(open_px.isna().sum().sum()), "min", float(np.nanmin(open_px.values)))
print("entries shape", entries.shape, "sum", int(entries.values.sum()))
opv, ent = open_px.values, entries.values
bad = ent & (~np.isfinite(opv) | (opv <= 0))
print("entry-execution bars with bad open:", int(bad.sum()))


def trial(name, **kw):
    try:
        pf = vbt.Portfolio.from_signals(close=close_px, entries=entries, exits=False,
                                        init_cash=1e6, fees=0.003, freq="1D", **kw)
        print(f"  [OK]   {name}")
        return pf
    except Exception as e:
        print(f"  [FAIL] {name}: {repr(e)[:120]}")
        return None


print("--- 逐項 ---")
trial("minimal")
trial("price=open", price=open_px)
trial("sl/tp", sl_stop=0.05, tp_stop=0.10)
trial("size%", size=0.30, size_type="percent")
trial("cash_sharing", size=0.30, size_type="percent", cash_sharing=True, call_seq="auto")
trial("FULL", price=open_px, sl_stop=0.05, tp_stop=0.10, size=0.30,
      size_type="percent", cash_sharing=True, call_seq="auto", slippage=0.001)

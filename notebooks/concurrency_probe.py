"""
notebooks/concurrency_probe.py
量測『回測實際並倉檔數分布』→ 佐證 live max_positions 該設幾。
回測無硬上限(cash+percent sizing 決定)，這是驗證過的 Sharpe 0.90 真實行為。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from src.backtest.signal_builder import HistoricalSignalBuilder
from src.backtest.backtester import TaiwanBacktester
from src.utils.helpers import load_config

U = ["2330","2454","2303","2308","2379","3034","3711","2337","6415","3008","2317","2382",
     "2357","2376","3231","4938","2356","2353","2881","2882","2891","2886","2884","2885",
     "2892","5880","1301","1303","1326","2002","1101","2207","2603","2609","2615","2412","2912","1216"]


def conc_series(pf):
    """每日並倉檔數（持有非零股數的標的數）。"""
    try:
        assets = pf.assets()
    except Exception:
        assets = pf.asset_flow().cumsum()
    return (assets.abs() > 1e-9).sum(axis=1)


def main():
    b = HistoricalSignalBuilder()
    b.selection_cfg = {"sector_cap_enabled": False}
    b.cap_cfg = {**load_config().get("capitulation", {})}
    price_df, sig = b.build(U, "2018-01-01", "2025-12-31")

    for cap in (70_000, 300_000):
        bt = TaiwanBacktester()
        pf = bt.run(price_df, sig, initial_capital=cap)["portfolio"]
        c = conc_series(pf)
        active = c[c > 0]
        print(f"\n=== 資金 {cap:,} 並倉分布（在場 {len(active)}/{len(c)} 日）===")
        print(f"  平均 {active.mean():.2f}｜中位 {active.median():.0f}｜最大 {int(c.max())}")
        vc = active.value_counts().sort_index()
        for k, v in vc.items():
            print(f"   {int(k)} 檔：{v:>4} 日（{v/len(active)*100:>4.1f}%）")
        for thr in (3, 4, 5):
            print(f"  在場日並倉 ≥{thr}：{(active >= thr).mean()*100:.1f}%")


if __name__ == "__main__":
    main()

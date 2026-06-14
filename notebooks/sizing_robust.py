"""
notebooks/sizing_robust.py
穩健性檢查：vol_only（inverse-vol, 無市場縮放）下掃 target_vol_daily × vol_lookback，
確認 Sharpe/回撤改善不是坐在單一幸運參數點（防 overfit）。基準 flat 一併列出。
用法：.venv\\Scripts\\python.exe notebooks\\sizing_robust.py
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


def row(bt, price_df, signal_df, label):
    st = bt.run(price_df, signal_df, initial_capital=CAP)["stats"]
    g = bt._check_gate(st)
    ok = "ALL" if g["all_pass"] else ("DD-" if (g["sharpe_ok"] and g["return_ok"]) else "x")
    print(f"{label:>22}{st['annual_return']*100:>8.1f}%{st['sharpe_ratio']:>9.2f}"
          f"{st['max_drawdown']*100:>8.1f}%{st['profit_factor']:>7.2f}{ok:>7}")


def main():
    price_df, signal_df = HistoricalSignalBuilder().build(UNIVERSE, START, END)
    bt = TaiwanBacktester()
    base = dict(bt.sizing_cfg)

    print(f"\n資金 {CAP:,}｜vol_only 穩健性掃描（無市場縮放）")
    print(f"{'設定':>22}{'年化':>9}{'Sharpe':>9}{'回撤':>9}{'PF':>7}{'Gate':>7}")
    print("-" * 64)

    bt.sizing_cfg = {**base, "method": "flat"}
    row(bt, price_df, signal_df, "flat (基準)")

    for lb in [10, 20, 40]:
        for tv in [0.015, 0.018, 0.020, 0.025, 0.030]:
            bt.sizing_cfg = {**base, "method": "vol_target",
                             "market_vol_scaling": False,
                             "vol_lookback": lb, "target_vol_daily": tv}
            row(bt, price_df, signal_df, f"lb={lb} tv={tv:.3f}")
        print("-" * 64)


if __name__ == "__main__":
    main()

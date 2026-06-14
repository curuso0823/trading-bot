"""
notebooks/a1_band_sweep.py
A1 微調：固定 atr_mult，收窄 ATR 停損「上限」(atr_trail_max)，
看能否保住 ATR 的高 Sharpe 又把 DD 拉回 -15% 內（cap 最寬停損 = 限制單筆深回檔）。
無 A2。用法：.venv\\Scripts\\python.exe notebooks\\a1_band_sweep.py
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
    print(f"{label:>18}{st['annual_return']*100:>8.1f}%{st['sharpe_ratio']:>9.2f}"
          f"{st['max_drawdown']*100:>8.1f}%{st['profit_factor']:>7.2f}{st['total_trades']:>7d}{ok:>7}")


def main():
    builder = HistoricalSignalBuilder()
    builder.selection_cfg = {"sector_cap_enabled": False}
    price_df, sig = builder.build(UNIVERSE, START, END)
    bt = TaiwanBacktester()
    base_exit = dict(bt.exit_cfg)

    print(f"\n資金 {CAP:,}｜A1 收窄停損上限掃描（atr_mult=4.5, min=0.08）")
    print(f"{'設定':>18}{'年化':>9}{'Sharpe':>9}{'回撤':>9}{'PF':>7}{'交易':>7}{'Gate':>7}")
    print("-" * 68)
    bt.exit_cfg = {**base_exit, "trailing_mode": "fixed"}
    row(bt, price_df, sig, "fixed 12%(基準)")
    for mx in [0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.18]:
        bt.exit_cfg = {**base_exit, "trailing_mode": "atr", "atr_mult": 4.5,
                       "atr_trail_min": 0.08, "atr_trail_max": mx}
        row(bt, price_df, sig, f"ATR x4.5 max={mx}")


if __name__ == "__main__":
    main()

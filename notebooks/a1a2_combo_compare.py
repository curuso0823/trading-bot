"""
notebooks/a1a2_combo_compare.py
A1×A2 疊加驗證（2×2）：
  baseline      固定停損12% + 無類股上限（= 現況 Method A）
  +A1           ATR 自適應停損 + 無類股上限
  +A2           固定停損12% + 類股分散上限
  +A1+A2        ATR 自適應停損 + 類股分散上限
A2 在 signal_builder 層 → 建兩套訊號；A1 在 backtester 層 → 切 exit_cfg。
用法：.venv\\Scripts\\python.exe notebooks\\a1a2_combo_compare.py
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
CAPS = [50_000, 300_000]
ATR_MULT = 4.5


def row(bt, price_df, signal_df, cap, label):
    st = bt.run(price_df, signal_df, initial_capital=cap)["stats"]
    g = bt._check_gate(st)
    ok = "ALL" if g["all_pass"] else ("DD-" if (g["sharpe_ok"] and g["return_ok"]) else "x")
    print(f"{label:>12}{st['annual_return']*100:>8.1f}%{st['sharpe_ratio']:>9.2f}"
          f"{st['max_drawdown']*100:>8.1f}%{st['profit_factor']:>7.2f}{st['total_trades']:>7d}{ok:>7}")


def main():
    builder = HistoricalSignalBuilder()
    builder.selection_cfg = {"sector_cap_enabled": False}
    price_df, sig_noA2 = builder.build(UNIVERSE, START, END)
    builder.selection_cfg = {"sector_cap_enabled": True, "max_per_sector": 2}
    _, sig_A2 = builder.build(UNIVERSE, START, END)

    bt = TaiwanBacktester()
    base_exit = dict(bt.exit_cfg)
    fixed = {"trailing_mode": "fixed"}
    atr = {"trailing_mode": "atr", "atr_mult": ATR_MULT}

    combos = [
        ("baseline", sig_noA2, fixed),
        ("+A1", sig_noA2, atr),
        ("+A2", sig_A2, fixed),
        ("+A1+A2", sig_A2, atr),
    ]
    for cap in CAPS:
        print(f"\n===== 資金 {cap:,}（A1 ATR x{ATR_MULT}）=====")
        print(f"{'設定':>12}{'年化':>9}{'Sharpe':>9}{'回撤':>9}{'PF':>7}{'交易':>7}{'Gate':>7}")
        print("-" * 60)
        for label, sigs, ex in combos:
            bt.exit_cfg = {**base_exit, **ex}
            row(bt, price_df, sigs, cap, label)


if __name__ == "__main__":
    main()

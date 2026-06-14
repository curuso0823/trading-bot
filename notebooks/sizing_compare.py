"""
notebooks/sizing_compare.py
方式A 驗證：在同一 universe / 訊號上，A/B 比較三種部位規模設定對 Sharpe/回撤的影響：
  (1) flat            固定 30%（現況基準）
  (2) vol_only        波動度反比配重，無市場曝險縮放
  (3) vol_target      波動度反比配重 + 市場波動曝險縮放（完整方式A）
訊號只建一次（含 exposure_scalar 欄）；三種設定皆走快取，重跑很快。
用法：.venv\\Scripts\\python.exe notebooks\\sizing_compare.py
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

CONFIGS = [
    ("flat",       {"method": "flat"}),
    ("vol_only",   {"method": "vol_target", "market_vol_scaling": False}),
    ("vol_target", {"method": "vol_target", "market_vol_scaling": True}),
]


def main():
    builder = HistoricalSignalBuilder()
    price_df, signal_df = builder.build(UNIVERSE, START, END)
    if price_df.empty:
        print("無資料")
        sys.exit(1)
    has_exp = "exposure_scalar" in signal_df.columns
    print(f"\n訊號：{int(signal_df['entry_signal'].sum())} 進場 | "
          f"exposure_scalar 欄={'有' if has_exp else '無'} | "
          f"{price_df['date'].min().date()}~{price_df['date'].max().date()}")

    bt = TaiwanBacktester()
    base_sizing = dict(bt.sizing_cfg)  # 保底預設

    for cap in CAPS:
        print(f"\n===== 資金 {cap:,} =====")
        print(f"{'設定':>12}{'年化':>9}{'Sharpe':>9}{'回撤':>9}{'總報酬':>10}{'勝率':>8}{'PF':>7}{'交易':>7}{'Gate':>7}")
        print("-" * 80)
        for name, override in CONFIGS:
            bt.sizing_cfg = {**base_sizing, **override}  # 套用該設定
            st = bt.run(price_df, signal_df, initial_capital=cap)["stats"]
            g = bt._check_gate(st)
            if g["all_pass"]:
                ok = "ALL"
            elif g["sharpe_ok"] and g["return_ok"] and not g["drawdown_ok"]:
                ok = "DD-"
            else:
                ok = "x"
            print(f"{name:>12}{st['annual_return']*100:>8.1f}%{st['sharpe_ratio']:>9.2f}"
                  f"{st['max_drawdown']*100:>8.1f}%{st['total_return']*100:>9.1f}%"
                  f"{st['win_rate']*100:>7.0f}%{st['profit_factor']:>7.2f}"
                  f"{st['total_trades']:>7d}{ok:>7}")


if __name__ == "__main__":
    main()

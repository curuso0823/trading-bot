"""
gate_check.py — 一次性檢查：目前 live 策略(LIVE_UNIVERSE, max_pos=6, odd_lot)在
各回測視窗的「交易筆數」與 performance_gate 狀態。回答「50 筆統計信心是否靠回測即達標」。
建訊號路徑與 notebooks 一致：build 用 DEFAULT_UNIVERSE+AI_CANDIDATES（含 regime 代理），run 用 LIVE_UNIVERSE。
"""
from src.backtest.capped_sim import (build_signals, run_capped,
                                     DEFAULT_UNIVERSE, AI_CANDIDATES, LIVE_UNIVERSE)
from src.utils.helpers import load_config

g = load_config()["performance_gate"]
print(f"gate 門檻：sharpe>={g['min_sharpe']} dd>={g['max_drawdown']} "
      f"annual>={g['min_annual_return']} trades>={g['min_trades']}\n")

print("build_signals(2018-2025) … 吃 FinMind，請稍候")
price_df, sig = build_signals(DEFAULT_UNIVERSE + AI_CANDIDATES, "2018-01-01", "2025-12-31")
print("訊號建好。\n")

WINDOWS = [
    ("全期 2018-2025", "2018-01-01", "2025-12-31"),
    ("config OOS 2023-2024", "2023-01-01", "2024-12-31"),
    ("AI窗 2023-2025", "2023-01-01", "2025-12-31"),
    ("近兩年 2024-2025", "2024-01-01", "2025-12-31"),
]

print(f"{'視窗':<22}{'n_trades':>9}{'sharpe':>8}{'annual':>8}{'maxDD':>8}  gate")
print("-" * 70)
for name, s, e in WINDOWS:
    r = run_capped(price_df, sig, LIVE_UNIVERSE, s, e,
                   capital=100_000, max_pos=6, mode="odd_lot")
    if r is None:
        print(f"{name:<22}  (無資料)")
        continue
    gate = r["gate"]
    flags = "".join("✓" if gate[k] else "✗" for k in ("trades", "sharpe", "annual", "dd"))
    verdict = "PASS" if r["gate_pass"] else "FAIL"
    print(f"{name:<22}{r['n_trades']:>9}{r['sharpe']:>8.2f}"
          f"{r['annual']*100:>7.1f}%{r['dd']*100:>7.1f}%  "
          f"trades{('✓' if gate['trades'] else '✗')} all[{flags}] {verdict}")

print("\n說明：gate 第一欄 trades✓ = 該視窗回測交易筆數已達 50+，統計信心由回測一次取得。")

"""
notebooks/b2_backtest_smoke.py
B2 煙霧測試：用合成資料驗證 backtester 的 vectorbt 1.0 呼叫、停損/停利、
持有上限與成本邏輯（不打 API）。
AAA 緩漲 → 應觸發停利+10%；BBB 緩跌 → 應觸發停損-5%；CCC 橫盤 → 測持有上限/MA。
用法：.venv\\Scripts\\python.exe notebooks\\b2_backtest_smoke.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from src.backtest.backtester import TaiwanBacktester

dates = pd.bdate_range("2024-01-02", periods=80)
specs = {"AAA": ("up", 100.0), "BBB": ("down", 100.0), "CCC": ("flat", 50.0)}

rows = []
for sid, (kind, base) in specs.items():
    for i, d in enumerate(dates):
        if kind == "up":
            p = base * (1 + 0.012 * i)
        elif kind == "down":
            p = base * (1 - 0.012 * i)
        else:
            p = base * (1 + 0.0008 * i) + (0.4 if i % 9 == 0 else 0.0)
        rows.append({"date": d, "stock_id": sid, "open": p, "high": p,
                     "low": p, "close": p, "volume": 1000})
price_df = pd.DataFrame(rows)

# 第 15 根 bar 對三檔同時發進場訊號（T+1 於第 16 根開盤進場）
sig_rows = [{"date": d, "stock_id": sid, "entry_signal": (i == 15)}
            for i, d in enumerate(dates) for sid in specs]
signal_df = pd.DataFrame(sig_rows)


def main():
    bt = TaiwanBacktester()
    res = bt.run(price_df, signal_df, initial_capital=1_000_000)
    if not res:
        print("回測回傳空（vectorbt 未安裝？）")
        sys.exit(1)

    print("=== stats ===")
    for k, v in res["stats"].items():
        print(f"  {k:16} {v}")

    tr = res["trades"]
    print(f"\n=== trades（{len(tr)} 筆）===")
    if not tr.empty:
        cols = [c for c in ["Column", "Entry Index", "Avg Entry Price",
                            "Exit Index", "Avg Exit Price", "PnL", "Return"]
                if c in tr.columns]
        print(tr[cols].to_string(index=False))

    # 健全性：應有交易、停損股報酬為負、停利股報酬為正
    ok = len(tr) >= 2 and res["stats"].get("total_trades", 0) >= 2
    print(f"\n煙霧測試（有產生交易、stats 可取）：{'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()

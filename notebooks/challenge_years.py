"""
notebooks/challenge_years.py
挑戰盤健壯度測試：下載 2018–2025 並分年回測目前定案策略
（odd_lot 滑價 + 方式A vol配重 + ATR max0.09 + regime 濾鏡）。
重點年：2018(美中貿易戰)、2021(少年股神狂熱)、2022(史詩級大空頭)。
輸出：年化 / Sharpe / 回撤 / PF / 交易 / Gate；另量化 #5「同日出場」筆數。
首次執行會下載 2018 起資料（~150 請求，<600/日），之後走快取。
用法：.venv\\Scripts\\python.exe notebooks\\challenge_years.py
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from src.backtest.signal_builder import HistoricalSignalBuilder
from src.backtest.backtester import TaiwanBacktester

UNIVERSE = [
    "2330", "2454", "2303", "2308", "2379", "3034", "3711", "2337", "6415", "3008",
    "2317", "2382", "2357", "2376", "3231", "4938", "2356", "2353",
    "2881", "2882", "2891", "2886", "2884", "2885", "2892", "5880",
    "1301", "1303", "1326", "2002", "1101", "2207",
    "2603", "2609", "2615", "2412", "2912", "1216",
]
START, END = "2018-01-01", "2025-12-31"
CAP = 70_000
YEARS = {
    "2018 美中貿易戰": ("2018-01-01", "2018-12-31"),
    "2019": ("2019-01-01", "2019-12-31"),
    "2020 covid": ("2020-01-01", "2020-12-31"),
    "2021 少年股神": ("2021-01-01", "2021-12-31"),
    "2022 大空頭": ("2022-01-01", "2022-12-31"),
    "2023": ("2023-01-01", "2023-12-31"),
    "2024": ("2024-01-01", "2024-12-31"),
    "2025": ("2025-01-01", "2025-12-31"),
    "全期 18-25": (START, END),
}


def main():
    builder = HistoricalSignalBuilder()
    builder.selection_cfg = {"sector_cap_enabled": False}
    price_df, sig = builder.build(UNIVERSE, START, END)
    if price_df.empty:
        print("無資料"); sys.exit(1)
    print(f"\n資料範圍 {price_df['date'].min().date()} ~ {price_df['date'].max().date()}｜"
          f"標的 {sig['stock_id'].nunique()}｜進場訊號 {int(sig['entry_signal'].sum())}")

    bt = TaiwanBacktester()
    print(f"\n資金 {CAP:,}（odd_lot 滑價 + 方式A vol配重 + ATR max0.09 + regime）")
    print(f"{'年/盤勢':>16}{'年化':>9}{'Sharpe':>9}{'回撤':>9}{'PF':>7}{'交易':>7}{'Gate':>6}")
    print("-" * 64)
    full_pf = None
    for yname, (s, e) in YEARS.items():
        s, e = pd.Timestamp(s), pd.Timestamp(e)
        pdf = price_df[(price_df["date"] >= s) & (price_df["date"] <= e)]
        sdf = sig[(sig["date"] >= s) & (sig["date"] <= e)]
        if sdf.empty or int(sdf["entry_signal"].sum()) == 0:
            print(f"{yname:>16}{'(無訊號/regime空頭整年→不進場)':>40}")
            continue
        res = bt.run(pdf, sdf, initial_capital=CAP)
        st = res["stats"]
        g = bt._check_gate(st)
        ok = "ALL" if g["all_pass"] else ("DD-" if (g["sharpe_ok"] and g["return_ok"]) else "x")
        print(f"{yname:>16}{st['annual_return']*100:>8.1f}%{st['sharpe_ratio']:>9.2f}"
              f"{st['max_drawdown']*100:>8.1f}%{st['profit_factor']:>7.2f}{st['total_trades']:>7d}{ok:>6}")
        if yname.startswith("全期"):
            full_pf = res["portfolio"]

    # #5 量化：全期同日出場（進場日=出場日）筆數
    if full_pf is not None:
        tr = full_pf.trades.records_readable
        ecol = next((c for c in tr.columns if "Entry Index" in c), None)
        xcol = next((c for c in tr.columns if "Exit Index" in c), None)
        if ecol and xcol:
            same = int((tr[ecol] == tr[xcol]).sum())
            print(f"\n#5 同日出場(進場日=出場日)：{same}/{len(tr)} 筆 "
                  f"({same/max(len(tr),1)*100:.1f}%) → {'可忽略' if same/max(len(tr),1) < 0.03 else '需注意'}")


if __name__ == "__main__":
    main()

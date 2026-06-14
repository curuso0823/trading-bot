"""
notebooks/regime_slope_test.py
快修驗證：regime 加「MA60 斜率向上」對熊市的效果。
比 baseline(只要 0050>MA60) vs +斜率(MA60>MA60_N日前, N=10/20)，分年看 2018/2022 等。
資料已快取。用法：.venv\\Scripts\\python.exe notebooks\\regime_slope_test.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from src.backtest.signal_builder import HistoricalSignalBuilder
from src.backtest.backtester import TaiwanBacktester
from src.utils.helpers import load_config

U = ["2330","2454","2303","2308","2379","3034","3711","2337","6415","3008","2317","2382",
     "2357","2376","3231","4938","2356","2353","2881","2882","2891","2886","2884","2885",
     "2892","5880","1301","1303","1326","2002","1101","2207","2603","2609","2615","2412","2912","1216"]
START, END = "2018-01-01", "2025-12-31"
CAP = 70_000
YEARS = {"2018貿易戰": ("2018-01-01","2018-12-31"), "2021股神": ("2021-01-01","2021-12-31"),
         "2022大空頭": ("2022-01-01","2022-12-31"), "2024": ("2024-01-01","2024-12-31"),
         "2025關稅V": ("2025-01-01","2025-12-31"), "全期18-25": (START, END)}


def build(slope, sd):
    b = HistoricalSignalBuilder()
    b.selection_cfg = {"sector_cap_enabled": False}
    b.regime_cfg = {**load_config()["regime"], "require_ma_slope": slope, "ma_slope_days": sd}
    return b.build(U, START, END)


def run_year(bt, price_df, sig, label):
    print(f"\n  {label}")
    print(f"  {'年/盤勢':>12}{'年化':>9}{'Sharpe':>9}{'回撤':>9}{'PF':>7}{'交易':>7}{'Gate':>6}")
    for yname, (s, e) in YEARS.items():
        s, e = pd.Timestamp(s), pd.Timestamp(e)
        pdf = price_df[(price_df["date"]>=s)&(price_df["date"]<=e)]
        sdf = sig[(sig["date"]>=s)&(sig["date"]<=e)]
        if sdf.empty or int(sdf["entry_signal"].sum())==0:
            print(f"  {yname:>12}{'(regime擋下整年→0進場)':>40}"); continue
        st = bt.run(pdf, sdf, initial_capital=CAP)["stats"]; g = bt._check_gate(st)
        ok = "ALL" if g["all_pass"] else ("DD-" if (g["sharpe_ok"] and g["return_ok"]) else "x")
        print(f"  {yname:>12}{st['annual_return']*100:>8.1f}%{st['sharpe_ratio']:>9.2f}"
              f"{st['max_drawdown']*100:>8.1f}%{st['profit_factor']:>7.2f}{st['total_trades']:>7d}{ok:>6}")


def main():
    bt = TaiwanBacktester()
    print(f"資金 {CAP:,}｜regime MA60 斜率快修對照")
    for label, (slope, sd) in {"baseline(無斜率)": (False,10), "+斜率MA60>10日前": (True,10),
                               "+斜率MA60>20日前": (True,20)}.items():
        p, s = build(slope, sd)
        run_year(bt, p, s, label)


if __name__ == "__main__":
    main()

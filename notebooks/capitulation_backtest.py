"""
notebooks/capitulation_backtest.py
P2：投降感知 regime（新版）vs 0050>MA60（舊版）分年回測 2018-2025 @70k。
只差一個閘門（capitulation.enabled），其餘策略完全相同 → 乾淨歸因。
硬底線：救 2022（大空頭）且「不殺」2023/2024（大牛）。

用法：.venv\\Scripts\\python.exe notebooks\\capitulation_backtest.py
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
YEARS = {
    "2018貿易戰": ("2018-01-01", "2018-12-31"), "2019反彈": ("2019-01-01", "2019-12-31"),
    "2020covid": ("2020-01-01", "2020-12-31"), "2021股神": ("2021-01-01", "2021-12-31"),
    "2022大空頭": ("2022-01-01", "2022-12-31"), "2023AI牛": ("2023-01-01", "2023-12-31"),
    "2024AI牛": ("2024-01-01", "2024-12-31"), "2025關稅V": ("2025-01-01", "2025-12-31"),
    "全期18-25": (START, END),
}


def build(cap_enabled: bool, mode: str = "full", failed: bool = True):
    b = HistoricalSignalBuilder()
    b.selection_cfg = {"sector_cap_enabled": False}
    b.cap_cfg = {**load_config().get("capitulation", {}), "enabled": cap_enabled,
                 "allow_mode": mode, "failed_bottom_exit": failed}
    return b.build(U, START, END)


def stats_for(bt, price_df, sig, s, e):
    s, e = pd.Timestamp(s), pd.Timestamp(e)
    pdf = price_df[(price_df["date"] >= s) & (price_df["date"] <= e)]
    sdf = sig[(sig["date"] >= s) & (sig["date"] <= e)]
    if sdf.empty or int(sdf["entry_signal"].sum()) == 0:
        return None
    return bt.run(pdf, sdf, initial_capital=CAP)["stats"]


def fmt(st):
    if st is None:
        return f"{'(0進場)':>34}"
    tr = st.get("total_return", st.get("annual_return", 0))
    return (f"{st['annual_return']*100:>7.1f}%{st['sharpe_ratio']:>8.2f}"
            f"{st['max_drawdown']*100:>8.1f}%{tr*100:>8.1f}%{st['profit_factor']:>6.2f}{st['total_trades']:>5d}")


def main():
    bt = TaiwanBacktester()
    print(f"資金 {CAP:,}｜投降感知 regime + P3失敗底出場 分年回測")
    modes = {                                       # (cap_enabled, allow_mode, failed_bottom_exit)
        "舊版base":    (False, "full", False),       # 0050>MA60
        "擋假反彈":    (True, "block_only", False),  # P2 winner 0.90
        "擋假反彈+P3": (True, "block_only", True),   # P3 是否幫得到 winner？
        "早解鎖+P3":   (True, "unlock_only", True),  # P3 是否救活早解鎖？
        "full+P3":     (True, "full", True),         # 全部
    }
    built = {}
    for name, (en, md, fb) in modes.items():
        print(f"  建立訊號：{name}…")
        built[name] = build(en, md, fb)

    hdr = f"{'年化':>7}{'Shrp':>6}{'回撤':>7}{'筆':>5}"
    print(f"\n{'年/盤勢':>9} │" + "│".join(f" {n:^26} " for n in modes))
    print(f"{'':>9} │" + "│".join(f" {hdr} " for _ in modes))
    print("  " + "─" * 150)
    for yname, (s, e) in YEARS.items():
        cells = []
        for name in modes:
            p, sg = built[name]
            st = stats_for(bt, p, sg, s, e)
            if st is None:
                cells.append(f"{'(0進場)':>26} ")
            else:
                cells.append(f"{st['annual_return']*100:>6.1f}%{st['sharpe_ratio']:>6.2f}"
                              f"{st['max_drawdown']*100:>6.1f}%{st['total_trades']:>5d} ")
        sep = "" if yname != "全期18-25" else "  " + "─" * 150 + "\n"
        print(f"{sep}{yname:>9} │" + "│".join(cells))

    print("\n  關鍵：早解鎖『無P3』vs『+P3』→ P3 是否救活早解鎖（2022 不流血、2025 V 回正）？"
          "\n        full+P3 是否勝過『擋假反彈』(Sharpe 0.90)？")


if __name__ == "__main__":
    main()

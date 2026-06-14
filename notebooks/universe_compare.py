"""
notebooks/universe_compare.py
任務1：38檔(現行) vs 44檔(+6 擴充候選) 8年回測（mp=5 集中策略=現行live）。
看擴充是否改善 Sharpe/DD、新6檔被選頻率、族群分散是否提升。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest.capped_sim import build_signals, run_capped, DEFAULT_UNIVERSE, EXT_CANDIDATES, FULL_UNIVERSE
from src.utils.sectors import get_sector

NAMES = {"1513":"中興電","1519":"華城","2618":"長榮航","2049":"上銀","1795":"美時","3045":"台灣大"}
START, END = "2018-01-01", "2025-12-31"


def main():
    print("建立 44 檔訊號（含 6 擴充，吃 FinMind，首次較慢）…")
    price_df, sig = build_signals(FULL_UNIVERSE, START, END)

    res = {}
    for name, uni in [("38檔(現行)", DEFAULT_UNIVERSE), ("44檔(+6)", FULL_UNIVERSE)]:
        res[name] = run_capped(price_df, sig, uni, START, END, capital=70_000, max_pos=5, mode="odd_lot")

    print(f"\n{'指標':>10}{'38檔(現行)':>14}{'44檔(+6)':>14}")
    for k, lab, f in [("annual","年化",lambda v:f"{v*100:.1f}%"), ("sharpe","Sharpe",lambda v:f"{v:.2f}"),
                      ("dd","最大回撤",lambda v:f"{v*100:.1f}%"), ("pf","PF",lambda v:f"{v:.2f}"),
                      ("win_rate","勝率",lambda v:f"{v*100:.0f}%"), ("n_trades","交易數",lambda v:f"{v}"),
                      ("avg_concurrent","平均並倉",lambda v:f"{v:.1f}")]:
        print(f"{lab:>10}{f(res['38檔(現行)'][k]):>14}{f(res['44檔(+6)'][k]):>14}")

    print(f"\n分年 年化%/Sharpe：{'38檔':>22}{'44檔':>16}")
    for yr in range(2018, 2026):
        a = res["38檔(現行)"]["per_year"].get(yr); b = res["44檔(+6)"]["per_year"].get(yr)
        af = f"{a['ret']*100:>6.1f}%/{a['sharpe']:>5.2f}" if a else "—"
        bf = f"{b['ret']*100:>6.1f}%/{b['sharpe']:>5.2f}" if b else "—"
        print(f"  {yr}{af:>26}{bf:>16}")

    # 新6檔被選頻率 + 族群分散
    ec = res["44檔(+6)"]["entry_counts"]
    print(f"\n新6檔在 44檔版被選進場次數（共 {res['44檔(+6)']['n_trades']} 筆交易）：")
    for s in EXT_CANDIDATES:
        print(f"  {s} {NAMES[s]}({get_sector(s)})：{ec.get(s,0)} 次")
    print(f"  6檔合計：{sum(ec.get(s,0) for s in EXT_CANDIDATES)} 次"
          f"（占總進場 {sum(ec.get(s,0) for s in EXT_CANDIDATES)/max(1,sum(ec.values()))*100:.0f}%）")

    # 族群分散：各版進場的 sector 分布
    for name in ["38檔(現行)", "44檔(+6)"]:
        ec = res[name]["entry_counts"]
        bys = {}
        for s, c in ec.items():
            bys[get_sector(s)] = bys.get(get_sector(s), 0) + c
        tot = sum(bys.values())
        top = sorted(bys.items(), key=lambda x: -x[1])[:5]
        print(f"\n{name} 進場族群分布（前5）：" + "｜".join(f"{k} {v/tot*100:.0f}%" for k, v in top))


if __name__ == "__main__":
    main()

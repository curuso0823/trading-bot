"""
notebooks/validate_expanded_watchlist.py
#1 驗證擴充 watchlist 效果：baseline 35檔(現行 live) vs expanded top-150（由 build_watchlist.py 產出）。
同 live 口徑：capped_sim、block_only、mp=6、odd_lot、100k、2018-2025。
重點看：① 交易筆數是否變多（樣本數目標）② Gate 是否仍 PASS ③ 分年是否退化 ④ 標的多樣性。
注意：live watchlist 設 300（每日掃描 ~331 req 安全）；此處只驗 150（8 年歷史回測 420 fresh req 在 600/hr 內，
      300 需 932 req 超額度 → 完整 300 歷史驗證需分批快取或付費 Sponsor）。
"""
import sys
import os
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest.capped_sim import build_signals, run_capped, LIVE_UNIVERSE

START, END = "2018-01-01", "2025-12-31"
CAP, MP, MODE = 100_000, 6, "odd_lot"

exp = pd.read_csv("data/processed/watchlist_expanded.csv", dtype={"stock_id": str})
UNI150 = exp["stock_id"].head(150).tolist()
print(f"baseline = {len(LIVE_UNIVERSE)} 檔；expanded = {len(UNI150)} 檔（top-150 by turnover）")


def show(tag, st):
    if st is None:
        print(f"\n=== {tag} ===\n  (None)")
        return
    g, py = st["gate"], st["per_year"]
    print(f"\n=== {tag} ===")
    print(f"全期 Sharpe {st['sharpe']:.2f} | DD {st['dd']*100:.1f}% | 年化 {st['annual']*100:.1f}% "
          f"| 交易 {st['n_trades']} | 勝率 {st['win_rate']*100:.0f}% | PF {st['pf']:.2f} "
          f"| 進場標的 {len(st['entry_counts'])} 檔 | Gate {'PASS' if st['gate_pass'] else 'FAIL'} {g}")
    for yr in sorted(py):
        r = py[yr]
        print(f"  {yr}: ret {r['ret']*100:+6.1f}%  Sharpe {r['sharpe']:+.2f}  DD {r['dd']*100:6.1f}%")


print("\n[1/2] building baseline 35（多為快取）…")
pb, sb = build_signals(LIVE_UNIVERSE, START, END)
base = run_capped(pb, sb, LIVE_UNIVERSE, START, END, capital=CAP, max_pos=MP, mode=MODE)
show("baseline 35檔（現行 live）", base)

print("\n[2/2] building expanded 150（~420 fresh req，數分鐘）…")
pe, se = build_signals(UNI150, START, END)
exp_st = run_capped(pe, se, UNI150, START, END, capital=CAP, max_pos=MP, mode=MODE)
show("expanded 150檔", exp_st)

if base and exp_st:
    print(f"\n=== 對照 ===")
    print(f"交易筆數：{base['n_trades']} → {exp_st['n_trades']}（{exp_st['n_trades']-base['n_trades']:+d}）")
    print(f"進場標的數：{len(base['entry_counts'])} → {len(exp_st['entry_counts'])}")
    print(f"全期 Sharpe：{base['sharpe']:.2f} → {exp_st['sharpe']:.2f}｜DD：{base['dd']*100:.1f}% → "
          f"{exp_st['dd']*100:.1f}%｜年化：{base['annual']*100:.1f}% → {exp_st['annual']*100:.1f}%")
    top_new = sorted(exp_st["pnl_by_stock"].items(), key=lambda x: -x[1])[:8]
    print(f"expanded 貢獻前 8 名（含新加入標的）：{top_new}")

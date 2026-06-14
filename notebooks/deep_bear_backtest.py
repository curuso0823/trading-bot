"""
notebooks/deep_bear_backtest.py
#3 深度熊市/急殺收停損 — 分年回測驗證。
設定＝live：capped_sim、LIVE_UNIVERSE(35)、block_only regime、mp=6、odd_lot、100k。
tighten mask = 0050 bearish(跌破MA60/假反彈) 且 (panic vol百分位≥0.85 或 深崩 dd≤-0.15)，
  由 CapitulationClassifier.panic_0050 算（單一真相源，與 live 同口徑）。
判準：改善 2018/2021/2022/2025 壞年的 DD/報酬，且「不殺」2023/24 牛年。
"""
import os
import sys
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.backtest.capped_sim import build_signals, run_capped, LIVE_UNIVERSE
from src.signals.capitulation import CapitulationClassifier
from src.data.fetcher import FinMindFetcher
from src.utils.helpers import load_config

START, END = "2018-01-01", "2025-12-31"
CAP, MP, MODE = 100_000, 6, "odd_lot"

cfg = load_config()
cap_cfg = cfg.get("capitulation", {})

print("building signals (block_only, LIVE_UNIVERSE 35)… 慢，吃 FinMind 快取")
price_df, sig = build_signals(LIVE_UNIVERSE, START, END)

# tighten mask（0050 單一真相源）
px0 = FinMindFetcher().get_daily_price("0050", "2016-01-01", END).set_index("date")["close"]
px0.index = pd.to_datetime(px0.index)
pan = CapitulationClassifier.panic_0050(px0, cap_cfg, 60)
tighten = pan["tighten"]
print(f"tighten 日數：{int(tighten.sum())} / {len(tighten)}（{tighten.mean():.1%}）"
      f"｜deep_bear 日數：{int(pan['deep_bear'].sum())}｜panic 日數：{int(pan['gate_panic'].sum())}")


def show(tag, st):
    if st is None:
        print(f"\n=== {tag} ===\n  (None — 無資料)")
        return
    g, py = st["gate"], st["per_year"]
    print(f"\n=== {tag} ===")
    print(f"全期 Sharpe {st['sharpe']:.2f} | DD {st['dd']*100:.1f}% | 年化 {st['annual']*100:.1f}% "
          f"| 交易 {st['n_trades']} | PF {st['pf']:.2f} | Gate {'PASS' if st['gate_pass'] else 'FAIL'} {g}")
    for yr in sorted(py):
        r = py[yr]
        flag = "  <壞年" if yr in (2018, 2021, 2022, 2025) else ("  <牛年" if yr in (2023, 2024) else "")
        print(f"  {yr}: ret {r['ret']*100:+6.1f}%  Sharpe {r['sharpe']:+.2f}  DD {r['dd']*100:6.1f}%{flag}")


base = run_capped(price_df, sig, LIVE_UNIVERSE, START, END, capital=CAP, max_pos=MP, mode=MODE)
show("baseline（無 deep_bear）", base)

for dbmax in [0.06, 0.05, 0.04]:
    st = run_capped(price_df, sig, LIVE_UNIVERSE, START, END, capital=CAP, max_pos=MP, mode=MODE,
                    tighten_mask=tighten, deep_bear_max=dbmax)
    show(f"deep_bear_max={dbmax} [mask=panic|deep, {int(tighten.sum())}日]", st)

# 最窄解讀：只在「確認深熊」日收停損（user 字面：判定為深度熊市時）
print("\n\n########## mask = deep_bear ONLY（純深熊日，排除廣義 panic/recovery）##########")
db_mask = pan["deep_bear"]
for dbmax in [0.06, 0.05]:
    st = run_capped(price_df, sig, LIVE_UNIVERSE, START, END, capital=CAP, max_pos=MP, mode=MODE,
                    tighten_mask=db_mask, deep_bear_max=dbmax)
    show(f"deep_bear-only max={dbmax} [{int(db_mask.sum())}日]", st)

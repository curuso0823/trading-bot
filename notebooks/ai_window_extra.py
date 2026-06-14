"""mp=6 與 hybrid 的全期(18-25)穩健性補測（35檔 100k）——避免單窗結論。"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest.capped_sim import build_signals, run_capped, DEFAULT_UNIVERSE, AI_CANDIDATES, LIVE_UNIVERSE

price_df, sig = build_signals(DEFAULT_UNIVERSE + AI_CANDIDATES, "2018-01-01", "2025-12-31")
print(f"{'變體':<24}{'年化':>8}{'Sharpe':>7}{'MaxDD':>9}{'PF':>7}{'交易':>5}{'Gate':>6}")
for tag, kw, win in [
    ("全期 mp5 零股(現行)", dict(max_pos=5, mode="odd_lot"), ("2018-01-01", "2025-12-31")),
    ("全期 mp6 零股", dict(max_pos=6, mode="odd_lot"), ("2018-01-01", "2025-12-31")),
    ("全期 mp5 hybrid", dict(max_pos=5, mode="hybrid"), ("2018-01-01", "2025-12-31")),
    ("全期 mp6 hybrid", dict(max_pos=6, mode="hybrid"), ("2018-01-01", "2025-12-31")),
    ("24-25 mp6 零股", dict(max_pos=6, mode="odd_lot"), ("2024-01-01", "2025-12-31")),
    ("2022熊 mp6 零股", dict(max_pos=6, mode="odd_lot"), ("2022-01-01", "2022-12-31")),
    ("2022熊 mp5 零股", dict(max_pos=5, mode="odd_lot"), ("2022-01-01", "2022-12-31")),
]:
    r = run_capped(price_df, sig, LIVE_UNIVERSE, *win, capital=100_000, **kw)
    print(f"{tag:<24}{r['annual']*100:>7.1f}%{r['sharpe']:>7.2f}{r['dd']*100:>8.1f}%{r['pf']:>7.2f}"
          f"{r['n_trades']:>5}{'PASS' if r['gate_pass'] else 'fail':>6}")

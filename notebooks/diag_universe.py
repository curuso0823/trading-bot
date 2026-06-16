"""
notebooks/diag_universe.py
任務診斷（純快取，不打 API）：
  1) 選股漏斗分解：regime → TA(逐條) → 籌碼 → 流動性 → entry，量化每層通過率（答「為何頻率低」）
  2) universe 比較：35(現行) / 38(原始) / 53(全快取候選) 全期 + 分年 PF/Sharpe/DD/年化/交易數
  3) 0050 買進持有 benchmark（同期）
所有資料用 2018-01-01~2025-12-31（快取已存，免 API）。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from src.backtest.capped_sim import (build_signals, run_capped,
                                      DEFAULT_UNIVERSE, AI_CANDIDATES, LIVE_UNIVERSE)
from src.data.fetcher import FinMindFetcher
from src.signals.tech_signal import TechSignal
from src.signals.capitulation import CapitulationClassifier
from src.utils.helpers import load_config

START, END, CAP = "2018-01-01", "2025-12-31", 100_000
FULL53 = sorted(set(DEFAULT_UNIVERSE + AI_CANDIDATES))
cfg = load_config()


def hr(t): print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


# ───────────────────────── build signals once (53 檔) ─────────────────────────
print(f"建訊號（53 檔，{START}~{END}，純快取）…")
price_df, sig = build_signals(FULL53, START, END)
print(f"price_df {len(price_df)} 列；entry 訊號合計 {int(sig['entry_signal'].sum())}")


# ───────────────────────── (1) 選股漏斗分解（35 現行）─────────────────────────
hr("(1) 選股漏斗分解 — 現行 35 檔 watchlist（為何頻率低）")
tech = TechSignal()
ta_cfg = cfg["ta_filter"]; chip_cfg = cfg["chip_scoring"]
f = FinMindFetcher()

# regime（block_only，0050）每日 allow 比例
px0 = f.get_daily_price("0050", "2016-01-01", END)
r0 = CapitulationClassifier.regime_0050(px0.set_index("date")["close"], cfg["capitulation"], 60)
r0 = r0[(r0.index >= START) & (r0.index <= END)]
allow_regime = r0["allow_block_only"]
n_days = len(allow_regime)
print(f"交易日數                : {n_days}")
print(f"regime 允許進場日比例    : {allow_regime.mean()*100:5.1f}%  "
      f"（空頭/假反彈擋下 {(~allow_regime).sum()} 日）")

# 逐檔逐日 TA 各條件通過率（35 檔）
cond_counts = {"above_ma": 0, "ma_up": 0, "vol_surge": 0, "rsi_ok": 0, "ta_all": 0}
chip_ge2 = 0
liq_ok = 0
entry_all = 0
stockday_total = 0
per_stock_entry = {}
for sid in LIVE_UNIVERSE:
    px = f.get_daily_price(sid, START, END)
    if px.empty:
        continue
    d = tech.compute(px).set_index("date")
    d = d[(d.index >= START) & (d.index <= END)]
    ma, rsi = f"ma{tech.ma_period}", f"rsi{tech.rsi_period}"
    c_above = d["close"] > d[ma]
    c_maup = d["ma_slope"] > 0
    c_vol = d["vol_ratio"] >= tech.vol_ratio_min
    c_rsi = (d[rsi] >= tech.rsi_min) & (d[rsi] <= tech.rsi_max)
    c_ta = c_above & c_maup & c_vol & c_rsi
    stockday_total += len(d)
    cond_counts["above_ma"] += int(c_above.sum())
    cond_counts["ma_up"] += int(c_maup.sum())
    cond_counts["vol_surge"] += int(c_vol.sum())
    cond_counts["rsi_ok"] += int(c_rsi.sum())
    cond_counts["ta_all"] += int(c_ta.sum())
    # 籌碼（用已建好的 sig，較快；對齊本檔）
    s_sid = sig[(sig["stock_id"] == sid)].set_index("date")
    if not s_sid.empty:
        sc = s_sid["score"].reindex(d.index).fillna(0)
        chip_ge2 += int((sc >= chip_cfg["min_score"]).sum())
        es = s_sid["entry_signal"].reindex(d.index).fillna(False).astype(bool)
        entry_all += int(es.sum())
        per_stock_entry[sid] = int(es.sum())
    # 流動性
    turnover = (px.set_index("date")["close"] * px.set_index("date")["volume"]).reindex(d.index)
    liq = turnover.rolling(20).mean() >= cfg["trading"]["min_liquidity_turnover"]
    liq_ok += int(liq.sum())

print(f"\n股票-日 總數（35檔×交易日）: {stockday_total}")
print(f"{'層級':<26}{'通過 stock-day':>16}{'佔比':>10}")
print(f"{'  ① 收盤站上 MA20':<26}{cond_counts['above_ma']:>16}{cond_counts['above_ma']/stockday_total*100:>9.1f}%")
print(f"{'  ② MA20 斜率向上':<26}{cond_counts['ma_up']:>16}{cond_counts['ma_up']/stockday_total*100:>9.1f}%")
print(f"{'  ③ 量比 ≥ 1.5x':<26}{cond_counts['vol_surge']:>16}{cond_counts['vol_surge']/stockday_total*100:>9.1f}%")
print(f"{'  ④ RSI 50–80':<26}{cond_counts['rsi_ok']:>16}{cond_counts['rsi_ok']/stockday_total*100:>9.1f}%")
print(f"{'  ①&②&③&④ TA 全中':<26}{cond_counts['ta_all']:>16}{cond_counts['ta_all']/stockday_total*100:>9.2f}%")
print(f"{'  籌碼 score ≥ 2':<26}{chip_ge2:>16}{chip_ge2/stockday_total*100:>9.1f}%")
print(f"{'  流動性達標':<26}{liq_ok:>16}{liq_ok/stockday_total*100:>9.1f}%")
print(f"{'  最終 entry（全閘門）':<26}{entry_all:>16}{entry_all/stockday_total*100:>9.3f}%")

# 每日 entry 訊號分布（35 檔）
sig35 = sig[sig["stock_id"].isin(LIVE_UNIVERSE)]
by_day = sig35.groupby("date")["entry_signal"].sum()
by_day = by_day.reindex(allow_regime.index).fillna(0)
print(f"\n每日 entry 訊號數分布（{n_days} 個交易日）：")
print(f"  0 檔的日數    : {(by_day == 0).sum():4d}（{(by_day==0).mean()*100:.1f}%）  ← 多數日 0 候選")
print(f"  ≥1 檔的日數   : {(by_day >= 1).sum():4d}（{(by_day>=1).mean()*100:.1f}%）")
print(f"  平均/日       : {by_day.mean():.3f} 檔")
print(f"  全期 entry 訊號總數: {int(by_day.sum())}（注意：訊號≠成交，受並倉上限 6 與資金限制）")


# ───────────────────────── (2) universe 比較 ─────────────────────────
hr("(2) universe 比較 — 35 現行 / 38 原始 / 53 全候選（100k, mp=6, 零股, 現行config）")
variants = {"35 現行(LIVE)": LIVE_UNIVERSE,
            "38 原始(DEFAULT)": DEFAULT_UNIVERSE,
            "53 全候選(+AI15)": FULL53}
res = {name: run_capped(price_df, sig, uni, START, END, capital=CAP, max_pos=6, mode="odd_lot")
       for name, uni in variants.items()}
cols = list(variants)
print(f"\n{'指標':>14}" + "".join(f"{c:>20}" for c in cols))
rows = [("annual", "年化", lambda v: f"{v*100:.1f}%"), ("sharpe", "Sharpe", lambda v: f"{v:.2f}"),
        ("dd", "最大回撤", lambda v: f"{v*100:.1f}%"), ("pf", "獲利因子PF", lambda v: f"{v:.2f}"),
        ("win_rate", "勝率", lambda v: f"{v*100:.0f}%"), ("n_trades", "交易筆數", lambda v: f"{v}"),
        ("avg_concurrent", "平均並倉", lambda v: f"{v:.1f}"),
        ("total_return", "總報酬", lambda v: f"{v*100:.0f}%"),
        ("gate_pass", "Gate", lambda v: "PASS" if v else "FAIL")]
for k, lab, fmt in rows:
    print(f"{lab:>14}" + "".join(f"{fmt(res[c][k]):>20}" for c in cols))
print(f"{'交易/年':>14}" + "".join(f"{res[c]['n_trades']/8:>19.1f}" for c in cols))

print(f"\n分年 報酬%/Sharpe/DD%：")
print(f"{'年':>6}" + "".join(f"{c:>24}" for c in cols))
for yr in range(2018, 2026):
    line = f"{yr:>6}"
    for c in cols:
        y = res[c]["per_year"].get(yr)
        cell = f"{y['ret']*100:>6.1f}/{y['sharpe']:>4.1f}/{y['dd']*100:>5.1f}" if y else "—"
        line += f"{cell:>24}"
    print(line)


# ───────────────────────── (3) 0050 benchmark ─────────────────────────
hr("(3) 0050 買進持有 benchmark（同期 2018–2025）")
p = px0[(px0["date"] >= START) & (px0["date"] <= END)].set_index("date")["close"]
ret = p.pct_change().dropna()
yrs = len(p) / 252
cagr = (p.iloc[-1] / p.iloc[0]) ** (1 / yrs) - 1
sharpe = ret.mean() / ret.std() * np.sqrt(252)
dd = (p / p.cummax() - 1).min()
print(f"  年化 {cagr*100:.1f}%  Sharpe {sharpe:.2f}  最大回撤 {dd*100:.1f}%  總報酬 {(p.iloc[-1]/p.iloc[0]-1)*100:.0f}%")
print(f"  分年報酬%：", end="")
for yr in range(2018, 2026):
    py = p[p.index.year == yr]
    if len(py) > 5:
        print(f" {yr}:{(py.iloc[-1]/py.iloc[0]-1)*100:+.0f}", end="")
print()

print("\n[done]")

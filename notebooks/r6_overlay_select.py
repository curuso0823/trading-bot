"""
notebooks/r6_overlay_select.py
R6 選參 — 在快取 0050 上特徵化「vol-target + MA overlay」被動變體（使用者選的口味）。純快取、0 API、不改 live。

使用者意圖（白話）：平時跟從 0050，唯 0050 跌破某 threshold 才退（持續監測），漲回 threshold 就再跟上去。
  → 對應 live benchmark 引擎的 regime_overlay：close < MA(regime_ma) 當日砍曝險（half=減半／zero=歸零），
    回到 MA 上方自動恢復。threshold＝MA；half/zero＝退多深；base vol＝平時曝險（高→平時≈滿倉跟 0050）。

本腳本掃 base∈{≈BH, 0.011} × MA∈{60,120,200} × action∈{half,zero}，報 full+OOS(2022–25) Sharpe/Calmar/maxDD/
年化、2022/2020 崩盤段 DD、OOS 進出切換次數（whipsaw 代理）、平均曝險（平時多滿）→ 依使用者意圖選參。
複用 notebooks/benchmark_backtest.py 的 simulate_benchmark / simulate_buyhold / vol_target_exposure（同 live 引擎口徑）。

用法：.venv/bin/python notebooks/r6_overlay_select.py
"""
import os
import sys
import importlib.util

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
NB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(NB_DIR)
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

_spec = importlib.util.spec_from_file_location("benchmark_backtest", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

FWD = [2022, 2023, 2024, 2025]
SQRT252 = np.sqrt(252)
BH_BASE_VOL = 0.05      # 「≈買持」base：target_vol 高使曝險恆滿（0.05/realized_vol≫1 → clip 1.0）＝「平時跟 0050」


def m_full(eq):
    r = eq.pct_change().dropna()
    sh = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    ann = float((eq.iloc[-1] / eq.iloc[0]) ** (252 / len(eq)) - 1)
    dd = float((eq / eq.cummax() - 1).min())
    return sh, ann, dd


def m_oos(eq):
    e = eq[eq.index.year.isin(FWD)]
    r = e.pct_change().dropna()
    sh = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    ann = float((e.iloc[-1] / e.iloc[0]) ** (252 / len(e)) - 1)
    dd = float((e / e.cummax() - 1).min())
    cal = ann / abs(dd) if abs(dd) > 1e-9 else float("nan")
    return sh, ann, dd, cal


def crash_dd(eq, lo, hi):
    w = eq[(eq.index >= pd.Timestamp(lo)) & (eq.index <= pd.Timestamp(hi))]
    return float((w / w.cummax() - 1).min()) if len(w) > 2 else float("nan")


def switches_avgexp(close_full, base_vol, ma, action):
    """OOS 期間進出切換次數（below-MA 狀態翻轉）＋平均曝險（平時多滿）。"""
    exp = bm.vol_target_exposure(close_full, target_daily_vol=base_vol, lookback=20, exposure_cap=1.0,
                                 regime_overlay=True, regime_ma=ma, regime_action=action)
    ma_s = close_full.rolling(ma).mean()
    below = (close_full < ma_s).fillna(False)
    oos = close_full.index.year.isin(FWD)
    sw = int((below[oos].astype(int).diff().abs() == 1).sum())     # 每 2 次＝一次完整退出+回補
    return sw, float(exp[oos].mean())


# ───────────────────────── 跑 ─────────────────────────
print("R6 overlay 選參 | 載入快取 0050（純快取、0 API）…")
adj = bm.load_adjusted_0050()
close_full = adj.set_index("date")["close"].sort_index().astype(float)

bh = bm.simulate_buyhold(adj)
benb = bm.simulate_benchmark(adj, 0.011)

rows = []
# 參考：純買持、基準B
for name, st in [("0050 純買持", bh), ("基準B(vol0.011,無overlay)", benb)]:
    eq = st["equity"]
    fsh, fann, fdd = m_full(eq)
    osh, oann, odd, ocal = m_oos(eq)
    rows.append((name, fsh, fdd, osh, ocal, odd, oann, crash_dd(eq, "2022-01-01", "2022-12-31"),
                 crash_dd(eq, "2020-02-01", "2020-04-30"), 0, float("nan")))

# overlay 變體：base∈{≈BH, 0.011} × MA∈{60,120,200} × action∈{half,zero}
for base_label, base_vol in [("≈BH", BH_BASE_VOL), ("vol.011", 0.011)]:
    for ma in [60, 120, 200]:
        for action in ["half", "zero"]:
            st = bm.simulate_benchmark(adj, base_vol, overlay=True, regime_ma=ma, regime_action=action)
            eq = st["equity"]
            fsh, fann, fdd = m_full(eq)
            osh, oann, odd, ocal = m_oos(eq)
            sw, avgexp = switches_avgexp(close_full, base_vol, ma, action)
            rows.append((f"{base_label}+MA{ma}{action}", fsh, fdd, osh, ocal, odd, oann,
                         crash_dd(eq, "2022-01-01", "2022-12-31"), crash_dd(eq, "2020-02-01", "2020-04-30"), sw, avgexp))

print("\n" + "=" * 128)
print("R6 被動 overlay 變體（快取 0050；『平時跟 0050、跌破 MA 退、漲回再跟』＝regime_overlay）｜OOS=2022–25")
print("=" * 128)
hdr = (f"{'變體':<22}{'全期Sh':>7}{'全期DD%':>8}{'OOS_Sh':>7}{'OOS_Cal':>8}{'OOS_DD%':>8}{'OOS年化%':>8}"
       f"{'2022段DD%':>10}{'2020段DD%':>10}{'OOS切換':>8}{'平均曝險':>9}")
print(hdr)
print("-" * 128)
for (name, fsh, fdd, osh, ocal, odd, oann, dd22, dd20, sw, avgexp) in rows:
    ae = f"{avgexp*100:>8.0f}%" if avgexp == avgexp else f"{'—':>9}"
    print(f"{name:<22}{fsh:>7.2f}{fdd*100:>8.1f}{osh:>7.2f}{ocal:>8.2f}{odd*100:>8.1f}{oann*100:>8.1f}"
          f"{dd22*100:>10.1f}{dd20*100:>10.1f}{sw:>8d}{ae}")
print("=" * 128)
print("讀法：使用者要『平時跟 0050(平均曝險高)、跌破 MA 退、漲回再跟』。")
print("  · base≈BH 平時曝險≈100%（真的跟 0050）；base vol.011 平時≈80–90%（已先 de-risk）。")
print("  · MA60＝threshold 較近、反應快但切換多(whipsaw、成本高)；MA200＝平滑、少切換但較鈍(退得晚、回得晚)。")
print("  · zero＝跌破全退現金（保護強、whipsaw 痛）；half＝減半（溫和）。")
print("  · 挑：OOS Calmar 高、2022 段 DD 淺、OOS 切換不過多、平均曝險高（符合『平時跟 0050』）的折衷。")
print("\n[done] R6 選參特徵化完成。依表選定 (base, MA, action) → 寫進 config/settings.yaml strategy.benchmark。")

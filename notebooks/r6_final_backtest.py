"""
notebooks/r6_final_backtest.py
R6 最終策略分年回測：0050 vol-managed（target_vol 0.011）+ MA200-zero 最後防線
（平時 vol-target 跟 0050；唯 0050 跌破 MA200 → 全退現金，漲回 MA200 → 全進）。
＝live `r6-passive-landing` 的 config 口徑。純快取、0 API。對照 0050 純買持、基準B（vol0.011 無 overlay）。

⚠️ 不與舊 active 35 檔比較（其回測受後見之明/survivorship 污染＝本重建起因）。
   0050 單一 ETF 無 survivorship；但單一市場/單一期間 power 有限、MA200/vol0.011 為**結構性選參**（非 OOS-fit）
   → 此為**描述性特徵化**、非「證實超額」（R5 已定：無顯著 alpha）。

用法：.venv/bin/python notebooks/r6_final_backtest.py
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

_spec = importlib.util.spec_from_file_location("bm", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

SQRT252 = np.sqrt(252)
FWD = [2022, 2023, 2024, 2025]


def agg(eq):
    r = eq.pct_change().dropna()
    sh = float(r.mean() / r.std() * SQRT252) if r.std() > 0 else 0.0
    ann = float((eq.iloc[-1] / eq.iloc[0]) ** (252 / len(eq)) - 1)
    dd = float((eq / eq.cummax() - 1).min())
    return ann, sh, dd, (ann / abs(dd) if abs(dd) > 1e-9 else float("nan"))


def oos_agg(eq):
    return agg(eq[eq.index.year.isin(FWD)])


print("R6 最終策略分年回測 | 載入快取 0050（0 API）…")
adj = bm.load_adjusted_0050()
final = bm.simulate_benchmark(adj, 0.011, overlay=True, regime_ma=200, regime_action="zero")
benb = bm.simulate_benchmark(adj, 0.011, overlay=False)
bh = bm.simulate_buyhold(adj)
S = {"R6最終": final, "0050買持": bh, "基準B": benb}
PY = {k: bm._per_year(v["equity"]) for k, v in S.items()}

print("\n" + "=" * 96)
print("分年表（每格＝報酬% / Sharpe / 年內最大回撤%）｜R6最終＝0050 vol-mgd(0.011) + MA200-zero 最後防線")
print("=" * 96)
print(f"{'年':>6}{'R6最終':>27}{'0050純買持':>27}{'基準B(無防線)':>27}")


def cell(t):
    return f"{t[0]*100:>7.1f}% /{t[1]:>5.2f} /{t[2]*100:>6.1f}%" if t else f"{'—':>22}"


for y in range(2018, 2026):
    tag = "" if y in FWD else " "
    print(f"{y:>6}{cell(PY['R6最終'].get(y)):>27}{cell(PY['0050買持'].get(y)):>27}{cell(PY['基準B'].get(y)):>27}")
print("（2022–25＝R5 OOS 窗；2018–21＝其前。參數為結構性選、非分年 fit）")

print("-" * 96)
print(f"{'區間 / 指標':<18}{'R6最終':>14}{'0050純買持':>14}{'基準B':>14}")
for label, fn in [("全期 2018-25", agg), ("OOS 2022-25", oos_agg)]:
    a = {k: fn(v["equity"]) for k, v in S.items()}
    print(f"{label+' 年化%':<18}{a['R6最終'][0]*100:>14.1f}{a['0050買持'][0]*100:>14.1f}{a['基準B'][0]*100:>14.1f}")
    print(f"{'  Sharpe':<18}{a['R6最終'][1]:>14.2f}{a['0050買持'][1]:>14.2f}{a['基準B'][1]:>14.2f}")
    print(f"{'  maxDD%':<18}{a['R6最終'][2]*100:>14.1f}{a['0050買持'][2]*100:>14.1f}{a['基準B'][2]*100:>14.1f}")
    print(f"{'  Calmar':<18}{a['R6最終'][3]:>14.2f}{a['0050買持'][3]:>14.2f}{a['基準B'][3]:>14.2f}")

# MA200 最後防線觸發（目標曝險訊號；實際持倉受月度/5pp 帶再平滑）
close = adj.set_index("date")["close"].sort_index().astype(float)
exp = bm.vol_target_exposure(close, target_daily_vol=0.011, lookback=20, exposure_cap=1.0,
                             regime_overlay=True, regime_ma=200, regime_action="zero")
ma = close.rolling(200).mean()
below = close < ma
print("\n" + "=" * 96)
print("MA200 最後防線活動（per year；目標曝險訊號）：平均曝險% / 全退現金天數(exp=0) / 該年曾跌破 MA200")
print("=" * 96)
for y in range(2018, 2026):
    m = close.index.year == y
    if m.sum() < 5:
        continue
    ey, by = exp[m], below[m]
    print(f"{y:>6}   平均目標曝險 {ey.mean()*100:>5.0f}%   全退天數 {int((ey <= 1e-9).sum()):>4}   曾跌破MA200 {'是' if bool(by.any()) else '否'}")

print("\n讀法：MA200 最後防線只在『曾跌破』年觸發（全退天數>0）；其餘年平時 vol-managed 跟 0050。")
print("⚠️ 描述性、非證實超額：R5 已定無顯著 alpha；overlay 前瞻＝降深熊 DD、但 MA 附近 whipsaw、牛市≈跟 0050。survivorship 不適用 0050、但單期 power 有限。")
print("\n[done] R6 最終策略分年回測完成（純快取）。")

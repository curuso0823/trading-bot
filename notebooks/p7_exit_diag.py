"""
notebooks/p7_exit_diag.py
Phase 7 診斷（不動引擎，只用既有 run_capped 參數，純快取）。

問題（缺失#4）：趨勢策略卻在大多頭年慘敗 —— 2024（0050 +49%）只賺 ~+7~10%、2020（+30%）只賺 +17.5%。
假說：ATR 移動停損 clip 在 [0.08,0.09]（最寬 9% 韁繩）對高波動 AI/電子太緊，正常回檔就被洗出、之後難追回。

⚠️ reframe（Phase 6 已知）：無條件放寬停損（atr_hi→0.15）+ 拉長 max_hold 並未改善 2024 捕獲。
   本診斷要回答的核心問題：2024 的慘敗到底是
     (A) exit 問題 —— 有進到主升股、但被早停損咬掉（whipsaw），放寬出場救得回；還是
     (B) participation/結構問題 —— 主升股根本沒進場 / 6 格常空著，放寬出場救不了（要改 universe/格數）。

決策閘：
  · kill-switch 探針（拿掉停損上限 clip + 關 max_hold）若仍救不回 2024/2020 捕獲 → 偏 (B)。
  · 2024 participation 拆解（avg 並倉、進場次數、主升股是否進場）→ 佐證 (A) vs (B)。
  → 若指向 (B)：停手，不做 regime 連動停損實驗（p7_regime_stops.py），文件結論改走 Phase 9/重訪 Phase 6 加格。
  → 若指向 (A)：才做引擎 widen_mask 改造 + p7_regime_stops.py。

本檔不改 live config、不改引擎。用法：.venv/bin/python notebooks/p7_exit_diag.py
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.backtest.capped_sim import build_signals, run_capped, LIVE_UNIVERSE
from src.data.fetcher import FinMindFetcher

START, END, CAP, MP = "2018-01-01", "2025-12-31", 100_000, 6
YEARS = list(range(2018, 2026))
BULL_FOCUS = [2020, 2024]   # 規格點名的大多頭年（預先固定，不調參）
BEAR_FOCUS = [2022]         # 熊市防禦年


def calmar(annual, dd):
    return annual / abs(dd) if dd and abs(dd) > 1e-9 else float("nan")


def cap_ratio(strat, bench):
    """捕獲率＝策略年報酬 / 0050 年報酬（同號才有意義；bench≈0 回 nan）。"""
    if bench is None or bench != bench or abs(bench) < 1e-9:
        return float("nan")
    return strat / bench


# ───────────────────────── 0050 逐年買進持有（捕獲率分母）─────────────────────────
print("抓 0050 還原日K（2016 暖機，純快取）…")
px0 = FinMindFetcher().get_daily_price("0050", "2016-01-01", END).set_index("date")["close"]
px0.index = pd.to_datetime(px0.index)
px0 = px0.sort_index().astype(float)
b0 = {}   # 0050 逐年買進持有報酬
for y in YEARS:
    sy = px0[px0.index.year == y]
    if len(sy) >= 5:
        b0[y] = float(sy.iloc[-1] / sy.iloc[0] - 1)
print("0050 逐年買進持有：" + "  ".join(f"{y} {b0.get(y, float('nan'))*100:+.0f}%" for y in YEARS))


# ───────────────────────── build signals ONCE ─────────────────────────
print(f"\n建訊號（{len(LIVE_UNIVERSE)} 檔 LIVE_UNIVERSE，{START}~{END}，純快取）…")
price_df, sig = build_signals(LIVE_UNIVERSE, START, END)


def run(label, **kw):
    st = run_capped(price_df, sig, LIVE_UNIVERSE, START, END, capital=CAP, max_pos=MP, mode="odd_lot", **kw)
    st["_label"] = label
    return st


# ───────────────────────── ① baseline 逐年 策略 vs 0050 + 捕獲率 ─────────────────────────
base = run("baseline(現行 60/0.09)")
print("\n" + "=" * 96)
print("① baseline 逐年：策略 vs 0050 買進持有（捕獲率＝策略/0050）")
print(f"全期：年化 {base['annual']*100:.1f}% / Sharpe {base['sharpe']:.2f} / Calmar {calmar(base['annual'],base['dd']):.2f} "
      f"/ DD {base['dd']*100:.1f}% / 交易 {base['n_trades']}（{base['n_trades']/8:.1f}/年）/ avg並倉 {base['avg_concurrent']:.1f}")
print("=" * 96)
print(f"{'年':>6}{'策略%':>9}{'0050%':>9}{'捕獲率':>9}{'註':>10}")
for y in YEARS:
    s = base["per_year"].get(y, {}).get("ret")
    s = s * 100 if s is not None else float("nan")
    bv = b0.get(y)
    cr = cap_ratio(s / 100 if s == s else float("nan"), bv)
    note = "  ←大多頭" if (bv is not None and bv > 0.25) else ("  ←熊市" if (bv is not None and bv < 0) else "")
    print(f"{y:>6}{s:>9.1f}{(bv*100 if bv is not None else float('nan')):>9.1f}{cr:>9.2f}{note}")
print(f"\n大多頭年捕獲率（{BULL_FOCUS}）＝"
      + "  ".join(f"{y}:{cap_ratio(base['per_year'].get(y,{}).get('ret',float('nan')), b0.get(y)):.2f}" for y in BULL_FOCUS)
      + f"｜熊市年捕獲率（{BEAR_FOCUS}）＝"
      + "  ".join(f"{y}:{cap_ratio(base['per_year'].get(y,{}).get('ret',float('nan')), b0.get(y)):.2f}" for y in BEAR_FOCUS))


# ───────────────────────── ② kill-switch 探針（拆解 stop / max_hold）─────────────────────────
# atr_hi=0.30 → 實質拿掉 9% 上限 clip（多數股回到「完整 ATR 韁繩」）；max_hold=99999 → 關時間停損。
probes = [
    ("baseline      (60 / 0.09)", {}),
    ("寬停損A        (60 / 0.30)", dict(atr_hi=0.30)),
    ("關max_holdB    (off/ 0.09)", dict(max_hold=99999)),
    ("兩者全開C      (off/ 0.30)", dict(atr_hi=0.30, max_hold=99999)),
]
print("\n" + "=" * 96)
print("② kill-switch 探針：給「最大出場餘裕」能否救回大多頭捕獲？（同時看交易數＝slot 佔用混淆）")
print("   若 C 仍救不回 2024/2020 → exits 不是 #4 槓桿（偏 participation/結構問題）")
print("=" * 96)
hdr = f"{'設定':<20}{'年化%':>8}{'Sharpe':>8}{'DD%':>8}{'交易':>7}"
for y in BULL_FOCUS + BEAR_FOCUS:
    hdr += f"{str(y)+'%':>8}{str(y)+'×':>7}"
print(hdr)
for label, kw in probes:
    st = run(label, **kw)
    row = f"{label:<20}{st['annual']*100:>8.1f}{st['sharpe']:>8.2f}{st['dd']*100:>8.1f}{st['n_trades']:>7}"
    for y in BULL_FOCUS + BEAR_FOCUS:
        r = st["per_year"].get(y, {}).get("ret", float("nan"))
        row += f"{r*100:>8.1f}{cap_ratio(r, b0.get(y)):>7.2f}"
    print(row)
print("（×＝捕獲率＝策略/0050；交易數大跌＝寬停損/關max_hold 讓部位久不出場、壓低新進場，須一起讀）")


# ───────────────────────── ③ 2024 participation 拆解 ─────────────────────────
# 重用同一份訊號、把區間切到 2024（cold-start：前 ~20 日 rolling NaN → sizing/trail 用 fallback，早段並倉略低估）。
y24 = run_capped(price_df, sig, LIVE_UNIVERSE, "2024-01-01", "2024-12-31",
                 capital=CAP, max_pos=MP, mode="odd_lot")
ec24 = y24["entry_counts"]
pnl24 = y24["pnl_by_stock"]
print("\n" + "=" * 96)
print("③ 2024 participation 拆解（區間切片重跑；cold-start 早段並倉略低估，須配合全期 entry_counts 讀）")
print("=" * 96)
print(f"2024 切片：年化 {y24['annual']*100:.1f}% / avg 並倉 {y24['avg_concurrent']:.2f}（上限 {MP}）"
      f" / 進場 {sum(ec24.values())} 次 / 進場過的標的 {len(ec24)} 檔 / 交易 {y24['n_trades']}")
if y24["avg_concurrent"] < MP * 0.7:
    print(f"⚠️ 2024 avg 並倉 {y24['avg_concurrent']:.2f} ≪ 上限 {MP} → 格子常空著＝participation 不足（偏結構問題 B）")
else:
    print(f"  2024 avg 並倉 {y24['avg_concurrent']:.2f} 接近上限 → 格子有填滿，慘敗較可能來自 exit（偏 A）")
print("\n2024 進場次數（前 12）：")
for s, c in sorted(ec24.items(), key=lambda x: -x[1])[:12]:
    print(f"   {s}: {c} 次  (2024 PnL {pnl24.get(s, 0.0):+.0f})")
print("2024 PnL 貢獻（前/後 各 6）：")
for s, v in sorted(pnl24.items(), key=lambda x: -x[1])[:6]:
    print(f"   +  {s}: {v:+.0f}")
for s, v in sorted(pnl24.items(), key=lambda x: x[1])[:6]:
    print(f"   -  {s}: {v:+.0f}")


# ───────────────────────── ④ 全期 進場/貢獻（主升股是否進場）─────────────────────────
ec = base["entry_counts"]
pnl = base["pnl_by_stock"]
never = [s for s in LIVE_UNIVERSE if ec.get(s, 0) == 0]
print("\n" + "=" * 96)
print("④ 全期（2018–25）進場分佈：主升股有沒有被選到？")
print("=" * 96)
print(f"35 檔中全期從未進場：{len(never)} 檔 → {never}")
print("全期進場最多（前 10）：")
for s, c in sorted(ec.items(), key=lambda x: -x[1])[:10]:
    print(f"   {s}: {c} 次  (全期 PnL {pnl.get(s, 0.0):+.0f})")


# ───────────────────────── 決策閘摘要 ─────────────────────────
print("\n" + "-" * 96)
print("決策閘讀法：")
print("  · ② C（兩者全開）2024/2020 捕獲率若仍未明顯跳升 → exits 非槓桿 → 偏 (B) 結構問題。")
print("  · ③ 2024 avg 並倉若 ≪ 6 或主升股進場次數低 → participation 不足 → 偏 (B)。")
print("  → 偏 (B)：停手，不做 p7_regime_stops.py，文件結論改走 Phase 9（universe）/重訪 Phase 6（加格）。")
print("  → 偏 (A)（捕獲明顯跳升且格子有填滿但被早停咬掉）：才做引擎 widen_mask + p7_regime_stops.py。")
print("\n[done]")

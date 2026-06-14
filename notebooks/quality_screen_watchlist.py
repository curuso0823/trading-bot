"""
notebooks/quality_screen_watchlist.py
#1b controlled quality-screen 擴充：不用純流動性(已證毀 edge)，改用「3 年 CAGR ≥ 0050」前瞻性動能篩
（= user 既有 AI 選股法）從流動池選 quality leaders，加到 curated 35，控制總數，驗證是否：
  ① 交易筆數↑（樣本目標）② edge 不像純流動性那樣崩（Gate 仍 PASS）。
⚠️ look-ahead caveat：watchlist 為前瞻性策展（與 curated 35 同口徑用近期動能），全期回測偏樂觀；真驗在 paper。
   故重看 AI 窗 2023-25 + 「保住 edge vs 毀掉 edge」的相對比較，而非全期絕對值。
資料多已快取（validate_expanded 跑過 top-150）→ 便宜。
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
from src.data.fetcher import FinMindFetcher

START, END, AISTART = "2018-01-01", "2025-12-31", "2023-01-01"
CAP, MP, MODE = 100_000, 6, "odd_lot"
f = FinMindFetcher()


def cagr3(sid):
    """3 年 CAGR + 近 1 年報酬（還原價）。資料不足回 (None, None)。"""
    df = f.get_daily_price(sid, START, END)
    if df.empty or len(df) < 300:
        return None, None
    col = "adj_close" if "adj_close" in df.columns else "close"
    s = df[col].astype(float).values
    n = len(s)
    r3 = s[-1] / s[max(0, n - 756)] - 1
    yrs = min(3.0, (n - 1) / 252)
    c = (1 + r3) ** (1 / max(1e-9, yrs)) - 1 if (1 + r3) > 0 else -1.0
    r1 = s[-1] / s[max(0, n - 252)] - 1
    return c, r1


c0050, _ = cagr3("0050")
print(f"0050 3yr CAGR ≈ {c0050*100:.0f}%（前瞻性 benchmark）")

exp = pd.read_csv("data/processed/watchlist_expanded.csv", dtype={"stock_id": str})
pool = exp["stock_id"].head(150).tolist()       # 流動池（已快取）
rows = []
for sid in pool:
    c, r1 = cagr3(sid)
    if c is None:
        continue
    rows.append({"stock_id": sid, "cagr3": c, "r1y": r1,
                 "quality": bool(c >= c0050 and r1 > 0)})
scr = pd.DataFrame(rows).sort_values("cagr3", ascending=False).reset_index(drop=True)
leaders = scr[scr["quality"]]["stock_id"].tolist()
base35 = set(LIVE_UNIVERSE)
adds = [s for s in leaders if s not in base35]                       # 不重複 curated 35
print(f"流動池 150 → quality leaders(CAGR≥0050 且 1yr>0)：{len(leaders)} 檔；"
      f"扣掉已在 35 的，可加 {len(adds)} 檔")

# 最大集合一次建訊號，子集用 run_capped 切（省 FinMind）
SIZES = [n for n in [40, 45, 50, 55, 61] if n - 35 <= len(adds)] or [35 + len(adds)]
uni_max = LIVE_UNIVERSE + adds[:max(SIZES) - 35]
print(f"\nbuilding signals（uni={len(uni_max)}，多為快取）…")
pdf, sig = build_signals(uni_max, START, END)


def stat(uni, start):
    return run_capped(pdf, sig, uni, start, END, capital=CAP, max_pos=MP, mode=MODE)


def line(tag, st):
    if st is None:
        print(f"  {tag:<22} (None)")
        return
    g = "PASS" if st["gate_pass"] else "FAIL"
    print(f"  {tag:<22} Sharpe {st['sharpe']:.2f} | DD {st['dd']*100:6.1f}% | 年化 {st['annual']*100:5.1f}% "
          f"| 交易 {st['n_trades']:>3} | 進場 {len(st['entry_counts']):>2}檔 | Gate {g}")


print("\n=== 全期 2018-2025 ===")
line("baseline 35 (curated)", stat(LIVE_UNIVERSE, START))
print("  --- 對照：純流動性 150 已驗 = Sharpe 0.70 / DD -22.1% / Gate FAIL ---")
for n in SIZES:
    line(f"quality {n} (35+{n-35})", stat(LIVE_UNIVERSE + adds[:n - 35], START))

print("\n=== AI 窗 2023-2025（前瞻性名單的主場）===")
line("baseline 35 (curated)", stat(LIVE_UNIVERSE, AISTART))
for n in SIZES:
    line(f"quality {n} (35+{n-35})", stat(LIVE_UNIVERSE + adds[:n - 35], AISTART))

print(f"\n加入的 quality leaders（前 15，by 3yr CAGR）：")
add_df = scr[scr["stock_id"].isin(adds)].head(15)
exp_idx = exp.set_index("stock_id")
for _, r in add_df.iterrows():
    nm = exp_idx.loc[r["stock_id"], "name"] if r["stock_id"] in exp_idx.index else ""
    print(f"  {r['stock_id']} {nm:<6} 3yrCAGR {r['cagr3']*100:5.0f}%  1yr {r['r1y']*100:+5.0f}%")

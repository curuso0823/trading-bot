"""
notebooks/p6_exit_linkage.py
Phase 6 配套C — 出場連動敏感度（純快取，不打 API）。

接續 p6_maxpos_sweep.py 的結論：配套A（風險預算守恆）能把 DD/分散度控住，但會稀釋年化 →
無格通過 Gate。本檔問：高 N 守恆格有 DD headroom（-12~-14% vs 軟線 -18%），
「放寬出場」（更寬 ATR 上限 / 更長或關閉 max_hold）能否把 headroom 換回年化、且不破 DD？
並特別看 2024（0050 +49%，本策略僅 +7.2%＝缺失#4）的大多頭捕獲率 與 2022（熊市）的防禦。

候選（接 p6_maxpos_sweep）：固定N=6（控制組）、守恆N=15、守恆N=20。
grid = max_hold ∈ {40,60,90,off} × atr_hi ∈ {0.09現行, 0.12, 0.15}。atr_lo 固定 0.08、atr_mult 固定 4.5。

⚠️ max_hold / atr_hi 是 Phase 7（出場改造）的共用槓桿；本檔僅在 Phase 6 頻率脈絡下做敏感度，
   最終出場改造（regime 連動停損 / 分批停利 / 加碼 / max_hold 重定義）的 A/B 屬 Phase 7，不在此決策。
本檔不改 live config。用法：.venv/bin/python notebooks/p6_exit_linkage.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest.capped_sim import build_signals, run_capped, LIVE_UNIVERSE

START, END, CAP = "2018-01-01", "2025-12-31", 100_000
N_YEARS = 8
MAXHOLD_GRID = [40, 60, 90, 99999]      # 99999 = 實質關閉時間停損
ATRHI_GRID = [0.09, 0.12, 0.15]
# (label, max_pos, size_min, size_max)；size ∝ 6/N（配套A）
CANDIDATES = [
    ("固定N=6", 6, None, None),
    ("守恆N=15", 15, 0.10 * 6 / 15, 0.30 * 6 / 15),
    ("守恆N=20", 20, 0.10 * 6 / 20, 0.30 * 6 / 20),
]


def concentration(pnl_by_stock):
    total = sum(pnl_by_stock.values())
    if abs(total) < 1e-9:
        return float("nan"), float("nan")
    vals = sorted(pnl_by_stock.values(), reverse=True)
    return vals[0] / total * 100.0, sum(vals[:3]) / total * 100.0


def calmar(annual, dd):
    return annual / abs(dd) if dd and abs(dd) > 1e-9 else float("nan")


def pct_up(x, b):
    if b is None or b != b or abs(b) < 1e-9:
        return float("-inf")
    return x / b - 1.0


def yr(st, y):
    d = st["per_year"].get(y)
    return d["ret"] * 100.0 if d else float("nan")


# ───────────────────────── build signals ONCE ─────────────────────────
print(f"建訊號（{len(LIVE_UNIVERSE)} 檔 LIVE_UNIVERSE，{START}~{END}，純快取）…")
price_df, sig = build_signals(LIVE_UNIVERSE, START, END)


def run_one(max_pos, smin, smax, max_hold, atr_hi):
    st = run_capped(price_df, sig, LIVE_UNIVERSE, START, END, capital=CAP,
                    max_pos=max_pos, size_min=smin, size_max=smax,
                    max_hold=max_hold, atr_hi=atr_hi)
    top1, top3 = concentration(st["pnl_by_stock"])
    return {"trades_yr": st["n_trades"] / N_YEARS, "annual": st["annual"],
            "sharpe": st["sharpe"], "calmar": calmar(st["annual"], st["dd"]),
            "dd": st["dd"], "y2024": yr(st, 2024), "y2022": yr(st, 2022),
            "top1": top1, "top3": top3}


# 全域 Phase 6 基準 = 固定N=6 / 現行出場（60 / 0.09）
GBASE = run_one(6, None, None, 60, 0.09)
print(f"\n全域基準 固定N=6 / 出場60·0.09：Sharpe {GBASE['sharpe']:.2f} / Calmar {GBASE['calmar']:.2f} / "
      f"DD {GBASE['dd']*100:.1f}% / 2024 {GBASE['y2024']:+.0f}% / 2022 {GBASE['y2022']:+.0f}% "
      f"/ top3 {GBASE['top3']:.0f}%")
print("（0050 對照：2024 +49% / 2022 −22%）")
print("Gate（vs 全域基準）：DD≤-18%軟線(>-20%REJECT) ＆ Calmar或Sharpe +≥10% ＆ top1&top3<基準")


def gate(r):
    if r["dd"] < -0.20:
        return "REJECT"
    dd_ok = r["dd"] >= -0.18
    risk_ok = (pct_up(r["calmar"], GBASE["calmar"]) >= 0.10
               or pct_up(r["sharpe"], GBASE["sharpe"]) >= 0.10)
    conc_ok = (r["top1"] < GBASE["top1"]) and (r["top3"] < GBASE["top3"])
    return "PASS" if (dd_ok and risk_ok and conc_ok) else "fail"


all_pass = []
for label, mp, smin, smax in CANDIDATES:
    print("\n" + "=" * 100)
    print(f"候選 {label}（size_min={smin}, size_max={smax}）— 出場連動 max_hold × atr_hi")
    print("=" * 100)
    print(f"{'max_hold':>9}{'atr_hi':>8}{'交易/年':>8}{'年化%':>8}{'Sharpe':>8}{'Calmar':>8}"
          f"{'回撤%':>8}{'2024%':>8}{'2022%':>8}{'top3%':>8}{'Gate':>8}")
    for mh in MAXHOLD_GRID:
        for ah in ATRHI_GRID:
            r = run_one(mp, smin, smax, mh, ah)
            g = gate(r)
            if g == "PASS":
                all_pass.append((label, mh, ah, r))
            mh_lbl = "off" if mh >= 9999 else str(mh)
            print(f"{mh_lbl:>9}{ah:>8.2f}{r['trades_yr']:>8.1f}{r['annual']*100:>8.1f}{r['sharpe']:>8.2f}"
                  f"{r['calmar']:>8.2f}{r['dd']*100:>8.1f}{r['y2024']:>+8.0f}{r['y2022']:>+8.0f}"
                  f"{r['top3']:>8.0f}{g:>8}")

# ───────────────────────── 摘要 ─────────────────────────
print("\n" + "-" * 100)
if all_pass:
    best = max(all_pass, key=lambda t: (t[3]["calmar"], t[3]["sharpe"]))
    lbl, mh, ah, r = best
    mh_lbl = "off" if mh >= 9999 else str(mh)
    print(f"通過 Gate 的組合：{len(all_pass)} 個")
    print(f"→ 最佳：{lbl} + max_hold={mh_lbl} / atr_hi={ah:.2f}  "
          f"Calmar {r['calmar']:.2f}（基準 {GBASE['calmar']:.2f}）/ Sharpe {r['sharpe']:.2f} / "
          f"DD {r['dd']*100:.1f}% / 2024 {r['y2024']:+.0f}% / 交易{r['trades_yr']:.0f}/年")
else:
    print("無任何出場連動組合通過 Phase 6 Gate。")
print("（max_hold/atr_hi 屬 Phase 7 共用槓桿；此處僅敏感度，最終出場改造 A/B 與 walk-forward 屬 Phase 7/8。）")
print("\n[done]")

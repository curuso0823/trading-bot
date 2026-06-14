"""
notebooks/universe_ai_compare.py
任務2+4 驗證：38(現行) vs +8精選 vs +15全候選 vs 修剪版，8年(2018-25) 100k mp=5 零股。
含新增股 per-stock 策略損益（pnl_by_stock）+ 進場次數 + 當前價位 sizing 可行性。
regime 已釘選原 38 檔（universe_source=fixed）→ 四變體共用同一 regime 基準，純比選單效果。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest.capped_sim import build_signals, run_capped, DEFAULT_UNIVERSE, AI_CANDIDATES
from src.data.fetcher import FinMindFetcher

NAMES = {"2449": "京元電", "8299": "群聯", "2408": "南亞科", "6515": "穎崴", "5274": "信驊",
         "2383": "台光電", "2368": "金像電", "3037": "欣興", "2313": "華通", "4958": "臻鼎-KY",
         "3017": "奇鋐", "2345": "智邦", "8210": "勤誠", "2059": "川湖", "6669": "緯穎"}
PICK8 = ["2449", "8299", "2408", "2383", "3017", "2368", "2345", "3037"]
LAGGARDS = ["3034", "6415", "2379", "3008", "2353", "4938"]  # 聯詠/矽力/瑞昱/大立光/宏碁/和碩
START, END, CAP = "2018-01-01", "2025-12-31", 100_000


def main():
    f = FinMindFetcher()
    print("AI 候選現價與 100k sizing 可行性（最低配重 10% = 1 萬/檔）：")
    for s in AI_CANDIDATES:
        px = f.get_daily_price(s, "2026-06-01", "2026-06-10", adjust=False)
        last = float(px["close"].iloc[-1]) if not px.empty else float("nan")
        ok = "OK" if last <= 10_000 else "超預算→低配重時買不到1股"
        print(f"  {s} {NAMES[s]:<6} 現價 {last:>8,.0f}  {ok}")

    uni_all = DEFAULT_UNIVERSE + AI_CANDIDATES
    print("\n建訊號（53 檔，新股需抓 FinMind 2016-2025，較慢）…")
    price_df, sig = build_signals(uni_all, START, END)

    variants = {
        "A 38現行": DEFAULT_UNIVERSE,
        "B 38+15全候選": DEFAULT_UNIVERSE + AI_CANDIDATES,
        "C 38+8精選": DEFAULT_UNIVERSE + PICK8,
        "D 修剪32+8精選": [s for s in DEFAULT_UNIVERSE if s not in LAGGARDS] + PICK8,
    }
    res = {}
    for name, uni in variants.items():
        res[name] = run_capped(price_df, sig, uni, START, END, capital=CAP, max_pos=5, mode="odd_lot")

    cols = list(variants)
    print(f"\n{'指標':>10}" + "".join(f"{c:>16}" for c in cols))
    for k, lab, fmt in [("annual", "年化", lambda v: f"{v*100:.1f}%"), ("sharpe", "Sharpe", lambda v: f"{v:.2f}"),
                        ("dd", "最大回撤", lambda v: f"{v*100:.1f}%"), ("pf", "PF", lambda v: f"{v:.2f}"),
                        ("win_rate", "勝率", lambda v: f"{v*100:.0f}%"), ("n_trades", "交易數", lambda v: f"{v}"),
                        ("gate_pass", "Gate", lambda v: "PASS" if v else "FAIL")]:
        print(f"{lab:>10}" + "".join(f"{fmt(res[c][k]):>16}" for c in cols))

    print(f"\n分年 報酬%：" + "".join(f"{c:>16}" for c in cols))
    for yr in range(2018, 2026):
        row = ""
        for c in cols:
            y = res[c]["per_year"].get(yr)
            row += f"{(y['ret']*100 if y else 0):>15.1f}%"
        print(f"  {yr}{row}")

    b = res["B 38+15全候選"]
    print(f"\n新增 15 檔在 B 變體：進場次數 / 實現損益（B 共 {b['n_trades']} 筆）")
    for s in AI_CANDIDATES:
        print(f"  {s} {NAMES[s]:<6} {b['entry_counts'].get(s, 0):>3} 次  {b['pnl_by_stock'].get(s, 0.0):>+12,.0f} 元")
    tot = sum(b["pnl_by_stock"].get(s, 0.0) for s in AI_CANDIDATES)
    print(f"  合計：{tot:+,.0f} 元")


if __name__ == "__main__":
    main()

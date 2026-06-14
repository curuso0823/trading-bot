"""
notebooks/ai_score_behavior.py
驗證「AI 股外資進出快/分數不穩」+ mp5→mp6 是否實際把 AI 股送進場（AI窗 23-25, 35檔, 100k）。
量化：①各族群 entry_signal 天數/分數均值/分數波動（不穩定性）②有訊號但被滿倉擠掉的天數
③mp5 vs mp6 進場分布轉移（特別是 AI 採用 4 檔）。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from src.backtest.capped_sim import build_signals, run_capped, DEFAULT_UNIVERSE, AI_CANDIDATES, LIVE_UNIVERSE, AI_ADOPTED
from src.utils.sectors import get_sector

S, E = "2023-01-01", "2025-12-31"
N = {"3017": "奇鋐", "8299": "群聯", "2449": "京元電", "8210": "勤誠"}


def main():
    price_df, sig = build_signals(DEFAULT_UNIVERSE + AI_CANDIDATES, "2018-01-01", "2025-12-31")
    sg = sig[(sig["stock_id"].isin(set(LIVE_UNIVERSE))) & (sig["date"] >= S) & (sig["date"] <= E)]

    # ① 族群訊號行為：有訊號天數、訊號日分數均值、分數std（不穩定性代理）
    rows = []
    for sid, g in sg.groupby("stock_id"):
        d = g[g["entry_signal"] == True]
        if len(g) == 0:
            continue
        rows.append({"sid": sid, "sec": get_sector(sid), "sig_days": len(d),
                     "score_mean": d["score"].mean() if len(d) else 0.0,
                     "score_std": g["score"].std()})
    df = pd.DataFrame(rows)
    agg = df.groupby("sec").agg(檔數=("sid", "count"), 訊號日合計=("sig_days", "sum"),
                                訊號日均分=("score_mean", "mean"), 分數波動=("score_std", "mean")).round(2)
    print("=== ① 族群訊號行為（AI窗）===")
    print(agg.sort_values("訊號日合計", ascending=False).to_string())
    print("\nAI 採用 4 檔個別：")
    for x in AI_ADOPTED:
        r = df[df["sid"] == x]
        if not r.empty:
            r = r.iloc[0]
            print(f"  {x} {N[x]:<4} 訊號日 {r['sig_days']:>3}，訊號日均分 {r['score_mean']:.2f}，分數σ {r['score_std']:.2f}")
    fin = df[df["sec"] == "FIN"]
    print(f"  對照 FIN 平均：訊號日 {fin['sig_days'].mean():.0f}，均分 {fin['score_mean'].mean():.2f}，分數σ {fin['score_std'].mean():.2f}")

    # ② ③ mp5 vs mp6：進場分布轉移
    print("\n=== ②③ mp5 → mp6 進場轉移（AI窗）===")
    res = {}
    for mp in [5, 6]:
        res[mp] = run_capped(price_df, sig, LIVE_UNIVERSE, S, E, capital=100_000, max_pos=mp, mode="odd_lot")
    for mp in [5, 6]:
        r = res[mp]
        bys = {}
        for sid, c in r["entry_counts"].items():
            bys[get_sector(sid)] = bys.get(get_sector(sid), 0) + c
        tot = sum(bys.values())
        ai4 = sum(r["entry_counts"].get(x, 0) for x in AI_ADOPTED)
        ai4p = sum(r["pnl_by_stock"].get(x, 0.0) for x in AI_ADOPTED)
        top = sorted(bys.items(), key=lambda x: -x[1])[:6]
        print(f"mp={mp}：進場 {tot} 次｜AI採用4檔 {ai4} 次({ai4/tot*100:.0f}%) 損益 {ai4p:+,.0f}｜"
              + "、".join(f"{k}{v}" for k, v in top))
    print("\nAI 採用 4 檔逐檔（mp5 → mp6）：")
    for x in AI_ADOPTED:
        c5, c6 = res[5]["entry_counts"].get(x, 0), res[6]["entry_counts"].get(x, 0)
        p5, p6 = res[5]["pnl_by_stock"].get(x, 0.0), res[6]["pnl_by_stock"].get(x, 0.0)
        print(f"  {x} {N[x]:<4} 進場 {c5}→{c6} 次，損益 {p5:+,.0f}→{p6:+,.0f}")


if __name__ == "__main__":
    main()

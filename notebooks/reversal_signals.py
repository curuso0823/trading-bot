"""
notebooks/reversal_signals.py
研究：量測各候選訊號對台股「真反轉 vs 熊市假反彈」的區分力（2018-2025，資料已快取）。
方法：把訊號算成日序列，對「未來60日 0050 報酬」做相關；重點看「0050 跌破 MA60 的危險區」
      子樣本（熊市反彈與V底都在此發生）→ 在這裡相關性高的訊號最能分辨真底 vs 假反彈。
另列幾個已知「真底 / 假反彈」日期的訊號快照供直觀比較。
訊號來源全用現有 FinMind 快取（0050 + 38檔大中型股的價/法人/融資）。
用法：.venv\\Scripts\\python.exe notebooks\\reversal_signals.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from src.data.fetcher import FinMindFetcher

U = ["2330","2454","2303","2308","2379","3034","3711","2337","6415","3008","2317","2382",
     "2357","2376","3231","4938","2356","2353","2881","2882","2891","2886","2884","2885",
     "2892","5880","1301","1303","1326","2002","1101","2207","2603","2609","2615","2412","2912","1216"]
START, END = "2018-01-01", "2025-12-31"
f = FinMindFetcher()


def main():
    # 指數代理 0050
    bx = f.get_daily_price("0050", START, END).set_index("date")["close"].astype(float)
    idx = pd.DataFrame(index=bx.index)
    idx["bench"] = bx
    for n in (60, 120, 200):
        idx[f"ma{n}"] = bx.rolling(n).mean()
    ret = bx.pct_change()
    idx["vol20"] = ret.rolling(20).std()
    idx["mom20"] = bx.pct_change(20)
    idx["dd"] = bx / bx.rolling(252, min_periods=60).max() - 1
    idx["dist_ma60"] = bx / idx["ma60"] - 1
    idx["fwd60"] = bx.shift(-60) / bx - 1          # 目標：未來60日報酬

    # 38檔面板（廣度 + 法人 + 融資）
    closes, ups, foreign, trust, margin = {}, {}, {}, {}, {}
    for s in U:
        p = f.get_daily_price(s, START, END)
        if p.empty:
            continue
        c = p.set_index("date")["close"].astype(float)
        closes[s] = c
        ups[s] = (c.pct_change() > 0).astype(float)
        inst = f.get_institutional(s, START, END)
        if not inst.empty and "diff" in inst.columns:
            fo = inst[inst["name"] == "Foreign_Investor"].set_index("date")["diff"].astype(float)
            tr = inst[inst["name"] == "Investment_Trust"].set_index("date")["diff"].astype(float)
            foreign[s] = fo; trust[s] = tr
        mg = f.get_margin(s, START, END)
        if not mg.empty and "MarginPurchaseTodayBalance" in mg.columns:
            margin[s] = mg.set_index("date")["MarginPurchaseTodayBalance"].astype(float)

    cl = pd.DataFrame(closes).reindex(idx.index).ffill()
    ma20 = cl.rolling(20).mean(); ma60c = cl.rolling(60).mean()
    idx["breadth_ma20"] = (cl > ma20).mean(axis=1)          # % 站上 MA20 的個股
    idx["breadth_ma60"] = (cl > ma60c).mean(axis=1)
    idx["adv5"] = pd.DataFrame(ups).reindex(idx.index).mean(axis=1).rolling(5).mean()  # 5日上漲家數比
    # 法人：38檔淨買股數加總(百萬股)，5日累計
    fnet = pd.DataFrame(foreign).reindex(idx.index).sum(axis=1) / 1e6
    tnet = pd.DataFrame(trust).reindex(idx.index).sum(axis=1) / 1e6
    idx["foreign5"] = fnet.rolling(5).sum()
    idx["trust5"] = tnet.rolling(5).sum()
    # 融資總餘額(38檔加總)的20日變化%（投降式急殺=負）
    mtot = pd.DataFrame(margin).reindex(idx.index).ffill().sum(axis=1)
    idx["margin_chg20"] = mtot.pct_change(20)

    sigs = ["breadth_ma20", "breadth_ma60", "adv5", "foreign5", "trust5",
            "margin_chg20", "vol20", "dist_ma60", "dd", "mom20"]

    d = idx.dropna(subset=["fwd60"])
    below = d[d["bench"] < d["ma60"]]   # 危險/模糊區：跌破 MA60（熊市反彈與真底都在此）

    print(f"\n樣本：全 {len(d)} 日；跌破MA60子樣本 {len(below)} 日（{len(below)/len(d):.0%}）")
    print("\n=== 各訊號 vs 未來60日報酬 的相關（|corr| 越大=區分力越強）===")
    print(f"{'訊號':>14}{'全樣本':>10}{'跌破MA60區':>12}")
    print("-" * 38)
    rows = []
    for s in sigs:
        c_all = d[s].corr(d["fwd60"])
        c_bel = below[s].corr(below["fwd60"])
        rows.append((s, c_all, c_bel))
    for s, ca, cb in sorted(rows, key=lambda r: -abs(r[2])):  # 依「跌破MA60區」區分力排序
        print(f"{s:>14}{ca:>10.2f}{cb:>12.2f}")

    # 已知事件快照（最近交易日）：真底 vs 假反彈，看訊號當下值
    print("\n=== 事件快照（訊號當日值；真底應 breadth/法人/量能轉強、vol見頂回落）===")
    events = {
        "2019-01-04 真底(18崩後)": "2019-01-04", "2020-03-19 真底(covid)": "2020-03-19",
        "2022-10-25 真底(22熊底)": "2022-10-25", "2025-04-09 真底(關稅V)": "2025-04-09",
        "2022-03-30 假反彈(22)": "2022-03-30", "2022-08-15 假反彈(22)": "2022-08-15",
    }
    cols = ["breadth_ma20", "foreign5", "trust5", "margin_chg20", "vol20", "dist_ma60", "fwd60"]
    print(f"{'事件':>22}" + "".join(f"{c:>11}" for c in cols))
    for label, dt in events.items():
        pos = idx.index[idx.index <= pd.Timestamp(dt)]
        if len(pos) == 0:
            continue
        r = idx.loc[pos[-1]]
        print(f"{label:>22}" + "".join(
            f"{(r[c]*100 if c in ('breadth_ma20','margin_chg20','vol20','dist_ma60','fwd60') else r[c]):>10.1f}"
            + ("%" if c in ('breadth_ma20','margin_chg20','vol20','dist_ma60','fwd60') else "") for c in cols))


if __name__ == "__main__":
    main()

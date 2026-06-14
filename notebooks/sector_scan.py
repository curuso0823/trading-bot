"""
notebooks/sector_scan.py
任務1+3：在列 SEMI 9 檔 + EMS 8 檔近三年(AI時代)體檢；任務2+4：場外候選同口徑掃描。
還原價(含息) 2023-06-10 ~ 2026-06-10：3年總報酬/CAGR/Sharpe/MaxDD + 1年/6月動能 + 流動性，0050 對照。
標籤：強(CAGR≥1.5×0050 且 1年>0) / 中(≥0050) / 弱(<0050，拖後腿)。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from src.data.fetcher import FinMindFetcher

FETCH_START, W3Y_START, END = "2022-11-01", "2023-06-10", "2026-06-10"

IN_SEMI = {"2330": "台積電", "2454": "聯發科", "2303": "聯電", "2379": "瑞昱", "3034": "聯詠",
           "3711": "日月光投控", "2337": "旺宏", "6415": "矽力-KY", "3008": "大立光"}
IN_EMS = {"2317": "鴻海", "2382": "廣達", "2357": "華碩", "2376": "技嘉", "3231": "緯創",
          "4938": "和碩", "2356": "英業達", "2353": "宏碁"}
# 場外候選（2025-26 AI 報導 + ASIC/IP/散熱/PCB/網通供應鏈）
CAND_SEMI = {"3661": "世芯-KY", "3443": "創意", "3035": "智原", "5274": "信驊", "3529": "力旺",
             "8299": "群聯", "2408": "南亞科", "2449": "京元電", "6515": "穎崴", "3680": "家登",
             "6526": "達發", "4966": "譜瑞-KY"}
CAND_EMS = {"6669": "緯穎", "3706": "神達", "2301": "光寶科", "2345": "智邦", "3017": "奇鋐",
            "3324": "雙鴻", "2421": "建準", "2368": "金像電", "2383": "台光電", "3037": "欣興",
            "3533": "嘉澤", "2059": "川湖", "8210": "勤誠", "2313": "華通", "4958": "臻鼎-KY"}

f = FinMindFetcher()


def metrics(sid):
    df = f.get_daily_price(sid, FETCH_START, END, adjust=True)
    if df.empty or len(df) < 100:
        return None
    d = df.set_index("date")
    px = d["adj_close"].astype(float)
    turn60 = float((d["close"] * d["volume"]).tail(60).mean() / 1e8)  # 日均成交額(億)
    w = px[px.index >= W3Y_START]
    if len(w) < 252:
        return None
    r = w.pct_change().dropna()
    yrs = len(w) / 252
    return {
        "ret3y": float(w.iloc[-1] / w.iloc[0] - 1),
        "cagr": float((w.iloc[-1] / w.iloc[0]) ** (1 / yrs) - 1),
        "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0,
        "dd": float((w / w.cummax() - 1).min()),
        "ret1y": float(w.iloc[-1] / w.iloc[-min(252, len(w))] - 1),
        "ret6m": float(w.iloc[-1] / w.iloc[-min(126, len(w))] - 1),
        "turn60": turn60, "bars": len(w),
    }


def show(title, group, bench):
    print(f"\n=== {title} ===")
    print(f"{'代號':>6} {'名稱':<8}{'3年總報酬':>9}{'CAGR':>8}{'Sharpe':>8}{'MaxDD':>8}{'近1年':>8}{'近6月':>8}{'日均額億':>9}  評")
    rows = []
    for sid, name in group.items():
        m = metrics(sid)
        if m is None:
            print(f"{sid:>6} {name:<8}  資料不足/上市過短")
            continue
        rows.append((sid, name, m))
    for sid, name, m in sorted(rows, key=lambda x: -x[2]["ret3y"]):
        tag = ("強" if m["cagr"] >= bench["cagr"] * 1.5 and m["ret1y"] > 0
               else ("中" if m["cagr"] >= bench["cagr"] else "弱"))
        print(f"{sid:>6} {name:<8}{m['ret3y']*100:>8.0f}%{m['cagr']*100:>7.1f}%{m['sharpe']:>8.2f}"
              f"{m['dd']*100:>7.1f}%{m['ret1y']*100:>7.1f}%{m['ret6m']*100:>7.1f}%{m['turn60']:>9.1f}  {tag}")
    return rows


def main():
    bench = metrics("0050")
    print(f"基準 0050（含息）：3年 {bench['ret3y']*100:.0f}% / CAGR {bench['cagr']*100:.1f}%"
          f" / Sharpe {bench['sharpe']:.2f} / DD {bench['dd']*100:.1f}% / 近1年 {bench['ret1y']*100:.1f}%")
    recs = []
    for t, g in [("任務1：在列半導體 9 檔", IN_SEMI), ("任務3：在列電子代工 8 檔", IN_EMS),
                 ("任務2：場外半導體候選", CAND_SEMI), ("任務4：場外代工/AI鏈候選", CAND_EMS)]:
        for sid, name, m in show(t, g, bench):
            recs.append({"group": t, "stock_id": sid, "name": name, **m})
    pd.DataFrame(recs).to_csv("data/processed/sector_scan_202606.csv", index=False, encoding="utf-8-sig")
    print("\n已存 data/processed/sector_scan_202606.csv")


if __name__ == "__main__":
    main()

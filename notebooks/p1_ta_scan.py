"""
notebooks/p1_ta_scan.py
Phase 1 驗證：對一小撮權值股跑 TA 初篩，確認 pipeline 正常、指標與訊號數量合理。
（不掃全市場以節省 FinMind 免費額度）
用法：.venv\\Scripts\\python.exe notebooks\\p1_ta_scan.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from src.data.fetcher import FinMindFetcher
from src.signals.tech_signal import TechSignal

# 流動性高、跨產業的觀察清單（驗證用）
WATCH = {
    "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2308": "台達電",
    "2382": "廣達", "3231": "緯創", "2603": "長榮", "2891": "中信金",
    "1301": "台塑", "2412": "中華電",
}
START = "2025-12-01"

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)


def main():
    f = FinMindFetcher()
    t = TechSignal()
    rows = []
    for sid, name in WATCH.items():
        df = f.get_daily_price(sid, START)  # 預設 adjust=True（還原）
        if df.empty or len(df) < t.ma_period + 5:
            rows.append({"stock_id": sid, "name": name, "note": "資料不足"})
            continue
        d = t.compute(df)
        r = d.iloc[-1]
        rows.append({
            "stock_id": sid, "name": name, "date": r["date"].date(),
            "close": round(r["close"], 1), "ma20": round(r["ma20"], 1),
            "slope": round(r["ma_slope"], 2), "vol_x": round(r["vol_ratio"], 2),
            "rsi": round(r["rsi14"], 1),
            "aboveMA": t.is_above_ma(r), "MAup": t.is_ma_trending_up(r),
            "volSurge": t.is_volume_surge(r), "rsiOK": t.is_rsi_healthy(r),
            "TRIGGER": t.is_triggered(r),
        })

    out = pd.DataFrame(rows)
    print("\n=== P1 TA 掃描結果（觀察清單）===")
    print(out.to_string(index=False))

    trig = out[out.get("TRIGGER", False) == True] if "TRIGGER" in out else out.iloc[0:0]
    print(f"\n觸發 TA 三條件：{len(trig)} / {len(WATCH)} 檔" +
          (f" → {list(trig['stock_id'])}" if len(trig) else ""))

    # 健全性檢查
    ok = True
    if "rsi" in out:
        ok &= bool(out["rsi"].dropna().between(0, 100).all())
        ok &= bool(out["ma20"].notna().all())
    print(f"健全性（RSI∈[0,100]、MA20 非缺值）：{'PASS' if ok else 'FAIL'}")


if __name__ == "__main__":
    main()

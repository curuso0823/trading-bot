"""
notebooks/measure_slippage.py
盤中量測：抓 universe 的「盤中零股」買賣價差，估每檔有效滑價（半價差）+ 掛單深度。
給回測一個數據驅動的零股滑價值（取代 0.4% 猜測）。
※ 單次快照僅供參考；穩健量測需盤中多次取樣。必須在台股盤中(09:00-13:30)執行。
用法：.venv\\Scripts\\python.exe notebooks\\measure_slippage.py
"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from src.data.fetcher import FugleFetcher

UNIVERSE = [
    "2330", "2454", "2303", "2308", "2379", "3034", "3711", "2337", "6415", "3008",
    "2317", "2382", "2357", "2376", "3231", "4938", "2356", "2353",
    "2881", "2882", "2891", "2886", "2884", "2885", "2892", "5880",
    "1301", "1303", "1326", "2002", "1101", "2207",
    "2603", "2609", "2615", "2412", "2912", "1216",
]


def main():
    f = FugleFetcher()
    rows = []
    for sid in UNIVERSE:
        try:
            q = f.get_realtime_quote(sid, odd=True)
            bids, asks = q.get("bids") or [], q.get("asks") or []
            if not bids or not asks:
                continue
            bid, ask = bids[0]["price"], asks[0]["price"]
            mid = (bid + ask) / 2
            if mid <= 0:
                continue
            half_spread = (ask - bid) / 2 / mid
            ask_depth = asks[0]["size"]  # 最佳賣價掛單股數
            rows.append({"stock_id": sid, "mid": mid,
                         "half_spread_%": round(half_spread * 100, 3),
                         "ask_depth_股": ask_depth})
        except Exception as e:
            print(f"  {sid} err: {repr(e)[:80]}")
        time.sleep(0.3)  # 避免 Fugle 頻率限制

    if not rows:
        print("無資料（非盤中？或 Fugle 額度）")
        sys.exit(1)

    df = pd.DataFrame(rows).sort_values("half_spread_%")
    print("\n=== 盤中零股有效滑價量測（半價差）===")
    print(df.to_string(index=False))
    hs = df["half_spread_%"]
    print(f"\n樣本 {len(df)} 檔 | 半價差 中位數 {hs.median():.3f}% | 平均 {hs.mean():.3f}% | "
          f"25/75 分位 {hs.quantile(.25):.3f}%/{hs.quantile(.75):.3f}%")
    print(f"→ 建議回測 odd_lot_slippage ≈ {hs.median()/100:.4f}（中位半價差，取代 0.004 猜測）")
    print(f"  我原本的 0.4% 假設 = {0.4/hs.median():.1f}x 實測中位數" if hs.median() > 0 else "")


if __name__ == "__main__":
    main()

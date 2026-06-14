"""
notebooks/p2_chip_scan.py
Phase 2 驗證：對觀察清單直接跑籌碼評分（繞過 TA 觸發），確認法人/融資評分
用修正後的 dataset 名稱、英文法人名、buy-sell diff、融資餘額欄位都算得出真分數。
用法：.venv\\Scripts\\python.exe notebooks\\p2_chip_scan.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from src.signals.score_engine import ScoreEngine

WATCH = ["2330", "2317", "2454", "2308", "2382", "3231", "2603", "2891", "1301", "2412"]

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)


def main():
    se = ScoreEngine()
    # 偽 TA 候選（run_chip_scoring 只需要 stock_id）
    ta_candidates = [{"stock_id": sid, "close": 0} for sid in WATCH]

    df = se.run_chip_scoring(ta_candidates)
    if df.empty:
        print("籌碼評分無結果（檢查 token / 額度 / 資料）")
        sys.exit(2)

    cols = ["stock_id", "foreign_score", "trust_score", "margin_score",
            "short_penalty", "chip_score", "foreign_net"]
    print("\n=== P2 籌碼評分結果（基準日為前一交易日）===")
    print(df[cols].to_string(index=False))

    # 健全性檢查
    ok = True
    ok &= bool(df["foreign_score"].isin([0, 2]).all())
    ok &= bool(df["trust_score"].isin([0, 1]).all())
    ok &= bool(df["margin_score"].isin([0, 1]).all())
    ok &= bool(df["short_penalty"].isin([0, -1]).all())
    recomputed = (df["foreign_score"] + df["trust_score"] +
                  df["margin_score"] + df["short_penalty"])
    ok &= bool((recomputed == df["chip_score"]).all())
    # 至少要有一檔的法人分非 0（證明英文名比對 + diff 有效，不是靜默全 0）
    nonzero_foreign = bool((df["foreign_score"] > 0).any() or (df["foreign_net"] != 0).any())

    n_pass = int((df["chip_score"] >= se.min_score).sum())
    print(f"\n達門檻（chip_score ≥ {se.min_score}）：{n_pass} / {len(df)} 檔")
    print(f"分數結構健全（各項在合理值域、chip_score=各項加總）：{'PASS' if ok else 'FAIL'}")
    print(f"籌碼層非靜默全 0（法人名/diff 生效）：{'PASS' if nonzero_foreign else 'FAIL'}")
    sys.exit(0 if (ok and nonzero_foreign) else 2)


if __name__ == "__main__":
    main()

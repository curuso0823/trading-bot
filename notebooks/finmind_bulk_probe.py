"""
notebooks/finmind_bulk_probe.py
驗證 FinMind register(免費) token 能否「不帶 data_id、只給日期」整包抓全市場。
→ 決定 #1 走「全市場每日掃描」還是「離線擴大 watchlist」。
唯讀；每資料集只打 1 次、單一日期（省額度，不爆配額）。
"""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

# Windows 主控台預設 cp950，無法印 emoji/部分字元 → 強制 utf-8（不擋輸出）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TOKEN = os.getenv("FINMIND_TOKEN")
BASE = "https://api.finmindtrade.com/api/v4/data"
PROBE_DATE = "2026-06-10"   # 已知有資料的交易日（bot 當天有跑）

DATASETS = [
    "TaiwanStockPrice",
    "TaiwanStockInstitutionalInvestorsBuySell",
    "TaiwanStockMarginPurchaseShortSale",
]


def probe(dataset: str) -> str:
    # 故意「不帶 data_id」→ 測整包 by-date 查詢是否開放
    params = {"dataset": dataset, "start_date": PROBE_DATE,
              "end_date": PROBE_DATE, "token": TOKEN}
    try:
        r = requests.get(BASE, params=params, timeout=30)
        j = r.json()
    except Exception as e:
        return f"{dataset}: 例外 {type(e).__name__}: {e}"
    status = j.get("status")
    msg = j.get("msg", "")
    data = j.get("data", []) or []
    n_rows = len(data)
    n_ids = len({d.get("stock_id") for d in data}) if data else 0
    sample = data[0] if data else None
    verdict = ("[BULK-OK] 整包可用（免費層）" if n_ids > 50 else
               ("[FEW] 僅回少量/單檔" if n_rows else "[BLOCKED] 無資料/被擋"))
    return (f"{dataset}\n   status={status} rows={n_rows} unique_ids={n_ids} "
            f"msg={msg!r}\n   {verdict}\n   sample={sample}")


def main():
    if not TOKEN:
        print("FINMIND_TOKEN 未設定（檢查 .env）")
        return
    print(f"token 末四碼 …{TOKEN[-4:]}   probe_date={PROBE_DATE}")
    print("=" * 64)
    for ds in DATASETS:
        print(probe(ds))
        print("-" * 64)


if __name__ == "__main__":
    main()

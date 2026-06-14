"""
notebooks/build_watchlist.py
#1 擴大 watchlist：用 TWSE/TPEx 公開 bulk EOD（非 FinMind，不耗 600/hr 額度）取全市場單日成交金額(turnover)，
→ 排名 + 分布 → 估算「合理上限」(150-300) → 產出擴充 watchlist 候選。
liquidity 是真正的 binding 限制（零股要掛得到），故以 20 日成交額 floor 50M(config) 為基準排名。
"""
import sys
import os
import requests
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.data.universe import fetch_tw_stock_universe


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return 0.0


def fetch_twse():
    """TWSE 上市全市場最新交易日（OpenAPI，JSON，一次全拿）。TradeValue=成交金額。"""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data:
        print(f"  TWSE keys 範例: {list(data[0].keys())}")
    rows = [(str(d.get("Code", "")).strip(),
             _num(d.get("TradeValue") or d.get("成交金額")))
            for d in data]
    return pd.DataFrame(rows, columns=["stock_id", "turnover"]), "TWSE"


def fetch_tpex():
    """TPEx 上櫃全市場（OpenAPI）。欄位名可能變動 → 防禦式找 turnover-like 欄。"""
    candidates = [
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
        "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes",
    ]
    for url in candidates:
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            data = r.json()
            if not data:
                continue
            keys = list(data[0].keys())
            print(f"  TPEx keys 範例 ({url.split('/')[-1]}): {keys}")
            # 找 code 欄 + turnover 欄
            code_k = next((k for k in keys if "Code" in k or "代號" in k), None)
            val_k = next((k for k in keys if k in
                          ("TransactionAmount", "TradeValue", "Value", "成交金額")), None)
            if not (code_k and val_k):
                print(f"    欄位不符，跳過")
                continue
            rows = [(str(d.get(code_k, "")).strip(), _num(d.get(val_k))) for d in data]
            return pd.DataFrame(rows, columns=["stock_id", "turnover"]), url.split("/")[-1]
        except Exception as e:
            print(f"  TPEx {url} 失敗: {type(e).__name__}: {e}")
    return pd.DataFrame(columns=["stock_id", "turnover"]), "none"


uni = fetch_tw_stock_universe()
uni_ids = set(uni["stock_id"].astype(str))
print(f"universe: {len(uni)} 檔（4 碼普通股）")

twse, _ = fetch_twse()
print(f"TWSE bulk: {len(twse)} 列")
tpex, tp_src = fetch_tpex()
print(f"TPEx bulk: {len(tpex)} 列（來源 {tp_src}）")

liq = pd.concat([twse, tpex], ignore_index=True)
liq = liq[liq["stock_id"].isin(uni_ids)].drop_duplicates("stock_id")
liq = liq.merge(uni[["stock_id", "name", "market", "industry"]], on="stock_id", how="left")
liq = liq.sort_values("turnover", ascending=False).reset_index(drop=True)
liq = liq[~liq["stock_id"].str.startswith("00")].reset_index(drop=True)  # 排除 ETF（台股 ETF 皆 00xx）

M = 1e6
print(f"\n=== 全市場單日成交額分布（{len(liq)} 檔有報價）===")
for thr in [1000, 500, 200, 100, 50, 20]:
    print(f"  ≥ {thr:>4}M: {int((liq['turnover'] >= thr * M).sum()):>4} 檔")

n50 = int((liq["turnover"] >= 50 * M).sum())
n100 = int((liq["turnover"] >= 100 * M).sum())
cap = max(150, min(300, n100))
print(f"\n流動性 floor 50M(config) 內 = {n50} 檔；≥100M = {n100} 檔")
print(f"估算合理上限 cap = clip(≥100M={n100}, 150, 300) = {cap}")
print(f"（額度檢核：每日掃描 ~{cap}+chip30+regime1 ≈ {cap + 31} req < 600/hr ✓）")

top = liq.head(cap).copy()
ids = top["stock_id"].tolist()
out = "data/processed/watchlist_expanded.csv"
top.to_csv(out, index=False, encoding="utf-8-sig")
print(f"\n擴充 watchlist = top {cap} by turnover（ETF 已排除），已存 {out}")
print(f"產業分布 top: {top['industry'].value_counts().head(8).to_dict()}")

# 快取覆蓋（決定 validation 回測的 fresh-fetch 預算；600/hr 限制下需 ≤~550 fresh）
from pathlib import Path
cache = Path("data/raw/finmind_cache")
def _cached(sid):
    return any(cache.glob(f"TaiwanStockPrice__{sid}__*"))
print("\n=== validation 回測抓取預算估算 ===")
for N in [120, 150, 200, 300]:
    sub = liq.head(N)["stock_id"].tolist()
    nc = sum(_cached(s) for s in sub)
    print(f"  top {N}: 已快取 {nc}/{N}，需新抓 ~{N - nc} 檔 ×4 dataset ≈ {(N - nc) * 4} req"
          + ("  ✓在600/hr內" if (N - nc) * 4 < 560 else "  ✗超600/hr"))

print("\nLIVE_300 = " + str(ids))

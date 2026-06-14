"""
utils/slippage_logger.py
盤中量測真實零股滑價：進場時抓 Fugle 盤中零股報價，記錄
參考價 vs 實際最佳買/賣價 → 累積真實「開盤時段」滑價（PaperBroker 本身零滑價，靠這個量）。
寫入 data/processed/slippage_log.csv，連跑數日後用來重校回測的 slippage 假設。
"""
import csv
from datetime import datetime
from pathlib import Path
from loguru import logger

LOG_PATH = "data/processed/slippage_log.csv"
_FIELDS = ["ts", "stock_id", "side", "ref_price", "best_bid", "best_ask",
           "mid", "half_spread_pct", "impl_slip_pct", "ask_depth"]


def record_slippage(fugle, stock_id: str, ref_price: float, side: str = "buy") -> dict | None:
    """
    抓盤中零股報價，計算半價差與相對參考價的隱含滑價，append 到 CSV。
    買進隱含滑價 = (best_ask - ref)/ref；賣出 = (ref - best_bid)/ref。
    回傳該筆紀錄 dict（或 None）。需在台股盤中執行才有報價。
    """
    try:
        q = fugle.get_realtime_quote(stock_id, odd=True)
        bids, asks = q.get("bids") or [], q.get("asks") or []
        if not bids or not asks or ref_price <= 0:
            return None
        bid, ask = float(bids[0]["price"]), float(asks[0]["price"])
        mid = (bid + ask) / 2
        if mid <= 0:
            return None
        half_spread = (ask - bid) / 2 / mid
        impl = (ask - ref_price) / ref_price if side == "buy" else (ref_price - bid) / ref_price
        row = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "stock_id": stock_id, "side": side, "ref_price": round(ref_price, 2),
            "best_bid": bid, "best_ask": ask, "mid": round(mid, 2),
            "half_spread_pct": round(half_spread * 100, 4),
            "impl_slip_pct": round(impl * 100, 4),
            "ask_depth": asks[0].get("size", 0),
        }
        _append(row)
        logger.info(f"滑價量測 | {stock_id} {side} 半價差{row['half_spread_pct']}% "
                    f"隱含{row['impl_slip_pct']}%")
        return row
    except Exception as e:
        logger.warning(f"滑價量測失敗 | {stock_id} | {e}")
        return None


def _append(row: dict):
    p = Path(LOG_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    with open(p, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def summary(path: str = LOG_PATH) -> None:
    """讀 slippage_log.csv，輸出隱含滑價/半價差的統計（連跑數日後檢視）。"""
    import pandas as pd
    p = Path(path)
    if not p.exists():
        print("尚無滑價紀錄")
        return
    df = pd.read_csv(p)
    print(f"樣本 {len(df)} 筆（{df['ts'].min()} ~ {df['ts'].max()}）")
    for col in ["half_spread_pct", "impl_slip_pct"]:
        s = df[col]
        print(f"  {col}: 中位 {s.median():.3f}% 平均 {s.mean():.3f}% "
              f"75分位 {s.quantile(.75):.3f}%")
    print(f"→ 建議 odd_lot_slippage ≈ {df['impl_slip_pct'].median()/100:.4f}（隱含滑價中位）")

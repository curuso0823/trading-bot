"""
execution/odd_lot_fill.py
零股盤中成交模型（純函數，PaperBroker/live 共用）。

問題：PaperBroker「限價單一律成交」對零股過度樂觀——盤中零股簿薄，賣一掛量常遠少於想買股數
（day-1 鐵證：2884 賣一僅 38 股 vs 想買 431 股）。理想化成交 → 高估零股可達性。

模型（部分成交 + 吃多檔 book-walk）：
  盤中買單以「賣一」起吃，沿賣方階梯往上吃到「價格衝擊上限(max_impact_pct)」或想買量為止：
    - 吃滿想買量              → (want, vwap, 0)
    - 只吃到一部分（薄帳）    → (filled, vwap, remaining)；餘量(remaining)轉盤後零股集合競價
                                 (14:30，深度厚)補單 → 與盤中部分倉合併成完整目標倉。
    - 連 min_fill 都吃不到    → (0, best_ask, want)；全量轉盤後。
  無零股簿(首撮前/API失敗) → None 讓呼叫端 fallback 舊行為(假設滑價成交，不擋單；資料缺失不擋單)。
比舊版「全有或全無」更貼近實況：薄帳通常「吃得到一部分」，且能沿階梯多吃幾檔（付一點價格衝擊）。
"""


def parse_odd_book(quote: dict, levels: int = 1):
    """從 Fugle 零股報價解析 (best_bid, best_ask, ask_depth)。ask_depth=賣方前 levels 檔加總(股)。
    無有效簿 → (0.0, 0.0, 0)。保留供摘要/向後相容。"""
    asks = quote.get("asks") or []
    bids = quote.get("bids") or []
    if not asks or not bids:
        return 0.0, 0.0, 0
    try:
        best_ask = float(asks[0]["price"])
        best_bid = float(bids[0]["price"])
        depth = sum(int(a.get("size", 0) or 0) for a in asks[:max(1, levels)])
    except (KeyError, ValueError, TypeError):
        return 0.0, 0.0, 0
    return best_bid, best_ask, depth


def parse_odd_ladder(quote: dict, levels: int = 5):
    """解析賣方階梯 → asks=[(price, size), ...] 升冪（前 levels 檔，僅留 price>0 且 size>0）。
    供 book-walk 部分成交。無有效簿（無 asks 或無 bids）→ []。"""
    asks = quote.get("asks") or []
    bids = quote.get("bids") or []
    if not asks or not bids:
        return []
    out = []
    for a in asks[:max(1, levels)]:
        try:
            p, s = float(a["price"]), int(a.get("size", 0) or 0)
        except (KeyError, ValueError, TypeError):
            continue
        if p > 0 and s > 0:
            out.append((p, s))
    return out


def odd_lot_buy_fill(want_qty: int, asks, max_impact_pct: float = 0.0, min_fill: int = 1):
    """零股盤中買單：部分成交 + 吃多檔(book-walk 到價格衝擊上限)。
    參數：
      want_qty       想買股數。
      asks           賣方階梯 [(price, size), ...] 升冪（parse_odd_ladder 產出）。
      max_impact_pct 允許吃到比賣一高多少%（0=只吃賣一價那檔；0.004=可往上吃到 +0.4%）。
      min_fill       盤中至少要吃到的股數，未達 → 視為盤中不成交(0)、全量轉盤後。
    回傳 (filled_qty, vwap_price, remaining_qty)；無簿(asks 空)→ None（呼叫端 fallback，不擋單）。"""
    if not asks:
        return None
    best_ask = asks[0][0]
    if best_ask <= 0:
        return None
    want = int(want_qty)
    if want <= 0:
        return 0, round(best_ask, 2), max(0, want)
    price_cap = best_ask * (1.0 + max(0.0, float(max_impact_pct)))
    filled, cost, remaining = 0, 0.0, want
    for price, size in asks:
        if remaining <= 0 or price > price_cap:
            break
        take = min(remaining, int(size))
        if take <= 0:
            continue
        filled += take
        cost += take * price
        remaining -= take
    if filled < max(1, int(min_fill)):
        return 0, round(best_ask, 2), want          # 盤中吃不到 min_fill → 全量轉盤後
    return filled, round(cost / filled, 2), remaining

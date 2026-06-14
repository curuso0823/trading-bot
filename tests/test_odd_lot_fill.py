"""tests/test_odd_lot_fill：零股部分成交 + book-walk 模型（純函數，不打網）。"""
from src.execution.odd_lot_fill import parse_odd_book, parse_odd_ladder, odd_lot_buy_fill


def _book(bid, ask, ask_size, levels_sizes=None, step=0.05):
    asks = [{"price": ask, "size": ask_size}]
    if levels_sizes:
        asks += [{"price": round(ask + step * (i + 1), 2), "size": s}
                 for i, s in enumerate(levels_sizes)]
    return {"bids": [{"price": bid, "size": 999}], "asks": asks}


# ---- parse_odd_book（保留，向後相容）----
def test_parse_odd_book_basic():
    assert parse_odd_book(_book(34.0, 34.5, 38)) == (34.0, 34.5, 38)


def test_parse_odd_book_multi_level_depth():
    q = _book(30.0, 30.5, 100, levels_sizes=[200])
    assert parse_odd_book(q, levels=2)[2] == 300
    assert parse_odd_book(q, levels=1)[2] == 100      # 預設只看賣一


def test_parse_odd_book_empty_returns_zeros():
    assert parse_odd_book({}) == (0.0, 0.0, 0)
    assert parse_odd_book({"bids": [], "asks": []}) == (0.0, 0.0, 0)


# ---- parse_odd_ladder（新增，book-walk 用）----
def test_parse_odd_ladder_basic():
    assert parse_odd_ladder(_book(34.0, 34.5, 38)) == [(34.5, 38)]


def test_parse_odd_ladder_multi_level():
    q = _book(30.0, 30.5, 100, levels_sizes=[200])
    assert parse_odd_ladder(q, levels=2) == [(30.5, 100), (30.55, 200)]


def test_parse_odd_ladder_drops_zero_size_and_empty():
    assert parse_odd_ladder({}) == []
    q = {"bids": [{"price": 30, "size": 9}], "asks": [{"price": 30.5, "size": 0}]}
    assert parse_odd_ladder(q) == []                   # size 0 → 過濾


# ---- odd_lot_buy_fill（部分成交 + book-walk）----
def test_buy_fill_full_at_ask():
    # 想買 335、賣一深度 3698 → 整筆成交 @ 賣一，餘 0
    assert odd_lot_buy_fill(335, [(30.5, 3698)]) == (335, 30.5, 0)


def test_buy_fill_partial_thin_book():
    # day-1 2884：想買 431、賣一僅 38 → 部分成交 38，餘 393 轉盤後
    assert odd_lot_buy_fill(431, [(34.5, 38)]) == (38, 34.5, 393)


def test_buy_fill_book_walk_within_impact():
    # 想買 100：賣一 38@34.5 + 賣二 62@34.6（max_impact 1%, cap 34.845）→ 吃滿 100 @VWAP
    fq, vwap, rem = odd_lot_buy_fill(100, [(34.5, 38), (34.6, 100)], max_impact_pct=0.01)
    assert fq == 100 and rem == 0
    assert vwap == round((38 * 34.5 + 62 * 34.6) / 100, 2)   # 34.56


def test_buy_fill_impact_cap_blocks_higher_level():
    # max_impact 0 → 只吃賣一價那檔；賣二 35.0 > 34.5 → 不吃。部分成交 38，餘 62
    assert odd_lot_buy_fill(100, [(34.5, 38), (35.0, 100)], max_impact_pct=0.0) == (38, 34.5, 62)


def test_buy_fill_below_min_fill_defers_all():
    # 賣一只有 2 股、min_fill 5 → 盤中視為不成交，全量轉盤後
    assert odd_lot_buy_fill(100, [(34.5, 2)], min_fill=5) == (0, 34.5, 100)


def test_buy_fill_no_book_returns_none():
    assert odd_lot_buy_fill(100, []) is None


def test_buy_fill_exact_depth_boundary():
    # 深度恰等於想買量 → 整筆成交，餘 0
    assert odd_lot_buy_fill(454, [(23.9, 454)]) == (454, 23.9, 0)

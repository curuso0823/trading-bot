"""execution/paper_broker：撮合、現金、持倉"""
from src.execution.paper_broker import PaperBroker


def test_buy_deducts_cash_and_tracks_position():
    b = PaperBroker(initial_cash=1_000_000)
    r = b.place_order("2330", "Buy", 100.0, 1000)   # 零股 1000 股 → amount 100000
    assert r.get("status") == "Filled"
    # 金額 100000 + 手續費 142
    assert abs(b.get_balance() - (1_000_000 - 100_142)) < 1
    assert len(b.get_positions()) == 1


def test_sell_without_position_errors():
    b = PaperBroker(initial_cash=1_000_000)
    assert "error" in b.place_order("2330", "Sell", 100.0, 1000)


def test_insufficient_cash_rejected():
    b = PaperBroker(initial_cash=50_000)
    assert "error" in b.place_order("2330", "Buy", 100.0, 1000)  # 需 ~10萬 > 5萬


def test_profit_roundtrip_increases_cash():
    b = PaperBroker(initial_cash=1_000_000)
    b.place_order("2330", "Buy", 100.0, 2000)
    r = b.place_order("2330", "Sell", 110.0, 2000)
    assert r.get("status") == "Filled"
    assert len(b.get_positions()) == 0
    assert b.get_balance() > 1_000_000   # 賺 2萬，扣成本後仍 > 初始


def test_invalid_order_rejected():
    b = PaperBroker(initial_cash=1_000_000)
    assert "error" in b.place_order("2330", "Buy", 0.0, 1)
    assert "error" in b.place_order("2330", "Buy", 100.0, 0)

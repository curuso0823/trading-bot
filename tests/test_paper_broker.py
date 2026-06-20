"""execution/paper_broker：撮合、現金、持倉"""
import pytest

from src.execution.mmf_sleeve import SyntheticMMF
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


# ───────────── adjust_cash（allocator MMF cash↔sleeve 轉移的現金腿；additive）─────────────

def test_adjust_cash_credit_and_debit():
    """adjust_cash：正→入帳、負→出帳；回傳實際變動量、餘額隨之變。"""
    b = PaperBroker(initial_cash=100_000)
    assert b.adjust_cash(50_000) == pytest.approx(50_000)
    assert b.get_balance() == pytest.approx(150_000)
    assert b.adjust_cash(-30_000) == pytest.approx(-30_000)
    assert b.get_balance() == pytest.approx(120_000)


def test_adjust_cash_no_overdraft_clip():
    """出帳超過現金 → clip 到 0（不透支）；回傳實際扣除額＝原現金的負值。"""
    b = PaperBroker(initial_cash=40_000)
    moved = b.adjust_cash(-999_999)
    assert moved == pytest.approx(-40_000)          # 只扣得到 40k
    assert b.get_balance() == pytest.approx(0.0)


def test_mmf_cash_roundtrip_conserves_total_equity(tmp_path):
    """守恆不變量：broker 現金 + MMF.value() 在 deposit/withdraw round-trip 後不變
    （main.py 把 MMF 轉移與 broker 現金腿原子掛鉤——must-fix #1）。"""
    b = PaperBroker(initial_cash=300_000)
    mmf = SyntheticMMF(state_path=tmp_path / "mmf_sleeve.json", annual_yield=0.015)
    total0 = b.get_balance() + mmf.value()

    # deposit（cash→MMF）：broker 出帳、MMF 等額入單位 —— 模擬 main.py 段 4 原子腿
    amt = 80_000
    debited = -b.adjust_cash(-amt)
    mmf.deposit(debited)
    assert b.get_balance() + mmf.value() == pytest.approx(total0)   # 不重複計、不憑空生

    # withdraw（MMF→cash）：MMF 贖回、broker 等額入帳 —— 模擬 main.py 段 2 原子腿
    actual = mmf.withdraw(50_000)
    b.adjust_cash(actual)
    assert b.get_balance() + mmf.value() == pytest.approx(total0)   # round-trip 守恆

    # 全數退回 MMF 後也守恆
    actual2 = mmf.withdraw(mmf.value())
    b.adjust_cash(actual2)
    assert b.get_balance() + mmf.value() == pytest.approx(total0)
    assert mmf.value() == pytest.approx(0.0, abs=1e-6)

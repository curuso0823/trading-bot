"""risk/risk_guard：熔斷規則、進場核准、統一出場判斷"""
from src.risk.risk_guard import RiskGuard

CAP = 300_000


def test_consecutive_loss_halt():
    rg = RiskGuard(CAP)
    for _ in range(3):
        rg.record_trade_result(-500)   # 小額，避免先觸發日虧損上限
    assert rg.get_status()["halted"]


def test_daily_loss_halt():
    rg = RiskGuard(CAP)
    rg.record_trade_result(-7000)      # -2.33% < -2%
    st = rg.get_status()
    assert st["halted"]
    assert "單日虧損" in st["halt_reason"]


def test_resume_clears_halt():
    rg = RiskGuard(CAP)
    rg.record_trade_result(-7000)
    rg.resume()
    assert not rg.get_status()["halted"]


def test_can_enter_position_cap():
    from src.utils.helpers import load_config
    cap_n = load_config()["entry"]["max_positions"]
    rg = RiskGuard(CAP)
    assert rg.can_enter("x", 50.0, 1, cap_n)[0] is False        # 已達上限 → 擋
    assert rg.can_enter("x", 50.0, 1, cap_n - 1)[0] is True     # 未達上限 → 放行


def test_can_enter_oversize_rejected():
    rg = RiskGuard(CAP)
    ok, _ = rg.can_enter("x", 100.0, 1000, 0)  # 100*1000=10萬 > 30%*30萬=9萬
    assert not ok


def test_can_enter_ok():
    rg = RiskGuard(CAP)
    ok, _ = rg.can_enter("x", 100.0, 500, 0)   # 5萬 < 9萬
    assert ok


def test_check_exits_trailing_triggers():
    rg = RiskGuard(CAP)  # config use_trailing=true, trailing_stop_pct=0.12
    pos = [{"stock_id": "a", "entry_price": 100, "peak_price": 100,
            "last_price": 87, "hold_days": 1}]   # 自峰值 -13%
    assert dict(rg.check_exits(pos)).get("a") == "trailing_stop"


def test_check_exits_trailing_holds():
    rg = RiskGuard(CAP)
    pos = [{"stock_id": "b", "entry_price": 100, "peak_price": 100,
            "last_price": 90, "hold_days": 1}]   # 自峰值 -10% → 不出場
    assert rg.check_exits(pos) == []


def test_check_exits_max_hold():
    rg = RiskGuard(CAP)
    pos = [{"stock_id": "c", "entry_price": 100, "peak_price": 105,
            "last_price": 104, "hold_days": 60}]  # 未觸停損，但持有達 60
    assert dict(rg.check_exits(pos)).get("c") == "max_hold"

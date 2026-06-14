"""tests/test_position_accumulate：部位加碼（零股部分成交→盤後補單合併成完整倉）。
與 PaperBroker 加碼口徑一致，避免兩帳本均價漂移。positions.json 由 conftest clean_state 隔離。"""
from src.execution.order_manager import PositionManager


def test_add_accumulates_reaverages_and_keeps_trail():
    pm = PositionManager()
    pm.add("2884", 30.0, 100, trail_pct=0.08)
    pm.add("2884", 32.0, 100)              # 盤後補單加碼（未帶 trail_pct）
    pos = pm._positions["2884"]
    assert pos["quantity"] == 200
    assert pos["entry_price"] == 31.0       # (30*100 + 32*100)/200
    assert pos["trail_pct"] == 0.08         # 保留首次的 ATR 寬度
    assert pos["peak_price"] == 32.0        # 峰值取大


def test_add_new_position_unchanged_behavior():
    pm = PositionManager()
    pm.add("2330", 100.0, 5, trail_pct=0.09)
    pos = pm._positions["2330"]
    assert pos["quantity"] == 5
    assert pos["entry_price"] == 100.0
    assert pos["trail_pct"] == 0.09


def test_add_fills_missing_trail_on_topup():
    # 首次無 trail_pct（None）、補單帶入 → 補上
    pm = PositionManager()
    pm.add("2317", 50.0, 10, trail_pct=None)
    pm.add("2317", 50.0, 10, trail_pct=0.085)
    assert pm._positions["2317"]["trail_pct"] == 0.085

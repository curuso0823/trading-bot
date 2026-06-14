"""utils/helpers：交易成本、交易日判斷"""
import datetime as dt
from src.utils.helpers import calc_trade_cost, is_trading_day, order_lot


def test_odd_lot_min_fee():
    # 零股小單 amount=10*1=10 → 手續費觸零股最低 1 元
    c = calc_trade_cost(10.0, 1, "buy")
    assert c["fee"] == 1
    assert c["tax"] == 0


def test_sell_cost_with_tax():
    # 零股 1000 股 @100 → amount=100000；手續費 142；證交稅 300
    c = calc_trade_cost(100.0, 1000, "sell")
    assert c["fee"] == 142
    assert c["tax"] == 300
    assert c["total_cost"] == 442


def test_is_trading_day_weekday():
    assert is_trading_day(dt.date(2026, 6, 5)) is True   # 週五


def test_is_trading_day_weekend():
    assert is_trading_day(dt.date(2026, 6, 6)) is False  # 週六


def test_is_trading_day_holiday():
    assert is_trading_day(dt.date(2026, 1, 1)) is False  # 元旦


def test_order_lot_config():
    # config trading.order_lot；零股策略應為 IntradayOdd（且與 lot_size=1 一致）
    assert order_lot() in {"Common", "IntradayOdd", "Odd", "Fixing"}
    assert order_lot() == "IntradayOdd"


def test_paper_broker_accepts_order_lot(tmp_path, monkeypatch):
    # PaperBroker.place_order 接受 order_lot 參數且能成交（介面與 live 一致）
    from src.execution.paper_broker import PaperBroker
    monkeypatch.setattr(PaperBroker, "ACCOUNT_FILE", str(tmp_path / "acc.json"))
    b = PaperBroker(initial_cash=100_000)
    r = b.place_order("2330", "Buy", 100.0, 5, order_lot="IntradayOdd")
    assert r.get("status") == "Filled"


def test_vol_position_pct_high_vol_smaller():
    # 方式A 反波動配重：高波動股配重應 ≤ 低波動股，且落在 [min,max]=[0.10,0.30]
    import pandas as pd
    from src.utils.helpers import vol_position_pct
    n = 40
    low = pd.DataFrame({"close": [100.0 + 0.01 * i for i in range(n)]})            # 近乎無波動
    high = pd.DataFrame({"close": [100.0 * (1.05 if i % 2 else 0.95) for i in range(n)]})  # ±5%來回
    assert vol_position_pct(high) <= vol_position_pct(low)
    assert 0.10 <= vol_position_pct(high) <= 0.30
    assert 0.10 <= vol_position_pct(low) <= 0.30


def test_order_manager_enter_odd_lot(tmp_path, monkeypatch):
    # 盤後零股補單路徑：OrderManager.enter 帶 order_lot="Odd" 能成交
    from src.execution.paper_broker import PaperBroker
    from src.execution.order_manager import OrderManager
    monkeypatch.setattr(PaperBroker, "ACCOUNT_FILE", str(tmp_path / "acc.json"))
    om = OrderManager(PaperBroker(initial_cash=100_000))
    r = om.enter("2330", 100.0, 5, "盤後補單", 2.0, order_lot="Odd")
    assert "error" not in r and r.get("status") == "Filled"


def test_count_trading_days():
    # #4：交易日計數（entry 當日=0、下一交易日=1、跨週末排除週末）
    from src.utils.helpers import count_trading_days
    assert count_trading_days(dt.date(2026, 6, 9), dt.date(2026, 6, 9)) == 0   # 同日
    assert count_trading_days(dt.date(2026, 6, 8), dt.date(2026, 6, 9)) == 1   # 一(8)→二(9)
    # 週五(6/5)→下週一(6/8)：只算 6/8（六日排除）= 1
    assert count_trading_days(dt.date(2026, 6, 5), dt.date(2026, 6, 8)) == 1
    assert count_trading_days(dt.date(2026, 6, 9), dt.date(2026, 6, 1)) == 0   # end<start


def test_exec_slippage_odd_lot():
    # #3：odd_lot 模式回 odd_lot_slippage（config 0.0015）
    from src.utils.helpers import exec_slippage
    s = exec_slippage()
    assert 0 < s < 0.01


def test_position_mgr_hold_days_trading(tmp_path, monkeypatch):
    # #4：PositionManager.get_hold_days 以交易日計（同日=0 → T+1 防呆生效）
    from src.execution.order_manager import PositionManager
    monkeypatch.setattr(PositionManager, "POSITIONS_FILE", str(tmp_path / "pos.json"))
    pm = PositionManager()
    pm.add("2330", 100.0, 10, "t", 2, trail_pct=0.09)
    assert pm.get_hold_days("2330") == 0           # 同日進場 → 0（盤中 T+1 會跳過出場）
    from src.utils.helpers import load_config
    assert pm.max_positions == load_config()["entry"]["max_positions"]   # #11：讀 config（不寫死）

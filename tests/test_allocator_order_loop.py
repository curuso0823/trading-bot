"""main.py allocator 下單迴圈的執行安全性（must-fix #2 回歸鎖）。

驗證重點（對抗 review execution-safety）：
  - T+1 被跳過的賣單其釋金不在 broker 現金內 → 買序以 broker『實際現金』為硬上限縮量，
    永不超買、broker 現金永不 < 0、且不觸發 OrderManager 的 insufficient_cash 串級重試 + 長 sleep。
  - MMF 提領在買序前原子 credit 進 broker（段 2）、回存在買序後原子 debit（段 4）→ 現金守恆。

本檔不 import main（避免其模組級單例 make_broker/FugleFetcher 副作用）；改用 main.py 所用的同一組
primitive（PaperBroker + OrderManager + calc_trade_cost），逐字 replay 段 3 的現金縮量閘邏輯，
鎖住「不超買、不重試 sleep」的不變量。純本地、不打網。
"""
import pytest

from src.execution.mmf_sleeve import SyntheticMMF
from src.execution.order_manager import OrderManager
from src.execution.paper_broker import PaperBroker
from src.utils.helpers import calc_trade_cost, lot_size

LOT = lot_size()


def _gated_buy(order_mgr, broker, sym, px, want_qty, running_cash):
    """逐字複製 main.py 段 3 的現金縮量閘 + 下單（回傳 (filled_qty, new_running_cash)）。"""
    qty = int(want_qty)
    while qty >= 1:
        amt = px * qty * LOT
        fee = calc_trade_cost(px, qty, "buy")["fee"]
        if amt + fee <= running_cash + 1e-6:
            break
        qty -= 1
    if qty < 1:
        return 0, running_cash
    res = order_mgr.enter(sym, px, qty, "allocator_rebalance")
    if "error" in res:
        return 0, running_cash
    return qty, broker.get_balance()


def test_buy_gated_on_actual_cash_after_skipped_sell_no_overdraft(monkeypatch):
    """T+1：賣單被跳過（釋金未實現）→ 買序以 broker 實際現金縮量，現金不為負、不觸發重試 sleep。

    情境＝Phase C 歸零重建首日：全部 hold_days=0 → 所有同日賣單延後；planner 仍把買單照
    full delta_qty 排出。若不縮量＝insufficient_cash 串級 + 每筆最多 3×60s sleep。
    """
    # 任何 time.sleep 被呼叫＝進了 OrderManager 重試路徑＝must-fix #2 未修好
    import src.execution.order_manager as om_mod
    monkeypatch.setattr(om_mod.time, "sleep",
                         lambda *_a, **_k: pytest.fail("不應進入 insufficient_cash 重試 sleep"))

    broker = PaperBroker(initial_cash=20_000)        # 現金有限（賣單釋金被 T+1 跳過 → 無新增現金）
    order_mgr = OrderManager(broker)
    px = 50.0
    # planner 把這些買單照 full 排出（假設賣單會釋金）；實際賣單全被 T+1 跳過 → 只能用 20k 現金買
    planned_buys = [("0050", 600), ("00981A", 400), ("00991A", 400)]   # 名目遠超 20k

    running_cash = broker.get_balance()              # 段 3 起點＝broker 實際現金（不含被跳過賣單）
    total_spent = 0.0
    for sym, want in planned_buys:
        filled, running_cash = _gated_buy(order_mgr, broker, sym, px, want, running_cash)
        total_spent += filled * px * LOT

    assert broker.get_balance() >= 0.0               # 現金永不為負（不融資、不 cascade）
    assert running_cash == pytest.approx(broker.get_balance())
    # 買到的總名目受 20k 現金約束（含手續費 → 略少於 20k）
    assert total_spent <= 20_000 + 1e-6
    # 至少買到一些（現金足夠第一筆的縮量量）、且現金幾乎用罄
    assert total_spent > 0


def test_mmf_withdraw_before_buys_funds_them_and_conserves(tmp_path, monkeypatch):
    """段 2 MMF 提領在買序前 credit 進 broker → place_order 看得到墊款；現金守恆、不重試。"""
    import src.execution.order_manager as om_mod
    monkeypatch.setattr(om_mod.time, "sleep",
                         lambda *_a, **_k: pytest.fail("不應進入重試 sleep"))

    broker = PaperBroker(initial_cash=1_000)         # broker 現金極少
    mmf = SyntheticMMF(state_path=tmp_path / "mmf_sleeve.json", annual_yield=0.015)
    mmf.deposit(100_000)                             # MMF 充裕
    order_mgr = OrderManager(broker)
    total0 = broker.get_balance() + mmf.value()

    # 段 2：提領墊買序（原子）— 模擬 planner 算出的 withdraw 墊款
    withdraw_amt = 30_000
    actual = mmf.withdraw(withdraw_amt)
    broker.adjust_cash(actual)
    assert broker.get_balance() + mmf.value() == pytest.approx(total0)   # 提領腿守恆

    # 段 3：用墊款後的 broker 現金買（縮量閘）
    px = 50.0
    running_cash = broker.get_balance()
    assert running_cash == pytest.approx(1_000 + 30_000)
    filled, running_cash = _gated_buy(order_mgr, broker, "0050", px, 500, running_cash)
    assert filled > 0                                # 墊款讓買單成交（place_order 看得到現金）
    assert broker.get_balance() >= 0.0
    # 買完 broker 現金 + MMF 仍守恆（買股把現金換成持倉市值；此處只驗現金/MMF 不憑空增減）
    spent = filled * px * LOT + calc_trade_cost(px, filled, "buy")["fee"]
    assert broker.get_balance() + mmf.value() == pytest.approx(total0 - spent)

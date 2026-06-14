"""
notebooks/c_paper_validate.py
Phase C 驗證：用 PaperBroker 驅動完整 下單→部位→風控 循環，驗證狀態機。
不需 Shioaji。每次執行先清空狀態確保確定性。
用法：.venv\\Scripts\\python.exe notebooks\\c_paper_validate.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from src.execution.paper_broker import PaperBroker
from src.execution.order_manager import OrderManager, PositionManager
from src.risk.risk_guard import RiskGuard
from src.utils.helpers import lot_size

CAP = 300_000
STATE = ["paper_account.json", "positions.json", "daily_risk_state.json"]


def reset():
    for fn in STATE:
        Path(f"data/processed/{fn}").unlink(missing_ok=True)


results = []
def check(name, cond):
    results.append(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    reset()

    # ---------- Part A：下單 + 部位 + 進場風控 ----------
    print("=== A. 下單 / 部位 / 進場核准（PaperBroker 撮合）===")
    broker = PaperBroker(initial_cash=CAP)
    broker.connect()
    omg = OrderManager(broker)
    pmg = PositionManager()
    rg = RiskGuard(total_capital=CAP)

    for sid, px in [("1111", 50.0), ("2222", 60.0), ("3333", 40.0)]:
        qty = max(1, int(CAP * 0.30 / (px * lot_size())))
        ok, why = rg.can_enter(sid, px, qty, len(pmg.summary()))
        if ok:
            res = omg.enter(sid, px, qty, "test", 3.0)
            if "error" not in res:
                pmg.add(sid, px, qty, "test", 3.0)
    check("進場 3 檔成功", len(pmg.summary()) == 3)
    check("PaperBroker 現金已扣（< 初始）", broker.get_balance() < CAP)
    check("PaperBroker 持倉 = 3", len(broker.get_positions()) == 3)

    ok4, _ = rg.can_enter("4444", 30.0, 1, len(pmg.summary()))
    check("第 4 檔被持倉上限(3)擋下", not ok4)

    okbig, _ = rg.can_enter("9999", 1000.0, 1000, 0)  # 1000股×1000元=100萬 > 30%*30萬
    check("超額單股部位被擋下", not okbig)

    pmg.update_prices({"1111": 50.0 * 0.945})  # -5.5%
    to_exit = rg.check_stop_loss(pmg.get_all_pnl())
    check("停損偵測到 1111(-5.5%)", "1111" in to_exit)
    q1111 = next(p["quantity"] for p in pmg.summary() if p["stock_id"] == "1111")
    sell = omg.exit("1111", 50.0 * 0.945, q1111, "stop_loss")
    pmg.remove("1111")
    check("停損出場成交且部位移除", "error" not in sell and len(pmg.summary()) == 2)

    # ---------- Part B：連虧熔斷 + 持久化 ----------
    print("\n=== B. 連虧熔斷 + 持久化 ===")
    reset()
    rga = RiskGuard(total_capital=CAP)
    for _ in range(3):
        rga.record_trade_result(-500)   # 小額，避免先觸發日虧損上限
    check("連虧 3 筆 → 熔斷", rga.get_status()["halted"])
    okh, _ = rga.can_enter("5555", 30.0, 1, 0)
    check("熔斷中禁止進場", not okh)

    rgb = RiskGuard(total_capital=CAP)  # 重新載入（測持久化）
    check("熔斷狀態持久化（重載仍熔斷）", rgb.get_status()["halted"])
    rgb.resume()
    rgc = RiskGuard(total_capital=CAP)
    check("resume 後持久化解除", not rgc.get_status()["halted"])

    # ---------- Part C：日虧損上限熔斷 ----------
    print("\n=== C. 日虧損上限熔斷 ===")
    reset()
    rgd = RiskGuard(total_capital=CAP)
    rgd.record_trade_result(-7000)   # -2.33% < -2% 上限
    st = rgd.get_status()
    check("單日大虧 → 熔斷", st["halted"])
    check("熔斷原因為日虧損", "單日虧損" in st["halt_reason"])

    print(f"\n{'='*40}")
    print(f"Phase C 驗證：{sum(results)}/{len(results)} PASS"
          + ("  ✅" if all(results) else "  ❌"))
    print("="*40)
    reset()  # 清乾淨
    sys.exit(0 if all(results) else 2)


if __name__ == "__main__":
    main()

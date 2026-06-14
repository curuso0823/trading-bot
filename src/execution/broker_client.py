"""
execution/broker_client.py
永豐 Shioaji API 封裝
所有 shioaji 操作都在這裡，上層模組不直接接觸 SDK
"""
import os
from loguru import logger
from dotenv import load_dotenv
from src.utils.helpers import order_lot as cfg_order_lot

load_dotenv()


class BrokerClient:
    """
    永豐 Shioaji 客戶端封裝
    simulation=True 時為模擬盤，False 才是實盤
    切換實盤前請三思並在模擬盤完整測試 10 個交易日
    """

    def __init__(self):
        self._api = None
        self._simulation = os.getenv("SHIOAJI_SIMULATION", "true").lower() == "true"
        if self._simulation:
            logger.warning("⚠️  模擬盤模式 — 不會產生真實下單")

    def connect(self) -> bool:
        """建立連線，回傳是否成功"""
        try:
            import shioaji as sj

            self._api = sj.Shioaji(simulation=self._simulation)
            accounts = self._api.login(
                api_key=os.getenv("SHIOAJI_API_KEY"),
                secret_key=os.getenv("SHIOAJI_SECRET_KEY"),
            )

            # CA 憑證（實盤下單必須）
            if not self._simulation:
                self._api.activate_ca(
                    ca_path=os.getenv("SHIOAJI_CA_PATH"),
                    ca_passwd=os.getenv("SHIOAJI_CA_PASSWORD"),
                    person_id=accounts[0].person_id,
                )

            logger.info(f"Shioaji 連線成功 | simulation={self._simulation} | 帳戶數={len(accounts)}")
            return True

        except ImportError:
            logger.error("shioaji 未安裝：pip install shioaji")
            return False
        except Exception as e:
            logger.error(f"Shioaji 連線失敗：{e}")
            return False

    def disconnect(self):
        if self._api:
            self._api.logout()
            logger.info("Shioaji 已登出")

    # ---------- 帳戶查詢 ----------

    def get_balance(self) -> float:
        """取得可用資金（元）"""
        if not self._api:
            return 0.0
        try:
            account = self._api.stock_account
            balance = self._api.get_account_balance(account)
            return float(balance.acc_balance)
        except Exception as e:
            logger.error(f"查詢餘額失敗：{e}")
            return 0.0

    def get_positions(self) -> list[dict]:
        """
        取得目前持倉
        回傳: [{'stock_id': str, 'quantity': int, 'cost': float, 'pnl': float}]
        """
        if not self._api:
            return []
        try:
            positions = self._api.list_positions(self._api.stock_account)
            result = []
            for pos in positions:
                result.append({
                    "stock_id": pos.code,
                    "quantity": pos.quantity,   # 張數
                    "cost": pos.price,          # 均成本
                    "pnl": pos.pnl,             # 未實現損益
                    "last_price": pos.last_price,
                })
            return result
        except Exception as e:
            logger.error(f"查詢持倉失敗：{e}")
            return []

    # ---------- 下單操作 ----------

    def place_order(self, stock_id: str, action: str,
                    price: float, quantity: int,
                    order_type: str = "ROD", order_lot: str = None) -> dict:
        """
        掛單
        action: 'Buy' or 'Sell'
        quantity: 委託量。整股(Common/Fixing)單位=張(1張=1000股)；零股(IntradayOdd/Odd)單位=股。
                  須與 trading.lot_size 一致（lot_size=1→零股=股；=1000→整股=張）。
        order_type: 'ROD'(當日有效) / 'IOC' / 'FOK'
        order_lot: Common/IntradayOdd/Odd/Fixing；None→取 config trading.order_lot。
                   ⚠️ 修正：先前未設 order_lot → Shioaji 預設 Common(整股)，零股策略 live 會誤下整股。
        回傳: {'order_id': str, 'status': str} 或 {'error': str}
        """
        if not self._api:
            logger.error("BrokerClient 尚未連線")
            return {"error": "not_connected"}

        try:
            import shioaji as sj

            lot = order_lot or cfg_order_lot()
            sj_lot = getattr(sj.constant.StockOrderLot, lot, None)
            if sj_lot is None:
                logger.warning(f"未知 order_lot={lot}，改用 Common(整股)")
                sj_lot = sj.constant.StockOrderLot.Common

            contract = self._api.Contracts.Stocks[stock_id]
            order = self._api.Order(
                price=price,
                quantity=quantity,
                action=sj.constant.Action.Buy if action == "Buy" else sj.constant.Action.Sell,
                price_type=sj.constant.StockPriceType.LMT,  # 限價
                order_type=getattr(sj.constant.OrderType, order_type),
                order_lot=sj_lot,                            # 整股/盤中零股/盤後零股/定價
                account=self._api.stock_account,
            )

            trade = self._api.place_order(contract, order)
            logger.info(f"下單成功 | {action} {stock_id} {quantity} ({lot}) @{price} | id={trade.order.id}")

            return {
                "order_id": trade.order.id,
                "status": trade.status.status,
                "stock_id": stock_id,
                "action": action,
                "price": price,
                "quantity": quantity,
            }

        except Exception as e:
            logger.error(f"下單失敗 | {action} {stock_id} | {e}")
            return {"error": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        """取消委託"""
        if not self._api:
            return False
        try:
            # 需要先 update_status 取得最新委託物件
            self._api.update_status(self._api.stock_account)
            trades = self._api.list_trades()
            target = next((t for t in trades if t.order.id == order_id), None)
            if not target:
                logger.warning(f"找不到委託 {order_id}")
                return False
            self._api.cancel_order(target)
            logger.info(f"取消委託成功 | order_id={order_id}")
            return True
        except Exception as e:
            logger.error(f"取消委託失敗 | {order_id} | {e}")
            return False

    def cancel_all_orders(self) -> int:
        """緊急：取消所有未成交委託，回傳取消數量"""
        if not self._api:
            return 0
        try:
            self._api.update_status(self._api.stock_account)
            trades = self._api.list_trades()
            cancelled = 0
            for trade in trades:
                if trade.status.status in ["PendingSubmit", "PreSubmitted", "Submitted"]:
                    self._api.cancel_order(trade)
                    cancelled += 1
            logger.warning(f"緊急取消所有委託：{cancelled} 筆")
            return cancelled
        except Exception as e:
            logger.error(f"緊急取消失敗：{e}")
            return 0

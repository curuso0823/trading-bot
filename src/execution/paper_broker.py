"""
execution/paper_broker.py
模擬盤券商：本地撮合，公開介面與 BrokerClient 對齊（可 drop-in 替換），
讓系統在 Shioaji 開戶通過前就能端到端跑模擬盤、驗證下單/風控/部位邏輯。

撮合假設（紙上交易）：限價單一律以委託價成交，扣除台股實際交易成本。
帳戶狀態（現金 + 持倉）本地 JSON 持久化，程式重啟不丟失。
"""
import json
from pathlib import Path
from loguru import logger
from src.utils.helpers import calc_trade_cost, lot_size, order_lot as cfg_order_lot


class PaperBroker:
    ACCOUNT_FILE = "data/processed/paper_account.json"

    def __init__(self, initial_cash: float = 300_000):
        self._initial_cash = initial_cash
        self._cash = initial_cash
        self._positions: dict[str, dict] = {}   # stock_id -> {quantity(張), cost(每股均價)}
        self._order_seq = 0
        self._load()

    # ---------- 持久化 ----------
    def _load(self):
        p = Path(self.ACCOUNT_FILE)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            self._cash = d.get("cash", self._initial_cash)
            self._positions = d.get("positions", {})
            self._order_seq = d.get("order_seq", 0)
            logger.info(f"模擬帳戶載入：現金 {self._cash:,.0f}，持倉 {len(self._positions)} 檔")

    def _save(self):
        p = Path(self.ACCOUNT_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"cash": self._cash, "positions": self._positions,
                       "order_seq": self._order_seq}, f, ensure_ascii=False, indent=2)

    # ---------- BrokerClient 對齊介面 ----------
    def connect(self) -> bool:
        logger.warning("📝 PaperBroker（模擬盤）— 本地撮合，不會產生真實下單")
        return True

    def disconnect(self):
        self._save()

    def get_balance(self) -> float:
        return float(self._cash)

    def get_positions(self) -> list[dict]:
        return [{"stock_id": sid, "quantity": p["quantity"], "cost": p["cost"],
                 "pnl": 0.0, "last_price": p["cost"]}
                for sid, p in self._positions.items()]

    def place_order(self, stock_id: str, action: str, price: float,
                    quantity: int, order_type: str = "ROD",
                    order_lot: str = None) -> dict:
        # order_lot：模擬盤不做真實時段路由，僅記錄以與 live 介面一致
        order_lot = order_lot or cfg_order_lot()
        if quantity <= 0 or price <= 0:
            return {"error": "invalid_order"}

        amount = price * quantity * lot_size()  # 整股×1000 / 零股×1
        cost = calc_trade_cost(price, quantity, "buy" if action == "Buy" else "sell")

        if action == "Buy":
            total = amount + cost["fee"]
            if total > self._cash:
                return {"error": "insufficient_cash"}
            self._cash -= total
            pos = self._positions.get(stock_id)
            if pos:  # 加碼 → 重算均價
                new_qty = pos["quantity"] + quantity
                pos["cost"] = (pos["cost"] * pos["quantity"] + price * quantity) / new_qty
                pos["quantity"] = new_qty
            else:
                self._positions[stock_id] = {"quantity": quantity, "cost": price}
        else:  # Sell
            pos = self._positions.get(stock_id)
            if not pos or pos["quantity"] < quantity:
                return {"error": "no_position"}
            self._cash += amount - cost["fee"] - cost["tax"]
            pos["quantity"] -= quantity
            if pos["quantity"] <= 0:
                del self._positions[stock_id]

        self._order_seq += 1
        self._save()
        logger.info(f"📝 模擬成交 | {action} {stock_id} x{quantity} ({order_lot}) @{price} | 餘額 {self._cash:,.0f}")
        return {"order_id": f"PAPER{self._order_seq:06d}", "status": "Filled",
                "stock_id": stock_id, "action": action, "price": price, "quantity": quantity}

    def cancel_order(self, order_id: str) -> bool:
        return True  # 紙上即時成交，無待撤委託

    def cancel_all_orders(self) -> int:
        return 0

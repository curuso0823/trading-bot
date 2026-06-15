"""
execution/order_manager.py
下單管理：進場 / 出場 / 漲停重試 / 委託監控
"""
import time
import pandas as pd
from loguru import logger
from src.execution.broker_client import BrokerClient
from src.utils.logger import log_trade
from src.utils.helpers import load_config, calc_trade_cost


class OrderManager:
    """
    下單邏輯管理器
    所有進出場操作的唯一入口，不繞過此層直接呼叫 BrokerClient
    """

    LIMIT_UP_RETRY = 3       # 漲停時最多重試次數
    LIMIT_UP_WAIT = 60       # 每次重試間隔（秒）

    def __init__(self, broker: BrokerClient):
        self.broker = broker
        self.cfg = load_config()

    def enter(self, stock_id: str, price: float, quantity: int,
              reason: str, score: float = None, order_lot: str = None) -> dict:
        """
        進場下單（限價），被拒時重試（實盤：漲停買不到 → 等價格脫離漲停再試）。
        order_lot: None→config 預設(盤中零股)；盤後補單傳 "Odd"(盤後零股)。
        TODO（需 Shioaji order-status 介面，開戶接上後補）：
          - 部分成交：對未成交餘量續掛
          - 委託逾時取消：超時未成交則撤單
        """
        result = {"error": "not_placed"}
        for attempt in range(self.LIMIT_UP_RETRY):
            result = self.broker.place_order(stock_id, "Buy", price, quantity, order_lot=order_lot)
            if "error" not in result:
                break
            logger.warning(f"進場下單被拒，重試 {attempt+1}/{self.LIMIT_UP_RETRY} "
                           f"| {stock_id} | {result.get('error')}")
            if attempt < self.LIMIT_UP_RETRY - 1:
                time.sleep(self.LIMIT_UP_WAIT)

        if "error" in result:
            logger.error(f"進場失敗（重試 {self.LIMIT_UP_RETRY} 次仍失敗）| {stock_id} | {result['error']}")
            return result

        log_trade("BUY", stock_id, price, quantity, reason, score)
        cost = calc_trade_cost(price, quantity, "buy")
        logger.info(f"進場成本估算：{cost}")
        return result

    def exit(self, stock_id: str, price: float, quantity: int,
             reason: str) -> dict:
        """
        出場下單（限價）
        """
        result = self.broker.place_order(stock_id, "Sell", price, quantity)

        if "error" in result:
            logger.error(f"出場失敗 | {stock_id} | {result['error']}")
            return result

        log_trade("SELL", stock_id, price, quantity, reason)
        return result

    def emergency_exit_all(self, positions: list[dict],
                           current_prices: dict) -> list[dict]:
        """
        緊急全部出場（市價接近賣出）
        觸發條件：RiskGuard 熔斷
        """
        logger.critical("⚠️ 緊急出場：清除所有部位")
        self.broker.cancel_all_orders()
        results = []
        for pos in positions:
            sid = pos["stock_id"]
            price = current_prices.get(sid, pos["cost"])
            # 緊急出場用跌停價附近掛（確保成交），實際使用時考慮市價單
            result = self.exit(sid, price * 0.95, pos["quantity"], reason="emergency_exit")
            results.append(result)
        return results


# ────────────────────────────────────────────────────────
"""
execution/position_manager.py
部位追蹤：持倉狀態、損益計算、本地持久化
"""
import json
import os
from datetime import date
from pathlib import Path
from loguru import logger
from src.utils.helpers import load_config, count_trading_days


class PositionManager:
    """
    部位追蹤器
    - 本地 JSON 持久化，程式重啟不丟失狀態
    - 提供即時損益查詢供 RiskGuard 使用
    """

    POSITIONS_FILE = "data/processed/positions.json"

    def __init__(self):
        self.cfg = load_config()
        # #11：最多同時持倉檔數改讀 config（與 RiskGuard/回測同源，避免寫死漂移）
        self.max_positions = int(self.cfg.get("entry", {}).get("max_positions", 6))
        self._positions: dict[str, dict] = {}
        self._load()

    def _load(self):
        """從本地 JSON 載入持倉狀態"""
        path = Path(self.POSITIONS_FILE)
        if path.exists():
            with open(path, encoding="utf-8") as f:
                self._positions = json.load(f)
            logger.info(f"持倉狀態載入：{len(self._positions)} 檔")
        else:
            self._positions = {}

    def _save(self):
        """持久化到本地 JSON"""
        path = Path(self.POSITIONS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._positions, f, ensure_ascii=False, indent=2, default=str)

    def add(self, stock_id: str, price: float, quantity: int,
            reason: str = "", score: float = None, trail_pct: float = None):
        """記錄進場；若已持有同檔 → 加碼（重算均價、合併張數，保留最早 entry_date 與既有 trail_pct、峰值取大）。
        與 PaperBroker 加碼口徑一致（零股部分成交→盤後補單合併成完整倉時，兩帳本均價不漂移）。
        trail_pct：A1 進場時定的 ATR 移動停損寬度（None=用 config 固定%）。"""
        existing = self._positions.get(stock_id)
        if existing and int(existing.get("quantity", 0)) > 0:   # 加碼（部分成交 + 盤後補單）
            new_qty = int(existing["quantity"]) + int(quantity)
            if new_qty <= 0:
                return
            existing["entry_price"] = round(
                (existing["entry_price"] * existing["quantity"] + price * quantity) / new_qty, 4)
            existing["quantity"] = new_qty
            existing["last_price"] = price
            existing["peak_price"] = max(existing.get("peak_price", price), price)
            if existing.get("trail_pct") is None and trail_pct is not None:
                existing["trail_pct"] = trail_pct
            self._save()
            logger.info(f"部位加碼 | {stock_id} | +{quantity} → {new_qty}股 @均{existing['entry_price']}")
            return
        self._positions[stock_id] = {
            "stock_id": stock_id,
            "entry_price": price,
            "quantity": quantity,
            "entry_date": date.today().isoformat(),
            "reason": reason,
            "score": score,
            "last_price": price,
            "peak_price": price,      # 峰值（移動停損用，進場後逐日更新）
            "trail_pct": trail_pct,   # A1：進場時固定的移動停損寬度（ATR 自適應）
        }
        self._save()
        logger.info(f"部位新增 | {stock_id} | {quantity}股 @{price}")

    def remove(self, stock_id: str):
        """記錄出場"""
        if stock_id in self._positions:
            del self._positions[stock_id]
            self._save()
            logger.info(f"部位移除 | {stock_id}")

    def update_prices(self, prices: dict[str, float]):
        """更新最新價格 + 峰值（盤中監控用）"""
        for sid, price in prices.items():
            if sid in self._positions:
                pos = self._positions[sid]
                pos["last_price"] = price
                pos["peak_price"] = max(pos.get("peak_price", pos["entry_price"]), price)
        self._save()

    def get_pnl(self, stock_id: str) -> float:
        """取得單一持倉未實現損益率"""
        pos = self._positions.get(stock_id)
        if not pos:
            return 0.0
        entry = pos["entry_price"]
        last = pos.get("last_price", entry)
        return (last - entry) / entry if entry > 0 else 0.0

    def get_all_pnl(self) -> dict[str, float]:
        """取得所有持倉損益率"""
        return {sid: self.get_pnl(sid) for sid in self._positions}

    def get_hold_days(self, stock_id: str) -> int:
        """取得持倉『交易日』數（#4：與回測 max_hold 的 bar 計數對齊；entry 當日=0、下一交易日=1）。
        同時讓盤中 T+1 防呆（hold_days<1）以交易日判定，跨週末更正確。"""
        pos = self._positions.get(stock_id)
        if not pos:
            return 0
        entry_date = date.fromisoformat(pos["entry_date"])
        return count_trading_days(entry_date, date.today())

    def can_add_position(self) -> bool:
        """是否還能新增持倉（未達上限，config entry.max_positions）"""
        return len(self._positions) < self.max_positions

    def summary(self) -> list[dict]:
        """取得完整持倉摘要（供 Telegram 通知用）"""
        result = []
        for sid, pos in self._positions.items():
            result.append({
                **pos,
                "pnl_pct": round(self.get_pnl(sid) * 100, 2),
                "hold_days": self.get_hold_days(sid),
            })
        return result

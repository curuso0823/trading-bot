"""
risk/risk_guard.py
風控守門員：停損 / 單日虧損上限 / 連虧熔斷
所有交易前都必須通過 RiskGuard 的核准
"""
import json
from datetime import date
from pathlib import Path
from loguru import logger
from src.utils.helpers import load_config, load_settings, lot_size


class RiskGuard:
    """
    風控規則（依優先順序）：
    1. 單筆停損 -5%（硬性，盤中監控）
    2. 單日虧損 > 總資金 -2% → 全停機
    3. 連虧 3 筆 → 暫停等人工審核
    4. 單股倉位 ≤ 總資金 30%
    5. 持倉數 ≤ 6 檔
    """

    DAILY_STATE_FILE = "data/processed/daily_risk_state.json"

    def __init__(self, total_capital: float):
        self.total_capital = total_capital
        cfg = load_config()
        settings = load_settings()
        self.stop_loss_pct = cfg["exit"]["stop_loss_pct"]             # -0.05
        self.max_position_pct = cfg["entry"]["position_size_pct"]     # 0.30
        self.max_positions = cfg["entry"]["max_positions"]            # 6
        self.daily_loss_limit = settings["risk"]["daily_loss_limit"]  # -0.02
        self.consec_loss_halt = settings["risk"]["consecutive_loss_halt"]  # 3
        # 出場參數（與回測同口徑：趨勢跟隨用移動停損）
        self.take_profit_pct = cfg["exit"].get("take_profit_pct")     # null=不停利
        self.max_hold_days = cfg["exit"].get("max_hold_days")         # 60
        self.use_trailing = cfg["exit"].get("use_trailing", False)
        self.trailing_stop_pct = cfg["exit"].get("trailing_stop_pct", 0.12)
        self._state = self._load_state()

    # ─────────────────────────────────────
    # 狀態管理（每日重置）
    # ─────────────────────────────────────

    def _load_state(self) -> dict:
        path = Path(self.DAILY_STATE_FILE)
        if path.exists():
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
            # 若是新的一天，重置日內計數器
            if state.get("date") != date.today().isoformat():
                state = self._fresh_state()
        else:
            state = self._fresh_state()
        return state

    def _fresh_state(self) -> dict:
        return {
            "date": date.today().isoformat(),
            "daily_pnl": 0.0,       # 今日已實現損益
            "consecutive_loss": 0,  # 連虧計數
            "halted": False,         # 是否已觸發熔斷
            "halt_reason": "",
        }

    def _save_state(self):
        path = Path(self.DAILY_STATE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    # ─────────────────────────────────────
    # 進場核准
    # ─────────────────────────────────────

    def can_enter(self, stock_id: str, price: float, quantity: int,
                  current_positions: int) -> tuple[bool, str]:
        """
        進場前檢查，回傳 (是否允許, 拒絕原因)
        """
        # 1. 系統是否已熔斷
        if self._state["halted"]:
            return False, f"系統熔斷中：{self._state['halt_reason']}"

        # 2. 持倉數上限
        if current_positions >= self.max_positions:
            return False, f"持倉已達上限（{self.max_positions} 檔）"

        # 3. 單股倉位上限
        position_value = price * quantity * lot_size()  # 整股×1000 / 零股×1
        if position_value > self.total_capital * self.max_position_pct:
            return False, f"單股倉位超過上限（{self.max_position_pct*100:.0f}% 總資金）"

        return True, ""

    # ─────────────────────────────────────
    # 盤中監控（每 5 分鐘呼叫）
    # ─────────────────────────────────────

    def check_stop_loss(self, positions_pnl: dict[str, float]) -> list[str]:
        """
        檢查哪些持倉需要停損
        positions_pnl: {stock_id: pnl_pct}（負數為虧損）
        回傳：需要停損出場的 stock_id 清單
        """
        to_exit = []
        for sid, pnl in positions_pnl.items():
            if pnl <= self.stop_loss_pct:
                logger.warning(f"停損觸發 | {sid} | 損益={pnl*100:.1f}%")
                to_exit.append(sid)
        return to_exit

    def check_max_hold(self, positions_hold_days: dict[str, int],
                       max_days: int = 15) -> list[str]:
        """持有超過上限天數的部位需出場（舊介面，保留相容）"""
        return [sid for sid, days in positions_hold_days.items() if days >= max_days]

    def check_exits(self, positions: list[dict]) -> list[tuple[str, str]]:
        """
        config 驅動的統一出場判斷（與回測 backtester 同口徑）。
        positions 每筆需含：stock_id, entry_price, peak_price, last_price, hold_days
        回傳 [(stock_id, reason), ...]；reason ∈ trailing_stop / stop_loss / take_profit / max_hold
        優先序：移動(或固定)停損 > 停利 > 持有上限
        """
        out = []
        for p in positions:
            sid = p["stock_id"]
            entry = p.get("entry_price", 0) or 0
            last = p.get("last_price", entry)
            peak = p.get("peak_price", entry) or entry
            hold = p.get("hold_days", 0)
            pnl = (last - entry) / entry if entry > 0 else 0.0
            reason = None

            if self.use_trailing:
                trail = p.get("trail_pct") or self.trailing_stop_pct  # A1：進場時定的 ATR 寬度，無則用固定%
                if peak > 0 and (last - peak) / peak <= -trail:
                    reason = "trailing_stop"
            elif pnl <= self.stop_loss_pct:
                reason = "stop_loss"

            if reason is None and self.take_profit_pct and pnl >= self.take_profit_pct:
                reason = "take_profit"
            if reason is None and self.max_hold_days and hold >= self.max_hold_days:
                reason = "max_hold"

            if reason:
                logger.warning(f"出場訊號 | {sid} | {reason} | pnl={pnl*100:.1f}% "
                               f"自峰值={(last/peak-1)*100:.1f}% 持有{hold}日")
                out.append((sid, reason))
        return out

    # ─────────────────────────────────────
    # 出場後更新（每筆交易結束呼叫）
    # ─────────────────────────────────────

    def record_trade_result(self, pnl_amount: float):
        """
        記錄已實現損益，觸發熔斷判斷
        pnl_amount: 已實現損益（元，負數為虧損）
        """
        self._state["daily_pnl"] += pnl_amount

        # 更新連虧計數
        if pnl_amount < 0:
            self._state["consecutive_loss"] += 1
        else:
            self._state["consecutive_loss"] = 0  # 獲利就重置

        # 觸發熔斷判斷
        daily_pnl_pct = self._state["daily_pnl"] / self.total_capital
        if daily_pnl_pct <= self.daily_loss_limit:
            self._trigger_halt(f"單日虧損達 {daily_pnl_pct*100:.1f}%（上限 {self.daily_loss_limit*100:.0f}%）")

        elif self._state["consecutive_loss"] >= self.consec_loss_halt:
            self._trigger_halt(f"連續虧損 {self._state['consecutive_loss']} 筆")

        self._save_state()

    def _trigger_halt(self, reason: str):
        """觸發熔斷"""
        self._state["halted"] = True
        self._state["halt_reason"] = reason
        logger.critical(f"🔴 風控熔斷：{reason}")

    def resume(self):
        """人工審核後手動解除熔斷"""
        self._state["halted"] = False
        self._state["halt_reason"] = ""
        self._state["consecutive_loss"] = 0
        self._save_state()
        logger.info("✅ 熔斷已解除，系統恢復交易")

    # ─────────────────────────────────────
    # 狀態查詢（供 Telegram 報表）
    # ─────────────────────────────────────

    def get_status(self) -> dict:
        return {
            **self._state,
            "daily_pnl_pct": round(
                self._state["daily_pnl"] / self.total_capital * 100, 2
            ),
        }

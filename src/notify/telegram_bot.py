"""
notify/telegram_bot.py
Telegram 推播通知
涵蓋：進場訊號 / 停損警報 / 每日盈虧摘要 / 系統異常
"""
import os
import asyncio
import traceback
from datetime import date
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


class TelegramNotifier:
    """
    Telegram Bot 推播封裝
    使用 python-telegram-bot v20+（async）
    """

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not self.token or not self.chat_id:
            logger.warning("Telegram 未設定（TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID），通知功能停用")
            self._enabled = False
        else:
            self._enabled = True

    def _send(self, text: str):
        """同步包裝（供排程器呼叫）"""
        if not self._enabled:
            logger.info(f"[Telegram 停用] {text[:80]}...")
            return
        try:
            import telegram
            async def _do():
                bot = telegram.Bot(token=self.token)
                await bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode="HTML",
                )
            asyncio.run(_do())
        except Exception as e:
            logger.error(f"Telegram 推播失敗：{e}")

    # ─────────────────────────────────────
    # 各類通知模板
    # ─────────────────────────────────────

    def send_entry_signal(self, stock_id: str, stock_name: str,
                          price: float, quantity: int,
                          chip_score: float, reason: str):
        """進場訊號通知"""
        msg = (
            f"📈 <b>進場訊號</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"股票：{stock_id} {stock_name}\n"
            f"方向：買進\n"
            f"價格：${price:.2f}\n"
            f"數量：{quantity} 張\n"
            f"籌碼分：{chip_score:.1f}\n"
            f"原因：{reason}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚠️ 進場後請設定停損 {price * 0.95:.2f}"
        )
        self._send(msg)

    def send_exit_signal(self, stock_id: str, stock_name: str,
                         entry_price: float, exit_price: float,
                         quantity: int, reason: str, pnl_pct: float):
        """出場通知"""
        emoji = "✅" if pnl_pct >= 0 else "🔴"
        msg = (
            f"{emoji} <b>出場</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"股票：{stock_id} {stock_name}\n"
            f"原因：{reason}\n"
            f"進場：${entry_price:.2f}\n"
            f"出場：${exit_price:.2f}\n"
            f"損益：{pnl_pct:+.1f}%\n"
            f"張數：{quantity} 張"
        )
        self._send(msg)

    def send_stop_loss_alert(self, stock_id: str, price: float, pnl_pct: float):
        """停損警報（緊急）"""
        msg = (
            f"🚨 <b>停損觸發</b>\n"
            f"股票：{stock_id}\n"
            f"當前價：${price:.2f}\n"
            f"損益：{pnl_pct*100:+.1f}%\n"
            f"正在執行停損出場..."
        )
        self._send(msg)

    def send_halt_alert(self, reason: str):
        """熔斷警報"""
        msg = (
            f"🔴 <b>風控熔斷</b>\n"
            f"原因：{reason}\n"
            f"系統已暫停交易\n"
            f"請人工審核後執行 resume() 恢復"
        )
        self._send(msg)

    def send_daily_summary(self, positions: list[dict],
                           daily_pnl: float, total_capital: float,
                           candidates_count: int):
        """每日盤後摘要（13:30 後推送）"""
        today = date.today().isoformat()
        pnl_pct = daily_pnl / total_capital * 100 if total_capital else 0

        pos_lines = ""
        for pos in positions:
            emoji = "↑" if pos["pnl_pct"] >= 0 else "↓"
            pos_lines += f"  {emoji} {pos['stock_id']} {pos['pnl_pct']:+.1f}% ({pos['hold_days']}日)\n"

        msg = (
            f"📊 <b>每日摘要 {today}</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"今日損益：{pnl_pct:+.1f}%（{daily_pnl:+.0f} 元）\n"
            f"今日候選：{candidates_count} 檔\n"
            f"━━━━━━━━━━━━━━━\n"
            f"目前持倉：\n{pos_lines if pos_lines else '  （無持倉）'}"
        )
        self._send(msg)

    def send_error(self, error: Exception, context: str = ""):
        """系統錯誤通知"""
        tb = traceback.format_exc()[-500:]  # 最後 500 字元避免太長
        msg = (
            f"⚠️ <b>系統錯誤</b>\n"
            f"位置：{context}\n"
            f"錯誤：{str(error)[:200]}\n"
            f"<pre>{tb}</pre>"
        )
        self._send(msg)

    def send_text(self, text: str) -> bool:
        """自訂文字通知；回傳是否已嘗試送出（供 NotifyManager 路由）"""
        self._send(text)
        return self._enabled

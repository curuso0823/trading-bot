"""
notify/line_bot.py
LINE 推播通知（LINE Messaging API push）。
註：LINE Notify 已於 2025/3 停止服務，改用 Messaging API：
    POST https://api.line.me/v2/bot/message/push
    header  Authorization: Bearer {channel access token}
    body    {"to": user_id, "messages": [{"type":"text","text":...}]}
需 .env：LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID
方法名與 TelegramNotifier 對齊（純文字，無 HTML）。
"""
import os
import traceback
from datetime import date
import requests
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


class LineNotifier:
    PUSH_URL = "https://api.line.me/v2/bot/message/push"

    def __init__(self):
        self.token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
        self.user_id = os.getenv("LINE_USER_ID")
        self._enabled = bool(self.token and self.user_id)
        if not self._enabled:
            logger.warning("LINE 未設定（LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID），通知停用")

    def _send(self, text: str) -> bool:
        if not self._enabled:
            logger.info(f"[LINE 停用] {text[:80]}...")
            return False
        try:
            resp = requests.post(
                self.PUSH_URL,
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json"},
                json={"to": self.user_id,
                      "messages": [{"type": "text", "text": text[:4900]}]},
                timeout=10,
            )
            if resp.status_code == 200:
                return True
            logger.error(f"LINE 推播失敗 {resp.status_code}：{resp.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"LINE 推播例外：{e}")
            return False

    def send_entry_signal(self, stock_id, stock_name, price, quantity, chip_score, reason):
        self._send(f"📈 進場訊號\n股票：{stock_id} {stock_name}\n"
                   f"買進 {quantity} 股 @${price:.2f}\n籌碼分：{chip_score:.1f}\n原因：{reason}")

    def send_exit_signal(self, stock_id, stock_name, entry_price, exit_price,
                         quantity, reason, pnl_pct):
        emoji = "✅" if pnl_pct >= 0 else "🔴"
        self._send(f"{emoji} 出場\n{stock_id} {stock_name}\n原因：{reason}\n"
                   f"進場 ${entry_price:.2f} → 出場 ${exit_price:.2f}\n"
                   f"損益：{pnl_pct:+.1f}%（{quantity} 股）")

    def send_stop_loss_alert(self, stock_id, price, pnl_pct):
        self._send(f"🚨 停損觸發\n{stock_id} 現價 ${price:.2f}　損益 {pnl_pct*100:+.1f}%\n執行出場中...")

    def send_halt_alert(self, reason):
        self._send(f"🔴 風控熔斷\n原因：{reason}\n系統已暫停，請人工審核後 resume()")

    def send_daily_summary(self, positions, daily_pnl, total_capital, candidates_count):
        pnl_pct = daily_pnl / total_capital * 100 if total_capital else 0
        lines = "".join(
            f"  {'↑' if p['pnl_pct'] >= 0 else '↓'} {p['stock_id']} "
            f"{p['pnl_pct']:+.1f}% ({p['hold_days']}日)\n" for p in positions
        ) or "  （無持倉）"
        self._send(f"📊 每日摘要 {date.today().isoformat()}\n"
                   f"今日損益：{pnl_pct:+.1f}%（{daily_pnl:+.0f} 元）\n"
                   f"候選：{candidates_count} 檔\n持倉：\n{lines}")

    def send_error(self, error, context=""):
        tb = traceback.format_exc()[-400:]
        self._send(f"⚠️ 系統錯誤\n位置：{context}\n{str(error)[:200]}\n{tb}")

    def send_text(self, text: str) -> bool:
        return self._send(text)

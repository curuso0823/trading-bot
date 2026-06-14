"""
notify/discord_bot.py
Discord webhook 備援推播（無限免費、免 bot）。
需 .env：DISCORD_WEBHOOK_URL（Discord 伺服器→頻道→整合→Webhook→複製 URL）
只需 send_text(text)->bool 原語（NotifyManager 負責格式化與路由）。
"""
import os
import requests
from loguru import logger
from dotenv import load_dotenv

load_dotenv()


class DiscordNotifier:
    def __init__(self):
        self.url = os.getenv("DISCORD_WEBHOOK_URL")
        self._enabled = bool(self.url)
        if not self._enabled:
            logger.warning("Discord webhook 未設定（DISCORD_WEBHOOK_URL），備援停用")

    def send_text(self, text: str) -> bool:
        if not self._enabled:
            return False
        try:
            r = requests.post(self.url, json={"content": text[:1900]}, timeout=10)
            if r.status_code in (200, 204):
                return True
            logger.error(f"Discord 推播失敗 {r.status_code}：{r.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"Discord 推播例外：{e}")
            return False

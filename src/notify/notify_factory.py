"""
notify/notify_factory.py
依 settings.notify.provider 回傳通知器：line（預設）/ telegram。
上層（main.py）只透過此工廠取得 notifier，不直接 new。
兩者方法名一致（send_entry_signal / send_exit_signal / send_stop_loss_alert /
send_halt_alert / send_daily_summary / send_error / send_text）。
"""
from loguru import logger
from src.utils.helpers import load_settings


def _build_channel(name: str):
    name = str(name).lower()
    if name == "telegram":
        from src.notify.telegram_bot import TelegramNotifier
        return TelegramNotifier()
    if name == "discord":
        from src.notify.discord_bot import DiscordNotifier
        return DiscordNotifier()
    if name == "none":
        class _Null:
            def send_text(self, text):
                return False
        return _Null()
    from src.notify.line_bot import LineNotifier
    return LineNotifier()


def make_notifier():
    """回傳 NotifyManager（主推播 + 備援 + 每日上限節流 + 批次）。"""
    from src.notify.notify_manager import NotifyManager
    cfg = load_settings().get("notify", {})
    primary = _build_channel(cfg.get("provider", "line"))
    backup = _build_channel(cfg.get("backup", "discord"))
    logger.info(f"通知器：主={cfg.get('provider','line')} 備援={cfg.get('backup','discord')} "
                f"每日上限={cfg.get('daily_cap', 8)}")
    return NotifyManager(primary, backup, daily_cap=cfg.get("daily_cap", 8))

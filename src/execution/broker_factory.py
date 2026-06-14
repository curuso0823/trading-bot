"""
execution/broker_factory.py
依 settings.broker.mode 回傳券商實例：paper（本地模擬撮合）或 shioaji（永豐實盤）。
上層（main.py）只透過此工廠取得 broker，不直接 new，方便 Shioaji 開戶前先跑模擬盤。
兩種實作的公開介面一致（connect/get_balance/get_positions/place_order/cancel_*）。
"""
from loguru import logger
from src.utils.helpers import load_settings


def make_broker():
    cfg = load_settings().get("broker", {"mode": "paper"})
    mode = str(cfg.get("mode", "paper")).lower()

    if mode == "shioaji":
        from src.execution.broker_client import BrokerClient
        logger.info("券商模式：shioaji（實盤/模擬依 .env SHIOAJI_SIMULATION）")
        return BrokerClient()

    from src.execution.paper_broker import PaperBroker
    logger.info("券商模式：paper（本地模擬撮合）")
    return PaperBroker(initial_cash=cfg.get("paper_initial_cash", 300_000))

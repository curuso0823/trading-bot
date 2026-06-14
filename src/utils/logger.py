"""
utils/logger.py
結構化日誌系統，基於 loguru
"""
import sys
from pathlib import Path
from loguru import logger
import yaml


def setup_logger(config_path: str = "config/settings.yaml") -> None:
    """初始化全域 logger，從 settings.yaml 讀取設定"""
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)["logging"]

    log_dir = Path(cfg["log_path"])
    log_dir.mkdir(exist_ok=True)

    # 移除預設 handler
    logger.remove()

    # Console handler（開發期友善輸出）。
    # pythonw.exe（背景無視窗）時 sys.stdout 為 None，跳過以免 setup_logger 崩潰。
    if sys.stdout is not None:
        logger.add(
            sys.stdout,
            level=cfg["level"],
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> | {message}",
            colorize=True,
        )

    # 交易操作日誌（每日輪轉，結構化格式方便事後分析）
    logger.add(
        log_dir / "trading_{time:YYYY-MM-DD}.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
        rotation=cfg["rotation"],
        retention=cfg["retention"],
        encoding="utf-8",
    )

    # 錯誤日誌（獨立檔案，方便 debug）
    logger.add(
        log_dir / "error_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}\n{exception}",
        rotation="1 week",
        retention="60 days",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
    )


def log_trade(action: str, stock_id: str, price: float, quantity: int,
              reason: str, score: float = None, **kwargs) -> None:
    """
    標準化下單日誌格式
    方便事後用 pandas 解析分析
    """
    extra = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    score_str = f"score={score:.1f}" if score is not None else ""
    logger.info(
        f"TRADE | action={action} | stock={stock_id} | price={price:.2f} "
        f"| qty={quantity} | {score_str} | reason={reason}"
        + (f" | {extra}" if extra else "")
    )

"""
strategy_engines/active_engine.py
ActiveEngine：現行 active 策略的薄包裝。

只是把既有的 ScoreEngine 用引擎介面包起來，方便 main.py 以統一的 mode 旗標路由。
**不改變任何行為**：run() 直接轉呼 ScoreEngine.run()，回傳同一份候選 DataFrame；
save_candidates / last_regime 也原樣透傳。main.py 的 active 分支仍直接用全域 score_engine，
這個包裝是為了讓「引擎層」概念完整、並讓未來想統一入口時有個落點。
"""
from __future__ import annotations
import pandas as pd
from src.strategy_engines.base import StrategyEngine
from src.signals.score_engine import ScoreEngine


class ActiveEngine(StrategyEngine):
    mode = "active"

    def __init__(self, score_engine: ScoreEngine | None = None):
        # 允許注入既有單例（main.py 已建 score_engine）→ 不重複建立 fetcher 等資源
        self.score_engine = score_engine if score_engine is not None else ScoreEngine()

    def run(self, stock_ids: list[str] | None = None) -> pd.DataFrame:
        """產出今日候選清單（行為與現行 ScoreEngine.run 完全一致）。"""
        return self.score_engine.run(stock_ids)

    def save_candidates(self, df: pd.DataFrame, *args, **kwargs) -> str:
        return self.score_engine.save_candidates(df, *args, **kwargs)

    @property
    def last_regime(self) -> str:
        return getattr(self.score_engine, "last_regime", "")

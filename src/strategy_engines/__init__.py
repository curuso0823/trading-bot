"""
strategy_engines
================
可切換的策略引擎層，讓 main.py 依 settings.yaml 的 strategy.mode 路由：

  - active    → ActiveEngine：薄包裝現行 ScoreEngine（行為與現況完全一致）。
  - benchmark → BenchmarkEngine：0050「波動目標 + 部分現金」對照組
                （給定可用資金與當前持倉 → 算出目標 0050 部位/再平衡動作）。

設計原則：active 路徑零行為改變；benchmark 邏輯完全自包含（自己的曝險/再平衡），
不沾染 active 的籌碼候選與 ATR 移動停損。
"""
from src.strategy_engines.base import StrategyEngine, RebalanceAction
from src.strategy_engines.active_engine import ActiveEngine
from src.strategy_engines.benchmark_engine import BenchmarkEngine, make_engine

__all__ = [
    "StrategyEngine",
    "RebalanceAction",
    "ActiveEngine",
    "BenchmarkEngine",
    "make_engine",
]

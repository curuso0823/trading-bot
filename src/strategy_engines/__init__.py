"""
strategy_engines
================
策略引擎層（live = benchmark 被動策略：0050 波動目標 + MA200 overlay）。

  - benchmark → BenchmarkEngine：給定可用資金與當前持倉 → 算出目標 0050 部位/再平衡動作。

註：2026-06-17 PIT 乾淨重建裁決誠實池無前瞻 alpha → live 改被動為主；舊 active 籌碼策略
執行路徑（ScoreEngine/ActiveEngine/tech+chip 選股/ATR 移動停損）已移除。make_engine 僅回
BenchmarkEngine；mode 非 benchmark 時 fail-safe 仍回 benchmark。
"""
from src.strategy_engines.base import StrategyEngine, RebalanceAction
from src.strategy_engines.benchmark_engine import BenchmarkEngine, make_engine

__all__ = [
    "StrategyEngine",
    "RebalanceAction",
    "BenchmarkEngine",
    "make_engine",
]

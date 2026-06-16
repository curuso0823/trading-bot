"""
strategy_engines/base.py
策略引擎介面/基底 + 再平衡動作資料類別。

兩種引擎共用一個薄介面 `StrategyEngine`：
  - mode 屬性（"active" / "benchmark"）供 main.py 路由與日誌用。

ActiveEngine 走 active 流程（候選清單 → top-N 並倉 → ATR 移動停損），維持現況；
BenchmarkEngine 走自己的單標的「波動目標」再平衡，產出 RebalanceAction（買/賣/不動）。
刻意不把兩者硬塞進同一個方法簽名 —— active 是「多檔候選 + 風控下單」、
benchmark 是「單標的目標曝險再平衡」，硬統一只會引入抽象稅。main.py 用 mode 分支即可。
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RebalanceAction:
    """benchmark 再平衡的單一動作（pure 計算結果，不碰 broker）。

    side:        "buy" / "sell" / "hold"
    stock_id:    標的（benchmark = 0050）
    delta_qty:   需成交股數（>0；side=hold 時為 0）。單位 = 零股「股」（lot_size=1）。
    target_qty:  再平衡後目標持股（股）
    current_qty: 再平衡前現有持股（股）
    target_exposure: 目標曝險比例（0~exposure_cap）
    reason:      人類可讀說明（日誌/通知用）
    """
    side: str
    stock_id: str
    delta_qty: int
    target_qty: int
    current_qty: int
    target_exposure: float
    reason: str = ""

    @property
    def is_noop(self) -> bool:
        return self.side == "hold" or self.delta_qty <= 0


class StrategyEngine:
    """策略引擎基底。子類別至少要有 `mode` 字串屬性。"""

    mode: str = "base"

    def __repr__(self) -> str:  # pragma: no cover - 日誌便利
        return f"<{type(self).__name__} mode={self.mode}>"

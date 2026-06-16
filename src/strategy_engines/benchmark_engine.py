"""
strategy_engines/benchmark_engine.py
BenchmarkEngine：0050「波動目標 + 部分現金」對照組（最低複雜度，逼近/超越現行策略的風險調整報酬）。

規格：
  - 標的：只用 0050。
  - 波動目標配重：exposure_t = clip(target_daily_vol / realized_vol_20d(0050), 0, exposure_cap)，
    不加槓桿（cap=1.0），其餘擺現金。
  - （可選）regime overlay：0050 收盤 < MA(200 或 60) 時，曝險砍半或歸零（可開關）。
  - 再平衡：每月第一個交易日，或當前曝險偏離目標 > rebalance_band(5pp) 才調倉（降低換手）。
  - 成本：台股買賣手續費 0.1425% + 賣出稅 0.3%（沿用 calc_trade_cost / strategy.yaml cost）。

設計：
  - 純計算邏輯（exposure / target qty / rebalance 決策）與「資料來源」「broker」解耦，
    才能在回測（餵歷史 close 向量）與 live（餵 PositionManager + Fugle 報價）兩邊重用同一份口徑。
  - target_exposure(close_series, today) 與 decide_rebalance(...) 不碰任何 I/O，便於單元測試（合成資料）。
  - 不依賴 vectorbt（純 pandas/numpy），風格對齊 src/backtest/capped_sim.py。
"""
from __future__ import annotations
from datetime import date

import numpy as np
import pandas as pd

from src.strategy_engines.base import StrategyEngine, RebalanceAction
from src.utils.helpers import load_settings, lot_size


def _benchmark_cfg() -> dict:
    """讀 settings.yaml 的 strategy.benchmark 區塊（缺值給安全預設）。"""
    strat = load_settings().get("strategy", {}) or {}
    bm = dict(strat.get("benchmark", {}) or {})
    bm.setdefault("symbol", "0050")
    bm.setdefault("target_daily_vol", 0.011)
    bm.setdefault("vol_lookback", 20)
    bm.setdefault("exposure_cap", 1.0)
    bm.setdefault("rebalance_band", 0.05)
    bm.setdefault("monthly_rebalance", True)
    bm.setdefault("regime_overlay", False)
    bm.setdefault("regime_ma", 200)
    bm.setdefault("regime_action", "half")
    return bm


def realized_vol(close: pd.Series, lookback: int) -> pd.Series:
    """日報酬滾動標準差（已實現日波動）。與 capped_sim 的 close.pct_change().rolling(n).std() 同口徑。"""
    return close.astype(float).pct_change().rolling(lookback).std()


def vol_target_exposure(close: pd.Series, *, target_daily_vol: float, lookback: int,
                        exposure_cap: float = 1.0,
                        regime_overlay: bool = False, regime_ma: int = 200,
                        regime_action: str = "half") -> pd.Series:
    """逐日目標曝險序列（0~cap）。pure：給一條 close 算整段 exposure，回測/單元測試共用。

    exposure = clip(target_daily_vol / realized_vol_20d, 0, cap)
    regime overlay（可選）：close < MA(regime_ma) 當日，exposure ×0.5（half）或 ×0（zero）。
    暖身不足（vol 為 NaN）→ 該日 exposure = 0（不下注，保守）。
    """
    close = close.astype(float)
    rv = realized_vol(close, lookback)
    with np.errstate(divide="ignore", invalid="ignore"):
        exp = (float(target_daily_vol) / rv).clip(lower=0.0, upper=float(exposure_cap))
    exp = exp.where(rv > 0, 0.0)        # vol=0/NaN → 0 曝險
    exp = exp.fillna(0.0)

    if regime_overlay:
        ma = close.rolling(int(regime_ma)).mean()
        below = close < ma                       # MA 暖身不足 → NaN → 視為「未跌破」(不砍)
        below = below.fillna(False)
        mult = 0.0 if str(regime_action).lower() == "zero" else 0.5
        exp = exp.where(~below, exp * mult)
    return exp


def is_month_first_trading_day(dates: pd.DatetimeIndex) -> pd.Series:
    """標記每個交易日是否為「當月第一個交易日」（用實際交易日索引，非日曆 1 號）。"""
    s = pd.Series(dates, index=dates)
    ym = s.dt.to_period("M")
    return ym.ne(ym.shift(1)).fillna(True)   # 與前一交易日不同月 → 該月首個交易日


class BenchmarkEngine(StrategyEngine):
    """0050 波動目標對照組引擎。

    live 用法（main.py benchmark 分支）：
      eng = BenchmarkEngine()
      px  = fetch 0050 近 ~ (max(lookback, regime_ma)+暖身) 日線 close（用快取，不打 API）
      exp = eng.current_target_exposure(px["close"])           # 今日目標曝險
      act = eng.decide_rebalance(equity, cash, cur_qty, price, exp, force_monthly=今天是當月首日)
      若 act.side != hold → 透過 OrderManager 下單、PositionManager 記帳。

    回測用法見 notebooks/benchmark_backtest.py（餵整段 close 向量化計算）。
    """
    mode = "benchmark"

    def __init__(self, cfg: dict | None = None):
        c = cfg if cfg is not None else _benchmark_cfg()
        self.symbol: str = str(c.get("symbol", "0050"))
        self.target_daily_vol: float = float(c.get("target_daily_vol", 0.011))
        self.lookback: int = int(c.get("vol_lookback", 20))
        self.exposure_cap: float = float(c.get("exposure_cap", 1.0))
        self.rebalance_band: float = float(c.get("rebalance_band", 0.05))
        self.monthly_rebalance: bool = bool(c.get("monthly_rebalance", True))
        self.regime_overlay: bool = bool(c.get("regime_overlay", False))
        self.regime_ma: int = int(c.get("regime_ma", 200))
        self.regime_action: str = str(c.get("regime_action", "half"))

    # ---------- pure 曝險計算 ----------

    def exposure_series(self, close: pd.Series) -> pd.Series:
        """整段逐日目標曝險（回測/批次用）。"""
        return vol_target_exposure(
            close, target_daily_vol=self.target_daily_vol, lookback=self.lookback,
            exposure_cap=self.exposure_cap, regime_overlay=self.regime_overlay,
            regime_ma=self.regime_ma, regime_action=self.regime_action)

    def current_target_exposure(self, close: pd.Series) -> float:
        """今日（序列最後一筆）目標曝險。live 盤前算。"""
        s = self.exposure_series(close)
        if s.empty:
            return 0.0
        return float(s.iloc[-1])

    # ---------- 再平衡決策（pure，不碰 broker）----------

    def decide_rebalance(self, equity: float, cash: float, current_qty: int,
                         price: float, target_exposure: float,
                         force_monthly: bool = False) -> RebalanceAction:
        """給定權益/現金/現有持股/現價/目標曝險 → 算出再平衡動作。

        equity:  總權益（cash + 持倉市值），目標市值 = equity × target_exposure。
        current_qty / price 以「股」「每股價」計（零股 lot_size=1）。
        只有「偏離目標曝險 > rebalance_band」或 force_monthly=True 時才調倉（降低換手）。
        買進受現金約束（不融資）：實際買量 = min(目標增量, 現金可負擔量含手續費)。
        """
        lot = lot_size()
        price = float(price)
        if price <= 0 or equity <= 0:
            return RebalanceAction("hold", self.symbol, 0, current_qty, current_qty,
                                   target_exposure, "無效價格/權益")

        cur_value = current_qty * price * lot
        cur_exposure = cur_value / equity if equity > 0 else 0.0
        drift = abs(cur_exposure - target_exposure)

        if not force_monthly and drift <= self.rebalance_band:
            return RebalanceAction("hold", self.symbol, 0, current_qty, current_qty,
                                   target_exposure,
                                   f"曝險偏離 {drift*100:.1f}pp ≤ {self.rebalance_band*100:.0f}pp，不調倉")

        target_value = equity * target_exposure
        target_qty = int(target_value / (price * lot))   # 向下取整到可成交股數
        delta = target_qty - current_qty

        if delta == 0:
            return RebalanceAction("hold", self.symbol, 0, current_qty, current_qty,
                                   target_exposure, "目標股數=現有股數")

        if delta > 0:   # 加碼，受現金約束（含買進手續費；最低手續費以零股 1 元計）
            from src.utils.helpers import load_config
            cc = load_config()["cost"]
            buy_rate = float(cc["buy_fee_rate"])
            min_fee = int(cc.get("min_fee_odd", 1)) if lot == 1 else int(cc["min_fee"])
            buyable = delta
            # 逐步縮量直到「成交額 + 手續費 ≤ 可用現金」（與 capped_sim 同口徑）
            while buyable >= 1:
                amt = price * buyable * lot
                fee = max(round(amt * buy_rate), min_fee)
                if amt + fee <= cash:
                    break
                buyable -= 1
            if buyable < 1:
                return RebalanceAction("hold", self.symbol, 0, current_qty, current_qty,
                                       target_exposure, "現金不足以加碼")
            reason = (f"加碼 {buyable} 股 → 目標曝險 {target_exposure*100:.0f}%"
                      f"（現曝險 {cur_exposure*100:.0f}%，偏離 {drift*100:.1f}pp"
                      f"{'，月度再平衡' if force_monthly else ''}）")
            return RebalanceAction("buy", self.symbol, buyable, current_qty + buyable,
                                   current_qty, target_exposure, reason)

        # delta < 0：減碼（賣零股，T+1 限制由呼叫端把關）
        sell_qty = -delta
        reason = (f"減碼 {sell_qty} 股 → 目標曝險 {target_exposure*100:.0f}%"
                  f"（現曝險 {cur_exposure*100:.0f}%，偏離 {drift*100:.1f}pp"
                  f"{'，月度再平衡' if force_monthly else ''}）")
        return RebalanceAction("sell", self.symbol, sell_qty, target_qty,
                               current_qty, target_exposure, reason)


def make_engine(score_engine=None):
    """依 settings.yaml 的 strategy.mode 回傳對應引擎（active 預設）。

    mode 缺失/未知 → 一律回 ActiveEngine（fail-safe：絕不誤切到 benchmark 而動到 live 路徑）。
    score_engine：active 時可注入既有單例，避免重複建立資源。
    """
    from loguru import logger
    from src.strategy_engines.active_engine import ActiveEngine

    mode = str((load_settings().get("strategy", {}) or {}).get("mode", "active")).lower()
    if mode == "benchmark":
        logger.info("策略引擎：benchmark（0050 波動目標對照組）")
        return BenchmarkEngine()
    if mode != "active":
        logger.warning(f"strategy.mode={mode!r} 未知 → fail-safe 回退 active（不動 live 路徑）")
    return ActiveEngine(score_engine)

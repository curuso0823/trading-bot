"""
utils/helpers.py
共用工具函數：設定載入、台股交易成本計算、日期工具
"""
import yaml
from datetime import date, timedelta
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=None)
def load_config(path: str = "config/strategy.yaml") -> dict:
    """載入 YAML 設定，lru_cache 確保只讀一次"""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=None)
def load_settings(path: str = "config/settings.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def lot_size() -> int:
    """每單位計價股數：整股=1000、零股=1（由 config trading.lot_size 決定）"""
    return load_config().get("trading", {}).get("lot_size", 1000)


def order_lot() -> str:
    """Shioaji 委託張/股別：Common/IntradayOdd/Odd/Fixing（config trading.order_lot）。
    預設 IntradayOdd（盤中零股）。PaperBroker 忽略，僅 live Shioaji 用。"""
    return load_config().get("trading", {}).get("order_lot", "IntradayOdd")


def calc_trade_cost(price: float, quantity: int, action: str) -> dict:
    """
    計算台股實際交易成本（支援整股/盤中零股）。
    quantity 單位依 trading.lot_size：整股為「張」、零股為「股」。
    手續費含退傭折讓；零股用較低的最低手續費。
    action: 'buy' or 'sell'
    """
    cfg = load_config()["cost"]
    lot = lot_size()
    amount = price * quantity * lot

    rate = cfg["buy_fee_rate"]
    rebate = cfg.get("fee_rebate", 0.0)
    min_fee = cfg.get("min_fee_odd", 1) if lot == 1 else cfg["min_fee"]
    fee = max(round(amount * rate * (1 - rebate)), min_fee)
    tax = round(amount * cfg["sell_tax_rate"]) if action == "sell" else 0

    return {
        "fee": fee,
        "tax": tax,
        "total_cost": fee + tax,
        "net_amount": amount - fee - tax if action == "sell" else amount + fee,
    }


def atr_trailing_pct(price_df) -> float | None:
    """
    A1 live：從近期日線算 ATR% → 移動停損寬度 = clip(atr_mult × ATR%, min, max)，回傳最新一筆。
    與回測 backtester._trailing_stop 同口徑（rolling 均 TR / close）。
    trailing_mode != atr 或資料不足 → 回傳 None（呼叫端 fallback 固定 trailing_stop_pct）。
    price_df 需含 high/low/close 欄（FinMindFetcher.get_daily_price 輸出）。
    """
    import pandas as pd
    ex = load_config().get("exit", {})
    if str(ex.get("trailing_mode", "fixed")).lower() != "atr":
        return None
    n = int(ex.get("atr_period", 14))
    if price_df is None or len(price_df) < n + 1 or not {"high", "low", "close"}.issubset(price_df.columns):
        return None
    k = float(ex.get("atr_mult", 4.5))
    lo = float(ex.get("atr_trail_min", 0.08))
    hi = float(ex.get("atr_trail_max", 0.10))
    c = price_df["close"].astype(float)
    h = price_df["high"].astype(float)
    low = price_df["low"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([h - low, (h - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    atr_pct = (tr.rolling(n).mean() / c).iloc[-1]
    if pd.isna(atr_pct):
        return None
    return float(min(max(k * atr_pct, lo), hi))


def vol_position_pct(price_df) -> float:
    """
    方式A live 部位配重：個股反波動 size_pct = clip(base × target_vol/σ, min, max)。
    與回測 backtester._position_size(vol_target) 同口徑（market_vol_scaling 已關閉故不含曝險縮放）。
    sizing.method != vol_target 或資料不足 → 回 base(entry.position_size_pct)。
    price_df 需含 close 欄（FinMindFetcher.get_daily_price 輸出）。
    """
    import pandas as pd
    cfg = load_config()
    base = float(cfg.get("entry", {}).get("position_size_pct", 0.30))
    s = cfg.get("sizing", {})
    if str(s.get("method", "flat")).lower() != "vol_target":
        return base
    lb = int(s.get("vol_lookback", 20))
    if price_df is None or "close" not in price_df.columns or len(price_df) < lb + 2:
        return base
    tgt = float(s.get("target_vol_daily", 0.02))
    lo = float(s.get("min_position_pct", 0.10))
    hi = float(s.get("max_position_pct", base))
    vol = price_df["close"].astype(float).pct_change().rolling(lb).std().iloc[-1]
    if pd.isna(vol) or vol <= 0:
        return base
    return float(min(max(base * tgt / vol, lo), hi))


@lru_cache(maxsize=8)
def _tw_holidays(year: int):
    """快取某年度台灣國定假日集合（holidays 套件）；不可用時回傳空集合。"""
    try:
        import holidays
        return set(holidays.country_holidays("TW", years=year))
    except Exception:
        return set()


def is_trading_day(target_date: date = None) -> bool:
    """
    判斷是否為台股交易日：排除週末 + 國定假日。
    註：未涵蓋颱風假與補行交易日（罕見，需人工處理）。
    """
    if target_date is None:
        target_date = date.today()
    if target_date.weekday() >= 5:                 # 週末
        return False
    return target_date not in _tw_holidays(target_date.year)


def get_prev_trading_day(n: int = 1) -> date:
    """取得前 n 個交易日日期（簡易版）"""
    d = date.today()
    count = 0
    while count < n:
        d -= timedelta(days=1)
        if is_trading_day(d):
            count += 1
    return d


def count_trading_days(start: date, end: date = None) -> int:
    """start 之後到 end（含）之間的『交易日』數（排除週末/假日）。
    供 live 持有天數用『交易日』與回測 max_hold（vectorbt 以 bar=交易日計）對齊。
    entry 當日 → 0；下一交易日 → 1。"""
    if end is None:
        end = date.today()
    if end <= start:
        return 0
    d = start + timedelta(days=1)
    n = 0
    while d <= end:
        if is_trading_day(d):
            n += 1
        d += timedelta(days=1)
    return n


def exec_slippage() -> float:
    """成交滑價率（依 trading.mode 取 odd/round_lot_slippage）。
    live/paper 下單以此調整成交價（買 +slip、賣 -slip），與回測 _slippage_per_stock 同口徑。"""
    tr = load_config().get("trading", {})
    mode = str(tr.get("mode", "odd_lot")).lower()
    if mode == "round_lot":
        return float(tr.get("round_lot_slippage", 0.001))
    return float(tr.get("odd_lot_slippage", 0.0015))   # odd_lot / hybrid 預設


def tw_stock_list_path() -> Path:
    """上市上櫃股票清單的本地快取路徑"""
    return Path("data/raw/tw_stock_universe.csv")

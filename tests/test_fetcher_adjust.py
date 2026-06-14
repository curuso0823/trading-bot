"""data/fetcher：反向還原（除權息 + 分割偵測）"""
import pandas as pd
from src.data.fetcher import FinMindFetcher


def _df(dates, closes):
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "open": closes, "high": closes, "low": closes,
        "close": list(closes), "adj_close": list(closes),
    })


def test_split_detection_removes_cliff():
    # 第3日 1->4 分割（189 -> 47.25，比值 0.25），除權息資料為空
    df = _df(["2025-06-16", "2025-06-17", "2025-06-18", "2025-06-19"],
             [188.0, 189.0, 47.25, 47.0])
    div = pd.DataFrame(columns=["date", "before_price", "after_price"])
    out = FinMindFetcher._apply_back_adjust(df, div)
    # 最新日不變、分割前被 ×0.25
    assert abs(out["close"].iloc[-1] - 47.0) < 1e-6
    assert abs(out["close"].iloc[0] - 188.0 * 0.25) < 1e-6
    # 還原後無斷崖（單日比值落在 ±漲跌停可能範圍內）
    r = (out["close"] / out["close"].shift(1)).dropna()
    assert r.min() > 0.70 and r.max() < 1.43


def test_dividend_adjust_ratio():
    df = _df(["2025-01-16", "2025-01-17"], [198.0, 195.0])
    div = pd.DataFrame({"date": pd.to_datetime(["2025-01-17"]),
                        "before_price": [198.0], "after_price": [195.0]})
    out = FinMindFetcher._apply_back_adjust(df, div)
    assert abs(out["close"].iloc[0] - 198.0 * (195.0 / 198.0)) < 1e-3
    assert abs(out["close"].iloc[-1] - 195.0) < 1e-6


def test_no_events_keeps_prices():
    df = _df(["2025-03-03", "2025-03-04", "2025-03-05"], [100.0, 101.0, 99.5])
    div = pd.DataFrame(columns=["date", "before_price", "after_price"])
    out = FinMindFetcher._apply_back_adjust(df, div)
    assert list(out["close"]) == [100.0, 101.0, 99.5]

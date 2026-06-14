"""signals/tech_signal：純 pandas 指標（Wilder RSI、欄位）"""
import numpy as np
import pandas as pd
from src.signals.tech_signal import TechSignal


def test_rsi_bounds_and_uptrend():
    s = pd.Series(np.linspace(100, 150, 40))      # 持續上漲
    rsi = TechSignal._rsi(s, 14).dropna()
    assert rsi.between(0, 100).all()
    assert rsi.iloc[-1] > 90                        # 全程上漲 → RSI 高


def test_rsi_downtrend_low():
    s = pd.Series(np.linspace(150, 100, 40))       # 持續下跌
    rsi = TechSignal._rsi(s, 14).dropna()
    assert rsi.iloc[-1] < 10


def test_compute_adds_expected_columns():
    n = 60
    rng = np.linspace(10, 20, n)
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n),
        "open": rng, "high": rng, "low": rng, "close": rng,
        "volume": np.full(n, 1000.0),
    })
    d = TechSignal().compute(df)
    for c in ["ma20", "ma_slope", "vol_ratio", "rsi14", "bb_upper", "bb_lower", "bb_mid", "rvol20"]:
        assert c in d.columns


def test_overextension_filter_deviation():
    """過度延伸濾鏡（乖離）：None=不啟用恆 True；設上限後超過即擋。"""
    ts = TechSignal()
    row = pd.Series({"ma20": 100.0, "close": 125.0, "rvol20": 0.01})  # 離 MA20 +25%
    ts.max_ext_pct = None
    assert ts.is_not_overextended(row)                 # 未啟用 → True
    ts.max_ext_pct = 0.15
    assert not ts.is_not_overextended(row)             # +25% > 15% → 擋
    ts.max_ext_pct = 0.30
    assert ts.is_not_overextended(row)                 # +25% ≤ 30% → 放行


def test_overextension_filter_volatility():
    """過度延伸濾鏡（波動）：20日波動超上限即擋。"""
    ts = TechSignal()
    ts.max_ext_pct = None
    row = pd.Series({"ma20": 100.0, "close": 105.0, "rvol20": 0.05})  # 高波動 5%
    ts.max_vol_pct = None
    assert ts.is_not_overextended(row)
    ts.max_vol_pct = 0.03
    assert not ts.is_not_overextended(row)             # 5% > 3% → 擋
    ts.max_vol_pct = 0.06
    assert ts.is_not_overextended(row)                 # 5% ≤ 6% → 放行

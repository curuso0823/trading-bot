"""strategy_engines/benchmark_engine：0050 波動目標對照組（合成資料，不打 API）。

驗證重點：
  - vol_target_exposure 的 clip(target/realized_vol, 0, cap) 配重與 regime overlay。
  - is_month_first_trading_day 月度標記。
  - BenchmarkEngine.decide_rebalance 的再平衡帶（>5pp 才動）、月度強制、現金約束、買賣方向。
  - make_engine 依 settings.mode 路由且 fail-safe 回 active。
"""
import numpy as np
import pandas as pd
import pytest

from src.strategy_engines.benchmark_engine import (
    BenchmarkEngine, vol_target_exposure, is_month_first_trading_day, make_engine,
    _regime_below,
)


# ────────────────────── 配重（exposure）──────────────────────

def _close(vol_daily, n=120, start="2020-01-01"):
    """造一條『指定日波動』的隨機漫步 close（固定種子可重現）。"""
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0, vol_daily, n)
    close = 100 * np.exp(np.cumsum(rets))
    return pd.Series(close, index=pd.bdate_range(start, periods=n))


def test_exposure_caps_at_one_when_vol_below_target():
    """實現波動 << 目標 → 比值 >1 但被 cap 在 1.0（不加槓桿）。"""
    close = _close(vol_daily=0.003)        # 很低波動
    exp = vol_target_exposure(close, target_daily_vol=0.011, lookback=20, exposure_cap=1.0)
    tail = exp.dropna().iloc[25:]          # 跳過暖身
    assert (tail <= 1.0 + 1e-9).all()
    assert tail.max() == pytest.approx(1.0, abs=1e-9)
    assert (tail >= 0.99).mean() > 0.8     # 低波動 → 幾乎滿倉


def test_exposure_scales_down_in_high_vol():
    """實現波動 >> 目標 → 曝險 < 1（去風險），且 = target/realized 量級。"""
    close = _close(vol_daily=0.03)         # 高波動
    exp = vol_target_exposure(close, target_daily_vol=0.011, lookback=20, exposure_cap=1.0)
    tail = exp.dropna().iloc[25:]
    assert (tail < 1.0).all()
    assert tail.mean() < 0.6               # 約 0.011/0.03 ≈ 0.37 量級


def test_exposure_matches_clip_formula():
    """逐點對齊 clip(target/realized_vol_20, 0, cap)（只比對暖身後、vol 已定義的區段）。"""
    close = _close(vol_daily=0.012)
    rv = close.pct_change().rolling(20).std()
    expect = (0.011 / rv).clip(0.0, 1.0)
    got = vol_target_exposure(close, target_daily_vol=0.011, lookback=20, exposure_cap=1.0)
    mask = rv.notna()                      # 暖身期 engine 回 0、expect 為 NaN → 排除後逐點比
    pd.testing.assert_series_equal(got[mask], expect[mask], check_names=False)


def test_warmup_exposure_is_zero():
    """暖身期（rolling std 為 NaN）→ 曝險 0（保守不下注）。"""
    close = _close(vol_daily=0.01, n=30)
    exp = vol_target_exposure(close, target_daily_vol=0.011, lookback=20)
    assert (exp.iloc[:19] == 0.0).all()    # 前 19 日無足夠樣本 → 0


def test_regime_overlay_half_and_zero():
    """收盤 < MA 當日，half→×0.5、zero→×0。用單調下跌序列確保跌破 MA。"""
    n = 80
    close = pd.Series(np.linspace(100, 60, n), index=pd.bdate_range("2020-01-01", periods=n))
    base = vol_target_exposure(close, target_daily_vol=0.011, lookback=20, exposure_cap=1.0,
                               regime_overlay=False)
    half = vol_target_exposure(close, target_daily_vol=0.011, lookback=20, exposure_cap=1.0,
                               regime_overlay=True, regime_ma=20, regime_action="half")
    zero = vol_target_exposure(close, target_daily_vol=0.011, lookback=20, exposure_cap=1.0,
                               regime_overlay=True, regime_ma=20, regime_action="zero")
    # 下跌段末端必在 MA20 之下
    below_idx = close.index[-1]
    assert half.loc[below_idx] == pytest.approx(base.loc[below_idx] * 0.5, rel=1e-9)
    assert zero.loc[below_idx] == pytest.approx(0.0, abs=1e-12)


def test_regime_overlay_numeric_mult():
    """regime_action 數值（如 0.85，live R6）→ 跌破 MA 當日 exposure ×0.85；字串數值亦接受。"""
    n = 80
    close = pd.Series(np.linspace(100, 60, n), index=pd.bdate_range("2020-01-01", periods=n))
    base = vol_target_exposure(close, target_daily_vol=0.011, lookback=20, exposure_cap=1.0,
                               regime_overlay=False)
    below_idx = close.index[-1]
    for ra in (0.85, "0.85"):
        keep = vol_target_exposure(close, target_daily_vol=0.011, lookback=20, exposure_cap=1.0,
                                   regime_overlay=True, regime_ma=20, regime_action=ra)
        assert keep.loc[below_idx] == pytest.approx(base.loc[below_idx] * 0.85, rel=1e-9)


# ────────────────────── whipsaw 修正：N 日確認(E1) + 緩衝帶(E2) ──────────────────────

def test_regime_confirm_band_defaults_neutral():
    """confirm_days=1 + band_pct=0.0（預設）→ 與舊每日 MA 規則逐位相同（行為中性 additive；保 98 綠）。"""
    n = 120
    rng = np.random.default_rng(7)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.015, n))),
                      index=pd.bdate_range("2020-01-01", periods=n))
    old = vol_target_exposure(close, target_daily_vol=1.0, lookback=20, exposure_cap=1.0,
                              regime_overlay=True, regime_ma=20, regime_action=0.85)
    new = vol_target_exposure(close, target_daily_vol=1.0, lookback=20, exposure_cap=1.0,
                              regime_overlay=True, regime_ma=20, regime_action=0.85,
                              regime_confirm_days=1, regime_band_pct=0.0)
    pd.testing.assert_series_equal(old, new, check_names=False)


def test_regime_below_defaults_equal_old_rule():
    """_regime_below(confirm=1,band=0) 逐位 == 舊 (close < ma).fillna(False)。"""
    idx = pd.bdate_range("2020-01-01", periods=40)
    rng = np.random.default_rng(11)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1.0, 40)), index=idx)
    ma = close.rolling(10).mean()
    got = _regime_below(close, ma, confirm_days=1, band_pct=0.0)
    expect = (close < ma).fillna(False)
    pd.testing.assert_series_equal(got, expect, check_names=False)


def test_regime_confirm_days_filters_short_breach():
    """E1：1-2 日假跌破不觸發 reduced（confirm=3）；同序列 confirm=1 會觸發那兩日。"""
    idx = pd.bdate_range("2020-01-01", periods=10)
    close = pd.Series([100, 100, 100, 100, 95, 96, 100, 100, 100, 100], index=idx, dtype=float)
    ma = pd.Series(100.0, index=idx)
    b1 = _regime_below(close, ma, confirm_days=1, band_pct=0.0)
    b3 = _regime_below(close, ma, confirm_days=3, band_pct=0.0)
    assert b1.iloc[4] and b1.iloc[5]      # 每日規則：跌破當日即 reduced
    assert not b3.any()                   # 僅 2 連跌破 < 3 → 從不轉態（whipsaw 被濾掉）


def test_regime_band_deadzone_filters_shallow_breach():
    """E2：close 僅微跌破 MA（在 1% 帶內）不觸發；無帶則觸發。"""
    idx = pd.bdate_range("2020-01-01", periods=6)
    ma = pd.Series(100.0, index=idx)
    close = pd.Series([100, 100, 99.5, 99.5, 99.5, 99.5], index=idx, dtype=float)  # 跌 0.5% < 1% 帶
    b0 = _regime_below(close, ma, confirm_days=1, band_pct=0.0)
    b1pct = _regime_below(close, ma, confirm_days=1, band_pct=0.01)
    assert b0.iloc[2]                     # 無帶：99.5<100 → reduced
    assert not b1pct.any()                # 1% 帶：99.5 > 100×0.99=99 → 死區 → 不觸發


def test_regime_combined_hysteresis_reentry():
    """combined N=3+1%：超下帶連 3 日→reduced；死區維持；站回上帶連 3 日才 full。"""
    idx = pd.bdate_range("2020-01-01", periods=14)
    ma = pd.Series(100.0, index=idx)
    close = pd.Series([100, 98, 98, 98, 100.5, 100.5, 101.5, 101.5, 101.5, 100, 100, 100, 100, 100],
                      index=idx, dtype=float)
    b = _regime_below(close, ma, confirm_days=3, band_pct=0.01)   # 下帶99 上帶101
    assert not b.iloc[2]                  # 98 只 2 連 < 3 → 尚未 reduced
    assert b.iloc[3]                      # 第 3 連跌破 → reduced
    assert b.iloc[4] and b.iloc[5]        # 100.5 在死區(99~101) → 維持 reduced
    assert b.iloc[7]                      # 101.5 僅 2 連 > 上帶 → 仍 reduced
    assert not b.iloc[8]                  # 第 3 連站回上帶 → full


def test_benchmark_engine_reads_confirm_band_config():
    """BenchmarkEngine 從 config 讀 regime_confirm_days / regime_band_pct 並套進 exposure_series。"""
    cfg = {"symbol": "0050", "target_daily_vol": 1.0, "vol_lookback": 20, "exposure_cap": 1.0,
           "rebalance_band": 0.05, "monthly_rebalance": True, "regime_overlay": True,
           "regime_ma": 20, "regime_action": 0.85, "regime_confirm_days": 3, "regime_band_pct": 0.01}
    eng = BenchmarkEngine(cfg)
    assert eng.regime_confirm_days == 3
    assert eng.regime_band_pct == pytest.approx(0.01)
    idx = pd.bdate_range("2020-01-01", periods=60)
    rng = np.random.default_rng(3)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 60))), index=idx)
    got = eng.exposure_series(close)
    expect = vol_target_exposure(close, target_daily_vol=1.0, lookback=20, exposure_cap=1.0,
                                 regime_overlay=True, regime_ma=20, regime_action=0.85,
                                 regime_confirm_days=3, regime_band_pct=0.01)
    pd.testing.assert_series_equal(got, expect, check_names=False)


def test_benchmark_engine_default_config_is_neutral():
    """未給 confirm/band 的 config → 引擎預設 confirm=1/band=0（舊行為，行為中性）。"""
    eng = BenchmarkEngine({"symbol": "0050", "regime_overlay": True, "regime_ma": 200,
                           "regime_action": 0.85})
    assert eng.regime_confirm_days == 1
    assert eng.regime_band_pct == 0.0


# ────────────────────── 月度標記 ──────────────────────

def test_month_first_trading_day():
    dates = pd.DatetimeIndex(["2020-01-02", "2020-01-03", "2020-02-03", "2020-02-04", "2020-03-02"])
    flags = is_month_first_trading_day(dates)
    assert list(flags) == [True, False, True, False, True]


# ────────────────────── 再平衡決策 ──────────────────────

def _eng():
    return BenchmarkEngine({"symbol": "0050", "target_daily_vol": 0.011, "vol_lookback": 20,
                            "exposure_cap": 1.0, "rebalance_band": 0.05, "monthly_rebalance": True,
                            "regime_overlay": False})


def test_rebalance_buy_from_flat():
    """空手 + 目標曝險 0.8 → 買進，target_qty ≈ equity*0.8/price。"""
    eng = _eng()
    act = eng.decide_rebalance(equity=100_000, cash=100_000, current_qty=0,
                               price=50.0, target_exposure=0.8)
    assert act.side == "buy"
    # 100k*0.8/50 = 1600 股（受手續費微調，允許 -1）
    assert 1598 <= act.delta_qty <= 1600
    assert act.current_qty == 0


def test_rebalance_hold_within_band():
    """現曝險 0.78、目標 0.80 → 偏離 2pp ≤ 5pp → 不調倉（非月度）。"""
    eng = _eng()
    # 1560 股 @50 = 78,000 → 曝險 0.78
    act = eng.decide_rebalance(equity=100_000, cash=22_000, current_qty=1560,
                               price=50.0, target_exposure=0.80, force_monthly=False)
    assert act.side == "hold"
    assert act.delta_qty == 0


def test_rebalance_triggers_outside_band():
    """現曝險 0.50、目標 0.80 → 偏離 30pp > 5pp → 加碼。"""
    eng = _eng()
    act = eng.decide_rebalance(equity=100_000, cash=50_000, current_qty=1000,
                               price=50.0, target_exposure=0.80, force_monthly=False)
    assert act.side == "buy"
    assert act.delta_qty > 0
    assert act.target_qty > act.current_qty


def test_rebalance_monthly_forces_even_within_band():
    """偏離僅 2pp（帶內）但 force_monthly=True → 仍調倉。"""
    eng = _eng()
    act = eng.decide_rebalance(equity=100_000, cash=22_000, current_qty=1560,
                               price=50.0, target_exposure=0.80, force_monthly=True)
    assert act.side in ("buy", "sell")     # 月度強制 → 不為 hold（除非剛好同股數）


def test_rebalance_sell_when_overexposed():
    """現曝險 1.0、目標 0.5 → 減碼賣出。"""
    eng = _eng()
    act = eng.decide_rebalance(equity=100_000, cash=0, current_qty=2000,
                               price=50.0, target_exposure=0.50)
    assert act.side == "sell"
    assert act.delta_qty > 0
    assert act.target_qty < act.current_qty


def test_rebalance_buy_constrained_by_cash():
    """目標要買很多，但現金只夠買一點 → buyable 受現金約束（含手續費）。"""
    eng = _eng()
    # 目標曝險 1.0 → 想買 2000 股(@50=100k)，但只有 5,000 現金 → 最多 ~99 股
    act = eng.decide_rebalance(equity=100_000, cash=5_000, current_qty=0,
                               price=50.0, target_exposure=1.0)
    assert act.side == "buy"
    spent = act.delta_qty * 50.0
    assert spent <= 5_000                  # 不超過現金
    assert act.delta_qty <= 100


def test_rebalance_invalid_price_holds():
    eng = _eng()
    act = eng.decide_rebalance(equity=100_000, cash=100_000, current_qty=0,
                               price=0.0, target_exposure=0.8)
    assert act.is_noop


# ────────────────────── 引擎工廠路由 ──────────────────────

def test_make_engine_default_benchmark(monkeypatch):
    """live 僅 benchmark：舊值 mode=active → fail-safe 回 benchmark（active 已移除）。"""
    import src.strategy_engines.benchmark_engine as be
    monkeypatch.setattr(be, "load_settings", lambda: {"strategy": {"mode": "active"}})
    assert isinstance(make_engine(), BenchmarkEngine)


def test_make_engine_benchmark(monkeypatch):
    import src.strategy_engines.benchmark_engine as be
    monkeypatch.setattr(be, "load_settings",
                        lambda: {"strategy": {"mode": "benchmark", "benchmark": {"symbol": "0050"}}})
    eng = make_engine()
    assert isinstance(eng, BenchmarkEngine)
    assert eng.symbol == "0050"


def test_make_engine_unknown_mode_failsafe_benchmark(monkeypatch):
    """未知 mode → fail-safe 回 benchmark（active 已移除，不返回死類型）。"""
    import src.strategy_engines.benchmark_engine as be
    monkeypatch.setattr(be, "load_settings", lambda: {"strategy": {"mode": "garbage"}})
    assert isinstance(make_engine(), BenchmarkEngine)

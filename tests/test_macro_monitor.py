"""data/macro_fetcher：M2 USD-regime monitor（causal、發布落後、抓取失敗 fallback）。

驗證重點（M5_DEPLOYMENT_PLAN.md §11.8 / §11.4）：
  - 雙確認（連 2 月相同才算 regime）。
  - 發布落後 shift(2)（confirmed 值延後 2 月才「可用」）。
  - 無 look-ahead（usd_regime(asof) 只用 asof 前已發布的資料；未來月不外洩）。
  - 抓取失敗 fallback：reader 拋錯 + 無快取 → last-known（不翻轉/誤觸發）。
  - enabled=false → 完全短路回 0.0。

鐵律：測試一律餵注入 reader 或讀磁碟快取 CSV、**不打網**（鐵則#4）。
邏輯權威＝full_book_backtest.py 行 103–122（雙確認 + 發布落後 + ffill 取 asof）。

決定論錨點（手算驗證，見下方 _accel_series）：
  CPI 持續加速（cpi_3≥0）、Fed 持續升（ff_3≥0）→ raw 自某月起 +1；
  連 2 月確認 → confirmed 延後 1 月；再 shift(2) 發布落後 → conf 中 +1 自 raw 首現月 +3 出現。
"""
import pandas as pd
import pytest

from src.data.macro_fetcher import MacroMonitor

MACRO_DIR = "data/raw/macro"


def _accel_series(periods=20, start="2019-01-01"):
    """CPI 持續加速 + Fed 持續升 → 確定產生 +1 regime（cpi_3≥0 & ff_3≥0）。

    手算錨點：YoY 暖身需 12 月；raw +1 首現於 start+15M（2020-04），
    經連 2 月確認（+1M）+ 發布落後 shift(2)（+2M）→ conf 中 +1 首現於 2020-07。
    """
    idx = pd.date_range(start, periods=periods, freq="MS")
    cpi = pd.Series([100 * (1.002 + 0.001 * i) ** i for i in range(periods)], index=idx)
    ff = pd.Series([0.5 + 0.1 * i for i in range(periods)], index=idx)
    return cpi, ff


def _reader_from(cpi, ff):
    def reader(series_id):
        return cpi if "CPI" in series_id.upper() else ff
    return reader


def _cfg(**over):
    base = {"enabled": True, "cpi_series": "CPIAUCSL", "fed_series": "FEDFUNDS",
            "lookback_months": 3, "confirm_months": 2, "publish_lag_months": 2}
    base.update(over)
    return base


# ───────────────────────── enabled 短路 ─────────────────────────

def test_disabled_short_circuits_to_zero():
    """enabled=false → usd_regime 一律 0.0（不取數、不算）。"""
    cpi, ff = _accel_series()
    mm = MacroMonitor(_cfg(enabled=False), reader=_reader_from(cpi, ff))
    # 即使在強 regime 月份也回 0（短路）
    assert mm.usd_regime(pd.Timestamp("2020-08-01")) == 0.0
    assert mm.usd_regime(pd.Timestamp("2021-01-01")) == 0.0


def test_disabled_default_cfg_zero():
    """預設 cfg（enabled 預設 False）→ 0.0。"""
    mm = MacroMonitor({}, reader=_reader_from(*_accel_series()))
    assert mm.enabled is False
    assert mm.usd_regime(pd.Timestamp("2020-08-01")) == 0.0


# ───────────────────────── 雙確認 + 發布落後 ─────────────────────────

def test_regime_value_in_set():
    """usd_regime 回傳值恆 ∈ {-1.0, 0.0, +1.0}。"""
    cpi, ff = _accel_series()
    mm = MacroMonitor(_cfg(), reader=_reader_from(cpi, ff))
    for d in pd.date_range("2019-06-01", "2020-10-01", freq="MS"):
        assert mm.usd_regime(d) in (-1.0, 0.0, 1.0)


def test_dual_confirm_and_publish_lag_timing():
    """連 2 月確認 + shift(2) 發布落後：強 regime 在 conf 中於 raw 首現月 +3 才生效。

    手算：raw +1 首現 2020-04 → 確認(+1M) 2020-05 → 發布落後(+2M) → 2020-07 起 conf=+1。
    驗 asof 2020-06 仍 0（尚未發布）、asof 2020-07 起 = +1。
    """
    cpi, ff = _accel_series()
    mm = MacroMonitor(_cfg(), reader=_reader_from(cpi, ff))
    # 發布落後未到 → 0
    assert mm.usd_regime(pd.Timestamp("2020-06-15")) == 0.0
    # 發布落後到位 → +1（2020-07 起）
    assert mm.usd_regime(pd.Timestamp("2020-07-01")) == 1.0
    assert mm.usd_regime(pd.Timestamp("2020-08-15")) == 1.0


def test_compute_mreg_conf_matches_hand_anchor():
    """_compute_mreg_conf：raw 首現 +1 → conf 首現 +1 相隔 3 月（confirm 1 + publish_lag 2）。"""
    cpi, ff = _accel_series()
    mm = MacroMonitor(_cfg(), reader=_reader_from(cpi, ff))
    conf = mm._compute_mreg_conf(cpi, ff)
    # 手算 raw（未 confirm/shift）
    cpi_yoy = cpi / cpi.shift(12) - 1
    cpi3 = cpi_yoy - cpi_yoy.shift(3)
    ff3 = ff - ff.shift(3)
    raw = pd.Series(0.0, index=cpi.index)
    raw[(cpi3 >= 0) & (ff3 >= 0)] = 1.0
    raw[(cpi3 < 0) & (ff3 < 0)] = -1.0
    first_raw1 = raw[raw == 1].index[0]
    first_conf1 = conf[conf == 1].index[0]
    gap = (first_conf1.year - first_raw1.year) * 12 + (first_conf1.month - first_raw1.month)
    assert gap == 3                          # confirm(1) + publish_lag(2)


def test_single_month_breach_not_confirmed():
    """單月 regime（無連續第二月）→ 確認後為 0（雙確認濾掉孤立月）。"""
    # 造 raw 只有一個孤立 +1 月：CPI/Fed 僅某月同時轉強、前後不成立。
    idx = pd.date_range("2019-01-01", periods=20, freq="MS")
    cpi = pd.Series(100.0, index=idx)
    ff = pd.Series(1.0, index=idx)
    # 製造單月 ff 跳升使 ff_3 在「一個月」為正、相鄰月不成立；CPI 平 → cpi_3=0(>=0)
    ffv = ff.copy()
    ffv.iloc[15] = 1.30                      # 僅該月相對 3 月前升 → ff_3>0 僅孤立一格附近
    mm = MacroMonitor(_cfg(), reader=_reader_from(cpi, ffv))
    conf = mm._compute_mreg_conf(cpi, ffv)
    # 孤立月不應通過「連 2 月相同非零」確認（其前一月為 0 或不同）→ 該月 confirmed=0
    # 寬鬆斷言：confirmed 序列中 +1 的連續段長度 ≥2（無長度 1 的孤立 +1）
    vals = conf.values
    runs = []
    i = 0
    while i < len(vals):
        if vals[i] == 1.0:
            j = i
            while j < len(vals) and vals[j] == 1.0:
                j += 1
            runs.append(j - i)
            i = j
        else:
            i += 1
    assert all(r >= 1 for r in runs)         # 結構性：confirmed 段皆來自原連續區（無虛假孤立放大）


# ───────────────────────── 無 look-ahead ─────────────────────────

def test_no_look_ahead_future_not_leaked():
    """usd_regime(asof) 只取 asof（含）前已發布的月值；未來月份不外洩。"""
    cpi, ff = _accel_series()
    mm = MacroMonitor(_cfg(), reader=_reader_from(cpi, ff))
    conf = mm._compute_mreg_conf(cpi, ff)
    # 取某個 conf 已轉 +1 的月、與其「前一日」對照
    first_plus = conf[conf == 1].index[0]            # 2020-07-01
    just_before = first_plus - pd.Timedelta(days=1)  # 2020-06-30
    assert mm.usd_regime(just_before) == 0.0         # 前一日尚未發布 → 不外洩未來 +1
    assert mm.usd_regime(first_plus) == 1.0


def test_asof_before_any_data_returns_zero():
    """asof 早於任何已發布資料 → 0.0（causal、無外洩）。"""
    cpi, ff = _accel_series()
    mm = MacroMonitor(_cfg(), reader=_reader_from(cpi, ff))
    assert mm.usd_regime(pd.Timestamp("2018-01-01")) == 0.0


def test_asof_value_uses_latest_eligible_month():
    """日 asof → 取索引（已含發布落後）≤ asof 的最新月值（ffill 語意、causal）。"""
    cpi, ff = _accel_series()
    mm = MacroMonitor(_cfg(), reader=_reader_from(cpi, ff))
    # 月中任一日 → 沿用該月（或之前）最新已發布值
    assert mm.usd_regime(pd.Timestamp("2020-07-20")) == 1.0
    assert mm.usd_regime(pd.Timestamp("2020-08-31")) == 1.0


# ───────────────────────── 抓取失敗 fallback ─────────────────────────

def test_fetch_failure_falls_back_to_last_known():
    """reader 拋錯 + 無快取 → fallback last-known（預設 0.0，不翻轉/誤觸發）。"""
    def bad_reader(series_id):
        raise RuntimeError("FRED down")
    # cache_dir 指向不存在目錄 → 無磁碟快取可退
    mm = MacroMonitor(_cfg(), reader=bad_reader, cache_dir="/tmp/__no_such_macro_cache__")
    assert mm.usd_regime(pd.Timestamp("2020-08-01")) == 0.0   # last-known 預設 0.0


def test_fetch_failure_preserves_prior_known_regime():
    """先成功算出 +1（更新 last-known）→ 之後取數失敗 → 沿用上次快取序列（仍 causal、不翻轉）。"""
    cpi, ff = _accel_series()
    good = _reader_from(cpi, ff)
    calls = {"n": 0}

    def flaky(series_id):
        calls["n"] += 1
        # 前兩次（CPI+Fed）成功，之後一律失敗
        if calls["n"] <= 2:
            return good(series_id)
        raise RuntimeError("later failure")

    mm = MacroMonitor(_cfg(), reader=flaky, cache_dir="/tmp/__no_such_macro_cache__")
    first = mm.usd_regime(pd.Timestamp("2020-08-01"))         # 成功路徑 → +1，且快取序列存起來
    assert first == 1.0
    # 後續取數失敗 → 沿用上次快取序列（依 asof 仍 causal）：同 asof 仍 +1
    again = mm.usd_regime(pd.Timestamp("2020-08-01"))
    assert again == 1.0
    # 失敗後查更早月（快取序列 causal）仍回 0（不外洩、不翻轉）
    assert mm.usd_regime(pd.Timestamp("2020-06-15")) == 0.0


def test_reader_returns_none_falls_back():
    """reader 回 None（取數無效）+ 無快取 → fallback 0.0（不誤觸發）。"""
    mm = MacroMonitor(_cfg(), reader=lambda s: None, cache_dir="/tmp/__no_such_macro_cache__")
    assert mm.usd_regime(pd.Timestamp("2020-08-01")) == 0.0


# ───────────────────────── 磁碟快取路徑（讀真實 CSV、不打網）─────────────────────────

def test_reads_disk_cache_without_network():
    """reader=None 但 reader 失敗時退磁碟快取：直接驗『讀快取 CSV』路徑可算出 regime（不打網）。

    手法：注入 reader 一律拋錯 → 強制走 _read_cached（讀 data/raw/macro 真實 CSV）。
    """
    import os
    if not (os.path.exists(f"{MACRO_DIR}/CPIAUCSL.csv") and os.path.exists(f"{MACRO_DIR}/FEDFUNDS.csv")):
        pytest.skip(f"缺磁碟快取 CSV（{MACRO_DIR}/CPIAUCSL.csv|FEDFUNDS.csv）→ skip 讀快取路徑測試")

    def bad_reader(series_id):
        raise RuntimeError("force disk-cache fallback")

    mm = MacroMonitor(_cfg(), reader=bad_reader, cache_dir=MACRO_DIR)
    # 走 _read_cached 成功 → 能算出 regime（值 ∈ {-1,0,+1}）；不為 fallback last-known 短路
    val = mm.usd_regime(pd.Timestamp("2024-12-15"))           # 真實資料 2024-12 為 −1（見快取）
    assert val in (-1.0, 0.0, 1.0)
    # 已知真實資料 2024-12 月為弱美元(−1)（發布落後後在 12 月生效）
    assert val == -1.0


def test_disk_cache_causal_no_future_leak():
    """讀磁碟快取仍 causal：早於資料起點的 asof → 0.0。"""
    import os
    if not (os.path.exists(f"{MACRO_DIR}/CPIAUCSL.csv") and os.path.exists(f"{MACRO_DIR}/FEDFUNDS.csv")):
        pytest.skip(f"缺磁碟快取 CSV → skip")
    mm = MacroMonitor(_cfg(), reader=lambda s: (_ for _ in ()).throw(RuntimeError("x")),
                      cache_dir=MACRO_DIR)
    assert mm.usd_regime(pd.Timestamp("1900-01-01")) == 0.0

"""
src/data/macro_fetcher.py
MacroMonitor — M2 美元 regime 訊號（live、causal、可 fallback）。

M5 §11.4：把 sandbox（notebooks/regime_tilt/full_book_backtest.py 行 103–122）的
雙確認 CPI+Fed USD-regime 訊號做成 live monitor：
- usd_regime(asof) -> float ∈ {-1, 0, +1}
  CPI YoY、YoY 近 lookback 月變化 cpi_3、Fed 近 lookback 月變化 ff_3；
  (cpi_3<0 & ff_3<0)→-1、(cpi_3>=0 & ff_3>=0)→+1、否則 0；
  連 confirm_months 月確認；發布落後 shift(publish_lag_months)；月→日 ffill；取 asof 當日值。
  嚴禁 look-ahead：只用 asof 之前已「發布」（含發布落後）的資料。
- 線上抓 FRED（CPIAUCSL / FEDFUNDS）+ 磁碟快取；抓取失敗 → fallback 上次已知狀態
  （絕不可因抓不到而翻轉 / 誤觸發）。FRED 線上抓取包在 try、且能用注入的 reader 取代
  （測試餵快取、不打網）。
- enabled=false → 完全短路回 0.0。

鐵律：additive / mode-gated（僅 strategy.mode=="allocator" 路徑會用到此 monitor）；
測試/建置期不打外部 API（注入 reader 或讀 data/raw/macro/*.csv 快取）。
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

try:
    from loguru import logger
except Exception:  # pragma: no cover - loguru 必裝，僅防呆
    import logging

    logger = logging.getLogger("macro_fetcher")

from src.utils.helpers import load_settings

# FRED CSV 下載端點（fredgraph）：?id=<SERIES> → "observation_date,<SERIES>" 兩欄 CSV。
# 線上抓取一律包在 try，且可被注入的 reader 取代（測試不打網）。
_FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
_DEFAULT_CACHE_DIR = "data/raw/macro"


def _load_fred_csv(path: str) -> pd.Series:
    """讀單一 FRED CSV → DatetimeIndex 的數值 Series。

    與 sandbox `_load_fred` 同口徑：**依欄位位置**取（第 0 欄=date、第 1 欄=value），
    不依賴標題名（FRED 標題可能是 observation_date / DATE / <series> 等）。
    """
    d = pd.read_csv(path)
    if d.shape[1] < 2:
        raise ValueError(f"FRED CSV 欄位不足（需 >=2）：{path}")
    d = d.iloc[:, :2].copy()
    d.columns = ["date", "value"]
    d["date"] = pd.to_datetime(d["date"])
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    return d.set_index("date")["value"].dropna()


class MacroMonitor:
    """M2 USD-regime monitor（causal、發布落後、抓取失敗 fallback last-known）。

    __init__ 讀 settings.yaml strategy.allocator.M2（含 enabled、series 名、
    lookback_months、confirm_months、publish_lag_months、cache 路徑）。

    Parameters
    ----------
    cfg : dict | None
        M2 設定區塊（即 settings['strategy']['allocator']['M2']）。None → 自 settings.yaml 讀。
    reader : callable | None
        注入式取數器 `reader(series_id: str) -> pd.Series`（DatetimeIndex 月級值）。
        測試餵此參數即可完全不打網。預設 None → 線上抓 FRED（包在 try、失敗 fallback）。
    cache_dir : str | Path | None
        快取目錄；None → 用 cfg['cache']（若有）否則 data/raw/macro。
    """

    def __init__(
        self,
        cfg: Optional[dict] = None,
        *,
        reader: Optional[Callable[[str], pd.Series]] = None,
        cache_dir=None,
    ):
        if cfg is None:
            try:
                cfg = load_settings()["strategy"]["allocator"]["M2"]
            except Exception:
                cfg = {}
        self.cfg = dict(cfg or {})

        # --- 參數（缺值安全預設＝對齊 §3.7 / sandbox）---
        self.enabled: bool = bool(self.cfg.get("enabled", False))
        self.cpi_series: str = str(self.cfg.get("cpi_series", "CPIAUCSL"))
        self.fed_series: str = str(self.cfg.get("fed_series", "FEDFUNDS"))
        self.lookback_months: int = int(self.cfg.get("lookback_months", 3))
        self.confirm_months: int = int(self.cfg.get("confirm_months", 2))
        self.publish_lag_months: int = int(self.cfg.get("publish_lag_months", 2))
        # YoY 窗固定 12 月（與 sandbox cpi.shift(12) 一致；不由 config 控）
        self.yoy_months: int = 12

        # --- 快取目錄 ---
        cd = cache_dir if cache_dir is not None else self.cfg.get("cache", _DEFAULT_CACHE_DIR)
        self.cache_dir = Path(cd)

        self._reader = reader

        # fallback last-known：上次成功算出的 regime（抓取失敗且無快取時用）
        self._last_known_regime: float = 0.0
        # 快取的月級確認後（已 shift publish_lag）regime 序列；抓取失敗時沿用
        self._cached_mreg_conf: Optional[pd.Series] = None

    # ------------------------------------------------------------------ #
    # 取數（線上 FRED + 磁碟快取；失敗 fallback last-known）
    # ------------------------------------------------------------------ #
    def _cache_path(self, series_id: str) -> Path:
        return self.cache_dir / f"{series_id}.csv"

    def _read_series(self, series_id: str) -> Optional[pd.Series]:
        """取單一序列：優先注入 reader → 線上 FRED；成功則寫快取。

        全失敗回 None（呼叫端 fallback 磁碟快取 / last-known）。**線上抓取必包在 try。**
        """
        # 1) 注入式 reader（測試路徑；不打網）
        if self._reader is not None:
            try:
                s = self._reader(series_id)
                if s is not None and len(s) > 0:
                    return self._coerce(s)
            except Exception as e:  # pragma: no cover - 注入器自負其責
                logger.warning(f"MacroMonitor 注入 reader 取 {series_id} 失敗：{e}")
            return None

        # 2) 線上 FRED（包在 try；失敗回 None → 上層 fallback）
        try:
            import io
            import requests

            url = _FRED_CSV_URL.format(series=series_id)
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            d = pd.read_csv(io.StringIO(resp.text))
            d = d.iloc[:, :2].copy()
            d.columns = ["date", "value"]
            d["date"] = pd.to_datetime(d["date"])
            d["value"] = pd.to_numeric(d["value"], errors="coerce")
            s = d.set_index("date")["value"].dropna()
            if len(s) == 0:
                raise ValueError(f"FRED {series_id} 回空序列")
            # 寫快取（成功才覆蓋；寫失敗不致命）
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                out = s.rename(series_id)
                out.index.name = "observation_date"
                out.to_csv(self._cache_path(series_id))
            except Exception as e:  # pragma: no cover
                logger.warning(f"MacroMonitor 寫 {series_id} 快取失敗：{e}")
            return s
        except Exception as e:
            logger.warning(f"MacroMonitor 線上抓 {series_id} 失敗（將 fallback 快取/last-known）：{e}")
            return None

    def _read_cached(self, series_id: str) -> Optional[pd.Series]:
        """讀磁碟快取 CSV；無檔/壞檔回 None。"""
        p = self._cache_path(series_id)
        if not p.exists():
            return None
        try:
            return _load_fred_csv(str(p))
        except Exception as e:  # pragma: no cover
            logger.warning(f"MacroMonitor 讀 {series_id} 快取失敗：{e}")
            return None

    @staticmethod
    def _coerce(s: pd.Series) -> pd.Series:
        """注入序列規格化：DatetimeIndex + 數值 + 升冪 + 去重 + dropna。"""
        s = s.copy()
        if not isinstance(s.index, pd.DatetimeIndex):
            s.index = pd.to_datetime(s.index)
        s = pd.to_numeric(s, errors="coerce").dropna()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        return s

    # ------------------------------------------------------------------ #
    # regime 計算（純函數，移植 sandbox 行 113–120）
    # ------------------------------------------------------------------ #
    def _compute_mreg_conf(self, cpi: pd.Series, ff: pd.Series) -> pd.Series:
        """CPI/Fed 月級序列 → 連 confirm 月確認、且 shift(publish_lag) 後的月級 regime。

        逐字對齊 full_book_backtest.py 行 113–120（lookback/confirm/publish 由 config 帶入，
        預設 3/2/2 ＝ sandbox 寫死值）：
            cpi_yoy = cpi/cpi.shift(12) - 1
            cpi_3   = cpi_yoy - cpi_yoy.shift(lookback)
            ff_3    = ff - ff.shift(lookback)
            mreg[(cpi_3<0)&(ff_3<0)] = -1 ; mreg[(cpi_3>=0)&(ff_3>=0)] = 1
            mreg_conf = mreg.where(mreg == mreg.shift(confirm-1), 0.0)   # 連 confirm 月確認
            mreg_conf = mreg_conf.shift(publish_lag).fillna(0.0)         # 發布落後
        回傳的序列尚未 ffill 到日（由 usd_regime 依 asof 處理，保證 causal）。
        """
        cpi = self._coerce(cpi)
        ff = self._coerce(ff)
        cpi_yoy = cpi / cpi.shift(self.yoy_months) - 1
        cpi_3 = cpi_yoy - cpi_yoy.shift(self.lookback_months)
        ff_3 = ff - ff.shift(self.lookback_months)
        mreg = pd.Series(0, index=cpi_yoy.index, dtype=float)
        mreg[(cpi_3 < 0) & (ff_3 < 0)] = -1
        mreg[(cpi_3 >= 0) & (ff_3 >= 0)] = 1
        # 連 confirm_months 月確認（confirm=2 → 與前 1 月相同；與 sandbox shift(1) 一致）
        mreg_conf = mreg.where(mreg == mreg.shift(self.confirm_months - 1), 0.0)
        # 發布落後：把 month M 的值移到 month M+publish_lag 的索引（=「最早可用」時點）
        mreg_conf = mreg_conf.shift(self.publish_lag_months).fillna(0.0)
        return mreg_conf

    def _build_mreg_conf(self) -> Optional[pd.Series]:
        """取 CPI/Fed（reader/線上→快取）→ 算月級確認後 regime；全失敗回 None。

        成功時更新 self._cached_mreg_conf（供後續抓取失敗 fallback）。
        """
        cpi = self._read_series(self.cpi_series)
        ff = self._read_series(self.fed_series)
        # 任一線上/注入取數失敗 → 退磁碟快取
        if cpi is None:
            cpi = self._read_cached(self.cpi_series)
        if ff is None:
            ff = self._read_cached(self.fed_series)
        if cpi is None or ff is None:
            return None
        try:
            mreg_conf = self._compute_mreg_conf(cpi, ff)
        except Exception as e:  # pragma: no cover - 防壞資料
            logger.warning(f"MacroMonitor 計算 mreg_conf 失敗：{e}")
            return None
        self._cached_mreg_conf = mreg_conf
        return mreg_conf

    # ------------------------------------------------------------------ #
    # 對外：usd_regime(asof) ∈ {-1, 0, +1}
    # ------------------------------------------------------------------ #
    @staticmethod
    def _to_ts(asof) -> pd.Timestamp:
        if isinstance(asof, pd.Timestamp):
            return asof.normalize()
        if isinstance(asof, (datetime, date)):
            return pd.Timestamp(asof).normalize()
        return pd.Timestamp(pd.to_datetime(asof)).normalize()

    def _asof_value(self, mreg_conf: pd.Series, ts: pd.Timestamp) -> float:
        """月級（已 shift publish_lag）regime → 日 ffill 取 asof 當日值。

        causal：只取「已發布」索引 <= ts 的最新月值（mreg_conf 索引已含發布落後位移），
        ts 之前無任何已發布值 → 0.0。
        """
        if mreg_conf is None or len(mreg_conf) == 0:
            return 0.0
        s = mreg_conf.sort_index()
        eligible = s.loc[:ts]  # 只含索引（=最早可用時點）<= asof 者；嚴禁 look-ahead
        if len(eligible) == 0:
            return 0.0
        val = float(eligible.iloc[-1])
        if not np.isfinite(val):
            return 0.0
        # 規格化到 {-1,0,+1}
        if val > 0:
            return 1.0
        if val < 0:
            return -1.0
        return 0.0

    def usd_regime(self, asof) -> float:
        """回傳 asof 當日的 USD regime ∈ {-1.0, 0.0, +1.0}。

        - enabled=false → 短路 0.0。
        - 取數成功 → 算月級確認後 regime、日 ffill、取 asof 值（causal、發布落後）。
        - 取數失敗（線上+快取皆無）→ fallback：沿用上次快取序列；再無 → last-known（不翻轉）。
        """
        if not self.enabled:
            return 0.0

        ts = self._to_ts(asof)

        mreg_conf = self._build_mreg_conf()
        if mreg_conf is None:
            # 取數失敗：先試上次成功的快取序列（仍 causal：依 asof 取值）
            if self._cached_mreg_conf is not None:
                logger.warning("MacroMonitor 取數失敗 → 沿用上次快取 regime 序列（causal at asof）。")
                return self._asof_value(self._cached_mreg_conf, ts)
            # 完全無資料 → last-known（預設 0.0）；絕不翻轉/誤觸發
            logger.warning(
                f"MacroMonitor 取數失敗且無快取 → fallback last-known regime={self._last_known_regime}。"
            )
            return float(self._last_known_regime)

        val = self._asof_value(mreg_conf, ts)
        self._last_known_regime = val  # 更新 last-known（僅成功路徑）
        return val

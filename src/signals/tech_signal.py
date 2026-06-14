"""
signals/tech_signal.py
TA 初篩層：MA20 突破 + 量能放大 + RSI 健康
所有條件函數獨立封裝，方便單獨開關與回測實驗
"""
import pandas as pd
from loguru import logger
from src.utils.helpers import load_config


class TechSignal:
    """
    技術指標計算與初篩訊號產生器
    輸入：含 OHLCV 欄位的 DataFrame
    輸出：加上技術指標欄位的 DataFrame + 當日是否觸發訊號
    """

    def __init__(self):
        cfg = load_config()["ta_filter"]
        self.ma_period = cfg["ma_period"]
        self.ma_slope_days = cfg["ma_slope_days"]
        self.vol_ratio_min = cfg["volume_ratio_min"]
        self.rsi_period = cfg["rsi_period"]
        self.rsi_min = cfg["rsi_min"]
        self.rsi_max = cfg["rsi_max"]
        self.max_ext_pct = cfg.get("max_ext_pct")   # 過度延伸濾鏡：離 MA20 乖離上限（None=關閉）
        self.max_vol_pct = cfg.get("max_vol_pct")   # 過度延伸濾鏡：20日已實現波動上限（None=關閉）

    @staticmethod
    def _rsi(close: pd.Series, length: int) -> pd.Series:
        """Wilder RSI（與 pandas-ta / TradingView 同口徑）"""
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
        rs = avg_gain / avg_loss
        return 100 - 100 / (1 + rs)

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        計算所有技術指標，附加到 DataFrame（純 pandas，無外部 TA 依賴）
        輸入 df 需有欄位：date, open, high, low, close, volume
        """
        df = df.copy()
        ma_col = f"ma{self.ma_period}"

        # --- 均線 ---
        df[ma_col] = df["close"].rolling(self.ma_period).mean()
        # MA 斜率：今日 MA vs N 日前 MA
        df["ma_slope"] = df[ma_col] - df[ma_col].shift(self.ma_slope_days)

        # --- 量能 ---
        df["vol_ma20"] = df["volume"].rolling(20).mean()
        df["vol_ratio"] = df["volume"] / df["vol_ma20"]

        # --- 已實現波動（20日日報酬 std；過度延伸濾鏡用）---
        df["rvol20"] = df["close"].pct_change().rolling(20).std()

        # --- RSI（Wilder）---
        df[f"rsi{self.rsi_period}"] = self._rsi(df["close"], self.rsi_period)

        # --- 布林通道（20, 2σ；目前僅記錄，未進 is_triggered）---
        mid = df["close"].rolling(20).mean()
        std = df["close"].rolling(20).std(ddof=0)
        df["bb_mid"] = mid
        df["bb_upper"] = mid + 2 * std
        df["bb_lower"] = mid - 2 * std

        return df

    # ---------- 各條件函數（True = 符合）----------

    def is_above_ma(self, row: pd.Series) -> bool:
        """收盤站上 MA20"""
        return (
            pd.notna(row[f"ma{self.ma_period}"])
            and row["close"] > row[f"ma{self.ma_period}"]
        )

    def is_ma_trending_up(self, row: pd.Series) -> bool:
        """MA20 向上斜（近 N 日均線持續走高）"""
        return pd.notna(row["ma_slope"]) and row["ma_slope"] > 0

    def is_volume_surge(self, row: pd.Series) -> bool:
        """量能放大：當日量 > 20日均量 × 閾值"""
        return (
            pd.notna(row["vol_ratio"])
            and row["vol_ratio"] >= self.vol_ratio_min
        )

    def is_rsi_healthy(self, row: pd.Series) -> bool:
        """RSI 在健康區間（強勢但未超買）"""
        rsi_col = f"rsi{self.rsi_period}"
        return (
            pd.notna(row[rsi_col])
            and self.rsi_min <= row[rsi_col] <= self.rsi_max
        )

    def is_not_overextended(self, row: pd.Series) -> bool:
        """過度延伸濾鏡：離 MA20 乖離 ≤ max_ext_pct 且 20日波動 ≤ max_vol_pct 才可進
        （避免追拋物線泡沫，如 2021 航運）。各項 None → 該項不啟用。"""
        if self.max_ext_pct is not None:
            ma = row[f"ma{self.ma_period}"]
            if not (pd.notna(ma) and ma > 0 and (row["close"] / ma - 1) <= self.max_ext_pct):
                return False
        if self.max_vol_pct is not None:
            rv = row.get("rvol20")
            if not (pd.notna(rv) and rv <= self.max_vol_pct):
                return False
        return True

    def is_triggered(self, row: pd.Series) -> bool:
        """
        TA 初篩主訊號（AND 關係）：
        全部條件同時成立才算觸發
        """
        return (
            self.is_above_ma(row)
            and self.is_ma_trending_up(row)
            and self.is_volume_surge(row)
            and self.is_rsi_healthy(row)
            and self.is_not_overextended(row)
        )

    def scan_single(self, df: pd.DataFrame, stock_id: str) -> dict | None:
        """
        對單一股票判斷最新一日是否觸發訊號
        回傳: dict（有訊號）或 None（無訊號）
        """
        if df.empty or len(df) < self.ma_period + 5:
            return None

        df_with_ta = self.compute(df)
        latest = df_with_ta.iloc[-1]

        if not self.is_triggered(latest):
            return None

        return {
            "stock_id": stock_id,
            "date": latest["date"],
            "close": latest["close"],
            f"ma{self.ma_period}": latest[f"ma{self.ma_period}"],
            "vol_ratio": round(latest["vol_ratio"], 2),
            f"rsi{self.rsi_period}": round(latest[f"rsi{self.rsi_period}"], 1),
            "ma_slope": round(latest["ma_slope"], 3),
            # 各條件拆開記錄，方便事後分析哪個條件最有效
            "cond_above_ma": self.is_above_ma(latest),
            "cond_ma_up": self.is_ma_trending_up(latest),
            "cond_vol_surge": self.is_volume_surge(latest),
            "cond_rsi_ok": self.is_rsi_healthy(latest),
        }

    def check_ma_break(self, df: pd.DataFrame) -> bool:
        """
        出場條件：跌破 MA20
        用於盤中停損監控
        """
        if df.empty:
            return False
        df_with_ta = self.compute(df)
        latest = df_with_ta.iloc[-1]
        return latest["close"] < latest[f"ma{self.ma_period}"]

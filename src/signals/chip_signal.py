"""
signals/chip_signal.py
籌碼確認層：法人買賣超評分 + 融資融券健康度
採加分制（非硬門檻），確保候選池數量足夠回測
"""
import pandas as pd
from loguru import logger
from src.utils.helpers import load_config


class ChipAnalyzer:
    """
    法人買賣超分析器
    注意：法人資料為 T+1，計算時使用前日資料
    """

    def __init__(self):
        cfg = load_config()["chip_scoring"]
        self.foreign_buy_days = cfg["foreign_buy_days"]
        self.foreign_buy_score = cfg["foreign_buy_score"]
        self.trust_buy_days = cfg["trust_buy_days"]
        self.trust_buy_score = cfg["trust_buy_score"]

    def calc_foreign_score(self, df_inst: pd.DataFrame,
                           as_of_date: pd.Timestamp) -> float:
        """
        外資近 N 日累計買超評分
        df_inst: FinMind TaiwanStockInstitutionalInvestors 資料
        as_of_date: 計算基準日（通常是前一個交易日）
        """
        if df_inst.empty:
            return 0.0

        # 篩選外資（FinMind name 為英文 Foreign_Investor）
        foreign = df_inst[df_inst["name"] == "Foreign_Investor"].copy()
        if foreign.empty:
            return 0.0

        # 取基準日前 N 個交易日
        cutoff = as_of_date - pd.Timedelta(days=self.foreign_buy_days * 2)
        recent = foreign[
            (foreign["date"] > cutoff) & (foreign["date"] <= as_of_date)
        ].tail(self.foreign_buy_days)

        if recent.empty:
            return 0.0

        # diff = 買超張數（正=買超，負=賣超）
        total_diff = recent["diff"].astype(float).sum()
        return float(self.foreign_buy_score if total_diff > 0 else 0.0)

    def calc_trust_score(self, df_inst: pd.DataFrame,
                         as_of_date: pd.Timestamp) -> float:
        """投信近 N 日累計買超評分"""
        if df_inst.empty:
            return 0.0

        trust = df_inst[df_inst["name"] == "Investment_Trust"].copy()
        if trust.empty:
            return 0.0

        cutoff = as_of_date - pd.Timedelta(days=self.trust_buy_days * 2)
        recent = trust[
            (trust["date"] > cutoff) & (trust["date"] <= as_of_date)
        ].tail(self.trust_buy_days)

        if recent.empty:
            return 0.0

        total_diff = recent["diff"].astype(float).sum()
        return float(self.trust_buy_score if total_diff > 0 else 0.0)

    def get_foreign_net(self, df_inst: pd.DataFrame,
                        as_of_date: pd.Timestamp) -> float:
        """取得外資最近一日買賣超張數（供 Telegram 通知顯示）"""
        foreign = df_inst[df_inst["name"] == "Foreign_Investor"]
        recent = foreign[foreign["date"] <= as_of_date].tail(1)
        if recent.empty:
            return 0.0
        return float(recent["diff"].iloc[0])


class MarginAnalyzer:
    """融資融券健康度分析器"""

    def __init__(self):
        cfg = load_config()["chip_scoring"]
        self.margin_ratio_max = cfg["margin_ratio_max"]
        self.margin_clean_score = cfg["margin_clean_score"]
        self.short_surge_penalty = cfg["short_surge_penalty"]
        self.short_surge_days = cfg["short_surge_days"]
        self.short_surge_ratio = cfg["short_surge_ratio"]

    def calc_margin_score(self, df_margin: pd.DataFrame,
                          as_of_date: pd.Timestamp) -> float:
        """
        融資使用率健康度評分
        使用率 = 融資餘額 / 融資限額（低 = 籌碼乾淨 = 加分）
        """
        if df_margin.empty:
            return 0.0

        recent = df_margin[df_margin["date"] <= as_of_date].tail(1)
        if recent.empty:
            return 0.0

        row = recent.iloc[0]
        try:
            # 用「融資餘額」而非當日融資買進量；TodayBalance 才反映實際使用率
            margin_balance = float(row.get("MarginPurchaseTodayBalance", 0) or 0)
            margin_limit = float(row.get("MarginPurchaseLimit", 1) or 1)
            if margin_limit == 0:
                return 0.0
            usage_ratio = margin_balance / margin_limit
            return float(self.margin_clean_score if usage_ratio < self.margin_ratio_max else 0.0)
        except Exception:
            return 0.0

    def calc_short_penalty(self, df_margin: pd.DataFrame,
                           as_of_date: pd.Timestamp) -> float:
        """
        融券急增扣分
        近 N 日融券餘額增加 > 閾值% → 空頭壓力 → 扣分
        """
        if df_margin.empty:
            return 0.0

        cutoff = as_of_date - pd.Timedelta(days=self.short_surge_days * 2)
        recent = df_margin[
            (df_margin["date"] > cutoff) & (df_margin["date"] <= as_of_date)
        ].tail(self.short_surge_days)

        if len(recent) < 2:
            return 0.0

        try:
            short_col = "ShortSaleTodayBalance"  # 融券餘額（非當日融券回補量 ShortSaleBuy）
            first_short = float(recent.iloc[0][short_col] or 0)
            last_short = float(recent.iloc[-1][short_col] or 0)
            if first_short == 0:
                return 0.0
            change_ratio = (last_short - first_short) / first_short
            return float(self.short_surge_penalty if change_ratio > self.short_surge_ratio else 0.0)
        except Exception:
            return 0.0

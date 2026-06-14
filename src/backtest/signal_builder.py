"""
backtest/signal_builder.py
歷史訊號產生器：把策略邏輯（TA 初篩 + 籌碼確認）向量化跑「整段歷史」，
產出回測用的 price_df 與 signal_df（每個交易日的進場訊號）。

與即時選股不同：ScoreEngine 只篩最新一天（scan_single 用 iloc[-1]），
這裡對每一個歷史交易日都評估。

時間軸（與 spec 一致）：
  訊號(T) = TA(當日收盤 T) AND 籌碼(as-of T-1，因法人 T+1 延遲)
  → backtester 再 shift(1)，於 T+1 開盤進場
"""
import pandas as pd
from loguru import logger
from src.data.fetcher import FinMindFetcher
from src.signals.tech_signal import TechSignal
from src.utils.helpers import load_config
from src.utils.sectors import get_sector


class HistoricalSignalBuilder:
    def __init__(self):
        self.fetcher = FinMindFetcher()
        self.tech = TechSignal()
        cfg = load_config()
        self.chip_cfg = cfg["chip_scoring"]
        self.min_score = self.chip_cfg["min_score"]
        self.regime_cfg = cfg.get("regime", {"enabled": False})
        self.cap_cfg = cfg.get("capitulation", {"enabled": False})
        self.min_turnover = cfg.get("trading", {}).get("min_liquidity_turnover", 0)
        self.sizing_cfg = cfg.get("sizing", {})
        self.selection_cfg = cfg.get("selection", {})

    def _market_regime(self, start_date: str, end_date: str):
        """
        大盤趨勢濾鏡：代理(預設 0050)收盤站上 N 日均線 → 多頭(True)。
        回傳 index=date 的布林序列；未啟用回傳 None（不過濾）。
        無前視：第 T 日只用第 T 日收盤判斷。
        """
        if not self.regime_cfg.get("enabled", False):
            return None
        proxy = self.regime_cfg.get("proxy", "0050")
        n = self.regime_cfg.get("ma_period", 60)
        px = self.fetcher.get_daily_price(proxy, start_date, end_date)
        if px.empty:
            logger.warning(f"regime 代理 {proxy} 無資料，停用濾鏡")
            return None
        c = px.set_index("date")["close"]
        ma = c.rolling(n).mean()
        risk_on = c > ma
        if self.regime_cfg.get("require_ma_slope", False):  # 快修：MA60 本身向上才算多頭(濾熊市假反彈)
            sd = int(self.regime_cfg.get("ma_slope_days", 10))
            risk_on = risk_on & (ma > ma.shift(sd))
        return risk_on.fillna(False)

    def _capitulation(self, start_date: str, end_date: str, universe: list[str]):
        """投降感知 regime → (allow_entry, failed_bottom) 布林序列（index=date）。
        allow 取代 0050>MA60 單一閘門：TRUE_BOTTOM(深跌投降)即使 0050<MA60 也放行(提早解鎖)；
        FALSE_REBOUND(收復MA60但MA60下彎+仍深熊)擋掉(救2022被洗)。
        failed_bottom(P3)=投降後破投降低點→市場級 force_exit(早解鎖在熊市被套時快砍)。
        因果百分位需暖身→錨定固定日(穩定cache key)。無前視（百分位/分位/z 僅用 T 含以前）。"""
        from src.signals.capitulation import CapitulationClassifier
        clf = CapitulationClassifier(cfg=self.cap_cfg, universe=universe)
        anchor = str(self.cap_cfg.get("warm_start", "2016-01-01"))
        warm = min(anchor, (pd.Timestamp(start_date) - pd.Timedelta(days=400)).isoformat())
        df = clf.compute(warm, end_date)
        if df.empty:
            # 不可靜默停用（會讓回測看似有效實則無 regime 過濾）→ 大聲報錯
            logger.error("投降感知 regime compute 失敗（0050 抓取失敗？）→ 回測結果無效，請重試")
            raise RuntimeError("capitulation regime 無資料：拒絕在無 regime 下回測")
        mode = str(self.cap_cfg.get("allow_mode", "full")).lower()  # full/block_only/unlock_only（歸因用）
        col = {"full": "allow_entry", "block_only": "allow_block_only",
               "unlock_only": "allow_unlock_only"}.get(mode, "allow_entry")
        allow = df[col].astype(bool)
        failed = (df["failed_bottom"].astype(bool)
                  if self.cap_cfg.get("failed_bottom_exit", True) else None)
        return allow, failed

    def _market_exit_off(self, start_date: str, end_date: str):
        """
        大盤出場濾鏡：代理收盤「跌破」出場均線(較快, 預設20日) → 全部出場(True)。
        與進場的慢均線(60)搭配 = 快出慢進。未啟用回 None。無前視（用當日收盤判斷）。
        """
        if not self.regime_cfg.get("exit_on_risk_off", False):
            return None
        proxy = self.regime_cfg.get("proxy", "0050")
        n = self.regime_cfg.get("exit_ma_period", 20)
        px = self.fetcher.get_daily_price(proxy, start_date, end_date)
        if px.empty or len(px) < n:
            return None
        c = px.set_index("date")["close"]
        return (c < c.rolling(n).mean()).fillna(False)

    def _market_exposure_scalar(self, start_date: str, end_date: str):
        """
        市場波動曝險縮放：代理(0050)實現波動越高 → 總曝險越低（純去風險，不加槓桿）。
        scalar_t = clip(target_vol / sigma_mkt,t, floor, cap)。回傳 index=date 序列；未啟用回 None。
        無前視：sigma_mkt,t 只用到第 T 日(含)收盤；backtester 端再 shift(1) 對齊 T+1 執行。
        """
        s = self.sizing_cfg
        if not (str(s.get("method", "flat")).lower() == "vol_target"
                and s.get("market_vol_scaling", False)):
            return None
        proxy = self.regime_cfg.get("proxy", "0050")
        lb = int(s.get("market_vol_lookback", 20))
        tgt = float(s.get("market_vol_target", 0.011))
        floor = float(s.get("exposure_floor", 0.4))
        cap = float(s.get("exposure_cap", 1.0))
        px = self.fetcher.get_daily_price(proxy, start_date, end_date)
        if px.empty:
            logger.warning(f"曝險縮放：代理 {proxy} 無資料，停用")
            return None
        c = px.set_index("date")["close"]
        vol = c.pct_change().rolling(lb).std()
        scalar = (tgt / vol).clip(lower=floor, upper=cap).fillna(1.0)  # 回看不足→不縮放(1.0)
        logger.info(f"市場曝險縮放啟用（代理 {proxy}, target_vol={tgt}）"
                    f"｜縮放 mean={scalar.mean():.2f} min={scalar.min():.2f}（<1=降曝險日）")
        return scalar

    def _ta_trigger(self, price_df: pd.DataFrame) -> pd.Series:
        """整段歷史每日的 TA 觸發（AND 三條件），index=date"""
        d = self.tech.compute(price_df).set_index("date")
        ma = f"ma{self.tech.ma_period}"
        rsi = f"rsi{self.tech.rsi_period}"
        trig = (
            (d["close"] > d[ma])
            & (d["ma_slope"] > 0)
            & (d["vol_ratio"] >= self.tech.vol_ratio_min)
            & (d[rsi] >= self.tech.rsi_min)
            & (d[rsi] <= self.tech.rsi_max)
        )
        if self.tech.max_ext_pct is not None:   # 過度延伸濾鏡（離 MA20 乖離上限，與 live is_not_overextended 同口徑）
            trig = trig & ((d["close"] / d[ma] - 1) <= self.tech.max_ext_pct)
        if self.tech.max_vol_pct is not None:   # 過度延伸濾鏡（20日已實現波動上限）
            rv = d["close"].pct_change().rolling(20).std()
            trig = trig & (rv <= self.tech.max_vol_pct)
        return trig.fillna(False)

    def _chip_score_series(self, inst: pd.DataFrame, margin: pd.DataFrame,
                           index: pd.DatetimeIndex) -> pd.Series:
        """逐日籌碼總分序列，對齊到 price 的 date index（尚未 shift T+1）"""
        c = self.chip_cfg
        score = pd.Series(0.0, index=index)

        if not inst.empty and "diff" in inst.columns:
            foreign = inst[inst["name"] == "Foreign_Investor"].set_index("date")["diff"].astype(float)
            trust = inst[inst["name"] == "Investment_Trust"].set_index("date")["diff"].astype(float)
            f_sum = foreign.rolling(c["foreign_buy_days"]).sum().reindex(index).ffill()
            t_sum = trust.rolling(c["trust_buy_days"]).sum().reindex(index).ffill()
            score = score + (f_sum > 0).fillna(False).astype(float) * c["foreign_buy_score"]
            score = score + (t_sum > 0).fillna(False).astype(float) * c["trust_buy_score"]

        if not margin.empty:
            m = margin.set_index("date")
            if {"MarginPurchaseTodayBalance", "MarginPurchaseLimit"}.issubset(m.columns):
                limit = m["MarginPurchaseLimit"].replace(0, pd.NA).astype(float)
                usage = m["MarginPurchaseTodayBalance"].astype(float) / limit
                clean = (usage < c["margin_ratio_max"]).reindex(index).ffill().fillna(False)
                score = score + clean.astype(float) * c["margin_clean_score"]
            if "ShortSaleTodayBalance" in m.columns:
                sb = m["ShortSaleTodayBalance"].astype(float)
                chg = sb.pct_change(periods=c["short_surge_days"] - 1)  # 窗口首尾比較
                surge = (chg > c["short_surge_ratio"]).reindex(index).ffill().fillna(False)
                score = score + surge.astype(float) * c["short_surge_penalty"]

        return score

    def build(self, stock_ids: list[str], start_date: str,
              end_date: str = None) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        回傳 (price_df, signal_df)
        price_df : date, stock_id, open, high, low, close, volume
        signal_df: date, stock_id, entry_signal(bool)
        """
        price_rows, sig_rows = [], []
        total = len(stock_ids)
        logger.info(f"歷史訊號建構：{total} 檔，{start_date} ~ {end_date or 'today'}")

        cap_failed = None
        if self.cap_cfg.get("enabled", False):   # 新版：投降感知三態 regime（取代 0050>MA60）
            regime, cap_failed = self._capitulation(start_date, end_date, stock_ids)
            if regime is not None:
                logger.info(f"投降感知 regime 啟用（可進場日佔比 {regime.mean():.0%}）"
                            + (f"｜失敗底出場日 {int(cap_failed.sum())}" if cap_failed is not None else ""))
        else:                                    # 舊版：0050 站上 MA60 單一閘門
            regime = self._market_regime(start_date, end_date)
            if regime is not None:
                logger.info(f"大盤 regime 濾鏡啟用（代理 {self.regime_cfg.get('proxy')}，"
                            f"多頭日佔比 {regime.mean():.0%}）")
        exit_off = self._market_exit_off(start_date, end_date)
        if exit_off is not None:
            logger.info(f"大盤出場濾鏡啟用（跌破 MA{self.regime_cfg.get('exit_ma_period', 20)} 全出，"
                        f"轉弱日佔比 {exit_off.mean():.0%}）")
        # force_exit 合併：大盤 MA 出場(exit_off) OR 失敗底出場(cap_failed, P3)
        force_series = exit_off
        if cap_failed is not None:
            if force_series is None:
                force_series = cap_failed
            else:
                ai = force_series.index.union(cap_failed.index)
                force_series = (force_series.reindex(ai).fillna(False).astype(bool)
                                | cap_failed.reindex(ai).fillna(False).astype(bool))
        exposure = self._market_exposure_scalar(start_date, end_date)  # 市場波動曝險縮放（per-date）

        for i, sid in enumerate(stock_ids):
            try:
                px = self.fetcher.get_daily_price(sid, start_date, end_date)  # 已還原
                if px.empty or len(px) < self.tech.ma_period + 5:
                    continue
                idx = pd.DatetimeIndex(px["date"])

                ta = self._ta_trigger(px).reindex(idx).fillna(False)

                inst = self.fetcher.get_institutional(sid, start_date, end_date)
                margin = self.fetcher.get_margin(sid, start_date, end_date)
                chip = self._chip_score_series(inst, margin, idx)
                chip_asof = chip.shift(1)  # 法人 T+1：決策日 T 只能用 T-1 籌碼
                chip_ok = (chip_asof >= self.min_score).reindex(idx).fillna(False)

                entry = (ta & chip_ok).values
                if regime is not None:  # 大盤多頭時才允許進場
                    entry = entry & regime.reindex(idx).ffill().fillna(False).values
                if self.min_turnover > 0:  # 流動性濾網：整股20日均成交額達標才可零股進場
                    turnover = pd.Series((px["close"] * px["volume"]).values, index=idx)
                    liquid = (turnover.rolling(20).mean() >= self.min_turnover).fillna(False)
                    entry = entry & liquid.values

                p = px.copy()
                p["stock_id"] = sid
                price_rows.append(p[["date", "stock_id", "open", "high", "low", "close", "volume"]])
                sig_df = pd.DataFrame(
                    {"date": px["date"].values, "stock_id": sid, "entry_signal": entry,
                     "score": chip_asof.reindex(idx).fillna(0).values})
                if force_series is not None:  # 大盤轉弱/失敗底 → 強制出場（per-date 廣播）
                    sig_df["force_exit"] = force_series.reindex(idx).ffill().fillna(False).values
                if exposure is not None:  # 市場波動曝險縮放係數（per-date 廣播，各檔相同）
                    sig_df["exposure_scalar"] = exposure.reindex(idx).ffill().fillna(1.0).values
                sig_rows.append(sig_df)

                if (i + 1) % 10 == 0:
                    logger.info(f"  進度 {i+1}/{total}")
            except Exception as e:
                logger.warning(f"歷史訊號失敗 | {sid} | {e}")

        if not price_rows:
            return pd.DataFrame(), pd.DataFrame()

        price_df = pd.concat(price_rows, ignore_index=True)
        signal_df = pd.concat(sig_rows, ignore_index=True)
        if self.selection_cfg.get("sector_cap_enabled", False):
            signal_df = self._apply_sector_cap(signal_df)
        logger.info(f"歷史訊號完成：{len(price_df)} 列價格，"
                    f"{int(signal_df['entry_signal'].sum())} 個進場訊號")
        return price_df, signal_df

    def _apply_sector_cap(self, signal_df: pd.DataFrame) -> pd.DataFrame:
        """
        A2：同類股同時進場上限。每個交易日在「當日 entry=True」的標的中，
        同一類股(get_sector)只保留 score(籌碼分) 最高的前 max_per_sector 檔，其餘 entry 轉 False。
        降低 3 檔全同產業齊跌的系統性回撤。無前視（只用當日已知的 entry/score）。
        """
        cap = int(self.selection_cfg.get("max_per_sector", 2))
        before = int(signal_df["entry_signal"].sum())
        sd = signal_df.copy()
        sd["_sector"] = sd["stock_id"].map(get_sector)
        ent = sd[sd["entry_signal"]].copy()
        # 同 (date, sector) 內按 score 降序；同分以 stock_id 穩定排序 → cumcount 取名次
        ent = ent.sort_values(["date", "_sector", "score", "stock_id"],
                              ascending=[True, True, False, True])
        ent["_rank"] = ent.groupby(["date", "_sector"]).cumcount() + 1
        drop_idx = ent.index[ent["_rank"] > cap]
        sd.loc[drop_idx, "entry_signal"] = False
        sd = sd.drop(columns=["_sector"])
        after = int(sd["entry_signal"].sum())
        logger.info(f"A2 類股分散（同群上限 {cap}）：進場訊號 {before} → {after}"
                    f"（砍 {before - after} 個過度集中）")
        return sd

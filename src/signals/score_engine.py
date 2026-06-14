"""
signals/score_engine.py
整合評分器：串接 TA 初篩 + 籌碼評分
這是兩層選股邏輯的核心連接點
"""
import pandas as pd
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger
from src.data.fetcher import FinMindFetcher
from src.data.universe import get_stock_ids
from src.signals.tech_signal import TechSignal
from src.signals.chip_signal import ChipAnalyzer, MarginAnalyzer
from src.utils.helpers import (load_config, load_settings, get_prev_trading_day,
                               atr_trailing_pct, vol_position_pct)


class ScoreEngine:
    """
    每日選股主流程：
    1. 批次掃描全市場 → TA 初篩候選池
    2. 對候選池計算籌碼評分
    3. 輸出最終候選清單（含分數與進場理由）
    """

    def __init__(self):
        self.fetcher = FinMindFetcher()
        self.tech = TechSignal()
        self.chip = ChipAnalyzer()
        self.margin = MarginAnalyzer()
        self.min_score = load_config()["chip_scoring"]["min_score"]
        self.min_turnover = load_config().get("trading", {}).get("min_liquidity_turnover", 0)
        self.last_regime = ""   # 當日 regime 決策標籤（供 EOD 歸檔記錄）

    def _market_risk_on(self) -> bool:
        """
        大盤趨勢濾鏡（與回測 HistoricalSignalBuilder 同口徑）：
        capitulation.enabled → 採投降感知 block_only（擋熊市假反彈，救2022）；
        否則退回舊版「代理(0050)站上 N 日均線」。未啟用/資料不足 → 預設允許。
        """
        cap_cfg = load_config().get("capitulation", {"enabled": False})
        if cap_cfg.get("enabled", False):
            return self._capitulation_risk_on(cap_cfg)
        cfg = load_config().get("regime", {"enabled": False})
        if not cfg.get("enabled", False):
            return True
        proxy = cfg.get("proxy", "0050")
        n = cfg.get("ma_period", 60)
        sd = int(cfg.get("ma_slope_days", 10))
        start = (date.today() - pd.Timedelta(days=n * 2 + sd + 30)).isoformat()
        px = self.fetcher.get_daily_price(proxy, start)
        if px.empty or len(px) < n:
            logger.warning(f"regime 代理 {proxy} 資料不足，預設允許進場")
            return True
        ma_series = px.set_index("date")["close"].rolling(n).mean()
        last = float(px["close"].iloc[-1])
        ma = float(ma_series.iloc[-1])
        risk_on = last > ma
        slope_up = True
        if cfg.get("require_ma_slope", False) and len(ma_series) > sd:  # 快修：MA60 向上才算多頭
            ma_then = float(ma_series.iloc[-1 - sd])
            slope_up = ma > ma_then
            risk_on = risk_on and slope_up
        logger.info(f"大盤 regime：{proxy} {last:.1f} vs MA{n} {ma:.1f}"
                    f"{'，MA60斜率' + ('↑' if slope_up else '↓') if cfg.get('require_ma_slope') else ''}"
                    f" → {'多頭(可進場)' if risk_on else '空頭(不進場)'}")
        self.last_regime = f"ma60:{'多頭' if risk_on else '空頭'}"
        return risk_on

    def _capitulation_risk_on(self, cap_cfg: dict) -> bool:
        """投降感知 regime（live，採 block_only）：站上 MA60 但 MA60 下彎且仍深處熊市(false_rebound)
        → 擋掉（熊市假反彈，救 2022）。只依賴 0050（不需 panel/籌碼）→ 與回測 regime_0050 同口徑。
        早解鎖/full 已否決且需 panel → live 一律 block_only。資料不足 → 預設允許。"""
        from src.signals.capitulation import CapitulationClassifier
        reg = load_config().get("regime", {})
        proxy = reg.get("proxy", "0050")
        n = int(reg.get("ma_period", 60))
        # dd252 需 ≥252 交易日 + MA60/slope → 抓約 560 日曆日
        start = (date.today() - pd.Timedelta(days=560)).isoformat()
        px = self.fetcher.get_daily_price(proxy, start)
        if px.empty or len(px) < n:
            # #9 fail-closed：無法確認 regime → 寧可不進場（熊市防禦策略「存疑即出場外」）
            logger.warning(f"投降感知 regime 代理 {proxy} 資料不足/抓取失敗 → fail-closed 今日不進場")
            return False
        mode = str(cap_cfg.get("allow_mode", "block_only")).lower()
        if mode != "block_only":
            logger.warning(f"capitulation.allow_mode={mode} 在 live 僅支援 block_only"
                           f"（早解鎖需 panel 且已否決）→ 改用 block_only")
        r0 = CapitulationClassifier.regime_0050(px.set_index("date")["close"], cap_cfg, n)
        row = r0.iloc[-1]
        allow = bool(row["allow_block_only"])
        last_close, ma = float(px["close"].iloc[-1]), float(row["ma"])
        label = ("空頭(不進場)" if not bool(row["above_ma60"]) else
                 ("假反彈擋下(不進場)" if bool(row["false_rebound_0050"]) else "多頭(可進場)"))
        logger.info(f"投降感知 regime(block_only)：{proxy} {last_close:.1f} vs MA{n} {ma:.1f}"
                    f"{'，MA60↓' if bool(row['ma60_falling']) else ''}"
                    f"{'，深熊' if bool(row['precond_deep']) else ''} → {label}")
        self.last_regime = f"block_only:{label}"
        return allow

    # ────────────────────────────────────────────
    # Phase 1：TA 初篩
    # ────────────────────────────────────────────

    def _resolve_universe(self) -> list[str]:
        """
        決定 live 每日掃描範圍（config universe）。
        免費 FinMind 600 req/日：全市場(~1980檔)會爆額度 → 預設只掃 watchlist。
        full 模式截斷到 max_scan 以保護額度（需付費 FinMind 才宜全掃）。
        """
        cfg = load_config().get("universe", {})
        mode = str(cfg.get("mode", "watchlist")).lower()
        if mode == "watchlist":
            wl = [str(s) for s in (cfg.get("watchlist") or [])]
            if wl:
                logger.info(f"選股範圍：watchlist {len(wl)} 檔（免費 FinMind 額度友善）")
                return wl
            logger.warning("watchlist 空 → 回退全市場")
        ids = get_stock_ids()
        cap = int(cfg.get("max_scan", 0) or 0)
        if cap and len(ids) > cap:
            logger.warning(f"full 模式：{len(ids)} 檔超過上限 {cap} → 截斷（保護 FinMind 免費 600/日）。"
                           f"要全掃請用付費 FinMind 或改 watchlist。")
            ids = ids[:cap]
        return ids

    def _scan_one(self, sid: str, start_date: str) -> dict | None:
        """單檔 TA 掃描（供平行化）。Q2優化：adjust=False 省除權息請求；
        通過者順手用同一份日線算 ATR 移動停損寬度(trail_pct)，免 market_open 熱路徑再抓一次。"""
        df = self.fetcher.get_daily_price(sid, start_date, adjust=False)  # B：省一次 API 請求
        if df.empty:
            return None
        # 流動性濾網：整股20日均成交額未達門檻 → 零股難成交，跳過
        if self.min_turnover > 0:
            if float((df["close"] * df["volume"]).tail(20).mean()) < self.min_turnover:
                return None
        result = self.tech.scan_single(df, sid)
        if result:
            # #2：ATR/配重改用「還原價」計（與回測對齊）。只對通過 TA 的少數檔多抓一次除權息還原；
            #     價格本身已快取(adjust 不入 cache key)，僅 +1 除權息請求 → 38檔掃描速度不受影響。
            adj = self.fetcher.get_daily_price(sid, start_date, adjust=True)
            base = adj if not adj.empty else df
            result["trail_pct"] = atr_trailing_pct(base)   # A1：進場 ATR 停損寬度（fixed 模式回 None）
            result["size_pct"] = vol_position_pct(base)    # 方式A：反波動部位配重（flat 模式回 base）
        return result

    def run_ta_scan(self, stock_ids: list[str] = None,
                    lookback_days: int = 120) -> list[dict]:
        """
        批次掃描股票池，找出符合 TA 條件的候選（平行抓 FinMind 降延遲）。
        lookback_days: 抓取多少天的歷史資料（計算均線需要足夠天數）
        """
        if stock_ids is None:
            stock_ids = self._resolve_universe()

        start_date = (date.today() - pd.Timedelta(days=lookback_days)).isoformat()
        workers = int(load_settings()["data"].get("scan_workers", 6))
        total = len(stock_ids)
        logger.info(f"TA 掃描開始：{total} 檔，起始日 {start_date}，並發 {workers}")

        candidates = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(self._scan_one, sid, start_date): sid for sid in stock_ids}
            for fut in as_completed(futs):
                sid = futs[fut]
                try:
                    r = fut.result()
                    if r:
                        candidates.append(r)
                except Exception as e:
                    logger.warning(f"TA 掃描失敗 | {sid} | {e}")

        logger.info(f"TA 初篩完成：{len(candidates)}/{total} 檔通過")
        return candidates

    # ────────────────────────────────────────────
    # Phase 2：籌碼評分
    # ────────────────────────────────────────────

    def run_chip_scoring(self, ta_candidates: list[dict],
                         lookback_days: int = 30) -> pd.DataFrame:
        """
        對 TA 候選池批次計算籌碼評分
        法人資料用前一個交易日（T+1 規則）
        """
        as_of_date = pd.Timestamp(get_prev_trading_day())
        start_date = (as_of_date - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        results = []

        logger.info(f"籌碼評分開始：{len(ta_candidates)} 檔候選，基準日 {as_of_date.date()}")

        for item in ta_candidates:
            sid = item["stock_id"]
            try:
                # 抓法人 & 融資資料
                df_inst = self.fetcher.get_institutional(sid, start_date)
                df_margin = self.fetcher.get_margin(sid, start_date)

                # 各項評分
                foreign_score = self.chip.calc_foreign_score(df_inst, as_of_date)
                trust_score = self.chip.calc_trust_score(df_inst, as_of_date)
                margin_score = self.margin.calc_margin_score(df_margin, as_of_date)
                short_penalty = self.margin.calc_short_penalty(df_margin, as_of_date)

                total_score = foreign_score + trust_score + margin_score + short_penalty

                results.append({
                    **item,
                    "foreign_score": foreign_score,
                    "trust_score": trust_score,
                    "margin_score": margin_score,
                    "short_penalty": short_penalty,
                    "chip_score": total_score,
                    "foreign_net": self.chip.get_foreign_net(df_inst, as_of_date),
                })

            except Exception as e:
                logger.warning(f"籌碼評分失敗 | {sid} | {e}")

        df = pd.DataFrame(results)
        if df.empty:
            logger.warning("籌碼評分：無結果")
            return df

        # 按綜合分排序
        df = df.sort_values("chip_score", ascending=False).reset_index(drop=True)
        logger.info(
            f"籌碼評分完成：{len(df)} 檔，其中 {(df['chip_score'] >= self.min_score).sum()} 檔達門檻"
        )
        return df

    # ────────────────────────────────────────────
    # 主入口：產生每日候選清單
    # ────────────────────────────────────────────

    def run(self, stock_ids: list[str] = None) -> pd.DataFrame:
        """
        執行完整選股流程
        回傳 DataFrame：每列一檔股票，含 TA 指標、籌碼分數、進場理由
        """
        # Step 0: 大盤 regime 濾鏡（空頭直接不進場，省去全市場掃描）
        if not self._market_risk_on():
            logger.info("大盤 regime 空頭，今日不選股/不進場")
            return pd.DataFrame()

        # Step 1: TA 初篩
        ta_candidates = self.run_ta_scan(stock_ids)

        if not ta_candidates:
            logger.warning("TA 初篩無結果，今日無候選標的")
            return pd.DataFrame()

        # Step 2: 籌碼評分
        df_scored = self.run_chip_scoring(ta_candidates)

        if df_scored.empty:
            return pd.DataFrame()

        # Step 3: 篩選達門檻（chip_score >= min_score）
        df_final = df_scored[df_scored["chip_score"] >= self.min_score].copy()

        # 產生進場理由說明（供 Telegram 通知用）
        df_final["reason"] = df_final.apply(self._build_reason, axis=1)

        logger.info(f"今日最終候選：{len(df_final)} 檔")
        return df_final

    def _build_reason(self, row: pd.Series) -> str:
        """組合人類可讀的進場理由"""
        parts = []
        if row["cond_above_ma"]:
            parts.append(f"站上MA20({row['ma20']:.1f})")
        if row["cond_vol_surge"]:
            parts.append(f"量比{row['vol_ratio']:.1f}x")
        if row[f"rsi14"] is not None:
            parts.append(f"RSI{row['rsi14']:.0f}")
        if row["foreign_score"] > 0:
            parts.append(f"外資買超{row['foreign_net']:.0f}張")
        if row["trust_score"] > 0:
            parts.append("投信買超")
        if row["margin_score"] > 0:
            parts.append("融資乾淨")
        return " | ".join(parts)

    def save_candidates(self, df: pd.DataFrame,
                        path: str = "data/processed/candidates_{date}.csv") -> str:
        """儲存候選清單到本地（回測與日誌用）"""
        import os
        today = date.today().isoformat()
        filepath = path.format(date=today)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        logger.info(f"候選清單已儲存：{filepath}")
        return filepath

"""
signals/capitulation.py
投降感知 regime 分類器（真底 vs 假反彈）。

設計依據：4 篇 quant paper（大底 nowcasting / 融資-流動性非線性螺旋 / breadth washout /
外資正回饋）+ 本地實測（vol20 +0.33 最強、dist_ma60/dd 次強、外資單獨 -0.06 無效）。

核心命題（paper 第10節）：
    真底 = forced-liquidity + breadth-washout regime FIRST，再由短期價格反轉確認，
    不是「收復 MA60 / 均線轉多」這種滯後價格確認。

四大壓力塊（每塊 raw → 因果滾動百分位/分位/z → gate 布林；全部無前視，只用 T 含以前）：
  A panic_liquidity (0050)  : 已實現波動 + Amihud 非流動性百分位（最強）
  B breadth_washout (38檔)  : close<MA60 比例 + 3日均下跌家數比（用 MA60 廣度，MA20 是反指）
  C margin_stress  (38檔)   : 跨檔平均融資 chg20 的極端低分位（非線性門檻）
  D foreign_flow   (38檔)   : 外資淨賣 z（只能 co-confirm，永不單獨成立）

三選 2/3 布林（保守版，論文 §8）：
    true_bottom = deep AND margin AND breadth AND (panic OR foreign)
    false_rebound = 收復MA60 AND MA60下彎 AND 深處熊市 AND NOT true_bottom
    → regime ∈ {TRUE_BOTTOM, FALSE_REBOUND, NORMAL_BULL, BEAR}

Tier-1：breadth/margin/foreign 用 watchlist 聚合代理（重用 get_margin/get_institutional，
零 schema 風險、檔案多已快取）；market-total dataset 為未來 Tier-2 live 省 req 的優化。
"""
import numpy as np
import pandas as pd
from loguru import logger
from src.data.fetcher import FinMindFetcher
from src.utils.helpers import load_config


def _causal_pctl(s: pd.Series, window: int, min_periods: int) -> pd.Series:
    """當前值在「過去 window 日（含當日）」中的百分位 rank（0~1，1=當日為區間最大）。
    純因果：每個 T 只用 [T-window+1, T]。NaN 安全（暖身期可能偏噪，事件期已穩定）。"""
    return s.rolling(window, min_periods=min_periods).apply(
        lambda a: float(np.mean(a <= a[-1])), raw=True)


class CapitulationClassifier:
    """市場級每日 regime 分類器；回測與 live 共用單一真相源。"""

    def __init__(self, cfg: dict = None, universe: list[str] = None):
        full = load_config()
        self.cfg = cfg if cfg is not None else full.get("capitulation", {})
        self.regime_cfg = full.get("regime", {})
        self.proxy = self.regime_cfg.get("proxy", "0050")
        self.ma_n = int(self.regime_cfg.get("ma_period", 60))
        if universe is None:
            src = str(self.cfg.get("universe_source", "watchlist")).lower()
            if src == "fixed":
                # 釘選 regime 測量基準：watchlist 擴充（AI 強勢股加單）時，
                # 廣度/融資/外資聚合代理仍用「事件驗證時的固定清單」，閾值不漂移
                universe = [str(s) for s in self.cfg.get("universe_list", [])]
            else:
                universe = (full.get("universe", {}).get("watchlist", [])
                            if src == "watchlist" else [])
        self.universe = [str(s) for s in universe]
        self.fetcher = FinMindFetcher()

    # ────────────────────────────────────────────
    def _panel(self, start: str, end: str):
        """抓 universe 的 close/volume/融資餘額/外資淨額，組成寬表（date × stock）。"""
        closes, vols, margins, foreigns = {}, {}, {}, {}
        for sid in self.universe:
            try:
                px = self.fetcher.get_daily_price(sid, start, end)  # 還原
                if not px.empty:
                    px = px.set_index("date")
                    closes[sid] = px["close"].astype(float)
                    vols[sid] = px["volume"].astype(float)
                mg = self.fetcher.get_margin(sid, start, end)
                if not mg.empty and "MarginPurchaseTodayBalance" in mg.columns:
                    margins[sid] = mg.set_index("date")["MarginPurchaseTodayBalance"].astype(float)
                inst = self.fetcher.get_institutional(sid, start, end)
                if not inst.empty and "diff" in inst.columns:
                    f = inst[inst["name"] == "Foreign_Investor"].set_index("date")["diff"].astype(float)
                    foreigns[sid] = f[~f.index.duplicated()]
            except Exception as e:
                logger.warning(f"capitulation panel 失敗 | {sid} | {e}")
        close = pd.DataFrame(closes).sort_index()
        vol = pd.DataFrame(vols).sort_index()
        margin = pd.DataFrame(margins).sort_index()
        foreign = pd.DataFrame(foreigns).sort_index()
        return close, vol, margin, foreign

    # ────────────────────────────────────────────
    def compute(self, start: str, end: str = None) -> pd.DataFrame:
        """回傳 index=date 的 regime 診斷表（含所有 raw、gate、三態標籤）。無前視。"""
        c = self.cfg
        win = int(c.get("pct_window", 756))
        mp = int(c.get("pct_min_periods", 252))

        # ── 市場代理 0050：panic + depth + base regime ──
        px0 = self.fetcher.get_daily_price(self.proxy, start, end)
        if px0.empty:
            logger.warning("capitulation：proxy 無資料")
            return pd.DataFrame()
        m = px0.set_index("date")[["close", "volume"]].astype(float)
        idx = m.index
        ret0 = m["close"].pct_change(fill_method=None)

        # Block A：恐慌/流動性
        vol20 = ret0.rolling(20).std()
        turnover = (m["close"] * m["volume"]).replace(0, np.nan)
        amihud20 = (ret0.abs() / turnover).rolling(20).mean()
        vol_pctl = _causal_pctl(vol20, win, mp)
        amihud_pctl = _causal_pctl(amihud20, win, mp)
        # ⚠️ 實證修正：Amihud 在指數級爆量崩盤時反而「低」（|ret|/成交額，分母爆量）→ 不可當投降。
        #    已實現波動百分位(vol_pctl) 單獨即乾淨標出 4 個真底(0.86~1.0)、且假反彈低(2022/08 0.4~0.6)。
        #    panic_use_amihud=false（預設）：panic = 只看 vol_pctl。amihud_pctl 僅留診斷。
        gate_panic = vol_pctl >= c.get("panic_vol_pctl", 0.85)
        if bool(c.get("panic_use_amihud", False)):
            gate_panic = gate_panic & (amihud_pctl >= c.get("panic_amihud_pctl", 0.80))

        # 深度 + base regime（MA60）：抽到 regime_0050（與 live 共用單一真相源）
        r0 = self.regime_0050(m["close"], c, self.ma_n)
        dd_long = r0["dd252"]
        precond_deep = r0["precond_deep"]
        ma = r0["ma"]
        above_ma = r0["above_ma60"]
        ma_falling = r0["ma60_falling"]

        # ── universe 聚合：breadth + margin + foreign ──
        close, vol, margin, foreign = self._panel(start, end)
        close = close.reindex(idx)

        # Block B：廣度 washout（MA60）
        ma60u = close.rolling(self.ma_n).mean()
        below = close.lt(ma60u).where(ma60u.notna())
        pct_below = below.mean(axis=1)
        r = close.pct_change(fill_method=None)
        adv = (r > 0).sum(axis=1)
        dec = (r < 0).sum(axis=1)
        tot = (adv + dec).replace(0, np.nan)
        decline_3dma = (dec / tot).rolling(3).mean()
        gate_breadth = (pct_below >= c.get("breadth_below_ma60", 0.75)) | \
                       (decline_3dma >= c.get("breadth_decline_3dma", 0.65))

        # Block C：融資斷頭（跨檔平均 chg20，scale-free；非線性極端低分位）
        margin = margin.reindex(idx).ffill()
        mchg20 = (margin / margin.shift(20) - 1).mean(axis=1)
        mchg60 = (margin / margin.shift(60) - 1).mean(axis=1)  # 診斷：慢熊用
        mq = mchg20.rolling(win, min_periods=mp).quantile(c.get("margin_q", 0.05))
        gate_margin = (mchg20 <= mq) | (mchg20 <= c.get("margin_abs", -0.15))

        # Block D：外資順勢賣壓（淨額加總，z；只能 co-confirm）
        foreign = foreign.reindex(idx).fillna(0.0)
        fnet20 = foreign.sum(axis=1).rolling(20).sum()
        sell = -fnet20
        fz = (sell - sell.rolling(win, min_periods=mp).mean()) / sell.rolling(win, min_periods=mp).std()
        gate_foreign = fz >= c.get("foreign_sell_z", 2.0)

        # ── 組合：三選 2/3 布林（保守版）── 純邏輯抽到 combine_regime（可單元測試）
        comb = self.combine_regime(precond_deep, gate_panic, gate_breadth,
                                   gate_margin, gate_foreign, above_ma, ma_falling,
                                   false_rebound_0050=r0["false_rebound_0050"])
        # P3：失敗底市場級出場（投降後破投降低點）
        failed = self.failed_bottom_signal(m["close"], comb["true_bottom"],
                                            int(c.get("failed_window", 40)),
                                            float(c.get("failed_buffer", 0.0)))

        return pd.DataFrame({
            "close": m["close"], "ma60": ma, "dd252": dd_long,
            "vol20": vol20, "vol_pctl": vol_pctl, "amihud_pctl": amihud_pctl,
            "pct_below_ma60": pct_below, "decline_3dma": decline_3dma,
            "margin_chg20": mchg20, "margin_chg60": mchg60, "foreign_z": fz,
            "gate_panic": comb["gate_panic"], "gate_breadth": comb["gate_breadth"],
            "gate_margin": comb["gate_margin"], "gate_foreign": comb["gate_foreign"],
            "n_blocks": comb["n_blocks"], "precond_deep": comb["precond_deep"],
            "above_ma60": comb["above_ma60"], "ma60_falling": comb["ma60_falling"],
            "true_bottom": comb["true_bottom"], "confirmed": comb["confirmed"],
            "alt_3of4": comb["alt_3of4"], "alt_2of4": comb["alt_2of4"],
            "false_rebound": comb["false_rebound"], "allow_entry": comb["allow_entry"],
            "allow_block_only": comb["allow_block_only"],
            "allow_unlock_only": comb["allow_unlock_only"],
            "failed_bottom": failed, "regime": comb["regime"],
        })

    @staticmethod
    def combine_regime(precond_deep, gate_panic, gate_breadth, gate_margin,
                       gate_foreign, above_ma, ma_falling, false_rebound_0050=None) -> pd.DataFrame:
        """純組合邏輯（無 IO，可單元測試）。輸入皆為對齊 index 的布林 Series。

        實證後規則（2016-2025 事件判別校準）：
          - 強塊 = panic(vol百分位) + breadth(MA60 washout)，兩者皆「必要」(+depth)。
            這對乾淨標出 2018/12、2020/03、2022/10、2025/04 四個真底，且擋掉 2022/03(不夠深)、
            2022/08(vol低) 兩個假反彈。對應本地實測 vol20+0.33 / breadth 強。
          - 弱塊 = margin / foreign = 只能「co-confirm」加強信心，不可當必要條件：
            margin 在崩盤當下 20日變化反而為正(斷頭有數週延遲)；foreign 僅 covid 級爆賣才亮。
            → confirmed = true_bottom AND (margin OR foreign)，供加碼/全倉分級用。
          - 鐵律：foreign 永不單獨成立（panic+breadth 必要已保證）。
        """
        gp = gate_panic.fillna(False)
        gb = gate_breadth.fillna(False)
        gm = gate_margin.fillna(False)
        gf = gate_foreign.fillna(False)
        deep = precond_deep.fillna(False)
        above = above_ma.fillna(False)
        falling = ma_falling.fillna(False)
        n_blocks = gp.astype(int) + gb.astype(int) + gm.astype(int) + gf.astype(int)

        true_bottom = deep & gp & gb                 # 主規則：深度 + panic + breadth（兩強塊必要）
        confirmed = true_bottom & (gm | gf)          # 弱塊 co-confirm → 加碼/全倉分級
        alt_3of4 = deep & (n_blocks >= 3)            # 診斷對照
        alt_2of4 = deep & (n_blocks >= 2)            # 診斷對照
        # false_rebound：優先用 regime_0050 算好的（含 reclaim 豁免），確保 live/回測同口徑
        base_fr = (false_rebound_0050.reindex(above.index).fillna(False)
                   if false_rebound_0050 is not None else (above & falling & deep))
        false_rebound = base_fr & (~true_bottom)

        regime = pd.Series(
            np.select([true_bottom.values, false_rebound.values, above.values],
                      ["TRUE_BOTTOM", "FALSE_REBOUND", "NORMAL_BULL"], default="BEAR"),
            index=deep.index)
        # 進場閘門三變體（供分離歸因：早解鎖 vs 擋假反彈 各自效果）：
        allow_entry = true_bottom | (above & ~false_rebound)  # full = 兩者皆做
        allow_block_only = above & ~false_rebound             # 只擋假反彈（不早解鎖）
        allow_unlock_only = true_bottom | above               # 只早解鎖（不擋假反彈）

        return pd.DataFrame({
            "gate_panic": gp, "gate_breadth": gb, "gate_margin": gm, "gate_foreign": gf,
            "n_blocks": n_blocks, "precond_deep": deep, "above_ma60": above,
            "ma60_falling": falling, "true_bottom": true_bottom, "confirmed": confirmed,
            "alt_3of4": alt_3of4, "alt_2of4": alt_2of4, "false_rebound": false_rebound,
            "allow_entry": allow_entry, "allow_block_only": allow_block_only,
            "allow_unlock_only": allow_unlock_only, "regime": regime,
        })

    @staticmethod
    def regime_0050(close: pd.Series, cfg: dict, ma_n: int = 60) -> pd.DataFrame:
        """純 0050 的 regime 子集（above_ma / MA60下彎 / 深度 / false_rebound / allow_block_only）。
        block_only 閘門「只」依賴這些 → live 只需抓 0050（不必 38 檔 panel/籌碼）。
        回測 compute() 也共用此函式 = 單一真相源。無前視。"""
        ma = close.rolling(ma_n).mean()
        above = close > ma
        falling = ma < ma.shift(int(cfg.get("ma60_falling_days", 20)))
        hl = int(cfg.get("deep_high_lookback", 252))
        dd = close / close.rolling(hl, min_periods=120).max() - 1
        deep = dd <= cfg.get("deep_dd", -0.10)
        false_rebound = above & falling & deep
        # task2 精修選項：持續站上 MA60 連 N 日 → 視為「真 recovery 持穩」豁免擋單（救 2019）。
        # N=0 關閉。真假反彈差別=2019收復後『持穩』vs 2022/08收復後『2-3週又破底』。
        exempt_n = int(cfg.get("reclaim_exempt_days", 0))
        if exempt_n > 0:
            sustained = above.rolling(exempt_n).min().fillna(0).astype(bool)
            false_rebound = false_rebound & ~sustained
        allow_block_only = above & ~false_rebound
        return pd.DataFrame({
            "ma": ma, "above_ma60": above, "ma60_falling": falling, "dd252": dd,
            "precond_deep": deep, "false_rebound_0050": false_rebound,
            "allow_block_only": allow_block_only,
        })

    @staticmethod
    def panic_0050(close: pd.Series, cfg: dict, ma_n: int = 60) -> pd.DataFrame:
        """0050-only 急殺/深熊旗標（#3 回測 tighten mask 與 live 風控共用單一真相源；無前視）。
        - gate_panic = 已實現波動(20d) 因果百分位 ≥ panic_vol_pctl（與 compute() 同口徑，純 0050）。
        - deep_bear  = 跌破 MA60 且 距 252 日高 ≤ deep_bear.dd_threshold（確認深熊，比進場 -10% 更深）。
        - tighten    = bearish(跌破 MA60 或 假反彈) 且 (panic 或 深崩)。
          ⚠️ 用 bearish 當閘門很關鍵：牛市健康急回（仍站 MA60 上）不收停損 → 避免 whipsaw（2025 教訓：
          急殺在 V 底附近被掃出）。深熊有墳場（P3/exit_on_risk_off 全程啟用否決），此開關只在確認危險態啟用。"""
        win = int(cfg.get("pct_window", 756))
        mp = int(cfg.get("pct_min_periods", 252))
        ret = close.pct_change(fill_method=None)
        vol20 = ret.rolling(20).std()
        vol_pctl = _causal_pctl(vol20, win, mp)
        gate_panic = (vol_pctl >= cfg.get("panic_vol_pctl", 0.85)).fillna(False)
        r0 = CapitulationClassifier.regime_0050(close, cfg, ma_n)
        above = r0["above_ma60"].fillna(False)
        fr = r0["false_rebound_0050"].fillna(False)
        db = cfg.get("deep_bear", {}) or {}
        dd_thr = float(db.get("dd_threshold", -0.15))
        deep_dd = (r0["dd252"] <= dd_thr).fillna(False)
        deep_bear = (~above) & deep_dd
        bearish = (~above) | fr
        tighten = bearish & (gate_panic | deep_dd)
        return pd.DataFrame({"vol_pctl": vol_pctl, "gate_panic": gate_panic,
                             "deep_bear": deep_bear, "tighten": tighten})

    @staticmethod
    def failed_bottom_signal(close: pd.Series, true_bottom: pd.Series,
                             window: int = 40, buffer: float = 0.0) -> pd.Series:
        """失敗底市場級出場訊號（P3，無前視）。
        邏輯：一次 TRUE_BOTTOM 投降後，記住該投降段的最低收盤(cap_low)；其後 window 交易日內，
        若 0050 收盤「跌破 cap_low(×(1-buffer))」→ 此底失敗 → 全面去風險(force_exit=True)。
        早解鎖(unlock)進場在熊市多腿急殺被套時，靠此快砍(取代寬 ATR 移動停損)。
        真 V 底(2025)不破 cap_low → 不觸發 → 抱住反彈。"""
        c = close.values
        tb = true_bottom.reindex(close.index).fillna(False).values.astype(bool)
        out = np.zeros(len(c), dtype=bool)
        last_tb = -10**9
        cap_low = np.inf
        for i in range(len(c)):
            if tb[i]:                                  # 投降日：更新該段最低收盤
                cap_low = c[i] if (i - last_tb) > window else min(cap_low, c[i])
                last_tb = i
            elif (i - last_tb) <= window:              # 投降後觀察窗內
                if c[i] < cap_low * (1.0 - buffer):    # 跌破投降低點 → 底失敗
                    out[i] = True
        return pd.Series(out, index=close.index)

    # ────────────────────────────────────────────
    def latest_regime(self, lookback_days: int = 1100) -> dict:
        """live 用：算到最新一天的 regime 標籤 + 診斷（單列 dict）。資料不足回 NORMAL_BULL 放行。"""
        from datetime import date
        start = (date.today() - pd.Timedelta(days=lookback_days)).isoformat()
        df = self.compute(start)
        if df.empty:
            return {"regime": "NORMAL_BULL", "allow_entry": True}
        return df.iloc[-1].to_dict()

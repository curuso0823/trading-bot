"""
backtest/backtester.py
Vectorbt 台股回測框架
正確處理：交易成本、漲跌停、T+1 延遲、Walk-forward 分析
"""
import pandas as pd
import numpy as np
from loguru import logger
from src.utils.helpers import load_config


class TaiwanBacktester:
    """
    台股回測框架
    重要：所有訊號以「收盤後確認，隔日開盤進場」為準（T+1 執行）
    """

    def __init__(self):
        cfg = load_config()
        self.cost_cfg = cfg["cost"]
        self.exit_cfg = cfg["exit"]
        self.entry_cfg = cfg["entry"]
        self.ta_cfg = cfg["ta_filter"]
        self.bt_cfg = cfg["backtest"]
        self.gate_cfg = cfg["performance_gate"]
        self.trading_cfg = cfg.get("trading", {})
        self.sizing_cfg = cfg.get("sizing", {})

    def run(self, price_df: pd.DataFrame, signal_df: pd.DataFrame,
            initial_capital: float = None) -> dict:
        """
        執行回測
        price_df: 含 date, open, high, low, close, volume 的 DataFrame
        signal_df: 含 date, stock_id, entry_signal(bool) 的 DataFrame
        回傳: {'stats': dict, 'portfolio': vbt.Portfolio, 'trades': pd.DataFrame}
        """
        try:
            import vectorbt as vbt
        except ImportError:
            logger.error("vectorbt 未安裝：pip install vectorbt")
            return {}

        if initial_capital is None:
            initial_capital = self.bt_cfg["initial_capital"]

        # --- 價格面板：close 供估值/停損停利判斷，open 供「隔日開盤」執行 ---
        # 跨多檔 pivot 後，停牌/上市日不同會產生 NaN。ffill 填內部缺口、bfill 填前置（上市前）缺口，
        # 確保面板無 NaN（前置/停牌區段訊號本為 False，bfill 的平盤價不會產生假交易）。
        close_px = price_df.pivot(index="date", columns="stock_id", values="close").sort_index().ffill().bfill()
        open_px = price_df.pivot(index="date", columns="stock_id", values="open").reindex_like(close_px).ffill().bfill()
        high_px = price_df.pivot(index="date", columns="stock_id", values="high").reindex_like(close_px).ffill().bfill()
        low_px = price_df.pivot(index="date", columns="stock_id", values="low").reindex_like(close_px).ffill().bfill()

        # --- 進場訊號：T 日確認 → T+1 開盤執行（shift 1）---
        entries = (
            signal_df.pivot(index="date", columns="stock_id", values="entry_signal")
            .reindex(index=close_px.index, columns=close_px.columns)
            .fillna(False).astype(bool)
            .shift(1).fillna(False).astype(bool)
        )

        # --- 出場訊號：跌破 MA20 / 持有上限（停損停利交給 from_signals 的 sl_stop/tp_stop）---
        exits = self._build_exit_signals(close_px, entries)

        # 大盤 regime 出場：轉弱日強制出清所有部位（決策當日 → 隔日執行，shift 1 避免前視）
        if "force_exit" in signal_df.columns:
            fe = (signal_df.pivot(index="date", columns="stock_id", values="force_exit")
                  .reindex(index=close_px.index, columns=close_px.columns)
                  .fillna(False).astype(bool).shift(1).fillna(False).astype(bool))
            exits = exits | fe

        # --- 台股交易成本 ---
        # vectorbt 的 fees 是「單邊單一費率」（非 buy/sell dict）。台股來回成本 =
        # 買手續費 + 賣手續費 + 證交稅，平均到單邊，使來回總成本正確（單邊歸屬為近似）。
        round_trip = (self.cost_cfg["buy_fee_rate"]
                      + self.cost_cfg["sell_fee_rate"]
                      + self.cost_cfg["sell_tax_rate"])
        fee_per_side = round_trip / 2

        # 停損模式：移動停損(sl_trail，自高點回落) 或 固定初始停損
        # A1：移動停損寬度可固定(trailing_stop_pct) 或 ATR 自適應(隨個股波動)
        # #5 註記：live 為零股 T+1（當日進場不可當日賣，停損最快 T+1 執行）；vectorbt sl_trail
        #   理論上可同根(進場日)觸發出場 → 模型略寬鬆。但移動停損寬 ~9%，需進場當日自峰值回落 9%
        #   才會同日出場，極罕見；下方回測會量化同日出場筆數確認其不重大。
        use_trailing = self.exit_cfg.get("use_trailing", False)
        sl = (self._trailing_stop(close_px, high_px, low_px) if use_trailing
              else abs(self.exit_cfg["stop_loss_pct"]))
        tp = self.exit_cfg.get("take_profit_pct")

        # 滑價：hybrid → per-stock（整股買得起=低滑價 / 高價只能零股=高滑價）
        slip = self._slippage_per_stock(close_px, initial_capital)

        # 部位規模：flat(固定%) 或 vol_target(波動度反比配重 × 市場波動曝險縮放)
        size = self._position_size(close_px, signal_df)

        fs_kwargs = dict(
            close=close_px, entries=entries, exits=exits,
            price=open_px,                                  # 隔日開盤價執行（較保守）
            sl_stop=sl,
            init_cash=initial_capital,
            fees=fee_per_side,
            slippage=slip,
            size=size,                                      # 純量(flat) 或 per-stock×per-time 矩陣
            size_type="percent",
            cash_sharing=True,                              # 共用資金池
            call_seq="auto",
            freq="1D",
        )
        if use_trailing:
            fs_kwargs["sl_trail"] = True                    # 移動停損：自波段高點回落 sl_stop% 出場
        if tp:                                              # 趨勢模式 take_profit=None → 不設上限
            fs_kwargs["tp_stop"] = tp

        # --- 執行回測 ---
        portfolio = vbt.Portfolio.from_signals(**fs_kwargs)

        return {
            "stats": self._extract_stats(portfolio),
            "portfolio": portfolio,
            "trades": portfolio.trades.records_readable,
        }

    def _trailing_stop(self, close_px: pd.DataFrame, high_px: pd.DataFrame,
                       low_px: pd.DataFrame):
        """
        A1：移動停損寬度。
          trailing_mode=fixed → 純量 trailing_stop_pct（= 原本固定 12% 行為）
          trailing_mode=atr   → per-stock×per-time：trail = clip(atr_mult × ATR%, min, max)
              波動大的股給更寬停損(少被洗)、波動小的收緊。ATR% = ATR/close（Wilder TR 的 rolling 均）。
        無前視：以「當日及以前」資訊算後 shift(1)，對齊 entries 的 T+1 進場（停損寬度於進場時定）。
        """
        fixed = float(self.exit_cfg.get("trailing_stop_pct", 0.12))
        mode = str(self.exit_cfg.get("trailing_mode", "fixed")).lower()
        if mode != "atr":
            return fixed

        n = int(self.exit_cfg.get("atr_period", 14))
        k = float(self.exit_cfg.get("atr_mult", 4.5))
        lo = float(self.exit_cfg.get("atr_trail_min", 0.08))
        hi = float(self.exit_cfg.get("atr_trail_max", 0.18))

        prev_close = close_px.shift(1)
        tr = np.maximum.reduce([
            (high_px - low_px).values,
            (high_px - prev_close).abs().values,
            (low_px - prev_close).abs().values,
        ])
        tr = pd.DataFrame(tr, index=close_px.index, columns=close_px.columns)
        atr_pct = tr.rolling(n).mean() / close_px
        trail = (k * atr_pct).clip(lower=lo, upper=hi)
        logger.info(f"ATR 自適應停損啟用｜period={n} mult={k} 區間[{lo:.0%},{hi:.0%}]｜"
                    f"trail 中位={float(trail.stack().median()):.3f}")
        return trail.shift(1).fillna(fixed)

    def _position_size(self, close_px: pd.DataFrame, signal_df: pd.DataFrame):
        """
        回傳給 vectorbt 的 size：
          method=flat       → 純量 position_size_pct（= 原本固定 30% 行為）
          method=vol_target → per-stock×per-time 配重矩陣：
              個股配重 size_i,t = clip(base × target_vol / sigma_i,t, min, max)  ← 波動低放大、高縮小
              再乘市場曝險縮放 exposure_scalar_t（0050 波動越高越降，來自 signal_df）
        無前視：矩陣以「當日及以前」資訊計算後 shift(1)，對齊 entries 的 T+1 開盤執行。
        """
        base = float(self.entry_cfg["position_size_pct"])
        method = str(self.sizing_cfg.get("method", "flat")).lower()
        if method != "vol_target":
            return base

        s = self.sizing_cfg
        lb = int(s.get("vol_lookback", 20))
        tgt = float(s.get("target_vol_daily", 0.02))
        lo = float(s.get("min_position_pct", 0.10))
        hi = float(s.get("max_position_pct", base))

        # 個股日報酬波動（rolling std）。vol->0(停牌/前置平盤段) 會使倍率爆量 → 由 clip 上限約束；
        # 該段 entries 皆 False 不影響結果。vol->NaN(回看不足) 之後以 base 補。
        vol = close_px.pct_change().rolling(lb).std()
        size = (base * tgt / vol).clip(lower=lo, upper=hi)

        # 市場波動曝險縮放（每日同一純量，由 signal_df.exposure_scalar 帶入）
        if s.get("market_vol_scaling", False) and "exposure_scalar" in signal_df.columns:
            exp = (signal_df.groupby("date")["exposure_scalar"].first()
                   .reindex(close_px.index).ffill().bfill().fillna(1.0))
            size = size.mul(exp, axis=0).clip(lower=0.0, upper=hi)
            logger.info(f"vol_target 配重啟用｜target_vol={tgt}, 配重[{lo:.0%},{hi:.0%}]｜"
                        f"市場曝險縮放 mean={float(exp.mean()):.2f} min={float(exp.min()):.2f}")
        else:
            logger.info(f"vol_target 配重啟用（無市場曝險縮放）｜target_vol={tgt}, 配重[{lo:.0%},{hi:.0%}]")

        # 無前視：對齊 entries 的 shift(1)；前置缺值以 base 補（該段 entries 多為 False）
        return size.shift(1).fillna(base)

    def _slippage_per_stock(self, close_px: pd.DataFrame, initial_capital: float):
        """
        per-stock 滑價：
          odd_lot   → 全部用零股滑價（= live 實況：5-7萬全走零股；與實盤對齊）
          round_lot → 全部用整股滑價
          hybrid    → 整股買得起(1張≤單檔預算)→低滑價，高價只能零股→高滑價
        """
        mode = str(self.trading_cfg.get("mode", "round_lot")).lower()
        if mode == "odd_lot":
            return self.trading_cfg.get("odd_lot_slippage", 0.0015)
        if mode == "round_lot":
            return self.trading_cfg.get("round_lot_slippage", 0.001)
        if mode != "hybrid":
            return self.trading_cfg.get("slippage", 0.001)
        budget = initial_capital * self.entry_cfg["position_size_pct"]
        rslip = self.trading_cfg.get("round_lot_slippage", 0.001)
        oslip = self.trading_cfg.get("odd_lot_slippage", 0.004)
        rep = close_px.median()  # 各檔期間代表價（中位數）
        slip = rep.apply(lambda p: rslip if (p * 1000 <= budget) else oslip)
        n_odd = int((slip == oslip).sum())
        logger.info(f"hybrid 計價：整股(低滑價){len(rep) - n_odd} 檔 / "
                    f"零股(高滑價){n_odd} 檔，單檔預算 {budget:,.0f}")
        return slip.reindex(close_px.columns).fillna(oslip).values

    def _build_exit_signals(self, close_px: pd.DataFrame,
                            entries: pd.DataFrame) -> pd.DataFrame:
        """
        出場訊號矩陣：跌破 MA20 + 持有天數上限。
        （停損 -5% / 停利 +10% 由 from_signals 的 sl_stop/tp_stop 內建處理）
        """
        exits = pd.DataFrame(False, index=close_px.index, columns=close_px.columns)

        # 跌破 MA20 出場
        if self.exit_cfg.get("ma_break_exit", True):
            ma = close_px.rolling(self.ta_cfg["ma_period"]).mean()
            exits = exits | (close_px < ma)

        # 持有天數上限：進場後 max_hold 根交易日強制出場
        max_hold = self.exit_cfg.get("max_hold_days")
        if max_hold:
            exits = exits | entries.shift(max_hold).fillna(False).astype(bool)

        return exits.reindex(index=entries.index, columns=entries.columns).fillna(False).astype(bool)

    def run_walk_forward(self, price_df: pd.DataFrame,
                         signal_df: pd.DataFrame) -> dict:
        """
        Walk-forward 分析
        In-sample: 2019–2022（調參）
        Out-of-sample: 2023–2024（驗證，不能再動參數）
        """
        insample_end = pd.Timestamp(self.bt_cfg["insample_end"])
        outsample_end = pd.Timestamp(self.bt_cfg["outsample_end"])

        # In-sample 回測
        price_in = price_df[price_df["date"] <= insample_end]
        signal_in = signal_df[signal_df["date"] <= insample_end]
        result_in = self.run(price_in, signal_in)

        # Out-of-sample 回測（參數鎖定，禁止調整）
        price_out = price_df[
            (price_df["date"] > insample_end) & (price_df["date"] <= outsample_end)
        ]
        signal_out = signal_df[
            (signal_df["date"] > insample_end) & (signal_df["date"] <= outsample_end)
        ]
        result_out = self.run(price_out, signal_out)

        return {
            "insample": result_in,
            "outsample": result_out,
            "gate_pass": self._check_gate(result_out.get("stats", {})),
        }

    def _extract_stats(self, portfolio) -> dict:
        """提取關鍵績效數字"""
        try:
            stats = portfolio.stats()
            total_return = float(stats.get("Total Return [%]", 0)) / 100
            # vectorbt 1.0 的 stats() 無 "Annualized Return [%]"，由總報酬與期間自算
            period = stats.get("Period")
            days = period.days if hasattr(period, "days") else 0
            annual_return = (1 + total_return) ** (365.0 / days) - 1 if days > 0 else 0.0
            return {
                "total_return": total_return,
                "annual_return": annual_return,
                "sharpe_ratio": float(stats.get("Sharpe Ratio", 0)),
                # vectorbt 回正值；Gate 以負值門檻比較，統一存成負值
                "max_drawdown": -abs(float(stats.get("Max Drawdown [%]", 0)) / 100),
                "win_rate": float(stats.get("Win Rate [%]", 0)) / 100,
                "total_trades": int(stats.get("Total Trades", 0)),
                "profit_factor": float(stats.get("Profit Factor", 0)),
            }
        except Exception as e:
            logger.error(f"績效統計失敗：{e}")
            return {}

    def _check_gate(self, stats: dict) -> dict:
        """
        檢查是否通過 Phase 3 Gate 條件
        回傳各條件的通過狀態
        """
        gate = self.gate_cfg
        checks = {
            "sharpe_ok": stats.get("sharpe_ratio", 0) >= gate["min_sharpe"],
            "drawdown_ok": stats.get("max_drawdown", -999) >= gate["max_drawdown"],
            "return_ok": stats.get("annual_return", 0) >= gate["min_annual_return"],
            "trades_ok": stats.get("total_trades", 0) >= gate["min_trades"],
        }
        checks["all_pass"] = all(checks.values())
        return checks

    def generate_report(self, result: dict, benchmark_df: pd.DataFrame = None) -> None:
        """
        用 quantstats 產出完整績效報告
        benchmark_df: 大盤加權指數（用於計算 alpha）
        """
        try:
            import quantstats as qs
            portfolio = result.get("portfolio")
            if portfolio is None:
                return

            returns = portfolio.returns()

            if benchmark_df is not None:
                benchmark_returns = benchmark_df["close"].pct_change().dropna()
                qs.reports.html(
                    returns,
                    benchmark=benchmark_returns,
                    output="data/processed/backtest_report.html",
                    title="Taiwan Stock Bot — 混合策略回測報告",
                )
            else:
                qs.reports.html(
                    returns,
                    output="data/processed/backtest_report.html",
                    title="Taiwan Stock Bot — 混合策略回測報告",
                )

            logger.info("績效報告已產出：data/processed/backtest_report.html")

        except ImportError:
            logger.error("quantstats 未安裝")
        except Exception as e:
            logger.error(f"報告產出失敗：{e}")

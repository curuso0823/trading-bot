"""
strategy_engines/allocator_engine.py
AllocatorEngine — 6 資產 Asset Allocator（M5）的權重決策引擎。

定位（M5_DEPLOYMENT_PLAN.md §11.3）：
  - 把研究沙盒 notebooks/regime_tilt/full_book_backtest.py::target_weights()（行 126–162）的
    M0（不對稱帶寬）+ M1（股票腿 ×0.75 de-risk + 釋出資金分配）+ M2（現金 ±5pp tilt、受地板 clip）
    決策邏輯**逐字**移植到 live 引擎，輸出 6 標的目標權重向量（和為 1）。
  - 純計算、無 I/O：target_weights() 不碰行情/帳本/檔案；regime_on / usd_regime 由呼叫端餵入。

鐵律（additive / mode-gated）：
  - mode = "allocator"；只有 settings.yaml strategy.mode == "allocator" 時 make_engine() 才回本引擎。
    mode == "benchmark" 路徑（BenchmarkEngine）逐位不變——本檔不改動 benchmark_engine 既有公開簽名，
    僅 import 複用 _regime_below / is_month_first_trading_day（M1 骨幹）。

權威來源（凍結參數，逐項對齊 §3 config / §11.2 / tw_rebalancing_rules_2026_07.md / full_book_backtest）：
  TARGET / BANDS / EQUITY / A_DERISK=0.75 / SELL_FRAC=0.60。
  交叉驗證契約（§11.3）：對任一 drift/on/usd，
    AllocatorEngine.target_weights(...) ≡ full_book_backtest.target_weights(..., use_m1=True, use_m2=cfg)（容差 1e-9）。
"""
from __future__ import annotations

import pandas as pd

from src.strategy_engines.base import StrategyEngine
from src.strategy_engines.benchmark_engine import _regime_below
from src.utils.helpers import load_settings


# ───────── 凍結預設（§3.7 / §11.2；缺值安全 fallback，與 full_book_backtest 同值）─────────
_DEFAULT_TARGET = {"0050": 0.35, "00981A": 0.16, "00991A": 0.16,
                   "00635U": 0.10, "00864B": 0.115, "MMF": 0.115}
_DEFAULT_BANDS = {"0050": (0.31, 0.42), "00981A": (0.13, 0.23), "00991A": (0.125, 0.23),
                  "00635U": (0.08, 0.15), "00864B": (0.10, 0.15), "MMF": (0.095, 0.145)}
_DEFAULT_EQUITY = ["0050", "00981A", "00991A"]
_DEFAULT_COLS = ["0050", "00981A", "00991A", "00635U", "00864B", "MMF"]
_DEFAULT_SELL_FRAC = 0.60
_DEFAULT_A_DERISK = 0.75
_DEFAULT_M1_MA = 200
_DEFAULT_M1_CONFIRM = 3
_DEFAULT_M1_BAND = 0.01


def _allocator_cfg() -> dict:
    """讀 settings.yaml 的 strategy.allocator 區塊（缺值給安全預設，對齊 §3）。"""
    strat = load_settings().get("strategy", {}) or {}
    return dict(strat.get("allocator", {}) or {})


class AllocatorEngine(StrategyEngine):
    """6 資產 Asset Allocator 權重決策引擎（M0/M1/M2 → 目標權重 dict）。

    live 用法（main.py allocator 分支，§11.7）：
      eng = AllocatorEngine()
      on  = eng.compute_regime_on(closes_0050)          # 0050 MA200 + E1+E2 確認、T+1
      usd = MacroMonitor.usd_regime(asof)               # M2（enabled 時）；否則 0.0
      tw  = eng.target_weights(drift_weights, on, usd)  # 6 標的目標權重（和為 1）
      → 餵 PortfolioRebalancer.plan(...) 出有序零股訂單。

    target_weights / compute_regime_on 皆純計算、不碰 I/O。
    """
    mode = "allocator"

    def __init__(self, cfg: dict | None = None):
        c = cfg if cfg is not None else _allocator_cfg()

        # --- 標的順序 / 目標權重 / 帶寬（assets 區塊；缺值回凍結預設）---
        assets = dict(c.get("assets", {}) or {})
        if assets:
            # 維持 config 宣告順序；缺漏標的補凍結預設
            cols = list(assets.keys())
            for s in _DEFAULT_COLS:
                if s not in cols:
                    cols.append(s)
            self.cols: list[str] = cols
            self.target: dict[str, float] = {}
            self.bands: dict[str, tuple[float, float]] = {}
            for s in self.cols:
                a = dict(assets.get(s, {}) or {})
                self.target[s] = float(a.get("target", _DEFAULT_TARGET.get(s, 0.0)))
                dlo, dhi = _DEFAULT_BANDS.get(s, (0.0, 1.0))
                self.bands[s] = (float(a.get("band_lower", dlo)),
                                 float(a.get("band_upper", dhi)))
        else:
            self.cols = list(_DEFAULT_COLS)
            self.target = dict(_DEFAULT_TARGET)
            self.bands = dict(_DEFAULT_BANDS)

        # --- equity sleeve（M1 股票腿）---
        eq = list(c.get("equity_sleeve", []) or [])
        self.equity: list[str] = eq if eq else list(_DEFAULT_EQUITY)

        # --- M0 賣出比例（超上界賣 60% 超額）---
        self.sell_fraction: float = float(c.get("sell_fraction", _DEFAULT_SELL_FRAC))

        # --- M1 參數（股票腿 de-risk + regime 訊號）---
        m1 = dict(c.get("M1", {}) or {})
        self.a_derisk: float = float(m1.get("derisk_action", _DEFAULT_A_DERISK))
        self.m1_signal_symbol: str = str(m1.get("signal_symbol", "0050"))
        self.m1_ma: int = int(m1.get("ma", _DEFAULT_M1_MA))
        self.m1_confirm_days: int = int(m1.get("confirm_days", _DEFAULT_M1_CONFIRM))
        self.m1_band_pct: float = float(m1.get("band_pct", _DEFAULT_M1_BAND))

        # --- enabled layers（M1/M2 開關；缺省＝["M0","M1"]，M2 預設不開）---
        layers = list(c.get("enabled_layers", []) or [])
        layers_up = [str(x).upper() for x in layers]
        if layers_up:
            self.use_m1: bool = "M1" in layers_up
            self.use_m2: bool = "M2" in layers_up
        else:
            self.use_m1 = True
            self.use_m2 = False
        # M2 另受其 enabled 子旗標把關（雙閘：layer 在清單 且 M2.enabled）
        m2 = dict(c.get("M2", {}) or {})
        if "enabled" in m2:
            self.use_m2 = bool(self.use_m2 and bool(m2.get("enabled")))

    # ---------- 純權重決策（權威＝full_book_backtest.target_weights 行 126–162）----------

    def target_weights(self, drift_weights: dict[str, float],
                       regime_on: bool, usd_regime: float) -> dict[str, float]:
        """M0/M1/M2 三層 → 6 標的目標權重（和為 1）。純計算、無 I/O。

        逐字對齊 full_book_backtest.target_weights(w_drift, on, usd, use_m1, use_m2)：
          use_m1 = self.use_m1（M1 layer 開關），use_m2 = self.use_m2（M2 layer & enabled）。
        - M1 ON（use_m1 且 regime_on）：股票腿 flat = target×0.75；freed=Σ(target−new)；
          黃金 = min(target_gold + freed/3, 黃金上界)、MMF = target_MMF + freed·2/3 + 黃金溢出；
          00864B 不變；**M1 ON 時不套 M0 帶寬**（直接從 TARGET flat-cut）。
        - 否則 M0：逐非-MMF 腿 cur>upper→cur−sell_fraction·(cur−target)、cur<lower→target、帶內持有；
          MMF = max(1−Σ非MMF, MMF 下界)。
        - M2（use_m2 且 usd≠0）：只動現金腿（00864B↔MMF），±0.05 受硬地板/上限 clip。
        - 末步：全權重正規化 tw[k]/Σtw。
        """
        target = self.target
        bands = self.bands
        cols = self.cols
        gold = "00635U"
        bond = "00864B"
        mmf = "MMF"

        if self.use_m1 and regime_on:
            tw = dict(target)
            freed = 0.0
            for s in self.equity:
                new = target[s] * self.a_derisk
                freed += target[s] - new
                tw[s] = new
            want_gold = target[gold] + freed / 3.0
            gold_w = min(want_gold, bands[gold][1])
            tw[gold] = gold_w
            tw[mmf] = target[mmf] + freed * 2.0 / 3.0 + (want_gold - gold_w)
            # 00864B 不變
        else:
            tw = {}
            for s in cols:
                if s == mmf:
                    continue
                lo, hi = bands[s]
                t = target[s]
                cur = drift_weights[s]
                if cur > hi:
                    tw[s] = cur - self.sell_fraction * (cur - t)
                elif cur < lo:
                    tw[s] = t
                else:
                    tw[s] = cur
            nonmmf = sum(tw.values())
            tw[mmf] = max(1.0 - nonmmf, bands[mmf][0])

        # M2 cash-only tilt（受硬地板 / 上限 clip）
        if self.use_m2 and usd_regime != 0:
            if usd_regime < 0:   # 弱美元：減 00864B、加 MMF
                shift = max(0.0, min(0.05, tw[bond] - bands[bond][0], bands[mmf][1] - tw[mmf]))
                tw[bond] -= shift
                tw[mmf] += shift
            else:                # 強美元：加 00864B、減 MMF
                shift = max(0.0, min(0.05, bands[bond][1] - tw[bond], tw[mmf] - bands[mmf][0]))
                tw[bond] += shift
                tw[mmf] -= shift

        tot = sum(tw.values())
        return {k: tw[k] / tot for k in cols}

    # ---------- regime 訊號（0050 MA200 + E1+E2 確認、T+1）----------

    def compute_regime_on(self, closes_0050: pd.Series) -> bool:
        """0050 收盤 MA200 + _regime_below(confirm_days, band_pct) → 今日 regime_on（bool）。

        T+1 語意（與 sandbox full_book_backtest 行 98–100 一致）：sandbox 在整段 regime 序列上 shift(1)
        後取 asof 日值＝「act T+1」；live 每日以**截至昨日收盤**的全序列重算，取末日確認態作為今日決策。
        傳入的 closes_0050 應為**截至昨日（含）**的 0050 收盤序列；本方法回傳其 _regime_below 末日值。
        （等價於 sandbox 的 regime_full.shift(1) 在今日的取值——皆為「昨日確認態、今日作用」。）

        資料不足（空序列或 MA200 全 NaN）→ 視為「未跌破」回 False（保守、與 _regime_below 暖身一致）。
        """
        close = pd.Series(closes_0050).astype(float)
        if close.empty:
            return False
        ma = close.rolling(int(self.m1_ma)).mean()
        below = _regime_below(close, ma, confirm_days=int(self.m1_confirm_days),
                              band_pct=float(self.m1_band_pct))
        if below.empty:
            return False
        return bool(below.iloc[-1])

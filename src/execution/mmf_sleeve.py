"""
execution/mmf_sleeve.py
SyntheticMMF — 合成 cash 等價 sleeve（永豐 MMF 的 paper 模型，M5 allocator §11.6）。

定位：
  永豐 MMF 為「非交易所標的」（基金申購/贖回），paper 階段以一個 pseudo-symbol "MMF" 的
  合成 NAV sleeve 表示。**不經 PaperBroker、不發 place_order**——cash↔MMF 為即時、零費的內部轉移。
  計入組合總權益與權重；歸零重建時依目標權重 11.5% 初始化（由呼叫端 deposit）。

模型（凍結，對齊 settings.yaml strategy.allocator.mmf_annual_yield / full_book_backtest MMF_ANN）：
  - NAV 起始 1.0；日 accrual = (1 + annual_yield) ** (1/252) − 1，**僅交易日計**。
  - value() = units × nav。
  - deposit(twd)：cash → MMF（units += twd / nav）；withdraw(twd)：MMF → cash（即時、零費）。

狀態持久化：data/processed/mmf_sleeve.json = {units, nav, last_accrual_date}。
  可由外部以 file path 注入（測試用 tmp path）；預設用正式路徑。

accrual 防重複：用 src.utils.helpers.count_trading_days 計 last_accrual_date(不含) → asof(含) 之間
  的『交易日』數，僅就該天數複利一次；同日重複呼叫回 0 天 → NAV 不變（避免重複 accrual）。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from loguru import logger

from src.utils.helpers import count_trading_days, load_settings


class SyntheticMMF:
    """合成 MMF cash 等價 sleeve（pseudo-symbol "MMF"，不經 broker）。"""

    SYMBOL = "MMF"
    STATE_FILE = "data/processed/mmf_sleeve.json"

    def __init__(self, state_path: str | Path | None = None,
                 annual_yield: float | None = None):
        """
        state_path：狀態檔路徑（測試以 tmp path 注入）；None → 正式路徑 STATE_FILE。
        annual_yield：年化殖利率；None → 讀 settings.yaml strategy.allocator.mmf_annual_yield（缺值 0.015）。
        """
        self.state_path = Path(state_path) if state_path is not None else Path(self.STATE_FILE)
        if annual_yield is None:
            alloc = (load_settings().get("strategy", {}) or {}).get("allocator", {}) or {}
            annual_yield = float(alloc.get("mmf_annual_yield", 0.015))
        self.annual_yield: float = float(annual_yield)
        # 日 accrual 因子（交易日複利）
        self.daily_rate: float = (1.0 + self.annual_yield) ** (1.0 / 252.0) - 1.0

        # 狀態：NAV 起始 1.0、無單位、無上次 accrual 日
        self.units: float = 0.0
        self.nav: float = 1.0
        self.last_accrual_date: date | None = None
        self._load()

    # ---------- 持久化 ----------

    def _load(self) -> None:
        p = self.state_path
        if not p.exists():
            return
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            logger.warning(f"SyntheticMMF 狀態載入失敗，採預設（units=0, nav=1.0）| {p} | {e}")
            return
        self.units = float(d.get("units", 0.0))
        self.nav = float(d.get("nav", 1.0))
        lad = d.get("last_accrual_date")
        self.last_accrual_date = date.fromisoformat(lad) if lad else None
        logger.info(f"SyntheticMMF 載入：units={self.units:.6f} nav={self.nav:.6f} "
                    f"value={self.value():,.2f} last_accrual={self.last_accrual_date}")

    def _save(self) -> None:
        p = self.state_path
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "units": self.units,
                        "nav": self.nav,
                        "last_accrual_date": (
                            self.last_accrual_date.isoformat()
                            if self.last_accrual_date else None
                        ),
                    },
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            logger.warning(f"SyntheticMMF 狀態寫入失敗 | {p} | {e}")

    # ---------- 估值 ----------

    def value(self) -> float:
        """sleeve 現值 = units × nav。"""
        return self.units * self.nav

    # ---------- 日 accrual（僅交易日複利，防重複）----------

    def accrue(self, asof: date | None = None) -> float:
        """
        把 NAV 從 last_accrual_date 複利到 asof（僅計交易日；同日重複呼叫不重複 accrual）。
        回傳本次 accrue 的交易日數（0＝無變動）。首次呼叫（無 last_accrual_date）只設基準日、不複利
        （避免對未知歷史窗一次灌入大量 accrual）。
        """
        if asof is None:
            asof = date.today()

        # 首次：僅鎖定基準日（自 asof 起未來才複利），不回溯
        if self.last_accrual_date is None:
            self.last_accrual_date = asof
            self._save()
            return 0

        # count_trading_days 計 (last_accrual_date, asof] 之間的交易日數；asof<=last 回 0（含同日/回溯）
        n_days = count_trading_days(self.last_accrual_date, asof)
        if n_days <= 0:
            # asof 未前進（或回溯）→ 不動 NAV；但若 asof 較新且為交易日仍更新基準日（n=0 表中間無交易日）
            if asof > self.last_accrual_date:
                self.last_accrual_date = asof
                self._save()
            return 0

        self.nav *= (1.0 + self.daily_rate) ** n_days
        self.last_accrual_date = asof
        self._save()
        return n_days

    # ---------- 申購/贖回（cash↔MMF，即時零費）----------

    def deposit(self, twd: float) -> float:
        """cash → MMF：投入 twd 元，units += twd / nav。回傳新增 units。twd≤0 → 無動作回 0。"""
        twd = float(twd)
        if twd <= 0 or self.nav <= 0:
            return 0.0
        added = twd / self.nav
        self.units += added
        self._save()
        return added

    def withdraw(self, twd: float) -> float:
        """
        MMF → cash：贖回 twd 元（即時、零費），units -= twd / nav。
        受現值上限保護：實際贖回 = min(twd, value())；回傳『實際贖回的 TWD 金額』。twd≤0 → 回 0。
        """
        twd = float(twd)
        if twd <= 0 or self.nav <= 0:
            return 0.0
        cap = self.value()
        actual = min(twd, cap)
        removed_units = actual / self.nav
        self.units -= removed_units
        if self.units < 0:                 # 浮點殘差保護
            self.units = 0.0
        self._save()
        return actual

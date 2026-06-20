"""
execution/portfolio_rebalancer.py
PortfolioRebalancer — 把 6 資產目標權重轉成「現金感知、先賣後買、整數零股、Fugle 零股撮合價」的
有序訂單（M5 allocator §11.5；★ live 才有的最關鍵新工程）。

定位（additive / mode-gated）：
  僅在 settings.yaml strategy.mode=="allocator" 路徑使用（由 main.py allocator 任務呼叫）；
  benchmark 路徑完全不觸及此檔。純計算 + 注入式報價（quotes 由呼叫端餵入、不在此打網）。

研究沙盒 `notebooks/regime_tilt/full_book_backtest.py` 是 returns-based 月度權重模擬；live 必須是
持股級、整數 lot、現金約束、先賣後買的真實下單。本類別把「目標權重 → 股數 → 有序 RebalanceAction」
這段 live-only 工程實作出來，決策權重本身（M0/M1/M2）由 AllocatorEngine 上游算妥後注入。

契約（§11.5）：
  plan(target_weights, holdings, cash, mmf_value, quotes, *, bands, …) -> list[RebalanceAction]
  ① 總權益 = cash + Σ持倉市值 + mmf_value
  ② 目標市值 = 權益 × 權重
  ③ 帶寬閘（只在出帶才動：出上界賣、破下界買回 target、帶內不動——與 §11.2 M0 同口徑；
     M1/M2 效果已 baked 在 target_weights 內）
  ④ 目標市值 → 整數零股股數（lot_size()，零股 = 1 股粒度）
  ⑤ 排序：賣序 [00991A,00981A,00635U,0050] → 買序 [0050,00981A,00991A,00635U]
  ⑥ 先賣後買：先全域算清現金流（避免 PaperBroker 原子單中途現金用罄 cascade 失敗）、賣出釋金後才買
  ⑦ 硬地板：MMF≥.095、00864B≥.10 不得破
  ⑧ 現金約束（不融資、含 calc_trade_cost 手續費）

零股成交價（§10b 硬要求）：
  買 → fugle.get_realtime_quote(sym, odd=True) 的賣方階梯 parse_odd_ladder + odd_lot_buy_fill
       （book-walk 部分成交 vwap）；無簿 → fallback lastPrice×(1+slippage)。
  賣 → parse_odd_book 的最佳買價；無簿 → fallback lastPrice×(1−slippage)。

MMF：不出 RebalanceAction。以 SyntheticMMF deposit/withdraw 當買序末/賣序末的現金緩衝——
  在回傳結構（RebalancePlan）中標示 MMF 轉移量，由 main.py 實際執行（deposit/withdraw）。

「帶寬閘」設計註（重要、勿改成「in-band 一律 hold」）：
  target_weights 已是 AllocatorEngine 算妥的最終目標（M0 帶寬已 baked、M1/M2 已 tilt）。
  本層的帶寬閘＝**no-churn deadband**：一檔非-MMF 資產只有在
    (a) 當前權重落在帶外（M0 觸發），或
    (b) 注入的 target_weight 本身落在帶外（M1/M2 蓄意推離，如 M1 ON 把股票腿砍到 < 下界）
  才下單、且一律「移動到 target_weight」；當前與目標皆在帶內 → 持有不動。
  此口徑 = §11.2 M0（帶內持有/帶外移到 target）且能正確執行 M1/M2，與 sandbox 在觸發日
  「跳到 target_weights」一致（M0 帶內腿其 target==cur → 移動量≈0）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from src.execution.odd_lot_fill import odd_lot_buy_fill, parse_odd_book, parse_odd_ladder
from src.strategy_engines.base import RebalanceAction
from src.utils.helpers import calc_trade_cost, exec_slippage, load_settings, lot_size

# 凍結排序（§11.5 ⑤ / tw_rebalancing_rules §3）— 不依賴 config，避免漂移
SELL_ORDER = ["00991A", "00981A", "00635U", "0050"]
BUY_ORDER = ["0050", "00981A", "00991A", "00635U"]
MMF_SYMBOL = "MMF"
BOND_SYMBOL = "00864B"
DEFAULT_FLOORS = {"MMF": 0.095, "00864B": 0.10}
DEFAULT_SELL_FRACTION = 0.60
_EPS = 1e-9


@dataclass
class MMFTransfer:
    """MMF cash↔sleeve 轉移指示（不出 RebalanceAction；由 main.py 經 SyntheticMMF 執行）。

    side:      "deposit"（cash→MMF）/ "withdraw"（MMF→cash）/ "none"
    amount:    轉移 TWD 金額（≥0）
    reason:    人類可讀說明
    """
    side: str = "none"
    amount: float = 0.0
    reason: str = ""

    @property
    def is_noop(self) -> bool:
        return self.side == "none" or self.amount <= _EPS


@dataclass
class RebalancePlan:
    """plan() 的完整回傳結構。

    actions:        有序 RebalanceAction（順序即執行順序：先賣後買）。
    mmf_transfer:   MMF 現金緩衝轉移（賣序末釋金存入 / 買序末提領墊款）。
    projected_cash: 全部 actions（含成本、含 MMF 轉移）執行後的預估現金餘額（不得 < 0）。
    notes:          診斷訊息（地板保護、現金縮量、跳過原因…）。
    fill_prices:    {sym: 規劃時算定的成交價}（賣＝最佳買價、買＝book-walk vwap）。
                    執行端（main.py）據此下單 → 消除 planner/executor 報價分歧（§12.2）。
    """
    actions: list[RebalanceAction] = field(default_factory=list)
    mmf_transfer: MMFTransfer = field(default_factory=MMFTransfer)
    projected_cash: float = 0.0
    notes: list[str] = field(default_factory=list)
    fill_prices: dict[str, float] = field(default_factory=dict)

    def __iter__(self):
        """讓 plan 回傳可直接當 list[RebalanceAction] 迭代（main.py 下單迴圈）。"""
        return iter(self.actions)

    def __len__(self):
        return len(self.actions)

    def __getitem__(self, i):
        return self.actions[i]


class PortfolioRebalancer:
    """目標權重 → 有序零股訂單（現金感知、先賣後買、整數 lot、硬地板、Fugle 零股撮合價）。

    用法（main.py allocator_rebalance_task）：
      reb = PortfolioRebalancer(fugle=fugle)            # 注入報價來源（測試餵 fake_quote_fn）
      plan = reb.plan(target_w, holdings, cash, mmf_value, quotes, bands=bands)
      for act in plan.actions:                          # 先賣後買、已現金校驗
          om.exit / om.enter ...
      if not plan.mmf_transfer.is_noop:                 # MMF 緩衝
          mmf.deposit / mmf.withdraw ...
    """

    def __init__(self, *, fugle=None, cfg: dict | None = None,
                 quote_fn=None):
        """
        fugle:    FugleFetcher（提供 get_realtime_quote(sym, odd=True)）；可為 None（全走 quotes 注入）。
        cfg:      strategy.allocator 區塊；None → 讀 settings.yaml（缺值安全預設）。
        quote_fn: 測試用報價函式 quote_fn(sym, odd) -> dict，覆寫 fugle（餵假簿、不打網）。
        """
        self.fugle = fugle
        self.quote_fn = quote_fn
        c = cfg if cfg is not None else self._load_cfg()
        self.sell_fraction: float = float(c.get("sell_fraction", DEFAULT_SELL_FRACTION))
        floors = dict(DEFAULT_FLOORS)
        floors.update(c.get("hard_floor", {}) or {})
        self.hard_floor: dict[str, float] = {k: float(v) for k, v in floors.items()}
        # book-walk / 滑價參數（與 odd_lot_fill / capped_sim 同源）
        from src.utils.helpers import load_config
        tr = load_config().get("trading", {}) or {}
        self.book_levels: int = int(tr.get("odd_lot_book_levels", 5))
        self.max_impact_pct: float = float(tr.get("odd_lot_max_impact_pct", 0.004))
        self.slippage: float = exec_slippage()

    @staticmethod
    def _load_cfg() -> dict:
        strat = load_settings().get("strategy", {}) or {}
        return dict(strat.get("allocator", {}) or {})

    # ────────────────────────── 報價解析 ──────────────────────────

    def _get_quote(self, sym: str, quotes: dict | None) -> dict:
        """取單一標的零股報價。優先：注入 quotes[sym] → quote_fn → fugle.get_realtime_quote。"""
        if quotes and sym in quotes and quotes[sym]:
            return quotes[sym]
        if self.quote_fn is not None:
            try:
                return self.quote_fn(sym, True) or {}
            except Exception as e:                       # pragma: no cover - 防呆
                logger.warning(f"quote_fn 取報價失敗 | {sym} | {e}")
                return {}
        if self.fugle is not None:
            try:
                return self.fugle.get_realtime_quote(sym, odd=True) or {}
            except Exception as e:                       # pragma: no cover - 防呆
                logger.warning(f"fugle 取零股報價失敗 | {sym} | {e}")
                return {}
        return {}

    @staticmethod
    def _last_price(quote: dict) -> float:
        """報價的參考最後價（fallback 用）。無 → 0.0。"""
        try:
            lp = quote.get("lastPrice")
            return float(lp) if lp else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _sell_fill_price(self, sym: str, quote: dict, ref_price: float) -> float:
        """賣出零股成交價＝零股簿最佳買價（parse_odd_book）；無簿 → fallback ref×(1−slippage)。"""
        best_bid, _, _ = parse_odd_book(quote)
        if best_bid > 0:
            return round(best_bid, 2)
        base = self._last_price(quote) or ref_price
        return round(base * (1.0 - self.slippage), 2) if base > 0 else 0.0

    def _buy_fill(self, sym: str, quote: dict, want_qty: int, ref_price: float):
        """買進零股成交：book-walk（賣方階梯 vwap、部分成交）；無簿 → fallback 全量成交 @ref×(1+slip)。

        回傳 (filled_qty, fill_price)。filled_qty 可能 < want_qty（薄帳部分成交，餘量本輪不買）。
        """
        asks = parse_odd_ladder(quote, levels=self.book_levels)
        res = odd_lot_buy_fill(want_qty, asks, max_impact_pct=self.max_impact_pct)
        if res is not None:
            filled, vwap, _remaining = res
            return int(filled), float(vwap)
        # 無零股簿 → fallback：假設可全量成交 @ lastPrice×(1+slip)（資料缺失不擋單，與 odd_lot_fill 註解一致）
        base = self._last_price(quote) or ref_price
        if base <= 0:
            return 0, 0.0
        return int(want_qty), round(base * (1.0 + self.slippage), 2)

    # ────────────────────────── 主流程 ──────────────────────────

    def plan(self, target_weights: dict[str, float], holdings: dict[str, int],
             cash: float, mmf_value: float, quotes: dict | None = None, *,
             bands: dict[str, tuple[float, float]],
             ref_prices: dict[str, float] | None = None) -> RebalancePlan:
        """目標權重 → 有序零股訂單（先賣後買、現金約束、硬地板、零股撮合價）。

        參數：
          target_weights  {sym: weight}（含 MMF；AllocatorEngine 算妥的最終目標，M0/M1/M2 已 baked）。
          holdings        {sym: qty(股)}（非 MMF；缺 = 0；MMF 不在此，用 mmf_value）。
          cash            現金（TWD）。
          mmf_value       MMF sleeve 現值（TWD；= SyntheticMMF.value()）。
          quotes          {sym: 零股報價 dict}（注入；測試餵假簿）。缺 sym → 走 quote_fn/fugle/fallback。
          bands           {sym: (band_lower, band_upper)}（含 MMF；無 → 不套帶寬閘=一律移到 target）。
          ref_prices      {sym: 參考價}（無零股簿時 fallback 用；建議餵昨收/MA 末值）。

        回傳 RebalancePlan（actions 順序即執行順序；mmf_transfer 由 main.py 執行）。
        """
        holdings = {k: int(v) for k, v in (holdings or {}).items()}
        ref_prices = ref_prices or {}
        bands = bands or {}
        lot = lot_size()
        plan = RebalancePlan()

        # ── ① 總權益（cash + Σ非MMF持倉市值 + mmf_value）──
        # 持倉市值用「賣出成交價」估（= 變現口徑，與後續釋金一致；避免高估權益）。
        cur_prices: dict[str, float] = {}
        holding_value = 0.0
        for sym, qty in holdings.items():
            if qty <= 0:
                continue
            q = self._get_quote(sym, quotes)
            px = self._sell_fill_price(sym, q, ref_prices.get(sym, 0.0))
            cur_prices[sym] = px
            holding_value += qty * px * lot
        equity = float(cash) + holding_value + float(mmf_value)
        if equity <= 0:
            plan.notes.append("總權益 ≤ 0，無動作")
            plan.projected_cash = float(cash)
            return plan

        def cur_weight(sym: str) -> float:
            qty = holdings.get(sym, 0)
            px = cur_prices.get(sym, 0.0)
            return (qty * px * lot) / equity if equity > 0 else 0.0

        # ── ②③④ 逐非-MMF 資產：帶寬閘 + 目標市值 → 整數零股股數 ──
        # 對每檔算 desired_delta_shares（>0 買 / <0 賣 / 0 持有）。MMF 在 plan 不直接下單。
        nonmmf_syms = [s for s in target_weights if s != MMF_SYMBOL]
        desired: dict[str, int] = {}
        for sym in nonmmf_syms:
            tw = float(target_weights.get(sym, 0.0))
            cw = cur_weight(sym)
            lo, hi = bands.get(sym, (None, None))
            # 帶寬閘（no-churn deadband）：當前與目標皆在帶內 → 不動；任一在帶外 → 移到 target。
            if lo is not None and hi is not None:
                cur_in_band = (lo - _EPS) <= cw <= (hi + _EPS)
                tgt_in_band = (lo - _EPS) <= tw <= (hi + _EPS)
                if cur_in_band and tgt_in_band:
                    desired[sym] = 0
                    continue
            target_value = equity * tw
            ref = cur_prices.get(sym) or ref_prices.get(sym, 0.0)
            # 估價：賣用現價（已是賣價口徑），買用同一參考（精確買價於下單時 book-walk 再定）
            est_px = ref if ref and ref > 0 else self._last_price(self._get_quote(sym, quotes))
            if not est_px or est_px <= 0:
                desired[sym] = 0
                plan.notes.append(f"{sym}：無有效報價，跳過")
                continue
            target_qty = int(round(target_value / (est_px * lot)))   # 整數零股（lot=1 → 股）
            target_qty = max(0, target_qty)
            desired[sym] = target_qty - holdings.get(sym, 0)

        # ── ⑤⑥ 排序 + 先賣後買：先全域算清現金流 ──
        actions: list[RebalanceAction] = []
        running_cash = float(cash)

        # 賣序（賣出釋金；含硬地板保護）
        for sym in SELL_ORDER:
            if sym not in desired or desired[sym] >= 0:
                continue
            sell_qty = -desired[sym]
            held = holdings.get(sym, 0)
            sell_qty = min(sell_qty, held)
            # 硬地板（00864B 等）：不得因賣出低於地板權重市值
            sell_qty = self._cap_sell_for_floor(sym, sell_qty, held, cur_prices, lot,
                                                 equity, plan)
            if sell_qty <= 0:
                continue
            q = self._get_quote(sym, quotes)
            px = cur_prices.get(sym) or self._sell_fill_price(sym, q, ref_prices.get(sym, 0.0))
            if px <= 0:
                plan.notes.append(f"{sym}：賣出無有效價，跳過")
                continue
            cost = calc_trade_cost(px, sell_qty, "sell")
            proceeds = px * sell_qty * lot - cost["fee"] - cost["tax"]
            running_cash += proceeds
            target_qty = held - sell_qty
            actions.append(RebalanceAction(
                "sell", sym, sell_qty, target_qty, held, float(target_weights.get(sym, 0.0)),
                f"再平衡賣 {sell_qty} 股 @{px}（出帶/減碼；釋金 {proceeds:,.0f}）"))
            plan.fill_prices[sym] = px      # 執行端據此下單（消除報價分歧 §12.2）

        # 賣序末：把「超額現金 / 補倉所需」先用 MMF 緩衝衡量（買序需現金時可從 MMF 提領）。
        # 規則（tw §3 資金序）：補倉資金優先用 MMF。先估買序總需求 → 不足部分自 MMF 提領（守地板）。

        # 買序（受現金約束、book-walk 部分成交、不融資）
        # 先估買序總需求金額（含手續費粗估），若 running_cash 不足 → 從 MMF 提領補足（守 MMF 地板）。
        buy_specs: list[tuple[str, int, float]] = []   # (sym, want_qty, est_px)
        gross_buy_need = 0.0
        for sym in BUY_ORDER:
            if sym not in desired or desired[sym] <= 0:
                continue
            want = desired[sym]
            q = self._get_quote(sym, quotes)
            est_px = cur_prices.get(sym) or self._last_price(q) or ref_prices.get(sym, 0.0)
            if not est_px or est_px <= 0:
                plan.notes.append(f"{sym}：買進無有效估價，跳過")
                continue
            buy_specs.append((sym, want, float(est_px)))
            amt = est_px * want * lot
            fee = calc_trade_cost(est_px, want, "buy")["fee"]
            gross_buy_need += amt + fee

        # MMF 緩衝（提領）：補倉現金不足 → 自 MMF 提領，但 MMF 不得破地板（§11.5 ⑦）。
        mmf_floor_value = self.hard_floor.get(MMF_SYMBOL, 0.0) * equity
        mmf_withdrawable = max(0.0, float(mmf_value) - mmf_floor_value)
        withdraw_amt = 0.0
        if gross_buy_need > running_cash + _EPS and mmf_withdrawable > _EPS:
            need = gross_buy_need - running_cash
            withdraw_amt = min(need, mmf_withdrawable)
            running_cash += withdraw_amt
            plan.notes.append(
                f"MMF 提領 {withdraw_amt:,.0f} 墊買序（守 MMF 地板 {mmf_floor_value:,.0f}）")

        # 逐檔買進：book-walk 取成交價/可成交量 + 現金縮量（不融資、含手續費）
        for sym, want, est_px in buy_specs:
            if want <= 0:
                continue
            q = self._get_quote(sym, quotes)
            filled, fill_px = self._buy_fill(sym, q, want, est_px)
            if filled <= 0 or fill_px <= 0:
                plan.notes.append(f"{sym}：零股簿無量/無價，本輪未買")
                continue
            # 現金縮量：逐步降量直到「成交額 + 手續費 ≤ running_cash」（避免 PaperBroker cascade）
            buyable = filled
            while buyable >= 1:
                amt = fill_px * buyable * lot
                fee = calc_trade_cost(fill_px, buyable, "buy")["fee"]
                if amt + fee <= running_cash + _EPS:
                    break
                buyable -= 1
            if buyable < 1:
                plan.notes.append(f"{sym}：現金不足，本輪未買")
                continue
            amt = fill_px * buyable * lot
            fee = calc_trade_cost(fill_px, buyable, "buy")["fee"]
            running_cash -= (amt + fee)
            held = holdings.get(sym, 0)
            # 區分減量原因：filled<want=薄帳 book-walk 吃不滿；buyable<filled=現金縮量（皆部分成交）
            if buyable < want:
                why = "（薄帳部分成交）" if filled < want and buyable >= filled else "（現金縮量部分成交）"
            else:
                why = ""
            actions.append(RebalanceAction(
                "buy", sym, buyable, held + buyable, held, float(target_weights.get(sym, 0.0)),
                f"再平衡買 {buyable} 股 @{fill_px}{why}（出帶/補倉；耗現金 {amt + fee:,.0f}）"))
            plan.fill_prices[sym] = fill_px    # 執行端據此下單（消除報價分歧 §12.2）

        # ── 買序末：殘餘現金回存 MMF（cash buffer）；扣回提領後淨額決定 deposit/withdraw ──
        # 目標：把「未用於買股的現金」回到 MMF（維持目標現金水位、不留閒置現金）。
        # net MMF 轉移 = (買序末 running_cash 超過開盤 cash 想保留量) → 簡化：所有非買股剩餘現金回存 MMF。
        # 但若本輪有提領 withdraw_amt，需先抵銷；最終 transfer = deposit(剩餘) or withdraw(已提領未抵銷)。
        plan.actions = actions
        plan.projected_cash, plan.mmf_transfer = self._settle_mmf(
            opening_cash=float(cash), running_cash=running_cash,
            withdraw_amt=withdraw_amt, equity=equity, mmf_value=float(mmf_value), plan=plan)
        return plan

    # ────────────────────────── 硬地板 / MMF 結算 ──────────────────────────

    def _cap_sell_for_floor(self, sym: str, sell_qty: int, held: int,
                            cur_prices: dict, lot: int, equity: float,
                            plan: RebalancePlan) -> int:
        """硬地板保護：00864B（及任何 hard_floor 標的）賣出後權重不得低於地板。
        回傳 clip 後可賣股數（≥0）。MMF 不在此（MMF 不下 RebalanceAction）。"""
        floor = self.hard_floor.get(sym)
        if floor is None or sym == MMF_SYMBOL:
            return max(0, sell_qty)
        px = cur_prices.get(sym, 0.0)
        if px <= 0:
            return max(0, sell_qty)
        min_value = floor * equity
        min_qty = int(min_value / (px * lot))            # 不得低於此股數（向下取整＝保守保地板）
        max_sellable = max(0, held - min_qty)
        if sell_qty > max_sellable:
            plan.notes.append(
                f"{sym}：賣量 {sell_qty}→{max_sellable}（守硬地板 {floor:.1%}＝{min_value:,.0f}）")
            return max_sellable
        return max(0, sell_qty)

    def _settle_mmf(self, *, opening_cash: float, running_cash: float,
                    withdraw_amt: float, equity: float, mmf_value: float,
                    plan: RebalancePlan):
        """買序末 MMF 現金緩衝結算。

        running_cash 已含：賣出釋金 + MMF 提領(withdraw_amt) − 買進耗用。
        策略：把「未投入風險資產的剩餘現金」回存 MMF（維持現金水位），但需抵銷本輪提領。
          淨流向 MMF = running_cash − opening_cash − withdraw_amt
            > 0 → deposit（賣多於買 + 未動提領 → 回存）；
            < 0 → 不應發生（買序已受 running_cash 約束、不會超用）→ 殘差視為 0。
        deposit 上不可破其他資產地板（MMF 只增不減地板，故 deposit 永遠安全）。
        回傳 (projected_cash, MMFTransfer)。
        """
        # 淨 MMF 轉移：回存量 = 期末現金 − 期初現金 − 已提領（提領是 MMF→cash，需抵銷）
        net_to_mmf = running_cash - opening_cash - withdraw_amt
        if withdraw_amt > _EPS and net_to_mmf >= -_EPS:
            # 有提領但期末現金仍 ≥ 期初：表示提領未真正用盡 → 等量退回 MMF（淨提領 = withdraw−回退）
            give_back = min(withdraw_amt, max(0.0, net_to_mmf))
            net_withdraw = withdraw_amt - give_back
            projected_cash = running_cash - give_back
            if net_withdraw > _EPS:
                return projected_cash, MMFTransfer(
                    "withdraw", round(net_withdraw, 2),
                    f"買序墊款淨提領 MMF {net_withdraw:,.0f}")
            # 提領全數退回 + 可能還有額外賣出剩餘 → 看 projected vs opening
            extra = projected_cash - opening_cash
            if extra > _EPS:
                return opening_cash, MMFTransfer(
                    "deposit", round(extra, 2), f"賣序釋金回存 MMF {extra:,.0f}")
            return projected_cash, MMFTransfer()
        if withdraw_amt > _EPS:
            # 期末現金 < 期初：提領確實被買序用掉 → 淨提領 = withdraw（現金回到期初附近）
            net_withdraw = opening_cash - running_cash + withdraw_amt
            net_withdraw = max(0.0, min(net_withdraw, withdraw_amt))
            return running_cash, MMFTransfer(
                "withdraw", round(net_withdraw, 2), f"買序墊款提領 MMF {net_withdraw:,.0f}")
        # 無提領：剩餘現金（賣多於買）回存 MMF
        if net_to_mmf > _EPS:
            return opening_cash, MMFTransfer(
                "deposit", round(net_to_mmf, 2), f"賣序釋金回存 MMF {net_to_mmf:,.0f}")
        return running_cash, MMFTransfer()

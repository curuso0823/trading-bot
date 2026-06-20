"""execution/portfolio_rebalancer：目標權重 → 有序零股訂單（現金感知、先賣後買）。

驗證重點（M5_DEPLOYMENT_PLAN.md §11.8 / §11.5）：
  - 現金約束（不融資；projected_cash ≥ 0）。
  - 先賣後買（所有 sell 在所有 buy 之前）。
  - 賣序 / 買序優先序（SELL_ORDER / BUY_ORDER）。
  - 整數零股（lot=1，股粒度；delta_qty 為 int）。
  - 硬地板不破（00864B ≥ 10%；_cap_sell_for_floor 直接驗）。
  - cascade 不爆（多買單 + 現金有限 → 後續買單縮量/跳過、現金永不 < 0）。
  - 零股 book-walk 成交價（餵假零股簿：賣方階梯部分成交 vwap、賣用最佳買價）。

純計算 + 注入式報價（quotes 由測試餵入；不打網）。報價以 fake book dict 餵入 plan(quotes=...)。
"""
import pytest

from src.execution.portfolio_rebalancer import (
    BUY_ORDER, DEFAULT_FLOORS, PortfolioRebalancer, RebalancePlan, SELL_ORDER,
)

BANDS = {"0050": (0.31, 0.42), "00981A": (0.13, 0.23), "00991A": (0.125, 0.23),
         "00635U": (0.08, 0.15), "00864B": (0.10, 0.15), "MMF": (0.095, 0.145)}
ALL_SYMS = ["0050", "00981A", "00991A", "00635U", "00864B"]


def _book(bid, ask, size, last=None, ask_levels=None):
    """造零股報價：bids/asks 各一檔（或多檔賣方階梯）+ lastPrice。

    ask_levels: [(price, size), ...] 覆寫賣方階梯（book-walk 用）；None → 單檔 ask@size。
    """
    asks = ([{"price": p, "size": s} for p, s in ask_levels]
            if ask_levels else [{"price": ask, "size": size}])
    return {"bids": [{"price": bid, "size": size}], "asks": asks,
            "lastPrice": last if last is not None else round((bid + ask) / 2, 2)}


def _deep_quotes(bid=49.95, ask=50.05, size=1_000_000):
    """全標的深簿（足量、窄價差）→ 不受深度限制，純驗排序/現金/地板。"""
    return {s: _book(bid, ask, size) for s in ALL_SYMS}


def _refs(price=50.0):
    return {s: price for s in ALL_SYMS}


def _reb():
    return PortfolioRebalancer(cfg={})        # 不讀 settings.yaml（避免漂移）；用內建凍結預設


# ───────────────────────── 排序 / 先賣後買 ─────────────────────────

def test_sell_before_buy_ordering():
    """0050 超重（賣）+ 多檔欠重（買）→ 所有 sell 在所有 buy 之前。"""
    reb = _reb()
    holdings = {"0050": 10000, "00981A": 1000, "00991A": 1000, "00635U": 1000, "00864B": 1000}
    tw = {"0050": 0.20, "00981A": 0.30, "00991A": 0.16, "00635U": 0.10,
          "00864B": 0.115, "MMF": 0.115}
    plan = reb.plan(tw, holdings, cash=300_000, mmf_value=100_000,
                    quotes=_deep_quotes(), bands=BANDS, ref_prices=_refs())
    sides = [a.side for a in plan.actions]
    assert "sell" in sides and "buy" in sides
    last_sell = max(i for i, s in enumerate(sides) if s == "sell")
    first_buy = min(i for i, s in enumerate(sides) if s == "buy")
    assert last_sell < first_buy, f"先賣後買被破壞：{[(a.side, a.stock_id) for a in plan.actions]}"


def test_buy_priority_order_respected():
    """多檔同時欠重 → 買序依 BUY_ORDER（0050 → 00981A → 00991A → 00635U）。"""
    reb = _reb()
    # 全部欠重（持倉很低），充裕現金 → 全部買得到，純驗順序
    holdings = {s: 100 for s in ALL_SYMS}
    tw = {"0050": 0.35, "00981A": 0.16, "00991A": 0.16, "00635U": 0.10,
          "00864B": 0.115, "MMF": 0.115}
    plan = reb.plan(tw, holdings, cash=1_000_000, mmf_value=0.0,
                    quotes=_deep_quotes(), bands=BANDS, ref_prices=_refs())
    buys = [a.stock_id for a in plan.actions if a.side == "buy"]
    # 出現的買單須為 BUY_ORDER 的子序列（相對順序一致）
    idx = [BUY_ORDER.index(s) for s in buys if s in BUY_ORDER]
    assert idx == sorted(idx), f"買序未依 BUY_ORDER：{buys}"


def test_sell_priority_order_respected():
    """多檔同時超重 → 賣序依 SELL_ORDER（00991A → 00981A → 00635U → 0050）。"""
    reb = _reb()
    # 多檔超重（持倉高），target 偏低 → 多檔賣，驗賣序
    holdings = {"0050": 8000, "00981A": 4000, "00991A": 4000, "00635U": 4000, "00864B": 1000}
    tw = {"0050": 0.15, "00981A": 0.10, "00991A": 0.10, "00635U": 0.08,
          "00864B": 0.115, "MMF": 0.30}
    plan = reb.plan(tw, holdings, cash=50_000, mmf_value=50_000,
                    quotes=_deep_quotes(), bands=BANDS, ref_prices=_refs())
    sells = [a.stock_id for a in plan.actions if a.side == "sell"]
    idx = [SELL_ORDER.index(s) for s in sells if s in SELL_ORDER]
    assert idx == sorted(idx), f"賣序未依 SELL_ORDER：{sells}"


# ───────────────────────── 現金約束 / cascade ─────────────────────────

def test_no_margin_projected_cash_nonneg():
    """任一 plan 的 projected_cash ≥ 0（不融資）。"""
    reb = _reb()
    holdings = {"0050": 1000, "00981A": 1000, "00991A": 1000, "00635U": 1000, "00864B": 1000}
    tw = {"0050": 0.50, "00981A": 0.20, "00991A": 0.16, "00635U": 0.08,
          "00864B": 0.10, "MMF": 0.095}
    plan = reb.plan(tw, holdings, cash=10_000, mmf_value=0.0,
                    quotes=_deep_quotes(), bands=BANDS, ref_prices=_refs())
    assert plan.projected_cash >= -1e-6


def test_cascade_does_not_blow_up_cash_constrained():
    """多買單 + 現金有限 + 無 MMF → 後續買單縮量/跳過、現金永不 < 0（避免 PaperBroker cascade）。"""
    reb = _reb()
    holdings = {s: 1000 for s in ALL_SYMS}
    # 全部想加碼，但現金只有 30k、MMF=0 → 先賣釋金、後買到現金用罄即停
    tw = {"0050": 0.30, "00981A": 0.25, "00991A": 0.25, "00635U": 0.12,
          "00864B": 0.10, "MMF": 0.095}
    plan = reb.plan(tw, holdings, cash=30_000, mmf_value=0.0,
                    quotes=_deep_quotes(), bands=BANDS, ref_prices=_refs())
    assert plan.projected_cash >= -1e-6           # 不爆現金（先全域算清現金流，非逐單原子失敗）
    # 至少一筆買被現金縮量/跳過（驗 cascade 防護真的發生：現金用罄即停、非中途崩）
    assert any("現金不足" in n or "現金縮量" in n for n in plan.notes)


def test_buy_constrained_by_cash_only_no_sells():
    """純現金約束（無可賣持倉、無 MMF）→ 買單總額受現金限制、不超買、不融資。

    僅持 100 股 0050（其餘 0、無從賣出）+ 15k 現金、MMF=0；0050 跌破下界 → 想大買，
    但無釋金來源 → 買單總成交額（含手續費）≤ 開盤現金、projected_cash ≥ 0。
    """
    reb = _reb()
    holdings = {"0050": 100}                       # 其餘標的 0 → SELL_ORDER 無可賣
    tw = {"0050": 0.50, "00981A": 0.16, "00991A": 0.16, "00635U": 0.08,
          "00864B": 0.10, "MMF": 0.0}
    plan = reb.plan(tw, holdings, cash=15_000, mmf_value=0.0,
                    quotes=_deep_quotes(), bands=BANDS, ref_prices=_refs())
    # 無任何賣單（無持倉可賣）
    assert all(a.side == "buy" for a in plan.actions)
    # 買單總額（含手續費粗估）受現金約束、不融資
    spent = sum(a.delta_qty * 50.05 for a in plan.actions)
    assert spent <= 15_000 + 1e-6
    assert plan.projected_cash >= -1e-6


# ───────────────────────── 整數零股 ─────────────────────────

def test_integer_odd_lot_shares():
    """所有 delta_qty 為整數（int）且 ≥ 1（lot=1 股粒度）。"""
    reb = _reb()
    holdings = {"0050": 10000, "00981A": 500, "00991A": 1000, "00635U": 1000, "00864B": 1000}
    tw = {"0050": 0.20, "00981A": 0.30, "00991A": 0.16, "00635U": 0.10,
          "00864B": 0.115, "MMF": 0.115}
    plan = reb.plan(tw, holdings, cash=300_000, mmf_value=100_000,
                    quotes=_deep_quotes(), bands=BANDS, ref_prices=_refs())
    assert plan.actions
    for a in plan.actions:
        assert isinstance(a.delta_qty, int)
        assert a.delta_qty >= 1
        assert isinstance(a.target_qty, int)


# ───────────────────────── 硬地板 ─────────────────────────

def test_hard_floor_cap_sell_protects_00864b():
    """_cap_sell_for_floor：00864B 賣出後殘值不得低於 10%×equity（賣量被 clip）。"""
    reb = _reb()
    plan = RebalancePlan()
    # held 5000 @50、equity 650k → floor 65k = 1300 股 → 最多賣 5000−1300=3700
    capped = reb._cap_sell_for_floor("00864B", sell_qty=4350, held=5000,
                                     cur_prices={"00864B": 50.0}, lot=1,
                                     equity=650_000, plan=plan)
    assert capped == 3700
    # 殘值 ≥ 地板
    assert (5000 - capped) * 50.0 >= 0.10 * 650_000 - 1e-6
    assert any("硬地板" in n for n in plan.notes)


def test_hard_floor_no_cap_when_within():
    """賣量未威脅地板 → 不 clip（原量返回）。"""
    reb = _reb()
    capped = reb._cap_sell_for_floor("00864B", sell_qty=1000, held=5000,
                                     cur_prices={"00864B": 50.0}, lot=1,
                                     equity=650_000, plan=RebalancePlan())
    assert capped == 1000


def test_hard_floor_mmf_excluded():
    """MMF 不出 RebalanceAction → _cap_sell_for_floor 對 MMF 不套地板（原量返回）。"""
    reb = _reb()
    capped = reb._cap_sell_for_floor("MMF", sell_qty=999, held=1000,
                                     cur_prices={"MMF": 1.0}, lot=1,
                                     equity=650_000, plan=RebalancePlan())
    assert capped == 999
    # 結構性確認：MMF / 00864B 皆不在 SELL_ORDER（只當地板 ballast）
    assert "MMF" not in SELL_ORDER
    assert "00864B" not in SELL_ORDER
    assert DEFAULT_FLOORS == {"MMF": 0.095, "00864B": 0.10}


# ───────────────────────── 零股 book-walk 成交價 ─────────────────────────

def test_buy_book_walk_partial_fill_thin_book():
    """買單薄帳 book-walk：賣一 38 + 賣二 62（impact 內）→ 吃滿 100 @ VWAP；越界檔不吃。"""
    reb = _reb()
    thin = _book(49.95, 50.05, 0, ask_levels=[(50.05, 38), (50.10, 62), (99.0, 9999)])
    quotes = dict(_deep_quotes())
    quotes["00981A"] = thin
    holdings = {"0050": 12000, "00981A": 0, "00991A": 1000, "00635U": 1000, "00864B": 1000}
    tw = {"0050": 0.20, "00981A": 0.30, "00991A": 0.16, "00635U": 0.10,
          "00864B": 0.115, "MMF": 0.115}
    plan = reb.plan(tw, holdings, cash=500_000, mmf_value=100_000,
                    quotes=quotes, bands=BANDS, ref_prices=_refs())
    buy981 = [a for a in plan.actions if a.stock_id == "00981A" and a.side == "buy"]
    assert buy981, "應有 00981A 買單"
    # impact cap = 50.05×1.004 ≈ 50.25 → 只吃賣一+賣二（38+62=100），99.0 越界不吃
    assert buy981[0].delta_qty == 100
    expected_vwap = round((38 * 50.05 + 62 * 50.10) / 100, 2)
    assert f"@{expected_vwap}" in buy981[0].reason
    assert "薄帳部分成交" in buy981[0].reason


def test_sell_fill_uses_best_bid():
    """賣出成交價＝零股簿最佳買價（parse_odd_book best_bid），非 lastPrice。"""
    reb = _reb()
    quotes = {s: _book(49.90, 50.20, 1_000_000) for s in ALL_SYMS}
    holdings = {"0050": 12000, "00981A": 1000, "00991A": 1000, "00635U": 1000, "00864B": 1000}
    tw = {"0050": 0.20, "00981A": 0.30, "00991A": 0.16, "00635U": 0.10,
          "00864B": 0.115, "MMF": 0.115}
    plan = reb.plan(tw, holdings, cash=300_000, mmf_value=100_000,
                    quotes=quotes, bands=BANDS, ref_prices=_refs())
    sell0050 = [a for a in plan.actions if a.stock_id == "0050" and a.side == "sell"]
    assert sell0050, "應有 0050 賣單"
    assert "@49.9" in sell0050[0].reason          # 賣在最佳買價 49.90，非 50.05/50.20


def test_buy_fill_uses_ask_ladder_vwap():
    """買進成交價＝賣方階梯 book-walk VWAP（深簿單檔→賣一價）。"""
    reb = _reb()
    quotes = {s: _book(49.90, 50.20, 1_000_000) for s in ALL_SYMS}
    holdings = {s: 100 for s in ALL_SYMS}
    tw = {"0050": 0.35, "00981A": 0.16, "00991A": 0.16, "00635U": 0.10,
          "00864B": 0.115, "MMF": 0.115}
    plan = reb.plan(tw, holdings, cash=1_000_000, mmf_value=0.0,
                    quotes=quotes, bands=BANDS, ref_prices=_refs())
    buys = [a for a in plan.actions if a.side == "buy"]
    assert buys
    for a in buys:
        assert "@50.2" in a.reason                # 深簿單檔賣一 50.20


# ───────────────────────── MMF 緩衝 / 帶寬閘 ─────────────────────────

def test_mmf_withdraw_funds_buy_respecting_floor():
    """現金不足、MMF 充裕 → 自 MMF 提領墊買序，且 MMF 不破地板（§11.5 ⑦）。"""
    reb = _reb()
    holdings = {"0050": 1000, "00981A": 1000, "00991A": 1000, "00635U": 1000, "00864B": 1000}
    tw = {"0050": 0.50, "00981A": 0.16, "00991A": 0.16, "00635U": 0.08,
          "00864B": 0.10, "MMF": 0.095}
    plan = reb.plan(tw, holdings, cash=1_000, mmf_value=300_000,
                    quotes=_deep_quotes(), bands=BANDS, ref_prices=_refs())
    assert plan.mmf_transfer.side == "withdraw"
    assert plan.mmf_transfer.amount > 0
    assert plan.projected_cash >= -1e-6
    # 提領量不可使 MMF < 地板（9.5%×equity）
    # equity 用變現口徑估（持倉@bid 49.95）：~ 5×(1000×49.95)=249,750 + 1000 cash + 300k mmf
    assert any("守 MMF 地板" in n for n in plan.notes)


def test_mmf_deposit_when_sells_exceed_buys():
    """賣多於買（釋金 > 補倉）→ 殘餘現金回存 MMF（deposit）。"""
    reb = _reb()
    holdings = {"0050": 12000, "00981A": 1000, "00991A": 1000, "00635U": 1000, "00864B": 1000}
    # 大砍 0050、其餘不太需買 → 釋金回存 MMF
    tw = {"0050": 0.10, "00981A": 0.16, "00991A": 0.16, "00635U": 0.10,
          "00864B": 0.115, "MMF": 0.305}
    plan = reb.plan(tw, holdings, cash=50_000, mmf_value=50_000,
                    quotes=_deep_quotes(), bands=BANDS, ref_prices=_refs())
    assert plan.mmf_transfer.side == "deposit"
    assert plan.mmf_transfer.amount > 0


def test_band_gate_holds_when_both_in_band():
    """帶寬閘：當前與目標權重皆在帶內 → 不下單（no-churn deadband）。"""
    reb = _reb()
    # 每檔持倉權重 ≈ target、皆帶內 → desired 0、無 action
    holdings = {"0050": 7000, "00981A": 3200, "00991A": 3200, "00635U": 2000, "00864B": 2300}
    tw = {"0050": 0.35, "00981A": 0.16, "00991A": 0.16, "00635U": 0.10,
          "00864B": 0.115, "MMF": 0.115}
    # equity ≈ Σ(qty×49.95) + cash + mmf；設定使各權重落帶內
    plan = reb.plan(tw, holdings, cash=23_000, mmf_value=23_000,
                    quotes=_deep_quotes(), bands=BANDS, ref_prices=_refs())
    # 帶內 → 不應有大額調倉（允許 0 筆；若有也僅出帶腿）。此處驗無動作。
    assert len(plan.actions) == 0, f"帶內不應下單：{[(a.side, a.stock_id, a.delta_qty) for a in plan.actions]}"


def test_zero_equity_returns_empty_plan():
    """總權益 ≤ 0（無現金、無持倉、無 MMF）→ 空 plan、無動作。"""
    reb = _reb()
    plan = reb.plan({"0050": 1.0}, holdings={}, cash=0.0, mmf_value=0.0,
                    quotes=_deep_quotes(), bands=BANDS)
    assert len(plan.actions) == 0
    assert plan.mmf_transfer.is_noop


def test_plan_is_iterable_as_action_list():
    """RebalancePlan 可直接當 list[RebalanceAction] 迭代/len/index（main.py 下單迴圈）。"""
    reb = _reb()
    holdings = {"0050": 10000, "00981A": 1000, "00991A": 1000, "00635U": 1000, "00864B": 1000}
    tw = {"0050": 0.20, "00981A": 0.30, "00991A": 0.16, "00635U": 0.10,
          "00864B": 0.115, "MMF": 0.115}
    plan = reb.plan(tw, holdings, cash=300_000, mmf_value=100_000,
                    quotes=_deep_quotes(), bands=BANDS, ref_prices=_refs())
    as_list = list(plan)
    assert len(as_list) == len(plan)
    if len(plan) > 0:
        assert plan[0] is as_list[0]


# ───────────────────────── fill_prices（planner/executor 報價一致，§12.2 修正）─────────────────────────

def test_fill_prices_recorded_and_match_actions():
    """plan.fill_prices 對每筆 action 記錄成交價 ＝ action.reason 內的 @price。
    執行端（main.py 段1/段3）據此下單，消除『planner book-walk vwap vs executor 1股重抓價』分歧。"""
    reb = _reb()
    quotes = {s: _book(49.90, 50.20, 1_000_000) for s in ALL_SYMS}
    holdings = {"0050": 12000, "00981A": 1000, "00991A": 1000, "00635U": 1000, "00864B": 1000}
    tw = {"0050": 0.20, "00981A": 0.30, "00991A": 0.16, "00635U": 0.10,
          "00864B": 0.115, "MMF": 0.115}
    plan = reb.plan(tw, holdings, cash=300_000, mmf_value=100_000,
                    quotes=quotes, bands=BANDS, ref_prices=_refs())
    assert plan.actions
    for a in plan.actions:
        assert a.stock_id in plan.fill_prices            # 每筆 action 都有記錄價
        px = plan.fill_prices[a.stock_id]
        assert px > 0
        assert f"@{px}" in a.reason                      # 記錄價＝該 action 實際用的價
        # 口徑：賣＝零股簿最佳買價 49.90；買＝賣方階梯 book-walk vwap（深簿單檔 50.20）
        assert px == (49.9 if a.side == "sell" else 50.2)

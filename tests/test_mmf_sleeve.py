"""execution/mmf_sleeve：合成 MMF cash 等價 sleeve（不經 broker）。

驗證重點（M5_DEPLOYMENT_PLAN.md §11.8 / §11.6）：
  - accrual：n 交易日後 NAV/value 正確（(1+daily)^n）；首次呼叫只設基準日（不回溯灌入）；
    同日 / 回溯重複呼叫不重複 accrue。
  - deposit/withdraw round-trip（即時、零費；units 守恆）。
  - value() = units × nav。
  - 不經 PaperBroker / 不發 place_order（純內部 cash↔MMF 轉移）。

鐵律：狀態檔以 tmp path 注入，**絕不碰** data/processed/mmf_sleeve.json（執行期帳本）。
凍結：annual_yield 0.015、日 accrual (1.015)^(1/252)−1、僅交易日複利。
"""
from datetime import date

import pytest

from src.execution.mmf_sleeve import SyntheticMMF
from src.utils.helpers import count_trading_days

ANNUAL = 0.015
DAILY = (1.0 + ANNUAL) ** (1.0 / 252.0) - 1.0


@pytest.fixture
def sleeve(tmp_path):
    """tmp 狀態檔的 SyntheticMMF（固定 annual_yield，不讀 settings、不碰正式帳本）。"""
    return SyntheticMMF(state_path=tmp_path / "mmf_sleeve.json", annual_yield=ANNUAL)


# ───────────────────────── 初始 / 估值 ─────────────────────────

def test_initial_state(sleeve):
    """NAV 起始 1.0、units 0、value 0。"""
    assert sleeve.nav == pytest.approx(1.0)
    assert sleeve.units == pytest.approx(0.0)
    assert sleeve.value() == pytest.approx(0.0)
    assert sleeve.SYMBOL == "MMF"


def test_value_equals_units_times_nav(sleeve):
    """value() = units × nav（手動設值驗）。"""
    sleeve.units = 123.0
    sleeve.nav = 1.05
    assert sleeve.value() == pytest.approx(123.0 * 1.05)


# ───────────────────────── deposit / withdraw round-trip ─────────────────────────

def test_deposit_adds_units_at_nav(sleeve):
    """deposit(twd)：units += twd/nav；value 增加 twd（NAV=1 時 units==twd）。"""
    added = sleeve.deposit(100_000)
    assert added == pytest.approx(100_000 / 1.0)
    assert sleeve.units == pytest.approx(100_000)
    assert sleeve.value() == pytest.approx(100_000)


def test_withdraw_round_trip(sleeve):
    """deposit 後 withdraw 同額 → value 回到 0（即時、零費；units 守恆）。"""
    sleeve.deposit(100_000)
    out = sleeve.withdraw(40_000)
    assert out == pytest.approx(40_000)
    assert sleeve.value() == pytest.approx(60_000)
    out2 = sleeve.withdraw(60_000)
    assert out2 == pytest.approx(60_000)
    assert sleeve.value() == pytest.approx(0.0, abs=1e-9)
    assert sleeve.units == pytest.approx(0.0, abs=1e-9)


def test_withdraw_capped_at_value(sleeve):
    """withdraw 超過現值 → 實際只贖回 value()（不透支）；units 不為負。"""
    sleeve.deposit(10_000)
    out = sleeve.withdraw(999_999)
    assert out == pytest.approx(10_000)
    assert sleeve.value() == pytest.approx(0.0, abs=1e-9)
    assert sleeve.units >= 0.0


def test_deposit_withdraw_nonpositive_noop(sleeve):
    """twd ≤ 0 → 無動作回 0（不改 units）。"""
    sleeve.deposit(50_000)
    u0 = sleeve.units
    assert sleeve.deposit(0) == 0.0
    assert sleeve.deposit(-100) == 0.0
    assert sleeve.withdraw(0) == 0.0
    assert sleeve.withdraw(-100) == 0.0
    assert sleeve.units == pytest.approx(u0)


def test_deposit_after_accrual_uses_current_nav(sleeve):
    """NAV 漲後 deposit → units 以當前 NAV 計（同額 twd 得較少 units）。"""
    sleeve.nav = 1.10
    added = sleeve.deposit(11_000)
    assert added == pytest.approx(11_000 / 1.10)        # =10000 units
    assert sleeve.value() == pytest.approx(11_000)


# ───────────────────────── accrual（僅交易日、防重複）─────────────────────────

def test_first_accrue_only_sets_baseline(sleeve):
    """首次 accrue（無 last_accrual_date）→ 只設基準日、不複利（回 0、NAV 不變）。"""
    sleeve.deposit(100_000)
    n = sleeve.accrue(date(2024, 1, 2))
    assert n == 0
    assert sleeve.nav == pytest.approx(1.0)
    assert sleeve.last_accrual_date == date(2024, 1, 2)


def test_accrue_n_trading_days_value(sleeve):
    """n 交易日後 NAV=(1+daily)^n、value 正確（2024-01-02→01-09＝5 交易日）。"""
    sleeve.deposit(100_000)
    sleeve.accrue(date(2024, 1, 2))                     # 基準
    n = sleeve.accrue(date(2024, 1, 9))
    assert n == count_trading_days(date(2024, 1, 2), date(2024, 1, 9))   # =5
    assert n == 5
    assert sleeve.nav == pytest.approx((1.0 + DAILY) ** 5, abs=1e-12)
    assert sleeve.value() == pytest.approx(100_000 * (1.0 + DAILY) ** 5, abs=1e-6)


def test_repeated_same_day_accrue_no_double(sleeve):
    """同日重複 accrue → 0 交易日、NAV 不變（防重複 accrual）。"""
    sleeve.deposit(100_000)
    sleeve.accrue(date(2024, 1, 2))
    sleeve.accrue(date(2024, 1, 9))
    nav_after = sleeve.nav
    n2 = sleeve.accrue(date(2024, 1, 9))               # 同日再呼叫
    assert n2 == 0
    assert sleeve.nav == pytest.approx(nav_after, abs=1e-15)


def test_backward_accrue_no_change(sleeve):
    """asof 回溯（早於 last_accrual_date）→ 0 交易日、NAV 不變。"""
    sleeve.deposit(100_000)
    sleeve.accrue(date(2024, 1, 9))                     # 基準
    nav0 = sleeve.nav
    n = sleeve.accrue(date(2024, 1, 2))                 # 回溯
    assert n == 0
    assert sleeve.nav == pytest.approx(nav0, abs=1e-15)


def test_incremental_accrue_compounds_correctly(sleeve):
    """分段 accrue（02→09→16）複利 ≡ 連續總天數（無遺漏/重複）。"""
    sleeve.deposit(100_000)
    sleeve.accrue(date(2024, 1, 2))
    sleeve.accrue(date(2024, 1, 9))
    sleeve.accrue(date(2024, 1, 16))
    total_days = count_trading_days(date(2024, 1, 2), date(2024, 1, 16))
    assert sleeve.nav == pytest.approx((1.0 + DAILY) ** total_days, abs=1e-12)


# ───────────────────────── 持久化 / 不經 broker ─────────────────────────

def test_state_persists_across_reload(tmp_path):
    """deposit + accrue 後重新載入同 state_path → units/nav/last_accrual 還原。"""
    sp = tmp_path / "mmf_sleeve.json"
    m1 = SyntheticMMF(state_path=sp, annual_yield=ANNUAL)
    m1.deposit(80_000)
    m1.accrue(date(2024, 1, 2))
    m1.accrue(date(2024, 1, 9))
    units, nav, lad = m1.units, m1.nav, m1.last_accrual_date

    m2 = SyntheticMMF(state_path=sp, annual_yield=ANNUAL)
    assert m2.units == pytest.approx(units)
    assert m2.nav == pytest.approx(nav)
    assert m2.last_accrual_date == lad
    assert m2.value() == pytest.approx(units * nav)


def test_does_not_touch_paper_broker(tmp_path):
    """SyntheticMMF 不經 broker：無 place_order 介面、deposit/withdraw 純內部（不依賴 PaperBroker）。"""
    m = SyntheticMMF(state_path=tmp_path / "mmf_sleeve.json", annual_yield=ANNUAL)
    # 不應有任何下單/broker 介面（合成 sleeve 是 cash 等價、不掛單）
    assert not hasattr(m, "place_order")
    assert not hasattr(m, "broker")
    # round-trip 後現值守恆，不經撮合/手續費
    m.deposit(50_000)
    assert m.value() == pytest.approx(50_000)           # 零費：deposit 全額入帳
    assert m.withdraw(50_000) == pytest.approx(50_000)  # 零費：withdraw 全額出帳


def test_uses_injected_state_path_not_production(tmp_path):
    """狀態檔走注入 tmp path（驗 STATE_FILE 預設常數存在但本實例用 tmp、不碰正式帳本）。"""
    sp = tmp_path / "mmf_sleeve.json"
    m = SyntheticMMF(state_path=sp, annual_yield=ANNUAL)
    m.deposit(1_000)
    assert sp.exists()                                  # 寫到 tmp
    assert SyntheticMMF.STATE_FILE == "data/processed/mmf_sleeve.json"   # 預設常數未被本測試動到
    assert str(m.state_path) == str(sp)

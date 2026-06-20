"""strategy_engines/allocator_engine：6 資產 Asset Allocator 權重決策（M0/M1/M2）。

驗證重點（M5_DEPLOYMENT_PLAN.md §11.8）：
  - M0 帶寬三分支（超上界賣 60% 超額 / 破下界買回 target / 帶內持有）+ MMF 殘差地板。
  - M1（股票 sleeve ×0.75 flat + freed → MMF·2/3 + gold·1/3 + gold cap 溢出 → MMF + 00864B 不變）。
  - M2（雙向 cash-only tilt、硬地板 clip、enabled 關閉短路）。
  - 末步正規化和為 1。
  - 退化測試：layer 關閉 ≡ 對應行為（M1 off ≡ M0；M2 off ≡ 不 tilt）。

純計算、不打 API、不碰 I/O：直接以注入 cfg 建構引擎，餵 drift_weights / regime_on / usd_regime。
凍結參數權威＝full_book_backtest.target_weights()（行 126–162）＋ §11.2：
  TARGET / BANDS / EQUITY / A_DERISK=0.75 / SELL_FRAC=0.60。
"""
import pytest

from src.strategy_engines.allocator_engine import AllocatorEngine

# 凍結參數（與 §11.2 / full_book_backtest 同值）── 測試自帶 cfg，避免依賴 settings.yaml 漂移。
TARGET = {"0050": 0.35, "00981A": 0.16, "00991A": 0.16,
          "00635U": 0.10, "00864B": 0.115, "MMF": 0.115}
BANDS = {"0050": (0.31, 0.42), "00981A": (0.13, 0.23), "00991A": (0.125, 0.23),
         "00635U": (0.08, 0.15), "00864B": (0.10, 0.15), "MMF": (0.095, 0.145)}
COLS = ["0050", "00981A", "00991A", "00635U", "00864B", "MMF"]
EQUITY = ["0050", "00981A", "00991A"]


def _cfg(layers):
    """造一份完整 allocator cfg（assets/bands/M1/M2 皆對齊凍結值）。"""
    return {
        "enabled_layers": layers,
        "assets": {s: {"target": TARGET[s], "band_lower": BANDS[s][0],
                       "band_upper": BANDS[s][1]} for s in COLS},
        "sell_fraction": 0.60,
        "equity_sleeve": list(EQUITY),
        "hard_floor": {"MMF": 0.095, "00864B": 0.10},
        "M1": {"signal_symbol": "0050", "ma": 200, "confirm_days": 3,
               "band_pct": 0.01, "derisk_action": 0.75},
        "M2": {"enabled": True, "cpi_series": "CPIAUCSL", "fed_series": "FEDFUNDS",
               "lookback_months": 3, "confirm_months": 2, "publish_lag_months": 2},
    }


def _eng_m0():
    return AllocatorEngine(_cfg(["M0"]))


def _eng_m0m1():
    return AllocatorEngine(_cfg(["M0", "M1"]))


def _eng_m0m1m2():
    return AllocatorEngine(_cfg(["M0", "M1", "M2"]))


# 帶內基準漂移（每檔皆在帶內 → M0 應原樣保留非-MMF、MMF 補殘差）
DRIFT_INBAND = {"0050": 0.35, "00981A": 0.16, "00991A": 0.16,
                "00635U": 0.10, "00864B": 0.115}


def _sum1(tw):
    return sum(tw.values()) == pytest.approx(1.0, abs=1e-12)


# ───────────────────────── M0：帶寬三分支 ─────────────────────────

def test_m0_inband_holds_drift_then_normalizes():
    """所有非-MMF 在帶內 → 各腿保留 drift；MMF=max(1−Σ,.095)；末步正規化、和為 1。"""
    eng = _eng_m0()
    tw = eng.target_weights(DRIFT_INBAND, regime_on=False, usd_regime=0.0)
    # Σ非MMF=0.885 → MMF=max(0.115,.095)=0.115，總和恰 1.0 → 正規化不改值
    assert tw["0050"] == pytest.approx(0.35, abs=1e-12)
    assert tw["00864B"] == pytest.approx(0.115, abs=1e-12)
    assert tw["MMF"] == pytest.approx(0.115, abs=1e-12)
    assert _sum1(tw)


def test_m0_above_upper_sells_60pct_excess():
    """0050 漂到 0.45 > 上界 .42 → cur−0.60·(cur−target)=0.39（正規化前）。"""
    eng = _eng_m0()
    drift = dict(DRIFT_INBAND, **{"0050": 0.45})
    tw = eng.target_weights(drift, regime_on=False, usd_regime=0.0)
    # 正規化前：0050=0.39、其餘帶內持有、MMF=max(1−Σ非MMF,.095)
    # Σ非MMF=0.39+0.16+0.16+0.10+0.115=0.925 → MMF=max(0.075,.095)=0.095；tot=1.02
    assert tw["0050"] == pytest.approx(0.39 / 1.02, abs=1e-9)
    assert tw["MMF"] == pytest.approx(0.095 / 1.02, abs=1e-9)
    assert _sum1(tw)
    # 賣 60% 超額：0050 仍高於 target 權重佔比（沒賣到 target）
    assert tw["0050"] > tw["00981A"]


def test_m0_below_lower_buys_back_to_target():
    """00981A 跌到 0.10 < 下界 .13 → 買回 target 0.16（正規化前）。"""
    eng = _eng_m0()
    drift = dict(DRIFT_INBAND, **{"00981A": 0.10})
    tw = eng.target_weights(drift, regime_on=False, usd_regime=0.0)
    # 正規化前 00981A=target=0.16；Σ非MMF=0.35+0.16+0.16+0.10+0.115=0.885 → MMF=0.115；tot=1.0
    assert tw["00981A"] == pytest.approx(0.16, abs=1e-9)
    assert _sum1(tw)


def test_m0_mmf_floor_when_nonmmf_overweight():
    """非-MMF 合計把 MMF 擠到 < 地板 → MMF clip 到 .095（正規化前），再正規化。"""
    eng = _eng_m0()
    # 兩檔股票都在帶內偏高，使 Σ非MMF 接近 1 → MMF 觸地板
    drift = {"0050": 0.40, "00981A": 0.22, "00991A": 0.22,
             "00635U": 0.14, "00864B": 0.14}      # 皆帶內、Σ=1.12
    tw = eng.target_weights(drift, regime_on=False, usd_regime=0.0)
    # 全帶內保留 → Σ非MMF=1.12 → MMF=max(1−1.12,.095)=0.095（地板）；tot=1.215
    assert tw["MMF"] == pytest.approx(0.095 / 1.215, abs=1e-9)
    assert _sum1(tw)


def test_m0_three_branches_simultaneously():
    """同時：0050 超上界（賣）、00991A 破下界（買回）、其餘帶內（持有）→ 三分支並存且和為 1。"""
    eng = _eng_m0()
    drift = {"0050": 0.46, "00981A": 0.16, "00991A": 0.10,
             "00635U": 0.10, "00864B": 0.115}
    tw = eng.target_weights(drift, regime_on=False, usd_regime=0.0)
    # 0050: 0.46−0.6·(0.46−0.35)=0.394（賣60%超額）；00991A→target 0.16（買回）；00981A/635/864 持有
    nonmmf = 0.394 + 0.16 + 0.16 + 0.10 + 0.115        # =0.929
    mmf = max(1.0 - nonmmf, 0.095)                      # =0.095（0.071<0.095）
    tot = nonmmf + mmf
    assert tw["0050"] == pytest.approx(0.394 / tot, abs=1e-9)
    assert tw["00991A"] == pytest.approx(0.16 / tot, abs=1e-9)
    assert tw["00981A"] == pytest.approx(0.16 / tot, abs=1e-9)
    assert _sum1(tw)


# ───────────────────────── M1：股票腿 de-risk + freed 分配 ─────────────────────────

def test_m1_on_flat_cuts_equity_and_reallocates():
    """M1 ON：股票腿 ×0.75；freed→MMF·2/3+gold·1/3；gold cap .15 溢出→MMF；00864B 不變；不套 M0 帶寬。"""
    eng = _eng_m0m1()
    # 漂移刻意給帶外值，驗證 M1 ON 時「不套 M0 帶寬」＝直接從 TARGET flat-cut（與 drift 無關）
    drift = {"0050": 0.50, "00981A": 0.25, "00991A": 0.05,
             "00635U": 0.05, "00864B": 0.20}
    tw = eng.target_weights(drift, regime_on=True, usd_regime=0.0)
    # 股票腿 = TARGET×0.75（非從 drift）
    assert tw["0050"] == pytest.approx(0.35 * 0.75, abs=1e-9)      # 0.2625
    assert tw["00981A"] == pytest.approx(0.16 * 0.75, abs=1e-9)    # 0.12
    assert tw["00991A"] == pytest.approx(0.16 * 0.75, abs=1e-9)    # 0.12
    # freed = 0.0875+0.04+0.04 = 0.1675；want_gold=0.10+0.1675/3=0.155833 → cap .15（溢 0.005833）
    assert tw["00635U"] == pytest.approx(0.15, abs=1e-9)
    # MMF = 0.115 + 0.1675·2/3 + 0.005833 = 0.2325
    assert tw["MMF"] == pytest.approx(0.2325, abs=1e-9)
    # 00864B 不變
    assert tw["00864B"] == pytest.approx(0.115, abs=1e-9)
    assert _sum1(tw)


def test_m1_freed_split_two_thirds_mmf_one_third_gold():
    """freed 分配比例：黃金未觸 cap 時，gold 增量＝freed/3、MMF 增量＝freed·2/3。

    手法：用較淺的 derisk（0.95，凍結 TARGET 不動）→ freed 小、want_gold 不觸 .15 上界，
    且 M1 ON 權重和恰為 1（凍結 TARGET 加總為 1，無正規化縮放）→ 可直接以未正規化值驗切分。
    """
    cfg = _cfg(["M0", "M1"])
    cfg["M1"]["derisk_action"] = 0.95
    eng = AllocatorEngine(cfg)
    tw = eng.target_weights(DRIFT_INBAND, regime_on=True, usd_regime=0.0)
    freed = (0.35 + 0.16 + 0.16) * (1 - 0.95)          # =0.0335（小，gold 不觸 cap）
    assert (0.10 + freed / 3.0) < 0.15                  # 確認未觸黃金上界
    # gold 增量 = freed/3、MMF 增量 = freed·2/3（2:1）、00864B 不變、和為 1
    assert tw["00635U"] == pytest.approx(0.10 + freed / 3.0, abs=1e-12)
    assert (tw["MMF"] - 0.115) == pytest.approx(2.0 * (tw["00635U"] - 0.10), abs=1e-12)
    assert tw["00864B"] == pytest.approx(0.115, abs=1e-12)
    assert _sum1(tw)


def test_m1_off_equals_m0_when_regime_off():
    """退化：M1 layer 開但 regime_on=False ≡ 純 M0（同 drift 下逐鍵相等）。"""
    eng = _eng_m0m1()
    eng_m0 = _eng_m0()
    drift = dict(DRIFT_INBAND, **{"0050": 0.45})       # 觸 M0 賣分支
    a = eng.target_weights(drift, regime_on=False, usd_regime=0.0)
    b = eng_m0.target_weights(drift, regime_on=False, usd_regime=0.0)
    for k in COLS:
        assert a[k] == pytest.approx(b[k], abs=1e-12)


def test_m1_layer_disabled_ignores_regime_on():
    """退化：M1 layer 未啟用（["M0"]）→ 即使 regime_on=True 也走 M0（不 de-risk）。"""
    eng = _eng_m0()       # 只有 M0
    on = eng.target_weights(DRIFT_INBAND, regime_on=True, usd_regime=0.0)
    off = eng.target_weights(DRIFT_INBAND, regime_on=False, usd_regime=0.0)
    for k in COLS:
        assert on[k] == pytest.approx(off[k], abs=1e-12)
    # 且未把股票腿砍到 0.75
    assert on["0050"] == pytest.approx(0.35, abs=1e-9)


# ───────────────────────── M2：cash-only tilt + 地板 clip ─────────────────────────

def test_m2_weak_usd_shifts_bond_to_mmf():
    """M2 弱美元(−1)：00864B −5pp、MMF +5pp（正規化前），受 00864B 地板 .10 / MMF 上限 .145 clip。"""
    eng = _eng_m0m1m2()
    # 從帶內 M0 基準（00864B=0.115、MMF=0.115）出發；shift=min(.05, .115−.10, .145−.115)=min(.05,.015,.03)=.015
    tw = eng.target_weights(DRIFT_INBAND, regime_on=False, usd_regime=-1.0)
    # 正規化前：864=0.115−0.015=0.10、MMF=0.115+0.015=0.13；其餘 0.35/.16/.16/.10；tot=1.0
    assert tw["00864B"] == pytest.approx(0.10, abs=1e-9)     # 觸地板
    assert tw["MMF"] == pytest.approx(0.13, abs=1e-9)
    assert _sum1(tw)


def test_m2_strong_usd_shifts_mmf_to_bond():
    """M2 強美元(+1)：00864B +5pp、MMF −5pp，受 00864B 上限 .15 / MMF 地板 .095 clip。"""
    eng = _eng_m0m1m2()
    # shift=min(.05, .15−.115, .115−.095)=min(.05,.035,.02)=.02
    tw = eng.target_weights(DRIFT_INBAND, regime_on=False, usd_regime=1.0)
    assert tw["00864B"] == pytest.approx(0.135, abs=1e-9)
    assert tw["MMF"] == pytest.approx(0.095, abs=1e-9)       # 觸地板
    assert _sum1(tw)


def test_m2_disabled_no_tilt():
    """退化：M2 未啟用（["M0","M1"]）→ 即使 usd≠0 現金腿不動 ≡ M2 layer 關。"""
    eng = _eng_m0m1()        # 無 M2
    tw_neg = eng.target_weights(DRIFT_INBAND, regime_on=False, usd_regime=-1.0)
    tw_pos = eng.target_weights(DRIFT_INBAND, regime_on=False, usd_regime=1.0)
    tw_zero = eng.target_weights(DRIFT_INBAND, regime_on=False, usd_regime=0.0)
    for k in COLS:
        assert tw_neg[k] == pytest.approx(tw_zero[k], abs=1e-12)
        assert tw_pos[k] == pytest.approx(tw_zero[k], abs=1e-12)


def test_m2_enabled_flag_gates_layer():
    """雙閘：layer 清單含 M2 但 M2.enabled=False → use_m2=False（短路、不 tilt）。"""
    cfg = _cfg(["M0", "M1", "M2"])
    cfg["M2"]["enabled"] = False
    eng = AllocatorEngine(cfg)
    assert eng.use_m2 is False
    tw_neg = eng.target_weights(DRIFT_INBAND, regime_on=False, usd_regime=-1.0)
    tw_zero = eng.target_weights(DRIFT_INBAND, regime_on=False, usd_regime=0.0)
    for k in COLS:
        assert tw_neg[k] == pytest.approx(tw_zero[k], abs=1e-12)


def test_m2_zero_regime_is_noop():
    """usd_regime=0 → M2 不動（即使 enabled）。"""
    eng = _eng_m0m1m2()
    tw = eng.target_weights(DRIFT_INBAND, regime_on=False, usd_regime=0.0)
    assert tw["00864B"] == pytest.approx(0.115, abs=1e-9)
    assert tw["MMF"] == pytest.approx(0.115, abs=1e-9)


# ───────────────────────── 正規化 / 不變量 ─────────────────────────

@pytest.mark.parametrize("on,usd", [(False, 0.0), (True, 0.0), (False, -1.0),
                                    (False, 1.0), (True, -1.0), (True, 1.0)])
def test_weights_always_sum_to_one(on, usd):
    """任一 (regime_on, usd_regime) 組合 → 6 標的權重和恆為 1、皆 ≥ 0、鍵齊全。"""
    eng = _eng_m0m1m2()
    drift = dict(DRIFT_INBAND, **{"0050": 0.44})       # 含一檔出帶
    tw = eng.target_weights(drift, regime_on=on, usd_regime=usd)
    assert set(tw.keys()) == set(COLS)
    assert all(v >= -1e-12 for v in tw.values())
    assert _sum1(tw)


def test_default_cfg_uses_frozen_constants():
    """空 cfg → 回凍結預設（TARGET/BANDS/EQUITY/SELL_FRAC/A_DERISK）；M1 預設開、M2 預設關。"""
    eng = AllocatorEngine({})
    assert eng.cols == COLS
    assert eng.target == TARGET
    assert eng.sell_fraction == pytest.approx(0.60)
    assert eng.a_derisk == pytest.approx(0.75)
    assert eng.equity == EQUITY
    assert eng.use_m1 is True
    assert eng.use_m2 is False
    assert eng.mode == "allocator"

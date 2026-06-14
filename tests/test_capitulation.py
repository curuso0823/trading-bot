"""
tests/test_capitulation.py
投降感知 regime 分類器單元測試：純邏輯（combine_regime）+ 因果百分位無前視。
不打 FinMind，全用合成資料。
"""
import numpy as np
import pandas as pd
import pytest
from src.signals.capitulation import CapitulationClassifier, _causal_pctl


def _b(vals):
    return pd.Series([bool(v) for v in vals], index=pd.RangeIndex(len(vals)))


def _combine(deep, panic, breadth, margin, foreign, above, falling):
    return CapitulationClassifier.combine_regime(
        _b(deep), _b(panic), _b(breadth), _b(margin), _b(foreign), _b(above), _b(falling))


def test_foreign_alone_does_not_trigger_true_bottom():
    """鐵律：外資 gate 單獨成立（其餘全暗）不可判 true_bottom。"""
    out = _combine(deep=[1], panic=[0], breadth=[0], margin=[0], foreign=[1],
                   above=[0], falling=[0])
    assert not out["true_bottom"].iloc[0]


def test_panic_breadth_deep_triggers():
    """主規則：深度 + panic + breadth（兩強塊）即成立，margin/foreign 非必要。"""
    out = _combine(deep=[1], panic=[1], breadth=[1], margin=[0], foreign=[0],
                   above=[0], falling=[0])
    assert out["true_bottom"].iloc[0]
    assert out["regime"].iloc[0] == "TRUE_BOTTOM"
    assert not out["confirmed"].iloc[0]      # 無弱塊 co-confirm → 僅 tier-1


def test_missing_panic_blocks_true_bottom():
    """panic 暗（breadth+margin+foreign 亮）→ panic 為必要 → 不成立。"""
    out = _combine(deep=[1], panic=[0], breadth=[1], margin=[1], foreign=[1],
                   above=[0], falling=[0])
    assert not out["true_bottom"].iloc[0]
    assert out["alt_3of4"].iloc[0]           # 但對照 3of4 會亮（診斷用）


def test_missing_breadth_blocks_true_bottom():
    """breadth 暗（panic+margin+foreign 亮）→ breadth 為必要 → 不成立。"""
    out = _combine(deep=[1], panic=[1], breadth=[0], margin=[1], foreign=[1],
                   above=[0], falling=[0])
    assert not out["true_bottom"].iloc[0]


def test_confirmed_requires_coconfirm():
    """confirmed tier：主規則成立且 margin 或 foreign 至少一亮 → confirmed。"""
    out = _combine(deep=[1], panic=[1], breadth=[1], margin=[0], foreign=[1],
                   above=[0], falling=[0])
    assert out["true_bottom"].iloc[0]
    assert out["confirmed"].iloc[0]


def test_not_deep_blocks_true_bottom():
    """未達深度前提 → 即使 gate 全亮也不可 true_bottom。"""
    out = _combine(deep=[0], panic=[1], breadth=[1], margin=[1], foreign=[1],
                   above=[0], falling=[0])
    assert not out["true_bottom"].iloc[0]
    assert not out["alt_2of4"].iloc[0]


def test_false_rebound_labels_bear_bounce():
    """收復MA60 + MA60下彎 + 深處熊市 + 無投降 → FALSE_REBOUND、不放行進場。"""
    out = _combine(deep=[1], panic=[0], breadth=[0], margin=[0], foreign=[0],
                   above=[1], falling=[1])
    assert out["regime"].iloc[0] == "FALSE_REBOUND"
    assert out["false_rebound"].iloc[0]
    assert not out["allow_entry"].iloc[0]


def test_true_bottom_overrides_false_rebound_and_allows_entry():
    """真底即使在 MA60 下方也放行（提早解鎖）。"""
    out = _combine(deep=[1], panic=[1], breadth=[1], margin=[1], foreign=[0],
                   above=[0], falling=[1])
    assert out["regime"].iloc[0] == "TRUE_BOTTOM"
    assert out["allow_entry"].iloc[0]


def test_normal_bull_allows_entry():
    """站上 MA60 且 MA60 未下彎 → NORMAL_BULL、放行。"""
    out = _combine(deep=[0], panic=[0], breadth=[0], margin=[0], foreign=[0],
                   above=[1], falling=[0])
    assert out["regime"].iloc[0] == "NORMAL_BULL"
    assert out["allow_entry"].iloc[0]


def test_causal_pctl_no_lookahead():
    """因果百分位無前視：用前綴算出的值，不因之後加資料而改變。"""
    rng = np.random.default_rng(0)
    s = pd.Series(rng.normal(size=300))
    full = _causal_pctl(s, window=60, min_periods=20)
    prefix = _causal_pctl(s.iloc[:200], window=60, min_periods=20)
    # 前 200 筆的因果百分位在「截斷未來」後必須完全相同
    pd.testing.assert_series_equal(full.iloc[:200], prefix, check_names=False)


def test_causal_pctl_value_is_rank_of_current():
    """單調遞增序列 → 當前值永遠是區間最大 → 百分位 = 1.0。"""
    s = pd.Series(np.arange(100, dtype=float))
    p = _causal_pctl(s, window=30, min_periods=5)
    assert np.allclose(p.dropna(), 1.0)


def _series(vals):
    return pd.Series([float(v) for v in vals], index=pd.RangeIndex(len(vals)))


def test_failed_bottom_fires_on_break_below_cap_low():
    """投降低點=10，其後跌破(9)→失敗底觸發；未跌破前不觸發。"""
    close = _series([20, 15, 10, 12, 13, 9, 8])     # idx2=投降低10，idx5=9 破低
    tb = _series([0, 0, 1, 0, 0, 0, 0]).astype(bool)
    out = CapitulationClassifier.failed_bottom_signal(close, tb, window=40, buffer=0.0)
    assert not out.iloc[3] and not out.iloc[4]      # 12/13 未破10 → 不觸發
    assert out.iloc[5] and out.iloc[6]              # 9/8 破10 → 觸發


def test_failed_bottom_silent_on_v_recovery():
    """真 V 底：投降後一路漲不破低 → 永不觸發（對應 2025 抱住反彈）。"""
    close = _series([20, 12, 10, 14, 18, 22, 26])
    tb = _series([0, 0, 1, 0, 0, 0, 0]).astype(bool)
    out = CapitulationClassifier.failed_bottom_signal(close, tb, window=40, buffer=0.0)
    assert not out.any()


def test_failed_bottom_only_within_window():
    """超出觀察窗後即使破低也不觸發（避免無限期掛鉤舊底）。"""
    close = _series([20, 10, 11, 11, 11, 9])        # idx5 破低但距投降(idx1)=4
    tb = _series([0, 1, 0, 0, 0, 0]).astype(bool)
    out = CapitulationClassifier.failed_bottom_signal(close, tb, window=3, buffer=0.0)
    assert not out.iloc[5]                          # 距投降>window → 不觸發


CAP_CFG = {"ma60_falling_days": 20, "deep_high_lookback": 252, "deep_dd": -0.10}


def test_regime_0050_identities():
    """live/回測共用的 regime_0050：代數恆等式必成立（任意資料）。"""
    rng = np.random.default_rng(1)
    close = pd.Series(100 + np.cumsum(rng.normal(0, 1, 400)))
    r = CapitulationClassifier.regime_0050(close, CAP_CFG, ma_n=60)
    fr = r["above_ma60"] & r["ma60_falling"] & r["precond_deep"]
    pd.testing.assert_series_equal(r["false_rebound_0050"], fr, check_names=False)
    abk = r["above_ma60"] & ~r["false_rebound_0050"]
    pd.testing.assert_series_equal(r["allow_block_only"], abk, check_names=False)
    assert (r["allow_block_only"] <= r["above_ma60"]).all()   # 放行 ⊆ 站上MA60


def test_regime_0050_blocks_bear_bounce():
    """熊市假反彈（長空 MA60 下彎 + 深跌 + 末端『短而急』彈站上 MA60）→ false_rebound → 擋掉。"""
    base = np.linspace(260, 100, 288)               # 陡長空，MA60 持續下彎
    bounce = np.linspace(100, 128, 12)              # 短急反彈（12日）站上落後的 MA60，但太短不足以翻轉 MA60
    close = pd.Series(np.concatenate([base, bounce]))
    row = CapitulationClassifier.regime_0050(close, CAP_CFG, ma_n=60).iloc[-1]
    assert bool(row["above_ma60"]) and bool(row["ma60_falling"]) and bool(row["precond_deep"])
    assert bool(row["false_rebound_0050"]) and not bool(row["allow_block_only"])


def test_regime_0050_allows_clean_bull():
    """乾淨多頭（一路漲、MA60 上彎、不深）→ 放行。"""
    close = pd.Series(np.linspace(100, 200, 320))
    row = CapitulationClassifier.regime_0050(close, CAP_CFG, ma_n=60).iloc[-1]
    assert bool(row["above_ma60"]) and not bool(row["ma60_falling"])
    assert not bool(row["false_rebound_0050"]) and bool(row["allow_block_only"])


def test_universe_source_fixed_pins_list(monkeypatch):
    """universe_source=fixed → 廣度代理用 universe_list 釘選清單，不跟 watchlist 漂移。"""
    monkeypatch.setenv("FINMIND_TOKEN", "dummy")
    cfg = {"universe_source": "fixed", "universe_list": ["1111", "2222"]}
    c = CapitulationClassifier(cfg=cfg)
    assert c.universe == ["1111", "2222"]
    cfg_wl = {"universe_source": "watchlist"}
    c2 = CapitulationClassifier(cfg=cfg_wl)
    assert len(c2.universe) > 30          # 跟隨 strategy.yaml watchlist（38+）

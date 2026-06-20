"""tests/test_allocator_vs_sandbox：live AllocatorEngine ≡ 研究沙盒 full_book_backtest（§11.8）。

交叉驗證契約（§11.3）：對任一 (drift_weights, regime_on, usd_regime)，
  AllocatorEngine.target_weights(...) ≡ full_book_backtest.target_weights(..., use_m1, use_m2)
  （abs < 1e-9）＝研究/live 數字不得 drift（決策邏輯逐字移植自沙盒行 126–162）。

載法：比照 notebooks/regime_tilt/band_upper_sweep_realistic.py，用
  importlib.util.spec_from_file_location 載入 full_book_backtest 為模組。
  沙盒在 import 期會讀 data/raw/finmind_cache + data/raw/macro 快取（算 regime/usd 序列）；
  快取缺失 → import 失敗 → pytest.skip 並在 message 標明缺什麼（不可靜默通過）。
  （target_weights 本身是純函數、與快取無關；但模組 import 會觸發快取載入，故以 skip 守缺資料。）

不打 API：沙盒純快取、0 API（檔頭明載）；本測試只呼叫其純函數 target_weights，無網路。
"""
import importlib.util
import os

import pytest

from src.strategy_engines.allocator_engine import AllocatorEngine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FBB_PATH = os.path.join(ROOT, "notebooks", "regime_tilt", "full_book_backtest.py")


def _load_sandbox():
    """importlib 載入 full_book_backtest（比照 band_upper_sweep_realistic.py 載法）。

    沙盒 import 期讀快取（finmind_cache / macro）算 regime/usd 序列；缺資料 → 拋例外，
    由呼叫端轉 pytest.skip（標明缺檔），避免缺快取時靜默 pass。
    """
    spec = importlib.util.spec_from_file_location("fbb_test", _FBB_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def fbb():
    if not os.path.exists(_FBB_PATH):
        pytest.skip(f"找不到研究沙盒：{_FBB_PATH}")
    try:
        return _load_sandbox()
    except FileNotFoundError as e:
        pytest.skip(f"沙盒載入需快取資料但缺檔（finmind_cache / macro）→ skip：{e}")
    except Exception as e:  # 快取壞檔 / 相依缺失等 → skip 並標明，不靜默通過
        pytest.skip(f"沙盒載入失敗（非斷言失敗，標明以利排查）：{type(e).__name__}: {e}")


# ── 涵蓋 M0 三分支 / M1 ON / M2 ±1 的代表性 drift 組合 ──
_DRIFTS = [
    # 帶內（M0 持有）
    {"0050": 0.35, "00981A": 0.16, "00991A": 0.16, "00635U": 0.10, "00864B": 0.115},
    # 0050 超上界（M0 賣 60%）
    {"0050": 0.45, "00981A": 0.16, "00991A": 0.16, "00635U": 0.10, "00864B": 0.115},
    # 00981A 破下界（M0 買回 target）
    {"0050": 0.35, "00981A": 0.10, "00991A": 0.16, "00635U": 0.10, "00864B": 0.115},
    # 多檔同時出帶（賣+買+持有並存）
    {"0050": 0.46, "00981A": 0.16, "00991A": 0.10, "00635U": 0.155, "00864B": 0.14},
    # 非-MMF 偏重（MMF 觸地板）
    {"0050": 0.40, "00981A": 0.22, "00991A": 0.22, "00635U": 0.14, "00864B": 0.14},
    # 整體偏輕（MMF 殘差變大）
    {"0050": 0.32, "00981A": 0.13, "00991A": 0.126, "00635U": 0.085, "00864B": 0.105},
]
_ONS = [False, True]
_USDS = [0.0, -1.0, 1.0]
COLS = ["0050", "00981A", "00991A", "00635U", "00864B", "MMF"]


def _eng(use_m1, use_m2):
    """造對應 layer 開關的 AllocatorEngine（凍結參數），對齊 sandbox use_m1/use_m2。"""
    layers = ["M0"]
    if use_m1:
        layers.append("M1")
    if use_m2:
        layers.append("M2")
    cfg = {"enabled_layers": layers,
           # M2.enabled 必須為 True 才能讓 use_m2 生效（雙閘）；layer 不含 M2 時此旗標無影響。
           "M2": {"enabled": True}}
    return AllocatorEngine(cfg)


@pytest.mark.parametrize("use_m1", [False, True])
@pytest.mark.parametrize("use_m2", [False, True])
@pytest.mark.parametrize("drift", _DRIFTS)
@pytest.mark.parametrize("on", _ONS)
@pytest.mark.parametrize("usd", _USDS)
def test_engine_matches_sandbox(fbb, use_m1, use_m2, drift, on, usd):
    """AllocatorEngine.target_weights ≡ full_book_backtest.target_weights（abs < 1e-9）。"""
    eng = _eng(use_m1, use_m2)
    got = eng.target_weights(dict(drift), regime_on=on, usd_regime=usd)
    want = fbb.target_weights(dict(drift), on, usd, use_m1, use_m2)
    assert set(got.keys()) == set(want.keys()) == set(COLS)
    for k in COLS:
        assert got[k] == pytest.approx(want[k], abs=1e-9), (
            f"key={k} use_m1={use_m1} use_m2={use_m2} on={on} usd={usd} "
            f"drift={drift}: live={got[k]!r} vs sandbox={want[k]!r}")


def test_engine_layers_match_sandbox_args(fbb):
    """sanity：layer 開關正確映射到 sandbox use_m1/use_m2（M1 ON 時兩邊都走 de-risk 分支）。"""
    drift = {"0050": 0.35, "00981A": 0.16, "00991A": 0.16, "00635U": 0.10, "00864B": 0.115}
    # M1 layer 關 → 即使 on=True 兩邊都走 M0（不 de-risk）
    eng_m0 = _eng(use_m1=False, use_m2=False)
    got = eng_m0.target_weights(dict(drift), regime_on=True, usd_regime=0.0)
    want = fbb.target_weights(dict(drift), True, 0.0, False, False)
    for k in COLS:
        assert got[k] == pytest.approx(want[k], abs=1e-9)
    # M1 layer 開 + on=True → 兩邊都 de-risk（0050→0.2625 量級、和為 1）
    eng_m1 = _eng(use_m1=True, use_m2=False)
    got_on = eng_m1.target_weights(dict(drift), regime_on=True, usd_regime=0.0)
    want_on = fbb.target_weights(dict(drift), True, 0.0, True, False)
    for k in COLS:
        assert got_on[k] == pytest.approx(want_on[k], abs=1e-9)

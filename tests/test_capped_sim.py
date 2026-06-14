"""backtest/capped_sim：集中策略回測引擎（合成資料，不打 FinMind）"""
import pandas as pd
from src.backtest.capped_sim import run_capped


def _synthetic(rise=0.004):
    dates = pd.bdate_range("2020-01-01", periods=120)
    rp, rs = [], []
    for k, sid in enumerate(["AAA", "BBB"]):
        base = 100 + k * 10
        for i, d in enumerate(dates):
            px = base * (1 + rise * i)            # 平穩上漲
            rp.append({"date": d, "stock_id": sid, "open": px, "high": px * 1.01,
                       "low": px * 0.99, "close": px})
            rs.append({"date": d, "stock_id": sid, "entry_signal": i == 20, "score": 3.0})
    return pd.DataFrame(rp), pd.DataFrame(rs)


def test_run_capped_returns_full_stats():
    p, s = _synthetic()
    st = run_capped(p, s, ["AAA", "BBB"], "2020-01-01", "2020-12-31", capital=70_000, max_pos=2)
    assert st is not None
    for k in ["annual", "sharpe", "dd", "pf", "win_rate", "n_trades", "per_year",
              "equity_pts", "equity_dates", "gate", "gate_pass", "avg_concurrent"]:
        assert k in st
    assert st["total_return"] > 0          # 上漲市場 → 正報酬


def test_run_capped_respects_max_pos():
    p, s = _synthetic()
    st = run_capped(p, s, ["AAA", "BBB"], "2020-01-01", "2020-12-31", capital=70_000, max_pos=1)
    assert st["avg_concurrent"] <= 1.01     # 並倉上限 1 → 不超過 1


def test_run_capped_empty_universe_returns_none():
    p, s = _synthetic()
    assert run_capped(p, s, ["ZZZ"], "2020-01-01", "2020-12-31") is None


def test_run_capped_sector_max_caps_same_sector():
    """合成股無 sector 對照 → 同歸 OTHER；OTHER 上限 1 → 兩檔同訊號只進一檔。"""
    p, s = _synthetic()
    st = run_capped(p, s, ["AAA", "BBB"], "2020-01-01", "2020-12-31",
                    capital=100_000, max_pos=2, sector_max={"OTHER": 1})
    assert st["avg_concurrent"] <= 1.01
    base = run_capped(p, s, ["AAA", "BBB"], "2020-01-01", "2020-12-31",
                      capital=100_000, max_pos=2)
    assert base["avg_concurrent"] > 1.01      # 無上限時兩檔都進（對照組）

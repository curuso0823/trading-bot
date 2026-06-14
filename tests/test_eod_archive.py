"""utils/eod_archive：當日 state 收盤歸檔（快照 + daily_history）"""
import json
import csv
from src.utils.eod_archive import archive_eod


def _write(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _setup_state(proc):
    proc.mkdir(parents=True, exist_ok=True)
    _write(proc / "paper_account.json", {"cash": 50000, "positions": {"2330": {"quantity": 100, "cost": 100}}})
    _write(proc / "positions.json", {"2330": {"entry_price": 100, "last_price": 110,
                                              "quantity": 100, "entry_date": "2026-06-10", "peak_price": 112}})
    _write(proc / "daily_risk_state.json", {"daily_pnl": 800, "halted": False})
    _write(proc / "day_state.json", {"candidates": [{"stock_id": "2330"}], "filled": ["2330"], "exits": []})


def test_archive_eod_snapshot_and_summary(tmp_path):
    proc, arch = tmp_path / "processed", tmp_path / "archive"
    _setup_state(proc)
    s = archive_eod(70000, "block_only:多頭", lot=1, proc_dir=proc, archive_dir=arch)
    assert s["equity"] == 50000 + 110 * 100          # 現金 + 持倉市值
    assert s["cum_return_pct"] == round((s["equity"] / 70000 - 1) * 100, 2)
    assert s["n_entries"] == 1 and s["n_positions"] == 1 and s["n_exits"] == 0
    assert s["regime"] == "block_only:多頭"
    daydir = arch / s["date"]
    assert (daydir / "summary.json").exists()
    assert (daydir / "positions.json").exists()        # 狀態檔快照
    assert (daydir / "daily_risk_state.json").exists()


def test_daily_history_appends_and_dedups(tmp_path):
    proc, arch = tmp_path / "processed", tmp_path / "archive"
    _setup_state(proc)
    s = archive_eod(70000, "r1", 1, proc, arch)
    archive_eod(70000, "r2", 1, proc, arch)            # 同日重跑 → 去重
    hist = arch / "daily_history.csv"
    assert hist.exists()
    with open(hist, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert sum(1 for r in rows if r["date"] == s["date"]) == 1   # 同日只一列
    assert rows[-1]["regime"] == "r2"                  # 後跑覆蓋


def test_archive_eod_no_state_safe(tmp_path):
    # 0 候選/0 持倉日（block_only 擋下）→ 仍安全產出一列（權益=初始、進出場0）
    proc, arch = tmp_path / "processed", tmp_path / "archive"
    proc.mkdir()
    s = archive_eod(70000, "block_only:假反彈擋下(不進場)", 1, proc, arch)
    assert s["equity"] == 70000 and s["n_entries"] == 0 and s["n_positions"] == 0
    assert (arch / "daily_history.csv").exists()

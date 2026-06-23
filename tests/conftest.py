"""pytest 共用設定：讓 tests 可 import src，並在每個測試前後清掉本地狀態檔。

⚠️ 這些狀態檔與「正式 paper 帳本」同路徑（data/processed/）。per-test 清檔是測試隔離所需，
   但若直接清掉真檔，會在 bot 正 paper-trading 時毀掉 live 帳本
   （2026-06-23 曾因 pytest 清掉 live 0050 部位）。故以 session 級「備份→還原」包住整輪測試：
   session 開始先備份既有 live 檔內容，session 結束後還原，讓 pytest 對 live 帳本零副作用。
"""
import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_STATE = ["paper_account.json", "positions.json", "daily_risk_state.json", "notify_count.json"]
_PROC = Path("data/processed")


@pytest.fixture(scope="session", autouse=True)
def _preserve_live_state():
    """Session 級：備份既有 live 狀態檔內容，session 結束後還原。
    （原本不存在、測試過程新建的檔 → 還原成「不存在」以維持乾淨。）"""
    backup = {f: (_PROC / f).read_bytes() for f in _STATE if (_PROC / f).exists()}
    yield
    for f in _STATE:
        p = _PROC / f
        if f in backup:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(backup[f])
        else:
            p.unlink(missing_ok=True)


@pytest.fixture(autouse=True)
def clean_state():
    for f in _STATE:
        (_PROC / f).unlink(missing_ok=True)
    yield
    for f in _STATE:
        (_PROC / f).unlink(missing_ok=True)

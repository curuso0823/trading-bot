"""pytest 共用設定：讓 tests 可 import src，並在每個測試前後清掉本地狀態檔。"""
import os
import sys
from pathlib import Path
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_STATE = ["paper_account.json", "positions.json", "daily_risk_state.json", "notify_count.json"]


@pytest.fixture(autouse=True)
def clean_state():
    for f in _STATE:
        Path(f"data/processed/{f}").unlink(missing_ok=True)
    yield
    for f in _STATE:
        Path(f"data/processed/{f}").unlink(missing_ok=True)

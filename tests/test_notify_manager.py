"""notify/notify_manager：每日上限節流、批次、緊急不受限、主推失敗轉備援"""
from src.notify.notify_manager import NotifyManager


class FakeChan:
    def __init__(self, ok=True):
        self.ok = ok
        self.sent = []

    def send_text(self, text):
        if self.ok:
            self.sent.append(text)
            return True
        return False


def _entry():
    return [{"stock_id": "x", "name": "", "price": 1.0, "quantity": 1,
             "chip_score": 2.0, "reason": "t"}]


def test_daily_cap_routes_overflow_to_backup():
    p, b = FakeChan(), FakeChan()
    nm = NotifyManager(p, b, daily_cap=3)
    for _ in range(5):
        nm.entries(_entry())
    assert len(p.sent) == 3      # 前 3 則走主推
    assert len(b.sent) == 2      # 超過上限 → 備援


def test_critical_bypasses_cap():
    p, b = FakeChan(), FakeChan()
    nm = NotifyManager(p, b, daily_cap=0)
    nm.halt("test")              # CRITICAL 不受每日上限
    assert len(p.sent) == 1


def test_primary_fail_falls_back():
    p, b = FakeChan(ok=False), FakeChan(ok=True)
    nm = NotifyManager(p, b, daily_cap=8)
    nm.entries(_entry())
    assert len(b.sent) == 1      # 主推失敗 → 備援


def test_entries_batched_into_one():
    p, b = FakeChan(), FakeChan()
    nm = NotifyManager(p, b)
    nm.entries([{"stock_id": "a", "price": 1.0, "quantity": 1},
                {"stock_id": "b", "price": 2.0, "quantity": 2}])
    assert len(p.sent) == 1
    assert "2 檔" in p.sent[0]


def test_system_is_log_only():
    p, b = FakeChan(), FakeChan()
    nm = NotifyManager(p, b)
    nm.system("startup")
    assert len(p.sent) == 0 and len(b.sent) == 0


def test_error_cap_then_backup():
    p, b = FakeChan(), FakeChan()
    nm = NotifyManager(p, b, daily_cap=8, error_cap=2)
    for _ in range(4):
        nm.error(ValueError("boom"), "ctx")
    assert len(p.sent) == 2      # 前 2 則錯誤走主推
    assert len(b.sent) == 2      # 其餘進備援

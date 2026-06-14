"""
utils/singleton.py
單例鎖：確保同一時間只有一個 bot 實例在跑。
用 OS 級檔案鎖（Windows msvcrt / POSIX fcntl）→ 行程死亡時 OS 自動釋放鎖，
無 stale-PID 問題。背景常駐 + 自動重啟情境下，防止「孤兒舊進程 + 新進程」
雙開造成重複下單（Windows venv 必為兩進程，Task Scheduler 停止若漏殺子進程，
舊實例可能殘留 → 此鎖讓新實例偵測到後自行退出）。
"""
import os
from pathlib import Path

LOCK_PATH = "data/processed/bot.lock"
_lock_handle = None  # 保持檔案 handle 存活以持有鎖（勿被 GC 回收）


def acquire_singleton_lock(path: str = LOCK_PATH) -> bool:
    """
    嘗試取得單例鎖。成功回傳 True（鎖持有至行程結束，OS 自動釋放）；
    已被另一實例持有回傳 False。
    """
    global _lock_handle
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    f = open(p, "a+")
    f.seek(0)  # 確保兩實例都鎖同一個 byte(0)，否則 a+ 末端位置不同會各鎖各的
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _lock_handle = f  # 持有鎖
    return True

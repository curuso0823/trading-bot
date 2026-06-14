"""探針：在無主控台(sys.stdout=None, 模擬 pythonw)環境下逐步建構，寫檔記錄卡點。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

log = open("data/processed/probe.txt", "w", encoding="utf-8")
def w(m):
    log.write(m + "\n"); log.flush()

try:
    sys.stdout = None
    sys.stderr = None
    w("start (stdout=None)")
    from src.utils.logger import setup_logger
    setup_logger(); w("setup_logger OK")
    from src.signals.score_engine import ScoreEngine
    w("import ScoreEngine OK")
    se = ScoreEngine(); w("ScoreEngine() OK")
    from src.data.fetcher import FugleFetcher
    w("import FugleFetcher OK")
    f = FugleFetcher(); w("FugleFetcher() OK")
    w("ALL CONSTRUCTED OK")
except BaseException as e:
    import traceback
    w("EXCEPTION: " + repr(e))
    w(traceback.format_exc())
finally:
    log.close()

"""
notebooks/timing_probe.py
量測 live 關鍵路徑延遲：選股(TA掃描+籌碼評分) 與 下單熱路徑(報價+ATR+風控)。
用法：.venv\\Scripts\\python.exe notebooks\\timing_probe.py
注意：會實打 FinMind/Fugle（約 50 請求），免費額度足夠但會消耗當日配額。
"""
import os
import sys
import time
import datetime as dt
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.signals.score_engine import ScoreEngine
from src.data.fetcher import FugleFetcher, FinMindFetcher
from src.utils.helpers import atr_trailing_pct
from src.risk.risk_guard import RiskGuard

avg = lambda x: sum(x) / len(x) if x else 0.0


def main():
    print("=== 選股 + 策略判斷（pre_market，08:50）— 平行+adjust=False+trail_pct預算 ===")
    se = ScoreEngine()
    # lookback=118 強制冷快取（同日重跑用 120 會命中剛建的快取，量不到真實延遲）
    t = time.perf_counter(); ta = se.run_ta_scan(lookback_days=118); ta_s = time.perf_counter() - t
    n = max(len(se._resolve_universe()), 1)
    print(f"TA 掃描 {n} 檔（cold）：{ta_s:.1f}s（{ta_s/n*1000:.0f} ms/檔），通過 {len(ta)} 檔")
    t = time.perf_counter(); df = se.run_chip_scoring(ta) if ta else None
    chip_s = time.perf_counter() - t
    print(f"籌碼評分 {len(ta)} 檔：{chip_s:.1f}s")
    print(f"→ 選股總延遲：{ta_s + chip_s:.1f}s（改善前 ~323s）")

    print("\n=== 下單熱路徑（market_open，每檔）— ATR 已於掃描預算、不再抓 ===")
    fugle = FugleFetcher(); rg = RiskGuard(50_000)
    samples = ["2882", "2412", "1216", "2603", "5880"]
    qt, rt = [], []
    for sid in samples:
        t = time.perf_counter()
        try: fugle.get_realtime_quote(sid)
        except Exception: pass
        qt.append(time.perf_counter() - t)
        t = time.perf_counter(); rg.can_enter(sid, 100.0, 1, 0); rt.append(time.perf_counter() - t)
    print(f"Fugle 即時報價：avg {avg(qt)*1000:.0f} ms")
    print(f"風控 can_enter：avg {avg(rt)*1000:.2f} ms")
    print(f"→ 單檔下單路徑(報價+風控)：avg {(avg(qt)+avg(rt))*1000:.0f} ms（改善前 ~1717ms，省掉 ATR 抓取）")


if __name__ == "__main__":
    main()

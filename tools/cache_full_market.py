"""
tools/cache_full_market.py
全市場 FinMind 快取建構器（背景常駐，自我限速）。

目的：把全市場 ~1700 檔的 4 個 FinMind 資料集抓進 data/raw/finmind_cache，
      供日後離線回測 / 擴大選股研究，免再燒 API 額度。
      （免費 register 層：600 次/小時。bulk by-date 已實測被擋，只能逐檔抓。）

設計：
  - 限速：每「滾動小時」≤ MAX_PER_HOUR（預設 550，留 headroom 給 live bot）。
  - 安靜窗：每日 QUIET_START~QUIET_END（預設 08–10 台北時）暫停，保護 live bot 盤前選股/開盤的 FinMind 用量。
  - 可續跑：已快取檔（FinMindFetcher._cache_path 存在）直接跳過；查無資料的 (股,集) 記入 no_data 不重抓。
  - 狀態持久化：data/processed/cache_builder_state.json（滾動小時時間戳 + no_data + 計數）→ 重啟續跑。
  - 日期區間固定 START~END（對齊 capped_sim.build_signals 預設）→ 抓完即可被現有回測程式直接命中快取。
  - 資料集分輪抓（價量→除權息→法人→融資）：先讓「全市場都有價量」最大化早期可用性。

用法：
  nohup .venv/bin/python tools/cache_full_market.py > logs/cache_builder.out 2>&1 &
監看：
  tail -f logs/cache_builder.out
停止：
  pkill -f cache_full_market.py
"""
import os
import sys
import json
import time
import argparse
from collections import deque
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pytz
from src.data.fetcher import FinMindFetcher
from src.data.universe import fetch_tw_stock_universe
from src.backtest.capped_sim import FULL_UNIVERSE

TZ = pytz.timezone("Asia/Taipei")
STATE_FILE = Path("data/processed/cache_builder_state.json")


def log(msg: str):
    print(f"{datetime.now(TZ).strftime('%F %T')} | {msg}", flush=True)


class RateLimiter:
    """滾動小時限速：每 3600 秒最多 max 次 API 呼叫（含跨重啟持久化的時間戳）。"""

    def __init__(self, max_per_hour: int, ts: list):
        self.max = max_per_hour
        self.calls = deque(float(t) for t in ts)

    def _prune(self, now):
        while self.calls and now - self.calls[0] > 3600:
            self.calls.popleft()

    def wait_for_slot(self):
        while True:
            now = time.time()
            self._prune(now)
            if len(self.calls) < self.max:
                return
            sleep_for = 3600 - (now - self.calls[0]) + 1
            log(f"⏳ 滾動小時已達上限 {self.max}，睡 {sleep_for/60:.1f} 分鐘等額度釋放")
            time.sleep(max(2, sleep_for))

    def record(self):
        self.calls.append(time.time())

    def count_last_hour(self):
        self._prune(time.time())
        return len(self.calls)


def wait_quiet(qs: int, qe: int):
    """安靜窗（保護 live bot 盤前/開盤的 FinMind 用量）：台北時 [qs, qe) 內暫停到 qe:00。"""
    while True:
        now = datetime.now(TZ)
        if qs <= now.hour < qe:
            target = now.replace(hour=qe % 24, minute=0, second=0, microsecond=0)
            secs = (target - now).total_seconds()
            if secs <= 0:
                return
            log(f"🤫 安靜窗（保護 live bot {qs:02d}:00–{qe:02d}:00）→ 睡 {secs/60:.0f} 分鐘至 {qe:02d}:00")
            time.sleep(min(secs, 1800))  # 最多睡 30 分鐘後重新判斷（避免時鐘漂移卡死）
        else:
            return


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(limiter: RateLimiter, no_data: set, counts: dict):
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "updated": datetime.now(TZ).strftime("%F %T"),
            "call_ts": list(limiter.calls),
            "no_data": sorted(no_data),
            "counts": counts,
        }, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log(f"狀態存檔失敗：{e}")


def build_stock_order() -> list[str]:
    """全市場清單（上市+上櫃 4 碼普通股），已知流動性標的優先排前面。"""
    df = fetch_tw_stock_universe()
    ids = [str(s) for s in df["stock_id"].tolist()] if not df.empty else []
    seen, ordered = set(), []
    for s in [str(x) for x in FULL_UNIVERSE] + ids:   # 先放 FULL_UNIVERSE（多已快取，快速跳過＋確保重點先完成）
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-per-hour", type=int, default=550)
    ap.add_argument("--quiet-start", type=int, default=8)   # 台北時 08:00 起暫停
    ap.add_argument("--quiet-end", type=int, default=10)    # 至 10:00 恢復
    ap.add_argument("--start-date", default="2018-01-01")   # 對齊 capped_sim.build_signals 預設
    ap.add_argument("--end-date", default="2025-12-31")
    args = ap.parse_args()

    S, E = args.start_date, args.end_date
    f = FinMindFetcher()
    state = load_state()
    limiter = RateLimiter(args.max_per_hour, state.get("call_ts", []))
    no_data = set(tuple(x.split("|")) for x in state.get("no_data", []) if "|" in x)
    counts = state.get("counts", {"fetched": 0, "skipped_cached": 0, "empty": 0})

    stocks = build_stock_order()
    datasets = [
        ("TaiwanStockPrice", lambda sid: f.get_daily_price(sid, S, E, adjust=False)),
        ("TaiwanStockDividendResult", lambda sid: f.get_dividend_result(sid, S, E)),
        ("TaiwanStockInstitutionalInvestorsBuySell", lambda sid: f.get_institutional(sid, S, E)),
        ("TaiwanStockMarginPurchaseShortSale", lambda sid: f.get_margin(sid, S, E)),
    ]
    total_targets = len(stocks) * len(datasets)
    log(f"啟動：全市場 {len(stocks)} 檔 × {len(datasets)} 集 = {total_targets} 目標檔；"
        f"區間 {S}~{E}；限速 {args.max_per_hour}/時；安靜窗 {args.quiet_start:02d}–{args.quiet_end:02d}")
    log(f"續跑狀態：已抓 {counts['fetched']}、跳過(已快取) {counts['skipped_cached']}、無資料 {len(no_data)}")

    empty_streak = 0
    done = 0
    for ds_name, fn in datasets:
        for sid in stocks:
            done += 1
            path = f._cache_path(ds_name, sid, S, E)
            if path.exists():
                counts["skipped_cached"] += 1
                continue
            if (sid, ds_name) in no_data:
                continue

            wait_quiet(args.quiet_start, args.quiet_end)
            limiter.wait_for_slot()
            try:
                df = fn(sid)        # 命中則回 df 並寫快取；內含 0.5s sleep + 3 retry
            except Exception as e:
                df = None
                log(f"例外 {sid}/{ds_name}：{e}")
            limiter.record()

            if df is None or len(df) == 0:
                counts["empty"] += 1
                no_data.add((sid, ds_name))
                empty_streak += 1
                # 連續多檔 price 落空 → 疑似觸發限流/網路問題 → 退避 10 分鐘
                if ds_name == "TaiwanStockPrice" and empty_streak >= 15:
                    log(f"⚠️ 連續 {empty_streak} 檔價量落空（疑限流/網路）→ 退避 10 分鐘")
                    time.sleep(600)
                    empty_streak = 0
            else:
                counts["fetched"] += 1
                empty_streak = 0

            if counts["fetched"] % 25 == 0 and (df is not None and len(df)):
                save_state(limiter, no_data, counts)
                pct = done / total_targets * 100
                log(f"進度 {done}/{total_targets} ({pct:.1f}%) | 本輪集 {ds_name} | "
                    f"已抓 {counts['fetched']} 跳過 {counts['skipped_cached']} 無資料 {len(no_data)} | "
                    f"近一小時用量 {limiter.count_last_hour()}/{args.max_per_hour} | 最新 {sid}")
        log(f"✅ 資料集完成一輪：{ds_name}")
        save_state(limiter, no_data, counts)

    save_state(limiter, no_data, counts)
    log(f"🎉 全部完成：抓取 {counts['fetched']}、已快取跳過 {counts['skipped_cached']}、無資料 {len(no_data)}")


if __name__ == "__main__":
    main()

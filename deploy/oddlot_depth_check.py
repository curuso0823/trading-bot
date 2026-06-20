"""
deploy/oddlot_depth_check.py — Phase C 上線前「盤中零股深度」複驗（READ-ONLY、絕不下單）。

由 launchd（com.tradingbot.oddlotcheck）於交易日盤中（預設週一 10:00 Taipei）自動執行：
對 6 資產組合的 5 檔 ETF（MMF 合成、跳過）抓即時零股簿，評估參考組合規模（~NT$100k）下
各腿小額零股單的可成交性——尤其週六快照偏薄的 00864B（L1 ~106 股）/00635U。
結果寫 logs/oddlot_depth_<date>.log + stdout（launchd 收）+ best-effort LINE 一行 verdict。

純驗證、不碰 live/帳本/config；Fugle 即時報價（read-only）。可重複跑（每週一），驗完即可移除：
  launchctl bootout gui/$(id -u)/com.tradingbot.oddlotcheck
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import pytz

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

from src.data.fetcher import FugleFetcher                                  # noqa: E402
from src.execution.odd_lot_fill import odd_lot_buy_fill, parse_odd_book, parse_odd_ladder  # noqa: E402

TZ = pytz.timezone("Asia/Taipei")
SYMS = ["0050", "00981A", "00991A", "00635U", "00864B"]   # MMF 合成、不在交易所
WEIGHTS = {"0050": 0.35, "00981A": 0.16, "00991A": 0.16, "00635U": 0.10, "00864B": 0.115}
BOOK_NT = 100_000                                          # 參考組合規模（估各腿想買股數）
MAX_IMPACT = 0.004                                         # 與 PortfolioRebalancer 同口徑


def _session_open(now: datetime) -> bool:
    """盤中零股撮合時段（交易日 09:10–13:30 Taipei；不判國定假，休市時簿為空會自然反映）。"""
    return now.weekday() < 5 and (9, 10) <= (now.hour, now.minute) <= (13, 30)


def main() -> None:
    now = datetime.now(TZ)
    is_open = _session_open(now)
    head = f"=== 盤中零股深度複驗 {now:%Y-%m-%d %H:%M} (Taipei) | session_open={is_open} ==="
    lines = [head]
    verdict = []
    fugle = FugleFetcher()

    for sym in SYMS:
        try:
            q = fugle.get_realtime_quote(sym, odd=True) or {}
        except Exception as e:                            # noqa: BLE001
            lines.append(f"{sym}: 取報價失敗 {e}")
            verdict.append(f"{sym}=ERR")
            continue
        bid, ask, l1depth = parse_odd_book(q)
        lp = q.get("lastPrice")
        try:
            px = float(lp) if lp else (ask or bid or 0.0)
        except (TypeError, ValueError):
            px = ask or bid or 0.0
        want = int(round(WEIGHTS[sym] * BOOK_NT / px)) if px > 0 else 0
        asks = parse_odd_ladder(q, levels=5)
        fill = odd_lot_buy_fill(want, asks, max_impact_pct=MAX_IMPACT) if (asks and want > 0) else None
        if fill is not None:
            filled, vwap, remaining = fill
            ok = filled >= want
            verdict.append(f"{sym}={'OK' if ok else 'THIN'}")
            lines.append(
                f"{sym}: last {px} bid {bid} ask {ask} L1 {l1depth}股 | 想買 {want}股 → "
                f"成交 {filled}/{want} @{vwap} 餘 {remaining} {'✅可成交' if ok else '🟡薄帳/部分'}")
        else:
            verdict.append(f"{sym}={'NOBOOK' if is_open else 'CLOSED'}")
            lines.append(
                f"{sym}: last {px} bid {bid} ask {ask} L1 {l1depth}股 | 無零股簿"
                f"（{'盤中無量' if is_open else '休市/盤前→須交易日盤中再跑'}）")

    report = "\n".join(lines)
    print(report)
    try:
        p = _ROOT / "logs" / f"oddlot_depth_{now:%Y%m%d}.log"
        p.parent.mkdir(exist_ok=True)
        p.write_text(report + "\n", encoding="utf-8")
        print(f"[written] {p}")
    except Exception as e:                                # noqa: BLE001
        print(f"[warn] 寫 log 失敗: {e}")
    try:                                                  # best-effort 通知（不阻斷）
        from src.notify.notify_factory import make_notifier
        make_notifier().system(f"[零股深度複驗 {now:%m-%d %H:%M}] " + " ".join(verdict))
    except Exception as e:                                # noqa: BLE001
        print(f"[warn] 通知略過: {e}")


if __name__ == "__main__":
    main()

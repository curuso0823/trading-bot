"""
main.py
排程主程式入口
APScheduler 控制每日流程：盤前選股 → 開盤下單 → 盤中監控 → 盤後報表
"""
import sys
import json
import signal
from pathlib import Path
from datetime import datetime
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from src.utils.logger import setup_logger
from src.utils.helpers import (load_settings, load_config, is_trading_day, lot_size,
                               exec_slippage, calc_trade_cost)
from src.utils.singleton import acquire_singleton_lock
from src.signals.score_engine import ScoreEngine
from src.strategy_engines import make_engine, BenchmarkEngine
from src.execution.broker_factory import make_broker
from src.execution.order_manager import OrderManager, PositionManager
from src.risk.risk_guard import RiskGuard
from src.notify.notify_factory import make_notifier
from src.data.fetcher import FugleFetcher
from src.utils.slippage_logger import record_slippage
from src.utils.eod_archive import archive_eod
from src.execution.odd_lot_fill import parse_odd_ladder, odd_lot_buy_fill

# ──────────────────────────────────────────────────────
# 全域元件（單例）
# ──────────────────────────────────────────────────────
setup_logger()

broker = make_broker()
position_mgr = PositionManager()
notifier = make_notifier()
score_engine = ScoreEngine()
fugle = FugleFetcher()

# 策略路由（settings.strategy.mode）：active=現行籌碼策略 / benchmark=0050 波動目標對照組。
# 預設 active；未知值 fail-safe 回 active（make_engine 內保護）。active 引擎薄包裝 score_engine（不重建資源）。
STRATEGY_MODE = str((load_settings().get("strategy", {}) or {}).get("mode", "active")).lower()
strategy_engine = make_engine(score_engine)

# 初始資金從帳戶餘額取得（啟動時讀一次）
TOTAL_CAPITAL = 0.0

TZ = pytz.timezone("Asia/Taipei")

# 儲存今日候選清單（盤前產出，開盤時使用）+ 今日出場（延到每日摘要批次推）
_today_candidates = []
_today_exits = []
_today_intended = []   # 今日嘗試進場的單（盤後零股補單用）
_today_filled = set()  # 今日「曾成交」的 stock_id（補單用 intended−filled；避免把盤中買後又賣的誤判為未成交）
_today_oddlot_repushed = []  # 盤中因零股賣一深度不足『掛不到』→ 轉盤後補單的 sid（量化零股盤中摩擦）
_risk_guard = None

# #6：當日 state 持久化（盤中重啟才不會遺失候選/補單追蹤）
_DAY_STATE_FILE = Path("data/processed/day_state.json")


def _save_day_state():
    """持久化當日 state（candidates/intended/filled/exits）→ 盤中重啟可復原。"""
    try:
        _DAY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_DAY_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": datetime.now(TZ).strftime("%Y-%m-%d"),
                       "candidates": _today_candidates, "intended": _today_intended,
                       "filled": list(_today_filled), "exits": _today_exits,
                       "oddlot_repushed": _today_oddlot_repushed},
                      f, ensure_ascii=False, default=str)
    except Exception as e:
        logger.warning(f"當日 state 存檔失敗：{e}")


def _load_day_state():
    """啟動時若 day_state 為『今日』→ 復原當日 state（盤中重啟續跑，不重置候選/補單追蹤）。"""
    global _today_candidates, _today_intended, _today_filled, _today_exits, _today_oddlot_repushed
    try:
        if not _DAY_STATE_FILE.exists():
            return
        with open(_DAY_STATE_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("date") != datetime.now(TZ).strftime("%Y-%m-%d"):
            return  # 昨日檔 → 不復原（讓今日 pre_market 重新產）
        _today_candidates = d.get("candidates", [])
        _today_intended = d.get("intended", [])
        _today_filled = set(d.get("filled", []))
        _today_exits = d.get("exits", [])
        _today_oddlot_repushed = d.get("oddlot_repushed", [])
        logger.info(f"當日 state 復原：候選 {len(_today_candidates)}、嘗試 {len(_today_intended)}、"
                    f"曾成交 {len(_today_filled)}（盤中重啟續跑）")
    except Exception as e:
        logger.warning(f"當日 state 復原失敗：{e}")


def _reconcile_positions():
    """#5：啟動時對帳 broker 持倉 vs PositionManager（兩帳本非原子，崩潰/重啟於 enter↔add 之間可能不一致）。
    - broker 有、PositionManager 無 → 孤兒（現金已扣卻無人監控停損）→ 補進 PositionManager 納入風控。
    - PositionManager 有、broker 無 → 殘留（broker 已賣/未成交）→ 自 PositionManager 移除。
    註：補回的部位 entry_date 記為今日（孤兒多為同日剛進場 → 通常正確；跨日罕見情形 hold_days 會重算）。"""
    try:
        bpos = {p["stock_id"]: p for p in broker.get_positions()}
    except Exception as e:
        logger.warning(f"對帳：取 broker 持倉失敗，跳過 | {e}")
        return
    pm = set(position_mgr._positions.keys())
    bset = set(bpos.keys())
    for sid in bset - pm:           # 孤兒 → 補進
        b = bpos[sid]
        position_mgr.add(sid, float(b.get("cost", 0) or 0), int(b.get("quantity", 0) or 0),
                         "reconciled", None, trail_pct=None)
        logger.warning(f"🔧 對帳：補回孤兒部位 {sid}（broker 有、PositionManager 無）→ 納入風控監控")
    for sid in pm - bset:           # 殘留 → 移除
        position_mgr.remove(sid)
        logger.warning(f"🔧 對帳：移除殘留部位 {sid}（PositionManager 有、broker 無）")
    if bset == pm:
        logger.info(f"對帳：雙帳本一致（{len(pm)} 檔）")


# ──────────────────────────────────────────────────────
# 排程任務
# ──────────────────────────────────────────────────────

def _within_session() -> bool:
    """現在(台北)是否在交易時段內（schedule.market_open ~ market_close）。零padding HH:MM 可直接字串比較。"""
    sch = load_settings()["schedule"]
    now = datetime.now(TZ).strftime("%H:%M")
    return sch["market_open"] <= now <= sch["market_close"]


def pre_market_task():
    """
    08:50 盤前任務：
    - 更新帳戶資金
    - 執行 ScoreEngine 產出今日候選清單
    - 推送候選摘要到 Telegram
    """
    global _today_candidates, _today_exits, _today_intended, _today_filled, _risk_guard, TOTAL_CAPITAL
    global _today_oddlot_repushed

    if not is_trading_day():
        logger.info("今日非交易日，跳過")
        return

    _today_candidates = []   # #1：開頭就重置（避免 run() 失敗時殘留昨日候選 → 開盤用過期名單下單）
    _today_exits = []        # 跨日重置
    _today_intended = []     # 跨日重置（盤後零股補單用）
    _today_filled = set()    # 跨日重置
    _today_oddlot_repushed = []   # 跨日重置（零股盤中摩擦計數）
    _save_day_state()

    logger.info("=== 盤前選股開始 ===")

    try:
        # 更新資金
        TOTAL_CAPITAL = broker.get_balance()
        if TOTAL_CAPITAL <= 0:
            logger.warning("無法取得帳戶餘額，使用預設值 50,000")
            TOTAL_CAPITAL = 50_000

        _risk_guard = RiskGuard(total_capital=TOTAL_CAPITAL)

        # 執行選股
        df = score_engine.run()
        _today_candidates = df.to_dict("records") if not df.empty else []
        _save_day_state()

        # 儲存候選清單
        if not df.empty:
            score_engine.save_candidates(df)

        # 盤前為低優先 → 只記 log（不佔 LINE 額度），明細併入開盤/每日摘要
        notifier.system(
            f"盤前選股完成：候選 {len(_today_candidates)} 檔，資金 {TOTAL_CAPITAL:,.0f}，"
            f"風控 {'熔斷中' if _risk_guard.get_status()['halted'] else '正常'}"
        )

        logger.info(f"盤前選股完成：{len(_today_candidates)} 檔候選")

    except Exception as e:
        logger.exception("盤前任務失敗")
        notifier.error(e, "pre_market_task")


def market_open_task():
    """
    開盤下單任務（時間由 config schedule.market_open 決定）：
    - 依候選清單掛進場單（盤中零股，09:10 首撮前掛妥）
    - 每檔都通過 RiskGuard 核准
    """
    global _today_intended, _today_filled, _today_oddlot_repushed
    if not is_trading_day() or not _today_candidates:
        return

    if Path("data/processed/HALT").exists():
        logger.warning("HALT 旗標存在 → 暫停進場（移除旗標後恢復）")
        notifier.system("HALT 旗標存在，本日暫停進場")
        return

    logger.info("=== 開盤下單開始 ===")
    order_mgr = OrderManager(broker)
    slip = exec_slippage()
    _tcfg = load_config().get("trading", {})
    odd_fill_on = bool(_tcfg.get("odd_lot_fill_model", True))   # 零股成交不確定性開關
    odd_book_levels = int(_tcfg.get("odd_lot_book_levels", 5))  # book-walk 解析賣方階梯檔數
    odd_max_impact = float(_tcfg.get("odd_lot_max_impact_pct", 0.0))  # book-walk 價格衝擊上限
    # #2/#7：以『可用現金』為配重基準並逐筆遞減（對齊回測 vectorbt percent-of-cash；
    #        刻意用現金而非權益，與回測同口徑，非 bug）。
    available = TOTAL_CAPITAL
    entered = []  # 批次進場，收齊後一則推播

    for candidate in _today_candidates:
        sid = candidate["stock_id"]
        score = candidate.get("chip_score", 0)
        reason = candidate.get("reason", "")
        if sid in position_mgr._positions:   # 已持有→不重複進場（與回測 c not in held 同口徑；進場一次、移動停損出場）
            continue

        try:
            # #10：用整股即時報價當價格參考（零股首撮前無價；整股已開盤有價且≈零股價）
            quote = fugle.get_realtime_quote(sid)
            ref = quote.get("lastPrice") or candidate.get("close", 0)  # Fugle 回 lastPrice
            if not ref:
                continue
            price = round(ref * (1 + slip), 2)   # #3：買進滑價（與回測同口徑），預算/風控基準價

            # #2：方式A 反波動配重，但對『剩餘可用資金』收 size_pct（避免全用全額 → 過度配置/集中）
            size_pct = candidate.get("size_pct", 0.30)
            capital_per_pos = max(0.0, available) * size_pct
            quantity = max(1, int(capital_per_pos / (price * lot_size())))

            # 風控核准（以預算量/基準價判斷曝險上限）
            current_count = len(position_mgr.summary())
            ok_enter, reject_reason = _risk_guard.can_enter(sid, price, quantity, current_count)

            if not ok_enter:
                logger.info(f"進場拒絕 | {sid} | {reject_reason}")
                continue

            # A1+Q2：trail_pct 已於 pre_market 掃描時用同份日線算好（candidate 帶入）。
            trail_pct = candidate.get("trail_pct")

            # 記錄嘗試進場（盤後補單用：記想買量 quantity + 盤中已成交量 filled_qty，盤後補到 target）
            intended_rec = {"stock_id": sid, "price": price, "quantity": quantity,
                            "reason": reason, "score": score, "trail_pct": trail_pct,
                            "size_pct": size_pct, "filled_qty": 0}
            _today_intended.append(intended_rec)

            # ── 零股部分成交 + 吃多檔(book-walk)：吃賣一起到價格衝擊上限，回 (filled, vwap, remaining) ──
            #    吃滿→全量成交；薄帳→部分成交(餘量轉盤後深簿補滿)；完全吃不到→盤中不成交→全量轉盤後。
            #    無零股簿(首撮前/stub/API失敗) → fallback 舊行為(假設滑價 price 成交，不擋單)。
            fill_qty = quantity
            if odd_fill_on and lot_size() == 1:
                asks = parse_odd_ladder(fugle.get_realtime_quote(sid, odd=True), odd_book_levels)
                fill = odd_lot_buy_fill(quantity, asks, max_impact_pct=odd_max_impact)
                if fill is not None:
                    fq, vwap, remaining = fill
                    if fq == 0:
                        logger.info(f"零股盤中吃不到（賣方深度不足 < 想買 {quantity} 股）→ 全量轉盤後補單 | {sid}")
                        _today_oddlot_repushed.append(sid)   # 量化零股盤中摩擦
                        record_slippage(fugle, sid, ref, "buy")  # 仍量測真實薄帳
                        continue
                    fill_qty, price = fq, vwap   # 以實際成交量 + VWAP 成交（取代假設滑價）
                    if remaining > 0:
                        _today_oddlot_repushed.append(sid)
                        logger.info(f"零股部分成交 {fq}/{quantity} 股（餘 {remaining} 轉盤後補滿）| {sid} @VWAP {vwap}")

            # 下單（實際成交量）
            result = order_mgr.enter(sid, price, fill_qty, reason, score)
            if "error" not in result:
                position_mgr.add(sid, price, fill_qty, reason, score, trail_pct=trail_pct)
                intended_rec["filled_qty"] = fill_qty
                if fill_qty >= quantity:
                    _today_filled.add(sid)  # 全量成交→盤後不補（部分成交者留待盤後補滿）
                available -= price * fill_qty * lot_size()   # #2：遞減可用資金（用實際成交量）
                entered.append({"stock_id": sid, "name": "", "price": price,
                                "quantity": fill_qty, "chip_score": score, "reason": reason})
                record_slippage(fugle, sid, ref, "buy")  # 量測真實零股滑價（用原始報價 ref）

        except Exception as e:
            logger.exception(f"開盤下單失敗 | {sid}")
            notifier.error(e, f"market_open_task | {sid}")

    _save_day_state()              # #6：持久化當日 intended/filled
    notifier.entries(entered)  # 批次：今日進場 N 檔 → 1 則


def intraday_monitor_task():
    """
    盤中監控（只在 market_open~market_close 之間，每 N 分鐘）：
    更新持倉價格 → 統一出場判斷 → 風控狀態。收盤後不動作（避免對停盤報價誤判/誤出場）。
    """
    if not is_trading_day() or not _within_session():
        return
    if _risk_guard is None:   # #4 防呆：重啟漏跑 pre_market 時（main 啟動已預設，雙保險）
        return

    positions = position_mgr.summary()
    if not positions:
        return

    order_mgr = OrderManager(broker)

    # 取得最新價格
    current_prices = {}
    for pos in positions:
        sid = pos["stock_id"]
        quote = fugle.get_realtime_quote(sid)
        if quote.get("lastPrice"):
            current_prices[sid] = quote["lastPrice"]

    position_mgr.update_prices(current_prices)
    slip = exec_slippage()

    # 統一出場判斷（移動停損/停利/持有上限，與回測同口徑）
    positions = position_mgr.summary()  # 取更新後的 last/peak/hold_days
    crit_exits = []  # 緊急出場(停損/移動停損)→即時批次推；停利/到期延到每日摘要
    for sid, reason in _risk_guard.check_exits(positions):
        pos_info = next((p for p in positions if p["stock_id"] == sid), {})
        if pos_info.get("hold_days", 0) < 1:
            continue  # 零股不可當沖（T+1）：同日進場不可當日賣出
        ref = current_prices.get(sid) or pos_info.get("last_price", 0)
        if ref <= 0:
            continue  # 無報價，下一輪再處理
        price = round(ref * (1 - slip), 2)   # #3：賣出滑價（與回測同口徑，取代固定 ×0.99）
        pnl_pct = pos_info.get("pnl_pct", 0)
        qty = pos_info.get("quantity", 1)
        entry = pos_info.get("entry_price", price)

        order_mgr.exit(sid, price, qty, reason)
        position_mgr.remove(sid)

        rec = {"stock_id": sid, "reason": reason, "pnl_pct": pnl_pct, "price": price}
        _today_exits.append(rec)
        if reason in ("stop_loss", "trailing_stop"):
            crit_exits.append(rec)

        # #8：已實現損益計入買賣手續費+交易稅（熔斷判斷用淨額，不再用毛額）
        costs = calc_trade_cost(entry, qty, "buy")["total_cost"] + calc_trade_cost(price, qty, "sell")["total_cost"]
        pnl_amount = (price - entry) * qty * lot_size() - costs
        _risk_guard.record_trade_result(pnl_amount)

        if _risk_guard.get_status()["halted"]:
            notifier.halt(_risk_guard.get_status()["halt_reason"])
            # #13：熔斷時若設定要求 → 緊急清倉（否則僅停新單、既有部位續由移動停損管理）
            if load_settings()["risk"].get("emergency_exit_on_halt", False):
                _emergency_liquidate(order_mgr, current_prices, slip)
            break

    _save_day_state()              # #6：持久化當日 exits/filled
    notifier.exits_critical(crit_exits)  # 停損/移動停損 → 1 則即時（無則不發）


def _emergency_liquidate(order_mgr, current_prices: dict, slip: float):
    """#13：熔斷緊急清倉（仍守 T+1：同日進場零股不可當日賣）。賣出後同步移除雙帳本記錄。
    先篩出可賣部位才印 log，避免「印了紅字卻一檔沒賣」誤導。"""
    positions = position_mgr.summary()
    sellable = [p for p in positions if p.get("hold_days", 0) >= 1
                and (current_prices.get(p["stock_id"]) or p.get("last_price", 0)) > 0]
    skipped = [p["stock_id"] for p in positions if p.get("hold_days", 0) < 1]
    if not sellable:
        logger.warning(f"熔斷緊急清倉：目前無可賣部位（{len(skipped)} 檔 T+1 同日或無報價）")
        return
    logger.critical(f"⚠️ 熔斷緊急清倉：出清 {len(sellable)} 檔可賣部位")
    for p in sellable:
        sid = p["stock_id"]
        ref = current_prices.get(sid) or p.get("last_price", 0)
        order_mgr.exit(sid, round(ref * (1 - slip), 2), p.get("quantity", 1), "emergency_halt")
        position_mgr.remove(sid)
    if skipped:
        logger.warning(f"緊急清倉跳過（T+1 同日不可賣）：{skipped}")


def post_market_task():
    """
    14:00 盤後任務：
    - 推送每日摘要報表
    """
    if not is_trading_day():
        return

    positions = position_mgr.summary()
    status = _risk_guard.get_status() if _risk_guard else {}
    daily_pnl = status.get("daily_pnl", 0)

    notifier.daily_summary(
        positions=positions,
        daily_pnl=daily_pnl,
        total_capital=TOTAL_CAPITAL,
        candidates_count=len(_today_candidates),
        exits_today=_today_exits,  # 今日所有出場（含延後的停利/到期）併入此則
    )

    # EOD 歸檔：當日 state 快照 + daily_history.csv 時間序列（data/archive/{date}/）
    initial = float(load_settings().get("broker", {}).get("paper_initial_cash", TOTAL_CAPITAL) or TOTAL_CAPITAL)
    archive_eod(initial, getattr(score_engine, "last_regime", ""), lot_size())

    logger.info("=== 盤後報表推送完成 ===")


def afterhours_fill_task():
    """
    13:50 盤後零股補單：
    盤中(09:05)「嘗試進場但未成交/被拒」的單（intended − 已持倉），改掛盤後零股(Odd)
    → 14:30 集合競價補上。價格用收盤價(Fugle 13:30 後 lastPrice)。
    paper 模式：盤中全成交 → 無待補 → no-op。
    live：被拒/未成交者補單；完整「已委託但未成交」判斷需 Shioaji 成交回報（order_manager TODO）。
    """
    if not is_trading_day():
        return
    if not load_config().get("trading", {}).get("afterhours_fill", False):
        return
    if Path("data/processed/HALT").exists():
        logger.warning("HALT 旗標存在 → 跳過盤後零股補單")
        return
    if _risk_guard is None or not _today_intended:
        return

    # 未成交 = 今日嘗試進場 − 今日曾成交（用「曾成交」而非「目前持倉」，避免把盤中買後又賣的誤判補單）
    unfilled = [c for c in _today_intended if c["stock_id"] not in _today_filled]
    if not unfilled:
        logger.info("盤後零股補單：無待補單（盤中皆已成交）")
        return

    logger.info(f"=== 盤後零股補單：{len(unfilled)} 檔待補 ===")
    order_mgr = OrderManager(broker)
    slip = exec_slippage()
    available = broker.get_balance()   # #2：以當前現金為基準（開盤已成交者已扣），逐筆遞減
    filled = []
    for c in unfilled:
        sid = c["stock_id"]
        try:
            # 補到 target 的「餘量」（盤中部分成交者只補剩下的；完全沒成交者補全量）
            remaining = int(c["quantity"]) - int(c.get("filled_qty", 0))
            if remaining <= 0:
                continue
            quote = fugle.get_realtime_quote(sid)
            ref = quote.get("lastPrice") or c["price"]
            if not ref:
                continue
            price = round(ref * (1 + slip), 2)   # #3：買進滑價（與回測同口徑）
            cash_cap = int(max(0.0, available) / (price * lot_size()))   # 現金可負擔股數上限
            quantity = min(remaining, cash_cap)
            if quantity < 1:
                continue
            # 部分成交者盤後補單＝加碼既有倉，不佔新名額 → 持倉數檢核排除自己
            count_for_check = sum(1 for p in position_mgr.summary() if p["stock_id"] != sid)
            ok_enter, why = _risk_guard.can_enter(sid, price, quantity, count_for_check)
            if not ok_enter:
                logger.info(f"盤後補單拒絕 | {sid} | {why}")
                continue
            result = order_mgr.enter(sid, price, quantity, c["reason"],
                                     c.get("score"), order_lot="Odd")  # 盤後零股
            if "error" not in result:
                position_mgr.add(sid, price, quantity, c["reason"],
                                 c.get("score"), trail_pct=c.get("trail_pct"))  # 加碼合併進部分倉
                c["filled_qty"] = int(c.get("filled_qty", 0)) + quantity
                _today_filled.add(sid)  # 標記已補上，避免重複
                available -= price * quantity * lot_size()   # #2：遞減可用資金
                filled.append({"stock_id": sid, "name": "", "price": price,
                               "quantity": quantity, "chip_score": c.get("score", 0),
                               "reason": "盤後零股補單"})
        except Exception as e:
            logger.exception(f"盤後零股補單失敗 | {sid}")
            notifier.error(e, f"afterhours_fill_task | {sid}")

    _save_day_state()              # #6
    if filled:
        notifier.entries(filled)  # 批次：盤後補單 → 1 則
    logger.info(f"盤後零股補單完成：補上 {len(filled)} 檔")


# ──────────────────────────────────────────────────────
# benchmark 模式：0050 波動目標對照組（自包含，僅 mode=benchmark 時排程）
# active 模式完全不走這段；此處不沾染 active 的籌碼候選/ATR 移動停損。
# ──────────────────────────────────────────────────────

def _benchmark_0050_closes(lookback_days: int = 320) -> "pd.Series | None":
    """取 0050 近期日線收盤（算 realized_vol_20 / MA）。live 用 Fugle 歷史K（與 active 同一即時源，
    不打 FinMind API）。回 close Series（index=date），資料不足回 None。"""
    import pandas as pd
    sym = getattr(strategy_engine, "symbol", "0050")
    start = (datetime.now(TZ).date() - pd.Timedelta(days=lookback_days)).isoformat()
    try:
        df = fugle.get_candles(sym, start)
    except Exception as e:
        logger.warning(f"benchmark：取 {sym} 歷史K失敗 | {e}")
        return None
    if df is None or df.empty or "close" not in df.columns:
        return None
    return df.set_index("date")["close"].astype(float)


def benchmark_pre_market_task():
    """benchmark 盤前：算今日 0050 目標曝險（僅記錄/通知，實際調倉在 rebalance）。"""
    global _risk_guard, TOTAL_CAPITAL
    if not is_trading_day():
        logger.info("今日非交易日，跳過")
        return
    logger.info("=== [benchmark] 盤前：計算 0050 目標曝險 ===")
    try:
        TOTAL_CAPITAL = broker.get_balance() or 50_000
        _risk_guard = RiskGuard(total_capital=TOTAL_CAPITAL)   # 沿用熔斷/單日虧損上限（不套 ATR 停損）
        closes = _benchmark_0050_closes()
        if closes is None or len(closes) < strategy_engine.lookback + 2:
            notifier.system("[benchmark] 0050 歷史資料不足，今日不調倉")
            return
        exp = strategy_engine.current_target_exposure(closes)
        notifier.system(f"[benchmark] 0050 今日目標曝險 {exp*100:.0f}%"
                        f"（target_vol={strategy_engine.target_daily_vol}, "
                        f"overlay={'on' if strategy_engine.regime_overlay else 'off'}）")
        logger.info(f"[benchmark] 目標曝險 {exp:.3f}")
    except Exception as e:
        logger.exception("[benchmark] 盤前任務失敗")
        notifier.error(e, "benchmark_pre_market_task")


def benchmark_rebalance_task():
    """benchmark 再平衡：每月第一個交易日 或 曝險偏離 > band 時，把 0050 持倉調到目標曝險。
    開盤後執行（用即時報價當成交價）。買進受現金約束；賣出守 T+1（同日進場不可當日賣）。"""
    import pandas as pd
    if not is_trading_day():
        return
    if Path("data/processed/HALT").exists():
        logger.warning("[benchmark] HALT 旗標存在 → 暫停再平衡")
        notifier.system("[benchmark] HALT 旗標存在，本日暫停再平衡")
        return
    if _risk_guard is not None and _risk_guard.get_status().get("halted"):
        logger.warning("[benchmark] 風控熔斷中 → 暫停再平衡")
        return

    sym = strategy_engine.symbol
    logger.info(f"=== [benchmark] {sym} 再平衡 ===")
    try:
        closes = _benchmark_0050_closes()
        if closes is None or len(closes) < strategy_engine.lookback + 2:
            logger.warning("[benchmark] 0050 資料不足 → 不調倉")
            return
        target_exp = strategy_engine.current_target_exposure(closes)

        quote = fugle.get_realtime_quote(sym)
        price = quote.get("lastPrice") or float(closes.iloc[-1])
        if not price or price <= 0:
            logger.warning("[benchmark] 無有效報價 → 不調倉")
            return

        # 現有 0050 持倉（用 PositionManager 帳本；benchmark 只交易單一標的）
        pos = next((p for p in position_mgr.summary() if p["stock_id"] == sym), None)
        cur_qty = int(pos["quantity"]) if pos else 0
        cash = broker.get_balance()
        equity = cash + cur_qty * price * lot_size()

        # 每月第一個交易日 → 強制再平衡。用『實際交易日序列』判定：
        # 今日月份是否異於序列中「最後一個非今日交易日」的月份。
        recent = pd.DatetimeIndex(closes.index[-25:])
        force_monthly = False
        if len(recent) >= 2:
            today_m = pd.Timestamp(datetime.now(TZ).date()).to_period("M")
            prev_m = (recent[-1].to_period("M") if recent[-1].date() != datetime.now(TZ).date()
                      else recent[-2].to_period("M"))
            force_monthly = today_m != prev_m

        slip = exec_slippage()
        act = strategy_engine.decide_rebalance(equity, cash, cur_qty, price, target_exp,
                                               force_monthly=force_monthly)
        if act.is_noop:
            logger.info(f"[benchmark] 不調倉：{act.reason}")
            return

        order_mgr = OrderManager(broker)
        if act.side == "buy":
            fill = round(price * (1 + slip), 2)
            # benchmark 單標的曝險上限 100%，與 active 30% 單檔上限口徑不同 → 不套 can_enter 的部位上限，
            # 僅守熔斷（現金約束已在 decide_rebalance 內處理）。
            if _risk_guard and _risk_guard.get_status().get("halted"):
                logger.warning("[benchmark] 熔斷 → 不加碼")
                return
            res = order_mgr.enter(sym, fill, act.delta_qty, "benchmark_rebalance")
            if "error" not in res:
                position_mgr.add(sym, fill, act.delta_qty, "benchmark_rebalance", None, trail_pct=None)
                notifier.entries([{"stock_id": sym, "name": "0050", "price": fill,
                                   "quantity": act.delta_qty, "chip_score": 0,
                                   "reason": act.reason}])
                logger.info(f"[benchmark] {act.reason}")
        else:  # sell：守 T+1（同日進場不可當日賣）
            hold_days = pos.get("hold_days", 0) if pos else 0
            if hold_days < 1:
                logger.info("[benchmark] T+1：0050 同日進場不可當日賣，延後")
                return
            fill = round(price * (1 - slip), 2)
            res = order_mgr.exit(sym, fill, act.delta_qty, "benchmark_rebalance")
            if "error" not in res:
                if act.target_qty <= 0:
                    position_mgr.remove(sym)
                else:
                    # 部分減碼：直接覆寫帳本張數（PositionManager.add 為加碼語意，這裡需減）
                    p = position_mgr._positions.get(sym)
                    if p:
                        p["quantity"] = act.target_qty
                        position_mgr._save()
                notifier.exits_critical([{"stock_id": sym, "reason": "benchmark_rebalance",
                                          "pnl_pct": pos.get("pnl_pct", 0) if pos else 0,
                                          "price": fill}])
                logger.info(f"[benchmark] {act.reason}")
    except Exception as e:
        logger.exception("[benchmark] 再平衡失敗")
        notifier.error(e, "benchmark_rebalance_task")


# ──────────────────────────────────────────────────────
# 啟動排程
# ──────────────────────────────────────────────────────

def graceful_shutdown(signum, frame):
    """收到 SIGTERM / SIGINT 時優雅退出"""
    logger.warning("收到終止訊號，正在關閉系統...")
    broker.disconnect()
    notifier.system("交易系統已關閉")
    sys.exit(0)


def main():
    # 單例鎖：避免孤兒舊進程 + 自動重啟造成雙開重複下單（背景常駐必備）
    if not acquire_singleton_lock():
        logger.error("偵測到另一個 bot 實例已在執行（單例鎖未取得），本實例退出以避免重複下單。")
        sys.exit(0)

    settings = load_settings()
    sched_cfg = settings["schedule"]

    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    # 連線券商
    if not broker.connect():
        logger.error("券商連線失敗，系統無法啟動")
        sys.exit(1)

    # #4：啟動即初始化資金與風控（避免在 08:50 之後重啟、漏跑 pre_market 時 _risk_guard=None
    #     → 盤中監控對既有持倉無法做停損）。pre_market 之後會再刷新。
    global TOTAL_CAPITAL, _risk_guard
    TOTAL_CAPITAL = broker.get_balance() or 50_000
    _risk_guard = RiskGuard(total_capital=TOTAL_CAPITAL)
    logger.info(f"啟動初始化：資金 {TOTAL_CAPITAL:,.0f}，風控就緒")

    _reconcile_positions()   # #5：對帳雙帳本（修補崩潰/重啟造成的孤兒/殘留部位）
    _load_day_state()        # #6：盤中重啟 → 復原當日候選/補單追蹤

    scheduler = BlockingScheduler(timezone=TZ)

    if STRATEGY_MODE == "benchmark":
        # ── benchmark 對照組排程（0050 波動目標再平衡；完全不註冊 active 任務）──
        # 盤前算目標曝險（08:50）→ 開盤後再平衡（market_open）→ 盤後報表（14:00，復用 post_market）。
        # 不排 active 的 market_open/intraday_monitor/afterhours（benchmark 無候選/無 ATR 移動停損）。
        h, m = sched_cfg["pre_market"].split(":")
        scheduler.add_job(benchmark_pre_market_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))
        h, m = sched_cfg["market_open"].split(":")
        scheduler.add_job(benchmark_rebalance_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))
        h, m = sched_cfg["post_market"].split(":")
        scheduler.add_job(post_market_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))
        logger.info(f"✅ 交易系統啟動（benchmark 模式：{strategy_engine}），等待排程...")
        notifier.system(f"交易系統已啟動（benchmark 對照組：{strategy_engine.symbol} 波動目標 "
                        f"target_vol={strategy_engine.target_daily_vol}）")
    else:
        # ── active 現行策略排程（原封不動，與 benchmark 整合前逐字相同）──
        # 盤前選股 08:50
        h, m = sched_cfg["pre_market"].split(":")
        scheduler.add_job(pre_market_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))

        # 開盤下單（時間取自 config schedule.market_open）
        h, m = sched_cfg["market_open"].split(":")
        scheduler.add_job(market_open_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))

        # 盤中監控 每 N 分鐘（cron 涵蓋 9-13 時，實際動作由 _within_session 限在 market_open~market_close）
        scheduler.add_job(
            intraday_monitor_task,
            CronTrigger(hour="9-13", minute=f"*/{sched_cfg['intraday_check']}", timezone=TZ),
        )

        # 盤後零股補單 13:50（盤中未成交 → 改掛盤後零股 Odd，14:30 集合競價）
        scheduler.add_job(afterhours_fill_task, CronTrigger(hour=13, minute=50, timezone=TZ))

        # 盤後報表 14:00
        h, m = sched_cfg["post_market"].split(":")
        scheduler.add_job(post_market_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))

        logger.info("✅ 交易系統啟動，等待排程...")
        notifier.system("交易系統已啟動")

    try:
        scheduler.start()
    except Exception as e:
        logger.exception("排程器異常")
        notifier.error(e, "main scheduler")
        broker.disconnect()


if __name__ == "__main__":
    main()

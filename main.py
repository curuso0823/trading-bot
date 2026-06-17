"""
main.py
排程主程式入口
APScheduler 控制每日流程：盤前選股 → 開盤下單 → 盤中監控 → 盤後報表
"""
import sys
import signal
from pathlib import Path
from datetime import datetime
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from src.utils.logger import setup_logger
from src.utils.helpers import load_settings, is_trading_day, lot_size, exec_slippage
from src.utils.singleton import acquire_singleton_lock
from src.strategy_engines import make_engine
from src.execution.broker_factory import make_broker
from src.execution.order_manager import OrderManager, PositionManager
from src.risk.risk_guard import RiskGuard
from src.notify.notify_factory import make_notifier
from src.data.fetcher import FugleFetcher
from src.utils.eod_archive import archive_eod

# ──────────────────────────────────────────────────────
# 全域元件（單例）
# ──────────────────────────────────────────────────────
setup_logger()

broker = make_broker()
position_mgr = PositionManager()
notifier = make_notifier()
fugle = FugleFetcher()

# 策略引擎：benchmark 被動（0050 波動目標 + MA200 overlay）。
# make_engine 內 fail-safe：mode 非 benchmark 仍回 BenchmarkEngine（舊 active 執行路徑已移除）。
strategy_engine = make_engine()

# 初始資金從帳戶餘額取得（啟動時讀一次）
TOTAL_CAPITAL = 0.0
TZ = pytz.timezone("Asia/Taipei")
_risk_guard = None


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
        candidates_count=0,        # benchmark 被動：無選股候選
        exits_today=[],            # benchmark：出場走 rebalance 即時通知，無每日批次清單
    )

    # EOD 歸檔：當日 state 快照 + daily_history.csv 時間序列（data/archive/{date}/）
    initial = float(load_settings().get("broker", {}).get("paper_initial_cash", TOTAL_CAPITAL) or TOTAL_CAPITAL)
    archive_eod(initial, getattr(strategy_engine, "last_regime", ""), lot_size())

    logger.info("=== 盤後報表推送完成 ===")


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

    scheduler = BlockingScheduler(timezone=TZ)

    # ── benchmark 被動排程（0050 波動目標再平衡 + MA200 overlay；無 active 候選/ATR 移動停損）──
    # 盤前算目標曝險（08:50）→ 開盤後再平衡（market_open）→ 盤後報表（14:00）。
    h, m = sched_cfg["pre_market"].split(":")
    scheduler.add_job(benchmark_pre_market_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))
    h, m = sched_cfg["market_open"].split(":")
    scheduler.add_job(benchmark_rebalance_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))
    h, m = sched_cfg["post_market"].split(":")
    scheduler.add_job(post_market_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))
    logger.info(f"✅ 交易系統啟動（benchmark 被動：{strategy_engine}），等待排程...")
    notifier.system(f"交易系統已啟動（benchmark：{strategy_engine.symbol} 波動目標 "
                    f"target_vol={strategy_engine.target_daily_vol}、MA{strategy_engine.regime_ma} overlay）")

    try:
        scheduler.start()
    except Exception as e:
        logger.exception("排程器異常")
        notifier.error(e, "main scheduler")
        broker.disconnect()


if __name__ == "__main__":
    main()

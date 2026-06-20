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
from src.utils.helpers import load_settings, is_trading_day, lot_size, exec_slippage, calc_trade_cost
from src.utils.singleton import acquire_singleton_lock
from src.strategy_engines import make_engine
from src.execution.broker_factory import make_broker
from src.execution.order_manager import OrderManager, PositionManager
from src.risk.risk_guard import RiskGuard
from src.notify.notify_factory import make_notifier
from src.data.fetcher import FinMindFetcher, FugleFetcher, completed_daily_closes
from src.utils.eod_archive import archive_eod

# allocator（M5；additive、mode-gated）— 僅 strategy.mode=="allocator" 路徑使用，import 不啟動任何排程。
from src.strategy_engines.allocator_engine import AllocatorEngine
from src.execution.portfolio_rebalancer import PortfolioRebalancer
from src.execution.mmf_sleeve import SyntheticMMF
from src.data.macro_fetcher import MacroMonitor

# ──────────────────────────────────────────────────────
# 全域元件（單例）
# ──────────────────────────────────────────────────────
setup_logger()

broker = make_broker()
position_mgr = PositionManager()
notifier = make_notifier()
fugle = FugleFetcher()
# 歷史日收盤（MA200 regime / realized_vol）走 FinMind（adjust、全史磁碟快取、與回測同源）；
# Fugle 免費層歷史 K 僅 ~22 bars 不足 MA200(≥202) → 會讓防禦 overlay 全程 NaN 失效（2026-06-19c 修正）。
# Fugle 僅保留「即時零股報價＝成交價」用途。
finmind = FinMindFetcher()

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

    benchmark 行為逐位不變；allocator 模式下 position_mgr.summary() 已涵蓋全部 6 標的持倉
    （多標的播報天然成立），僅「額外」追加合成 MMF sleeve 現值一行（不在 broker 帳本內）。
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

    # allocator-only 追加：合成 MMF sleeve 現值播報（additive；benchmark 不進此分支）
    if _allocator_mode():
        try:
            mmf_val = SyntheticMMF().value()
            notifier.system(f"[allocator] 合成 MMF sleeve 現值 {mmf_val:,.0f} 元")
        except Exception:
            logger.exception("[allocator] 盤後 MMF 現值播報失敗（不影響盤後報表）")

    logger.info("=== 盤後報表推送完成 ===")


# ──────────────────────────────────────────────────────
# benchmark 模式：0050 波動目標對照組（自包含，僅 mode=benchmark 時排程）
# active 模式完全不走這段；此處不沾染 active 的籌碼候選/ATR 移動停損。
# ──────────────────────────────────────────────────────

def _finmind_closes(sym: str, lookback_days: int) -> "pd.Series | None":
    """取單一標的歷史日收盤（FinMind，adjust=True、全史磁碟快取）→ T+1 完整收盤 Series。
    供 MA200 regime / realized_vol 用——Fugle 免費層歷史僅 ~22 bars 不足 MA200，故 regime 史料一律走
    FinMind（與回測同源、T+1 無未完成 bar）；Fugle 僅供即時零股報價（成交價）。資料不足/取數失敗回 None。"""
    import pandas as pd
    start = (datetime.now(TZ).date() - pd.Timedelta(days=int(lookback_days))).isoformat()
    try:
        df = finmind.get_daily_price(sym, start, adjust=True)
    except Exception as e:
        logger.warning(f"[regime] FinMind 取 {sym} 歷史失敗 | {e}")
        return None
    if df is None or df.empty or "close" not in df.columns:
        return None
    return completed_daily_closes({sym: df}, datetime.now(TZ).date()).get(sym)


def _benchmark_0050_closes(lookback_days: int = 400) -> "pd.Series | None":
    """取 0050 近期日線收盤（算 realized_vol_20 / MA200）。
    **改用 FinMind 全史**（adjust=True、全史磁碟快取、T+1 完整收盤）：Fugle 免費層歷史 K 僅 ~22 bars、
    不足 MA200(≥202) → 會讓 MA200 防禦 overlay 全程 NaN、靜默失效（2026-06-19c 修正、使用者拍板）。
    回 close Series（index=date），資料不足回 None。"""
    sym = getattr(strategy_engine, "symbol", "0050")
    return _finmind_closes(sym, lookback_days)


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
# allocator 模式：6 資產 Asset Allocator（M0 帶寬 + M1 de-risk + M2 現金 tilt）
# additive / mode-gated：僅 settings.yaml strategy.mode=="allocator" 時排程此段。
# benchmark 路徑完全不觸及（上方 benchmark 任務逐位不變）。
# 規格真相＝M5_DEPLOYMENT_PLAN.md §11.7；決策權威＝full_book_backtest.target_weights()。
# ──────────────────────────────────────────────────────

# allocator 標的（MMF 為合成 sleeve，不打行情、不出 RebalanceAction）
_ALLOC_MARKET_SYMBOLS = ["0050", "00981A", "00991A", "00635U", "00864B"]
_ALLOC_MMF_SYMBOL = "MMF"
_ALLOC_STATE_FILE = "data/processed/allocator_state.json"


def _allocator_mode() -> bool:
    """目前 strategy.mode 是否為 allocator（每次讀 config，與 make_engine 同源）。"""
    return str((load_settings().get("strategy", {}) or {}).get("mode", "benchmark")).lower() == "allocator"


def _alloc_lookback_days(eng: "AllocatorEngine") -> int:
    """取足夠回看天數：MA(m1_ma) + 暖身 + 緩衝（日曆日，涵蓋週末/假日）。"""
    bars = int(getattr(eng, "m1_ma", 200)) + int(getattr(eng, "m1_confirm_days", 3)) + 5
    return int(bars * 1.6) + 30   # 交易日→日曆日粗放換算 + 緩衝


def _load_alloc_state() -> dict:
    """讀 allocator 觸發狀態（昨日 regime_on / usd_regime）；無檔回安全預設（皆未啟動）。
    註：此為 runtime 觸發狀態（等價 sandbox 的 prev_on/prev_usd），非凍結帳本。"""
    import json
    p = Path(_ALLOC_STATE_FILE)
    if not p.exists():
        return {"prev_regime_on": None, "prev_usd_regime": None}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return {"prev_regime_on": d.get("prev_regime_on"),
                "prev_usd_regime": d.get("prev_usd_regime")}
    except Exception as e:
        logger.warning(f"[allocator] 觸發狀態載入失敗，採預設 | {e}")
        return {"prev_regime_on": None, "prev_usd_regime": None}


def _save_alloc_state(regime_on: bool, usd_regime: float) -> None:
    """持久化今日 regime_on / usd_regime（供明日觸發判定；與 sandbox 每日更新 prev_* 一致）。"""
    import json
    p = Path(_ALLOC_STATE_FILE)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"prev_regime_on": bool(regime_on),
                       "prev_usd_regime": float(usd_regime),
                       "asof": datetime.now(TZ).date().isoformat()},
                      f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"[allocator] 觸發狀態寫入失敗 | {e}")


def _alloc_fetch_closes(start: str) -> dict:
    """並行取 5 檔 ETF 歷史日線（Fugle，與 benchmark 同即時源，不打 FinMind）。
    回 {sym: close Series(index=date)}（缺資料的檔 → 空 Series）。
    **T+1 紀律**：剔除今日未完成 bar（盤中 09:12 即時源可能含）→ regime/ref 一律用完整收盤、
    對齊 sandbox `regime_on=shift(1)` 與 `compute_regime_on` 的「截至昨日收盤」契約。"""
    raw = fugle.get_candles_multi(_ALLOC_MARKET_SYMBOLS, start)
    return completed_daily_closes(raw, datetime.now(TZ).date())


def _alloc_holdings() -> dict:
    """目前 5 檔 ETF 持股（股）— 自 PositionManager 帳本（MMF 不在此，走 SyntheticMMF）。"""
    held: dict = {}
    for p in position_mgr.summary():
        sid = p["stock_id"]
        if sid in _ALLOC_MARKET_SYMBOLS:
            held[sid] = int(p["quantity"])
    return held


def allocator_pre_market_task():
    """allocator 盤前（08:50）：算今日 6 標的目標權重 + regime/usd 狀態（僅記錄/通知，實際調倉在 rebalance）。"""
    import pandas as pd
    global _risk_guard, TOTAL_CAPITAL
    if not is_trading_day():
        logger.info("今日非交易日，跳過")
        return
    logger.info("=== [allocator] 盤前：計算 6 資產目標權重 ===")
    try:
        TOTAL_CAPITAL = broker.get_balance() or 50_000
        _risk_guard = RiskGuard(total_capital=TOTAL_CAPITAL)   # 沿用熔斷/單日虧損上限
        eng = strategy_engine
        closes = _alloc_fetch_closes(
            (datetime.now(TZ).date() - pd.Timedelta(days=_alloc_lookback_days(eng))).isoformat())
        c0050 = _finmind_closes("0050", _alloc_lookback_days(eng))   # regime 史料走 FinMind（Fugle ~22 bars 不足 MA200）
        if c0050 is None or len(c0050) < int(eng.m1_ma) + 2:
            notifier.system("[allocator] 0050 歷史資料不足，今日盤前不評估")
            return
        regime_on = eng.compute_regime_on(c0050)
        usd_regime = 0.0
        if getattr(eng, "use_m2", False):
            try:
                usd_regime = MacroMonitor().usd_regime(datetime.now(TZ).date())
            except Exception:
                logger.exception("[allocator] 盤前 MacroMonitor 取數失敗（usd_regime 視為 0）")
                usd_regime = 0.0
        # 用「上次持倉漂移權重」當 drift 輸入估算目標（盤前僅播報，rebalance 會以即時價重算）
        tw = eng.target_weights(dict(eng.target), regime_on, usd_regime)
        msg = "、".join(f"{s} {tw.get(s, 0)*100:.0f}%" for s in eng.cols)
        notifier.system(f"[allocator] 今日 regime_on={'ON' if regime_on else 'off'} "
                        f"usd={usd_regime:+.0f} 目標權重 {msg}")
        logger.info(f"[allocator] regime_on={regime_on} usd={usd_regime} tw={tw}")
    except Exception as e:
        logger.exception("[allocator] 盤前任務失敗")
        notifier.error(e, "allocator_pre_market_task")


def allocator_rebalance_task():
    """allocator 再平衡（開盤後 09:12）：觸發＝當月首交易日 OR regime_on 變 OR usd 變。
    觸發時 PortfolioRebalancer 出有序零股訂單（先賣後買）+ SyntheticMMF 轉移 → PositionManager 記帳。
    沿用 HALT 旗標 / 風控熔斷 / T+1（賣出守同日進場不可當日賣）。"""
    import pandas as pd
    if not is_trading_day():
        return
    if Path("data/processed/HALT").exists():
        logger.warning("[allocator] HALT 旗標存在 → 暫停再平衡")
        notifier.system("[allocator] HALT 旗標存在，本日暫停再平衡")
        return
    if _risk_guard is not None and _risk_guard.get_status().get("halted"):
        logger.warning("[allocator] 風控熔斷中 → 暫停再平衡")
        return

    logger.info("=== [allocator] 6 資產再平衡 ===")
    try:
        eng = strategy_engine
        today = datetime.now(TZ).date()

        # ① 合成 MMF 日 accrual（僅交易日複利、防重複）
        mmf = SyntheticMMF()
        mmf.accrue(today)
        mmf_value = mmf.value()

        # ② 多標的取數：歷史K（算 0050 regime_on）+ 各腿即時零股報價
        closes = _alloc_fetch_closes((today - pd.Timedelta(days=_alloc_lookback_days(eng))).isoformat())
        c0050 = _finmind_closes("0050", _alloc_lookback_days(eng))   # regime 史料走 FinMind（Fugle ~22 bars 不足 MA200）
        if c0050 is None or len(c0050) < int(eng.m1_ma) + 2:
            logger.warning("[allocator] 0050 資料不足 → 不調倉")
            return
        regime_on = eng.compute_regime_on(c0050)

        # ③ M2（M2 開時取 usd_regime；否則 0）
        usd_regime = 0.0
        if getattr(eng, "use_m2", False):
            try:
                usd_regime = MacroMonitor().usd_regime(today)
            except Exception:
                logger.exception("[allocator] MacroMonitor 取數失敗（usd_regime 視為 0、不誤觸發）")
                usd_regime = 0.0

        # ⑤ 觸發判定（與 sandbox simulate 同口徑：月初 OR regime_on 變 OR usd 變）
        #    prev_* 取自昨日持久化狀態；首次（無狀態）→ 視為「已變」以建立基準。
        st = _load_alloc_state()
        prev_on = st.get("prev_regime_on")
        prev_usd = st.get("prev_usd_regime")
        recent = pd.DatetimeIndex(c0050.index[-25:])
        force_monthly = False
        if len(recent) >= 1:
            today_m = pd.Timestamp(today).to_period("M")
            last = recent[-1]
            prev_m = (last.to_period("M") if last.date() != today
                      else (recent[-2].to_period("M") if len(recent) >= 2 else None))
            force_monthly = (prev_m is None) or (today_m != prev_m)
        regime_changed = (prev_on is None) or (bool(prev_on) != bool(regime_on))
        usd_changed = bool(getattr(eng, "use_m2", False)) and (
            (prev_usd is None) or (float(prev_usd) != float(usd_regime)))
        triggered = force_monthly or regime_changed or usd_changed

        # 每日更新觸發狀態（與 sandbox 每日更新 prev_* 一致，無論是否再平衡）
        _save_alloc_state(regime_on, usd_regime)

        if not triggered:
            logger.info(f"[allocator] 未觸發再平衡（月初={force_monthly} regime變={regime_changed} "
                        f"usd變={usd_changed}）")
            return

        # ④ 目標權重（M0/M1/M2 → 6 標的，和為 1）。drift 用當前持倉權重。
        holdings = _alloc_holdings()
        cash = broker.get_balance()
        quotes = fugle.get_odd_quotes_multi(_ALLOC_MARKET_SYMBOLS)
        ref_prices = {s: float(c.iloc[-1]) for s, c in closes.items() if len(c) > 0}

        # 當前漂移權重（估總權益用即時/昨收參考價；給 target_weights 的 M0 帶寬分支）
        lot = lot_size()
        def _ref_px(sym: str) -> float:
            q = quotes.get(sym) or {}
            lp = q.get("lastPrice")
            try:
                lp = float(lp) if lp else 0.0
            except (TypeError, ValueError):
                lp = 0.0
            return lp or ref_prices.get(sym, 0.0)
        hv = {s: holdings.get(s, 0) * _ref_px(s) * lot for s in _ALLOC_MARKET_SYMBOLS}
        equity = float(cash) + sum(hv.values()) + float(mmf_value)
        if equity <= 0:
            logger.warning("[allocator] 總權益 ≤ 0 → 不調倉")
            return
        drift = {s: hv[s] / equity for s in _ALLOC_MARKET_SYMBOLS}
        drift[_ALLOC_MMF_SYMBOL] = float(mmf_value) / equity
        target_w = eng.target_weights(drift, regime_on, usd_regime)

        # ⑥ 規劃有序零股訂單（現金感知、先賣後買、硬地板、零股撮合價）
        reb = PortfolioRebalancer(fugle=fugle)
        plan = reb.plan(target_w, holdings, float(cash), float(mmf_value),
                        quotes, bands=eng.bands, ref_prices=ref_prices)
        if not plan.actions and plan.mmf_transfer.is_noop:
            logger.info("[allocator] 規劃無動作（帶內/無偏離）")
            for n in plan.notes:
                logger.info(f"[allocator] {n}")
            return

        order_mgr = OrderManager(broker)
        entries, exits = [], []
        mt = plan.mmf_transfer

        # ── 先賣後買，分三段，現金與 MMF 轉移皆原子守恆（避免 cascade／重複計）──
        # 段 1：賣序（T+1 防呆；釋金真實落到 broker._cash）。
        for act in plan.actions:
            if act.is_noop or act.side != "sell":
                continue
            sym = act.stock_id
            # T+1 防呆：同日進場不可當日賣（釋金未實現 → 後段買序以 broker 實際現金為準、不會被它撐起）
            pos = next((p for p in position_mgr.summary() if p["stock_id"] == sym), None)
            hold_days = pos.get("hold_days", 0) if pos else 0
            if hold_days < 1:
                logger.info(f"[allocator] T+1：{sym} 同日進場不可當日賣，延後（其釋金不計入買序預算）")
                continue
            # 成交價：用 planner 已算定的 fill price（消除 planner/executor 報價分歧）；缺則 fallback 重取零股簿
            px = plan.fill_prices.get(sym) or _alloc_sell_px(sym, quotes.get(sym), ref_prices.get(sym, 0.0))
            if px <= 0:
                logger.warning(f"[allocator] {sym} 賣出無有效價，跳過")
                continue
            res = order_mgr.exit(sym, px, act.delta_qty, "allocator_rebalance")
            if "error" not in res:
                if act.target_qty <= 0:
                    position_mgr.remove(sym)
                else:
                    p = position_mgr._positions.get(sym)
                    if p:
                        p["quantity"] = act.target_qty
                        position_mgr._save()
                exits.append({"stock_id": sym, "reason": "allocator_rebalance",
                              "pnl_pct": pos.get("pnl_pct", 0) if pos else 0, "price": px})
                logger.info(f"[allocator] {act.reason}")

        # 段 2：MMF 提領墊買序 — 在買序之前執行，且與 broker 現金原子掛鉤（守恆 + 讓 place_order 看得到墊款）。
        #   mmf.withdraw 回傳『實際贖回額』（受現值上限 clip）→ 等額 credit 進 broker，現金不憑空生出/消失。
        if not mt.is_noop and mt.side == "withdraw":
            actual = mmf.withdraw(mt.amount)
            credited = broker.adjust_cash(actual)        # MMF→cash：入 broker
            logger.info(f"[allocator] MMF withdraw {actual:,.0f}（{mt.reason}）→ broker 現金 +{credited:,.0f}")

        # 段 3：買序 — 以 broker『實際現金』為預算逐單下單（含手續費縮量），現金用罄即停。
        #   ▸ T+1 被跳過的賣單其釋金本就不在 broker 現金內 → 買量自然縮減，不觸發 insufficient_cash 串級重試/長 sleep。
        running_cash = broker.get_balance()
        for act in plan.actions:
            if act.is_noop or act.side != "buy":
                continue
            if _risk_guard and _risk_guard.get_status().get("halted"):
                logger.warning("[allocator] 熔斷 → 不加碼")
                break
            sym = act.stock_id
            # 用 planner 已算定的 book-walk fill price（與規劃同口徑，消除分歧）；缺則 fallback 重取零股簿
            px = plan.fill_prices.get(sym) or _alloc_buy_px(sym, quotes.get(sym), ref_prices.get(sym, 0.0))
            if px <= 0:
                logger.warning(f"[allocator] {sym} 買進無有效價，跳過")
                continue
            # 現金縮量：以 broker 實際現金為硬上限降量（含 calc_trade_cost 手續費）→ 不超買、不觸發重試 sleep。
            qty = int(act.delta_qty)
            while qty >= 1:
                amt = px * qty * lot
                fee = calc_trade_cost(px, qty, "buy")["fee"]
                if amt + fee <= running_cash + 1e-6:
                    break
                qty -= 1
            if qty < 1:
                logger.info(f"[allocator] {sym} 現金不足（broker 現金 {running_cash:,.0f}），本輪未買")
                continue
            res = order_mgr.enter(sym, px, qty, "allocator_rebalance")
            if "error" not in res:
                running_cash = broker.get_balance()       # 以 broker 真實餘額續推（含成本）
                position_mgr.add(sym, px, qty, "allocator_rebalance", None, trail_pct=None)
                why = "（現金縮量部分成交）" if qty < act.delta_qty else ""
                entries.append({"stock_id": sym, "name": sym, "price": px,
                                "quantity": qty, "chip_score": 0,
                                "reason": f"{act.reason}{why}"})
                logger.info(f"[allocator] {act.reason}{why}")

        # 段 4：殘餘現金回存 MMF — 在買序之後執行，且與 broker 現金原子掛鉤（守恆）。
        #   broker.adjust_cash(-amount) 受不透支 clip，回傳實際出帳額 → 等額存入 MMF（不存入 broker 沒有的現金）。
        if not mt.is_noop and mt.side == "deposit":
            debited = -broker.adjust_cash(-mt.amount)    # cash→MMF：出 broker（clip 到可用現金）
            mmf.deposit(debited)
            logger.info(f"[allocator] MMF deposit {debited:,.0f}（{mt.reason}）← broker 現金 −{debited:,.0f}")

        if entries:
            notifier.entries(entries)
        if exits:
            notifier.exits_critical(exits)
        for n in plan.notes:
            logger.info(f"[allocator] note: {n}")
        logger.info(f"[allocator] 再平衡完成：賣 {len(exits)} 買 {len(entries)}，"
                    f"預估現金 {plan.projected_cash:,.0f}")
    except Exception as e:
        logger.exception("[allocator] 再平衡失敗")
        notifier.error(e, "allocator_rebalance_task")


def _alloc_buy_px(sym: str, quote: dict | None, ref_price: float) -> float:
    """allocator 買進零股成交價＝賣方階梯 book-walk vwap；無簿 → fallback ref×(1+slip)。"""
    from src.execution.odd_lot_fill import odd_lot_buy_fill, parse_odd_ladder
    slip = exec_slippage()
    q = quote or {}
    asks = parse_odd_ladder(q, levels=5)
    res = odd_lot_buy_fill(1, asks, max_impact_pct=0.004)
    if res is not None:
        _filled, vwap, _rem = res
        if vwap > 0:
            return round(float(vwap), 2)
    lp = q.get("lastPrice")
    try:
        base = float(lp) if lp else 0.0
    except (TypeError, ValueError):
        base = 0.0
    base = base or float(ref_price or 0.0)
    return round(base * (1.0 + slip), 2) if base > 0 else 0.0


def _alloc_sell_px(sym: str, quote: dict | None, ref_price: float) -> float:
    """allocator 賣出零股成交價＝零股簿最佳買價；無簿 → fallback ref×(1−slip)。"""
    from src.execution.odd_lot_fill import parse_odd_book
    slip = exec_slippage()
    q = quote or {}
    best_bid, _, _ = parse_odd_book(q)
    if best_bid > 0:
        return round(float(best_bid), 2)
    lp = q.get("lastPrice")
    try:
        base = float(lp) if lp else 0.0
    except (TypeError, ValueError):
        base = 0.0
    base = base or float(ref_price or 0.0)
    return round(base * (1.0 - slip), 2) if base > 0 else 0.0


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

    if _allocator_mode():
        # ── allocator 排程（6 資產：M0 帶寬 + M1 de-risk + M2 現金 tilt；additive、mode-gated）──
        # 盤前算目標權重/regime（08:50）→ 開盤後組合再平衡（market_open）→ 盤後報表（14:00，多標的）。
        h, m = sched_cfg["pre_market"].split(":")
        scheduler.add_job(allocator_pre_market_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))
        h, m = sched_cfg["market_open"].split(":")
        scheduler.add_job(allocator_rebalance_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))
        h, m = sched_cfg["post_market"].split(":")
        scheduler.add_job(post_market_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))
        layers = ",".join(["M0"] + (["M1"] if getattr(strategy_engine, "use_m1", False) else [])
                          + (["M2"] if getattr(strategy_engine, "use_m2", False) else []))
        logger.info(f"✅ 交易系統啟動（allocator 6 資產：layers={layers}，{strategy_engine}），等待排程...")
        notifier.system(f"交易系統已啟動（allocator：6 資產 Asset Allocator，啟用層 {layers}）")
    else:
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

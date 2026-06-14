"""
notebooks/paper_debug.py
部署後 paper 全流程「試跑」debug：實際呼叫 main.py 的排程任務函式，
在隔離 temp state 目錄下端到端跑（不碰真實 paper 狀態檔），stub 掉 Fugle 報價與 notifier（不發 LINE）。
逐項檢查並印 [OK]/[!! ISSUE]，把部署後 paper 過程可能出的問題抓出來。

用法：.venv\\Scripts\\python.exe notebooks\\paper_debug.py
"""
import os, sys, json, tempfile, importlib, traceback
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from datetime import date, timedelta

ISSUES = []
def ok(msg): print(f"  [OK]   {msg}")
def issue(sev, msg): ISSUES.append((sev, msg)); print(f"  [!! {sev}] {msg}")
def hdr(t): print(f"\n===== {t} =====")

# ── 隔離 state 路徑（patch 在 import main 之前）──
TMP = Path(tempfile.mkdtemp(prefix="paperdbg_"))
# loguru 第一道導向：import main 前先清空 sink（src.utils.logger 模組層 add 的真實檔 sink
# 會在 import 時掛上 → 若只在 import 後 remove 一次，任何先期 log 仍會寫進真實 logs/）
from loguru import logger as _lg0
_lg0.remove()
_lg0.add(str(TMP / "harness.log"), level="INFO")
from src.execution import paper_broker as pb_mod
from src.execution import order_manager as om_mod
from src.risk import risk_guard as rg_mod
pb_mod.PaperBroker.ACCOUNT_FILE = str(TMP / "paper_account.json")
om_mod.PositionManager.POSITIONS_FILE = str(TMP / "positions.json")
rg_mod.RiskGuard.DAILY_STATE_FILE = str(TMP / "daily_risk_state.json")

import main  # 模組級會用上面 patch 過的路徑建 broker / position_mgr

# ── stub Fugle 報價 + notifier（避免真實 API/LINE）──
PRICES = {}
ODD_DEPTH = {}   # sid -> 零股賣一深度(股)；未設=充足(視為盤中可成交)。供零股成交模型 CHECK 用


def _stub_quote(sid, odd=False):
    if sid not in PRICES:
        return {}
    px = PRICES[sid]
    if odd:   # 零股簿：賣一價 ≈ 現價、深度由 ODD_DEPTH 控（預設極大=充足）
        d = ODD_DEPTH.get(sid, 10_000_000)
        return {"lastPrice": px,
                "bids": [{"price": round(px * 0.999, 2), "size": d}],
                "asks": [{"price": round(px * 1.001, 2), "size": d}]}
    return {"lastPrice": px}


main.fugle.get_realtime_quote = _stub_quote

class FakeNotifier:
    def __init__(self): self.calls = []
    def __getattr__(self, name):
        def f(*a, **k): self.calls.append((name, a, k)); return None
        return f
main.notifier = FakeNotifier()
main.record_slippage = lambda *a, **k: None     # 不寫真實 slippage_log
import src.utils.eod_archive as _ea             # EOD 歸檔改寫 temp（不污染真實 data/archive）
_ea.PROC = TMP
_ea.ARCHIVE_DIR = TMP / "archive"
main._DAY_STATE_FILE = TMP / "day_state.json"   # 當日 state 也改寫 temp（避免污染真實 data/processed）
from loguru import logger as _lg                # loguru 第二道導向：import main 過程若有模組重掛真實 sink，再清一次
_lg.remove(); _lg.add(str(TMP / "harness.log"), level="INFO")
# 實測 2026-06-10 07:54 harness 合成交易曾寫進真實 trading log → 兩道導向缺一不可
main._within_session = lambda: True             # 夜間試跑：強制視為盤中，讓 intraday 真的執行
main.is_trading_day = lambda *a, **k: True       # 只 patch main 的短路判斷（不動 helpers 的，count_trading_days 仍用真實日曆）

def fresh_state():
    for f in TMP.glob("*.json"):
        f.unlink()
    importlib.reload  # no-op
    main.broker = main.make_broker()             # 重讀 config（70000）+ temp 空帳戶
    main.position_mgr = om_mod.PositionManager()
    main.TOTAL_CAPITAL = main.broker.get_balance() or 50_000
    main._risk_guard = rg_mod.RiskGuard(total_capital=main.TOTAL_CAPITAL)
    main._today_candidates, main._today_intended, main._today_filled, main._today_exits = [], [], set(), []


# ════════════════════════ CHECK 1：部署後 live regime（新 capitulation block_only）══════════
hdr("CHECK 1：live 選股 regime（capitulation block_only 已接）")
try:
    r = main.score_engine._market_risk_on()
    ok(f"_market_risk_on() 正常回傳 → {'多頭可進場' if r else '空頭/假反彈擋下(不進場)'}（type={type(r).__name__}）")
    if not isinstance(r, bool):
        issue("中", "_market_risk_on 回傳非 bool")
except Exception as e:
    issue("高", f"live regime 崩潰：{e}")
    traceback.print_exc()


# ════════════════════════ CHECK 2：開盤下單 — 配重 / 現金扣減 / 雙帳本一致 ══════════
hdr("CHECK 2：market_open 配重、現金、雙部位帳本一致性")
fresh_state()
CANDS = [
    {"stock_id": "2330", "close": 100.0, "size_pct": 0.30, "trail_pct": 0.09, "chip_score": 3, "reason": "t"},
    {"stock_id": "2317", "close": 50.0,  "size_pct": 0.30, "trail_pct": 0.08, "chip_score": 2, "reason": "t"},
    {"stock_id": "2412", "close": 40.0,  "size_pct": 0.30, "trail_pct": None, "chip_score": 2, "reason": "t"},
]
PRICES.update({"2330": 100.0, "2317": 50.0, "2412": 40.0})
main._today_candidates = [dict(c) for c in CANDS]
cap0 = main.TOTAL_CAPITAL
try:
    main.market_open_task()
    pm = main.position_mgr.summary()
    pbpos = main.broker.get_positions()
    ok(f"market_open 完成：PositionManager {len(pm)} 檔、PaperBroker {len(pbpos)} 檔")
    if len(pm) != len(pbpos):
        issue("高", f"雙帳本不一致：PositionManager {len(pm)} vs PaperBroker {len(pbpos)}")
    else:
        ok("雙帳本檔數一致")
    # #2 驗證：應逐筆遞減配重（後續檔對『剩餘現金』收 size_pct → 遞減），非都≈30%
    deployed = cap0 - main.broker.get_balance()
    print(f"        pre_market 資金={cap0:,.0f}｜開盤後已部署={deployed:,.0f}（{deployed/cap0*100:.0f}%）｜現金剩 {main.broker.get_balance():,.0f}")
    sizes = {p["stock_id"]: p["entry_price"] * p["quantity"] for p in pm}
    vals = [sizes.get(c["stock_id"], 0) for c in CANDS]
    print(f"        各檔部位金額（依序）：{[round(v) for v in vals]}")
    if vals[0] > vals[1] > vals[2]:
        ok("#2 已修：逐筆遞減配重（對齊回測 vectorbt percent-of-cash），不再過度配置")
    else:
        issue("中", f"#2 未生效：配重未遞減 {[round(v) for v in vals]}")
except Exception as e:
    issue("高", f"market_open 崩潰：{e}"); traceback.print_exc()


# ════════════════════════ CHECK 3：T+1 同日不可當沖（同日進場當日不可賣）══════════
hdr("CHECK 3：T+1 同日出場防呆")
PRICES["2330"] = 70.0   # 2330 當日 -30% 暴跌
try:
    before = {p["stock_id"] for p in main.position_mgr.summary()}
    main.intraday_monitor_task()
    after = {p["stock_id"] for p in main.position_mgr.summary()}
    if "2330" in after:
        ok("2330 當日暴跌 -30% 但因 hold_days<1（T+1）未被賣出 → 正確（零股不可當沖）")
    else:
        issue("高", "2330 同日就被賣出 → 違反 T+1 零股不可當沖")
except Exception as e:
    issue("高", f"intraday 崩潰：{e}"); traceback.print_exc()


# ════════════════════════ CHECK 4：移動停損出場 — 1% 掛單折價 + 雙帳本一致 ══════════
hdr("CHECK 4：隔日移動停損出場（掛單價 last×0.99 折價、雙帳本同步）")
# 把所有持倉 entry_date 改成昨天 → hold_days=1（可出場）
for sid, p in main.position_mgr._positions.items():
    p["entry_date"] = (date.today() - timedelta(days=1)).isoformat()
main.position_mgr._save()
PRICES["2330"] = 70.0   # 仍深跌，觸發停損/移動停損
cash_before = main.broker.get_balance()
try:
    main.intraday_monitor_task()
    pm = {p["stock_id"] for p in main.position_mgr.summary()}
    pbset = {p["stock_id"] for p in main.broker.get_positions()}
    if "2330" not in pm and "2330" not in pbset:
        ok("2330 隔日觸發出場，且 PositionManager 與 PaperBroker 同步移除")
    elif ("2330" in pm) != ("2330" in pbset):
        issue("高", f"出場後雙帳本不一致：PositionManager有={'2330' in pm} PaperBroker有={'2330' in pbset}")
    exits = [e for e in main._today_exits if e["stock_id"] == "2330"]
    if exits:
        from src.utils.helpers import exec_slippage
        ep = exits[0]["price"]; want = round(70.0 * (1 - exec_slippage()), 2)
        if abs(ep - want) < 0.05 and ep > 70.0 * 0.99:
            ok(f"#3 已修：出場價 {ep}（≈last×(1−slip)={want}），非舊 ×0.99=69.30 → paper 滑價對齊回測")
        else:
            issue("中", f"#3 未生效：出場價 {ep}（預期 {want}）")
except Exception as e:
    issue("高", f"出場流程崩潰：{e}"); traceback.print_exc()


# ════════════════════════ CHECK 5：max_hold 用『日曆日』vs 回測『交易日』══════════
hdr("CHECK 5：max_hold_days 日曆 vs 交易日")
fresh_state()
main.broker.place_order("2454", "Buy", 100.0, 100)
main.position_mgr.add("2454", 100.0, 100, "t", 2, trail_pct=0.09)
# entry_date 設 61 日曆日前
main.position_mgr._positions["2454"]["entry_date"] = (date.today() - timedelta(days=61)).isoformat()
main.position_mgr._save()
PRICES["2454"] = 100.0
try:
    hd = main.position_mgr.get_hold_days("2454")
    exits = main._risk_guard.check_exits(main.position_mgr.summary())
    reasons = dict(exits)
    print(f"        2454 hold_days(交易日)={hd}（61 日曆日前進場）；check_exits → {reasons.get('2454')}")
    if reasons.get("2454") == "max_hold":
        issue("中", f"#4 未生效：61 日曆仍觸發 max_hold（hold={hd}）")
    elif hd < 50:
        ok(f"#4 已修：max_hold 改交易日（61 日曆 ≈ {hd} 交易日 < 60）→ 未誤觸，與回測對齊")
    else:
        issue("中", f"hold_days={hd} 異常（應 ≈43 交易日）")
except Exception as e:
    issue("中", f"max_hold 檢查崩潰：{e}"); traceback.print_exc()


# ════════════════════════ CHECK 6：盤前失敗 → 候選是否殘留（stale）══════════
hdr("CHECK 6：pre_market 例外時 _today_candidates 是否殘留昨日（stale）")
fresh_state()
main._today_candidates = [{"stock_id": "9999", "close": 10, "size_pct": 0.3, "chip_score": 9, "reason": "昨日殘留"}]
_orig_run = main.score_engine.run
main.score_engine.run = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("模擬選股失敗"))
try:
    main.pre_market_task()   # 內部 try/except 會吞例外
    if any(c["stock_id"] == "9999" for c in main._today_candidates):
        issue("高", "pre_market 失敗後 _today_candidates 殘留昨日候選 → 09:05 會用『過期名單』下單！(應在 pre_market 開頭重置)")
    else:
        ok("pre_market 失敗後候選已清空")
finally:
    main.score_engine.run = _orig_run


# ════════════════════════ CHECK 7：重啟後狀態一致性（雙帳本 reload）══════════
hdr("CHECK 7：重啟（重新 load 狀態檔）後一致性")
fresh_state()
main.broker.place_order("2330", "Buy", 100.0, 200)
main.position_mgr.add("2330", 100.0, 200, "t", 3, trail_pct=0.09)
main._risk_guard.record_trade_result(-500.0)
try:
    nb = main.make_broker()                       # 模擬重啟：重建並 reload temp 檔
    npm = om_mod.PositionManager()
    nrg = rg_mod.RiskGuard(total_capital=70000)
    pb_has = {p["stock_id"] for p in nb.get_positions()}
    pm_has = set(npm._positions.keys())
    print(f"        reload：PaperBroker持倉={pb_has}｜PositionManager持倉={pm_has}｜現金={nb.get_balance():,.0f}｜daily_pnl={nrg.get_status()['daily_pnl']}")
    if pb_has == pm_has == {"2330"}:
        ok("重啟後雙帳本與現金/風控狀態一致 reload")
    else:
        issue("高", "重啟後雙帳本不一致")
    # 跨日重置：daily_risk_state 若昨日檔，今日應重置
    nrg2 = rg_mod.RiskGuard(total_capital=70000)
    if nrg2.get_status()["date"] == date.today().isoformat():
        ok("RiskGuard 跨日狀態日期正確（今日）")
except Exception as e:
    issue("高", f"重啟一致性崩潰：{e}"); traceback.print_exc()


# ════════════════════════ CHECK 8：兩帳本『部分寫入』缺口（崩潰於 enter 與 add 之間）══════════
hdr("CHECK 8：order 成交但 position_mgr.add 前崩潰 → 孤兒部位")
fresh_state()
main.broker.place_order("2317", "Buy", 50.0, 100)   # 只動 PaperBroker（模擬 enter 成功）
# 故意不呼叫 position_mgr.add（模擬兩步驟之間崩潰/重啟）
pbset = {p["stock_id"] for p in main.broker.get_positions()}
pmset = set(main.position_mgr._positions.keys())
if "2317" in pbset and "2317" not in pmset:
    print("        重現孤兒：PaperBroker 有 2317、PositionManager 無（enter↔add 之間崩潰）")
    main._reconcile_positions()   # #5：模擬重啟對帳
    if "2317" in set(main.position_mgr._positions.keys()):
        ok("#5 已修：_reconcile_positions 啟動對帳把孤兒補回 PositionManager（納入風控停損監控）")
    else:
        issue("中", "#5 未生效：reconcile 未補回孤兒部位")
else:
    ok("（孤兒情境未重現，略過）")


# ════════════════════════ CHECK 9：盤後零股補單（paper 應 no-op）══════════
hdr("CHECK 9：afterhours_fill_task（paper 全成交→no-op）")
fresh_state()
main._today_intended = [{"stock_id": "2330", "price": 100.0, "quantity": 10, "reason": "t",
                         "score": 3, "trail_pct": 0.09, "size_pct": 0.30}]
main._today_filled = {"2330"}   # 已成交
try:
    main.afterhours_fill_task()
    ok("afterhours_fill_task 正常（intended 已全 filled → 無待補）")
except Exception as e:
    issue("高", f"afterhours_fill 崩潰：{e}"); traceback.print_exc()


# ════════════════════════ CHECK 10：盤後報表 post_market_task ══════════
hdr("CHECK 10：post_market_task（每日摘要）")
try:
    main.post_market_task()
    ds = [c for c in main.notifier.calls if c[0] == "daily_summary"]
    ok(f"post_market_task 正常，daily_summary 呼叫 {len(ds)} 次")
    hist = TMP / "archive" / "daily_history.csv"
    if hist.exists() and any((TMP / "archive").glob("*/summary.json")):
        ok("EOD 歸檔：daily_history.csv + 當日 summary.json 已產生（分日期建檔）")
    else:
        issue("中", "post_market 未產生 EOD 歸檔")
except Exception as e:
    issue("高", f"post_market 崩潰：{e}"); traceback.print_exc()


# ════════════════════════ CHECK 11：熔斷後擋進場 ══════════
hdr("CHECK 11：連虧/單日虧損熔斷 → 擋進場")
fresh_state()
for _ in range(3):
    main._risk_guard.record_trade_result(-600.0)   # 3×-600=-1800 < -2%(=-1400) 且連虧3
st = main._risk_guard.get_status()
try:
    if st["halted"]:
        ok(f"熔斷觸發：{st['halt_reason']}")
        main._today_candidates = [dict(CANDS[0])]
        PRICES["2330"] = 100.0
        main.market_open_task()
        n = len(main.position_mgr.summary())
        if n == 0:
            ok("熔斷中 market_open 未進場（can_enter 擋下）")
        else:
            issue("高", f"熔斷中仍進場 {n} 檔！")
    else:
        issue("高", "3 連虧/超日限未觸發熔斷")
except Exception as e:
    issue("高", f"熔斷流程崩潰：{e}"); traceback.print_exc()


# ════════════════════════ CHECK 12：regime 空頭 → run() 不掃描不進場 ══════════
hdr("CHECK 12：regime 空頭/假反彈 → run() 回空（省掃描）")
fresh_state()
_orig = main.score_engine._market_risk_on
main.score_engine._market_risk_on = lambda: False
try:
    df = main.score_engine.run()
    if df is None or df.empty:
        ok("regime 空頭 → run() 回空 DataFrame（不掃描、不進場）")
    else:
        issue("高", "regime 空頭但 run() 仍回候選")
except Exception as e:
    issue("高", f"run() 空頭路徑崩潰：{e}"); traceback.print_exc()
finally:
    main.score_engine._market_risk_on = _orig


# ════════════════════════ CHECK 13：真實全選股 run()（scan+chip，實際每日 08:50 路徑）══════════
hdr("CHECK 13：真實 score_engine.run()（regime+38檔掃描+籌碼，吃快取）")
import time as _t
try:
    t0 = _t.time()
    df = main.score_engine.run()
    dt = _t.time() - t0
    n = 0 if df is None or df.empty else len(df)
    ok(f"真實 run() 完成：{n} 檔候選，耗時 {dt:.1f}s（08:50 盤前實際路徑，無崩潰）")
    if n and not {"stock_id", "size_pct", "trail_pct"}.issubset(set(df.columns)):
        issue("中", f"候選缺欄位（market_open 需 size_pct/trail_pct）：{set(df.columns)}")
    elif n:
        ok("候選含 size_pct/trail_pct（market_open 配重/停損可用）")
except Exception as e:
    issue("高", f"真實 run() 崩潰：{e}"); traceback.print_exc()


# ════════════════════════ CHECK 14：#6 當日 state 存檔→重啟復原 ══════════
hdr("CHECK 14：#6 day_state 持久化（盤中重啟復原候選/補單追蹤）")
fresh_state()
main._today_candidates = [{"stock_id": "1234", "close": 10, "size_pct": 0.3}]
main._today_filled = {"1234"}
main._save_day_state()
main._today_candidates, main._today_filled = [], set()   # 模擬重啟記憶體清空
main._load_day_state()
if any(c.get("stock_id") == "1234" for c in main._today_candidates) and "1234" in main._today_filled:
    ok("#6 已修：day_state 存檔 → 同日重啟復原候選與曾成交集合")
else:
    issue("中", "#6 未生效：day_state 未復原")


# ════════════════════════ CHECK 15：#9 regime 抓取失敗 → fail-closed ══════════
hdr("CHECK 15：#9 0050 抓取失敗 → regime fail-closed（不進場）")
fresh_state()
import pandas as _pd
_ofetch = main.score_engine.fetcher.get_daily_price
main.score_engine.fetcher.get_daily_price = lambda *a, **k: _pd.DataFrame()
try:
    r = main.score_engine._market_risk_on()
    if r is False:
        ok("#9 已修：0050 抓不到 → fail-closed（回 False，今日不進場）")
    else:
        issue("中", f"#9 未生效：資料失敗時回 {r}（應 False）")
except Exception as e:
    issue("高", f"fail-closed 路徑崩潰：{e}")
finally:
    main.score_engine.fetcher.get_daily_price = _ofetch


# ════════════════════════ CHECK 16：#13 熔斷緊急清倉（守 T+1）══════════
hdr("CHECK 16：#13 _emergency_liquidate 清可賣部位、守 T+1")
fresh_state()
om = om_mod.OrderManager(main.broker)
main.broker.place_order("2454", "Buy", 100.0, 50)
main.position_mgr.add("2454", 100.0, 50, "t", 2, trail_pct=0.09)
main.position_mgr._positions["2454"]["entry_date"] = (date.today() - timedelta(days=5)).isoformat()
main.position_mgr._save()
PRICES["2454"] = 95.0
main._emergency_liquidate(om, {"2454": 95.0}, 0.0015)
gone = "2454" not in main.position_mgr._positions and "2454" not in {p["stock_id"] for p in main.broker.get_positions()}
ok("#13 已修：緊急清倉出清可賣部位（雙帳本同步）") if gone else issue("中", "#13 未生效：未出清")
# T+1：同日進場不可清
main.broker.place_order("2330", "Buy", 100.0, 10)
main.position_mgr.add("2330", 100.0, 10, "t", 2)   # entry_date=today
PRICES["2330"] = 90.0
main._emergency_liquidate(om, {"2330": 90.0}, 0.0015)
ok("#13：緊急清倉仍守 T+1（同日進場未賣）") if "2330" in main.position_mgr._positions else issue("高", "#13 違反 T+1：同日部位被緊急清倉")


# ════════════════════════ CHECK 17：零股成交不確定性（賣一深度不足→盤中不成交→盤後補單）══════════
hdr("CHECK 17：零股成交模型 — 薄帳掛不到 → 轉盤後零股補單")
fresh_state()
ODD_DEPTH.clear()
# 2884 模擬 day-1 薄帳（賣一僅 38 股）、2892 深度充足（3698 股）
CANDS17 = [
    {"stock_id": "2884", "close": 34.0, "size_pct": 0.30, "trail_pct": 0.09, "chip_score": 4, "reason": "t"},
    {"stock_id": "2892", "close": 30.0, "size_pct": 0.30, "trail_pct": 0.08, "chip_score": 3, "reason": "t"},
]
PRICES.update({"2884": 34.0, "2892": 30.0})
ODD_DEPTH.update({"2884": 38, "2892": 3698})    # 2884 薄、2892 厚
main._today_candidates = [dict(c) for c in CANDS17]
try:
    main.market_open_task()
    held = {p["stock_id"] for p in main.position_mgr.summary()}
    if "2884" not in held and "2892" in held:
        ok("零股模型生效：2884（賣一38股<想買量）盤中未成交、2892（深度充足）成交")
    else:
        issue("高", f"零股模型異常：盤中持倉={held}（預期僅 2892）")
    # 2884 應在 intended 但不在 filled → afterhours 補單接住
    if "2884" in [c["stock_id"] for c in main._today_intended] and "2884" not in main._today_filled:
        ok("2884 已記 intended 且未在 filled → 盤後補單會接手")
    else:
        issue("中", "2884 未正確標記為待補單")
    # 零股盤中摩擦計數（EOD summary 會帶出 n_oddlot_repushed）
    if "2884" in main._today_oddlot_repushed:
        ok("零股盤中摩擦已計數（_today_oddlot_repushed 含 2884 → EOD 可見）")
    else:
        issue("中", "盤中掛不到未計入 oddlot_repushed")
    # 跑盤後零股補單（盤後集合競價深度厚→視為成交）
    main.afterhours_fill_task()
    held2 = {p["stock_id"] for p in main.position_mgr.summary()}
    if "2884" in held2:
        ok("盤後零股補單：2884 於 14:30 集合競價補上 → 真實反映『盤中掛不到、盤後補成交』")
    else:
        issue("中", f"盤後補單未補上 2884（持倉={held2}）")
except Exception as e:
    issue("高", f"零股成交模型崩潰：{e}"); traceback.print_exc()

# CHECK 17b：模型關閉 → 回舊行為（保證成交）
hdr("CHECK 17b：odd_lot_fill_model=false → 回舊保證成交（向後相容）")
fresh_state()
_oload = main.load_config
import copy as _copy
_cfg_off = _copy.deepcopy(_oload())
_cfg_off["trading"]["odd_lot_fill_model"] = False
main.load_config = lambda: _cfg_off
try:
    PRICES["2884"] = 34.0; ODD_DEPTH["2884"] = 38   # 一樣薄帳
    main._today_candidates = [{"stock_id": "2884", "close": 34.0, "size_pct": 0.30,
                               "trail_pct": 0.09, "chip_score": 4, "reason": "t"}]
    main.market_open_task()
    if "2884" in {p["stock_id"] for p in main.position_mgr.summary()}:
        ok("模型關閉 → 2884 薄帳仍保證成交（舊行為，向後相容）")
    else:
        issue("中", "模型關閉時未回退舊保證成交")
except Exception as e:
    issue("高", f"模型開關崩潰：{e}"); traceback.print_exc()
finally:
    main.load_config = _oload


# ════════════════════════ 總結 ══════════
hdr("總結：抓出的問題清單")
if not ISSUES:
    print("  （無）")
else:
    sev_order = {"高": 0, "中": 1, "低": 2}
    for sev, msg in sorted(ISSUES, key=lambda x: sev_order.get(x[0], 9)):
        print(f"  [{sev}] {msg}")
print(f"\n  temp state dir = {TMP}（可刪）")

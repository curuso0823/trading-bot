"""
utils/eod_archive.py
收盤後（post_market）把當日 paper 狀態彙整、分日期歸檔，供事後分析。

問題：data/processed/ 的狀態檔多為「覆寫」（paper_account/positions/daily_risk_state/day_state），
每天會被隔日蓋掉 → 當日收盤快照遺失，無法回看「這 10 天 paper 怎麼跑的」。

解法（不動 live 檔路徑，只在 EOD 複製快照）：
  data/archive/{YYYY-MM-DD}/   ← 當日完整快照：summary.json + 各 state 檔副本 + 候選 + 當日滑價
  data/archive/daily_history.csv ← 每日一列時間序列（權益/報酬/損益/進出場/regime），最方便分析

用：main.post_market_task 14:00 呼叫 archive_eod()。也可手動補跑分析。
"""
import json
import csv
import shutil
from datetime import date
from pathlib import Path
from loguru import logger

PROC = Path("data/processed")
ARCHIVE_DIR = Path("data/archive")
HISTORY_FIELDS = ["date", "equity", "cash", "pos_value", "cum_return_pct", "daily_pnl",
                  "n_positions", "n_candidates", "n_entries", "n_exits", "n_slippage",
                  "n_intended", "n_oddlot_repushed", "halted", "regime", "lot"]


def _read_json(p: Path, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def archive_eod(initial_capital: float, regime_label: str = "", lot: int = 1,
                proc_dir=None, archive_dir=None) -> dict:
    """彙整當日 state → data/archive/{date}/ 快照 + daily_history.csv 一列。回傳 summary dict。
    proc_dir/archive_dir 預設取模組常數（call-time 解析 → 可被測試/工具覆寫）。
    永不拋例外（包在 try）→ 不讓歸檔拖垮 post_market。"""
    try:
        return _archive_eod(initial_capital, regime_label, lot,
                            Path(proc_dir or PROC), Path(archive_dir or ARCHIVE_DIR))
    except Exception as e:
        logger.warning(f"EOD 歸檔失敗（不影響交易）：{e}")
        return {}


def _archive_eod(initial_capital, regime_label, lot, proc_dir, archive_dir) -> dict:
    today = date.today().isoformat()
    daydir = archive_dir / today
    daydir.mkdir(parents=True, exist_ok=True)

    account = _read_json(proc_dir / "paper_account.json", {}) or {}
    positions = _read_json(proc_dir / "positions.json", {}) or {}
    risk = _read_json(proc_dir / "daily_risk_state.json", {}) or {}
    daystate = _read_json(proc_dir / "day_state.json", {}) or {}

    cash = float(account.get("cash", initial_capital) or initial_capital)
    pos_value = 0.0
    for _sid, p in positions.items():
        last = float(p.get("last_price", p.get("entry_price", 0)) or 0)
        qty = float(p.get("quantity", 0) or 0)
        pos_value += last * qty * lot
    equity = cash + pos_value
    exits = daystate.get("exits", []) or []
    filled = daystate.get("filled", []) or []
    candidates = daystate.get("candidates", []) or []
    intended = daystate.get("intended", []) or []
    oddlot_repushed = daystate.get("oddlot_repushed", []) or []   # 盤中零股掛不到→轉盤後

    # 當日滑價（從累積 log 濾出今日列，另存一份到 daydir）
    n_slip = 0
    slog = proc_dir / "slippage_log.csv"
    if slog.exists():
        try:
            with open(slog, encoding="utf-8-sig", newline="") as f:
                today_rows = [r for r in csv.DictReader(f) if str(r.get("ts", "")).startswith(today)]
            n_slip = len(today_rows)
            if today_rows:
                with open(daydir / "slippage_today.csv", "w", encoding="utf-8-sig", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=today_rows[0].keys())
                    w.writeheader()
                    w.writerows(today_rows)
        except Exception:
            pass

    summary = {
        "date": today, "equity": round(equity, 1), "cash": round(cash, 1),
        "pos_value": round(pos_value, 1),
        "cum_return_pct": round((equity / initial_capital - 1) * 100, 2) if initial_capital else 0.0,
        "daily_pnl": round(float(risk.get("daily_pnl", 0) or 0), 1),
        "n_positions": len(positions), "n_candidates": len(candidates),
        "n_entries": len(filled), "n_exits": len(exits), "n_slippage": n_slip,
        "n_intended": len(intended),                          # 想進場筆數
        "n_oddlot_repushed": len(oddlot_repushed),            # 盤中零股掛不到→轉盤後（零股摩擦量化）
        "halted": bool(risk.get("halted", False)), "regime": regime_label or "", "lot": lot,
        "positions": positions, "exits": exits,
    }

    # 1) 當日完整快照
    with open(daydir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    for fn in ["paper_account.json", "positions.json", "daily_risk_state.json", "day_state.json"]:
        src = proc_dir / fn
        if src.exists():
            shutil.copy2(src, daydir / fn)
    cand = proc_dir / f"candidates_{today}.csv"
    if cand.exists():
        shutil.copy2(cand, daydir / cand.name)

    # 2) daily_history.csv 一列（同日去重 → 可重跑覆蓋）
    archive_dir.mkdir(parents=True, exist_ok=True)
    hist = archive_dir / "daily_history.csv"
    rows = []
    if hist.exists():
        with open(hist, encoding="utf-8-sig", newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("date") != today]
    rows.append({k: summary[k] for k in HISTORY_FIELDS})
    rows.sort(key=lambda r: r["date"])
    with open(hist, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        w.writeheader()
        w.writerows(rows)

    logger.info(f"EOD 歸檔 → {daydir}｜權益 {equity:,.0f}、今日損益 {summary['daily_pnl']:+,.0f}、"
                f"持倉 {len(positions)}、進場 {len(filled)}、出場 {len(exits)}、regime {regime_label}")
    return summary


def print_history(archive_dir: Path = ARCHIVE_DIR) -> None:
    """快速檢視 daily_history.csv（連跑數日後用）。"""
    hist = Path(archive_dir) / "daily_history.csv"
    if not hist.exists():
        print("尚無 daily_history（需收盤 EOD 歸檔後產生）")
        return
    with open(hist, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"{'日期':>11}{'權益':>10}{'累報酬%':>9}{'日損益':>9}{'持倉':>5}{'進':>4}{'出':>4}{'掛不到':>6}  regime")
    for r in rows:
        print(f"{r['date']:>11}{float(r['equity']):>10,.0f}{float(r['cum_return_pct']):>8.2f}%"
              f"{float(r['daily_pnl']):>+9,.0f}{r['n_positions']:>5}{r['n_entries']:>4}{r['n_exits']:>4}"
              f"{r.get('n_oddlot_repushed', 0) or 0:>6}  {r.get('regime','')}")

"""
notify/notify_manager.py
通知節流層：包住「主推播(LINE)」+「備援(Discord)」，
- 主推播每日上限（預設 8）+ 持久化計數 + 跨日自動重置
- 超過上限 或 主推播失敗 → 自動轉備援
- 分級：CRITICAL(停損/熔斷/錯誤) 不受每日上限；NORMAL(進場/摘要) 受上限；LOW(啟動/盤前) 只記 log
- 批次：同時段重要訊息打包成 1 則，降低每日發訊次數

main.py 只與本類互動（高階語意方法），各 channel 只需 send_text(text)->bool。
"""
import json
from datetime import date
from pathlib import Path
from loguru import logger


class NotifyManager:
    COUNT_FILE = "data/processed/notify_count.json"

    def __init__(self, primary, backup, daily_cap: int = 8, error_cap: int = 2):
        self.primary = primary    # LineNotifier
        self.backup = backup      # DiscordNotifier
        self.daily_cap = daily_cap
        self.error_cap = error_cap
        self._state = self._load()

    # ---------- 計數持久化 ----------
    def _load(self) -> dict:
        p = Path(self.COUNT_FILE)
        today = date.today().isoformat()
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    s = json.load(f)
                if s.get("date") == today:
                    return s
            except Exception:
                pass
        return {"date": today, "primary": 0, "errors": 0}

    def _save(self):
        Path(self.COUNT_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(self.COUNT_FILE, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    def _roll(self):
        today = date.today().isoformat()
        if self._state.get("date") != today:
            self._state = {"date": today, "primary": 0, "errors": 0}

    # ---------- 路由 ----------
    def _route(self, text: str, critical: bool = False) -> bool:
        """critical=True 不受每日上限（仍計數）。超額/失敗 → 備援。"""
        self._roll()
        sent = False
        if critical or self._state["primary"] < self.daily_cap:
            sent = bool(self.primary.send_text(text))
            if sent:
                self._state["primary"] += 1
                self._save()
        if not sent:  # 超過上限 或 主推播失敗 → 備援
            sent = bool(self.backup.send_text(text))
            if not sent:
                logger.warning(f"主+備援皆未送出：{text[:50]}")
        return sent

    # ---------- 高階語意方法（main.py 用）----------
    def system(self, text: str):
        """低優先（啟動/關閉/盤前）：只記 log，不佔 LINE 額度。"""
        logger.info(f"[notify-system] {text}")

    def entries(self, items: list):
        """批次進場 → 1 則。item: {stock_id,name,price,quantity,chip_score,reason}"""
        if not items:
            return
        lines = [f"📈 今日進場 {len(items)} 檔"]
        for it in items:
            lines.append(f"• {it['stock_id']} {it.get('name','')} {it['quantity']}股 "
                         f"@${it['price']:.2f}｜分{it.get('chip_score',0):.1f}｜{it.get('reason','')}")
        self._route("\n".join(lines))

    def exits_critical(self, items: list):
        """緊急出場(停損/移動停損)批次 → 1 則即時。item: {stock_id,reason,pnl_pct,price}"""
        if not items:
            return
        lines = [f"🚨 出場警示 {len(items)} 檔"]
        for it in items:
            lines.append(f"• {it['stock_id']} {it['reason']} {it['pnl_pct']:+.1f}% @${it['price']:.2f}")
        self._route("\n".join(lines), critical=True)

    def halt(self, reason: str):
        self._route(f"🔴 風控熔斷\n{reason}\n系統暫停，請人工 resume()", critical=True)

    def daily_summary(self, positions, daily_pnl, total_capital,
                      candidates_count, exits_today=None):
        pnl_pct = daily_pnl / total_capital * 100 if total_capital else 0
        lines = [f"📊 每日摘要 {date.today().isoformat()}",
                 f"今日損益 {pnl_pct:+.1f}%（{daily_pnl:+.0f}元）｜候選 {candidates_count} 檔"]
        if exits_today:
            lines.append(f"今日出場 {len(exits_today)} 筆：" + "、".join(
                f"{e['stock_id']}({e['reason']} {e['pnl_pct']:+.1f}%)" for e in exits_today))
        pos_lines = [f"  {'↑' if p['pnl_pct'] >= 0 else '↓'} {p['stock_id']} "
                     f"{p['pnl_pct']:+.1f}% ({p['hold_days']}日)" for p in positions]
        lines.append("持倉：")
        lines += pos_lines or ["  （無持倉）"]
        self._route("\n".join(lines))

    def error(self, error, context: str = ""):
        """錯誤：每日上限 error_cap 則走主推播，其餘只進備援+log（避免錯誤風暴吃額度）。"""
        self._roll()
        text = f"⚠️ 系統錯誤\n位置：{context}\n{str(error)[:200]}"
        if self._state["errors"] < self.error_cap:
            if self._route(text, critical=True):
                self._state["errors"] += 1
                self._save()
        else:
            self.backup.send_text(text)
            logger.error(f"[error overflow→backup] {context}")

    # 相容舊呼叫
    def send_text(self, text: str):
        self.system(text)

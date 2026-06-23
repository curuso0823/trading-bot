"""
dashboard.py — 模擬盤「唯讀」監控網頁（display-only）
================================================================
純 Python 標準函式庫（http.server / json / csv），零新依賴。
只「讀」bot 寫出的狀態檔，不下任何單、不改任何狀態 → 與交易完全解耦，
即使 dashboard 崩了也不影響 bot；bot 沒在跑時照樣能看最後狀態。

讀取來源（data/processed/）：
  positions.json        持倉即時標記（進場/現價/峰值/股數/日期）
  paper_account.json    現金
  daily_risk_state.json 今日已實現損益 / 連虧 / 熔斷
  slippage_log.csv      真實零股滑價
  candidates_*.csv      當日候選
  logs/*.log            日誌尾巴
另外自己 append data/processed/equity_curve.csv（每分鐘一筆，畫權益曲線；屬監控檔非交易狀態）。

用法（專案根目錄、用 venv 的 python）：
  .\.venv\Scripts\python.exe dashboard.py
  瀏覽器開 http://127.0.0.1:8787
  手機同 Wi-Fi 想看 → 設環境變數再跑：  $env:DASHBOARD_HOST="0.0.0.0"; .\.venv\Scripts\python.exe dashboard.py
  然後手機開 http://<電腦區網IP>:8787
停止：Ctrl+C
"""
import os
import sys
import json
import csv
import glob
import html
from datetime import date, datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
PROC = ROOT / "data" / "processed"
LOGS = ROOT / "logs"
EQUITY_CSV = PROC / "equity_curve.csv"
ARCHIVE_DIR = ROOT / "data" / "archive"

HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("DASHBOARD_PORT", "8787"))
REFRESH_SEC = int(os.environ.get("DASHBOARD_REFRESH", "10"))


# ────────────────────────── 設定讀取（容錯） ──────────────────────────
def _load_yaml(path: Path) -> dict:
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def load_cfg() -> dict:
    strat = _load_yaml(ROOT / "config" / "strategy.yaml")
    settings = _load_yaml(ROOT / "config" / "settings.yaml")
    trading = strat.get("trading", {})
    exit_ = strat.get("exit", {})
    entry = strat.get("entry", {})
    broker = settings.get("broker", {})
    return {
        "lot_size": trading.get("lot_size", 1),
        "trailing": exit_.get("trailing_stop_pct", 0.12),
        "use_trailing": exit_.get("use_trailing", True),
        "stop_loss": exit_.get("stop_loss_pct", -0.05),
        "max_positions": entry.get("max_positions", 6),
        "initial_cash": broker.get("paper_initial_cash", 150_000),
        "mode": broker.get("mode", "paper"),
        "odd_slip_assumed": trading.get("odd_lot_slippage", 0.0015),
    }


# ────────────────────────── 狀態檔讀取（容錯） ──────────────────────────
def _read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _read_csv(path: Path) -> list[dict]:
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _tail(path: Path, n: int = 25) -> list[str]:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            f.seek(max(0, size - 16384))
            data = f.read().decode("utf-8", errors="replace")
        return data.splitlines()[-n:]
    except Exception:
        return []


def _newest(pattern: str) -> Path | None:
    files = glob.glob(str(PROC / pattern)) if "processed" not in pattern else glob.glob(pattern)
    files = glob.glob(str(PROC / pattern))
    return Path(max(files, key=os.path.getmtime)) if files else None


# ────────────────────────── 計算快照 ──────────────────────────
def build_snapshot(cfg: dict) -> dict:
    lot = cfg["lot_size"]
    positions_raw = _read_json(PROC / "positions.json", {}) or {}
    account = _read_json(PROC / "paper_account.json", {}) or {}
    risk = _read_json(PROC / "daily_risk_state.json", {}) or {}

    cash = float(account.get("cash", cfg["initial_cash"]))
    today = date.today()

    rows, pos_value = [], 0.0
    for sid, p in positions_raw.items():
        entry = float(p.get("entry_price", 0) or 0)
        last = float(p.get("last_price", entry) or entry)
        peak = float(p.get("peak_price", entry) or entry)
        qty = float(p.get("quantity", 0) or 0)
        try:
            hold = (today - date.fromisoformat(str(p.get("entry_date", today)))).days
        except Exception:
            hold = 0
        mv = last * qty * lot
        cost_v = entry * qty * lot
        pos_value += mv
        pnl_pct = (last / entry - 1) * 100 if entry > 0 else 0.0
        from_peak = (last / peak - 1) * 100 if peak > 0 else 0.0  # 距峰值（負=回落）
        trail_w = float(p.get("trail_pct") or cfg["trailing"])     # A1：per-position ATR 寬度，無則固定%
        trail_room = from_peak + trail_w * 100                     # 離移動停損還剩幾 %（越小越危險）
        rows.append({
            "sid": sid, "qty": qty, "entry": entry, "last": last, "peak": peak,
            "pnl_pct": pnl_pct, "upnl": mv - cost_v, "hold": hold,
            "from_peak": from_peak, "trail_room": trail_room,
            "reason": p.get("reason", ""), "score": p.get("score"),
        })
    rows.sort(key=lambda r: r["trail_room"])  # 最接近停損的排前面

    equity = cash + pos_value
    initial = float(cfg["initial_cash"])
    daily_pnl = float(risk.get("daily_pnl", 0.0) or 0.0)

    # 滑價統計
    slip = _read_csv(PROC / "slippage_log.csv")
    def _med(col):
        vals = sorted(float(r[col]) for r in slip if r.get(col) not in (None, ""))
        return vals[len(vals)//2] if vals else None
    slip_stat = {
        "n": len(slip),
        "half_med": _med("half_spread_pct"),
        "impl_med": _med("impl_slip_pct"),
        "assumed": cfg["odd_slip_assumed"] * 100,
    }

    # 候選（最新一檔）
    cand_file = _newest("candidates_*.csv")
    candidates = _read_csv(cand_file)[:10] if cand_file else []

    # 近日戰績（EOD 歸檔的 daily_history.csv，每日一列）
    history = _read_csv(ARCHIVE_DIR / "daily_history.csv")[-12:]

    # 日誌尾巴
    log_file = None
    logs = glob.glob(str(LOGS / "*.log"))
    if logs:
        log_file = Path(max(logs, key=os.path.getmtime))
    log_lines = _tail(log_file, 25) if log_file else []

    return {
        "mode": cfg["mode"], "halted": bool(risk.get("halted")),
        "halt_reason": risk.get("halt_reason", ""),
        "consec": risk.get("consecutive_loss", 0),
        "cash": cash, "pos_value": pos_value, "equity": equity, "initial": initial,
        "cum_ret": (equity / initial - 1) * 100 if initial else 0.0,
        "daily_pnl": daily_pnl, "daily_pnl_pct": daily_pnl / initial * 100 if initial else 0.0,
        "n_pos": len(rows), "max_pos": cfg["max_positions"], "trailing": cfg["trailing"] * 100,
        "positions": rows, "slip": slip_stat, "candidates": candidates, "history": history,
        "cand_file": cand_file.name if cand_file else None,
        "log_lines": log_lines, "log_file": log_file.name if log_file else None,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def sample_equity(snap: dict):
    """每分鐘 append 一筆權益到 equity_curve.csv（自身監控檔，非交易狀態）。"""
    try:
        PROC.mkdir(parents=True, exist_ok=True)
        now_min = datetime.now().strftime("%Y-%m-%dT%H:%M")
        last_min = None
        if EQUITY_CSV.exists():
            with open(EQUITY_CSV, encoding="utf-8") as f:
                rows = f.read().splitlines()
            if len(rows) > 1:
                last_min = rows[-1].split(",")[0][:16]
        if last_min == now_min:
            return
        new = not EQUITY_CSV.exists()
        with open(EQUITY_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["ts", "equity", "cash", "pos_value", "daily_pnl"])
            w.writerow([datetime.now().isoformat(timespec="minutes"),
                        round(snap["equity"], 1), round(snap["cash"], 1),
                        round(snap["pos_value"], 1), round(snap["daily_pnl"], 1)])
        # #12：避免無限長 — 超過上限即裁切保留最後 N 筆（保表頭）
        _trim_equity_csv()
    except Exception:
        pass


def _trim_equity_csv(cap: int = 8000, keep: int = 5000):
    try:
        if not EQUITY_CSV.exists():
            return
        with open(EQUITY_CSV, encoding="utf-8") as f:
            rows = f.read().splitlines()
        if len(rows) <= cap:
            return
        head, body = rows[0], rows[1:]
        with open(EQUITY_CSV, "w", newline="", encoding="utf-8") as f:
            f.write("\n".join([head] + body[-keep:]) + "\n")
    except Exception:
        pass


def equity_points(limit: int = 400) -> list[float]:
    rows = _read_csv(EQUITY_CSV)
    pts = []
    for r in rows[-limit:]:
        try:
            pts.append(float(r["equity"]))
        except Exception:
            pass
    return pts


# ────────────────────────── SVG 走勢圖（純字串） ──────────────────────────
def svg_sparkline(pts: list[float], w=720, h=120) -> str:
    if len(pts) < 2:
        return '<div class="muted">（權益曲線需累積 ≥2 筆取樣，dashboard 開著就會逐分鐘記錄）</div>'
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1
    step = w / (len(pts) - 1)
    coords = " ".join(f"{i*step:.1f},{h - (p-lo)/rng*(h-10) - 5:.1f}" for i, p in enumerate(pts))
    up = pts[-1] >= pts[0]
    color = "#34d399" if up else "#f87171"
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" '
            f'style="width:100%;height:{h}px">'
            f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{coords}"/>'
            f'</svg>')


# ────────────────────────── HTML 渲染 ──────────────────────────
def money(v): return f"{v:,.0f}"
def pct(v): return f"{v:+.2f}%"
def cls(v): return "pos" if v >= 0 else "neg"


def render(snap: dict) -> str:
    s = snap
    halt_banner = (f'<div class="halt">🔴 風控熔斷中：{html.escape(str(s["halt_reason"]))}'
                   f'（人工 resume 後恢復）</div>') if s["halted"] else ""

    cards = [
        ("總權益", money(s["equity"]), "", "現金+持倉市值"),
        ("累計報酬", pct(s["cum_ret"]), cls(s["cum_ret"]), f"初始 {money(s['initial'])}"),
        ("今日已實現", f"{s['daily_pnl']:+,.0f}", cls(s["daily_pnl"]), pct(s["daily_pnl_pct"])),
        ("現金", money(s["cash"]), "", f"持倉市值 {money(s['pos_value'])}"),
        ("持倉數", f"{s['n_pos']}/{s['max_pos']}", "", f"連虧 {s['consec']}"),
    ]
    card_html = "".join(
        f'<div class="card"><div class="k">{k}</div>'
        f'<div class="v {c}">{v}</div><div class="sub">{sub}</div></div>'
        for k, v, c, sub in cards)

    if s["positions"]:
        prows = "".join(
            f'<tr><td>{html.escape(p["sid"])}</td><td class="r">{p["qty"]:g}</td>'
            f'<td class="r">{p["entry"]:.2f}</td><td class="r">{p["last"]:.2f}</td>'
            f'<td class="r {cls(p["pnl_pct"])}">{pct(p["pnl_pct"])}</td>'
            f'<td class="r {cls(p["upnl"])}">{p["upnl"]:+,.0f}</td>'
            f'<td class="r">{p["hold"]}日</td>'
            f'<td class="r {cls(p["from_peak"])}">{p["from_peak"]:+.1f}%</td>'
            f'<td class="r {"neg" if p["trail_room"] < 4 else ""}">{p["trail_room"]:.1f}%</td></tr>'
            for p in s["positions"])
        ptable = (f'<table><thead><tr><th>代號</th><th class="r">股數</th>'
                  f'<th class="r">進場</th><th class="r">現價</th><th class="r">損益%</th>'
                  f'<th class="r">未實現</th><th class="r">持有</th><th class="r">距峰值</th>'
                  f'<th class="r">離停損</th></tr></thead><tbody>{prows}</tbody></table>'
                  f'<div class="muted">「離停損」= 距移動停損({s["trailing"]:.0f}%)還剩幾%，越小越危險（&lt;4% 標紅）</div>')
    else:
        ptable = '<div class="muted">（目前無持倉）</div>'

    sl = s["slip"]
    if sl["n"]:
        slip_html = (f'樣本 {sl["n"]} 筆｜半價差中位 <b>{sl["half_med"]:.3f}%</b>｜'
                     f'隱含滑價中位 <b>{sl["impl_med"]:.3f}%</b>｜'
                     f'回測假設 {sl["assumed"]:.3f}% '
                     f'{"✅貼近" if (sl["impl_med"] or 0) <= sl["assumed"]*1.2 else "⚠️偏高，考慮上調"}')
    else:
        slip_html = '<span class="muted">尚無滑價樣本（盤中進場時量測）</span>'

    if s["candidates"]:
        keys = list(s["candidates"][0].keys())[:5]
        chead = "".join(f"<th>{html.escape(k)}</th>" for k in keys)
        crows = "".join("<tr>" + "".join(
            f'<td>{html.escape(str(c.get(k, "")))}</td>' for k in keys) + "</tr>"
            for c in s["candidates"])
        cand_html = (f'<table><thead><tr>{chead}</tr></thead><tbody>{crows}</tbody></table>'
                     f'<div class="muted">來源 {html.escape(s["cand_file"] or "")}</div>')
    else:
        cand_html = '<div class="muted">（尚無候選清單）</div>'

    if s.get("history"):
        def _f(v, d=0):
            try: return float(v)
            except Exception: return d
        hrows = "".join(
            f'<tr><td>{html.escape(h.get("date",""))}</td>'
            f'<td class="r">{_f(h.get("equity")):,.0f}</td>'
            f'<td class="r {cls(_f(h.get("cum_return_pct")))}">{_f(h.get("cum_return_pct")):+.2f}%</td>'
            f'<td class="r {cls(_f(h.get("daily_pnl")))}">{_f(h.get("daily_pnl")):+,.0f}</td>'
            f'<td class="r">{h.get("n_positions","")}</td>'
            f'<td class="r">{h.get("n_entries","")}/{h.get("n_exits","")}</td>'
            f'<td class="r">{h.get("n_oddlot_repushed","") or ""}</td>'
            f'<td>{html.escape(str(h.get("regime","")))}</td></tr>'
            for h in s["history"])
        hist_html = (f'<table><thead><tr><th>日期</th><th class="r">權益</th><th class="r">累報酬</th>'
                     f'<th class="r">日損益</th><th class="r">持倉</th><th class="r">進/出</th>'
                     f'<th class="r" title="盤中零股賣一深度不足、掛不到→轉盤後補單的筆數">掛不到</th>'
                     f'<th>regime</th></tr></thead><tbody>{hrows}</tbody></table>'
                     f'<div class="muted">每日收盤(14:00)自動歸檔 → data/archive/&lt;日期&gt;/ 與 daily_history.csv</div>')
    else:
        hist_html = '<div class="muted">（尚無每日戰績；首個交易日收盤後產生）</div>'

    log_html = "".join(
        f'<div class="logline {"err" if ("ERROR" in l or "CRITICAL" in l) else ("warn" if "WARNING" in l else "")}">'
        f'{html.escape(l)}</div>' for l in s["log_lines"]) or '<div class="muted">（無日誌）</div>'

    spark = svg_sparkline(equity_points())

    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_SEC}">
<title>交易監控｜模擬盤</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:#0b0f17;color:#e5e7eb;font:14px/1.5 -apple-system,"Segoe UI",system-ui,sans-serif}}
.wrap{{max-width:980px;margin:0 auto;padding:16px}}
h1{{font-size:18px;margin:0}}
.top{{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px}}
.badge{{padding:2px 8px;border-radius:6px;background:#1f2937;font-size:12px}}
.halt{{background:#7f1d1d;color:#fff;padding:10px;border-radius:8px;margin:12px 0;font-weight:600}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}}
.card{{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:12px}}
.card .k{{color:#9ca3af;font-size:12px}}
.card .v{{font-size:22px;font-weight:700;margin:2px 0}}
.card .sub{{color:#6b7280;font-size:11px}}
section{{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:12px;margin:12px 0}}
section>h2{{font-size:13px;color:#9ca3af;margin:0 0 8px;font-weight:600}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:6px 8px;border-bottom:1px solid #1f2937;text-align:left}}
th{{color:#9ca3af;font-weight:600}}
.r{{text-align:right;font-variant-numeric:tabular-nums}}
.pos{{color:#34d399}} .neg{{color:#f87171}}
.muted{{color:#6b7280;font-size:12px;margin-top:6px}}
.logwrap{{font:12px/1.45 ui-monospace,Consolas,monospace;max-height:240px;overflow:auto;background:#0b0f17;border-radius:8px;padding:8px}}
.logline{{white-space:pre-wrap;word-break:break-all}}
.logline.warn{{color:#fbbf24}} .logline.err{{color:#f87171}}
</style></head><body><div class="wrap">
<div class="top"><h1>📊 交易監控 <span class="badge">{html.escape(s["mode"])}</span></h1>
<div class="badge">更新 {s["ts"]}｜每 {REFRESH_SEC}s 自動刷新</div></div>
{halt_banner}
<div class="cards">{card_html}</div>
<section><h2>權益曲線（dashboard 開著時逐分鐘取樣）</h2>{spark}</section>
<section><h2>持倉</h2>{ptable}</section>
<section><h2>真實滑價量測</h2>{slip_html}</section>
<section><h2>今日候選</h2>{cand_html}</section>
<section><h2>近日戰績（每日收盤歸檔）</h2>{hist_html}</section>
<section><h2>日誌尾巴 {html.escape(s["log_file"] or "")}</h2><div class="logwrap">{log_html}</div></section>
<div class="muted">唯讀監控 — 不會下任何單、不改任何狀態。資料來源 data/processed/ 與 logs/。</div>
</div></body></html>"""


# ────────────────────────── HTTP server ──────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 靜音 access log
        pass

    def do_GET(self):
        if self.path.startswith("/favicon"):
            self.send_response(204); self.end_headers(); return
        cfg = load_cfg()
        snap = build_snapshot(cfg)
        if self.path.startswith("/api"):
            body = json.dumps(snap, ensure_ascii=False, default=str).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        else:
            sample_equity(snap)
            body = render(snap).encode("utf-8")
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{'127.0.0.1' if HOST in ('0.0.0.0', '') else HOST}:{PORT}"
    print(f"📊 監控網頁啟動 → {url}")
    if HOST == "0.0.0.0":
        print("   （已綁 0.0.0.0；手機同 Wi-Fi 開 http://<本機區網IP>:{}）".format(PORT))
    print("   唯讀，不影響交易。Ctrl+C 結束。")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止監控網頁。")
        srv.shutdown()


if __name__ == "__main__":
    main()

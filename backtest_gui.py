"""
backtest_gui.py — 回測專用 GUI（中文、唯讀、與交易 dashboard 完全分離）
=====================================================================
純 Python 標準函式庫（http.server），零新依賴。用 capped_sim 引擎（= 忠實重現 live 集中策略）。
啟動時建一次 44 檔訊號快取，之後每次「跑回測」只在選定子集上重算（快）。

可調：資金(滑桿 50k~500k)、最多並倉檔數、年份區間、零股/整股/混合、選股（含「策略推薦38檔」一鍵）。
輸出：年化/Sharpe/最大回撤/PF/勝率/交易數/平均並倉/總報酬 + Gate 判定 + 權益曲線(SVG) + 分年表 + 各檔被選次數。

用法：.\\.venv\\Scripts\\python.exe backtest_gui.py  → 瀏覽器開 http://127.0.0.1:8799
（與交易 dashboard 8787 不同埠，可同時開）
"""
import os
import sys
import html
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from src.backtest.capped_sim import (build_signals, run_capped, DEFAULT_UNIVERSE, FULL_UNIVERSE,
                                     AI_CANDIDATES, LIVE_UNIVERSE)
from src.utils.sectors import get_sector

PORT = int(os.environ.get("BACKTEST_GUI_PORT", "8799"))
HOST = os.environ.get("BACKTEST_GUI_HOST", "127.0.0.1")

NAMES = {
    "2330":"台積電","2454":"聯發科","2303":"聯電","2308":"台達電","2379":"瑞昱","3034":"聯詠",
    "3711":"日月光投控","2337":"旺宏","6415":"矽力-KY","3008":"大立光",
    "2317":"鴻海","2382":"廣達","2357":"華碩","2376":"技嘉","3231":"緯創","4938":"和碩","2356":"英業達","2353":"宏碁",
    "2881":"富邦金","2882":"國泰金","2891":"中信金","2886":"兆豐金","2884":"玉山金","2885":"元大金","2892":"第一金","5880":"合庫金",
    "1301":"台塑","1303":"南亞","1326":"台化","2002":"中鋼","1101":"台泥","2207":"和泰車",
    "2603":"長榮","2609":"陽明","2615":"萬海","2412":"中華電","2912":"統一超","1216":"統一",
    "1513":"中興電","1519":"華城","2618":"長榮航","2049":"上銀","1795":"美時","3045":"台灣大",
    "2449":"京元電","8299":"群聯","2408":"南亞科","6515":"穎崴","5274":"信驊",
    "2383":"台光電","2368":"金像電","3037":"欣興","2313":"華通","4958":"臻鼎-KY",
    "3017":"奇鋐","2345":"智邦","8210":"勤誠","2059":"川湖","6669":"緯穎",
}
SECTOR_NAMES = {"SEMI":"半導體","EMS":"電子代工","COMPONENT":"電子零件","FIN":"金融","PLASTIC":"塑化",
                "CEMENT":"水泥","STEEL":"鋼鐵","AUTO":"汽車","SHIP":"航運","TELECOM":"電信","RETAIL":"通路",
                "FOOD":"食品","POWER":"重電綠能","AIRLINE":"航空","MACHINE":"工具機","BIOTECH":"生技",
                "PCB":"PCB/CCL","THERMAL":"散熱","NETWORK":"網通","CHASSIS":"機殼導軌"}
SECTOR_ORDER = ["SEMI","EMS","PCB","THERMAL","NETWORK","CHASSIS","COMPONENT","FIN","PLASTIC",
                "CEMENT","STEEL","AUTO","SHIP","TELECOM","RETAIL","FOOD","POWER","AIRLINE","MACHINE","BIOTECH"]

_SIG = {}   # 訊號快取（啟動時建一次）


def signals():
    if "d" not in _SIG:
        print(f"⏳ 建立 {len(FULL_UNIVERSE)} 檔回測訊號（首次需抓資料較慢，之後跑回測都很快）…")
        _SIG["d"] = build_signals(FULL_UNIVERSE, "2018-01-01", "2025-12-31")
        print("✅ 訊號就緒")
    return _SIG["d"]


# ───────────────────────── 表單 ─────────────────────────
def checkbox_grid(selected: set) -> str:
    groups = {}
    for s in FULL_UNIVERSE:
        groups.setdefault(get_sector(s), []).append(s)
    out = []
    for sec in SECTOR_ORDER:
        if sec not in groups:
            continue
        ext = ' <span class="extbadge">擴充候選(實測拖累)</span>' if sec in ("POWER","AIRLINE","MACHINE","BIOTECH") else ""
        boxes = "".join(
            f'<label class="chk"><input type="checkbox" name="stk" value="{s}"'
            f'{" checked" if s in selected else ""}> {s} {NAMES.get(s,"")}</label>'
            for s in groups[sec])
        out.append(f'<div class="secgrp"><div class="sechd">{SECTOR_NAMES.get(sec,sec)}{ext}</div>{boxes}</div>')
    return "".join(out)


def form_html(p: dict) -> str:
    cap = int(p.get("capital", 100000))
    mp = int(p.get("maxpos", 5))
    sy, ey = int(p.get("sy", 2018)), int(p.get("ey", 2025))
    mode = p.get("mode", "odd_lot")
    selected = set(p.get("stk", DEFAULT_UNIVERSE))
    yopts = lambda cur: "".join(f'<option value="{y}"{" selected" if y==cur else ""}>{y}</option>' for y in range(2018, 2026))
    mopts = "".join(f'<option value="{v}"{" selected" if v==mode else ""}>{t}</option>'
                    for v, t in [("odd_lot","零股(live實況)"),("round_lot","整股"),("hybrid","混合(高價零股/低價整股)")])
    return f"""
<form method="POST" action="/run">
  <div class="ctlrow">
    <div class="ctl"><label>初始資金 <b id="capv">{cap:,}</b> 元</label>
      <input type="range" name="capital" min="50000" max="500000" step="10000" value="{cap}"
             oninput="document.getElementById('capv').textContent=Number(this.value).toLocaleString()"></div>
    <div class="ctl"><label>最多並倉 <b id="mpv">{mp}</b> 檔</label>
      <input type="range" name="maxpos" min="1" max="10" step="1" value="{mp}"
             oninput="document.getElementById('mpv').textContent=this.value"></div>
  </div>
  <div class="ctlrow">
    <div class="ctl2"><label>起始年</label><select name="sy">{yopts(sy)}</select></div>
    <div class="ctl2"><label>結束年</label><select name="ey">{yopts(ey)}</select></div>
    <div class="ctl2"><label>交易單位</label><select name="mode">{mopts}</select></div>
  </div>
  <div class="selbar">
    <span>選股（{len(selected)} 檔已選）：</span>
    <button type="button" class="mini" onclick="pick('live')">⭐ 現行live選單({len(LIVE_UNIVERSE)}檔)</button>
    <button type="button" class="mini" onclick="pick('rec')">舊基準38檔</button>
    <button type="button" class="mini" onclick="pick('ai')">🤖 38+AI候選15</button>
    <button type="button" class="mini" onclick="pick('all')">全選{len(FULL_UNIVERSE)}</button>
    <button type="button" class="mini" onclick="pick('none')">清除</button>
  </div>
  <div class="grid">{checkbox_grid(selected)}</div>
  <button type="submit" class="run">▶ 跑回測</button>
</form>
<script>
const REC={list(DEFAULT_UNIVERSE)};
const AI={list(AI_CANDIDATES)};
const LIVE={list(LIVE_UNIVERSE)};
function pick(m){{
  document.querySelectorAll('input[name=stk]').forEach(c=>{{
    c.checked = m==='all' ? true : m==='none' ? false :
                m==='ai' ? (REC.includes(c.value)||AI.includes(c.value)) :
                m==='live' ? LIVE.includes(c.value) : REC.includes(c.value);
  }});
}}
</script>"""


# ───────────────────────── 結果 ─────────────────────────
def svg_equity(pts, dates, w=760, h=240):
    if not pts or len(pts) < 2:
        return '<div class="muted">無資料</div>'
    lo, hi = min(pts), max(pts)
    rng = (hi - lo) or 1
    init = pts[0]
    step = w / (len(pts) - 1)
    coords = " ".join(f"{i*step:.1f},{h-(p-lo)/rng*(h-24)-12:.1f}" for i, p in enumerate(pts))
    yinit = h - (init - lo) / rng * (h - 24) - 12
    up = pts[-1] >= init
    col = "#34d399" if up else "#f87171"
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;height:{h}px">'
            f'<line x1="0" y1="{yinit:.1f}" x2="{w}" y2="{yinit:.1f}" stroke="#475569" stroke-dasharray="4 4"/>'
            f'<polyline fill="none" stroke="{col}" stroke-width="2" points="{coords}"/>'
            f'<text x="2" y="14" fill="#94a3b8" font-size="11">高 {hi:,.0f}</text>'
            f'<text x="2" y="{h-4}" fill="#94a3b8" font-size="11">低 {lo:,.0f}（虛線=初始 {init:,.0f}）</text>'
            f'<text x="{w-90}" y="14" fill="#94a3b8" font-size="11">{dates[0]}→{dates[-1]}</text></svg>')


def results_html(st, p) -> str:
    if st is None:
        return '<div class="muted">所選範圍無交易（檢查選股/年份/regime 是否擋下）</div>'
    g = st["gate"]
    badge = lambda ok: f'<span class="gb {"gp" if ok else "gf"}">{"通過" if ok else "未達"}</span>'
    cards = [
        ("年化報酬", f'{st["annual"]*100:+.1f}%', "pos" if st["annual"] >= 0 else "neg"),
        ("Sharpe", f'{st["sharpe"]:.2f}', "pos" if st["sharpe"] >= 1 else ""),
        ("最大回撤", f'{st["dd"]*100:.1f}%', "neg"),
        ("獲利因子 PF", f'{st["pf"]:.2f}', "pos" if st["pf"] >= 1 else "neg"),
        ("勝率", f'{st["win_rate"]*100:.0f}%', ""),
        ("總報酬", f'{st["total_return"]*100:+.1f}%', "pos" if st["total_return"] >= 0 else "neg"),
        ("交易數", f'{st["n_trades"]}', ""),
        ("平均並倉", f'{st["avg_concurrent"]:.1f} 檔', ""),
        ("期末權益", f'{st["final_equity"]:,.0f}', ""),
    ]
    cardhtml = "".join(f'<div class="rcard"><div class="rk">{k}</div><div class="rv {c}">{v}</div></div>' for k, v, c in cards)
    gates = (f'Gate：Sharpe≥1 {badge(g["sharpe"])}　回撤≤-15% {badge(g["dd"])}　'
             f'年化≥10% {badge(g["annual"])}　交易≥50 {badge(g["trades"])}　'
             f'<b>{"✅ 全過" if st["gate_pass"] else "部分未達"}</b>')
    yrows = "".join(
        f'<tr><td>{y}</td><td class="r {"pos" if d["ret"]>=0 else "neg"}">{d["ret"]*100:+.1f}%</td>'
        f'<td class="r">{d["sharpe"]:.2f}</td><td class="r neg">{d["dd"]*100:.1f}%</td></tr>'
        for y, d in sorted(st["per_year"].items()))
    ec = sorted(st["entry_counts"].items(), key=lambda x: -x[1])
    picks = "｜".join(f'{s} {NAMES.get(s,"")}×{c}' for s, c in ec[:12]) or "（無）"
    return f"""
<div class="rcards">{cardhtml}</div>
<div class="gatebar">{gates}</div>
<section><h3>權益曲線（資金 {int(p["capital"]):,}｜並倉≤{p["maxpos"]}｜{p["sy"]}-{p["ey"]}｜{p["mode"]}）</h3>
  {svg_equity(st["equity_pts"], st["equity_dates"])}</section>
<div class="twocol">
  <section><h3>分年</h3><table><thead><tr><th>年</th><th class="r">報酬</th><th class="r">Sharpe</th><th class="r">回撤</th></tr></thead>
    <tbody>{yrows}</tbody></table></section>
  <section><h3>被選最多的標的</h3><div class="muted2">{picks}</div></section>
</div>"""


def page(p, results="") -> str:
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>回測 GUI</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#0b0f17;color:#e5e7eb;font:14px/1.5 -apple-system,"Segoe UI",system-ui,sans-serif}}
.wrap{{max-width:980px;margin:0 auto;padding:16px}}h1{{font-size:19px;margin:0 0 4px}}
.sub{{color:#6b7280;font-size:12px;margin-bottom:14px}}
form{{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:16px;margin-bottom:14px}}
.ctlrow{{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:10px}}
.ctl{{flex:1;min-width:240px}}.ctl2{{min-width:130px}}
label{{font-size:12px;color:#9ca3af;display:block;margin-bottom:3px}}
input[type=range]{{width:100%}}select{{background:#0b0f17;color:#e5e7eb;border:1px solid #374151;border-radius:6px;padding:5px 8px;width:100%}}
.selbar{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:10px 0 6px;font-size:12px;color:#9ca3af}}
.mini{{background:#1f2937;color:#e5e7eb;border:1px solid #374151;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px}}
.mini:hover{{background:#374151}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;max-height:260px;overflow:auto;
  background:#0b0f17;border-radius:8px;padding:10px}}
.secgrp{{border:1px solid #1f2937;border-radius:8px;padding:7px}}
.sechd{{font-size:11px;color:#60a5fa;margin-bottom:4px;font-weight:600}}
.extbadge{{color:#f59e0b;font-weight:400}}
.chk{{display:block;font-size:12px;color:#cbd5e1;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.run{{margin-top:12px;background:#2563eb;color:#fff;border:0;border-radius:8px;padding:10px 22px;font-size:15px;font-weight:600;cursor:pointer}}
.run:hover{{background:#1d4ed8}}
.rcards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:12px 0}}
.rcard{{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:11px}}
.rk{{color:#9ca3af;font-size:12px}}.rv{{font-size:21px;font-weight:700;margin-top:2px}}
.gatebar{{background:#0f172a;border:1px solid #1f2937;border-radius:8px;padding:10px;font-size:13px;margin-bottom:12px}}
.gb{{padding:1px 7px;border-radius:5px;font-size:12px}}.gp{{background:#064e3b;color:#34d399}}.gf{{background:#4c1d24;color:#f87171}}
section{{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:12px;margin:10px 0}}
section>h3{{font-size:13px;color:#9ca3af;margin:0 0 8px}}
.twocol{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}@media(max-width:680px){{.twocol{{grid-template-columns:1fr}}}}
table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:5px 8px;border-bottom:1px solid #1f2937;text-align:left}}
th{{color:#9ca3af}}.r{{text-align:right;font-variant-numeric:tabular-nums}}.pos{{color:#34d399}}.neg{{color:#f87171}}
.muted{{color:#6b7280}}.muted2{{color:#9ca3af;font-size:12px;line-height:1.9}}
</style></head><body><div class="wrap">
<h1>📈 策略回測 GUI</h1>
<div class="sub">忠實重現 live 集中策略（top-N by 籌碼分 + 反波動配重 + ATR 移動停損 + T+1）。唯讀，與交易系統分離。</div>
{form_html(p)}
{results}
</div></body></html>"""


# ───────────────────────── HTTP ─────────────────────────
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body):
        b = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/favicon"):
            self.send_response(204); self.end_headers(); return
        self._send(page({"capital": 100000, "maxpos": 6, "sy": 2018, "ey": 2025, "mode": "odd_lot", "stk": LIVE_UNIVERSE}))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        q = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        p = {"capital": int(q.get("capital", ["100000"])[0]), "maxpos": int(q.get("maxpos", ["6"])[0]),
             "sy": int(q.get("sy", ["2018"])[0]), "ey": int(q.get("ey", ["2025"])[0]),
             "mode": q.get("mode", ["odd_lot"])[0], "stk": q.get("stk", [])}
        if p["ey"] < p["sy"]:
            p["sy"], p["ey"] = p["ey"], p["sy"]
        if not p["stk"]:
            p["stk"] = LIVE_UNIVERSE
        try:
            price_df, sig = signals()
            st = run_capped(price_df, sig, p["stk"], f'{p["sy"]}-01-01', f'{p["ey"]}-12-31',
                            capital=p["capital"], max_pos=p["maxpos"], mode=p["mode"])
            res = results_html(st, p)
        except Exception as e:
            res = f'<div class="muted">回測失敗：{html.escape(str(e))}</div>'
        self._send(page(p, res))


def main():
    signals()   # 啟動時先建快取（避免第一次請求等太久）
    srv = ThreadingHTTPServer((HOST, PORT), H)
    url = f"http://{'127.0.0.1' if HOST in ('0.0.0.0','') else HOST}:{PORT}"
    print(f"📈 回測 GUI 啟動 → {url}（Ctrl+C 結束）")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。"); srv.shutdown()


if __name__ == "__main__":
    main()

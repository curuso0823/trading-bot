"""
notebooks/tomorrow_dryrun.py
盤前 dry-run（唯讀，不寫任何 live 狀態檔）：用與 pre_market 相同的流程
（TA 初篩 → 籌碼評分 → min_score → regime）跑「明天 08:50 會看到的候選清單」，
驗證 35 檔新選單下 AI 股是否實際出現在可下單名單。
今晚法人/融資資料若已發布，明早結果應一致。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.signals.score_engine import ScoreEngine
from src.utils.sectors import get_sector
from src.utils.helpers import load_config

NAMES = {"2330": "台積電", "2454": "聯發科", "2303": "聯電", "2308": "台達電", "3711": "日月光", "2337": "旺宏",
         "2317": "鴻海", "2382": "廣達", "2357": "華碩", "3231": "緯創", "2356": "英業達",
         "2881": "富邦金", "2882": "國泰金", "2891": "中信金", "2886": "兆豐金", "2884": "玉山金",
         "2885": "元大金", "2892": "第一金", "5880": "合庫金",
         "1301": "台塑", "1303": "南亞", "1326": "台化", "2002": "中鋼", "1101": "台泥", "2207": "和泰車",
         "2603": "長榮", "2609": "陽明", "2615": "萬海", "2412": "中華電", "2912": "統一超", "1216": "統一",
         "3017": "奇鋐", "8299": "群聯", "2449": "京元電", "8210": "勤誠"}


def main():
    eng = ScoreEngine()
    risk_on = eng._market_risk_on()
    print(f"regime：{getattr(eng, 'last_regime', '')} → {'可進場' if risk_on else '擋單(不進場)'}")

    ta = eng.run_ta_scan()
    print(f"\nTA 初篩通過 {len(ta)} 檔：" + "、".join(f"{c['stock_id']}{NAMES.get(c['stock_id'], '')}" for c in ta))
    if not ta:
        print("（今日無 TA 通過 → 明天無候選）")
        return

    scored = eng.run_chip_scoring(ta)
    min_score = load_config()["chip_scoring"]["min_score"]
    ok = scored[scored["chip_score"] >= min_score].sort_values("chip_score", ascending=False)
    mp = int(load_config()["entry"]["max_positions"])
    print(f"\n籌碼過門檻(≥{min_score}) {len(ok)} 檔（明早依序填 {mp} 個倉位）：")
    print(f"{'順位':>4} {'代號':>6} {'名稱':<6}{'族群':<10}{'總分':>5}{'外資':>5}{'投信':>5}{'融資':>5}{'配重':>7}")
    for i, (_, r) in enumerate(ok.iterrows(), 1):
        sid = r["stock_id"]
        tag = " ←AI新增" if sid in ("3017", "8299", "2449", "8210") else ""
        sp = float(r["size_pct"]) if "size_pct" in r and r["size_pct"] else 0.0
        print(f"{i:>4} {sid:>6} {NAMES.get(sid, ''):<6}{get_sector(sid):<10}{r['chip_score']:>5.0f}"
              f"{r['foreign_score']:>5.0f}{r['trust_score']:>5.0f}{r['margin_score']:>5.0f}{sp*100:>6.0f}%{tag}")

    # ── 診斷：AI/電子代表股卡在 TA 哪一條 ──
    import pandas as pd
    cfg = load_config()["ta_filter"]
    print(f"\nTA 未過診斷（門檻：收>MA{cfg['ma_period']}↑、量比≥{cfg['volume_ratio_min']}、"
          f"RSI {cfg['rsi_min']}-{cfg['rsi_max']}）：")
    for sid in ["3017", "8299", "2449", "8210", "2330", "2382", "2454", "3711"]:
        df = eng.fetcher.get_daily_price(sid, (pd.Timestamp.today() - pd.Timedelta(days=120)).strftime("%Y-%m-%d"),
                                         adjust=False)
        if df.empty or len(df) < 30:
            print(f"  {sid} 資料不足")
            continue
        c, v = df["close"].astype(float), df["volume"].astype(float)
        ma = c.rolling(cfg["ma_period"]).mean()
        above = c.iloc[-1] > ma.iloc[-1]
        slope = ma.iloc[-1] > ma.iloc[-1 - cfg["ma_slope_days"]]
        vr = v.iloc[-1] / v.rolling(20).mean().iloc[-1]
        delta = c.diff()
        up = delta.clip(lower=0).rolling(cfg["rsi_period"]).mean()
        dn = (-delta.clip(upper=0)).rolling(cfg["rsi_period"]).mean()
        rsi = float((100 - 100 / (1 + up / dn)).iloc[-1])
        fails = []
        if not above:
            fails.append("收<MA20")
        if not slope:
            fails.append("MA20下彎")
        if vr < cfg["volume_ratio_min"]:
            fails.append(f"量比{vr:.2f}<{cfg['volume_ratio_min']}")
        if not (cfg["rsi_min"] <= rsi <= cfg["rsi_max"]):
            fails.append(f"RSI{rsi:.0f}超出{cfg['rsi_min']}-{cfg['rsi_max']}")
        print(f"  {sid} {NAMES.get(sid, ''):<6}{'通過' if not fails else '✗ ' + '、'.join(fails)}")


if __name__ == "__main__":
    main()

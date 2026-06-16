"""
notebooks/diag_filters.py
濾網敏感度（純快取）：固定 35 檔現行 universe，逐一鬆綁各閘門，看「交易頻率 vs 風險報酬」取捨。
  A 量比門檻 volume_ratio_min ∈ {1.0,1.2,1.5現行,2.0}
  B 籌碼門檻 chip min_score ∈ {0,1,2現行}
  C regime ∈ {block_only現行, 關閉}
答：頻率瓶頸是哪一層？放寬後頻率上升多少、付出多少 Sharpe/DD 代價？
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import importlib
from src.utils import helpers
from src.backtest.capped_sim import run_capped, LIVE_UNIVERSE
import src.backtest.signal_builder as sb

START, END, CAP = "2018-01-01", "2025-12-31", 100_000
N_YEARS = 8


def fresh_cfg():
    """拿到可變的 config dict（load_config lru_cache 同一物件，改完即生效於新建的 builder/TechSignal）。"""
    helpers.load_config.cache_clear()
    return helpers.load_config()


def build_and_run(uni, label):
    """用當前（已被 mutate 的）config 重建訊號→run_capped→回傳 stats + 0檔日比例。"""
    b = sb.HistoricalSignalBuilder()
    b.selection_cfg = {"sector_cap_enabled": False}
    price_df, sig = b.build([str(s) for s in uni], START, END)
    stats = run_capped(price_df, sig, uni, START, END, capital=CAP, max_pos=6, mode="odd_lot")
    # 0 檔日比例
    s35 = sig[sig["stock_id"].isin([str(x) for x in uni])]
    by_day = s35.groupby("date")["entry_signal"].sum()
    stats["_sig_total"] = int(by_day.sum())
    stats["_zero_day_pct"] = float((by_day == 0).mean() * 100) if len(by_day) else 0.0
    stats["_label"] = label
    return stats


def show(rows, title):
    print("\n" + "=" * 92 + f"\n{title}\n" + "=" * 92)
    print(f"{'變體':<22}{'訊號數':>8}{'0檔日%':>8}{'交易數':>8}{'交易/年':>8}"
          f"{'年化%':>8}{'Sharpe':>8}{'回撤%':>8}{'PF':>7}{'勝率%':>7}")
    for r in rows:
        print(f"{r['_label']:<22}{r['_sig_total']:>8}{r['_zero_day_pct']:>7.0f}%{r['n_trades']:>8}"
              f"{r['n_trades']/N_YEARS:>8.1f}{r['annual']*100:>8.1f}{r['sharpe']:>8.2f}"
              f"{r['dd']*100:>8.1f}{r['pf']:>7.2f}{r['win_rate']*100:>7.0f}")


# ───────────── A：量比門檻 ─────────────
rowsA = []
for vt in [1.0, 1.2, 1.5, 2.0]:
    c = fresh_cfg()
    c["ta_filter"]["volume_ratio_min"] = vt
    tag = "現行" if vt == 1.5 else ""
    rowsA.append(build_and_run(LIVE_UNIVERSE, f"量比≥{vt} {tag}"))
fresh_cfg()["ta_filter"]["volume_ratio_min"] = 1.5  # 還原
show(rowsA, "A. 量能門檻 volume_ratio_min（其餘維持現行：chip≥2、regime block_only）")

# ───────────── B：籌碼門檻 ─────────────
rowsB = []
for ms in [0, 1, 2]:
    c = fresh_cfg()
    c["ta_filter"]["volume_ratio_min"] = 1.5
    c["chip_scoring"]["min_score"] = ms
    tag = "現行" if ms == 2 else ""
    rowsB.append(build_and_run(LIVE_UNIVERSE, f"chip≥{ms} {tag}"))
fresh_cfg()["chip_scoring"]["min_score"] = 2  # 還原
show(rowsB, "B. 籌碼門檻 chip min_score（其餘維持現行：量比≥1.5、regime block_only）")

# ───────────── C：regime 開關 ─────────────
rowsC = []
# 現行：block_only
c = fresh_cfg(); c["ta_filter"]["volume_ratio_min"] = 1.5; c["chip_scoring"]["min_score"] = 2
c["capitulation"]["enabled"] = True; c["regime"]["enabled"] = True
rowsC.append(build_and_run(LIVE_UNIVERSE, "regime block_only 現行"))
# 關閉所有 regime
c = fresh_cfg(); c["capitulation"]["enabled"] = False; c["regime"]["enabled"] = False
rowsC.append(build_and_run(LIVE_UNIVERSE, "regime 全關"))
fresh_cfg()["capitulation"]["enabled"] = True  # 還原
show(rowsC, "C. 大盤 regime 濾鏡（其餘維持現行：量比≥1.5、chip≥2）")

print("\n[done]")

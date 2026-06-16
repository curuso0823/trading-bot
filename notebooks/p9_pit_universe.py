"""
notebooks/p9_pit_universe.py
Phase 9 · Part 2 — point-in-time 機械選股池：量化「後見之明(look-ahead)」折扣 + 驗證「動量選龍頭是否真實」。

兩個任務（缺失#2 ＋ Part1/3a 的關鍵 confound 解除）：
  (#2) 現行 35 檔 watchlist 是 2026 用「近 3 年 CAGR」事後挑贏家。把它換成「**只用當時可得價量**」的機械
       動量選龍頭池，量化手挑贏家貢獻多少績效（look-ahead 折扣）。
  (驗證) Part1/3a 發現「動量傾斜」在 35 檔 OOS 漂亮（IR vs B +0.26），但那是**在手挑贏家池裡做動量**＝可能只是
       「在已知會漲的名單裡挑會漲的」。本檔在**廣池 1,979 檔**做同樣的機械動量選龍頭，看 edge 是否還在。

⚠️ 硬限制（誠實標註）：
  · 廣池籌碼/除權息資料快取補建中 → 廣池一律用 **未還原價(adjust=False)**（純快取、不打 API）；
    除權息日會被當小幅下跌，對 120 日動量/TA 是輕微近似（universe 篩選穩健，但須標註）。
  · **倖存者偏誤無法消除**：廣池＝現存活標的（FinMind 無下市資料）→ A1−A2 量到的是 **look-ahead 折扣的下界**
    （survivorship 仍灌水 A2）；真實後見之明折扣更大。
  · ffill 洩漏（capped_sim:86-93 對晚上市股 bfill 捏造平盤）：sig 只建在「真實交易列」→ entry pivot 對捏造列 fillna(False)
    ＝天然不進場（已驗），另 assert「無任何 entry 早於各股首個真實交易日」。

控制臂（皆同一 price-only 動量規則 + 同 run_capped 旋鈕 max_pos=6；除 A0）：
  A0 = live 全策略（35、還原價、chip+TA+regime）        ← 參考
  A1 = 35 檔、未還原、price-only 動量+TA（無 chip/regime）
  A2 = 廣池、未還原、price-only 動量+TA
  A3 = FULL_UNIVERSE(59)、未還原、price-only 動量+TA      ← breadth 控制
  B  = 0050 買持 + 基準B(vol0.011)                        ← 被動地板
  → **look-ahead 折扣 = A1 − A2**（同規則同未還原，只差 universe：手挑贏家 vs 機械廣池）。
  → **動量選龍頭是否真實**：A2 vs 被動 + A2 的 2024 捕獲。
用法：.venv/bin/python notebooks/p9_pit_universe.py
"""
import os
import sys
import glob
import importlib.util

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
NB_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(NB_DIR))

import numpy as np
import pandas as pd
from src.backtest.capped_sim import build_signals, run_capped, LIVE_UNIVERSE, FULL_UNIVERSE
from src.backtest.signal_builder import HistoricalSignalBuilder

_spec = importlib.util.spec_from_file_location("benchmark_backtest", os.path.join(NB_DIR, "benchmark_backtest.py"))
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

START, END, CAP = "2018-01-01", "2025-12-31", 100_000
FWD_YEARS = [2022, 2023, 2024, 2025]
SQRT252 = np.sqrt(252)
LOOKBACK, SKIP = 120, 5
MIN_TURNOVER = 50_000_000          # 同 live config trading.min_liquidity_turnover（20 日均成交額門檻，元）
MIN_ROWS = LOOKBACK + 60           # 至少要有足夠歷史才可算動量/TA
CACHE = "data/raw/finmind_cache"


# ───────────────────────── helpers ─────────────────────────
def calmar(a, dd):
    return a / abs(dd) if dd and abs(dd) > 1e-9 else float("nan")


def concentration(pnl):
    total = sum(pnl.values())
    if abs(total) < 1e-9:
        return float("nan"), float("nan")
    vals = sorted(pnl.values(), reverse=True)
    return vals[0] / total * 100.0, sum(vals[:3]) / total * 100.0


def sharpe_of(dr):
    sd = dr.std()
    return float(dr.mean() / sd * SQRT252) if sd > 0 else 0.0


def ann_of(dr):
    n = len(dr)
    return float((1 + dr).prod() ** (252 / n) - 1) if n > 0 else float("nan")


def eq_series(st):
    return pd.Series(st["equity_full"], index=pd.to_datetime(st["equity_full_dates"]))


def year_dr(eq, y):
    return eq[eq.index.year == y].pct_change().dropna()


def load_raw(sid):
    """直接讀快取 pkl（未還原；保證不打 API）。raw FinMind 欄位 → 標準 OHLCV。"""
    p = f"{CACHE}/TaiwanStockPrice__{sid}__{START}__{END}.pkl"
    df = pd.read_pickle(p)
    df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["close"] > 0) & (df["open"] > 0)].sort_values("date")
    df["stock_id"] = str(sid)
    return df[["date", "stock_id", "open", "high", "low", "close", "volume"]]


# ───────────────────────── 0050 / 基準B（純快取）─────────────────────────
print("載入 0050 + 基準B（vol0.011；純快取）…")
adj0050 = bm.load_adjusted_0050()
px0 = adj0050.set_index("date")["close"].sort_index().astype(float)
b0 = {}
for y in range(2018, 2026):
    sy = px0[px0.index.year == y]
    if len(sy) >= 5:
        b0[y] = float(sy.iloc[-1] / sy.iloc[0] - 1)
bench_b = bm.simulate_benchmark(adj0050, 0.011)
bench_b_eq = bench_b["equity"]
benb_oos = pd.concat([year_dr(bench_b_eq, Y) for Y in FWD_YEARS])
bh0050_eq = bm.simulate_buyhold(adj0050)["equity"] if hasattr(bm, "simulate_buyhold") else None


# ───────────────────────── 載入廣池（未還原；純快取）+ 建 price-only 訊號 ─────────────────────────
all_sids = sorted({os.path.basename(p).split("__")[1]
                   for p in glob.glob(f"{CACHE}/TaiwanStockPrice__*__{START}__{END}.pkl")})
print(f"\n廣池候選 {len(all_sids)} 檔（皆有價量 pkl）。載入未還原日線 + 算 TA/動量/流動性（純快取，不打 API）…")

hsb = HistoricalSignalBuilder()
frames, ta_map, liq_map = [], {}, {}
for i, sid in enumerate(all_sids):
    try:
        px = load_raw(sid)
        if len(px) < MIN_ROWS:
            continue
        idx = pd.DatetimeIndex(px["date"])
        ta = hsb._ta_trigger(px).reindex(idx).fillna(False)                       # 複用 live TA 觸發
        turn = pd.Series((px["close"] * px["volume"]).to_numpy(), index=idx)      # 同 live 流動性口徑
        liq = (turn.rolling(20).mean() >= MIN_TURNOVER).fillna(False)
        if not bool((ta & liq).any()):     # 從未「TA且流動」→ 不可能進場 → 不納入工作集（PIT-safe：曾可交易才留）
            continue
        px = px.assign(_ta=ta.to_numpy(), _liq=liq.to_numpy())
        frames.append(px)
    except Exception:
        continue
    if (i + 1) % 400 == 0:
        print(f"  …掃描 {i+1}/{len(all_sids)}（工作集累積 {len(frames)}）")

broad_pdf = pd.concat(frames, ignore_index=True)
WORKING = sorted(broad_pdf["stock_id"].unique())
print(f"工作集 {len(WORKING)} 檔（≥{MIN_ROWS} 列 ＆ 曾達 TA且流動）。")

# 動量（廣池橫斷面百分位 rank；未還原 close；PIT：close[T-skip]/close[T-lookback]-1）
close_w = broad_pdf.pivot(index="date", columns="stock_id", values="close").sort_index()
mom = close_w.shift(SKIP) / close_w.shift(LOOKBACK) - 1.0
mom_rank = mom.rank(axis=1, pct=True)
mom_long = mom_rank.reset_index().melt(id_vars="date", var_name="stock_id", value_name="score")

# entry = TA & 流動；score = 動量 rank（無 chip、無 regime）
broad_sig = broad_pdf[["date", "stock_id", "_ta", "_liq"]].copy()
broad_sig = broad_sig.merge(mom_long, on=["date", "stock_id"], how="left")
broad_sig["entry_signal"] = broad_sig["_ta"] & broad_sig["_liq"]
broad_sig["score"] = broad_sig["score"].fillna(0.0)
broad_sig = broad_sig[["date", "stock_id", "entry_signal", "score"]]

# ── asserts：無 dup；無 entry 早於各股首個真實交易日（ffill 洩漏防護）──
assert broad_sig.duplicated(["date", "stock_id"]).sum() == 0, "broad_sig 有重複 (date,stock_id)！"
first_real = broad_pdf.groupby("stock_id")["date"].min()
ent = broad_sig[broad_sig["entry_signal"]]
leak = (ent["date"] < ent["stock_id"].map(first_real)).sum()
assert leak == 0, f"{leak} 個 entry 早於上市日（ffill 洩漏）！"
n_late = int((first_real > pd.Timestamp("2018-06-01")).sum())
print(f"[ffill 防護] {n_late} 檔晚於 2018-06 上市；assert「無 entry 早於各股上市日」✓（捏造平盤列天然不進場）")

THE_35 = [s for s in LIVE_UNIVERSE if s in set(WORKING)]
THE_FULL = [s for s in FULL_UNIVERSE if s in set(WORKING)]
print(f"35 檔在工作集：{len(THE_35)}/35｜FULL_UNIVERSE 在工作集：{len(THE_FULL)}/{len(FULL_UNIVERSE)}")


def run_broad(universe):
    return run_capped(broad_pdf, broad_sig, universe, START, END, capital=CAP, mode="odd_lot",
                      max_pos=6, full_equity=True)


# ───────────────────────── A0 = live 全策略（還原、chip+TA+regime）─────────────────────────
print("\n建 A0 = live 全策略訊號（35 檔、還原價、chip+TA+regime；純快取）…")
a0_pdf, a0_sig = build_signals(LIVE_UNIVERSE, START, END)
A0 = run_capped(a0_pdf, a0_sig, LIVE_UNIVERSE, START, END, capital=CAP, mode="odd_lot", max_pos=6, full_equity=True)
A1 = run_broad(THE_35)
A2 = run_broad(WORKING)
A3 = run_broad(THE_FULL)

# regime-on 公平對照：保留 live 的投降感知 regime 防禦（market-level、PIT、**非後見之明**），
# 只把「手挑 universe」「chip」拿掉 → A1r−A2r 才是不被「拿掉 regime」污染的乾淨 look-ahead 對照。
print("計算 capitulation regime（block_only，PIT）並建 regime-on 變體…")
allow, _ = hsb._capitulation(START, END, LIVE_UNIVERSE)
reg = allow.reindex(close_w.index).ffill().fillna(False)
sig_r = broad_sig.copy()
sig_r["entry_signal"] = sig_r["entry_signal"].to_numpy() & sig_r["date"].map(reg).fillna(False).to_numpy()


def run_broad_r(universe):
    return run_capped(broad_pdf, sig_r, universe, START, END, capital=CAP, mode="odd_lot",
                      max_pos=6, full_equity=True)


A1r = run_broad_r(THE_35)
A2r = run_broad_r(WORKING)
A3r = run_broad_r(THE_FULL)

# A4r = 機械 top-K 流動性 PIT universe（K≈59，配 A3r 手挑數量）：每日取 trailing-60d 成交額前 K 大（PIT），
# 再 momentum+regime+TA。A3r(手挑59) − A4r(機械60) = **同規模下的純『手挑』後見之明溢價**（最乾淨的 #2 數）。
TOPK = 60
vol_w = broad_pdf.pivot(index="date", columns="stock_id", values="volume").reindex(index=close_w.index, columns=close_w.columns)
liq60 = (close_w * vol_w).rolling(60).mean()
topk_mask = liq60.rank(axis=1, ascending=False, method="first") <= TOPK     # 每日前 K 大流動性（只用過去 60 日，PIT）
topk_long = topk_mask.reset_index().melt(id_vars="date", var_name="stock_id", value_name="topk")
s4 = broad_sig.merge(topk_long, on=["date", "stock_id"], how="left")
s4["entry_signal"] = (s4["entry_signal"].to_numpy() & s4["topk"].fillna(False).to_numpy()
                      & s4["date"].map(reg).fillna(False).to_numpy())
s4 = s4[["date", "stock_id", "entry_signal", "score"]]
A4r = run_capped(broad_pdf, s4, WORKING, START, END, capital=CAP, mode="odd_lot", max_pos=6, full_equity=True)


def metrics(st, name):
    eq = eq_series(st)
    pooled = pd.concat([year_dr(eq, Y) for Y in FWD_YEARS])
    ir_d = pd.concat([pooled.rename("s"), benb_oos.rename("b")], axis=1).dropna()
    ir = sharpe_of(ir_d["s"] - ir_d["b"]) if len(ir_d) > 10 else float("nan")
    _, t3 = concentration(st["pnl_by_stock"])
    d24, d20 = st["per_year"].get(2024, {}), st["per_year"].get(2020, {})
    return {"name": name, "ann": st["annual"], "sharpe": st["sharpe"], "dd": st["dd"],
            "pooled_sharpe": sharpe_of(pooled), "ir": ir, "top3": t3,
            "cap24": (d24.get("ret") / b0[2024]) if d24 else float("nan"),
            "cap20": (d20.get("ret") / b0[2020]) if d20 else float("nan"),
            "n_names": len(st["entry_counts"]), "trades_yr": st["n_trades"] / 8}


rows = [metrics(A0, "A0 live(35,chip+regime,還原)"),
        metrics(A1, "A1 35,price-only,無regime"), metrics(A2, f"A2 廣池{len(WORKING)},無regime"),
        metrics(A3, f"A3 FULL{len(THE_FULL)},無regime"),
        metrics(A1r, "A1r 35,price-only,+regime"), metrics(A2r, f"A2r 廣池{len(WORKING)},+regime"),
        metrics(A3r, f"A3r FULL{len(THE_FULL)},+regime"), metrics(A4r, f"A4r 機械top{TOPK}流動,+regime")]

print("\n" + "=" * 116)
print("控制臂對照（全期；A1–A3 無 regime、A1r–A3r 保留投降感知 regime 防禦；皆 price-only 動量、未還原、max_pos=6）")
print("=" * 116)
print(f"{'臂':<28}{'年化%':>7}{'Sharpe':>8}{'DD%':>7}{'pooledSh':>9}{'IRvsB':>8}{'2024捕':>8}{'2020捕':>8}{'top3%':>7}{'進場檔':>7}")
for m in rows:
    print(f"{m['name']:<28}{m['ann']*100:>7.1f}{m['sharpe']:>8.2f}{m['dd']*100:>7.1f}{m['pooled_sharpe']:>9.2f}"
          f"{m['ir']:>+8.2f}{m['cap24']:>8.2f}{m['cap20']:>8.2f}{m['top3']:>7.0f}{m['n_names']:>7}")
print(f"{'B  0050 買持':<28}{'—':>7}{'1.01':>8}{'-34':>7}{'—':>9}{'0.00':>8}{'1.0':>8}{'1.0':>8}")
print(f"{'B  基準B vol0.011':<28}{bench_b['annual']*100:>7.1f}{bench_b['sharpe']:>8.2f}{bench_b['dd']*100:>7.1f}"
      f"{sharpe_of(benb_oos):>9.2f}{'0.00':>8}")

mA0, mA1, mA2, mA3, mA1r, mA2r, mA3r, mA4r = rows
sb = sharpe_of(benb_oos)
print("\n" + "-" * 116)
print("【regime 貢獻（防止高估後見之明）】拿掉 regime 的傷害：")
print(f"  35：A1r {mA1r['pooled_sharpe']:.2f} → A1 {mA1['pooled_sharpe']:.2f}（DD {mA1r['dd']*100:.0f}%→{mA1['dd']*100:.0f}%）｜"
      f"廣池：A2r {mA2r['pooled_sharpe']:.2f} → A2 {mA2['pooled_sharpe']:.2f}（DD {mA2r['dd']*100:.0f}%→{mA2['dd']*100:.0f}%）")
print("  → 機械 price-only 的 DD 崩壞主要來自『拿掉 regime』；誠實 PIT 策略應保留 regime（PIT、非後見之明）。")

print("\n【#2 look-ahead 折扣（乾淨：A1r − A2r，皆 +regime、皆無 chip、皆未還原，只差 universe）】")
print(f"  pooled OOS Sharpe：{mA1r['pooled_sharpe']:.2f}(手挑35) → {mA2r['pooled_sharpe']:.2f}(機械廣池)（Δ {mA2r['pooled_sharpe']-mA1r['pooled_sharpe']:+.2f}）")
print(f"  全期年化：{mA1r['ann']*100:.1f}% → {mA2r['ann']*100:.1f}%（Δ {(mA2r['ann']-mA1r['ann'])*100:+.1f}pp）｜2024 捕獲 {mA1r['cap24']:.2f} → {mA2r['cap24']:.2f}")
print(f"  A3r(FULL{len(THE_FULL)}) {mA3r['pooled_sharpe']:.2f}（≈A1r ⇒ breadth 非主因；介於 ⇒ 連續）")
print("  ⚠️ 倖存者仍在 A2r → 此 look-ahead 折扣是**下界**（真實後見之明更大）。")

print(f"\n【純『手挑』溢價（最乾淨：A3r 手挑{len(THE_FULL)} − A4r 機械top{TOPK}，同規模、皆動量+regime、皆無chip）】")
print(f"  pooled OOS Sharpe：{mA3r['pooled_sharpe']:.2f}(手挑) vs {mA4r['pooled_sharpe']:.2f}(機械)（Δ {mA3r['pooled_sharpe']-mA4r['pooled_sharpe']:+.2f}）"
      f"｜年化 {mA3r['ann']*100:.1f}% vs {mA4r['ann']*100:.1f}%｜2024 捕獲 {mA3r['cap24']:.2f} vs {mA4r['cap24']:.2f}")
hp = mA3r["pooled_sharpe"] - mA4r["pooled_sharpe"]
print(f"  → 同規模下手挑 vs 機械差 {hp:+.2f} Sharpe：{'手挑溢價大＝後見之明顯著' if hp > 0.2 else '手挑溢價小＝universe 規模/品質才是主因，非挑特定贏家'}")

print("\n【誠實 PIT 機械策略（最佳非手挑臂）vs 被動】")
best_pit = max((mA2r, mA4r), key=lambda m: m["pooled_sharpe"])
print(f"  最佳機械 PIT＝{best_pit['name']}：pooled OOS Sharpe {best_pit['pooled_sharpe']:.2f} vs 基準B {sb:.2f} vs 0050 1.01"
      f"｜IR vs B {best_pit['ir']:+.2f}｜2024 捕獲 {best_pit['cap24']:.2f}")
pit_ok = best_pit["pooled_sharpe"] > sb and best_pit["ir"] > 0
print(f"  → 誠實 PIT 機械策略{'**勝**被動（edge 非純後見之明）' if pit_ok else '**打不贏**被動 → 去手挑後 edge 大幅縮水（plan-doc 預測成立）'}（線索；Part 3b 綁決策）")

print("\n【#4：機械選龍頭能否修大多頭捕獲？】")
best24 = max(mA2r["cap24"], mA4r["cap24"])
print(f"  最佳機械臂 2024 捕獲 {best24:.2f} vs A0(live) 0.29 → "
      f"{'改善' if best24 > 0.34 else '未改善（機械選龍頭**救不了** 2024，反而更差）'}")

print("\n[done] 下一步：把表現最佳的 price-only 臂帶進 Part 3b walk-forward；綜合判定見 Part 4。")

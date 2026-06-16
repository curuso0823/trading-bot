"""
backtest/capped_sim.py
忠實重現 LIVE「集中策略」的回測引擎：每日依 chip_score 由高到低填補空位（top-N 並倉上限）、
vol-sizing 對剩餘現金收 size_pct、ATR per-position 移動停損、max_hold 交易日、T+1 同日不可賣、
訊號T→開盤T+1執行（含滑價+費稅）。block_only regime 已內含於 signal_builder(cap_cfg)。

設計給「回測 GUI」與 notebooks 共用：
  build_signals(universe, start, end) -> (price_df, sig)   # 慢，吃 FinMind，GUI 啟動時建一次快取
  run_capped(price_df, sig, universe, start, end, ...) -> stats dict   # 快，純計算，每次請求重跑
"""
import numpy as np
import pandas as pd
from src.backtest.signal_builder import HistoricalSignalBuilder
from src.utils.helpers import load_config
from src.utils.sectors import get_sector

# 已驗證的 38 檔 + 6 檔擴充候選
DEFAULT_UNIVERSE = ["2330","2454","2303","2308","2379","3034","3711","2337","6415","3008",
                    "2317","2382","2357","2376","3231","4938","2356","2353",
                    "2881","2882","2891","2886","2884","2885","2892","5880",
                    "1301","1303","1326","2002","1101","2207",
                    "2603","2609","2615","2412","2912","1216"]
EXT_CANDIDATES = ["1513","1519","2618","2049","1795","3045"]
# AI 供應鏈強勢候選（2026-06 sector_scan：近3年 CAGR 全數 ≥ 0050 的 52%；任務2+4）
AI_CANDIDATES = ["2449","8299","2408","6515","5274",            # 半導體：京元電/群聯/南亞科/穎崴/信驊
                 "2383","2368","3037","2313","4958",            # PCB/CCL：台光電/金像電/欣興/華通/臻鼎
                 "3017","2345","8210","2059","6669"]            # 散熱奇鋐/網通智邦/機殼勤誠/導軌川湖/ODM緯穎
# 2026-06 分窗驗證採用的 4 檔（universe_ai_window.py）：AI窗23-25 22.5%/Sharpe1.63/DD-12.8% 全Gate PASS、
# 近兩年24-25 三變體最佳；+8/+15 皆破 DD Gate 否決。全期18-25 偏弱係 2018-22（AI 股未起飛）排擠，非前瞻性缺陷。
AI_ADOPTED = ["3017","8299","2449","8210"]                      # 奇鋐/群聯/京元電/勤誠
# 2026-06-10 前瞻性除名（user 決策：選單供未來交易用，AI 時代結構已異於 19-21，不以全期利潤最大化為準）
# ——近3年 CAGR 全數大幅落後 0050(52%)：
REMOVED_LAGGARDS = ["3008","2379","6415","3034",                # 大立光28%/瑞昱24%/矽力13%/聯詠9%(近1年負)
                    "2353","4938","2376"]                       # 宏碁7%/和碩13%/技嘉16%
LIVE_UNIVERSE = [s for s in DEFAULT_UNIVERSE if s not in REMOVED_LAGGARDS] + AI_ADOPTED  # = config watchlist（35 檔）
FULL_UNIVERSE = DEFAULT_UNIVERSE + EXT_CANDIDATES + AI_CANDIDATES


def build_signals(universe, start="2018-01-01", end="2025-12-31"):
    """跑 HistoricalSignalBuilder（block_only regime + TA + 籌碼）→ (price_df, signal_df)。慢（吃 FinMind）。"""
    b = HistoricalSignalBuilder()
    b.selection_cfg = {"sector_cap_enabled": False}
    b.cap_cfg = {**load_config().get("capitulation", {})}
    return b.build([str(s) for s in universe], start, end)


def _lot_slip(close, capital, mode, cfg):
    """每檔 lot 單位與滑價：odd_lot(零股) / round_lot(整股) / hybrid(1張買得起→整股否則零股)。"""
    tr = cfg.get("trading", {})
    odd_s, rnd_s = float(tr.get("odd_lot_slippage", 0.0015)), float(tr.get("round_lot_slippage", 0.001))
    pos_pct = float(cfg.get("entry", {}).get("position_size_pct", 0.30))
    lot, slip = {}, {}
    for s in close.columns:
        if mode == "round_lot":
            lot[s], slip[s] = 1000, rnd_s
        elif mode == "hybrid":
            afford = float(close[s].median()) * 1000 <= capital * pos_pct
            lot[s], slip[s] = (1000, rnd_s) if afford else (1, odd_s)
        else:
            lot[s], slip[s] = 1, odd_s
    return lot, slip


def run_capped(price_df, sig, universe, start, end, capital=100_000, max_pos=6, mode="odd_lot",
               slip_scale=1.0, size_min=None, size_max=None, sector_max=None,
               tighten_mask=None, deep_bear_max=None,
               atr_mult=None, atr_lo=None, atr_hi=None, max_hold=None, target_vol=None):
    """在 (universe, 日期區間) 子集上跑集中策略模擬，回傳完整統計 dict（含分年、權益曲線點）。
    slip_scale：滑價壓力倍數（風險情境分析用，如急跌日零股簿薄 ×2/×3）。
    size_min/size_max：覆寫配重上下限（預設讀 0.10/0.30，與 live sizing 一致）。
    sector_max：同類股同時持倉上限，如 {"FIN": 2}（None=不限，行為與舊版完全一致）。
    tighten_mask/deep_bear_max（#3）：per-date 布林 Series + 收緊後停損帶上限。tighten 日把「既有部位」
        移動停損帶上限收到 deep_bear_max（攻急殺）。兩者皆 None=不啟用，行為與舊版逐字相同。
    atr_mult/atr_lo/atr_hi/max_hold/target_vol：覆寫 ATR 停損帶(4.5/0.08/0.09)、最長持有(60日)、
        波動目標(0.02)。皆 None=逐字同舊版（Phase 6 出場/配重實驗用）。"""
    cfg = load_config()
    uni = set(str(s) for s in universe)
    s0, e0 = pd.Timestamp(start), pd.Timestamp(end)
    pdf = price_df[(price_df["stock_id"].isin(uni)) & (price_df["date"] >= s0) & (price_df["date"] <= e0)]
    sg = sig[(sig["stock_id"].isin(uni)) & (sig["date"] >= s0) & (sig["date"] <= e0)]
    if pdf.empty or sg.empty:
        return None
    close = pdf.pivot(index="date", columns="stock_id", values="close").sort_index().ffill().bfill()
    op = pdf.pivot(index="date", columns="stock_id", values="open").reindex_like(close).ffill().bfill()
    hi = pdf.pivot(index="date", columns="stock_id", values="high").reindex_like(close).ffill().bfill()
    lo = pdf.pivot(index="date", columns="stock_id", values="low").reindex_like(close).ffill().bfill()
    entry = sg.pivot(index="date", columns="stock_id", values="entry_signal").reindex(
        index=close.index, columns=close.columns).fillna(False)
    score = sg.pivot(index="date", columns="stock_id", values="score").reindex(
        index=close.index, columns=close.columns).fillna(0.0)

    smin = 0.10 if size_min is None else float(size_min)
    smax = 0.30 if size_max is None else float(size_max)
    amult = 4.5 if atr_mult is None else float(atr_mult)
    alo = 0.08 if atr_lo is None else float(atr_lo)
    ahi = 0.09 if atr_hi is None else float(atr_hi)
    mhold = 60 if max_hold is None else int(max_hold)
    tvol = 0.02 if target_vol is None else float(target_vol)
    vol20 = close.pct_change().rolling(20).std()
    size_pct = (smax * tvol / vol20).clip(smin, smax)
    pc = close.shift(1)
    trng = np.maximum.reduce([(hi - lo).values, (hi - pc).abs().values, (lo - pc).abs().values])
    atr_pct = pd.DataFrame(trng, index=close.index, columns=close.columns).rolling(14).mean() / close
    trail = (amult * atr_pct).clip(alo, ahi)
    # #3 深度熊市/急殺：tighten 日把既有部位停損帶上限收到 deep_bear_max（None=不啟用，逐字同舊版）
    tg = (tighten_mask.reindex(close.index).fillna(False).to_numpy()
          if tighten_mask is not None else None)

    stocks = list(close.columns)
    sec_a = [get_sector(s) for s in stocks]
    lotm, slipm = _lot_slip(close, capital, mode, cfg)
    lot_a = np.array([lotm[s] for s in stocks], float)
    slip_a = np.array([slipm[s] for s in stocks], float) * float(slip_scale)
    C, O, E, SC, SZ, TR = close.values, op.values, entry.values, score.values, size_pct.values, trail.values
    n, m = C.shape
    cc = cfg["cost"]

    def bf(amt, lot):
        return max(round(amt * cc["buy_fee_rate"]), cc.get("min_fee_odd", 1) if lot == 1 else cc["min_fee"])

    def sc(amt, lot):
        return (max(round(amt * cc["sell_fee_rate"]), cc.get("min_fee_odd", 1) if lot == 1 else cc["min_fee"])
                + round(amt * cc["sell_tax_rate"]))

    cash, held, eq, trades, entry_cnt = float(capital), {}, np.empty(n), [], {}
    pnl_by_stock = {}
    conc = np.zeros(n)
    for i in range(n):
        eq[i] = cash + sum(h["qty"] * C[i, c] * lot_a[c] for c, h in held.items())
        conc[i] = len(held)
        if i + 1 >= n:
            continue
        ni = i + 1
        for c, h in held.items():
            if C[i, c] > h["peak"]:
                h["peak"] = C[i, c]
        tighten_today = bool(tg[i]) if tg is not None else False
        exiting = []
        for c, h in held.items():
            if (i - h["entry_i"]) < 1:
                continue
            et = min(h["trail"], deep_bear_max) if (tighten_today and deep_bear_max is not None) else h["trail"]
            if C[i, c] <= h["peak"] * (1 - et) or (i - h["entry_i"]) >= mhold:
                exiting.append(c)
        for c in exiting:
            h = held.pop(c)
            L = lot_a[c]
            amt = O[ni, c] * (1 - slip_a[c]) * h["qty"] * L
            proceeds = amt - sc(amt, L)
            cash += proceeds
            pnl = proceeds - h["basis"]
            trades.append(pnl)
            pnl_by_stock[stocks[c]] = pnl_by_stock.get(stocks[c], 0.0) + pnl
        free = max_pos - len(held)
        if free > 0:
            cands = sorted([(c, SC[i, c]) for c in range(m) if E[i, c] and c not in held], key=lambda x: -x[1])
            if sector_max is None:
                cands = cands[:free]            # 無上限：與舊版行為逐字相同
            else:                               # 同類股上限：跳過已滿類股、不浪費名額
                sec_cnt = {}
                for c2 in held:
                    sec_cnt[sec_a[c2]] = sec_cnt.get(sec_a[c2], 0) + 1
                picked = []
                for c, scv in cands:
                    if len(picked) >= free:
                        break
                    cap_n = sector_max.get(sec_a[c])
                    if cap_n is not None and sec_cnt.get(sec_a[c], 0) >= cap_n:
                        continue
                    picked.append((c, scv))
                    sec_cnt[sec_a[c]] = sec_cnt.get(sec_a[c], 0) + 1
                cands = picked
            for c, _ in cands:
                L = lot_a[c]
                sp = SZ[i, c] if np.isfinite(SZ[i, c]) else 0.30
                fill = O[ni, c] * (1 + slip_a[c])
                if not np.isfinite(fill) or fill <= 0:
                    continue
                qty = int((cash * sp) / (fill * L))
                while qty >= 1 and fill * qty * L + bf(fill * qty * L, L) > cash:
                    qty -= 1
                if qty < 1:
                    continue
                amt = fill * qty * L
                basis = amt + bf(amt, L)
                cash -= basis
                held[c] = {"qty": qty, "peak": fill, "entry_i": ni,
                           "trail": TR[i, c] if np.isfinite(TR[i, c]) else 0.09, "basis": basis}
                entry_cnt[stocks[c]] = entry_cnt.get(stocks[c], 0) + 1
    return _stats(pd.Series(eq, index=close.index), trades, conc, entry_cnt, pnl_by_stock, cfg, capital)


def _stats(s, trades, conc, entry_cnt, pnl_by_stock, cfg, capital):
    r = s.pct_change().dropna()
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0
    yrs = len(s) / 252
    cagr = float((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) if s.iloc[0] > 0 and yrs > 0 else 0.0
    dd = float((s / s.cummax() - 1).min())
    wins = [t for t in trades if t > 0]
    loss = [t for t in trades if t <= 0]
    pf = float(sum(wins) / abs(sum(loss))) if loss and sum(loss) != 0 else (999.0 if wins else 0.0)
    g = cfg["performance_gate"]
    gate = {"sharpe": sharpe >= g["min_sharpe"], "dd": dd >= g["max_drawdown"],
            "annual": cagr >= g["min_annual_return"], "trades": len(trades) >= g["min_trades"]}
    per_year = {}
    for yr in sorted(set(s.index.year)):
        sy = s[s.index.year == yr]
        if len(sy) < 5:
            continue
        ry = sy.pct_change().dropna()
        per_year[int(yr)] = {"ret": float(sy.iloc[-1] / sy.iloc[0] - 1),
                             "sharpe": float(ry.mean() / ry.std() * np.sqrt(252)) if ry.std() > 0 else 0.0,
                             "dd": float((sy / sy.cummax() - 1).min())}
    step = max(1, len(s) // 320)
    active = conc[conc > 0]
    return {
        "annual": cagr, "sharpe": sharpe, "dd": dd, "pf": pf,
        "total_return": float(s.iloc[-1] / s.iloc[0] - 1), "n_trades": len(trades),
        "win_rate": float(len(wins) / len(trades)) if trades else 0.0,
        "final_equity": float(s.iloc[-1]), "initial": float(capital),
        "avg_concurrent": float(active.mean()) if len(active) else 0.0,
        "gate": gate, "gate_pass": all(gate.values()),
        "per_year": per_year, "entry_counts": entry_cnt,
        "pnl_by_stock": {k: round(float(v), 1) for k, v in pnl_by_stock.items()},
        "equity_pts": [round(float(v), 1) for v in s.iloc[::step]],
        "equity_dates": [str(d.date()) for d in s.index[::step]],
    }

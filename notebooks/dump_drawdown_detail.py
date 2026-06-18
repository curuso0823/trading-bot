"""
notebooks/dump_drawdown_detail.py
為 2020 / 2022 回撤研究準備『接地數據』（agent 分析用）：
  • dump 三策略每日權益/回撤 + 0050 收盤/MA200/本策略 目標&實際曝險 + 再平衡交易 → CSV。
  • 印出 2020、2022 的年內最大回撤跌段（峰→谷→回復：日期/深度/天數）、MA200 穿越日、本策略實際交易。
純快取、0 API（複用 dca_compare / benchmark_backtest，未動 live）。
用法：.venv/bin/python notebooks/dump_drawdown_detail.py
"""
import os
import sys
import importlib.util

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

NB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(NB_DIR)
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

# 複用 dca_compare（內含 bm=benchmark_backtest + simulate_dca）
_spec = importlib.util.spec_from_file_location("dc", os.path.join(NB_DIR, "dca_compare.py"))
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)
bm = dc.bm

OUT_CSV = "data/processed/drawdown_detail.csv"
YEARS = [2020, 2022]


# ── 本策略 live 口徑明細模擬（記錄每日 實際曝險/持股/現金 + 再平衡交易）──────────────
def sim_strat_detailed(adj):
    """base 100%(target_vol=1.0) + 跌破 MA200 ×0.85，月度/5pp 帶再平衡，T+1 開盤成交。
    回 (dates, eq, held_exp, target_exp, trades)。trades=[(date, side, qty, fill)]。"""
    df = adj[(adj["date"] >= pd.Timestamp(bm.START)) & (adj["date"] <= pd.Timestamp(bm.END))].reset_index(drop=True)
    dates = pd.DatetimeIndex(df["date"])
    close = df["close"].to_numpy(float)
    opn = df["open"].to_numpy(float)
    full_close = adj.set_index("date")["close"].astype(float)
    exp_full = bm.vol_target_exposure(full_close, target_daily_vol=1.0, lookback=bm.LOOKBACK, exposure_cap=1.0,
                                      regime_overlay=True, regime_ma=200, regime_action=0.85)
    target_exp = exp_full.reindex(dates).to_numpy(float)
    month_first = bm.is_month_first_trading_day(dates).to_numpy(bool)

    n = len(df)
    cash, qty, avg_cost = bm.INITIAL, 0, 0.0
    eq = np.empty(n)
    held = np.empty(n)
    trades = []
    for i in range(n):
        eq[i] = cash + qty * close[i] * bm.LOT
        held[i] = (qty * close[i] * bm.LOT) / eq[i] if eq[i] > 0 else 0.0
        if i + 1 >= n:
            continue
        te = target_exp[i]
        if not np.isfinite(te):
            continue
        if not (month_first[i] or abs(held[i] - te) > bm.BAND):
            continue
        fill_buy, fill_sell = opn[i + 1] * (1 + bm.SLIP), opn[i + 1] * (1 - bm.SLIP)
        target_qty = int((eq[i] * te) / (fill_buy * bm.LOT)) if fill_buy > 0 else 0
        delta = target_qty - qty
        if delta > 0:
            buyable = delta
            while buyable >= 1:
                amt = fill_buy * buyable * bm.LOT
                if amt + bm._buyfee(amt) <= cash:
                    break
                buyable -= 1
            if buyable < 1:
                continue
            amt = fill_buy * buyable * bm.LOT
            cash -= amt + bm._buyfee(amt)
            new_qty = qty + buyable
            avg_cost = (avg_cost * qty + (amt + bm._buyfee(amt))) / new_qty
            qty = new_qty
            trades.append((dates[i + 1].date(), "buy", int(buyable), round(fill_buy, 2)))
        elif delta < 0:
            sell_qty = -delta
            amt = fill_sell * sell_qty * bm.LOT
            cash += amt - bm._sellcost(amt)
            qty -= sell_qty
            if qty == 0:
                avg_cost = 0.0
            trades.append((dates[i + 1].date(), "sell", int(sell_qty), round(fill_sell, 2)))
    return dates, pd.Series(eq, index=dates), pd.Series(held, index=dates), pd.Series(target_exp, index=dates), trades


def dd_series(eq):
    return eq / eq.cummax() - 1.0


def worst_episode_in_year(eq, year):
    """年內（cummax 自年初重置）最大回撤跌段：峰→谷→回復。"""
    s = eq[eq.index.year == year]
    if len(s) < 5:
        return None
    dd = s / s.cummax() - 1.0
    trough_date = dd.idxmin()
    pre = s.loc[:trough_date]
    peak_val = float(pre.max())
    peak_date = pre.idxmax()
    trough_val = float(s.loc[trough_date])
    depth = trough_val / peak_val - 1.0 if peak_val > 0 else 0.0
    post = s.loc[trough_date:]
    rec = post[post >= peak_val]
    rec_date = rec.index[0] if len(rec) else None
    return dict(peak_date=peak_date.date(), peak=peak_val, trough_date=trough_date.date(),
                trough=trough_val, depth=depth, drop_days=(trough_date - peak_date).days,
                rec_date=(rec_date.date() if rec_date is not None else None),
                rec_days=((rec_date - trough_date).days if rec_date is not None else None))


def main():
    print("為 2020/2022 回撤研究 dump 接地數據 | 載入快取 0050（0 API）…")
    adj = bm.load_adjusted_0050()

    bh = bm.simulate_buyhold(adj)
    dca = dc.simulate_dca(adj)
    dates, eq_strat, held_strat, texp_strat, trades = sim_strat_detailed(adj)

    eq_bh, eq_dca = bh["equity"], dca["equity"]
    # sanity：明細 eq 應與 simulate_benchmark 一致
    eq_chk = bm.simulate_benchmark(adj, 1.0, overlay=True, regime_ma=200, regime_action=0.85)["equity"]
    diff = float((eq_strat - eq_chk).abs().max())
    print(f"sanity｜本策略明細 eq vs simulate_benchmark 最大差 = {diff:.4f}（應≈0）")

    close_full = adj.set_index("date")["close"].astype(float)
    ma200 = close_full.rolling(200).mean()
    close_w = close_full.reindex(dates)
    ma_w = ma200.reindex(dates)
    below_w = (close_w < ma_w).fillna(False)

    out = pd.DataFrame({
        "date": [d.date() for d in dates],
        "close": close_w.values.round(3),
        "ma200": ma_w.values.round(3),
        "below_ma200": below_w.values.astype(int),
        "target_exp_strat": texp_strat.values.round(4),
        "held_exp_strat": held_strat.values.round(4),
        "eq_bh": eq_bh.values.round(1),
        "dd_bh": dd_series(eq_bh).values.round(4),
        "eq_strat": eq_strat.values.round(1),
        "dd_strat": dd_series(eq_strat).values.round(4),
        "eq_dca": eq_dca.values.round(1),
        "dd_dca": dd_series(eq_dca).values.round(4),
    })
    os.makedirs("data/processed", exist_ok=True)
    out.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"[csv] {OUT_CSV} ← {len(out)} 列，{out['date'].min()} ~ {out['date'].max()}")
    print("     欄位：date, close, ma200, below_ma200, target_exp_strat, held_exp_strat,"
          " eq_bh, dd_bh, eq_strat, dd_strat, eq_dca, dd_dca")
    print("     註：target_exp_strat=訊號(1.0/0.85)；held_exp_strat=實際持倉曝險(受5pp帶/月度/T+1 延後)；dd_*=全期峰值回撤")

    series = {"0050買持": eq_bh, "本策略(出15%)": eq_strat, "定期定額": eq_dca}
    for yr in YEARS:
        print("\n" + "=" * 88)
        print(f"【{yr}】年內最大回撤跌段（峰→谷→回復）")
        print("-" * 88)
        print(f"{'策略':<16}{'峰值日':>12}{'谷底日':>12}{'深度':>9}{'下跌天數':>9}{'回復日':>13}{'回復天數':>9}")
        for name, eq in series.items():
            e = worst_episode_in_year(eq, yr)
            if not e:
                continue
            rec = str(e["rec_date"]) if e["rec_date"] else "年內未回復"
            recd = str(e["rec_days"]) if e["rec_days"] is not None else "—"
            print(f"{name:<16}{str(e['peak_date']):>12}{str(e['trough_date']):>12}"
                  f"{e['depth']*100:>8.1f}%{e['drop_days']:>9}{rec:>13}{recd:>9}")

        # MA200 穿越（本策略訊號轉折）
        by = below_w[below_w.index.year == yr]
        flips = by.ne(by.shift(1))
        flips.iloc[0] = False
        cross = by[flips]
        print(f"\n  MA200 穿越日（本策略訊號轉折；below=收盤<MA200→目標砍至85%）：")
        if len(cross) == 0:
            init = "below(跌破)" if bool(by.iloc[0]) else "above(站上)"
            print(f"    （{yr} 全年無穿越，年初狀態＝{init}）")
        else:
            for d, v in cross.items():
                print(f"    {d.date()}  → {'跌破 MA200（砍至85%訊號）' if v else '站回 MA200（回滿訊號）'}")

        # 本策略 當年實際再平衡交易
        yt = [t for t in trades if t[0].year == yr]
        print(f"\n  本策略 {yr} 實際再平衡交易（{len(yt)} 筆；T+1 開盤成交）：")
        for d, side, q, fill in yt:
            print(f"    {d}  {side:>4}  {q:>5} 股 @ {fill}")

    print("\n[done] 接地數據 dump 完成（純快取、0 API、未動 live）。")


if __name__ == "__main__":
    main()

"""
backtest/pit_universe.py
機械 PIT（point-in-time）選股池 —— **無 look-ahead**，取代手挑 watchlist。

承 docs/PIT_REBUILD_PLAN.md R0a 與 IMPROVEMENT_PLAN_v2.md 附錄 B：手挑 35 檔 LIVE_UNIVERSE
經 Phase 9 證實帶 +0.38 OOS Sharpe 後見之明溢價。本模組以「每個 rebalance 時點 t **只用 t 之前
資料**」的純機械規則動態選股，徹底排除事後挑贏家。

規則（皆 PIT；參數預先指定，非 tuned）：
  · trailing W 日均成交額 (close×volume) → 橫斷面 rank → top-K
  · 上市滿 M 年（first_real_date ≤ t − M 年）。⚠️ 快取左censored 於 2018 → 在快取首 ~grace 天即出現的
    股＝「快取前已上市的老股」（非新 IPO，真實年資 ≥ 資料跨度），豁免年資等待；只有**樣本期內真 IPO**
    （first_real 明顯落在樣本內）才需等滿 M 年。否則所有老股在 2019 前都被誤判「未滿 1 年」→ 2018 整年空池。
  · 價格下限 floor（去雞蛋水餃股）
  · 週期 reselect（季 'Q' / 年 'A'），成員在 reselect 點釘死、區間內不變 → per-date membership（時變）
  · 記錄換手率（universe 穩定性 Gate：不因雜訊每月大換血）

無前視證明（模組內 assert 把關）：
  1) turnover/價格/上市年資 在 t 的判定只引用 ≤ t 資料（rolling 視窗嚴格 ≤ t；rank 在 t 橫斷面）。
  2) 成員只在 rebalance 日改變；每日 d 的成員由「≤ d 的最近 rebalance」決定（往前廣播，不回看未來）。
  3) 禁用任何 t 之後資訊（無 CAGR、無 AI 名單、無未來報酬）。
  ⚠️ 唯一無法以規則消除的前視＝**池本身 survivorship**（FinMind 無下市/歷史成分）→ 結論帶 caveat。

時變 universe 如何餵 run_capped（不改引擎、behavior-neutral）：
  apply_membership(sig, member) 把成員 baked 進 entry_signal（entry &= member），其餘欄位不動，
  直接餵 capped_sim.run_capped（沿用 Phase 9 p9_pit_universe.py:211 把遮罩 baked 進 entry 的手法）。
  成員只 gate「進場」；已持倉者照常由 ATR 移動停損／max_hold 出場（與 live 一致，避免假換手）。

用法（自檢）：.venv/bin/python src/backtest/pit_universe.py
"""
import numpy as np
import pandas as pd

TRADING_DAYS_YEAR = 252


# ───────────────────────── 純函式 ─────────────────────────
def _wide(price_df: pd.DataFrame, field: str) -> pd.DataFrame:
    """long price_df → date×stock 寬表（只含真實交易列；缺日為 NaN，不 ffill/bfill）。"""
    return price_df.pivot(index="date", columns="stock_id", values=field).sort_index()


def compute_turnover(close_w: pd.DataFrame, vol_w: pd.DataFrame, window: int) -> pd.DataFrame:
    """trailing window 日均成交額 (close×volume)。純因果：rolling 只用過去＋當日。
    缺日 NaN 不灌水；min_periods 取半窗 → 有足夠真實交易日才給估計，否則 NaN（→ 不合格）。"""
    turn = close_w * vol_w
    return turn.rolling(window, min_periods=max(20, window // 2)).mean()


def rebalance_dates(index: pd.DatetimeIndex, freq: str) -> pd.DatetimeIndex:
    """每季/每年『第一個交易日』作為 reselect 時點。"""
    idx = pd.DatetimeIndex(index).sort_values()
    code = {"Q": "Q", "quarter": "Q", "A": "Y", "Y": "Y", "year": "Y"}.get(str(freq))
    if code is None:
        raise ValueError(f"rebalance freq 須為 Q/A，收到 {freq!r}")
    period = idx.to_period(code)
    is_first = np.empty(len(idx), dtype=bool)
    is_first[0] = True
    is_first[1:] = period[1:] != period[:-1]
    return idx[is_first]


def build_membership(price_df: pd.DataFrame, *, top_k: int, rebalance: str = "Q",
                     turnover_window: int = 60, min_history_years: float = 1.0,
                     price_floor: float = 10.0, listed_grace_days: int = 120):
    """回傳 (member_w: date×stock bool 時變成員, churn_df, members_by_reb)。全程無前視。
    listed_grace_days：快取首日後 grace 天內即首次交易者＝快取前已上市的老股，豁免 M 年年資等待。"""
    close_w = _wide(price_df, "close")
    vol_w = _wide(price_df, "volume").reindex(index=close_w.index, columns=close_w.columns)
    idx = close_w.index
    stocks = list(close_w.columns)

    turn = compute_turnover(close_w, vol_w, turnover_window)
    first_real = close_w.apply(lambda c: c.first_valid_index())   # 各股首個真實交易日（= 上市年資代理）
    min_hist = pd.Timedelta(days=int(round(min_history_years * 365.25)))
    pre_existing = first_real <= (idx[0] + pd.Timedelta(days=int(listed_grace_days)))  # 快取前老股（左censored）
    rebs = rebalance_dates(idx, rebalance)

    members_by_reb, churn, prev = {}, [], set()
    for t in rebs:
        row_turn = turn.loc[t]
        row_close = close_w.loc[t]
        # 老股豁免年資等待；真 IPO 須 first_real ≤ t − M 年（NaT → False，未上市）
        age_ok = pre_existing.values | ((t - first_real) >= min_hist).values
        price_ok = row_close >= price_floor                        # NaN → False
        turn_ok = row_turn.notna() & (row_turn > 0)
        eligible = age_ok & price_ok.fillna(False).values & turn_ok.values
        # ⚠️ 必須先 dropna：pandas 2.1 的 Series([全NaN]).nlargest(k) 會誤回前 k 個 label（非空），
        #    冷啟期（無合格者）會憑空選股 → 用 dropna() 只留真正合格的候選再排序。
        cand = row_turn.where(pd.Series(eligible, index=stocks)).dropna()
        sel = set(cand.nlargest(top_k).index) if (top_k > 0 and len(cand)) else set()
        members_by_reb[t] = sel
        added, removed = len(sel - prev), len(prev - sel)
        churn.append({"date": t, "n": len(sel), "added": added, "removed": removed,
                      "churn_pct": (removed / len(prev)) if prev else float("nan")})
        prev = sel

    # 廣播為逐日成員（[t_i, t_{i+1}) 用 t_i 的選擇；reselect 點之外不變）
    member_w = pd.DataFrame(False, index=idx, columns=stocks)
    reb_list = list(rebs)
    for i, t in enumerate(reb_list):
        end = reb_list[i + 1] if i + 1 < len(reb_list) else (idx[-1] + pd.Timedelta(days=1))
        seg = (idx >= t) & (idx < end)
        sel = members_by_reb[t]
        if sel:
            member_w.loc[seg, sorted(sel)] = True

    _assert_no_lookahead(member_w, rebs)
    churn_df = pd.DataFrame(churn)
    return member_w, churn_df, members_by_reb


def _assert_no_lookahead(member_w: pd.DataFrame, rebs: pd.DatetimeIndex) -> None:
    """成員只能在 rebalance 日改變（否則代表洩漏了區間內的未來資訊）。"""
    changed = (member_w != member_w.shift(1)).any(axis=1).to_numpy()
    changed[0] = False
    off = set(member_w.index[changed]) - set(rebs)
    assert not off, f"PIT 違規：成員在非 rebalance 日改變：{sorted(off)[:5]}"


def apply_membership(sig: pd.DataFrame, member_w: pd.DataFrame) -> pd.DataFrame:
    """把 PIT 成員 baked 進 entry_signal（entry &= member），其餘欄位原樣保留 → 直接餵 run_capped。
    不在成員寬表中的 (date,stock) 視為非成員（False）。**不修改 run_capped**。"""
    long_true = member_w.stack()                       # MultiIndex (date, stock) bool
    long_true = long_true[long_true].reset_index()
    long_true.columns = ["date", "stock_id", "_member"]
    out = sig.merge(long_true, on=["date", "stock_id"], how="left")
    member = out["_member"].fillna(False).to_numpy()
    out["entry_signal"] = out["entry_signal"].to_numpy() & member
    return out.drop(columns="_member")


def churn_summary(churn_df: pd.DataFrame) -> str:
    """換手率一行摘要（跳過首次 reselect 的 NaN）。"""
    c = churn_df["churn_pct"].dropna()
    if c.empty:
        return "churn: n/a"
    return (f"reselect {len(churn_df)} 次｜每次平均成員 {churn_df['n'].mean():.0f}｜"
            f"換手率 mean {c.mean():.0%} / median {c.median():.0%} / max {c.max():.0%}")


# ───────────────────────── 自檢（純函式、無 IO、不打 API）─────────────────────────
def _selfcheck():
    print("pit_universe 自檢（合成資料，驗無前視 + top-K + 上市年資 + churn）…")
    dates = pd.bdate_range("2018-01-01", "2020-12-31")   # 3 年工作日
    n = len(dates)

    def mkrow(sid, close, vol, first=None):
        d = dates if first is None else dates[dates >= pd.Timestamp(first)]
        cl = np.full(len(d), float(close)); vo = np.full(len(d), float(vol))
        return pd.DataFrame({"date": d, "stock_id": sid, "open": cl, "high": cl,
                             "low": cl, "close": cl, "volume": vo})

    # A: 全程高量；C: 全程中量；B: 前低後高（2020 才放量）；D: 2020-01 才上市（年資不足）；E: 雞蛋水餃(低價)
    volB = np.where(dates < pd.Timestamp("2020-01-01"), 1.0, 1e9)
    rowB = pd.DataFrame({"date": dates, "stock_id": "B", "open": 50.0, "high": 50.0,
                         "low": 50.0, "close": 50.0, "volume": volB})
    pdf = pd.concat([
        mkrow("A", 100, 1e7), mkrow("C", 80, 5e6), rowB,
        mkrow("D", 200, 1e12, first="2020-01-02"),       # 超高量但 2020 才上市
        mkrow("E", 2, 1e12),                              # 超高量但低於 price_floor
    ], ignore_index=True)
    pdf["date"] = pd.to_datetime(pdf["date"])

    member, churn, mbr = build_membership(pdf, top_k=2, rebalance="Q", turnover_window=60,
                                          min_history_years=1.0, price_floor=10.0, listed_grace_days=120)
    rebs = rebalance_dates(pd.DatetimeIndex(sorted(pdf["date"].unique())), "Q")

    def yq(t):
        return (t.year, (t.month - 1) // 3 + 1)
    sel = {yq(t): s for t, s in mbr.items()}
    print("  逐季 reselect 選中：", {f"{y}Q{q}": sorted(s) for (y, q), s in sel.items()})

    # 冷啟：2018Q1（樣本首個 reselect）成交額暖身不足 → 空池（不憑空選股）
    assert sel[(2018, 1)] == set(), f"2018Q1 應冷啟空池，實得 {sorted(sel[(2018, 1)])}"
    # 左censored 老股豁免：2018Q2（暖身後）A,C 即入選（即便快取年資<1yr）→ 證明豁免生效、2018 不被整年丟棄
    assert sel[(2018, 2)] == {"A", "C"}, f"2018Q2 老股豁免應選 A,C，實得 {sorted(sel[(2018, 2)])}"
    # 無前視（最關鍵）：B 2020 才放量 → 2018/2019 任一季都不得入選（用 trailing 量，非未來量）
    assert all("B" not in sel[(y, q)] for y in (2018, 2019) for q in (1, 2, 3, 4)), \
        "前視洩漏：B 不該在 2020 放量前入選"
    # 真 IPO 年資：D 2020-01 才上市 → 全期年資不足，永不入選
    assert all("D" not in s for s in sel.values()), "年資違規：D 2020 IPO 不該入選"
    # 價格下限：E 價 2 < floor 10 → 永不入選（即便量超大）
    assert all("E" not in s for s in sel.values()), "價格下限違規：E 低於 floor 不該入選"
    # top-K：B 2020 放量後入選（PIT 流動性更新），且尺寸 ≤ K
    assert "B" in sel[(2020, 2)] and len(sel[(2020, 2)]) <= 2, "B 2020 放量後應入選且 top-K≤2"
    # 成員只在 reselect 日變（無前視 assert）
    _assert_no_lookahead(member, rebs)
    # apply_membership：baked 進 entry（用 2019；B 非成員、A 成員）
    sig = pd.DataFrame({"date": pdf["date"], "stock_id": pdf["stock_id"],
                        "entry_signal": True, "score": 1.0})
    sig2 = apply_membership(sig, member)
    b19 = (sig2["stock_id"] == "B") & (sig2["date"].dt.year == 2019)
    a19 = (sig2["stock_id"] == "A") & (sig2["date"].dt.year == 2019)
    assert not sig2.loc[b19, "entry_signal"].any(), "apply_membership 未正確 gate 非成員(B@2019)"
    assert sig2.loc[a19, "entry_signal"].all(), "apply_membership 誤殺成員(A@2019)"
    print("  ", churn_summary(churn))
    print("自檢 PASS ✅（冷啟空池 / 老股豁免 / 無前視 / top-K / 年資 / 價格下限 / apply_membership 皆正確）")


if __name__ == "__main__":
    _selfcheck()

"""
notebooks/r0_data_audit.py
R0 · §1 前置 —— 資料就緒稽核（純快取，不打 API、不碰 FinMindFetcher）。

承 docs/PIT_REBUILD_PLAN.md §1 與 IMPROVEMENT_PLAN_v2.md 附錄 B：乾淨 PIT 重建前，先驗
廣池籌碼是否就緒、逐檔籌碼缺口、可用子集，並明記 survivorship 殘留（FinMind 此 stack 無下市）。

輸出：
  · 逐 dataset 覆蓋率（價量/法人/融資券/除權息）。
  · 四方完整集 price∩inst∩margin∩div（= adjust=True+籌碼純快取可用工作池）與各差集。
  · 逐檔 institutional/margin 起訖 + 缺口（覆蓋率、最大連續缺漏交易日），標「籌碼完整」子集。
  · survivorship 殘留聲明。
  · 就緒 Gate 判定（法人∩融資券 ≥ 1400）。
  · 寫 data/processed/r0_cache_audit.json（four_way / chip_dense / full_span 清單，供 R0b 共用同一池）。

純快取保證：本檔只 glob + pd.read_pickle 既有 pkl，絕不實例化 fetcher、絕不連網。
用法：.venv/bin/python notebooks/r0_data_audit.py
"""
import os
import sys
import glob
import json

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
NB_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(NB_DIR)
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

CACHE = os.path.join(ROOT, "data", "raw", "finmind_cache")
WINDOW = "2018-01-01__2025-12-31"
OUT_JSON = os.path.join(ROOT, "data", "processed", "r0_cache_audit.json")

PRICE = "TaiwanStockPrice"
INST = "TaiwanStockInstitutionalInvestorsBuySell"
MARGIN = "TaiwanStockMarginPurchaseShortSale"
DIV = "TaiwanStockDividendResult"

GATE_MIN = 1400              # 就緒門檻：法人 ∩ 融資券 ≥ 1400（PIT_REBUILD_PLAN §1）
CHIP_DENSE_COV = 0.95       # 「籌碼完整」門檻：inst & margin 覆蓋該股交易日 ≥ 95%
FULL_SPAN_BY = "2018-06-01"  # 全期橫跨：首個真實交易列 ≤ 此日（否則為期中 IPO）


def ids_for(dataset: str, window: str = WINDOW) -> set:
    """該 dataset 在指定 window 有 pkl 的 stock_id 集合（純檔名解析，不讀檔）。"""
    pat = f"{CACHE}/{dataset}__*__{window}.pkl"
    return {os.path.basename(p).split("__")[1] for p in glob.glob(pat)}


def price_dates(sid: str) -> pd.DatetimeIndex:
    """該股價量真實交易日（close>0 & open>0；與 fetcher.get_daily_price 同口徑過濾）。"""
    df = pd.read_pickle(f"{CACHE}/{PRICE}__{sid}__{WINDOW}.pkl")
    df = df.rename(columns={"max": "high", "min": "low", "Trading_Volume": "volume"})
    df["date"] = pd.to_datetime(df["date"])
    df = df[(df["close"] > 0) & (df["open"] > 0)]
    return pd.DatetimeIndex(df["date"].sort_values().unique())


def chip_dates(sid: str, dataset: str) -> pd.DatetimeIndex:
    p = f"{CACHE}/{dataset}__{sid}__{WINDOW}.pkl"
    if not os.path.exists(p):
        return pd.DatetimeIndex([])
    df = pd.read_pickle(p)
    if df.empty or "date" not in df.columns:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(pd.to_datetime(df["date"]).sort_values().unique())


def coverage_and_gap(cal: pd.DatetimeIndex, have: pd.DatetimeIndex):
    """在價量交易日曆 cal 上，have 的覆蓋率 + 最大連續缺漏交易日數 + 起訖。"""
    if len(cal) == 0:
        return float("nan"), 0, None, None
    haveset = set(have)
    present = np.array([d in haveset for d in cal], dtype=bool)
    cov = float(present.mean())
    # 最大連續 False（以交易日計）
    max_gap = run = 0
    for v in present:
        run = 0 if v else run + 1
        max_gap = max(max_gap, run)
    first = (have.min().date().isoformat() if len(have) else None)
    last = (have.max().date().isoformat() if len(have) else None)
    return cov, int(max_gap), first, last


def main():
    print("=" * 100)
    print("R0 §1 資料就緒稽核（純快取，不打 API） | window", WINDOW)
    print("=" * 100)

    price, inst, marg, div = (ids_for(PRICE), ids_for(INST), ids_for(MARGIN), ids_for(DIV))
    print("\n[逐 dataset 覆蓋率]")
    print(f"  價量   TaiwanStockPrice                       : {len(price)}")
    print(f"  法人   InstitutionalInvestorsBuySell          : {len(inst)}")
    print(f"  融資券 MarginPurchaseShortSale                : {len(marg)}")
    print(f"  除權息 DividendResult                         : {len(div)}")

    inst_marg = inst & marg
    four_way = price & inst & marg & div
    no_div = price - div
    no_marg = price - marg
    no_inst = price - inst
    print("\n[交集 / 差集]")
    print(f"  法人 ∩ 融資券                = {len(inst_marg)}   (Gate 門檻 ≥ {GATE_MIN})")
    print(f"  四方完整 price∩inst∩marg∩div = {len(four_way)}   ← adjust=True+籌碼 純快取工作池")
    print(f"  有價量但無除權息 (adjust=True 會打 API → 排除) = {len(no_div)}")
    print(f"  有價量但無融資券 = {len(no_marg)}   ｜ 有價量但無法人 = {len(no_inst)}")

    # ── 逐檔籌碼缺口（在四方完整集上）──
    work = sorted(four_way, key=lambda s: (len(s), s))
    print(f"\n[逐檔籌碼缺口分析] 掃描四方完整集 {len(work)} 檔（讀 price+inst+margin pkl）…")
    rows = []
    for i, sid in enumerate(work):
        try:
            cal = price_dates(sid)
            ci, gi, fi, li = coverage_and_gap(cal, chip_dates(sid, INST))
            cm, gm, fm, lm = coverage_and_gap(cal, chip_dates(sid, MARGIN))
            rows.append({"sid": sid, "n_days": len(cal),
                         "first_trade": (cal.min().date().isoformat() if len(cal) else None),
                         "last_trade": (cal.max().date().isoformat() if len(cal) else None),
                         "cov_inst": ci, "gap_inst": gi, "inst_first": fi, "inst_last": li,
                         "cov_margin": cm, "gap_margin": gm, "margin_first": fm, "margin_last": lm})
        except Exception as e:
            rows.append({"sid": sid, "error": str(e)})
        if (i + 1) % 300 == 0:
            print(f"  …{i+1}/{len(work)}")
    aud = pd.DataFrame(rows)
    ok = aud[aud.get("error").isna()] if "error" in aud.columns else aud

    def deciles(s):
        s = s.dropna()
        return "  ".join(f"{q:.2f}" for q in s.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).values)

    print("\n[覆蓋率分布（四方完整集；該股交易日中有籌碼的比例）]  分位 p10 p25 p50 p75 p90")
    print(f"  法人 cov   : {deciles(ok['cov_inst'])}")
    print(f"  融資券 cov : {deciles(ok['cov_margin'])}")
    print("  註：融資券覆蓋率偏低多為『非融資券標的』(合法無資料)，非資料損毀；籌碼分量該期記 0（保守、無前視）。")

    full_span = ok[ok["first_trade"] <= FULL_SPAN_BY]
    later_ipo = ok[ok["first_trade"] > FULL_SPAN_BY]
    chip_dense = ok[(ok["cov_inst"] >= CHIP_DENSE_COV) & (ok["cov_margin"] >= CHIP_DENSE_COV)]
    chip_dense_full = chip_dense[chip_dense["first_trade"] <= FULL_SPAN_BY]
    print("\n[可用子集]")
    print(f"  全期橫跨（首交易 ≤ {FULL_SPAN_BY}） : {len(full_span)}   ｜ 期中 IPO（> {FULL_SPAN_BY}）: {len(later_ipo)}")
    print(f"  籌碼完整（inst&margin cov ≥ {CHIP_DENSE_COV:.0%}） : {len(chip_dense)}   ｜ 其中全期橫跨 : {len(chip_dense_full)}")

    worst_i = ok.nsmallest(8, "cov_inst")[["sid", "cov_inst", "gap_inst", "n_days"]]
    worst_m = ok.nsmallest(8, "cov_margin")[["sid", "cov_margin", "gap_margin", "n_days"]]
    print("\n[最差法人覆蓋 8 檔]   " + "  ".join(f"{r.sid}:{r.cov_inst:.2f}(gap{r.gap_inst})" for r in worst_i.itertuples()))
    print("[最差融資覆蓋 8 檔]   " + "  ".join(f"{r.sid}:{r.cov_margin:.2f}(gap{r.gap_margin})" for r in worst_m.itertuples()))

    # ── survivorship 殘留聲明 ──
    print("\n" + "-" * 100)
    print("⚠️ survivorship 殘留（無法消除）：FinMind 此 stack 無下市/歷史成分 →")
    print("   工作池＝『2018 後仍存活且資料完整』池。2018 存在但 2026 前下市者完全缺席 →")
    print("   所有後續 PIT/OOS 數字皆為 **上界**，結論一律帶此 caveat。不假裝消除。")

    # ── Gate 判定 ──
    gate = len(inst_marg) >= GATE_MIN
    print("\n" + "=" * 100)
    print(f"就緒 Gate：法人∩融資券 {len(inst_marg)} {'≥' if gate else '<'} {GATE_MIN} → "
          f"{'PASS ✅（可啟動 R0）' if gate else 'FAIL ⛔（停，待 builder 補建）'}"
          f"｜四方完整工作池 {len(four_way)} 檔")
    print("=" * 100)

    # ── 寫 artifact（供 R0b 共用同一池；data/processed 已 gitignore）──
    try:
        os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
        payload = {
            "window": WINDOW, "gate_pass": bool(gate),
            "counts": {"price": len(price), "inst": len(inst), "margin": len(marg), "div": len(div),
                       "inst_cap_margin": len(inst_marg), "four_way": len(four_way)},
            "four_way": sorted(four_way),
            "chip_dense": sorted(chip_dense["sid"].tolist()),
            "full_span": sorted(full_span["sid"].tolist()),
            "no_div": sorted(no_div), "no_margin": sorted(no_marg), "no_inst": sorted(no_inst),
            "params": {"chip_dense_cov": CHIP_DENSE_COV, "full_span_by": FULL_SPAN_BY, "gate_min": GATE_MIN},
        }
        with open(OUT_JSON, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        print(f"\n[artifact] 已寫 {os.path.relpath(OUT_JSON, ROOT)}（four_way={len(four_way)} / "
              f"chip_dense={len(chip_dense)} / full_span={len(full_span)}）→ R0b 共用同一池")
    except Exception as e:
        print(f"[artifact] 寫入失敗（不影響稽核結論）：{e}")

    if not gate:
        sys.exit("Gate FAIL：資料未就緒，依紀律停止，不在不完整資料上重建。")


if __name__ == "__main__":
    main()

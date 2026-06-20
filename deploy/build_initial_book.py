"""
deploy/build_initial_book.py — Phase C 遷移「初始建倉」（一次性）。

把現行帳戶（benchmark 0050 或全現金）一次建到 6 資產 target 配置，**含 00864B**——補
PortfolioRebalancer 的冷啟缺口（其 BUY_ORDER/SELL_ORDER 皆不含 00864B、不會主動建/補該腿）。
建妥後再由人手切 config strategy.mode: allocator + 重啟，交給 allocator 做後續 drift 管理。

安全設計：
  - 預設 **dry-run**（只印計畫＋預估權重、不下單、不寫帳本）；加 --execute 才實際在 paper 帳戶下單。
  - --execute 會先搶單例鎖：若 bot 正在跑（鎖被持有）→ 拒絕執行（避免雙寫帳本競爭）。先停 bot 再跑。
  - 不碰 config、不切 mode、不重啟。

用法（先停 bot + 備份 data/processed/*.json；建議市場時段 09:10–13:30 跑＝真實零股簿）：
  .venv/bin/python deploy/build_initial_book.py             # 預覽
  .venv/bin/python deploy/build_initial_book.py --execute   # 實際建倉（paper）
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

from loguru import logger                                                      # noqa: E402
from src.data.fetcher import FugleFetcher                                      # noqa: E402
from src.execution.broker_factory import make_broker                          # noqa: E402
from src.execution.mmf_sleeve import SyntheticMMF                             # noqa: E402
from src.execution.odd_lot_fill import odd_lot_buy_fill, parse_odd_book, parse_odd_ladder  # noqa: E402
from src.execution.order_manager import OrderManager, PositionManager         # noqa: E402
from src.utils.helpers import calc_trade_cost, exec_slippage, load_settings, lot_size  # noqa: E402

ETF_SYMS = ["0050", "00981A", "00991A", "00635U", "00864B"]   # 交易所標的；MMF 為合成
MMF_SYM = "MMF"


def _alloc_targets() -> dict:
    """從 settings.yaml strategy.allocator.assets 讀 6 標的目標權重。"""
    alloc = (load_settings().get("strategy", {}) or {}).get("allocator", {}) or {}
    assets = alloc.get("assets", {}) or {}
    return {s: float(assets.get(s, {}).get("target", 0.0)) for s in ETF_SYMS + [MMF_SYM]}


def _buy_px(quote: dict | None, ref: float) -> float:
    """買進零股成交價＝賣方階梯 book-walk vwap；無簿 → ref×(1+slip)。"""
    slip = exec_slippage()
    asks = parse_odd_ladder(quote or {}, levels=5)
    res = odd_lot_buy_fill(1, asks, max_impact_pct=0.004) if asks else None
    if res is not None and res[1] > 0:
        return round(float(res[1]), 2)
    lp = (quote or {}).get("lastPrice")
    try:
        base = float(lp) if lp else 0.0
    except (TypeError, ValueError):
        base = 0.0
    base = base or float(ref or 0.0)
    return round(base * (1.0 + slip), 2) if base > 0 else 0.0


def _sell_px(quote: dict | None, ref: float) -> float:
    """賣出零股成交價＝零股簿最佳買價；無簿 → ref×(1−slip)。"""
    slip = exec_slippage()
    bid, _, _ = parse_odd_book(quote or {})
    if bid > 0:
        return round(float(bid), 2)
    lp = (quote or {}).get("lastPrice")
    try:
        base = float(lp) if lp else 0.0
    except (TypeError, ValueError):
        base = 0.0
    base = base or float(ref or 0.0)
    return round(base * (1.0 - slip), 2) if base > 0 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase C 初始建倉（6 資產含 00864B）")
    ap.add_argument("--execute", action="store_true", help="實際下單（預設 dry-run 只預覽）")
    args = ap.parse_args()
    tag = "EXECUTE" if args.execute else "DRY-RUN"

    if args.execute:
        from src.utils.singleton import acquire_singleton_lock
        if not acquire_singleton_lock():
            print("🟥 偵測到 bot 正在執行（單例鎖被持有）→ 拒絕 --execute（避免帳本雙寫競爭）。\n"
                  "   先停 bot：bash deploy/macos/stop_bot.sh，再重跑 --execute。")
            return

    tw = _alloc_targets()
    if abs(sum(tw.values()) - 1.0) > 0.02:
        logger.warning(f"target 權重和 {sum(tw.values()):.3f} 偏離 1.0，請檢查 config")

    broker = make_broker()
    broker.connect()
    pos_mgr = PositionManager()
    fugle = FugleFetcher()
    mmf = SyntheticMMF()
    lot = lot_size()

    cash = float(broker.get_balance())
    holdings = {p["stock_id"]: int(p["quantity"]) for p in pos_mgr.summary()
                if p["stock_id"] in ETF_SYMS}
    quotes = fugle.get_odd_quotes_multi(ETF_SYMS)
    spx = {s: _sell_px(quotes.get(s), 0.0) for s in ETF_SYMS}     # 變現口徑估權益
    mmf_val = float(mmf.value())

    hv = {s: holdings.get(s, 0) * spx.get(s, 0.0) * lot for s in ETF_SYMS}
    equity = cash + sum(hv.values()) + mmf_val
    print(f"=== build_initial_book [{tag}] ===")
    print(f"現金 {cash:,.0f}｜持倉 { {s: holdings.get(s, 0) for s in ETF_SYMS} }｜"
          f"MMF {mmf_val:,.0f}｜總權益 {equity:,.0f}")
    if equity <= 0:
        print("總權益 ≤ 0，中止。")
        return

    # 目標股數 + 買賣計畫（含 00864B；先賣超額、後買不足；買序 0050→…→00864B）
    plan_sell, plan_buy = [], []
    for s in ETF_SYMS:
        px_est = spx.get(s) or _buy_px(quotes.get(s), 0.0)
        if px_est <= 0:
            print(f"  ⚠️ {s}: 無有效報價，跳過")
            continue
        tgt_sh = int(round(equity * tw[s] / (px_est * lot)))
        delta = tgt_sh - holdings.get(s, 0)
        if delta < 0:
            plan_sell.append((s, -delta, spx[s]))
        elif delta > 0:
            plan_buy.append((s, delta, _buy_px(quotes.get(s), 0.0)))
    plan_buy.sort(key=lambda x: ETF_SYMS.index(x[0]))
    tgt_mmf = equity * tw[MMF_SYM]

    print("\n計畫（先賣後買 → MMF 收尾）：")
    for s, q, px in plan_sell:
        print(f"  賣 {s} {q}股 @{px} ≈ {q * px * lot:,.0f}")
    for s, q, px in plan_buy:
        print(f"  買 {s} {q}股 @{px} ≈ {q * px * lot:,.0f}  {'← 00864B 冷啟補腿' if s == '00864B' else ''}")
    print(f"  MMF 目標 {tgt_mmf:,.0f}（現 {mmf_val:,.0f}）")

    if not args.execute:
        # 預估建倉後權重（用估價，不下單）
        proj = dict(holdings)
        for s, q, _ in plan_sell:
            proj[s] = proj.get(s, 0) - q
        for s, q, _ in plan_buy:
            proj[s] = proj.get(s, 0) + q
        print("\n預估建倉後權重：")
        for s in ETF_SYMS:
            w = proj.get(s, 0) * spx.get(s, 0.0) * lot / equity if equity > 0 else 0
            print(f"  {s}: {proj.get(s, 0)}股 ({w * 100:.1f}% / 目標 {tw[s] * 100:.1f}%)")
        print(f"  MMF: 目標 {tw[MMF_SYM] * 100:.1f}%")
        print("\n[dry-run] 未下單、未寫帳本。確認無誤後加 --execute 實際建倉（先停 bot）。")
        return

    om = OrderManager(broker)
    # 段 1：賣（釋金）
    for s, q, px in plan_sell:
        res = om.exit(s, px, q, "initial_build")
        if "error" not in res:
            p = pos_mgr._positions.get(s)
            if p:
                newq = int(p["quantity"]) - q
                if newq <= 0:
                    pos_mgr.remove(s)
                else:
                    p["quantity"] = newq
                    pos_mgr._save()
            print(f"  ✓ 賣 {s} {q}@{px}")
        else:
            print(f"  ✗ 賣 {s} 失敗：{res.get('error')}")
    # 段 2：買（以 broker 實際現金為硬閘縮量）
    running = float(broker.get_balance())
    for s, q, px in plan_buy:
        buyable = q
        while buyable >= 1:
            amt = px * buyable * lot
            fee = calc_trade_cost(px, buyable, "buy")["fee"]
            if amt + fee <= running + 1e-6:
                break
            buyable -= 1
        if buyable < 1:
            print(f"  - 買 {s} 現金不足（{running:,.0f}），跳過")
            continue
        res = om.enter(s, px, buyable, "initial_build")
        if "error" not in res:
            pos_mgr.add(s, px, buyable, "initial_build", None, trail_pct=None)
            running = float(broker.get_balance())
            print(f"  ✓ 買 {s} {buyable}@{px}" + ("（現金縮量）" if buyable < q else ""))
        else:
            print(f"  ✗ 買 {s} 失敗：{res.get('error')}")
    # 段 3：殘餘現金存入 MMF（≈ 目標水位；買不滿的殘額也併入＝現金緩衝，allocator 後續再部署）
    residual = float(broker.get_balance())
    if residual > 1:
        debited = -broker.adjust_cash(-residual)
        mmf.deposit(debited)
        print(f"  ✓ 殘餘現金 {debited:,.0f} → MMF（目標 {tgt_mmf:,.0f}）")

    # 驗收
    print("\n=== 建倉後 ===")
    cash2 = float(broker.get_balance())
    h2 = {p["stock_id"]: int(p["quantity"]) for p in pos_mgr.summary()
          if p["stock_id"] in ETF_SYMS}
    q2 = fugle.get_odd_quotes_multi(ETF_SYMS)
    hv2 = {s: h2.get(s, 0) * (_sell_px(q2.get(s), 0.0) or 0.0) * lot for s in ETF_SYMS}
    mmf2 = float(mmf.value())
    eq2 = cash2 + sum(hv2.values()) + mmf2
    for s in ETF_SYMS:
        w = hv2[s] / eq2 if eq2 > 0 else 0
        flag = "  ⚠️ <地板" if (s == "00864B" and w < 0.10) else ""
        print(f"  {s}: {h2.get(s, 0)}股 ≈ {hv2[s]:,.0f} ({w * 100:.1f}% / 目標 {tw[s] * 100:.1f}%){flag}")
    print(f"  MMF: {mmf2:,.0f} ({(mmf2 / eq2 * 100) if eq2 else 0:.1f}% / 目標 {tw[MMF_SYM] * 100:.1f}%)")
    print(f"  現金殘 {cash2:,.0f}｜總權益 {eq2:,.0f}")
    print("\n下一步：切 config strategy.mode: allocator + 重啟（launchctl kickstart -k gui/$(id -u)/com.tradingbot.start）。")


if __name__ == "__main__":
    main()

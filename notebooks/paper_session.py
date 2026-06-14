"""
notebooks/paper_session.py
端到端模擬盤 session：歷史逐日重播，把策略訊號送過 LIVE 執行路徑
（PaperBroker 本地撮合 + RiskGuard.check_exits 統一出場 + can_enter 風控），
證明整套系統端到端可跑，並與 vectorbt 回測對照（live 路徑是否重現回測）。

注意：用整股(1張=1000股) + 單檔≤30% 上限。高價權值股需大資金才買得起 1 張，
故此 demo 用較大資金跑通機制；真實 ≤5萬 資金的限制見輸出提醒。
用法：.venv\\Scripts\\python.exe notebooks\\paper_session.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
import pandas as pd
from src.backtest.signal_builder import HistoricalSignalBuilder
from src.execution.paper_broker import PaperBroker
from src.risk.risk_guard import RiskGuard
from src.utils.helpers import load_config, calc_trade_cost, lot_size

LOT = lot_size()

UNIVERSE = [
    "2330", "2454", "2303", "2308", "2379", "3034", "3711", "2337", "6415", "3008",
    "2317", "2382", "2357", "2376", "3231", "4938", "2356", "2353",
    "2881", "2882", "2891", "2886", "2884", "2885", "2892", "5880",
    "1301", "1303", "1326", "2002", "1101", "2207",
    "2603", "2609", "2615", "2412", "2912", "1216",
]
START, END = "2022-09-01", "2025-12-31"
INIT_CASH = 10_000_000   # demo 用大資金跑通整股機制（真實限制見結尾提醒）


def main():
    for fn in ["paper_account.json", "daily_risk_state.json"]:
        Path(f"data/processed/{fn}").unlink(missing_ok=True)

    cfg = load_config()
    pos_pct = cfg["entry"]["position_size_pct"]
    max_pos = cfg["entry"]["max_positions"]

    builder = HistoricalSignalBuilder()
    price_df, signal_df = builder.build(UNIVERSE, START, END)

    close = price_df.pivot(index="date", columns="stock_id", values="close").sort_index().ffill().bfill()
    open_ = price_df.pivot(index="date", columns="stock_id", values="open").reindex_like(close).ffill().bfill()
    sig = (signal_df.pivot(index="date", columns="stock_id", values="entry_signal")
           .reindex(index=close.index, columns=close.columns).fillna(False))
    dates = close.index

    broker = PaperBroker(initial_cash=INIT_CASH)
    broker.connect()
    rg = RiskGuard(total_capital=INIT_CASH)

    positions = {}      # sid -> {entry, peak, last, qty, entry_idx}
    trades = []         # 已實現：{sid, ret, pnl, reason}
    equity = []
    rejected_price = set()

    for i, d in enumerate(dates):
        # 1) 更新持倉 last/peak
        for sid, p in positions.items():
            px = float(close.at[d, sid])
            p["last"] = px
            p["peak"] = max(p["peak"], px)

        # 2) 出場（統一 check_exits：移動停損/持有上限）
        posdicts = [{"stock_id": sid, "entry_price": p["entry"], "peak_price": p["peak"],
                     "last_price": p["last"], "hold_days": i - p["entry_idx"]}
                    for sid, p in positions.items()]
        for sid, reason in rg.check_exits(posdicts):
            p = positions[sid]
            px_exit = float(open_.at[d, sid]) if i + 1 < len(dates) else float(close.at[d, sid])
            res = broker.place_order(sid, "Sell", px_exit, p["qty"])
            if "error" in res:
                continue
            buy_c = calc_trade_cost(p["entry"], p["qty"], "buy")["total_cost"]
            sell_c = calc_trade_cost(px_exit, p["qty"], "sell")["total_cost"]
            pnl = (px_exit - p["entry"]) * p["qty"] * LOT - buy_c - sell_c
            trades.append({"sid": sid, "ret": px_exit / p["entry"] - 1, "pnl": pnl, "reason": reason})
            del positions[sid]

        # 3) 進場（T+1：用前一日訊號，今日開盤進場）
        if i > 0:
            todays_sig = sig.iloc[i - 1]
            for sid in todays_sig.index[todays_sig.values]:
                if sid in positions or len(positions) >= max_pos:
                    continue
                px_in = float(open_.at[d, sid])
                if px_in <= 0:
                    continue
                qty = max(1, int(broker.get_balance() * pos_pct / (px_in * LOT)))
                ok, why = rg.can_enter(sid, px_in, qty, len(positions))
                if not ok:
                    if "單股倉位" in why:
                        rejected_price.add(sid)
                    continue
                res = broker.place_order(sid, "Buy", px_in, qty)
                if "error" not in res:
                    positions[sid] = {"entry": px_in, "peak": px_in, "last": px_in,
                                      "qty": qty, "entry_idx": i}

        # 4) 權益 = 現金 + 持倉市值
        mv = sum(p["qty"] * float(close.at[d, sid]) * LOT for sid, p in positions.items())
        equity.append(broker.get_balance() + mv)

    eq = pd.Series(equity, index=dates)
    total_ret = eq.iloc[-1] / INIT_CASH - 1
    dd = (eq / eq.cummax() - 1).min()
    wins = [t for t in trades if t["pnl"] > 0]
    win_rate = len(wins) / len(trades) if trades else 0
    by_reason = pd.Series([t["reason"] for t in trades]).value_counts().to_dict() if trades else {}

    print("\n=== 端到端模擬盤 session 結果（LIVE 路徑重播）===")
    print(f"  期間          {dates[0].date()} ~ {dates[-1].date()}")
    print(f"  初始/期末     {INIT_CASH:,.0f} → {eq.iloc[-1]:,.0f}")
    print(f"  總報酬        {total_ret*100:+.1f}%")
    print(f"  最大回撤      {dd*100:.1f}%")
    print(f"  完成交易      {len(trades)} 筆，勝率 {win_rate*100:.0f}%")
    print(f"  出場原因分布  {by_reason}")
    print(f"  尚未平倉      {len(positions)} 檔")
    print(f"\n  對照 vectorbt 回測（同 universe/期間）：總報酬 ~+37%、Sharpe 1.08")
    print(f"  → live 路徑(PaperBroker+check_exits) 與回測同數量級即代表執行邏輯一致")
    if rejected_price:
        print(f"\n⚠️ 因「單股≤30%總資金」+ 整股限制被擋下的高價股：{len(rejected_price)} 檔 "
              f"（如 {sorted(rejected_price)[:5]}）")
        print("   真實 ≤5萬 資金幾乎只能買 <50元 個股或改用盤中零股 —— 部署前需面對的限制。")


if __name__ == "__main__":
    main()

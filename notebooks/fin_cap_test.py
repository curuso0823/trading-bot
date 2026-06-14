"""
notebooks/fin_cap_test.py
升級2 測試：金融同時持倉上限 FIN≤2 / FIN≤3（mp=6, 35檔, 100k 零股）× 多窗。
對症依據：AI窗 FIN 吃 32% 進場(27/84) 3年僅 -518 元（佔位不貢獻）。
也測「FIN≤2 + 傳產各≤1」加強版，看資金是否被推向會賺的電子/AI。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.backtest.capped_sim import build_signals, run_capped, DEFAULT_UNIVERSE, AI_CANDIDATES, LIVE_UNIVERSE
from src.utils.sectors import get_sector

OLD_ECON = {"PLASTIC": 1, "CEMENT": 1, "STEEL": 1, "AUTO": 1, "SHIP": 1, "FOOD": 1, "RETAIL": 1, "TELECOM": 1}
VARIANTS = {
    "無上限(基準)": None,
    "FIN≤3": {"FIN": 3},
    "FIN≤2": {"FIN": 2},
    "FIN≤2+傳產各≤1": {"FIN": 2, **OLD_ECON},
}
WINDOWS = [("AI窗23-25", "2023-01-01", "2025-12-31"),
           ("近兩年24-25", "2024-01-01", "2025-12-31"),
           ("全期18-25", "2018-01-01", "2025-12-31"),
           ("2022熊", "2022-01-01", "2022-12-31"),
           ("2025(4月崩)", "2025-01-01", "2025-12-31")]


def main():
    price_df, sig = build_signals(DEFAULT_UNIVERSE + AI_CANDIDATES, "2018-01-01", "2025-12-31")
    for wname, s, e in WINDOWS:
        print(f"\n=== {wname}（mp=6）===")
        print(f"{'變體':<16}{'年化':>8}{'Sharpe':>7}{'MaxDD':>9}{'PF':>7}{'勝率':>6}{'交易':>5}{'Gate':>6}")
        for vname, cap in VARIANTS.items():
            r = run_capped(price_df, sig, LIVE_UNIVERSE, s, e, capital=100_000, max_pos=6,
                           mode="odd_lot", sector_max=cap)
            print(f"{vname:<16}{r['annual']*100:>7.1f}%{r['sharpe']:>7.2f}{r['dd']*100:>8.1f}%"
                  f"{r['pf']:>7.2f}{r['win_rate']*100:>5.0f}%{r['n_trades']:>5}{'PASS' if r['gate_pass'] else 'fail':>6}")

    # AI 窗最佳變體的族群轉移
    print("\nAI窗 進場族群（無上限 vs FIN≤2 vs FIN≤2+傳產≤1）：")
    for vname in ["無上限(基準)", "FIN≤2", "FIN≤2+傳產各≤1"]:
        r = run_capped(price_df, sig, LIVE_UNIVERSE, "2023-01-01", "2025-12-31",
                       capital=100_000, max_pos=6, mode="odd_lot", sector_max=VARIANTS[vname])
        bys, byp = {}, {}
        for sid, c in r["entry_counts"].items():
            bys[get_sector(sid)] = bys.get(get_sector(sid), 0) + c
            byp[get_sector(sid)] = byp.get(get_sector(sid), 0.0) + r["pnl_by_stock"].get(sid, 0.0)
        tot = sum(bys.values())
        fin_n, fin_p = bys.get("FIN", 0), byp.get("FIN", 0.0)
        ai_n = sum(bys.get(k, 0) for k in ["EMS", "SEMI", "THERMAL", "CHASSIS", "PCB", "NETWORK", "COMPONENT"])
        ai_p = sum(byp.get(k, 0.0) for k in ["EMS", "SEMI", "THERMAL", "CHASSIS", "PCB", "NETWORK", "COMPONENT"])
        print(f"  {vname:<16} FIN {fin_n}次({fin_n/tot*100:.0f}%) {fin_p:+,.0f}｜電子/AI {ai_n}次({ai_n/tot*100:.0f}%) {ai_p:+,.0f}｜總進場 {tot}")


if __name__ == "__main__":
    main()

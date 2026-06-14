"""
notebooks/capitulation_regime_test.py
P1 驗證：投降感知 regime 分類器的「事件判別力」（不交易，只看亮燈時機對不對）。

通過標準（這才算數，非報酬最佳化）：
  [真底] 2020/3、2022/10、2025/4（及2018/12，暖身caveat）→ TRUE_BOTTOM 應在 ±窗口內亮燈
  [假反彈] 2022/3、2022/8 熊市反彈 → 應判 FALSE_REBOUND、且「不可」誤判 TRUE_BOTTOM
  [稀有性] 全期 TRUE_BOTTOM 天數應「少且成簇」（散在200天=壞了）

用法：.venv\\Scripts\\python.exe notebooks\\capitulation_regime_test.py
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from src.signals.capitulation import CapitulationClassifier

HIST_START = "2016-01-01"   # 給 2018/12 約 2.75 年因果百分位暖身
END = "2025-12-31"

# 已知事件（台股大盤近似低點 / 熊市反彈窗口）
TRUE_BOTTOMS = {
    "2018/12 貿易戰底": ("2018-12-18", "2019-01-15"),
    "2020/03 covid底":  ("2020-03-13", "2020-03-31"),
    "2022/10 大空頭底": ("2022-10-20", "2022-11-10"),
    "2025/04 關稅V底":  ("2025-04-07", "2025-04-25"),
}
FALSE_RALLIES = {
    "2022/03 熊市反彈": ("2022-03-25", "2022-04-12"),
    "2022/08 熊市反彈": ("2022-08-10", "2022-08-26"),
}


def show_window(df, name, s, e):
    sub = df.loc[(df.index >= s) & (df.index <= e)]
    if sub.empty:
        print(f"\n  {name}: (無資料)"); return sub
    print(f"\n  ── {name}  [{s}~{e}] ──")
    print(f"  {'date':>11}{'close':>8}{'dd252':>8}{'volP':>6}{'amiP':>6}"
          f"{'%<MA60':>7}{'mg20':>8}{'fz':>6} | {'P B M F':>8} deep  regime")
    for d, row in sub.iterrows():
        gates = f"{int(row.gate_panic)} {int(row.gate_breadth)} {int(row.gate_margin)} {int(row.gate_foreign)}"
        print(f"  {d.date()!s:>11}{row.close:>8.1f}{row.dd252*100:>7.1f}%{row.vol_pctl:>6.2f}"
              f"{row.amihud_pctl:>6.2f}{row.pct_below_ma60*100:>6.0f}%{row.margin_chg20*100:>7.1f}%"
              f"{row.foreign_z:>6.1f} | {gates:>8}  {int(row.precond_deep)}   {row.regime}")
    return sub


def main():
    clf = CapitulationClassifier()
    print(f"投降感知 regime 分類器 — 事件判別驗證")
    print(f"universe={len(clf.universe)}檔聚合代理 | proxy={clf.proxy} | {HIST_START}~{END}")
    df = clf.compute(HIST_START, END)
    if df.empty:
        print("!! 無資料，請確認 FinMind token/快取"); return
    df = df[df.index >= "2017-06-01"]   # 丟掉百分位暖身不足段（仍保留 2018 前緩衝）

    # ① 全期 / 分年 regime 分佈
    print("\n========== 分年 regime 天數分佈 ==========")
    yr = df.groupby(df.index.year)["regime"].value_counts().unstack(fill_value=0)
    for col in ["NORMAL_BULL", "FALSE_REBOUND", "TRUE_BOTTOM", "BEAR"]:
        if col not in yr.columns:
            yr[col] = 0
    print(yr[["NORMAL_BULL", "FALSE_REBOUND", "TRUE_BOTTOM", "BEAR"]].to_string())

    # ② TRUE_BOTTOM 稀有性 + 成簇
    tb = df[df["true_bottom"]]
    n_tb = len(tb)
    # 數簇：相鄰 TRUE_BOTTOM 日間隔 >10 交易日視為新簇
    clusters = 0
    if n_tb:
        gaps = tb.index.to_series().diff().dt.days.fillna(999)
        clusters = int((gaps > 20).sum())
    print(f"\n========== TRUE_BOTTOM 稀有性 ==========")
    print(f"  全期 TRUE_BOTTOM 天數 = {n_tb} / {len(df)}  ({n_tb/len(df)*100:.1f}%) ；約 {clusters} 簇")
    print(f"  （理想：少且成簇＝對應 ~4 個真底；散在數百天=過敏，需收緊）")
    if n_tb:
        print("  TRUE_BOTTOM 日期：", ", ".join(str(d.date()) for d in tb.index[:40]))

    # ③ 真底事件：是否亮燈
    print("\n========== 真底事件判別（應 TRUE_BOTTOM 亮燈）==========")
    score_true = {}
    for name, (s, e) in TRUE_BOTTOMS.items():
        sub = show_window(df, name, s, e)
        hit = (sub["regime"] == "TRUE_BOTTOM").any() if not sub.empty else False
        alt3 = sub["alt_3of4"].any() if not sub.empty else False
        alt2 = sub["alt_2of4"].any() if not sub.empty else False
        score_true[name] = (hit, alt3, alt2)

    # ④ 假反彈事件：應 FALSE_REBOUND、不可 TRUE_BOTTOM
    print("\n\n========== 假反彈事件判別（應 FALSE_REBOUND、禁 TRUE_BOTTOM）==========")
    score_false = {}
    for name, (s, e) in FALSE_RALLIES.items():
        sub = show_window(df, name, s, e)
        fr = (sub["regime"] == "FALSE_REBOUND").any() if not sub.empty else False
        bad = (sub["regime"] == "TRUE_BOTTOM").any() if not sub.empty else False
        score_false[name] = (fr, bad)

    # ⑤ 計分卡
    print("\n\n========== 判別計分卡 ==========")
    print("  真底（主規則 conservative / 對照 3of4 / 2of4）：")
    for name, (hit, a3, a2) in score_true.items():
        mark = "[OK]" if hit else ("[~3of4]" if a3 else ("[~2of4]" if a2 else "[MISS]"))
        print(f"    {name:>16}: 主規則={'亮' if hit else '暗'}  3of4={'亮' if a3 else '暗'}"
              f"  2of4={'亮' if a2 else '暗'}   {mark}")
    print("  假反彈（要 FALSE_REBOUND 且禁 TRUE_BOTTOM）：")
    for name, (fr, bad) in score_false.items():
        mark = "[OK]" if (fr and not bad) else ("[LEAK真底!]" if bad else "[未標假反彈]")
        print(f"    {name:>16}: FALSE_REBOUND={'是' if fr else '否'}  誤判真底={'是!' if bad else '否'}   {mark}")

    # 存檔供後續看
    out = "data/processed/capitulation_regime.csv"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    df.to_csv(out, encoding="utf-8-sig")
    print(f"\n  完整 regime 序列已存：{out}")


if __name__ == "__main__":
    main()

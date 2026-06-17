# CLAUDE.md — 新 session 開工前必讀（專案真相與紀律）

> 本檔由 Claude Code 在每個 session 啟動時自動載入。**這是本專案的最高優先脈絡**：以下「現況真相」凌駕任何舊文件/舊回測數字。

---

## 🟥 現況真相（2026-06-17，R0 乾淨重建後）— 不可被舊污染結論帶偏

- 本專案的**歷史回測選股池（35 檔手挑 `LIVE_UNIVERSE`）經 Phase 9 證實含重大後見之明污染**：
  該名單是 2026 用「近 3 年 CAGR」事後挑 AI 贏家（`AI_ADOPTED` 更用 2023–25 績效分窗挑出＝直接 look-ahead）、剔落後股。
  量化：**同規模手挑溢價 = +0.38 pooled OOS Sharpe / +9pp 年化（下界，倖存者未除）**。
- 因此**以下數字一律「錯誤被污染、被高估」，不得當定論引用、不得據以調 live**：
  全期 **12.7% / Sharpe 1.16 / DD −16.0% / 總報酬 152%**、Phase 6/7/8 的一切結果、§6.2/6.3 漏斗、`a1_*`/`a2_*`/`exit_sweep`/`sizing_*` 等旁支絕對數字。
- **誠實真相（R0 已執行，2026-06-17；此為新真實 baseline，取代上面污染數字）**：在**無 look-ahead 機械 PIT universe**（`src/backtest/pit_universe.py`：1706 四方完整池、季 reselect、trailing-60d 成交額 top-K + 上市滿 1y + 價格下限）上跑**完整 live edge**（TA+籌碼+block_only regime+vol_target、`adjust=True`、純快取），對照預先指定被動（`notebooks/r0_honest_baseline.py`）：
  - **OOS(2022–25) pooled Sharpe 隨 K 在 0.56–1.21 非單調跳動（中位 0.93）** vs 基準B **0.80** / 0050 **0.95** → **與被動大致打平、無穩健 alpha**（IR vs 基準B 僅 1/3 K 為正；全期 Sharpe 0.62–0.75 一致輸被動；最佳 K=150 的 1.21＝三選一 cherry-pick，鄰格 K=100 反而 0.56＝雜訊跡象）。
  - **唯一較穩的相對優勢＝regime 降 DD**：PIT 臂 DD −22~−29% vs 被動 −32~−34%、最差前進年 −15~−17%（仍含存活池灌水、比帳面小＝附錄 B Tier D）。
  - 誠實全期約 **8–10% / Sharpe 0.62–0.75**（含 2018 冷啟），**取代污染的 12.7% / 1.16 / −16%**——手挑溢價確實又大又真。
  - ⚠️ 仍是**上界**（survivorship：FinMind 無下市）；**主動是否有真 alpha 未定論**，K 去留待 **R1 walk-forward（每 fold 內 OOS 選 K）** 裁決。注：R0 的 ~0.9 比 Phase 9 粗版 momentum-only 的 ≈0.50 高，係 R0 跑**完整 edge**（籌碼+adjust+乾淨 top-K），非翻案。

## 📌 權威文件（真相地位，依序必讀）

1. **`docs/PIT_REBUILD_PLAN.md`** ← **前進計劃的唯一真相**。以乾淨 PIT 資料「從零重建可驗證獲利策略」的逐步 playbook（R0→R6；**R0 已完成、現於 R1**，R0 結果見該檔 §2 結果區）。任何「接下來做什麼」以此為準。
2. **`docs/IMPROVEMENT_PLAN_v2.md` 附錄 B** ← 全專案 universe 後見之明污染稽核（Tier A–D 受污染清單、含被否決結論）。
3. `taiwan_trading_bot_master.md` 第六章 ＋ `docs/IMPROVEMENT_PLAN_v2.md` 本文 ← 歷史脈絡，但其數字已就地標 🟥「錯誤被污染」，**僅供脈絡、非定論**。

## ✅ 鐵則（所有 session 遵守）

1. **不得**把上述污染數字當有效結論引用，**不得**據舊污染結論改 live（`config/strategy.yaml`、`src/`）。
2. 在乾淨 PIT 重建（`PIT_REBUILD_PLAN.md` R0–R5）通過**總 Gate（OOS 勝基準B，或 DD 優勢單獨成立）前，live 全不動**。
3. 每個實驗綁 **walk-forward OOS**，in-sample 只當線索；對照基準**固定預先指定**：0050 買持 + 基準B（vol_target 0.011，**非** best-of-sweep）。
4. 回測**純快取、不打 API**（背景 full-market builder 在跑、共用 FinMind 配額）；引擎改動須**行為中性 additive**（新參數預設＝舊行為，中性檢查把關）。
5. **倖存者偏誤無法消除**（FinMind 此 stack 無下市/歷史成分）→ 即使「誠實 PIT」結果仍是上界，結論須帶此 caveat。
6. **不自動 push；commit 僅在使用者明說時**；commit 排除 runtime 產物（`data/archive/*`、`logs/*`、`start.sh.save`）。

## 🧭 專案定位（快速 orientation）

- 台股 paper-trading bot；live＝`config/strategy.yaml` + `src/`（單一真相）。回測引擎＝`src/backtest/capped_sim.py`（`run_capped`，live-aligned：top-N chip-score 進場、vol_target 配重、ATR 移動停損、max_hold、T+1 執行）。
- 既有 walk-forward / grid harness 可複用：`notebooks/p8_walkforward.py`、`p6_*`、`p7_exit_diag.py`、`p9_*`、`benchmark_backtest.py`。
- **PIT 重建進度**：廣池籌碼 builder **已完成**（法人∩融資券 1813 ≥ 1400，四方完整 price∩inst∩margin∩div = **1706**）；**R0 已執行完畢**（`notebooks/r0_data_audit.py` + `src/backtest/pit_universe.py` + `notebooks/r0_honest_baseline.py`，結果見「現況真相」）。**下一步＝R1（walk-forward 選 K）**，等使用者下指令。
- **重建走新 branch `pit-rebuild`**（R0 產物在此）；`main`（live config/src）不動到通過總 Gate。R0 純新增模組/notebook，未改 live、未 commit。

---

*建立 2026-06-16｜更新 2026-06-17（R0 完成、現況真相改寫為乾淨 baseline）| 性質：standing 真相與紀律；隨乾淨重建進度（R1–R6）續更新。*

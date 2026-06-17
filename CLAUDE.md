# CLAUDE.md — 新 session 開工前必讀（專案真相與紀律）

> 本檔由 Claude Code 在每個 session 啟動時自動載入。**這是本專案的最高優先脈絡**：以下「現況真相」凌駕任何舊文件/舊回測數字。

---

## 🟥 現況真相（2026-06-17，R0–R5 乾淨重建收束後）— 不可被舊污染結論帶偏

- 本專案的**歷史回測選股池（35 檔手挑 `LIVE_UNIVERSE`）經 Phase 9 證實含重大後見之明污染**：
  該名單是 2026 用「近 3 年 CAGR」事後挑 AI 贏家（`AI_ADOPTED` 更用 2023–25 績效分窗挑出＝直接 look-ahead）、剔落後股。
  量化：**同規模手挑溢價 = +0.38 pooled OOS Sharpe / +9pp 年化（下界，倖存者未除）**。
- 因此**以下數字一律「錯誤被污染、被高估」，不得當定論引用、不得據以調 live**：
  全期 **12.7% / Sharpe 1.16 / DD −16.0% / 總報酬 152%**、Phase 6/7/8 的一切結果、§6.2/6.3 漏斗、`a1_*`/`a2_*`/`exit_sweep`/`sizing_*` 等旁支絕對數字。
- **誠實真相（R0 已執行，2026-06-17；此為新真實 baseline，取代上面污染數字）**：在**無 look-ahead 機械 PIT universe**（`src/backtest/pit_universe.py`：1706 四方完整池、季 reselect、trailing-60d 成交額 top-K + 上市滿 1y + 價格下限）上跑**完整 live edge**（TA+籌碼+block_only regime+vol_target、`adjust=True`、純快取），對照預先指定被動（`notebooks/r0_honest_baseline.py`）：
  - **OOS(2022–25) pooled Sharpe 隨 K 在 0.56–1.21 非單調跳動（中位 0.93）** vs 基準B **0.80** / 0050 **0.95** → **與被動大致打平、無穩健 alpha**（IR vs 基準B 僅 1/3 K 為正；全期 Sharpe 0.62–0.75 一致輸被動；最佳 K=150 的 1.21＝三選一 cherry-pick，鄰格 K=100 反而 0.56＝雜訊跡象）。
  - **唯一較穩的相對優勢＝regime 降 DD**：PIT 臂 DD −22~−29% vs 被動 −32~−34%、最差前進年 −15~−17%（仍含存活池灌水、比帳面小＝附錄 B Tier D）。
  - 誠實全期約 **8–10% / Sharpe 0.62–0.75**（含 2018 冷啟），**取代污染的 12.7% / 1.16 / −16%**——手挑溢價確實又大又真。
  - ⚠️ 仍是**上界**（survivorship：FinMind 無下市）；**主動是否有真 alpha：R1 已裁決＝無穩健 alpha（見下）**。注：R0 的 ~0.9 比 Phase 9 粗版 momentum-only 的 ≈0.50 高，係 R0 跑**完整 edge**（籌碼+adjust+乾淨 top-K），非翻案。
- **R1 細網格 walk-forward 裁決（2026-06-17，pit-rebuild；`notebooks/r1_walkforward.py`，結果見 `PIT_REBUILD_PLAN.md` §2「✅ R1 結果」）**：
  - **Q1：K=150 的 1.21＝in-sample cherry-pick（已證實，不採信）。** 18 點細網格 OOS Sharpe 鋸齒無高原（1 SE δ=0.51，150 僅 ~1σ 突出於 ~0.7 雜訊 floor＝孤峰）；walk-forward 每 fold 內選 K **從不選到 150**（落 110/300/400），pooled OOS 崩到 0.07–0.64、**全輸基準B 0.80、IR 全負、選擇不穩**。**ETF-排除 sanity 再坐實**：移除 0050 等 6 檔 ETF 後 1.21@150 崩到 0.89、峰移 K=50＝K 隨池組成重排（150 尖峰部分係策略在持基準 0050/0056）。**→ K 去留已裁決：誠實池無穩健特殊 K，不固定。**
  - **Q2：加格（max_pos>6）僅方向性線索、非穩健翻盤。** in-sample 加格＋budget sizing 明確改善（Sharpe↑/DD↓/集中度 top3 63%→24%，誠實池確比手挑池更需分散＝附錄 B 方向成立）；但 walk-forward N* 在 B1 代表 K 不穩、**IR vs 基準B 全負**（即使 K=150 穩定臂 pooled 1.12 也只是低-DD/低報酬**防禦 profile、非 alpha**）。**→ 不據以調 live；列為 R5 sizing 結構輸入。**
  - **R1 總 Gate：FAIL（無穩健 alpha）。唯一站得住的真 edge＝regime 降 DD**（外層 vs 被動 OOS 成立：wf 最差前進年 −12~−15% vs 被動 −32~−34%）。所有 OOS 仍是**上界**（survivorship）。**→ 下一步＝R-attrib（量化 regime-DD 層＋sizing 線索）＋ R5 誠實出口（被動為主、縮小主動）；total Gate 未過 → live 全不動。**
- **R-attrib 逐層歸因（2026-06-17，pit-rebuild；`notebooks/r_attribution.py`，詳見 `PIT_REBUILD_PLAN.md` §3）**：元件級 ablation（L0 等權PIT→+引擎→+TA→+籌碼gate→+籌碼select→+regime(=R1full)→+動量；etf_excl K=100；Sanity：L5 OOS 0.70 逐字重現 R1）。**結論：無任何層加 robust OOS alpha（signal-layer ΔSharpe 皆在 δ≈0.5 雜訊內、IR vs B 全程<0）；唯 regime 層 K-穩健（跨 K 一致 +17~24pp DD 降）＝防禦非 alpha。籌碼層 standalone 跨 K 變號(−0.53/+0.86/−0.17)、K=100 轉負(PnL 分散 top3 625%)＝master Phase 10#6 疑慮坐實**（唯在 regime 上有條件性 ~6pp DD 助益、未驗 K-穩健）；TA/動量＝雜訊。**→ R5 輸入：active 價值＝regime DD-overlay；極簡 regime+size 地板(0.57/−21%)已捕大半，全 edge 僅多雜訊內 Sharpe+~6pp DD。total Gate 未過 → live 不動。**
- **R5 正式裁決（2026-06-17，pit-rebuild；`notebooks/r5_alpha_verdict.py`，詳見 `PIT_REBUILD_PLAN.md` §5）＝重建收束**：風險對齊 DD 檢定（防禦 sleeve／+chip／全 edge L5 vs 0050、基準B 摻現金 de-risk 到同 vol；Sharpe/Calmar/DD-vol 皆 scale-invariant）＋顯著性（IR bootstrap、α/β Newey-West）。**① 無顯著 alpha**（IR vs B −0.28~−0.38 全負、95% CI 全含 0、α t≈0）；**② regime 降-DD 是「真但不顯著」的防禦、非純恆等式**（同 vol 下 maxDD 比基準B 淺 +3.6~+6.9pp、DD/vol 更優、2022 熊市 sleeve 段 −14.5% vs B@vol −29.5%＝確在擇時砍崩盤；**此修正「純恆等式」的過嚴預期**）；**③ 但對原始 0050 全輸**（0050 OOS Sharpe 0.94/Calmar 0.59、年化 20% vs 主動 8–9%；2023–25 大漲 buy-hold 完勝）、防禦不顯著、報酬代價大 → **不構成 mandate**；④ chip 提升 Sharpe/Calmar 但惡化 DD/vol、不值保留。**→ 總 Gate FAIL → live 全不動。誠實出口＝以被動（0050）為主；regime 防禦 sleeve 僅在明確 drawdown mandate 下小規模可選。** survivorship → 全為上界、結論更穩。**現行 live 手挑 35 檔帳面 edge 經證為後見之明、前瞻無 alpha；重建 R0→R5 誠實收束，R2/R3/R4 已被涵蓋跳過、R6 僅在使用者選落地時執行。**
- **R6 被動落地（2026-06-17；使用者拍板）**：R5 後使用者選「被動為主」、口味＝**vol-target + MA200 overlay**（平時跟 0050、跌破 MA200 退、漲回再跟）。live 早有 active/benchmark 模式開關（commit 45006c4）→ **零 code、純 config flip**：`config/settings.yaml` `strategy.mode: active→benchmark`、`benchmark`＝0050 / target_vol 0.011（**平時 vol-managed 為主**）/ regime_overlay true / regime_ma 200 / regime_action zero（**MA200 跌破＝最後一道防線**、全退現金）。**參數由意圖＋結構選（非 OOS 峰值挑、鐵則#7）。** `pytest` 97 passed、dry-run 正確（今日 0050＞MA200、未觸最後防線）。**定位＝結構性降回撤規則、非經證實 outperformer。待使用者部署（重啟 main.py＋清 `data/processed/paper_account.json` 孤兒倉）＋commit（皆未自動）；rollback＝mode 回 active。** ⇒ **live 由手挑 35 檔 active 改為被動 0050+MA200 overlay（config 已寫、待部署生效）。**

## 📌 權威文件（真相地位，依序必讀）

1. **`docs/PIT_REBUILD_PLAN.md`** ← **前進計劃的唯一真相**。以乾淨 PIT 資料「從零重建可驗證獲利策略」的逐步 playbook（R0→R6；**R0/R1/R-attrib/R5 全完成、總 Gate FAIL＝被動為主誠實出口、重建收束；R2/R3/R4 已被涵蓋跳過、R6 僅在使用者選落地時**，結果見該檔 §2/§3/§5）。任何「接下來做什麼」以此為準。
2. **`docs/IMPROVEMENT_PLAN_v2.md` 附錄 B** ← 全專案 universe 後見之明污染稽核（Tier A–D 受污染清單、含被否決結論）。
3. `taiwan_trading_bot_master.md` 第六章 ＋ `docs/IMPROVEMENT_PLAN_v2.md` 本文 ← 歷史脈絡，但其數字已就地標 🟥「錯誤被污染」，**僅供脈絡、非定論**。

## ✅ 鐵則（所有 session 遵守）

1. **不得**把上述污染數字當有效結論引用，**不得**據舊污染結論改 live（`config/strategy.yaml`、`src/`）。
2. 在乾淨 PIT 重建（`PIT_REBUILD_PLAN.md` R0–R5）通過**總 Gate（OOS 勝基準B，或 DD 優勢單獨成立）前，live 全不動**。
3. 每個實驗綁 **walk-forward OOS**，in-sample 只當線索；對照基準**固定預先指定**：0050 買持 + 基準B（vol_target 0.011，**非** best-of-sweep）。
4. 回測**純快取、不打 API**（背景 full-market builder 在跑、共用 FinMind 配額）；引擎改動須**行為中性 additive**（新參數預設＝舊行為，中性檢查把關）。
5. **倖存者偏誤無法消除**（FinMind 此 stack 無下市/歷史成分）→ 即使「誠實 PIT」結果仍是上界，結論須帶此 caveat。
6. **不自動 push；commit 僅在使用者明說時**；commit 排除 runtime 產物（`data/archive/*`、`logs/*`、`start.sh.save`）。
7. **參數掃描一律用細網格**：凡「調某一參數看結果」的掃描，單一參數至少 ~12–18 點、核心區間步長要小，**不得用 3–4 點粗掃下結論** —— 粗掃無法分辨「平滑高原＝訊號」vs「鋸齒跳動＝雜訊」（R0 的 K=50/100/150 → OOS 0.93/0.56/1.21 即無法解讀的教訓）。細掃是**特徵化/找線索**，決策仍只綁 walk-forward OOS，**不得用 in-sample 峰值挑參數**（那＝把 OOS 變 in-sample 的 cherry-pick）。
8. **舊 Phase 6/7/8 的絕對門檻不可移轉到誠實池**：那些 DD floor（−18% 軟／−20% 硬 REJECT）、Calmar/Sharpe 絕對目標係按**污染手挑池**（DD −14..−16%）校準；誠實 PIT 池 DD 結構性更深（R0：−22..−29%，**但仍優於被動 −32..−34%**），直接套絕對 floor 會 REJECT 全部格、選擇退化成永遠 fallback。重建期所有 reused gate 一律**重錨**：DD／績效門檻錨到 ①預先指定被動基準（基準B／0050），②同族相對比較（如 max_pos 錨 N=6）。**只有相對／結構準則可移轉，絕對數字一律退役。**

## 🧭 專案定位（快速 orientation）

- 台股 paper-trading bot；live＝`config/strategy.yaml` + `src/`（單一真相）。回測引擎＝`src/backtest/capped_sim.py`（`run_capped`，live-aligned：top-N chip-score 進場、vol_target 配重、ATR 移動停損、max_hold、T+1 執行）。
- 既有 walk-forward / grid harness 可複用：`notebooks/p8_walkforward.py`、`p6_*`、`p7_exit_diag.py`、`p9_*`、`benchmark_backtest.py`。
- **PIT 重建進度**：廣池籌碼 builder **已完成**（四方完整 **1706**）；**R0 + R1 + R-attrib + R5 已執行完畢（重建收束）**（R0：`r0_*`+`pit_universe.py`；R1：`r1_walkforward.py`+`r1_base_sig.pkl`；R-attrib：`r_attribution.py`+`r_attrib_base.pkl`；R5：`r5_alpha_verdict.py`，結果見「現況真相」對應區 ＋ `PIT_REBUILD_PLAN.md` §2/§3/§5）。裁決：K=cherry-pick、加格僅方向性、無任一層加 robust alpha、**唯 regime 崩盤防禦真但不顯著且不敵 0050 buy-hold → 無可前瞻複製 alpha、被動為主誠實出口、總 Gate FAIL**。**R6 已執行＝使用者選被動落地**：`config/settings.yaml` 改 benchmark 模式（0050 vol-target + MA200-zero overlay；平時跟 0050、跌破退、漲回進）、`pytest` 97 綠、dry-run 正確、**未 commit/未部署**（待使用者重啟 main.py＋清 paper 孤兒倉＋commit；可選 param flip half/MA120/0.011 base）。**重建 R0→R6 完成。** 後續：部署後監看；或另開因子研究（超出範圍）。R2/R3/R4 已被涵蓋跳過。
- **重建走新 branch `pit-rebuild`**（R0/R1 產物在此）；`main`（live config/src）不動到通過總 Gate。R0/R1 純新增模組/notebook，未改 live、未 commit。

---

*建立 2026-06-16｜更新 2026-06-17（R0→R6 完成；裁決：無顯著 alpha、唯 regime 崩盤防禦真但不顯著且不敵 0050 → 被動為主；R6 使用者選被動落地＝0050+MA200 overlay、config 寫+測試綠、待部署/commit）| 性質：standing 真相與紀律。*

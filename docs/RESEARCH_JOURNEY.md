# 研究歷程報告 — 從「手挑籌碼策略」到「被動 0050 + MA200 防線」

> **建立 2026-06-17。** 本檔統整本專案完整研究歷程（Phase 0→11 ＋ PIT 重建 R0→R6），是**一路研究改進過程的單一回顧文件**。
> 細節數字與逐步記錄見：`taiwan_trading_bot_master.md` 第六章、`docs/IMPROVEMENT_PLAN_v2.md`（含附錄 B 污染稽核）、`docs/PIT_REBUILD_PLAN.md`（R0–R6 結果）、`CLAUDE.md`（現況真相）。

---

## TL;DR（一段話）

原始「手挑 35 檔 + 籌碼/TA + ATR 移動停損」主動策略的帳面績效（年化 12.7% / Sharpe 1.16 / DD −16%）**經證實大半來自後見之明污染**（手挑 universe 用未來資訊事後挑贏家）。在**無 look-ahead 的乾淨 PIT 資料**上從零重建（R0→R5）後，**誠實池無可前瞻複製的 alpha**：沒有任何訊號層（TA / 籌碼 / 動量）加得出穩健或統計顯著的超額；唯一真實且 K-穩健的東西是 **regime 的降-回撤（防禦、非 alpha）**，而它在風險對齊比較下**仍不顯著、且打不贏單純持有 0050**。據此**誠實出口＝被動為主**：live 已改為 **0050 vol-target + MA200 overlay（跌破 MA200 留倉 85% / 漲回回滿）**＝R6。舊 active 策略的**直接執行路徑已刪除**，研究過程全數保留並由本報告統整。⚠️ 所有 OOS 數字仍是**上界**（FinMind 無下市資料 → survivorship 無法消除）。**（2026-06-18 後續）** 再對該防禦 overlay 做 **whipsaw 修正**（E1 N 日確認 + E2 緩衝帶），經 walk-forward 驗證後整併入 live（combined N=3 + 1% 帶）：**結構 Gate PASS（降 whipsaw、DD 不惡化、牛市不犧牲）、但 alpha 仍 FAIL（對同 beta 0050 無顯著超額）**＝結構性微調、非 alpha（見 §(f)）。

---

## 0. 系統與方法（背景）

- 台股 paper-trading bot；5 層架構（資料 → 市場分析 → 回測 → 執行 → 監控）。live＝`config/` + `src/`。
- 回測引擎 `src/backtest/capped_sim.py`（`run_capped`，live-aligned：top-N chip-score 進場、vol_target 配重、ATR 移動停損、max_hold 60、T+1）。
- **紀律（全程）**：決策只綁 **walk-forward OOS**（in-sample 只當線索）；對照基準**固定預先指定**＝ 0050 買持 + 基準B（vol_target 0.011，非 best-of-sweep）；引擎改動行為中性 additive；**參數掃描用細網格**（不得 3 點下結論）；**舊污染絕對門檻不可移轉到誠實池**（重錨被動）。

---

## (a) 起點：手挑主動策略 + 其（污染的）帳面績效

- **進場**：TA 四條件 AND（站上向上 MA20、量比≥1.5、RSI 50–80）＋籌碼加分（外資連買 +2 / 投信 +1 / 融資乾淨 +1 / 融券急增 −1，≥2 入選）。
- **選股池**：手挑 35 檔 `LIVE_UNIVERSE = DEFAULT_UNIVERSE(38) − REMOVED_LAGGARDS(7) + AI_ADOPTED(4)`。
- **帳面回測（2018–25 / 100k / 零股 / 6 格）— 已知污染**：年化 **12.7%** / 總報酬 152% / **Sharpe 1.16** / **DD −16%** / PF 1.97 / 222 筆。對照 0050 買持 年化 20% / Sharpe 1.01 / DD −34%。
  - 一句話：**總報酬不到 0050 一半；Sharpe 領先極小且不顯著；唯一硬 edge＝回撤砍半**（2022 熊 −3.2% vs 指數 −22%）。自設 Gate FAIL（DD −16% 破 −15%）。

## (b) 診斷：Phase 6/7/8/9（全在污染的 35 檔池上）

- **Phase 6（並倉 × 出場）**：固定權重加格 6→20 → DD 爆（N≥8 REJECT）；守恆配重壓 DD 但稀釋報酬；A+C 組合 in-sample 4 格過 Gate（最佳 N=15/90/0.15：Sharpe 1.14→1.36、Calmar→1.31、DD→−9.9%）＝**只改善風險面、報酬持平**，#4（大多頭捕獲）未修。
- **Phase 7（出場診斷）**：逐年捕獲 2024 僅 **0.29**＝真正破口；kill-switch 探針顯示**放寬出場讓 2024 更差**（0.29→0.03）→ #4 是**結構性（參與/集中）非出場**。
- **Phase 8（walk-forward）**：擴張窗再優化**從不選到** Phase 6 冠軍（4 窗 3 選回 6 格）；pooled OOS 候選 1.36 **< live 6 格 1.40**；唯一一致 OOS 好處＝DD。**IR vs 基準B ≈ 0** → 預示 Phase 10。Phase 6 候選 OOS **否決**、live 不動。
- **Phase 9（規則化選龍頭 + 去後見之明）**：動量傾斜 in-sample 改善（IR +0.26）但 **walk-forward 失敗**（3/4 窗選 λ0、pooled 1.26<1.40）且 +0.26 IR **完全依賴手挑 35+籌碼鷹架**；純集中（max_pos↓）反傷。

## (c) 關鍵發現：後見之明污染（Phase 9 §2 + 附錄 B）

- **控制臂比較**（全 price-only 動量、+regime、只差 universe）：

  | 臂 | universe | pooled OOS Sharpe | 2024 捕獲 |
  |---|---|---|---|
  | A0 | live 手挑 35 + 籌碼 | 1.40 | 0.29 |
  | A3r | 手挑 59（2026-CAGR 挑） | 0.88 | −0.02 |
  | A4r | **機械 top-60 流動性（PIT）** | **0.50** | 0.09 |
  | A2r | 機械廣池 1566 | −0.13 | −0.29 |
  | 0050 / 基準B | 被動 | 1.01 / 0.80 | 1.0 |

- **同規模手挑溢價 = A3r − A4r = +0.38 pooled OOS Sharpe / +9pp 年化（下界，倖存者未除）。**
- **最佳誠實機械策略（A4r 0.50）打不贏被動。** 機械選龍頭 2024 捕獲 0.09 ≪ live 0.29 → 規則化機械選股**否決**。
- **污染根源**（附錄 B.1）：`AI_ADOPTED`（3017/8299/2449/8210）用 **2023–25 績效分窗**挑出＝**直接 look-ahead**；`REMOVED_LAGGARDS` 按「近 3 年 CAGR 落後」事後剔除；`AI_CANDIDATES` 按「3 年 CAGR ≥ 0050」。
- **污染稽核分級**（附錄 B.2）：Tier A（絕對數字被高估：12.7%/1.16、Phase 6/7/8 全部、旁支）／Tier B（相對「否決」一階穩健但移轉性未驗，最可疑＝Phase 6「加格無益」）／Tier C（以為真其實部分後見：「唯一 edge＝降 DD」含手挑低波灌水）／Tier D（真、保留：regime DD 貢獻、機械臂本身、工程品質）。

## (d) 乾淨 PIT 重建 R0→R5（branch `pit-rebuild`，純快取 0-API，live 全程不動）

- **資料就緒**：四方完整 `price∩inst∩margin∩div = 1706` 檔工作池。⚠️ survivorship 不可消除 → 所有 OOS 皆**上界**。
- **PIT universe 模組** `src/backtest/pit_universe.py`：無 look-ahead（trailing-60d 成交額 top-K + 上市滿 1y + 價格下限 + 季 reselect），membership baked 進 entry、不改引擎。

- **R0 誠實基準**（季 reselect，OOS 2022–25 pooled）：PIT K=50/100/150 → OOS Sharpe **0.93 / 0.56 / 1.21**（非單調＝雜訊、中位 0.93）；基準B 0.80、0050 0.95；全期 Sharpe 0.62–0.75 一致輸被動。**與被動打平、無穩健 alpha，唯 regime 降 DD。** 取代污染的 12.7%/1.16 → 誠實全期約 8–10% / Sharpe 0.62–0.75。
- **R1 細網格 walk-forward**：18 點 K-sweep 鋸齒無高原（1 SE δ=0.51 → K=150 的 1.21＝孤峰）；walk-forward 選 K* **從不選到 150**、pooled 全輸 B、IR 全負＝**K=150 的 1.21 是 in-sample cherry-pick**。加格在誠實池 in-sample 明確改善（附錄 B 方向成立）但 walk-forward **非穩健翻盤**（IR<0＝低-DD/低報酬防禦 profile）。ETF-排除 sanity 坐實。**總 Gate FAIL。**
- **R-attrib 逐層歸因**（L0 等權→+引擎→+TA→+籌碼gate→+籌碼select→+regime→+動量）：**無任一層加 robust OOS alpha**（signal-layer ΔSharpe 皆在 δ≈0.5 內、IR vs B 全程<0）；**唯 regime 層 K-穩健（跨 K 一致 +17~24pp DD 降）＝防禦非 alpha**；**籌碼層 standalone 跨 K 變號、K=100 轉負**（PnL top3 625%）＝master Phase 10#6 疑慮**坐實**；TA/動量＝雜訊。
- **R5 正式裁決（風險對齊 DD 檢定 + 顯著性）**：防禦 sleeve / +chip / 全 edge vs 0050、基準B（摻現金 de-risk 到同 vol；Sharpe/Calmar/DD-vol 皆 scale-invariant）。
  - **無顯著 alpha**：IR vs B −0.28~−0.38 全負、block-bootstrap 95% CI **全含 0**、α vs 0050（Newey-West）t = 0.00/0.56/0.48。
  - regime 降-DD **真但不顯著**（同 vol 下 maxDD 比基準B 淺 +3.6~+6.9pp、2022 熊抗跌明顯較好）＝**非純恆等式**；**但對原始 0050 全輸**（0050 OOS Sharpe 0.94/Calmar 0.59/年化 20% vs 主動 8–9%）、不顯著、報酬代價大 → **不構成 mandate**。
  - **裁決：被動為主（誠實出口）。** R2/R3/R4 已被涵蓋跳過（動量＝雜訊、出場非問題、選擇不穩已答）。

## (e) 落地：被動 R6（0050 + MA200 防線；最終留倉 85%）

- 使用者選**被動為主**、口味＝**vol-target + MA200 overlay**（平時跟 0050、跌破 MA200 退、漲回再跟）。
- **零 code 改動上線機制**：live 早有 active/benchmark 模式開關（`config/settings.yaml strategy.mode`）→ flip 即可。
- **退場深度細網格掃描**（0~100% 留倉，5% 步長；`r6_retreat_finegrid.py`）：單調 trade-off（留倉↑→報酬↑、2022 保護↓、2018 whipsaw↓）；全期 maxDD U 形（兩端最差、中段最淺）→ **避免全退(whipsaw 自傷)與全不退(無保護)兩極**；**明示為風險偏好旋鈕、非挑 sample 峰值**。
- **最終 live 定稿（留倉 85%）**：`settings.yaml` benchmark＝0050 / `target_daily_vol 1.0`（停 vol-cap＝base 100% 跟 0050）/ `regime_overlay true` / `regime_ma 200` / **`regime_action 0.85`**（跌破 MA200 留 85% 曝險、漲回回滿）。引擎 `regime_action` additive 支援數值（zero/half 不變）。
- **誠實定位**：**結構性降回撤規則、非經證實 outperformer**（R5 無顯著 alpha；overlay 前瞻＝降深熊 DD、但 MA 附近 whipsaw、牛市≈跟 0050；分年回測「贏 0050」是 2022 期間特性 + 雜訊，**不外推**）。

---

## (f) E1+E2 whipsaw 修正研究 + 整併落地（2026-06-18）

承 R6 落地後的事件研究：2020(−27%)/2022(−31%) 回撤事件歸因（`docs/DRAWDOWN_EVENT_STUDY_2020_2022.md`）發現 MA200 daily 規則兩盲區＝**初跌無保護（滯後）+ whipsaw（2022 在 3.5 週 7 次穿越）**；事件偵測研究（`docs/EVENT_DETECTION_RESEARCH.md`）裁決新聞面**不可回測**（FinMind 新聞僅 2020-04 起＝1 熊市週期）→ 先做純快取的 whipsaw 修正。

- **沙盒 E1-E3（in-sample 細網格，`docs/E1_E3_COMPARISON.md`；3 沙盒 agent 各建一支新 notebook）**：E1 N 日連續確認 / E2 對稱緩衝帶 / E3 ATR 帶。三者 OOS Sharpe 皆**平滑高原**（全距 ≪ δ=0.51＝無 cherry-pick、亦無 alpha）；**whipsaw 削減是唯一單調效果（2022 flips 7→1）**。排名 E1>E2>E3（E3 高 K 反噬、暫緩）。
- **正式 walk-forward（`docs/E1_E2_WALKFORWARD.md`、`notebooks/e1e2_walkforward.py`）**：擴張窗 [2018,Y-1]→Y、DD floor 重錨同族 current-live。**結構 Gate PASS（跨 4 fold OOS：DD 不惡化且優於基準B/0050、whipsaw↓、牛市不犧牲）；alpha Gate FAIL。** ⚠️ **方法論修正**：「IRvs基準B +1.13」是 **beta 非 alpha**（基準B de-risked；**0050 自身 IRvsB=+1.00** 為證）→ 真 alpha 檢定＝同 beta 的 **IRvs0050 = −0.18/−0.27（無）**。選參「測不準」（E1 跨 fold 跳動、E2 rail to grid edge）＝平滑高原徵兆＝任何小 N/帶 ≈ 等價、效益與選參無關。
- **整併落地（`notebooks/e1e2_combined_validate.py`；使用者拍板 combined N=3 + band=1.0%）**：把 R6 overlay 的 below 判定由「每日 MA200」改為「**連 3 日跌破 MA200×0.99 才砍至 85%、連 3 日站回 ×1.01 才回滿**」。落地＝`config/settings.yaml` 新增 `regime_confirm_days: 3`/`regime_band_pct: 0.01`；引擎 `benchmark_engine.py` 新增 `_regime_below` 狀態機 + `vol_target_exposure(regime_confirm_days=1, regime_band_pct=0.0)` **additive（預設＝舊行為、行為中性、98 原測不變）**。效果（2018-25 純快取、survivorship 上界）：**2022 假穿越 7→1、最差前進年 DD −31.2→−30.5%、交易 126→105、2018/2022 報酬+Sharpe 皆優於舊規則、2020 V 急崩無 over-lag**。3 個獨立 agent 驗證全過（行為中性 max|Δ|=0、新 config ≡ 沙盒數字 17/17、對抗 review 無 look-ahead）；`pytest` **105 passed**（98+7）。
- **誠實定位**：**現行防禦 overlay 的結構性降 whipsaw 微調、非 alpha**（R5 未翻案、0050 買持全期報酬仍王）；rollback＝config 兩鍵回 1/0.0（復舊每日 MA200 規則）。

---

## (g) 事件偵測延伸研究：E4/E5/E7/E7b 全 FAILED、E8 僅規劃（2026-06-18，純沙盒未碰 live）

承 §(f) E1+E2 落地後，沿 `docs/EVENT_DETECTION_RESEARCH.md` roadmap 把「比 MA200 更早/更準的崩盤偵測」逐一試到底——**全部 FAILED，live 一律不動**。每條皆多 agent 沙盒（plan→build→對抗驗證→synthesis）、純快取 0-API、walk-forward OOS（FWD=[2022-25]、唯 2022 OOS 崩盤）、**beta/alpha 嚴格分離**（IRvs基準B 是 beta、0050 自身=+1.00；真 alpha=IRvs0050）、survivorship 上界。

| 研究線 | 內容 | 裁決 | 為何失敗（一句話） |
|---|---|---|---|
| **E4** | 第二道防線（5d vol-spike OR from-peak 速度，提前出 15%）| 🟥 FAILED | 牛市假觸發多（累計 −8.8pp vs 0050）、whipsaw↑、alpha FAIL |
| **E5** | 組合閘（E4 + 外資連續淨賣，≥2 訊號才動）| 🟥 FAILED | 組合閘確壓牛市假觸發(唯一 PASS 子項)但仍不降 DD、增 whipsaw、外資票無貢獻、alpha FAIL |
| **us_lead_0050** | 美股 ^SOX/SMH/TSM ADR 對 0050 領先性（FinMind `USStockPrice`）| 🔬 領先**真實**(corr 0.55、Granger 單向 p≈1e-115、跨期穩定) | 但 **~99% 在 0050 開盤跳空被吸收、盤中≈隨機 → 不可萃取** |
| **E7** | 美股半導體當「砍倉**時點**」訊號 | 🟥 FAILED | 賣在跳空後 + 86% 平時假警報反傷；連結構 Gate 都沒過 |
| **E7b** | 美股半導體「確認延續→砍倉**深度**」（非時點）| 🟥 FAILED | 修好假警報，但 matched-D 對照證 US-conditioning 不如「無條件砍更深」(flat-deep)、且引入深度 whipsaw |
| **E8** | 新聞情緒 ex-post 研究 | 📋 僅規劃(`docs/E8_PLAN.md`)、**未執行** | 2020 急崩在 FinMind 新聞窗(2020-04)前、唯 2022 OOS 崩盤(n=1)→結構上不可 walk-forward、永不碰 live |

- **共同教訓**：所有「更早/更準崩盤訊號」方向，要嘛在開盤跳空被吸收（美股線）、要嘛假觸發成本 > 防禦效益（E4/E5/E7）、要嘛資料不足以驗證（E8）。**無一翻案 R5「無 alpha、0050 報酬王、regime 僅防禦」。**
- **負結果中唯一可用線索**：若有明確 drawdown mandate，降 DD 的槓桿＝**flat-deep（直接把 `regime_action` 砍更深，如 0.70/0.60）**——但那是沿 R6 已知前緣的**風險偏好抉擇、非 alpha、非研究新發現**（R6 已掃過並選 0.85；E7b 的 matched-D 對照證實它支配 US-conditioning）。
- **🟩 live 分隔線**：自 §(f) **E1+E2** 起，live（0050 + MA200 連3日+1%帶-85% overlay）**未再有任何改動**；E4–E8 全為**沙盒研究歸檔、零 live/engine/config 變更**。

---

## 倉庫清理紀錄（2026-06-17）

- **刪除（舊 active 直接執行路徑）**：`src/signals/score_engine.py`、`src/signals/chip_signal.py`、`src/strategy_engines/active_engine.py`；`main.py` 的 active 任務（pre_market / market_open / intraday_monitor / _emergency_liquidate / afterhours_fill / _within_session / _save·_load_day_state）＋ active 全域 ＋ active 排程分支；`make_engine`/`__init__` 去 ActiveEngine（benchmark-only fail-safe）。
- **保留（研究/共用，經反向相依驗證不可刪）**：`src/signals/tech_signal.py`、`src/signals/capitulation.py`（research 回測引擎 signal_builder/capped_sim 依賴）；`src/backtest/*`（capped_sim/signal_builder/pit_universe）；shared infra（broker/order/risk/fetcher/notify/utils）；`config/strategy.yaml`（research 回測讀取，保留未剪裁、僅重述定位）。
- **驗證**：`pytest` 全綠（98）；`main.py` 重構為 benchmark-only（ast 通過、無 active 殘留參照）。

## 研究檔案清單（保留）

- **文件**：`taiwan_trading_bot_master.md`（第六章 Phase 1–11 史 + 6.9 否決清單）、`docs/IMPROVEMENT_PLAN_v2.md`（+ 附錄 B 污染稽核）、`docs/PIT_REBUILD_PLAN.md`（R0–R6 結果）、`CLAUDE.md`（現況真相 + 鐵則）。
- **PIT 重建 notebooks**：`r0_data_audit.py`、`r0_honest_baseline.py`、`r1_walkforward.py`、`r_attribution.py`、`r5_alpha_verdict.py`、`r6_overlay_select.py`、`r6_retreat_sweep.py`、`r6_final_backtest.py`、`r6_bh_half_backtest.py`、`r6_retreat_finegrid.py`、`benchmark_backtest.py`。
- **Phase 6–9 notebooks**：`p6_maxpos_sweep.py`、`p6_exit_linkage.py`、`p7_exit_diag.py`、`p8_walkforward.py`、`p9_concentration.py`、`p9_walkforward.py`、`p9_pit_universe.py`。
- **早期/旁支/universe-construction/probe notebooks**：見 `notebooks/`（Phase 0–5 建置、a1/a2/exit/sizing/capitulation 旁支、universe 建構＝污染源證據 universe_ai_window 等、API/timing probe）。
- **whipsaw 修正 / 事件研究（2026-06-18，§(f)）**：文件 `docs/DRAWDOWN_EVENT_STUDY_2020_2022.md`、`docs/EVENT_DETECTION_RESEARCH.md`、`docs/E1_E3_COMPARISON.md`、`docs/E1_E2_WALKFORWARD.md`；notebooks `dca_compare.py`、`dump_drawdown_detail.py`、`e1_nday_confirm.py`、`e2_hysteresis_band.py`、`e3_atr_band.py`、`e1e2_walkforward.py`、`e1e2_combined_validate.py`（純快取；輸出 CSV 在 gitignore 的 `data/processed/`，由 notebook 重生）。
- **事件偵測延伸研究（2026-06-18，§(g)；全 FAILED/僅規劃、純沙盒未碰 live）**：文件 `docs/E4_E5_COMPARISON.md`、`docs/E7_US_SEMI_DEFENSE.md`、`docs/E7B_DEPTH_MODULATION.md`、`docs/E8_PLAN.md`；notebooks `e4_second_line.py`、`e5_combination_gate.py`、`us_lead_0050.py`、`e7_us_semi_defense.py`、`e7b_depth_modulation.py`（純快取；美股經 FinMind `USStockPrice` 下載至 gitignore 的 `data/raw/finmind_cache/USStockPrice__*.pkl`，由 notebook 重生）。
- **持久化**：`data/processed/`（r0_cache_audit.json、r1_base_sig.pkl、r_attrib_base.pkl；gitignore 的 cache）。

## 殘留風險與誠實聲明

- **survivorship**：FinMind 無下市/歷史成分 → 廣池＝存活池 → 所有 OOS 仍是**上界**，真實更低。
- **單一市場/單期**：統計 power 有限；R6 overlay 的「贏 0050」是期間相依，非穩定超額。
- **核心**：乾淨真相是「主動打不贏被動」——**接受它**＝整個 v2 後見之明稽核換來的誠實答案。

# 事件驅動崩盤偵測 + Whipsaw 解方研究

> **產生方式**：多 agent workflow（`event-driven-detection-research`；5 agents＝4 並行研究[whipsaw 解方／崩盤訊號／新聞資源／DIY 爬蟲]＋1 綜整 roadmap），WebSearch 查證、附來源。
> **觸發脈絡**：承 `docs/DRAWDOWN_EVENT_STUDY_2020_2022.md`——發現 MA200 有「初跌無保護＋whipsaw」兩盲區，故研究解方。
> **harness 事實已對 repo 核對（2026-06-17，主控驗證屬實）**：`vol_target_exposure` 支援數值 regime_action；0050 快取含 high/low（ATR 可算）；0050 三大法人籌碼已快取；`benchmark_backtest.py:204` 的「12.7%/1.16」為污染數字、不可當 Gate。
> **性質**：研究假說輸入、非 live 依據。所有實驗須先過下方 Roadmap §5 walk-forward OOS Gate（呼應 R5/CLAUDE.md）；通過前 live（MA200 + regime_action 0.85）不動；結果皆 survivorship 上界。
> **關鍵裁決**：新聞事件偵測方向在現有資料下**無法 walk-forward 回測**（FinMind 新聞僅 2020-04 起＝1 個熊市週期）→ 依紀律不可碰 live，僅可做 ex-post 純研究。

> ⚠️ 訊號 lead-time（如 vol-spike 早 11–14 天）為 agent 由時間軸推估、**尚未回測**，須經 E1/E4 walk-forward 驗證後才算數。

---

# 0050 + MA200 Overlay 強化研究：可執行 Roadmap

> 綜整四份平行研究（whipsaw 解方／崩盤訊號／新聞資源／DIY 爬蟲），對齊 CLAUDE.md 鐵則與現有 harness 實況。
> **已驗證 harness 事實**（非報告轉述）：`benchmark_engine.py:vol_target_exposure()` 已支援數值 `regime_action`；`benchmark_backtest.py` 載入的 0050 還原日線**含 high/low 欄位**（ATR 可算、零新數據）；0050 三大法人籌碼**已快取**（`TaiwanStockInstitutionalInvestorsBuySell__0050__2018-01-01__2025-12-31.pkl`，**修正研究報告 2「需驗快取」的保留**）；walk-forward OOS = FWD `[2022,2023,2024,2025]`，**基準B = `simulate_benchmark(adj, 0.011)`（vol0.011 無 overlay，預先指定，非 best-of-sweep）**，0050 買持為報酬王。

---

## 0. 一句話總結（先看這個）

- **whipsaw 修正**：值得做，且**全在現有 harness 一個函數內、純快取**。先試 **N=3 日確認 + 對稱緩衝帶**（最有量化證據、改動最小），ATR 動態帶次之。
- **更快崩盤訊號**：技術/市場面（vol-spike、from-peak 速度、外資淨賣）**全可純快取回測**，優先；新聞面**不優先**（見下）。
- **新聞事件偵測**：**裁決＝現在不做 live、先做純研究 ex-post**。生死問題（歷史可回測性）的答案是 **FinMind 新聞只到 2020-04＝僅 1 個熊市週期，統計功效不足以過本專案 walk-forward Gate**。依紀律：**不可回測＝live 不能動**。
- **誠實框架**：所有新訊號一律先過下文 **§5 的明確 Gate**；通過前 live 維持現行 0050 + MA200-85%。**所有結果仍是 survivorship 上界**（FinMind 無下市）。

---

## 1. Whipsaw 立即可試的修正（排序）

### 背景診斷（四報告共識）
現行規則兩個結構盲區：**(a) 初跌無保護**（MA200 滯後，2020 跌 −14% 才觸發、2022 −11%）、**(b) whipsaw**（2022 在 3.5 週內 7 次穿越）。核心取捨是**對立**的：減慢訊號→惡化 2020 急崩保護；加快訊號→惡化 2022 whipsaw。**沒有免費午餐**——但有「近乎免費」的甜蜜點。

### 🥇 優先 1：N 日連續確認（Consecutive-Close Confirmation）

| 項目 | 內容 |
|---|---|
| **機制** | 出場：`(close < MA200)` 連續 N 日皆成立才砍到 85%；回補：連續 N 日站回才回滿。可非對稱（出場 N_exit、回補 N_reentry 不同天數）。 |
| **為何排第一** | **唯一有直接量化證據**（Alvarez SPY/QQQ 2000–2023）：N=2~3 讓交易次數減半、MDD 改善、CAR 幾乎不變＝「no degradation」。對 2022「跌破→次日站回」型假穿越直接消除。 |
| **降 whipsaw vs 保牛市取捨** | N≤3 對牛市參與**影響極小**（平均延遲 N/2 天）；**代價在 2020 急崩多承受 N 天下跌**（N=3 約 −6~8%）——這正是要在 walk-forward 量化的東西。 |
| **harness 改動** | `vol_target_exposure()` 內 `below = close < ma` → `below = (close < ma).rolling(N, min_periods=N).min().astype(bool)`。**純向量、與現有 `exp.where(~below, ...)` 完全相容**。 |
| **純快取回測** | ✅ 是（只需 0050 收盤，已快取） |
| **細網格** | N ∈ {1,2,3,4,5,7,10}（≥7 點，符合鐵則#7）× 對稱/非對稱 |

### 🥈 優先 2：對稱緩衝帶 / Hysteresis Band

| 項目 | 內容 |
|---|---|
| **機制** | 出場 `close < MA200×(1−α)`、回補 `close > MA200×(1+β)`，中間死區不動作。需一個布林狀態變數記「目前是否處於減碼態」。 |
| **為何排第二** | 機制正交於 N 日確認（**距離型** vs **時間型**），可單獨比也可疊加。文獻（StockCharts Arthur Hill）SMA Envelope(1%) 大幅減訊號、Sharpe 改善。 |
| **降 whipsaw vs 保牛市取捨** | 強抑 whipsaw；牛市代價小（β=1%≈台股 0050 一個交易日的移動）；**初跌保護略差**（α 讓觸發更晚）。 |
| **harness 改動** | 同函數加 `band_pct` 參數 + 狀態機（現有 `benchmark_backtest.py` 已有 per-day for loop，加狀態追蹤容易）。 |
| **純快取回測** | ✅ 是 |
| **細網格** | α=β ∈ {0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 3.5}%（12 點，符合鐵則#7） |

### 🥉 優先 3：ATR 動態帶（Volatility-Scaled Band）

| 項目 | 內容 |
|---|---|
| **機制** | 帶寬 = `K×ATR(22)` 而非固定%。高波動期（崩盤）自動擴帶抑雜訊、平靜牛市收帶快回補。 |
| **為何排第三** | 概念優於固定帶（自適應），但實作較複雜、無前兩者那麼直接的量化證據。**重要**：0050 快取**有 high/low → 真 ATR 可算、零新數據**。 |
| **取捨** | 比固定帶對牛市更友善；崩盤初期 ATR 剛膨脹、帶還沒全開＝初跌保護略差於固定帶。 |
| **純快取回測** | ✅ 是（ATR 用已快取 high/low/close） |
| **細網格** | K ∈ {0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0} × ATR(22) |

### ⏸ 暫不優先（理由明確）

- **月評估（technique 4）**：2020 急崩**完全無保護**（月底才看一次、此時已跌 ~30%）。台股多急崩史→不可接受。
- **雙均線/MA 斜率（technique 5）**：lag 最長（死叉可達 1–3 月），2020 急崩 1 月就結束、保護幾乎為零。
- **非對稱「出場快回補慢」（technique 3）**：對 2022 慢熊最強，但對 2020 V 反彈牛市參與代價最大、需狀態機。**列為前三項回測後的後補加強**——若 walk-forward 顯示 2022 型 whipsaw 殘留再引入。

### Whipsaw 取捨速覽

| 修正 | 降 whipsaw | 保牛市代價 | 初跌保護 | harness 難度 | 純快取 |
|---|---|---|---|---|---|
| **N=3 確認** | 強（短穿越） | 極小 | 差（多等 N 天） | **最易（改一行）** | ✅ |
| **固定帶 1%** | 強 | 小 | 略差 | 易（加狀態機） | ✅ |
| **ATR 動態帶** | 強+自適應 | 比固定帶小 | 略差 | 中 | ✅ |
| 非對稱回補 | 最強 | 最大（V反彈） | 不影響出場 | 中 | ✅ |
| 月評估 | 極強 | 中 | **最差** | 最易 | ✅ |

> ⚠️ **重要陷阱（鐵則#7/#8）**：現有 `benchmark_backtest.py` 把「現行 active 12.7%/1.16」寫死當對照（line 204）——**那是污染數字、不可當 Gate**。新掃描一律對照**基準B（vol0.011 無 overlay）+ 0050 買持**，且**不得用 in-sample 峰值挑 N/α/K**（那把 OOS 變 cherry-pick）。

---

## 2. 是否加入更快的 event-driven 崩盤訊號

**核心命題（四報告共識）**：MA200 不是壞掉，而是**設計用途是中期趨勢、本就非崩盤偵測器**。要更快只能引入「速度型/前導型」訊號——但 2020（急崩 V 型）與 2022（慢熊假彈）是對立壓力測試，**任何快訊號都會在 2022 反彈中多次假觸發**。

### 技術/市場面 vs 新聞面：lead-time 與假訊號成本

| 訊號 | 對 2020 lead | 對 2022 行為 | 假訊號成本（出15%代價） | 純快取可回測 | 需新數據 |
|---|---|---|---|---|---|
| **5d 已實現 vol spike**（>1.5× 60d 均） | **早 11–14 天** | 溫和、無明確提前 | 中（每年 2–4 次假警報，~0.2pp/次） | ✅ 0050 收盤 | 否 |
| **from-peak 速度停損**（−X% in N 天） | **早 8–10 天** | 慢熊觸發晚、反覆 | 中（大回撤必發） | ✅ 0050 收盤 | 否 |
| **MA20 短均線** | 早 6–9 天 | **whipsaw 暴增** | 高 | ✅ | 否 |
| **外資連續淨賣超**（FinMind） | 早 7–10 天 | 早 6 週+ | 中（季節性再平衡雜訊） | ✅ **0050 籌碼已快取** | 否 |
| **費半 SOX 跌破 MA50** | **早 13–15 天** | 早 6–8 週、慢熊較穩 | 中低 | ❌ | **需外部 SOX** |
| **VIXTWN（台指選擇權隱波）** | 早 2–5 天 | — | 中 | ❌ | **需 MacroMicro/TAIFEX CSV** |
| **多訊號組合閘（2+ 同時）** | — | — | **低**（假陽性 35%→~10%，文獻） | ✅（用前三純快取項） | 否 |
| **新聞情緒/事件** | 理論同步~領先 | — | 中-高（假陽性高、T+1 才更新） | ❌（見 §3） | 需爬取+NLP |

### 建議優先序

1. **最優先（純快取、針對 2020 盲區）**：在 MA200 之上**疊加第二道防線**（不改現有 MA200 行為）——「5d vol-spike **或** from-peak −X% in N 天」→ 提前出 15%。這是研究報告 2 的**方案 B 雙層確認**，能補 2020 的 −14% 盲區，且 2022 額外假觸發可控（出 15% 輕量設計讓代價有限）。
2. **次優先（純快取，已修正可得性）**：**外資連續淨賣超**作為組合閘的一員（0050 籌碼已快取）。注意 R-attrib 已證**籌碼層 standalone 跨 K 變號＝不穩**，故只當「組合確認」一票、不單獨用。
3. **暫緩（需新數據、且需先過資料引入成本評估）**：**SOX**（對台股 2020 領先 13–15 天最強，但需建外部數據管線、脫離純快取體系）；**VIXTWN**（最值得的外部數據，但同需新 pipeline）。**僅在 §1+上述純快取項回測後仍顯不足時才投入**。
4. **不優先**：新聞面（見 §3 裁決）。

> **設計紀律**：出 15% 是**刻意輕量**（牛長熊短時仍跟到牛市），四報告一致認為**不該為了加訊號而激進加大出倉比例**。任何「第二道防線」總出倉建議仍 ≤ 30%。

---

## 3. 新聞事件偵測：買/用 vs 自建 — 明確裁決

### 🔴 生死問題：歷史新聞可回測性 → **答案是「不可行」（在本專案紀律下）**

這是決定性判準。報告 3、4 交叉確認的歷史深度：

| 來源 | 歷史深度 | walk-forward OOS 可行性 |
|---|---|---|
| **FinMind TaiwanStockNews** | **僅 2020-04 起** | ❌ 部分：覆蓋 2020+2022，**僅 1 個完整熊市週期、統計功效不足** |
| 鉅亨 Cnyes API（非官方） | **近 2 年滾動** | ❌ 無法固定 in-sample/OOS 邊界 |
| MOPS 重大訊息 | 技術上有歷史 | ❌ **TWSE 主機積極封鎖自動爬取**（已有確認失敗案例） |
| Google News RSS | 僅近 ~100 篇 | ❌ 完全不可行 + ToS 違規 |
| 聯合知識庫（付費） | 2000 年代起 | ⚠️ 唯一完整歷史，但需商業授權、超出專案規模 |

> **裁決依據 CLAUDE.md 鐵則#2/#5**：訊號若無法做滿足紀律的 walk-forward OOS → **不能碰 live**。新聞訊號最遠只到 2020-04，無法對 2008/2015/2018 崩盤做 OOS，**無法通過本專案 Gate**。

### 買/用 vs 自建 — 三層裁決

| 選項 | 裁決 | 理由 |
|---|---|---|
| **買商業 API**（RavenPack/LSEG/Bloomberg） | ❌ **否決** | 台灣本地中文媒體覆蓋不透明 + $20k–$200k+/年，個人/小型策略不可行。 |
| **買台股專業**（TEJ，有現成情緒分數+2018 起） | ⚠️ **理論最佳但個人不可購** | 機構/學術定價，個人無方案。**唯一能繞過歷史深度問題的路**，但門檻高。 |
| **自建**（FinMind + Cnyes + 中文 FinBERT / Claude Haiku 分類） | ⚠️ **技術可行（1–2 週 MVP、~$10/年 LLM 成本）但回測不可行** | 技術門檻低、成本近零；**但卡在歷史深度死穴**。 |

### ✅ 明確建議路徑（分階段，不碰 live）

1. **現在**：**不接 live、不投入爬蟲管線**。維持現行 overlay。
2. **若要探索新聞**：先用 FinMind TaiwanStockNews 批次下載 2020–2026 全量標題（注意：每請求僅 1 天、需 ~2000 次、約 3–7 天批次，**走背景配額、不擾 live**），做**純 ex-post 研究**——檢驗新聞情緒與後續 5–10 日報酬的相關性 / Granger 因果，**完全不接進 bot**。
3. **唯有 ex-post 顯著**，才討論是否值得採購聯合知識庫（完整歷史）做真 walk-forward，或接受「短 OOS 窗口 + 額外不確定性」。
4. **MOPS 重大訊息**：僅可作 live **即時警報**（崩盤發生後的確認，如「財務危機/交易停止」關鍵詞），**不可作預測訊號**（且受 TWSE 封鎖風險）。

> **一句話**：新聞事件偵測**目前不存在個人可負擔且可回測的方案**——這是真實缺口。依紀律，**先 ex-post 研究、永不在通過 Gate 前接 live**。

---

## 4. 優先實驗清單

> 排序＝（純快取可行 + 改動小 + 證據強）優先。每項標明：純快取？／需新數據？／要過什麼 Gate 才能碰 live。

| # | 實驗 | 純快取回測 | 需新數據 | harness 改動 | 要過的 Gate（碰 live 前） |
|---|---|---|---|---|---|
| **E1** | **N 日確認**（N∈{1,2,3,4,5,7,10}，對稱+非對稱） | ✅ | 否 | `vol_target_exposure` 改一行 + 新 sweep notebook（複用 `r6_retreat_finegrid.py` 骨架） | **§5 Gate** |
| **E2** | **對稱緩衝帶**（α=β 12 點 0–3.5%） | ✅ | 否 | 同函數加 `band_pct` + 狀態機 | **§5 Gate** |
| **E3** | **ATR 動態帶**（K×ATR(22)，K 8 點） | ✅（high/low 已快取） | 否 | 加 ATR 計算 + 狀態機 | **§5 Gate** |
| **E4** | **第二道防線：vol-spike OR from-peak 速度**（提前出 15%，不改 MA200 本體） | ✅ | 否 | 新增「早期出場」疊加層 | **§5 Gate**（且須證 2022 額外假觸發代價可控） |
| **E5** | **組合閘**（E4 + 外資連續淨賣超，2+ 同時才動） | ✅（0050 籌碼已快取） | 否 | 加籌碼訊號當組合票 | **§5 Gate**（注意 R-attrib 證籌碼 standalone 不穩→僅當組合確認） |
| **E6** | **非對稱回補**（出場快 / 回補需 MA 斜率向上或創新高） | ✅ | 否 | 狀態機（回補加條件） | **§5 Gate**（僅在 E1–E3 後 2022 whipsaw 殘留才做） |
| **E7** | **SOX / VIXTWN 前導訊號** | ❌ | **是（外部 pipeline）** | 建新數據擷取 | 先過「資料引入值得性」評估，再 §5 Gate |
| **E8** | **新聞 ex-post 研究**（情緒 vs 前向報酬相關性） | ❌（背景下載 2020+） | 是（FinMind 新聞批次） | 獨立研究腳本 | **不接 live**；先看 ex-post 是否顯著 |

**建議執行順序**：E1 → E2 →（E1/E2 結果定型後）E3、E4 →（殘留問題才）E5/E6 → E7/E8 為長線選項。

---

## 5. 誠實框架：Gate 定義（呼應 R5 / CLAUDE.md，live 通過前不動）

任何 §4 實驗要碰 live，**必須全部滿足**（移植 R1 的 Gate 結構、按誠實池重錨，鐵則#8）：

### Gate 條件（全 AND）

1. **對照固定預先指定**：基準B = `simulate_benchmark(adj, 0.011)`（vol0.011 無 overlay）+ 0050 買持。**不浮動選 best-of-sweep、不引用污染的 12.7%/1.16。**
2. **walk-forward OOS**：FWD = `[2022,2023,2024,2025]`，pooled OOS 為主裁；in-sample 只當線索。
3. **降-DD 主訴求需單獨成立**（此 overlay 的真 edge，R5 已證「regime 防禦真但不顯著」）：
   - 同 vol 對齊下，walk-forward 最差前進年 DD **優於基準B/0050**（R5：sleeve 2022 −14.5% vs B@vol −29.5%）；
   - 對 **whipsaw 修正（E1–E3）**：須證**不惡化** OOS DD 優勢、且**降低換手/whipsaw 損耗**（2022/2018 段穿越次數與成本）、**不顯著犧牲牛市報酬**（2023–25 段 vs 純 0050 的報酬差在可接受帶內）。
4. **plateau-band 穩定（鐵則#7）**：細網格 OOS 須呈**平滑高原**而非鋸齒孤峰（用 1 SE 的 δ 帶判隸屬）；參數最優若是「三選一孤峰」＝雜訊、不採信（R0 K=150 的教訓）。
5. **若主打報酬/Sharpe alpha**（E4/E5 想證提前出場帶來超額）：須 **IR vs 基準B > 0** 且 bootstrap CI 不含 0、α t 顯著（R5 標準）——**但預期大概率 FAIL**（R0–R5 已證誠實池無穩健前瞻 alpha；此 overlay 定位是**結構性降回撤規則、非 outperformer**）。

### 鐵律提醒（每個實驗都套）

- **回測純快取、0 API**（背景 builder 在跑、共用 FinMind 配額）；引擎改動須**行為中性 additive**（新參數預設＝舊行為，過中性檢查 + `pytest`）。
- **舊 Phase 6/7/8 絕對門檻不可移轉**（那些 DD floor 按污染手挑池校準）；誠實/被動池一律**重錨到基準B/0050 的相對比較**。
- **survivorship 無法消除**（FinMind 無下市）→ 所有結果是**上界**，結論須帶此 caveat。
- **通過總 Gate 前，live 配置（`config/settings.yaml`：MA200 + regime_action 0.85）一律不動**。
- **不自動 push、commit 僅在使用者明說時**；commit 排除 runtime 產物。

---

## 相關檔案（絕對路徑）

- 引擎（whipsaw 修正落點，改 `vol_target_exposure`）：`/Users/cch_0182/trading-bot/src/strategy_engines/benchmark_engine.py`（line 50–84）
- 回測 harness（掃描骨架、含 high/low 載入 + 月度/偏離再平衡迴圈）：`/Users/cch_0182/trading-bot/notebooks/benchmark_backtest.py`
- 細網格 sweep 範本（複用於 E1–E3）：`/Users/cch_0182/trading-bot/notebooks/r6_retreat_finegrid.py`
- walk-forward / 基準B / OOS 範本（複用於 Gate）：`/Users/cch_0182/trading-bot/notebooks/r1_walkforward.py`（基準B 定義在 line 275、FWD 在 line 68）
- live 配置（Gate 通過前不動）：`/Users/cch_0182/trading-bot/config/settings.yaml`（`strategy.benchmark`）
- 0050 籌碼快取（E5 用，已存在）：`/Users/cch_0182/trading-bot/data/raw/finmind_cache/TaiwanStockInstitutionalInvestorsBuySell__0050__2018-01-01__2025-12-31.pkl`
- 研究紀律與真相：`/Users/cch_0182/trading-bot/CLAUDE.md`、`/Users/cch_0182/trading-bot/docs/PIT_REBUILD_PLAN.md`、`/Users/cch_0182/trading-bot/docs/RESEARCH_JOURNEY.md`

---

# 附錄 A：Whipsaw 抑制技術（完整研究）

# Whipsaw 抑制技術研究報告：0050 + MA200 Overlay 的具體解方

## 一、問題重述與現況診斷

現行規則（daily close vs MA200，跌破→85%，站回→100%）有兩個結構性盲區：

| 問題 | 根因 | 2020 實測 | 2022 實測 |
|---|---|---|---|
| **初跌無保護** | MA200 反應滯後＝均線離價距離 | −14% 才觸發（3/12） | −11% 才觸發（3/7） |
| **whipsaw** | 每日判斷+單一門檻＝震盪期反覆穿越 | 3 次穿越，~2.1pp 損耗 | 3.5 週內 7 次穿越，~0.77pp 損耗 |

核心矛盾：**出場快（減少初跌保護盲區）** vs **訊號穩（減少 whipsaw）** 是天然對立的；以下六個方向各有不同的取捨角度。

---

## 二、六個候選技術的詳細評估

---

### 技術 1：緩衝帶 / Hysteresis Band（非對稱門檻）

#### 機制
不使用「同一條 MA200」作為雙向觸發，而是設定：
- **出場門檻**：`close < MA200 × (1 − α)`，例如 α=1%→跌至 MA200 下方 1% 才減碼
- **回補門檻**：`close > MA200 × (1 + β)`，例如 β=1%→站回 MA200 上方 1% 才補回

這創造一個「死區」——價格在 MA200 ± 1% 之間震盪時不觸發任何訊號。

#### 取捨效果
| 面向 | 效果 |
|---|---|
| **whipsaw 抑制** | 強。穿越需消耗額外距離，MA200 附近的短暫上下穿越直接過濾。文獻（StockCharts Arthur Hill 測試）：SMA Envelope (200, 1%) 與 Keltner Channel (200,1,22) 大幅減少訊號次數，Sharpe 改善，最佳結果Bollinger Band(200,1) 達13個訊號 vs 未過濾的數十個。 |
| **牛市參與** | 略有損失。β=1% 代表回補時多等 1%，如果是 V 型快速反彈（如 2020），可能比原版晚 2–4 個交易日補回。台股 0050 典型日波動約 0.9–1.2%，1% band ≈ 1 個交易日的移動。 |
| **初跌保護** | 比原版更差。α=1% 代表觸發更晚，初跌盲區從 −11~−14% 擴大到 −12~−15%。**此方向的取捨是：犧牲保護速度換訊號品質。** |

#### Harness 可回測性
**可直接回測（純快取）**。修改 `benchmark_engine.py` 的 `vol_target_exposure()` 函數：目前 `below = close < ma` 改為 `below = close < ma * (1 - alpha)`，新增 `above = close > ma * (1 + beta)` 作為解除條件（狀態機）。`benchmark_backtest.py` 掃 α, β 網格即可。主要工程量：加一個布林狀態變數記錄「當前是否處於 reduced-exposure 狀態」。

---

### 技術 2：時間確認（Consecutive-Close Confirmation Lag）

#### 機制
原版：close 跌破 MA200 **當日**觸發。改為：**連續 N 個交易日**的收盤皆在 MA200 同側，才觸發動作。

最嚴謹的實驗來源：Alvarez Quant Trading 對 SPY/QQQ 的 MA200 + N-day 確認測試（N=1~10），結論：

- **N=2~3**：交易次數減少約 50%，CAR 損失僅 0.1~0.2 pp，MDD 顯著改善。**「No degradation in original statistics」——幾乎免費的過濾。**
- **N=5**：Russell 2000 測試中假訊號減少 20%；N=2~10 對 QQQ 均為「higher CAR, lower MDD, fewer trades」。
- 超過 N=5 時保護速度明顯下降，與 1% band 類似開始侵蝕熊市保護。

#### 取捨效果
| 面向 | 效果 |
|---|---|
| **whipsaw 抑制** | 強，尤其對「一兩天假穿越」完全消除。2022 的 7 次穿越中，若 N=3，多數「跌破→次日站回」型態會被直接過濾。 |
| **牛市參與** | N=2~3 影響極小。確認期 N 天 ≈ 平均延遲 N/2 天進出場，對月度報酬影響微。N=5 以上才開始有可感知的進場延遲。 |
| **初跌保護** | **比原版更差。** 連續 N 日確認等於在崩盤初期多等 N 天，這在 2020 那種急崩中代價是顯著的（2020/3 高峰到谷底只有 18 個交易日）。N=3 ≈ 額外延遲 3 天 × 約 2.5%/天＝多吃 7.5% 下跌。 |

#### Harness 可回測性
**最容易實作（純快取）**。在 `vol_target_exposure()` 中把 `below = close < ma` 改成 `below = (close < ma).rolling(N).min().astype(bool)`（連 N 天皆 True）；回補同理：`above = (close >= ma).rolling(N).min()`。幾行程式。

---

### 技術 3：非對稱「出場快、回補慢」（Asymmetric Reentry with High Condition）

#### 機制
**出場規則不變**（跌破 MA200 即減碼），但**回補需要額外條件**，例如：
- (A) 站回 MA200 且 close 創過去 M 日新高（近期高點確認）
- (B) 站回 MA200 且 MA200 斜率向上（`MA200[t] > MA200[t-N]`）
- (C) 站回 MA200 且距離上次出場已過 T 個交易日（冷卻期）

邏輯根據：崩盤底部反彈常見「跌破→短暫彈上 MA200→再跌」的型態（2022 反覆出現）；要求創近期新高或均線轉向才能確認是真回補而非假反彈。

Meb Faber 的「12-Month High Switch」變體也是此方向的延伸——只有資產處於 12 個月高點 5% 範圍內才持有（本質上是「強勢才回補」的高條件版）。

#### 取捨效果
| 面向 | 效果 |
|---|---|
| **whipsaw 抑制** | **最強**。非對稱設計從根本上打破「砍倉→追買」的對稱循環。2022 型態（熊市中多次假彈）最受益。 |
| **牛市參與** | **最大代價**。V 型反彈（2020）中，若要等站回 MA200 + 創 20 日新高，可能晚回補 2–3 週，錯失反彈早段。具體：2020/3/23 谷底→4/14 站回 MA200+創 20 日高，延遲約 15 個交易日。 |
| **初跌保護** | 出場規則不變，**不惡化初跌保護**。這是本技術的核心優勢：出場速度不打折。 |

#### Harness 可回測性
**中等難度，但可純快取實作**。需要狀態機（tracking `in_reduced_exposure` flag），回補邏輯需計算滾動最高收盤或 MA 斜率。這需要修改 `vol_target_exposure()` 為有狀態計算（目前是純向量化），或在 `benchmark_backtest.py` 的模擬迴圈中加入狀態追蹤（已有 per-day for loop，較易加）。

---

### 技術 4：降低評估頻率（Monthly-Only Signal Evaluation）

#### 機制
完全對齊 Meb Faber GTAA 核心設計：**每月月底（或月首）才評估一次** price vs MA200，中間每日不看。目前 harness 已有月首再平衡邏輯（`is_month_first_trading_day`），只需關閉偏離觸發（`drift > BAND`），讓訊號評估只在月首觸發。

Faber 原文：「10-month SMA，monthly evaluation」，歷史驗證顯示月評估 vs 日評估的 whipsaw 次數大幅減少，但長期績效幾乎等同。

#### 取捨效果
| 面向 | 效果 |
|---|---|
| **whipsaw 抑制** | **極強，且免費**。月評估的穿越次數是日評估的 1/21（僅月底一個觀察點），短暫震盪完全不感知。2022 那 7 次 3.5 週內的穿越，在月評估下只會看到 1~2 次月底快照。 |
| **牛市參與** | 損失有限。月評估最差情況是「月中跌破，月底恰好站回 MA200 上方→未觸發出場」，多承受最多 1 個月的下跌。但台股 0050 月波動約 5–8%，這個額外敞口是有意義的。 |
| **初跌保護** | **最差**。2020/3：月底評估節點是 3/31，此時 0050 已從高點下跌 ~30%，月評估完全沒有初跌保護。**對急崩事件是致命弱點。** |

**關鍵洞察**：月評估適用於「溫吞熊市」（2022 型），對「急崩+V 型反彈」（2020 型）保護失效。台股歷史兩種型態都有，月評估無法全保。

#### Harness 可回測性
**最簡單，已有基礎建設**。`benchmark_backtest.py` 的 `if not (month_first[i] or drift > BAND):` 改為 `if not month_first[i]:` 即可模擬純月評估。

---

### 技術 5：慢訊號 / 雙均線（MA Slope Filter 或 Dual MA）

#### 機制
兩種子方向：

**(A) MA 斜率過濾**：`close < MA200` 觸發出場，但加條件「MA200 斜率向下（`MA200[t] < MA200[t-N]`）」才出場。斜率平坦（橫盤）時即使跌破也不出場——代表「整個均線還沒轉向，短暫跌破很可能是雜訊」。

**(B) 雙均線**：使用 MA50（快線）vs MA200（慢線）的金死叉作為訊號，而非 price vs MA200。快線死叉慢線需要較長的下跌持續才能觸發，自然過濾短暫穿越。

EMA 版本（StockCharts 文獻）：10-month EMA vs 10-month SMA，EMA 因指數加權對近期更敏感，實測產生更少 whipsaw，但出場慢 1 個月。

#### 取捨效果
| 面向 | 效果 |
|---|---|
| **whipsaw 抑制** | 中等。斜率過濾可排除「均線仍向上時的短暫跌破」；雙均線死叉需要約 1–3 個月的明顯趨勢才觸發。兩者都比單純 price vs MA200 慢，whipsaw 減少，但保護也慢。 |
| **牛市參與** | 影響較小。斜率向上時絕不出場，牛市高原期不會誤觸出場。雙均線死叉通常在牛市結束後才觸發，不提前出場。 |
| **初跌保護** | **最差方向之一**。雙均線死叉的 lag 可達 1–3 個月——2020 急崩 1 個月就結束了，死叉信號可能在底部附近才觸發，完全沒有保護。MA 斜率方向同理：均線下彎需時間。 |

#### Harness 可回測性
**可實作（純快取）**。斜率過濾：在 `vol_target_exposure()` 加 `ma_slope = ma - ma.shift(N)` 條件；雙均線：加 `ma50 = close.rolling(50).mean()` 與死叉判斷。均為純向量計算。

---

### 技術 6：ATR 動態帶（Volatility-Scaled Hysteresis）

#### 機制
技術 1 的進化版：緩衝帶寬度不固定（如固定 1%），而是動態設為 `K × ATR(N)`，例如：
- 出場門檻：`close < MA200 - 1 × ATR(22)`
- 回補門檻：`close > MA200 + 1 × ATR(22)`

當市場波動率高時（2020/2022 崩盤期），ATR 膨脹，帶寬自動擴大，避免在高波動期的雜訊中反覆觸發。當市場平靜（牛市中段），ATR 縮小，帶寬收窄，訊號敏感度提高。

這是 Keltner Channel 應用於 trend filter 的邏輯，StockCharts 測試：Keltner(200,1,22) 效果與 SMA Envelope(1%) 類似，但動態適應高低波動環境。

#### 取捨效果
| 面向 | 效果 |
|---|---|
| **whipsaw 抑制** | 強，且在高波動期（2020/2022）最有效——正是最需要的時候自動擴帶。 |
| **牛市參與** | 損失類似固定帶，但在低波動牛市期帶寬自動收窄，比固定帶更快重新入場。整體比技術 1 對牛市更友善。 |
| **初跌保護** | 比固定帶略差。崩盤初期 ATR 剛開始膨脹，帶寬還不夠寬；幾天後才完全展開。實務影響輕微。 |
| **實作複雜度** | 比固定帶高一級：需計算 ATR（已有 pandas 可完成，不需外部庫）。 |

#### Harness 可回測性
**可實作（純快取）**。ATR = `close.diff().abs().rolling(22).mean()`（簡化版）或真 ATR（需 high/low；0050 資料有欄位）。在 `vol_target_exposure()` 或回測迴圈中加入即可。

---

## 三、各技術取捨矩陣

| 技術 | Whipsaw 抑制 | 牛市參與代價 | 初跌保護影響 | Harness 難度 | 適用情境 |
|---|---|---|---|---|---|
| **1. 固定帶 (α%/β%)** | 強 | 小 | 略差 | 易 | 2022 型震盪熊市 |
| **2. N-Day 確認** | 強（短穿越） | 極小（N≤3） | 差（多等 N 天） | 最易 | 假穿越為主的情境 |
| **3. 非對稱回補** | 最強 | 最大（V 型反彈） | 不影響出場 | 中 | 2022 型慢熊 |
| **4. 月評估** | 極強 | 中 | 最差（急崩無效） | 最易 | 僅適合慢熊 |
| **5. 雙均線/斜率** | 中 | 小（牛市不誤觸） | 最差（lag 最長） | 易 | 不推薦單獨用 |
| **6. ATR 動態帶** | 強＋自適應 | 比固定帶小 | 略差 | 中 | 高低波動交替市場 |

**核心取捨命題**：你的案例中，2020（急崩+V型）與 2022（慢熊+反覆假彈）是兩個對立的壓力測試——**任何減慢訊號的技術都會惡化 2020 型保護；任何加快訊號的技術都會惡化 2022 型 whipsaw**。沒有免費午餐。

**相對最優**：技術 2（N-Day 確認，N=3）在 Alvarez 的 SPY/QQQ 實測中是「近乎免費」的改善——交易次數減半、CAR 幾乎不變、MDD 降低。這是唯一有直接量化證據支持「不犧牲主要效果」的技術。

---

## 四、優先嘗試排序（含理由）

### 優先級 1：N=3 Day Consecutive Confirmation（技術 2）

**理由**：
- 唯一有直接量化證據（Alvarez Quant Trading，SPY 2000–2023）：N=3 讓 50% 交易消失，MDD 改善，CAR 幾乎不變。
- 實作最簡單：`benchmark_engine.py` 的 `below = close < ma` 改一行。
- **保守邏輯**：「確認跌破」不是讓你更慢出場，而是只對真穿越才行動。你的 2022 案例中「賣820→買787→賣901」——若 N=3，第一次賣 820 後兩天站回就不會觸發第二次賣，3.5 週 7 次穿越可能剩 2–3 次。
- **caveat**：N=3 對 2020 急崩多承受 3 天下跌（約 6–8%），這是明確的代價，值得在 walk-forward 中量化。

### 優先級 2：固定對稱帶 α=β=1%（技術 1）

**理由**：
- 機制直覺清晰，文獻（Arthur Hill StockCharts）有 SMA Envelope 測試。
- 與 N-Day 確認的差異：帶的過濾是「距離型」，確認是「時間型」；可組合（先有帶，再確認），也可單獨比較。
- 現有 harness 的 `regime_action=0.85` 是對稱的（跌破→出，站回→進），加帶是最小侵入式修改。
- **caveat**：1% 對台股 0050（日波動約 1%）等於「1 個交易日的移動」，是否足夠？可掃 0.5%/1%/1.5%/2% 的細網格（符合 CLAUDE.md 規則 7 的 12–18 點）。

### 優先級 3：ATR 動態帶（技術 6）

**理由**：
- 概念上優於固定帶：在 2022 那種高波動期帶寬自動擴大，在 2020 急崩初期帶寬還未完全展開（不過分惡化初跌保護），在牛市平靜期帶寬收縮不錯過回補。
- 但實作比技術 1 複雜（需 ATR），且沒有前兩者那麼直接的文獻量化支持。
- **建議**：先完成技術 1/2 的回測，若 whipsaw 仍顯著再引入 ATR。

### 優先級 4：非對稱回補 + MA 斜率條件（技術 3/5 組合）

**理由**：
- 對 2022 型慢熊威力最強（「真跌才出、真回才補」），但對 2020 型 V 反彈牛市參與代價最大。
- 需要狀態機，實作中等。
- **建議**：作為技術 1+2 的後補加強方案，在前兩者的 walk-forward 結果出來後，若 2022 型 whipsaw 仍殘留，再引入非對稱回補。

### 暫不優先：月評估（技術 4）、雙均線（技術 5 獨立版）

- **月評估**：2020 型急崩完全無保護（月底才看一次，此時已跌 30%），在台股多急崩的歷史中這個弱點無法接受。
- **雙均線**：lag 太長，急崩保護幾乎為零，僅適合慢趨勢市場。

---

## 五、對現有 Harness 的最小改動路徑

**技術 2（N-Day 確認）的實作建議**：

修改 `/Users/cch_0182/trading-bot/src/strategy_engines/benchmark_engine.py`，`vol_target_exposure()` 函數中：

```python
# 現行（日線，每日判斷）
below = close < ma
below = below.fillna(False)

# 改為 N-Day 確認
N = 3  # 參數化，傳入
# 出場：連 N 天收盤皆在 MA 下方
below = (close < ma).rolling(N, min_periods=N).min().astype(bool)
below = below.fillna(False)
# 回補：連 N 天收盤皆在 MA 上方（可設不同 N_reentry 實現非對稱）
# 需狀態機或：以 ~below 作為「解除 reduced exposure」的觸發
```

這仍是向量計算，與現有 `exp.where(~below, exp * mult)` 接口完全相容。掃 N=1/2/3/4/5/7/10（7 點）× 對稱/非對稱（各 N 設不同出場/回補天數）= 細網格。

**技術 1（固定帶）的實作建議**：

同一函數，增加 `band_pct` 參數：
```python
below = close < ma * (1 - band_pct)    # 出場：跌破帶下緣
in_bull = close > ma * (1 + band_pct)  # 回補：站上帶上緣（需狀態機）
```

或簡化為對稱固定帶（先跑，再探討非對稱），掃 band=0/0.5%/1%/1.5%/2%/2.5%/3%（7點以上）。

---

## 六、紀律提醒（對應 CLAUDE.md）

1. 以上任何參數調整**須綁 walk-forward OOS**，in-sample 峰值（如「帶寬 2% 的 in-sample Sharpe 最高」）不得直接採信。
2. 對照基準固定預先指定：0050 買進持有（Sharpe ~0.94–0.95）+ 基準B（vol_target，Sharpe ~0.80），不浮動選 best-of-sweep。
3. **掃描網格**：帶寬至少 12 點（0/0.25/0.5/0.75/1/1.25/1.5/1.75/2/2.5/3/3.5%），N-Day 至少 7 點（1~10），才能識別「平滑高原 vs 鋸齒雜訊」。
4. 所有結果仍含 survivorship（FinMind 無下市），結論須帶此 caveat。
5. 通過 OOS Gate 前，**live 配置不動**（現行 MA200 + 0.85 regime_action 保持）。

---

## 七、參考來源

- [Moving Average Crossover Rules That Reduce Whipsaws — TrendsAndBreakouts](https://trendsandbreakouts.com/ma-crossover)
- [SystemTrader: Reducing MA Whipsaws with Smoothing and Quantifying Filters — StockCharts/Arthur Hill](https://articles.stockcharts.com/article/articles-arthurhill-2018-10-systemtrader---reducing-moving-average-whipsaws-with-smoothing-and-quantifying-filters-)
- [Reducing Whipsaws When Using 200-day Moving Average — Alvarez Quant Trading](https://alvarezquanttrading.com/blog/reducing-whipsaws-when-using-200-day-moving-average-for-market-timing/)
- [Meb Faber's 12-Month High Switch — Allocate Smartly](https://allocatesmartly.com/meb-fabers-12-month-high-switch/)
- [A Quantitative Approach to Tactical Asset Allocation (Meb Faber GTAA) — TrendFollowing.com](https://www.trendfollowing.com/whitepaper/CMT-Simple.pdf)
- [Kaufman's Adaptive Moving Average (KAMA) — StockCharts ChartSchool](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/kaufmans-adaptive-moving-average-kama)
- [Moving Average Trend Following: 200-Day Strategy Explained — GraniteShares](https://graniteshares.com/institutional/us/en-us/research/the-200-moving-average-strategy-explained/)
- [Mebane Faber Strategy — Quantified Strategies](https://www.quantifiedstrategies.com/meb-faber-momentum-trend-following-strategy/)
- [Avoiding Whipsaw: Strategies to Minimize False Signals — Above the Green Line](https://abovethegreenline.com/whipsaw-trading/)
- [Trend-Following Strategies: Dealing with Whipsaws — Proactive Advisor Magazine](https://proactiveadvisormagazine.com/trend-following-strategies-dealing-with-whipsaws/)

---

# 附錄 B：崩盤/regime 偵測訊號（完整研究）

# Regime / 崩盤偵測研究報告

## 目錄

1. [2020 與 2022 兩次跌的性質確認（Part A）](#part-a)
2. [訊號盤點：比 MA200 更快的崩盤偵測（Part B）](#part-b)
3. [各訊號對 2020 / 2022 具體評估](#part-b2)
4. [假訊號成本與牛市誤觸估算](#false-positive)
5. [台股資料可得性與回測可行性](#data)
6. [文獻佐證摘要](#literature)
7. [對現有策略的行動建議](#action)

---

## Part A：2020 vs 2022 跌的性質確認

### 2020 COVID 崩盤 — 外生急性衝擊、V 型復原

**性質定性：外生總經事件（pandemic shock）**

| 維度 | 證據 |
|---|---|
| 驅動因子 | COVID-19 全球蔓延 → 恐慌拋售；非台股估值過高或技術性頭部 |
| 台灣市場特殊性 | 台灣防疫管控佳、無封城，外資仍拋售（市場整體恐慌，無視基本面差異）；PMC 研究確認投資人在崩盤期集體拋股、無論產業差異（herding） |
| 復原型態 | 三段式：恐慌期 → 反彈期 → V 型後期。台灣因防疫信心恢復快，V 型特徵顯著 |
| 崩盤速度 | 急速（數週內跌幅最大）；S&P 500 進入熊市僅用 22 個交易日（史上最快） |
| 均值回歸 | 是；基本面未真正惡化，政策（Fed 無限 QE）迅速托底 |

**對 MA200 的啟示**：急跌速度遠超 MA200 反應時間。MA200 是「中期趨勢確認器」，對急性衝擊天生慢一拍。

---

### 2022 升息熊市 — 外生總經事件（但是慢熊）

**性質定名：外生但慢速結構性再定價（macro tightening bear）**

| 維度 | 證據 |
|---|---|
| 驅動因子 | Fed 2022 年升息 11 次（3月開始）；通膨 2022/6 達 9.1%；俄烏戰爭推升能源糧食；TAIEX 全年收盤 −22.4% |
| 崩盤速度 | 慢熊；非急崩，而是全年持續下壓，伴隨反彈陷阱 |
| 波段特徵 | 2022 Q1 即展開，但 TAIEX 直到 7/1 才官方宣告進入熊市（20% 回撤） |
| 台灣特殊壓力 | 費半 SOX 同年下跌 ~36%；台積電、半導體股受半導體周期下行疊加；8 月裴洛西訪台地緣風險額外衝擊 |
| 2022 vs 2020 性質差異 | 2022 是「duration risk 事件」（非信用危機）：股債同跌、不是恐慌性 de-risking，是合理定價重設 |

**對 MA200 的啟示**：慢熊環境 MA200 會在相對早期被跌穿（相比 2020 急崩），但 2022 的反覆拉鋸讓 MA200 的 7 次穿越形成高 whipsaw 代價。

---

## Part B：比 MA200 更快的訊號盤點

### 訊號矩陣總覽

| 訊號類別 | 代表指標 | 核心邏輯 | 前置優勢估計 |
|---|---|---|---|
| 已實現波動跳升 | 5d/20d 日報酬標準差；ATR 擴張 | 崩盤前 vol 先跳 | 3–10 天 |
| 隱含波動率（VIX 類） | VIXTWN（台灣選擇權隱波）；美 VIX | 市場對未來 30 天風險定價 | 2–5 天 |
| Vol-of-Vol（VoV） | 美 VVIX；自製 VIXTWN 的 5d std | vol 的波動先跳、比 vol 本身更早 | 5–7 天 |
| 從峰回撤速度觸發 | From-peak% 在 N 天內跌破 X% | 直接衡量損害速度 | 即時（同步） |
| 短窗趨勢 | MA20 / Price vs 20d avg；5-10d EMA | 更快的趨勢確認 | 5–15 天 |
| 市場廣度惡化 | 台股多空家數比；% 個股跌破自身 MA60 | 指數可能掩蓋廣度惡化 | 3–7 天 |
| 跨資產壓力 | 費半 SOX；美 10 年期殖利率波動；美元 DXY 急升；黃金/美債同步 | 台股對外資、半導體敏感 | 1–5 天 |
| 外資淨賣超 | 三大法人外資淨買賣（FinMind 有） | 外資是台股主要法人 | 1–3 天 |
| 爆量/跳空缺口 | 成交量 spike > N 倍均量；缺口 > Y% | 恐慌拋售必然放量 | 即時 |

---

## Part B.2：對 2020 / 2022 具體評估

### 2020 COVID 急崩

#### 時序回顧（相對於 MA200 觸發 3/12 為基準）

```
2020-01-31  WHO 宣布 PHEIC（公共衛生緊急事件）
2020-02-21  S&P 500 從峰下跌開始；vol 偵測模型偵測到 regime 轉換 [arxiv 2104.03667]
2020-02-24  TAIEX 單日重挫；ATR 擴張開始
2020-02-26  5d 已實現 vol 開始快速上升
2020-03-02  外資開始大量淨賣超
2020-03-09  "Black Monday" 油價崩；VVIX 提前 VIX 尖峰數天先行跳升
2020-03-10  vol 峰值前置；VVIX 領先 VIX 最高點 [yamarkets 研究]
2020-03-12  [基準] MA200 觸發（此時 TAIEX 已從峰 −14%）
2020-03-16  VIX 歷史新高
```

**各訊號提前量估計（vs MA200 3/12）：**

| 訊號 | 估計觸發時間 | 提前天數 | 說明 |
|---|---|---|---|
| VVIX / vol-of-vol 跳升 | ~3/3–3/5 | 7–9 天 | VVIX 在 VIX 達峰前先行；間接衡量「vol 的vol」劇烈 |
| 已實現 5d vol 突破 1.5× 均值 | ~2/26–2/28 | 約 11–14 天 | vol clustering：高 vol 後跟高 vol |
| from-peak 速度停損（-8% in 7d） | ~3/2–3/4 | 8–10 天 | 急崩時速度停損最直接 |
| MA20 跌穿（短均線） | ~3/3–3/6 | 6–9 天 | 更快趨勢確認 |
| 外資連續淨賣超 3 日 | ~3/2–3/5 | 7–10 天 | FinMind 有三大法人資料 |
| 費半 SOX 跌破 MA50 | ~2/25–2/27 | 13–15 天 | 半導體先行；台股高相關 |

**2020 的關鍵診斷**：急崩型。任何「速度型」訊號（vol spike、from-peak 速度、短均線）都能早 MA200 整整 1–2 週觸發。**vol 類最早，SOX 最可靠作前導。**

---

### 2022 慢熊

#### 時序回顧（相對於 MA200 觸發 3/7 為基準）

```
2022-01-05  Fed 會議紀錄超鷹；美 10 年期急升；TAIEX 開始從高點回落
2022-01-中  費半 SOX 跌破多個均線（從 2021/12 峰下跌更早）
2022-02-24  俄羅斯入侵烏克蘭；市場一度急跌後反彈
2022-03-07  [基準] MA200 觸發（TAIEX 已從峰 −11%）
2022-03月   7 次 MA200 穿越（whipsaw 最嚴重段）
2022-07-01  TAIEX 正式進入熊市（−20%）
```

**各訊號在 2022 的行為：**

| 訊號 | 2022 行為 | 提前 MA200 | 假訊號風險 |
|---|---|---|---|
| vol spike / ATR | 較 2020 溫和；全年 vol 中等偏高但未出現 2020 式急跳 | 無明確提前 | 高（慢熊中 vol 持續偏高但不尖峰） |
| from-peak 速度停損 | 因為是慢熊，速度慢，觸發時間晚於 2020 | 無明顯提前 | 中（反覆小幅回撤多次觸發） |
| MA20 跌穿 | 2022/1 即觸發，但之後反覆穿越多次 | 早 6–7 週 | 高（whipsaw 從 3 次增到更多）|
| 費半 SOX 信號 | SOX 2021/12 起就下跌，領先 TAIEX；2022/1 跌破 MA50 | 早 ~6–8 週 | 低（慢熊前導比較穩定）|
| 外資連續賣超 | 外資 2022 全年持續淨賣；1 月起即開始 | 早 6 週以上 | 中（但慢熊期間不連續） |
| 廣度惡化（% 跌破 MA60） | 2022/1–2 廣度快速惡化，早於指數明顯崩跌 | 早 4–6 週 | 中 |

**2022 的關鍵診斷**：慢熊型。**速度停損類訊號幫助有限**；反而**費半/外資/廣度**等前導指標更可靠。但無論何種「快速」訊號，慢熊本質上就是長期漸進惡化，任何快訊號都會在反彈時反覆假觸發。

---

## 假訊號成本（牛市誤觸代價）

### 核心 tradeoff

| 訊號速度 | 典型錯誤類型 | 牛市誤觸率估計 | 出 15% 代價估算 |
|---|---|---|---|
| MA200（現行） | 反應慢；保護 2020 的 −14% 盲區 | 低（穿越才動） | whipsaw 估 2022 ~0.77pp；2020 ~2.1pp |
| MA20 | 反應快；高 whipsaw | 高；側橫盤每年 3–5 次 | 每次約 −0.3~0.5pp（含成本）× 次數 |
| vol spike（5d vol > 1.5× 均） | 急跌前警報；平時偶發 | 中；每年約 2–4 次假警報 | 每次 ~−0.2pp；全年可能 −1pp |
| from-peak −5% in 5d | 速度觸發；급崩必中 | 中；大幅回撤必發；每年 1–3 次 | 每次出 15% 代價小；但進出成本累積 |
| SOX 跌破 MA50 | 半導體前導；方向性但非精確 | 中低；每年約 1–2 次有效；0–1 次無效 | 見 2020：提前 13–15 天但大跌確實來了 |
| 外資連 3 日淨賣 | 法人賣壓；台股外資主導 | 中；每年 4–8 次（包含季節性外資再平衡） | 需過濾門檻 |
| 多訊號組合（2+ 同時觸發） | 假陽性率 ~35% 降至 ~10% | 低；每年約 0–1 次假警報 | 代價可控 |

關鍵研究發現：**「單一訊號假陽性率約 30–35%；3 個以上訊號同時觸發，歷史準確率超過 90%」**（volatilitybox.com 研究）。對僅出 15% 的輕量 overlay 而言，假訊號代價相對可控，但頻繁進出的交易成本（台股買賣 0.1425% + 0.3% 稅）仍是真實損耗。

---

## 台股資料可得性與回測可行性

### FinMind 已有資料

| 資料 | FinMind 資料集名稱 | 可用性 |
|---|---|---|
| 個股日收盤/OHLCV | `TaiwanStockPrice` | 已快取 |
| 三大法人（外資/投信/自營）淨買賣 | `TaiwanStockInstitutionalInvestorsBuySell` | 有（需驗快取） |
| 外資持股比例 | `TaiwanStockHoldingSharesPer` | 有 |
| 0050 成分股 | 無歷史成分（survivorship 問題） | 無法 PIT |
| 技術指標（KD/MA/MACD） | `TaiwanStockTechnicalIndicator` | 有（或自算） |

### 台灣選擇權隱含波動率（VIXTWN）

- **TAIFEX 官方計算**，每 15 秒更新，與 CBOE VIX 方法一致
- **MacroMicro 有歷史序列** (en.macromicro.me/series/4608/tw-vixtwn)，可下載 CSV
- FinMind 未直接提供 VIXTWN；需從 TAIFEX 官網或 MacroMicro 另行取得
- **德意志交易所（Deutsche Börse）** 也提供 TAIFEX 波動率指數商業數據

### 費半 SOX

- 可從 Yahoo Finance / 公開 API 取得（非 FinMind 範疇）
- 現有快取體系不含；需額外建

### 回測可行性評估

| 訊號組合 | 可行性 | 說明 |
|---|---|---|
| 現有 MA200 + 短均線（MA20/MA50） | 高 | 完全從已快取 0050 自算；`benchmark_backtest.py` 可直接擴充 |
| MA200 + 5d 已實現 vol 門檻 | 高 | 只需日收盤序列；同上 |
| MA200 + from-peak 速度停損 | 高 | 純日收盤計算 |
| MA200 + 外資淨賣超 | 中 | FinMind 有法人資料，需確認歷史深度與快取 |
| MA200 + VIXTWN | 中 | 需額外從 MacroMicro 或 TAIFEX 取 CSV |
| MA200 + SOX | 低 | 需額外外部數據；非快取體系 |
| 多訊號組合閘 | 中高 | 可先用前三組（純快取）測試；後續加外部數據擴充 |

---

## 文獻佐證摘要

| 主題 | 關鍵發現 | 來源 |
|---|---|---|
| 2020 regime 偵測時間點 | ML 方法 2020-02-21 即偵測到 regime 轉換；確認法 3–8 天後 | [arxiv 2104.03667](https://arxiv.org/pdf/2104.03667) |
| VVIX 領先 VIX | VVIX 在 VIX 達歷史峰前提前跳升；vol-of-vol 是崩盤前兆 | [yamarkets vol regime](https://www.yamarkets.com/blog/best-strategies-for-high-volatility-markets) |
| 多訊號準確率 | 3+ 訊號同時觸發準確率 >90%；單訊號假陽性 ~35% | [volatilitybox](https://volatilitybox.com/research/volatility-regime-detection/) |
| 廣度先行 | A-D line / 個股跌破 MA 的廣度惡化比指數早數天 | [Fidelity breadth](https://www.fidelity.com/learning-center/trading-investing/advance-decline) |
| 崩盤速度（drawdown speed） | 崩盤前相關矩陣最大特徵值快速主導化；結構惡化早於價格 | [ResearchGate Drawdowns & Speed](https://www.researchgate.net/publication/236222821_Drawdowns_and_the_Speed_of_Market_Crash) |
| VIX 閾值與假陽性 | 單日 VIX spike 假陽性 ~30%；配合 VVIX 可提升準確率 | [CAIA Volatility Tsunami](https://caia.org/sites/default/files/forecasting_a_volatility_tsunami.pdf) |
| HMM 隱馬可夫模型 | 比單一閾值規則更精確（完整分布資訊）；3-state bull/bear/neutral | [MDPI HMM](https://www.mdpi.com/2227-7072/6/2/36) |
| Taiwan VIX 預測力 | VIXTWN 對 TAIEX 波動具預測力（出現研究 2013） | [ResearchGate TVIX](https://www.researchgate.net/publication/266524972) |
| MA200 策略弱點 | 28% 勝率；橫盤市場大量假訊號 | [QuantifiedStrategies](https://quantifiedstrategies.com/200-day-moving-average-trading-strategy/) |
| 2022 TAIEX 熊市 | 正式 −20% 進入熊市；Fed 升息 11 次、俄烏戰爭為主因 | [Taipei Times](https://www.taipeitimes.com/News/biz/archives/2022/07/02/2003780962) |

---

## 對現有策略的行動建議

### 診斷總結

| 面向 | 結論 |
|---|---|
| MA200 的根本盲區 | 非「訊號壞了」而是設計用途不同：MA200 衡量中期趨勢、不是崩盤偵測器 |
| 2020 急崩最可改善 | vol spike + from-peak 速度組合，能早 MA200 約 7–14 天觸發 |
| 2022 慢熊改善有限 | 慢熊性質讓任何快訊號都多次假觸發；費半 SOX、外資是相對較佳的前導 |
| 出 15% 的輕量設計正確 | 假訊號代價因此受限；不建議激進加大出倉比例 |

### 可立即回測的候選改良（純快取，可接 benchmark_backtest.py）

**方案 A — vol-spike 輔助觸發（2020 針對性改善）**
- 條件：5d 日報酬標準差 > 1.5×（過去 60d 均值）AND TAIEX 從 20d 高點下跌 > 4%
- 額外效果：提前捕獲 2020 的盲區；2022 可能多 2–3 次假觸發
- 成本：每次假觸發 ~0.15–0.25pp（交易成本）

**方案 B — 雙層確認（降 whipsaw 同時提速）**
- 上層：既有 MA200 觸發 → 出 15%
- 新增：5d vol spike 或 from-peak −7% in 10d → 提前出 15%（合計仍不超過 30%）
- 優點：不改現有 MA200 行為，只添加一層早期保護

**方案 C — MA50 輔助（折衷速度）**
- MA50 替代部分 MA200 角色：跌破 MA50 出 10%；跌破 MA200 再出 5%
- 需回測 2018–2025 以評估 MA50 的 whipsaw 代價

### 需額外資料才能測試

- **VIXTWN**（台灣隱含波動）：需從 MacroMicro 或 TAIFEX 另取；是最值得引入的外部數據
- **費半 SOX**：對台股（半導體主導）有高預測力，特別是 2020 急崩的 13–15 天領先；需外部數據
- **三大法人外資淨賣超**：FinMind 理論上有，需確認快取覆蓋期間再回測

---

*本報告不構成 live 調倉依據。依 CLAUDE.md 鐵則：任何參數改動須先完成 walk-forward OOS 並通過 Gate（OOS > 基準B），總 Gate FAIL 前 live 不動。上述方案建議作為下一輪研究假說輸入。*

---

## Sources

- [Investors' reactions and firms' actions in the Covid-19 period: Taiwan - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8496924/)
- [2020 stock market crash - Wikipedia](https://en.wikipedia.org/wiki/2020_stock_market_crash)
- [TAIEX drops over 20% from peak, entering bear market - Taipei Times](https://www.taipeitimes.com/News/biz/archives/2022/07/02/2003780962)
- [2022 stock market decline - Wikipedia](https://en.wikipedia.org/wiki/2022_stock_market_decline)
- [Taiwan Stock Benchmark Falls 20% From Peak - BNN Bloomberg](https://www.bnnbloomberg.ca/taiwan-stock-benchmark-falls-20-from-peak-set-for-bear-market-1.1786462)
- [Volatility Regime Detection: From Simple Rules to Machine Learning - Volatility Box](https://volatilitybox.com/research/volatility-regime-detection/)
- [Market Regime Detection via Realized Covariances - arxiv](https://arxiv.org/pdf/2104.03667)
- [Early warning signals for stock market crashes - EPJ Data Science](https://epjdatascience.springeropen.com/articles/10.1140/epjds/s13688-024-00457-2)
- [Drawdowns and the Speed of Market Crash - ResearchGate](https://www.researchgate.net/publication/236222821_Drawdowns_and_the_Speed_of_Market_Crash)
- [Taiwan VIX - VIXTWN Series - MacroMicro](https://en.macromicro.me/series/4608/tw-vixtwn)
- [TAIFEX TAIEX Options Volatility Index](https://www.taifex.com.tw/enl/eng7/vixMinNew)
- [The Forecasting Power of the Volatility Index in Taiwan - ResearchGate](https://www.researchgate.net/publication/266524972_The_Forecasting_Power_of_the_Volatility_Index_in_Emerging_Markets_Evidence_from_the_Taiwan_Stock_Market)
- [Forecasting a Volatility Tsunami - CAIA](https://caia.org/sites/default/files/forecasting_a_volatility_tsunami.pdf)
- [Predictive Signals from VIX Spikes - Preprints.org](https://www.preprints.org/manuscript/202602.1048)
- [Hidden Markov Model Market Regimes - QuantifiedStrategies](https://www.quantifiedstrategies.com/hidden-markov-model-market-regimes-how-hmm-detects-market-regimes-in-trading-strategies/)
- [Regime-Switching Factor Investing with HMM - MDPI](https://www.mdpi.com/1911-8074/13/12/311)
- [I Tested 20 Trend-Based Regime Filters - Setup4Alpha](https://setup4alpha.substack.com/p/i-tested-20-trend-based-regime-filters)
- [200-Day Moving Average Strategy Backtest - QuantifiedStrategies](https://www.quantifiedstrategies.com/200-day-moving-average-trading-strategy/)
- [Advance Decline Indicator - Fidelity](https://www.fidelity.com/learning-center/trading-investing/advance-decline)
- [FinMind Open Financial Data API](https://finmind.github.io/)
- [Philadelphia Semiconductor Index SOX Guide - TradingSim](https://www.tradingsim.com/blog/philadelphia-semiconductor-index)

---

# 附錄 C：新聞/事件分析資源盤點（完整研究）

# 台股事件偵測：金融新聞擷取與情緒分析資源全盤點

*調查日期：2026-06-17｜標的：TAIEX / 0050 / TSMC（2330）*

---

## 一、商業新聞 + 情緒 API

### 1. RavenPack
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 40,000+ 來源、300M 文章/月、13 種語言、90,000+ 全球公司 |
| 台股/中文支援 | **有但有限**：透過 SCRIPTS Asia 涵蓋約 2,000 家北亞公司（含台灣），有中文來源；但台灣本地中文財經媒體（鉅亨、工商）覆蓋深度不透明 |
| 延遲 | 毫秒級即時 |
| 價格 | **企業議價**，市場估計年費 $100k–$200k+；有 WRDS 學術管道（大學訂閱制） |
| API | REST + 串流；JSON；WRDS 也可查 |
| 歷史新聞 | 有，2000 年起（含）；20+ 年歷史回測 |
| 授權 | 商業授權，企業合約 |
| 回測可用性 | 是，歷史資料完整，是學術研究常見資料來源 |
| 缺口 | 台灣本土中文媒體（MoneyDJ、鉅亨中文版）覆蓋不透明；價格對個人或小型策略不可行 |

**來源**：[RavenPack News Analytics](https://www.ravenpack.com/products/edge/data/news-analytics)、[WRDS RavenPack](https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/ravenpack/)、[RavenPack APAC](https://www.ravenpack.com/research/news-sentiment-apac)

---

### 2. LSEG / Refinitiv Machine Readable News
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 50,000+ 公司即時新聞；歷史回到 1996 年（情緒分析資料 2003 年起） |
| 台股/中文支援 | **有限**：LSEG Workspace 2025 年 3 月起整合 Dow Jones 中文新聞（WSJ 中文等）；但台灣本土中文媒體覆蓋薄弱；**Eikon 已於 2025-06-30 停止服務**，改用 LSEG Workspace |
| 延遲 | 毫秒級串流 |
| 價格 | LSEG Workspace 估計 $20k–$50k+/年；Machine Readable News 需另議 |
| API | WebSocket（JSON）；REST；Bulk files |
| 歷史新聞 | 1996 年起（極佳深度） |
| 授權 | 企業商業授權 |
| 備注 | Eikon Python API 已停；改用 [LSEG Developer Portal](https://developers.lseg.com/) |

**來源**：[LSEG Machine Readable News](https://www.lseg.com/en/data-analytics/financial-news-service/machine-readable-news)、[Eikon 停服通知](https://www.lseg.com/en/data-analytics/products/eikon-trading-software)

---

### 3. Bloomberg Terminal / BLPAPI
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 全球最廣；台股、台積電新聞齊全 |
| 台股/中文支援 | **是**：Bloomberg 有中文財經新聞服務 |
| 延遲 | 毫秒級 |
| 價格 | Terminal 約 $24k/年/seat；Server API（B-PIPE）額外費用 |
| API | BLPAPI（C++/Python）；Server API |
| 歷史新聞 | 有，多年歷史 |
| 授權 | 嚴格商業授權，禁止二次轉散布 |
| 實用性 | 個人/小型策略不可行；但若已訂閱 Bloomberg，是最完整的台股新聞來源 |

---

### 4. Dow Jones Newswires
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | Factiva 整合；WSJ、Barron's、MarketWatch 等 |
| 台股/中文支援 | 有中文版 WSJ；亞太財經新聞涵蓋台灣，但本地台灣中文媒體（鉅亨、工商）不含 |
| 延遲 | 即時 |
| 價格 | Factiva 個人版約 $150–400/月；企業授權需議；LSEG Workspace 已整合 DJ |
| API | REST（Postman collections 有公開範例） |
| 歷史新聞 | 有，Factiva 歷史深度良好 |

**來源**：[LSEG DJ 合作](https://www.lseg.com/en/media-centre/press-releases/2024/lseg-and-dow-jones-announce-a-multi-year-data-news-and-analytics-partnership)

---

### 5. Alpha Vantage News & Sentiment
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 美股為主；200,000+ tickers（含 ADR） |
| 台股/中文支援 | **不明確**：文件只提 US market data；台股中文新聞很可能不涵蓋 |
| 延遲 | 即時（premium） |
| 價格 | 免費：25 calls/天；付費：$49.99–$249.99/月（75–1200 rpm）；年付約 $499–$2,499 |
| API | REST；JSON |
| 歷史新聞 | 有（LLM 增強情緒分析 + 15 年財報電話會議）；但台股新聞歷史不確定 |
| 授權 | 商業可用；有免費額度 |
| 台股適用性 | **低**：以美股為主，台股中文新聞覆蓋不透明 |

**來源**：[Alpha Vantage](https://www.alphavantage.co/premium/)

---

### 6. Finnhub
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 60+ 交易所；65,000+ 公司；含 Reddit/Twitter 情緒 |
| 台股/中文支援 | **部分**：有 TSMC（TSM ADR）新聞；台灣本地中文新聞不確定；本土上市（2330.TW）覆蓋薄 |
| 延遲 | 即時 |
| 價格 | 免費：60 calls/min；付費計畫見 [finnhub.io/pricing](https://finnhub.io/pricing-stock-api-market-data) |
| API | REST；WebSocket；Python SDK |
| 歷史新聞 | 有限；免費版為近期新聞 |
| 備注 | 台股中文本地新聞覆蓋不強；適合 TSMC ADR（紐約掛牌）英文新聞 |

**來源**：[Finnhub](https://finnhub.io/)

---

### 7. Marketaux
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 5,000+ 來源；30+ 語言；80+ 市場；200,000+ 實體 |
| 台股/中文支援 | **聲稱 30+ 語言、80+ 市場**，但台股中文本地媒體覆蓋深度不透明；文件不公開語言清單 |
| 延遲 | 即時 |
| 價格 | 免費：100 請求/天；付費：多層次，歷史資料需付費 |
| API | REST；JSON；sentiment score −1 to +1 |
| 歷史新聞 | 付費版有歷史資料（深度不明） |
| 授權 | 商業可用 |

**來源**：[Marketaux](https://www.marketaux.com/)、[FreeAPIHub](https://freeapihub.com/apis/marketaux)

---

### 8. Tiingo
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 108,404 全球標的（含中國股，但不含台灣本地掛牌） |
| 台股/中文支援 | **差**：News API 明確僅涵蓋 **10,000 美股**；台股（TWD 掛牌）新聞不含 |
| 延遲 | 即時 |
| 價格 | 免費版：500 symbols/月；Power：$30/月（$300/年） |
| API | REST；Python SDK（tiingo） |
| 歷史新聞 | **僅 3 個月可查詢**（商業客戶需聯繫可達 15 年） |
| 授權 | 商業需另議 |
| 台股適用性 | **不適合**：新聞 API 美股限定 |

**來源**：[Tiingo Pricing](https://www.tiingo.com/about/pricing)、[QuantConnect Tiingo News](https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/tiingo/tiingo-news-feed)

---

### 9. Polygon.io
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 美股為強項；國際股票有限 |
| 台股/中文支援 | **不適合**：主要覆蓋美股；台灣本地交易所無覆蓋 |
| 價格 | 免費：100 calls/月；付費：$29–$199+/月 |
| API | REST；WebSocket |
| 台股新聞 | 無直接台股新聞；可查 TSM ADR 英文新聞 |

---

### 10. EODHD（EOD Historical Data）
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 60+ 交易所；150k+ tickers；含台灣 TW 交易所（0050.TW、2330.TW） |
| 台股/中文支援 | **價格資料有**：TW Exchange 有歷史收盤價；新聞 Feed 功能存在但詳情不清 |
| 延遲 | EOD 為主；有 Intraday 方案 |
| 價格 | $19.99–$99.99/月；All-in-One $99.99/月含新聞 Feed |
| API | REST；JSON；CSV |
| 歷史新聞 | 新聞 Feed 深度不透明；價格資料 30+ 年 |
| 備注 | 主要優勢是歷史 OHLCV；新聞質量待確認 |

**來源**：[EODHD TW Exchange](https://eodhd.com/exchange/TW)

---

### 11. NewsAPI.org / newsdata.io / APITube
| 項目 | 內容 |
|------|------|
| NewsAPI.org | 150,000 來源；50+ 國家；但金融標的偵測無；台灣覆蓋有限；免費 100 req/天；$449/月（Business）；僅近 30 天免費 |
| newsdata.io | 84,675+ 來源；89 語言；154 國；有中文；金融標的連結無；需自行 NLP；免費有限 |
| APITube | $0 免費（200 req/天）；$99–$599/月；60+ 語言；10 年歷史（付費）；有情緒分數；台灣特定覆蓋不明 |

**來源**：[APITube Pricing](https://apitube.io/pricing)、[newsdata.io datasets](https://newsdata.io/datasets)

---

## 二、台灣 / 中文本地來源

### 12. FinMind `TaiwanStockNews`
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 台股個股新聞（指定 stock_id 查詢） |
| 台股/中文支援 | **是，完全台股**：回傳 title、description、source、link，繁體中文 |
| 延遲 | 每日更新（非即時） |
| 價格 | **免費**（基本會員） |
| API | REST；`dataset=TaiwanStockNews`；Python `requests` 可直接用 |
| 歷史新聞 | 2020-04-01 起 |
| 重大限制 | **單次請求僅限一天資料**（需逐日迴圈）；無情緒分數；無事件分類；僅提供標題+連結，全文需另行抓取 |
| 回測可用性 | 中等：需自行逐日抓、全文另取、自行做情緒/事件分類 |

**欄位範例**：`date, stock_id, title, description, source, link`

API 呼叫範例：
```python
requests.get("https://api.finmindtrade.com/api/v4/data",
  params={"dataset":"TaiwanStockNews","data_id":"2330","start_date":"2023-01-01"})
```

**來源**：[FinMind Others](https://finmind.github.io/tutor/TaiwanMarket/Others/)、[FinMind llms-full.txt](https://finmind.github.io/llms-full.txt)

---

### 13. TWSE OpenAPI + MOPS 公開資訊觀測站重大訊息
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | TWSE 每日新聞公告；MOPS 重大訊息（法律強制揭露：盈餘、董事會決議、重大契約等） |
| 台股/中文支援 | **是，原生繁體中文**；官方來源 |
| 延遲 | 即時（MOPS 重大訊息在公告後數分鐘內上線） |
| 價格 | **免費**（政府開放資料） |
| API | TWSE OpenAPI：`https://openapi.twse.com.tw/v1/swagger.json`（143 個 endpoint）；MOPS：非官方 API，需 POST 爬蟲 `https://mops.twse.com.tw/mops/web/ajax_t51sb10` |
| 歷史新聞 | TWSE 新聞有歷史（CSV 下載）；MOPS 歷史公告可回溯 |
| 限制 | MOPS 無官方 REST API；需自建爬蟲；速率限制嚴格（需遵守 robots.txt） |
| 回測可用性 | **高**：重大訊息是真正的 material event，是最接近「台股事件偵測」所需原始信號的來源 |

**來源**：[data.gov.tw TWSE News](https://data.gov.tw/en/datasets/11546)、[MOPS 重大訊息爬蟲 Medium](https://medium.com/wuthmax/python%E6%8A%93%E5%8F%96%E5%85%AC%E9%96%8B%E8%B3%87%E8%A8%8A%E8%A7%80%E6%B8%AC%E7%AB%99%E9%87%8D%E5%A4%A7%E8%A8%8A%E6%81%AF%E5%B0%87%E7%B5%90%E6%9E%9C%E5%AF%AB%E4%BF%A1%E9%80%9A%E7%9F%A5-917bbfc11c13)

---

### 14. 鉅亨網（CNYES/Anue）
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 台股、美股、外匯、期貨、基金；即時財經新聞 24/7 |
| 台股/中文支援 | **是，繁體中文財經新聞主力** |
| 延遲 | 即時 |
| 價格 | 無官方開發者 API；**非官方抓取**：`https://api.cnyes.com/media/api/v1/newslist/category/headline`（GET） |
| 歷史新聞 | 可回溯，但歷史深度需自行驗證；非官方存取 |
| 授權 | **無官方開發者授權**；爬蟲可能違反服務條款；僅供研究參考 |
| 限制 | 無官方 API；速率限制；ToS 風險 |

---

### 15. TEJ 台灣經濟新報
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 台、中、港、韓、日全區；股票、總體、ESG；新聞情緒數據（2018 年起，30,000+ 筆）；負向事件研究 |
| 台股/中文支援 | **是，最完整的台股專業資料庫**；已有量化情緒指數（TCRI −3 到 +3） |
| 延遲 | 即時更新 + 歷史 |
| 價格 | **機構/學術定價**；無公開價格；需洽 TEJ；學術版透過大學圖書館訂閱；個人無法單買 |
| API | TEJ API（Python/R）；TEJ PRO 桌面版；TQuant Lab |
| 歷史新聞 | 有，2018 年起情緒數據；更早的新聞文本亦有 |
| 回測可用性 | **最高**：有量化情緒分數、回測引擎（TQuant）、台股完整標的 |
| 缺點 | 價格不透明；個人無合適方案 |

**來源**：[TEJ 官網](https://www.tejwin.com/)、[TEJ API](https://api.tej.com.tw/)

---

### 16. Fugle 富果 API
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 台股即時行情、歷史 OHLCV、股務事件（除權、發股） |
| 台股/中文支援 | **是**；原生台股 |
| 延遲 | 即時（WebSocket） |
| 價格 | 免費（基本）；開發者：NT$1,499/月；進階：NT$2,999/月 |
| 新聞支援 | **無**：僅行情與股務事件，沒有新聞 API |

**來源**：[Fugle Pricing](https://developer.fugle.tw/docs/pricing/)

---

### 17. MoneyDJ
| 項目 | 內容 |
|------|------|
| 覆蓋範圍 | 台股財經新聞、研究報告；中文 |
| 台股/中文支援 | **是** |
| API | 無官方 API；需爬蟲；ToS 風險同上 |

---

## 三、開源 / LLM 事件與情緒 NLP

### 18. FinBERT（ProsusAI）
| 項目 | 內容 |
|------|------|
| 模型 | BERT 在金融語料預訓練 + 情緒分類微調（英文） |
| 台股/中文支援 | **不支援中文**；英文財經文本 |
| 授權 | Apache 2.0（開源） |
| HuggingFace | [ProsusAI/finbert](https://github.com/ProsusAI/finBERT) |
| 適用 | TSM ADR（英文新聞）可用；台股中文不適用 |

---

### 19. 中文金融 BERT（hw2942）
| 項目 | 內容 |
|------|------|
| 模型 | `bert-base-chinese` 微調於中文金融新聞情緒（2,000 樣本訓練集） |
| 台股/中文支援 | **是**：繁/簡中文金融文本 |
| 效能 | 下載量 14,692/月；無公開 benchmark 數字 |
| 授權 | 未指定（HuggingFace 上公開） |
| HuggingFace | [hw2942/bert-base-chinese-finetuning-financial-news-sentiment-v2](https://huggingface.co/hw2942/bert-base-chinese-finetuning-financial-news-sentiment-v2) |
| 限制 | 訓練集小（2k）；無 Taiwan 特定驗證 |

---

### 20. 台灣金融 FinBERT（學術研究）
| 項目 | 內容 |
|------|------|
| 研究 | 2025 年 Springer 論文：BERT 在台股新聞 + PTT 討論版（Stock 板）微調；準確率 90.62% |
| 資料集 | Taiwan 0050 成分股新聞（2021–2023，38,918 篇）+ PTT 每日情緒 |
| 公開性 | **學術論文**；模型/資料集未公開發布（需聯繫作者或重建） |
| 意義 | **可行性已驗證**：台股中文 FinBERT 是可建立的 |

**來源**：[Springer 論文](https://link.springer.com/article/10.1007/s10791-025-09515-3)

---

### 21. FinGPT（AI4Finance Foundation）
| 項目 | 內容 |
|------|------|
| 模型 | LLaMA2-7b/13b + ChatGLM2-6B，LoRA 微調於金融情緒；開源 |
| 台股/中文支援 | **ChatGLM2 基底**（中文支援強）；但訓練資料以英文金融新聞+推特為主 |
| 效能 | F1 87.62%（情緒）、95.50%（標題分類）；中文台股未具體驗證 |
| 成本 | 自建訓練 < $300 on RTX 3090 |
| GitHub | [AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) |
| 授權 | MIT（開源） |
| 台股方案 | 可以 ChatGLM2-6B 為基底，在 FinMind+MOPS 中文語料上 LoRA 微調 → 最具彈性 |

---

### 22. LLM Zero-Shot 事件分類
| 項目 | 內容 |
|------|------|
| 方法 | 用 GPT-4/Claude/Llama3 + prompt，zero-shot 分類新聞為「重大崩跌觸發事件」類別 |
| 台股/中文支援 | **GPT-4/Claude 中文理解強**；可直接用於鉅亨/MOPS 中文新聞分類 |
| 成本 | API 呼叫費；批次跑歷史 token 費用需計算 |
| 優點 | 不需標注資料；快速原型；可自定義事件分類 taxonomy |
| 缺點 | 速度慢（逐筆推論）；成本高（大量歷史新聞）；非結構化輸出需後處理 |
| 研究依據 | 已有論文驗證 zero-shot LLM 在金融新聞分類的可行性（[Frontiers 2025](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1608365/full)） |

---

## 四、結構化比較摘要

| 來源 | 台股/中文 | 即時 | 歷史回測 | 情緒/事件分析 | 費用 | 可行性評估 |
|------|-----------|------|----------|----------------|------|------------|
| **MOPS 重大訊息** | ✅ 原生 | ✅ | ✅ 多年 | ❌ 需自建 | **免費** | ⭐⭐⭐⭐ 高：最關鍵的 material events |
| **FinMind TaiwanStockNews** | ✅ 繁中 | ❌ 每日 | ✅ 2020+ | ❌ 需自建 | **免費** | ⭐⭐⭐⭐ 高：現成台股新聞最易入手 |
| **TEJ** | ✅ 台股專業 | ✅ | ✅ | ✅ 有情緒分數 | 機構定價 | ⭐⭐⭐⭐⭐ 最完整，但個人不可行 |
| **中文 FinBERT（hw2942）** | ✅ 中文 | N/A | N/A | ✅ 情緒分類 | **免費** | ⭐⭐⭐ 中：小樣本，需驗證 |
| **FinGPT（ChatGLM2 微調）** | ⚠️ 可微調 | N/A | N/A | ✅ | **低成本自建** | ⭐⭐⭐⭐ 高彈性：需語料+GPU |
| **LLM Zero-shot（GPT-4/Claude）** | ✅ 強 | ✅ | ⚠️ 成本高 | ✅ | API 費 | ⭐⭐⭐ 中：原型好但規模化貴 |
| **TWSE OpenAPI** | ✅ | ✅ | ✅ | ❌ | **免費** | ⭐⭐⭐ 補充：官方公告 |
| **RavenPack** | ⚠️ 有限 | ✅ | ✅ 20年+ | ✅ | $100k+/年 | ⭐ 企業才可行 |
| **LSEG Workspace** | ⚠️ 有限 | ✅ | ✅ 1996+ | ✅ | $20k+/年 | ⭐ 企業才可行 |
| **Alpha Vantage** | ❌ 美股主 | ✅ | ⚠️ | ✅ | $50–$250/月 | ❌ 台股不適用 |
| **Finnhub** | ❌ ADR限 | ✅ | ⚠️ | ⚠️ | 免費起 | ❌ 台股本地不適用 |
| **Tiingo** | ❌ 美股限 | ✅ | ⚠️ 3個月 | ❌ | $30/月 | ❌ 台股不適用 |
| **Polygon** | ❌ 美股主 | ✅ | ✅ | ❌ | $29+/月 | ❌ 台股不適用 |
| **鉅亨/MoneyDJ** | ✅ 最豐富 | ✅ | ⚠️ | ❌ | 爬蟲風險 | ⭐⭐⭐ 有風險，需法律評估 |
| **Bloomberg** | ✅ | ✅ | ✅ | ✅ | $24k+/年 | ⭐ 企業才可行 |

---

## 五、結論：台股事件偵測是否已有現成堪用方案？

### 核心答案：**存在可用基礎，但沒有「開箱即用」的完整解決方案，有明確缺口需自建**

**可用的部分（可立即組合）：**

1. **資料來源端**：FinMind `TaiwanStockNews`（免費，2020+，繁中，個股可查）+ MOPS 重大訊息（免費爬蟲，官方 material events）+ TWSE OpenAPI（官方公告）。三者合計已覆蓋台股最關鍵的 news + events 原始文字。

2. **NLP 端**：HuggingFace `hw2942/bert-base-chinese-finetuning-financial-news-sentiment-v2`（中文金融情緒，開箱可用）；或 GPT-4/Claude zero-shot 分類（正確率更高但每筆有 API 費）。

**缺口（需自建）：**

- **MOPS 歷史批量擷取**：無官方 bulk API，需自建爬蟲 + 歷史爬蟲（有速率限制和 ToS 風險）。
- **全文文本**：FinMind 只提供標題+連結；全文需另行抓取各新聞源。
- **情緒→市場事件的 label 對應**：現有開源模型訓練於「正/負/中性」，對「是否為引發大跌的 macro/geo 事件」（如關稅、地緣衝突、Fed 決策）需重新定義 taxonomy 並微調。
- **即時推播**：FinMind 無即時；MOPS 有即時但需輪詢；商業即時服務（RavenPack/Bloomberg）個人不可行。
- **回測覆蓋範圍**：FinMind 新聞資料僅 2020+ 起；如果要在 2018 回測起點使用，覆蓋不全。

**對現行 live 策略（0050 + MA200 overlay）的具體建議路徑：**

若目標是「比 MA200 更早偵測到大跌」，最可行的自建路徑是：

1. **MOPS 重大訊息輪詢**（免費）：每 5 分鐘爬一次，關鍵詞觸發（「財務危機」、「交易停止」、「重大虧損」）→ 即時警示，成本接近零。
2. **FinMind 每日新聞 + 中文 FinBERT 情緒**（免費）：批次算出 0050 成分股加權情緒分數，與價格信號疊加，低成本且 walk-forward 可跑 2020+ 回測。
3. **若需更廣的 macro 新聞**（地緣、Fed、關稅）：鉅亨非官方 API 或 newsdata.io（89 語言、有中文）作為補充，或用 LLM zero-shot 分類英文 Finnhub/Alpha Vantage（針對 TSMC ADR 的宏觀事件）。

「完全商業化即時中文台股情緒 API」（等同 RavenPack 覆蓋台灣本地媒體）目前**不存在個人可負擔的方案**——這是真實缺口。TEJ 最接近但個人無法直接訂購。

---

**所有來源連結**

- [RavenPack News Analytics](https://www.ravenpack.com/products/edge/data/news-analytics)
- [RavenPack APAC Research](https://www.ravenpack.com/research/news-sentiment-apac)
- [WRDS RavenPack](https://wrds-www.wharton.upenn.edu/pages/about/data-vendors/ravenpack/)
- [LSEG Machine Readable News](https://www.lseg.com/en/data-analytics/financial-news-service/machine-readable-news)
- [LSEG Eikon 停服通知](https://www.lseg.com/en/data-analytics/products/eikon-trading-software)
- [LSEG DJ 多年合作](https://www.lseg.com/en/media-centre/press-releases/2024/lseg-and-dow-jones-announce-a-multi-year-data-news-and-analytics-partnership)
- [Alpha Vantage Premium](https://www.alphavantage.co/premium/)
- [Finnhub](https://finnhub.io/)
- [Marketaux](https://www.marketaux.com/)
- [Tiingo Pricing](https://www.tiingo.com/about/pricing)
- [QuantConnect Tiingo News Feed](https://www.quantconnect.com/docs/v2/writing-algorithms/datasets/tiingo/tiingo-news-feed)
- [EODHD TW Exchange](https://eodhd.com/exchange/TW)
- [APITube Pricing](https://apitube.io/pricing)
- [newsdata.io datasets](https://newsdata.io/datasets)
- [FinMind Others 文件](https://finmind.github.io/tutor/TaiwanMarket/Others/)
- [FinMind llms-full.txt](https://finmind.github.io/llms-full.txt)
- [TWSE News 政府開放資料](https://data.gov.tw/en/datasets/11546)
- [MOPS 重大訊息爬蟲教學](https://medium.com/wuthmax/python%E6%8A%93%E5%8F%96%E5%85%AC%E9%96%8B%E8%B3%87%E8%A8%8A%E8%A7%80%E6%B8%AC%E7%AB%99%E9%87%8D%E5%A4%A7%E8%A8%8A%E6%81%AF%E5%B0%87%E7%B5%90%E6%9E%9C%E5%AF%AB%E4%BF%A1%E9%80%9A%E7%9F%A5-917bbfc11c13)
- [TEJ 台灣經濟新報](https://www.tejwin.com/)
- [Fugle 行情定價](https://developer.fugle.tw/docs/pricing/)
- [hw2942 中文金融 FinBERT](https://huggingface.co/hw2942/bert-base-chinese-finetuning-financial-news-sentiment-v2)
- [台灣金融 FinBERT 論文 Springer](https://link.springer.com/article/10.1007/s10791-025-09515-3)
- [FinGPT GitHub](https://github.com/AI4Finance-Foundation/FinGPT)
- [LLM 股市 AI 綜述 Frontiers 2025](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1608365/full)
- [鉅亨網 API 爬蟲教學](https://blog.jiatool.com/posts/cnyes_news_spider/)

---

# 附錄 D：DIY 爬蟲可行性（完整研究）

# 台股新聞爬取＋事件偵測管線：DIY 可行性深度評估

**評估日期**：2026-06-17｜評估員：Claude Code（deep-research）

---

## 一、各來源查證結果（Part A）

### 1. 鉅亨網（Anue/CNYES）

**技術可行性：高**

- 非官方 JSON API 端點已被社群逆向工程，可直接 GET：
  - `https://api.cnyes.com/media/api/v1/newslist/category/tw_stock`
  - `https://api.cnyes.com/media/api/v1/newslist/category/headline?page={p}&limit=30&startAt={unix}&endAt={unix}`
- 支援 `startAt`/`endAt`（Unix 時間戳）分頁，每頁最多 30 篇，有 `last_page` 讓批次可估總量。
- **歷史深度**：文件記載**兩年限制（"時間範圍有限定兩年內"）**，再往前是否有資料未知。
- **ToS / 法遵**：無公開 API 授權。所有教學文章均聲明「僅供個人教育學習，切勿商業用途」。網站為動態渲染（JS），全文需 Playwright/Selenium，標題層可直接 JSON。
- **Rate limit**：未正式文件化，建議隨機延遲。
- **RSS**：無證據顯示鉅亨有公開 RSS Feed，以 API 為主。

**參考**：[jiatool 教學](https://blog.jiatool.com/posts/cnyes_news_spider/)｜[Cupoy 工作坊](https://www.cupoy.com/collection/00000180B6E4E37F000000026375706F795F72656C656173654355/00000181EB6621200000000E6375706F795F72656C656173654349)

---

### 2. FinMind — TaiwanStockNews

**技術可行性：高（官方支援，免費層）**

- 官方 dataset 名：`TaiwanStockNews`（消息面分類）
- **歷史深度：自 2020-04-01 起**
- 查詢方式：`GET https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockNews&data_id=2330&start_date=2020-04-01`
- 欄位：`date, stock_id, description, link, source, title`
- **限制**：每次查詢**僅能取單一日**（single day per request）＝批次回撈 1500 天至少 1500 次請求；免費層 300 req/hr（付費 600/hr）。
- **ToS**：官方 API，有明確授權，免費層可研究使用。
- **補充**：另有 `TaiwanStockSuspended`（停牌公告）、`TaiwanStockDayTradingSuspension`、`TaiwanStockMarginShortSaleSuspension` 等監管公告類資料集，均為官方支援。

**參考**：[FinMind 官方文件](https://finmind.github.io/llms-full.txt)｜[GitHub](https://github.com/FinMind/FinMind)

---

### 3. TWSE RSS / MOPS 重大訊息 OpenAPI

**技術可行性：中（歷史深度問題是關鍵障礙）**

- **TWSE RSS**：存在，僅提供「證交所新聞」單一 Feed，用途限「使用者閱讀」，版權歸新聞合法權利人，**不適合自動抓取建資料庫**。
- **MOPS 重大訊息網頁爬取**：
  - 端點：`https://mops.twse.com.tw/mops/web/ajax_t51sb10`（POST）和 `ajax_t05st01`（歷史版）
  - 參數：`year`（民國年）、`month1`、`begin_day`、`end_day`（以 ROC 紀元輸入）
  - **歷史深度**：MOPS 介面有「歷史重大訊息」查詢選項，社群實驗可查到 ROC 107 年（2018）以前，但**無法確認能否回溯至 2010/2015**（官方未文件化下限）。
  - **重大障礙**：GitHub 上有已知 Python gist 明確標示「此版本**會被證交所主機擋**，無法正常使用，僅供示範」——TWSE 積極防止自動化爬取重大訊息 API。
  - **TWSE OpenAPI（openapi.twse.com.tw）**：以交易、財務、ESG 數據為主（143 個工具），有提及重大訊息但為當日 rolling snapshot，**非歷史存檔**。
  - **Apify 第三方代理**：`nexgendata/taiwan-mops-company-announcements` 可取得結構化重大訊息，但定價 **$300/1000 筆**，且同樣基於 TWSE rolling snapshot，無長期歷史。

**參考**：[TWSEMCPServer](https://github.com/twjackysu/TWSEMCPServer)｜[Apify MOPS actor](https://apify.com/nexgendata/taiwan-mops-company-announcements/api/mcp)｜[Medium MOPS 教學](https://medium.com/wuthmax/python%E6%8A%93%E5%8F%96%E5%85%AC%E9%96%8B%E8%B3%87%E8%A8%8A%E8%A7%80%E6%B8%AC%E7%AB%99%E9%87%8D%E5%A4%A7%E8%A8%8A%E6%81%AF%E5%B0%87%E7%B5%90%E6%9E%9C%E5%AF%AB%E4%BF%A1%E9%80%9A%E7%9F%A5-917bbfc11c13)

---

### 4. Google News RSS（關鍵字搜尋）

**技術可行性：低（ToS 風險＋無歷史）**

- 可構造 URL 如：`https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-TW&gl=TW&ceid=TW:zh` 或 `rss/search?q=台股+崩盤`
- **每個 feed 最多回傳 100 篇**，均為近期文章，**無法取得歷史存檔**。
- 2024 年起 URL 包裝成 base64 Google redirect，需額外 HTTP 解碼。
- **ToS 明確限制**：僅限「個人非商業閱讀」，自動化蒐集建立資料庫違反 Google 服務條款；undocumented 端點使用可能觸發 CAPTCHA 或封鎖。
- **結論**：僅適合每日即時監看（5 分鐘/每半小時輪詢），**完全不可用於歷史回測**。

**參考**：[wprssaggregator 指南](https://www.wprssaggregator.com/google-news-rss-feed/)

---

### 5. MoneyDJ 理財網

**技術可行性：低（無公開 API，ToS 不明）**

- MoneyDJ 有 RSS 說明頁面（wiki），但無公開 RSS 端點清單。
- 無開發者 API 文件，無公開新聞 API。
- 網站動態載入，爬全文需 JS 渲染工具。
- ToS 無法線上取得，無授權資訊。
- 社群教學幾乎為零，維護成本高。
- **結論**：不建議投入，性價比遠低於 FinMind + CNYES。

---

### 6. 經濟日報（聯合報系）

- 聯合知識庫（UDN）有付費新聞資料庫（商業授權），可機構採購。
- 無公開爬蟲/RSS/API，公開搜尋功能有反爬機制。
- 歷史新聞存檔完整（可至 2000 年代），但**需商業授權合約**，非自建方案。
- **結論**：若要歷史回測，這是唯一有完整存檔的商業路線，但費用高、談判複雜。

---

### 7. PTT 股板情緒

**技術可行性：中（技術可行，信號雜訊比存疑）**

- PTT 有公開 web 版（ptt.cc），可用 requests + cookies（傳年齡確認 cookie）繞過驗證，BeautifulSoup 解析文章標題。
- 目標看板：`/bbs/Stock/`（股票板），`/bbs/Gossiping/`（八卦板財經文）。
- **歷史深度**：PTT 文章有長達 10–15 年的存檔，技術上可爬回 2010 年代，但體量大（每日數百篇）。
- **已有工具**：社群有 PTT 情緒指標小工具（pttstock.com），但為消費品，非 API。
- **關鍵問題**：PTT 股板情緒是短線散戶噪音，對中長線崩盤風險訊號**信雜比極低**；研究文獻顯示台股散戶情緒指標 Granger 因果性弱，僅在牛市較顯著。

---

## 二、開源台股財經新聞爬蟲（Part B）

查到的開源專案以**價格/數據爬蟲**為主，**純新聞爬蟲幾乎空白**：

| 專案 | 資料類型 | 新聞支援 | 活躍度 |
|---|---|---|---|
| [FinMind/FinMind](https://github.com/FinMind/FinMind) | 50+ 台股數據集含 TaiwanStockNews | 有（官方 API 包裝） | 高 |
| [m80126colin/news-fetch](https://github.com/m80126colin/news-fetch) | 台灣新聞爬蟲 | Apple Daily（停刊）為主 | 低/停更 |
| [ga642381/Taiwan-Stock-Crawler](https://github.com/ga642381/Taiwan-Stock-Crawler) | TWSE 股價歷史 | 無 | 低 |
| [Asoul/tsec](https://github.com/Asoul/tsec) | 上市上櫃股票爬蟲 | 無 | 低 |
| [HsinHeng/TaiwanStockCrawler](https://github.com/HsinHeng/TaiwanStockCrawler) | 股價即時 | 無 | 低 |
| [yutingshih/stockspider](https://github.com/yutingshih/stockspider) | 股價+財報 | 無 | 低 |

**結論**：無現成、可直接複用的台股財經新聞爬蟲開源專案。最接近的是 FinMind 的 `TaiwanStockNews` wrapper，但底層資料 2020 年才開始，且每日一次 API 限制。自建 cnyes 爬蟲技術門檻低，但 ToS 灰色地帶。

---

## 三、歷史回測可行性：明確裁決（Part C）

這是**最關鍵的判斷**：

### 各來源歷史深度總表

| 來源 | 歷史深度 | 可程式批次下載 | walk-forward OOS 可行性 |
|---|---|---|---|
| FinMind TaiwanStockNews | **2020-04-01 起** | 是（每次一天，慢） | **部分可行（2020–2026，約 6 年）** |
| Cnyes API | **近 2 年**（限制） | 灰色地帶 | **不可行**（太短，無法覆蓋 2008/2015/2018 崩盤） |
| MOPS 重大訊息 | 技術上含歷史，但主機封鎖 | **被 TWSE 主機攔截** | **不可行** |
| TWSE OpenAPI | 僅當日 rolling snapshot | 否（無歷史） | **不可行** |
| Google News RSS | 僅近期 ~100 篇 | ToS 違規 | **完全不可行** |
| 聯合知識庫（付費） | 2000 年代起 | 需商業授權 | 理論可行但高門檻 |
| PTT 股板 | 10–15 年存檔 | 技術可行 | 技術可行，但信噪比存疑 |

### 核心結論

> **回測結論（明確）：以現有免費/低成本方案，「新聞訊號」無法做滿足本專案紀律的 walk-forward OOS 驗證。**

具體原因：
1. **FinMind TaiwanStockNews**：起始 2020-04，能覆蓋 2020 新冠崩盤、2022 熊市，共約 6 年。但缺乏 2008、2015、2018 等歷史崩盤，OOS 期間僅一個完整熊市週期，**統計功效不足以裁決訊號**。
2. **Cnyes**：2 年限制意味著永遠是 rolling window，無法固定歷史集，**in-sample/OOS 邊界無法固定**，根本無法做 walk-forward。
3. **MOPS**：即使歷史存在，TWSE 主機積極封鎖自動化爬取，維護成本極高且不穩定。
4. **付費授權（聯合知識庫）**：最現實的完整歷史方案，但需商業採購，超出本專案規模。

---

## 四、管線架構設計（Part B，供參）

若接受「僅能驗證 2020–2026 短窗口」的限制，最小可行架構如下：

```
[擷取層]
  FinMind TaiwanStockNews API（每股每日批次）
  + Cnyes /newslist/category/tw_stock（關鍵字層，今日起算）
         ↓
[過濾/分類層]
  關鍵字黑名單（「崩盤」「熔斷」「停牌」「強制平倉」「暴跌」「系統性風險」...）
  → 命中 → LLM 二次分類（是否引發大跌：YES/NO）
         ↓
[LLM 分類器：Claude Haiku 4.5]
  每篇標題 ~50 tokens，每日約 200–500 篇台股新聞
  成本：500 篇 × 100 tokens × $0.50/MTok（batch） = $0.025/日 ≈ $9/年
         ↓
[風險訊號生成]
  崩盤風險評分（0–1）= LLM 判定正例數 / 總篇數（當日）
  可選：加權源（MOPS 重大訊息權重 > 鉅亨一般新聞）
         ↓
[接進 bot]
  main.py APScheduler → 每日收盤後執行
  若訊號 > threshold → 強化 MA200 overlay（如：regime_action 從 0.85 → 0.70）
  或作為 0050 overlay 的「第二道防線」（新聞惡化 AND 跌破 MA200）
```

---

## 五、LLM 分類成本（Part D）

| 模型 | 標準價（input/output per MTok） | Batch（50% off） |
|---|---|---|
| Claude Haiku 4.5 | $1.00 / $5.00 | **$0.50 / $2.50** |
| Claude Sonnet 4.6 | $3.00 / $15.00 | $1.50 / $7.50 |
| Claude Opus 4.7 | $5.00 / $25.00 | $2.50 / $12.50 |

**對本用途的成本估算**（標題分類，非全文）：
- 台股每日新聞量：約 300–800 篇（含各股）
- 每篇 prompt 約 100 tokens（標題 + 少量 context），output 約 5 tokens（YES/NO/UNCERTAIN）
- Haiku 4.5 batch：500 篇 × 105 tokens × $0.50/MTok = **$0.026/日 = $9.5/年**
- 完全可接受，即使用 Sonnet 也只 $28.5/年。

**FinBERT 中文財經版本**：
- 學術研究已有「台灣金融 BERT」預訓練模型（論文稱 accuracy 90.62%），可在 HuggingFace 搜尋 `chinese-finbert` 或相關 checkpoint。
- 本地部署零 API 成本，但需 GPU/推理資源，且需標注資料 fine-tune。
- **對本專案**：Haiku API 更務實（免標注、免部署、即用），FinBERT 留作進階。

**參考**：[CloudZero 定價指南](https://www.cloudzero.com/blog/claude-api-pricing/)｜[Caylent Haiku 4.5 深度解析](https://caylent.com/blog/claude-haiku-4-5-deep-dive-cost-capabilities-and-the-multi-agent-opportunity)

---

## 六、主要風險清單

| 風險 | 嚴重性 | 說明 |
|---|---|---|
| **回測窗口太短** | **致命** | FinMind 新聞僅 2020 起，無法覆蓋多個完整熊市週期，OOS 統計功效不足，無法通過本專案 walk-forward gate |
| **CNYES API 不穩定** | 高 | 非官方端點，cnyes 可能隨時更改結構或封鎖；2 年窗口無歷史研究價值 |
| **MOPS 主動封鎖** | 高 | TWSE 積極阻擋自動化爬取重大訊息，已有明確失敗案例記錄 |
| **ToS 法遵** | 中–高 | CNYES、Google News 均明確限制商業/自動化用途，個人研究灰色地帶 |
| **假陽性過高** | 中 | 台股每日有大量一般財報/公司新聞，崩盤關鍵字過濾假陽性率高；「聯準會升息」不一定今天崩 |
| **延遲** | 中 | FinMind 為 T 日更新（批次），即時性不如 RSS；崩盤往往在盤中，T+1 訊號意義有限 |
| **維護負擔** | 中 | 多來源爬蟲需持續維護（HTML 結構變動、API 變更），比純 FinMind 量化數據高 10× |
| **LLM 分類錯誤** | 低–中 | Haiku 批次在標題分類上可信，但「暴跌」新聞 ≠ 繼續跌，direction accuracy 仍有限 |

---

## 七、可行性總裁決

### 技術可行性：可（FinMind + Cnyes 組合）

管線技術上可在 1–2 週內建出 MVP，主要用 FinMind 官方 API + cnyes 非官方 API，成本幾乎為零（僅 LLM 約 $10/年）。

### 回測可行性：**不可行（在本專案紀律下）**

> **最關鍵結論：此方向在本專案「walk-forward OOS + 純快取」紀律下無法驗證。**

- 可用歷史資料最遠 2020-04（FinMind），僅 6 年、1 個熊市週期。
- 無法對 2008、2015、2018 崩盤做 OOS 驗證，統計功效不足以確認「新聞訊號是否真能提早偵測崩盤」。
- 訊號若無法通過 walk-forward gate → 依 CLAUDE.md 鐵則，live 全不動。
- 即使 FinMind 資料夠長，「回溯爬取 6 年新聞」本身也有實際困難（每次一天的限制 = 需 ~2000 次請求，需約 3–7 天批次），且資料品質（標題是否代表市場衝擊？）未知。

### 建議優先順序

1. **現在**：維持現有 0050+MA200-85% overlay（已通過 R5 裁決的防禦有效性）。
2. **若要進行新聞研究**：先用 FinMind TaiwanStockNews 批次下載 2020–2026 全量標題，做**事後研究（ex-post）**，檢驗新聞訊號與後續 5–10 日報酬的相關性（Granger causality），**不先接進 live bot**。
3. **若 ex-post 研究顯示顯著 signal**：再討論是否值得採購聯合知識庫（2000 年代起）以做完整 walk-forward；或接受「短 OOS 窗口＋額外不確定性」的交換條件。
4. **MOPS 重大訊息**：在 TWSE 不封鎖的前提下，可做為 live 即時警報（崩盤發生後的確認），但不宜作為預測訊號。

---

## 資料來源

- [鉅亨網 Cnyes 爬蟲教學](https://blog.jiatool.com/posts/cnyes_news_spider/)
- [FinMind 官方 API 文件（llms-full.txt）](https://finmind.github.io/llms-full.txt)
- [FinMind GitHub](https://github.com/FinMind/FinMind)
- [TWSE MCP Server（169 工具）](https://github.com/twjackysu/TWSEMCPServer)
- [Apify MOPS 重大訊息 Actor](https://apify.com/nexgendata/taiwan-mops-company-announcements/api/mcp)
- [Medium MOPS 爬蟲實作](https://medium.com/wuthmax/python%E6%8A%93%E5%8F%96%E5%85%AC%E9%96%8B%E8%B3%87%E8%A8%8A%E8%A7%80%E6%B8%AC%E7%AB%99%E9%87%8D%E5%A4%A7%E8%A8%8A%E6%81%AF%E5%B0%87%E7%B5%90%E6%9E%9C%E5%AF%AB%E4%BF%A1%E9%80%9A%E7%9F%A5-917bbfc11c13)
- [MOPS 重大訊息 GitHub gist（已確認被封鎖）](https://gist.github.com/imrexhuang/1423e74fe72838f4660cabaf32f94ce6)
- [Google News RSS 實務指南](https://www.wprssaggregator.com/google-news-rss-feed/)
- [Claude API 定價 2026](https://www.cloudzero.com/blog/claude-api-pricing/)
- [Haiku 4.5 成本分析](https://caylent.com/blog/claude-haiku-4-5-deep-dive-cost-capabilities-and-the-multi-agent-opportunity)
- [台灣財經 BERT 研究論文](https://link.springer.com/article/10.1007/s10791-025-09515-3)
- [台股新聞情緒預測研究（ScienceDirect）](https://www.sciencedirect.com/science/article/pii/S1029313217301707)
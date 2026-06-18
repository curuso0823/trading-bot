# E4 / E5 並排比較：MA200 Overlay 的「第二道防線」早期偵測兩方案

> # 🟥 裁決：**FAILED（E4、E5 雙敗）** — live 一律不動
>
> **結構 Gate FAIL + alpha Gate FAIL → 總 Gate 未過；R5「無 alpha、0050 報酬王」未翻案。本檔＝失敗性研究記錄（candidate 篩選），非部署決策。**
>
> | 方案 | 結構 Gate | alpha Gate | 特有 Gate | 總裁決 |
> |---|---|---|---|---|
> | **E4**（純 OR 閘：vol-spike OR from-peak） | **FAIL**（⑤ whipsaw：2022 flips 1→5） | **FAIL**（IRvs0050 −0.31） | **FAIL**（牛市少賺 −8.8pp vs 0050） | 🟥 **FAILED** |
> | **E5**（K-of-N 組合閘 + 外資票） | **FAIL**（③ DD 未改善 −31.0% + ⑤ whipsaw：2022 fold flips 1→31） | **FAIL**（IRvs0050 −0.24） | 外資票無貢獻＝E5-① **FAIL**；唯 E5-②「組合閘比 OR 閘壓低牛市假觸發」**PASS** | 🟥 **FAILED** |
>
> - **唯一可 OOS 驗證的崩盤（2022）上，E4/E5 都沒省 DD、反增 whipsaw**；最亮賣點（2020 初跌補盲區、早 31 交易日）落在 **in-sample**，此 expanding window 結構上**無法 OOS 驗證**（見 §3 死穴）。
> - 漂亮的 IR vs 基準B（+1.1）**是 beta 不是 alpha**（0050 自身 IRvsB=+1.00）；真 alpha（同 beta 的 IRvs0050）兩者皆負。
> - 若日後仍要走「結構防禦/降盲區」：**E5 > E4**（組合閘壓假觸發奏效），但**須移除外資票 S4 + 早期層加自身 N 日確認**解 whipsaw 死穴後再跑正式 walk-forward——現版仍不可落地。

> **產生方式**：多 agent workflow（2 沙盒 agent 各自建構並執行 E4 / E5 細網格 + walk-forward，1 綜整 agent 重跑驗證並比較）。每個沙盒**純快取、0 API**（僅 `bm.load_adjusted_0050()` 讀本地 pickle + `pd.read_pickle` 讀 0050 外資籌碼 pkl，無任何 fetcher 網路呼叫）、**不改任何既有檔**（src / config / live / 既有 notebook、docs 的 git diff 為空），引擎邏輯本地複製、退化點 byte-identical。
> **本綜整 doc 的數字＝SYNTHESIS agent 親自重跑兩 notebook 的真實 stdout**（`.venv/bin/python notebooks/e4_second_line.py`、`notebooks/e5_combination_gate.py`，兩者 exit 0、全 assert 過）。與兩 build agent 的回報**逐項核對一致**（少數細節差異已於 §8 標明，一律以重跑為準）。
> **回測窗**：full = 2018–2025（含 2016 起暖身算 MA200/rv60/from-peak）；資料證明＝**2433 列、2016-01-04 ~ 2025-12-31**（0050 還原日線）＋ 外資 Foreign_Investor **1944 列、2018-01-02 ~ 2025-12-31**。**OOS（前進）= [2022, 2023, 2024, 2025]** expanding window。
> **定位**：E4/E5 是「在 current-live MA200 overlay **之上疊加第二道防線/組合閘**、**不改 MA200 本體**」的早期偵測研究——目標：補「初跌無保護」盲區（MA200 滯後：2020 跌 −14% 才觸發每日版、現行連 3 日+1% 帶版更遲到 −19%；2022 −11%），同時量化牛市代價。承 `docs/EVENT_DETECTION_RESEARCH.md` §2「雙層確認」/ §4（E4/E5 列）/ 附錄 B Part B.2 假訊號表，與 §5 walk-forward OOS Gate。
> **紀律鐵則**：總 Gate（R5 / EVENT_DETECTION §5）未過前，**live 配置（`config/settings.yaml`：MA200 + regime_action 0.85 + confirm 3 / band 1%）一律不動**。本文是 **candidate 篩選/失敗性記錄、非部署決策**。
> **survivorship 上界（不可消除）**：FinMind 此 stack 無下市/歷史成分、0050 為單一存續 ETF → 所有 DD / lead-time / Sharpe 數字皆為**上界**。「降回撤」效益若有偏差是**偏樂觀**（這反而讓「防禦非 alpha」的結論更穩）。
> **R5 定論不可違**：誠實/被動池**無顯著前瞻 alpha**；E4/E5 一律定位為**結構性降回撤/降盲區候選**，**不得宣稱 alpha**。

---

## 🟥 一句話總結（先看這個）

- **兩方案的 alpha 都顯著 FAIL（如預期，與 R0–R5 / E1–E2 一致）**：真 alpha 檢定（同 beta 的 **IR vs 0050**）E4 −0.31、E5 −0.24，皆負；OOS Sharpe 對 0050 的邊際 E4 +0.041 / E5 +0.062，**都 ≪ δ=0.513**。漂亮的 IR vs 基準B（E4 +1.11、E5 +1.14）**是 beta 不是 alpha**（鐵證：0050 買持自身 IR vs 基準B = +1.001＝純 beta、零技巧）。
- **兩方案的「結構 Gate」也 FAIL**：E4 卡在 **⑤ whipsaw 惡化**（2022 flips 1→5）；E5 卡在 **③ DD 未改善（−30.5%＝持平不嚴格優）+ ⑤ whipsaw 大惡化（2022 fold flips 1→31）**。早期層是「瞬時」訊號（vol-spike / from-peak 逐日閃動、未經自身 N 日確認）→ 必然爆增曝險態翻轉與換手（交易 105→158/188）。
- **唯一站得住的「組合閘設計奏效」訊號＝E5-②**：E5（K-of-N 組合閘）相對 E4（純 OR 閘）**確實壓低牛市假觸發**（牛市早期觸發天數 109→85[K2]→40[K3]、牛市曝險態 flips 47→29→11），且崩盤保護不顯著差。**但這只證「組合閘比 OR 閘乾淨」，不改變「整體不過結構 Gate、無 alpha」的結論。**
- **外資票（S4）無貢獻**（E5-① FAIL）：含外資 − 無外資 ΔOOS Sharpe **+0.012（≪δ）**、ΔDD −0.3pp → 外資票**至多中性**（不拖累也不貢獻），與 R-attrib「籌碼層 standalone 跨 K 變號＝不穩」一致。S4 在牛市 True 天數高達 288/3 年＝雜訊源，靠 K-of-N 取 min 才沒拖垮。
- **2020 初跌盲區「補上了」——但這是 in-sample、未經 OOS 驗證**：E4/E5 在 0050 僅跌 −6.5% 時即早期出（vs MA200 連 3 日版 −19.1% 才動），早 **31 個交易日**（約一個半月）。**但 2020 落在 expanding window 的訓練段，此窗結構上無法 OOS 驗證此改善**（見 §3 死穴）。
- **建議**：E4/E5 **皆不值得帶去落地**；R5「無 alpha、0050 報酬王」未翻案。若仍要在「結構防禦/降盲區」框架下繼續，**E5 比 E4 更值得**（組合閘壓假觸發奏效），但**應移除外資票 S4**（無貢獻），且早期層必須先加自身確認（補 E1/E2 式 N 日/band）以解 whipsaw 死穴——否則永遠卡 Gate⑤。

---

## 1. 並排比較表：E4 vs E5 vs 三基準（關鍵指標）

> **選點原則（鐵則#7）**：兩方案的細網格 OOS Sharpe 皆為平坦高原（見 §4），**不得用 in-sample OOS Sharpe 峰值當「最佳」採用**。下表主列＝**walk-forward per-fold 選參（Calmar 主規則）**的 pooled OOS（這是主裁），另列**穩健 plateau pick（固定主版小參數、非 per-fold 重選）**與深砍變體當參考。三基準為**預先指定、compute-once**（絕不 best-of-sweep、絕不引用污染的 12.7%/1.16/−16%）。

| 策略 / 對照 | 全期年化 | 全期Sharpe | 全期maxDD | 全期Calmar | OOS Sharpe | OOS年化 | 最差前進年DD | IR vs B (β) | IR vs 0050 (α) | 執行交易數 |
|---|---|---|---|---|---|---|---|---|---|---|
| **0050 買持（報酬王 / α 基準）** | 20.0% | 1.01 | −34.0% | 0.59 | **0.947** | **20.3%** | −34.0% | +1.001 | **+0.000** | — |
| 基準B（vol0.011, 無 overlay） | 14.7% | 0.90 | −32.2% | 0.46 | 0.798 | 13.5% | −32.2% | +0.000 | −1.001 | — |
| **current-live（MA200 連3+1% −85%）** | 19.0% | 1.01 | −30.5% | 0.62 | **1.003** | 20.4% | **−30.5%** | +1.156 | −0.118 | **105** |
| **walk-fwd E4（calmar 主規則）** | — | — | — | — | 0.988 | 19.9% | −30.5% | +1.113 | **−0.311** | — |
| walk-fwd E4（sharpe robustness） | — | — | — | — | 0.971 | 19.4% | −30.5% | +1.039 | −0.470 | — |
| E4 穩健 plateau pick C5 (M1.5+fp−8%,10) | 18.2% | 1.00 | −30.5% | 0.60 | 0.974 | 19.2% | −30.5% | +1.078 | −0.528 | 165 |
| E4-deep（C5 參數，雙確認→70%） | — | — | −30.4% | — | 1.016 | 19.6% | −30.4% | +1.241 | −0.309 | 180 |
| **walk-fwd E5（calmar 主規則）** | — | — | — | — | **1.008** | 19.9% | −30.5% | +1.142 | **−0.241** | — |
| walk-fwd E5（sharpe robustness） | — | — | — | — | 1.006 | 20.1% | −30.7% | +1.222 | −0.240 | — |
| E5 穩健 plateau pick（主版固定 K2/VR1.5/FP0.06/PK20/FN3/M0.85） | 18.4% | 1.00 | −31.0% | 0.59 | 0.995 | 19.8% | −31.0% | +1.168 | −0.344 | 158 |
| E4（OR 閘 S2\|S3, −85% ; E5 notebook 內口徑）※ | 18.1% | 1.00 | −31.0% | 0.59 | 0.958 | 18.8% | −31.0% | +1.018 | −0.641 | 188 |

> ※ **E4 兩種口徑**：上半「walk-fwd E4 / 穩健 C5」來自 **e4_second_line.py**（早期訊號獨立狀態機、R_hold=3 退出確認、態層 OR 合成）。最後一列「E4（OR 閘 S2|S3）」是 **e5_combination_gate.py** 為了與 E5 公平對照而用的**純 OR 閘**（無狀態機、無 R_hold、瞬時 min 合成）——故其交易數 188、IRvs0050 −0.641 比 e4_second_line 的 C5（165 / −0.528）更差、更「裸」。**兩者都 FAIL，差異不影響任何 Gate 結論**；比較 E4 vs E5 時，主用 e4_second_line 的 walk-fwd/C5 列。

**判讀（δ = 0.513）**：
- 所有 E4/E5 變體 OOS Sharpe（0.958–1.016）vs current-live 1.003 的差**全埋在 δ 雜訊內**＝風險調整報酬與現行 overlay **統計打平、無分辨力**。
- **沒有任一變體 OOS 年化超過 0050（20.3%）+ δ**；對 0050 全期報酬一致小輸（早期出 15% 在牛市少跟）。
- E4/E5 比 current-live **多 53–83 筆交易**（105 → 158[E5]/165[E4-C5]/188[E4-OR]）＝早期層的真實換手成本，**OOS 無對等回報**。

---

## 2. 兩方案的機制差異（接地）

| 維度 | **E4 — 第二道防線（早期出場）** | **E5 — 組合閘（K-of-N）** |
|---|---|---|
| 早期觸發邏輯 | `early = (5d vol-spike: rv5 > M×rv60) OR (from-peak: close 自 trailing-N_win 峰 ≤ −X%)` | `votes = Σ{S1,S2,S3,(S4)} ≥ K`；S1=MA200 每日 raw_below、S2=vol-spike、S3=from-peak、**S4=外資連 FN 日淨賣（只當組合票、絕不單獨）** |
| 訊號數 | 2（vol-spike、from-peak） | 4（含外資）/ 3（無外資 ablation） |
| 合成方式 | **態層 OR**：`final_below = base_below OR early_state`；早期訊號**獨立狀態機**（立即進 reduced、退出須清除連 R_hold=3 日） | **取 min**：`final = min(combined_state, early_factor)`；單防線各砍 15%、同時觸發仍 0.85（≤15%）；早期層**瞬時**（無自身確認） |
| 砍倉檔位 | 主版 85%（出 15%）；深砍變體＝base∧early 雙確認→70% | 主版 85%；V_DEEP 變體＝兩防線同時→70% |
| 早期層自身確認 | **有**（R_hold=3 退出緩衝，但進入仍立即） | **無**（vol-spike/from-peak 逐日閃動直接進 final）→ flips 更爆 |
| 對外資的態度 | 不用 | 只當組合確認一票（做含/不含 ablation 證貢獻） |
| 退化點重現 current-live | ✅ early 全關（M=None,X=None）逐位＝base_exp、equity max\|Δ\| = **0.0e+00 元** | ✅ early 全關（K=99）max\|Δ\| = **0.0e+00 元** |
| 引擎口徑一致性 sanity | base＝exp_combined(3,0.01)＝current-live | (c1) exp_combined(1,0.0) ≡ 引擎 daily overlay max\|Δ\|=0；(c2) exp_combined(3,0.01) 跌破態 ≡ 引擎 `_regime_below(confirm=3,band=0.01)` 逐位 |

**核心設計差異**：E4 把兩個快訊號用 **OR + 獨立狀態機（含退出確認）** 串起來；E5 把四個（含趨勢 S1、籌碼 S4）用 **K-of-N 投票 + 瞬時 min** 串起來。E5 的賣點＝文獻「單訊號假陽性 ~35%、3+ 同時 ~10%」→ **組合閘應比 OR 閘壓低牛市假觸發**（§5 證此成立＝E5-② PASS）；E4 的賣點＝最直接補初跌（vol-spike 最早）。**E5 的代價是早期層無自身確認 → whipsaw 更嚴重（2022 fold flips 31 vs E4 walk-fwd 5）。**

---

## 3. 崩盤整治：2018 / 2020 / 2022 逐事件（明標 in-sample vs OOS）

> ### ⚠️⚠️ 方法論死穴（最重要，務必納入任何後續判讀）
> walk-forward FWD=[2022,2023,2024,2025]＝**expanding window，2018–2021 永遠在 in-sample 訓練段**。
> → **2018 Q4 崩盤 [IS]、2020 COVID V 崩 [IS]、2022 慢熊 [唯一 OOS 前進窗崩盤]、2023–25 牛 [OOS]。**
> **E4/E5 主打要補的「2020 初跌盲區」落在 in-sample，此窗結構上無法做 OOS 驗證**——2018/2020 的任何「改善」（DD 縮、報酬增、lead-time）**只能是 descriptive / ex-post in-sample 觀察、不得當 OOS 證據**。
> **walk-forward OOS 實際只能檢定「加 E4/E5 是否惡化 2022 + 牛市(2023–25)」。** 兩 notebook 已於頭尾與各事件列醒目標示。

### 3a. 逐事件 stress 表（報酬 / 年內 maxDD / flips；標 IS vs OOS）

| 策略 | 2018Q4 ret/DD/flips **[IS]** | 2020COVID ret/DD/flips **[IS]** | **2022 慢熊 ret/DD/flips [OOS]** |
|---|---|---|---|
| 0050 買持 | −5.5% / −16.0% / — | +30.2% / −28.2% / — | −21.9% / −34.0% / — |
| 基準B（vol0.011） | −7.8% / −16.4% / — | +21.6% / −24.9% / — | −24.1% / −32.2% / — |
| **current-live** | −6.9% / −15.1% / 5 | +26.9% / −27.3% / 2 | **−19.4% / −30.5% / 1** |
| E4 C5 (M1.5+fp−8%,10) | −7.3% / −15.4% / 9 | +28.9% / **−25.9%** / 8 | −19.6% / −30.5% / **5** |
| E4 C6 (M2.0+fp−10%,10) | −7.5% / −15.4% / 7 | +27.3% / −26.6% / 6 | −19.4% / −30.5% / 1 |
| E4-deep (C5,→70%) | −7.3% / −15.3% / 9 | +28.3% / **−25.2%** / 8 | −19.6% / −30.4% / 5 |
| E4 OR 閘（E5 nb 口徑） | −7.8% / −15.4% / 9 | +28.8% / −26.1% / 10 | −20.1% / −31.0% / 9 |
| E5 K=2 主版（含外資） | −7.7% / −15.4% / 9 | +28.4% / −26.1% / 8 | −19.9% / −31.0% / 7 |
| E5 K=3（含外資） | −7.3% / −15.4% / 7 | +27.0% / −27.3% / 4 | −19.6% / −30.7% / 1 |
| E5 K=2 無外資（N=3） | −7.3% / −15.4% / 7 | +26.7% / −27.5% / 8 | −19.6% / −30.7% / 1 |
| E5 K=2 V_DEEP（同觸 70%） | −9.3% / −16.1% / 26 | +26.1% / **−25.4%** / 16 | −19.3% / **−29.3%** / 38 |

**逐事件解讀**：

- **2018 Q4 [IS, descriptive]**：早期訊號**使 flips 上升**（current-live 5 → E4/E5 主版 7–9、V_DEEP 高達 26），年內 DD 幾乎不變（−15.1% → −15.4%）、報酬略降。＝早期層在 2018 主要是**增換手、無實質保護增益**（此年非急崩、MA200 已夠用）。
- **2020 COVID [IS, descriptive]**：這是 E4/E5 唯一「看起來補了盲區」的事件——E4 C5/deep、E5 V_DEEP 把年內 DD 從 −27.3% 壓到 **−25.2 ~ −25.9%**（縮 ~1.4–2.1pp）、報酬 +1.4–2.0pp、Sharpe↑。**但 2020 在 in-sample，這是 ex-post 觀察、不得當 OOS 證據**；代價＝flips 2 → 8（E4 C5）/ 16（V_DEEP）。**注意 E5 K=3 與無外資版的 2020 DD 反而沒改善（−27.3% / −27.5%）**＝K=3 太嚴、初跌時湊不到 3 票，補盲區能力退化。
- **2022 慢熊 [OOS＝唯一前進窗崩盤＝walk-forward 真能裁的崩盤]**：**早期訊號未改善 DD**（current-live −30.5% → E4/E5 主版 −30.5 ~ −31.0%，**持平或略差 0.2–0.5pp**）、報酬幾乎打平（−19.4% → −19.6 ~ −20.1%）、**flips 大增（1 → 5[E4 walk-fwd]/7[E5 K2]/9[E4 OR]/31[E5 walk-fwd 2022 fold]）**。早期出後在反彈段以略低曝險承受續跌 + 再進場成本。**唯 V_DEEP 把 2022 DD 壓到 −29.3%（深砍 30% 換來），代價＝flips 38、2018 報酬更差 −9.3%。** → **這是「補初跌」假說在唯一 OOS 崩盤上的真實成績：沒省到 DD、反而增 whipsaw。**

### 3b. 2020 lead-time（[IS-descriptive / NOT OOS evidence]）

> 錨：2020 峰 2020-01-14 close=20.635。MA200 主錨＝current-live overlay（連 3 日+1% 帶）首入 reduced = **2020-03-16（自峰 −19.1%）**；附錨＝raw 每日 MA200 首破 = 2020-03-12（自峰 −14.0%，DRAWDOWN_EVENT_STUDY「−14% 盲區」基準）。

| 訊號 / 方案 | 2020 首觸發日 | 早於 MA200（連3日版 03-16）幾交易日 | 早觸時自峰跌幅 |
|---|---|---|---|
| vol-spike (M=1.5 與 2.0 同) | 2020-01-30 | **+31** | −6.5% |
| from-peak −8% (N=10) | 2020-03-12 | +2 | −14.0%（恰與 raw 每日 MA200 同日） |
| from-peak −10% (N=10) | 2020-03-13 | +1 | −15.2% |
| **E4 C5 合成（vs OR fp）** | 2020-01-30（vs 主導） | **+31** | −6.5% |
| **E5 主版 K=2（含外資）** | 2020-01-30 | **+31** | −6.5% |
| E5 K=3（含外資） | 2020-02-03 | +29 | −6.8% |
| E4 OR 閘（S2\|S3） | 2020-01-30 | +31 | −6.5% |

**lead-time 解讀**：
- **vol-spike 是補初跌的真主力**——在 0050 僅跌 −6.5% 時就警報，比 MA200（連 3 日版要跌 −19% 才動）早 **31 個交易日（約一個半月）**。E4 / E5 K=2 / E4 OR 三者 lead-time 相同（皆由 vol-spike 主導 31 日）；**E5 K=3 略晚（29 日）**＝多要一票的代價。
- **from-peak 只在已跌 −14 ~ −15% 才觸發**（早 1–2 日）＝補的是 base 態「連 3 日確認」的延遲、**非真正補初跌**。
- ⚠️ **lead-time n = 1/event、統計力極低、不可外推**；且 2020 全在 in-sample。**「早 31 天」這個亮點數字，恰恰是此窗無法 OOS 驗證的那一個。**
- 2018 Q4 附帶（次要）：early 首觸 2018-10-11、自峰 −11.6%（早於 base 態）。

---

## 4. 牛市代價（2023–25, OOS）：vs current-live 與 vs 0050

> 0050 各年（報酬王基準）：2023 +26.9% / 2024 +49.3% / 2025 +36.9%。

| 策略 | 2023 (vs 0050) | 2024 (vs 0050) | 2025 (vs 0050) | 3 年累計 vs 0050 | 牛市 pooled 年化 |
|---|---|---|---|---|---|
| 0050 買持 | 26.9% (0.0) | 49.3% (0.0) | 36.9% (0.0) | 0.0pp | 39.9% |
| **current-live** | 24.8% (−2.1) | 48.7% (−0.6) | 35.7% (−1.2) | **−3.9pp** | **38.4%** |
| E4 C5 (M1.5+fp−8%,10) | 23.0% (−3.9) | 47.7% (−1.6) | 33.6% (−3.3) | **−8.8pp** | — |
| E4 C6 (M2.0+fp−10%,10) | 24.8% (−2.1) | 44.6% (−4.7) | 35.7% (−1.2) | −8.0pp | — |
| E4-deep (C5,→70%) | 23.0% (−3.9) | 47.7% (−1.6) | 35.5% (−1.4) | — | — |
| E5 K=2 主版（含外資） | — | — | — | — | 37.8% |
| E5 K=3（含外資） | — | — | — | — | 37.7% |
| E5 K=2 無外資 | — | — | — | — | 37.5% |

**牛市代價解讀**：

- **current-live 本身對 0050 已少賺 ~3.9pp/3 年**（−85% 留倉在牛市少跟）——這是 overlay 防禦的「基礎稅」。
- **E4 的牛市代價最大**：C5 累計對 0050 少賺 **−8.8pp**（比 current-live **多犧牲 ~4.9pp**）。元凶＝**敏感的 vol-spike 在牛市回檔多次誤觸**（C5 牛市早期觸發事件數 2023/24/25 = 6/8/7 次），以 85% 跟漲。
- **E5 的牛市代價輕微得多**：K=2 主版牛市年化 37.8% 僅比 current-live 38.4% 低 0.6pp、比 0050 39.9% 低 2.1pp。**這正是組合閘（K-of-N）的價值**——把 vol-spike 的單訊號假觸發用「需湊 K 票」過濾掉（牛市早期觸發天數 E4 OR 109 → E5 K2 85 → E5 K3 40）。
- **方向性（EARLY_MULT 細掃，OOS）**：牛市年化隨早出加深**單調下降**（M=1.0→38.4%、0.85→37.8%、0.7→36.8%、0.55→35.9%）＝純去風險 beta 效果（牛市 ann 與 DD 同步縮）、**非選時 alpha**。

---

## 5. walk-forward OOS 裁決 + plateau（δ ≈ 0.513）

### 5a. walk-forward per-fold 選參（主裁；Calmar 主規則 + Sharpe robustness）

**E4**（candidate C0–C8 + 2 個 R=1 變體＝11 個；DD floor 重錨同族 current-live 同窗 −DD_BAND 0.022；每 fold 11/11 過 floor）：
- calmar per-fold：2022:C5 / 2023:C4 / 2024:C4 / 2025:C0（相異 3 個）→ pooled OOS Sharpe **0.988** / 年化 19.9% / IRvsB +1.113 / IRvs0050 −0.311 / worst-fwd-DD −30.5%。
- sharpe per-fold：2022:C5 / 2023:C4 / 2024:C4 / 2025:C5（相異 2 個）→ pooled **0.971** / IRvs0050 −0.470。
- robustness：Calmar↔Sharpe pooled 差 **0.017 ≤ 0.2 ＝穩**。穩健高原 pick C5 直接套 OOS = 0.974 ≈ walk-forward 0.988 → **選參穩定、非孤峰式翻動**（與 R0 K=150 教訓相反）。

**E5**（108 candidate：K∈{2,3} × VR∈{1.5,1.8,2.2} × (FP,PK)∈{(.05,20),(.07,20),(.09,30)} × {FN3,FN5,noFI} × M∈{.85,.75}；每 fold 108/108 過 floor）：
- calmar per-fold：2022:K2/VR1.8/FP.07/PK20/FN3/M.75 / 2023:同但 M.85 / 2024–25:K2/VR2.2/FP.05/PK20/**noFI**/M.75（相異 3/4）→ pooled OOS Sharpe **1.008** / 年化 19.9% / IRvsB +1.142 / IRvs0050 −0.241 / worst-fwd-DD −30.5%。
- sharpe per-fold：四 fold 全選 K2/VR1.8/FP.07/PK20/FN3/M.85（相異 1/4）→ pooled **1.006** / IRvs0050 −0.240。
- robustness：Calmar↔Sharpe pooled 差 **0.002 ≤ 0.2 ＝穩**。穩健 plateau pick（主版固定）= 0.995。
- **注意**：calmar 規則 2024/2025 fold **選到 noFI（無外資）**＝walk-forward 自己也傾向丟掉外資票，與 §6 ablation 一致。

### 5b. plateau 評估（δ = 0.513；判平滑高原 vs 鋸齒孤峰）

| 方案 | 細網格（單參 ≥12 點） | OOS Sharpe 振幅 | 落 δ 帶內 | 判定 |
|---|---|---|---|---|
| **E4** | M（14 點）/ X（14）/ N_win（14）/ R_hold（5） | M:[0.906,0.991]、X:[0.973,1.008]、N_win:[0.977,1.008]、R_hold:[0.937,0.967] | M 14/14、X 14/14、N_win 14/14、R_hold 5/5 | **平滑高原**（全埋 δ 內、無孤峰） |
| **E5** | VR_THR(14) / FP_DROP(14) / PK_WIN(12) / FN(12) / EARLY_MULT(13) | 振幅 0.032 / 0.050 / 0.035 / 0.037 / 0.073，**全 ≪ δ** | 14/14, 14/14, 12/12, 12/12, 13/13（100%） | **平滑高原**（全埋 δ 內、無孤峰） |

**plateau 的關鍵反讀（兩方案共通）**：細網格全是平滑高原**並非好消息**——它恰恰證明**早期層在 OOS 上「無分辨力」**：不論參數怎麼調，OOS Sharpe 都黏在 ~1.0（current-live 值）附近，差異全在 δ 雜訊內。**＝「加 E4/E5 不改變 OOS 風險調整報酬、只多換手」的訊號，而非「找到好參數」的訊號。** 唯一有方向性的軸是 **EARLY_MULT（深砍）**：M 越小 OOS Sharpe 微升（E5 1.003→1.065、E4-deep 同向），**但那是降曝險的 beta 效果**（牛市 ann / DD 同步縮）、**非 alpha**。**決策只綁 walk-forward OOS，刻意不挑 in-sample 峰。**

---

## 6. beta vs alpha（關鍵：嚴格分離，明標哪個是 beta 哪個是 alpha）

> **鐵證參考線（兩 notebook 皆首先印出）**：0050 買持自身 **IR vs 基準B = +1.001**（純 beta、零技巧）。基準B（vol0.011 無 overlay）是 **de-risked 低曝險** → 任何全曝險策略對它的 IR ≈ +1 都只是 beta 差，**不是 alpha**。

| 指標 | E4 walk-fwd | E5 walk-fwd | current-live | 性質 | 判讀 |
|---|---|---|---|---|---|
| **IR vs 基準B** | **+1.113** | **+1.142** | +1.156 | **BETA（非 alpha）** | ≈ 0050 自身的 +1.001 → 只是 beta 陷阱，**不可當功勞** |
| **IR vs 0050** | **−0.311** | **−0.241** | −0.118 | **真 ALPHA 檢定（同 beta）** | **全為負** → 對報酬王 0050 無任何超額 |
| OOS Sharpe 對 0050 邊際 | +0.041 | +0.062 | +0.056 | alpha 量級 | **≪ δ=0.513** → 不顯著 |

**alpha 判定** ＝ (IR vs 0050 > 0) AND (OOS Sharpe − S0_0050 > δ)：
- **E4：FAIL**（IRvs0050 −0.311 < 0、邊際 +0.041 ≪ δ）。
- **E5：FAIL**（IRvs0050 −0.241 < 0、邊際 +0.062 ≪ δ）。

**結論**：**兩方案 alpha 顯著 FAIL，與 R0–R5 / E1–E2 完全一致。** E4/E5 對 0050 buy-hold 無任何顯著超額；漂亮的 IR vs 基準B（+1.11/+1.14）是 **beta 陷阱**（0050 自身 IRvsB=+1.00 為鐵證）。**E4/E5 定位＝結構性降回撤 / 降盲區 / 降假觸發規則，非 outperformer。R5「無 alpha、0050 報酬王」未翻案。**

---

## 7. §5 Gate 對 E4、E5 逐項裁決

> 主裁＝walk-forward Calmar 主規則。δ=0.513。current-live 基準：OOS Sharpe 1.003、worst-fwd-DD −30.5%、2022 flips 1、OOS 年化 20.4%。基準B worst-fwd-DD −32.2%、0050 −34.0%。

| Gate 項 | E4 | E5 |
|---|---|---|
| ① 對照固定預先指定（基準B+0050，非 best-of-sweep、不引污染數字） | ✔ | ✔ |
| ② walk-forward OOS（FWD pooled 主裁） | ✔ | ✔ |
| ③ 降-DD 不惡化且優於兩被動（worst-fwd-DD） | ✓ −30.5%（= live、> B −32.2、> 0050 −34.0） | **✗** −30.5%（= live，**持平不嚴格優**；E5 主版 −31.0% 反略差） |
| ④ OOS Sharpe 不顯著差於 current-live（δ 帶內） | ✓ 0.988 vs 1.003 | ✓ 1.008 vs 1.003 |
| ⑤ whipsaw / 換手不惡化（2022 flips ≤ current-live 1） | **✗** 2022 flips 5 > 1 | **✗** 2022 fold flips 31 > 1（早期層瞬時開關大惡化） |
| ⑥ 牛市不顯著犧牲（OOS 年化, 容差 1pp） | ✓ 19.9% vs 20.4% | ✓ 19.9% vs 20.4% |
| ⑦ 選參穩定 / plateau（Calmar↔Sharpe 差 ≤ 0.2） | ✓ 差 0.017、相異 3 個 | ✓ 差 0.002、相異 3/4 |
| ⑧ **真 alpha（同 beta vs 0050；預期 FAIL）** | **✗** IRvs0050 −0.311、邊際 +0.041 ≪ δ | **✗** IRvs0050 −0.241、邊際 +0.062 ≪ δ |
| **▶ 結構 Gate（③∧④∧⑤∧⑥）** | **FAIL（卡 ⑤）** | **FAIL（卡 ③ + ⑤）** |
| **▶ alpha Gate（⑧）** | **FAIL（預期）** | **FAIL（預期）** |

### 7a. E4 特有 Gate（research §4：「須證 2022 額外假觸發代價可控」）

| 子項 | 結果 | 裁決 |
|---|---|---|
| E4a — 2022 淨效益（C5：報酬 Δ−0.21pp、年內 DD Δ+0.07pp；逐筆：2022 early 觸發 39 日、多砍 18 天、多 2.0 round-trip、估成本 0.265pp；C6 鈍版 0 多砍/0 RT/0 成本） | 2022 本身淨效益尚可控 | ✓ 可控 |
| E4b — 牛市代價（C5 2023–25 各年 vs live；累計 vs 0050 −8.8pp、比 live 多犧牲 ~4.9pp） | 牛市犧牲過大 | **✗** |
| **E4c — 淨判定** | 2022 可控但牛市代價不可控 | **✗ 早期假觸發代價不可控 → 不採** |

### 7b. E5 特有 Gate（① 改善由組合而非外資單獨；② 比 E4 牛市假觸發更少）

| 子項 | 結果 | 裁決 |
|---|---|---|
| **E5-①（改善由組合 S1–S3 而非外資 S4 單獨驅動）** | 無外資 N=3 達結構準則？ DD 不惡化 **✗**（−30.7% 持平不嚴格優）/ whip **✗**（仍卡）/ 牛市 ✓；含外資不惡化 ✓（ΔSh **+0.012**、ΔDD −0.3pp，皆 < δ／容差） | **FAIL**（無外資版本身不過結構準則；惟外資票確實**至多中性**＝不貢獻也不拖累，與 R-attrib 籌碼層不穩一致） |
| **E5-②a（牛市假觸發比 E4 少）** | 牛市 early 天數 E5 85 < E4 109 ✓；牛市 flips E5 29 ≤ E4 47 ✓ | ✓ |
| **E5-②b（崩盤保護不顯著差）** | 2022 OOS DD E5 −31.0% ≥ E4 −31.0%−1.5pp ✓；2020 lead E5 31 ≥ E4 31−2 ✓[IS-descriptive] | ✓ |
| **▶ E5-②（組合閘 vs OR 閘）** | 組合閘設計奏效 | **PASS** |
| **▶ E5『組合閘價值』⟺ E5-① ∧ E5-②** | E5-① FAIL | **不成立** |

**E5 Gate 重點**：E5 組合閘相對 E4 **確實壓低牛市假觸發（E5-② PASS，組合閘設計奏效）**，但整體仍 **FAIL 結構 Gate（不降 DD、增 whipsaw、無 alpha）**，且**外資票無貢獻（E5-① FAIL）**。

**總定錨**：**兩方案的結構 Gate + alpha Gate + 各自特有 Gate 都未全過 → 總 Gate（R5：對 0050 無顯著 alpha + 無 mandate）未翻案 → live（MA200 + 0.85 + confirm3/band1%）一律不動。**

---

## 8. SYNTHESIS agent 重跑 vs build agent 回報：核對紀錄

SYNTHESIS agent 親自重跑兩 notebook，**所有 Gate-相關與主表數字逐項一致**。少數 build 回報的細節與重跑有極小出入（皆非 Gate-changing、不影響任何結論），一律以**重跑為準**：

1. **E4 main_table 寫 current-live OOS 年化「20.4%」、Part A 表頭顯示「20.0」**：純四捨五入位數差（Part D 精確 20.4% vs Part A 表格欄寬 20.0）。重跑 Part D 確認 **20.4%**。一致。
2. **E5 build 回報 walk-fwd calmar 2022 fold 報酬/flips**：build 寫 2022 選 M0.75；重跑確認 2022:K2/VR1.8/FP.07/PK20/FN3/**M0.75**（ret −19.9% / Sh −1.17 / **flips 31**）、2023:M0.85、2024–25:noFI/M0.75。與 build「2022→M0.75、2023→same but M0.85」**一致**。
3. **E5 build stdout_excerpt 提及 ablation「含外資 −0.344 / 無外資 −0.364」**：重跑 Part D 確認**含外資 IRvs0050 −0.344 / 無外資 −0.364**、ΔOOS Sharpe **+0.012**、ΔDD −0.3pp。一致。
4. **E5 build 回報 K=3 lead-time「2020-02-03、−6.8%、早 29 日」**：重跑逐字確認。一致。
5. **退化/中性 sanity**：E4 early 全關 equity max|Δ| = **0.0e+00**；E5 early 全關（K=99）max|Δ| = **0.0e+00**；E5 引擎口徑 (c1) max|Δ|=0、(c2) 逐位一致。全部 PASS。
6. **cache-proof**：兩 notebook 開頭皆印 **2433 列 / 2016-01-04~2025-12-31**（0050）+ **Foreign_Investor 1944 列 / 2018-01-02~2025-12-31**（E5），確認純快取、0 API。

**結論**：**未發現 build 杜撰；兩 build 回報忠實。** 本 doc 採用的全部數字為 SYNTHESIS 重跑值。

---

## 9. E4 vs E5：誰更值得 + 取捨

| 比較維度 | E4（第二道防線 OR） | E5（組合閘 K-of-N） | 誰勝 |
|---|---|---|---|
| OOS Sharpe（walk-fwd calmar） | 0.988 | 1.008 | E5（但差 ≪ δ＝打平） |
| IR vs 0050（真 alpha） | −0.311 | −0.241 | E5（兩者皆負＝皆 FAIL） |
| worst-fwd-DD | −30.5% | −30.5%（主版 −31.0%） | 打平 / E4 略優 |
| **牛市代價 vs 0050** | **−8.8pp（C5）** | **~−2.1pp（K2 牛市 ann 37.8%）** | **E5（組合閘壓假觸發奏效）** |
| **牛市假觸發天數（3 年）** | 109（OR） | **85（K2）/ 40（K3）** | **E5** |
| whipsaw（2022 flips） | walk-fwd 5 / OR 9 | walk-fwd fold 31 / K3 主版 1 | **E4 略優**（E5 早期層瞬時更爆；惟 K3 主版反而最低） |
| 2020 補盲區 lead-time（IS） | +31 日（vol-spike 主導） | +31 日（K2）/ +29（K3） | 打平（K3 略遜） |
| 2022 OOS DD | −30.5% | −31.0%（K3/無外資 −30.7%） | E4 略優 |
| 訊號乾淨度 / 假陽性壓制 | 低（OR 放大假觸發） | **高（K-of-N 取 min 壓制）** | **E5（設計初衷）** |
| 結構複雜度 / 可維護 | 較簡（2 訊號 + 狀態機） | 較繁（4 訊號 + 投票 + 外資資料依賴 + proxy caveat） | E4 |
| 外資票價值 | N/A | **無貢獻（E5-① FAIL、ΔSh +0.012≪δ）** | — |

**取捨結論**：
- **若硬要選一個帶去做「結構防禦/降盲區」的後續研究：E5 更值得**——其**組合閘確實壓低牛市假觸發（E5-② PASS）**，這是 E4 純 OR 閘做不到的（E4 牛市少賺 −8.8pp vs E5 ~−2.1pp）。E5 把「補初跌的敏感訊號（vol-spike）」用「需湊 K 票」過濾掉牛市雜訊，方向正確。
- **但 E5 必須改兩處才有意義**：① **移除外資票 S4**（無貢獻、增 proxy 風險、牛市 True 天數 288/3 年＝雜訊源）；② **早期層加自身確認**（補 E1/E2 式 N 日確認 / band，把瞬時訊號的 whipsaw 死穴解掉——E5 walk-fwd 2022 fold flips 31 是兩方案最差，正因早期層無確認）。**否則永遠卡 Gate⑤。**
- **E4 的致命傷是純 OR 閘放大 vol-spike 的牛市假觸發**（−8.8pp）＝E5 設計就是為了修這個，故 E4 在「牛市代價/假陽性壓制」上明確劣於 E5。

---

## 10. Recommendation（誠實框架）

**是否值得後續 / 落地：兩者皆不值得落地；R5「無 alpha、0050 報酬王」未翻案。**

1. **總 Gate 未翻案 → live 一律不動。** E4 與 E5 的結構 Gate（卡 whipsaw、E5 另卡 DD 未改善）、alpha Gate（IRvs0050 全負、邊際 ≪ δ）、各自特有 Gate（E4c 牛市代價不可控、E5-① 外資無貢獻）皆未全過。**這是一次乾淨的失敗性記錄**（如 R0–R5 / E1–E2 的預期）。
2. **誠實框架（務必區分兩個問題）**：
   - **結構防禦 / 降盲區**：E4/E5 確實能在 in-sample（2020）大幅提早觸發（早 31 交易日、自峰僅 −6.5% 即警報）＝**補盲區的機制是真的**；E5 組合閘確實壓低牛市假觸發（真的）。**但**（a）此補盲區效益**落在 in-sample、結構上無法用此窗 OOS 驗證**（死穴）；（b）在唯一 OOS 崩盤（2022）上**沒省到 DD、反增 whipsaw**；（c）牛市有實質代價（E4 −8.8pp、E5 ~−2.1pp）。
   - **alpha**：**明確、預期地 FAIL**。IR vs 基準B 的「漂亮 +1.1」是 **beta 陷阱**（0050 自身 = +1.00），真 alpha（IR vs 0050）全負。**E4/E5 不是 outperformer。**
3. **若使用者有明確「降初跌回撤」mandate** 且願承擔牛市代價：**唯一可考慮的方向＝E5 的精簡版（去外資 + 早期層加 N 日確認）**，且**必須再跑一輪正式 walk-forward 確認 whipsaw 死穴已解**（現版未解 → 仍不可落地）。但須誠實認知：**此方向永遠無法 OOS 驗證它最想補的 2020 初跌**（FinMind 此窗結構限制），且**對 0050 報酬仍是淨輸**。
4. **不建議投入 E7（SOX/VIXTWN 外部數據）**：在純快取的 E4/E5 已證「補盲區機制為真但 OOS 不過 Gate、牛市有代價、無 alpha」之後，引入外部 pipeline 的邊際價值低、且仍卡同樣的 OOS 窗限制與 survivorship 上界。

---

## honesty_notes（保留與死穴）

1. **survivorship 上界（不可消除）**：FinMind 此 stack 無下市 / 歷史成分、0050 為單一存續 ETF → 所有 DD / lead-time / Sharpe 為**上界**；且 OOS 僅 2022 一次崩盤、lead-time n=1/event＝統計檢定力極低、**不可外推母體期望**。上界性質反而讓「防禦非 alpha」的結論更穩（真值只會更差）。
2. **2018 / 2020 in-sample 死穴（最重要）**：walk-forward FWD=[2022–2025]＝expanding window → **2018 Q4 與 2020 COVID 永遠在訓練段**。**E4/E5 主打要補的「2020 初跌盲區」（早 31 交易日、−6.5% 警報、2020 DD −27.3%→−25.9%）全部落在 in-sample，此窗結構上無法 OOS 驗證**——這些「改善」只能是 descriptive / ex-post 觀察、**不得當 OOS 證據**。**唯一落在 OOS 前進窗的崩盤＝2022 慢熊，而 E4/E5 在 2022 沒省 DD、反增 whipsaw。** ＝E4/E5 最亮的賣點恰恰是無法驗證的那一個。
3. **beta vs alpha 不可混**：IR vs 基準B 是 **beta 非 alpha**（0050 自身 IRvsB=+1.001 為鐵證）；真 alpha＝IR vs 0050，E4 −0.311 / E5 −0.241 皆負。任何引用「+1.1 IR」當功勞都是 beta 陷阱。
4. **0050 自身外資流＝proxy**（ETF 籌碼 ≠ 全市場外資；已查證快取無全市場法人資料，僅逐檔 ETF/個股 `TaiwanStockInstitutionalInvestorsBuySell`）。外資票經 ablation 證**至多中性**（ΔSh +0.012≪δ、ΔDD −0.3pp），與 R-attrib「籌碼層 standalone 跨 K 變號＝不穩」一致；S4 牛市 True 天數 288/3 年＝靠 K-of-N 取 min 才沒拖垮。
5. **早期層「瞬時」缺陷（E5 尤甚）**：vol-spike（rv5/rv60）、from-peak 逐日閃動、**未經自身 N 日確認** → 最終曝險態 flips 必然遠高於 current-live（E5 walk-fwd 2022 fold 31、E4 OR 牛市 47 vs live 3）；故 Gate⑤ 用「曝險態 flips」必然 FAIL，**n_exec（交易數 105→158/188）為更真實的成本量度**。此為兩方案（尤其 E5）的真實設計缺陷。
6. **深砍變體（E4-deep / E5 V_DEEP →70%）僅附帶測、非主版**：名目 OOS Sharpe 略高（E4-deep 1.016、EARLY_MULT 細掃深砍微升）但**全 ≪ δ ＝雜訊 + beta**（降曝險使牛市 ann/DD 同步縮）；V_DEEP 2022 DD −29.3% 是深砍 30% 換來、代價 flips 38 + 2018 報酬 −9.3%。**不據以採用。**
7. **plateau「平滑高原」是壞消息不是好消息**：兩方案細網格全埋 δ 內＝早期層在 OOS **無分辨力**（不論參數，OOS Sharpe 都黏在 ~1.0），＝「加 E4/E5 不改變 OOS 風險調整報酬、只多換手」的訊號。
8. **E4 兩種 notebook 口徑**：e4_second_line（獨立狀態機+R_hold，C5 交易 165/IRvs0050 −0.528）vs e5_combination_gate 的 E4 OR 對照（瞬時 min，交易 188/IRvs0050 −0.641）——**兩者皆 FAIL，差異不影響任何結論**；比較時主用 e4_second_line。
9. **沙盒紀律**：本研究純沙盒——**未改任何既有檔**（src / config / live / 既有 notebook / docs 的 git diff 為空，僅新增 `notebooks/e4_second_line.py`、`notebooks/e5_combination_gate.py` 與本 doc）、**未 commit、未切 branch**（仍在 `e1e2-whipsaw-overlay`）、**0 API 純快取**。

---

## 相關檔案（絕對路徑）

- E4 notebook：`/Users/cch_0182/trading-bot/notebooks/e4_second_line.py`
- E5 notebook：`/Users/cch_0182/trading-bot/notebooks/e5_combination_gate.py`
- 本比較 doc：`/Users/cch_0182/trading-bot/docs/E4_E5_COMPARISON.md`
- 前置研究 roadmap（E4/E5 出處 + §5 Gate）：`/Users/cch_0182/trading-bot/docs/EVENT_DETECTION_RESEARCH.md`
- 同窗 whipsaw 三方案比較（E1/E2/E3，方法論先例）：`/Users/cch_0182/trading-bot/docs/E1_E3_COMPARISON.md`、`/Users/cch_0182/trading-bot/docs/E1_E2_WALKFORWARD.md`
- 崩盤事件研究（−14% 盲區 / 2022 whipsaw 基線）：`/Users/cch_0182/trading-bot/docs/DRAWDOWN_EVENT_STUDY_2020_2022.md`
- 回測 harness（快取載入 + 三基準 + 引擎）：`/Users/cch_0182/trading-bot/notebooks/benchmark_backtest.py`、`/Users/cch_0182/trading-bot/src/strategy_engines/benchmark_engine.py`
- walk-forward 範本：`/Users/cch_0182/trading-bot/notebooks/e1e2_walkforward.py`、`/Users/cch_0182/trading-bot/notebooks/e1e2_combined_validate.py`
- 0050 外資籌碼快取（E5 用）：`/Users/cch_0182/trading-bot/data/raw/finmind_cache/TaiwanStockInstitutionalInvestorsBuySell__0050__2018-01-01__2025-12-31.pkl`
- 研究紀律與真相：`/Users/cch_0182/trading-bot/CLAUDE.md`、`/Users/cch_0182/trading-bot/docs/PIT_REBUILD_PLAN.md`、`/Users/cch_0182/trading-bot/docs/RESEARCH_JOURNEY.md`

---

*建立 2026-06-18｜SYNTHESIS agent（重跑驗證 E4/E5 + 並排比較）｜性質：candidate 篩選 / 失敗性記錄、非部署決策。總 Gate 未翻案 → live 不動。*

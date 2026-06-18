# E7b — 美股半導體訊號作為「砍倉**深度**調節 / 確認延續」（depth-modulation，非 trigger-modulation）

> **SYNTHESIS doc**（integrates build `notebooks/e7b_depth_modulation.py` ＋ 內建 2 道對抗驗證：S3 look-ahead 四層 falsification、S4 additive 行為中性五軸 ＋ SYNTHESIS agent 獨立重derive）。
> 純快取重跑 verified（`.venv/bin/python notebooks/e7b_depth_modulation.py`，EXIT=0、全 assert 通過；完整輸出存 `logs/e7b_run.out`，runtime 產物、不入版控）。
> **不改 engine / config / live、未 commit、未切 branch（現 `e1e2-whipsaw-overlay`）。**
> 建立 2026-06-18｜性質：實驗裁決（承 E7 §7 建議與 R0–R5／E1–E5 之誠實框架）。

---

## 0. 一句話總裁決

**結構 Gate：FAIL（無一 E7b 變體在 DD-vs-報酬前緣 Pareto 勝過 flat-deep 控制組——這是 E7b 唯一存在理由，未達成）。alpha Gate：FAIL（全 config IRvs0050 < 0、OOS Sharpe−0050 ≪ δ=0.513）。**

E7b 把 E7 的「美股半導體領先」從**砍倉時點**改用在**確認延續**（進場仍由乾淨的 local-MA200 把關、只在已進本地崩盤態時用 US 訊號決定砍倉**深度**），**成功移除了 E7 的「86% 平時假警報反傷」問題**（2020 加深事件數＝0、2022 加深事件僅 3~5 次）。但**決定性控制組 flat-deep（同結構、below 段內無條件砍到 D_deep、不看美股）證明：US-conditioning 沒有加值**——在**相同 D_deep** 下，E7b 的 wfDD **普遍比 flat-deep 更深（更差）**、報酬持平（matched-D_deep ΔDD −0.28pp@D0.70、−0.72pp@D0.50；獨立重derive 逐位吻合）。意即 US 訊號把「加深」用在了**更差的子集**。**R5「無 alpha、0050 報酬王、regime 僅防禦」未被翻案。live（0050 + MA200 N3/band1% 85% overlay）一律不動。**

---

## 1. Verifier 彙整（內建於 build＝硬 assert ＋ SYNTHESIS 獨立重derive）

build 把 verifier 直接嵌入為「FAIL 即 `assert` 停」的硬閘，重跑全數 PASS；SYNTHESIS agent 另以**完全獨立的重實作**核對核心數字（非 import notebook、自寫 sim/exp/對齊），逐位吻合。

| Verifier | 內容 | 結果 |
|---|---|---|
| **S3 — look-ahead（因果對齊，四層）** | (a) 範例日期對齊：對台股交易日 D，貢獻 `us_overnight[D]` 的美股 session 須 < D；(b) corr falsification：美股序列 `shift(-1)`（偷看未來）→ 與 0050 當日報酬相關性須崩；(c) **config-level falsification（E7b 特有）**：US level 整體 `shift(-1)` → 代表 config 的 OOS Sharpe/wfDD/態須改變；(d) 覆蓋率/末對齊日 | **PASS（乾淨）**。日期對齊 6/6 ✓（TW 2022-03-07 ← 美股 2022-03-04；TW 2024-08-05 ← 美股 2024-08-02）。corr 崩：^SOX 0.546→**0.126**、SMH 0.550→**0.152**、QQQ 0.488→**0.112**（皆崩）；TSM 0.515→0.297 殘留＝已記錄的 TW→US 反向回饋（ADR 同日連動），非 bug、且僅 negative-control 不入 config。config-level：偷看未來改變 us_confirm 態 **52 日**、績效微變（SYNTHESIS 獨立重算亦得 **52 日** ✓）。覆蓋率 96.4%、末對齊日 2025-12-31。 |
| **S4 — 行為中性（additive 鐵證，五軸）** | US 訊號關閉/D_deep=0.85 ⇒ 逐位重現 current-live；us_confirm 恆 True ⇒ 重現 flat-deep | **PASS，max\|Δ\|=0**。(0) `exp_combined(1,0.0,0.85)` ≡ 引擎 `simulate_benchmark(overlay,200,0.85)` max\|Δ\|=0；(0b) current-live `exp_combined(3,0.01,0.85)` ≡ E7b `final_exp_depth(D=0.85)` max\|Δ\|=0（交易 105=105）；(1) us_confirm 恆 False（from-peak X=999%／動能 −999%）⇒ E7b(D=0.70) ≡ current-live max\|Δ\|=**0.0**；(2) D_deep=0.85（即使 us_confirm 觸發 1141 日）⇒ ≡ current-live max\|Δ\|=**0.0**；(3) flat-deep 兩實作互證 + flat-0.85 ≡ current-live；(3b) us_confirm 恆 True ⇒ E7b(D) ≡ flat-deep(D) max\|Δ\|=**0.0**。 |
| **SYNTHESIS 獨立重derive** | 不 import notebook，自寫 sim/exp_combined/US 對齊/final_exp_depth，重算 current-live、flat-deep 全曲線、matched-D_deep ΔDD、falsification 態差 | **全吻合**。current-live OOS Sh **1.003**／wfDD **−30.5%**／nx **105**；flat-deep D0.70 Sh **1.065**/wfDD **−27.1%**、D0.60 Sh 1.105/wfDD −24.7%、D0.50 Sh 1.142/wfDD −22.3%；flat-0.85 ≡ current-live max\|Δ\|=0；matched-D_deep（^SOX peak-8%）ΔDD **−0.72/−0.28/+0.00pp**（D 0.50/0.70/0.85，E7b 更深）；falsification 態差 **52 日**。 |

**Verifier blocker 結論：無 look-ahead、無 wiring bug、行為中性嚴格成立（五軸 max\|Δ\|=0）、核心裁決數字經獨立重derive逐位確認。E7b 結果可信（survivorship 上界前提下），裁決無需降級。**

> ⚠️ **唯一非阻斷瑕疵**：執行環境無 `matplotlib`，S-frontier(3) 的前緣 **PNG 圖**未產生（程式 try/except 不阻斷）。但**前緣裁決靠的是 S-frontier(1) 前緣表 ＋ (2) matched-D_deep 控制比較**（皆完整、已驗證），PNG 僅為視覺輔助、非 load-bearing。前緣表已足以裁決，**不影響任何結論**。

---

## 2. 🟥 核心裁決：US-conditioning 是否在 DD-vs-報酬前緣勝過 flat-deep？（E7b 唯一存在理由）

**E7b 的價值命題只有一個**：R6 已掃 0~100% 退場深度、選定 0.85（更深→牛市拖累過大）。所以把 below 段砍更深（flat-deep D<0.85）「DD 更低但牛市更差」是**已知前緣**。**E7b 唯一可能站住＝US-conditioning 在『同樣 DD 改善下犧牲更少牛市』或『同樣牛市代價下 DD 更低』，即 Pareto 支配 flat-deep。**

### 主判＝matched-D_deep 控制比較（乾淨控制變因）

最乾淨的控制：**E7b@D vs flat@D（同一 D_deep）**，唯一差異就是「below 段內 D_deep 是否被 us_confirm 條件化」（E7b 只在 US 確認延續時加深；flat 無條件加深）。

| 在相同 D_deep 下 | E7b wfDD vs flat wfDD | E7b OOS年化 vs flat | 判定 |
|---|---|---|---|
| ^SOX peak-8% @ D=0.50 | **−0.72pp（E7b 更深/更差）** | 持平（Δann +0.01pp） | US 無加值 |
| ^SOX peak-8% @ D=0.70（plateau 主裁點） | **−0.28pp（E7b 更深/更差）** | 持平（Δann −0.01pp） | US 無加值 |
| momentum-8% ^SOX @ D=0.70 | **−2.75pp（E7b 顯著更深/更差）** | 更差（Δann −0.31pp） | US 無加值（更糟） |
| 全 64 點 matched 掃描 | **61/64 E7b 同 D 下 wfDD 更深或持平** | 普遍持平 | — |

- **matched-D_deep『US 加值』點數＝3/64**（fr-SMH-0.50、fr-SMH-0.55、mo-^SOX-0.875）。但這 3 點 **Δann 全貼著 +0.10pp 雜訊地板（≤+0.2pp）、且全在『極淺 D_deep 端』（訊號稀疏、近 current-live）**＝非系統性前緣勝出。
- **其餘 61/64 全『重合/更差』，且 wfDD 普遍比同 D flat 更深。** 機制：US 訊號把「加深」**錯置**——只在「US 確認」的子集加深，但這子集相對「整段 below」並非更危險的子集（甚至更差），所以同樣的曝險預算（D_deep）換到的 DD 改善反而**少於**無條件 flat。
- **SYNTHESIS 獨立重derive 完全確認**：ΔDD = −0.72/−0.28/+0.00pp（D 0.50/0.70/0.85），E7b 在相同深度下 DD 一律不淺於 flat。

### 結論（核心）

**US-conditioning 未系統性打破 flat-deep 前緣。** flat-deep 是 E7b 的「天花板對照」：在 DD-vs-報酬前緣上，E7b 的曲線**落在 flat-deep 曲線之上或重合（同 DD 報酬不更高、同報酬 DD 不更淺）**，且在多數 D 端 E7b 還**更差**（同 D 下 DD 更深）。**E7b 與 flat-deep 同前緣（甚至略劣）＝US-conditioning 零加值＝E7b 唯一存在理由不成立＝FAIL。**

---

## 3. 並排比較表（E7b 代表 vs current-live vs flat-deep 族 vs 兩被動；2018-01-01～2025-12-31，純快取）

固定預先指定基準（**絕不 best-of-sweep、絕不引污染 12.7%/1.16/−16%**）：
- δ（OOS Sharpe 1SE, current-live pooled n=961）= **0.513**（plateau / 顯著性雜訊尺度）；DD_BAND = 2.2pp（DD 軸雜訊）
- OOS Sharpe：**0050 0.947（報酬王）｜基準B 0.798（de-risked beta）｜current-live 1.003**
- 最差前進年 DD：**0050 −34.0%｜基準B −32.2%｜current-live −30.5%**
- **0050 自身 IRvs基準B = +1.001**（純 beta、零技巧）＝**beta 參考線**（walk-fwd 的 IRvsB 高 = beta，**不是 alpha**）

| config | D_deep | 全期年化 | 全期Sh | 全期maxDD | OOS年化 | **OOS Sh** | **wfDD** | IRvsB(β) | **IRvs0050(α)** | 牛市23-25 | 交易 |
|---|:--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **0050 買持**（報酬王/α基準） | — | — | — | — | — | **0.95** | **−34.0%** | +1.00 | 0.00 | **39.9%** | — |
| **基準B**（vol0.011, de-risk/β） | — | — | — | — | — | **0.80** | **−32.2%** | 0.00 | — | 30.5% | — |
| **① current-live**（N3/band1%/0.85） | 0.85 | 19.0 | 1.01 | −30.5 | 20.4 | **1.003** | **−30.5%** | +1.16 | −0.118 | 38.4% | 105 |
| ──族② **flat-deep**（無條件深，控制組）── | | | | | | | | | | | |
| ② flat-deep D=0.50 | 0.50 | 17.1 | 1.02 | −25.2 | 20.9 | **1.142** | **−22.3%** | +1.02 | −0.045 | 35.9% | 104 |
| ② flat-deep D=0.60 | 0.60 | 17.7 | 1.02 | −25.8 | 20.8 | 1.105 | **−24.7%** | +1.14 | −0.054 | 36.6% | 107 |
| ② flat-deep D=0.70（plateau） | 0.70 | 18.2 | 1.02 | −27.1 | 20.7 | 1.065 | **−27.1%** | +1.21 | −0.066 | 37.3% | 104 |
| ② flat-deep D=0.85（≡current-live） | 0.85 | 19.0 | 1.01 | −30.5 | 20.4 | 1.003 | −30.5% | +1.16 | −0.118 | 38.4% | 105 |
| ──族③ **E7b**（US-conditioned，D=0.70 plateau）── | | | | | | | | | | | |
| ③ E7b ^SOX from-peak-8% / D0.70 | 0.70 | 18.7 | 1.04 | −27.3 | 20.7 | 1.057 | −27.3% | +1.23 | −0.065 | 37.9% | 117 |
| ③ E7b SMH from-peak-8% / D0.70 | 0.70 | 18.7 | 1.04 | −27.3 | 20.7 | 1.060 | −27.3% | +1.24 | −0.054 | 37.9% | 118 |
| ③ E7b ^SOX momentum-8% / D0.70 | 0.70 | 18.9 | 1.02 | −29.8 | 20.4 | 1.011 | −29.8% | +1.20 | −0.124 | 37.9% | 117 |
| ③ E7b QQQ from-peak-8% / D0.70（negative-control） | 0.70 | 18.7 | 1.04 | −27.4 | 20.6 | 1.055 | −27.4% | +1.22 | −0.074 | 37.9% | 120 |

**讀法**（全 config plateau 中值 D=0.70、非 in-sample 峰）：
- **DD 面**：E7b D0.70 wfDD −27.3% vs **同 D flat-deep −27.1%**（E7b **略差 +0.2pp**）；momentum E7b −29.8% vs flat-0.70 −27.1%（E7b **明顯差 +2.7pp**）。**E7b 相對其真正的控制組（同 D flat）全不更優、多更差。**（相對 current-live −30.5% 的 +3.2pp「改善」全來自「砍更深」這個 flat 早已掃出的維度，**非 US 訊號**。）
- **alpha 面**：**全 config IRvs0050 介於 −0.045 ~ −0.124（全負）**；OOS Sharpe−0050 = +0.06~+0.11（≪ δ=0.513）。**alpha 一致 FAIL。** IRvsB 都 +1.2 左右＝**beta、非 alpha**（0050 自身 IRvsB=+1.00 已是純 beta 參考線）。
- **negative-control（QQQ）**：QQQ（大盤、非半導體）E7b 與 ^SOX/SMH **幾乎同質**（wfDD −27.4% vs −27.3%、IRvs0050 −0.074 vs −0.065）。**半導體特異性不成立**——若 US-conditioning 真有半導體 edge，QQQ 應顯著較差；實際無差＝任何「改善」都來自 flat 的砍深維度，不是半導體訊號內容。
- **代價**：E7b 交易數 117~120 > current-live 105 / flat-deep 104~107（多 ~12 筆、來自 0.85↔D_deep 來回）。

---

## 4. 崩盤防禦（2018/2020/2022，標 IS/OOS）＋ 牛市-DD 取捨 ＋ 深度 whipsaw

> ⚠️ **2018Q4 與 2020 COVID：walk-forward expanding window 下永在訓練段 ＝ IS（描述性）。唯一 OOS 崩盤 ＝ 2022（n=1 崩盤週期、統計功效低）。** depth-whip ＝某年曝險變動次數（含 0.85↔D_deep 來回）。

| config | 2018報酬/DD (IS) | 2020報酬/DD/深whip (IS) | **2022報酬/DD/深whip (OOS)** | 牛23-25年化 (OOS) |
|---|---|---|---|---|
| 0050 買持 | −5.5% / −16.0% | +30.2% / −28.2% / — | **−21.9% / −34.0% / —** | **39.9%** |
| 基準B | −7.8% / −16.4% | +21.6% / −24.9% / — | **−24.1% / −32.2% / —** | 30.5% |
| **① current-live** | −6.9% / −15.1% | +26.9% / −27.3% / 2 | **−19.4% / −30.5% / 1** | 38.4% |
| ② flat-deep D=0.70 | −7.7% / −14.6% | +23.4% / −26.4% / 2 | **−16.9% / −27.1% / 1** | 37.3% |
| ② flat-deep D=0.60 | −8.2% / −14.8% | +21.2% / −25.8% / 2 | **−15.3% / −24.7% / 1** | 36.6% |
| ③ E7b ^SOX peak-8% / D0.70 | −7.2% / −14.3% | +24.7% / −26.4% / **3** | **−17.9% / −27.3% / 5** | 37.9% |
| ③ E7b SMH peak-8% / D0.70 | −7.2% / −14.3% | +24.7% / −26.4% / **3** | **−17.7% / −27.3% / 5** | 37.9% |
| ③ E7b ^SOX momentum-8% / D0.70 | −6.9% / −15.1% | +26.6% / −26.4% / **3** | **−18.7% / −29.8% / 8** | 37.9% |

**判讀：**
- **牛市-DD 取捨**：flat-deep 把 below 段砍更深，牛市年化 37.3%（D0.70）/36.6%（D0.60）vs current-live 38.4%，換到 2022 DD −27.1%/−24.7% vs −30.5%＝**已知前緣（深↔牛市代價）**。E7b D0.70 牛市 37.9%、2022 DD −27.3%——**落在 flat-deep 同前緣上、不更優**（同 D flat 的 2022 DD 是 −27.1%，E7b −27.3% 反略深）。
- **深度 whipsaw（E7b 特有副作用）**：current-live/flat-deep 的 2022 深度變動＝1（乾淨）；**E7b from-peak 2022 深whip=5、momentum=8**——US 訊號在 below 段內反覆 confirm/un-confirm，導致 0.85↔0.70 來回。**這正是 Gate ⑤ FAIL 的原因**（深度層 whipsaw 惡化）。below 態本身仍 1 flip（進場由乾淨 local-MA200 把關，未惡化），但**疊上的深度層引入了新 whipsaw**。
- **2018/2020（IS）**：E7b 與 flat-deep DD 互有微小高低、無系統性優勢；2020 加深事件＝0（見 §5）。

---

## 5. 🟥 深度調節事件研究（E7b 核心機制）＋ walk-forward OOS ＋ plateau ＋ beta-vs-alpha

### (a) 加深事件研究（below_local 段內 us_confirm False→True 加深日，後續續跌=划算 vs 反彈=反傷）

事件＝E7b 相對 flat-0.85/current-live 多砍（0.85→D_deep=0.70，多砍 15pp）的時點，砍在 open[T+1]，量 open[T+1]→close[T+1+k] 前向路徑：

| 代表 config | 加深事件 n | 分層 | fwd5 均值 | fwd10 均值 | 淨效益(fwd10) | 2022(OOS) 淨(fwd10) | 結論 |
|---|:--:|---|---|---|---|---|---|
| ^SOX peak-8% | **3** | 2022×2 + other×1 | −1.04% | **+1.49%** | **−0.224pp** | **−0.197pp** | **反傷（fwd10 反彈）** |
| SMH peak-8% | **3** | 2022×2 + other×1 | −1.04% | +1.49% | −0.224pp | −0.197pp | 反傷 |
| ^SOX momentum-8% | **5** | 2022×4 + other×1 | −0.32% | −0.15% | +0.023pp | **+0.283pp** | 全體小划算、2022 划算 |

**核心發現（呼應 E7 §7 假說與 DRAWDOWN 研究）：**
1. **E7 的「86% 平時假警報反傷」確實被移除**：進場由乾淨 local-MA200 把關 → **2020 加深事件＝0**（不再砍進 V 型急彈）、加深事件總數從 E7 的 263 降到 **3~5**。假說的「移除假警報稀釋」部分**成立**。
2. **但加深事件 n 極少（3~5）＝統計功效極低**，且**from-peak 在 2022 OOS 段反傷**（fwd10 +1.32% → 多砍 15pp 反讓你少賺 −0.197pp；因為 from-peak-8% 觸發點偏早，砍後 0050 短線反彈）；**momentum 在 2022 小划算（+0.283pp）但代價是深whip=8 + matched-D 下 DD 比 flat 深 2.75pp**。
3. **關鍵**：即使「移除假警報」後，**同 D_deep 下 E7b 加深的時點仍不如 flat 無條件加深乾淨**——US confirm 的子集不是「整段 below 中更危險的子集」，所以條件化反而**浪費了曝險預算**（§2 matched-D_deep）。

### (b) walk-forward OOS（主裁；FWD=[2022,2023,2024,2025] expanding，per-fold 在 [2018,Y-1] 以 Calmar 主+Sharpe robustness 選 D_deep，DD floor 重錨 current-live−DD_BAND，永不固定 fallback）

| 目標 | sel22/23/24/25 (Calmar) | pooled OOS Sh | OOS年化 | wfDD | IRvsB(β) | **IRvs0050(α)** | empties |
|---|---|--:|--:|--:|--:|--:|:--:|
| flat-deep (no US) | 0.95/0.65/0.65/0.65 | 0.948 | 18.8 | −32.8 | +0.93 | **−0.436** | 0 |
| E7b from-peak ^SOX | 0.90/0.50/0.50/0.50 | 0.993 | 19.4 | −31.6 | +1.01 | **−0.255** | 0 |
| E7b from-peak SMH | 0.90/0.50/0.60/0.50 | 0.991 | 19.3 | −31.6 | +1.00 | **−0.265** | 0 |
| E7b momentum ^SOX | 0.50/0.50/0.50/0.50 | 1.019 | 20.3 | −28.8 | +1.20 | **−0.123** | 0 |
| E7b from-peak QQQ (control) | 0.85/0.50/0.50/0.50 | 1.011 | 19.6 | −30.5 | +1.05 | **−0.220** | 0 |

- pooled OOS Sharpe 全落 **0.948~1.019**——**全在 current-live 1.003 的 δ=0.513 帶內**，無一顯著勝出。
- **IRvsB 全 +0.9~+1.2（beta）；IRvs0050 全負（−0.123 ~ −0.436）＝真 alpha 一致 FAIL。**
- **per-fold 選參不穩**：flat-deep 與 E7b 在 fold 22 選 0.85~0.95、其後跳到 0.50（最深端）＝**「DD 越深 in-sample Calmar 越好」的角點效應**，無穩健 D_deep（與 R0 K=150 教訓同型；正因如此 plateau 不固定）。E7b 與 flat-deep **選參型態幾乎相同**＝US 訊號未帶進可辨識的選參結構。
- **walk-forward 下 E7b 與 flat-deep 同帶（Sh 0.95~1.02），E7b 未在主裁上勝出。**

### (c) plateau（δ 判平滑高原 vs 鋸齒孤峰）

- us_confirm 軸（各 flavor × ^SOX/SMH，12 點）OOS Sharpe **全距僅 0.037~0.084，全 ≲ δ=0.513 ⇒ 平滑高原**；D_deep 軸（16 點）全距 0.035~0.175，亦平滑。
- plateau pick（直接套 OOS 的 D_deep=0.70 中值）與 walk-forward 動態選參結果 **5/5「一致」**——無 cherry-pick 風險，但**「整片平原 ≈ current-live」正是「訊號沒帶進可辨識 OOS 邊際」的徵狀**（同 E7：看似 robust，實為「無論什麼參數 E7b 都 ≈ flat-deep 同 D」）。

### (d) beta vs alpha（鐵則、勿誤引）

walk-forward 的 IRvsB ≈ +1.2 是 **beta 不是 alpha**——鐵證＝**0050 買持自身 IRvsB = +1.00**（純 beta、零技巧）。真 alpha 檢定 = 同 beta 的 **IRvs0050，E7b 全 config < 0**（−0.045 ~ −0.436）；OOS Sharpe−0050 = +0.06~+0.11 ≪ δ=0.513。**E7b 與 R0–R5／E1–E5／E7 一致：無顯著 alpha。**

---

## 6. §5 Gate 逐項裁決 ＋ E7b 特有 Gate（②–⑩，全 AND；重錨同族 current-live + 兩被動；鐵則 #8 絕對 floor 退役）

逐 config 裁決摘要（✓/✗ 取自 S12；plateau D=0.70 主裁點）：

| config | ②降-DD不惡化且優於兩被動 | ③OOS Sh 不顯著差 live(δ帶) | ④牛市不犧牲 | ⑤**whipsaw不惡化(含深度層)** | ⑥alpha(IRvs0050>0 ∧ Sh−0050>δ) | ⑦**加深可交易性**(fwd10淨>0) | ⑧🟥**前緣勝flat-deep**(matched-D) | ⑨牛市≥對應flat-D | ⑩**綜合結構 Gate** |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|---|
| E7b ^SOX peak-8% / D0.70 | ✓(−27.3) | ✓ | ✓ | **✗(深whip 5 vs flat 1)** | ✗ | **✗(−0.224pp 反傷)** | **✗(ΔDD −0.28pp 更深)** | ✓ | **FAIL** |
| E7b SMH peak-8% / D0.70 | ✓(−27.3) | ✓ | ✓ | **✗(深whip 5 vs flat 1)** | ✗ | **✗(−0.224pp 反傷)** | **✗(ΔDD −0.28pp 更深)** | ✓ | **FAIL** |
| E7b ^SOX momentum-8% / D0.70 | ✓(−29.8) | ✓ | ✓ | **✗(深whip 8 vs flat 1)** | ✗ | ✓(+0.023pp; 2022 +0.283pp) | **✗(ΔDD −2.75pp 更深)** | ✓ | **FAIL** |

**逐項解讀：**
- **② 降-DD**：全 ✓「不惡化且優於兩被動」——但**「優於」全靠 current-live/flat-deep 砍深已優於被動；E7b 相對其真正控制組（同 D flat）不更優**（②過不代表前緣勝出，⑧才是）。
- **③ OOS Sharpe / ④ 牛市**：全 ✓（在 δ 帶內、牛市 vs live 不犧牲）——這是「沒變差」、**不是「變好」**（整片 plateau ≈ flat-deep 同 D）。
- **⑤ whipsaw（含深度層）**：**全 ✗**。below 態 22flips=1（未惡化，進場乾淨）；但**深度層 whip 5~8 ≫ 同 D flat 的 1**＝US 條件化在 below 段內反覆切換深度＝新 whipsaw。
- **⑥ alpha**：**全 FAIL**（IRvs0050 全負、Sh 邊際 ≪ δ）——預期內，未翻案。
- **⑦ 加深可交易性**：from-peak **✗（fwd10 全體 −0.224pp 反傷、2022 −0.197pp）**；momentum ✓（但 ⑤⑧ 已掛）。「移除假警報」後加深在 from-peak 仍反傷（觸發偏早、砍後反彈）。
- **⑧ 🟥前緣勝 flat-deep（matched-D_deep，E7b 唯一存在理由）**：**全 ✗**。同 D 下 ΔDD −0.28pp（from-peak）/ −2.75pp（momentum）＝E7b **更深（更差）**、報酬持平＝**US-conditioning 零系統性加值**。
- **⑩ 綜合結構 Gate**：**無一 PASS（全 FAIL）**，全卡在「⑧ 前緣未勝 flat-deep」＋「⑤ 深度 whipsaw 惡化」。

> **§5 Gate 總裁決：結構 Gate 全 FAIL（卡 ⑧ 前緣未勝 flat-deep + ⑤ 深度 whipsaw），alpha Gate 全 FAIL。** 對照 E1+E2 通過「結構 Gate PASS / alpha FAIL」——E1+E2 是**修 current-live 自身 whipsaw**（同一本地訊號的確認/緩衝微調）故過結構 Gate；**E7b 是疊加外部訊號做深度條件化，但同 D 下不如 flat 無條件加深乾淨，且引入深度 whipsaw**＝連結構 Gate 都沒過（與 E7 同命：外部訊號換不到可辨識的淨好處）。

---

## 7. Recommendation（誠實框架）

**不建議落地、不建議列入後續主線。R5「無 alpha、0050 報酬王、regime 僅防禦」未被翻案。** 理由：

1. **E7b 唯一存在理由（在 DD-vs-報酬前緣 Pareto 勝過 flat-deep）未達成。** matched-D_deep 控制比較鐵證：同 D_deep 下 E7b 的 wfDD 普遍**更深（更差）**、報酬持平（ΔDD −0.28pp@D0.70、−2.75pp momentum；SYNTHESIS 獨立重derive逐位確認）。**US-conditioning 把「加深」用在更差的子集＝零加值。**
2. **negative-control（QQQ）與 ^SOX/SMH 同質**＝半導體特異性不成立；任何相對 current-live 的「改善」都來自 flat-deep 早已掃出的「砍更深」維度，**不是 US 訊號內容**。
3. **E7b 確實移除了 E7 的「86% 平時假警報反傷」**（進場由乾淨 local-MA200 把關、2020 加深事件＝0）——**這是 E7b 相對 E7 唯一誠實可記錄的進步**；但移除假警報後，from-peak 加深在 2022 OOS 仍反傷、momentum 雖小划算卻引入深度 whipsaw（8 次）且 matched-D 下 DD 更深。**「乾淨進場」沒能讓「條件化加深」勝過「無條件加深」。**
4. **alpha 全 FAIL**（IRvs0050 全負、Sh 邊際 ≪ δ），與 R0–R5／E1–E5／E7 完全一致。

**若使用者仍想要更低的崩盤 DD（明確 drawdown mandate）**：**直接用 flat-deep（無條件砍更深，如 D=0.70 或 0.60），不要 US-conditioning**——flat-deep 在前緣上**支配或等於** E7b（同 DD 報酬不更低、且無深度 whipsaw、無外部資料相依、更簡單）。但 flat-deep 本身也只是「沿已知 深↔牛市 前緣移動」、非 alpha，且牛市代價真實（D0.70 牛市 37.3% vs current-live 38.4% vs 0050 39.9%），**是否要更深 overlay 是風險偏好抉擇、非績效改善**。**現階段 live（0050 + MA200 N3/band1% 85% overlay）不動。**

---

## 8. Honesty notes（caveats）

- **survivorship 無法消除 ＝ 所有結果是【上界】**：FinMind 此 stack 0050 無下市、美股為 ADR/ETF/指數**存續樣本**（^SOX/SMH/QQQ/TSM 都活到今天）。真實含倒閉/下市只會更差。
- **2018Q4 / 2020 COVID 永在訓練段 ＝ IS**：walk-forward expanding window 下它們永遠在 [2018,Y-1] 訓練段。**唯一 OOS 崩盤 ＝ 2022（n=1 崩盤週期）**——加深事件研究/前緣的 2022 段是**單一週期、統計功效極低**（加深事件僅 n=3~5）；2020 的「無假警報」是 IS 描述性。
- **「賣在跳空」仍適用於深度變更**：E7 的物理天花板（~99% 美股領先在 0050 開盤跳空被吸收、T+1 開盤成交＝賣在跳空後）對 E7b 的**深度加深**同樣成立——加深也是在 open[T+1] 執行、賣在已跳空的價。E7b 只是把「是否進場」換成「進場後砍多深」，未改變成交時點的物理限制。
- **加深事件 n 極少（3~5）**：plateau D=0.70 下 from-peak 僅 3 次、momentum 僅 5 次加深事件，2022 OOS 段的「反傷/划算」描述性、勿過度解讀。
- **plateau 全平 ≈ flat-deep 同 D**：OOS Sharpe 對 us_confirm 參數不敏感（全距 ≤ 0.084 ≪ δ），看似「穩健」實則是「US 訊號沒帶進可辨識邊際」——勿誤讀為 E7b robust。
- **beta ≠ alpha**：IRvsB ≈ +1.2 全是 beta（0050 自身 IRvsB=+1.00）；勿引用為 E7b 的 outperformance。
- **matplotlib 缺席**：前緣 PNG 未產生（非阻斷）；裁決靠前緣表 + matched-D_deep 控制比較（皆已驗證）。
- **絕不引污染數字**：本 doc 全程未使用 12.7%/1.16/−16% 等手挑池污染數字；所有基準為預先指定的 0050 買持 / 基準B / current-live。
- **重錨**：DD/績效門檻全錨到同族 current-live、flat-deep（同 D）與兩被動（鐵則 #8）；舊 Phase 6/7/8 絕對 DD floor 未移轉。

---

*建立 2026-06-18｜SYNTHESIS（build `notebooks/e7b_depth_modulation.py` + 內建 S3 四層 look-ahead / S4 五軸行為中性 verifier + SYNTHESIS 獨立重derive；純快取重跑 verified、EXIT=0）｜結構 Gate 全 FAIL（未在 DD-vs-報酬前緣 Pareto 勝 flat-deep + 深度 whipsaw 惡化）、alpha 全 FAIL｜R5 未翻案、live 不動｜不改 engine/config/live、未 commit、未切 branch。*

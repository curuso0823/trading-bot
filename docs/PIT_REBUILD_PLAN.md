# PIT 乾淨重建計劃 — 從零建立（可驗證的）獲利策略

> **建立 2026-06-16**。承 [`IMPROVEMENT_PLAN_v2.md` 附錄 B](IMPROVEMENT_PLAN_v2.md)（後見之明污染稽核）。
> 觸發：背景監看 `logs/chip_cache_watch.out` 報「廣池籌碼（法人∩融資券）≥ ~1400」即啟動（明天）。

---

## 0. 定位與心理準備（先讀）

- **起因**：Phase 9 證實現行策略帳面 edge 大半是手挑 universe 的**後見之明**（同規模手挑溢價 **+0.38 pooled OOS Sharpe / +9pp 年化**，下界）；最佳**誠實 PIT 機械策略 0.50 打不贏被動**（基準B 0.80、0050 1.01）。**→ R0 已執行（2026-06-17）**：跑**完整 edge**（籌碼+adjust+乾淨 top-K）版，OOS 中位 ~0.93、仍**與被動打平、無穩健 alpha、唯 regime 降 DD**（見 §2 ✅ R0 結果；0.50 是 Phase 9 momentum-only 粗版，R0 較高非翻案）。
- **目標**：**不是「救活舊策略」，而是用乾淨資料找出「真正存在、可前瞻複製的 edge」（若有）。** 誠實出口可能是「以被動為主、縮小主動部位」——那也是有價值的結論。
- **成功定義**：得到**不含後見之明的真相**，不是「一定要生出獲利策略」。
- **不可違反的紀律**（承 Phase 6/7/8/9）：① 每步綁 **walk-forward OOS**，in-sample 只當線索；② 對照基準**固定且預先指定**＝ 0050 買持 + 基準B（vol_target 0.011，**非** best-of-sweep）；③ 走**新 branch `pit-rebuild`**，**live（main）全程不動**，直到通過總 Gate（OOS 勝基準B、或 DD 優勢單獨成立）；④ **禁用任何 t 之後資訊**（無「近 3 年 CAGR」、無「AI 贏家」名單）。

---

## 1. 前置 — 資料就緒驗證 ✅（2026-06-17 完成）

- **就緒 Gate**：廣池籌碼（法人∩融資券）≥ ~1400（理想 ~90%）、除權息 100%（使 `adjust=True` 還原價可用、不打 API）。
- **PIT 完整性稽核**：逐檔檢查 institutional/margin 的起訖日與缺口 → 標出「2018–25 籌碼完整」的可用子集；缺口大的股票在對應期間不得納入（避免假訊號）。
- **survivorship 殘留**：FinMind 此 stack **無下市/歷史成分** → 廣池仍是「現存活池」。**明記此殘留偏誤、結論帶 caveat、不假裝消除**（所有 OOS 數字仍是上界）。
- **產出**：`notebooks/r0_data_audit.py` —— 覆蓋率報表 + 可用子集清單 + 殘留偏誤聲明。

---

## 2. R0 — 機械 PIT universe 規則 ＋ 誠實基準 ✅（2026-06-17 完成，結果見本節末）

**R0a：機械 PIT universe 規則（無 look-ahead）**
- 規則：每個 rebalance 時點 t，**只用 t 之前資料** —— trailing N 日成交額 **top-K** ＋ 上市滿 M 年 ＋ 價格下限（去雞蛋水餃股）。
- 週期 reselect（季/年），輸出 **per-date membership（時變）**；記錄**換手率**（universe 穩定性 Gate：不因雜訊每月大換血）。
- 多個 K（50/100/150）備選，留 R1 walk-forward 選。
- **產出**：`src/backtest/pit_universe.py`（PIT membership builder；這是**真正的 code 模組**，未來取代手挑 watchlist）。

**R0b：誠實基準（新的真實對照組）**
- 在 PIT universe 上跑現有 edge 疊加（TA + 籌碼 + regime + vol_target），用真 PIT 籌碼（`adjust=True`）。
- 立即對照 0050 買持、基準B。**這取代污染的 12.7%/1.16，成為一切後續的真實 baseline。**
- **產出**：`notebooks/r0_honest_baseline.py`。預期：接近或略輸被動，只剩 regime 降 DD —— 先確立這個誠實起點。

### ✅ R0 結果（2026-06-17 執行；新真實 baseline，取代污染 12.7%/1.16）

**資料就緒 Gate：PASS** —— 法人∩融資券 1813 ≥ 1400；**四方完整 price∩inst∩margin∩div = 1706 檔**（adjust=True+籌碼純快取工作池；排除 204 無除權息以免 adjust 打 API）。⚠️ survivorship 殘留：FinMind 無下市 → 池＝存活池 → 所有數字皆**上界**。

**交付**（branch `pit-rebuild`，純快取驗證 0 次 API、未改 live、未 commit）：
- `notebooks/r0_data_audit.py` — 覆蓋率/缺口報表 + 可用子集（籌碼完整 879、全期橫跨 1538）+ 殘留聲明（寫 `data/processed/r0_cache_audit.json` 供 R0b 共用同池）。
- `src/backtest/pit_universe.py` — **無 look-ahead PIT membership builder**（trailing-60d 成交額 top-K + 上市滿 1y[老股豁免左censored] + 價格下限 10 + 季/年 reselect + 換手率；自檢全綠）。時變 universe 經 `apply_membership()` baked 進 entry 餵 `run_capped`，**不改引擎**。
- `notebooks/r0_honest_baseline.py` — 完整 live edge（TA+籌碼+block_only regime+vol_target，adjust=True）跑 PIT universe，regime 走 fixed-38 錨定（cache-safe，避免廣池 panel 在 2016 warm 窗打 API）。

**誠實基準（季 reselect，OOS=2022–25 pooled；季 churn ~24–30%）：**

| 臂 | 全期Sharpe | OOS Sharpe | IR vs B | DD | 最差年DD |
|---|---|---|---|---|---|
| PIT K=50 | 0.62 | 0.93 | −0.13 | −29% | −17% |
| PIT K=100 | 0.68 | 0.56 | −0.49 | −23% | −15% |
| PIT K=150 | 0.75 | 1.21 | +0.12 | −28% | −15% |
| 廣池(無top-K,參考) | 0.31 | 0.24 | −0.72 | −22% | −14% |
| 基準B vol0.011 | 0.90 | **0.80** | — | −32% | |
| 0050 買持 | 1.01 | **0.95** | — | −34% | |

**一句話判定：誠實 baseline 與被動「大致打平、無穩健 alpha」，唯一站得住的相對優勢是 regime 降 DD。** OOS Sharpe 隨 K **非單調**（0.93/0.56/1.21）＝雜訊跡象，中位 0.93；IR vs 基準B 僅 1/3 為正；全期 Sharpe 0.62–0.75 一致輸被動（B 0.90 / 0050 1.01）。**最佳 K=150 的 1.21 是 in-sample cherry-pick → 不採信**（用 OOS 挑 K＝把 OOS 變 in-sample）。DD 較低（PIT −22~−29% vs 被動 −32~−34%）。**廣池無 top-K 反而最差（0.24）→ top-K 流動性限制有用。**

**→ 對 R1 的指示**：用 walk-forward **在每 fold 內 OOS 選 K**，裁決「K=150 的 1.21 是真訊號還是雜訊」＋附錄 B 旗標的「誠實池是否反而需要加格（max_positions）」。R0 ~0.9 比 Phase 9 ≈0.50 高係跑完整 edge（籌碼+adjust），非翻案。**總 Gate 未過 → live 不動。**

### ✅ R1 結果（2026-06-17 執行；細網格 walk-forward 裁決 K 與 max_positions）

**交付**（branch `pit-rebuild`，純快取 0 次 API、未改 live、未 commit）：`notebooks/r1_walkforward.py`（＋持久化 `data/processed/r1_base_sig.pkl` 全 edge base sig）。Part 0 中性檢查全綠（apply_membership 中性、entry 從不新增、members_union 子集加速 behavior-neutral）；A1 細網格 K=50/100/150 OOS Sharpe = **0.93/0.56/1.21 與 R0 逐字對得上**（細網格忠實）。引擎零改動。預登記＝大概率 NOT PASS（果如預期）。

**A1 細網格 K-sweep（18 點 K∈[20..400]，max_pos=6 fixed，OOS=2022–25 pooled Sharpe）：**
`0.63/0.45/0.65/`**`0.93`**`/0.72/0.67/0.62/`**`0.56`**`/0.64/0.69/0.76/`**`1.21`**`/0.71/0.79/0.69/0.42/0.57/0.53`（K=50/100/**150** 粗體）。
→ **隨 K 鋸齒跳動、無平滑高原**。1 SE(δ)=**0.51**（n≈966）＝雜訊巨大：峰 150 的 1.21 僅比鄰格 140/160（0.76/0.71）高 ~0.5＝**~1σ**＝**孤峰非高原**（δ-帶 [140,150,160,175] 只是「>0.70」低門檻假象）。全期 Sharpe 0.41–0.81 一致 < 被動。

**B1 walk-forward 選 K*（每 fold 內 OOS 選 K；★Q1 決策★）：** 主規則 Calmar·相對 K*=`[110,300,400,300]` → pooled OOS **0.07**、IR −0.85、**不穩**；Sharpe·相對 K*=`[110,110,110,110]`（穩定但**選 110≠150**）→ pooled 0.64、IR −0.39。−32%abs 兩變體與相對同值（floor 罕 binding）。跨 4 規則 pooled∈{0.07, 0.64} **不一致**。固定臂對照：K=50/100/150 = 0.93/0.56/1.21、IR −0.13/−0.49/+0.12；被動 B 0.80 / 0050 0.95。
→ **walk-forward 從不選到 150、pooled 全輸 B、IR 全負、選擇不穩**。**Q1：K=150 的 1.21＝in-sample cherry-pick（雜訊），不採信。K 維度無穩健 OOS 訊號 → K 去留已裁決：不固定特殊 K。**

**B2 walk-forward 選 max_pos（★Q2 決策★；K=B1代表300 ＋ K=150峰 對照；N* 不穩⇒REJECT 翻盤）：**

| K | 規則 | N*_22..25 | pooled OOS | IR vs B | 最差年DD | N*穩定? |
|---|---|---|---|---|---|---|
| 150 | Calmar·相對 | 20b,14b,14b,14b | **1.12** | −0.15 | −13.2% | ✓ |
| 150 | Sharpe·相對 | 20b,18b,14b,14b | 0.97 | −0.28 | −13.2% | ✓ |
| 300 | Calmar·相對 | 12f,6f,20b,20b | 0.91 | −0.36 | −11.9% | ✗不穩 |

A2 in-sample：加格在誠實池**明確改善**（Sharpe↑、DD↓、top3 集中度 63%→24%、budget sizing 更佳；K=100&150 皆然）＝**附錄 B「誠實池疑似需加格」方向成立**（不同於手挑 35 池 Phase-6「加格無益」）。但 walk-forward：在 B1 代表 K=300 → N* 不穩（6↔20、fixed↔budget）、IR −0.36<0 ⇒ **未穩健翻盤**；在 in-sample 峰 K=150 → N* **穩定**（budget N~14–20）、pooled **1.12**（standalone 勝兩被動）、DD −13.2%（vs 被動 −32/−34%），**但 IR vs B −0.15<0**＝**低 DD/低報酬的防禦型 profile、非 alpha**，且條件於 in-sample 才知的 K=150。
→ **Q2：加格＋budget sizing 是強方向性結構線索（誠實池確比手挑池更需分散），但非穩健 alpha 翻盤——它強化「regime/低-DD 防禦」這層、不是擊敗被動。列為 R-attrib/R5 的 sizing 輸入，不據以調 live。**

**外層 DD 真檢定（vs 被動，OOS 最差前進年）：** wf-K −15.4% / wf-N −11.9% / 固定 K=150 −15.3% vs 基準B −32.2% / 0050 −34.0% → **regime 降 DD 這層 edge 成立（>2.2pp）**。+1 日 leak 乾淨（Sharpe 0.60→0.59）。

**R1 總 Gate：FAIL（無穩健 alpha）。** Q1=cherry-pick、Q2=僅方向性（非穩健翻盤）、IR vs B 全負、選擇不穩。**唯一站得住的真 edge＝regime 降 DD**（外層成立，與 R0／附錄 B Tier D 一致）。⚠️ survivorship（FinMind 無下市）→ 所有 OOS＝**上界**、真實更低。

**ETF-排除 sanity（`R1_EXCLUDE_ETF=1`；移除 6 檔 ETF `0050/0051/0052/0053/0055/0056`，使策略不交易基準本身 0050）：所有結論穩健、Q1 更被坐實。** in-sample 峰 **1.21@150 崩到 0.89、峰移到 K=50（1.02）**、δ-帶寬 11/18 近橫掃＝**K 隨池組成重排、無穩定特殊 K**（150 尖峰部分係策略在持 0050/0056）；B1 K* 仍不穩（`[300×4]`／`[110,300,110,110]`、pooled 0.53/0.43 輸 B、IR 負）；Q2 仍方向性非翻盤（N* 不穩、wf-N IR vs B −0.38<0、K=150 穩定臂 pooled 1.09 仍 IR −0.19<0）；regime-DD 仍唯一成立（wf-N −13.3% vs 被動 −32/−34%）。**→ FAIL 非「策略交易基準」假象；有無 ETF，誠實池主動皆無穩健 alpha。** full-pool ＝ R0 apples-to-apples baseline（預設保留）、ETF-排除＝opt-in sanity（`notebooks/r1_walkforward.py` 旗標）。

**→ 級聯（等使用者指令，不自動進）：** **R-attrib**（逐層歸因，量化 regime-DD 層 ＋ 加格/sizing 方向線索）＋ **R5 誠實出口**（被動為主、縮小主動；active 定位＝低-DD 防禦 sleeve，若跑用 budget-sizing ~12–20 名而非集中 6）。**total Gate 未過 → live 全不動。**

---

## 3. R-attrib — 逐層歸因（哪一層才是真 edge）

在 PIT universe + walk-forward OOS 上，逐層 A/B 拆解，報每層 **OOS Sharpe / IR vs 基準B / DD** 增量：

1. PIT universe buy-hold（被動地板）
2. ＋ TA（動量/突破/量比）
3. ＋ 籌碼（法人/投信/融資/融券）← **乾淨版的籌碼增量檢定**（master Phase 3.5 / Phase 10 #6）
4. ＋ regime（投降感知）← 量化 DD 貢獻（Phase 9 已知這層 PIT-真）
5. ＋ 動量傾斜（Phase 9 的可選項）← **乾淨驗證**（解除手挑 confound）

→ **保留有貢獻的層、砍掉沒貢獻的**（降複雜度）；若籌碼增量不顯著 → 降級為可選甚至移除。
- **產出**：`notebooks/r_attribution.py`（逐層增量表）。

### ✅ R-attrib 結果（2026-06-17；元件級逐層 ablation，etf_excl 主 K=100，OOS 2022–25 pooled）

**交付**：`notebooks/r_attribution.py`（+持久化 `data/processed/r_attrib_base.pkl`：分離 ta/chip_ok/chip_score/liquid/turnover/mom 元件）。**Sanity：L5(=R1 full edge) OOS 0.70 逐字重現 R1 同池同 K**（ablation base 忠實）。引擎零改動、純快取。判讀紀律：增量綁 OOS、**δ=1SE≈0.51 → |ΔSharpe|<0.5 在雜訊內**、跨 K 變號＝非真、重錨相對被動。

**累積 ladder（每層 +1 component；ΔOOS＝相鄰增量）：**

| 層 | OOS_Sh | ΔOOS | IRvsB | 最差年DD | 判定 |
|---|---|---|---|---|---|
| L0 等權PIT指數(gross) | 0.66 | — | +0.16 | −40% | 被動地板（比 0050 更深 DD） |
| L1 +引擎/size-select | 0.60 | −0.05 | −0.13 | −33% | 集中大型名→DD −7.8pp、Sharpe 平 |
| L2 +TA timing | 0.30 | −0.30 | −0.65 | −35% | 雜訊內負（TA 害） |
| L3 +籌碼 gate | 0.18 | −0.12 | −0.77 | −39% | 雜訊內 |
| L4 +籌碼 select | −0.23 | −0.41 | −1.19 | −39% | standalone 轉負、PnL 分散 top3 625% |
| **L5 +regime(=R1full)** | **0.70** | **+0.94** | −0.37 | **−15%** | **regime 救活：ΔwDD +24pp** |
| L6 +動量傾斜 | 0.67 | −0.04 | −0.35 | −15% | 雜訊內 |
| (被動) 基準B / 0050 | 0.80 / 0.95 | — | — | −32/−34% | |

**K-穩健性（鐵則#7）：** 籌碼增量(L2→L4, 無 regime) 跨 K=100/50/150 = **−0.53/+0.86/−0.17＝變號、非 K-穩健**；regime 增量(L4→L5 ΔwDD) = **+24/+17/+18pp＝一致大降 DD**、ΔOOS +0.94/+0.42/+0.77 一致正。

**反事實 regime-first（regime 為地板、逐加層；R5「砍什麼」）：** regime+size 0.57/DD−21% → +TA 0.59 → +籌碼gate 0.63 → +籌碼select(=L5) 0.70/DD−15%。**ΔSharpe 全在雜訊內（累積 +0.14），唯 chip_select 在 regime 上把 DD −21→−15%（+6pp、cut churn/concentration）。**

**結論（與 R1 一致、量化版）：**
1. **無任何層加 robust OOS alpha**：所有 signal-layer Sharpe 增量在 δ≈0.5 雜訊內或負，IR vs B 全程 <0（全 edge L5 IR −0.37）。
2. **regime＝唯一 K-穩健真貢獻、且純靠 DD**（跨 K 一致 +17~24pp DD 降）。它也「救活」standalone 為負的籌碼/TA 層（L4 −0.23→L5 +0.70）＝edge 是**防禦非 alpha**。
3. **籌碼層無 robust Sharpe alpha**：standalone 跨 K **變號**、K=100 轉負(PnL 分散 top3 625%) → master Phase 10#6 疑慮在誠實池**坐實**；唯在 regime 上有**條件性 DD 助益**(~6pp，未驗 K-穩健)。
4. **TA/動量＝雜訊**（TA ≤0、動量 −0.04）→ 誠實池無乾淨擇時/動量 alpha（解除手挑 confound）。
5. **→ R5 輸入**：誠實 active 的價值＝regime DD-overlay；極簡地板 regime+size 已捕大半（0.57/−21%），全 chip/TA edge 加的是雜訊內 Sharpe + ~6pp DD。**R5 權衡「極簡 regime 防禦 sleeve vs 保留 chip 換 DD」；無論如何無 alpha → 被動為主、active 小而防禦。total Gate 未過 → live 不動。** ⚠️ survivorship → OOS 皆上界。

---

## 4. R1–R4 — 在誠實 universe 上重跑 Phase 6/7/8（複用既有 harness，只換 universe）

| 步 | 內容 | 重點 | 複用 |
|---|---|---|---|
| ~~**R1**~~ ✅（2026-06-17 完成） | 細網格 walk-forward 裁 K ＋ `max_positions` | **已完成，結果見 §2「✅ R1 結果」**：Q1 K=150 的 1.21＝cherry-pick（不採信）；Q2 加格僅方向性線索（非穩健翻盤、IR<0）；總 Gate FAIL、唯 regime 降 DD 成立 | `r1_walkforward.py`（複用 `p6/p8/p9`、`pit_universe`）|
| ~~**R2 動量傾斜**~~ ⏭️ 跳過 | — | **已被 R-attrib L6 涵蓋**：誠實池動量增量 **−0.04＝雜訊**（解除手挑 confound 後無動量 alpha）→ 無需專跑 | — |
| ~~**R3 Phase 7**~~ ⏭️ 跳過 | — | 原條件＝「龍頭捕獲仍差才做」；問題非捕獲、是**根本無 alpha** → moot | — |
| ~~**R4 Phase 8**~~ ⏭️ 跳過 | — | **已被 R1 涵蓋**：walk-forward **K\*/N\* 已證不穩**（選擇穩定問題＝答完=不穩）→ 無需專跑 | — |

> **R2/R3/R4 經 R1+R-attrib 元件級拆解全數涵蓋 → 跳過**（動量＝雜訊、出場非問題、選擇穩定已答=不穩）。**剩餘唯一實質步驟＝R5**（直接執行）。

- 所有決策綁 OOS；**選擇穩定＝Gate、尖峰＝棄、高原＝留**（同 Phase 8 紀律）。

---

## 5. R5 — 正式裁決（誠實基準上）—— 聚焦「regime 降-DD 是真防禦還是恆等式」

R0/R1/R-attrib 已定讞：**誠實池無穩健 alpha，唯一真貢獻＝regime 降-DD（防禦非 alpha）**。R5 不再泛測 alpha，而是裁決**唯一還沒被決定性回答的問題**：

> regime 的降-DD 到底是「真防禦 edge」，還是只是「少持有一點 0050」的**恆等式假象**？

**(1) 風險對齊 DD 檢定（決定性 centerpiece）**：被動全持當然 DD 大、任何摻現金的東西 DD 都變小＝恆等式。要證明防禦有價值，必須打贏**風險對齊被動**（de-risk 到同 vol／同 DD 的 0050+現金），非全持 0050。
  - 對比：regime 防禦 sleeve（極簡 regime+size；及 +chip 變體）vs「0050／基準B 摻現金 de-risk 到 ①同 realized vol、②同最差年 DD」。
  - 指標：Sharpe（cash-mix 下 ≈ 不變，重點不在此）、**Calmar、最差年 DD、尾部崩盤段（2022 熊／2020 COVID／2018Q4）**。
  - 預告（R-attrib）：regime+size 0.57@−21% vs 被動 de-risk 到 −21% 仍 ~0.80 → **大概率輸**；唯一可能翻盤＝regime 同 vol 下特別砍掉最壞崩盤（尾部擇時）。
**(2) 顯著性（確認無 alpha）**：IR vs 基準B 的 bootstrap／Newey-West 95% 區間（預期含 0 或全負）、α/β 迴歸 vs 0050（預期 α 不顯著）。
**(3) 極簡化（砍 chip？）**：chip 已證雜訊+變號+Phase10#6 疑慮坐實，只換條件性 ~6pp DD。除非 (1) 證明那 6pp 是真尾部保護，否則 sleeve 砍 chip、只留 regime+size。
**(4) 裁決樹**：
  - 風險對齊**贏**（尤其尾部/Calmar）→ 真防禦 edge → 小規模 active sleeve（低回撤工具）mandate → 才考慮 R6 小額落地。
  - 風險對齊**平/輸** → 連防禦都非 edge → **純被動**（0050／基準B），active 歸零。
  - 任一情況 live 先不動，待裁決 + 使用者拍板。
- **survivorship**：OOS 皆上界；連上界都打不贏風險對齊被動 → 真實更糟、結論更穩。
- **產出**：`notebooks/r5_alpha_verdict.py`。

### ✅ R5 結果（2026-06-17 執行；風險對齊 DD 檢定＋顯著性；裁決＝被動為主誠實出口、重建收束）

**交付**（branch `pit-rebuild`，純快取 0 API、未改 live、未 commit）：`notebooks/r5_alpha_verdict.py`（複用 `r_attrib_base.pkl` 分層臂＋`pit_universe`＋benchmark 模組；fixed-38 regime、etf_excl K=100、引擎零改動）。防禦三臂＝regime+size 極簡 sleeve／+chip／全 edge L5；對照預先指定 0050 買持＋基準B。**Sharpe/Calmar/DD-vol 三比率皆 scale-invariant（cash-mix 下不變）＝公平風險對齊**。

**風險對齊 DD 檢定（OOS 2022–25；「同 vol DD vs B」＝把基準B 摻現金 de-risk 到同 vol 後臂淺多少 pp）：**

| 臂 | 年化% | Sharpe | maxDD% | Calmar | DD/vol | 同vol DD vs B | 2022熊段DD(臂/B@vol) |
|---|---|---|---|---|---|---|---|
| 防禦sleeve(regime+size) | 7.8 | 0.55 | −23.5 | 0.33 | 1.46 | **+6.0pp 淺** | −14.5 / −29.5 |
| +chip | 9.1 | 0.74 | −21.0 | 0.43 | 1.61 | +3.6pp | −10.4 / −24.5 |
| 全edge L5 | 8.0 | 0.68 | −16.6 | 0.48 | 1.34 | **+6.9pp 淺** | −15.1 / −23.5 |
| 0050 買持 | 20.2 | **0.94** | −34.0 | **0.59** | 1.54 | — | — |
| 基準B vol0.011 | 13.3 | 0.79 | −32.2 | 0.41 | 1.81 | — | — |

**顯著性（OOS）：** IR vs 基準B = −0.34/−0.28/−0.38（全負）、block-bootstrap 95% CI **全含 0**（~[−1.5,+0.8]）；α vs 0050（Newey-West lag5）= +0.0/+3.5/+2.7%、**t = 0.00/0.56/0.48 全不顯著**。

**裁決：被動為主（誠實出口）。**
1. **無顯著 alpha**（IR<0、CI 含 0、α t≈0）——與 R0/R1/R-attrib 一致、定讞。
2. **regime 降-DD 是「真但不顯著」的防禦、非純恆等式**（**修正 R5 跑前「純恆等式」假設**）：同 vol 下 maxDD 比風險管理被動基準B 淺 +3.6~+6.9pp、DD/vol 更優（L5 1.34/sleeve 1.46 vs B 1.81/0050 1.54）、2022 熊市抗跌明顯更好（sleeve 段 DD −14.5% vs B@vol −29.5%）＝regime 確在擇時砍崩盤。
3. **但不構成 mandate**：① 對**原始 0050 全輸**（Sharpe 0.94/Calmar 0.59；2023–25 大漲、buy-hold 完勝，主動年化僅 8–9% vs 0050 20%）；② 防禦優勢**統計不顯著**（OOS 僅 1 次崩盤、CI 含 0）；③ 報酬代價大。
4. **chip**：OOS 提升 Sharpe/Calmar 但**惡化 DD/vol**、全不顯著 → 不值保留（合 Phase 10#6 疑慮）。

**→ 總 Gate：FAIL（無顯著 alpha；DD 優勢真但不顯著、且被原始 0050 完勝）→ live 全不動。** 誠實出口＝**以被動（0050）為主**；regime 防禦 sleeve 僅在**明確 drawdown mandate**（願以上漲期落後換崩盤保護）下作小規模可選。⚠️ survivorship → 全為上界、真實更糟、結論更穩。

**🏁 重建收束**：R0→R1→R-attrib→R5 一致——誠實 PIT 池**無可前瞻複製的 alpha**；唯一真東西＝regime 崩盤防禦（真但不顯著、不敵 buy-hold）。**現行 live（手挑 35 檔）帳面 edge 經證為後見之明、前瞻無 alpha。** R2/R3/R4 已被涵蓋（跳過）。**R6 僅在使用者選『被動落地／防禦 sleeve』時執行；否則重建在此誠實收尾、live 維持凍結待拍板。**

---

## 6. R6 — 落地（**僅在 R5 通過**）

- 把通過的「PIT universe 規則 + 有貢獻的 edge 層 + 參數」寫進 code/config：
  - 啟用 `src/backtest/pit_universe.py` + live 端對應接線（**真正 code 改動，取代手挑 watchlist**）。
  - 對應 `config/strategy.yaml` keys、測試 fixture、文件同步。
- 全套 `pytest` 綠 → paper-trade 驗流程 → 小額 live。
- **在此步之前 live 全不動。**

### ✅ R6 結果（2026-06-17；使用者選「被動為主」落地＝benchmark + MA200 overlay；config 已寫+測試、待部署）

R5 裁決後使用者選 **R6 被動落地**、口味＝**vol-target + MA200 overlay**（白話：平時跟 0050、跌破 MA200 退、漲回再跟）。
- **零 code 改動**：live 早有 active/benchmark 模式開關（commit 45006c4，`config/settings.yaml → strategy.mode`）→ 純 config flip。`BenchmarkEngine`：只交易 0050、vol-target 配重、MA overlay、月度/偏離再平衡、fail-safe（未知 mode 回退 active）。
- **改動**（`config/settings.yaml`）：`mode: active→benchmark`；`benchmark`＝0050 / target_daily_vol **0.011**（**平時 vol-managed 為主**、~80% 曝險；要恆滿跟0050改0.05）/ cap 1.0 / **regime_overlay true / regime_ma 200 / regime_action zero**（**MA200 跌破＝最後一道防線**→全退現金、漲回全進；要溫和改 half）。**參數由使用者意圖＋結構穩健選（MA200 canonical、whipsaw 最少 12次/4年），非 OOS 峰值挑（鐵則#7；跨變體 spread＝雜訊、R5 已定無顯著 alpha）。**
- **驗證**：`pytest` **97 passed**（零 code 改動）；dry-run：make_engine()→BenchmarkEngine（0050 / vol 0.011 / overlay MA200 zero）、今日 0050 65.60 ＞ MA200 52.56（未觸最後防線）。
- **誠實定位**：結構性降回撤規則、符合使用者風險偏好；**非經證實 outperformer**（R5 無顯著 alpha；overlay 前瞻預期＝降深熊 DD 但 MA 附近 whipsaw、牛市≈跟 0050；OOS 表「贏 0050」是期間特性+雜訊、不外推）。
- **待使用者**：① 部署（重啟 main.py；切換前現有 active paper 持倉成孤兒→刪 `data/processed/paper_account.json` 或先平倉）；② git commit/branch（不自動）；③ 可選 param flip（half/MA120/0.011 base）。rollback＝mode 改回 active。

---

## 7. 殘留風險與誠實聲明

- **survivorship**：FinMind 無下市 → 廣池偏樂觀 → 所有 OOS 仍是上界，結論須帶此 caveat。
- **單一市場/單一期間**：統計檢定 power 有限；R5 結果與 R4 穩健性一起讀。
- **核心提醒**：若乾淨真相是「打不贏被動」，**接受它**——這正是整個 v2 後見之明稽核要換來的誠實答案。

---

## 觸發與分支（操作摘要）

- **觸發**：✅ 已達成 —— builder 完成、法人∩融資券 **1813 ≥ 1400**、四方完整 **1706**、除權息足以 `adjust=True` 純快取。R0 已執行。
- **branch**：`pit-rebuild`（R0 產物在此，未 commit）；`main`（live config/src）不動到通過總 Gate。
- **執行順序**：~~前置~~ ✅ → ~~R0~~ ✅ → ~~R1~~ ✅（K=cherry-pick、加格僅方向性、FAIL）→ ~~R-attrib~~ ✅（無層加 alpha、唯 regime 降 DD、籌碼疑慮坐實）→ ~~R5~~ ✅（…被動為主誠實出口、總 Gate FAIL）→ ~~R6~~ ✅（使用者選被動落地＝benchmark + MA200-zero overlay；config 寫+測試綠、**待部署/commit**）；~~R2/R3/R4~~ ⏭️ 跳過。**重建 R0→R6 完成；live 由手挑 35 檔 active 轉被動 0050+MA200 overlay，待部署生效。**

*版本：v1 | 2026-06-16 | 性質：等乾淨 PIT 資料就緒後的執行 playbook（非定論，每步綁 OOS）*

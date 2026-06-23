# MULTI_ASSET_UPGRADE_PLAN — 0050 →「4+1」五資產升級 ＋ 資產分配器（Asset Allocator）計畫

> ## ✅ 狀態更新（2026-06-23）：本計畫的資產分配器已實作並上線 paper（`config/settings.yaml strategy.mode: allocator`，M0+M1+M2 三層全開）。
> - **live＝6 資產 allocator**：0050 35% / 00981A 16% / 00991A 16% / 00635U 10% / 00864B 11.5% / 合成台幣 MMF 11.5%；本金 NT$150,000、mode=paper（Fugle 盤中零股、模擬撮合）。M2 於 2026-06-23 實測抓真資料（FRED `fredgraph.csv` 公開端點、免 key）後上線。
> - **對應 live 程式**：`src/strategy_engines/allocator_engine.py`、`main.py` allocator 任務、`src/data/macro_fetcher.py`（M2 MacroMonitor）、`src/execution/mmf_sleeve.py`（合成 MMF）、`deploy/build_initial_book.py`（初始建倉）。
> - **定位不變（勿讀成翻案）**：allocator＝使用者選定的多資產分散+regime 風控，**非經證實 alpha**；R5「無穩健 alpha、0050 報酬王」仍成立、未翻案；此為鐵則#2「使用者拍板部署」分支的 **paper 評估**。**未新增任何 alpha 宣稱。**
> - 以下為**原始設計/規格**；實作真相見 **CLAUDE.md** 與 **`docs/M5_DEPLOYMENT_PLAN.md`**。文中凡標「未實作 / 待實作 / 尚未部署 / live 未動」等未來式者，均已被本橫幅 supersede（並就地加註 ✅）。
>
> **狀態（原始，2026-06-19）：計畫（PLAN）階段 — 純規劃文件，未改任何 code / config / live。** 建立 2026-06-19。**〔✅ 已於 2026-06-23 實作上線（M0+M1+M2），此行為歷史狀態。〕**
> **定位：** 把 live 從單一 0050 演進為「4+1」五資產組合，並以一個**規則化「資產分配器」overlay** 即時監測兩個 regime（AI/股票下行、美元/利率）、在鎖定戰略權重周圍做**有界跨檔互換**。
> **鐵則全程適用（CLAUDE.md）：** 總 Gate 未過前 **live 全不動**；每個實驗綁 **walk-forward OOS**；回測**純快取、0 API**；引擎改動須 **additive 行為中性**；**survivorship → 所有 OOS 為上界**；參數**細網格**；**不自動 push、commit 僅在使用者明說**。
> **這是 R5/E1–E8 之後的延伸：** 主動選股無穩健 alpha、0050 報酬王、唯 regime 防禦真但不顯著。本計畫不推翻這些；分配器以**防禦/再平衡**為本,任何「切換 alpha」必須 OOS 自證,否則 fallback 到靜態再平衡。

---

## 0. 一頁摘要（TL;DR）

- **升級對象＝「4+1」**：1 既有（0050）＋ 4 新增（00981A、00991A 主動台股；00864B 美元超短債；00635U 黃金期貨）。**戰略倉位比例已於上一步定案**（§2），本計畫處理的是**策略層＝資產分配器**。
- **資產分配器＝圍繞 baseline 的有界 regime overlay**，兩個監測器：
  1. **AI/股票下行** → 砍 AI 集中的股票 sleeve、轉進防禦（台幣現金/黃金）。**骨幹＝已證實的 MA200 regime（含 E1+E2 whipsaw 修正）**，多資產化。
  2. **美元/利率** → 在 USD sleeve（00864B、00635U 的 USD 成分）與台幣 sleeve 間做**慢速 macro tilt**（觸發點＝US CPI 鬆動→Fed 轉降息）。
- **off 狀態 ≡ 靜態帶寬再平衡**（additive 行為中性的 baseline）。
- **最大誠實限制：兩檔主動 ETF <1 年資料、從未經歷空頭** → 分配器的下行邏輯只能在 **0050 歷史**上 walk-forward，主動以「高 β 0050」代理 + caveat；其真實空頭行為**無法驗證**。
- **分階段 M0→M4**，每階段沙盒研究→walk-forward→過 Gate→使用者拍板才動 live；未過則**退回 M0 靜態再平衡**（仍是有效的分散升級）。**〔✅ 2026-06-23：M0+M1+M2 三層皆已實作並上線 paper（非退回 M0）；以下分階段敘述為原始規劃路徑。〕**

---

## 1. 背景與現況

- **現 live**：benchmark 被動＝0050 vol-target（target_daily_vol=1.0＝平時 100% 跟 0050）＋ **MA200 regime overlay**（E1+E2：連 3 日跌破 MA200×0.99、±1% 緩衝帶 → 砍至 85%／`regime_action=0.85`）。引擎 `src/strategy_engines/benchmark_engine.py` ＋ `main.py` benchmark 任務。
- **上一步已完成（研究/計畫,未改碼）**：5 資產**戰略倉位比例定案**（§2）＋ 標的真相查證（見記憶 `portfolio-expansion-5-asset`）。
- **本步＝策略設計**，核心交付＝**資產分配器**（本檔）。使用者明示這是「計畫」任務。**〔✅ 2026-06-23：計畫已落地——allocator（M0+M1+M2）已實作並上線 paper，`config/settings.yaml strategy.mode: allocator`；本檔自此為原始設計/規格紀錄。〕**

---

## 2. 鎖定的戰略配置（分配器的 baseline）

| Sleeve（角色） | 權重 | 工具 | 幣別 |
|---|---|---|---|
| 0050（被動核心） | 35% | 0050 | TWD |
| 00981A（主動衛星） | 16% | 主動統一台股增長 | TWD |
| 00991A（主動衛星） | 16% | 主動復華未來50 | TWD |
| 00635U（分散器·黃金） | 10% | 期元大S&P黃金（期貨型） | USD |
| 00864B（壓艙·美元） | 11.5% | 中信美債0-1（未避險） | USD |
| 台幣 MMF（壓艙·台幣） | 11.5% | 國泰台灣貨幣市場/群益安穩 | TWD |

- **曝險**：台股股票 67%（全押 AI/台積電,**頭號集中度風險,使用者刻意承擔**）／黃金 10%／類現金 23%。幣別 TWD 78.5%／**USD 21.5%**。
- **此即分配器的「中性/off」目標權重**；分配器只在其**周圍**做有界 tilt。

---

## 3. 資產分配器（Asset Allocator）— 核心設計

### 3.1 定位與哲學

- **是什麼**：一個 regime-conditional 的**權重 overlay**，在 baseline（§2）周圍做**有界**跨檔互換；**不是 high-frequency 擇時、不是選股**。
- **off 狀態 ≡ 靜態帶寬再平衡**到 baseline（例：股票 sleeve ±5pp、衛星/黃金 ±2–3pp 觸發再平衡）。這是 **additive 行為中性的 baseline-S**，也是所有 Gate 的對照。
- **作用層級＝sleeve（資產類別），非個股/次產業**。理由見 §3.2 的「科技突破/供應鏈重組」說明。

### 3.2 監測器 1：AI/股票下行 regime（de-risk 股票 → 防禦）

**目標**：當 AI 集中的股票 sleeve（67%）進入下行 regime，按比例砍股票、轉進台幣現金/黃金。

**對使用者三個子情境的誠實對應**：
| 子情境 | 可偵測性 | 分配器做什麼 |
|---|---|---|
| **大盤修正**（broad correction） | **可**（MA200/vol/drawdown regime＝已證實防禦槓桿） | 主戰場：regime-off 砍股票 sleeve → 現金/黃金 |
| **政策干預**（出口管制/法規等） | **多為跳空事件**，盤前難預判（E7 證實美股領先 ~99% 在開盤跳空被吸收） | **反應而非預測**：確認後 de-risk,不假裝能 front-run |
| **科技突破→某 AI 成分/供應鏈短暫重組** | **單一名/次產業 rotation,非指數級下行** | **多半超出 sleeve-level 分配器範圍** → 委由**主動 ETF 經理人 + 0050 指數方法**處理（這正是付 ~2% 內扣買的東西；R1 已證明 sleeve-level 無穩健選股 alpha）。**只有當它擴散成大盤下行 regime,Monitor 1 才介入。** |

**候選訊號（全部須 cache-available、因果、survivorship-aware）**：
- **MA200 regime（骨幹,已證實）**：沿用 live 的 E1+E2（連 3 日 + 1% 帶）。**這是唯一跨 K 穩健的防禦槓桿（R-attrib）**,分配器以此為地基。
- realized-vol spike（0050 20d）／drawdown-from-peak：**E-item A 已證在 E1+E2 之上 headroom 有限** → 列為「需自證才進」。
- 美股半導體領先（^SOX/SMH/TSM ADR 隔夜）：**E7/E7b 已證盤中不可萃取** → 預設**不採**,除非有新證據過 Gate。
- active-vs-0050 背離：下行時高 β 主動跌更多 → 可「先砍主動、後砍 0050」的順位邏輯（待驗）。

**先驗預期**：除 MA200 骨幹外,其餘訊號**大概率 FAIL**（E1–E8 已逐一試過）；仍納入研究但**不預設會成功**,過不了就只留 MA200 骨幹的多資產化。

### 3.3 監測器 2：美元/利率 regime（USD ↔ TWD tilt）

**目標**：在 USD sleeve（00864B、00635U 的 USD 成分）與台幣 sleeve 間做**慢速（月級）macro tilt**。

**候選訊號（cache-available）**：DXY vs 其 MA、US–TW 利差、Fed 政策路徑、**US CPI 趨勢（關鍵 regime 觸發）**、USD/TWD vs MA。

**規則骨架（待細網格 + walk-forward 定參）**：
- **強美元 regime**（DXY>MA 且 Fed 偏鷹/CPI 黏）→ 偏好 00864B（USD carry+升勢）、可略減黃金（USD 逆風 + contango 雙拖累）。
- **弱美元 regime**（CPI 鬆動→Fed 轉降息訊號）→ 00864B → 台幣 MMF 輪動、調升黃金（USD 走弱＝金價順風）。

**先驗預期**：剛完成的研究顯示**機構對美元方向分歧大、forecasting 不可靠**；故 Monitor 2 是**慢速 regime tilt（跟隨而非預測）**,且**門檻保守**。**最該盯的單一觸發點＝US CPI 何時讓 Fed 鬆手**（弱美元/台幣升值劇本回歸的訊號）。過不了 Gate 就**不做 tilt、維持靜態 USD/TWD 各半**。

### 3.4 跨檔互換矩陣（互換邏輯,皆有界、off=靜態再平衡）

| 觸發 regime | 動作 | 來源 → 去向 | 上限（暫定,待 OOS 調校） |
|---|---|---|---|
| 股票下行 ON | 砍股票 sleeve | 0050+主動 → 台幣MMF + 黃金 | 股票 −最多 ~20pp（先砍主動） |
| 股票下行 ON（細部） | 先砍高 β | 主動 → 0050 → 現金 | 主動先於 0050 |
| 強美元 | 偏 USD carry | 台幣MMF → 00864B；黃金略減 | USD sleeve ±最多 ~8pp |
| 弱美元（Fed 轉降息） | 去美元 + 加黃金 | 00864B → 台幣MMF；現金/股票 → 黃金 | 同上 |

> 所有 tilt 疊加後仍受「單一 sleeve 硬上限」約束（如主動合計 ≤ ~35%、黃金 ≤ ~15%、單一 USD sleeve ≤ ~20%）。**分配器 off ⇒ 矩陣全 0 ⇒ 回到 §2 靜態再平衡。**

### 3.5 與既有 MA200 overlay 的關係

- 現 live 的 MA200-85% overlay 是 Monitor 1 的**特例**（只蓋 0050、砍 15%）。分配器＝把它**多資產化**：regime-off 時砍整個股票 sleeve、按矩陣分流到現金/黃金。
- **行為中性要求**：分配器在「只蓋 0050、其餘 sleeve 中性」的退化參數下,須能**逐位重現現行 live**（max|Δ|=0）——這是 additive 落地的把關（沿 E1+E2 的做法）。

---

### 3.6 已鎖定的 M1/M2 設計決策（2026-06-19,使用者拍板）

- **M1 訊號**：**MA200 骨幹**（E1+E2：連 3 日跌破 MA200×0.99 + 1% 帶）。不加複合訊號（先驗多 FAILED）。
- **M1 深度（已定 2026-06-19）：V1 溫和 flat、a=0.75**（regime ON → 股票 sleeve 砍至 75%）。沙盒 `notebooks/regime_tilt/m1_depth_compare.py`（複用 `_lab.py`、0050-proxy、純快取、自驗 max|Δ|=0 對齊 live）裁決：**V1 flat 全面 dominate V2 分層深砸**（V2 深回撤段砍過頭、同等 DD 付更多反彈、Sharpe 更低；V1=平滑高原 vs V2=雜訊面,與 Item C/E7b 先驗一致）→ 分層機制放棄,深度收斂成 V1 旋鈕。a=0.75 profile（0050-sleeve、fixed-depth）：最差年 DD −28.1%（vs live-0.85 −30.4% / 0050買持 −34.0%）、反彈犧牲 ~5.6pp（vs 買持）、OOS Sharpe 1.051、效率 ~1.05 DD/反彈。**深度=風險偏好旋鈕非 alpha**（WF 選參不穩 0.975↔0.70、IRvs0050 −0.46;DD 改善真、反彈代價真）。
- **M0×M1 接縫**：**下行 regime ON 時暫停股票買跌**（停止對 0050/主動的逢低加碼,讓 de-risk 主導;OFF 恢復靜態不對稱帶寬的買跌）。其餘靜態規則不變。
- **M2 美元（已定 2026-06-19）：雙確認(CPI 領先 + Fed 確認) → ±5pp、只動現金**。弱美元=US CPI YoY 下行 **且** Fed 轉鴿/降息 → 00864B −5pp / 台幣MMF +5pp;強美元=CPI 黏/上行 **且** Fed 持平/升息 → 反向。月級 + 多月確認、CPI 按發布落後(防 look-ahead)、tilt 受硬地板(00864B≥10%/MMF≥9.5%)clip。黃金不隨 M2(留 M1)。**先驗低**(USD timing 難 + 2018–26 僅 ~4–5 次 Fed 轉折=樣本少)→ 可能過不了 Gate,則 USD/台幣維持靜態各 11.5%。
- **執行預設（低爭議,未另問）**：tilt 平移目標權重、帶寬隨之移動（單一引擎、additive、off ≡ 靜態規則 max|Δ|=0）；每日判 regime + 連 N 日確認防抖；de-risk 去向以永豐 MMF 為主、至多半數進黃金（黃金逢強美元逆風則少進）；M1+gold 與 M2−gold 拉鋸時風險-off 由 M1 優先、受黃金上限 15% 約束。
- **M1 深度沙盒已完成（2026-06-19）**：`notebooks/regime_tilt/m1_depth_compare.py`（複用 `_lab.py`、0050-proxy、純快取、自驗 max|Δ|=0 對齊 live）。結論見上（V1 a=0.75 鎖定、V2 出局）。
- **✅ 資料牆已解除（2026-06-19,使用者授權受控抓取）**：背景 agent 已抓 00635U(2015-04~)、00864B(**2019-10~**)、00981A/00991A(<1yr,β 實測 1.09/1.19≈代理) 入快取 + US 總經(CPIAUCSL/FEDFUNDS/DFF/DEXTAUS/DTWEXBGS) 入 `data/raw/macro/`;FinMind 僅 5 請求未撞限。**資料 caveat:** (a) **00864B 配息只有 2025-08 後 4 筆→pre-2025 總報酬低估(漏 coupon)**→回測補估 ~2.5–3%/yr carry 並報有/無兩版;(b) 00864B 2018–2019 缺→該期 11.5% 掛台幣 MMF;(c) 主動 <1yr→用擬合代理模型(β+net_alpha+idio,見上「全書」條),非實績。
- **✅ 全書整合驗證完成(2026-06-19;2026-06-19b 改用使用者擬合代理模型重跑)**：`notebooks/regime_tilt/full_book_backtest.py`(returns-based、純快取、自驗通過:模型 wiring max|Δ|=0、toggle 退化 max|Δ|=0、look-ahead 控制[regime shift1/macro 連2月確認+落後2月/參數鎖定]、coupon 有/無兩版 + idio 殘差 MC)。**主動代理升級:** 由粗 β×0050 → `active_etf_proxy_model_00981A_00991A.md`(r=β·r0050+net_alpha/252+ε;**00981A β1.10/淨α+2.2%/σ_idio7%**、**00991A β1.05/淨α+1.0%/σ_idio5%**、資產級 DD 懲罰 −4/−2.5pp)。**逐層 ablation(含 coupon、deterministic):** 0050買持 20.0%/Sh1.01/−34.0% → **M0 靜態** 16.9%/1.15/−23.6%(2022 −14.1%) → **M0+M1** 16.3%/1.21/−19.7%(2022 −10.7%) → **M0+M1+M2** 16.3%/1.21/−19.1%。**idio MC(400 paths、seed12345):** M0+M1 Sharpe 中位1.20/p5 1.15、maxDD 中位−19.7%/p5 −20.8% → 殘差於組合級(16%+16%)被分散掉、不改結論。**結論(較粗代理更穩):M0 分散大幅降 DD+升 Sharpe(代價 −3.1pp CAGR);M1 再降 DD ~4pp 且 CAGR 幾乎不掉=值得;M2 僅 +0.6pp DD(δ 內)=不值得→USD/台幣靜態。0050 報酬王(16.3% vs 20% CAGR);allocator 換 ~3.7pp CAGR 買 DD −34→−19.7%/Sh 1.01→1.21 的順曲線。** ⚠️**alpha 裁決修正(M4 verify,2026-06-19b)：先前「IRvs0050 全負=無 alpha」係 beta-not-alpha 陷阱(CLAUDE.md 鐵則所警示)——allocator β≈0.63<1,牛市負超額是 beta 非缺 alpha。正解＝風險對齊測試(R5 式):beta-adj α=+4.8%/yr、NW t=+3.0(FWD,**gifted 主動 α 關掉仍成立**);vol-matched 同 14.4% vol 下 allocator CAGR 18.3%/Calmar 0.92 vs de-risk-0050 13.2%/Calmar 0.57。⇒ allocator 有真實且顯著的風險調整優勢,來自分散(黃金/債/現金)+regime de-risk,非選股 skill 亦非 gifted α。但此 +α 顯著性倚賴 FWD 窗的 2022 空頭 + 2022-25 黃金多頭(period-specific,前瞻或縮小;與 R5「單資產 regime 防禦真但不顯著」一致,新增者＝6 資產分散在此窗顯著)。**修正陳述:「無超額報酬(低 beta、輸牛市)但有真實風險調整優勢(分散+de-risk、非 skill/gifted-α、且 window-dependent)」。** 註:新代理較粗版 CAGR/Sharpe 微升,係 00991A 去槓桿(β1.19→1.05)降波動 + 模型賦予的 deterministic 淨α(+2.2/+1.0%,**與 R5「主動 alpha 當 0」紀律相左、屬使用者輸入假設**);若 α=0 則 CAGR 約 −0.5pp、結論不變。caveat:主動仍代理(idio 為 Gaussian、未含資產級 −4/−2.5pp DD 懲罰所代表的集中/換股/肥尾風險→真實書 maxDD ≈ MC p5 或更深);未經空頭資料佐證→全為上界。
- **✅ M4 Gate adversarial verify 完成(2026-06-19b)**:獨立 verifier(general-purpose agent)+ 主迴圈自驗複核。**VERDICT＝數字精確重現、結論大致成立但一處 MAJOR 修正**:① look-ahead(M1 shift1 act T+1、M2 連2月確認+落後2月+ffill)OK 無洩漏;② 代理 wiring max|Δ|=0、MC seed bit-identical OK;③ M0 帶寬實作合 doc §6 pseudocode(賣 60% of 超過 TARGET)、優先序/floor 抽象化但 returns-based 不影響 NAV、00864B≥10% floor 有守 OK;④ TC 單邊各腿正確、周轉 drag ~0.09%/yr 不影響排序 OK;⑤ **MAJOR＝「無 alpha」用錯統計(IRvs0050 對低-beta book＝beta 非 alpha),正解 beta-adj α t=3.0/vol-matched Calmar 0.92 vs 0.57＝有真實風險調整優勢(分散+de-risk、非 skill)、α=0 仍成立但 window-dependent**(已於上「全書」條修正陳述);⑥ α=0 敏感度＝headline 幾乎不動(CAGR −0.5pp、IRvs0050 更負→坐實 IR 是 beta 效應)。**整體＝可信、防禦邏輯紮實,唯 alpha 陳述需用 R5 式風險對齊版本(已改)。**
- **M0 上界帶寬細網格掃描(2026-06-19b;`notebooks/regime_tilt/band_upper_sweep.py`)**:應使用者要求對 0050(+7~12%)/00981A·00991A(+6~9%)上界(漲幾 pp 強制賣出)0.5pp 細掃(11×7×7=539,M0+M1 deterministic)。**結果＝完全 inert**:539 格 byte-identical(CAGR 16.26%/Sh 1.205/Calmar 0.827/maxDD −19.66% 全同,spread=0)。診斷證實股票腿最高僅漂到 **0050 37.0% / 00981A 20.7% / 00991A 17.9%(M0 單獨)**,**從不及最緊上界(42/22/22%)** → 月度再平衡(僅 1 月漂移)+33% 防禦腿稀釋+regime 重置使股票權重最多離目標 ~2pp。⇒ **此範圍無「最佳」可挑、零 overfit 風險(現行 default +7/+6/+7% 即可,寬窄等價)**;上界要成為有效「修剪贏家/控集中」槓桿須**反向收緊到 <~37/20/18%**(會犧牲 CAGR,另一個 sweep)。caveat:主動 β-proxy 完全相關壓抑腿間漂移、月度 cadence(真實 00981A 已近 22%)。
- **↑REALISTIC 複跑(2026-06-19b;`band_upper_sweep_realistic.py`)＝修正上條兩缺陷後結論不變**:① 主動改用「更真實」模型＝β+net_alpha **+ idiosyncratic ε(σ 7%/5%)**(打破完全相關 artifact)、N=60 common-random-numbers;② 配置改 **M0+M1+M2**;③ 判定用 verifier 修正的 **beta-adj α vs 0050**(非被 beta 污染的 IRvs0050)。**539 格仍 byte-identical(spread=0):CAGR 16.29%/Sh 1.206/Calmar 0.841/maxDD −19.38%/β-adj α +5.46%/yr/β 0.63;best=default,gap≪2·SE→無真最佳、零 overfit。** band-bind 診斷(idio-on 自由漂移)證 idio 確有加漂移但仍不足:**0050 峰 p95 38.6%/max 39.2%(<42)、00981A p95 21.2%/max 21.7%(逼近但 0/60 路徑破 22%)、00991A p95 19.2%/max 20.1%(<22)**。⇒ **上界 inert 是真結論非 artifact;唯 00981A +6%(22%)是唯一「邊緣活著」的 cap(真實肥尾偶可能咬到)**。要當有效修剪槓桿仍須收緊:0050 <~38% / 00981A <~21% / 00991A <~20%。
- **下一步＝使用者部署抉擇**:全書 + M0 + M1(a=0.75)落地?(M2 建議不做、USD/台幣靜態。)取捨已釐清＝棄 ~3.7pp/yr CAGR(輸牛市 beta)換 DD −34→−19.7%/Sh 1.01→1.21 + 真實但 window-dependent 的風險調整優勢。live 在使用者明確拍板前不動。**〔✅ 2026-06-23 已拍板部署：使用者選擇 M0+M1+M2 三層全開（M2 改用 FRED 真資料上線，非如此處初步建議的「不做」）並上線 paper（mode: allocator、NT$150,000）。此行的「下一步/不動」敘述已被執行 supersede。〕**

### 3.7 🔒 鎖定規格全文（M0+M1+M2）＋ 測試方法論（2026-06-19b 使用者最終拍板定案）

> **單一真相來源**：策略規格 + 驗證方法論定版於此。後續任何改動須在此更新並重跑下列 Gate。**本規格 2026-06-19b 經使用者最終拍板定案＝部署目標版本**（M0+M1+M2 全層 + 00981A 上界 +7% + 所有附帶參數）。部署路徑見 **`docs/M5_DEPLOYMENT_PLAN.md`**。**〔✅ 2026-06-23：已依此凍結規格實作上線 paper（`strategy.mode: allocator`，M0+M1+M2 三層全開）——此處「規劃中／live 仍未動（0050+MA200 overlay）」已被部署 supersede；凍結參數本身未變。〕**

**A. 策略規格（凍結）**
- **資產書（6 檔目標權重）**：0050 35% / 00981A 16% / 00991A 16% / 00635U 10% / 00864B 11.5% / 永豐MMF 11.5%（曝險見 §2）。主動 ETF 代理＝`active_etf_proxy_model_00981A_00991A.md`：r=β·r0050+net_alpha/252+ε（00981A β1.10/α+2.2%/σ7%、00991A β1.05/α+1.0%/σ5%；資產級 DD 懲罰 −4/−2.5pp 為報告 caveat）。
- **M0 靜態不對稱帶寬**（權威全文＝`tw_rebalancing_rules_2026_07.md`）：上界→賣出超過 **target** 的 60%（不賣到 target、留強勢續跑）、跌破下界→買回 target、帶內→持有不重置、MMF 吸收殘差；賣序 00991A→00981A→00635U→0050、買序反向、資金序 MMF超額→MMF常態→00864B超額→其他賣出；硬地板 MMF≥9.5%/00864B≥10%。**帶寬（2026-06-19b）**：0050 (31,42)、**00981A (13,23)**〔上界 +6→+7% 本次放寬〕、00991A (12.5,23)、00635U (8,15)、00864B (10,15)、MMF (9.5,14.5)（%）。
- **M1 股票下行 de-risk**：MA200 骨幹 E1+E2（連 3 日跌破 MA200×0.99 + ±1% 帶確認）；ON → 股票 sleeve ×**0.75**（flat、非分層）、**暫停股票買跌**、釋出資金 2/3→MMF + 1/3→黃金（黃金上限 15%）；OFF 恢復 M0。act T+1（shift1）。
- **M2 美元 tilt**：雙確認（US CPI YoY 近3月下行 **且** Fed funds 近3月下行＝弱美元）→ **±5pp 只動現金**（00864B↔MMF）；月級 + 連2月確認 + 發布落後 shift(2)、受硬地板 clip；黃金不隨 M2。**狀態：邊際（δ 內、僅 +0.6pp DD），列入規格但可關**（關＝USD/台幣靜態各 11.5%）。**〔✅ 2026-06-23：使用者選擇「開」並上線——M2 已實作（`src/data/macro_fetcher.py` MacroMonitor，2026-06-23 實測抓 FRED `fredgraph.csv` 真資料後上線）。±5pp/硬地板等參數同上、未變。〕**
- **再平衡節奏**：月初交易日 + regime/usd 變動觸發；周轉成本 0.002 單邊/各腿（非 MMF）。

**B. 測試方法論（凍結）**
- **引擎**：returns-based 月度+觸發模擬器（`notebooks/regime_tilt/full_book_backtest.py`）；單一 additive 引擎、off ≡ 靜態（行為中性 max|Δ|=0 把關）。
- **walk-forward OOS**：FWD=[2022,2023,2024,2025]、擴張式 train→test；in-sample 只當線索（鐵則#7）。**固定預先指定基準**：0050 買持 + 基準B（vol_target 0.011）；**δ=0.513**（Sharpe 1 SE）為雜訊尺度。
- **真 alpha 檢定（verifier 修正、定版）**：**beta-adj α vs 0050**（OLS、Newey-West HAC t）＋ **vol-matched Calmar**（R5 式，de-risk 0050 到同 vol 比）。**禁用 IRvs0050 當 alpha**（低-beta book 會把 beta 誤判成缺 alpha＝beta-not-alpha 陷阱）。
- **idiosyncratic Monte Carlo**：σ 7%/5% Gaussian 殘差、**common-random-numbers（固定 seed）**、報 path-mean + p5/p95。
- **細網格掃描紀律**：單參數 ≥12–18 點、小步長；判 plateau vs 孤峰 + WF，**不以 in-sample 峰挑參數**。
- **倖存者偏誤**：FinMind 無下市 + 主動未經空頭 → 全 OOS 為**上界**。**Gates（重錨基準，鐵則#8）**：總 Gate＝OOS 勝基準B **或** DD 優勢單獨成立；絕對門檻一律重錨到基準B/0050。
- **Calmar 窗口慣例（避免再混淆）**：報告須標窗口。凍結臂 M0+M1+M2(αON)：**full(2018-25)=0.84｜OOS FWD(2022-25)=~1.00**（差在分子 CAGR：full 16.3% vs FWD 19.1%；分母 maxDD 皆 ~−19%＝2022 主導）。〔不含 M2 的 M0+M1：full 0.83｜FWD αON 0.96/αOFF 0.92——「0.92」屬此臂，勿與含 M2 的 ~1.00 混淆。〕

**C. 凍結結果（M0+M1+M2、含 coupon、idio-on path-mean；M4 verify 通過）**
- 0050 買持 20.0% / Sh 1.01 / Calmar 0.59 / maxDD −34.0%（報酬王）。
- **M0+M1+M2** 16.3% / Sh 1.21 / maxDD −19.1~−19.4% / Calmar **0.84**(full 18-25)｜**~1.00**(OOS FWD 22-25：αON det 1.001·idio-mean 1.002/p5 0.88、αOFF 0.96)。對照 0050 買持 Calmar ~0.59(兩窗近同)。
- **真 alpha**：beta-adj α **+5.46%/yr**（β 0.63；NW t≈+3.0、**gifted α=0 仍成立**）。〔verifier 原始 vol-matched 檢定跑較保守的 M0+M1＝Calmar 0.92 vs de-risk-0050 0.57；加 M2 後 OOS Calmar→~1.00。〕
- **定性**：無超額**報酬**（低 beta 輸牛市 16.3% vs 20%），但有真實且顯著**風險調整**優勢＝分散（金/債/現金）+ regime de-risk（**非 skill、非 gifted α**、window-dependent＝倚賴 2022 空頭+黃金多頭）。
- **重跑**：`.venv/bin/python notebooks/regime_tilt/full_book_backtest.py`（ablation+idio MC）、`band_upper_sweep_realistic.py`（帶寬 inert 證明）。

---

## 4. 殘酷的先驗證據（必讀,避免重蹈覆轍）

1. **E1–E8 事件偵測延伸研究全 FAILED**：比 MA200 更早/更準的崩盤偵測抓不到；vol-spike/from-peak（E4）、組合閘+外資（E5）、美股半導體時點/深度（E7/E7b）全 FAILED；E8（新聞情緒）結構上不可 walk-forward。**→ Monitor 1 除 MA200 骨幹外,預設失敗。**
2. **美股半導體領先 0050 為真但不可萃取**：corr 0.55、Granger 單向,但 ~99% 在開盤跳空被吸收、盤中≈隨機。**→ 不可 front-run 政策/急崩跳空。**
3. **美元 timing 不確定**：機構對 2026 美元方向分歧（Goldman 看貶但自承「條件性綁降息」、ING/Citi 偏多）；華許上任淨偏多美元、與直覺相反。**→ Monitor 2 慢速、保守、跟隨 CPI/Fed。**
4. **兩檔主動 ETF <1 年、未經空頭**：無法直接 walk-forward;分配器下行邏輯只能用 **0050 歷史**驗證、主動以「高 β（~1.2）0050」代理 + caveat;**其真實空頭行為無資料佐證**——這是本計畫最大不確定性。
5. **R5：主動無穩健 alpha、0050 報酬王、regime 僅防禦**。**→ 分配器的價值假設＝降 DD / 改善風險調整後報酬,不是追絕對 alpha。**

---

## 5. Gates 與成功準則（重錨,鐵則#8）

- **對照基準（預先指定,不得事後挑）**：
  - **Baseline-S**：§2 五資產 + 靜態帶寬再平衡（分配器 off）＝**主要對照**。
  - 0050 買持（報酬王 reference）、現行 live（100% 0050 + MA200-85）。
- **過 Gate 條件（walk-forward OOS,擴張窗）**：分配器須**任一成立**——
  - (a) 風險調整後報酬（Sharpe/Calmar）**顯著**優於 Baseline-S（超出 δ＝Sharpe 1SE 雜訊帶）；或
  - (b) **max DD 明顯降低且報酬代價不成比例**（同 R5 的風險對齊檢定:de-risk 到同 vol 比較）。
- **每個訊號/門檻**：細網格（≥12–18 點）、跨參數穩健（plateau 非孤峰）、IRvs0050（真·同 β alpha 檢定,預期多為負,僅防禦線索可留）。
- **additive 行為中性**：分配器 off ≡ Baseline-S;退化參數逐位重現現行 live。
- **survivorship caveat**：FinMind 無下市、主動 <1yr → 所有 OOS 為**上界**,結論帶此標註。
- **資料紀律**：純快取、0 API（共用 builder 配額）。

---

## 6. 分階段 Roadmap（每階段：沙盒 agent workflow → walk-forward → Gate → 使用者拍板）

| 階段 | 內容 | 先驗成功率 | 產出/退路 |
|---|---|---|---|
| **M0 靜態 baseline** | 落地 §2 五資產 + 帶寬再平衡（無分配器）。建立 Baseline-S。 | 高（純分散+紀律,不需 alpha） | **可單獨部署的安全升級**;即使後續全 FAIL 也值得 |
| **M1 股票下行 monitor** | MA200 regime 多資產化（砍股票 sleeve→現金/黃金）。在 0050 歷史 walk-forward。 | 中高（MA200 是唯一證實槓桿） | 過 Gate→併入;否則只留現行 0050-only overlay |
| **M2 美元/利率 monitor** | USD↔TWD 慢速 regime tilt（CPI/Fed 驅動）。 | 低-中（USD timing 難） | 過 Gate→併入;否則 USD/TWD 維持靜態各半 |
| **M3 額外股票訊號** | vol/breadth/US-semi 等（E4–E8 重做於多資產） | **低**（先驗多 FAIL） | 純研究;預期多退回 M1 骨幹 |
| **M4 驗證 Gate**✅ | 全書 ablation + idio MC + adversarial verify（beta-adj α/vol-matched）。**已過**：M0+M1+M2 有真實風險調整優勢（防禦非 alpha） | — | ✅ 完成（§3.7/§5） |
| **M5 部署** ✅ | benchmark→6 資產 allocator 落地（config+引擎+rebalancer+macro），分階段：建置→影子→paper 實跑 | — | **✅ 已於 2026-06-23 實作上線 paper**（`strategy.mode: allocator`、M0+M1+M2 全開、NT$150,000）；計畫＝`docs/M5_DEPLOYMENT_PLAN.md` |

- **M0–M4（研究/驗證）已完成**：規格 M0+M1+M2 於 §3.7 使用者拍板定案；**M5（部署）✅ 已於 2026-06-23 實作上線 paper**（`strategy.mode: allocator`，M0+M1+M2 三層全開；playbook＝`docs/M5_DEPLOYMENT_PLAN.md`）——此處原述「純規劃、live 仍未動」已被部署 supersede（鐵則#2 的「使用者拍板部署」分支）。每階段一項變更、配 plan→execute→(verify)→analyze。
- 可複用 harness：`notebooks/e1e2_walkforward.py`（黃金模板）、`benchmark_backtest.py`、`r0–r6_*`、`capped_sim.py`。

---

## 7. 待使用者拍板的決策（進 M0 前）

> **〔✅ 2026-06-23：以下決策皆已拍板並隨 allocator 上線——再平衡＝M0 不對稱帶寬（月初 + regime/usd 觸發）、tilt 上限＝凍結參數（§3.7）、下行先砍主動高 β、M2 選「做」（FRED 真資料）、載具＝獨立 allocator 引擎（`src/strategy_engines/allocator_engine.py`）。以下為原始待決清單。〕**

1. **再平衡規則**：帶寬（股票 ±5pp？衛星/黃金 ±2–3pp？）vs 定期（季？）vs 混合；以及小額（~十幾萬）下用**盤中零股 + MMF 申購**執行的最低變動門檻（避免過度交易侵蝕）。
2. **分配器 tilt 上限**：§3.4 暫定上限是否合意（保守 vs 積極）。使用者高風險偏好 → 可放寬,但需 OOS 證明值得。
3. **主動 ETF 在下行時的處理順位**：先砍主動（高 β）保 0050,是否同意此預設。
4. **M2 美元 monitor 要不要做**：鑑於 USD timing 不確定 + 先驗低,是否值得投入,或直接 USD/TWD 靜態各半、只靠 CPI 觸發點人工覆核。
5. **部署載具**：分配器要不要做成現有 `benchmark_engine` 的 additive 擴展（單一引擎、行為中性把關),還是獨立多資產引擎。

---

## 8. Caveats（必附）

- **主動 <1yr、未經空頭** → 分配器下行邏輯的 OOS 是「0050 代理 + 主動高 β 假設」,真實主動空頭行為未知（最大不確定性）。
- **集中度未消除**：分配器只能在 regime-off 時暫時降股票;平時仍是 ~67% AI 押注（使用者刻意）。
- **黃金期貨拖累**：00635U contango+費 ~1.43%/年;弱美元時順風、強美元時雙逆風。
- **alpha 預期 FAIL**：這是防禦/再平衡工程,非追 alpha;成功定義＝降 DD 或改善風險調整後報酬 vs Baseline-S。
- **survivorship → 全為上界**。
- **純計畫**：本檔未改任何 code/config/live、未 commit。**〔✅ 2026-06-23 已超越「純計畫」：allocator 已實作並上線 paper（`strategy.mode: allocator`，M0+M1+M2）；本檔自此為原始設計/規格紀錄，實作真相見 CLAUDE.md / `docs/M5_DEPLOYMENT_PLAN.md`。〕**

---

*建立 2026-06-19｜性質：計畫（PLAN）→ **✅ 2026-06-23 已實作上線 paper（mode: allocator，M0+M1+M2 三層全開）**，本檔自此為原始設計/規格紀錄｜上游＝5 資產戰略配置定案（記憶 `portfolio-expansion-5-asset`）｜紀律＝CLAUDE.md 鐵則 + R5/E1–E8 先驗（**定位不變：分散+regime 風控、非經證實 alpha、R5 未翻案**）｜實作真相＝CLAUDE.md / `docs/M5_DEPLOYMENT_PLAN.md`。*

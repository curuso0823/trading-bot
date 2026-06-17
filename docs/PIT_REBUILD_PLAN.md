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

---

## 4. R1–R4 — 在誠實 universe 上重跑 Phase 6/7/8（複用既有 harness，只換 universe）

| 步 | 內容 | 重點 | 複用 |
|---|---|---|---|
| **R1 Phase 6**（最高） | 重掃 `max_positions` | **特別驗「加格在誠實池是否反而需要」** —— 手挑池 6 格已夠、誠實池可能需更多格才接得到龍頭（附錄 B 旗標的疑似翻盤）| `p6_maxpos_sweep.py`、`p6_exit_linkage.py` |
| **R2 動量傾斜** | `score'=chip+λ·mom` 乾淨驗 | 在 PIT+籌碼 上重做 Phase 9 的動量檢定（解除手挑 confound）| `p9_walkforward.py` |
| **R3 Phase 7** | 出場敏感度 | **僅當**誠實池龍頭捕獲仍差才做 | `p7_exit_diag.py` |
| **R4 Phase 8** | walk-forward + 選擇穩定 | 誠實 universe 上的抗過擬合最終把關 | `p8_walkforward.py` |

- 所有決策綁 OOS；**選擇穩定＝Gate、尖峰＝棄、高原＝留**（同 Phase 8 紀律）。

---

## 5. R5 — 正式 alpha 裁決（Phase 10，在**誠實基準**上）

- alpha/beta 迴歸（策略日報酬 vs 0050）、IR 對基準B 的**顯著性**（bootstrap / Newey-West）、籌碼層增量檢定。
- **裁決規則（承總 Gate）**：
  - alpha 對基準B **t ≥ 2**（或 bootstrap 95% 區間不含 0）→ 主動策略有統計可辯護價值 → 進 R6 落地。
  - alpha 不顯著、**但 DD 優勢大到單獨成立 mandate** → 保留但縮小規模，定位為「低回撤工具」。
  - **皆不成立 → 誠實出口：縮小主動部位、以被動（0050 / 基準B）為主。**
- **產出**：`notebooks/r5_alpha_verdict.py`。

---

## 6. R6 — 落地（**僅在 R5 通過**）

- 把通過的「PIT universe 規則 + 有貢獻的 edge 層 + 參數」寫進 code/config：
  - 啟用 `src/backtest/pit_universe.py` + live 端對應接線（**真正 code 改動，取代手挑 watchlist**）。
  - 對應 `config/strategy.yaml` keys、測試 fixture、文件同步。
- 全套 `pytest` 綠 → paper-trade 驗流程 → 小額 live。
- **在此步之前 live 全不動。**

---

## 7. 殘留風險與誠實聲明

- **survivorship**：FinMind 無下市 → 廣池偏樂觀 → 所有 OOS 仍是上界，結論須帶此 caveat。
- **單一市場/單一期間**：統計檢定 power 有限；R5 結果與 R4 穩健性一起讀。
- **核心提醒**：若乾淨真相是「打不贏被動」，**接受它**——這正是整個 v2 後見之明稽核要換來的誠實答案。

---

## 觸發與分支（操作摘要）

- **觸發**：✅ 已達成 —— builder 完成、法人∩融資券 **1813 ≥ 1400**、四方完整 **1706**、除權息足以 `adjust=True` 純快取。R0 已執行。
- **branch**：`pit-rebuild`（R0 產物在此，未 commit）；`main`（live config/src）不動到通過總 Gate。
- **執行順序**：~~前置~~ ✅ → ~~R0~~ ✅ → **R-attrib / R1（下一步，等使用者指令）** → R2 →（R3）→ R4 → R5 →（R6）。每步獨立 checkpoint、回報。

*版本：v1 | 2026-06-16 | 性質：等乾淨 PIT 資料就緒後的執行 playbook（非定論，每步綁 OOS）*

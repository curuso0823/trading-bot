# E8 完整規劃：新聞情緒 ex-post 研究（sentiment vs forward-return）

> **狀態**：規劃完成、**未執行**。承 `docs/EVENT_DETECTION_RESEARCH.md` §3 + §4(E8 列) + 附錄 C/D。
> **定位（讀這段就好）**：E8 是**純 ex-post 研究**，檢驗「台股新聞情緒」與「0050 前向報酬」是否有可萃取關聯。**它在本專案紀律下永遠無法碰 live**（理由見 §1 天花板），唯一合法產出＝一個 **go/no-go 決策：是否值得花錢買 TEJ/聯合知識庫的完整歷史新聞**去做真正的 walk-forward。
> **與前面 E1–E5 的根本差異**：E1–E5 是純快取、0 API；**E8 必須打 FinMind API（~1530 請求）下載新聞**，與背景 full-market builder 共用配額 → 違反鐵則#4 的「純快取」前提 → **必須先取得使用者明確授權 + 配額協調（§3 Stage 0 gate），未授權前不得下載。**

---

## 1. 🟥 天花板（為什麼 E8 永遠不碰 live）— 先講死，免得做完誤判

三個結構性限制，**疊起來 = E8 在紀律下不可能過 Gate**：

1. **2020 急崩完全不在資料窗內**：FinMind `TaiwanStockNews` 自 **2020-04-01** 起；但 COVID 崩盤（0050 自 1 月高點急殺）**底部約落在 2020-03-19**——新聞資料起點**晚於崩盤底**。→ E8 最想驗證的「急崩前新聞是否領先」的**那一次急崩，資料缺席**。
2. **新聞窗內唯一可測崩盤＝2022（n=1）**：2020-04 至今約 6 年，其中只有 **2022 慢熊**一次明確回撤事件。**crash-lead 假說 n=1 → 統計功效 ≈ 0、不可外推。**
3. **無法做本專案 walk-forward OOS**（鐵則#2/#5）：需多個獨立熊市週期切 in/out-sample；新聞只有 1 個 → 結構上不可能過 Gate。

**∴ E8 的最大可能產出 = ex-post 特徵化 + 一個採購決策建議，絕不改 live。** 任何「顯著」結果都只是「值得進一步評估買資料」，不是落地依據。

> **主控誠實預期**：daily sentiment↔return 的學界共識是「contemporaneous 強（新聞反映已發生）、predictive 弱」；本研究**大概率 FAIL（無可萃取前向訊號）**，結論將是「關閉新聞方向、不投入採購/爬蟲」。E8 的價值在於**把這個缺口量化、白紙黑字關掉它**，而非期待找到 alpha。

---

## 2. 目標與假說（pre-register，先寫死再測）

| 假說 | 內容 | 預期 | 性質 |
|---|---|---|---|
| **H1 contemporaneous** | sentiment_t 與 **同日** return_t 強相關 | 成立 | ＝反映已發生、**非**預測（對照組） |
| **H2 predictive（核心）** | sentiment_t 與 **前向** return_{t+1}, r_{t+1..t+5}, r_{t+1..t+10} 相關 / Granger 因果 | 弱/不顯著 | 唯一有決策意義的檢定 |
| **H3 crash-lead** | 負面新聞 spike 是否**領先** 2022 回撤（事件研究） | n=1、描述性 | 無統計力、僅敘事 |
| **H4 vol-predict（附）** | sentiment 對前向**已實現波動**的預測力（崩盤＝波動事件） | 探索 | 比報酬方向可能更實 |

**Non-goals（明確不做）**：不接 live、不做 alpha 宣稱、不碰鉅亨/MOPS 爬蟲（ToS 風險且非必要）、不買商業資料（除非 E8 結果支持才另議）。

---

## 3. 執行階段（含 gate / 估時 / 估費）

### Stage 0 — API 探針 + 配額授權（**GATE，未過不前進**）
- **探針（1–3 個請求、配額可忽略）**：實打 FinMind `TaiwanStockNews` 確認：
  - (a) `data_id` 可否**省略/留空 → 取得市場級「單日全市場新聞」**？（決定下載量級，見下）
  - (b) `description` 欄位實際內容/長度（夠不夠做情緒、需不需要全文）。
  - (c) 每日新聞篇數量級、欄位 schema、確認起始日 2020-04-01。
- **🟥 配額 gate（使用者決策）**：E8 主下載 ~1530 請求共用 builder 配額。執行前必須：
  1. 使用者**明確授權**「花 FinMind 配額跑 E8」；
  2. 確認背景 builder 狀態（在跑/閒置）；限速 ≤ 安全 req/hr，**不餓死 builder**；
  3. 排在 builder 閒置窗或錯開。
- 產出：探針結果 → 決定 Stage 1 的下載策略（市場級 vs bellwether）。

### Stage 1 — 新聞批次下載（依探針二選一）
- **路徑 A（首選，若 data_id 可省）市場級**：1 請求/日 × ~1530 交易日 ≈ **1530 請求**（free 300/hr ≈ ~5–6 hr 掛機；付費 600/hr 減半）。涵蓋全市場新聞。
- **路徑 B（fallback，若必須 per-stock）bellwether 代理**：只抓**權值代表**——`2330`（台積電，0050 權重 ~50%、TAIEX 主導）為主，可選 +`2317`/`2454`。1 檔 × ~1530 日 ≈ 1530 請求/檔。**不做全 50 檔成分（50×1530≈76k 請求、free 層 ~250 hr＝不可行）**；明標「bellwether ≠ 全市場情緒」caveat。
- **快取**：沿用 FinMind 快取目錄 `data/raw/finmind_cache/TaiwanStockNews__*.pkl`（runtime 產物、**不 commit**）；逐日抓→合併存，斷點續傳（已存在則跳過）。
- **不改 live fetcher**：standalone 下載腳本，重用 `FinMindFetcher._request("TaiwanStockNews", …)`（generic、已支援）或自包含 requests；不新增/不修改 live 執行路徑方法。
- **look-ahead 防護**：FinMind news `date`＝**日粒度（無盤中時戳）**→ 保守假設「day t 的新聞最早 t+1 開盤才可用」；所有 predictive 檢定一律用 **forward return from t+1**。

### Stage 2 — 情緒/事件標註
- **主方法**：中文金融 FinBERT `hw2942/bert-base-chinese-finetuning-financial-news-sentiment-v2`（**免費、離線、可重現、零 API/配額張力**）→ 每篇 {neg, neu, pos} 機率。
  - 依賴：`transformers`+`torch`（一次性 model 下載 ~400MB）；CPU 可跑、GPU 更快。
  - caveat：訓練集小（2k）、無 Taiwan 特定驗證 → 需下面交叉驗證。
- **交叉驗證**：用 **Claude Haiku** 對**分層抽樣（2022 崩盤窗 + 隨機）N≈300–500 篇**標情緒，量 FinBERT↔Haiku 一致性（Cohen's κ）→ 判 FinBERT 在台股新聞可靠度。成本 ~$1–5。
- **（stretch、非首版）事件 taxonomy**：對「macro/geo 崩盤觸發類」（Fed/升息/地緣/關稅）用 LLM zero-shot 分類——列為進階、首版不做。

### Stage 3 — 聚合 + 對齊 + 統計 + 報告
- **聚合**：per-article → **日級市場 sentiment 序列**多變體：mean polarity、%negative、news volume、neg-count、(pos−neg)/total。
- **對齊**：0050 已快取還原日線報酬——contemporaneous r_t、forward r_{t+1} / r_{t+1..t+5} / r_{t+1..t+10}、forward 已實現波動。
- **統計檢定**：
  - (a) **相關矩陣**：每個 sentiment 變體 × {contemp, fwd 1/5/10d}；**contemp vs fwd 對比**（區分「反映 vs 預測」）。
  - (b) **Granger 因果**：sentiment→return（控過去報酬 lag）、雙向都測。
  - (c) **預測迴歸**：fwd_return ~ sentiment + controls（news volume、星期、報酬自相關）；**Newey-West HAC** t-stat。
  - (d) **事件研究**：2022 回撤 + 任意 −X% 事件，畫 sentiment 在事件前/中/後路徑（描述性、標 n）。
  - (e) **多重檢定校正**：測多窗多變體 → **Bonferroni/FDR**；報「校正後是否仍顯著」。
  - (f) **功效誠實**：~1500 日 obs 對 daily 關聯尚可；**crash-lead（n=1、2020 缺）功效≈0**，明標。

---

## 4. E8 專屬 Gate / 決策樹（live 永不適用）

E8 **不適用** walk-forward live Gate（資料深度結構上不足）。E8 的**研究 go/no-go**：

- **GO（買資料評估）** ⟸ H2 前向 predictive **校正後仍顯著且方向一致** **且** H3 事件研究顯示 lead：→ 結論「值得評估採購 TEJ（2018 起情緒分數）/聯合知識庫（完整歷史）做真 walk-forward」。
- **NO-GO（關閉方向，預期）** ⟸ 否則：→ 結論「新聞面對本策略**無 ex-post 可萃取前向訊號**、關閉此方向、不投入採購/爬蟲」。
- **任何結果都不碰 live**（鐵則#2/#5）。

---

## 5. 交付物

| 檔 | 內容 | 性質 |
|---|---|---|
| `notebooks/e8_news_download.py` | standalone 批次下載 + 快取 + 斷點續傳 | 沙盒、不改 live |
| `notebooks/e8_sentiment_score.py` | FinBERT 標註 + Haiku 抽樣交叉驗證 | 沙盒 |
| `notebooks/e8_news_analysis.py` | 聚合 + 對齊 + 統計 + 事件研究 | 沙盒 |
| `docs/E8_NEWS_EXPOST.md` | 結果報告 + 功效誠實 + go/no-go | 報告 |
| `data/raw/finmind_cache/TaiwanStockNews__*.pkl` | 新聞快取 | runtime、**不 commit** |

執行模式（若 GO）：沿用 E1–E5 的沙盒多 agent 模式（plan→build→synthesis），或 download→score→analyze 三階段 pipeline。

---

## 6. 紀律張力與風險（必讀）

1. **🟥 API/配額（最大）**：~1530 請求共用 builder 配額 → **Stage 0 配額 gate 為硬前提**（使用者授權 + builder 協調 + 限速）。**未授權前不下載一個 byte。**
2. **2020 缺崩盤**：news 起點 2020-04 晚於 COVID 底（~03-19）→ 最想驗的急崩缺席。
3. **n=1 crash**：crash-lead 無統計力，僅敘事。
4. **代理偏誤**：若走 bellwether（2330）路徑，≠ 全市場新聞情緒；market-level（路徑 A）可得則優先。
5. **look-ahead**：日粒度 news → 一律 forward from t+1；同日新聞視為不可交易。
6. **依賴新增**：FinBERT（torch ~400MB）或 Haiku API（~$1–5）；一次性。
7. **ToS**：FinMind 官方免費層研究可用（OK）；**不碰**鉅亨/MOPS 爬蟲。
8. **survivorship**：與全專案同——結論帶上界 caveat。
9. **不接 live、不 commit（除非使用者明說）、不切 branch**。

---

## 7. 估時 / 估費總表

| Stage | 內容 | 時間 | 費用 | Gate |
|---|---|---|---|---|
| 0 | 探針 + 授權 | 即時 | ~0 | 🟥 使用者授權配額 |
| 1 | 下載 ~1530 請求 | ~5–6 hr 掛機（free） | ~0 | — |
| 2 | FinBERT 標註 + Haiku 抽樣 | 數十分–數小時 | $0（FinBERT）/ ~$1–5（Haiku） | — |
| 3 | 分析 + 報告 | 數小時 | ~0 | — |
| **總** | | **~1 工作天**（不含下載掛機） | **~$0–5** | |

---

## 8. 主控建議（一句話）

**E8 規劃完整、技術全可行，但價值受三重結構限制（2020 缺、n=1、永不碰 live）壓到很低**——它只能產出「要不要買貴資料」的 go/no-go，而預期答案是 no-go。**建議：除非你想為「白紙黑字關掉新聞方向」或「評估 TEJ 採購」而做這份 ex-post 特徵化，否則可不執行。** 若要執行，**Stage 0 的配額授權是不可跳過的第一道 gate**（這是唯一會動到 FinMind 配額、和背景 builder 搶資源的實驗）。

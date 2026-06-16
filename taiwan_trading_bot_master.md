# Taiwan Stock Trading Bot — 完整規劃與程式碼參考文件

> 本文件供 Claude Code 直接使用，包含：  
> 1. 策略概覽與設計決策  
> 2. Implementation Plan（5 個 Phase）  
> 3. 五層架構的資源選用與規則  
> 4. 完整目錄結構（**現況**）  
> 5. 附錄 A：初版完整程式碼快照（歷史參考）／附錄 B：初版從零重建指示（歷史）  

> ⚠️ **本文件是「初版設計藍圖」，含當時的 config 與程式碼快照。策略與實作此後已大幅演進**
> （移動停損/ATR、vol_target 配重、regime 濾鏡、投降感知 capitulation、零股交易、watchlist、
> 並倉上限 3→6…）。**最新真相一律以 `config/strategy.yaml` + `src/` 為準**；本文內嵌的 config/
> 程式碼片段僅供設計脈絡參考，可能與現況不符。文中策略骨架值已校準至現行版本，但內嵌完整原始碼未逐行同步。

---

## 一、策略概覽

> ⚠️ **2026-06-16 起本策略進入 v2 檢討期。**
> 一次完整回測診斷（2018–2025，100k 資金，零股，max_positions=6）顯示：本策略**全期年化僅 12.7%、
> 總報酬 152%，不到 0050 買進持有同期（308%）的一半**，且**未通過自訂 Gate**（最大回撤 -16.0%、破 -15% 線）。
> 多項原始設計前提已被推翻 —— 例如「低頻是因濾網/選股範圍太嚴」是錯的（真因是**並倉上限 + 抱贏家出場**），
> 「擴大 AI 選單能改善績效」在更廣 universe 測試中被反證，watchlist 亦有後見之明/倖存者偏誤之虞。
> **本章以下被推翻的敘述已就地標註「【2026-06-16 診斷後失效，見第六章】」（劃記保留原文，供歷史對照），
> 完整診斷數據、七大缺失與分階段改善計劃見「[六、策略診斷與改善計劃 v2（2026-06-16）](#六策略診斷與改善計劃-v22026-06-16)」**
> 及其連結的 [`docs/IMPROVEMENT_PLAN_v2.md`](docs/IMPROVEMENT_PLAN_v2.md)。未驗證前，請勿再把舊結論當定論引用。

**策略類型**：混合策略 — 技術指標初篩 + 籌碼確認  
**交易市場**：台股（上市 + 上櫃）  
**主要語言**：Python  
**資金規模**：小額試跑（5 萬以下），最多同時持倉 6 檔 _【2026-06-16 診斷後需重新檢視，見第六章：「6 檔並倉上限」是交易頻率與權益曲線穩定度的真正瓶頸，且 100k 零股容量/實用性偏低】_  
**開發工具**：Claude Code（代理式開發，時程以小時計）

### 核心選股邏輯

> 【2026-06-16 診斷後部分失效，見第六章】此「全市場初篩」漏斗為**初版藍圖**；現行 live 實際只掃
> 人工挑選的 watchlist（35 檔，免費 FinMind 額度所限），且該清單於 2026-06 才用「近 3 年 CAGR」
> 把已漲完的 AI 贏家納入、把落後股剔除，**有後見之明/倖存者偏誤**。漏斗實測數字亦與下圖不同（見 6.3）：
> watchlist 上 TA 四條件 AND 後僅 6.74% stock-day 通過、最終 entry 僅 4.15%、50.5% 交易日為 0 候選。
> **更關鍵：放寬量比門檻讓訊號從 2831 暴增到 7524，交易數卻幾乎不變（221→219）——
> 證明選股漏斗不是交易頻率的瓶頸，真正卡點是並倉上限 + 抱贏家出場（見 6.4）。**

```
全市場 ~1,700 檔
  → TA 初篩（MA20 突破 + 量能放大 + RSI 健康）  →  50–80 檔 / 日
  → 籌碼評分（法人買超加分制 + 融資健康度）     →   5–15 檔 / 日
  → 進場候選清單（chip_score ≥ 2 分）
```

### 關鍵設計決策

| 決策點 | 選擇 | 原因 |
|--------|------|------|
| 策略類型 | TA 為主 + 籌碼確認 | 純籌碼訊號稀少，樣本數不足；純 TA 競爭激烈，alpha 衰退快 |
| 籌碼門檻 | 加分制（非硬門檻）| 確保每日候選 5–15 檔，回測樣本數可達 50+ 筆 |
| 券商 API | 永豐 Shioaji | 台股 Python 生態最完整，社群資源最豐富，API 免費 |
| 歷史資料 | FinMind（免費）| 涵蓋日K、法人、融資，免費層回測夠用 |
| 即時資料 | Fugle MarketData（免費）| 盤中報價，免費層頻率足夠 |
| 回測框架 | Vectorbt | 向量化，參數掃描速度快，適合小資金策略驗證 |

> 【2026-06-16 診斷後失效，見第六章】上表「籌碼門檻＝加分制 → 確保候選 5–15 檔 → 回測樣本 50+ 筆」
> 的因果論述在現行 watchlist + 並倉上限架構下**不成立**：候選數多寡幾乎不影響成交筆數（放寬量比訊號量 ×2.7
> 交易數不動），且籌碼疊加對 Sharpe 僅貢獻約 +0.2，核心 edge（站上向上 MA20＋量比 1.5＋RSI 50–80）
> 為通用動量/突破，並非獨特優勢。**整體「相對 0050 的價值主張」需重新評估**（唯一硬優勢是回撤減半）。

---

## 二、Implementation Plan

### 總覽

| Phase | 名稱 | 工時 | 狀態 |
|-------|------|------|------|
| 0 | 環境建置 & 資料驗證 | 3–4 h | 未開始 |
| 1 | 技術指標選股層（TA 初篩）| 6–7 h | 未開始 |
| 2 | 籌碼確認層（品質過濾）| 5–6 h | 未開始 |
| 3 | 策略回測 & 參數優化 | 10–12 h | 未開始 |
| 4 | 自動化下單系統建構 | 9–11 h | 未開始 |
| 5 | 監控通知 & 實盤上線 | 4–5 h | 未開始 |
| **合計** | | **~38 h** | |

### Phase 0：環境建置 & 資料驗證（3–4 h）

**任務清單：**

| # | 任務 | 工時 |
|---|------|------|
| 0.1 | 建立專案目錄結構、虛擬環境、安裝所有依賴 | 0.5 h |
| 0.2 | 申請 FinMind 免費 token，測試法人/日K/融資資料拉取 | 1 h |
| 0.3 | 申請 Fugle MarketData API key，測試即時報價連線 | 1 h |
| 0.4 | 資料品質驗證 notebook：時間軸對齊、除權息還原、缺值處理 | 1.5 h |

**完成標準：** 可輸出任一股票近 3 年乾淨合併 DataFrame（還原日K + 法人買賣超，時間軸正確對齊，無缺值）

> **注意**：現在就去申請 FinMind + Fugle + 永豐帳戶，讓等待期與 Phase 1–2 開發並行

---

### Phase 1：技術指標選股層（6–7 h）

**TA 初篩三條件（AND 關係）：**
1. 收盤站上 MA20 且 MA20 向上斜（近 3 日斜率為正）
2. 當日成交量 > 過去 20 日均量 × 1.5（量能放大）
3. RSI(14) 介於 50–80（強勢但未超買）

| # | 任務 | 工時 |
|---|------|------|
| 1.1 | TechSignal class：pandas-ta 計算 MA/RSI/量比/布林通道 | 1.5 h |
| 1.2 | 各條件函數獨立封裝（is_above_ma / is_volume_surge / is_rsi_healthy）| 1 h |
| 1.3 | 全市場批次掃描器（含 rate-limit sleep + retry）| 2 h |
| 1.4 | mplfinance 視覺化驗證，確認訊號出現時機合理 | 1.5 h |

**完成標準：** 給定任意日期，輸出當日符合 TA 三條件的股票清單，數量在 30–100 檔之間

---

### Phase 2：籌碼確認層（5–6 h）

**籌碼評分規則（加分制）：**

| 條件 | 分數 |
|------|------|
| 外資近 3 日累計買超 > 0 | +2 分 |
| 投信近 5 日累計買超 > 0 | +1 分 |
| 融資使用率 < 15%（籌碼乾淨）| +1 分 |
| 融券張數近 3 日急增 > 20% | −1 分 |
| **進場門檻** | **≥ 2 分** |

> 採加分制而非硬門檻，確保每日候選 5–15 檔，回測樣本數 50+ 筆

| # | 任務 | 工時 |
|---|------|------|
| 2.1 | ChipAnalyzer：外資/投信買賣超 rolling 計算 | 2 h |
| 2.2 | MarginAnalyzer：融資使用率 + 融券急增偵測 | 1.5 h |
| 2.3 | ScoreEngine：串接 TA 候選池 + 籌碼評分，輸出最終候選表 | 1.5 h |

**完成標準：** ScoreEngine 輸出每日 5–20 檔含 TA 指標 + 籌碼評分的候選清單

> **重要**：法人資料 T+1 延遲。籌碼資料用「前日」，TA 訊號用「當日收盤」，合併後隔日才能下單

---

### Phase 3：策略回測 & 參數優化（10–12 h）

| # | 任務 | 工時 |
|---|------|------|
| 3.1 | Vectorbt 台股回測框架（交易成本 + 漲跌停模擬 + T+1 延遲）| 2 h |
| 3.2 | 進出場規則參數化（停損/停利/跌破MA/持有天數上限，全寫進 YAML）| 2.5 h |
| 3.3 | Walk-forward 驗證（2019–2022 訓練，2023–2024 驗證）| 3 h |
| 3.4 | Quantstats 績效報告（夏普/回撤/月勝率/Alpha vs 大盤）| 1.5 h |
| 3.5 | TA only vs 混合策略對比實驗（量化籌碼層的實際貢獻）| 1.5 h |

**台股交易成本設定：**
- 買進：手續費 0.1425%
- 賣出：手續費 0.1425% + 交易稅 0.3%
- 最低手續費：20 元
- 額外滑價：0.1%（模擬真實市場）

**Gate 條件（不達標回 Phase 1–2 調整）：**

| 指標 | 門檻 |
|------|------|
| Out-of-sample 夏普比率 | ≥ 1.0 |
| 最大回撤 | ≤ −15% |
| 年化報酬率 | ≥ 10% |
| 交易筆數 | ≥ 50 筆 |

> **「交易筆數 ≥ 50 筆」是統計信心的唯一來源，且在「歷史回測」上量測，不靠實盤/模擬盤累積。**
> 回測一次跑 8 年（2018–2025）即遠超門檻：全期 222 筆、config out-of-sample(2023–24) 60 筆、
> 近兩年 68 筆，每個視窗都 ≥ 50（見 `notebooks/gate_check.py`）。
> 因此 live 端**不需要、也不應該等實盤交易攢到 50 筆**——live 是低頻趨勢策略（降頻、抱贏家、
> 並倉上限 6、常有 0 候選日），那是設計而非缺陷。實盤年化約 10 筆，硬等 50 筆要數年且無意義。

> 【2026-06-16 診斷補述，見第六章】低頻**本身**確為設計，但其**主因歸屬**已被重新確認：
> 真因是「並倉上限 6 + 抱贏家（ATR 移動停損、最長 60 天、無停利）」鎖死週轉，**不是濾網/選股範圍太嚴**。
> 證據：同 35 檔 universe 把 max_positions 6→10→15→20，交易/年從 27.8→43.6→61.5→73.8。
> 另外，本診斷實測**全期最大回撤 -16.0%，已破 -15% Gate 線（未通過）**，與上方「遠超門檻」需分別看待
> （筆數達標 ≠ 回撤/Sharpe 達標）。是否、如何提高頻率屬待驗證的 v2 議題，見 6.5 / Phase 6。

---

### Phase 4：自動化下單系統建構（9–11 h）

| # | 任務 | 工時 |
|---|------|------|
| 4.1 | 永豐 Shioaji 串接（登入/查餘額/查持倉，API key 存 .env）| 1.5 h |
| 4.2 | OrderManager（買/賣/漲停重試/部分成交/委託逾時取消）| 2.5 h |
| 4.3 | PositionManager（持倉追蹤，本地 JSON 持久化，最多 6 檔）| 2 h |
| 4.4 | RiskGuard（停損/日虧損上限/連虧熔斷/倉位上限）| 2 h |
| 4.5 | APScheduler 排程整合（盤前選股→開盤下單→盤中監控→盤後報表）| 1.5 h |

**風控規則（硬性，依優先順序）：**
1. 單筆虧損 −5% → 自動砍倉
2. 單日虧損 > 總資金 −2% → 全停機
3. 連虧 3 筆 → 暫停等人工審核
4. 單股倉位 ≤ 總資金 30%
5. 持倉數 ≤ 6 檔

**Gate 條件：** 模擬盤連跑 10 個交易日（2 週）無異常才切實盤。

> **此關驗證「系統運轉正確」，不重新驗證「策略 alpha」——後者已由 Phase 3 回測 50+ 筆完成。**
> 故此 gate **不要求任何最低交易筆數**（可能整段期間僅 0–數筆進場，甚至全空手，皆算通過）。
> 「無異常」指標：① 排程準點（盤前選股→開盤下單→盤中監控→盤後報表全跑完）、
> ② 下單/成交回報與本地持倉/現金對得起來、③ RiskGuard 該觸發時有觸發（停損/熔斷/倉位上限）、
> ④ 無未捕捉例外或資料拉取失敗導致用過期名單下單。重點是流程穩定，不是交易頻率。

---

### Phase 5：監控通知 & 實盤上線（4–5 h）

| # | 任務 | 工時 |
|---|------|------|
| 5.1 | Telegram Bot（進場/出場/停損/熔斷/每日摘要/error traceback）| 1.5 h |
| 5.2 | Python logging 結構化日誌（RotatingFileHandler，保留 30 天）| 0.5 h |
| 5.3 | 部署（GCP e2-micro 永久免費層 或 本機）| 1.5 h |
| 5.4 | 實盤切換 & 首週人工監控，準備一鍵緊急停機指令 | 1 h |

**實盤上線標準：**
- 初始資金 ≤ 3 萬（剩餘備用）
- 第一個月目標：零系統錯誤，下單行為 100% 符合預期
- 報酬率是次要的，這個月的任務是找 bug，不是賺錢

---

## 六、策略診斷與改善計劃 v2（2026-06-16）

> 章節編號沿用使用者指定的「六」，**內容上承接「二、Implementation Plan」**（故置於此處）。
> 本章是 2026-06-16 完整回測診斷的結論彙整 + 改善方向；**分階段改善計劃的展開細節見**
> [`docs/IMPROVEMENT_PLAN_v2.md`](docs/IMPROVEMENT_PLAN_v2.md)。
>
> ⚠️ **語氣聲明**：除「診斷數據/結論」（已實證）外，所有改善方向皆為**方向性、待驗證的假說**，不是定論。
> 在對應 Gate 與 walk-forward 通過前，請勿把點子當結論引用或拿去調 live。
>
> 🟥 **【後見之明污染補述 — 2026-06-16】** 上句「診斷數據/結論（已實證）」需修正：**§6.2 的絕對績效（12.7%／1.16／−16.0%／152%）、6.3 漏斗、Phase 6/7/8 的數字都在手挑 35 檔 watchlist 上量測，帶 look-ahead 污染、被高估**（Phase 9 量化同規模手挑溢價 **+0.38 Sharpe／+9pp**，下界）＝「錯誤被污染」，**勿當定論**。全清單見 [`docs/IMPROVEMENT_PLAN_v2.md`](docs/IMPROVEMENT_PLAN_v2.md) 附錄 B；乾淨重建步驟見 [`docs/PIT_REBUILD_PLAN.md`](docs/PIT_REBUILD_PLAN.md)。

### 6.1 診斷基本設定

| 項目 | 設定 |
|------|------|
| 回測期間 | 2018–2025（約 8 年）|
| 初始資金 | 100,000 元（100k）|
| 交易單位 | 零股 |
| 並倉上限 | max_positions = 6 |
| 選股池 | watchlist 35 檔（現行 live 設定）|

### 6.2 全期績效與被動基準對照　🟥【錯誤被污染：35 檔手挑 watchlist，下表絕對數字高估（+0.38 Sharpe／+9pp 下界），見 IMPROVEMENT_PLAN_v2 附錄 B；勿當定論】

| 指標 | 現行策略（35 檔, 6 格）| 0050 買進持有（同期）|
|------|------------------------|----------------------|
| 年化報酬 | **12.7%** | **20.0%** |
| 總報酬 | **152%** | **308%** |
| Sharpe | **1.16** | 1.01 |
| 最大回撤 | **-16.0%** | -34.0% |
| Profit Factor | 1.97 | — |
| 勝率 | 48% | — |
| 交易筆數 | 222（≈27.8/年）| — |
| 自訂 Gate | **未通過**（DD -16% 破 -15% 線）| — |

**一句話結論**：整套複雜系統的總報酬不到 0050 的一半，Sharpe 僅微幅領先（單一市場/單期間樣本下不具統計顯著性），
**唯一硬優勢是回撤減半**（且 2022 熊市 -3.2% vs 指數 -22%）。

### 6.3 選股漏斗（35 檔 watchlist）

| 漏斗層級 | 通過率 / 說明 |
|----------|----------------|
| regime 閘門 | 只允許 **64.3%** 的交易日可進場 |
| TA 四條件 AND | 僅 **6.74%** 的 stock-day 通過 |
| ↳ 最大瓶頸：量比 ≥ 1.5x | 單條只有 **14%** 通過 |
| 最終 entry | 僅 **4.15%** 的 stock-day |
| 0 候選交易日佔比 | **50.5%**（過半交易日完全無候選）|

### 6.4 關鍵因果發現（最重要）

**交易頻率低的真因是「6 格並倉上限 + 抱贏家出場（ATR 移動停損、最長 60 天、無停利）」，不是選股範圍或濾網。**

| 證據 | 數據 |
|------|------|
| (a) 放寬量比門檻 → 訊號暴增、交易數幾乎不動 | 訊號 2831 → **7524**；交易數 221 → **219** |
| (b) 同 35 檔 universe，加大並倉上限 → 交易/年單調上升 | max_pos 6→10→15→20：交易/年 **27.8 → 43.6 → 61.5 → 73.8** |
| (c) 擴大 universe（35→53 檔）→ 全面變差 | 年化 12.7%→**9.9%**；Sharpe 1.16→**0.86**；DD -16%→**-23.5%** |

> 推論：瓶頸在「資金/格數週轉」與「抱贏家鎖倉」，不在訊號數量；單純擴大選股池反而引入更差標的、惡化風險。

> **Phase 6 已執行（2026-06-16，in-sample 線索）**：權衡曲線確認——① 固定配重加大並倉 DD 爆掉（N≥8 達 -21~-23%，REJECT）；
> ② 配套A（單檔配重 ∝6/N）壓住 DD/集中度但稀釋年化 → 無格過 Gate；③ **配套A＋配套C（高N守恆＋max_hold≈90＋atr_hi≈0.15）in-sample 有 4 格通過**
> （最佳：Sharpe 1.14→**1.36**、Calmar 0.91→**1.31**、DD -13.8→**-9.9%**、top3 49→**28%**、交易 27.6→**45/年**、年化持平）。
> 但**大多頭捕獲（#4）未改善**（2024 仍 ~+10% vs 0050 +49%）、且屬單期峰值獵取 → **未過 Phase 8 walk-forward 不調 live**。
> 詳見 [`docs/IMPROVEMENT_PLAN_v2.md`](docs/IMPROVEMENT_PLAN_v2.md) Phase 6「結果」。

> **Phase 8 已執行（2026-06-16，walk-forward 抗過擬合）**：上述 Phase 6 候選（守恆N15·90·.15）**未通過** out-of-sample。
> 真·再優化 walk-forward（擴張訓練窗）的點時 Gate **從未選到它**（4 窗 3 次選回固定 6 格）＝典型 4/72 單期峰值；
> pooled OOS Sharpe **1.36 打不贏現行 6 格的 1.40**、且為尖峰（max_hold 90→60 Calmar -39%）非高原。唯一前瞻穩健效果是**降 DD**（最差前進年 -9.3% vs 基準 -13.0%），與「唯一硬邊是回撤」一致。
> **`max_positions` 維持 6、出場維持 60/0.09、配重維持 0.30，live 全不動。** IR vs 基準B≈0（+0.01）預示 #1 / Phase 10。詳見 [`docs/IMPROVEMENT_PLAN_v2.md`](docs/IMPROVEMENT_PLAN_v2.md) Phase 8「結果」。

### 6.5 七大缺失（quant 角度）

| # | 缺失 | 重點 |
|---|------|------|
| 1 | **跑輸被動基準** | 年化 12.7%、總報酬僅 0050 一半（152% vs 308%）；Sharpe 領先微小且不顯著；唯一硬優勢是回撤減半 |
| 2 | **選股池後見之明/倖存者偏誤** | watchlist 人工挑選，2026-06 才用「近 3 年 CAGR」把已漲完 AI 贏家納入、剔除落後股＝用未來資訊優化歷史；前瞻績效恐顯著低於回測 |
| 3 | **過度擬合與脆弱性** | 參數針對 2018–2025 台股調峰值；同 35 檔僅差 3 個訊號，DD 就從 -13.8% 擺到 -16.0%（2.2pp）；有效持倉僅 ~5.3 檔，單檔特異風險主導權益曲線 |
| 4 | **趨勢策略卻在大多頭年慘敗** | 2024（0050 +49%）只賺 7.2%、2020（+30%）只賺 17.5%；ATR 8–9% 停損對高波動電子/AI 太緊，被洗出難追回；本質是低 beta 防禦工具，與「抱贏家」矛盾。**【2026-06-16 Phase 7 診斷：真因為結構性集中度、非 exit；見 6.5 後註與 v2 Phase 7 結果】** |
| 5 | **集中度同時綁死頻率與穩定度** | 6 格、單檔上限 30%，有效分散僅 ~5 檔 |
| 6 | **核心 edge 普通** | 進場＝站上向上 MA20＋量比 1.5＋RSI 50–80，就是通用動量/突破；籌碼疊加僅貢獻約 +0.2 Sharpe |
| 7 | **100k 零股容量/實用性低** | 最低配重 1 萬/檔、高價股買不起、零股滑價吃報酬；12.7%/年 ≈ 1.27 萬絕對獲利，相對維運複雜度投報比低 |

> **Phase 7 已執行（2026-06-16，診斷先行）**：針對 #4 的診斷（`notebooks/p7_exit_diag.py`，純快取）證實——
> **大多頭慘敗的真因是結構性（資金攤在 6 格非龍頭籃子、無法集中／輪動到少數 +49% 龍頭），不是「ATR 停損太緊被洗出」。**
> kill-switch 探針顯示放寬/拉長出場**反而讓 2024 更糟**（捕獲率 0.29 → 兩者全開 0.03），且 2020 與 2024 對出場寬度**反應相反** → exit 寬度非大多頭捕獲的系統性槓桿。
> 2024 切片 avg 並倉 5.61/6（格子是滿的）、AI 龍頭有進場但被攤散在落後股中、靠頻繁換股賺得多於抱著。
> **故 regime 連動停損／分批停利／加碼（原 Phase 7 做法①②③）對 #4 以 exit 角度否決——未改引擎、未動 live。** #4 真正槓桿移交
> **Phase 9（規則化集中到當期龍頭）** 與「重訪集中度」（與 Phase 6「加格」相反，需更集中而非更分散）。詳見 [`docs/IMPROVEMENT_PLAN_v2.md`](docs/IMPROVEMENT_PLAN_v2.md) Phase 7「結果」。

> **Phase 9 已執行（2026-06-16，規則化選龍頭 + 消除後見之明）**：
> · **#4**：純集中（max_pos↓）反傷；動量傾斜（`score'=chip+λ·mom_rank`）in-sample 把 2024 捕獲 0.29→0.39、IR vs 基準B +0.04→**+0.26**，但**過不了再優化 walk-forward**（點時 Gate 4 窗 3 次選回不傾斜＝選擇不穩）、且其 edge **完全依附「手挑35+籌碼」鷹架** → 列 **可選、待廣池籌碼 cache 補完做「PIT+籌碼」乾淨檢定、不否決、亦不採用 live**。
> · **#2（關鍵）**：廣池 1,979 檔做機械 PIT 選龍頭（price-only），**同規模純「手挑」溢價 = +0.38 pooled OOS Sharpe / +9pp 年化（下界，倖存者未除）**；最佳誠實 PIT 機械策略 0.50 **打不贏被動**（基準B 0.80、0050 1.01）→「去後見之明後 alpha 大幅縮水」**確認**。機械選龍頭 2024 捕獲 0.09≪0.29 → **「規則化選龍頭當機械 universe」否決**。
> · **級聯決策（不重跑 6/7/8）**：機械 universe 次於被動、非可信基底；6/7/8 的否決「能否轉移到誠實 PIT universe」**未驗**（尤其 **Phase 6「加格」否決疑為後見之明產物** —— 手挑贏家池裡 6 格已夠、誠實池裡可能反需加格）。**live 全不動。**
> · **全專案選股 universe 後見之明污染稽核（含更早期 Phase 與被否決結論）+ PIT 重構範圍 → 見** [`docs/IMPROVEMENT_PLAN_v2.md`](docs/IMPROVEMENT_PLAN_v2.md) **附錄 B**。

### 6.6 該肯定之處（不要一併否定）

- **回撤控制是真的**：全期 -16% vs 指數 -34%；2022 熊市 -3.2% vs -22%。
- **regime / 投降感知（capitulation）模組有效**：block_only 確實擋掉假反彈、解掉深熊。
- **工程品質與文件詳盡**：模組分層、單一真相 config、測試覆蓋皆到位。

### 6.7 分階段改善計劃（方向性、待驗證）

> 以下為各 Phase 的**目標摘要**；每階段的「做法 / 驗證實驗 / 驗證指標(Gate) / 風險」完整展開見
> [`docs/IMPROVEMENT_PLAN_v2.md`](docs/IMPROVEMENT_PLAN_v2.md)。**所有方向在 Gate + walk-forward 通過前皆非定論。**

| Phase | 目標 | 對應缺失 | 關鍵 Gate（摘要）|
|-------|------|----------|------------------|
| **Phase 6** ✅已執行：並倉上限與交易頻率 | 拆解低頻真因；畫「頻率 vs 風險調整報酬」權衡曲線。**加大並倉須綁配套**（縮小單檔配重 / 組合層波動目標 / 出場改造），因為單純 6→20 已知**不改善 Sharpe 還惡化 DD**。→ **已畫曲線（2026-06-16）：配套A＋C 高N守恆 in-sample 4 格過 Gate；live `max_positions` 維持 6，候選區 deferred 至 Phase 8 驗證** | #5, #3 | DD 不破 -18%（理想回 -15%）；Calmar/Sharpe 相對 6 格 +≥10%；單檔貢獻度下降 |
| **Phase 7** ✅已執行（診斷先行）：出場改造 | 修正大多頭年慘敗：停損寬度與 regime 連動、分批停利、（謹慎）加碼、重評 max_hold_days=60。→ **診斷（2026-06-16）以 exit 角度否決**：放寬/拉長出場反讓 2024 更糟（捕獲 0.29→0.03）、2020 與 2024 反應相反 → #4 為**結構性集中度**問題非 exit；未改引擎、live 不動，#4 移交 **Phase 9（規則化選龍頭）/ 重訪集中度** | #4, #6 | 大多頭年 up-capture 顯著上升；熊市 down-capture 不惡化；Sharpe/Calmar 不降 |
| **Phase 8** ✅已執行：抗過擬合壓測 | 滾動 walk-forward、參數高原檢測、擾動/bootstrap。→ **walk-forward（2026-06-16）否決 Phase 6 候選**：點時再優化從未選到守恆N15·90·.15（4/72 單期峰值）、pooled OOS Sharpe 1.36 **打不贏現行 6 格 1.40**、且為尖峰非高原；唯一前瞻穩健效果是降 DD（-9.3 vs -13.0）。**live 全不動**；IR vs 基準B≈0 預示 Phase 10。#4 移交 Phase 9 | #3 | OOS 聚合達 Gate（Sharpe≥1.0 / DD≤-15% / 年化≥10%）；參數落在高原而非尖峰 |
| **Phase 9** ✅已執行：point-in-time 規則化選股 + 規則化選龍頭 | 消除後見之明(#2) + 大多頭捕獲(#4)。→ **(2026-06-16)**：#4 動量傾斜 in-sample 誘人(2024 捕獲 0.29→0.39、IR +0.04→+0.26)但**過不了 walk-forward**、且**完全依附手挑池** → 列**可選、待廣池籌碼 cache 補完再驗、不否決**；**#2 確認為大**(同規模純手挑溢價 **+0.38 pooled Sharpe / +9pp**，下界)、機械選龍頭**否決**(2024 捕獲 0.09≪0.29)、誠實 PIT 機械策略 **0.50 打不贏被動 0.80** → **live 全不動**。級聯：**不重跑 6/7/8**(機械 universe 非可信基底)，**但其否決「可轉移到誠實 PIT」未驗**。全專案 universe 污染稽核 + PIT 重構範圍見 [`docs/IMPROVEMENT_PLAN_v2.md`](docs/IMPROVEMENT_PLAN_v2.md) **附錄 B** | #2, #4 | 去後見之明後 OOS 仍達 Gate（**未達**：誠實機械 0.50 < 被動 0.80）|
| **Phase 10**：對 0050 正式 alpha/IR 檢定 | alpha/beta 迴歸 + IR 顯著性 + 籌碼層增量檢定；裁決「主動策略值不值得維運」 | #1, #6 | 對「0050+vol-target」alpha t≥2（或 bootstrap 95% 不含 0）；籌碼層 IR 增量須顯著否則降級 |
| **Phase 11**：容量/實用性/投報比 | 資金規模敏感度、零股滑價回灌、高價股可及性、維運成本對帳 | #7 | 滑價校準後年化衰減 < 2pp；給出正投報比的最小資金門檻 |

> **凌駕各 Phase 的總決策基準**：v2 新增「**0050+波動目標(vol-target)**」對照組當決策門檻——
> 它享受被動 beta 但回撤被壓到與本策略相近，是最公平的對手。**若本策略風險調整後贏不過它（Phase 10 檢定不顯著、
> 且回撤優勢不足以單獨成立 mandate），v2 的理性結論可能是「縮小主動部位、以被動為主」。**

### 6.8 舊策略前提失效標註（避免未來誤引用）

下列原始設計前提/結論已被本次診斷**推翻或需重新檢視**。文中相關處已就地加註「【2026-06-16 診斷後失效，見第六章】」（劃記保留原文）：

| 已失效/待重評的舊敘述 | 新診斷結論 |
|------------------------|------------|
| 「低頻是因濾網/選股範圍太嚴」 | **錯**。真因是 6 格並倉上限 + 抱贏家出場（放寬量比訊號 ×2.7，交易數不動；加大並倉交易/年 27.8→73.8）|
| 「擴大 AI 選單能改善績效」 | **被反證**。35→53 檔後年化 12.7%→9.9%、Sharpe 1.16→0.86、DD -16%→-23.5%，全面變差 |
| 「籌碼加分制 → 候選 5–15 檔 → 樣本 50+ 是 alpha 來源」 | 候選多寡幾乎不影響成交筆數；籌碼僅貢獻約 +0.2 Sharpe，疑似不顯著（待 Phase 10 檢定）|
| 「本策略相對 0050 具明確價值主張」 | **需重評**。總報酬僅 0050 一半、Sharpe 領先不顯著；唯一硬優勢是回撤減半 |
| 「watchlist 是中性的流動性標的池」 | **【Phase 9 已量化，2026-06-16】** 含後見之明/倖存者偏誤：**同規模純「手挑」溢價 = +0.38 pooled OOS Sharpe / +9pp 年化（下界，倖存者未除）**；誠實 PIT 機械策略（0.50）**打不贏被動**（基準B 0.80）。`AI_ADOPTED` 4 檔（3017/8299/2449/8210）更是用 **2023–25 績效分窗**挑出（`universe_ai_window.py`）＝直接 look-ahead；`REMOVED_LAGGARDS` 7 檔以「近 3 年 CAGR 落後」剔除＝事後剔輸家。**全專案污染稽核＋PIT 重構範圍見 [`docs/IMPROVEMENT_PLAN_v2.md`](docs/IMPROVEMENT_PLAN_v2.md) 附錄 B。** |
| 「並倉上限 6 純為設計、無副作用」 | 6 格同時綁死交易頻率與權益曲線穩定度（有效分散僅 ~5 檔）；需在 Phase 6 重新權衡 |
| Phase 3 Gate「遠超門檻」的樂觀敘述 | 筆數確實達標，但**全期 DD -16% 已破 -15% Gate（未通過）**；筆數達標 ≠ 風險指標達標 |

> 注意：上表僅標示「失效/待重評」，**不否定 6.6 的肯定項**（回撤控制、regime 模組、工程品質仍有效）。

### 6.9 config 中已標註「效果不良不要採用」的選項清單

下列選項經實證否決（多數有對應 `notebooks/*backtest*.py` 證據），**程式碼保留、預設關閉，未來不要再採用**。
由主導者在 `config/strategy.yaml` 就地加註「效果不良不要採用」；本表僅作文件記錄，**不修改 config**。

| config 選項 | 區塊 | 預設 | 否決原因（摘要）|
|-------------|------|------|------------------|
| `max_ext_pct` | ta_filter（過度延伸濾鏡）| null（關）| 離 MA20 乖離上限濾鏡，實證無增益 |
| `max_vol_pct` | ta_filter（過度延伸濾鏡）| null（關）| 20 日已實現波動上限濾鏡，實證無增益 |
| `market_vol_scaling` | 配重 | false | 市場波動曝險縮放，實證效果不良 |
| `selection.sector_cap`（`sector_cap_enabled`）| selection | false | 類股分散上限，實證無助益 |
| `regime.require_ma_slope` | regime | false | 進場加 MA60 斜率向上條件，實證 wash |
| `capitulation.reclaim_exempt_days` | capitulation | 0 | 實證為刀鋒過擬合 |
| `capitulation.failed_bottom_exit`（P3）| capitulation | false | 「失敗底出場」實證反傷 |
| `capitulation.deep_bear` | capitulation | 關 | block_only 已解深熊，deep_bear 無增量（notebooks/deep_bear_backtest.py 否決）|
| `capitulation.allow_mode` 的 `unlock_only` / `full` | capitulation | block_only | unlock_only 早解鎖在熊市淨負（Sharpe 0.79）；採 block_only |
| `capitulation.panic_use_amihud` | capitulation | false | Amihud 在爆量崩盤反而偏低（分母爆量），不可當投降訊號 |

> 共通原則：這些都是「程式保留以便日後診斷、但已被實證否決」的旋鈕，預設 OFF。**v2 不應重新打開它們去追歷史峰值**，
> 除非有新的、通過 walk-forward 的證據。

---

## 三、五層架構的資源選用與規則

### 層 1：資料取得層

| 用途 | 工具 | 費用 | 說明 |
|------|------|------|------|
| 歷史日K + 法人 + 融資 | FinMind API | 免費 | 免費版每日 600 次請求，批次掃描需加 sleep(0.5s) |
| 盤中即時報價 | Fugle MarketData | 免費 | 申請 API key，有每秒頻率限制 |
| 上市/上櫃股票池 | 證交所公開頁面爬取 | 免費 | 本地快取，不需每次重抓 |

**重要規則：**
- 所有外部 API 呼叫集中在 `src/data/fetcher.py`，上層模組不直接碰 requests
- FinMind 每次請求後 sleep 0.5 秒，避免超過免費額度
- 法人資料為 T+1（今日資料明日才有），計算時使用前一個交易日
- 日K使用還原收盤價（`TaiwanStockPriceAdj` dataset）

---

### 層 2：市場分析層

| 用途 | 工具 | 費用 | 說明 |
|------|------|------|------|
| 技術指標計算 | pandas-ta | 免費 | 130+ 指標，純 Python，無須編譯 |
| 籌碼因子計算 | 自行實作（基於 pandas）| — | ChipAnalyzer + MarginAnalyzer |
| 視覺化驗證 | mplfinance | 免費 | K線 + 指標疊圖，開發期肉眼驗證用 |

**重要規則：**
- TA 初篩三條件為 AND 關係（全部成立才觸發）
- 籌碼評分為加分制（各項條件獨立加分，總分達門檻才進候選）
- 每個條件函數獨立封裝（`is_above_ma` / `is_volume_surge` 等），方便單獨開關測試
- ScoreEngine 是唯一串接兩層的模組，`main.py` 只呼叫 `ScoreEngine.run()`

---

### 層 3：策略設計與回測層

| 用途 | 工具 | 費用 | 說明 |
|------|------|------|------|
| 回測框架 | Vectorbt | 免費 | 向量化，速度快，適合參數掃描 |
| 參數優化 | Optuna | 免費 | 貝葉斯優化，比 grid search 高效 |
| 績效報告 | Quantstats | 免費 | 一行產出完整 HTML 報告 |

**重要規則：**
- 訊號在 T 日確認，T+1 日開盤進場（`entries.shift(1)` 實作）
- 進場用開盤價（`open`），比收盤價保守，避免高估績效
- 訓練集（2019–2022）調參後，驗證集（2023–2024）禁止再調整
- Gate 條件全部達標才能進 Phase 4，缺一不可

---

### 層 4：自動下單執行層

| 用途 | 工具 | 費用 | 說明 |
|------|------|------|------|
| 券商 API | 永豐 Shioaji | API 免費，需開戶 | 台股 Python 生態最完整 |
| 排程 | APScheduler | 免費 | cron-style，輕量穩定 |

**重要規則：**
- 所有 shioaji 操作集中在 `BrokerClient`，`OrderManager` 不直接碰 SDK
- `SHIOAJI_SIMULATION=true` 預設為模擬盤，需手動改 `false` 才切實盤
- CA 憑證只有實盤才需要，模擬盤可跳過
- 下單張數計算：`capital_per_pos = 總資金 × 30%`，`quantity = capital_per_pos / (price × 1000)`
- 所有下單都先通過 `RiskGuard.can_enter()` 核准

**排程時間（台灣時區）：**

| 時間 | 任務 |
|------|------|
| 08:50 | 盤前選股（拉昨日籌碼 → ScoreEngine → 產出候選清單）|
| 09:05 | 開盤下單（依候選清單，取得即時報價後掛限價單）|
| 09:05–13:30 每 5 分鐘 | 盤中監控（停損/持有天數上限/風控狀態）|
| 14:00 | 盤後報表（推送每日摘要到 Telegram）|

---

### 層 5：監控與風控層

| 用途 | 工具 | 費用 | 說明 |
|------|------|------|------|
| 即時推播 | Telegram Bot | 免費 | python-telegram-bot v20+（async）|
| 日誌 | loguru | 免費 | 結構化日誌，RotatingFileHandler |
| 部署 | GCP e2-micro | 永久免費 | 或本機開著跑 |

**重要規則：**
- `RiskGuard` 完全不下單，只做判斷，由 `main.py` 根據判斷結果呼叫 `OrderManager`
- `PositionManager` 用本地 JSON 持久化，程式重啟不丟失部位狀態
- 熔斷觸發後需人工執行 `RiskGuard.resume()` 才能恢復，防止系統自動重啟後繼續虧損
- 錯誤日誌獨立存放，含完整 traceback，保留 60 天

---

## 四、完整目錄結構

```
trading_bot/
├── pyproject.toml            # 依賴與專案設定（核心 runtime + research/broker/telegram/dev extras）
├── .env.example              # API keys 範本（複製為 .env）
├── .env                      # 實際 keys（git 忽略）
├── README.md
├── main.py                   # 排程主程式入口（APScheduler 常駐）
├── dashboard.py              # 本地監控儀表板（http.server）
├── backtest_gui.py           # 回測 GUI（http.server，用 capped_sim 引擎）
│
├── config/
│   ├── strategy.yaml         # 策略參數（單一真相來源：TA/籌碼/進出場/regime/capitulation/零股…）
│   └── settings.yaml         # 系統設定（排程/資料/風控/券商/通知/日誌）
│
├── src/
│   ├── data/
│   │   ├── fetcher.py        # FinMind（raw requests）+ Fugle 報價
│   │   └── universe.py       # 上市/上櫃股票池
│   ├── signals/
│   │   ├── tech_signal.py    # TA 初篩（MA/RSI/量比）
│   │   ├── chip_signal.py    # 籌碼（外資/投信/融資券）
│   │   ├── capitulation.py   # 投降感知 regime（真底/假反彈分類器）
│   │   └── score_engine.py   # 串接 TA+籌碼，輸出候選（live 選股核心）
│   ├── backtest/
│   │   ├── backtester.py     # TaiwanBacktester（vectorbt 全訊號研究引擎）
│   │   ├── capped_sim.py     # 小資金 top-N 集中策略回測（忠實重現 live）
│   │   └── signal_builder.py # 歷史訊號建構（block_only regime + TA + 籌碼）
│   ├── execution/
│   │   ├── broker_factory.py # paper / shioaji 切換
│   │   ├── broker_client.py  # 永豐 Shioaji 封裝
│   │   ├── paper_broker.py   # 本地模擬撮合
│   │   ├── order_manager.py  # 下單/查詢/取消 + 部位追蹤
│   │   └── odd_lot_fill.py   # 零股成交不確定性模型
│   ├── risk/
│   │   └── risk_guard.py     # 風控（移動停損/日虧損/連虧熔斷/倉位上限）
│   ├── notify/
│   │   ├── notify_manager.py # 推播路由（主/備援/每日上限）
│   │   ├── notify_factory.py
│   │   ├── line_bot.py       # LINE（主推）
│   │   ├── discord_bot.py    # Discord（備援）
│   │   └── telegram_bot.py   # Telegram
│   └── utils/
│       ├── helpers.py        # load_config / 成本 / trailing / sizing 同口徑工具
│       ├── logger.py
│       ├── sectors.py        # 類股分類
│       ├── singleton.py      # fcntl 單例鎖（防雙開）
│       ├── slippage_logger.py# 滑價量測
│       └── eod_archive.py    # 盤後歸檔
│
├── deploy/                   # 部署
│   ├── DEPLOY.md / DEPLOY_MACOS.md / DEPLOY_WINDOWS.md
│   ├── requirements-lock.txt # 可重現性鎖檔（由 pyproject 環境 freeze）
│   ├── macos/                # launchd plist + install/start/stop/uninstall
│   └── trading-bot.service   # GCP systemd unit
│
├── data/                     # raw 快取 / processed 狀態 / archive 歷史（git 忽略）
├── logs/                     # 交易日誌（自動輪轉）
├── notebooks/                # 研究/驗證腳本（用 backtester，需 .[dev]）
└── tests/                    # pytest（81 項）
```
> 註：各套件目錄含 `__init__.py`（省略未列）。依賴定義見 `pyproject.toml`（已取代舊的 requirements*.txt）。

**模組依賴關係：**
```
main.py
  ├── ScoreEngine            ← 選股核心（TA + 籌碼 + capitulation regime 閘門）
  │     ├── FinMind / Fugle fetcher
  │     ├── TechSignal / ChipAnalyzer
  │     └── Capitulation     ← regime（block_only 擋假反彈）
  ├── broker_factory → PaperBroker / BrokerClient(Shioaji)
  ├── OrderManager           ← 下單 + 部位追蹤（呼叫 broker）
  ├── RiskGuard              ← 風控（移動停損/熔斷，只判斷不下單）
  └── notify_manager → LINE(主) / Discord(備援) / Telegram
```

---

## 附錄 A：初版完整程式碼快照（歷史參考 — 與現況可能不符）

> ⚠️ 以下為**專案初版（從零生成時）的 config 與程式碼快照**，保留作設計脈絡參考。
> 程式碼此後已大幅演進，**最新一律以 `src/` 與 `config/` 為準**；本附錄不逐行同步。
> 例如下方 `### requirements.txt` 區塊已不存在於專案（改用 `pyproject.toml`）、
> `config/strategy.yaml` 也缺 regime/capitulation/ATR 移動停損/vol_target/零股等後加章節、
> 檔案清單亦非現況（現況見上方「四、完整目錄結構」）。

### `requirements.txt`

```
# 資料取得
finmind>=1.7.0
fugle-marketdata>=1.0.0
requests>=2.31.0
websocket-client>=1.6.0

# 技術分析
pandas>=2.0.0
pandas-ta>=0.3.14b
numpy>=1.24.0

# 回測 & 績效
vectorbt>=0.26.0
quantstats>=0.0.62
optuna>=3.4.0

# 可視化（開發期使用）
mplfinance>=0.12.10b
matplotlib>=3.7.0

# 下單執行
shioaji>=1.0.0

# 排程 & 通知
APScheduler>=3.10.0
python-telegram-bot>=20.0

# 工具
python-dotenv>=1.0.0
pyyaml>=6.0
loguru>=0.7.0
```

---

### `.env.example`

```
# FinMind API
FINMIND_TOKEN=your_finmind_token_here

# Fugle MarketData API
FUGLE_API_KEY=your_fugle_api_key_here

# 永豐 Shioaji
SHIOAJI_API_KEY=your_shioaji_api_key_here
SHIOAJI_SECRET_KEY=your_shioaji_secret_key_here
SHIOAJI_CA_PATH=./ca/Sinopac.pfx
SHIOAJI_CA_PASSWORD=your_ca_password_here
SHIOAJI_SIMULATION=true   # 改為 false 才切實盤

# Telegram
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# 環境
ENV=development   # development / production
```

---

### `config/strategy.yaml`

> ⚠️ **此為初版快照，已不同步，僅供設計脈絡參考。** 現行以 `config/strategy.yaml` 檔為單一真相來源——
> **2026-06-16 已重構**：移除所有實證否決的選項（過度延伸濾鏡、`market_vol_scaling`、類股分散、
> `regime.require_ma_slope`/`exit_on_risk_off`、`capitulation` 的 `panic_use_amihud`/`reclaim_exempt_days`/
> `unlock_only`·`full` 模式/`deep_bear`/`failed_*` 等，完整清單見 [6.9](#69-config-中已標註效果不良不要採用的選項清單)），
> 並改為統一精簡註解 + `⚠️ 待改善` 診斷標記。下方為初版內容、與現況不符，請勿據此設定。

```yaml
# ==========================================
# 策略參數 — 所有數字都在這裡調，不改 code
# ==========================================

# --- TA 初篩條件 ---
ta_filter:
  ma_period: 20             # 均線週期
  ma_slope_days: 3          # MA 向上斜率計算天數
  volume_ratio_min: 1.5     # 量比最小值（當日量 / 20日均量）
  rsi_period: 14
  rsi_min: 50               # RSI 下限
  rsi_max: 80               # RSI 上限（避免超買）

# --- 籌碼評分條件 ---
chip_scoring:
  foreign_buy_days: 3       # 外資連買計算天數
  foreign_buy_score: 2      # 外資買超得分
  trust_buy_days: 5         # 投信連買計算天數
  trust_buy_score: 1        # 投信買超得分
  margin_ratio_max: 0.15    # 融資使用率上限（15% 以下加分）
  margin_clean_score: 1     # 融資乾淨得分
  short_surge_penalty: -1   # 融券急增扣分
  short_surge_days: 3       # 融券急增判斷天數
  short_surge_ratio: 0.2    # 融券增加 20% 視為急增
  min_score: 2              # 進入候選清單最低分

# --- 進出場規則 ---（核心欄位節錄；完整含 ATR 移動停損、vol_target 配重、regime、
#     投降感知 capitulation、watchlist、零股交易等，見 config/strategy.yaml 單一真相來源）
entry:
  max_positions: 6          # 最多同時持倉檔數
  position_size_pct: 0.30   # 單股最大佔總資金比例（上限；實際由 vol_target 反比配重）

exit:
  stop_loss_pct: -0.05      # 初始硬停損（use_trailing=true 時改由 ATR 移動停損接手）
  take_profit_pct: null     # 不設停利上限，讓贏家續抱
  max_hold_days: 60         # 最長持有天數（趨勢需時間）
  ma_break_exit: false      # 關閉跌破 MA20 出場（過度交易主因）
  use_trailing: true        # 啟用 ATR 移動停損（抱贏家核心）

# --- 交易成本（台股）---
cost:
  buy_fee_rate: 0.001425    # 買進手續費 0.1425%
  sell_fee_rate: 0.001425   # 賣出手續費 0.1425%
  sell_tax_rate: 0.003      # 交易稅 0.3%（賣出才收）
  min_fee: 20               # 最低手續費 20 元

# --- 回測設定 ---
backtest:
  start_date: "2019-01-01"
  insample_end: "2022-12-31"
  outsample_end: "2024-12-31"
  initial_capital: 1_000_000

# --- 績效門檻（Gate 條件）---
performance_gate:
  min_sharpe: 1.0
  max_drawdown: -0.15
  min_annual_return: 0.10
  min_trades: 50
```

---

### `config/settings.yaml`

```yaml
# ==========================================
# 系統設定
# ==========================================

schedule:
  pre_market: "08:50"
  market_open: "09:00"
  intraday_check: 5
  market_close: "13:30"
  post_market: "14:00"

data:
  finmind_sleep: 0.5
  finmind_retry: 3
  cache_days: 1
  raw_data_path: "./data/raw"
  processed_data_path: "./data/processed"

risk:
  daily_loss_limit: -0.02
  consecutive_loss_halt: 3
  emergency_exit_on_halt: false

logging:
  level: "INFO"
  rotation: "1 day"
  retention: "30 days"
  log_path: "./logs"
```

---

### `src/utils/helpers.py`

```python
"""
utils/helpers.py
共用工具函數：設定載入、台股交易成本計算、日期工具
"""
import yaml
from datetime import date, timedelta
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=None)
def load_config(path: str = "config/strategy.yaml") -> dict:
    """載入 YAML 設定，lru_cache 確保只讀一次"""
    with open(path) as f:
        return yaml.safe_load(f)


@lru_cache(maxsize=None)
def load_settings(path: str = "config/settings.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def calc_trade_cost(price: float, quantity: int, action: str) -> dict:
    """
    計算台股實際交易成本
    action: 'buy' or 'sell'
    回傳: {'fee': float, 'tax': float, 'total_cost': float}
    """
    cfg = load_config()["cost"]
    amount = price * quantity * 1000  # 台股：quantity 單位為張，1張=1000股

    fee = max(round(amount * cfg["buy_fee_rate"]), cfg["min_fee"])
    tax = round(amount * cfg["sell_tax_rate"]) if action == "sell" else 0

    return {
        "fee": fee,
        "tax": tax,
        "total_cost": fee + tax,
        "net_amount": amount - fee - tax if action == "sell" else amount + fee,
    }


def is_trading_day(target_date: date = None) -> bool:
    """判斷是否為交易日（簡易版：排除週末）"""
    if target_date is None:
        target_date = date.today()
    return target_date.weekday() < 5


def get_prev_trading_day(n: int = 1) -> date:
    """取得前 n 個交易日日期"""
    d = date.today()
    count = 0
    while count < n:
        d -= timedelta(days=1)
        if is_trading_day(d):
            count += 1
    return d


def tw_stock_list_path() -> Path:
    return Path("data/raw/tw_stock_universe.csv")
```

---

### `src/utils/logger.py`

```python
"""
utils/logger.py
結構化日誌系統，基於 loguru
"""
import sys
from pathlib import Path
from loguru import logger
import yaml


def setup_logger(config_path: str = "config/settings.yaml") -> None:
    with open(config_path) as f:
        cfg = yaml.safe_load(f)["logging"]

    log_dir = Path(cfg["log_path"])
    log_dir.mkdir(exist_ok=True)

    logger.remove()

    logger.add(
        sys.stdout,
        level=cfg["level"],
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan> | {message}",
        colorize=True,
    )

    logger.add(
        log_dir / "trading_{time:YYYY-MM-DD}.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
        rotation=cfg["rotation"],
        retention=cfg["retention"],
        encoding="utf-8",
    )

    logger.add(
        log_dir / "error_{time:YYYY-MM-DD}.log",
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} | {message}\n{exception}",
        rotation="1 week",
        retention="60 days",
        encoding="utf-8",
        backtrace=True,
        diagnose=True,
    )


def log_trade(action: str, stock_id: str, price: float, quantity: int,
              reason: str, score: float = None, **kwargs) -> None:
    extra = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    score_str = f"score={score:.1f}" if score is not None else ""
    logger.info(
        f"TRADE | action={action} | stock={stock_id} | price={price:.2f} "
        f"| qty={quantity} | {score_str} | reason={reason}"
        + (f" | {extra}" if extra else "")
    )
```

---

### `src/data/fetcher.py`

```python
"""
data/fetcher.py
資料抓取層：FinMind（歷史 + 籌碼）+ Fugle（即時報價）
所有外部 API 呼叫都在這裡，上層模組不直接碰 requests
"""
import os
import time
import pandas as pd
from datetime import date
from loguru import logger
from dotenv import load_dotenv
from src.utils.helpers import load_settings

load_dotenv()


class FinMindFetcher:
    """
    FinMind 免費版注意事項：
    - 每日 API 請求上限：600 次（免費）
    - 批次掃描全市場時務必加 sleep
    - 資料為 T+1（法人資料當日無法取得）
    """

    BASE_URL = "https://api.finmindtrade.com/api/v4/data"

    def __init__(self):
        self.token = os.getenv("FINMIND_TOKEN")
        if not self.token:
            raise ValueError("FINMIND_TOKEN 未設定，請檢查 .env 檔案")
        settings = load_settings()
        self.sleep_sec = settings["data"]["finmind_sleep"]
        self.max_retry = settings["data"]["finmind_retry"]

    def _request(self, dataset: str, stock_id: str,
                 start_date: str, end_date: str = None) -> pd.DataFrame:
        import requests
        if end_date is None:
            end_date = date.today().isoformat()
        params = {
            "dataset": dataset,
            "data_id": stock_id,
            "start_date": start_date,
            "end_date": end_date,
            "token": self.token,
        }
        for attempt in range(self.max_retry):
            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") != 200:
                    logger.warning(f"FinMind status={data.get('status')} | {stock_id} | {dataset}")
                    return pd.DataFrame()
                df = pd.DataFrame(data["data"])
                time.sleep(self.sleep_sec)
                return df
            except Exception as e:
                logger.warning(f"FinMind retry {attempt+1}/{self.max_retry} | {e}")
                time.sleep(self.sleep_sec * (attempt + 1))
        logger.error(f"FinMind 請求失敗（已重試 {self.max_retry} 次）| {stock_id} | {dataset}")
        return pd.DataFrame()

    def get_daily_price(self, stock_id: str, start_date: str,
                        end_date: str = None) -> pd.DataFrame:
        df = self._request("TaiwanStockPriceAdj", stock_id, start_date, end_date)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        rename_map = {"open": "open", "max": "high", "min": "low",
                      "close": "close", "Trading_Volume": "volume"}
        df = df.rename(columns=rename_map)
        df["adj_close"] = df["close"]
        keep = ["date", "open", "high", "low", "close", "volume", "adj_close"]
        return df[[c for c in keep if c in df.columns]]

    def get_institutional(self, stock_id: str, start_date: str,
                          end_date: str = None) -> pd.DataFrame:
        """三大法人買賣超（T+1，今日資料明日才有）"""
        df = self._request("TaiwanStockInstitutionalInvestors",
                            stock_id, start_date, end_date)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    def get_margin(self, stock_id: str, start_date: str,
                   end_date: str = None) -> pd.DataFrame:
        """融資融券資料"""
        df = self._request("TaiwanStockMarginPurchaseShortSale",
                            stock_id, start_date, end_date)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)


class FugleFetcher:
    def __init__(self):
        self.api_key = os.getenv("FUGLE_API_KEY")
        if not self.api_key:
            raise ValueError("FUGLE_API_KEY 未設定")
        try:
            from fugle_marketdata import RestClient
            self.client = RestClient(api_key=self.api_key)
        except ImportError:
            logger.error("fugle-marketdata 未安裝：pip install fugle-marketdata")
            self.client = None

    def get_realtime_quote(self, stock_id: str) -> dict:
        if not self.client:
            return {}
        try:
            data = self.client.stock.intraday.quote(symbol=f"{stock_id}.TW")
            return data
        except Exception as e:
            logger.error(f"Fugle 即時報價失敗 | {stock_id} | {e}")
            return {}

    def get_candles(self, stock_id: str, start_date: str,
                    end_date: str = None, timeframe: str = "D") -> pd.DataFrame:
        if not self.client:
            return pd.DataFrame()
        try:
            if end_date is None:
                end_date = date.today().isoformat()
            data = self.client.stock.historical.candles(
                symbol=f"{stock_id}.TW",
                from_=start_date,
                to=end_date,
                fields="open,high,low,close,volume",
            )
            df = pd.DataFrame(data.get("data", []))
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"Fugle K線失敗 | {stock_id} | {e}")
            return pd.DataFrame()
```

---

### `src/data/universe.py`

```python
"""
data/universe.py
台股股票池管理：維護上市+上櫃可交易清單
"""
import pandas as pd
import requests
from pathlib import Path
from loguru import logger
from src.utils.helpers import tw_stock_list_path


def fetch_tw_stock_universe(force_refresh: bool = False) -> pd.DataFrame:
    cache_path = tw_stock_list_path()
    if cache_path.exists() and not force_refresh:
        df = pd.read_csv(cache_path, dtype={"stock_id": str})
        logger.info(f"股票池從快取載入：{len(df)} 檔")
        return df

    logger.info("抓取台股股票池...")
    dfs = []

    for mode, market in [("2", "TWSE"), ("4", "OTC")]:
        try:
            url = f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
            resp = requests.get(url, timeout=15)
            resp.encoding = "big5"
            tables = pd.read_html(resp.text)
            df = tables[0].copy()
            df.columns = df.iloc[0]
            df = df[1:]
            df = df[["有價證券代號及名稱", "市場別", "產業別"]].copy()
            df[["stock_id", "name"]] = df["有價證券代號及名稱"].str.split(r"\s+", n=1, expand=True)
            df["market"] = market
            df["industry"] = df["產業別"]
            dfs.append(df[["stock_id", "name", "market", "industry"]])
        except Exception as e:
            logger.error(f"抓取 {market} 清單失敗：{e}")

    if not dfs:
        return pd.DataFrame()

    df_all = pd.concat(dfs, ignore_index=True)
    df_all = df_all[df_all["stock_id"].str.match(r"^\d{4}$")].dropna(subset=["stock_id"]).reset_index(drop=True)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    df_all.to_csv(cache_path, index=False)
    logger.info(f"股票池已更新：{len(df_all)} 檔")
    return df_all


def get_stock_ids(market: str = "all") -> list[str]:
    df = fetch_tw_stock_universe()
    if market != "all":
        df = df[df["market"] == market]
    return df["stock_id"].tolist()
```

---

### `src/signals/tech_signal.py`

```python
"""
signals/tech_signal.py
TA 初篩層：MA20 突破 + 量能放大 + RSI 健康
"""
import pandas as pd
import pandas_ta as ta
from loguru import logger
from src.utils.helpers import load_config


class TechSignal:
    def __init__(self):
        cfg = load_config()["ta_filter"]
        self.ma_period = cfg["ma_period"]
        self.ma_slope_days = cfg["ma_slope_days"]
        self.vol_ratio_min = cfg["volume_ratio_min"]
        self.rsi_period = cfg["rsi_period"]
        self.rsi_min = cfg["rsi_min"]
        self.rsi_max = cfg["rsi_max"]

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df[f"ma{self.ma_period}"] = ta.sma(df["close"], length=self.ma_period)
        df["ma_slope"] = df[f"ma{self.ma_period}"] - df[f"ma{self.ma_period}"].shift(self.ma_slope_days)
        df["vol_ma20"] = ta.sma(df["volume"], length=20)
        df["vol_ratio"] = df["volume"] / df["vol_ma20"]
        df[f"rsi{self.rsi_period}"] = ta.rsi(df["close"], length=self.rsi_period)
        bbands = ta.bbands(df["close"], length=20, std=2)
        if bbands is not None:
            df["bb_upper"] = bbands["BBU_20_2.0"]
            df["bb_lower"] = bbands["BBL_20_2.0"]
            df["bb_mid"] = bbands["BBM_20_2.0"]
        return df

    def is_above_ma(self, row: pd.Series) -> bool:
        return pd.notna(row[f"ma{self.ma_period}"]) and row["close"] > row[f"ma{self.ma_period}"]

    def is_ma_trending_up(self, row: pd.Series) -> bool:
        return pd.notna(row["ma_slope"]) and row["ma_slope"] > 0

    def is_volume_surge(self, row: pd.Series) -> bool:
        return pd.notna(row["vol_ratio"]) and row["vol_ratio"] >= self.vol_ratio_min

    def is_rsi_healthy(self, row: pd.Series) -> bool:
        rsi_col = f"rsi{self.rsi_period}"
        return pd.notna(row[rsi_col]) and self.rsi_min <= row[rsi_col] <= self.rsi_max

    def is_triggered(self, row: pd.Series) -> bool:
        return (self.is_above_ma(row) and self.is_ma_trending_up(row)
                and self.is_volume_surge(row) and self.is_rsi_healthy(row))

    def scan_single(self, df: pd.DataFrame, stock_id: str) -> dict | None:
        if df.empty or len(df) < self.ma_period + 5:
            return None
        df_with_ta = self.compute(df)
        latest = df_with_ta.iloc[-1]
        if not self.is_triggered(latest):
            return None
        return {
            "stock_id": stock_id,
            "date": latest["date"],
            "close": latest["close"],
            f"ma{self.ma_period}": latest[f"ma{self.ma_period}"],
            "vol_ratio": round(latest["vol_ratio"], 2),
            f"rsi{self.rsi_period}": round(latest[f"rsi{self.rsi_period}"], 1),
            "ma_slope": round(latest["ma_slope"], 3),
            "cond_above_ma": self.is_above_ma(latest),
            "cond_ma_up": self.is_ma_trending_up(latest),
            "cond_vol_surge": self.is_volume_surge(latest),
            "cond_rsi_ok": self.is_rsi_healthy(latest),
        }

    def check_ma_break(self, df: pd.DataFrame) -> bool:
        if df.empty:
            return False
        df_with_ta = self.compute(df)
        latest = df_with_ta.iloc[-1]
        return latest["close"] < latest[f"ma{self.ma_period}"]
```

---

### `src/signals/chip_signal.py`

```python
"""
signals/chip_signal.py
籌碼確認層：法人買賣超評分 + 融資融券健康度
採加分制（非硬門檻），確保候選池數量足夠回測
"""
import pandas as pd
from src.utils.helpers import load_config


class ChipAnalyzer:
    def __init__(self):
        cfg = load_config()["chip_scoring"]
        self.foreign_buy_days = cfg["foreign_buy_days"]
        self.foreign_buy_score = cfg["foreign_buy_score"]
        self.trust_buy_days = cfg["trust_buy_days"]
        self.trust_buy_score = cfg["trust_buy_score"]

    def calc_foreign_score(self, df_inst: pd.DataFrame, as_of_date: pd.Timestamp) -> float:
        if df_inst.empty:
            return 0.0
        foreign = df_inst[df_inst["name"].str.contains("外資", na=False)].copy()
        if foreign.empty:
            return 0.0
        cutoff = as_of_date - pd.Timedelta(days=self.foreign_buy_days * 2)
        recent = foreign[(foreign["date"] > cutoff) & (foreign["date"] <= as_of_date)].tail(self.foreign_buy_days)
        if recent.empty:
            return 0.0
        total_diff = recent["diff"].astype(float).sum()
        return float(self.foreign_buy_score if total_diff > 0 else 0.0)

    def calc_trust_score(self, df_inst: pd.DataFrame, as_of_date: pd.Timestamp) -> float:
        if df_inst.empty:
            return 0.0
        trust = df_inst[df_inst["name"].str.contains("投信", na=False)].copy()
        if trust.empty:
            return 0.0
        cutoff = as_of_date - pd.Timedelta(days=self.trust_buy_days * 2)
        recent = trust[(trust["date"] > cutoff) & (trust["date"] <= as_of_date)].tail(self.trust_buy_days)
        if recent.empty:
            return 0.0
        total_diff = recent["diff"].astype(float).sum()
        return float(self.trust_buy_score if total_diff > 0 else 0.0)

    def get_foreign_net(self, df_inst: pd.DataFrame, as_of_date: pd.Timestamp) -> float:
        foreign = df_inst[df_inst["name"].str.contains("外資", na=False)]
        recent = foreign[foreign["date"] <= as_of_date].tail(1)
        if recent.empty:
            return 0.0
        return float(recent["diff"].iloc[0])


class MarginAnalyzer:
    def __init__(self):
        cfg = load_config()["chip_scoring"]
        self.margin_ratio_max = cfg["margin_ratio_max"]
        self.margin_clean_score = cfg["margin_clean_score"]
        self.short_surge_penalty = cfg["short_surge_penalty"]
        self.short_surge_days = cfg["short_surge_days"]
        self.short_surge_ratio = cfg["short_surge_ratio"]

    def calc_margin_score(self, df_margin: pd.DataFrame, as_of_date: pd.Timestamp) -> float:
        if df_margin.empty:
            return 0.0
        recent = df_margin[df_margin["date"] <= as_of_date].tail(1)
        if recent.empty:
            return 0.0
        row = recent.iloc[0]
        try:
            margin_buy = float(row.get("MarginPurchaseBuy", 0) or 0)
            margin_limit = float(row.get("MarginPurchaseLimit", 1) or 1)
            if margin_limit == 0:
                return 0.0
            usage_ratio = margin_buy / margin_limit
            return float(self.margin_clean_score if usage_ratio < self.margin_ratio_max else 0.0)
        except Exception:
            return 0.0

    def calc_short_penalty(self, df_margin: pd.DataFrame, as_of_date: pd.Timestamp) -> float:
        if df_margin.empty:
            return 0.0
        cutoff = as_of_date - pd.Timedelta(days=self.short_surge_days * 2)
        recent = df_margin[(df_margin["date"] > cutoff) & (df_margin["date"] <= as_of_date)].tail(self.short_surge_days)
        if len(recent) < 2:
            return 0.0
        try:
            first_short = float(recent.iloc[0]["ShortSaleBuy"] or 0)
            last_short = float(recent.iloc[-1]["ShortSaleBuy"] or 0)
            if first_short == 0:
                return 0.0
            change_ratio = (last_short - first_short) / first_short
            return float(self.short_surge_penalty if change_ratio > self.short_surge_ratio else 0.0)
        except Exception:
            return 0.0
```

---

### `src/signals/score_engine.py`

```python
"""
signals/score_engine.py
整合評分器：串接 TA 初篩 + 籌碼評分（核心連接點）
"""
import pandas as pd
from datetime import date
from loguru import logger
from src.data.fetcher import FinMindFetcher
from src.data.universe import get_stock_ids
from src.signals.tech_signal import TechSignal
from src.signals.chip_signal import ChipAnalyzer, MarginAnalyzer
from src.utils.helpers import load_config, get_prev_trading_day


class ScoreEngine:
    def __init__(self):
        self.fetcher = FinMindFetcher()
        self.tech = TechSignal()
        self.chip = ChipAnalyzer()
        self.margin = MarginAnalyzer()
        self.min_score = load_config()["chip_scoring"]["min_score"]

    def run_ta_scan(self, stock_ids: list[str] = None, lookback_days: int = 120) -> list[dict]:
        if stock_ids is None:
            stock_ids = get_stock_ids()
        start_date = (date.today() - pd.Timedelta(days=lookback_days)).isoformat()
        candidates = []
        total = len(stock_ids)
        logger.info(f"TA 掃描開始：{total} 檔股票")
        for i, sid in enumerate(stock_ids):
            if i % 100 == 0:
                logger.info(f"TA 掃描進度：{i}/{total}")
            try:
                df = self.fetcher.get_daily_price(sid, start_date)
                result = self.tech.scan_single(df, sid)
                if result:
                    candidates.append(result)
            except Exception as e:
                logger.warning(f"TA 掃描失敗 | {sid} | {e}")
        logger.info(f"TA 初篩完成：{len(candidates)}/{total} 檔通過")
        return candidates

    def run_chip_scoring(self, ta_candidates: list[dict], lookback_days: int = 30) -> pd.DataFrame:
        as_of_date = pd.Timestamp(get_prev_trading_day())
        start_date = (as_of_date - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        results = []
        logger.info(f"籌碼評分開始：{len(ta_candidates)} 檔候選，基準日 {as_of_date.date()}")
        for item in ta_candidates:
            sid = item["stock_id"]
            try:
                df_inst = self.fetcher.get_institutional(sid, start_date)
                df_margin = self.fetcher.get_margin(sid, start_date)
                foreign_score = self.chip.calc_foreign_score(df_inst, as_of_date)
                trust_score = self.chip.calc_trust_score(df_inst, as_of_date)
                margin_score = self.margin.calc_margin_score(df_margin, as_of_date)
                short_penalty = self.margin.calc_short_penalty(df_margin, as_of_date)
                total_score = foreign_score + trust_score + margin_score + short_penalty
                results.append({
                    **item,
                    "foreign_score": foreign_score,
                    "trust_score": trust_score,
                    "margin_score": margin_score,
                    "short_penalty": short_penalty,
                    "chip_score": total_score,
                    "foreign_net": self.chip.get_foreign_net(df_inst, as_of_date),
                })
            except Exception as e:
                logger.warning(f"籌碼評分失敗 | {sid} | {e}")
        df = pd.DataFrame(results)
        if df.empty:
            return df
        df = df.sort_values("chip_score", ascending=False).reset_index(drop=True)
        logger.info(f"籌碼評分完成：{len(df)} 檔，達門檻 {(df['chip_score'] >= self.min_score).sum()} 檔")
        return df

    def run(self, stock_ids: list[str] = None) -> pd.DataFrame:
        ta_candidates = self.run_ta_scan(stock_ids)
        if not ta_candidates:
            logger.warning("TA 初篩無結果")
            return pd.DataFrame()
        df_scored = self.run_chip_scoring(ta_candidates)
        if df_scored.empty:
            return pd.DataFrame()
        df_final = df_scored[df_scored["chip_score"] >= self.min_score].copy()
        df_final["reason"] = df_final.apply(self._build_reason, axis=1)
        logger.info(f"今日最終候選：{len(df_final)} 檔")
        return df_final

    def _build_reason(self, row: pd.Series) -> str:
        parts = []
        if row.get("cond_above_ma"):
            parts.append(f"站上MA20({row.get('ma20', 0):.1f})")
        if row.get("cond_vol_surge"):
            parts.append(f"量比{row.get('vol_ratio', 0):.1f}x")
        if row.get("rsi14"):
            parts.append(f"RSI{row['rsi14']:.0f}")
        if row.get("foreign_score", 0) > 0:
            parts.append(f"外資買超{row.get('foreign_net', 0):.0f}張")
        if row.get("trust_score", 0) > 0:
            parts.append("投信買超")
        if row.get("margin_score", 0) > 0:
            parts.append("融資乾淨")
        return " | ".join(parts)

    def save_candidates(self, df: pd.DataFrame,
                        path: str = "data/processed/candidates_{date}.csv") -> str:
        import os
        today = date.today().isoformat()
        filepath = path.format(date=today)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        df.to_csv(filepath, index=False, encoding="utf-8-sig")
        logger.info(f"候選清單已儲存：{filepath}")
        return filepath
```

---

### `src/backtest/backtester.py`

```python
"""
backtest/backtester.py
Vectorbt 台股回測框架
重要：訊號 T 日確認，T+1 日開盤進場（entries.shift(1)）
"""
import pandas as pd
from loguru import logger
from src.utils.helpers import load_config


class TaiwanBacktester:
    def __init__(self):
        cfg = load_config()
        self.cost_cfg = cfg["cost"]
        self.exit_cfg = cfg["exit"]
        self.bt_cfg = cfg["backtest"]
        self.gate_cfg = cfg["performance_gate"]

    def run(self, price_df: pd.DataFrame, signal_df: pd.DataFrame,
            initial_capital: float = None) -> dict:
        try:
            import vectorbt as vbt
        except ImportError:
            logger.error("vectorbt 未安裝")
            return {}
        if initial_capital is None:
            initial_capital = self.bt_cfg["initial_capital"]

        entries = signal_df.pivot(index="date", columns="stock_id", values="entry_signal")
        entries = entries.shift(1).fillna(False).astype(bool)  # T+1

        open_prices = price_df.pivot(index="date", columns="stock_id", values="open")
        common_dates = entries.index.intersection(open_prices.index)
        entries = entries.reindex(common_dates)
        open_prices = open_prices.reindex(common_dates)

        exits = self._build_exit_signals(price_df, entries)
        buy_fee = self.cost_cfg["buy_fee_rate"]
        sell_fee = self.cost_cfg["sell_fee_rate"] + self.cost_cfg["sell_tax_rate"]

        portfolio = vbt.Portfolio.from_signals(
            close=open_prices,
            entries=entries,
            exits=exits,
            init_cash=initial_capital,
            fees={"buy": buy_fee, "sell": sell_fee},
            slippage=0.001,
            size=1.0,
            size_type="value",
            cash_sharing=True,
            call_seq="auto",
        )
        return {
            "stats": self._extract_stats(portfolio),
            "portfolio": portfolio,
            "trades": portfolio.trades.records_readable,
        }

    def _build_exit_signals(self, price_df, entries):
        exits = pd.DataFrame(False, index=entries.index, columns=entries.columns)
        return exits

    def run_walk_forward(self, price_df: pd.DataFrame, signal_df: pd.DataFrame) -> dict:
        insample_end = pd.Timestamp(self.bt_cfg["insample_end"])
        outsample_end = pd.Timestamp(self.bt_cfg["outsample_end"])
        result_in = self.run(price_df[price_df["date"] <= insample_end],
                             signal_df[signal_df["date"] <= insample_end])
        result_out = self.run(
            price_df[(price_df["date"] > insample_end) & (price_df["date"] <= outsample_end)],
            signal_df[(signal_df["date"] > insample_end) & (signal_df["date"] <= outsample_end)]
        )
        return {
            "insample": result_in,
            "outsample": result_out,
            "gate_pass": self._check_gate(result_out.get("stats", {})),
        }

    def _extract_stats(self, portfolio) -> dict:
        try:
            stats = portfolio.stats()
            return {
                "total_return": float(stats.get("Total Return [%]", 0)) / 100,
                "annual_return": float(stats.get("Annualized Return [%]", 0)) / 100,
                "sharpe_ratio": float(stats.get("Sharpe Ratio", 0)),
                "max_drawdown": float(stats.get("Max Drawdown [%]", 0)) / 100,
                "win_rate": float(stats.get("Win Rate [%]", 0)) / 100,
                "total_trades": int(stats.get("Total Trades", 0)),
                "profit_factor": float(stats.get("Profit Factor", 0)),
            }
        except Exception as e:
            logger.error(f"績效統計失敗：{e}")
            return {}

    def _check_gate(self, stats: dict) -> dict:
        gate = self.gate_cfg
        checks = {
            "sharpe_ok": stats.get("sharpe_ratio", 0) >= gate["min_sharpe"],
            "drawdown_ok": stats.get("max_drawdown", -999) >= gate["max_drawdown"],
            "return_ok": stats.get("annual_return", 0) >= gate["min_annual_return"],
            "trades_ok": stats.get("total_trades", 0) >= gate["min_trades"],
        }
        checks["all_pass"] = all(checks.values())
        return checks

    def generate_report(self, result: dict, benchmark_df: pd.DataFrame = None) -> None:
        try:
            import quantstats as qs
            portfolio = result.get("portfolio")
            if portfolio is None:
                return
            returns = portfolio.returns()
            kwargs = {"output": "data/processed/backtest_report.html",
                      "title": "Taiwan Stock Bot — 混合策略回測報告"}
            if benchmark_df is not None:
                qs.reports.html(returns, benchmark=benchmark_df["close"].pct_change().dropna(), **kwargs)
            else:
                qs.reports.html(returns, **kwargs)
            logger.info("績效報告已產出：data/processed/backtest_report.html")
        except Exception as e:
            logger.error(f"報告產出失敗：{e}")
```

---

### `src/execution/broker_client.py`

```python
"""
execution/broker_client.py
永豐 Shioaji API 封裝（唯一接觸 SDK 的地方）
"""
import os
from loguru import logger
from dotenv import load_dotenv
load_dotenv()


class BrokerClient:
    def __init__(self):
        self._api = None
        self._simulation = os.getenv("SHIOAJI_SIMULATION", "true").lower() == "true"
        if self._simulation:
            logger.warning("⚠️  模擬盤模式 — 不會產生真實下單")

    def connect(self) -> bool:
        try:
            import shioaji as sj
            self._api = sj.Shioaji(simulation=self._simulation)
            accounts = self._api.login(
                api_key=os.getenv("SHIOAJI_API_KEY"),
                secret_key=os.getenv("SHIOAJI_SECRET_KEY"),
            )
            if not self._simulation:
                self._api.activate_ca(
                    ca_path=os.getenv("SHIOAJI_CA_PATH"),
                    ca_passwd=os.getenv("SHIOAJI_CA_PASSWORD"),
                    person_id=accounts[0].person_id,
                )
            logger.info(f"Shioaji 連線成功 | simulation={self._simulation}")
            return True
        except ImportError:
            logger.error("shioaji 未安裝")
            return False
        except Exception as e:
            logger.error(f"Shioaji 連線失敗：{e}")
            return False

    def disconnect(self):
        if self._api:
            self._api.logout()

    def get_balance(self) -> float:
        if not self._api:
            return 0.0
        try:
            balance = self._api.get_account_balance(self._api.stock_account)
            return float(balance.acc_balance)
        except Exception as e:
            logger.error(f"查詢餘額失敗：{e}")
            return 0.0

    def get_positions(self) -> list[dict]:
        if not self._api:
            return []
        try:
            positions = self._api.list_positions(self._api.stock_account)
            return [{"stock_id": p.code, "quantity": p.quantity,
                     "cost": p.price, "pnl": p.pnl, "last_price": p.last_price}
                    for p in positions]
        except Exception as e:
            logger.error(f"查詢持倉失敗：{e}")
            return []

    def place_order(self, stock_id: str, action: str, price: float,
                    quantity: int, order_type: str = "ROD") -> dict:
        if not self._api:
            return {"error": "not_connected"}
        try:
            import shioaji as sj
            contract = self._api.Contracts.Stocks[stock_id]
            order = self._api.Order(
                price=price, quantity=quantity,
                action=sj.constant.Action.Buy if action == "Buy" else sj.constant.Action.Sell,
                price_type=sj.constant.StockPriceType.LMT,
                order_type=getattr(sj.constant.OrderType, order_type),
                account=self._api.stock_account,
            )
            trade = self._api.place_order(contract, order)
            logger.info(f"下單成功 | {action} {stock_id} {quantity}張 @{price}")
            return {"order_id": trade.order.id, "status": trade.status.status,
                    "stock_id": stock_id, "action": action, "price": price, "quantity": quantity}
        except Exception as e:
            logger.error(f"下單失敗 | {action} {stock_id} | {e}")
            return {"error": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        if not self._api:
            return False
        try:
            self._api.update_status(self._api.stock_account)
            trades = self._api.list_trades()
            target = next((t for t in trades if t.order.id == order_id), None)
            if not target:
                return False
            self._api.cancel_order(target)
            return True
        except Exception as e:
            logger.error(f"取消委託失敗 | {e}")
            return False

    def cancel_all_orders(self) -> int:
        if not self._api:
            return 0
        try:
            self._api.update_status(self._api.stock_account)
            trades = self._api.list_trades()
            cancelled = sum(1 for t in trades
                            if t.status.status in ["PendingSubmit", "PreSubmitted", "Submitted"]
                            and self._api.cancel_order(t) is not None)
            logger.warning(f"緊急取消所有委託：{cancelled} 筆")
            return cancelled
        except Exception as e:
            logger.error(f"緊急取消失敗：{e}")
            return 0
```

---

### `src/execution/order_manager.py`

> **注意**：此檔案包含 `OrderManager` 與 `PositionManager` 兩個 class。  
> Claude Code 可選擇將 `PositionManager` 拆分到獨立的 `execution/position_manager.py`，並更新 `main.py` 的 import 路徑。

```python
"""
execution/order_manager.py — OrderManager
execution/position_manager.py — PositionManager（可選擇拆分）
"""
import json
import time
from datetime import date
from pathlib import Path
from loguru import logger
from src.execution.broker_client import BrokerClient
from src.utils.logger import log_trade
from src.utils.helpers import load_config, calc_trade_cost


class OrderManager:
    LIMIT_UP_RETRY = 3
    LIMIT_UP_WAIT = 60

    def __init__(self, broker: BrokerClient):
        self.broker = broker
        self.cfg = load_config()

    def enter(self, stock_id: str, price: float, quantity: int,
              reason: str, score: float = None) -> dict:
        result = self.broker.place_order(stock_id, "Buy", price, quantity)
        if "error" in result:
            logger.error(f"進場失敗 | {stock_id} | {result['error']}")
            return result
        log_trade("BUY", stock_id, price, quantity, reason, score)
        logger.info(f"進場成本估算：{calc_trade_cost(price, quantity, 'buy')}")
        return result

    def exit(self, stock_id: str, price: float, quantity: int, reason: str) -> dict:
        result = self.broker.place_order(stock_id, "Sell", price, quantity)
        if "error" in result:
            logger.error(f"出場失敗 | {stock_id} | {result['error']}")
            return result
        log_trade("SELL", stock_id, price, quantity, reason)
        return result

    def emergency_exit_all(self, positions: list[dict], current_prices: dict) -> list[dict]:
        logger.critical("⚠️ 緊急出場：清除所有部位")
        self.broker.cancel_all_orders()
        results = []
        for pos in positions:
            sid = pos["stock_id"]
            price = current_prices.get(sid, pos["cost"])
            results.append(self.exit(sid, price * 0.95, pos["quantity"], "emergency_exit"))
        return results


class PositionManager:
    POSITIONS_FILE = "data/processed/positions.json"
    MAX_POSITIONS = 3

    def __init__(self):
        self.cfg = load_config()
        self._positions: dict[str, dict] = {}
        self._load()

    def _load(self):
        path = Path(self.POSITIONS_FILE)
        if path.exists():
            with open(path) as f:
                self._positions = json.load(f)
            logger.info(f"持倉狀態載入：{len(self._positions)} 檔")

    def _save(self):
        path = Path(self.POSITIONS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self._positions, f, ensure_ascii=False, indent=2, default=str)

    def add(self, stock_id: str, price: float, quantity: int,
            reason: str = "", score: float = None):
        self._positions[stock_id] = {
            "stock_id": stock_id, "entry_price": price, "quantity": quantity,
            "entry_date": date.today().isoformat(), "reason": reason,
            "score": score, "last_price": price,
        }
        self._save()
        logger.info(f"部位新增 | {stock_id} | {quantity}張 @{price}")

    def remove(self, stock_id: str):
        if stock_id in self._positions:
            del self._positions[stock_id]
            self._save()

    def update_prices(self, prices: dict[str, float]):
        for sid, price in prices.items():
            if sid in self._positions:
                self._positions[sid]["last_price"] = price
        self._save()

    def get_pnl(self, stock_id: str) -> float:
        pos = self._positions.get(stock_id)
        if not pos:
            return 0.0
        entry = pos["entry_price"]
        last = pos.get("last_price", entry)
        return (last - entry) / entry if entry > 0 else 0.0

    def get_all_pnl(self) -> dict[str, float]:
        return {sid: self.get_pnl(sid) for sid in self._positions}

    def get_hold_days(self, stock_id: str) -> int:
        pos = self._positions.get(stock_id)
        if not pos:
            return 0
        return (date.today() - date.fromisoformat(pos["entry_date"])).days

    def can_add_position(self) -> bool:
        return len(self._positions) < self.MAX_POSITIONS

    def summary(self) -> list[dict]:
        return [{**pos, "pnl_pct": round(self.get_pnl(sid) * 100, 2),
                 "hold_days": self.get_hold_days(sid)}
                for sid, pos in self._positions.items()]
```

---

### `src/risk/risk_guard.py`

```python
"""
risk/risk_guard.py
風控守門員：不下單，只判斷
"""
import json
from datetime import date
from pathlib import Path
from loguru import logger
from src.utils.helpers import load_config, load_settings


class RiskGuard:
    DAILY_STATE_FILE = "data/processed/daily_risk_state.json"

    def __init__(self, total_capital: float):
        self.total_capital = total_capital
        cfg = load_config()
        settings = load_settings()
        self.stop_loss_pct = cfg["exit"]["stop_loss_pct"]
        self.max_position_pct = cfg["entry"]["position_size_pct"]
        self.max_positions = cfg["entry"]["max_positions"]
        self.daily_loss_limit = settings["risk"]["daily_loss_limit"]
        self.consec_loss_halt = settings["risk"]["consecutive_loss_halt"]
        self._state = self._load_state()

    def _load_state(self) -> dict:
        path = Path(self.DAILY_STATE_FILE)
        if path.exists():
            with open(path) as f:
                state = json.load(f)
            if state.get("date") != date.today().isoformat():
                state = self._fresh_state()
        else:
            state = self._fresh_state()
        return state

    def _fresh_state(self) -> dict:
        return {"date": date.today().isoformat(), "daily_pnl": 0.0,
                "consecutive_loss": 0, "halted": False, "halt_reason": ""}

    def _save_state(self):
        path = Path(self.DAILY_STATE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)

    def can_enter(self, stock_id: str, price: float, quantity: int,
                  current_positions: int) -> tuple[bool, str]:
        if self._state["halted"]:
            return False, f"系統熔斷中：{self._state['halt_reason']}"
        if current_positions >= self.max_positions:
            return False, f"持倉已達上限（{self.max_positions} 檔）"
        if price * quantity * 1000 > self.total_capital * self.max_position_pct:
            return False, f"單股倉位超過上限"
        return True, ""

    def check_stop_loss(self, positions_pnl: dict[str, float]) -> list[str]:
        to_exit = []
        for sid, pnl in positions_pnl.items():
            if pnl <= self.stop_loss_pct:
                logger.warning(f"停損觸發 | {sid} | {pnl*100:.1f}%")
                to_exit.append(sid)
        return to_exit

    def check_max_hold(self, positions_hold_days: dict[str, int], max_days: int = 15) -> list[str]:
        return [sid for sid, days in positions_hold_days.items() if days >= max_days]

    def record_trade_result(self, pnl_amount: float):
        self._state["daily_pnl"] += pnl_amount
        if pnl_amount < 0:
            self._state["consecutive_loss"] += 1
        else:
            self._state["consecutive_loss"] = 0
        daily_pnl_pct = self._state["daily_pnl"] / self.total_capital
        if daily_pnl_pct <= self.daily_loss_limit:
            self._trigger_halt(f"單日虧損達 {daily_pnl_pct*100:.1f}%")
        elif self._state["consecutive_loss"] >= self.consec_loss_halt:
            self._trigger_halt(f"連續虧損 {self._state['consecutive_loss']} 筆")
        self._save_state()

    def _trigger_halt(self, reason: str):
        self._state["halted"] = True
        self._state["halt_reason"] = reason
        logger.critical(f"🔴 風控熔斷：{reason}")

    def resume(self):
        self._state["halted"] = False
        self._state["halt_reason"] = ""
        self._state["consecutive_loss"] = 0
        self._save_state()
        logger.info("✅ 熔斷已解除")

    def get_status(self) -> dict:
        return {**self._state,
                "daily_pnl_pct": round(self._state["daily_pnl"] / self.total_capital * 100, 2)}
```

---

### `src/notify/telegram_bot.py`

```python
"""
notify/telegram_bot.py
Telegram 推播通知（python-telegram-bot v20+，async）
"""
import os
import asyncio
import traceback
from datetime import date
from loguru import logger
from dotenv import load_dotenv
load_dotenv()


class TelegramNotifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self._enabled = bool(self.token and self.chat_id)
        if not self._enabled:
            logger.warning("Telegram 未設定，通知功能停用")

    def _send(self, text: str):
        if not self._enabled:
            logger.info(f"[Telegram 停用] {text[:80]}...")
            return
        try:
            import telegram
            async def _do():
                bot = telegram.Bot(token=self.token)
                await bot.send_message(chat_id=self.chat_id, text=text, parse_mode="HTML")
            asyncio.run(_do())
        except Exception as e:
            logger.error(f"Telegram 推播失敗：{e}")

    def send_entry_signal(self, stock_id: str, stock_name: str, price: float,
                          quantity: int, chip_score: float, reason: str):
        self._send(
            f"📈 <b>進場訊號</b>\n━━━━━━━━━━━━━━━\n"
            f"股票：{stock_id} {stock_name}\n方向：買進\n價格：${price:.2f}\n"
            f"數量：{quantity} 張\n籌碼分：{chip_score:.1f}\n原因：{reason}\n"
            f"━━━━━━━━━━━━━━━\n⚠️ 進場後請設定停損 {price * 0.95:.2f}"
        )

    def send_exit_signal(self, stock_id: str, stock_name: str, entry_price: float,
                         exit_price: float, quantity: int, reason: str, pnl_pct: float):
        emoji = "✅" if pnl_pct >= 0 else "🔴"
        self._send(
            f"{emoji} <b>出場</b>\n━━━━━━━━━━━━━━━\n"
            f"股票：{stock_id} {stock_name}\n原因：{reason}\n"
            f"進場：${entry_price:.2f}\n出場：${exit_price:.2f}\n"
            f"損益：{pnl_pct:+.1f}%\n張數：{quantity} 張"
        )

    def send_stop_loss_alert(self, stock_id: str, price: float, pnl_pct: float):
        self._send(
            f"🚨 <b>停損觸發</b>\n股票：{stock_id}\n"
            f"當前價：${price:.2f}\n損益：{pnl_pct*100:+.1f}%\n正在執行停損出場..."
        )

    def send_halt_alert(self, reason: str):
        self._send(f"🔴 <b>風控熔斷</b>\n原因：{reason}\n系統已暫停交易\n請人工審核後執行 resume() 恢復")

    def send_daily_summary(self, positions: list[dict], daily_pnl: float,
                           total_capital: float, candidates_count: int):
        pnl_pct = daily_pnl / total_capital * 100 if total_capital else 0
        pos_lines = "".join(
            f"  {'↑' if p['pnl_pct'] >= 0 else '↓'} {p['stock_id']} {p['pnl_pct']:+.1f}% ({p['hold_days']}日)\n"
            for p in positions
        ) or "  （無持倉）"
        self._send(
            f"📊 <b>每日摘要 {date.today().isoformat()}</b>\n━━━━━━━━━━━━━━━\n"
            f"今日損益：{pnl_pct:+.1f}%（{daily_pnl:+.0f} 元）\n今日候選：{candidates_count} 檔\n"
            f"━━━━━━━━━━━━━━━\n目前持倉：\n{pos_lines}"
        )

    def send_error(self, error: Exception, context: str = ""):
        tb = traceback.format_exc()[-500:]
        self._send(f"⚠️ <b>系統錯誤</b>\n位置：{context}\n錯誤：{str(error)[:200]}\n<pre>{tb}</pre>")

    def send_text(self, text: str):
        self._send(text)
```

---

### `main.py`

```python
"""
main.py
排程主程式入口
APScheduler 控制：08:50 盤前選股 → 09:05 開盤下單 → 盤中每5分監控 → 14:00 盤後報表
"""
import sys
import signal
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from src.utils.logger import setup_logger
from src.utils.helpers import load_settings, is_trading_day
from src.signals.score_engine import ScoreEngine
from src.execution.broker_client import BrokerClient
from src.execution.order_manager import OrderManager, PositionManager
from src.risk.risk_guard import RiskGuard
from src.notify.telegram_bot import TelegramNotifier
from src.data.fetcher import FugleFetcher

setup_logger()

broker = BrokerClient()
position_mgr = PositionManager()
notifier = TelegramNotifier()
score_engine = ScoreEngine()
fugle = FugleFetcher()

TOTAL_CAPITAL = 0.0
TZ = pytz.timezone("Asia/Taipei")
_today_candidates = []
_risk_guard = None


def pre_market_task():
    global _today_candidates, _risk_guard, TOTAL_CAPITAL
    if not is_trading_day():
        return
    logger.info("=== 盤前選股開始 ===")
    try:
        TOTAL_CAPITAL = broker.get_balance() or 50_000
        _risk_guard = RiskGuard(total_capital=TOTAL_CAPITAL)
        df = score_engine.run()
        _today_candidates = df.to_dict("records") if not df.empty else []
        if not df.empty:
            score_engine.save_candidates(df)
        notifier.send_text(
            f"☀️ 盤前選股完成\n今日候選：{len(_today_candidates)} 檔\n"
            f"帳戶資金：{TOTAL_CAPITAL:,.0f} 元\n"
            f"風控狀態：{'熔斷中' if _risk_guard.get_status()['halted'] else '正常'}"
        )
    except Exception as e:
        logger.exception("盤前任務失敗")
        notifier.send_error(e, "pre_market_task")


def market_open_task():
    if not is_trading_day() or not _today_candidates:
        return
    logger.info("=== 開盤下單開始 ===")
    order_mgr = OrderManager(broker)
    for candidate in _today_candidates:
        sid = candidate["stock_id"]
        try:
            quote = fugle.get_realtime_quote(sid)
            price = quote.get("price", candidate.get("close", 0))
            if not price:
                continue
            quantity = max(1, int(TOTAL_CAPITAL * 0.30 / (price * 1000)))
            ok, reject_reason = _risk_guard.can_enter(sid, price, quantity, len(position_mgr.summary()))
            if not ok:
                logger.info(f"進場拒絕 | {sid} | {reject_reason}")
                continue
            result = order_mgr.enter(sid, price, quantity, candidate.get("reason", ""), candidate.get("chip_score", 0))
            if "error" not in result:
                position_mgr.add(sid, price, quantity, candidate.get("reason", ""), candidate.get("chip_score"))
                notifier.send_entry_signal(sid, sid, price, quantity, candidate.get("chip_score", 0), candidate.get("reason", ""))
        except Exception as e:
            logger.exception(f"開盤下單失敗 | {sid}")
            notifier.send_error(e, f"market_open_task | {sid}")


def intraday_monitor_task():
    if not is_trading_day():
        return
    positions = position_mgr.summary()
    if not positions:
        return
    order_mgr = OrderManager(broker)
    current_prices = {}
    for pos in positions:
        quote = fugle.get_realtime_quote(pos["stock_id"])
        if quote.get("price"):
            current_prices[pos["stock_id"]] = quote["price"]
    position_mgr.update_prices(current_prices)
    pnl_map = position_mgr.get_all_pnl()
    hold_days_map = {pos["stock_id"]: pos["hold_days"] for pos in positions}
    to_exit = list(set(_risk_guard.check_stop_loss(pnl_map) + _risk_guard.check_max_hold(hold_days_map)))
    for sid in to_exit:
        price = current_prices.get(sid, 0)
        reason = "stop_loss" if pnl_map.get(sid, 0) <= _risk_guard.stop_loss_pct else "max_hold_days"
        if reason == "stop_loss":
            notifier.send_stop_loss_alert(sid, price, pnl_map.get(sid, 0))
        pos_info = next((p for p in positions if p["stock_id"] == sid), {})
        order_mgr.exit(sid, price * 0.99, pos_info.get("quantity", 1), reason)
        position_mgr.remove(sid)
        pnl_amount = (price - pos_info.get("entry_price", price)) * pos_info.get("quantity", 1) * 1000
        _risk_guard.record_trade_result(pnl_amount)
        if _risk_guard.get_status()["halted"]:
            notifier.send_halt_alert(_risk_guard.get_status()["halt_reason"])
            break


def post_market_task():
    if not is_trading_day():
        return
    status = _risk_guard.get_status() if _risk_guard else {}
    notifier.send_daily_summary(
        positions=position_mgr.summary(),
        daily_pnl=status.get("daily_pnl", 0),
        total_capital=TOTAL_CAPITAL,
        candidates_count=len(_today_candidates),
    )
    logger.info("=== 盤後報表推送完成 ===")


def graceful_shutdown(signum, frame):
    logger.warning("收到終止訊號，正在關閉系統...")
    broker.disconnect()
    notifier.send_text("⚠️ 交易系統已關閉")
    sys.exit(0)


def main():
    settings = load_settings()
    sched_cfg = settings["schedule"]
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    if not broker.connect():
        logger.error("券商連線失敗，系統無法啟動")
        sys.exit(1)

    scheduler = BlockingScheduler(timezone=TZ)
    h, m = sched_cfg["pre_market"].split(":")
    scheduler.add_job(pre_market_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))
    scheduler.add_job(market_open_task, CronTrigger(hour=9, minute=5, timezone=TZ))
    scheduler.add_job(intraday_monitor_task,
                      CronTrigger(hour="9-13", minute=f"*/{sched_cfg['intraday_check']}", timezone=TZ))
    h, m = sched_cfg["post_market"].split(":")
    scheduler.add_job(post_market_task, CronTrigger(hour=int(h), minute=int(m), timezone=TZ))

    logger.info("✅ 交易系統啟動，等待排程...")
    notifier.send_text("✅ 交易系統已啟動")
    try:
        scheduler.start()
    except Exception as e:
        logger.exception("排程器異常")
        notifier.send_error(e, "main scheduler")
        broker.disconnect()


if __name__ == "__main__":
    main()
```

---

## 附錄 B：初版「從零重建」工作指示（歷史）

> ⚠️ 以下是當初「依本文件從零生成整個專案」用的指示。專案早已建好並大幅演進，**僅供歷史參考**。
> 實際安裝/部署請看 `README.md` 與 `deploy/`（依賴一律用 `pyproject.toml`）。

### 第一步：建立目錄結構

```bash
mkdir -p trading_bot/{config,src/{data,signals,backtest,execution,risk,notify,utils},logs,data/{raw,processed},notebooks,tests}
touch trading_bot/src/__init__.py
touch trading_bot/src/{data,signals,backtest,execution,risk,notify,utils}/__init__.py
```

### 第二步：將本文件中的所有程式碼區塊依路徑建立對應檔案

每個程式碼區塊的標題即為檔案路徑，例如：
- `### \`config/strategy.yaml\`` → 建立 `trading_bot/config/strategy.yaml`
- `### \`src/data/fetcher.py\`` → 建立 `trading_bot/src/data/fetcher.py`

### 第三步：Phase 0 驗證（建立後立即執行）

```bash
cd trading_bot
python -m venv venv && source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e .                                 # 核心 runtime；回測加 pip install -e ".[dev]"
cp .env.example .env
# 填入 FINMIND_TOKEN 後執行驗證
python -c "
from src.data.fetcher import FinMindFetcher
f = FinMindFetcher()
df = f.get_daily_price('2330', '2023-01-01')
print(df.tail(3))
print('日K資料正常' if not df.empty else '日K資料異常')
"
```

### 重要注意事項

1. `order_manager.py` 含 `OrderManager` 和 `PositionManager` 兩個 class，可視需要拆分
2. `SHIOAJI_SIMULATION=true` 預設模擬盤，Phase 4 Gate 通過後才改 `false`
3. `lru_cache` 在 `helpers.py` 中使用，修改 YAML 後需重啟程式才會生效
4. FinMind 免費版每日 600 次請求，批次掃描全市場約需 1,700 次，需分天或升級方案
5. 法人資料 T+1 延遲是最容易犯的回測錯誤，`ScoreEngine` 中的 `get_prev_trading_day()` 已處理

---

*文件版本：v1.0 | 生成時間：2026-06-07 | 策略：混合策略（TA 初篩 + 籌碼確認）*

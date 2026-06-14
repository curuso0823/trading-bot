# Taiwan Stock Trading Bot — 完整規劃與程式碼參考文件

> 本文件供 Claude Code 直接使用，包含：  
> 1. 策略概覽與設計決策  
> 2. Implementation Plan（5 個 Phase）  
> 3. 五層架構的資源選用與規則  
> 4. 完整目錄結構  
> 5. 所有 18 個檔案的完整程式碼  

---

## 一、策略概覽

**策略類型**：混合策略 — 技術指標初篩 + 籌碼確認  
**交易市場**：台股（上市 + 上櫃）  
**主要語言**：Python  
**資金規模**：小額試跑（5 萬以下），最多同時持倉 3 檔  
**開發工具**：Claude Code（代理式開發，時程以小時計）

### 核心選股邏輯

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

---

### Phase 4：自動化下單系統建構（9–11 h）

| # | 任務 | 工時 |
|---|------|------|
| 4.1 | 永豐 Shioaji 串接（登入/查餘額/查持倉，API key 存 .env）| 1.5 h |
| 4.2 | OrderManager（買/賣/漲停重試/部分成交/委託逾時取消）| 2.5 h |
| 4.3 | PositionManager（持倉追蹤，本地 JSON 持久化，最多 3 檔）| 2 h |
| 4.4 | RiskGuard（停損/日虧損上限/連虧熔斷/倉位上限）| 2 h |
| 4.5 | APScheduler 排程整合（盤前選股→開盤下單→盤中監控→盤後報表）| 1.5 h |

**風控規則（硬性，依優先順序）：**
1. 單筆虧損 −5% → 自動砍倉
2. 單日虧損 > 總資金 −2% → 全停機
3. 連虧 3 筆 → 暫停等人工審核
4. 單股倉位 ≤ 總資金 30%
5. 持倉數 ≤ 3 檔

**Gate 條件：** 模擬盤連跑 10 個交易日（2 週）無異常才切實盤

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
├── .env.example              # API keys 範本（實際使用時複製為 .env）
├── .env                      # 實際 keys（不可上傳 git）
├── README.md
├── requirements.txt
├── main.py                   # 排程主程式入口
│
├── config/
│   ├── strategy.yaml         # 策略參數（所有數字都在這裡調）
│   └── settings.yaml         # 系統設定（排程時間/日誌/風控）
│
├── src/
│   ├── __init__.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetcher.py        # FinMindFetcher + FugleFetcher
│   │   └── universe.py       # 上市/上櫃股票池管理
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── tech_signal.py    # TechSignal（TA 初篩）
│   │   ├── chip_signal.py    # ChipAnalyzer + MarginAnalyzer
│   │   └── score_engine.py   # ScoreEngine（串接兩層的核心）
│   ├── backtest/
│   │   ├── __init__.py
│   │   └── backtester.py     # TaiwanBacktester（Vectorbt 封裝）
│   ├── execution/
│   │   ├── __init__.py
│   │   ├── broker_client.py  # BrokerClient（Shioaji 封裝）
│   │   └── order_manager.py  # OrderManager + PositionManager
│   ├── risk/
│   │   ├── __init__.py
│   │   └── risk_guard.py     # RiskGuard（風控守門員）
│   ├── notify/
│   │   ├── __init__.py
│   │   └── telegram_bot.py   # TelegramNotifier
│   └── utils/
│       ├── __init__.py
│       ├── logger.py          # setup_logger + log_trade
│       └── helpers.py         # load_config / calc_trade_cost / 日期工具
│
├── data/
│   ├── raw/                  # FinMind 原始資料快取
│   └── processed/            # 候選清單 CSV / 回測報告 / 持倉 JSON
│
├── logs/                     # 交易日誌（自動輪轉）
│
├── notebooks/                # Jupyter 驗證用（Phase 0 資料探索）
│
└── tests/                    # 單元測試（之後補充）
```

**模組依賴關係：**
```
main.py
  ├── ScoreEngine          ← 選股核心（唯一入口）
  │     ├── FinMindFetcher
  │     ├── TechSignal
  │     └── ChipAnalyzer / MarginAnalyzer
  ├── BrokerClient         ← 唯一接觸 shioaji 的地方
  ├── OrderManager         ← 下單（呼叫 BrokerClient）
  ├── PositionManager      ← 部位狀態（獨立，不呼叫 broker）
  ├── RiskGuard            ← 風控（不下單，只判斷）
  └── TelegramNotifier     ← 通知（完全被動，只推播）
```

---

## 五、完整程式碼

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

# --- 進出場規則 ---
entry:
  max_positions: 3          # 最多同時持倉檔數
  position_size_pct: 0.30   # 單股最大佔總資金比例

exit:
  stop_loss_pct: -0.05      # 停損 -5%（硬性，優先執行）
  take_profit_pct: 0.10     # 停利 +10%
  max_hold_days: 15         # 最長持有天數
  ma_break_exit: true       # 跌破 MA20 出場

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

## 六、給 Claude Code 的工作指示

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
pip install -r requirements.txt
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

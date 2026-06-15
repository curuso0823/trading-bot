# Taiwan Stock Trading Bot
混合策略：技術指標初篩 + 籌碼確認，台股自動交易系統

## 策略邏輯
```
全市場 1,700 檔（live 因免費 FinMind 額度，預設只掃驗證過的 watchlist 35 檔）
  → TA 初篩（站上向上 MA20 + 量能放大 + RSI 健康）→ 候選池
  → 籌碼評分（外資/投信買超 + 融資健康度，加分制 ≥2 分）→ 進場候選
  → 趨勢跟隨進場（並倉上限 6、vol_target 配重、ATR 移動停損抱贏家）
```
> 低頻趨勢策略：常有 0 候選日屬設計（降頻、抱贏家），非缺陷。

## 模組地圖
```
src/
├── data/
│   ├── fetcher.py        # FinMind + Fugle 資料抓取
│   └── universe.py       # 股票池管理（上市+上櫃）
├── signals/
│   ├── tech_signal.py    # TA 初篩：MA / RSI / 量能
│   ├── chip_signal.py    # 籌碼確認：法人 / 融資券
│   └── score_engine.py   # 整合評分器（串接兩層）
├── backtest/
│   ├── backtester.py     # Vectorbt 回測框架
│   └── capped_sim.py     # 小資金集中策略回測（忠實重現 live，GUI/notebook 共用）
├── execution/
│   ├── broker_client.py  # 永豐 Shioaji 封裝
│   ├── broker_factory.py # paper / shioaji 切換
│   ├── order_manager.py  # 下單 / 查詢 / 取消 / 部位追蹤
│   ├── paper_broker.py   # 本地模擬撮合（paper 模式）
│   └── odd_lot_fill.py   # 零股成交不確定性模型
├── risk/
│   └── risk_guard.py     # 風控：移動停損 / 日虧損上限 / 連虧熔斷
├── notify/
│   ├── notify_manager.py # 推播路由：line(主) / discord(備援) / telegram
│   ├── line_bot.py       # LINE Messaging API（主推）
│   ├── discord_bot.py    # Discord（備援）
│   └── telegram_bot.py   # Telegram
└── utils/
    ├── logger.py          # 結構化日誌
    └── helpers.py         # 共用工具函數
config/
├── strategy.yaml          # 策略參數（可調）
└── settings.yaml          # 系統設定
main.py                    # 排程主程式入口
```

## 快速開始
```bash
cp .env.example .env            # 填入 API keys
pip install -e .                # 核心 runtime（live 用，不含 vectorbt）
python main.py                  # 啟動排程
```

依賴分組（`pyproject.toml` optional-extras）：
```bash
pip install -e ".[dev]"         # 開發/回測：+ vectorbt + pytest + 視覺化
pip install ".[broker]"         # 切實盤才需：永豐 Shioaji
pip install ".[telegram]"       # 用 Telegram 推播才需（主推 LINE 免額外裝）
```

## 開發流程 Gate
- Phase 0 完成：資料可正常抓取並對齊
- Phase 1 完成：TA 掃描器每日產出 30–80 候選
- Phase 2 完成：ScoreEngine 產出含評分候選清單
- Phase 3 Gate：Out-of-sample 夏普>1、回撤<15%、50+筆（**回測量測，非實盤累積**）
- Phase 4 Gate：模擬盤 10 交易日無異常（**不要求最低交易筆數**）
- Phase 5：實盤上線，初始資金 ≤ 3 萬

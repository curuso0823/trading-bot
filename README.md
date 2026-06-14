# Taiwan Stock Trading Bot
混合策略：技術指標初篩 + 籌碼確認，台股自動交易系統

## 策略邏輯
```
全市場 1,700 檔
  → TA 初篩（MA20 突破 + 量能放大 + RSI 健康）→ 50–80 檔/日
  → 籌碼評分（法人買超 + 融資健康度）         →  5–15 檔/日
  → 進場候選清單
```

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
│   └── backtester.py     # Vectorbt 回測框架
├── execution/
│   ├── broker_client.py  # 永豐 Shioaji 封裝
│   ├── order_manager.py  # 下單 / 查詢 / 取消
│   └── position_manager.py # 部位追蹤
├── risk/
│   └── risk_guard.py     # 風控：停損 / 日虧損上限 / 熔斷
├── notify/
│   └── telegram_bot.py   # Telegram 推播通知
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
cp .env.example .env      # 填入 API keys
pip install -r requirements.txt
python main.py            # 啟動排程
```

## 開發流程 Gate
- Phase 0 完成：資料可正常抓取並對齊
- Phase 1 完成：TA 掃描器每日產出 30–80 候選
- Phase 2 完成：ScoreEngine 產出含評分候選清單
- Phase 3 Gate：Out-of-sample 夏普>1、回撤<15%、50+筆
- Phase 4 Gate：模擬盤 10 交易日無異常
- Phase 5：實盤上線，初始資金 ≤ 3 萬

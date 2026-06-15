# GCP e2-micro 部署指南（模擬盤連跑）

讓 bot 在 GCP 永久免費層 VM 上 24h 常駐跑模擬盤，並累積真實開盤滑價數據。

> 目前為 **paper 模式**（PaperBroker，本地撮合、無真實下單）。執行階段**不需** vectorbt/shioaji（那些只在回測/實盤用）。

---

## 1. 建立 VM（GCP Console）
- Compute Engine → 建立執行個體
- **機型 `e2-micro`**（永久免費層）
- **區域必須是** `us-west1` / `us-central1` / `us-east1`（只有這三區的 e2-micro 免費）
- 開機磁碟：**Debian 12 (bookworm)**（內建 Python 3.11，免另裝）、標準永久磁碟 30GB（免費額度內）
- 防火牆：不需開任何 inbound（bot 只對外連 API，不收連線）

## 2. SSH 進去 + 基本套件
```bash
sudo apt update && sudo apt install -y python3.11-venv git
python3 --version   # 應為 3.11.x
```

## 3. 放上程式碼
擇一：
- **scp（最簡單）**：本機 `gcloud compute scp --recurse "C:\Users\wants\OneDrive\Desktop\trading bot" YOUR_VM:~/trading-bot --zone=YOUR_ZONE`
- **git**：把專案 push 到你的私有 GitHub repo，VM 上 `git clone`

> ⚠️ 只傳**程式碼**，別把本機的 `data/`、`logs/`、`.venv/` 傳上去（VM 上重建）。
> 若用 scp 整包傳了，在 VM 上先清狀態檔讓帳戶/計數從零開始：
> `rm -f data/processed/{paper_account,positions,daily_risk_state,notify_count,slippage_log}.* ; rm -rf .venv`

## 4. 建 venv + 裝依賴
```bash
cd ~/trading-bot
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install --no-cache-dir -e .   # 只裝核心 runtime（不含 vectorbt）；--no-cache-dir：1GB RAM 省記憶體
```

## 5. 填 .env（機密，VM 上手動建）
```bash
cp .env.example .env && nano .env
```
模擬盤連跑**至少**要填：
```
FINMIND_TOKEN=...                 # 選股資料
FUGLE_API_KEY=...                 # 即時/零股報價（滑價量測必需）
LINE_CHANNEL_ACCESS_TOKEN=...     # 主推播
LINE_USER_ID=...
DISCORD_WEBHOOK_URL=...           # 備援推播
```
Shioaji / Telegram 這次免填（paper 模式 + 用 LINE）。
確認 `config/settings.yaml` 的 `broker.mode: paper`、`notify.provider: line`。

## 6. 裝成常駐服務
```bash
sed -i "s/YOUR_USER/$USER/g" deploy/trading-bot.service
sudo cp deploy/trading-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now trading-bot
sudo systemctl status trading-bot      # 應為 active (running)
```
即時日誌：`journalctl -u trading-bot -f`，或看 `logs/` 下的檔。
啟動時你的 LINE 不會收到訊息（啟動訊息設為只記 log）；盤中才會有進場/摘要推播。

## 7. 緊急停機
```bash
bash deploy/emergency_stop.sh        # 停服務 + 設 HALT 旗標
# 恢復：rm data/processed/HALT && sudo systemctl start trading-bot
```
- 只想「暫停下單」但保留系統：`touch data/processed/HALT`（market_open 會跳過進場）
- 風控自動熔斷後恢復：刪 `data/processed/daily_risk_state.json`（或程式內 `RiskGuard.resume()`）

## 8. 連跑數日後 → 檢視真實滑價
```bash
.venv/bin/python -c "from src.utils.slippage_logger import summary; summary()"
```
會輸出隱含滑價/半價差中位數 → 用來重校 `config/strategy.yaml` 的 `trading.odd_lot_slippage`，再重跑回測確認 Gate。

## 完成標準（spec）
模擬盤連跑 **≥10 個交易日無系統錯誤**、下單行為 100% 符合預期 → 才考慮切實盤（需 Shioaji 開戶 + CA 憑證 + `broker.mode: shioaji`）。

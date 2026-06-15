# macOS launchd 自動化部署（每日 08:30 啟動 / 15:00 停止）

本機（Mac）以 `launchd` 取代 GCP 的 systemd / Windows 的 Task Scheduler：
每天 **08:30 自動啟動**交易 bot，**15:00 自動優雅停止**。目前為 **paper 模式**（本地撮合、不真實下單）。

> 時間對齊：本機時區為 UTC+8（CST），與 bot 內建的 `Asia/Taipei` 排程一致。
> 08:30 啟動 → 早於 bot 的盤前選股 08:50、開盤下單 09:12；15:00 停止 → 晚於盤後摘要 14:00，留 1 小時緩衝。

---

## 前置：建 venv + 裝依賴（依賴來源 = `pyproject.toml`）

launchd 只負責「排程啟動」，實際跑的是 `.venv/bin/python main.py`——所以 `.venv` 必須先建好。
依賴一律由 `pyproject.toml` 提供（核心 runtime **不含 vectorbt**，live 用不到）：

```bash
cd <專案根目錄>
python3.11 -m venv .venv               # 必須 Python 3.11（vectorbt/numba/numpy<2 生態）
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .   # 核心 runtime；要跑回測/測試再 -e ".[dev]"
```

驗證：`.venv/bin/python -c "import pandas, apscheduler, yaml, fugle_marketdata; print('deps ok')"`
（下方 `install.sh` 也會自動做這個前置檢查，缺 venv/依賴會直接擋下，不會留下會在 08:30 崩潰的排程。）

---

## 一鍵安裝

```bash
bash deploy/macos/install.sh
```

會把兩個 LaunchAgent 安裝到 `~/Library/LaunchAgents/` 並載入：
- `com.tradingbot.start` — 每日 08:30 啟動
- `com.tradingbot.stop`  — 每日 15:00 停止

安裝後**不需重開機**即生效。可重複執行（會自動卸載舊版再載入）。

## 解除安裝

```bash
bash deploy/macos/uninstall.sh
```

---

## 運作原理

```
08:30  launchd ──► start_bot.sh (supervisor) ──► .venv/bin/python main.py（常駐）
                       │                              └─ APScheduler 跑 08:50 選股 / 09:12 下單 / 盤中監控 / 14:00 摘要
                       └─ main.py 崩潰(非0退出) → 30s 後自動重啟（限視窗內）
15:00  launchd ──► stop_bot.sh ──► launchctl kill TERM ──► supervisor 轉送 SIGTERM
                                                              └─ main.py graceful_shutdown（broker.disconnect）→ 乾淨退出、不重啟
```

- **崩潰自動重啟**：supervisor 等同 systemd `Restart=on-failure`，但僅限 08:30~15:00 視窗內。
- **單例保護**：`main.py` 內建 fcntl 檔案鎖，不會雙開重複下單。
- **盤中重啟續跑**：重啟時 main.py 會 `_load_day_state()` 復原當日候選/部位，並對帳券商持倉。
- **非交易日**：bot 內建 `is_trading_day()`（含台股假日），週末/國定假日啟動後會自動空轉，15:00 照常停止（啟停皆只記 log、不推播 LINE）。

---

## 常用指令

```bash
UID_NUM=$(id -u)

# 看下次觸發時間 / 服務狀態
launchctl print gui/$UID_NUM/com.tradingbot.start | grep -A3 'next fire'

# 立即手動測跑一次（不必等 08:30；會一直跑到 15:00 或手動停止）
launchctl kickstart -k gui/$UID_NUM/com.tradingbot.start

# 立即手動停止
launchctl kickstart -k gui/$UID_NUM/com.tradingbot.stop
# 或直接：bash deploy/macos/stop_bot.sh

# 即時看 bot 日誌
tail -f logs/trading_*.log          # 主程式 loguru 日誌
tail -f logs/launchd_supervisor.log # supervisor 啟停/重啟紀錄
tail -f logs/launchd_start.err.log  # 啟動期 stderr（崩潰 traceback 會在這）
```

---

## 注意事項

1. **Mac 須開機並維持登入**：LaunchAgent 在使用者 GUI session 下執行。
   - 若 08:30 時 Mac 在**睡眠**：喚醒後 launchd 會補跑當天那次啟動。
   - 若 08:30 時 Mac **關機**：當天不會啟動（開機登入後也不會補跑當日的 08:30）。
   - 建議盤中讓 Mac 不要睡眠（系統設定 → 鎖定畫面/節能，或盤中插電不闔蓋）。
     進階：可用 `sudo pmset repeat wakeorpoweron MTWRF 08:25:00` 讓週一~五 08:25 自動喚醒。

2. **只想暫停下單、但保留系統**：`touch data/processed/HALT`（開盤任務會跳過進場）。恢復：`rm data/processed/HALT`。

3. **緊急全停**：`bash deploy/emergency_stop.sh`（若該腳本為 Linux 版，本機等效為 `bash deploy/macos/stop_bot.sh` + `touch data/processed/HALT`）。

4. **改時間**：編輯 `deploy/macos/com.tradingbot.{start,stop}.plist` 裡的 `Hour`/`Minute`，再重跑 `bash deploy/macos/install.sh`。

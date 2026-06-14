# Windows 本機背景部署（免雲端）

讓 bot 在你的 Windows 電腦背景常駐、開機/登入自動啟動、崩潰自動重啟。
適合：小資金、盤中(09:00–13:30)電腦本就會開著的情境。免 GCP 帳戶、免免費額度顧慮。

> 用 `pythonw.exe`（無主控台視窗）在背景跑；用「工作排程器(Task Scheduler)」管理常駐與自動重啟。

---

## ⚠️ 部署前兩個重要前置

### 1) 專案路徑（已完成）
已搬到非 OneDrive 同步路徑 `C:\trading-bot`（OneDrive 會一直同步 bot 持續寫的 `data/`、`logs/` → 檔案鎖衝突）。所有指令在此根目錄下執行，venv 為 `.venv`（Python 3.11.9，套件已裝）。

> ⚠️ **關於「孤兒進程」（已用程式碼解決，不需 `--copies`）**：
> Windows 的 venv `Scripts\pythonw.exe` **本質上一定是兩進程** —— 啟動器會 re-exec 到 base python 子進程做實事（`--copies` **改不掉**，這是 Windows venv 設計，非 bug）。風險是：Task Scheduler 停止時若漏殺 base 子進程 → 孤兒會繼續跑 `main.py`、甚至和自動重啟的新實例**雙開重複下單**。
> 本專案用**兩道防線**解決，與進程數無關：
> 1. **單例鎖**（`src/utils/singleton.py`，main.py 啟動時取 OS 檔案鎖）→ 偵測到已有實例就自行退出，**杜絕雙開**。行程死亡 OS 自動釋放，無 stale-PID 問題。
> 2. **emergency_stop.ps1 連整棵進程樹一起殺**（按 venv 路徑 / `main.py` 命令列強制清除）→ 即使有孤兒也一定停得掉。

### 2) 盤中別讓電腦睡眠
睡眠/休眠會讓背景程式暫停 → 錯過下單。設成不睡眠（至少 AC 電源）：
```powershell
powercfg /change standby-timeout-ac 0   # 插電時永不睡眠
powercfg /change hibernate-timeout-ac 0
```
（筆電闔蓋也會睡 → 設定「闔上時不動作」或外接電源開蓋。）

---

## 方式 A — 最簡單（建議第一次連跑用）
開一個 PowerShell，直接跑（會持續阻塞=正常），把視窗**最小化**留著：
```powershell
cd C:\trading-bot
$env:PYTHONUTF8=1
.\.venv\Scripts\python.exe main.py
```
盤中會自動選股/下單/推播；要停就 Ctrl+C 或關視窗。缺點：要保持登入、視窗別關。
（看得到、最好debug；連跑幾天確認無誤後再考慮方式 B 無人值守。）

## 方式 B — 背景常駐（無視窗、自動重啟）
> 孤兒/雙開已由單例鎖 + emergency_stop 處理（見上），無需 `--copies`。
在專案根目錄開 **PowerShell**：
```powershell
.\deploy\install_task.ps1            # 註冊並立即啟動（正式上線）
# 或先就緒不跑： .\deploy\install_task.ps1 -NoStart  （註冊後停用，之後 Enable+Start 才上線）
```
這會註冊一個「登入時自動啟動、崩潰自動重啟、無視窗背景跑」的工作排程 `TradingBot`。
> 註冊排程需要權限：請用**你自己的 PowerShell**執行（非沙箱）。若 `Register-ScheduledTask: Access is denied`，改開「以系統管理員身分執行」的 PowerShell。

確認：
```powershell
Get-ScheduledTask TradingBot | Get-ScheduledTaskInfo   # 看 LastRunTime / State
Get-Content logs\trading_*.log -Tail 20                 # 看日誌
```
> 啟動訊息只記 log（不推 LINE，省額度）；盤中才會有進場/摘要的 LINE 推播。

## 緊急停機 / 暫停
```powershell
.\deploy\emergency_stop.ps1     # 停工作 + 設 HALT 旗標（不再進場）
```
恢復：`Remove-Item data\processed\HALT; Start-ScheduledTask TradingBot`
- 只想暫停下單、保留系統：`New-Item data\processed\HALT -ItemType File`（market_open 會跳過進場）
- 風控熔斷後恢復：刪 `data\processed\daily_risk_state.json`

## 移除
```powershell
Unregister-ScheduledTask TradingBot -Confirm:$false
```

---

## 本機 vs GCP 取捨
| | 本機 Windows | GCP e2-micro |
|---|---|---|
| 成本/額度顧慮 | 無 | 永久免費層(但要設帳戶) |
| 盤中需電腦開著不睡 | 要 | 不用(雲端24h) |
| 設定難度 | 低(一鍵 ps1) | 中(建VM) |
| 適合 | 你現在這階段 | 之後想無人值守 |

模擬盤連跑 ≥10 交易日無系統錯誤 → 才考慮切實盤（Shioaji 開戶 + CA 憑證 + `broker.mode: shioaji`）。

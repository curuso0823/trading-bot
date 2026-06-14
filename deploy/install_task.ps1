# 註冊 Windows 工作排程：背景(無視窗)常駐、登入自動啟動、崩潰自動重啟。
# 用法（專案根目錄 PowerShell）：
#   .\deploy\install_task.ps1           註冊並立即啟動（正式上線）
#   .\deploy\install_task.ps1 -NoStart  只註冊但停用（部署就緒、先不跑；之後 Enable+Start 才上線）
param([switch]$NoStart)
$ErrorActionPreference = "Stop"

$proj = Split-Path -Parent $PSScriptRoot          # 專案根 = deploy 的上層
$py = Join-Path $proj ".venv\Scripts\pythonw.exe" # 無主控台視窗的 python
if (-not (Test-Path $py)) {
    Write-Error "找不到 $py — 請先建立 .venv（py -3.11 -m venv .venv 並裝 requirements.txt）"
    exit 1
}

$action = New-ScheduledTaskAction -Execute $py -Argument "main.py" -WorkingDirectory $proj
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName "TradingBot" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Taiwan stock trading bot (paper)" -Force | Out-Null

if ($NoStart) {
    Disable-ScheduledTask -TaskName "TradingBot" | Out-Null
    Write-Host "✅ 已註冊 TradingBot 但【停用】（部署就緒，尚未執行）。"
    Write-Host "   正式上線：Enable-ScheduledTask TradingBot ; Start-ScheduledTask TradingBot"
} else {
    Start-ScheduledTask -TaskName "TradingBot"
    Write-Host "✅ 已註冊並啟動 TradingBot（背景常駐、無視窗）。"
}
Write-Host "   日誌：logs\ ；狀態：Get-ScheduledTask TradingBot | Get-ScheduledTaskInfo"
Write-Host "   停機：.\deploy\emergency_stop.ps1"

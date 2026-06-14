# 一鍵緊急停機（Windows）。用法：.\deploy\emergency_stop.ps1
$proj = Split-Path -Parent $PSScriptRoot

Write-Host "== 緊急停機 =="
try {
    Stop-ScheduledTask -TaskName "TradingBot" -ErrorAction Stop
    Write-Host "✅ TradingBot 工作已停止"
} catch {
    Write-Host "（工作未在執行或不存在）"
}

# 連整棵進程樹一起殺：Windows venv 必為兩進程(stub→base child)，
# 若 Task Scheduler 停止時漏殺 base 子進程 → 孤兒會繼續跑 main.py。
# 這裡按「執行檔在本專案 venv」或「命令列含 main.py」強制清除，確保真的停。
$killed = 0
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" | Where-Object {
    ($_.ExecutablePath -like "$proj\.venv*") -or ($_.CommandLine -like "*main.py*")
} | ForEach-Object {
    try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; $script:killed++ } catch {}
}
Write-Host "✅ 已清除本專案 python 進程 $killed 個（含可能的孤兒子進程）"

# 設下單暫停旗標：即使工作重啟也不會進場，直到移除旗標
$procDir = Join-Path $proj "data\processed"
if (-not (Test-Path $procDir)) { New-Item -ItemType Directory -Path $procDir -Force | Out-Null }
New-Item -ItemType File -Path (Join-Path $procDir "HALT") -Force | Out-Null
Write-Host "✅ 已設 HALT 旗標：market_open 不會再進場"

Write-Host ""
Write-Host "目前為模擬盤（PaperBroker），無真實部位。"
Write-Host "恢復交易：Remove-Item data\processed\HALT ; Start-ScheduledTask TradingBot"
Write-Host "永久停用：Disable-ScheduledTask TradingBot"

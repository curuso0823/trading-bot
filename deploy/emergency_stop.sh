#!/bin/bash
# 一鍵緊急停機（GCP VM 上執行）。
# 用法：bash deploy/emergency_stop.sh
set -e

echo "== 緊急停機 =="
# 1) 停掉常駐服務（停止所有排程任務）
sudo systemctl stop trading-bot && echo "✅ trading-bot 服務已停止"

# 2) 設下單暫停旗標（即使手動重啟也不會進場，直到移除旗標）
mkdir -p data/processed
touch data/processed/HALT && echo "✅ 已設 HALT 旗標：market_open 不會再進場"

echo ""
echo "目前為模擬盤（PaperBroker），無真實部位。"
echo "恢復交易："
echo "  rm data/processed/HALT            # 移除暫停旗標"
echo "  sudo systemctl start trading-bot  # 重新啟動服務"
echo "若風控熔斷(halted)，另需在程式內 RiskGuard.resume() 或刪 data/processed/daily_risk_state.json"

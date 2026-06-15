#!/bin/bash
# ─────────────────────────────────────────────────────────────
# stop_bot.sh — launchd 於每日 15:00 執行：優雅停止 bot
#
# 對 start supervisor 送 SIGTERM → supervisor 轉送給 main.py
# → graceful_shutdown（broker.disconnect + 記 log「交易系統已關閉」）→ 乾淨退出。
# 因 start 服務未設 KeepAlive，乾淨退出後不會重啟，會一路停到隔日 08:30。
# ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG="$PROJECT_DIR/logs/launchd_supervisor.log"
UID_NUM="$(id -u)"

echo "$(date '+%F %T') stop_bot：送 SIGTERM 給 com.tradingbot.start" >> "$LOG"

# 主路徑：對 start 服務送 SIGTERM
launchctl kill TERM "gui/$UID_NUM/com.tradingbot.start" 2>/dev/null

# 後備：若服務未命中（例如尚未被 launchctl 追蹤），直接比對 supervisor 進程
sleep 3
pkill -TERM -f "$PROJECT_DIR/deploy/macos/start_bot.sh" 2>/dev/null

exit 0

#!/bin/bash
# ─────────────────────────────────────────────────────────────
# start_bot.sh — launchd 於每日 08:30 啟動的 supervisor
#
# 行為：
#   - 常駐執行 main.py（內建 APScheduler，盤前/開盤/盤中/盤後皆由它排）
#   - 崩潰（非 0 退出）→ 30s 後自動重啟（等同 GCP systemd 的 Restart=on-failure，
#     但僅限於 08:30~15:00 視窗內，因 15:00 supervisor 會被 stop_bot.sh 收掉）
#   - 收到 SIGTERM → 轉送給 main.py 觸發 graceful_shutdown（broker.disconnect）
#     後乾淨退出、不再重啟
#   - main.py 自身有單例鎖（fcntl flock）→ 不會雙開重複下單
# ─────────────────────────────────────────────────────────────
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR" || exit 1

PY="$PROJECT_DIR/.venv/bin/python"
LOG="$PROJECT_DIR/logs/launchd_supervisor.log"
CHILD=""

_term() {
    [ -n "$CHILD" ] && kill -TERM "$CHILD" 2>/dev/null
    [ -n "$CHILD" ] && wait "$CHILD" 2>/dev/null
    [ -n "${CAFFEINATE_PID:-}" ] && kill "$CAFFEINATE_PID" 2>/dev/null
    echo "$(date '+%F %T') supervisor 收到 SIGTERM → 已優雅停止 bot" >> "$LOG"
    exit 0
}
trap _term TERM INT

echo "$(date '+%F %T') supervisor 啟動（PROJECT_DIR=$PROJECT_DIR）" >> "$LOG"

# ── 盤中防 idle 睡眠（08:30 啟動盲區的白天版）─────────────────────
# Mac 盤中 idle 會進維護睡眠，悶住 08:50 選股 / 09:12 下單的 APScheduler cron。
# 背景 caffeinate 持有「禁止系統睡眠」assertion，綁定本 supervisor 壽命（-w $$）：
# 15:00 stop_bot 收掉 supervisor → assertion 隨即釋放，Mac 恢復可睡。
# （-i 連電池也防 idle 睡眠；-s 在 AC 時防睡眠；闔蓋仍強制睡眠，無永久不睡/斷電風險。）
CAFFEINATE_PID=""
if command -v caffeinate >/dev/null 2>&1; then
    caffeinate -is -w $$ &
    CAFFEINATE_PID=$!
    echo "$(date '+%F %T') 已啟動 caffeinate（PID $CAFFEINATE_PID）防盤中 idle 睡眠" >> "$LOG"
fi

while true; do
    "$PY" main.py &
    CHILD=$!
    wait "$CHILD"
    code=$?
    CHILD=""
    if [ "$code" -eq 0 ]; then
        echo "$(date '+%F %T') bot 正常退出（code 0）→ supervisor 結束" >> "$LOG"
        exit 0
    fi
    echo "$(date '+%F %T') bot 異常退出（code $code）→ 30s 後重啟" >> "$LOG"
    sleep 30
done

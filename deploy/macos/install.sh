#!/bin/bash
# ─────────────────────────────────────────────────────────────
# install.sh — 安裝 launchd 自動化（每日 08:30 啟動、15:00 停止）
# 可重複執行（idempotent）：會先卸載舊版再重新載入。
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LA_DIR="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

mkdir -p "$LA_DIR" "$PROJECT_DIR/logs"
chmod +x "$SCRIPT_DIR/start_bot.sh" "$SCRIPT_DIR/stop_bot.sh"

for label in com.tradingbot.start com.tradingbot.stop; do
    src="$SCRIPT_DIR/$label.plist"
    dst="$LA_DIR/$label.plist"
    # 把 plist 內的 __PROJECT_DIR__ 換成實際路徑（支援日後搬移資料夾，重跑即修正）
    sed "s#__PROJECT_DIR__#$PROJECT_DIR#g" "$src" > "$dst"
    # 重新載入：先 bootout 容錯舊版（忽略不存在的錯誤），再 bootstrap + enable
    launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_NUM" "$dst"
    launchctl enable "gui/$UID_NUM/$label"
    echo "✅ 已安裝並載入 $label"
done

echo
echo "完成。排程："
echo "  • 每日 08:30 → 啟動 bot（main.py 常駐，內建 Asia/Taipei 排程）"
echo "  • 每日 15:00 → 優雅停止 bot"
echo
echo "確認下次觸發時間："
echo "  launchctl print gui/$UID_NUM/com.tradingbot.start | grep -A3 'next fire'"
echo "立即手動測跑（不必等 08:30）："
echo "  launchctl kickstart -k gui/$UID_NUM/com.tradingbot.start"

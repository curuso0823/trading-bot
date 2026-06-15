#!/bin/bash
# ─────────────────────────────────────────────────────────────
# uninstall.sh — 解除 launchd 自動化（不影響專案檔案與狀態）
# ─────────────────────────────────────────────────────────────
set -uo pipefail

LA_DIR="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

for label in com.tradingbot.start com.tradingbot.stop; do
    launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
    rm -f "$LA_DIR/$label.plist"
    echo "🗑️  已移除 $label"
done

# 若 bot 仍在跑，順手優雅停掉
pkill -TERM -f "/deploy/macos/start_bot.sh" 2>/dev/null || true

echo "✅ 解除安裝完成。"

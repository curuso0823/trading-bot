#!/bin/bash
# ─────────────────────────────────────────────────────────────
# install.sh — 安裝 launchd 自動化（24/7 常駐：RunAtLoad + KeepAlive）
# 可重複執行（idempotent）：會先卸載舊版再重新載入。
# 註：舊的每日 15:00 stop 任務已停用（改 24/7 常駐）；殘留會在此一併 bootout + 刪除。
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LA_DIR="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"

# ── 前置檢查：.venv 與核心依賴必須就位（launchd 會跑 .venv/bin/python main.py）──
# 依賴來源為 pyproject.toml；缺則擋下安裝，避免留下會在 08:30 崩潰的排程。
PY="$PROJECT_DIR/.venv/bin/python"
if [ ! -x "$PY" ]; then
    echo "❌ 找不到 $PY" >&2
    echo "   先建 venv 並裝依賴： python3.11 -m venv .venv && .venv/bin/python -m pip install -e ." >&2
    exit 1
fi
if ! "$PY" -c "import pandas, apscheduler, yaml, fugle_marketdata" 2>/dev/null; then
    echo "❌ .venv 缺核心依賴。請執行： .venv/bin/python -m pip install -e ." >&2
    exit 1
fi
echo "✅ 前置檢查通過：.venv + 核心依賴就位"

mkdir -p "$LA_DIR" "$PROJECT_DIR/logs"
chmod +x "$SCRIPT_DIR/start_bot.sh"

# 停用舊的每日 15:00 stop 任務（24/7 常駐不需要；殘留會在開盤前 06:00 補觸發殺掉 bot）
launchctl bootout "gui/$UID_NUM/com.tradingbot.stop" 2>/dev/null || true
rm -f "$LA_DIR/com.tradingbot.stop.plist"

for label in com.tradingbot.start com.tradingbot.dashboard; do
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
echo
echo "完成。模式：24/7 常駐"
echo "  • 登入即啟動（RunAtLoad）＋ 任何退出 launchd 立即重啟（KeepAlive）"
echo "  • bot 內建 Asia/Taipei 排程只在交易日盤中動作（非交易日自動跳過）"
echo "  • caffeinate 防 idle 睡眠（需保持筆電開蓋）"
echo
echo "確認運行狀態："
echo "  launchctl print gui/$UID_NUM/com.tradingbot.start | grep -E 'state|runs'"
echo "更新程式碼後重啟："
echo "  launchctl kickstart -k gui/$UID_NUM/com.tradingbot.start"
echo "停機維護（如初始建倉）："
echo "  launchctl bootout gui/$UID_NUM/com.tradingbot.start"

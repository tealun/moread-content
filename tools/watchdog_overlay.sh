#!/bin/bash
# ──────────────────────────────────────────────────────
# Overlay Builder Watchdog — 每 5 分钟由 cron 调用
#
# 检查逻辑：
#   1. status.json 存在且 status == "running" → 检查 PID 是否活着
#   2. last_update 超过 10 分钟没更新 → 判定卡死，kill + 重启
#   3. status == "error" 或 "done" 或文件不存在 → 不干预
#   4. status == "done" → 清理，不重启
#
# 安装：
#   crontab -e
#   */5 * * * * /root/projects/moread-content/tools/watchdog_overlay.sh >> /tmp/overlay_watchdog.log 2>&1
# ──────────────────────────────────────────────────────

set -euo pipefail

PROJECT="/root/projects/moread-content"
STATUS_FILE="$PROJECT/dictionary/overlay.status.json"
SCRIPT="$PROJECT/tools/build_overlay.py"
LOG="/tmp/overlay_builder.log"

cd "$PROJECT"

# status.json 不存在 → 可能从未启动，不干预
if [ ! -f "$STATUS_FILE" ]; then
    echo "[$(date)] No status file, skipping"
    exit 0
fi

# 读取状态
STATUS=$(python3 -c "import json; d=json.load(open('$STATUS_FILE')); print(d.get('status','unknown'))")
PID=$(python3 -c "import json; d=json.load(open('$STATUS_FILE')); print(d.get('pid',''))")
LAST_UPDATE=$(python3 -c "
import json, datetime
d = json.load(open('$STATUS_FILE'))
lu = d.get('last_update', '')
if lu:
    dt = datetime.datetime.fromisoformat(lu)
    age = (datetime.datetime.now() - dt).total_seconds()
    print(int(age))
else:
    print(999999)
")

echo "[$(date)] status=$STATUS pid=$PID age=${LAST_UPDATE}s"

case "$STATUS" in
    "done")
        echo "[$(date)] Builder finished, nothing to do"
        exit 0
        ;;
    "error")
        echo "[$(date)] Builder in error state, restarting..."
        # Kill old process if still running
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            kill "$PID" 2>/dev/null || true
            sleep 2
        fi
        # Reset status
        python3 -c "
import json
d = json.load(open('$STATUS_FILE'))
d['status'] = 'restarting'
json.dump(d, open('$STATUS_FILE','w'), indent=2)
"
        echo "[$(date)] Starting builder..."
        nohup python3 "$SCRIPT" >> "$LOG" 2>&1 &
        echo "[$(date)] Started PID=$!"
        ;;
    "running")
        # 检查 PID 是否活着
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            # 进程活着，检查是否卡死（10 分钟无更新）
            if [ "$LAST_UPDATE" -gt 600 ]; then
                echo "[$(date)] STUCK (no update for ${LAST_UPDATE}s), killing PID=$PID"
                kill "$PID" 2>/dev/null || true
                sleep 2
                # Kill children too
                pkill -P "$PID" 2>/dev/null || true
                echo "[$(date)] Restarting..."
                nohup python3 "$SCRIPT" >> "$LOG" 2>&1 &
                echo "[$(date)] Started PID=$!"
            else
                echo "[$(date)] Healthy (age=${LAST_UPDATE}s)"
            fi
        else
            echo "[$(date)] Process $PID DEAD but status=running, restarting..."
            nohup python3 "$SCRIPT" >> "$LOG" 2>&1 &
            echo "[$(date)] Started PID=$!"
        fi
        ;;
    *)
        echo "[$(date)] Unknown status: $STATUS, skipping"
        ;;
esac

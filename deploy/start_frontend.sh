#!/usr/bin/env bash
# 启动本机前端 dev server（脱离会话独立存活）
#
# 用法：
#   bash start_frontend.sh          # 前台运行，Ctrl+C 停止（推荐，能看到日志）
#   bash start_frontend.sh --daemon # 后台运行，日志写入 .local/logs/frontend.log
#
# 端口 5273（避开本机 5173 冲突）；代理目标来自 frontend/.env.local。

set -euo pipefail

YUXI_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$YUXI_DIR/frontend"

PORT="${YUXI_FRONTEND_PORT:-5273}"

if [ "${1:-}" = "--daemon" ]; then
  mkdir -p "$YUXI_DIR/.local/logs"
  LOG="$YUXI_DIR/.local/logs/frontend.log"
  # nohup + disown：忽略 SIGHUP，父 shell 退出后进程继续存活
  nohup env -u NODE_OPTIONS npx vite --host --port "$PORT" > "$LOG" 2>&1 &
  disown
  echo "前端已在后台启动：http://localhost:$PORT"
  echo "日志：$LOG"
  echo "停止：pkill -f 'vite --host --port $PORT'"
  sleep 4
  tail -n 5 "$LOG" || true
else
  echo "启动前端 dev server：http://localhost:$PORT"
  echo "代理目标（来自 frontend/.env.local）："
  grep -E '^VITE_(API|MINIO)_URL=' .env.local || echo "  未配置，代理将指向默认容器地址"
  echo
  exec env -u NODE_OPTIONS npx vite --host --port "$PORT"
fi

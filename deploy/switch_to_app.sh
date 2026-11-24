#!/usr/bin/env bash
# 服务器：切回「应用容器 + 基建」形态，让本机跑的前端能连上后端
#
# 背景：
#   - 基建形态（server-infra.override.yml）把 api/worker/frontend 的 replicas 置 0，
#     本机前端虽有 vite 代理，但代理目标（10.249.7.130:5050）没有进程监听，接口会超时。
#   - 两种形态的基建端口绑定不同（基建形态 0.0.0.0，全栈形态 127.0.0.1），
#     同一宿主端口不能同时绑 0.0.0.0 与 127.0.0.1，所以必须先 down 再 up。
#
# 用法：bash switch_to_app.sh
set -euo pipefail

YUXI_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$YUXI_DIR"
COMPOSE="docker compose --profile container"

echo "==> 1/3 停止基建形态容器（释放宿主端口）"
${COMPOSE} -f docker-compose.yml -f deploy/server-infra.override.yml down --remove-orphans || true

echo "==> 2/3 启动应用形态（api 对外暴露 5050）"
${COMPOSE} -f docker-compose.yml -f deploy/server-app.override.yml up -d

echo "==> 3/3 验证"
${COMPOSE} -f docker-compose.yml -f deploy/server-app.override.yml ps
sleep 5
echo
if curl -fsS http://127.0.0.1:5050/api/system/health; then
  echo
  echo "后端就绪。本机前端（localhost:5273）的代理目标 http://10.249.7.130:5050 已可用。"
else
  echo "警告：后端健康检查未通过，请查看日志："
  echo "  ${COMPOSE} -f docker-compose.yml -f deploy/server-app.override.yml logs api --tail=50"
fi

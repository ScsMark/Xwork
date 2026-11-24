#!/usr/bin/env bash
# 服务器形态切换：服务端全栈 → 服务端基建（供本机跑应用）
#
# 背景：切换形态时旧容器仍占用宿主端口（5432 等），新容器绑定必然失败；
#      且 compose 合并 ports 是追加语义，override 必须用 !override 整段替换，
#      否则同一宿主端口会出现两条绑定记录。
#
# 用法：bash switch_to_infra.sh
set -euo pipefail

YUXI_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$YUXI_DIR"
COMPOSE="docker compose --profile container"

echo "==> 1/4 停止当前形态的容器（释放宿主端口）"
${COMPOSE} -f docker-compose.yml -f deploy/server-app.override.yml down --remove-orphans || true
${COMPOSE} -f docker-compose.yml -f deploy/server-app.override.yml ps -a

echo "==> 2/4 确认端口已释放"
for p in 5432 6379 9000 19530 7687 8090; do
  if ss -ltn "sport = :$p" 2>/dev/null | grep -q ":$p"; then
    echo "    警告：端口 $p 仍被占用，请检查是否有其他程序（如本机 postgres）监听"
  else
    echo "    端口 $p 已释放"
  fi
done

echo "==> 3/4 以基建形态启动（基建端口放开到 0.0.0.0）"
${COMPOSE} -f docker-compose.yml -f deploy/server-infra.override.yml up -d

echo "==> 4/4 验证"
${COMPOSE} -f docker-compose.yml -f deploy/server-infra.override.yml ps

echo
echo "完成。基建端口已对 10.249.7.130 开放，可用以下地址从本机连接："
echo "  postgres      10.249.7.130:5432"
echo "  redis         10.249.7.130:6379"
echo "  minio         10.249.7.130:9000"
echo "  milvus        10.249.7.130:19530"
echo "  neo4j         10.249.7.130:7687"
echo "  sandbox-runner 10.249.7.130:8090"
echo
echo "本机跑应用时，用 deploy/local.env 作为环境变量来源（已指向 10.249.7.130）。"

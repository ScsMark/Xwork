#!/usr/bin/env bash
# 服务器：升级到上游新版（合并了本地定制）
#
# 前提：已把 yuxi-server.tar.gz 上传到 ~/data/
#
# 本脚本做四件事：
#   1. 解压覆盖代码（保留服务器自己的 .env）
#   2. 检查 .env 必填项
#   3. 重建镜像（上游新增了大量后端模块与前端依赖，旧镜像缺文件）
#   4. 重建容器并验证
#
# 用法：bash upgrade_to_new_version.sh
set -euo pipefail

YUXI_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$YUXI_DIR"
COMPOSE="docker compose --profile container"
APP_FILES="-f docker-compose.yml -f deploy/server-app.override.yml"
PKG="$YUXI_DIR/../yuxi-server.tar.gz"

echo "==> 1/5 解压覆盖代码"
if [ ! -f "$PKG" ]; then
  echo "  未找到 $PKG，请先上传上传包到 ~/data/" >&2
  exit 1
fi
# --exclude 保留服务器自己的 .env：包内的沙箱 token 是随机值，
# 覆盖后与正在运行的 sandbox-runner 容器不一致会导致沙箱认证失败。
tar -xzf "$PKG" --exclude='Yuxi/.env'
echo "  已覆盖（.env 保留服务器版本）"

echo
echo "==> 1.5/5 清理上游已移除的残留文件"
if [ -f "$YUXI_DIR/deploy/prune_stale_files.sh" ]; then
  bash "$YUXI_DIR/deploy/prune_stale_files.sh" --apply || true
else
  echo "  未找到 prune_stale_files.sh，跳过（可手动删除已废弃的文件）"
fi

echo
echo "==> 2/5 检查 .env 必填项"
fail=0
check_env() {
  local key="$1" desc="$2" min_len="${3:-0}"
  local line val
  line=$(grep -E "^${key}=" .env 2>/dev/null | head -1)
  if [ -z "$line" ]; then
    echo "  ✗ ${key} 未设置（${desc}）"; fail=1; return
  fi
  val="${line#*=}"
  if [ "${#val}" -lt "$min_len" ]; then
    echo "  ✗ ${key} 长度 ${#val} < ${min_len}（${desc}）"; fail=1
  else
    echo "  ✓ ${key}（${desc}）"
  fi
}
if [ -f .env ]; then
  check_env NEO4J_PASSWORD "compose 插值必填" 1
  check_env SANDBOX_RUNNER_TOKEN "沙箱认证，≥16 字符" 16
  check_env JWT_SECRET_KEY "会话签名" 32
  check_env YUXI_ENCRYPTION_KEY "敏感字段加密" 32
  check_env API_KEY_DERIVATION_SECRET "密钥派生" 32
  check_env YUXI_INSTANCE_ID "实例标识" 8
  check_env POSTGRES_PASSWORD "数据库密码" 1
  check_env MINIO_SECRET_KEY "对象存储密钥" 1
else
  echo "  ✗ 缺少 .env"; fail=1
fi
if [ "$fail" -ne 0 ]; then
  echo "  必填项有缺失，请先补齐再继续（否则 app-init 会失败退出）" >&2
  exit 1
fi

echo
echo "==> 3/5 重建镜像"
echo "  上游新增了插件体系、aBridge、知识库领域服务等大量模块，"
echo "  且前端新增 js-tiktoken 依赖，必须重建镜像。"
echo "  （uv.lock 已指向国内镜像，构建时不会再卡官方源超时）"
${COMPOSE} ${APP_FILES} build

echo
echo "==> 4/5 重建容器"
# --force-recreate 会重建 app-init（一次性任务），从而执行新增的数据库迁移
# （上游新增了 migrations/agent_plugins.py）。若跳过，插件相关表不存在。
${COMPOSE} ${APP_FILES} up -d --force-recreate

echo
echo "==> 5/5 验证"
sleep 8

echo "  --- app-init 迁移结果"
${COMPOSE} ${APP_FILES} logs app-init --tail=15 2>/dev/null | grep -iE "schema|migrat|error|failed" | tail -6 || echo "  （无相关日志）"

echo
${COMPOSE} ${APP_FILES} ps
echo
echo "  --- 后端健康"
curl -fsS http://127.0.0.1:5050/api/system/health || echo "  警告：健康检查未通过"
echo
echo "  --- 品牌配置"
curl -fsS http://127.0.0.1:5050/api/system/info || echo "  警告：品牌接口未响应"
echo
echo
echo "完成。若 api 启动失败，查看日志："
echo "  ${COMPOSE} ${APP_FILES} logs api --tail=80"

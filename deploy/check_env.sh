#!/usr/bin/env bash
# 服务器：检查 .env 必填项（上传包不再携带 .env，服务器必须保留自己的配置）
#
# 用法：bash check_env.sh
set -uo pipefail

YUXI_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$YUXI_DIR"
ENV_FILE=".env"

echo "==> 检查 $ENV_FILE"
if [ ! -f "$ENV_FILE" ]; then
  echo "  ✗ 不存在 $ENV_FILE" >&2
  echo "    全新部署请先：cp .env.template $ENV_FILE 并填好密钥" >&2
  exit 1
fi

fail=0

check_present() {
  local key="$1" desc="$2" min_len="${3:-0}"
  local line val
  line=$(grep -E "^${key}=" "$ENV_FILE" 2>/dev/null | head -1)
  if [ -z "$line" ]; then
    echo "  ✗ ${key} 未设置（${desc}）"
    fail=1
    return
  fi
  val="${line#*=}"
  if [ "${#val}" -lt "$min_len" ]; then
    echo "  ✗ ${key} 长度 ${#val} < ${min_len}（${desc}）"
    fail=1
  else
    echo "  ✓ ${key}（${desc}）"
  fi
}

check_present NEO4J_PASSWORD "compose 插值必填，空值会导致 config 失败" 1
check_present SANDBOX_RUNNER_TOKEN "沙箱认证，app-init 校验 ≥16 字符" 16
check_present JWT_SECRET_KEY "会话签名" 32
check_present YUXI_ENCRYPTION_KEY "敏感字段加密" 32
check_present API_KEY_DERIVATION_SECRET "密钥派生" 32
check_present YUXI_INSTANCE_ID "实例标识" 8
check_present POSTGRES_PASSWORD "数据库密码" 1
check_present MINIO_SECRET_KEY "对象存储密钥" 1

echo
if [ "$fail" -eq 0 ]; then
  echo "全部必填项就绪。"
  echo
  echo "提醒：api/worker/sandbox-runner 三方共用同一个 SANDBOX_RUNNER_TOKEN，"
  echo "     修改后需重建这三个容器："
  echo "  docker compose --profile container -f docker-compose.yml \\"
  echo "    -f deploy/server-app.override.yml up -d --force-recreate api worker sandbox-runner"
else
  echo "存在缺失项，请先补齐再启动服务。"
fi
exit "$fail"

#!/usr/bin/env bash
# 服务器升级命令速查（手动逐步执行版）
#
# 一键版：bash deploy/upgrade_to_new_version.sh
# 本文件是同样的步骤拆开，便于逐步观察与排错。

cd ~/data/Yuxi

# 组合变量（与脚本内一致）
COMPOSE="docker compose --profile container"
APP="-f docker-compose.yml -f deploy/server-app.override.yml"

echo "===== 1/6 解压（--exclude 保留服务器自己的 .env）====="
cd ~/data
tar -xzf yuxi-server.tar.gz --exclude='Yuxi/.env'
cd Yuxi

echo "===== 2/6 校验 .env 必填项 ====="
# 缺项会导致 compose 插值失败或 app-init 启动即退出
grep -E '^(NEO4J_PASSWORD|SANDBOX_RUNNER_TOKEN|JWT_SECRET_KEY|YUXI_ENCRYPTION_KEY|API_KEY_DERIVATION_SECRET|YUXI_INSTANCE_ID|POSTGRES_PASSWORD|MINIO_SECRET_KEY)=' .env

echo "===== 3/6 清理上游已删除的残留文件（先预览）====="
bash deploy/prune_stale_files.sh
# 确认清单无误后再执行
bash deploy/prune_stale_files.sh --apply

echo "===== 4/6 重建镜像（必须：依赖变了 + 新增 js-tiktoken）====="
# 耗时较长；uv.lock 与 Dockerfile 都指向国内镜像，不会卡官方源
${COMPOSE} ${APP} build

echo "===== 5/6 重建容器 ====="
# --force-recreate 会重建 app-init（一次性任务），从而执行新增的数据库迁移
${COMPOSE} ${APP} up -d --force-recreate

echo "===== 6/6 验证 ====="
sleep 10
${COMPOSE} ${APP} ps
echo "--- app-init 迁移日志 ---"
${COMPOSE} ${APP} logs app-init --tail=20
echo "--- 后端健康 ---"
curl -fsS http://127.0.0.1:5050/api/system/health; echo
echo "--- 品牌配置 ---"
curl -fsS http://127.0.0.1:5050/api/system/info; echo

echo
echo "完成。若 api 异常：${COMPOSE} ${APP} logs api --tail=80"

#!/usr/bin/env bash
# 服务器：修复 Docker 构建上下文的权限报错
#
# 报错：target app-init: failed to solve: error from sender:
#       open /home/user/data/Yuxi/backend/yuxi/__pycache__: permission denied
#
# 原因：容器内以 root 运行的进程写 bind-mount 的源码目录，留下了 root 属主的
#       __pycache__；宿主普通用户无权读取，而 .dockerignore 的规则只写了
#       「__pycache__/」（仅匹配根层级），嵌套目录仍会进入构建上下文 → 构建报错。
#
# 用法：bash fix_build_permission.sh
#   1) 修正 .dockerignore（根治：这些目录不再进入构建上下文，无需删除）
#   2) 尝试清理残留缓存目录（有 sudo 才会成功，失败不影响构建）

set -uo pipefail

YUXI_DIR="${YUXI_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$YUXI_DIR" || exit 1

echo "==> 1/2 修正 .dockerignore"
DI=".dockerignore"
if [ -f "$DI" ]; then
  cp "$DI" "$DI.bak.$(date +%s)"
  # 用带 **/ 前缀的规则覆盖窄规则
  sed -i \
    -e 's|^__pycache__/$|**/__pycache__/|' \
    -e 's|^\*\.pyc$|**/*.pyc|' \
    -e 's|^\*\.pyo$|**/*.pyo|' \
    -e 's|^frontend/node_modules/$|**/node_modules/|' \
    -e 's|^frontend/dist/$|**/dist/|' \
    "$DI"
  echo "  已更新 $DI（备份为 $DI.bak.*）"
  grep -nE '^\*\*' "$DI" | head -10
else
  echo "  未找到 $DI，请手动确认内容" >&2
fi

echo
echo "==> 2/2 尝试清理残留缓存目录"
echo "  统计：$(find . -type d -name '__pycache__' 2>/dev/null | wc -l) 个 __pycache__ 目录"
if find . -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null; then
  echo "  已清理（或本来就没有）"
else
  echo "  无权限删除（目录属主是 root）——不影响构建，"
  echo "  因为 .dockerignore 已让它们不再进入构建上下文。"
  echo "  如需清理，用有 sudo 权限的账号执行："
  echo "    sudo find . -type d -name '__pycache__' -prune -exec rm -rf {} +"
fi

echo
echo "完成。现在可以重新构建："
echo "  docker compose --profile container -f docker-compose.yml -f deploy/server-app.override.yml build"

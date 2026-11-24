#!/usr/bin/env bash
# 服务器：解压新版后，清理上游已移除的残留代码文件
#
# 为什么需要：上游删除的文件不会因覆盖而消失，会残留在服务器上。
#   例：backend/yuxi/modules/extensions/skills/builtin/knowledge-base/SKILL.md
#       （上游移到 plugins/builtin/knowledge/skills/knowledge-base/）
#       frontend/src/modules/agents/ui/McpEnvEditor.vue（上游整体移除）
#
# 用法（必须在 Yuxi 代码根目录执行）：
#   cd ~/data/Yuxi
#   bash prune_stale_files.sh          # 只预览
#   bash prune_stale_files.sh --apply  # 实际删除
#
# 安全性：
#   - 不动 .env（服务器自己的配置）
#   - 不动 docker/volumes（PG/Redis/MinIO/Neo4j/Milvus 数据卷）
#   - 不动 backup/、.git/、node_modules/、.venv/ 等
#   - 只删 backend/ frontend/ deploy/ docker/ docs/ 下的文件
#   - 默认仅预览，必须显式 --apply 才删除

set -uo pipefail

YUXI_DIR="${YUXI_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PKG="${PKG:-$YUXI_DIR/../yuxi-server.tar.gz}"
MODE="${1:-}"

cd "$YUXI_DIR" || exit 1

if [ ! -f "$PKG" ]; then
  echo "未找到上传包 $PKG" >&2
  echo "请设置 PKG 环境变量指向 yuxi-server.tar.gz 的实际路径" >&2
  exit 1
fi

# 1. 新版文件清单
LIST=".prune_tmp_list"
ACTUAL=".prune_tmp_actual"
trap 'rm -f "$LIST" "$ACTUAL"' EXIT
tar -tzf "$PKG" | grep -v '/$' | sed 's|^Yuxi/||' | sort > "$LIST"

# 2. 服务器上的实际代码文件（排除保护项）
find . -type f \
  -not -path "./docker/volumes/*" \
  -not -path "./frontend/node_modules/*" \
  -not -path "./backend/.venv/*" \
  -not -path "./.venv/*" \
  -not -path "./.local/*" \
  -not -path "./frontend/dist/*" \
  -not -path "./backup/*" \
  -not -path "./.git/*" \
  -not -name ".env" \
  -not -name ".env.local" \
  -not -name ".npmrc" \
  -not -name ".prune_tmp_*" \
  -not -name "*.pyc" \
  -not -path "*/__pycache__/*" \
  | sed 's|^\./||' | sort > "$ACTUAL"

# 3. 差集：服务器有、新版没有
STALE=$(comm -13 "$LIST" "$ACTUAL")

echo "== 新版文件 $(wc -l < "$LIST") 个；服务器代码文件 $(wc -l < "$ACTUAL") 个 =="
if [ -z "$STALE" ]; then
  echo "没有需要清理的残留文件。"
  exit 0
fi

echo
echo "== 以下文件已不在新版中 =="
echo "$STALE" | sed 's/^/  - /'
echo

if [ "$MODE" != "--apply" ]; then
  echo "这是预览。确认无误后执行：bash prune_stale_files.sh --apply"
  exit 0
fi

echo "== 正在清理（移动到 .stale-trash/，可随时恢复）=="
DELETED=0
SKIPPED=0
TRASH=".stale-trash"
mkdir -p "$TRASH"
while IFS= read -r f; do
  [ -z "$f" ] && continue
  # 只处理代码目录下的文件；辅助脚本与其他路径一律跳过
  case "$f" in
    backend/*|frontend/*|deploy/*|docker/*|docs/*) ;;
    *) SKIPPED=$((SKIPPED + 1)); continue ;;
  esac
  if [ -f "$f" ]; then
    # 保留目录层级，避免同名文件互相覆盖
    DEST="$TRASH/$f"
    mkdir -p "$(dirname "$DEST")"
    if mv "$f" "$DEST" 2>/dev/null; then
      DELETED=$((DELETED + 1))
    else
      echo "  跳过（移动失败）: $f"
      SKIPPED=$((SKIPPED + 1))
    fi
  fi
done <<< "$STALE"

echo "已清理 $DELETED 个残留文件（移入 $TRASH/），跳过 $SKIPPED 个。"
echo "确认服务正常后可删除 $TRASH/；如需恢复，从该目录移回即可。"

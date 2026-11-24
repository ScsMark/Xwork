#!/usr/bin/env bash
# 服务器：修复 pnpm lockfile 与 workspace overrides 不匹配
#
# 报错：ERR_PNPM_LOCKFILE_CONFIG_MISMATCH
#       The current "overrides" configuration doesn't match the value found in the lockfile
#
# 根因：frontend/pnpm-workspace.yaml 里用 overrides 固定了 13 个包的版本
#      （yaml 2.8.3、katex 0.18.4、esbuild 0.28.2 等），
#      pnpm 10+ 会把 overrides 记进 pnpm-lock.yaml；用 pnpm 9 重新生成 lockfile
#      会丢掉这段记录，导致 pnpm 11 的 --frozen-lockfile 校验直接失败。
#
# 修复：从 pnpm-workspace.yaml 提取 overrides 段，插回 pnpm-lock.yaml
#      （位置：settings 之后、importers 之前，与上游一致）。
#
# 用法：bash fix_pnpm_lockfile.sh

set -uo pipefail

YUXI_DIR="${YUXI_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$YUXI_DIR/frontend" || exit 1

if [ ! -f pnpm-lock.yaml ] || [ ! -f pnpm-workspace.yaml ]; then
  echo "缺少 pnpm-lock.yaml 或 pnpm-workspace.yaml" >&2
  exit 1
fi

if grep -q '^overrides:' pnpm-lock.yaml; then
  echo "✓ pnpm-lock.yaml 已包含 overrides 段，无需修复"
else
  cp pnpm-lock.yaml "pnpm-lock.yaml.bak.$(date +%s)"
  python3 - <<'PY'
import re

# 用二进制读写，避免文本模式改写换行符（保证与上游文件字节一致）
with open('pnpm-workspace.yaml', 'rb') as f:
    ws = f.read()
with open('pnpm-lock.yaml', 'rb') as f:
    lock = f.read()

m = re.search(rb'^overrides:\n((?:[ \t]+.*\n)+)', ws, re.M)
if not m:
    raise SystemExit('pnpm-workspace.yaml 中未找到 overrides 段')

block = m.group(0).rstrip(b'\r\n')
count = len(block.split(b'\n')) - 1

# 先把 importers 之前的连续空行规范为一个，再插入 overrides 段，
# 保证结构与上游一致：lockfileVersion → settings → 空行 → overrides → 空行 → importers
new_lock, n = re.subn(rb'\n(?:[ \t]*\r?\n)+(?=importers:)', b'\n\n', lock, count=1)
if n != 1:
    raise SystemExit('未找到顶层 importers: 标记')
new_lock = new_lock.replace(b'importers:', block + b'\n\nimporters:', 1)

with open('pnpm-lock.yaml', 'wb') as f:
    f.write(new_lock)
print('已插入 overrides 段，共 %d 条' % count)
PY
  echo "  位置：第 $(grep -n '^overrides:' pnpm-lock.yaml | cut -d: -f1) 行"
fi

echo
echo "完成。现在可以重新构建："
echo "  docker compose --profile container -f docker-compose.yml -f deploy/server-app.override.yml build"
echo
echo "提示：若要彻底修正，请用新版上传包覆盖（内含上游原始 lockfile）"

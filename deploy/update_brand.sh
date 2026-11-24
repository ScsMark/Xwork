#!/usr/bin/env bash
# 服务器：更新品牌名（旧名 → XWork，含位图残留处理）
#
# 两个来源要一起处理：
#   A. 文字 —— branding.name / footer.copyright，来自
#      backend/yuxi/modules/system/static/info.template.yaml
#      （若存在 info.local.yaml 会覆盖模板，必须一并改）
#   B. 位图 —— 登录页背景 frontend/public/login-bg.jpg 内的旧名艺术字。
#      上游已移除该文件，但旧部署的服务器上仍留有副本；只要文件还在、
#      且 login_bg 仍指向它，就会继续显示旧字样。
#
# 用法：bash update_brand.sh
set -euo pipefail

YUXI_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$YUXI_DIR"
COMPOSE="docker compose --profile container"
APP_FILES="-f docker-compose.yml -f deploy/server-app.override.yml"
STAMP=$(date +%Y%m%d-%H%M%S)
OLD_NAME="语析"          # 旧品牌名
NEW_NAME="XWork"        # 新品牌名

echo "==> 1/5 盘点品牌相关文件"
echo "  --- 品牌配置目录"
ls -la backend/yuxi/modules/system/static/ 2>/dev/null || true

echo "  --- 前端 public 下的位图（逐个确认是否含旧字样）"
find frontend/public -maxdepth 2 -type f \( -name "*.jpg" -o -name "*.jpeg" -o -name "*.png" -o -name "*.webp" -o -name "*.svg" \) 2>/dev/null | while read -r f; do
  echo "    $f ($(stat -c%s "$f") bytes)"
done

echo
echo "==> 2/5 处理登录页背景位图残留"
BG="frontend/public/login-bg.jpg"
if [ -f "$BG" ]; then
  echo "  发现残留位图 $BG（含旧名艺术字）"
  mkdir -p "backup/$STAMP"
  cp "$BG" "backup/$STAMP/login-bg.jpg"
  echo "  已备份到 backup/$STAMP/login-bg.jpg"
  # 上游已改用内置山茶折枝 SVG 替代该图，直接移除即可回退到内置背景。
  # 若要保留该图但去掉字样，请把图片发出来单独处理。
  rm -f "$BG"
  echo "  已移除（登录页将回退到内置山茶折枝 SVG）"
else
  echo "  ✓ 无残留位图"
fi

echo
echo "==> 3/5 更新品牌配置（文本）"
for cfg in backend/yuxi/modules/system/static/info.template.yaml \
           backend/yuxi/modules/system/static/info.local.yaml; do
  if [ -f "$cfg" ]; then
    if grep -q "${OLD_NAME}" "$cfg"; then
      sed -i "s/${OLD_NAME}/${NEW_NAME}/g" "$cfg"
      echo "  ✓ 已更新 $cfg"
      grep -n "name:\|copyright:" "$cfg" | head -3
    else
      echo "  - $cfg 无需改动（已是 ${NEW_NAME} 或无旧名）"
    fi
  fi
done

echo
echo "==> 4/5 重启 api 与 frontend"
${COMPOSE} ${APP_FILES} up -d --force-recreate api frontend

echo
echo "==> 5/5 验证"
sleep 6
echo "  --- 品牌接口"
curl -fsS http://127.0.0.1:5050/api/system/info || echo "  警告：接口未响应"
echo
echo
echo "完成。请在浏览器强制刷新（Ctrl+F5 / 手机下拉刷新）。"
echo "若登录页仍显示旧背景图，说明服务器上还有其他位图残留，"
echo "请把上面第 1 步列出的图片逐个打开确认。"

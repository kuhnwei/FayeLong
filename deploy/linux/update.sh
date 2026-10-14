#!/usr/bin/env bash
# ============================================================
# FayeLong · 就地更新脚本（与本地 v1.11「就地更新」理念一致）
#
#   只替换「代码」，绝不触碰 /opt/fayelong/data（学习数据 100% 保留）。
#   用法（root）：
#       bash update.sh <含 backend/ 与 frontend/dist/ 的目录>
#       bash update.sh            # 默认用当前目录
#
#   流程：备份旧代码 → 原子替换 backend/ 与 frontend/dist/ → 同步依赖 → 重启
#   回滚：脚本结尾会打印一条可直接粘贴的回滚命令
# ============================================================
set -euo pipefail

APP_ROOT="/opt/fayelong"
PYPI_MIRROR="https://mirrors.aliyun.com/pypi/simple/"
SRC="${1:-$(pwd)}"
STAMP="$(date +%Y%m%d-%H%M%S)"

[ "$(id -u)" = 0 ] || { echo "请以 root 运行"; exit 1; }
[ -f "$SRC/backend/requirements.txt" ] || { echo "[ERROR] 源目录缺少 backend/：$SRC"; exit 1; }
[ -f "$SRC/frontend/dist/index.html" ] || { echo "[ERROR] 源目录缺少 frontend/dist/：$SRC"; exit 1; }

echo "==> 备份当前代码 → $APP_ROOT/.backup/*-$STAMP"
mkdir -p "$APP_ROOT/.backup"
cp -a "$APP_ROOT/backend" "$APP_ROOT/.backup/backend-$STAMP"
[ -d "$APP_ROOT/frontend/dist" ] && cp -a "$APP_ROOT/frontend/dist" "$APP_ROOT/.backup/dist-$STAMP"

echo "==> 暂存新代码"
rm -rf "$APP_ROOT/backend.new" "$APP_ROOT/frontend/dist.new"
cp -a "$SRC/backend" "$APP_ROOT/backend.new"
cp -a "$SRC/frontend/dist" "$APP_ROOT/frontend/dist.new"
rm -rf "$APP_ROOT/backend.new/.venv" "$APP_ROOT/backend.new/__pycache__"

echo "==> 原子替换（data/ 不在替换范围内）"
rm -rf "$APP_ROOT/backend" "$APP_ROOT/frontend/dist"
mv "$APP_ROOT/backend.new" "$APP_ROOT/backend"
mv "$APP_ROOT/frontend/dist.new" "$APP_ROOT/frontend/dist"

echo "==> 同步依赖（requirements 有变化时才真正安装）"
"$APP_ROOT/venv/bin/pip" install -q -i "$PYPI_MIRROR" \
	-r "$APP_ROOT/backend/requirements.txt" \
	-r "$APP_ROOT/backend/requirements-ml.txt"

echo "==> 重启服务"
systemctl restart fayelong
sleep 3
systemctl is-active fayelong
curl -s -o /dev/null -w "  health -> %{http_code}\n" --max-time 15 http://127.0.0.1:8000/api/health || true

echo
echo "完成。如需回滚到本次更新前，执行："
echo "  rm -rf $APP_ROOT/backend $APP_ROOT/frontend/dist \\"
echo "    && mv $APP_ROOT/.backup/backend-$STAMP $APP_ROOT/backend \\"
echo "    && cp -a $APP_ROOT/.backup/dist-$STAMP $APP_ROOT/frontend/dist \\"
echo "    && systemctl restart fayelong"

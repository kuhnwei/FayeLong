#!/usr/bin/env bash
# ============================================================
# FayeLong · Linux 部署脚本（Ubuntu 24.04 / Python 3.12）
#
#   幂等：可反复执行，已完成的步骤自动跳过。
#   用法（root）：
#       bash install.sh            # 全流程（等价于 all）
#       bash install.sh env        # 建目录 + 虚拟环境 + 装依赖
#       bash install.sh models     # 下载 whisper 模型（small/base）
#       bash install.sh dict       # 下载 ECDICT 词库
#       bash install.sh service    # 安装并启动 systemd 服务
#       bash install.sh caddy      # 配置 Caddy 反代 + 健康检查
#
#   前置：代码已就位于 /opt/fayelong/backend 与 /opt/fayelong/frontend/dist
# ============================================================
set -euo pipefail

APP_ROOT="/opt/fayelong"
PYPI_MIRROR="https://mirrors.aliyun.com/pypi/simple/"
PY="$APP_ROOT/venv/bin/python"
PIP="$APP_ROOT/venv/bin/pip"
MODELS="${FAYELONG_MODELS:-small base}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

c_blue=$'\033[1;34m'; c_red=$'\033[1;31m'; c_off=$'\033[0m'
step(){ printf '\n%s==> %s%s\n' "$c_blue" "$*" "$c_off"; }
die(){ printf '\n%s[ERROR] %s%s\n' "$c_red" "$*" "$c_off" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "请以 root 运行：sudo bash install.sh"

check_code(){
	step "检查代码目录"
	[ -f "$APP_ROOT/backend/requirements.txt" ] || die "缺少 $APP_ROOT/backend/requirements.txt"
	[ -f "$APP_ROOT/frontend/dist/index.html" ] || die "缺少 $APP_ROOT/frontend/dist/index.html"
	echo "  backend   : $(find "$APP_ROOT/backend/app" -name '*.py' | wc -l) 个 .py"
	echo "  frontend  : $APP_ROOT/frontend/dist（$(du -sh "$APP_ROOT/frontend/dist" | cut -f1)）"
}

ensure_dirs(){
	step "创建目录结构"
	mkdir -p "$APP_ROOT"/{backend,frontend,data}
	mkdir -p "$APP_ROOT"/data/{dict,logs,models,media/audio,media/library}
	mkdir -p /var/log/fayelong
	echo "  数据根：$APP_ROOT/data"
}

ensure_venv(){
	step "创建 Python 虚拟环境"
	if [ ! -x "$PY" ]; then
		python3 -c 'import ensurepip' 2>/dev/null || {
			echo "  缺少 venv/ensurepip，安装 python3.12-venv …"
			apt-get update -qq && apt-get install -y -qq python3.12-venv
		}
		python3 -m venv "$APP_ROOT/venv" || die "venv 创建失败（先 apt-get install -y python3.12-venv）"
	fi
	"$PIP" install --upgrade pip -q -i "$PYPI_MIRROR"
	"$PY" -V
}

install_deps(){
	step "安装 Python 依赖（阿里云 PyPI 源）"
	"$PIP" install -i "$PYPI_MIRROR" -r "$APP_ROOT/backend/requirements.txt"
	"$PIP" install -i "$PYPI_MIRROR" -r "$APP_ROOT/backend/requirements-ml.txt"

	step "验收关键依赖 import"
	"$PY" - <<'PYEOF'
import importlib, sys
mods = ["fastapi","uvicorn","sqlalchemy","pydantic_settings","multipart",
        "faster_whisper","ctranslate2","huggingface_hub","onnxruntime","numpy","lemminflect"]
bad = []
for m in mods:
    try:
        mod = importlib.import_module(m)
        print(f"  OK   {m:18s} {getattr(mod, '__version__', '')}")
    except Exception as e:
        bad.append(m); print(f"  FAIL {m:18s} {e}")
print("结果：", "全部通过" if not bad else f"{len(bad)} 个失败")
sys.exit(1 if bad else 0)
PYEOF
}

fetch_models(){
	step "下载 whisper 模型：$MODELS（镜像 hf-mirror.com）"
	for m in $MODELS; do
		"$PY" - "$m" <<'PYEOF'
import sys
sys.path.insert(0, "/opt/fayelong/backend")
from app.services.asr import download_model, model_ready, whisper_model_dir
m = sys.argv[1]
d = whisper_model_dir(m)
if model_ready(m):
    print(f"  已就绪：{d}")
else:
    print(f"  开始下载 {m} -> {d}")
    download_model(model=m)
    print(f"  完成：{d}")
PYEOF
	done
	du -sh "$APP_ROOT"/data/models/* 2>/dev/null || true
}

fetch_dict(){
	step "下载 ECDICT 词库（约 28 万词条 / ~800MB）"
	cd "$APP_ROOT/backend"
	"$PY" scripts/fetch_dict.py
	ls -la "$APP_ROOT/data/dict/"
}

install_service(){
	step "安装 systemd 服务（web + worker 两个 unit）"
	install -m 644 "$HERE/fayelong.service" /etc/systemd/system/fayelong.service
	# P3-2：任务是**独立进程**执行的。web 侧是 FAYELONG_WEB_INPROC_WORKER=off，
	# 少了这个 unit 就没人消费 jobs → 所有素材永远停在「排队中」。
	install -m 644 "$HERE/fayelong-worker.service" /etc/systemd/system/fayelong-worker.service
	systemctl daemon-reload
	systemctl enable fayelong fayelong-worker
	# 顺序：先 web（提供 API，用户先能打开页面）再 worker（开始消费任务）。
	# 反过来也安全 —— off 模式下 web 不干活，worker 先起只会更早开始处理积压任务。
	systemctl restart fayelong
	systemctl restart fayelong-worker
	sleep 4
	systemctl --no-pager status fayelong | head -14
	systemctl --no-pager status fayelong-worker | head -14
}

install_caddy(){
	step "配置 Caddy 反向代理（保留 :80 站点）"
	command -v caddy >/dev/null || die "未找到 caddy"
	if [ -f /etc/caddy/Caddyfile ]; then
		cp -a /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.$(date +%s)"
	fi
	install -m 644 "$HERE/Caddyfile.site" /etc/caddy/Caddyfile
	caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile || die "Caddyfile 校验失败"
	systemctl reload caddy
	systemctl is-active caddy
}

health_check(){
	step "本地健康检查"
	sleep 1
	curl -s -o /dev/null -w "  backend 127.0.0.1:8000/api/health -> %{http_code}\n" --max-time 15 http://127.0.0.1:8000/api/health || true
	curl -s -o /dev/null -w "  caddy   :80/                     -> %{http_code}\n" --max-time 15 http://127.0.0.1/ || true
}

target="${1:-all}"
case "$target" in
	env)     check_code; ensure_dirs; ensure_venv; install_deps ;;
	models)  fetch_models ;;
	dict)    fetch_dict ;;
	service) install_service; health_check ;;
	caddy)   install_caddy; health_check ;;
	all)     check_code; ensure_dirs; ensure_venv; install_deps
	         fetch_models; fetch_dict; install_service; install_caddy; health_check ;;
	*)       die "未知参数：$target（env|models|dict|service|caddy|all）" ;;
esac
step "完成：$target"

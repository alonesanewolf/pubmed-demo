#!/usr/bin/env bash
# ============================================================
# PubMed 领域分析 Demo —— 腾讯云服务器 部署 / 更新 / 回滚
#
# 目标机：Ubuntu 22.04（2C/2G）。机器上已有服务：
#   nginx:80(入口) / AI助手:8080 / NetSec:5100 / Brain:5200 /
#   MySQL:3306 / Redis:6379  —— 本脚本对它们零改动。
#
# 用法（root，在服务器上执行）：
#   bash deploy/deploy.sh              部署或更新（幂等，可反复执行）
#   bash deploy/deploy.sh rollback     卸载本 demo（停服+摘 nginx，不动其他服务）
#   FORCE_BUILD=1 bash deploy/deploy.sh   强制在服务器上重新构建前端
#
# 设计原则（面试可以直接讲这四条）：
#   1) 只新增不修改：nginx 用独立 conf 文件 + reload，绝不编辑现有 server 块
#   2) 服务自包含：独立 systemd 单元 / 独立 venv / 独立数据目录，卸载无残留
#   3) 部署即验证：装完自动健康检查 + 连通性探测，任一步失败立即停
#   4) 数据不覆盖：服务器上的 presets / journals.json 不会被代码部署冲掉
# ============================================================
set -euo pipefail

# ---------------- 可调参数（都可用环境变量覆盖）----------------
INSTALL_DIR="${INSTALL_DIR:-/opt/pubmed-demo}"
APP_USER="${APP_USER:-pubmed}"
APP_PORT="${APP_PORT:-8000}"            # uvicorn，只绑 127.0.0.1
PUBLIC_PORT="${PUBLIC_PORT:-5300}"      # nginx 对外端口
SERVICE_NAME="${SERVICE_NAME:-pubmed-demo}"
MEM_MAX="${MEM_MAX:-512M}"              # 本服务内存硬上限（2G 机器）
NPM_MIRROR="${NPM_MIRROR:-https://registry.npmmirror.com}"
PIP_MIRROR="${PIP_MIRROR:-https://pypi.tuna.tsinghua.edu.cn/simple}"
# 注意：NGINX_CONF 必须在此定义 —— 下面的 rollback 分支会用到它，
# 而脚本开着 set -u，变量先被引用后定义会直接报错退出。
NGINX_CONF="${NGINX_CONF:-/etc/nginx/conf.d/${SERVICE_NAME}.conf}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"   # deploy/ 的上一级 = pubmed-demo/

say()  { printf '\n\033[1;34m===== %s =====\033[0m\n' "$*"; }
ok()   { printf '  \033[32m[ok]\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m[!]\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m[x] %s\033[0m\n' "$*" >&2; exit 1; }

# ================= 回滚 =================
if [ "${1:-}" = "rollback" ]; then
    say "回滚：停服并摘除 nginx 配置（保留 ${INSTALL_DIR} 下的数据）"
    systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload
    if [ -f "$NGINX_CONF" ]; then
        rm -f "$NGINX_CONF"
        nginx -t && systemctl reload nginx
        ok "nginx 配置已摘除并 reload（其他服务不受影响）"
    fi
    ok "回滚完成。代码与数据仍保留在 ${INSTALL_DIR}，需要的话可整体删除。"
    exit 0
fi

# ================= 0. 部署前检查 =================
say "0/8 部署前检查"
[ "$(id -u)" -eq 0 ] || die "需要 root 权限：sudo bash deploy/deploy.sh"
ok "root 权限确认"

command -v python3 >/dev/null || die "未找到 python3：apt-get install -y python3 python3-venv python3-pip"
PYV="$(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
ok "Python ${PYV}"
case "$PYV" in
  3.10|3.11|3.12) ;;
  *) warn "Python ${PYV} 未经测试（推荐 3.10~3.12，即 Ubuntu 22.04 默认版本）" ;;
esac

command -v nginx >/dev/null || die "未找到 nginx：apt-get install -y nginx"
ok "nginx $(nginx -v 2>&1 | sed 's|.*version: ||' | cut -d/ -f2)"

# 端口占用检查（只警告不阻止，允许覆盖部署）
if ss -ltn 2>/dev/null | grep -q ":${PUBLIC_PORT} "; then
    warn "端口 ${PUBLIC_PORT} 已被占用，若不是本 demo 的旧进程请换 PUBLIC_PORT"
else
    ok "对外端口 ${PUBLIC_PORT} 空闲"
fi
if ss -ltn 2>/dev/null | grep -q "127.0.0.1:${APP_PORT} "; then
    warn "127.0.0.1:${APP_PORT} 已被占用（可能是本 demo 旧进程，将直接覆盖）"
fi

FREE_MB="$(free -m | awk '/^Mem:/{print $7}')"
if [ "${FREE_MB:-0}" -lt 300 ]; then
    warn "可用内存仅 ${FREE_MB}MB，注意同机其他服务"
else
    ok "可用内存 ${FREE_MB}MB"
fi
DISK_AVAIL="$(df -m / | awk 'NR==2{print $4}')"
if [ "${DISK_AVAIL:-0}" -lt 1024 ]; then
    die "根分区可用不足 1GB"
else
    ok "磁盘可用 ${DISK_AVAIL}MB"
fi

# ================= 1. 目录与用户 =================
say "1/8 创建安装目录与运行用户"
mkdir -p "${INSTALL_DIR}"/{backend/data/presets,backend/data/cache,backend/data/backups,frontend/dist,logs}
if ! id "$APP_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$APP_USER"
    ok "已创建系统用户 ${APP_USER}（无登录 shell）"
else
    ok "用户 ${APP_USER} 已存在"
fi

# ================= 2. 同步后端代码 =================
say "2/8 同步后端代码"
# 常见拓扑：tar 包解开在 /opt/pubmed-demo，就地部署 —— 此时源码目录就是
# 安装目录。若还做 tar 自拷贝，会触发 "file changed as we read it" 警告，
# tar 返回 1，被 set -o pipefail + set -e 当场杀掉（实测踩过）。
# 所以同目录时直接跳过同步。
if [ "$PROJECT_DIR" = "$INSTALL_DIR" ]; then
    ok "源码目录即安装目录（${INSTALL_DIR}），跳过同步"
else
    # 排除项：venv（服务器自建）/ __pycache__ / .env（服务器上的密钥不被覆盖）
    tar -C "${PROJECT_DIR}/backend" \
        --exclude=venv --exclude=__pycache__ --exclude='*.pyc' --exclude=.env \
        -cf - . | tar -C "${INSTALL_DIR}/backend" -xf -
    ok "backend/ 已同步（不含 venv 与 .env）"
fi

# journals.json：异地部署时，服务器可能通过「导入期刊表」接口更新过，
# 先备份再用项目版覆盖；就地部署（源码目录=安装目录）时两者是同一个
# 文件，cp 会报 "are the same file" 并被 set -e 杀掉，所以整段跳过。
if [ "$PROJECT_DIR" != "$INSTALL_DIR" ]; then
    if [ -f "${INSTALL_DIR}/backend/data/journals.json" ]; then
        cp "${INSTALL_DIR}/backend/data/journals.json" \
           "${INSTALL_DIR}/backend/data/backups/journals.$(date +%Y%m%d%H%M%S).json"
        ok "服务器端 journals.json 已备份到 data/backups/"
    fi
    if [ -f "${PROJECT_DIR}/backend/data/journals.json" ]; then
        cp "${PROJECT_DIR}/backend/data/journals.json" "${INSTALL_DIR}/backend/data/journals.json"
    fi
fi

# presets：只增不覆盖（抓取产物由人工 scp 管理，见 DEPLOY.md §数据采集）
ADDED=0; KEPT=0
for f in "${PROJECT_DIR}"/backend/data/presets/*.json; do
    [ -e "$f" ] || continue
    if [ -e "${INSTALL_DIR}/backend/data/presets/$(basename "$f")" ]; then
        KEPT=$((KEPT+1))
    else
        cp "$f" "${INSTALL_DIR}/backend/data/presets/"
        ADDED=$((ADDED+1))
    fi
done
ok "预置数据集：新增 ${ADDED} 个，服务器已有保留 ${KEPT} 个"

PRESET_TOTAL="$(find "${INSTALL_DIR}/backend/data/presets" -name '*.json' | wc -l)"
if [ "$PRESET_TOTAL" -eq 0 ]; then
    warn "服务器上没有任何预置数据集！演示前必须先抓取（DEPLOY.md §数据采集）"
else
    ok "服务器现有预置数据集 ${PRESET_TOTAL} 个"
fi

# ================= 3. Python 依赖 =================
say "3/8 安装 Python 依赖（venv）"
VENV="${INSTALL_DIR}/backend/venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip -q || true
if ! "$VENV/bin/pip" install --no-cache-dir -q -r "${INSTALL_DIR}/backend/requirements.txt"; then
    warn "默认 PyPI 源失败，切换清华镜像重试"
    "$VENV/bin/pip" install --no-cache-dir -q \
        -i "$PIP_MIRROR" -r "${INSTALL_DIR}/backend/requirements.txt"
fi
"$VENV/bin/python" -c "import fastapi, uvicorn, httpx, numpy; print('  deps ok:', fastapi.__version__)"
ok "依赖安装完成"

# ================= 4. 前端产物 =================
say "4/8 部署前端产物"
FRONTEND_DST="${INSTALL_DIR}/frontend"
# 4a. 同步源码（不含 node_modules / dist / .env），方便需要时在服务器上构建
if [ "$PROJECT_DIR" != "$INSTALL_DIR" ]; then
    tar -C "${PROJECT_DIR}/frontend" \
        --exclude=node_modules --exclude=dist --exclude=.env --exclude='*.local' \
        -cf - . | tar -C "$FRONTEND_DST" -xf -
fi
# 4b. 同步随包发布的 dist（本机构建产物）—— 同目录时同样跳过
if [ "$PROJECT_DIR" != "$INSTALL_DIR" ] && [ -d "${PROJECT_DIR}/frontend/dist" ]; then
    tar -C "${PROJECT_DIR}/frontend/dist" -cf - . | tar -C "${FRONTEND_DST}/dist" -xf -
    ok "已同步本地构建的 dist/"
fi

dist_status() {   # 输出 ok / mock_on / missing
    local f any=0 bad=0
    for f in "$FRONTEND_DST"/dist/assets/*.js; do
        [ -e "$f" ] || { echo missing; return; }
        any=1
        grep -qE 'VITE_USE_MOCK:[[:space:]]*"true"' "$f" && bad=1
    done
    [ "$any" = 1 ] || { echo missing; return; }
    [ "$bad" = 1 ] && echo mock_on || echo ok
}

ST="$(dist_status)"
if [ "$ST" = "mock_on" ]; then
    warn "随包发布的 dist 是 Mock 构建（VITE_USE_MOCK=true）——上线会全程假数据，强制重新构建"
    FORCE_BUILD=1
fi

if [ "${FORCE_BUILD:-0}" = "1" ] || [ "$ST" = "missing" ]; then
    command -v node >/dev/null 2>&1 || die \
        "服务器上没有 node，无法构建。请在本机执行：cd frontend; \$env:VITE_USE_MOCK='false'; npm run build，然后重跑本脚本"
    cd "$FRONTEND_DST"
    # .env.production 优先级高于 .env，确保构建关闭 mock
    printf 'VITE_USE_MOCK=false\nVITE_MOCK_FALLBACK=false\n' > .env.production
    if ! npm ci --no-audit --no-fund -q; then
        warn "默认 npm 源失败，切换 npmmirror 重试"
        npm ci --no-audit --no-fund -q --registry "$NPM_MIRROR"
    fi
    npm run build
    [ "$(dist_status)" = "ok" ] || die "构建结果校验失败：产物仍是 Mock 构建"
    ok "前端已在服务器上重新构建（mock 已关闭）"
else
    ok "使用随包发布的前端产物（已校验：非 Mock 构建）"
fi

# ================= 5. 环境变量文件 =================
say "5/8 环境变量"
if [ ! -f "${INSTALL_DIR}/backend/.env" ]; then
    cp "${INSTALL_DIR}/backend/.env.example" "${INSTALL_DIR}/backend/.env"
    warn "已从 example 生成 .env —— 请填入 DEEPSEEK_API_KEY（NCBI_API_KEY 仅采集需要）"
else
    ok ".env 已存在（密钥不会被覆盖）"
fi
chmod 600 "${INSTALL_DIR}/backend/.env"
if grep -qE '^[[:space:]]*DATA_MODE[[:space:]]*=[[:space:]]*(remote|hybrid)' "${INSTALL_DIR}/backend/.env"; then
    warn ".env 中 DATA_MODE=remote/hybrid，但服务器连不上 NCBI，建议改回 local"
fi
chown -R "${APP_USER}:${APP_USER}" "$INSTALL_DIR"
ok "目录归属已切到 ${APP_USER}"

# ================= 6. nginx =================
say "6/8 安装 nginx 配置（只新增，reload 不 restart）"
if [ -f "$NGINX_CONF" ]; then
    cp "$NGINX_CONF" "${NGINX_CONF}.bak.$(date +%Y%m%d%H%M%S)"
    ok "已备份现有 ${NGINX_CONF}"
fi
sed -e "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
    -e "s|__APP_PORT__|${APP_PORT}|g" \
    -e "s|__PUBLIC_PORT__|${PUBLIC_PORT}|g" \
    "${SCRIPT_DIR}/pubmed-demo.conf" > "${NGINX_CONF}"
if ! nginx -t 2>&1; then
    # 配置有问题：恢复备份（没有备份就删掉刚写的），绝不让坏配置生效。
    # 注意 ls|head 在 set -o pipefail 下可能返回非零，必须 || true 兜底。
    BACKUP="$(ls -1t "${NGINX_CONF}".bak.* 2>/dev/null | head -1 || true)"
    if [ -n "$BACKUP" ]; then
        cp "$BACKUP" "$NGINX_CONF"
        ok "已恢复备份 ${BACKUP}"
    else
        rm -f "$NGINX_CONF"
    fi
    die "nginx -t 未通过，已恢复原配置。请检查 ${NGINX_CONF}"
fi
systemctl reload nginx     # reload 是平滑的，不断现有连接；绝不用 restart
ok "nginx 配置已生效：${PUBLIC_PORT} -> 127.0.0.1:${APP_PORT}"

if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    ufw allow "${PUBLIC_PORT}/tcp" >/dev/null && ok "ufw 已放行 ${PUBLIC_PORT}/tcp"
else
    warn "ufw 未启用（或未安装），跳过防火墙配置"
fi

# ================= 7. systemd =================
say "7/8 安装 systemd 服务"
sed -e "s|__INSTALL_DIR__|${INSTALL_DIR}|g" \
    -e "s|__APP_PORT__|${APP_PORT}|g" \
    -e "s|__MEM_MAX__|${MEM_MAX}|g" \
    -e "s|__APP_USER__|${APP_USER}|g" \
    "${SCRIPT_DIR}/pubmed-demo.service" > "/etc/systemd/system/${SERVICE_NAME}.service"
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
ok "服务已启动并设为开机自启"

# ================= 8. 健康检查 =================
say "8/8 健康检查"
HEALTH=""
for _ in $(seq 1 30); do
    HEALTH="$(curl -s --max-time 3 "http://127.0.0.1:${APP_PORT}/api/health" || true)"
    [ -n "$HEALTH" ] && break
    sleep 1
done
[ -n "$HEALTH" ] || die "服务 30 秒内无响应。查看日志：journalctl -u ${SERVICE_NAME} -n 50 --no-pager"
echo "  /api/health -> ${HEALTH}"

echo "$HEALTH" | grep -q '"data_mode": *"local"' && ok "数据模式 local（只读预置数据，不碰外网）" \
    || warn "数据模式不是 local，演示前请确认"

# 连通性探测：提前暴露「服务器能不能连 NCBI」，别等演示当天才发现
PROBE="$(curl -s --max-time 40 "http://127.0.0.1:${APP_PORT}/api/admin/connectivity" || true)"
echo "  /api/admin/connectivity -> ${PROBE:-<无响应，40s 超时属正常：说明出网被拦>}"

say "部署完成"
SERVER_IP="$(curl -s --max-time 5 ifconfig.me || hostname -I | awk '{print $1}')"
cat <<EOF

  演示地址    http://${SERVER_IP}:${PUBLIC_PORT}/
  接口文档    http://${SERVER_IP}:${PUBLIC_PORT}/docs
  本机健康检查 curl -s http://127.0.0.1:${APP_PORT}/api/health

  常用命令
    查看日志   journalctl -u ${SERVICE_NAME} -f
    重启服务   systemctl restart ${SERVICE_NAME}
    重载 nginx nginx -t && systemctl reload nginx
    更新部署   bash ${INSTALL_DIR}/deploy/deploy.sh
    卸载回滚   bash ${INSTALL_DIR}/deploy/deploy.sh rollback

  TODO（部署不会替你做）
    1. 腾讯云控制台 -> 防火墙 -> 放行 ${PUBLIC_PORT}/tcp（否则外网打不开）
    2. 编辑 ${INSTALL_DIR}/backend/.env 填入 DEEPSEEK_API_KEY（不填则 AI 综述自动降级）
    3. 预置数据集为空的话，先按 DEPLOY.md §数据采集 抓取后 scp 上来
EOF

#!/usr/bin/env bash
# ==============================================================================
# Setup Script: xworkmate-bridge + AI Workspace (极简引导安装器)
#
# 架构定位：
#   [xworkmate-bridge] (:8787)
#          │ (HTTP Ingest & Agent API :8181)
#          ▼
#   [QMD Server (QMD_BACKEND=pg)] (:8181)
#          │ (SQL TCP :5432)
#          ▼
#   [PostgreSQL + pgvector] (:15432)
#
# 核心特性：
#   * 默认零参数运行：自动 All-in-One 部署全套 Bridge + QMD + PGvector 三层堆栈
#   * 最大程度调度 GitOps 配置 (ai-workspace-infra/gitops) 与 Playbook Roles
#   * 安全红线：内存机密生成、不落盘、不写入日志、退出即 unset、单次卡片高亮输出
# ==============================================================================

set -euo pipefail
set +x # 严禁开启跟踪，杜绝敏感变量进入日志

MODE="all-in-one"     # all-in-one, intranet, https, standalone
DEPLOY_TARGET="full"  # full, bridge-only
DOMAIN=""
ACME_EMAIL="ops@example.com"
LISTEN_IP="127.0.0.1"
BRIDGE_PORT="${BRIDGE_PORT:-8787}"
QMD_PORT="${QMD_PORT:-8181}"
PG_PORT="${PG_PORT:-15432}"
BASE_DIR="${HOME}/.xworkmate-workspace"
DATA_DIR="${DATA_DIR:-${BASE_DIR}/data}"

# 上游 QMD 连接 (standalone 模式使用)
QMD_API_URL="${BRIDGE_QMD_INGEST_API_URL:-http://127.0.0.1:8181/api/v1/agent/ingest}"

# GitOps 编排源
GITOPS_WORKSPACE_COMPOSE_URL="https://raw.githubusercontent.com/ai-workspace-infra/gitops/main/compose/xworkmate-workspace/docker-compose.yml"

usage() {
  local exit_code="${1:-0}"
  cat <<'EOF'
使用方法:
  # 默认一键 All-in-One 全栈部署 (Bridge + QMD + PostgreSQL + pgvector):
  curl -fsSL https://raw.githubusercontent.com/ai-workspace-infra/platform-ops-toolkit/main/scripts/setup-xworkmate-workspace.sh | bash

高级参数配置模式:
  --mode <all-in-one|intranet|https>  运行模式 (默认: all-in-one)
  --domain <domain.com>               公网 HTTPS 模式解析域名 (mode=https 时必填)
  --email <email>                     Caddy TLS 证书通知邮箱 (默认: ops@example.com)
  --listen-ip <ip>                    指定监听 IP (内网模式默认: 0.0.0.0, 默认模式: 127.0.0.1)
  --bridge-port <port>                Bridge 外部监听端口 (默认: 8787)
  --qmd-port <port>                   QMD 外部监听端口 (默认: 8181)
  --pg-port <port>                    PostgreSQL 外部监听端口 (默认: 15432)
  --standalone, --bridge-only         仅部署 Bridge 节点，级联外部已有 QMD
  --qmd-url <url>                     外部 QMD Ingest 端点 (--standalone 时使用)
  --data-dir <path>                   数据存储根目录 (默认: ~/.xworkmate-workspace/data)
  -h, --help                          显示帮助信息

环境变量注入规范 (托管/团队节点，由 Vault / KMS 注入，不落盘):
  AI_WORKSPACE_AUTH_TOKEN             Bridge 认证 Token (未指定则内存自动生成)
  POSTGRES_PASSWORD                   PostgreSQL 管理员口令
  QMD_INGEST_TOKEN                    QMD 数据摄入 Token
  QMD_MCP_TOKEN                       QMD MCP 协议令牌
EOF
  exit "${exit_code}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; MODE="https"; shift 2 ;;
    --email) ACME_EMAIL="$2"; shift 2 ;;
    --listen-ip) LISTEN_IP="$2"; shift 2 ;;
    --bridge-port|--port) BRIDGE_PORT="$2"; shift 2 ;;
    --qmd-port) QMD_PORT="$2"; shift 2 ;;
    --pg-port) PG_PORT="$2"; shift 2 ;;
    --standalone|--bridge-only) DEPLOY_TARGET="bridge-only"; shift 1 ;;
    --qmd-url) QMD_API_URL="$2"; DEPLOY_TARGET="bridge-only"; shift 2 ;;
    --data-dir) DATA_DIR="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "错误: 未知参数 $1" >&2; usage 1 ;;
  esac
done

# ------------------------------------------------------------------------------
# 1. 内存机密生成与清理钩子 (零落地)
# ------------------------------------------------------------------------------
_gen_secret() {
  openssl rand -hex "$1" 2>/dev/null || head -c "$1" /dev/urandom | xxd -p | tr -d '\n'
}

AI_WORKSPACE_AUTH_TOKEN="${AI_WORKSPACE_AUTH_TOKEN:-$(_gen_secret 24)}"
POSTGRES_DB="${POSTGRES_DB:-postgres}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(_gen_secret 16)}"
QMD_INGEST_TOKEN="${QMD_INGEST_TOKEN:-$(_gen_secret 24)}"
QMD_MCP_TOKEN="${QMD_MCP_TOKEN:-$(_gen_secret 24)}"

cleanup_secrets() {
  unset AI_WORKSPACE_AUTH_TOKEN POSTGRES_PASSWORD QMD_INGEST_TOKEN QMD_MCP_TOKEN
}
trap cleanup_secrets EXIT

# ------------------------------------------------------------------------------
# 2. 检查 Docker 运行时与端口冲突平滑规避
# ------------------------------------------------------------------------------
echo "==> [1/4] 检查 Docker 运行时环境 (部署目标: ${DEPLOY_TARGET}, 模式: ${MODE})..."
command -v docker >/dev/null 2>&1 || { echo "错误: 未检测到 Docker 守护进程，请先安装 Docker 或 OrbStack" >&2; exit 1; }

COMPOSE_CMD="docker compose"
docker compose version >/dev/null 2>&1 || COMPOSE_CMD="docker-compose"

if [[ "$MODE" == "https" ]]; then
  [[ -z "$DOMAIN" ]] && { echo "错误: https 模式必须指定 --domain 参数" >&2; exit 1; }
  LISTEN_IP="0.0.0.0"
elif [[ "$MODE" == "intranet" && "$LISTEN_IP" == "127.0.0.1" ]]; then
  LISTEN_IP="0.0.0.0"
fi

_port_in_use() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -Pi :"$1" -sTCP:LISTEN -t >/dev/null 2>&1
  elif command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$1" 2>/dev/null
  else
    return 1
  fi
}

_container_owns_port() {
  docker port "$1" 2>/dev/null | grep -q ":$2$"
}

# 端口冲突平滑顺延（宿主机既有容器或服务占用时自动 fallback）
if [[ "$MODE" != "https" ]]; then
  if _port_in_use "${PG_PORT}"; then
    if ! _container_owns_port "workspace-postgresql" "${PG_PORT}"; then
      echo "==> 提示: 端口 ${PG_PORT} 已被其他进程占用，自动切换为备用端口 $((PG_PORT + 1))..."
      PG_PORT=$((PG_PORT + 1))
    fi
  fi
  if _port_in_use "${BRIDGE_PORT}"; then
    if ! _container_owns_port "workspace-bridge" "${BRIDGE_PORT}"; then
      echo "==> 提示: 端口 ${BRIDGE_PORT} 已被其他进程占用，自动切换为备用端口 $((BRIDGE_PORT + 10000))..."
      BRIDGE_PORT=$((BRIDGE_PORT + 10000))
    fi
  fi
  if _port_in_use "${QMD_PORT}"; then
    if ! _container_owns_port "workspace-qmd" "${QMD_PORT}"; then
      echo "==> 提示: 端口 ${QMD_PORT} 已被其他进程占用，自动切换为备用端口 $((QMD_PORT + 10000))..."
      QMD_PORT=$((QMD_PORT + 10000))
    fi
  fi
fi

# ------------------------------------------------------------------------------
# 3. 同步 GitOps 标准编排拓扑与目录准备
# ------------------------------------------------------------------------------
echo "==> [2/4] 初始化工作目录与 GitOps 编排声明: ${BASE_DIR}..."
mkdir -p "${BASE_DIR}" "${DATA_DIR}/pgdata" "${DATA_DIR}/qmd_models" "${DATA_DIR}/qmd_storage" "${DATA_DIR}/caddy_data" "${DATA_DIR}/caddy_config"
chmod 700 "${BASE_DIR}"

COMPOSE_FILE="${BASE_DIR}/docker-compose.yml"

# 优先拉取 GitOps 权威编排；若处于本地仓库工作树则直接复用
LOCAL_GITOPS_COMPOSE="$(dirname "$0")/../../gitops/compose/xworkmate-workspace/docker-compose.yml"
if [[ -f "${LOCAL_GITOPS_COMPOSE}" ]]; then
  cp "${LOCAL_GITOPS_COMPOSE}" "${COMPOSE_FILE}"
elif ! curl -fsSL "${GITOPS_WORKSPACE_COMPOSE_URL}" -o "${COMPOSE_FILE}" 2>/dev/null; then
  # 离线或无网连接时的极简内联兜底
  cat > "${COMPOSE_FILE}" <<'EOF'
services:
  postgresql:
    image: ${POSTGRESQL_IMAGE:-postgres-extensions:17}
    pull_policy: ${PULL_POLICY_POSTGRES:-if_not_present}
    container_name: workspace-postgresql
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB:-postgres}
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      PGDATA: /var/lib/postgresql/data/pgdata
    expose:
      - "5432"
    ports:
      - "${LISTEN_IP}:${PG_PORT:-15432}:5432"
    volumes:
      - ${DATA_DIR}/pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres} -d ${POSTGRES_DB:-postgres} -h 127.0.0.1"]
      interval: 5s
      timeout: 5s
      retries: 10
    networks:
      - workspace_net

  qmd:
    image: ${QMD_IMAGE:-ghcr.io/ai-workspace-lab/qmd:v2.8.3}
    pull_policy: ${PULL_POLICY_QMD:-if_not_present}
    container_name: workspace-qmd
    restart: unless-stopped
    environment:
      NODE_ENV: production
      QMD_BACKEND: pg
      QMD_PG_URL: "postgres://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD}@postgresql:5432/${POSTGRES_DB}?sslmode=disable"
      QMD_MCP_HOST: "0.0.0.0"
      QMD_MCP_TOKEN: ${QMD_MCP_TOKEN}
      QMD_INGEST_TOKEN: ${QMD_INGEST_TOKEN}
      QMD_CTX_COLLECT_INTERVAL: "0"
    expose:
      - "8181"
    ports:
      - "${LISTEN_IP}:${QMD_PORT:-8181}:8181"
    volumes:
      - ${DATA_DIR}/qmd_models:/app/models
    depends_on:
      postgresql:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "node", "-e", "require('http').get('http://127.0.0.1:8181/mcp', r => { process.exit(r.statusCode < 500 ? 0 : 1) })"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - workspace_net

  xworkmate-bridge:
    image: ${BRIDGE_IMAGE:-ghcr.io/ai-workspace-lab/xworkmate-bridge:v1.0-beta2}
    pull_policy: ${PULL_POLICY_BRIDGE:-if_not_present}
    container_name: workspace-bridge
    restart: unless-stopped
    environment:
      AI_WORKSPACE_AUTH_TOKEN: ${AI_WORKSPACE_AUTH_TOKEN}
      BRIDGE_AUTH_TOKEN: ${AI_WORKSPACE_AUTH_TOKEN}
      BRIDGE_QMD_INGEST_API_URL: "http://qmd:8181/api/v1/agent/ingest"
      BRIDGE_QMD_INGEST_TOKEN: ${QMD_INGEST_TOKEN}
      BRIDGE_QMD_MCP_TOKEN: ${QMD_MCP_TOKEN}
    expose:
      - "8787"
    ports:
      - "${LISTEN_IP}:${BRIDGE_PORT}:8787"
    depends_on:
      qmd:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f -H \"Authorization: Bearer ${AI_WORKSPACE_AUTH_TOKEN}\" http://127.0.0.1:8787/api/v1/agent/catalog || bash -c 'cat < /dev/null > /dev/tcp/127.0.0.1/8787' || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - workspace_net

networks:
  workspace_net:
    name: docker_workspace_net
    driver: bridge
EOF
fi

# 镜像策略自动探测 (本地镜像存在时自动设为 never，杜绝 GHCR 超时)
IMAGE_POSTGRES="${POSTGRESQL_IMAGE:-postgres-extensions:17}"
IMAGE_QMD="${QMD_IMAGE:-ghcr.io/ai-workspace-lab/qmd:v2.8.3}"
IMAGE_BRIDGE="${BRIDGE_IMAGE:-ghcr.io/ai-workspace-lab/xworkmate-bridge:v1.0-beta2}"
PULL_POLICY_POSTGRES="if_not_present"
PULL_POLICY_QMD="if_not_present"
PULL_POLICY_BRIDGE="if_not_present"

docker image inspect "${IMAGE_POSTGRES}" >/dev/null 2>&1 && PULL_POLICY_POSTGRES="never"
if docker image inspect "${IMAGE_QMD}" >/dev/null 2>&1; then
  PULL_POLICY_QMD="never"
elif docker image inspect "qmd:latest" >/dev/null 2>&1; then
  IMAGE_QMD="qmd:latest"; PULL_POLICY_QMD="never"
fi

if docker image inspect "${IMAGE_BRIDGE}" >/dev/null 2>&1; then
  PULL_POLICY_BRIDGE="never"
elif docker image inspect "xworkmate-bridge:latest" >/dev/null 2>&1; then
  IMAGE_BRIDGE="xworkmate-bridge:latest"; PULL_POLICY_BRIDGE="never"
fi

# ------------------------------------------------------------------------------
# 4. 启动容器拓扑 (零落地启动)
# ------------------------------------------------------------------------------
echo "==> [3/4] 启动 AI Workspace 拓扑容器..."
cd "${BASE_DIR}"

# 上游 QMD 连接
if [[ "$DEPLOY_TARGET" == "bridge-only" ]]; then
  BRIDGE_QMD_TARGET_URL="${QMD_API_URL}"
else
  BRIDGE_QMD_TARGET_URL="http://qmd:8181/api/v1/agent/ingest"
fi

POSTGRESQL_IMAGE="${IMAGE_POSTGRES}" \
QMD_IMAGE="${IMAGE_QMD}" \
BRIDGE_IMAGE="${IMAGE_BRIDGE}" \
PULL_POLICY_POSTGRES="${PULL_POLICY_POSTGRES}" \
PULL_POLICY_QMD="${PULL_POLICY_QMD}" \
PULL_POLICY_BRIDGE="${PULL_POLICY_BRIDGE}" \
POSTGRES_DB="${POSTGRES_DB}" \
POSTGRES_USER="${POSTGRES_USER}" \
POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
QMD_INGEST_TOKEN="${QMD_INGEST_TOKEN}" \
QMD_MCP_TOKEN="${QMD_MCP_TOKEN}" \
AI_WORKSPACE_AUTH_TOKEN="${AI_WORKSPACE_AUTH_TOKEN}" \
BRIDGE_QMD_INGEST_API_URL="${BRIDGE_QMD_TARGET_URL}" \
BRIDGE_QMD_INGEST_TOKEN="${QMD_INGEST_TOKEN}" \
BRIDGE_QMD_MCP_TOKEN="${QMD_MCP_TOKEN}" \
LISTEN_IP="${LISTEN_IP}" \
BRIDGE_PORT="${BRIDGE_PORT}" \
QMD_PORT="${QMD_PORT}" \
PG_PORT="${PG_PORT}" \
DATA_DIR="${DATA_DIR}" \
${COMPOSE_CMD} -f "${COMPOSE_FILE}" up -d --remove-orphans >/dev/null

echo "==> [4/4] 等待健康探针级联就绪..."
MAX_ATTEMPTS=24
ATTEMPT=0
ALL_HEALTHY=false

while [[ $ATTEMPT -lt $MAX_ATTEMPTS ]]; do
  BRIDGE_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' workspace-bridge 2>/dev/null || echo "starting")
  if [[ "$BRIDGE_HEALTH" == "healthy" ]]; then
    ALL_HEALTHY=true
    break
  fi
  sleep 2
  ATTEMPT=$((ATTEMPT + 1))
done

if [[ "$ALL_HEALTHY" != "true" ]]; then
  echo "警告: 部分容器尚未完全进入 healthy 状态，请执行 'docker compose logs' 查看排障信息。" >&2
fi

# ------------------------------------------------------------------------------
# 5. 终端一次性高亮输出凭据 (标准规范卡片)
# ------------------------------------------------------------------------------
if [[ "$MODE" == "https" ]]; then
  CLIENT_URL="https://${DOMAIN}"
elif [[ "$MODE" == "intranet" ]]; then
  LOCAL_IP="${LISTEN_IP}"
  [[ "$LOCAL_IP" == "0.0.0.0" ]] && LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
  CLIENT_URL="http://${LOCAL_IP}:${BRIDGE_PORT}"
else
  CLIENT_URL="http://127.0.0.1:${BRIDGE_PORT}"
fi

C_CYAN='\033[1;36m'
C_GREEN='\033[1;32m'
C_YELLOW='\033[1;33m'
C_RED='\033[1;31m'
C_RESET='\033[0m'

printf "\n"
printf "${C_GREEN}==========================================================================${C_RESET}\n"
printf "${C_GREEN}              XWorkmate Agent Context Stack 部署成功！${C_RESET}\n"
printf "${C_GREEN}==========================================================================${C_RESET}\n"
printf " 部署模式       : ${C_CYAN}%s${C_RESET}\n" "${MODE}"
printf " 服务地址 (URL) : ${C_CYAN}%s${C_RESET}\n" "${CLIENT_URL}"
printf " 认证令牌 (Token): ${C_YELLOW}%s${C_RESET}\n" "${AI_WORKSPACE_AUTH_TOKEN}"
printf "\n"
printf "${C_RED} [安全提示] Token 纯内存生成，未落地写入任何磁盘文件，也未记录到系统日志！${C_RESET}\n"
printf "            请立即将上述 Token 复制并妥善保管（如存入 1Password / Vault）。\n"
printf "\n"
printf "${C_CYAN}📱 【XWorkmate App 客户端连接配置】${C_RESET}\n"
printf "   1. 打开 XWorkmate App -> 菜单点击「设置 (Settings)」\n"
printf "   2. 进入「账户与同步 (Account & Sync)」页面\n"
printf "   3. 在「ACP Bridge Server / 自建 Bridge 服务」中填写：\n"
printf "      • 服务器地址 (URL)  : %s\n" "${CLIENT_URL}"
printf "      • 访问令牌 (Token)   : %s\n" "${AI_WORKSPACE_AUTH_TOKEN}"
printf "   4. 保存连接，侧栏任务列表将自动拉取并聚合 QMD 任务！\n"
printf "\n"
printf "${C_CYAN}🔍 【快速连通性验证】${C_RESET}\n"
printf "   curl -s -H \"Authorization: Bearer %s\" %s/api/v1/agent/catalog | jq .\n" "${AI_WORKSPACE_AUTH_TOKEN}" "${CLIENT_URL}"
printf "${C_GREEN}==========================================================================${C_RESET}\n"
printf "\n"

cleanup_secrets

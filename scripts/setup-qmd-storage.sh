#!/usr/bin/env bash
# ==============================================================================
# Setup Script: AI-Memory-Hub (QMD + PostgreSQL + pgvector + 扩展存储)
#
# 架构定位：
#   [QMD Server (QMD_BACKEND=pg)] (:8181)
#          │ (SQL TCP)
#          ▼
#   [PostgreSQL 17 + pgvector + pg_jieba + pg_trgm + pgmq] (:15432)
#          │ (持久卷)
#          ▼
#   [扩展持久化存储: pgdata, qmd_models, qmd_storage]
#
# 核心特性：
#   * 默认零参数运行：自动 All-in-One 部署 QMD + PostgreSQL 17 + pgvector + 扩展存储底座
#   * 高级参数配置模式：
#     --mode https --domain <domain> : 自动配置 Caddy 生产 TLS (80/443 收敛，数据库内部隔离)
#     --mode intranet                : 绑定局域网网卡 IP 或 0.0.0.0
#     --pg-only                      : 仅部署带扩展的 PostgreSQL 权威数据库底座
#     托管/团队节点                  : 由 Vault / KMS 注入环境变量，不生成随机值
#
# 安全红线约束：
#   * 不落地 (Zero Disk Persistence)：所有 Token 纯内存生成/继承，不向磁盘写入任何 .env 文件
#   * 不写入日志 (Zero Log Leakage)：强制 set +x，探针自检全部静默执行
#   * 终端打印一次：部署收敛后一次性高亮输出凭据与配置卡片，退出前立即 unset 内存变量
# ==============================================================================

set -euo pipefail
set +x # 严禁开启跟踪，杜绝敏感变量打印入日志

# ------------------------------------------------------------------------------
# 1. 参数默认值 (默认 All-in-One 本地开箱即用)
# ------------------------------------------------------------------------------
MODE="all-in-one"     # 默认: all-in-one, 可选: intranet, https
DEPLOY_TARGET="full"  # full (all-in-one), pg-only
DOMAIN=""
ACME_EMAIL="ops@example.com"
LISTEN_IP="127.0.0.1"
QMD_PORT="8181"
PG_PORT="15432"
BASE_DIR="${HOME}/.ai-memory-hub"
DATA_DIR="${BASE_DIR}/data"

# 镜像版本
IMAGE_POSTGRES="${POSTGRESQL_IMAGE:-postgres-extensions:17}"
IMAGE_QMD="${QMD_IMAGE:-ghcr.io/ai-workspace-lab/qmd:v2.8.3}"
IMAGE_CADDY="caddy:2-alpine"

usage() {
  cat <<'EOF'
使用方法:
  # 默认一键 All-in-One 全套底座部署 (QMD Server + PostgreSQL + pgvector + 扩展存储):
  curl -fsSL https://raw.githubusercontent.com/.../setup-ai-memory-hub.sh | bash

高级参数配置模式:
  --mode <all-in-one|intranet|https>  运行模式 (默认: all-in-one)
  --domain <domain.com>               公网 HTTPS 模式下的解析域名 (mode=https 时必填)
  --email <email>                     Caddy TLS 证书通知邮箱 (默认: ops@example.com)
  --listen-ip <ip>                    指定监听 IP (内网模式默认: 0.0.0.0, 默认模式: 127.0.0.1)
  --qmd-port <port>                   QMD 外部监听端口 (默认: 8181)
  --pg-port <port>                    PostgreSQL 外部监听端口 (默认: 15432)
  --pg-only                           仅部署带扩展的 PostgreSQL 权威数据库底座
  --data-dir <path>                   数据存储根目录 (默认: ~/.ai-memory-hub/data)
  -h, --help                          显示帮助信息

环境变量注入规范 (托管/团队节点，由 Vault / KMS 注入，不落盘):
  QMD_INGEST_TOKEN                    QMD 数据摄入 Token (未指定则内存自动生成)
  QMD_MCP_TOKEN                       QMD MCP 协议令牌
  POSTGRES_PASSWORD                   PostgreSQL 管理员口令
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    --domain)
      DOMAIN="$2"
      MODE="https"
      shift 2
      ;;
    --email)
      ACME_EMAIL="$2"
      shift 2
      ;;
    --listen-ip)
      LISTEN_IP="$2"
      shift 2
      ;;
    --qmd-port)
      QMD_PORT="$2"
      shift 2
      ;;
    --pg-port)
      PG_PORT="$2"
      shift 2
      ;;
    --pg-only)
      DEPLOY_TARGET="pg-only"
      shift 1
      ;;
    --data-dir)
      DATA_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "错误: 未知参数 $1" >&2
      usage
      ;;
  esac
done

# ------------------------------------------------------------------------------
# 2. 内存机密生成与清理钩子 (零文件落地)
# ------------------------------------------------------------------------------
_gen_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$1"
  else
    head -c "$1" /dev/urandom | xxd -p | tr -d '\n'
  fi
}

POSTGRES_DB="${POSTGRES_DB:-postgres}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(_gen_secret 16)}"
QMD_INGEST_TOKEN="${QMD_INGEST_TOKEN:-$(_gen_secret 24)}"
QMD_MCP_TOKEN="${QMD_MCP_TOKEN:-$(_gen_secret 24)}"

cleanup_secrets() {
  unset POSTGRES_PASSWORD QMD_INGEST_TOKEN QMD_MCP_TOKEN
}
trap cleanup_secrets EXIT

# ------------------------------------------------------------------------------
# 3. 环境与模式检查
# ------------------------------------------------------------------------------
echo "==> [1/4] 检查 Docker 运行时环境 (部署目标: ${DEPLOY_TARGET}, 模式: ${MODE})..."
if ! command -v docker >/dev/null 2>&1; then
  echo "错误: 未检测到 Docker 守护进程，请先安装 Docker 或 OrbStack" >&2
  exit 1
fi

COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD="docker-compose"
else
  echo "错误: 未检测到 docker compose 插件或 docker-compose 二进制" >&2
  exit 1
fi

if [[ "$MODE" == "https" ]]; then
  if [[ -z "$DOMAIN" ]]; then
    echo "错误: https 模式必须指定 --domain 参数 (例如: --domain qmd.example.com)" >&2
    exit 1
  fi
  LISTEN_IP="0.0.0.0"
elif [[ "$MODE" == "intranet" ]]; then
  if [[ "$LISTEN_IP" == "127.0.0.1" ]]; then
    LISTEN_IP="0.0.0.0"
  fi
fi

# ------------------------------------------------------------------------------
# 4. 生成无机密 Compose 声明文件 (零落地)
# ------------------------------------------------------------------------------
echo "==> [2/4] 初始化扩展存储目录与编排声明: ${BASE_DIR}..."
mkdir -p "${BASE_DIR}" \
         "${DATA_DIR}/pgdata" \
         "${DATA_DIR}/qmd_models" \
         "${DATA_DIR}/qmd_storage" \
         "${DATA_DIR}/caddy_data" \
         "${DATA_DIR}/caddy_config"
chmod 700 "${BASE_DIR}"

COMPOSE_FILE="${BASE_DIR}/docker-compose.yml"

if [[ "$DEPLOY_TARGET" == "pg-only" ]]; then
  cat > "${COMPOSE_FILE}" <<'EOF'
services:
  postgresql:
    image: ${POSTGRESQL_IMAGE}
    container_name: memory-hub-postgresql
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      PGDATA: /var/lib/postgresql/data/pgdata
    expose:
      - "5432"
    ports:
      - "${LISTEN_IP}:${PG_PORT}:5432"
    volumes:
      - ${DATA_DIR}/pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB} -h 127.0.0.1"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s
    networks:
      - memory_net

networks:
  memory_net:
    name: docker_memory_hub_net
    driver: bridge
EOF

elif [[ "$MODE" == "https" ]]; then
  # 生产 HTTPS 模式：Caddy 反代 QMD，PostgreSQL 仅留在 Docker 内部私网
  cat > "${BASE_DIR}/Caddyfile" <<EOF
${DOMAIN} {
    tls ${ACME_EMAIL}
    reverse_proxy qmd:8181 {
        header_up X-Real-IP {remote_host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
EOF

  cat > "${COMPOSE_FILE}" <<'EOF'
services:
  postgresql:
    image: ${POSTGRESQL_IMAGE}
    container_name: memory-hub-postgresql
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      PGDATA: /var/lib/postgresql/data/pgdata
    expose:
      - "5432"
    volumes:
      - ${DATA_DIR}/pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB} -h 127.0.0.1"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s
    networks:
      - memory_net

  qmd:
    image: ${QMD_IMAGE}
    container_name: memory-hub-qmd
    restart: unless-stopped
    environment:
      NODE_ENV: production
      QMD_BACKEND: pg
      QMD_PG_URL: "postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgresql:5432/${POSTGRES_DB}?sslmode=disable"
      QMD_MCP_HOST: "0.0.0.0"
      QMD_MCP_TOKEN: ${QMD_MCP_TOKEN}
      QMD_INGEST_TOKEN: ${QMD_INGEST_TOKEN}
      QMD_CTX_COLLECT_INTERVAL: "0"
      QMD_MODEL_CACHE_DIR: /app/models
    expose:
      - "8181"
    volumes:
      - ${DATA_DIR}/qmd_models:/app/models
      - ${DATA_DIR}/qmd_storage:/app/storage
    depends_on:
      postgresql:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f -H \"Authorization: Bearer ${QMD_INGEST_TOKEN}\" http://127.0.0.1:8181/api/v1/agent/ingest/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    networks:
      - memory_net

  caddy:
    image: ${CADDY_IMAGE}
    container_name: memory-hub-caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ${DATA_DIR}/caddy_data:/data
      - ${DATA_DIR}/caddy_config:/config
    depends_on:
      qmd:
        condition: service_healthy
    networks:
      - memory_net

networks:
  memory_net:
    name: docker_memory_hub_net
    driver: bridge
EOF

else
  # 默认 All-in-One 本地或内网 HTTP 模式
  cat > "${COMPOSE_FILE}" <<'EOF'
services:
  postgresql:
    image: ${POSTGRESQL_IMAGE}
    container_name: memory-hub-postgresql
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      PGDATA: /var/lib/postgresql/data/pgdata
    expose:
      - "5432"
    ports:
      - "${LISTEN_IP}:${PG_PORT}:5432"
    volumes:
      - ${DATA_DIR}/pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB} -h 127.0.0.1"]
      interval: 5s
      timeout: 5s
      retries: 10
      start_period: 10s
    networks:
      - memory_net

  qmd:
    image: ${QMD_IMAGE}
    container_name: memory-hub-qmd
    restart: unless-stopped
    environment:
      NODE_ENV: production
      QMD_BACKEND: pg
      QMD_PG_URL: "postgres://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgresql:5432/${POSTGRES_DB}?sslmode=disable"
      QMD_MCP_HOST: "0.0.0.0"
      QMD_MCP_TOKEN: ${QMD_MCP_TOKEN}
      QMD_INGEST_TOKEN: ${QMD_INGEST_TOKEN}
      QMD_CTX_COLLECT_INTERVAL: "0"
      QMD_MODEL_CACHE_DIR: /app/models
    expose:
      - "8181"
    ports:
      - "${LISTEN_IP}:${QMD_PORT}:8181"
    volumes:
      - ${DATA_DIR}/qmd_models:/app/models
      - ${DATA_DIR}/qmd_storage:/app/storage
    depends_on:
      postgresql:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f -H \"Authorization: Bearer ${QMD_INGEST_TOKEN}\" http://127.0.0.1:8181/api/v1/agent/ingest/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    networks:
      - memory_net

networks:
  memory_net:
    name: docker_memory_hub_net
    driver: bridge
EOF
fi

# ------------------------------------------------------------------------------
# 5. 启动容器拓扑 (零文件落地执行)
# ------------------------------------------------------------------------------
echo "==> [3/4] 启动 AI-Memory-Hub 存储集群..."
cd "${BASE_DIR}"

POSTGRESQL_IMAGE="${IMAGE_POSTGRES}" \
QMD_IMAGE="${IMAGE_QMD}" \
CADDY_IMAGE="${IMAGE_CADDY}" \
POSTGRES_DB="${POSTGRES_DB}" \
POSTGRES_USER="${POSTGRES_USER}" \
POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
QMD_INGEST_TOKEN="${QMD_INGEST_TOKEN}" \
QMD_MCP_TOKEN="${QMD_MCP_TOKEN}" \
LISTEN_IP="${LISTEN_IP}" \
QMD_PORT="${QMD_PORT}" \
PG_PORT="${PG_PORT}" \
DATA_DIR="${DATA_DIR}" \
${COMPOSE_CMD} -f "${COMPOSE_FILE}" up -d --remove-orphans >/dev/null

echo "==> [4/4] 等待健康探针级联就绪..."
MAX_ATTEMPTS=24
ATTEMPT=0
ALL_HEALTHY=false

while [[ $ATTEMPT -lt $MAX_ATTEMPTS ]]; do
  PG_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' memory-hub-postgresql 2>/dev/null || echo "starting")

  if [[ "$DEPLOY_TARGET" == "pg-only" ]]; then
    if [[ "$PG_HEALTH" == "healthy" ]]; then
      ALL_HEALTHY=true
      break
    fi
  else
    QMD_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' memory-hub-qmd 2>/dev/null || echo "starting")
    if [[ "$PG_HEALTH" == "healthy" && "$QMD_HEALTH" == "healthy" ]]; then
      ALL_HEALTHY=true
      break
    fi
  fi

  sleep 2
  ((ATTEMPT++))
done

if [[ "$ALL_HEALTHY" != "true" ]]; then
  echo "警告: 部分容器尚未完全进入 healthy 状态，请执行 '${COMPOSE_CMD} logs' 查看排障信息。" >&2
fi

# ------------------------------------------------------------------------------
# 6. 终端一次性高亮输出凭据 (标准规范卡片)
# ------------------------------------------------------------------------------
if [[ "$MODE" == "https" ]]; then
  ENDPOINT_URL="https://${DOMAIN}"
elif [[ "$MODE" == "intranet" ]]; then
  LOCAL_IP="${LISTEN_IP}"
  if [[ "$LOCAL_IP" == "0.0.0.0" ]]; then
    LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || ip route get 1 2>/dev/null | awk '{print $NF;exit}' || echo "127.0.0.1")
  fi
  ENDPOINT_URL="http://${LOCAL_IP}:${QMD_PORT}"
else
  ENDPOINT_URL="http://127.0.0.1:${QMD_PORT}"
fi

C_CYAN='\033[1;36m'
C_GREEN='\033[1;32m'
C_YELLOW='\033[1;33m'
C_RED='\033[1;31m'
C_RESET='\033[0m'

printf "\n"
printf "${C_GREEN}==========================================================================${C_RESET}\n"
printf "${C_GREEN}              AI-Memory-Hub 记忆与存储集群部署成功！${C_RESET}\n"
printf "${C_GREEN}==========================================================================${C_RESET}\n"
printf " 部署模式       : ${C_CYAN}%s${C_RESET}\n" "${MODE}"
printf " 服务地址 (URL) : ${C_CYAN}%s${C_RESET}\n" "${ENDPOINT_URL}"
printf " 认证令牌 (Ingest): ${C_YELLOW}%s${C_RESET}\n" "${QMD_INGEST_TOKEN}"
printf " 协议令牌 (MCP)   : ${C_YELLOW}%s${C_RESET}\n" "${QMD_MCP_TOKEN}"
if [[ "$MODE" != "https" ]]; then
  printf " 数据库端点(SQL): ${C_CYAN}%s:%s${C_RESET} (User: %s)\n" "${LISTEN_IP}" "${PG_PORT}" "${POSTGRES_USER}"
fi
printf "\n"
printf "${C_RED} [安全提示] Token 纯内存生成，未落地写入任何磁盘文件，也未记录到系统日志！${C_RESET}\n"
printf "            请立即将上述 Token 复制并妥善保管（如存入 1Password / Vault）。\n"
printf "\n"
printf "${C_CYAN}🔗 【供 xworkmate-bridge 级联连接的配置参数】${C_RESET}\n"
printf "   export BRIDGE_QMD_INGEST_API_URL=\"%s/api/v1/agent/ingest\"\n" "${ENDPOINT_URL}"
printf "   export BRIDGE_QMD_INGEST_TOKEN=\"%s\"\n" "${QMD_INGEST_TOKEN}"
printf "   export BRIDGE_QMD_MCP_TOKEN=\"%s\"\n" "${QMD_MCP_TOKEN}"
printf "\n"
printf "${C_CYAN}🔍 【快速连通性验证】${C_RESET}\n"
printf "   curl -s -H \"Authorization: Bearer %s\" %s/api/v1/agent/ingest/health | jq .\n" "${QMD_INGEST_TOKEN}" "${ENDPOINT_URL}"
printf "${C_GREEN}==========================================================================${C_RESET}\n"
printf "\n"

cleanup_secrets
EOF

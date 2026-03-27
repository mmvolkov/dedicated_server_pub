#!/bin/bash
###############################################################################
#  health-check.sh — Проверка доступности всех сервисов платформы
#  Использование: ./scripts/health-check.sh
###############################################################################

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

check() {
    local name="$1"
    local url="$2"
    local expected="${3:-200}"

    status=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" 2>/dev/null || echo "000")

    if [ "$status" = "$expected" ]; then
        echo -e "  ${GREEN}✓${NC} $name ($url) — $status"
        ((PASS++))
    else
        echo -e "  ${RED}✗${NC} $name ($url) — $status (ожидался $expected)"
        ((FAIL++))
    fi
}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Проверка сервисов AI RAG Platform"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo -e "${YELLOW}GPU:${NC}"
nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null || echo "  nvidia-smi недоступен"
echo ""

echo -e "${YELLOW}AI-сервисы:${NC}"
check "GPT-OSS-120B (vLLM)" "http://localhost:8001/health"
check "Giga-Embeddings"     "http://localhost:8003/health"
echo ""

echo -e "${YELLOW}Инфраструктура:${NC}"
check "Qdrant"              "http://localhost:6333/healthz"
check "PostgreSQL"          "http://localhost:5432" "000"  # TCP only, no HTTP
check "Redis"               "http://localhost:6379" "000"  # TCP only, no HTTP

# PostgreSQL — проверяем через docker
pg_status=$(docker exec postgres pg_isready -U n8n 2>/dev/null && echo "ok" || echo "fail")
if [ "$pg_status" = "ok" ]; then
    echo -e "  ${GREEN}✓${NC} PostgreSQL (pg_isready) — accepting connections"
    ((PASS++))
else
    echo -e "  ${RED}✗${NC} PostgreSQL (pg_isready) — not ready"
    ((FAIL++))
fi

# Redis — проверяем через docker
redis_status=$(docker exec redis redis-cli ping 2>/dev/null || echo "fail")
if [ "$redis_status" = "PONG" ]; then
    echo -e "  ${GREEN}✓${NC} Redis (PING) — PONG"
    ((PASS++))
else
    echo -e "  ${RED}✗${NC} Redis (PING) — $redis_status"
    ((FAIL++))
fi
echo ""

echo -e "${YELLOW}Веб-сервисы:${NC}"
check "n8n"                 "http://localhost:5678/healthz"
check "Frontend (nginx)"    "http://localhost:80" "301"  # redirect to HTTPS
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "  Результат: ${GREEN}$PASS passed${NC}, ${RED}$FAIL failed${NC}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit $FAIL

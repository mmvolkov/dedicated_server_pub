#!/bin/bash
###############################################################################
#  backup.sh — Бэкап PostgreSQL, Qdrant snapshots, n8n workflows
#  Использование: ./scripts/backup.sh
#  Cron: 0 3 * * * /data/ai-rag-platform/scripts/backup.sh >> /var/log/backup.log 2>&1
###############################################################################

set -e

BACKUP_DIR="${BACKUP_DIR:-/data/backups}"
RETAIN_DAYS="${RETAIN_DAYS:-30}"
DATE=$(date +%Y%m%d_%H%M)
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"

mkdir -p "$BACKUP_DIR"

echo "[$DATE] Начало бэкапа..."

# 1. PostgreSQL
echo "  → PostgreSQL dump..."
docker exec postgres pg_dump -U "${POSTGRES_USER:-n8n}" "${POSTGRES_DB:-n8n}" \
  | gzip > "$BACKUP_DIR/postgres_${DATE}.sql.gz"
echo "  ✓ PostgreSQL: postgres_${DATE}.sql.gz"

# 2. Qdrant snapshots
echo "  → Qdrant snapshots..."
collections=$(curl -s "$QDRANT_URL/collections" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for c in data.get('result', {}).get('collections', []):
    print(c['name'])
" 2>/dev/null || echo "")

for collection in $collections; do
    snapshot=$(curl -s -X POST "$QDRANT_URL/collections/$collection/snapshots" \
      | python3 -c "import sys,json; print(json.load(sys.stdin).get('result',{}).get('name',''))" 2>/dev/null)
    if [ -n "$snapshot" ]; then
        curl -s "$QDRANT_URL/collections/$collection/snapshots/$snapshot" \
          -o "$BACKUP_DIR/qdrant_${collection}_${DATE}.snapshot"
        echo "  ✓ Qdrant ($collection): qdrant_${collection}_${DATE}.snapshot"
    fi
done

# 3. n8n workflows
echo "  → n8n workflows export..."
docker exec n8n n8n export:workflow --all --output=/tmp/workflows.json 2>/dev/null
docker cp n8n:/tmp/workflows.json "$BACKUP_DIR/n8n_workflows_${DATE}.json" 2>/dev/null
echo "  ✓ n8n: n8n_workflows_${DATE}.json"

# 4. n8n credentials (зашифрованы N8N_ENCRYPTION_KEY)
docker exec n8n n8n export:credentials --all --output=/tmp/credentials.json 2>/dev/null
docker cp n8n:/tmp/credentials.json "$BACKUP_DIR/n8n_credentials_${DATE}.json" 2>/dev/null
echo "  ✓ n8n credentials: n8n_credentials_${DATE}.json"

# 5. Очистка старых бэкапов
echo "  → Удаление бэкапов старше ${RETAIN_DAYS} дней..."
find "$BACKUP_DIR" -type f -mtime +${RETAIN_DAYS} -delete
echo "  ✓ Очистка завершена"

# Итог
TOTAL_SIZE=$(du -sh "$BACKUP_DIR" | cut -f1)
echo "[$DATE] Бэкап завершён. Директория: $BACKUP_DIR ($TOTAL_SIZE)"

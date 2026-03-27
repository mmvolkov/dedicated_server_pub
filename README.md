# Вариант D — Production Stack

```
RTX PRO 6000 Blackwell (96 GB) | GPT-OSS-120B | On-Premises RAG + CRM
```

## Архитектура

```
                         ┌─── app.DOMAIN ──→ [nginx] Фронтенд (SPA)
                         │                      ↓ /api/*
Internet → [Traefik] ────┼─── ai.DOMAIN ───→ [GPT-OSS-120B] vLLM API
           SSL + Роутинг │                   [Giga-Embeddings] Embed API
                         │
                         ├─── n8n.DOMAIN ──→ [n8n] + [n8n-worker]
                         │                      ↓         ↓
                         │                  [PostgreSQL] [Redis]
                         │
                         └─── qdrant.DOMAIN → [Qdrant] Dashboard
```

## Сервисы (9 контейнеров)

| Сервис           | Образ                | GPU  | Порт внутр. | Домен             |
|------------------|----------------------|------|-------------|-------------------|
| traefik          | traefik:v3.3         | —    | 80, 443     | *.DOMAIN          |
| gpt-oss-120b     | vllm/vllm-openai     | ~75G | 8000        | ai.DOMAIN/v1      |
| giga-embeddings  | custom (FastAPI)     | ~7G  | 8000        | ai.DOMAIN/embed   |
| qdrant           | qdrant/qdrant        | —    | 6333        | qdrant.DOMAIN     |
| postgres         | postgres:16-alpine   | —    | 5432        | внутренний        |
| redis            | redis:7-alpine       | —    | 6379        | внутренний        |
| n8n              | n8nio/n8n            | —    | 5678        | n8n.DOMAIN        |
| n8n-worker       | n8nio/n8n            | —    | —           | внутренний        |
| frontend         | nginx:alpine         | —    | 80          | app.DOMAIN        |

## Быстрый старт

### 1. DNS

Настройте A-записи на IP сервера:

```
ai.example.com      → 1.2.3.4
n8n.example.com     → 1.2.3.4
app.example.com     → 1.2.3.4
qdrant.example.com  → 1.2.3.4
```

### 2. Конфигурация

```bash
cp .env.example .env
nano .env
```

Обязательные переменные:
- `DOMAIN` — ваш домен
- `ACME_EMAIL` — email для Let's Encrypt
- `POSTGRES_PASSWORD` — пароль PostgreSQL
- `N8N_ENCRYPTION_KEY` — ключ шифрования n8n (32+ символов)

### 3. Запуск

```bash
# Сначала инфраструктура
docker compose up -d traefik postgres redis qdrant

# Затем AI-модели (скачивание ~70 GB при первом запуске)
docker compose up -d giga-embeddings gpt-oss-120b

# Когда модели загружены — n8n и фронтенд
docker compose up -d n8n n8n-worker frontend
```

### 4. Проверка

```bash
# Статус
docker compose ps

# Логи загрузки модели
docker compose logs -f gpt-oss-120b

# Healthcheck
curl https://ai.example.com/v1/models
curl https://ai.example.com/embed/health
```

## Зачем PostgreSQL

n8n по умолчанию использует SQLite — это не подходит для production:
- Нет конкурентной записи (воркфлоу падают при параллельных запусках)
- Нет бэкапов без остановки
- Теряется история при обновлении контейнера

PostgreSQL решает все три проблемы + даёт n8n queue mode через Redis.

## Зачем Redis

- **n8n queue mode**: основной процесс (n8n) принимает webhook'и и складывает задачи в очередь, воркер (n8n-worker) их обрабатывает. Это развязывает приём запросов и выполнение.
- **Кэш** (опционально): можно кэшировать эмбеддинги часто запрашиваемых текстов.
- **Rate limiting**: Traefik может использовать Redis для распределённого rate limiting.

## Зачем Traefik (а не nginx proxy)

- **Автоматический SSL** через Let's Encrypt — без cron + certbot
- **Docker-native**: роуты настраиваются через labels контейнеров, не нужно править конфиги
- **Автообнаружение**: добавил контейнер с label → Traefik подхватил
- **Dashboard**: мониторинг роутов в реальном времени

## Фронтенд

Папка `frontend/` содержит placeholder-чат. Замените на свой:

```bash
# Next.js / Nuxt / любой SPA
# Сбилдите и положите static-файлы в ./frontend/

# Или замените сервис на свой контейнер:
# frontend:
#   build: ./my-frontend
#   labels: ...
```

nginx.conf в папке настроен на SPA-режим (все роуты → index.html) + проксирование `/api/*` к AI-сервисам.

## Бэкапы

```bash
# PostgreSQL
docker exec postgres pg_dump -U n8n n8n > backup_$(date +%Y%m%d).sql

# Qdrant (snapshot)
curl -X POST http://localhost:6333/collections/regulations/snapshots

# n8n workflows (export)
docker exec n8n n8n export:workflow --all --output=/tmp/workflows.json
```

## Мониторинг

vLLM экспортирует Prometheus-метрики:
```bash
curl http://localhost:8001/metrics | grep vllm_
```

Рекомендуется добавить Prometheus + Grafana (отдельный compose или managed).

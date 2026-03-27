# On-Premises AI Stack

Локальный AI-стек для:

- OpenAI-совместимого LLM API на `gpt-oss-120b`
- embeddings на `Giga-Embeddings-instruct`
- автоматизации и AI-агентов через `n8n`
- веб-чата на отдельном фронтенде `local-ai-chat`

Все основные сервисы работают в Docker и публикуются наружу через Traefik.

## Что реально развёрнуто

Текущее рабочее состояние подтверждено на сервере `Pythagoras`:

- GPU: `NVIDIA RTX PRO 6000 Blackwell`, `96 GB`
- OS: `Ubuntu 24.04`
- Driver: `580.126.09`
- CUDA по `nvidia-smi`: `13.0`
- Reverse proxy: `Traefik v3.6.10`
- LLM: `openai/gpt-oss-120b` через `vllm/vllm-openai:latest`
- Orchestration: `n8n + n8n-worker + PostgreSQL + Redis`
- Vector DB: `Qdrant`
- Frontend: `local-ai-chat`, собранный как Vite/React SPA

Подробные заметки по реальному развёртыванию: [DEPLOYMENT_NOTES_2026-03-24.md](D:/projects/dedicated_server/docs/DEPLOYMENT_NOTES_2026-03-24.md)

## Домены

Traefik публикует сервисы на таких хостах:

| Домен | Назначение |
|---|---|
| `ai.${DOMAIN}` | LLM API (`/v1/*`) и embed API (`/embed*`) |
| `n8n.${DOMAIN}` | UI и webhooks `n8n` |
| `chat.${DOMAIN}` | фронтенд `local-ai-chat` |
| `qdrant.${DOMAIN}` | Qdrant UI / API |
| `traefik.${DOMAIN}` | dashboard Traefik |

Важно: старый фронтовый хост `app.${DOMAIN}` больше не является основным. Рабочий внешний фронт сейчас это `chat.${DOMAIN}`.

## Архитектура

```text
Internet
  |
  v
Traefik (:80/:443, Let's Encrypt)
  |
  +--> ai.DOMAIN/v1/* ---------> gpt-oss-120b (vLLM)
  |
  +--> ai.DOMAIN/embed* -------> giga-embeddings
  |
  +--> n8n.DOMAIN -------------> n8n
  |
  +--> chat.DOMAIN ------------> frontend (local-ai-chat -> nginx)
  |
  +--> qdrant.DOMAIN ----------> qdrant

Internal services:
  postgres  <- n8n
  redis     <- n8n queue mode
  qdrant    <- n8n / embeddings / RAG
```

## Состав стека

### GPU-сервисы

| Сервис | Образ / модель | Назначение |
|---|---|---|
| `gpt-oss-120b` | `vllm/vllm-openai:latest` + `openai/gpt-oss-120b` | основной LLM API |
| `giga-embeddings` | кастомный FastAPI-сервис | embeddings для документов и запросов |

### Инфраструктура

| Сервис | Образ | Назначение |
|---|---|---|
| `traefik` | `traefik:v3.6.10` | reverse proxy, TLS, доменный роутинг |
| `postgres` | `postgres:16-alpine` | база данных `n8n` |
| `redis` | `redis:7-alpine` | queue mode для `n8n` |
| `qdrant` | `qdrant/qdrant:latest` | векторная БД |
| `n8n` | `n8nio/n8n:latest` | UI, webhooks, workflows |
| `n8n-worker` | `n8nio/n8n:latest` | обработка очереди |
| `frontend` | build из `./local-ai-chat` | внешний веб-интерфейс |

## Ключевые рабочие изменения

### 1. Traefik

Traefik был обновлён и стабилизирован:

- используется `traefik:v3.6.10`
- добавлена переменная:

```yaml
environment:
  - DOCKER_API_VERSION=1.40
```

Это устранило ошибку Docker provider вида `client version 1.24 is too old`.

### 2. LLM

Рабочая конфигурация `gpt-oss-120b` в compose:

```yaml
--model openai/gpt-oss-120b
--dtype auto
--max-model-len 65536
--gpu-memory-utilization 0.85
--served-model-name gpt-oss-120b
--trust-remote-code
--enable-auto-tool-choice
--tool-call-parser openai
```

Практический смысл:

- `0.85` понадобилось, чтобы vLLM перестал падать на `No available memory for the cache blocks`
- если KV cache снова начнёт упираться в память, первый безопасный откат — уменьшить `--max-model-len` до `32768`

### 3. Giga Embeddings

Рабочая версия embedder'а отличается от первоначального варианта:

- base image: `nvidia/cuda:12.8.0-runtime-ubuntu24.04`
- используется `transformers==4.51.0`
- добавлен `einops`
- убран `flash-attn`
- в [server.py](D:/projects/dedicated_server/giga-embeddings/server.py) используется:

```python
attn_implementation="eager"
```

Это соответствует текущим файлам:

- [Dockerfile](D:/projects/dedicated_server/giga-embeddings/Dockerfile)
- [server.py](D:/projects/dedicated_server/giga-embeddings/server.py)

Важно: на одной GPU embedder может не помещаться одновременно с `gpt-oss-120b`. В реальном развёртывании приоритет был отдан LLM.

### 4. Frontend

Фронт больше не раздаётся из старой папки `./frontend` как основной сайт.

Сейчас используется:

- проект: `./local-ai-chat`
- multi-stage Docker build
- nginx внутри контейнера
- внешний домен: `chat.${DOMAIN}`

Рабочий фрагмент compose:

```yaml
frontend:
  build:
    context: ./local-ai-chat
  container_name: frontend
  restart: unless-stopped
  labels:
    - traefik.enable=true
    - traefik.http.routers.frontend.rule=Host(`chat.${DOMAIN}`)
    - traefik.http.routers.frontend.entrypoints=websecure
    - traefik.http.routers.frontend.tls.certresolver=letsencrypt
    - traefik.http.services.frontend.loadbalancer.server.port=80
```

## Структура репозитория

```text
.
├── docker-compose.yml
├── .env.example
├── README.md
├── GITHUB_README.md
├── INSTALL_GUIDE.md
├── docs/
│   └── DEPLOYMENT_NOTES_2026-03-24.md
├── giga-embeddings/
│   ├── Dockerfile
│   └── server.py
├── local-ai-chat/
│   ├── Dockerfile
│   ├── nginx.conf
│   └── src/...
├── examples/
│   ├── llm_test.py
│   └── n8n-chat-backends/
└── scripts/
    ├── health-check.sh
    └── index-documents.py
```

Примечание: старая папка `frontend/` всё ещё может лежать в репозитории как ранний placeholder, но боевой фронт сейчас собирается из `local-ai-chat`.

## Быстрый запуск

```bash
cp .env.example .env
nano .env

docker compose up -d traefik postgres redis qdrant
docker compose up -d gpt-oss-120b
docker compose up -d n8n n8n-worker frontend
```

Если нужен embedder:

```bash
docker compose up -d giga-embeddings
```

Но включай его с оглядкой на VRAM.

## Проверки

### LLM

```bash
docker compose exec gpt-oss-120b curl -f http://localhost:8000/health
curl -k https://ai.${DOMAIN}/v1/models
curl -k https://ai.${DOMAIN}/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-oss-120b","messages":[{"role":"user","content":"Привет"}]}'
```

### Frontend

```bash
curl -k -I https://chat.${DOMAIN}
curl -k https://chat.${DOMAIN} | head
```

### Qdrant

```bash
curl -k https://qdrant.${DOMAIN}/healthz
```

### n8n

```bash
curl -k -I https://n8n.${DOMAIN}
```

## Локальные скрипты против LLM

Внешний LLM endpoint:

```text
https://ai.${DOMAIN}/v1
```

На текущей конфигурации отдельная проверка API key для LLM не настроена. Поэтому многие OpenAI-совместимые клиенты можно запускать с любым непустым ключом.

Пример: [llm_test.py](D:/projects/dedicated_server/examples/llm_test.py)

```bash
python examples/llm_test.py
```

Или с переопределением:

```bash
OPENAI_BASE_URL=https://ai.${DOMAIN}/v1 OPENAI_API_KEY=dummy-key python examples/llm_test.py
```

## Фронтенд и n8n webhook

`local-ai-chat` работает через `n8n`, а не напрямую с моделью.

Webhook:

```text
https://n8n.${DOMAIN}/webhook/lovable-chat
```

Фронтенд отправляет:

```json
{
  "message": "текст пользователя",
  "sessionId": "стабильный id сессии"
}
```

И ожидает ответ:

```json
{
  "ok": true,
  "reply": "Ответ модели"
}
```

Если в `n8n` используется `AI Agent`, рабочий `Respond to Webhook` выглядит так:

```javascript
{{ { ok: true, reply: $json.output } }}
```

Дополнительно:

- `Webhook` должен быть настроен через `Respond to Webhook`
- для браузерного вызова нужен CORS origin `https://chat.${DOMAIN}`

## Что ещё помнить

- `gpt-oss-120b` — приоритетный сервис, потому что он подтверждён как стабильно рабочий
- `giga-embeddings` лучше включать только когда действительно нужен embeddings/RAG
- `Traefik` и сертификаты уже стабилизированы, без причины их лучше не трогать
- если меняется контракт фронтенда, надо синхронно менять `n8n` workflow

## Ссылки

- рабочие заметки по деплою: [DEPLOYMENT_NOTES_2026-03-24.md](D:/projects/dedicated_server/docs/DEPLOYMENT_NOTES_2026-03-24.md)
- пример вызова LLM: [llm_test.py](D:/projects/dedicated_server/examples/llm_test.py)
- примеры backend-схем для чатов: [README.md](D:/projects/dedicated_server/examples/n8n-chat-backends/README.md)

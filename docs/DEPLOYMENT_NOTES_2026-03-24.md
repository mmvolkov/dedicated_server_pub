# Deployment Notes — 2026-03-24

Этот документ фиксирует практические изменения, которые были сделаны во время
реального развёртывания стека на сервере `Pythagoras`.

Сервер:

- CPU: AMD Ryzen 9 9950X
- RAM: 192 GB
- GPU: NVIDIA RTX PRO 6000 Blackwell 96 GB
- OS: Ubuntu 24.04

## Что было изменено

### 1. NVIDIA driver и GPU runtime

Во время развёртывания был подтверждён рабочий стек NVIDIA:

- установлен современный драйвер серии `580`
- рабочее состояние на сервере: `Driver Version: 580.126.09`
- `nvidia-smi` показывает `CUDA Version: 13.0`

Практические проверки:

```bash
nvidia-smi
docker run --rm --runtime=nvidia --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
```

Что это дало:

- Docker-контейнеры с `runtime: nvidia` начали видеть GPU
- `gpt-oss-120b` и `giga-embeddings` смогли стартовать внутри Docker

### 2. Traefik

Исходная проблема:

- Traefik не видел Docker provider и писал ошибку вида
  `client version 1.24 is too old`

Что изменили:

- обновили образ до `traefik:v3.6.10`
- добавили переменную окружения:

```yaml
environment:
  - DOCKER_API_VERSION=1.40
```

Что ещё важно:

- наружу публикуются только `80` и `443`
- сертификаты выпускаются через Let's Encrypt
- все роуты идут через labels в `docker-compose.yml`

Текущие домены:

- `ai.${DOMAIN}` — LLM API и embed API
- `n8n.${DOMAIN}` — n8n UI
- `chat.${DOMAIN}` — фронтенд
- `qdrant.${DOMAIN}` — Qdrant UI/API
- `traefik.${DOMAIN}` — dashboard Traefik

### 3. LLM — GPT-OSS-120B

Во время запуска `vLLM` упирался в память KV cache.

Ключевая ошибка:

```text
ValueError: No available memory for the cache blocks
```

Что изменили:

- подняли `--gpu-memory-utilization` с `0.70` до `0.85`
- переключили parser tool calling на `openai`

Текущая конфигурация в compose:

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

Практическое замечание:

- на сервере рабочая точка была найдена именно через увеличение
  `gpu-memory-utilization`
- если снова появится ошибка по KV cache, первый безопасный откат —
  уменьшить `--max-model-len` до `32768`

Проверки:

```bash
docker compose exec gpt-oss-120b curl -f http://localhost:8000/health
curl -k https://ai.${DOMAIN}/v1/models
curl -k https://ai.${DOMAIN}/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-oss-120b","messages":[{"role":"user","content":"Привет"}]}'
```

### 4. Giga Embeddings

Исходная версия embedder'а была нестабильной по нескольким причинам:

- невалидный/неудачный CUDA base image
- попытка использовать `flash-attn`
- несовместимость версии `transformers`
- missing dependency `einops`
- нестабильная attention implementation

Финальная рабочая схема:

- base image: `nvidia/cuda:12.8.0-runtime-ubuntu24.04`
- `transformers==4.51.0`
- добавлен `einops`
- убран `flash-attn`
- в коде используется `attn_implementation="eager"`

Зачем это было нужно:

- сборка стала воспроизводимой
- контейнер перестал падать на missing deps и несовместимых attention backends

Важно:

- embedder рабочий, но на одной GPU вместе с `gpt-oss-120b` может не помещаться
- в реальном развёртывании LLM был приоритетнее, поэтому embedder может
  потребовать отдельного запуска, второй GPU или снижения параметров LLM

Проверка:

```bash
docker compose up -d giga-embeddings
docker compose logs -f giga-embeddings
docker compose exec giga-embeddings curl -f http://localhost:8000/health
```

### 5. Фронтенд / сайт

Изначально в compose был placeholder-фронтенд из `./frontend`.

Что изменили:

- добавили отдельный фронтенд-проект `./local-ai-chat`
- фронтенд теперь собирается multi-stage Docker build'ом
- статические файлы раздаются через nginx внутри контейнера
- наружу он публикуется через Traefik на домене `chat.${DOMAIN}`

Итоговая схема:

```text
Internet -> Traefik -> frontend container -> nginx -> Vite/React SPA
```

Текущий compose-фрагмент:

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

Проверка:

```bash
curl -k -I https://chat.${DOMAIN}
curl -k https://chat.${DOMAIN} | head
```

### 6. Связка фронтенда с n8n

Фронтенд `local-ai-chat` работает не напрямую с моделью, а через `n8n` webhook:

```text
https://n8n.${DOMAIN}/webhook/lovable-chat
```

Формат запроса:

```json
{
  "message": "текст пользователя",
  "sessionId": "стабильный id сессии"
}
```

Формат ответа, который ожидает фронтенд:

```json
{
  "ok": true,
  "reply": "Текст ответа модели"
}
```

Критичные настройки в `n8n`:

- `Webhook` должен отвечать через `Respond to Webhook`
- для браузера должен быть настроен CORS:
  `https://chat.${DOMAIN}`
- если в workflow используется `AI Agent`, то текст ответа берётся из
  `$json.output`

Рабочий вариант для `Respond to Webhook`:

```javascript
{{ { ok: true, reply: $json.output } }}
```

Это важно, потому что ручная сборка JSON строкой ломалась на переносах строк и
кавычках из ответа модели.

## Текущий рабочий снимок стека

Ниже зафиксирован terminal snapshot рабочего состояния после запуска основных
сервисов:

```text
deploy@Pythagoras:/data/dedicated_server$ docker compose ps
NAME           IMAGE                       COMMAND                  SERVICE        CREATED        STATUS                 PORTS
frontend       dedicated_server-frontend   "/docker-entrypoint…"   frontend       9 hours ago    Up 9 hours             80/tcp
gpt-oss-120b   vllm/vllm-openai:latest     "vllm serve --model…"   gpt-oss-120b   11 hours ago   Up 11 hours (healthy)
n8n            n8nio/n8n:latest            "tini -- /docker-ent…"   n8n            15 hours ago   Up 15 hours            5678/tcp
n8n-worker     n8nio/n8n:latest            "tini -- /docker-ent…"   n8n-worker     15 hours ago   Up 15 hours            5678/tcp
postgres       postgres:16-alpine          "docker-entrypoint.s…"   postgres       17 hours ago   Up 17 hours (healthy)  5432/tcp
qdrant         qdrant/qdrant:latest        "./entrypoint.sh"        qdrant         17 hours ago   Up 17 hours            6333-6334/tcp
redis          redis:7-alpine              "docker-entrypoint.s…"   redis          17 hours ago   Up 17 hours (healthy)  6379/tcp
traefik        traefik:v3.6.10             "/entrypoint.sh --ap…"   traefik        15 hours ago   Up 15 hours            0.0.0.0:80->80/tcp, [::]:80->80/tcp, 0.0.0.0:443->443/tcp, [::]:443->443/tcp
```

## Сверка с git на 2026-03-25

Отдельно была проверена ситуация, когда на сервере в `/data/dedicated_server` оставались
локальные правки и `git pull` конфликтовал с файлами `giga-embeddings`.

После подтягивания актуального `main` подтверждено:

- `docker-compose.yml` в git соответствует актуальному compose-файлу на сервере
- фронтенд в compose публикуется на `chat.${DOMAIN}`, а не на старом `app.${DOMAIN}`
- `Traefik` в git зафиксирован на `v3.6.10`
- `gpt-oss-120b` в git зафиксирован с:
  - `--max-model-len 65536`
  - `--gpu-memory-utilization 0.85`
  - `--tool-call-parser openai`
- сервис `giga-embeddings` в compose остаётся описанным и корректным

Это означает, что текущий `docker-compose.yml` в репозитории уже можно считать
каноничным серверным вариантом.

### Что именно считать правильной конфигурацией Giga Embeddings

Правильной и зафиксированной в git считается следующая связка файлов:

- `giga-embeddings/Dockerfile`
- `giga-embeddings/server.py`

Ключевые параметры этой версии:

- base image: `nvidia/cuda:12.8.0-runtime-ubuntu24.04`
- Python зависимости:
  - `torch>=2.5.0`
  - `transformers==4.51.0`
  - `accelerate`
  - `einops`
- `flash-attn` не используется
- в `server.py` используется `attn_implementation="eager"`

Это не случайная временная версия, а именно тот рабочий вариант, на котором embedder
удалось стабильно поднять.

### Важное различие: compose vs runtime

Нужно различать две вещи:

1. **Конфигурация compose**
   Сервис `giga-embeddings` остаётся в `docker-compose.yml` и описан корректно.

2. **Фактический runtime на одной GPU**
   На сервере с одной `RTX PRO 6000 Blackwell 96 GB` `gpt-oss-120b` был приоритетным
   сервисом. Поэтому embedder мог быть временно остановлен, чтобы освободить VRAM.

То есть:

- `giga-embeddings` в compose есть и настроен правильно
- но это не означает, что он всегда должен одновременно работать вместе с LLM

Это не drift конфигурации, а осознанное эксплуатационное решение.

### Как проверить, были ли на сервере ещё другие правки

Если на сервере после `git stash` остался `stash@{0}`, то проверить отличие старой
локальной версии от текущего git можно так:

```bash
cd /data/dedicated_server
git diff HEAD stash@{0} -- giga-embeddings/Dockerfile giga-embeddings/server.py
```

Если diff пустой, значит:

- текущая версия `giga-embeddings` в git и есть нужная серверная версия
- stash можно удалить

Если diff непустой, его нужно отдельно разобрать, прежде чем удалять stash.

## Что помнить дальше

- `Traefik` и сертификаты уже стабилизированы, их лучше не трогать без причины
- `gpt-oss-120b` — приоритетный сервис, потому что он подтверждён в работе
- `giga-embeddings` нужно запускать с оглядкой на VRAM
- фронтенд на `chat.${DOMAIN}` зависит от корректного `n8n` webhook contract
- если меняется фронтенд-контракт, надо синхронно менять и workflow в `n8n`

# Инструкция по установке AI RAG Platform на выделенный сервер Selectel

> **Сервер**: AMD Ryzen 9 9950X, 192 GB DDR5, 2×2 TB NVMe, NVIDIA RTX PRO 6000 Blackwell 96 GB  
> **ОС**: Ubuntu 24.04 LTS  
> **Время установки**: ~2–3 часа (из них ~40 мин на скачивание моделей)

---

## Содержание

1. [Получение доступа к серверу в панели Selectel](#1-получение-доступа-к-серверу-в-панели-selectel)
2. [Подключение по SSH](#2-подключение-по-ssh)
3. [Базовая настройка ОС](#3-базовая-настройка-ос)
4. [Установка NVIDIA-драйверов](#4-установка-nvidia-драйверов)
5. [Установка Docker и NVIDIA Container Toolkit](#5-установка-docker-и-nvidia-container-toolkit)
6. [Подготовка дисков](#6-подготовка-дисков)
7. [Настройка DNS](#7-настройка-dns)
8. [Развёртывание платформы](#8-развёртывание-платформы)
9. [Проверка работоспособности](#9-проверка-работоспособности)
10. [Настройка автозапуска и бэкапов](#10-настройка-автозапуска-и-бэкапов)

---

## 1. Получение доступа к серверу в панели Selectel

После активации выделенного сервера в Selectel вам нужно найти данные для подключения.

### 1.1. Откройте панель управления

Перейдите на [my.selectel.ru](https://my.selectel.ru) и авторизуйтесь.

### 1.2. Найдите свой сервер

В верхнем меню нажмите **Продукты** → **Выделенные серверы** → **Серверы**.

Выберите ваш сервер из списка.

### 1.3. Запишите данные для подключения

Перейдите на вкладку **Операционная система**. Здесь вы найдёте:

- **IP-адрес** — публичный IP сервера (например, `95.213.xxx.xxx`)
- **Логин** — обычно `root`
- **Пароль** — сгенерированный при установке ОС

> **Запишите эти данные** — они понадобятся на следующем шаге.

### 1.4. (Рекомендуется) Добавьте SSH-ключ

Если вы ещё не создавали SSH-ключ:

```bash
# На вашем ЛОКАЛЬНОМ компьютере (не на сервере!)
ssh-keygen -t ed25519 -C "your-email@company.ru"
```

Нажмите Enter три раза (путь по умолчанию, без passphrase).

Скопируйте публичный ключ:

```bash
cat ~/.ssh/id_ed25519.pub
```

В панели Selectel: **Продукты** → **Выделенные серверы** → **SSH-ключи** → **Добавить ключ** → вставьте содержимое.

---

## 2. Подключение по SSH

### Linux / macOS

Откройте терминал и введите:

```bash
ssh root@<IP_СЕРВЕРА>
```

Замените `<IP_СЕРВЕРА>` на реальный IP из панели Selectel.

При первом подключении система спросит:

```
The authenticity of host '95.213.xxx.xxx' can't be established.
ED25519 key fingerprint is SHA256:xxxxx.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

Введите `yes` и нажмите Enter.

Если вы не добавляли SSH-ключ, введите пароль из панели Selectel.

### Windows 10/11

> 📖 **Официальная инструкция Selectel**: [Подключение к серверу по SSH (Windows)](https://docs.selectel.ru/dedicated/manage/connect-to-server/?connect-via-ssh=windows)

Откройте **PowerShell** или **Командную строку** (cmd) и введите:

```bash
ssh root@<IP_СЕРВЕРА>
```

Windows 10+ имеет встроенный SSH-клиент. Если его нет, используйте [PuTTY](https://www.putty.org/):

1. Скачайте и запустите `putty.exe`
2. В поле **Host Name** введите IP сервера
3. Порт: `22`, тип подключения: `SSH`
4. Нажмите **Open**
5. Введите логин (`root`) и пароль

### Проверка: вы на сервере

После успешного подключения вы увидите приглашение вида:

```
root@selectel-server:~#
```

Проверьте, что вы на нужной машине:

```bash
# Информация о системе
hostnamectl

# Процессор (должен быть Ryzen 9 9950X)
lscpu | grep "Model name"

# Оперативная память (должно быть ~192 GB)
free -h

# Диски (должны быть 2× NVMe)
lsblk
```

### Проверка GPU

```bash
# Видит ли система GPU?
lspci | grep -i nvidia
```

Ожидаемый вывод (примерно):

```
01:00.0 VGA compatible controller: NVIDIA Corporation [RTX PRO 6000] ...
```

Если вывод пустой — GPU не обнаружен. Обратитесь в поддержку Selectel.

---

## 3. Базовая настройка ОС

### 3.1. Обновление системы

```bash
apt update && apt upgrade -y
```

### 3.2. Установка базовых утилит

```bash
apt install -y \
  curl wget git htop iotop \
  build-essential software-properties-common \
  ufw fail2ban net-tools \
  unzip jq
```

### 3.3. Настройка часового пояса

```bash
timedatectl set-timezone Europe/Moscow
timedatectl
```

### 3.4. Настройка файрвола

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp     # SSH
ufw allow 80/tcp     # HTTP (Traefik)
ufw allow 443/tcp    # HTTPS (Traefik)
ufw --force enable
ufw status
```

Ожидаемый вывод:

```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
```

### 3.5. Создание рабочего пользователя

Работать под `root` на production — плохая практика:

```bash
adduser deploy
# Введите пароль и подтвердите

usermod -aG sudo deploy

# Скопируйте SSH-ключ для нового пользователя
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/ 2>/dev/null || true
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
```

Переключитесь на нового пользователя:

```bash
su - deploy
```

> С этого момента все команды выполняются от имени `deploy` с `sudo`.

---

## 4. Установка NVIDIA-драйверов

Это самый критичный этап. RTX PRO 6000 Blackwell требует **драйвер версии 580+**.

### 4.1. Установка заголовков ядра

```bash
sudo apt install -y linux-headers-$(uname -r)
```

### 4.2. Проверка рекомендуемого драйвера

```bash
sudo apt install -y ubuntu-drivers-common
ubuntu-drivers devices
```

Ожидаемый вывод (пример):

```
== /sys/devices/pci0000:00/0000:00:01.0/0000:01:00.0 ==
modalias : pci:v000010DEd00002900...
vendor   : NVIDIA Corporation
driver   : nvidia-driver-580 - third-party non-free recommended
```

### 4.3. Установка драйвера

```bash
# Установите рекомендуемую версию (580 или выше)
sudo apt install -y nvidia-driver-580 nvidia-utils-580
```

Если `ubuntu-drivers` не показывает Blackwell-драйверы, добавьте PPA:

```bash
sudo add-apt-repository ppa:graphics-drivers/ppa -y
sudo apt update
ubuntu-drivers devices
# Теперь должен появиться 580+
sudo apt install -y nvidia-driver-580
```

### 4.4. Перезагрузка

```bash
sudo reboot
```

Дождитесь перезагрузки (~30 секунд), затем подключитесь заново:

```bash
ssh deploy@<IP_СЕРВЕРА>
```

### 4.5. Проверка драйвера

```bash
nvidia-smi
```

**Ожидаемый вывод:**

```
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 580.xx.xx    Driver Version: 580.xx.xx    CUDA Version: 12.9                |
|-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp  Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|=========================================+========================+======================|
|   0  NVIDIA RTX PRO 6000       Off      | 00000000:01:00.0  Off  |                  Off |
|  0%   35C    P8              25W / 350W  |       0MiB / 98304MiB  |      0%      Default |
+-----------------------------------------+------------------------+----------------------+
```

**Что проверить:**

- **Driver Version**: 580.xx или выше
- **GPU Name**: RTX PRO 6000 (или RTX PRO 6000 Blackwell)
- **Memory**: 98304 MiB (~96 GB)
- **CUDA Version**: 12.8 или выше

**Если nvidia-smi выдаёт ошибку:**

```
NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.
```

Значит драйвер не загрузился. Проверьте:

```bash
# Загружен ли модуль ядра?
lsmod | grep nvidia

# Есть ли ошибки?
dmesg | grep -i nvidia | tail -20

# Попробуйте переустановить
sudo apt remove --purge nvidia-* -y
sudo apt autoremove -y
sudo reboot
# После ребута — повторить установку драйвера
```

### 4.6. Фиксация версии ядра

Обновление ядра может сломать NVIDIA-драйвер. Зафиксируйте текущую версию:

```bash
sudo apt-mark hold linux-image-$(uname -r) linux-headers-$(uname -r)
```

Проверка:

```bash
apt-mark showhold
```

Ожидаемый вывод:

```
linux-headers-6.8.0-xx-generic
linux-image-6.8.0-xx-generic
```

> Чтобы разблокировать в будущем: `sudo apt-mark unhold linux-image-...`

---

## 5. Установка Docker и NVIDIA Container Toolkit

### 5.1. Установка Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker deploy
```

**Перезайдите** в сессию, чтобы группа `docker` подхватилась:

```bash
exit
ssh deploy@<IP_СЕРВЕРА>
```

Проверка:

```bash
docker --version
# Docker version 27.x.x

docker run --rm hello-world
# Должен вывести "Hello from Docker!"
```

### 5.2. Установка NVIDIA Container Toolkit

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit

sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

### 5.3. Проверка GPU в Docker

```bash
docker run --rm --runtime=nvidia --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
```

**Ожидаемый вывод:** тот же, что и `nvidia-smi` на хосте — RTX PRO 6000, 96 GB, Driver 580.

Если вы видите эту таблицу — **GPU доступен внутри контейнеров**. Самый важный этап пройден.

---

## 6. Подготовка дисков

### 6.1. Просмотр дисков

```bash
lsblk
```

Пример вывода:

```
NAME        MAJ:MIN RM   SIZE RO TYPE MAUNTPOINTS
nvme0n1     259:0    0   1.8T  0 disk
├─nvme0n1p1 259:1    0     1G  0 part /boot/efi
├─nvme0n1p2 259:2    0     2G  0 part /boot
└─nvme0n1p3 259:3    0   1.8T  0 part /
nvme1n1     259:4    0   1.8T  0 disk
```

`nvme0n1` — системный диск (уже размечен), `nvme1n1` — второй диск для данных.

### 6.2. Разметка второго диска

```bash
# Форматирование (ВНИМАНИЕ: все данные на nvme1n1 будут уничтожены!)
sudo mkfs.ext4 -L data /dev/nvme1n1

# Создание точки монтирования
sudo mkdir -p /data

# Монтирование
sudo mount /dev/nvme1n1 /data

# Автомонтирование при перезагрузке
echo '/dev/nvme1n1 /data ext4 defaults 0 2' | sudo tee -a /etc/fstab

# Права для пользователя deploy
sudo chown -R deploy:deploy /data

# Проверка
df -h /data
```

### 6.3. Структура директорий

```bash
mkdir -p /data/{models,documents,backups}
```

---

## 7. Настройка DNS

Если у вас есть домен (например, `ai.company.ru`), создайте A-записи:

```
ai.ai.company.ru       → <IP_СЕРВЕРА>
n8n.ai.company.ru      → <IP_СЕРВЕРА>
app.ai.company.ru      → <IP_СЕРВЕРА>
qdrant.ai.company.ru   → <IP_СЕРВЕРА>
```

Проверка (после обновления DNS, может занять 5–30 минут):

```bash
dig +short ai.ai.company.ru
# Должен вернуть IP сервера
```

> Если домена нет — платформа будет доступна по IP-адресу. Traefik можно заменить на прямой проброс портов.

---

## 8. Развёртывание платформы

### 8.1. Клонирование репозитория

```bash
cd /data
git clone https://github.com/mmvolkov/dedicated_server.git
cd dedicated_server
```

### 8.2. Конфигурация

```bash
cp .env.example .env
nano .env
```

Заполните:

```env
DOMAIN=ai.company.ru
ACME_EMAIL=admin@company.ru
POSTGRES_PASSWORD=$(openssl rand -base64 32)
N8N_ENCRYPTION_KEY=$(openssl rand -hex 16)
QDRANT_API_KEY=$(openssl rand -base64 24)
```

Для генерации TRAEFIK_AUTH:

```bash
sudo apt install -y apache2-utils
htpasswd -nb admin ваш-пароль
# Скопируйте вывод в .env (TRAEFIK_AUTH=...)
# Замените одинарные $ на двойные $$ для docker compose
```

### 8.3. Запуск инфраструктуры

```bash
docker compose up -d traefik postgres redis qdrant
```

Подождите 10–15 секунд, проверьте:

```bash
docker compose ps
```

Все 4 сервиса должны быть в статусе `running` или `healthy`.

### 8.4. Запуск эмбеддера

```bash
docker compose up -d giga-embeddings
```

Первый запуск: сборка Docker-образа (~5 мин) + скачивание модели (~6 GB).

```bash
# Следить за процессом:
docker compose logs -f giga-embeddings
```

Ждите строку:

```
INFO:     Model loaded. Device: cuda:0
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 8.5. Запуск LLM

```bash
docker compose up -d gpt-oss-120b
```

Скачивание модели **~65 GB** — это самый долгий этап (10–40 минут в зависимости от канала).

```bash
# Следить за прогрессом:
docker compose logs -f gpt-oss-120b
```

Ждите строку:

```
INFO:     Started server process [1]
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### 8.6. Проверка VRAM

Пока модели грузятся, в другом терминале:

```bash
nvidia-smi
```

После загрузки обеих моделей вы должны видеть ~72 GB использованной VRAM.

### 8.7. Запуск n8n и фронтенда

```bash
docker compose up -d n8n n8n-worker frontend
```

### 8.8. Проверка всех сервисов

```bash
docker compose ps
```

Ожидаемый результат — **все 9 сервисов running**:

```
NAME              IMAGE                     STATUS
traefik           traefik:v3.3              Up (healthy)
postgres          postgres:16-alpine        Up (healthy)
redis             redis:7-alpine            Up (healthy)
qdrant            qdrant/qdrant:latest      Up
giga-embeddings   dedicated_server-giga...   Up (healthy)
gpt-oss-120b      vllm/vllm-openai:latest   Up (healthy)
n8n               n8nio/n8n:latest          Up
n8n-worker        n8nio/n8n:latest          Up
frontend          nginx:alpine              Up
```

---

## 9. Проверка работоспособности

### 9.1. GPU и модели

```bash
nvidia-smi
```

### 9.2. LLM API

```bash
# Список моделей
curl -s http://localhost:8001/v1/models | jq .

# Тестовый запрос
curl -s http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-oss-120b",
    "messages": [
      {"role": "system", "content": "Set reasoning effort to low. Отвечай кратко на русском."},
      {"role": "user", "content": "Что такое RAG в контексте LLM?"}
    ],
    "max_tokens": 200
  }' | jq -r '.choices[0].message.content'
```

### 9.3. Эмбеддер

```bash
curl -s http://localhost:8003/health | jq .
# {"status":"ok","model":"ai-sage/Giga-Embeddings-instruct"}

curl -s http://localhost:8003/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["Тестовый документ для проверки эмбеддинга"]}' | jq '.dim, .count'
# 2048
# 1
```

### 9.4. Qdrant

```bash
curl -s http://localhost:6333/healthz
# ok

# Создание тестовой коллекции
curl -s -X PUT http://localhost:6333/collections/test \
  -H "Content-Type: application/json" \
  -d '{"vectors": {"size": 2048, "distance": "Cosine"}}' | jq .
```

### 9.5. n8n

Откройте в браузере: `https://n8n.ai.company.ru` (или `http://<IP>:5678`)

При первом входе n8n попросит создать аккаунт администратора.

### 9.6. Фронтенд

Откройте в браузере: `https://app.ai.company.ru` (или `http://<IP>:80`)

### 9.7. Автоматическая проверка

```bash
chmod +x scripts/health-check.sh
./scripts/health-check.sh
```

---

## 10. Настройка автозапуска и бэкапов

### 10.1. Автозапуск Docker при перезагрузке

Docker с `restart: unless-stopped` автоматически поднимает контейнеры после ребута. Убедитесь, что Docker в автозагрузке:

```bash
sudo systemctl enable docker
```

### 10.2. Настройка бэкапов

```bash
chmod +x scripts/backup.sh

# Тестовый запуск
./scripts/backup.sh

# Настройка ежедневного бэкапа в 3:00
crontab -e
```

Добавьте строку:

```
0 3 * * * /data/dedicated_server/scripts/backup.sh >> /var/log/ai-backup.log 2>&1
```

### 10.3. Мониторинг GPU

Установите `nvtop` для визуального мониторинга:

```bash
sudo apt install -y nvtop
nvtop
```

---

## Быстрая шпаргалка

```bash
# Подключение
ssh deploy@<IP>

# Статус всех сервисов
cd /data/dedicated_server && docker compose ps

# Логи конкретного сервиса
docker compose logs -f gpt-oss-120b

# Перезапуск одного сервиса
docker compose restart gpt-oss-120b

# Остановка всего
docker compose down

# Запуск всего
docker compose up -d

# GPU мониторинг
nvidia-smi
nvtop

# Обновление платформы
git pull
docker compose pull
docker compose up -d
```

---

*Последнее обновление: март 2026*

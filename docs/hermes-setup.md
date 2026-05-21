# Hermes — Telegram AI Agent

## Обзор

Hermes — Telegram-бот с 16 инструментами на DeepSeek v4, управляющий сервером и инфраструктурой @eddytester.

**Стек:** Python 3.12, DeepSeek API (function calling), python-telegram-bot, systemd, SQLite, PostgreSQL (Honcho)

## Архитектура

### Инструменты (16 total)

| Группа | Инструменты | Назначение |
|---|---|---|
| **Инженерия (8)** | bash, read_file, write_file, read_agent_outputs, load_skill, practicum_health, practicum_deploy, suggest_features | Сервер, деплой, баги/фичи Практикум |
| **Здоровье (5)** | health_metric, health_nutrition, health_workout, health_profile, health_progress | Фитнес-трекер, питание, графики |
| **Java Coach (3)** | java_explain, java_review, java_exercise | Обучение Java по Obsidian-программе |

### Система

- **Сервер:** 77.73.135.110 (8GB RAM, 4 ядра, Ubuntu 24.04, Timeweb)
- **Демон:** systemd — `/etc/systemd/system/hermes.service` (Restart=always + multi-user.target)
- **Базы:** CouchDB (сессии), SQLite `/root/hermes/health.db` (здоровье), Honcho/PostgreSQL (memory)
- **Исходник:** `/root/hermes/hermes_bot.py` (~1500 строк)
- **Скилы:** `/root/hermes/skills/*.md` — bsa, practicum, channel, server, obsidian, agents, health, java

### Самоулучшение

Hermes может редактировать свои скилы (.md) без спроса. Новые инструменты (правка hermes_bot.py) — только после подтверждения пользователя.

## Honcho Memory (Plastic Labs)

### Что это

Memory-инфраструктура для AI-агентов. Хранит историю, делает background reasoning (выводы из диалогов), гибридный поиск (BM25 + векторы), отдаёт контекст для промпта.

### Развёртывание

```
docker compose -f /root/honcho/docker-compose.yml up -d
```

- **Порты:** localhost:8001 (непубличный, 8000 занят blog-analysis webhook)
- **Сервисы:** Honcho API, Deriver (background worker), PostgreSQL (pgvector), Redis (cache)
- **LLM:** DeepSeek chat для reasoning (OpenAI-compatible, `api.deepseek.com/v1`)
- **Эмбеддинги:** отключены (`EMBED_MESSAGES=false`) — OpenRouter/Cloudflare недоступен с Timeweb
- **Интеграция:** `honcho-ai` SDK → `hermes_honcho.py` — пишет сообщения, получает контекст

### Провайдеры

- **Reasoning:** DeepSeek chat (ключ из /root/hermes/.env)
- **Embeddings:** отключены (BM25 текстовый поиск вместо векторного)

## Установка и обслуживание

### Первая установка

```bash
# Клонировать Honcho
cd /root && git clone --depth 1 https://github.com/plastic-labs/honcho.git
cd honcho && cp docker-compose.yml.example docker-compose.yml
# Создать .env
docker compose up -d --build
```

### Запуск/остановка Hermes

```bash
systemctl start hermes
systemctl stop hermes
systemctl restart hermes
systemctl status hermes
journalctl -u hermes -n 50 --no-pager
```

### Логи

- Hermes: `journalctl -u hermes -f`
- Honcho: `docker compose -f /root/honcho/docker-compose.yml logs -f`

### Пути на сервере

| Путь | Назначение |
|---|---|
| `/root/hermes/hermes_bot.py` | Основной код бота |
| `/root/hermes/hermes_honcho.py` | Honcho memory integration |
| `/root/hermes/skills/*.md` | Контекстные скилы |
| `/root/hermes/health.db` | Данные здоровья (SQLite) |
| `/root/hermes/lib/charts.py` | Pillow-графики |
| `/root/honcho/` | Honcho memory server |
| `/root/blog-analysis/` | Репозиторий проекта |
| `/root/obsidian-vault/eddytester/` | Obsidian vault |
| `/root/java-learning/` | Java-примеры и код |
| `/etc/systemd/system/hermes.service` | systemd unit |

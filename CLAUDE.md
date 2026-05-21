# blog-analysis — CLAUDE.md

Автономная система AI-агентов для анализа, контент-планирования и монетизации Telegram-блога [@eddytester](https://t.me/eddytester) (QA/API-тестирование). Работает на сервере 24/7.

---

## Архитектура

```
         ┌──────────────────────────────────────────────┐
         │               requests_listener              │
         │  (cron: каждые 2 мин)                        │
         │  читает obsidian-vault/inbox.md              │
         │  находит задачи (!) → пробуждает BSA         │
         └──────────────┬───────────────────────────────┘
                        │
    ┌───────────────────┼───────────────────┐
    │                   │                   │
    ▼                   ▼                   ▼
┌─────────────┐ ┌──────────────┐ ┌──────────────────┐
│   BSA Chat  │ │   Telegram  │ │    Orchestrator   │
│ (DeepSeek + │ │ Bot (прямое │ │  ┌──────────────┐ │
│  function   │ │ общение с   │ │  │  PM Agent    │ │
│  calling)   │ │ BSA из TG)  │ │  │  Content Mgr │ │
│ bsa_chat.py │ │ telegram_   │ │  │  Gateway     │ │
│             │ │ bot.py      │ │  └──────────────┘ │
└──────┬──────┘ └──────┬──────┘ └──────────────────┘
       │               │
       ▼               ▼
┌──────────────────────────────────────────────────────┐
│               Nightly Pipeline (3AM)                  │
│  SCOUT → EDUCATOR → email_digest → outbox cleanup    │
│  nightly.sh                                          │
└──────────────────────────────────────────────────────┘
       │               │
       ▼               ▼
┌─────────────┐ ┌──────────────┐
│   Morning   │ │   Evening    │
│   Pulse     │ │   Pulse      │
│ (5AM cron)  │ │ (5PM cron)   │
└─────────────┘ └──────────────┘
```

### Агенты

| Агент | Файл | Назначение |
|-------|------|------------|
| **BSA Chat** | `agents/bsa/bsa_chat.py` | DeepSeek-чат с function calling. Терминал или триггер от listener |
| **BSA Agent** | `agents/bsa/bsa_agent.py` | Еженедельный стратегический аудит (State of Business + Strategic Bets) |
| **PM Agent** | `agents/orchestrator/pm_agent.py` | Оценка задач, классификация, scan_proposals |
| **Content Manager** | `agents/orchestrator/content_manager.py` | Управление контент-планом |
| **SCOUT** | `agents/scout/scanner.py`, `api_scout.py` | Разведка конкурентов, тренды QA-ниши |
| **ANALYST** | `agents/analyst/analyzer.py` | Контент-аналитика |
| **EDUCATOR** | `agents/educator/educator.py` | Генерация образовательных материалов |
| **DIGEST** | `agents/email_digest.py` | Ежедневный дайджест → email |
| **Researcher** | `agents/researcher.py` | Автономный веб-исследователь |
| **Requests Listener** | `agents/requests_listener.py` | Наблюдатель за Obsidian, пробуждает BSA |

---

## Окружение и ключи

### Chain загрузки (везде одинаковый):

1. **Bitwarden** — `BWVault()` из `agents/orchestrator/bw_helper.py`
   - Подключается к `bw serve` (localhost:8087)
   - Сессия: `/root/.bw_env` (файл с `BW_SESSION=...`) или env `BW_SESSION`
   - Ищет запись по имени (substring match)
2. **`.env`** — `agents/.env` (уже в .gitignore)
3. **`os.environ`**

### Переменные среды

| Переменная | Где используется | Bitwarden entry name |
|---|---|---|
| `DEEPSEEK_API_KEY` | Все агенты (DeepSeek API) | "DeepSeek API Key" |
| `RESEND_API_KEY` | `lib/mailer.py` | "Resend API Key" |
| `UNISENDER_API_KEY` | `lib/mailer.py` | "Unisender API Key" |
| `MAIL_USER` / `MAIL_PASS` | `lib/mailer.py` (SMTP) | — |
| `MAIL_FROM` / `MAIL_TO` | `lib/mailer.py` | — |
| `TG_TOKEN` | `agents/bsa/telegram_bot.py` | Файл `agents/bsa/.tg_token` |
| `TG_CHAT_ID` | `agents/bsa/telegram_bot.py` | Файл `agents/bsa/.tg_chat_id` |
| `BW_SESSION` | `bw_helper.py` | — (сессия Bitwarden CLI) |

Обрати внимание: `TG_TOKEN` и `TG_CHAT_ID` — это **отдельные файлы** в `agents/bsa/.tg_token` и `agents/bsa/.tg_chat_id`, не env-переменные (но код может читать и оттуда).

---

## Ключевые файлы

### Код (меняем, коммитим)

Файлы в `main` ветке. `agents/bsa/`, `agents/orchestrator/`, `lib/` — основная логика.

Не трогай без необходимости: `.bak` файлы, `identity.md`, промпты (txt).

### Runtime state (НЕ коммитим, см. .gitignore)

| Файл | Назначение |
|---|---|
| `agents/bsa/backlog.json` | Персистентный бэклог (создаётся backlog.py) |
| `agents/bsa/incoming/` | Входящие сообщения Telegram |
| `agents/bsa/dump.md` | Runtime dump |
| `agents/email_archive/` | Архив отправленных писем |
| `agents/scout/raw/` | Результаты сканирования (JSON) |
| `agents/scout/reports/` | Сгенерированные отчёты |
| `agents/scout/report_counter.txt` | Счётчик отчётов |
| `agents/dev/` | Артефакты dev-агента |
| `data/webhook_processed.json` | Webhook state |
| `agents/orchestrator/pm_context.json` | Контекст PM Agent |
| `agents/orchestrator/pm_history.json` | История PM Agent |
| `agents/bsa/bsa_thread.json` | Тред BSA |
| `agents/bsa/.bsa.lock` | Lock-файл |

### Obsidian vault (ОТДЕЛЬНЫЙ git-репозиторий)

Путь на сервере: `/root/obsidian-vault/`

Это **не часть blog-analysis**. Свой собственный git-репозиторий.

| Файл | Назначение |
|---|---|
| `inbox.md` | Эдди пишет запросы → listener находит задачи по `!` |
| `outbox.md` | BSA пишет ответы. Формат: `**Ты:**` / `**Bizzy:**` |
| `requests.md` | (не всегда присутствует) |

Discord-формат в inbox/outbox:
- `ээ вопрос!` — продолжить тред
- `эээ вопрос!` — новый тред (сброс контекста)
- Без `!` в конце — Эдди ещё печатает, не отвечать

---

## BSA Function Calling

### Инструменты (определены в `bsa_chat.py`)

Все инструменты, доступные BSA:

| Инструмент | Назначение |
|---|---|
| `read_file` | Чтение файлов из Obsidian vault и проекта |
| `write_file` | Запись/редактирование файлов |
| `list_dir` | Список файлов в директории |
| `glob_files` | Поиск файлов по glob-паттерну |
| `run_researcher` | Запуск Researcher агента (веб-поиск) |
| `run_content_manager` | Запуск Content Manager агента |
| `run_pm_agent` | Запуск PM Agent (оценка/классификация) |
| `run_agent` | Запуск произвольного агента (scout, educator и т.д.) |
| `send_email` | Отправка email через mailer |
| `update_status` | Обновление статуса задач в requests.md |
| `shorten_task` | Сокращение текста задачи |
| `check_channel` | Проверка постов Telegram-канала @eddytester |
| `backlog` | Управление бэклогом (add/done/summary/ip) |
| `propose_bug` | Создание предложения по багу для practicum API |

> `discuss_reply` — специальный инструмент только для discuss mode (запись в outbox.md).
> Определён в TOOL_MAP, но может не быть в TOOLS — injected при необходимости.

`TOOL_MAP` и `TOOLS` живут в `bsa_chat.py`. При добавлении нового инструмента нужно обновить оба списка.

### Агенты (внешние, вызываются через subprocess)

| Команда | Файл |
|---|---|
| `python3 agents/orchestrator/content_manager.py` | Управление контент-планом |
| `python3 agents/orchestrator/pm_agent.py assess "..."` | Оценка задачи |
| `python3 agents/orchestrator/pm_agent.py --scan-proposals` | Сканирование предложений |
| `python3 agents/orchestrator/pm_agent.py --classify "..."` | Классификация |
| `python3 agents/scout/scanner.py` | Запуск SCOUT |
| `python3 agents/educator/educator.py daily` | Генерация поста |
| `python3 agents/bsa/channel_checker.py` | Проверка канала |

---

## Сервер (217.144.185.210)

### Пути

| Что | Путь |
|---|---|
| Репозиторий | `/root/blog-analysis/` |
| Obsidian vault | `/root/obsidian-vault/` |
| Логи | `/tmp/requests_listener.log`, `/root/blog-analysis/logs/bsa.log` |
| .env | `/root/blog-analysis/agents/.env` |
| Bitwarden env | `/root/.bw_env` |
| Telegram secrets | `/root/blog-analysis/agents/bsa/.tg_token`, `.../.tg_chat_id` |

### Сервер Hermes (77.73.135.110)

Сервер для Hermes-агента (Timeweb, 8GB RAM, 4 ядра, Ubuntu 24.04).

| Что | Путь |
|---|---|
| Hermes бот | `/root/hermes/hermes_bot.py` (systemd, `hermes.service`) |
| Скилы | `/root/hermes/skills/*.md` |
| Health DB | `/root/hermes/health.db` (SQLite) |
| Honcho | `/root/honcho/` (Docker Compose, порт 8001) |
| Java программа | `/root/obsidian-vault/eddytester/Java/` (18 недель) |
| Java код | `/root/java-learning/` |

SSH: `ssh root@77.73.135.110` (пароль в Bitwarden)

### Cron (crontab -l)

| Расписание | Команда |
|---|---|
| `*/2 * * * *` | requests_listener.py (наблюдение за Obsidian) |
| `*/10 * * * *` | git pull/commit/push Obsidian vault |
| `0 5 * * *` | morning_pulse.py (утренний дайджест) |
| `0 17 * * *` | evening_pulse.py (вечерний дайджест) |
| `*/5 * * * *` | watchdog.sh |
| `0 9 * * *` | scout scanner.py |
| `30 9 * * *` | dev scanner.py |
| `30 10 * * *` | backlog.py — импорт scout/scanner и sync |
| `30 10 * * *` | pm_agent.py --scan-proposals |
| `0 3 * * *` | nightly.sh (основной пайплайн: SCOUT → EDUCATOR → DIGEST) |

---

## DeepSeek API

Все агенты общаются с DeepSeek API через **curl** (subprocess), не через Python SDK.

URL: `https://api.deepseek.com/chat/completions`
Модели: `deepseek-v4-flash` (основная), `deepseek-chat` (fallback в evening_pulse)

Аргументы: `temperature` (0.3-0.5), `max_tokens` (2048-16384), системный промпт + user prompt.

Если `curl` недоступен — некоторые файлы используют `requests` как fallback (с `pip install requests`).

---

## Запуск локально (macOS/Linux)

```bash
# 1. Клонировать
git clone git@github.com:overgoer/blog-analysis.git
cd blog-analysis

# 2. Убедиться, что curl доступен (нужен для DeepSeek API)
which curl

# 3. Установить ключ (один из вариантов)
export DEEPSEEK_API_KEY="sk-..."
# или создать agents/.env с DEEPSEEK_API_KEY=...

# 4. Запустить BSA в интерактивном режиме
python3 agents/bsa/bsa_chat.py

# 5. Или запустить пайплайн
python3 agents/email_digest.py --send
```

Для полного функционала нужен доступ к Obsidian vault и Bitwarden (только на сервере).

---

## Гит-стратегия

- `main` — стабильная ветка, всё что на сервере
- Остальные ветки — feature/fix, мёржатся через fast-forward
- Runtime state не коммитится (.gitignore)
- Obsidian vault — отдельный репозиторий

---

## Что не входит в этот репозиторий

- **Obsidian vault** (`/root/obsidian-vault/`) — отдельный git
- **java-tutor** (`/root/java-tutor/`) — другой проект (упоминается в crontab), теперь заменён Hermes
- **Hermes** (`/root/hermes/`) — Telegram AI-агент на DeepSeek v4, 16 инструментов, systemd
  - `hermes_bot.py` — основной код (Python, python-telegram-bot)
  - `health_db.py` — SQLite для здоровья (7 таблиц)
  - `hermes_honcho.py` — Honcho memory integration (Docker, порт 8001)
  - `skills/` — контекстные скилы (.md)
- **Honcho** (`/root/honcho/`) — Memory server (Plastic Labs, Docker Compose, порт 8001)
- **Продукты** (v0-test-api, free-trial-api, api-practicum-bot) — Node.js проекты на Timeweb

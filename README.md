# blog-analysis

Система автономных AI-агентов для анализа, контент-планирования и монетизации Telegram-блога [@eddytester](https://t.me/eddytester) (QA/API тестирование).

Работает на Linux-сервере 24/7 — cron-пайплайны, Telegram-бот, DeepSeek API.

## Стек

- **Язык**: Python 3 (stdlib + `requests`), Bash, JavaScript (Cloudflare Worker)
- **AI**: DeepSeek API (`deepseek-v4-flash`, `deepseek-chat`) через curl subprocess
- **Инфраструктура**: Linux-сервер, cron, Git/GitHub, Cloudflare Email Worker
- **Email**: SMTP + Resend API + Unisender API (резерв для РФ)
- **Хранилище**: Obsidian vault (отдельный git-репозиторий на сервере)
- **Секреты**: Bitwarden CLI (`bw serve`) с fallback на `.env`

## Архитектура агентов

### Ядро

| Агент | Файл | Назначение |
|-------|------|------------|
| **BSA Chat** | `agents/bsa/bsa_chat.py` | DeepSeek-чат с function calling (терминал или триггер) |
| **BSA Agent** | `agents/bsa/bsa_agent.py` | Еженедельный стратегический аудит |
| **PM Agent** | `agents/orchestrator/pm_agent.py` | Оценка задач, классификация, сканирование предложений |
| **Content Manager** | `agents/orchestrator/content_manager.py` | Управление контент-планом |
| **SCOUT** | `agents/scout/scanner.py`, `api_scout.py` | Разведка конкурентов, тренды QA |
| **ANALYST** | `agents/analyst/analyzer.py` | Контент-аналитика (категоризация, ER, тренды) |
| **EDUCATOR** | `agents/educator/educator.py` | Генерация образовательных материалов |
| **DIGEST** | `agents/email_digest.py` | Ежедневный дайджест с черновиками → email |
| **Researcher** | `agents/researcher.py` | Автономный веб-исследователь |
| **Requests Listener** | `agents/requests_listener.py` | Наблюдатель за Obsidian, пробуждает BSA |

### Telegram & BSA инфраструктура

| Компонент | Файл/Скрипт | Назначение |
|-----------|-------------|------------|
| **Telegram Bot** | `agents/bsa/telegram_bot.py` | Прямое общение с BSA из Telegram |
| **Backlog** | `agents/bsa/backlog.py` | CRUD-бэклог с JSON-персистентностью |
| **Morning Pulse** | `agents/bsa/morning_pulse.py` | Утренний дайджест (5AM) |
| **Evening Pulse** | `agents/bsa/evening_pulse.py` | Вечерний дайджест (5PM) |
| **Channel Checker** | `agents/bsa/channel_checker.py` | Проверка постов канала @eddytester |
| **Watchdog** | `agents/bsa/watchdog.sh` | Мониторинг процессов |

### Библиотеки

| Файл | Назначение |
|------|------------|
| `lib/mailer.py` | Отправка email (SMTP + Resend + Unisender) |
| `lib/obsidian.py` | Работа с Obsidian vault |
| `lib/git-sync.sh` | Синхронизация git-репозиториев |
| `lib/obsidian_sync.sh` | Синхронизация Obsidian vault |

## Пайплайны

| Пайплайн | Расписание | Цепочка |
|----------|------------|---------|
| **Ночной** | 3:00 AM | SCOUT → EDUCATOR → DIGEST → email → outbox cleanup |
| **Утренний пульс** | 5:00 AM | morning_pulse.py → Telegram |
| **Вечерний пульс** | 5:00 PM | evening_pulse.py → Telegram |
| **Obsidian-триггер** | Каждые 2 мин | requests_listener.py читает inbox.md, находит задачи (!), пробуждает BSA |
| **Sync vault** | Каждые 10 мин | git pull/commit/push Obsidian vault |
| **Скаутинг** | 9:00 AM | scout/scanner.py |
| **Watchdog** | Каждые 5 мин | watchdog.sh проверяет процессы |
| **Бэклог** | 10:30 AM | backlog.py — импорт scout и сканеров |

## Начало работы

### Требования

- Python 3.10+
- curl (для DeepSeek API)
- DeepSeek API ключ

### Установка

```bash
git clone git@github.com:overgoer/blog-analysis.git
cd blog-analysis
# Опционально: requests для fallback в некоторых модулях
pip install requests
```

### Ключи (порядок загрузки)

1. **Bitwarden** — `bw serve` (localhost:8087), ищет запись по имени
2. **`.env`** — `agents/.env` (уже в .gitignore)
3. **Переменные окружения**

Подробнее — в [CLAUDE.md](CLAUDE.md).

### Запуск

```bash
# BSA в интерактивном режиме
python3 agents/bsa/bsa_chat.py

# BSA в режиме триггера (однократный запуск)
python3 agents/bsa/bsa_chat.py --mode trigger

# PM Agent — оценка задачи
python3 agents/orchestrator/pm_agent.py "dev: сделай CI/CD"

# PM Agent — классификация
python3 agents/orchestrator/pm_agent.py --classify "напиши тесты для JWT"

# PM Agent — сканирование предложений
python3 agents/orchestrator/pm_agent.py --scan-proposals

# Requests Listener (демон)
python3 agents/requests_listener.py

# Ежедневный дайджест
python3 agents/email_digest.py

# Стратегический аудит BSA
python3 agents/bsa/bsa_agent.py

# Telegram бот
python3 agents/bsa/telegram_bot.py

# Morning/Evening Pulse
python3 agents/bsa/morning_pulse.py --send
python3 agents/bsa/evening_pulse.py --send

# Полный ночной пайплайн
bash agents/nightly.sh
```

## Структура директорий

```
├── agents/               # AI-агенты
│   ├── analyst/          # контент-аналитика
│   ├── bsa/              # Bizzy Smart Assistant (чат, бот, pulses, backlog)
│   ├── dev/              # dev-сканер
│   ├── digest/           # digest-агент
│   ├── educator/         # генерация материалов
│   ├── news/             # новостной агент
│   ├── orchestrator/     # PM Agent, Content Manager, Gateway
│   ├── scout/            # разведка конкурентов
│   ├── webhook/          # Cloudflare Worker
│   ├── bsa_agent.py      # стратегический аудит
│   ├── email_digest.py   # email-дайджест
│   ├── nightly.sh        # ночной пайплайн
│   ├── query.py          # запрос к агентам
│   ├── requests_listener.py  # Obsidian-триггер
│   └── researcher.py     # веб-исследователь
├── data/                 # данные канала (не коммитятся)
├── lib/                  # библиотеки (mailer, obsidian, git-sync)
├── CLAUDE.md             # документация для AI
├── .env.example          # шаблон переменных окружения
├── requirements.txt      # Python-зависимости
├── .gitignore            # secrets, runtime, IDE
├── MASTER_PLAN.md        # стратегический план
├── BACKLOG.md            # бэклог задач
└── README.md             # этот файл
```

## Лицензия

Private — @eddytester.

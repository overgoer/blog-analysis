# blog-analysis

Система автономных AI-агентов для анализа, контент-планирования и монетизации Telegram-блога [@eddytester](https://t.me/eddytester) (QA/API тестирование).

## Стек

- **Язык**: Python 3, Bash, JavaScript (Cloudflare Worker)
- **Инфраструктура**: Linux-сервер, cron, Git/GitHub, Cloudflare Email Worker, Resend.com API
- **Хранилище**: Obsidian vault (Git-репозиторий для контент-плана и заметок)

## Архитектура агентов

| Агент | Назначение |
|-------|-----------|
| **SCOUT** | Разведка конкурентов, анализ трендов в QA-нише |
| **ANALYST** | Контент-аналитика: категоризация 376+ постов, ER, тренды |
| **EDUCATOR** | Генерация образовательных материалов по backend/API тестированию |
| **DIGEST** | Ежедневный дайджест с 3-4 черновиками постов + email-рассылка |
| **BSA** (Bizzy Smart Assistant) | Веб-чат через DeepSeek API с function calling |
| **DEV** | Мониторинг инфраструктуры и автоматизация |
| **Orchestrator** | Координация и маршрутизация запросов между агентами |

## Пайплайны

- **Ночной** (3:00 AM, `nightly.sh`): SCOUT → EDUCATOR → DIGEST → email-рассылка
- **Obsidian-триггер** (`requests_listener.py`): отслеживает изменения в Obsidian vault, пробуждает BSA для обработки задач
- **Email-вход** (`cloudflare-worker.js`): приём писем через Cloudflare Email → webhook → обработка

## Директории

```
├── agents/          — AI-агенты
│   ├── analyst/     — контент-аналитика
│   ├── bsa/         — Bizzy Smart Assistant (веб-чат)
│   ├── dev/         — автоматизация
│   ├── educator/    — генерация образовательных материалов
│   ├── orchestrator/— координатор агентов
│   ├── scout/       — разведка конкурентов
│   ├── webhook/     — Cloudflare Worker
│   └── email_archive/— архив отправленных писем
├── data/            — данные канала (профиль, сырые посты, контент-план)
├── lib/             — библиотеки (mailer, git-sync, obsidian-sync)
├── MASTER_PLAN.md   — стратегический план (6 фаз)
├── BACKLOG.md       — бэклог задач с приоритетами
└── PLAN_BSA_WEB.md  — план реализации веб-чата
```

## Бизнес-цель

Конверсия аудитории Telegram-блога в платный продукт — **API Practicum**. Система автоматизирует:
- анализ эффективности контента
- генерацию идей для постов
- отслеживание конкурентов
- создание ежедневных дайджестов с черновиками
- координацию контент-стратегии

## Запуск

```bash
# Ночной пайплайн
bash agents/nightly.sh

# Запрос к агентам
python3 agents/query.py "твой вопрос"

# Генерация дайджеста
python3 agents/email_digest.py --send

# Запуск requests_listener
python3 agents/requests_listener.py
```

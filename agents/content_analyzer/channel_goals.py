#!/usr/bin/env python3
"""Channel goals and competitor definitions — used by strategy_review, reporter, and Bizzy."""

# ── Channel identity ────────────────────────────────────────────────────
CHANNEL_NAME = "@eddytester"
CHANNEL_NICHE = "QA / ручное тестирование бэкенда"
CHANNEL_VOICE = "Экспертиза с иронией. Глубокие разборы багов, чек-листы, инструменты. "
"Не гнаться за хайпом, не копировать конкурентов."

# ── Primary goals (P0 first) ────────────────────────────────────────────
GOALS = [
    {"priority": "P0", "name": "Practicum — запуск продаж", "metric": "Первые 10 000₽ выручки"},
    {"priority": "P1", "name": "5000 подписчиков", "metric": "Рост с текущих ~1500"},
    {"priority": "P1", "name": "Охват ~67% от подписчиков за 48ч", "metric": "1000/1500 = 67% за 2 дня"},
    {"priority": "P1", "name": "Экспертность и уважение аудитории", "metric": "Качественные комменты, сохранения"},
    {"priority": "P2", "name": "3 поста в неделю", "metric": "Пн, Ср, Пт — жёсткая норма"},
    {"priority": "P2", "name": ">50% постов с >5 комм", "metric": "Вовлечение через механику"},
]

GOALS_BY_PRIORITY = {g["priority"]: [] for g in GOALS}
for g in GOALS:
    GOALS_BY_PRIORITY[g["priority"]].append(g)

# ── Competitors (all important, each teaches something) ─────────────────
COMPETITORS = {
    "pro": {
        "name": "@qachanell",
        "author": "Русов Артём",
        "strength": "Мастодонт — первый в нише, вся джуновская аудитория у него. "
        "Экспертиза так себе, но продаёт.",
        "learn": "Воронка продаж через контент.",
    },
    "bigtech": {
        "name": "@qabigtech",
        "author": "Лебедев (QA Яндекс)",
        "strength": "Охваты, узнаваемость.",
        "learn": "Приёмы для охватов, заголовки.",
    },
    "protesting": {
        "name": "@protestinginfo",
        "author": "",
        "strength": "Топ-конкурент по охватам.",
        "learn": "Форматы, тайминг, что заходит аудитории.",
    },
    "rvtsakunov_1": {
        "name": "@rvtsakunov",
        "author": "",
        "strength": "Основной канал.",
        "learn": "Контент-стратегия.",
    },
    "rvtsakunov_2": {
        "name": "@rvtsakunov_manual",
        "author": "",
        "strength": "Второй канал",
        "learn": "Формат ручного тестирования.",
    },
    "burning": {
        "name": "@burning_tester",
        "author": "",
        "strength": "Топ по охватам, подача нерелевантна.",
        "learn": "Приёмы вовлечения, заголовки.",
    },
}

PRIMARY_COMPETITORS = ["@qachanell", "@qabigtech", "@protestinginfo", "@rvtsakunov", "@burning_tester"]

# ── Subscriber counts (known / estimated) ───────────────────────────────
# Used to compute reach rate (% of subscribers who viewed).
# Обновляй по мере уточнения данных.
SUBSCRIBERS = {
    "@eddytester": 1500,
    "@qachanell": 5000,      # оценка
    "@qabigtech": 3000,      # оценка
    "@burning_tester": 3000, # оценка
    "@protestinginfo": 5000, # оценка
    "@serious_tester": 5000, # оценка
}

# ── Analysis thresholds ─────────────────────────────────────────────────
CONFIDENCE_THRESHOLDS = {
    "LOW": {"min_samples": 1, "label": "Мало данных"},
    "MEDIUM": {"min_samples": 3, "label": "Тренд намечается"},
    "HIGH": {"min_samples": 5, "label": "Устойчивый паттерн"},
}

ENGAGEMENT_WEIGHTS = {"views": 1, "replies": 3, "forwards": 5}

# Engagement quality: posts that get replies but few forwards → community building
# Posts that get many forwards but few replies → viral but shallow
ENGAGEMENT_QUALITY = {
    "community": {"ratio": "replies > forwards", "label": "Комьюнити-билдинг"},
    "viral": {"ratio": "forwards > replies", "label": "Вирусный охват"},
    "read_only": {"ratio": "views >> replies + forwards", "label": "Читают, но не реагируют"},
}

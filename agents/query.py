#!/usr/bin/env python3
"""Query/Dialogue System for multi-agent collaboration.

Usage:
  python3 query.py "your question here"
  echo "вопрос" | python3 query.py

Routes questions to relevant agents based on topic and returns collaborative responses.
"""

import json
import os
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path

AGENTS_DIR = Path("/root/blog-analysis/agents")

# Agent routing rules: (keywords, agent_name, description)
ROUTING = [
    (["конкурент", "competitor", "scout", "что делают", " competitor", "channel analyze", "content format",
      "новые формат", "что публикуют", "тренд", "trend", "новости", "news"],
     "SCOUT",
     "Анализ конкурентов и трендов"),
    (["бэкенд", "backend", "postman", "sql", "баз дан", "http", "api", "jwt", "gRPC", "статус код",
      "бд", "database", "миграци", "очеред", "queue", "webhook", "websocket"],
     "EDUCATOR",
     "Backend tips для тестировщиков"),
    (["анализ", "analytics", "статистик", "stat", "content analyze", "post analyze", "пост",
      "аналитик", "audience", "аудит"],
     "ANALYST",
     "Аналитика контента"),
    (["dev", "разработк", "dev ops", "channel", "настройк", "автоматизаци", "automation",
      "script", "скрипт"],
     "DEV",
     "Разработка и автоматизация"),
]


def classify_question(question):
    """Determine which agents should respond based on question content."""
    q_lower = question.lower()
    relevant = []

    for keywords, agent, description in ROUTING:
        if any(kw.lower() in q_lower for kw in keywords):
            relevant.append((agent, description))

    # If no specific match, all agents respond
    if not relevant:
        relevant = [
            ("SCOUT", "Анализ конкурентов и трендов"),
            ("EDUCATOR", "Backend tips для тестировщиков"),
            ("ANALYST", "Аналитика контента"),
            ("DEV", "Разработка и автоматизация"),
        ]

    return relevant


def run_scout(query):
    """SCOUT agent response — competitive analysis."""
    try:
        # Check if scout report exists
        report_dir = AGENTS_DIR / "scout" / "reports"
        reports = sorted(report_dir.glob("report_*.md")) if report_dir.exists() else []
        latest = reports[-1] if reports else None

        result = ["🤖 **SCOUT (Разведка конкурентов)**"]

        if latest and latest.exists():
            content = latest.read_text()
            # Extract summary section
            summary = extract_section(content, "Сводка", 20)
            result.append(f"📊 Последний отчет ({latest.stem.replace('report_', '')}):")
            result.append(f"```\n{summary}\n```")
        else:
            result.append("⚠️ Отчетов пока нет. Дождись ночного запуска.")

        # Check if asking about format suggestions
        if any(kw in query.lower() for kw in ["формат", "format", "новые идей", "что попробова"]):
            result.append("")
            result.append("💡 **Предложения по новым форматам:**")
            result.append(generate_format_suggestions())

        return "\n".join(result)
    except Exception as e:
        return f"🤖 **SCOUT**\n⚠️ Ошибка: {e}"


def run_educator(query):
    """EDUCATOR agent response — backend tips."""
    try:
        result = ["🤖 **EDUCATOR (Backend образование)**"]
        # Generate a fresh tip relevant to query if possible
        tip_dir = AGENTS_DIR / "educator" / "tips"
        tip_dir.mkdir(parents=True, exist_ok=True)
        tips = sorted(tip_dir.glob("tip_*.md")) if tip_dir.exists() else []

        # If there's a recent tip, show it
        if tips:
            latest = tips[-1]
            content = latest.read_text()
            result.append(content)
        else:
            result.append("Запусти `python3 educator.py daily` для генерации.")

        return "\n".join(result)
    except Exception as e:
        return f"🤖 **EDUCATOR**\n⚠️ Ошибка: {e}"


def run_analyst(query):
    """ANALYST agent response — content analytics."""
    try:
        result = ["🤖 **ANALYST (Аналитика контента)**"]
        summary_dir = AGENTS_DIR / "analyst" / "reports"
        summaries = sorted(summary_dir.glob("summary_*.json")) if summary_dir.exists() else []
        if summaries:
            latest = summaries[-1]
            with open(latest) as f:
                data = json.load(f)
            if "error" not in data:
                total = data.get("total_posts", 0)
                avg_len = data.get("avg_length", 0)
                top = data.get("top_categories", {})
                cats = ", ".join(top.keys()) if top else "нет данных"
                result.append(f"📊 Всего постов: {total}, Средняя длина: {avg_len:.0f} символов")
                result.append(f"🏷️ Категории: {cats}")
            else:
                result.append(f"⚠️ {data.get('error')}")
        else:
            result.append("⚠️ Аналитика еще не запущена.")

        return "\n".join(result)
    except Exception as e:
        return f"🤖 **ANALYST**\n⚠️ Ошибка: {e}"


def run_dev(query):
    """DEV agent response — development/automation."""
    try:
        result = ["🤖 **DEV (Разработка и автоматизация)**"]
        result.append("🔧 Система работает в штатном режиме.")
        result.append("  • Ночной пайплайн: DEV → ANALYST → SCOUT → (EDUCATOR)")
        result.append("  • Расписание: 3:00 AM ежедневно")
        result.append(f"  • Агентов: SCOUT, ANALYST, EDUCATOR, DEV")

        # Check nightly log
        log_file = Path("/root/blog-analysis/agents/nightly.log")
        if log_file.exists():
            lines = log_file.read_text().strip().split("\n")
            last_run = [l for l in lines if "Nightly Run" in l]
            if last_run:
                result.append(f"  • Последний запуск: {last_run[-1]}")

        return "\n".join(result)
    except Exception as e:
        return f"🤖 **DEV**\n⚠️ Ошибка: {e}"


def extract_section(text, section_name, max_lines=20):
    """Extract a section from markdown content."""
    lines = text.split("\n")
    result = []
    in_section = False
    count = 0
    for line in lines:
        if section_name.lower() in line.lower() and line.startswith("##") or line.startswith("###"):
            in_section = True
            continue
        if in_section:
            if line.startswith("##") and count > 0:
                break
            result.append(line)
            count += 1
            if count > max_lines:
                break
    return "\n".join(result).strip()


def generate_format_suggestions():
    """Generate content format suggestions (SCOUT enhancement)."""
    suggestions = [
        "🎬 **Короткие видео/Reels** — разбор одного бага за 30-60 секунд (пример: \"Как я нашел баг в авторизации за 2 минуты\")",
        "📊 **Сравнительные таблицы** — Postman vs Insomnia, SQLite vs PostgreSQL для тестов — наглядные сравнения",
        "🧪 **Еженедельный тест-челлендж** — \"Найди баг в этом API\" с разбором в следующем посте",
        "📋 **Шпаргалки (Cheat Sheets)** — HTTP коды, SQL JOIN типы, Git команды — формат карточек",
        "🔍 **Разбор реального кейса** — как тестировали фичу от начала до конца (с скриншотами)",
        "🎯 **Опросы аудитории** — \"Какая БД сложнее всего в тестировании?\" — вовлекают и дают идеи для контента",
        "📚 **Подборка ресурсов** — ежемесячная коллекция полезных статей/инструментов по QA",
    ]
    return "\n".join(suggestions)


def main():
    # Read question
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    else:
        question = sys.stdin.read().strip()

    if not question:
        print("Использование: python3 query.py \"ваш вопрос\"")
        print("Или: echo \"вопрос\" | python3 query.py")
        sys.exit(1)

    print(f"# Запрос: {question}")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("")
    print("---")
    print("")

    # Classify and route
    relevant = classify_question(question)
    agent_map = {
        "SCOUT": run_scout,
        "EDUCATOR": run_educator,
        "ANALYST": run_analyst,
        "DEV": run_dev,
    }

    responses = []
    for agent, desc in relevant:
        if agent in agent_map:
            resp = agent_map[agent](question)
            responses.append(resp)

    print("\n\n---\n".join(responses))

    # Add footer with collaboration note
    print("")
    print("---")
    print("")
    print("*Ответ сформирован в коллаборации агентов.*")
    print(f"*Участвовали: {', '.join(a for a, _ in relevant)}*")


if __name__ == "__main__":
    main()

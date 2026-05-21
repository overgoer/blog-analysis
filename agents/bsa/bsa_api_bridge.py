#!/usr/bin/env python3
"""
BSA API Bridge — мост между BSA-стратегией и API-репозиториями Practicum.

Генерирует API Improvement Suggestions на стыке:
  (1) последних постов из content_map_index.json
  (2) бэклога постов из стратегии
  (3) текущего состояния API (v0-test-api + free-trial-api)

Запуск:
  python3 bsa_api_bridge.py                          # полный прогон
  python3 bsa_api_bridge.py --dry-run                # тест без сохранения
  python3 bsa_api_bridge.py --quick                  # только свежие посты (7 дней)

Результат: пишет в Obsidian vault файл API_SUGGESTIONS_YYYY-MM-DD.md
           и обновляет API_IMPROVEMENT_TRACKER.md
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Импортируем наши модули
sys.path.insert(0, str(Path(__file__).resolve().parent))
from api_inspector import inspect_api_v0, inspect_api_free_trial, format_inspection_report
from content_inspector import inspect_posts, inspect_strategy_backlog, format_posts_report

BASE = Path(__file__).resolve().parent
ORCH_DIR = BASE.parent / "orchestrator"
AGENTS_DIR = BASE.parent
VAULT_DIR = Path("/root/obsidian-vault/eddytester/Стратегия")
LOG_FILE = Path("/root/blog-analysis/logs/bsa_api_bridge.log")
TRACKER_FILE = VAULT_DIR / "API_IMPROVEMENT_TRACKER.md"

os.makedirs(VAULT_DIR, exist_ok=True)
os.makedirs(LOG_FILE.parent, exist_ok=True)


# ── Logging ─────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── Key Loading ─────────────────────────────────────────────────────────

def load_deepseek_key():
    """Load DeepSeek API key from Bitwarden or .env."""
    try:
        sys.path.insert(0, str(ORCH_DIR))
        from bw_helper import BWVault
        vault = BWVault()
        key = vault.get_password("DeepSeek API Key")
        if key:
            return key
    except Exception:
        pass

    env_file = AGENTS_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    return os.environ.get("DEEPSEEK_API_KEY")


# ── DeepSeek Call ────────────────────────────────────────────────────────

def call_deepseek(system_prompt, user_prompt, temperature=0.5, max_tokens=4096):
    """Call DeepSeek API and return response text."""
    key = load_deepseek_key()
    if not key:
        log("ERROR: No DeepSeek API key available")
        return None

    payload = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    })

    try:
        r = subprocess.run(
            ["curl", "-s", "https://api.deepseek.com/chat/completions",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, text=True, timeout=120,
        )
        resp = json.loads(r.stdout)
        return resp["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"DeepSeek call failed: {e}")
        return None


# ── Prompt Building ─────────────────────────────────────────────────────

def build_bridge_prompt(api_v0_report, api_free_report, posts_report, backlog_text):
    """Строит промпт для DeepSeek на генерацию API Improvement Suggestions."""

    system = """Ты — BSA (Business Strategy Agent), стратег экосистемы @eddytester.

Твоя задача: на стыке (1) контента канала, (2) стратегических целей и (3) текущего состояния API Practicum — предложить 2-3 улучшения API, которые одновременно:
- Дают полезный контент для канала @eddytester
- Расширяют платформу обучения для студентов Practicum
- Работают на стратегические цели (популяризация, монетизация, обучение)

## Принципы
- Не предлагай "ещё один баг" или "ещё один эндпоинт" в отрыве от контента
- Каждое предложение должно иметь триггер из реального поста или контент-плана
- Оценивай сложность: P0 (срочно), P1 (важно), P2 (можно отложить)
- Думай как CEO + контент-мейкер одновременно
- Учитывай, что всё делает соло-основатель (Эдди) — время критично

## Формат ответа (только JSON, без markdown)
{
  "generated_at": "YYYY-MM-DD",
  "suggestions": [
    {
      "id": 1,
      "title": "Краткое название улучшения",
      "trigger_post": "Какой пост/контент стал триггером",
      "api_repo": "v0-test-api | free-trial-api | оба",
      "description": "Что предлагается сделать в API",
      "strategic_alignment": "Как это связано с монетизацией/популяризацией/обучением",
      "complexity": "P0 | P1 | P2",
      "content_angle": "Пример контента, который из этого выйдет",
      "content_brief": "Краткий бриф для content_manager: заголовок, угол, ключевые точки"
    }
  ]
}"""

    user = f"""Проанализируй текущее состояние API и контента, предложи 2-3 улучшения.

## Текущая дата
{datetime.now().strftime('%Y-%m-%d')}

## Состояние API-репозиториев

{api_v0_report}

{api_free_report}

## Последние посты (за 30 дней)
{posts_report}

## Бэклог постов из стратегии
{backlog_text[:2000] if backlog_text else 'Нет данных'}

## Стратегические цели (из pm_context.json)
- Популяризация Telegram-канала @eddytester и блога
- Монетизация: продажа доступа к API Practicum
- Обучение: платформа для джунов с реальными багами
- Контент: 2-3 поста в неделю с практической ценностью

Сгенерируй 2-3 API Improvement Suggestions в формате JSON."""

    return system, user


# ── Saving ──────────────────────────────────────────────────────────────

def save_suggestions(suggestions_data):
    """Сохраняет предложения в Obsidian vault."""
    if not suggestions_data or "suggestions" not in suggestions_data:
        log("No suggestions to save")
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    filename = VAULT_DIR / f"API_SUGGESTIONS_{today}.md"

    lines = []
    lines.append(f"# 🏗 API Improvement Suggestions — {today}")
    lines.append("")
    lines.append(f"**Сгенерировано:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("**Источник:** BSA API Bridge")
    lines.append("")
    lines.append("---")
    lines.append("")

    for s in suggestions_data["suggestions"]:
        lines.append(f"## {s.get('id', '?')}. {s.get('title', 'Без названия')}")
        lines.append("")
        lines.append(f"**Репозиторий:** {s.get('api_repo', '?')}")
        lines.append(f"**Сложность:** {s.get('complexity', '?')}")
        lines.append("")
        lines.append(f"**Триггер:** {s.get('trigger_post', '—')}")
        lines.append("")
        lines.append(f"**Описание:** {s.get('description', '—')}")
        lines.append("")
        lines.append(f"**Стратегическая связь:** {s.get('strategic_alignment', '—')}")
        lines.append("")
        lines.append(f"**Контент-угол:** {s.get('content_angle', '—')}")
        lines.append("")
        lines.append(f"**Бриф для content_manager:**")
        lines.append(f"> {s.get('content_brief', '—')}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("> Статус: предложено → принято/отклонено → сделано → опубликовано")
    lines.append("> Отмечай статус в API_IMPROVEMENT_TRACKER.md")

    with open(filename, "w") as f:
        f.write("\n".join(lines))

    log(f"Saved suggestions to: {filename}")
    return filename


def update_tracker(suggestions_data):
    """Добавляет новые предложения в трекер."""
    if not suggestions_data or "suggestions" not in suggestions_data:
        return

    today = datetime.now().strftime("%Y-%m-%d")

    if not TRACKER_FILE.exists():
        content = """# 📊 API Improvement Tracker

**Предложено → Принято → Сделано → Опубликовано**

| # | Дата | Предложение | Репозиторий | Сложность | Статус | Пост |
|---|---|---|---|---|---|---|
"""
        TRACKER_FILE.write_text(content)

    existing = TRACKER_FILE.read_text()

    new_rows = []
    for s in suggestions_data["suggestions"]:
        title = s.get("title", "?").replace("|", "/")
        repo = s.get("api_repo", "?")
        complexity = s.get("complexity", "?")
        new_rows.append(
            f"| ? | {today} | {title} | {repo} | {complexity} | ⏳ предложено | — |"
        )

    if new_rows:
        if existing.strip().endswith("|"):
            existing += "\n" + "\n".join(new_rows) + "\n"
        else:
            existing += "\n".join(new_rows) + "\n"
        TRACKER_FILE.write_text(existing)
        log(f"Updated tracker: {TRACKER_FILE}")


# ── Main ────────────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    quick = "--quick" in sys.argv

    log("=" * 60)
    log(f"BSA API Bridge started (dry_run={dry_run}, quick={quick})")

    # Шаг 1: Инспектируем API через api_inspector
    log("Inspecting v0-test-api...")
    api_v0 = inspect_api_v0()
    api_v0_report = format_inspection_report(api_v0)
    log(f"  Endpoints: {len(api_v0.get('endpoints', []))}")
    log(f"  Bugs: {len(api_v0.get('bugs', []))}")

    log("Inspecting free-trial-api...")
    api_free = inspect_api_free_trial()
    api_free_report = format_inspection_report(api_free)
    log(f"  Endpoints: {len(api_free.get('endpoints', []))}")
    log(f"  Issues: {len(api_free.get('issues', []))}")

    # Шаг 2: Инспектируем контент через content_inspector
    days = 7 if quick else 30
    log(f"Inspecting posts (last {days} days)...")
    posts = inspect_posts(days=days)
    posts_report = format_posts_report(posts)
    log(f"  Posts found: {len(posts)}")

    log("Inspecting strategy backlog...")
    backlog = inspect_strategy_backlog()
    log(f"  Backlog length: {len(backlog)} chars")

    # Шаг 3: Строим промпт и вызываем DeepSeek
    log("Building prompt and calling DeepSeek...")
    system, user = build_bridge_prompt(api_v0_report, api_free_report, posts_report, backlog)

    if dry_run:
        log("DRY RUN: skipping DeepSeek call")
        print("\n=== SYSTEM PROMPT (first 500 chars) ===")
        print(system[:500])
        print("\n=== USER PROMPT (first 1000 chars) ===")
        print(user[:1000])
        print("\n=== END DRY RUN ===")
        return

    raw = call_deepseek(system, user, temperature=0.6, max_tokens=4096)
    if not raw:
        log("ERROR: No response from DeepSeek")
        return

    # Шаг 4: Парсим JSON
    log("Parsing response...")
    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        log(f"Failed to parse JSON: {e}")
        log(f"Raw response (first 1000): {raw[:1000]}")
        return

    # Шаг 5: Сохраняем
    log(f"Suggestions generated: {len(data.get('suggestions', []))}")
    filename = save_suggestions(data)
    if filename:
        update_tracker(data)
        log(f"Done! Saved to {filename}")
    else:
        log("No suggestions to save")

    log("BSA API Bridge finished")


if __name__ == "__main__":
    main()

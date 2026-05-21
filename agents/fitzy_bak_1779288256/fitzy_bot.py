#!/usr/bin/env python3
"""Fitzy — Telegram Health Coach Bot. DeepSeek-powered, single process."""
import sys
import os
import json
import time
import logging
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

BASE = Path(__file__).resolve().parent
PROMPT_FILE = BASE / "fitzy_prompt.md"
DB_PATH = BASE / "fitzy.db"
TG_TOKEN_FILE = BASE / ".tg_token"
TG_CHAT_ID_FILE = BASE / ".tg_chat_id"

from fitzy_db import (
    profile_get_all, profile_set,
    metrics_add, metrics_latest, metrics_range,
    workout_add, workout_list, workout_done,
    nutrition_add, nutrition_today, nutrition_summary,
    exam_add, exam_list,
    meds_add, meds_active,
    schedule_add, schedule_list, schedule_today,
    convo_add, convo_recent,
    init_db,
)

DEEPSEEK_API = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-v4-flash"


# --- Key loading ---

def load_deepseek_key():
    for path in [BASE / ".deepseek_key", BASE.parent / ".env"]:
        if path.exists():
            for line in path.read_text().splitlines():
                if "DEEPSEEK_API_KEY" in line:
                    return line.split("=", 1)[1].strip().strip("\"'")
    return os.environ.get("DEEPSEEK_API_KEY")


def load_tg_token():
    if TG_TOKEN_FILE.exists():
        return TG_TOKEN_FILE.read_text().strip()
    for path in [BASE.parent / ".env"]:
        if path.exists():
            for line in path.read_text().splitlines():
                if "TG_TOKEN" in line:
                    return line.split("=", 1)[1].strip().strip("\"'")
    return os.environ.get("TG_TOKEN")


def load_chat_id():
    if TG_CHAT_ID_FILE.exists():
        return TG_CHAT_ID_FILE.read_text().strip()
    return os.environ.get("TG_CHAT_ID")


# --- DeepSeek API ---

def call_deepseek(messages, tools=None, max_tokens=4096):
    api_key = load_deepseek_key()
    if not api_key:
        raise RuntimeError("No DeepSeek API key")

    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    if tools:
        payload["tools"] = tools

    req = urllib.request.Request(
        DEEPSEEK_API,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        log.error("DeepSeek API error %s: %s", e.code, body[:500])
        raise
    except Exception as e:
        log.error("DeepSeek call failed: %s", e)
        raise


# --- Tool implementations ---

def tool_save_metric(args):
    metrics_add(
        weight=args.get("weight"),
        pulse=args.get("pulse"),
        pressure_sys=args.get("pressure_sys"),
        pressure_dia=args.get("pressure_dia"),
        sleep_hours=args.get("sleep_hours"),
        water_ml=args.get("water_ml"),
        steps=args.get("steps"),
        note=args.get("note"),
    )
    return "✅ Метрика сохранена"


def tool_show_metrics(args):
    days = args.get("days", 7)
    data = metrics_latest(days)
    if not data:
        return "Нет данных"
    lines = ["📊 Последние замеры:"]
    for m in data:
        parts = [m["recorded_at"][:10]]
        if m["weight"]: parts.append(f'вес {m["weight"]}кг')
        if m["pulse"]: parts.append(f'пульс {m["pulse"]}')
        if m["pressure_sys"]: parts.append(f'давление {m["pressure_sys"]}/{m["pressure_dia"]}')
        if m["sleep_hours"]: parts.append(f'сон {m["sleep_hours"]}ч')
        lines.append("  " + " | ".join(parts))
    return "\n".join(lines)


def tool_add_workout(args):
    exercises = args.get("exercises", "")
    workout_add(
        title=args.get("title", "Тренировка"),
        exercises=exercises,
        date_str=args.get("date"),
    )
    return f'✅ Тренировка "{args.get("title", "Тренировка")}" добавлена'


def tool_list_workouts(args):
    data = workout_list(limit=args.get("limit", 5))
    if not data:
        return "Нет тренировок"
    lines = ["💪 Тренировки:"]
    for w in data:
        lines.append(f'  {w["date"]} | {w["title"]} | {w["status"]}')
    return "\n".join(lines)


def tool_add_meal(args):
    nutrition_add(
        date_str=args.get("date"),
        meal_type=args.get("meal_type", "перекус"),
        dish=args.get("dish", ""),
        kcal=args.get("kcal"),
        protein_g=args.get("protein_g"),
        fat_g=args.get("fat_g"),
        carbs_g=args.get("carbs_g"),
    )
    return "✅ Приём пищи записан"


def tool_today_nutrition(args):
    data = nutrition_today()
    if not data:
        return "Сегодня ещё ничего не записано"
    lines = ["🍽 Питание сегодня:"]
    for m in data:
        kcal = f'{m["kcal"]}ккал' if m["kcal"] else ""
        lines.append(f'  {m["meal_type"]}: {m["dish"]} {kcal}')
    summary = nutrition_summary()
    if summary.get("total_kcal"):
        lines.append(f'  Итого: {summary["total_kcal"]} ккал, б {summary["total_protein"]}г, ж {summary["total_fat"]}г, у {summary["total_carbs"]}г')
    return "\n".join(lines)


def tool_add_schedule(args):
    schedule_add(
        day_of_week=args["day_of_week"],
        time=args.get("time", ""),
        activity_type=args["activity_type"],
        description=args["description"],
    )
    return "✅ Добавлено в расписание"


def tool_schedule_today(args):
    items = schedule_today()
    if not items:
        return "На сегодня ничего не запланировано"
    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    today_name = days[date.today().weekday()]
    lines = [f"📅 {today_name}, {date.today().isoformat()}:"]
    for it in items:
        lines.append(f'  {it["time"] or "—"} | {it["activity_type"]}: {it["description"]}')
    return "\n".join(lines)


def tool_profile_get(args):
    data = profile_get_all()
    if not data:
        return "Профиль не заполнен. Используй /profile чтобы заполнить."
    return "👤 Профиль:\n" + "\n".join(f'  {k}: {v}' for k, v in data.items())


def tool_profile_set(args):
    for k, v in args.items():
        if v is not None:
            profile_set(k, v)
    return "✅ Профиль обновлён"


def tool_add_exam(args):
    exam_add(
        exam_type=args["exam_type"],
        doctor=args.get("doctor"),
        summary=args.get("summary"),
        raw_text=args.get("raw_text"),
        parsed_json=args.get("parsed"),
    )
    return "✅ Обследование сохранено"


def tool_list_exams(args):
    data = exam_list(args.get("limit", 10))
    if not data:
        return "Нет обследований"
    lines = ["🔬 Обследования:"]
    for e in data:
        lines.append(f'  {e["date"]} | {e["exam_type"]} | {e.get("doctor", "—")}')
    return "\n".join(lines)


def tool_add_meds(args):
    meds_add(
        name=args["name"],
        dose=args.get("dose"),
        schedule=args.get("schedule"),
        start_date=args.get("start_date"),
        end_date=args.get("end_date"),
        note=args.get("note"),
    )
    return "✅ Лекарство добавлено"


def tool_active_meds(args):
    data = meds_active()
    if not data:
        return "Нет активных препаратов"
    lines = ["💊 Активные препараты:"]
    for m in data:
        lines.append(f'  {m["name"]} | {m.get("dose", "—")} | {m.get("schedule", "—")}')
    return "\n".join(lines)


TOOL_FUNCTIONS = {
    "save_metric": tool_save_metric,
    "show_metrics": tool_show_metrics,
    "add_workout": tool_add_workout,
    "list_workouts": tool_list_workouts,
    "add_meal": tool_add_meal,
    "today_nutrition": tool_today_nutrition,
    "add_schedule": tool_add_schedule,
    "schedule_today": tool_schedule_today,
    "profile_get": tool_profile_get,
    "profile_set": tool_profile_set,
    "add_exam": tool_add_exam,
    "list_exams": tool_list_exams,
    "add_meds": tool_add_meds,
    "active_meds": tool_active_meds,
}

TOOLS_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "save_metric",
            "description": "Сохранить замер здоровья: вес, пульс, давление, сон, вода, шаги",
            "parameters": {
                "type": "object",
                "properties": {
                    "weight": {"type": "number", "description": "Вес в кг"},
                    "pulse": {"type": "integer", "description": "Пульс уд/мин"},
                    "pressure_sys": {"type": "integer", "description": "Систолическое давление"},
                    "pressure_dia": {"type": "integer", "description": "Диастолическое давление"},
                    "sleep_hours": {"type": "number", "description": "Сон в часах"},
                    "water_ml": {"type": "integer", "description": "Вода в мл"},
                    "steps": {"type": "integer", "description": "Шаги"},
                    "note": {"type": "string", "description": "Заметка"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "show_metrics",
            "description": "Показать последние замеры здоровья",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "За сколько дней"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_workout",
            "description": "Добавить тренировку",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Название тренировки"},
                    "exercises": {"type": "string", "description": "Список упражнений"},
                    "date": {"type": "string", "description": "Дата (YYYY-MM-DD)"},
                },
                "required": ["title", "exercises"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workouts",
            "description": "Показать список тренировок",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Сколько показать"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_meal",
            "description": "Записать приём пищи",
            "parameters": {
                "type": "object",
                "properties": {
                    "meal_type": {"type": "string", "description": "Завтрак/обед/ужин/перекус"},
                    "dish": {"type": "string", "description": "Блюдо"},
                    "kcal": {"type": "integer", "description": "Калории"},
                    "protein_g": {"type": "number", "description": "Белки г"},
                    "fat_g": {"type": "number", "description": "Жиры г"},
                    "carbs_g": {"type": "number", "description": "Углеводы г"},
                    "date": {"type": "string", "description": "Дата (YYYY-MM-DD)"},
                },
                "required": ["meal_type", "dish"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "today_nutrition",
            "description": "Показать что съедено сегодня",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_schedule",
            "description": "Добавить событие в расписание (day_of_week: 0=Пн, 6=Вс)",
            "parameters": {
                "type": "object",
                "properties": {
                    "day_of_week": {"type": "integer", "description": "0=Пн, 6=Вс"},
                    "time": {"type": "string", "description": "Время HH:MM"},
                    "activity_type": {"type": "string", "description": "Тип: тренировка/обследование/приём"},
                    "description": {"type": "string", "description": "Описание"},
                },
                "required": ["day_of_week", "activity_type", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_today",
            "description": "Показать расписание на сегодня",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "profile_get",
            "description": "Показать мой профиль (возраст, вес, цели, ограничения)",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "profile_set",
            "description": "Обновить профиль",
            "parameters": {
                "type": "object",
                "properties": {
                    "age": {"type": "integer"},
                    "height": {"type": "integer"},
                    "weight_goal": {"type": "number"},
                    "allergies": {"type": "string"},
                    "restrictions": {"type": "string"},
                    "fitness_goal": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_exam",
            "description": "Сохранить результат обследования",
            "parameters": {
                "type": "object",
                "properties": {
                    "exam_type": {"type": "string", "description": "Тип: анализ_крови, мрт, узи и т.д."},
                    "doctor": {"type": "string"},
                    "summary": {"type": "string", "description": "Краткое содержание"},
                    "parsed": {"type": "object", "description": "Структурированные данные"},
                },
                "required": ["exam_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_exams",
            "description": "Показать список обследований",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_meds",
            "description": "Добавить препарат в список",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "dose": {"type": "string"},
                    "schedule": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "active_meds",
            "description": "Показать список активных препаратов",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


# --- Agent loop ---

def run_agent(user_text, system_prompt):
    """Run DeepSeek agent with function calling. Returns response text."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    max_iterations = 10
    for iteration in range(max_iterations):
        log.info("Agent iteration %d, %d messages", iteration, len(messages))

        response = call_deepseek(messages, tools=TOOLS_DEFINITIONS)

        if not response or "choices" not in response:
            return "Извини, ошибка при обработке запроса."

        msg = response["choices"][0]["message"]
        messages.append(msg)

        # Check if the model wants to use tools
        if not msg.get("tool_calls"):
            # Final response
            return msg.get("content") or "Готово."

        # Execute each tool call
        for tc in msg["tool_calls"]:
            func_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}

            log.info("Tool call: %s %s", func_name, args)

            handler = TOOL_FUNCTIONS.get(func_name)
            if handler:
                try:
                    result = handler(args)
                except Exception as e:
                    result = f"Ошибка: {e}"
                    log.error("Tool %s failed: %s", func_name, e)
            else:
                result = f"Неизвестный инструмент: {func_name}"

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": str(result),
            })

    return "Превышено число итераций. Попробуй переформулировать."


# --- Telegram API ---

def tg_api(method, payload):
    token = load_tg_token()
    if not token:
        log.error("No TG token")
        return None
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        log.warning("Telegram API error (%s): %s", method, body[:300])
        return None
    except Exception as e:
        log.warning("Telegram API error (%s): %s", method, e)
        return None


def send_message(chat_id, text):
    if not text:
        return False
    payload = {"chat_id": int(chat_id), "text": text, "parse_mode": "HTML"}
    # Split if too long
    if len(text) > 4000:
        return send_long(chat_id, text)
    r = tg_api("sendMessage", payload)
    return bool(r and r.get("ok"))


def send_long(chat_id, text):
    """Split long text into chunks and send."""
    chunks = []
    for line in text.split("\n"):
        if not chunks or len(chunks[-1]) + len(line) + 1 > 4000:
            chunks.append(line)
        else:
            chunks[-1] += "\n" + line
    ok = True
    for chunk in chunks:
        if not send_message(chat_id, chunk):
            ok = False
        time.sleep(0.5)
    return ok


def poll_updates(offset=0):
    token = load_tg_token()
    if not token:
        return offset, []
    url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=30&offset={offset}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=35) as resp:
            data = json.loads(resp.read())
    except Exception:
        return offset, []

    messages = []
    if data.get("ok"):
        for update in data.get("result", []):
            update_id = update["update_id"]
            if update_id >= offset:
                offset = update_id + 1
            msg = update.get("message")
            if msg and msg.get("text"):
                messages.append(msg)
    return offset, messages


# --- Main ---

def build_system_prompt():
    prompt = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.exists() else "You are Fitzy, a health coach."
    # Add profile context
    profile = profile_get_all()
    if profile:
        prompt += "\n\n## Профиль пользователя\n"
        for k, v in profile.items():
            prompt += f"- {k}: {v}\n"
    # Add today's schedule
    today_items = schedule_today()
    if today_items:
        prompt += "\n## Расписание на сегодня\n"
        for it in today_items:
            prompt += f"- {it['time'] or '—'} | {it['activity_type']}: {it['description']}\n"
    # Add recent conversations for context
    recent = convo_recent(3)
    if recent:
        prompt += "\n## Последние обсуждения\n"
        for c in recent:
            prompt += f"- {c.get('topic', 'общее')}: {c['question'][:60]}...\n"
    return prompt


def process_message(chat_id, text):
    """Handle one incoming message."""
    log.info("Processing: %.60s", text)

    # Save conversation
    convo_add(text, topic="fitzy")

    # Build prompt with context
    system_prompt = build_system_prompt()

    # Run agent
    try:
        response = run_agent(text, system_prompt)
    except Exception as e:
        log.error("Agent error: %s", e)
        response = "Извини, ошибка при обработке. Попробуй ещё раз."

    # Save answer
    try:
        from fitzy_db import convo_add as save_convo
        # We already saved question, now update with answer
        conn = __import__("sqlite3", fromlist=[""]).connect(str(DB_PATH))
        conn.execute(
            "UPDATE conversations SET answer=? WHERE id=(SELECT MAX(id) FROM conversations)",
            (response,),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Send response
    send_message(chat_id, response)


def main():
    token = load_tg_token()
    if not token:
        log.error("No TG_BOT_TOKEN")
        sys.exit(1)

    chat_id = load_chat_id()
    if not chat_id:
        log.error("No TG_CHAT_ID")
        sys.exit(1)

    # Init DB
    init_db()

    # Set default profile if not set
    if "name" not in profile_get_all():
        profile_set("name", "Эдди")

    offset = 0
    OFFSET_FILE = BASE / ".offset"
    if OFFSET_FILE.exists():
        try:
            offset = int(OFFSET_FILE.read_text().strip())
        except ValueError:
            pass

    log.info("Fitzy started (poll 5s)")
    while True:
        try:
            offset, msgs = poll_updates(offset)
            if msgs:
                for msg in msgs:
                    text = msg.get("text", "").strip()
                    if text:
                        process_message(chat_id, text)
            # Save offset
            OFFSET_FILE.write_text(str(offset))
            time.sleep(5)
        except KeyboardInterrupt:
            log.info("Shutting down")
            break
        except Exception as e:
            log.error("Main loop error: %s", e)
            time.sleep(10)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--init-db":
        init_db()
        print("DB initialized")
    else:
        main()

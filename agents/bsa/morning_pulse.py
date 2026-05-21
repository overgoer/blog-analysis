#!/usr/bin/env python3
"""
Morning Pulse — Bizzy пишет Эдди сам каждое утро.

Что в пульсе:
1. Приветствие (с вариациями)
2. Что по плану сегодня (по календарю)
3. Статус продуктов (Practicum, free-trial, бот)
4. Что нашли SCOUT/ANALYST (если есть новое)
5. Одно действие на сегодня
6. Подпись

Запуск: python3 morning_pulse.py          # напечатать в консоль
        python3 morning_pulse.py --send    # отправить в Telegram + email
        python3 morning_pulse.py --dry-run # показать что будет отправлено

Cron: 0 7 * * * cd /root/blog-analysis/agents/bsa && python3 morning_pulse.py --send
"""

import json, os, random, subprocess, sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parent
AGENTS_DIR = BASE.parent

VAULT = Path("/root/obsidian-vault/eddytester")
STRAT_DIR = VAULT / "Стратегия"
POSTS_DIR = VAULT / "Посты"
DATA_DIR = Path("/root/blog-analysis/data")
SCOUT_DIR = Path("/root/blog-analysis/agents/scout/reports")

now = datetime.now()
today = date.today()
weekday = today.weekday()  # 0=mon


def _parse_cal_date(raw: str):
    """Parse calendar date like 'ПН 18.05' or '**ПН 18.05**' into (day_name, day_month_str)."""
    clean = raw.strip().replace("*", "").replace("|", "").strip()
    # Some entries are just day name without date
    parts = clean.split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    if len(parts) == 1:
        return parts[0], ""
    return "", ""


def _load_backlog():
    """Load backlog.json for status cross-reference."""
    bf = BASE / "backlog.json"
    if bf.exists():
        try:
            return json.loads(bf.read_text())
        except (json.JSONDecodeError, Exception):
            return None
    return None


def _status_emoji(s: str) -> str:
    s = s.lower().strip()
    if s in ("done", "✅", "готов", "опубликован"):
        return "✅"
    if s in ("in_progress", "🔄", "в работе"):
        return "🔄"
    if s in ("pending", "⬜", "запланирован"):
        return "⬜"
    return "⬜"


def _match_backlog(topic: str, backlog: dict) -> str:
    """Check if a topic matches a backlog item."""
    if not backlog or not topic:
        return ""
    items = backlog.get("items", []) if isinstance(backlog, dict) else backlog
    if isinstance(items, list):
        for item in items:
            title = (item.get("title", "") if isinstance(item, dict) else str(item)).lower()
            if topic.lower()[:20] in title or title[:20] in topic.lower():
                s = item.get("status", "") if isinstance(item, dict) else ""
                return _status_emoji(s)
    return ""

# ── Greetings ──────────────────────────────────────────────────────────

GREETINGS = {
    "monday": [
        "Понедельник — день тяжёлый, но не для нас. Система загружена.",
        "Новая неделя, новые баги. BSA calibriert.",
        "Модуль Bizzy активирован. Цель недели — Practicum.",
    ],
    "tuesday": [
        "Вторник — рабочий разгон. Поехали.",
        "Системы в норме. Канал ждёт контент.",
    ],
    "wednesday": [
        "Среда — середина недели. Самое время для сильного поста.",
        "Bizzy на связи. Что в плане на сегодня?",
    ],
    "thursday": [
        "Четверг. До выходных есть время сделать рывок.",
        "Пульс в норме. Давай посмотрим на план.",
    ],
    "friday": [
        "Пятница — последний рывок. 3 поста за неделю — норма.",
        "Bizzy отчёт: неделя почти закрыта. Остался最后一个 пост.",
    ],
    "saturday": [
        "Суббота — не значит отдыхать. Лёгкий пост в плане?",
        "Выходные — лучшее время для контента без спешки.",
    ],
    "sunday": [
        "Воскресенье — планируем неделю. Без плана нет результата.",
        "Тихий день. Самое время подумать о стратегии.",
    ],
}

SCIFI_LINES = [
    "«Исполнение важнее идеи.»",
    "«Победитель получает всё. Остальные — опыт.»",
    "«Не герой тот, кто не ошибался.»",
    "«Единственный способ — через практику.»",
    "«Баг — не ошибка, баг — данные.»",
]

# ── Data readers ───────────────────────────────────────────────────────


def read_calendar() -> Optional[list]:
    """Read today's entry(entries) from Календарь.md."""
    cal_file = STRAT_DIR / "Календарь.md"
    if not cal_file.exists():
        return None

    content = cal_file.read_text(encoding="utf-8")
    date_str = today.strftime("%d.%m")
    weekday_ru = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"][weekday]

    entries = []
    for line in content.split("\n"):
        # Match: | ПН 18.05 or | **ПН 18.05**
        clean = line.strip().replace("*", "").replace("|", "").strip()
        if clean.upper().startswith(weekday_ru) and date_str in clean:
            parts = [p.strip().replace("*", "") for p in line.split("|")]
            parts = [p for p in parts if p]
            # Skip header lines
            if not parts or "Дата" in parts[0] or "---" in parts[0]:
                continue
            if len(parts) >= 6:
                entries.append({
                    "date": parts[0],
                    "time": parts[1] if len(parts) > 1 else "",
                    "post_type": parts[2] if len(parts) > 2 else "",
                    "format": parts[3] if len(parts) > 3 else "",
                    "topic": parts[5] if len(parts) > 5 else "",
                    "status": parts[-1],  # last column
                })
    return entries if entries else None


def read_this_week_calendar() -> list:
    """Read all entries for this week from Календарь.md with date filtering."""
    cal_file = STRAT_DIR / "Календарь.md"
    if not cal_file.exists():
        return []

    content = cal_file.read_text(encoding="utf-8")

    # Determine this week's date range
    week_start = today - __import__("datetime").timedelta(days=weekday)
    week_end = week_start + __import__("datetime").timedelta(days=6)
    mon = week_start.day
    sun = week_end.day
    month_num = week_start.month

    entries = []

    for line in content.split("\n"):
        if line.strip().startswith("|") and "Дата" not in line and "---" not in line:
            parts = [p.strip() for p in line.split("|")]
            parts = [p for p in parts if p]
            if len(parts) >= 6:
                day_name, day_month = _parse_cal_date(parts[0])
                # Filter by date within this week
                try:
                    entry_day = int(day_month.split(".")[0])
                except (ValueError, IndexError):
                    entry_day = 0
                if entry_day == 0 or mon <= entry_day <= sun:
                    entries.append({
                        "raw": line,
                        "date": parts[0],
                        "topic": parts[5] if len(parts) > 5 else "",
                        "status": parts[-1] if len(parts) > 1 else "",
                    })

    return entries


def read_latest_scout() -> Optional[str]:
    """Return latest SCOUT report summary."""
    if not SCOUT_DIR.exists():
        return None
    reports = sorted(SCOUT_DIR.glob("summary_*.json"))
    if not reports:
        return None

    try:
        data = json.loads(reports[-1].read_text())
        recs = data.get("recommendations", [])
        if recs:
            return random.choice(recs[:3])[:200]
    except (json.JSONDecodeError, IndexError):
        pass
    return None


def read_strategy_focus():
    """Extract current focus from strategy v6 and cross-reference with backlog."""
    strategy_files = sorted(STRAT_DIR.glob("BSA_STRATEGY_v6_*.md"))
    if not strategy_files:
        strategy_files = sorted(STRAT_DIR.glob("BSA_STRATEGY_*.md"))
    if not strategy_files:
        return None

    content = strategy_files[-1].read_text(encoding="utf-8")

    # Extract bet summaries
    bets = []
    for line in content.split("\n"):
        if line.strip().startswith("### Bet"):
            bets.append(line.strip())

    # Find critical path items
    critical = []
    in_critical = False
    for line in content.split("\n"):
        if "Критический путь" in line:
            in_critical = True
            continue
        if in_critical:
            if line.strip().startswith("###") or line.strip().startswith("---"):
                break
            if line.strip().startswith("1.") or line.strip().startswith("2.") or line.strip().startswith("3.") or line.strip().startswith("4."):
                critical.append(line.strip())

    # Cross-reference with backlog for status
    backlog = _load_backlog()
    if backlog and critical:
        enriched = []
        for c in critical:
            emoji = _match_backlog(c, backlog)
            enriched.append(f"{emoji} {c}" if emoji else c)
        critical = enriched

    return {"bets": bets, "critical": critical}


def is_ready_today():
    """Check if today's post file exists."""
    cal = read_calendar()
    if not cal:
        return None, None

    topic = cal.get("topic", "")
    file_hint = cal.get("raw", "")
    # Extract file link from raw
    import re
    m = re.search(r'\[\[([^\]]+)\]\]', file_hint)
    if m:
        file_name = m.group(1).split("/")[-1]
        # Search in posts and strategy
        for d in [POSTS_DIR, STRAT_DIR]:
            for f in d.iterdir():
                if file_name.lower().replace(" ", "_") in f.name.lower().replace(" ", "_"):
                    return f.exists(), topic
    return None, topic


# ── Build pulse ────────────────────────────────────────────────────────


def check_health():
    """Return list of issues found in the system."""
    issues = []

    # 1. TG bot alive?
    try:
        r = subprocess.run(["pm2", "show", "tg-bizzy"], capture_output=True, text=True, timeout=10)
        if "online" not in r.stdout:
            issues.append("Telegram bot (tg-bizzy) не в сети")
    except Exception:
        issues.append("Не могу проверить tg-bizzy")

    # 2. Requests listener lock (stuck?)
    lock = Path("/tmp/requests_listener.lock")
    if lock.exists():
        age = (datetime.now() - datetime.fromtimestamp(lock.stat().st_mtime)).total_seconds()
        if age > 120:
            issues.append(f"requests_listener.lock висит ({int(age)}с)")

    # 3. Stuck outgoing messages
    outgoing_dir = Path("/root/blog-analysis/agents/bsa/outgoing")
    stuck = [f for f in outgoing_dir.glob("*.json") if f.stat().st_mtime < (datetime.now().timestamp() - 300)]
    if stuck:
        issues.append(f"{len(stuck)} сообщений застряли в outgoing/")

    # 4. SCOUT data freshness
    reports = sorted(SCOUT_DIR.glob("summary_*.json"))
    if reports:
        age = (datetime.now() - datetime.fromtimestamp(reports[-1].stat().st_mtime)).total_seconds()
        if age > 172800:  # > 2 days
            issues.append(f"SCOUT не обновлялся {int(age/86400)} дней")

    # 5. Vault git sync
    try:
        r = subprocess.run(
            ["git", "-C", "/root/obsidian-vault", "status", "--short"],
            capture_output=True, text=True, timeout=10,
        )
        dirty = len([l for l in r.stdout.split("\n") if l.strip()])
        if dirty > 10:
            issues.append(f"В ваулте {dirty} незакоммиченных файлов")
    except Exception:
        pass

    return issues


def build_pulse():
    lines = []

    # 1. Greeting
    day_key = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"][weekday]
    greeting = random.choice(GREETINGS[day_key])
    scifi = random.choice(SCIFI_LINES)
    lines.append(f"🌅 *Доброе утро, Эдди*\n")
    lines.append(f"> {scifi}\n")
    lines.append(f"{greeting}\n")

    # 2. Today's content plan
    cals = read_calendar()
    lines.append("━━━ *ПЛАН НА СЕГОДНЯ* ━━━")
    if cals:
        for cal in cals:
            post_status = cal.get("status", "")
            # Skip already published
            if "опубликован" in post_status.lower() or "✅" in post_status:
                continue
            lines.append(f"  • Формат: {cal.get('format', '—')} — {cal.get('topic', '—')}")
            lines.append(f"  • Время: {cal.get('time', '—')}: {cal.get('post_type', '—')}")
            lines.append(f"  • Статус: {post_status}")
            lines.append("")
        # Check if everything for today is published
        if all("опубликован" in c.get("status", "").lower() or "✅" in c.get("status", "") for c in cals):
            lines.append(f"  ✅ Сегодня всё опубликовано. Молодец!")
            lines.append("")
    else:
        lines.append(f"  Нет записи в календаре на сегодня.")
        lines.append(f"  Выходной или свободное плавание.")
        lines.append("")

    # 3. Week overview (upcoming)
    week_entries = read_this_week_calendar()
    if week_entries:
        published = [e for e in week_entries if "опубликован" in e.get("status", "").lower() or "✅" in e.get("status", "")]
        ready = [e for e in week_entries if "готов" in e.get("status", "").lower() and e not in published]
        pending = [e for e in week_entries if e not in published and e not in ready]
        lines.append(f"📋 *НЕДЕЛЯ:* {len(published)} опубликовано, {len(ready)} готово, {len(pending)} в работе")
        if pending:
            for p in pending[:3]:
                topic_str = p.get("topic", "")[:60]
                if topic_str:
                    lines.append(f"  • {topic_str}")
        lines.append("")

    # 4. Strategy / Practicum status
    focus = read_strategy_focus()
    if focus and focus.get("critical"):
        lines.append(f"🎯 *ПРОДУКТ:*")
        for c in focus["critical"][:3]:
            lines.append(f"  • {c}")
        lines.append("")

    # 5. Health check
    health_issues = check_health()
    for issue in health_issues:
        lines.append(f"  ⚠️ {issue}")
    if health_issues:
        lines.append("")

    # 6. SCOUT insights (if new)
    scout = read_latest_scout()
    if scout:
        lines.append(f"🔍 *ИНСАЙТ ОТ SCOUT:*")
        lines.append(f"  {scout}")
        lines.append("")

    # 7. Action point
    lines.append(f"⚡ *ДЕЙСТВИЕ НА СЕГОДНЯ:*")
    # Check if any pending posts need writing
    if cals:
        pending = [c for c in cals if "готов" not in c.get("status", "").lower() and "опубликован" not in c.get("status", "").lower() and "✅" not in c.get("status", "")]
        if pending:
            lines.append(f"  Дописать пост на сегодня: {pending[0].get('topic', '—')}")
        elif focus and focus.get("critical"):
            # Show first critical action without numbering
            lines.append(f"  {focus['critical'][0].split('. ', 1)[-1] if '. ' in focus['critical'][0] else focus['critical'][0]}")
        else:
            lines.append(f"  Следовать календарю. 3 поста в неделю — норма.")
    else:
        if focus and focus.get("critical"):
            lines.append(f"  {focus['critical'][0].split('. ', 1)[-1] if '. ' in focus['critical'][0] else focus['critical'][0]}")
        else:
            lines.append(f"  Следовать календарю. 3 поста в неделю — норма.")

    lines.append("")
    # No silly signature, just the business
    lines.append("— Bizzy 🤖")

    return "\n".join(lines)


# ── Sending ─────────────────────────────────────────────────────────────


def send_telegram(text):
    """Send via Telegram bot's push_message."""
    try:
        sys.path.insert(0, str(BASE))
        from telegram_bot import push_message
        push_message(text)
        return True
    except Exception as e:
        print(f"[pulse] TG push failed: {e}")
        return False


def send_email(text):
    """Send via mailer."""
    try:
        sys.path.insert(0, str(Path("/root/blog-analysis/lib")))
        from mailer import send_report
        send_report("🌅 Bizzy: утренний пульс", text)
        return True
    except Exception as e:
        print(f"[pulse] Email failed: {e}")
        return False


def main():
    dry_run = "--dry-run" in sys.argv
    do_send = "--send" in sys.argv

    pulse = build_pulse()
    print(pulse)

    if do_send and not dry_run:
        tg_ok = send_telegram(pulse)
        email_ok = send_email(pulse)
        print(f"\n[pulse] Telegram: {'✅' if tg_ok else '❌'}")
        print(f"[pulse] Email: {'✅' if email_ok else '❌'}")

    if do_send and dry_run:
        print("\n[pulse] --dry-run: сообщение НЕ отправлено")


if __name__ == "__main__":
    main()

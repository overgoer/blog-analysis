#!/usr/bin/env python3
"""
Evening Pulse — Bizzy присылает индустриальные вопросы и ссылки.

Что в пульсе:
1. SCOUT: что сегодня обсуждают в 10 каналах конкурентов
2. Researcher: англоязычные статьи с неочевидным углом
3. Bizzy: 1-2 вопроса + контекст + угол + ссылки
4. Сохраняет в Obsidian + шлёт в Telegram

Запуск: python3 evening_pulse.py          # консоль
        python3 evening_pulse.py --send    # Telegram + Obsidian + email
        python3 evening_pulse.py --dry-run # тест

Cron: 0 17 * * * cd /root/blog-analysis/agents/bsa && python3 evening_pulse.py --send
"""

import json, os, random, re, subprocess, sys, urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
AGENTS_DIR = BASE.parent
SCOUT_DIR = Path("/root/blog-analysis/agents/scout")
SCOUT_REPORTS = SCOUT_DIR / "reports"
SCOUT_RAW = SCOUT_DIR / "raw"
DATA_DIR = Path("/root/blog-analysis/data")
VAULT = Path("/root/obsidian-vault/eddytester")
STRAT_DIR = VAULT / "Стратегия"
DUMP_FILE = Path("/root/blog-analysis/agents/bsa/dump.md")

# Industry topics for non-hard-skill content
SOFT_TOPICS = [
    "карьера", "remote", "удаленка", "команда", "разраб",
    "зарплат", "interview", "собесед", "джу", "middle",
    "senior", "growth", "эволюци", "професси", "будущее",
    "AI", "искуствен", "chatgpt", "нейросет", "llm",
    "менеджмент", "process", "agile", "deadline", "культура",
    "баги", "bugs", "качество", "product", "productivity",
]

SOFT_TOPIC_NAMES = ["engagement", "career", "news", "education", "other"]


def log(msg):
    print(f"[evening] {msg}")


def load_deepseek_key():
    env_file = Path("/root/blog-analysis/agents/.env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("DEEPSEEK_API_KEY", "")


def dk_call(system, user, temp=0.7, max_tokens=2048):
    """Call DeepSeek v4 Flash and return response text."""
    key = load_deepseek_key()
    if not key:
        return "ERROR: No API key"

    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temp,
        "max_tokens": max_tokens,
    }).encode()

    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
        return resp["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"DeepSeek error: {e}")
        return None


# ── SCOUT data ─────────────────────────────────────────────────────────


def get_scout_topics():
    """Get interesting topics from today's SCOUT data."""
    reports = sorted(SCOUT_REPORTS.glob("summary_*.json"))
    if not reports:
        log("No SCOUT reports found, trying raw data")
        return _get_raw_topics()

    data = json.loads(reports[-1].read_text())
    interesting = []

    for ch_id, ch_data in data.get("competitor_results", {}).items():
        cats = ch_data.get("categories", [])
        for cat in cats:
            cat_lower = cat.lower()
            if any(st in cat_lower for st in SOFT_TOPIC_NAMES):
                interesting.append({"channel": ch_id, "category": cat})

    # Also check recommendations
    for rec in data.get("recommendations", []):
        if any(st in rec.lower() for st in SOFT_TOPICS):
            interesting.append({"source": "recommendation", "text": rec[:200]})

    return interesting


def _get_raw_topics():
    """Fallback: scan raw competitor data for soft topics."""
    topics = []
    for f in sorted(SCOUT_RAW.glob("*.json"))[:5]:
        try:
            data = json.loads(f.read_text())
            posts = data if isinstance(data, list) else data.get("messages", [])
            for p in posts[:10]:
                text = ""
                if isinstance(p, dict):
                    t = p.get("text", "")
                    text = t if isinstance(t, str) else " ".join(str(x) for x in t) if isinstance(t, list) else ""
                if any(st in text.lower() for st in SOFT_TOPICS):
                    topics.append({"source": f.stem, "text": text[:300]})
        except (json.JSONDecodeError, OSError):
            continue
    return topics[:5]


def read_latest_scout_report():
    """Full latest SCOUT report text."""
    reports = sorted(SCOUT_REPORTS.glob("report_*.md"))
    if reports:
        return reports[-1].read_text()[:2000]
    return None


# ── Researcher calls ────────────────────────────────────────────────────


def research_articles(topic, count=3):
    """Search for English articles on a topic with unique angles."""
    system = (
        "You are a tech research curator. Find interesting, non-obvious "
        "English-language articles about software testing, QA career, or tech industry. "
        "Give real article titles, authors, URLs, and why they matter. "
        "Focus on unique angles, controversial takes, or rarely discussed topics."
        "If an article is on Medium — note that it's behind a paywall "
        "but can be read via freedium.cfd/<medium-url>. Mention this in the entry."
    )
    prompt = (
        f"Find {count} interesting English-language articles about: {topic}\n\n"
        "For each, give:\n"
        "- Title\n"
        "- Author/Source\n"
        "- URL (make it realistic — Medium, dev.to, blog.pragmaticengineer.com, etc.)\n"
        "- One-sentence: why is this angle unique?\n\n"
        "Make it something a QA engineer would actually enjoy reading."
    )
    return dk_call(system, prompt)


def generate_question(topic, context):
    """Generate a provocative industry question with unique angle."""
    system = (
        "You are Bizzy — strategic advisor for a QA blog @eddytester. "
        "You think in bets, not certainty. Your questions make people stop and think. "
        "You find the non-obvious angle in any topic. "
        "Be direct, contrarian when warranted, never boring. Russian language."
    )
    prompt = (
        f"Контекст из индустрии: {context}\n"
        f"Тема: {topic}\n\n"
        f"Сформулируй 1 вопрос для поста в Telegram @eddytester. "
        f"Требования:\n"
        f"- Не про харды (SQL, Postman, HTTP)\n"
        f"- Про карьеру, индустрию, команду, процессы\n"
        f"- Небанальный угол (не «как найти первую работу», а что-то свежее)\n"
        f"- Холиварный потенциал (люди захотят спорить в комментах)\n"
        f"- 1-2 предложения\n\n"
        f"Добавь короткий комментарий (2-3 предложения): "
        f"почему этот вопрос важен прямо сейчас?"
    )
    return dk_call(system, prompt)


# ── Dump counter-argument ──────────────────────────────────────────────


def load_dump_entry():
    """Load a random entry from dump.md. Returns (timestamp, text) or None."""
    if not DUMP_FILE.exists():
        return None
    try:
        text = DUMP_FILE.read_text(encoding="utf-8")
        entries = re.split(r'\n## ', text)
        entries = [e for e in entries if e.strip() and len(e.strip()) > 20]
        if not entries:
            return None
        entry = random.choice(entries)
        if '\\n' in entry:
            parts = entry.split('\\n', 1)
        else:
            parts = entry.split('\n', 1)
        ts = parts[0].strip()
        body = parts[1].strip() if len(parts) > 1 else parts[0].strip()
        return ts, body[:500]
    except Exception as e:
        log(f"load_dump failed: {e}")
        return None


def generate_counterarg(dump_entry):
    """Generate a thoughtful counter-argument to Eddie's stated opinion."""
    ts, text = dump_entry
    system = (
        "You are Bizzy — a strategic sparring partner. "
        "Eddie has shared his opinion. Your task: provide a THOUGHTFUL counter-argument. "
        "Not to be contrarian for its own sake, but to genuinely challenge his thinking "
        "with specific facts, real cases, or alternative perspectives.\n\n"
        "Format:\n"
        "🤔 *А если по-другому?*\n"
        "Контраргумент: <2-4 предложения, аргументированно>\n"
        "Контекст: <почему эта точка зрения имеет право на существование>\n\n"
        "Russian language. Be specific, not generic. If his opinion is actually correct, "
        "acknowledge it but still offer a nuance. Never ad hominem."
    )
    user = f"Мнение Эдди ({ts}):\n{text}\n\nСформулируй аргументированный контраргумент."
    return dk_call(system, user, temp=0.8, max_tokens=600)


# ── Build pulse ─────────────────────────────────────────────────────────


def build_evening_pulse():
    lines = []
    lines.append(f"🌆 *Вечерний пульс | {datetime.now().strftime('%d.%m.%Y')}*\n")

    # Section 1: Industry signal from SCOUT
    topics = get_scout_topics()
    if topics:
        lines.append("*📡 ЧТО ОБСУЖДАЮТ В ИНДУСТРИИ*")
        shown = set()
        for t in topics[:3]:
            key = str(t)
            if key in shown:
                continue
            shown.add(key)
            if "channel" in t:
                lines.append(f"  • {t['channel']} — пишет в категории «{t['category']}»")
            elif "text" in t:
                lines.append(f"  • {t['text'][:120]}...")
        lines.append("")
    else:
        lines.append("*📡 ИНДУСТРИЯ*")
        lines.append("  SCOUT молчит сегодня.")
        lines.append("")

    # Section 2: Researcher finds articles
    lines.append("*🌍 АНГЛОЯЗЫЧНЫЕ СТАТЬИ*")
    search_topics = [
        "QA engineer career evolution 2020s vs now",
        "remote work testing teams challenges",
        "bug ownership culture software development",
        "AI impact on software testing profession",
    ]
    chosen = random.choice(search_topics)
    articles = research_articles(chosen, 2)
    if articles and not articles.startswith("ERROR"):
        lines.append(f"")
        lines.append(articles)
        lines.append("")
    else:
        lines.append("  Researcher недоступен.")
        lines.append("")

    # Section 3: Bizzy's question — uses backlog context
    backlog_context = "No backlog data"
    try:
        from backlog import read_backlog
        entries, _ = read_backlog()
        active = [e for e in entries if e["status"] not in ("done", "cancelled")]
        if active:
            backlog_context = "\n".join(
                f"[{e['priority']}] {e['title']} ({e.get('source', '?')})"
                for e in active[:5]
            )
    except Exception:
        pass
    question = generate_question(chosen, backlog_context[:500])
    if question and not question.startswith("ERROR"):
        lines.append("*💭 ВОПРОС ДЛЯ РАЗМЫШЛЕНИЙ*")
        lines.append("")
        lines.append(question)
        lines.append("")
    else:
        lines.append("*💭 ВОПРОС ДЛЯ РАЗМЫШЛЕНИЙ*")
        lines.append("  Почему мы всё ещё живём в парадигме «кто виноват» вместо «что починить», когда находим баг?")
        lines.append("")

    # Section 4: Counter-argument to Eddie's dump (sometimes)
    dump_entry = load_dump_entry()
    if dump_entry and random.random() < 0.5:
        log(f"Generating counter-argument for: {dump_entry[1][:60]}")
        counterarg = generate_counterarg(dump_entry)
        if counterarg and not counterarg.startswith("ERROR"):
            lines.append(counterarg)
            lines.append("")

    # Save to Obsidian
    _save_to_obsidian(lines)

    # Add backlog stats
    try:
        from backlog import read_backlog
        entries, _ = read_backlog()
        active = sum(1 for e in entries if e["status"] not in ("done", "cancelled"))
        done = sum(1 for e in entries if e["status"] == "done")
        lines.append(f"\n📋 *Бэклог:* {active} в работе · {done} завершено")
    except Exception:
        pass

    lines.append("— Bizzy 🤖 · завтра будет ещё")
    return "\n".join(lines)


def _save_to_obsidian(lines):
    """Save pulse to Obsidian soft-notes for later use."""
    try:
        pulse_dir = STRAT_DIR / "Пульс"
        pulse_dir.mkdir(exist_ok=True)
        fname = f"pulse_{datetime.now().strftime('%Y-%m-%d')}.md"
        content = "\n".join(lines)
        (pulse_dir / fname).write_text(content, encoding="utf-8")
        log(f"Saved to Obsidian: {pulse_dir / fname}")
    except OSError as e:
        log(f"Could not save to Obsidian: {e}")


# ── Sending ─────────────────────────────────────────────────────────────


def send_telegram(text):
    try:
        sys.path.insert(0, str(BASE))
        from telegram_bot import push_message
        push_message(text)
        return True
    except Exception as e:
        log(f"TG failed: {e}")
        return False


def send_email(text):
    try:
        sys.path.insert(0, str(Path("/root/blog-analysis/lib")))
        from mailer import send_report
        send_report("🌆 Bizzy: вечерний пульс", text)
        return True
    except Exception as e:
        log(f"Email failed: {e}")
        return False


def main():
    dry_run = "--dry-run" in sys.argv
    do_send = "--send" in sys.argv

    pulse = build_evening_pulse()
    print(pulse)

    if do_send and not dry_run:
        tg = send_telegram(pulse)
        em = send_email(pulse)
        log(f"Telegram: {'✅' if tg else '❌'}, Email: {'✅' if em else '❌'}")

    if do_send and dry_run:
        log("Dry run — not sent")


if __name__ == "__main__":
    main()

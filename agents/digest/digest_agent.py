#!/usr/bin/env python3
"""
Digest Agent — ежедневный дайджест здоровья системы и задач.

Доставляет одно письмо в день: что сделано, что в плане,
здоровье агентов, dev-поток, стратегические ставки, стримы.

Usage:
  python3 digest_agent.py              # normal run
  python3 digest_agent.py --dry-run    # print digest to stdout, no email
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
AGENTS_DIR = BASE / "agents"
LOGS_DIR = BASE / "logs"
ORCH_DIR = AGENTS_DIR / "orchestrator"
BSA_DIR = AGENTS_DIR / "bsa"
SCOUT_DIR = AGENTS_DIR / "scout"
OBSIDIAN_DIR = Path("/root/obsidian-vault/eddytester")
POSTS_DIR = OBSIDIAN_DIR / "Посты"
SCOUT_OBSIDIAN_DIR = OBSIDIAN_DIR / "Стратегия" / "Конкуренты"

SAVE_DIGEST_DIR = OBSIDIAN_DIR / "Дайджесты"

MOSCOW_OFFSET = timedelta(hours=3)


def now():
    return datetime.now(timezone.utc)


def moscow_time():
    return now() + MOSCOW_OFFSET


def log(msg):
    ts = now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[digest] {ts} {msg}", flush=True)


# ── Greetings ───────────────────────────────────────────────────────────────

GREETINGS = [
    ("Доброе утро, Эд. Сегодня на повестке дня — сюрприз, сюрприз...", "The Office"),
    ("С добрым утром, капитан. Система прошла самодиагностику, всё в норме.", "Mass Effect"),
    ("Приветствую, повелитель. Твои агенты готовы исполнять.", "Black Mirror"),
    ("Проснись, Нео... Ну, или просто прочитай дайджест.", "The Matrix"),
    ("Доброе утро, Эд. Сегодня — первый день остальной твоей недели.", "Groundhog Day"),
    ("Система запущена. Ждём указаний, коммандер.", "Star Trek / Mass Effect"),
    ("Эд проснулся. Вселенная может выдохнуть.", "Hitchhiker's Guide"),
    ("Сегодня будет великий день. Или нет. Но дайджест ты всё равно прочитаешь.", "Futurama"),
    ("Привет, Эд. Пока ты спал, агенты не бездельничали.", "Westworld"),
    ("Утро на базе. Соединение с агентами стабильное.", "Metal Gear Solid"),
    ("Внимание, экипаж. Утренний брифинг готов.", "Star Wars / The Expanse"),
    ("Отчёт о состоянии галактики... ну и твоих репозиториев.", "Marvel / Guardians"),
    ("Доброе утро! Сегодня — отличный день, чтобы что-то изменить.", "Stranger Things — vibes"),
    ("Система здорова. Ты — тоже (надеюсь). Погнали.", "Silicon Valley"),
    ("Сегодняшняя миссия, если ты решишь её принять...", "Mission Impossible"),
    ("Агенты на связи. Ресурсы в норме. Ты — за главного.", "The Expanse / Alien"),
    ("Доброе утро! Сегодня твой день. Агенты уже работают.", "The Lego Movie — Everything is Awesome"),
    ("Эд, приём. Утро наступило. Система готова к бою.", "Half-Life / Portal"),
    ("Докладываю обстановку. Противник не дремлет, но мы тоже.", "Civilization / XCOM"),
    ("Утро, Эд. Пока собака спит — мы уже собрали статистику.", "The Office / скотч"),
    ("Слушаю и повинуюсь. Ну, почти.", "The Boys / Властелин Колец"),
    ("Эд, доброе. Твои подданные отчитались за вчера.", "Dune"),
    ("Брифинг готов. Кофе — в твоих руках.", "Altered Carbon / Cyberpunk"),
    ("Всем кто на связи — доброе утро. Эд, тебе отдельный привет.", "The Witcher / Йеннифэр"),
    ("Докладываю: за вчера потерь нет, продуктивность в норме.", "Firefly / Serenity"),
]


def pick_greeting():
    """Pick a daily greeting based on the day of year."""
    day_of_year = (now().timetuple().tm_yday)
    idx = (day_of_year * 7 + 13) % len(GREETINGS)  # deterministic variation
    text, source = GREETINGS[idx]
    return f'{text}\n  — {source}'


# ── Data Collection ──────────────────────────────────────────────────────────

def tail_log(log_name, max_lines=30):
    """Read last N lines of a log file."""
    log_file = LOGS_DIR / log_name
    if not log_file.exists():
        return None
    try:
        r = subprocess.run(
            ["tail", "-n", str(max_lines), str(log_file)],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() if r.stdout.strip() else None
    except Exception:
        return None


def read_json(path):
    """Read and parse a JSON file. Returns None on failure."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def collect_processed_commands(since_hours=24):
    """Load processed commands from last N hours."""
    cmds = []
    cmd_dir = ORCH_DIR / "processed_cmds"
    if not cmd_dir.exists():
        return cmds, 0

    cutoff = now() - timedelta(hours=since_hours)
    for f in sorted(cmd_dir.iterdir(), reverse=True)[:20]:
        if not f.name.endswith(".json"):
            continue
        data = read_json(f)
        if not data:
            continue
        ts_str = data.get("timestamp", "")
        try:
            ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            ts = now()
        if ts < cutoff:
            continue
        cmds.append(data)
    return cmds, len(cmds)


def count_recent_errors(log_names, since_hours=24):
    """Count ERROR lines in recent logs."""
    since = now() - timedelta(hours=since_hours)
    total = 0
    for name in log_names:
        log_file = LOGS_DIR / name
        if not log_file.exists():
            continue
        try:
            r = subprocess.run(
                ["grep", "-ci", "error\\|traceback\\|failed", str(log_file)],
                capture_output=True, text=True, timeout=5,
            )
            count = int(r.stdout.strip() or "0")
            total += count
        except Exception:
            pass
    return total


def check_cron_health(since_hours=27):
    """Check if cron jobs ran recently by reading CHRON.md."""
    chron_file = Path.home() / "blog-analysis" / "CHRON.md"
    if not chron_file.exists():
        return None
    try:
        content = chron_file.read_text()
        expected = now() - timedelta(hours=since_hours)
        cutoff = expected.strftime("%a %b %d")
        recent_lines = [l for l in content.split("\n") if cutoff in l]
        return len(recent_lines)
    except Exception:
        return None


def collect_posts(since_days=3):
    """Collect recent posts from Obsidian Посты/ directory."""
    if not POSTS_DIR.exists():
        return []
    posts = []
    for f in sorted(POSTS_DIR.iterdir(), reverse=True)[:10]:
        if not f.name.endswith(".md"):
            continue
        mtime = os.path.getmtime(f)
        cutoff = now() - timedelta(days=since_days)
        if datetime.fromtimestamp(mtime, tz=timezone.utc) < cutoff:
            continue
        content = f.read_text()
        title_match = re.search(r"^# (.+)", content)
        title = title_match.group(1) if title_match else f.name
        angle_match = re.search(r"\*\*Angle:\*\* (.+)", content)
        angle = angle_match.group(1) if angle_match else ""
        posts.append({"title": title, "angle": angle, "file": str(f), "date": f.name[:10]})
    return posts


def collect_scout_reports(since_days=7):
    """Read latest SCOUT report from Obsidian, extract gaps."""
    if not SCOUT_OBSIDIAN_DIR.exists():
        return None
    reports = sorted(SCOUT_OBSIDIAN_DIR.glob("SCOUT_*.md"), reverse=True)
    if not reports:
        return None
    latest = reports[0]
    content = latest.read_text()
    gaps = []
    for line in content.split("\n"):
        m = re.search(r"\*\*(.+?)\*\*: gap \+([\d.]+)%", line)
        if m:
            gaps.append({"category": m.group(1), "gap": float(m.group(2))})
    return {"file": str(latest), "gaps": gaps, "date": latest.stem.replace("SCOUT_", "")}


def collect_bsa():
    """Read BSA thread for strategic bets."""
    thread = read_json(BSA_DIR / "bsa_thread.json")
    if not thread:
        return None
    bets = thread.get("current_bets", [])
    if not bets:
        bets = thread.get("strategic_bets", [])
    status = thread.get("status", "?")
    round_num = thread.get("round", 0)
    return {"bets": bets, "status": status, "round": round_num}


def collect_dev_status():
    """Read PM history for dev task status."""
    history = read_json(ORCH_DIR / "pm_history.json")
    if not history or not isinstance(history, list):
        return []
    # Last 5 entries, keep GO/NO_GO status
    recent = []
    for entry in sorted(history, key=lambda x: x.get("assessed_at", ""), reverse=True)[:5]:
        recent.append({
            "task": entry.get("task", "?")[:80],
            "verdict": entry.get("verdict", "?"),
            "date": entry.get("assessed_at", "?")[:10],
            "auto_run": entry.get("auto_run"),
        })
    return recent


def collect_api_scout(since_days=3):
    """Read latest API Scout analyses from Obsidian."""
    scout_dir = OBSIDIAN_DIR / "API Practicum" / "Scout"
    if not scout_dir.exists():
        return []
    reports = []
    for f in sorted(scout_dir.iterdir(), reverse=True)[:6]:
        if not f.name.endswith(".md"):
            continue
        content = f.read_text()
        summary = ""
        findings = 0
        for line in content.split("\n"):
            if line.startswith("## Summary"):
                summary = content.split("## Summary")[1].split("\n")[1:3]
                summary = " ".join(s.strip() for s in summary if s.strip())[:150]
            m = re.match(r"## Findings \((\d+)\)", line)
            if m:
                findings = int(m.group(1))
        reports.append({
            "repo": f.name.split("_")[0] if "_" in f.name else f.name,
            "file": str(f),
            "findings": findings,
            "summary": summary,
        })
    return reports


def collect_streams():
    """Check activity across streams from weekly data."""
    posts = collect_posts(since_days=7)
    return {"posts": len(posts)}


# ── Digest Builder ───────────────────────────────────────────────────────────

def build_digest():
    """Compile all data into a structured digest dict."""
    log("Collecting data...")

    # System health
    error_count = count_recent_errors([
        "cmd_processor.log", "content_manager.log", "researcher.log",
        "imap_check.log", "bsa.log", "api_scout.log",
    ])
    chron_marks = check_cron_health()
    health = "🟢" if error_count == 0 else f"🟡"
    health_detail = f"Всё в норме" if error_count == 0 else f"{error_count} ошибок в логах"

    # Commands
    cmds, cmd_count = collect_processed_commands()

    # Posts
    posts = collect_posts()

    # SCOUT
    scout = collect_scout_reports()

    # BSA
    bsa = collect_bsa()

    # Dev
    dev = collect_dev_status()

    # API Scout
    api_scout = collect_api_scout()

    # Streams
    streams = collect_streams()

    # Yesterday's content_manager log
    cm_log = tail_log("content_manager.log", 10)

    # Greeting
    greeting = pick_greeting()

    return {
        "greeting": greeting,
        "health": health,
        "health_detail": health_detail,
        "chron_marks": chron_marks,
        "date": moscow_time().strftime("%d %B %Y"),
        "cmd_count": cmd_count,
        "cmds": cmds,
        "posts": posts,
        "scout": scout,
        "bsa": bsa,
        "dev": dev,
        "api_scout": api_scout,
        "streams": streams,
        "cm_log": cm_log,
    }


def format_digest(d):
    """Format digest dict as a markdown email body."""
    lines = []
    lines.append(d["greeting"])
    lines.append("")
    lines.append("")

    # HEALTH
    lines.append(f"**Система:** {d['health']} {d['health_detail']}")
    lines.append("")

    # STREAMS — top
    week_posts = d["streams"].get("posts", 0)
    lines.append("━━━ **ЧЕМ ЗАЙМЁШЬСЯ СЕГОДНЯ** ━━━")
    lines.append("")

    # Show recent posts
    if d["posts"]:
        for p in d["posts"]:
            angle_text = f" — {p['angle']}" if p.get("angle") else ""
            lines.append(f"● [{p['title']}]({p['file']}){angle_text}")
    else:
        lines.append("● Новых постов пока нет — самое время начать!")
    lines.append("")

    lines.append(f"📡 **Неделя:** 📱 {week_posts} постов | ▶️ YouTube: 0 | 📸 Insta: 0")
    lines.append("")

    # YESTERDAY
    lines.append("━━━ **ВЧЕРА СОТВОРИЛИ** ━━━")
    lines.append("")

    # Processed commands
    if d["cmds"]:
        for cmd in d["cmds"][:5]:
            c = cmd.get("command", "?")
            args = (cmd.get("args") or "")[:60]
            lines.append(f"● Команда `{c}`: {args}")
    else:
        lines.append("● Команд не было")

    # SCOUT
    if d["scout"]:
        gaps_text = ""
        if d["scout"]["gaps"]:
            gaps_str = ", ".join(f"{g['category']} +{g['gap']}%" for g in d["scout"]["gaps"])
            gaps_text = f" gaps: {gaps_str}"
        lines.append(f"● SCOUT: {len(d['scout']['gaps'])} gaps{gaps_text}")

    # API Scout
    for r in d.get("api_scout", []):
        lines.append(f"● API Scout {r['repo']}: {r['findings']} finding{r['findings'] > 1 and 's' or ''} — {r['summary'][:100]}")

    # Content manager log
    if d["cm_log"]:
        for line in d["cm_log"].split("\n")[:3]:
            if "EMAIL" in line or "sent" in line or "TOPIC" in line:
                lines.append(f"● {line.strip()}")
    lines.append("")

    # DEV
    lines.append("━━━ **DEV ПОТОК** ━━━")
    lines.append("")
    if d["dev"]:
        for entry in d["dev"]:
            v = entry.get("verdict", "?")
            auto = entry.get("auto_run")
            icon = {"GO": "✅", "NO_GO": "❌", "NEED_MORE_INFO": "🟡"}.get(v, "⚪")
            task = entry.get("task", "?")[:70]
            date = entry.get("date", "")
            if auto:
                lines.append(f"{icon} {task} — {date} [auto: {auto.get('branch','?')[:30]}]")
            else:
                lines.append(f"{icon} {task} — {date}")
    else:
        lines.append("Нет dev-активности")
    lines.append("")

    # BSA
    if d["bsa"]:
        lines.append("━━━ **СТРАТЕГИЧЕСКИЕ СТАВКИ** ━━━")
        lines.append("")
        for bet in d["bsa"]["bets"]:
            title = bet.get("title", bet.get("bet", "?"))
            desc = bet.get("description", bet.get("desc", ""))[:120]
            lines.append(f"🎯 **{title}**")
            if desc:
                lines.append(f"   {desc}")
            lines.append("")
        lines.append(f"*Раунд {d['bsa']['round']} | Статус: {d['bsa']['status']}*")
        lines.append("")

    # Footer
    lines.append("━━━")
    lines.append(f"*Дайджест собран {d['date']} в {moscow_time().strftime('%H:%M')} MSK*")
    lines.append(f"*Агентов в строю: Content Manager, PM Agent, BSA, SCOUT, API Scout, Researcher*")
    lines.append("")

    return "\n".join(lines)


# ── Email ────────────────────────────────────────────────────────────────────

def send_digest(markdown_body, dry_run=False):
    """Send the digest email via mailer, or print to stdout."""
    if dry_run:
        print("\n" + "=" * 60)
        print(markdown_body)
        print("=" * 60)
        return True

    try:
        sys.path.insert(0, str(BASE / "lib"))
        from mailer import load_config, send

        cfg = load_config(str(AGENTS_DIR / ".mailcfg"))
        date_str = moscow_time().strftime("%d.%m")
        subject = f"☀️ Дайджест {date_str} — пульс системы"

        # Strip markdown bold/links for plain text
        plain = re.sub(r"\*\*(.*?)\*\*", r"\1", markdown_body)
        plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", plain)
        plain = re.sub(r"━━+", "---", plain)

        send(subject, plain, html=None, cfg=cfg)
        log(f"Digest sent: {subject}")
        return True
    except Exception as e:
        log(f"Digest send failed: {e}")
        return False


# ── Save to Obsidian ─────────────────────────────────────────────────────────

def save_digest_to_obsidian(markdown_body):
    """Save digest to Obsidian vault for reference."""
    try:
        SAVE_DIGEST_DIR.mkdir(parents=True, exist_ok=True)
        date_str = moscow_time().strftime("%Y-%m-%d")
        filename = SAVE_DIGEST_DIR / f"Digest_{date_str}.md"
        filename.write_text(markdown_body)
        log(f"Digest saved: {filename}")
    except Exception as e:
        log(f"Obsidian save failed: {e}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Daily Digest Agent")
    parser.add_argument("--dry-run", action="store_true", help="Print digest, no email")
    args = parser.parse_args()

    log("=== Digest Agent Start ===")
    digest_data = build_digest()
    markdown_body = format_digest(digest_data)

    if args.dry_run:
        send_digest(markdown_body, dry_run=True)
    else:
        send_digest(markdown_body)
        save_digest_to_obsidian(markdown_body)

    log("=== Digest Agent Complete ===")


if __name__ == "__main__":
    main()

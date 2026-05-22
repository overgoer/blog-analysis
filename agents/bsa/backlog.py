#!/usr/bin/env python3
"""
Backlog Manager — единый бэклог для Bizzy, SCOUT, dev-сканеров и PM.

Файл:      obsidian-vault/.../Стратегия/Бэклог.md (+ json-копия для машин)
Формат:    bullet-list with tags, парсится линейно
ID:        B-XXX (автоинкремент)
Источники: manual | scout | scanner | pm | telegram

Использование:
    python3 backlog.py                         # показать сводку
    python3 backlog.py --add "текст" --source scout --priority P2
    python3 backlog.py --done B-005
    python3 backlog.py --summary               # краткая сводка для Telegram
    python3 backlog.py --import-scout          # прочитать SCOUT → добавить идеи
    python3 backlog.py --import-scanner        # прочитать scanner → добавить задачи
    python3 backlog.py --sync-calendar         # прочитать календарь → добавить #post
"""

import json, os, re, sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
BACKLOG_FILE = Path("/root/obsidian-vault/eddytester/Стратегия/Бэклог.md")
BACKLOG_JSON = BASE / "backlog.json"
CALENDAR_FILE = Path("/root/obsidian-vault/eddytester/Стратегия/Календарь.md")

SCOUT_DIR = Path("/root/blog-analysis/agents/scout")
SCOUT_REPORTS = SCOUT_DIR / "reports"
SCOUT_RAW = SCOUT_DIR / "raw"

SCANNER_FILE = Path("/root/blog-analysis/agents/dev/latest_scan.json")

# ── Entry structure ───────────────────────────────────────────────────────

# Each entry is a dict:
#   id: str        B-001
#   priority: str  P0|P1|P2|P3
#   status: str    active|in_progress|done|cancelled
#   source: str    scout|scanner|pm|manual|telegram
#   origin: str    откуда пришло (конкретный источник)
#   created: str   2026-05-18
#   last_activity: str  2026-05-18 (обновляется при изменении статуса)
#   title: str     короткое название
#   desc: str      описание (optional)
#   section: str   sprint|queue|scout|dev

ENTRY_RE = re.compile(r'^- \[(P[0-3])\]\s+(B-\d+)\s+(.+?)(?:\s+`([^`]+)`.*)?$')
STATUS_RE = re.compile(r'^\s+Статус:\s*(.+?)(?:\.\s+(.+))?$')
TAG_RE = re.compile(r'`([^`]+)`')

# Canonical section names (без эмодзи — они добавляются при записи)
SECTION_ICONS = {
    "Активный спринт (P0-P1)": "🔥 ",
    "Очередь (P2-P3)": "",
    "Из SCOUT": "📡 ",
    "DEV": "🔧 ",
    "other": "",
}
CANONICAL_SECTIONS = list(SECTION_ICONS.keys())

# Strip emoji/icon prefix from a section header
STRIP_ICON = re.compile(r'^[^\wа-яА-Я]+ ', re.UNICODE)


def strip_icon(section):
    """Remove emoji/icon prefix from section name."""
    # Remove common emoji + space prefix
    while section and (ord(section[0]) > 127 or section[0] in " "):
        stripped = STRIP_ICON.sub("", section)
        if stripped == section:
            break
        section = stripped
    return section.strip()


def with_icon(section):
    """Add icon prefix to canonical section name."""
    icon = SECTION_ICONS.get(section, "")
    return f"{icon}{section}" if icon else section


def log(msg):
    print(f"[backlog] {msg}")


# ── Read/write backlog ────────────────────────────────────────────────────


def read_backlog():
    """Parse Бэклог.md into list of entry dicts. Returns (entries, sections_order)."""
    if not BACKLOG_FILE.exists():
        return [], []

    text = BACKLOG_FILE.read_text(encoding="utf-8")
    lines = text.split("\n")

    entries = []
    sections_order = []
    current_section = None
    current_entry = None

    for line in lines:
        # Section header
        if line.startswith("## "):
            raw_section = line[3:].strip()
            current_section = strip_icon(raw_section)
            sections_order.append(raw_section)
            continue

        # Entry line: - [P0] B-001 Title `source` `origin` `date`
        m = ENTRY_RE.match(line)
        if m:
            if current_entry:
                entries.append(current_entry)
            tags = TAG_RE.findall(line)
            raw_title = m.group(3).strip(" *")
            # Strip any status icons from persisted title (write_backlog adds them fresh)
            while raw_title and raw_title[0] in ("✅", "🔄", "❌"):
                raw_title = raw_title[1:].strip()
            raw_title = raw_title.strip()
            current_entry = {
                "id": m.group(2),
                "priority": m.group(1),
                "title": raw_title,
                "status": "active",
                "desc": "",
                "section": current_section or "other",
            }
            if len(tags) >= 1:
                current_entry["source"] = tags[0]
            if len(tags) >= 2:
                current_entry["origin"] = tags[1]
            if len(tags) >= 3:
                current_entry["created"] = tags[2]
            if len(tags) >= 4:
                current_entry["last_activity"] = tags[3]
            continue

        # Status line continuation
        if current_entry and line.startswith("  Статус:"):
            sm = STATUS_RE.match(line)
            if sm:
                current_entry["status"] = sm.group(1).strip()
                if sm.group(2):
                    current_entry["desc"] = sm.group(2).strip()
            continue

        # Description continuation (indented line after status)
        if current_entry and line.startswith("  ") and line.strip():
            txt = line.strip()
            if current_entry["desc"]:
                current_entry["desc"] += " " + txt

    if current_entry:
        entries.append(current_entry)

    return entries, sections_order


def write_backlog(entries, sections_order=None):
    """Write entries back to Бэклог.md."""
    if sections_order is None:
        _, sections_order = read_backlog()
        if not sections_order:
            sections_order = [with_icon(s) for s in CANONICAL_SECTIONS if s != "other"]

    # Group entries by section
    by_section = {}
    for e in entries:
        sec = e.get("section", "other")
        by_section.setdefault(sec, []).append(e)

    # Collect all sections: keep original order, add any missing canonical sections with entries
    all_sections = []
    seen = set()
    # First, add sections from sections_order (original file order)
    for raw_sec in sections_order:
        canonical = strip_icon(raw_sec)
        if canonical not in seen:
            all_sections.append(raw_sec)
            seen.add(canonical)
    # Add any canonical sections that have entries but aren't in the file yet
    for canonical in CANONICAL_SECTIONS:
        if canonical in by_section and canonical not in seen:
            all_sections.append(with_icon(canonical))
            seen.add(canonical)
    # Add any remaining sections with entries
    for sec in by_section:
        if sec not in seen:
            # Keep as-is with icon if it has one
            all_sections.append(with_icon(sec))
            seen.add(sec)

    lines = []
    lines.append("---")
    lines.append(f"updated: {datetime.now().strftime('%Y-%m-%dT%H:%M')}")
    lines.append("---")
    lines.append("")
    lines.append("# Бэклог")
    lines.append("")

    for section in all_sections:
        canonical = strip_icon(section)
        section_entries = by_section.get(canonical, [])
        if not section_entries:
            continue
        lines.append(f"## {section}")
        lines.append("")
        for e in section_entries:
            tags = " ".join(
                f"`{e.get(k, '?')}`"
                for k in ("source", "origin", "created")
                if e.get(k)
            )
            la = e.get("last_activity")
            if la:
                tags += f" `{la}`"
            status_icon = {"done": "✅", "cancelled": "❌", "in_progress": "🔄", "active": ""}.get(
                e.get("status", "active"), ""
            )
            title = e.get("title", "?")
            if status_icon:
                title = f"{status_icon} {title}"
            lines.append(f"- [{e.get('priority', 'P3')}] {e.get('id', 'B-???')} {title} {tags}")
            status = e.get("status", "active")
            desc = e.get("desc", "")
            if desc:
                lines.append(f"  Статус: {status}. {desc}")
            else:
                lines.append(f"  Статус: {status}")
            lines.append("")
        lines.append("")

    BACKLOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKLOG_FILE.write_text("\n".join(lines), encoding="utf-8")

    BACKLOG_JSON.write_text(
        json.dumps(
            {"updated": datetime.now().isoformat(), "entries": entries},
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )


# ── ID generation ─────────────────────────────────────────────────────────


def next_id(entries):
    existing = [int(e["id"].split("-")[1]) for e in entries if e.get("id", "").startswith("B-")]
    return f"B-{(max(existing) + 1) if existing else 1:03d}"


# ── CRUD operations ───────────────────────────────────────────────────────


def add_entry(title, priority="P3", source="manual", origin="manual", desc="", section="Очередь (P2-P3)"):
    """Add a new entry to the backlog."""
    entries, sections = read_backlog()
    today = datetime.now().strftime("%Y-%m-%d")
    entry = {
        "id": next_id(entries),
        "priority": priority,
        "status": "active",
        "source": source,
        "origin": origin,
        "created": today,
        "last_activity": today,
        "title": title,
        "desc": desc,
        "section": strip_icon(section) or "other",
    }
    entries.append(entry)
    write_backlog(entries, sections)
    log(f"Added: {entry['id']} [{priority}] {title}")
    return entry


def _touch(e):
    """Update last_activity to today."""
    e["last_activity"] = datetime.now().strftime("%Y-%m-%d")


def mark_done(entry_id):
    """Mark an entry as done."""
    entries, sections = read_backlog()
    for e in entries:
        if e["id"] == entry_id:
            e["status"] = "done"
            _touch(e)
            write_backlog(entries, sections)
            log(f"Done: {entry_id} — {e['title']}")
            return True
    log(f"Not found: {entry_id}")
    return False


def mark_in_progress(entry_id):
    entries, sections = read_backlog()
    for e in entries:
        if e["id"] == entry_id:
            e["status"] = "in_progress"
            _touch(e)
            write_backlog(entries, sections)
            return True
    return False


def _staleness_days(e):
    """Days since last_activity (or created fallback). Returns int or None."""
    raw = e.get("last_activity") or e.get("created")
    if not raw:
        return None
    try:
        d = datetime.strptime(raw, "%Y-%m-%d")
        return (datetime.now() - d).days
    except (ValueError, TypeError):
        return None


def get_summary():
    """Return a short Telegram-friendly summary."""
    entries, _ = read_backlog()
    if not entries:
        return "📋 Бэклог пуст."

    lines = ["📋 *Бэклог*"]
    active = [e for e in entries if e["status"] not in ("done", "cancelled")]
    done = [e for e in entries if e["status"] == "done"]

    if not active:
        lines.append("  Всё сделано! 🎉")
    else:
        for p in ("P0", "P1", "P2", "P3"):
            pe = [e for e in active if e["priority"] == p]
            if pe:
                lines.append(f"  *{p}:*")
                for e in pe:
                    icon = "🔄" if e["status"] == "in_progress" else "·"
                    sid = e["id"]
                    src = e.get("source", "?")
                    stale = _staleness_days(e)
                    suffix = ""
                    if stale is not None and stale >= 3:
                        suffix = f" ⏳{stale}д"
                    elif stale is not None and stale >= 1:
                        suffix = f" ({stale}д)"
                    lines.append(f"    {icon} {sid} {e['title']} `{src}`{suffix}")
                lines.append("")

    lines.append(f"  ✅ {len(done)} завершено · {len(active)} в работе")
    return "\n".join(lines)


# ── SCOUT integration ─────────────────────────────────────────────────────


def import_scout():
    """Read latest SCOUT report, add content ideas to backlog with dedup."""
    reports = sorted(SCOUT_REPORTS.glob("summary_*.json"))
    if not reports:
        log("No SCOUT reports found")
        return 0

    data = json.loads(reports[-1].read_text())

    # Load existing entries for dedup
    entries, sections = read_backlog()
    existing_titles = set(e["title"].lower().strip() for e in entries)
    existing_plain = set(t.replace("✅ ", "").replace("🔄 ", "") for t in existing_titles)
    added = 0

    def _maybe_add(title, priority, source, origin, desc, section):
        nonlocal added, entries, sections
        key = title.lower().strip()
        if key in existing_titles or key in existing_plain:
            return
        entry = {
            "id": next_id(entries),
            "priority": priority,
            "status": "active",
            "source": source,
            "origin": origin,
            "created": datetime.now().strftime("%Y-%m-%d"),
            "last_activity": datetime.now().strftime("%Y-%m-%d"),
            "title": title,
            "desc": desc,
            "section": strip_icon(section),
        }
        entries.append(entry)
        existing_titles.add(key)
        existing_plain.add(key)
        added += 1

    # Competitor topics
    for ch_id, ch_data in data.get("competitor_results", {}).items():
        cats = ch_data.get("categories", [])
        for cat in cats:
            title = f"Пост про {cat} (как у {ch_id})"
            desc = f"{ch_id} пишет в категории «{cat}»"
            _maybe_add(title, "P3", "scout", ch_id, desc, "Из SCOUT")

    # Recommendations
    for rec in data.get("recommendations", []):
        if len(rec) > 20:
            _maybe_add(rec[:80], "P3", "scout", "recommendation", rec[:200], "Из SCOUT")

    # Raw data fallback (only if nothing was added from structured data)
    if not added:
        for f in sorted(SCOUT_RAW.glob("*.json"))[:3]:
            try:
                raw = json.loads(f.read_text())
                posts = raw if isinstance(raw, list) else raw.get("messages", [])
                for p in posts[:5]:
                    text = ""
                    if isinstance(p, dict):
                        t = p.get("text", "")
                        text = t if isinstance(t, str) else " ".join(str(x) for x in t) if isinstance(t, list) else ""
                    if text and len(text) > 30:
                        _maybe_add(text[:80], "P3", "scout", f.stem, text[:200], "Из SCOUT")
            except Exception:
                pass

    if added:
        write_backlog(entries, sections)

    log(f"SCOUT: added {added} entries")
    return added


# ── Scanner integration ────────────────────────────────────────────────────


def import_scanner():
    """Read latest scanner report, add dev tasks to backlog with dedup."""
    if not SCANNER_FILE.exists():
        log("No scanner report")
        return 0

    data = json.loads(SCANNER_FILE.read_text())

    entries, sections = read_backlog()
    existing_titles = set(e["title"].lower().strip() for e in entries)
    existing_plain = set(t.replace("✅ ", "").replace("🔄 ", "") for t in existing_titles)
    added = 0

    def _maybe_add(title, priority, source, origin, desc, section):
        nonlocal added, entries, sections
        key = title.lower().strip()
        if key in existing_titles or key in existing_plain:
            return
        entry = {
            "id": next_id(entries),
            "priority": priority,
            "status": "active",
            "source": source,
            "origin": origin,
            "created": datetime.now().strftime("%Y-%m-%d"),
            "last_activity": datetime.now().strftime("%Y-%m-%d"),
            "title": title,
            "desc": desc,
            "section": strip_icon(section),
        }
        entries.append(entry)
        existing_titles.add(key)
        added += 1

    known_issues = {
        "api-practicum-bot": [
            ("Вынести токен из хардкода в .env", "api-practicum-bot: hardcoded token в main.py:25"),
            ("DB_PATH/DB_NAME inconsistency", "api-practicum-bot: DB_PATH/DB_NAME не согласованы"),
        ],
    }

    for repo, issues in known_issues.items():
        for title, desc in issues:
            _maybe_add(title, "P2", "scanner", repo, desc, "DEV")

    bugs = data.get("bugs_summary", "")
    if bugs and len(bugs) > 20:
        _maybe_add("Баг-фикс из документации", "P2", "scanner", "bugs.md", bugs[:200], "DEV")

    if added:
        write_backlog(entries, sections)

    log(f"Scanner: added {added} entries")
    return added


# ── Calendar sync ─────────────────────────────────────────────────────────


def sync_calendar():
    """Read Календарь.md, add non-published future posts to backlog as #post."""
    if not CALENDAR_FILE.exists():
        log("No calendar file")
        return 0

    text = CALENDAR_FILE.read_text(encoding="utf-8")
    lines = text.split("\n")

    entries, sections = read_backlog()
    # Build set of existing full titles + raw topic from desc
    existing_titles = set()
    existing_topics = set()
    for e in entries:
        existing_titles.add(e["title"].lower().strip())
        existing_topics.add(e["title"].lower().strip().replace("✅ ", "").replace("🔄 ", ""))
        desc = e.get("desc", "")
        if desc:
            existing_topics.add(desc.lower().strip())
    added = 0

    for line in lines:
        stripped = line.strip()

        if not stripped.startswith("|"):
            continue

        cols = [c.strip() for c in stripped.split("|")]
        cols = [c for c in cols if c]

        # Skip header, separator, empty rows
        if len(cols) < 5:
            continue
        if any("дата" in c.lower() for c in cols):
            continue
        if set(c.replace("-", "").strip() for c in cols) == {""}:
            continue

        date_str = cols[0].strip("* ").replace("**", "")
        topic = cols[5].strip("* ").replace("**", "") if len(cols) > 5 else ""
        status = cols[-1].strip("* ").replace("**", "") if cols else ""

        if "✅" in status or "ОПУБЛИКОВ" in status:
            continue
        if not topic or topic in ("Тема", "—", "") or len(topic) < 5:
            continue
        if topic in ("Комм (среднее)", "Переходы в бот", "Выручка", "Заметки"):
            continue
        if any(topic.startswith(w) for w in ("Запланировано", "Опубликовано", "Неделя", "Итого", "Резерв")):
            continue

        fmt = cols[3].strip("* ") if len(cols) > 3 else ""
        num = cols[4].strip("* ") if len(cols) > 4 else ""
        title = f"#post {fmt} {num} {topic}" if fmt and num and fmt != "—" else f"#post {topic}"

        title_key = title.lower().strip()
        topic_key = topic.lower().strip()
        if title_key in existing_titles or topic_key in existing_topics:
            continue

        entry = {
            "id": next_id(entries),
            "priority": "P2",
            "status": "active",
            "source": "manual",
            "origin": "calendar",
            "created": datetime.now().strftime("%Y-%m-%d"),
            "title": title.strip(),
            "desc": f"Из календаря: {date_str}, статус: {status}",
            "section": "Очередь (P2-P3)",
        }
        entries.append(entry)
        existing_titles.add(title_key)
        existing_topics.add(topic_key)
        added += 1

    if added:
        write_backlog(entries, sections)

    log(f"Calendar: synced {added} posts to backlog")
    return added


# ── CLI ────────────────────────────────────────────────────────────────────


def main():
    args = sys.argv[1:]

    if not args:
        entries, _ = read_backlog()
        if not entries:
            print("📋 Бэклог пуст.")
            return
        active = [e for e in entries if e["status"] not in ("done", "cancelled")]
        for e in active:
            icon = {"in_progress": "🔄", "active": "·"}.get(e["status"], "·")
            print(f"  {icon} {e['id']} [{e['priority']}] {e['title']} ({e.get('source', '?')})")
        done_count = sum(1 for e in entries if e["status"] == "done")
        print(f"\n  {done_count} завершено · {len(active)} в работе")
        return

    if "--add" in args:
        idx = args.index("--add")
        text = args[idx + 1] if idx + 1 < len(args) else "?"
        priority = "P3"
        source = "manual"
        origin = "manual"
        section = "Очередь (P2-P3)"

        if "--priority" in args:
            pidx = args.index("--priority")
            priority = args[pidx + 1] if pidx + 1 < len(args) else "P3"
        if "--source" in args:
            sidx = args.index("--source")
            source = args[sidx + 1] if sidx + 1 < len(args) else "manual"
        if "--origin" in args:
            oidx = args.index("--origin")
            origin = args[oidx + 1] if oidx + 1 < len(args) else "manual"
        if "--section" in args:
            sidx = args.index("--section")
            section = args[sidx + 1] if sidx + 1 < len(args) else "Очередь (P2-P3)"

        add_entry(text, priority, source, origin, section=section)

    if "--done" in args:
        idx = args.index("--done")
        eid = args[idx + 1] if idx + 1 < len(args) else ""
        mark_done(eid)

    if "--summary" in args:
        print(get_summary())

    if "--import-scout" in args:
        import_scout()

    if "--import-scanner" in args:
        import_scanner()

    if "--sync-calendar" in args:
        sync_calendar()

    if "--push" in args:
        idx = args.index("--push")
        text = args[idx + 1] if idx + 1 < len(args) else ""
        if text:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:20]
            (BASE / "outgoing" / f"out_{ts}.json").write_text(json.dumps({
                "text": text, "created_at": datetime.now().isoformat(),
            }, ensure_ascii=False))
            print(f"Pushed: %.60s" % text)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
requests_listener.py — reads requests.md, finds new ! tasks, routes them.

Sections in requests.md:
  -----задачи к BSA-----    <- user writes here
  -----статус BSA-----      <- BSA writes here (in-progress/done)

Classification:
  RESEARCH  -> researcher.py (DeepSeek, runs on server)
  CONTENT   -> queued for BSA (strategic agent)
  DEV       -> queued for BSA

Safe by design:
- Uses flock to prevent concurrent runs
- Task state is in the file itself — crash-safe
- Dry-run mode (--dry-run) for testing
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# -- Config --
REQUESTS_FILE = Path("/root/obsidian-vault/requests.md")
VAULT_DIR = Path("/root/obsidian-vault")
LOCK_FILE = Path("/tmp/requests_listener.lock")
LOG_FILE = Path("/tmp/requests_listener.log")
AGENTS_DIR = Path("/root/blog-analysis/agents")
RESEARCHER = AGENTS_DIR / "researcher" / "researcher.py"

TIMEOUT_MINUTES = 30  # if running task older than this, retry

# Classification keywords (lowercase)
RESEARCH_KEYS = [
    "исследуй", "research", "найди", "изучи", "поищи",
    "разбери", "проанализируй", "собери", "проверь",
]
CONTENT_KEYS = [
    "напиши", "перепиши", "пост", "создай", "отредактируй",
    "оформи", "дополни", "придумай", "напиcать",
]
DEV_KEYS = [
    "сделай", "реализуй", "добавь", "почини", "настрой",
    "установи", "обнови", "переделай", "мигрируй",
]


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def acquire_lock():
    """Acquire process lock via fcntl. Safe for cron."""
    try:
        import fcntl
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(fd, 0)
            os.write(fd, str(os.getpid()).encode())
            os.fsync(fd)
            return True
        except BlockingIOError:
            os.close(fd)
            return False
    except ImportError:
        return True


def release_lock():
    try:
        os.unlink(LOCK_FILE)
    except FileNotFoundError:
        pass


def git_pull():
    """Pull latest changes before reading."""
    subprocess.run(
        ["git", "-C", str(VAULT_DIR), "pull", "origin", "main", "--ff-only"],
        capture_output=True, timeout=30,
    )


def git_commit_push():
    """Commit and push status changes to requests.md."""
    subprocess.run(
        ["git", "-C", str(VAULT_DIR), "add", str(REQUESTS_FILE)],
        capture_output=True, timeout=30,
    )
    r = subprocess.run(
        ["git", "-C", str(VAULT_DIR), "diff", "--cached", "--quiet"],
        capture_output=True, timeout=30,
    )
    if r.returncode != 0:
        msg = f"sync: requests_listener {datetime.now().strftime('%Y-%m-%d_%H:%M')}"
        subprocess.run(
            ["git", "-C", str(VAULT_DIR), "commit", "-m", msg],
            capture_output=True, timeout=30,
        )
        subprocess.run(
            ["git", "-C", str(VAULT_DIR), "push", "origin", "main"],
            capture_output=True, timeout=30,
        )
        return True
    return False


def now_str():
    return datetime.now().strftime("%H:%M")


# -- requests.md parsing --


def split_sections(text):
    """Split into (user_content_lines, status_lines)."""
    status_marker = "-----статус"
    lines = text.split("\n")
    status_start = None
    for i, line in enumerate(lines):
        if status_marker in line.lower():
            status_start = i
            break
    if status_start is not None:
        return lines[:status_start], lines[status_start:], True
    return lines, [], False


def find_tasks_in_user_section(user_lines):
    """Find tasks ending with ! in user section. Each line = one task."""
    tasks = []
    # Join lines, split into logical blocks (separated by blank lines),
    # but each line ending with ! within a block is a separate task
    full_text = "\n".join(user_lines)
    lines = full_text.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.endswith("!"):
            task_text = stripped.rstrip("!").strip()
            task_text = re.sub(r"\s+", " ", task_text)
            tasks.append({"text": task_text, "raw": stripped})
    return tasks


def classify_task(task_text):
    """Classify task: RESEARCH / CONTENT / DEV."""
    t = task_text.lower()
    for kw in RESEARCH_KEYS:
        if kw in t:
            return "RESEARCH"
    for kw in CONTENT_KEYS:
        if kw in t:
            return "CONTENT"
    for kw in DEV_KEYS:
        if kw in t:
            return "DEV"
    return "CONTENT"  # default: send to BSA


def parse_status_section(status_lines):
    """Parse running/done tasks from status section.
    Returns dict: clean_task_text -> {status, detail, taken_at}
    """
    known = {}
    for line in status_lines:
        ls = line.strip()
        # Match patterns: ✅ task, 🔄 task (взято HH:MM), ❌ task
        m = re.match(r"^([✅🔄❌⏳])\s+(.+?)(?:\s*→\s*(.+))?$", ls)
        if m:
            emoji = m.group(1)
            raw_text = m.group(2).strip()
            detail = m.group(3).strip() if m.group(3) else ""
            # Extract (взято HH:MM) from running tasks
            taken_match = re.search(r"\(взято (\d+:\d+)\)", raw_text)
            taken_at = taken_match.group(1) if taken_match else None
            clean_text = re.sub(r"\s*\(взято \d+:\d+\)", "", raw_text).strip()
            status_map = {"✅": "done", "🔄": "running", "❌": "failed", "⏳": "pending"}
            known[clean_text] = {
                "status": status_map.get(emoji, "pending"),
                "detail": detail,
                "taken_at": taken_at,
            }
    return known


def build_status_block(tasks_running, tasks_done):
    """Build the status section markdown."""
    lines = []
    lines.append("-----статус BSA-----")
    lines.append("")
    if tasks_running:
        lines.append("В работе:")
        for t in tasks_running:
            lines.append(f"🔄 {t['text']} (взято {t['taken_at']})")
        lines.append("")
    if tasks_done:
        lines.append("Готово:")
        for t in tasks_done:
            detail = f" → {t['detail']}" if t.get('detail') else ""
            lines.append(f"✅ {t['text']}{detail}")
        lines.append("")
    if not tasks_running and not tasks_done:
        lines.append("(нет активных задач)")
        lines.append("")
    return "\n".join(lines)


# -- task execution --


def run_researcher(topic):
    """Run researcher.py. Returns (success, result_path_or_msg)."""
    try:
        log(f"  Starting researcher: {topic[:80]}")
        r = subprocess.run(
            [sys.executable, str(RESEARCHER), topic],
            capture_output=True, text=True, timeout=300,
        )
        # Find report path in stdout
        m = re.search(r"(?:Полный отчёт|Full report):\s*(.+\.md)", r.stdout)
        if m:
            return True, m.group(1)
        elif r.returncode == 0:
            return True, ""
        else:
            return False, r.stderr[:200]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)


def is_stale(taken_at):
    """Check if running task is older than TIMEOUT_MINUTES."""
    if not taken_at:
        return True
    try:
        parts = taken_at.split(":")
        now = datetime.now()
        taken = now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0)
        if taken > now:
            taken -= timedelta(days=1)
        return (now - taken).total_seconds() > TIMEOUT_MINUTES * 60
    except (ValueError, IndexError):
        return True


# -- main --


def main():
    dry_run = "--dry-run" in sys.argv
    if not dry_run and not acquire_lock():
        log("Another instance running, skipping")
        return
    try:
        _main(dry_run)
    finally:
        if not dry_run:
            release_lock()


def _main(dry_run):
    log("=" * 40)
    log("requests_listener started" + (" (DRY RUN)" if dry_run else ""))

    if not REQUESTS_FILE.exists():
        log(f"{REQUESTS_FILE} not found, skipping")
        return

    # Pull latest
    if not dry_run:
        git_pull()

    content = REQUESTS_FILE.read_text(encoding="utf-8")
    user_lines, status_lines, has_status = split_sections(content)
    known_tasks = parse_status_section(status_lines) if has_status else {}

    new_tasks = find_tasks_in_user_section(user_lines)
    if not new_tasks:
        log("No new tasks found")
        # Check for stale running tasks
        for t, info in known_tasks.items():
            if info["status"] == "running" and is_stale(info.get("taken_at", "")):
                log(f"  Stale task detected: {t}")
        return

    log(f"Found {len(new_tasks)} new task(s)")

    tasks_running = []
    tasks_done = []

    for task in new_tasks:
        task_text = task["text"]

        # Skip if already known
        if task_text in known_tasks:
            info = known_tasks[task_text]
            if info["status"] == "done":
                log(f"  Already done, skipping: {task_text}")
                tasks_done.append({"text": task_text, "detail": info["detail"]})
                continue
            elif info["status"] == "running":
                if is_stale(info.get("taken_at", "")):
                    log(f"  Stale, retrying: {task_text}")
                else:
                    log(f"  Already running: {task_text}")
                    continue

        task_type = classify_task(task_text)
        log(f"  [{task_type}] {task_text}")

        if task_type == "RESEARCH":
            if dry_run:
                log("    [DRY RUN] would run researcher")
                continue
            success, result = run_researcher(task_text)
            if success:
                detail = f"[отчёт]({result})" if result else "выполнено"
                tasks_done.append({"text": task_text, "detail": detail})
                log(f"    DONE: {result}")
            else:
                tasks_done.append({"text": task_text, "detail": f"❌ {result}"})
                log(f"    FAILED: {result}")
        else:
            if dry_run:
                log(f"    [DRY RUN] would queue for BSA")
                continue
            tasks_running.append({"text": task_text, "taken_at": now_str()})
            log("    Queued for BSA")

    # Merge with existing done tasks (preserve history)
    existing_done = [
        {"text": t, "detail": info["detail"]}
        for t, info in known_tasks.items()
        if info["status"] == "done"
    ]
    done_texts = set(t["text"] for t in tasks_done)
    for t in existing_done:
        if t["text"] not in done_texts:
            tasks_done.append(t)

    status_block = build_status_block(tasks_running, tasks_done)

    # Reconstruct full file
    user_header = "-----задачи к BSA-----"
    user_text = "\n".join(user_lines).strip()
    # Remove any stray status markers
    user_text = re.sub(r"^-----.*$", "", user_text, flags=re.MULTILINE).strip()
    full_text = user_header + "\n\n"
    if user_text:
        full_text += user_text + "\n\n"
    full_text += status_block + "\n"

    if dry_run:
        log("\n=== DRY RUN OUTPUT ===")
        print(full_text)
        return

    # Atomic write
    tmp = REQUESTS_FILE.with_suffix(".md.tmp")
    tmp.write_text(full_text, encoding="utf-8")
    tmp.rename(REQUESTS_FILE)
    log("File updated")

    pushed = git_commit_push()
    log(f"Done (pushed={pushed})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
requests_listener.py v2 — дверной звонок для BSA.

Читает requests.md, находит новые ! задачи,
отмечает их как ⏳ и будит BSA (bsa_chat.py --mode trigger).

Ничего не классифицирует, не запускает агентов.
Всё решение — за BSA.

Safe by design:
- Uses flock to prevent concurrent runs
- Atomic write via .tmp + rename
- Dry-run mode (--dry-run) for testing
"""

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# -- Config --
REQUESTS_FILE = Path("/root/obsidian-vault/requests.md")
VAULT_DIR = Path("/root/obsidian-vault")
LOCK_FILE = Path("/tmp/requests_listener.lock")
LOG_FILE = Path("/tmp/requests_listener.log")
AGENTS_DIR = Path("/root/blog-analysis/agents")
BSA_TRIGGER = AGENTS_DIR / "bsa" / "bsa_chat.py"


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
    """Find tasks ending with ! in user section."""
    tasks = []
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


def parse_status_section(status_lines):
    """Parse running/done tasks from status section.
    Returns dict: clean_task_text -> {status, detail, taken_at}
    """
    known = {}
    for line in status_lines:
        ls = line.strip()
        m = re.match(r"^([✅🔄❌⏳])\s+(.+?)(?:\s*→\s*(.+))?$", ls)
        if m:
            emoji = m.group(1)
            raw_text = m.group(2).strip()
            detail = m.group(3).strip() if m.group(3) else ""
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


def build_status_block(known_tasks):
    """Build the status section markdown from known_tasks dict."""
    lines = []
    lines.append("-----статус BSA-----")
    lines.append("")

    running = {k: v for k, v in known_tasks.items()
               if v["status"] in ("running", "pending")}
    done = {k: v for k, v in known_tasks.items()
            if v["status"] == "done"}

    if running:
        lines.append("В работе:")
        for text, info in running.items():
            taken = f" (взято {info['taken_at']})" if info.get('taken_at') else ""
            lines.append(f"🔄 {text}{taken}")
        lines.append("")
    if done:
        lines.append("Готово:")
        for text, info in done.items():
            detail = f" → {info['detail']}" if info.get('detail') else ""
            lines.append(f"✅ {text}{detail}")
        lines.append("")
    if not running and not done:
        lines.append("(нет активных задач)")
        lines.append("")
    return "\n".join(lines)


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
    log(f"requests_listener v2 started{' (DRY RUN)' if dry_run else ''}")

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
        return

    # Filter out tasks already tracked in status section
    fresh = []
    for t in new_tasks:
        if t["text"] in known_tasks:
            known_status = known_tasks[t["text"]]["status"]
            log(f"Already tracked ({known_status}), skipping: {t['text']}")
            continue
        fresh.append(t)

    if not fresh:
        log("All tasks already tracked by BSA")
        return

    log(f"Found {len(fresh)} new task(s), waking BSA")

    if dry_run:
        log("[DRY RUN] would mark ⏳ and call BSA")
        for t in fresh:
            log(f"  ⏳ {t['text']}")
        return

    # 1. Mark tasks as ⏳ (pending) in status section
    for t in fresh:
        known_tasks[t["text"]] = {
            "status": "pending",
            "detail": "",
            "taken_at": now_str(),
        }

    # Rebuild file with updated status
    status_block = build_status_block(known_tasks)
    user_header = "-----задачи к BSA-----"
    user_text = "\n".join(user_lines).strip()
    user_text = re.sub(r"^-----.*$", "", user_text, flags=re.MULTILINE).strip()
    full_text = user_header + "\n\n"
    if user_text:
        full_text += user_text + "\n\n"
    full_text += status_block + "\n"

    # Atomic write + commit
    tmp = REQUESTS_FILE.with_suffix(".md.tmp")
    tmp.write_text(full_text, encoding="utf-8")
    tmp.rename(REQUESTS_FILE)
    git_commit_push()
    log("Marked ⏳, committed. Now waking BSA...")

    # 2. Call BSA trigger (non-blocking for listener, but we wait for feedback)
    log(f"Calling: {BSA_TRIGGER} --mode trigger")
    result = subprocess.run(
        [sys.executable, str(BSA_TRIGGER), "--mode", "trigger"],
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode == 0:
        log("BSA completed successfully")
        if result.stdout:
            log(f"BSA output (last 200): {result.stdout.strip()[-200:]}")
    else:
        log(f"BSA failed (exit={result.returncode}): {result.stderr[:300]}")


if __name__ == "__main__":
    main()

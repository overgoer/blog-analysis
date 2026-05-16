#!/usr/bin/env python3
"""
requests_listener.py v2 — дверной звонок для BSA.

Читает requests.md, находит новые ! задачи,
отмечает их как ⏳ и будит BSA (bsa_chat.py --mode trigger).

Ничего не классифицирует, не запускает агентов.
Всё решение — за BSA.

После BSA — мержит статус, чтобы не потерять записи.
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
    subprocess.run(
        ["git", "-C", str(VAULT_DIR), "pull", "origin", "main", "--ff-only"],
        capture_output=True, timeout=30,
    )


def git_commit_push():
    subprocess.run(
        ["git", "-C", str(VAULT_DIR), "add", "-A"],
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
    status_marker = "-----статус"
    context_marker = "-----контекст"
    lines = text.split("\n")
    status_start = None
    context_start = None
    for i, line in enumerate(lines):
        if status_marker in line.lower() and status_start is None:
            status_start = i
        if context_marker in line.lower() and context_start is None:
            context_start = i
    if status_start is not None:
        if context_start is not None:
            return lines[:status_start], lines[status_start:context_start], lines[context_start:], True
        return lines[:status_start], lines[status_start:], [], True
    return lines, [], [], False


def find_tasks_in_user_section(user_lines):
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
    """Parse status section entries into dict."""
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
    lines = []
    lines.append("-----статус BSA-----")
    lines.append("")

    running = {k: v for k, v in known_tasks.items()
               if v["status"] in ("running", "pending")}
    done = {k: v for k, v in known_tasks.items()
            if v["status"] == "done"}

    # Dedup: exclude from running any task that is also done
    dupes = [k for k in running if k in done]
    if dupes:
        for k in dupes:
            del running[k]
        log(f"  Deduped {len(dupes)} tasks from running section")

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


def rebuild_file(user_lines, known_tasks, context_lines=None):
    """Rebuild requests.md from user content and known tasks."""
    # Safety: remove running entries not matching current user tasks
    user_tasks = set()
    for line in user_lines:
        line = line.strip().rstrip("!").strip()
        if line:
            user_tasks.add(line)
    if user_tasks:
        stale = [k for k in list(known_tasks) if known_tasks[k].get("status") in ("running", "pending") and k not in user_tasks]
        for k in stale:
            del known_tasks[k]
    status_block = build_status_block(known_tasks)
    user_header = "-----задачи к BSA-----"
    user_text = "\n".join(user_lines).strip()
    user_text = re.sub(r"^-----.*$", "", user_text, flags=re.MULTILINE).strip()
    full_text = user_header + "\n\n"
    if user_text:
        full_text += user_text + "\n\n"
    full_text += status_block + "\n"
    full_text += f"*последнее обновление: {datetime.now():%H:%M}*\n"
    # Preserve context section if it exists
    if context_lines:
        context_text = "\n".join(context_lines).strip()
        if context_text:
            full_text += context_text + "\n"
    return full_text


# -- main --

def update_timestamp_in_file():
    """Update the *последнее обновление* timestamp in requests.md."""
    try:
        text = REQUESTS_FILE.read_text(encoding="utf-8")
        new_ts = f"*последнее обновление: {datetime.now():%H:%M}*"
        import re
        if re.search(r"\*последнее обновление: \d{2}:\d{2}\*", text):
            text = re.sub(r"\*последнее обновление: \d{2}:\d{2}\*", new_ts, text)
        else:
            # No existing timestamp, add after status section
            text = text.replace("-----контекст задач-----", new_ts + "\n\n-----контекст задач-----")
        REQUESTS_FILE.write_text(text, encoding="utf-8")
    except Exception as e:
        log(f"update_timestamp error: {e}")

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

    if not dry_run:
        git_pull()

    content = REQUESTS_FILE.read_text(encoding="utf-8")
    user_lines, status_lines, context_lines, has_status = split_sections(content)
    known_tasks = parse_status_section(status_lines) if has_status else {}

    new_tasks = find_tasks_in_user_section(user_lines)
    if not new_tasks:
        log("No new tasks found")
        update_timestamp_in_file()
        return

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

    # 1. Mark as ⏳ and save pre-BSA state for merge
    for t in fresh:
        known_tasks[t["text"]] = {
            "status": "pending", "detail": "", "taken_at": now_str(),
        }

    full_text = rebuild_file(user_lines, known_tasks, context_lines)
    tmp = REQUESTS_FILE.with_suffix(".md.tmp")
    tmp.write_text(full_text, encoding="utf-8")
    tmp.rename(REQUESTS_FILE)
    git_commit_push()
    log("Marked ⏳, committed. Now waking BSA...")

    # Save snapshot of known_tasks BEFORE BSA for merge recovery
    pre_bsa_tasks = dict(known_tasks)

    # 2. Call BSA trigger
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

    # 3. Merge status: restore any entries BSA may have dropped
    try:
        new_content = REQUESTS_FILE.read_text(encoding="utf-8")
        _, new_status_lines, _, _ = split_sections(new_content)
        new_known = parse_status_section(new_status_lines)

        # If BSA wrote any status entries, trust its output.
        # Only restore pre-BSA entries if BSA left status completely empty (crashed).
        if new_known:
            log(f"BSA wrote {len(new_known)} status entries, skipping restore")
        else:
            restored = []
            for text, info in pre_bsa_tasks.items():
                if info["status"] in ("running", "pending"):
                    restored.append((text, info))
                    log(f"  Restored missing status: {text}")
            if restored:
                for text, info in restored:
                    new_known[text] = info
                merged_text = rebuild_file(user_lines, new_known, context_lines)
                mtmp = REQUESTS_FILE.with_suffix(".md.merge.tmp")
                mtmp.write_text(merged_text, encoding="utf-8")
                mtmp.rename(REQUESTS_FILE)
                git_commit_push()
                log(f"Restored {len(restored)} lost status entries")
    except Exception as e:
        log(f"Status merge failed: {e}")


if __name__ == "__main__":
    main()

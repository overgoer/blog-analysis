"""
requests_listener.py v3 -- dvernoj zvonok dlya BSA (inbox.md -> outbox.md).
Chitaet /root/obsidian-vault/inbox.md, nahodit novye ! zadachi
i ee-diskussiyu, budit BSA (bsa_chat.py).
Principy:
- Hash-based detekciya: esli inbox.md ne izmenilsya -- nichego ne delaem.
- Ne pishem NICHEGO v vault (nikakih timestampov, statusov, markerov).
- Ne commitim i ne pushim -- tolko chitaem.
- Working tree vsegda chistaya.
"""

import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

INBOX_FILE = Path('/root/obsidian-vault/inbox.md')
VAULT_DIR = Path('/root/obsidian-vault')
HASH_FILE = '/tmp/.inbox_last_hash'
LOCK_FILE = Path('/tmp/requests_listener.lock')
LOG_FILE = Path('/tmp/requests_listener.log')
AGENTS_DIR = Path('/root/blog-analysis/agents')
BSA_CHAT = AGENTS_DIR / 'bsa' / 'bsa_chat.py'

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def acquire_lock():
    try:
        import fcntl
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_RDWR)
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
        os.unlink(str(LOCK_FILE))
    except FileNotFoundError:
        pass

def git_pull():
    # Auto-commit any dirty files before pulling (Bizzy may have written via write_file)
    try:
        subprocess.run(['git', '-C', str(VAULT_DIR), 'add', '-A'], capture_output=True, timeout=15)
        r = subprocess.run(['git', '-C', str(VAULT_DIR), 'diff', '--cached', '--quiet'], capture_output=True, timeout=15)
        if r.returncode != 0:
            subprocess.run(['git', '-C', str(VAULT_DIR), 'commit', '-m', 'auto-save before pull'], capture_output=True, timeout=15)
    except Exception:
        pass
    r = subprocess.run(
        ['git', '-C', str(VAULT_DIR), 'pull', '--rebase'],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        log(f'git pull failed: {r.stderr[:200]}')
        return False
    return True

def read_hash():
    try:
        with open(HASH_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ''

def write_hash(h):
    with open(HASH_FILE, 'w') as f:
        f.write(h)

def find_tasks_in_text(text):
    tasks = []
    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.endswith('!'):
            task_text = stripped.rstrip('!').strip()
            task_text = re.sub(r'\s+', ' ', task_text)
            tasks.append(task_text)
    return tasks

def find_discussion_in_text(text):
    """Find discussion lines starting with ээ and ending with !."""
    questions = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('\u044d\u044d') and stripped.endswith('!'):
            questions.append(stripped)
    return questions

def main():
    dry_run = '--dry-run' in sys.argv
    if not dry_run and not acquire_lock():
        log('Another instance running, skipping')
        return
    try:
        _main(dry_run)
    finally:
        if not dry_run:
            release_lock()

def _main(dry_run):
    log('=' * 40)
    label = ' (DRY RUN)' if dry_run else ''
    log(f'requests_listener v3 started{label}')

    if not INBOX_FILE.exists():
        log(f'{INBOX_FILE} not found, skipping')
        return

    if not dry_run:
        if not git_pull():
            log('git pull failed, will still try to process current file')

    content = INBOX_FILE.read_text(encoding='utf-8')

    current_hash = hashlib.md5(content.encode()).hexdigest()
    last_hash = read_hash()
    if current_hash == last_hash:
        log('inbox.md unchanged, skipping')
        return
    log(f'inbox.md changed (hash: {current_hash[:12]}...)')

    tasks_section = ''
    discuss_section = ''
    current_section = None
    for line in content.split('\n'):
        if '\u0437\u0430\u0434\u0430\u0447' in line.lower():
            current_section = 'tasks'
            continue
        elif '\u0434\u0438\u0441\u043a\u0443\u0441\u0441\u0438\u044f' in line.lower():
            current_section = 'discuss'
            continue
        if current_section == 'tasks':
            tasks_section += line + '\n'
        elif current_section == 'discuss':
            discuss_section += line + '\n'

    tasks = find_tasks_in_text(tasks_section)
    questions = find_discussion_in_text(discuss_section)

    log(f'Tasks found: {len(tasks)}, Discussion messages: {len(questions)}')

    if not tasks and not questions:
        log('No new tasks or discussion content found')
        if not dry_run:
            write_hash(current_hash)
        return

    if dry_run:
        if tasks:
            log(f'[DRY RUN] Would call BSA with {len(tasks)} tasks')
        if questions:
            log(f'[DRY RUN] Would call BSA discuss: {questions[-1][:80]}...')
        return

    if tasks:
        log('Calling BSA --mode trigger')
        result = subprocess.run(
            [sys.executable, str(BSA_CHAT), '--mode', 'trigger'],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0:
            log('BSA trigger completed successfully')
            if result.stdout:
                log(f'BSA output (last 200): {result.stdout.strip()[-200:]}')
        else:
            log(f'BSA trigger failed (exit={result.returncode}): {result.stderr[:300]}')
            return

    elif questions:
        question = questions[-1]
        log(f'Discussion question: {question[:80]}...')
        result = subprocess.run(
            [sys.executable, str(BSA_CHAT), '--mode', 'discuss', question],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            log('BSA discuss completed successfully')
            if result.stdout:
                log(f'BSA discuss output: {result.stdout.strip()[-200:]}')
        else:
            log(f'BSA discuss failed (exit={result.returncode}): {result.stderr[:300]}')
            return

    write_hash(current_hash)
    log(f'Hash saved: {current_hash[:12]}... -- will skip until inbox.md changes again')

if __name__ == '__main__':
    main()

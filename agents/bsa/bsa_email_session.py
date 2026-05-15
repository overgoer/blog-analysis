#!/usr/bin/env python3
"""
BSA Email Session — persistent email-based chat with BSA.
Ищет письма с темой "bizzy <тема>", прогоняет через DeepSeek, отвечает.

Usage:
  python3 bsa_email_session.py                # check once (cron)
  python3 bsa_email_session.py --loop 300      # check every 5 min
  python3 bsa_email_session.py --now "текст"   # send a message now (for testing)
"""

import email as eml_lib, hashlib, imaplib, json, os, re, subprocess, sys, tempfile, time, select
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path

BASE = Path(__file__).resolve().parent
ORCH_DIR = BASE.parent / "orchestrator"
AGENTS_DIR = BASE.parent
VAULT = Path("/root/obsidian-vault/eddytester")
OBSIDIAN_STRAT = VAULT / "Стратегия"
CONTENT_MAP = Path("/root/blog-analysis/data/content_map_index.json")
PROMPT_FILE = BASE / "bsa_prompt.txt"
MAILCFG = AGENTS_DIR / ".mailcfg"
LOG_FILE = Path("/root/blog-analysis/logs/bsa_email.log")
SESSION_FILE = BASE / "bsa_email_thread.json"
PROCESSED_FILE = BASE / "bsa_email_processed.txt"
LOCK_FILE = BASE / "bsa_email.lock"


def acquire_lock():
    """Try to acquire process lock via fcntl flock. Auto-released on crash."""
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
SESSION_TIMEOUT_H = 3
ALLOWED_READ_DIRS = [str(VAULT), str(OBSIDIAN_STRAT),
                     str(Path("/root/blog-analysis/data")),
                     str(Path("/root/blog-analysis/agents/orchestrator")),
                     str(Path("/root/blog-analysis/agents/researcher")),
                     str(Path("/root/blog-analysis/agents/bsa"))]
ALLOWED_WRITE_DIRS = [str(OBSIDIAN_STRAT)]
ALLOWED_AGENTS = {"bsa": str(AGENTS_DIR / "bsa/bsa_agent.py"),
                  "pm": str(AGENTS_DIR / "orchestrator/pm_agent.py")}
os.makedirs(LOG_FILE.parent, exist_ok=True)

def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")

def load_key():
    try:
        sys.path.insert(0, str(ORCH_DIR))
        from bw_helper import BWVault
        key = BWVault().get_password("DeepSeek API Key")
        if key: return key
    except: pass
    return os.environ.get("DEEPSEEK_API_KEY") or ""

# ── DeepSeek ──────────────────────────────────────────────────────────────

def call_deepseek(messages, tools=None):
    key = load_key()
    if not key: return None, "No API key"
    payload = {"model": "deepseek-v4-flash", "messages": messages,
               "temperature": 0.5, "max_tokens": 4096}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(json.dumps(payload))
        tmp.close()
        r = subprocess.run(
            ["curl", "-s", "https://api.deepseek.com/chat/completions",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-d", f"@{tmp.name}"],
            capture_output=True, text=True, timeout=120)
        os.unlink(tmp.name)
        resp = json.loads(r.stdout)
        choice = resp["choices"][0]
        msg = choice["message"]
        if msg.get("tool_calls"): return msg, None
        return msg, msg["content"]
    except Exception as e:
        log(f"API error: {e}")
        return None, f"Error: {e}"

def build_prompt():
    p = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.exists() else "You are BSA."
    extra = []
    if CONTENT_MAP.exists():
        try:
            posts = json.loads(CONTENT_MAP.read_text())
            for post in posts[-5:]:
                extra.append(f"- {post.get('title','?')} ({post.get('date','?')})")
            if extra: extra.insert(0, "\n\nRecent posts:")
        except: pass
    files = list(OBSIDIAN_STRAT.glob("*.md")) if OBSIDIAN_STRAT.exists() else []
    if files:
        extra.append(f"\nStrategy files: {', '.join(f.name for f in files)}")
    p += "\n".join(extra)
    # Add email session instructions
    p += "\n\n## EMAIL SESSION\nТы общаешься с Эдди по email. Он пишет тебе письма с темой 'bizzy <тема>'."
    p += "\nОтвечай письмом. Используй инструменты когда нужно. В конце каждого ответа добавь короткий CTA."
    p += "\nЕсли Эдди не отвечает больше 3 часов — сессия архивируется в Obsidian."
    return p

# ── Tools ─────────────────────────────────────────────────────────────────

def _is_allowed(path, allowed):
    real = os.path.realpath(str(path))
    return any(real.startswith(os.path.realpath(d)) for d in allowed)

def tool_read_file(**kw):
    fp = kw.get("filepath") or kw.get("path") or kw.get("file", "")
    if not _is_allowed(fp, ALLOWED_READ_DIRS): return "Error: access denied"
    try:
        p = Path(fp)
        if not p.exists(): return "File not found"
        if p.stat().st_size > 100_000:
            return p.read_text(encoding="utf-8", errors="replace")[:50000] + "\n[...truncated]"
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception as e: return f"Error: {e}"

def tool_write_file(**kw):
    fp = kw.get('filepath') or kw.get('path') or kw.get('file', '')
    ct = kw.get('content') or kw.get('text') or kw.get('body', '')
    if not _is_allowed(fp, ALLOWED_WRITE_DIRS): return "Error: can only write to Стратегия/"
    try:
        p = Path(fp); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ct, encoding="utf-8"); return f"Saved ({len(ct)} bytes)"
    except Exception as e: return f"Error: {e}"

def tool_list_dir(**kw):
    dp = kw.get("dirpath") or kw.get("path") or kw.get("dir", "")
    if not _is_allowed(dp, ALLOWED_READ_DIRS): return "Error: access denied"
    try:
        p = Path(dp)
        return "\n".join(f.name + ("/" if f.is_dir() else f"  ({f.stat().st_size}b)") for f in p.iterdir())
    except Exception as e: return f"Error: {e}"

def tool_run_researcher(topic):
    if len(topic) > 500: return "Error: topic too long"
    try:
        r = subprocess.run(
            [str(AGENTS_DIR / ".venv/bin/python3"),
             str(AGENTS_DIR / "researcher/researcher.py"), topic],
            capture_output=True, text=True, timeout=300,
            cwd=str(AGENTS_DIR / "researcher"))
        return (r.stdout[-5000:] + ("\nSTDERR:\n" + r.stderr[-1000:]) if r.stderr.strip() else r.stdout[-5000:])
    except subprocess.TimeoutExpired: return "Error: timed out"
    except Exception as e: return f"Error: {e}"

TOOLS = [{"type": "function", "function": {
    "name": "read_file",
    "description": "Read file from Obsidian vault, data, or agents config",
    "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}}, "required": ["filepath"]}
}}, {"type": "function", "function": {
    "name": "write_file",
    "description": "Write file to Obsidian Стратегия/",
    "parameters": {"type": "object", "properties": {"filepath": {"type": "string"}, "content": {"type": "string"}}, "required": ["filepath", "content"]}
}}, {"type": "function", "function": {
    "name": "list_dir",
    "description": "List directory contents",
    "parameters": {"type": "object", "properties": {"dirpath": {"type": "string"}}, "required": ["dirpath"]}
}}, {"type": "function", "function": {
    "name": "run_researcher",
    "description": "Run researcher on a topic",
    "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}
}}]

TOOL_MAP = {"read_file": tool_read_file, "write_file": tool_write_file,
            "list_dir": tool_list_dir, "run_researcher": tool_run_researcher}

# ── IMAP ──────────────────────────────────────────────────────────────────

def decode_header_str(val):
    if not val: return ""
    parts = decode_header(val)
    res = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try: res.append(part.decode(charset or "utf-8", errors="replace"))
            except: res.append(part.decode("utf-8", errors="replace"))
        else: res.append(str(part))
    return "".join(res)

def get_text_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                try: return part.get_payload(decode=True).decode("utf-8", errors="replace")
                except: pass
            elif ct == "text/html":
                try:
                    text = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                    text = re.sub(r"<[^>]+>", " ", text)
                    return re.sub(r"\s+", " ", text).strip()
                except: pass
    else:
        try: return msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except: pass
    return ""

def strip_quote(body):
    """Remove quoted original from reply."""
    lines = body.splitlines()
    clean = []
    for line in lines:
        if line.strip().startswith(">") or line.strip().startswith("|"): break
        if "On " in line and " wrote:" in line: break
        if "написал(" in line: break
        if "---Оригинал" in line: break
        if "Отправлено" in line.strip(): break
        clean.append(line)
    return "\n".join(clean).strip()

def load_processed():
    if not PROCESSED_FILE.exists(): return set()
    return set(line.strip() for line in PROCESSED_FILE.read_text().splitlines() if line.strip())

def save_processed(ids):
    PROCESSED_FILE.write_text("\n".join(sorted(ids)) + "\n")

def check_imap():
    """Check INBOX for emails from eddy with 'bizzy' subject or replies to bizzy threads."""
    if not MAILCFG.exists():
        log("No .mailcfg")
        return []
    cfg = json.loads(MAILCFG.read_text())
    password = cfg.get("password", "")
    if not password:
        log("No IMAP password")
        return []
    processed = load_processed()
    results = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
        mail.login(cfg.get("username", "eddy.super1@gmail.com"), password)
        # Load active session to check for reply threading
        session = load_session()
        session_subject = session.get("subject", "").lower() if session else ""
        session_msg_id = session.get("last_message_id", "") if session else ""

        for folder in ["INBOX"]:
            status, _ = mail.select(folder)
            if status != "OK": continue
            status, msgs = mail.search(None, '(FROM "eddy.super1")')
            if status != "OK" or not msgs[0]: continue
            for mid in msgs[0].split():
                mid_s = mid.decode()
                if mid_s in processed: continue
                status, data = mail.fetch(mid, "(RFC822)")
                if status != "OK": continue
                msg = eml_lib.message_from_bytes(data[0][1])
                subject = decode_header_str(msg.get("Subject", "")).strip()
                body = strip_quote(get_text_body(msg))
                in_reply_to = msg.get("In-Reply-To", "") or ""
                references = msg.get("References", "") or ""
                msg_id_hdr = msg.get("Message-ID", "") or ""

                if not subject and not body: continue

                # Keep track of all subjects from eddy for context
                subj_lower = subject.lower()

                # Match: new session "bizzy <topic>"
                is_new = subj_lower.startswith("bizzy")
                # Match: reply to active session
                is_reply = session and (
                    session_msg_id in references or session_msg_id in in_reply_to or
                    subj_lower.startswith("re:") and session_subject and
                    (session_subject in subj_lower or subj_lower in session_subject)
                )

                if not is_new and not is_reply:
                    # Store for context but don't process
                    processed.add(mid_s)
                    save_processed(processed)
                    continue

                results.append({
                    "id": mid_s,
                    "subject": subject,
                    "body": body,
                    "msg_id": msg_id_hdr,
                    "in_reply_to": in_reply_to,
                    "references": references,
                })
                processed.add(mid_s)

        save_processed(processed)
        mail.logout()
    except Exception as e:
        log(f"IMAP error: {e}")
    return results

# ── Send Email via Resend ────────────────────────────────────────────────

def send_resend(subject, body, cfg, in_reply_to=None, references=None):
    """Send email via Resend API. Supports threading headers for replies."""
    from_addr = cfg.get("from_addr", "onboarding@resend.dev")
    to_addr = cfg.get("to_addr", "eddy.super1@gmail.com")
    api_key = cfg.get("resend_api_key", "")
    if not api_key:
        log("No resend_api_key")
        return False
    
    # Build JSON payload for Resend
    payload = {
        "from": from_addr,
        "to": [to_addr],
        "subject": subject,
        "text": body,
    }
    headers = {}
    if in_reply_to:
        headers["In-Reply-To"] = in_reply_to
    if references:
        headers["References"] = references
    if headers:
        payload["headers"] = headers

    try:
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(json.dumps(payload))
        tmp.close()
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", "https://api.resend.com/emails",
             "-H", f"Authorization: Bearer {api_key}",
             "-H", "Content-Type: application/json",
             "-d", f"@{tmp.name}"],
            capture_output=True, text=True, timeout=30)
        os.unlink(tmp.name)
        result = json.loads(r.stdout)
        if "id" in result:
            log(f"Email sent: {subject} (id={result['id']})")
            # Archive
            archive_dir = Path(AGENTS_DIR / "email_archive")
            archive_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            (archive_dir / f"mail_{ts}.txt").write_text(f"Subject: {subject}\n\n{body}")
            return result.get("id", "")
        else:
            log(f"Resend error: {r.stdout[:200]}")
            return False
    except Exception as e:
        log(f"Send error: {e}")
        return False

# ── Session Management ────────────────────────────────────────────────────

def load_session():
    if not SESSION_FILE.exists():
        return {"status": "idle", "subject": "", "messages": [],
                "last_activity": "", "last_message_id": "", "topic": ""}
    try:
        return json.loads(SESSION_FILE.read_text())
    except:
        return {"status": "idle", "subject": "", "messages": [],
                "last_activity": "", "last_message_id": "", "topic": ""}

def save_session(s):
    SESSION_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))

def archive_session(session):
    """Save session summary to Obsidian and reset."""
    if session.get("status") != "active": return
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    topic = session.get("topic", "unknown")
    filename = f"BSA_EMAIL_SESSION_{topic}_{ts}.md"
    content = f"""---
created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
type: email_session
status: archived
topic: {topic}
---

# Email Session: {topic}

**Archived after inactivity.**

## Summary
Session topic: {topic}
Duration: {session.get('duration', 'unknown')}
Messages: {len([m for m in session.get('messages', []) if m['role'] == 'user'])} exchanges

## Key decisions/outcomes

*Auto-archived after {SESSION_TIMEOUT_H}h of inactivity.*
"""
    obsidian_path = OBSIDIAN_STRAT / filename
    obsidian_path.write_text(content, encoding="utf-8")
    log(f"Session archived: {filename}")
    # Reset session
    save_session({"status": "idle", "subject": "", "messages": [],
                  "last_activity": "", "last_message_id": "", "topic": ""})

# ── Main Processing ───────────────────────────────────────────────────────

def run_conversation(messages):
    """Loop DeepSeek calls with tool execution, up to 8 rounds."""
    for _ in range(8):
        msg, text = call_deepseek(messages, tools=TOOLS)
        if msg is None:
            return f"Error: {text}", messages
        if msg.get("tool_calls"):
            messages.append(msg)
            for tc in msg["tool_calls"]:
                fn = tc["function"]
                try: args = json.loads(fn["arguments"])
                except: args = {}
                log(f"Tool: {fn['name']}")
                result = TOOL_MAP.get(fn["name"], lambda **_: f"Unknown tool: {fn['name']}")(**args)
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": str(result)[:10000]})
            continue
        return text, messages
    return "Iteration limit reached.", messages

def process_session():
    """Main logic: check timeout, check IMAP, process new messages."""
    if not acquire_lock():
        log("Another instance is running, skipping")
        return
    session = load_session()
    now = datetime.now()

    # Check timeout for active session
    if session.get("status") == "active" and session.get("last_activity"):
        last = datetime.fromisoformat(session["last_activity"])
        elapsed_h = (now - last).total_seconds() / 3600
        if elapsed_h >= SESSION_TIMEOUT_H:
            log(f"Session timeout ({elapsed_h:.0f}h): archiving")
            archive_session(session)
            session = load_session()  # reload after reset

    # Check IMAP
    emails = check_imap()
    if not emails:
        return

    for em in emails:
        subject = em["subject"]
        body = em["body"]
        msg_id = em["msg_id"]
        in_reply_to = em["in_reply_to"]

        if not body:
            log(f"Empty body from: {subject}")
            continue

        subj_lower = subject.lower()

        # New session
        if subj_lower.startswith("bizzy"):
            topic = subject[5:].strip() or "general"
            log(f"New session: {topic}")
            session = {
                "status": "active",
                "subject": subject,
                "topic": topic,
                "messages": [],
                "last_activity": now.isoformat(),
                "last_message_id": msg_id,
                "created": now.isoformat(),
            }
            # Add system prompt
            session["messages"].append({"role": "system", "content": build_prompt()})
            # Add user message
            session["messages"].append({"role": "user", "content": body})
            response, session["messages"] = run_conversation(session["messages"])

            if response:
                reply_subj = f"Re: {subject}"
                # Save last message ID for threading
                log(f"Response: {response[:100]}...")
                sent_id = send_resend(reply_subj, response,
                                       json.loads(MAILCFG.read_text()),
                                       in_reply_to=msg_id, references=msg_id)
                if sent_id:
                    session["last_message_id"] = msg_id
                    session["last_activity"] = datetime.now().isoformat()
                    session["messages"].append({"role": "assistant", "content": response})
            save_session(session)
            continue

        # Reply to active session
        if session.get("status") == "active":
            log(f"Reply to session: {subject}")
            session["last_activity"] = now.isoformat()
            session["last_message_id"] = msg_id
            session["messages"].append({"role": "user", "content": body})

            # Trim context if too long (rough: 50k chars for messages)
            total = sum(len(m.get("content", "")) for m in session["messages"])
            if total > 50000:
                # Keep system + last 5 exchanges
                sys_msg = session["messages"][0] if session["messages"][0]["role"] == "system" else None
                recent = [m for m in session["messages"] if m.get("role") != "system"][-20:]
                session["messages"] = ([sys_msg] if sys_msg else []) + recent
                session["messages"].insert(0 if sys_msg else 0,
                    {"role": "system", "content": "Previous context trimmed. Continue the conversation."})

            response, session["messages"] = run_conversation(session["messages"])
            if response:
                reply_subj = f"Re: {subject}" if not subject.lower().startswith("re:") else subject
                sent_id = send_resend(reply_subj, response,
                                       json.loads(MAILCFG.read_text()),
                                       in_reply_to=msg_id, references=msg_id)
                if sent_id:
                    session["last_message_id"] = msg_id
                    session["last_activity"] = datetime.now().isoformat()
                    session["messages"].append({"role": "assistant", "content": response})
            save_session(session)

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--now":
        # Send a one-shot message (for testing)
        msg = sys.argv[2] if len(sys.argv) > 2 else "test"
        session = load_session()
        if session.get("status") != "active":
            session = {"status": "active", "subject": "bizzy test",
                       "topic": "test", "messages": [],
                       "last_activity": datetime.now().isoformat(),
                       "last_message_id": "", "created": datetime.now().isoformat()}
            session["messages"].append({"role": "system", "content": build_prompt()})
        session["messages"].append({"role": "user", "content": msg})
        resp, session["messages"] = run_conversation(session["messages"])
        if resp:
            print(resp)
            session["messages"].append({"role": "assistant", "content": resp})
            session["last_activity"] = datetime.now().isoformat()
        save_session(session)
        return

    loop_sec = None
    if len(sys.argv) > 2 and sys.argv[1] == "--loop":
        loop_sec = int(sys.argv[2])

    log("BSA Email Session started")
    process_session()

    if loop_sec:
        try:
            while True:
                time.sleep(loop_sec)
                log(f"Checking ({loop_sec}s loop)...")
                process_session()
        except KeyboardInterrupt:
            log("Loop stopped")

if __name__ == "__main__":
    main()

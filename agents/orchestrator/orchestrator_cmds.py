#!/usr/bin/env python3
"""
Orchestrator Commands — IMAP email reader for @eddytester approvals.

Connects to Gmail IMAP, finds replies to digest emails from Eddy,
parses commands and executes them.

Commands:
  "тг 1"      — approve post (placeholder for now, logs to command log)
  "зашквар: X" — block topic X (adds to blacklist in topics.json)
  "в пул: X"   — add topic X to pool (appends to topics.json)

Usage:
  python3 orchestrator_cmds.py                    # check once and exit
  python3 orchestrator_cmds.py --loop 60           # check every 60 seconds
"""

import email
import imaplib
import json
import os
import re
import sys
import time
from datetime import datetime
from email.header import decode_header
from pathlib import Path

BASE = Path("/root/blog-analysis/agents")
TOPICS_FILE = BASE / "researcher" / "topics.json"
MAILCFG = BASE / ".mailcfg"
LOG_FILE = Path("/root/blog-analysis/logs/cmd_processor.log")
PROCESSED_DIR = BASE / "orchestrator" / "processed_cmds"

os.makedirs(PROCESSED_DIR, exist_ok=True)
os.makedirs(LOG_FILE.parent, exist_ok=True)


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_mailcfg():
    with open(MAILCFG) as f:
        return json.load(f)


def load_topics():
    with open(TOPICS_FILE) as f:
        return json.load(f)


def save_topics(data):
    with open(TOPICS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def decode_mime_header(header_value):
    """Decode a MIME encoded header value."""
    if not header_value:
        return ""
    decoded_parts = decode_header(header_value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                result.append(part.decode("utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)


def get_email_body(msg):
    """Extract plain text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode("utf-8", errors="replace")
                except:
                    pass
            elif part.get_content_type() == "text/html":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        # Strip HTML tags for plain text extraction
                        text = payload.decode("utf-8", errors="replace")
                        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                        text = re.sub(r"<[^>]+>", " ", text)
                        text = re.sub(r"\s+", " ", text).strip()
                        return text
                except:
                    pass
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="replace")
        except:
            pass
    return ""


def strip_reply_quote(body):
    """Strip quoted original message from a reply."""
    # Common reply markers
    lines = body.splitlines()
    clean = []
    for line in lines:
        # Stop at common quote markers
        if line.strip().startswith(">") or line.strip().startswith("|"):
            break
        if "On " in line and " wrote:" in line:
            break
        if line.strip() == "---" or line.strip() == "___":
            break
        if "\u043d\u0430\u043f\u0438\u0441\u0430\u043b(" in line:  # "написал("
            break
        if "---\u041e\u0440\u0438\u0433\u0438\u043d\u0430\u043b" in line:  # "---Оригинал"
            break
        if line.strip().startswith("\u041e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u043e"):  # "Отправлено"
            break
        clean.append(line)
    return "\n".join(clean).strip()


def parse_command(body):
    """Parse a single email body for orchestrator commands."""
    body_lower = body.lower().strip()
    result = {"cmd": None, "args": None, "raw": body[:200]}

    # "тг 1" — approve post (IMAP processing)
    m = re.search(r"\u0442\u0433\s*1", body_lower)  # "тг 1"
    if m:
        result["cmd"] = "\u0442\u0433 1"
        return result

    # "зашквар: X" — block topic
    m = re.search(r"\u0437\u0430\u0448\u043a\u0432\u0430\u0440\s*[:]\s*(.+)", body_lower)  # "зашквар:"
    if m:
        result["cmd"] = "\u0437\u0430\u0448\u043a\u0432\u0430\u0440"
        result["args"] = m.group(1).strip().strip('"').strip("'")
        return result

    # "в пул: X" — add topic to pool
    m = re.search(r"\u0432\s+\u043f\u0443\u043b\s*[:]\s*(.+)", body_lower)  # "в пул:"
    if m:
        result["cmd"] = "\u0432 \u043f\u0443\u043b"
        result["args"] = m.group(1).strip().strip('"').strip("'")
        return result

    return result


def execute_command(result, subject):
    """Execute a parsed command."""
    cmd = result["cmd"]
    if not cmd:
        return None

    data = load_topics()

    if cmd == "\u0442\u0433 1":
        log(f"CMD: \u043f\u043e\u0441\u0442 \u043e\u0434\u043e\u0431\u0440\u0435\u043d (\"\u0442\u0433 1\") — \u0437\u0430\u043b\u043e\u0433\u0438\u0440\u043e\u0432\u0430\u043d\u043e")
        return {"action": "approved", "detail": "Post approved (тг 1)"}

    elif cmd == "\u0437\u0430\u0448\u043a\u0432\u0430\u0440":
        topic = result["args"]
        if topic and len(topic) > 5:
            # Add to blacklist
            if "blacklist" not in data:
                data["blacklist"] = []
            if topic not in data["blacklist"]:
                data["blacklist"].append(topic)
                # Remove from pool if present
                if topic in data["pool"]:
                    data["pool"].remove(topic)
                save_topics(data)
                log(f"CMD: \u0437\u0430\u0448\u043a\u0432\u0430\u0440 \u2014 \"{topic[:60]}\" \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0430 \u0432 \u0447\u0435\u0440\u043d\u044b\u0439 \u0441\u043f\u0438\u0441\u043e\u043a")
                return {"action": "blocked", "detail": topic}
            else:
                log(f"CMD: \u0437\u0430\u0448\u043a\u0432\u0430\u0440 \u2014 \"{topic[:60]}\" \u0443\u0436\u0435 \u0432 \u0447\u0451\u0440\u043d\u043e\u043c \u0441\u043f\u0438\u0441\u043a\u0435")
                return {"action": "blocked_duplicate", "detail": topic}

    elif cmd == "\u0432 \u043f\u0443\u043b":
        topic = result["args"]
        if topic and len(topic) > 10:
            if topic not in data["pool"]:
                data["pool"].append(topic)
                save_topics(data)
                log(f"CMD: \u0432 \u043f\u0443\u043b \u2014 \"{topic[:60]}\" \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0430")
                return {"action": "added", "detail": topic}
            else:
                log(f"CMD: \u0432 \u043f\u0443\u043b \u2014 \"{topic[:60]}\" \u0443\u0436\u0435 \u0432 \u043f\u0443\u043b\u0435")
                return {"action": "added_duplicate", "detail": topic}

    return None


def process_email(msg, msg_id):
    """Process a single email message for commands."""
    subject = decode_mime_header(msg.get("Subject", ""))
    from_addr = decode_mime_header(msg.get("From", ""))
    date = msg.get("Date", "")

    log(f"  From: {from_addr} | Subject: {subject[:60]}")

    # Only process from eddy's address — then try to parse commands from any email
    if "eddy.super1" not in from_addr and "overgoer" not in from_addr:
        log("  SKIP: not from Eddy")
        return False

    body = get_email_body(msg)
    clean_body = strip_reply_quote(body)

    if not clean_body:
        log("  SKIP: no text body found")
        return False

    result = parse_command(clean_body)
    if not result["cmd"]:
        log(f"  SKIP: no command found in: {result['raw'][:80]}")
        return False

    status = execute_command(result, subject)

    # Save processed command
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    record = {
        "timestamp": ts,
        "subject": subject,
        "from": from_addr,
        "command": result["cmd"],
        "args": result["args"],
        "status": status,
    }
    with open(PROCESSED_DIR / f"cmd_{ts}.json", "w") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)

    return True


def check_mail():
    """Connect to IMAP, find unread digest replies, process commands."""
    cfg = load_mailcfg()
    username = cfg.get("username", "eddy.super1@gmail.com")
    password = cfg.get("password", "")

    if not password:
        log("ERROR: no SMTP password in .mailcfg")
        return []

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
        mail.login(username, password)
        # Enable UTF-8 for Cyrillic support
        try:
            mail._simple_command("ENABLE", "UTF8")
        except:
            pass
        mail.select("INBOX")

        # Search for unread messages from Eddy
        status, messages = mail.search(None, '(FROM "eddy.super1")')

        processed = []
        if status == "OK" and messages[0]:
            msg_ids = messages[0].split()
            log(f"Found {len(msg_ids)} digest replies from Eddy")

            for mid in msg_ids:
                status, data = mail.fetch(mid, "(RFC822)")
                if status != "OK":
                    continue

                msg = email.message_from_bytes(data[0][1])
                if process_email(msg, mid):
                    processed.append(mid)

                # Mark as read
                mail.store(mid, "+FLAGS", "\\Seen")

        mail.logout()
        return processed

    except Exception as e:
        log(f"IMAP ERROR: {e}")
        return []


def main():
    loop_interval = None

    if "--loop" in sys.argv:
        idx = sys.argv.index("--loop")
        if idx + 1 < len(sys.argv):
            try:
                loop_interval = int(sys.argv[idx + 1])
            except ValueError:
                pass

    if loop_interval:
        log(f"Starting IMAP listener (every {loop_interval}s)...")
        while True:
            processed = check_mail()
            if processed:
                log(f"Processed {len(processed)} commands")
            time.sleep(loop_interval)
    else:
        processed = check_mail()
        if processed:
            log(f"Processed {len(processed)} commands")
        else:
            log("No commands found")


if __name__ == "__main__":
    main()

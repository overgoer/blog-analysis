"""
Gateway — IMAP email processor, routes commands to Content Manager, PM Agent, etc.

Connects to Gmail IMAP, finds replies to digest emails from Eddy,
parses commands and executes them.

Commands:
  "тг 1"      — approve post (placeholder for now, logs to command log)
  "зашквар: X" — block topic X (adds to blacklist in topics.json)
  "в пул: X"   — add topic X to pool (appends to topics.json)
  "бэклог X"   — add idea to wishlist (wishlist.json)
  "dev: X"     — dev/research task → PM Agent (classify + assess)
  "[BSA]"     — strategy feedback → BSA Agent (dialogue round)

Usage:
  python3 gateway.py                    # check once and exit
  python3 gateway.py --loop 60           # check every 60 seconds
"""

import email
import imaplib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from email.header import decode_header
from pathlib import Path

BASE = Path("/root/blog-analysis/agents")
TOPICS_FILE = BASE / "researcher" / "topics.json"
MAILCFG = BASE / ".mailcfg"
LOG_FILE = Path("/root/blog-analysis/logs/cmd_processor.log")
PROCESSED_DIR = BASE / "orchestrator" / "processed_cmds"
SENT_FOLDER = "[Gmail]/&BB4EQgQ,BEAEMAQyBDsENQQ9BD0ESwQ1-"
PROCESSED_IDS_FILE = BASE / "orchestrator" / "processed_ids.txt"
WISHLIST_FILE = BASE / "orchestrator" / "wishlist.json"

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

def load_wishlist():
    if not WISHLIST_FILE.exists():
        return []
    with open(WISHLIST_FILE) as f:
        return json.load(f)

def save_wishlist(items):
    with open(WISHLIST_FILE, "w") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

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

def parse_commands(body):
    """Parse an email body for gateway commands. Returns a list of command dicts."""
    body_lower = body.lower().strip()
    results = []

    if re.search(r"\u0442\u0433\s*1", body_lower):
        results.append({"cmd": "\u0442\u0433 1", "args": None})

    for m in re.finditer(r"\u0437\u0430\u0448\u043a\u0432\u0430\u0440\s*[:]\s*(.+)", body_lower):
        topic = m.group(1).strip().strip('"').strip("'")
        if len(topic) > 5:
            results.append({"cmd": "\u0437\u0430\u0448\u043a\u0432\u0430\u0440", "args": topic})

    for m in re.finditer(r"\u0432\s+\u043f\u0443\u043b\s*[:]\s*(.+)", body_lower):
        topic = m.group(1).strip().strip('"').strip("'")
        if len(topic) > 10:
            results.append({"cmd": "\u0432 \u043f\u0443\u043b", "args": topic})

    for m in re.finditer(r"\u0431\u044d\u043a\u043b\u043e\u0433\s+(.+)", body_lower):
        idea = m.group(1).strip().strip('"').strip("'")
        if len(idea) > 5:
            results.append({"cmd": "\u0431\u044d\u043a\u043b\u043e\u0433", "args": idea})

    for m in re.finditer(r"dev\s*:\s*(.+)", body_lower):
        task = m.group(1).strip().strip('"').strip("'")
        if len(task) > 5:
            results.append({"cmd": "dev", "args": task})

    return results

def parse_command(body):
    """Legacy wrapper, parses and returns first command."""
    results = parse_commands(body)
    return results[0] if results else {"cmd": None, "args": None}
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
            if "blacklist" not in data:
                data["blacklist"] = []
            if topic not in data["blacklist"]:
                data["blacklist"].append(topic)
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

    elif cmd == "\u0431\u044d\u043a\u043b\u043e\u0433":
        idea = result["args"]
        if idea and len(idea) > 5:
            wishlist = load_wishlist()
            existing = [x for x in wishlist if x["idea"] == idea]
            if not existing:
                entry = {
                    "idea": idea,
                    "source": "email",
                    "status": "new",
                    "verdict": None,
                    "added": datetime.now().isoformat()
                }
                wishlist.append(entry)
                save_wishlist(wishlist)
                log(f"CMD: \u0431\u044d\u043a\u043b\u043e\u0433 \u2014 \"{idea[:60]}\" \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0430 \u0432 wishlist")
                return {"action": "wishlisted", "detail": idea}
            else:
                log(f"CMD: \u0431\u044d\u043a\u043b\u043e\u0433 \u2014 \"{idea[:60]}\" \u0443\u0436\u0435 \u0432 wishlist")
                return {"action": "wishlisted_duplicate", "detail": idea}

    elif cmd == "dev":
        task_text = result["args"]
        if task_text and len(task_text) > 5:
            from pm_agent import classify_task, assess_task
            classification = classify_task(task_text)
            log(f"DEV: \"{task_text[:80]}\" classified as {classification}")

            if classification == "RESEARCH":
                log(f"DEV: RESEARCH — logged for next researcher cycle")
                return {"action": "dev_research", "detail": task_text}
            else:
                log(f"DEV: CODE — running PM Agent assessment...")
                assessment = assess_task(task_text)
                log(f"DEV: assessment saved (verdict={assessment.get('verdict','?')})")
                if assessment.get("verdict") == "GO":
                    log(f"DEV: GO verdict — auto-run triggered via pm_agent")
                    return {"action": "dev_executed", "detail": task_text}
                return {"action": "dev_assessed", "detail": task_text, "verdict": assessment.get("verdict")}

    return None


BSA_AGENT = BASE / "bsa" / "bsa_agent.py"


def route_bsa_email(subject, body, message_id, in_reply_to=""):
    """Route a BSA email reply to BSA Agent for feedback processing."""
    if "bsa" not in subject.lower():
        return False

    log(f"BSA: routing feedback (msg_id={message_id[:30]})")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(body)
        body_file = f.name

    try:
        subprocess.run(
            [sys.executable or "python3", str(BSA_AGENT),
             "--feedback", message_id,
             "--body-file", body_file,
             "--in-reply-to", in_reply_to],
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        log("BSA: feedback processing timed out")
    finally:
        os.unlink(body_file)

    return True


# ── IMAP Processing (restored from original orchestrator_cmds.py) ────────


def process_email(msg, msg_id):
    """Process a single email message for commands and BSA feedback."""
    subject = decode_mime_header(msg.get("Subject", ""))
    from_addr = decode_mime_header(msg.get("From", ""))
    date = msg.get("Date", "")

    log(f"  From: {from_addr} | Subject: {subject[:60]}")

    # Only process from eddy's address
    if "eddy.super1" not in from_addr and "overgoer" not in from_addr:
        log("  SKIP: not from Eddy")
        return False

    body = get_email_body(msg)
    clean_body = strip_reply_quote(body)

    if not clean_body:
        log("  SKIP: no text body found")
        return False

    # Check for BSA feedback first (based on subject)
    in_reply_to = msg.get("In-Reply-To", "") or msg.get("Message-ID", "")
    if route_bsa_email(subject, clean_body, msg_id, in_reply_to):
        return True

    # Check for regular commands
    cmd_results = parse_commands(clean_body)
    if not cmd_results:
        log("  SKIP: no command found")
        return False

    any_executed = False
    for cmd_result in cmd_results:
        status = execute_command(cmd_result, subject)

        # Save each processed command
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        record = {
            "timestamp": ts,
            "subject": subject,
            "from": from_addr,
            "command": cmd_result["cmd"],
            "args": cmd_result["args"],
            "status": status,
        }
        with open(PROCESSED_DIR / f"cmd_{ts}.json", "w") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        any_executed = True

    return any_executed


def load_processed_ids():
    """Load set of already-processed message UIDs."""
    if not PROCESSED_IDS_FILE.exists():
        return set()
    with open(PROCESSED_IDS_FILE) as f:
        return set(line.strip() for line in f if line.strip())


def save_processed_ids(ids):
    """Save processed message UIDs."""
    with open(PROCESSED_IDS_FILE, "w") as f:
        for mid in sorted(ids):
            f.write(mid + "\n")


def check_folder(mail, folder_name, processed_ids, since_date=None):
    """Check a single IMAP folder for commands from Eddy."""
    results = []
    try:
        status, _ = mail.select(folder_name)
        if status != "OK":
            log(f"  Cannot select folder: {folder_name}")
            return results
        search_cmd = '(FROM "eddy.super1")'
        if since_date:
            search_cmd = f'(SINCE "{since_date}" FROM "eddy.super1")'
        status, messages = mail.search(None, search_cmd)
        if status != "OK" or not messages[0]:
            return results
        msg_ids = messages[0].split()
        new_ids = [m for m in msg_ids if m.decode() not in processed_ids]
        if not new_ids:
            return results
        for mid in new_ids:
            mid_str = mid.decode()
            status, data = mail.fetch(mid, "(RFC822)")
            if status != "OK":
                continue
            msg = email.message_from_bytes(data[0][1])
            if process_email(msg, mid_str):
                results.append(mid_str)
        return results
    except Exception as e:
        log(f"  Folder error ({folder_name}): {e}")
        return results


def check_mail():
    """Connect to IMAP, check INBOX + Sent Mail for commands from Eddy."""
    cfg = load_mailcfg()
    username = cfg.get("username", "eddy.super1@gmail.com")
    password = cfg.get("password", "")

    if not password:
        log("ERROR: no SMTP password in .mailcfg")
        return []

    processed_ids = load_processed_ids()
    all_processed = []

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
        mail.login(username, password)
        try:
            mail._simple_command("ENABLE", "UTF8")
        except:
            pass

        # Check INBOX
        log("Checking INBOX...")
        inbox_results = check_folder(mail, "INBOX", processed_ids)
        all_processed.extend(inbox_results)
        if inbox_results:
            log(f"  Found {len(inbox_results)} commands in INBOX")

        # Check Sent Mail — only last 7 days
        log("Checking Sent Mail (last 7 days)...")
        from datetime import datetime, timedelta
        since_date = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
        sent_results = check_folder(mail, SENT_FOLDER, processed_ids, since_date)
        all_processed.extend(sent_results)
        if sent_results:
            log(f"  Found {len(sent_results)} commands in Sent Mail")

        # Save processed IDs
        all_ids = processed_ids | set(all_processed)
        for mid in all_processed:
            mail.store(mid, "+FLAGS", "\\Seen")
        save_processed_ids(all_ids)

        mail.logout()
        return all_processed

    except Exception as e:
        log(f"IMAP ERROR: {e}")
        return []


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Gateway — IMAP command processor")
    parser.add_argument("--loop", type=int, default=None, help="Check every N seconds")
    args = parser.parse_args()

    cmds = check_mail()
    if cmds:
        log(f"Total: {len(cmds)} commands processed")
    elif args.loop:
        log("No new commands, sleeping...")

    if args.loop:
        try:
            import time as _time
            while True:
                _time.sleep(args.loop)
                cmds = check_mail()
                if cmds:
                    log(f"Loop: {len(cmds)} commands processed")
        except KeyboardInterrupt:
            log("Gateway loop stopped")


if __name__ == "__main__":
    main()

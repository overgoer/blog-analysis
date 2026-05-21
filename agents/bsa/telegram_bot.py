#!/usr/bin/env python3
"""
Telegram Bot for Bizzy — двухсторонний канал с @eddytester.

Bizzy → Telegram: пишет JSON в outgoing/, бот отправляет.
Telegram → Bizzy: сообщение → incoming/ + Obsidian inbox.md.

Запуск: python3 telegram_bot.py            # foreground
        pm2 start telegram_bot.py --interpreter python3  # демон
"""

import json, os, subprocess, sys, time, logging, textwrap
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

BASE = Path(__file__).resolve().parent
OUTGOING = BASE / "outgoing"
INCOMING = BASE / "incoming"
TOKEN_FILE = BASE / ".tg_token"
CHAT_ID_FILE = BASE / ".tg_chat_id"
POLL_INTERVAL = 15
INBOX_FILE = Path("/root/obsidian-vault/inbox.md")
DUMP_FILE = Path("/root/blog-analysis/agents/bsa/dump.md")
IDEAS_FILE = Path("/root/obsidian-vault/eddytester/Идеи/_IDEAS.md")

os.makedirs(OUTGOING, exist_ok=True)
os.makedirs(INCOMING, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(BASE / "telegram_bot.log")],
)
log = logging.getLogger("tg_bot")


def load_token():
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    token = os.environ.get("TG_BOT_TOKEN", "")
    if token:
        TOKEN_FILE.write_text(token)
    return token


def load_chat_id():
    if CHAT_ID_FILE.exists():
        return CHAT_ID_FILE.read_text().strip()


def save_chat_id(cid):
    CHAT_ID_FILE.write_text(str(cid))
    log.info("Chat ID saved: %s", cid)


def tg_api(method, data=None):
    token = load_token()
    if not token:
        log.error("No TG_BOT_TOKEN")
        return None
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        body = json.dumps(data).encode() if data else None
        req = Request(url, data=body, headers={"Content-Type": "application/json"})
        resp = urlopen(req, timeout=15)
        return json.loads(resp.read())
    except URLError as e:
        log.warning("Telegram API error (%s): %s", method, e)
        return None
    except (json.JSONDecodeError, OSError):
        return None


TG_MAX = 4096


def _md_to_html(text: str) -> str:
    """Convert common markdown to Telegram-safe HTML. Bulletproof."""
    import re
    # Code blocks first (protect their content)
    text = re.sub(r'```(\w*)\n(.*?)```', r'<code>\2</code>', text, flags=re.DOTALL)
    # Inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # Bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    # Italic *text* or _text_ (but not inside words for _)
    text = re.sub(r'(?<!\w)_(?!_)(.+?)(?<!_)_(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!\w)\*(?!\*)(.+?)(?<!\*)\*(?!\w)', r'<i>\1</i>', text)
    # Headers ### → bold
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    # Strikethrough ~~text~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    # No bullet markers → plain dash
    text = re.sub(r'^(\s*)[•●▪]\s+', r'\1— ', text, flags=re.MULTILINE)
    # Lines starting with number., make bold
    text = re.sub(r'^(\d+)[.)]\s+(.+)$', r'<b>\1.</b> \2', text, flags=re.MULTILINE)
    # Escape remaining HTML entities to prevent breakage
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;').replace('>', '&gt;')
    # But restore our inserted tags
    text = text.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
    text = text.replace('&lt;i&gt;', '<i>').replace('&lt;/i&gt;', '</i>')
    text = text.replace('&lt;code&gt;', '<code>').replace('&lt;/code&gt;', '</code>')
    text = text.replace('&lt;s&gt;', '<s>').replace('&lt;/s&gt;', '</s>')
    return text


def send_message(text, parse_mode="HTML"):
    cid = load_chat_id()
    if not cid:
        log.warning("No chat ID configured")
        return False

    # Sanitize: convert any markdown to HTML
    safe_text = _md_to_html(text)

    # Split long messages
    if len(safe_text) > TG_MAX:
        return _send_long(cid, safe_text, parse_mode)

    payload = {"chat_id": int(cid), "text": safe_text, "disable_notification": False}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    r = tg_api("sendMessage", payload)
    if r and r.get("ok"):
        return True
    log.warning("sendMessage failed for chat %s, retrying as text", cid)
    # Retry as plain text if HTML failed
    payload.pop("parse_mode", None)
    r = tg_api("sendMessage", payload)
    return bool(r and r.get("ok"))


def send_photo(caption, photo_path):
    """Send a photo file with caption."""
    import mimetypes
    cid = load_chat_id()
    if not cid:
        log.warning("No chat ID configured")
        return False
    fpath = Path(photo_path)
    if not fpath.exists():
        log.warning("Photo not found: %s", photo_path)
        return False

    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = b""
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
    body += f"{cid}\r\n".encode()
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="photo"; filename="{fpath.name}"\r\n'.encode()
    body += b"Content-Type: image/png\r\n\r\n"
    body += fpath.read_bytes()
    body += b"\r\n"
    if caption:
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="caption"\r\n\r\n'
        body += f"{caption[:200]}\r\n".encode()
    body += f"--{boundary}--\r\n".encode()

    token = load_token()
    if not token:
        return False
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    req = Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        resp = urlopen(req, timeout=30)
        r = json.loads(resp.read())
        return r.get("ok", False)
    except Exception as e:
        log.warning("sendPhoto error: %s", e)
        return False


def _send_long(cid, text, parse_mode):
    """Split long text into chunks and send sequentially."""
    chunks = []
    for line in text.split("\n"):
        if not chunks or len(chunks[-1]) + len(line) + 1 > TG_MAX:
            chunks.append(line)
        else:
            chunks[-1] += "\n" + line

    ok = True
    for i, chunk in enumerate(chunks):
        payload = {"chat_id": int(cid), "text": chunk, "disable_notification": i > 0}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        r = tg_api("sendMessage", payload)
        if not r or not r.get("ok"):
            log.warning("sendMessage chunk %d/%d failed", i + 1, len(chunks))
            ok = False
    return ok


def process_outgoing():
    sent = 0
    for fpath in sorted(OUTGOING.glob("*.json")):
        try:
            msg = json.loads(fpath.read_text())
        except (json.JSONDecodeError, OSError):
            fpath.unlink()
            continue
        text = msg.get("text", "")
        if not text:
            fpath.unlink()
            continue

        # !backlog commands — execute and don't send to Telegram
        if text.startswith("!backlog "):
            ok = _exec_backlog_cmd(text)
            if ok:
                log.info("Backlog cmd executed: %.60s", text)
            fpath.unlink()
            sent += 1
            continue

        ok = send_message(text)
        if ok:
            log.info("Sent: %s", fpath.name)
            fpath.unlink()
            sent += 1
        else:
            msg["retries"] = msg.get("retries", 0) + 1
            if msg["retries"] >= 3:
                msg["failed"] = True
                msg["failed_at"] = datetime.now().isoformat()
                log.error("Gave up: %s", fpath.name)
            fpath.write_text(json.dumps(msg, ensure_ascii=False))
    return sent


def _exec_backlog_cmd(text):
    """Execute !backlog command from outgoing queue. Returns True on success."""
    try:
        from backlog import add_entry, mark_done, get_summary
        cmd = text[len("!backlog "):].strip()

        if cmd.startswith("add "):
            rest = cmd[4:].strip()
            priority = "P3"
            title = rest
            # Accept both [P2] Text and P2 Text formats
            if rest.startswith("[") and rest[1] in "P0123":
                priority = f"P{rest[2]}" if len(rest) > 2 and rest[2].isdigit() else "P3"
                title = rest[4:].strip() if len(rest) > 4 else rest
            elif len(rest) > 2 and rest[0:2] in ("P0", "P1", "P2", "P3") and rest[2:3] in (" ", ""):
                priority = rest[0:2]
                title = rest[3:].strip()
            entry = add_entry(title, priority=priority, source="manual", origin="backlog_cmd")
            log.info("Backlog added: %s [%s]", entry["id"], priority)
            return True

        if cmd.startswith("done "):
            eid = cmd[5:].strip()
            ok = mark_done(eid)
            if ok:
                log.info("Backlog done: %s", eid)
            else:
                log.warning("Backlog done failed: %s not found", eid)
            return ok

        if cmd == "summary":
            summary = get_summary()
            log.info("Backlog summary requested")
            # Re-queue the summary as a regular message
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:20]
            (OUTGOING / f"out_{ts}.json").write_text(json.dumps({
                "text": summary, "created_at": datetime.now().isoformat(),
            }, ensure_ascii=False))
            return True

        return False
    except Exception as e:
        log.error("Backlog cmd error: %s", e)
        return False


def poll_updates(offset=0):
    payload = {"offset": offset + 1, "timeout": 10, "allowed_updates": ["message"]}
    r = tg_api("getUpdates", payload)
    if not r or not r.get("ok"):
        return offset, []
    max_id = offset
    messages = []
    for upd in r.get("result", []):
        uid = upd.get("update_id", 0)
        max_id = max(max_id, uid)
        msg = upd.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "")
        if text and chat_id:
            messages.append({
                "chat_id": chat_id,
                "text": text.strip(),
                "update_id": uid,
            })
    return max_id, messages


def handle_incoming(messages):
    for msg in messages:
        cid = msg["chat_id"]
        text = msg["text"]

        saved = load_chat_id()
        if not saved:
            save_chat_id(cid)
        elif str(cid) != saved:
            log.info("Ignored unknown chat: %s", cid)
            continue

        if text.startswith("/start"):
            send_message(
                "🤖 *Bizzy Telegram Bridge*\n\n"
                "Bizzy читает твои сообщения и отвечает.\n\n"
                "*Как общаться:*\n"
                "— Пиши любой текст — Bizzy получит\n"
                "— Команды для Bizzy пиши как обычно\n\n"
                "*Команды:*\n"
                "/status — состояние очередей\n"
                "/ping — проверка связи\n"
                "/dump — записать мысль/идею\n"
                "/post — предложить идею поста (Bizzy оценит)\n"
                "/backlog — сводка бэклога\n"
                "/bl — активные задачи\n"
                "/bl done B-001 — завершить задачу\n"
                "/bl add [P2] текст — добавить задачу\n"
                "/help — эта справка"
            )
            continue

        if text in ("/help", "/start"):
            send_message(
                "🤖 *Bizzy Telegram Bridge*\n\n"
                "— Пиши любой текст → Bizzy в inbox.md\n"
                "— Bizzy отвечает сюда + в Obsidian\n"
                "/status — очередь\n"
                "/dump — записать мысль\n"
                "/post — предложить идею поста\n"
                "/ping — pong"
            )
            continue

        if text == "/status":
            oc = len(list(OUTGOING.glob("*.json")))
            ic = len(list(INCOMING.glob("*.json")))
            send_message(f"📊 Исходящих: {oc}, Входящих: {ic}")
            continue

        if text == "/ping":
            send_message("pong 🏓")
            continue

        if text == "/backlog" or text == "/bl":
            try:
                from backlog import get_summary, read_backlog, add_entry, mark_done
                if text == "/backlog":
                    send_message(get_summary())
                else:
                    # /bl — show active items with IDs
                    entries, _ = read_backlog()
                    active = [e for e in entries if e["status"] not in ("done", "cancelled")]
                    if not active:
                        send_message("📋 Бэклог пуст. Всё сделано!")
                    else:
                        lines = ["📋 *Бэклог (активные)*"]
                        for e in active:
                            icon = "🔄" if e["status"] == "in_progress" else "·"
                            lines.append(f"{icon} {e['id']} [{e['priority']}] {e['title']}")
                        lines.append("")
                        lines.append("Команды: /bl, /bl done B-001")
                        send_message("\n".join(lines))
            except Exception as e:
                send_message(f"❌ Backlog error: {e}")
            continue

        if text.startswith("/bl done "):
            try:
                from backlog import mark_done
                eid = text[len("/bl done "):].strip()
                if mark_done(eid):
                    send_message(f"✅ {eid} завершён.")
                else:
                    send_message(f"❌ {eid} не найден.")
            except Exception as e:
                send_message(f"❌ Error: {e}")
            continue

        if text.startswith("/bl add "):
            try:
                from backlog import add_entry
                rest = text[len("/bl add "):].strip()
                # Format: [P2] Title or just Title (defaults to P3)
                priority = "P3"
                title = rest
                if rest.startswith("[") and rest[1] in "P0123":
                    priority = f"P{rest[2]}" if len(rest) > 2 and rest[2].isdigit() else "P3"
                    title = rest[4:].strip() if len(rest) > 4 else rest
                entry = add_entry(title, priority=priority, source="telegram", origin="telegram")
                send_message(f"✅ Добавлен {entry['id']} [{priority}]: {title}")
            except Exception as e:
                send_message(f"❌ Error: {e}")
            continue

        if text.startswith("/java "):
            question = text[len("/java "):].strip()
            if not question:
                send_message("Использование: /java <вопрос>")
                continue
            send_message("⏳ Спрашиваю Java Coach...")
            try:
                r = subprocess.run(
                    ["python3", "/root/java-tutor/coach.py", question],
                    capture_output=True, text=True, timeout=30,
                )
                reply = r.stdout.strip() or r.stderr.strip() or "❌ Нет ответа"
                send_message(reply)
            except Exception as e:
                send_message(f"❌ Ошибка: {e}")
            continue

        if text == "/java":
            send_message(
                "🤖 *Java Coach*\n\n"
                "Напиши /java <вопрос>:\n"
                "/java что такое final?\n"
                "/java дай задачу\n"
                "/java статус\n"
                "/java поехали"
            )
            continue

        if text.startswith("/dump"):
            entry = text[len("/dump"):].strip()
            if entry:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                try:
                    with open(DUMP_FILE, "a") as f:
                        f.write(f"\n## {ts}\n{entry}\n")
                    send_message("💡 Запомнил.")
                except OSError:
                    send_message("❌ Ошибка записи dump.")
            else:
                send_message("Использование: /dump <твоя мысль>")
            continue

        if text == "/post" or text.startswith("/post "):
            entry = text[6:].strip() if len(text) > 6 else ""
            if entry:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                try:
                    IDEAS_FILE.parent.mkdir(parents=True, exist_ok=True)
                    with open(IDEAS_FILE, "a") as f:
                        f.write(f"\n## {ts}\n{entry}\n")
                    send_message("✅ Идея записана. Bizzy оценит в ночном обходе и скажет своё мнение.")
                except OSError:
                    send_message("❌ Ошибка записи идеи.")
            else:
                send_message("Использование: /post <описание идеи>\nМожно с буллитами, можно одной строкой.")
            continue

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        (INCOMING / f"tg_{ts}.json").write_text(json.dumps({
            "source": "telegram", "text": text, "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False))

        try:
            with open(INBOX_FILE, "a") as f:
                if text.strip().endswith("!"):
                    # Task: write to tasks section, no ээ prefix
                    f.write(f"\n{text}")
                else:
                    # Discussion: write with ээ prefix
                    f.write(f"\nээ {text}!")
        except OSError:
            pass

        send_message("✅ Принято. Bizzy получит в следующем цикле.")


def push_message(text):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:20]
    (OUTGOING / f"out_{ts}.json").write_text(json.dumps({
        "text": text, "created_at": datetime.now().isoformat(), "retries": 0, "failed": False,
    }, ensure_ascii=False))
    log.info("Queued: %.60s", text.replace("\n", " "))


def main():
    if not load_token():
        log.error("No TG_BOT_TOKEN")
        sys.exit(1)
    offset = 0
    log.info("Telegram Bot started (poll %ss)", POLL_INTERVAL)
    while True:
        try:
            process_outgoing()
            offset, msgs = poll_updates(offset)
            if msgs:
                handle_incoming(msgs)
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            break
        except Exception as e:
            log.error("Unhandled: %s", e)
            time.sleep(POLL_INTERVAL * 2)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--push":
        push_message(" ".join(sys.argv[2:]))
    else:
        main()

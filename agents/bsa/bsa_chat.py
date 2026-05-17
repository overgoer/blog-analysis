#!/usr/bin/env python3
"""
BSA Chat — терминальный чат с Business Strategy Advisor @eddytester.

Запуск:
  python3 bsa_chat.py                       # интерактивный чат
  python3 bsa_chat.py --mode trigger        # однократный триггер от listener

Весь контекст, все инструменты, никаких костылей.
"""

import hashlib, json, os, re, subprocess, sys, readline, shutil
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
ORCH_DIR = BASE.parent / "orchestrator"
AGENTS_DIR = BASE.parent
VAULT = Path("/root/obsidian-vault/eddytester")
OBSIDIAN_STRAT = VAULT / "Стратегия"
CONTENT_MAP = Path("/root/blog-analysis/data/content_map_index.json")
PROMPT_FILE = BASE / "bsa_prompt.txt"
PROMPT_TRIGGER_FILE = BASE / "bsa_prompt_trigger.txt"
REQUESTS_FILE = Path("/root/obsidian-vault/requests.md")
INBOX_FILE = Path("/root/obsidian-vault/inbox.md")
OUTBOX_FILE = Path("/root/obsidian-vault/outbox.md")
VAULT_DIR = Path("/root/obsidian-vault")
LOG_FILE = Path("/root/blog-analysis/logs/bsa_chat.log")
ALLOWED_READ_DIRS = [str(VAULT), str(OBSIDIAN_STRAT),
                     str(Path("/root/obsidian-vault")),
                     str(Path("/root/blog-analysis/data")),
                     str(Path("/root/blog-analysis/agents/orchestrator")),
                     str(Path("/root/blog-analysis/agents/researcher")),
                     str(Path("/root/blog-analysis/agents/bsa"))]
ALLOWED_WRITE_DIRS = [str(OBSIDIAN_STRAT), str(Path("/root/obsidian-vault"))]
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


def call_deepseek(messages, tools=None):
    key = load_key()
    if not key: return None, "No API key"
    payload = {"model": "deepseek-v4-flash", "messages": messages,
               "temperature": 0.5, "max_tokens": 4096}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        import tempfile
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


def _is_allowed(path, allowed):
    real = os.path.realpath(str(path))
    return any(real.startswith(os.path.realpath(d)) for d in allowed)


def tool_read_file(**kwargs):
    fp = kwargs.get("filepath") or kwargs.get("path") or kwargs.get("file", "")
    if not _is_allowed(fp, ALLOWED_READ_DIRS): return "Error: access denied"
    try:
        p = Path(fp)
        if not p.exists(): return "File not found"
        if p.stat().st_size > 100_000:
            return p.read_text(encoding="utf-8", errors="replace")[:50000] + "\n[...truncated]"
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception as e: return f"Error: {e}"

def tool_write_file(**kwargs):
    fp = kwargs.get('filepath') or kwargs.get('path') or kwargs.get('file', '')
    ct = kwargs.get('content') or kwargs.get('text') or kwargs.get('body', '')
    if not _is_allowed(fp, ALLOWED_WRITE_DIRS): return "Error: can only write to Стратегия/"
    try:
        p = Path(fp); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(ct, encoding="utf-8"); return f"Saved ({len(ct)} bytes)"
    except Exception as e: return f"Error: {e}"

def tool_list_dir(**kwargs):
    dp = kwargs.get("dirpath") or kwargs.get("path") or kwargs.get("dir", "")
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

def tool_run_content_manager(topic):
    """Run full content pipeline for a topic."""
    try:
        r = subprocess.run(
            [str(AGENTS_DIR / ".venv/bin/python3"),
             str(AGENTS_DIR / "orchestrator/content_manager.py"),
             "--topic", topic, "--no-email"],
            capture_output=True, text=True, timeout=600,
            cwd=str(AGENTS_DIR))
        return (r.stdout[-5000:] + ("\nSTDERR:\n" + r.stderr[-1000:])
                if r.stderr.strip() else r.stdout[-5000:])
    except subprocess.TimeoutExpired: return "Error: content manager timed out"
    except Exception as e: return f"Error: {e}"

def tool_run_pm_agent(task_text):
    """Run PM Agent for GO/NO_GO assessment."""
    try:
        r = subprocess.run(
            [str(AGENTS_DIR / ".venv/bin/python3"),
             str(AGENTS_DIR / "orchestrator/pm_agent.py"), task_text],
            capture_output=True, text=True, timeout=120)
        return (r.stdout[-3000:] + ("\nSTDERR:\n" + r.stderr[-500:])
                if r.stderr.strip() else r.stdout[-3000:])
    except subprocess.TimeoutExpired: return "Error: PM Agent timed out"
    except Exception as e: return f"Error: {e}"

def tool_run_agent(agent_name):
    script = ALLOWED_AGENTS.get(agent_name)
    if not script: return f"Unknown agent: {agent_name}"
    try:
        r = subprocess.run([str(AGENTS_DIR / ".venv/bin/python3"), script],
                           capture_output=True, text=True, timeout=300)
        return r.stdout[-5000:] + ("\nSTDERR:\n" + r.stderr[-1000:] if r.stderr.strip() else "")
    except subprocess.TimeoutExpired: return f"Agent {agent_name} timed out"
    except Exception as e: return f"Error: {e}"

def tool_send_email(subject, body, to="eddy.super1@gmail.com"):
    try:
        sys.path.insert(0, str(AGENTS_DIR.parent / "lib"))
        from mailer import load_config, send
        cfg = load_config(str(AGENTS_DIR / ".mailcfg"))
        send(subject, body, cfg=cfg)
        return f"Email sent to {to}"
    except Exception as e: return f"Error: {e}"


def tool_update_status(task_text, status="running", detail=""):
    """Update task status. Writes to outbox.md as a Bizzy status message."""
    try:
        emoji = {"done": "\u2705", "running": "\U0001f504", "failed": "\u274c", "pending": "\u23f3"}
        e = emoji.get(status, "\U0001f504")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        d = f" \u2192 {detail}" if detail else ""
        entry = "\n---\n\n**\u0422\u044b:** \u0437\u0430\u0434\u0430\u0447\u0430: " + task_text + "\n\n**Bizzy:** " + e + " " + task_text + d + " (" + now + ")\n"
        with open(str(OUTBOX_FILE), "a") as f:
            f.write(entry)
        subprocess.run(["git", "-C", str(VAULT_DIR), "add", "outbox.md"], capture_output=True, timeout=15)
        r = subprocess.run(["git", "-C", str(VAULT_DIR), "diff", "--cached", "--quiet"], capture_output=True, timeout=15)
        if r.returncode != 0:
            subprocess.run(["git", "-C", str(VAULT_DIR), "commit", "-m", "bizzy: status " + now], capture_output=True, timeout=15)
            subprocess.run(["git", "-C", str(VAULT_DIR), "pull", "--rebase"], capture_output=True, timeout=15)
            subprocess.run(["git", "-C", str(VAULT_DIR), "push"], capture_output=True, timeout=15)
        return "Status written to outbox.md: " + task_text + " \u2192 " + status
    except Exception as e:
        log("update_status error: " + str(e))
        return "Error: " + str(e)

def tool_shorten_task(old_text, new_text):
    """Replace old task text with shorter version."""
    try:
        content = INBOX_FILE.read_text(encoding="utf-8") if INBOX_FILE.exists() else ""
        if old_text not in content:
            return "Note: '" + old_text + "' not found in inbox (may already be processed)"
        content = content.replace(old_text, new_text)
        INBOX_FILE.write_text(content, encoding="utf-8")
        return "Shortened: " + old_text + " \u2192 " + new_text
    except Exception as e:
        return "Error: " + str(e)

def tool_discuss_reply(response_text):
    """Append BSA response to outbox.md with **\u0422\u044b:** / **Bizzy:** format + git commit+push.
    Auto-detects \u044d\u044d\u044d (new thread) and adds visual separator."""
    try:
        last_question = ""
        is_new_tread = False
        try:
            inbox = INBOX_FILE.read_text(encoding="utf-8")
            for line in reversed(inbox.split("\n")):
                stripped = line.strip()
                if stripped.startswith("\u044d\u044d"):
                    last_question = stripped
                    is_new_tread = stripped.startswith("\u044d\u044d\u044d")
                    break
        except Exception:
            pass
        
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        sep = "\n--- * * * ---\n" if is_new_tread else ""
        if last_question:
            entry = sep + "\n---\n\n**\u0422\u044b:** " + last_question + "\n\n**Bizzy:** " + response_text + "\n"
        else:
            entry = sep + "\n---\n\n**Bizzy:** " + response_text + "\n"
        
        with open(str(OUTBOX_FILE), "a") as f:
            f.write(entry)
        
        subprocess.run(["git", "-C", str(VAULT_DIR), "add", "outbox.md"], capture_output=True, timeout=15)
        r = subprocess.run(["git", "-C", str(VAULT_DIR), "diff", "--cached", "--quiet"], capture_output=True, timeout=15)
        if r.returncode != 0:
            subprocess.run(["git", "-C", str(VAULT_DIR), "commit", "-m", "bizzy: response " + ts], capture_output=True, timeout=15)
            subprocess.run(["git", "-C", str(VAULT_DIR), "pull", "--rebase"], capture_output=True, timeout=15)
            subprocess.run(["git", "-C", str(VAULT_DIR), "push"], capture_output=True, timeout=15)
        return "\u2705 Response written to outbox.md (" + str(len(response_text)) + " chars)"
    except Exception as e:
        log("discuss_reply error: " + str(e))
        return "Error: " + str(e)

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
}}, {"type": "function", "function": {
    "name": "run_content_manager",
    "description": "Run full content pipeline on a topic. Use for content generation tasks.",
    "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}
}}, {"type": "function", "function": {
    "name": "run_pm_agent",
    "description": "Run PM Agent for GO/NO_GO on a dev task.",
    "parameters": {"type": "object", "properties": {"task_text": {"type": "string"}}, "required": ["task_text"]}
}}, {"type": "function", "function": {
    "name": "run_agent",
    "description": "Run agent: bsa (audit) or pm (product)",
    "parameters": {"type": "object", "properties": {"agent_name": {"type": "string", "enum": ["bsa", "pm"]}}, "required": ["agent_name"]}
}}, {"type": "function", "function": {
    "name": "send_email",
    "description": "Send email to eddy.super1@gmail.com",
    "parameters": {"type": "object", "properties": {"subject": {"type": "string"}, "body": {"type": "string"}, "to": {"type": "string"}}, "required": ["subject", "body"]}
}}, {"type": "function", "function": {
    "name": "update_status",
    "description": "Update task status in requests.md status section. Use instead of write_file for status updates. Preserves other sections.",
    "parameters": {"type": "object", "properties": {
        "task_text": {"type": "string"},
        "status": {"type": "string", "enum": ["done", "running", "pending", "failed"]},
        "detail": {"type": "string"}
    }, "required": ["task_text", "status"]}
}}, {"type": "function", "function": {
    "name": "shorten_task",
    "description": "Shorten task text in requests.md. Use when the original task description is too long.",
    "parameters": {"type": "object", "properties": {
        "old_text": {"type": "string"},
        "new_text": {"type": "string"}
    }, "required": ["old_text", "new_text"]}
}}]

TOOL_MAP = {"read_file": tool_read_file, "write_file": tool_write_file, "update_status": tool_update_status, "shorten_task": tool_shorten_task,
            "list_dir": tool_list_dir, "run_researcher": tool_run_researcher,
            "run_content_manager": tool_run_content_manager,
            "run_pm_agent": tool_run_pm_agent,
            "run_agent": tool_run_agent, "send_email": tool_send_email,
            "discuss_reply": tool_discuss_reply}


def build_prompt():
    p = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.exists() else "You are BSA."
    extra = []
    if CONTENT_MAP.exists():
        try:
            posts = json.loads(CONTENT_MAP.read_text())
            recent = posts[-5:]
            extra.append("\n\nRecent posts:\n" + "\n".join(
                f"- {p.get('title','?')} ({p.get('date','?')})" for p in recent))
        except: pass
    files = list(OBSIDIAN_STRAT.glob("*.md")) if OBSIDIAN_STRAT.exists() else []
    if files: extra.append(f"\nStrategy files: {', '.join(f.name for f in files)}")
    return p + "\n".join(extra)


def run_conversation(messages):
    for _ in range(12):
        msg, text = call_deepseek(messages, tools=TOOLS)
        if msg is None:
            return f"Error: {text}", messages
        if msg.get("tool_calls"):
            messages.append(msg)
            for tc in msg["tool_calls"]:
                fn = tc["function"]
                fn_name, args_str = fn["name"], fn["arguments"]
                try: args = json.loads(args_str)
                except: args = {}
                log(f"Tool: {fn_name}")
                result = TOOL_MAP.get(fn_name, lambda **_: f"Unknown tool: {fn_name}")(**args)
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": str(result)[:10000]})
            continue
        return text, messages
    return "Iteration limit reached.", messages


def trigger_mode():
    """One-shot BSA session: read inbox.md, decide, delegate, write to outbox.md."""
    if not load_key():
        log("ERROR: No API key in trigger mode")
        print("ERROR: DeepSeek API key not found", file=sys.stderr)
        sys.exit(1)

    log("BSA trigger mode started")

    # Load trigger prompt
    prompt_text = "You are BSA. Read requests.md and act."
    if PROMPT_TRIGGER_FILE.exists():
        prompt_text = PROMPT_TRIGGER_FILE.read_text(encoding="utf-8")
    elif PROMPT_FILE.exists():
        prompt_text = PROMPT_FILE.read_text(encoding="utf-8")

    # Build extra context
    extra = []
    if CONTENT_MAP.exists():
        try:
            posts = json.loads(CONTENT_MAP.read_text())
            recent = posts[-5:]
            extra.append("\nRecent posts:\n" + "\n".join(
                f"- {p.get('title','?')} ({p.get('date','?')})" for p in recent))
        except: pass
    strat_dir = OBSIDIAN_STRAT
    sfiles = list(strat_dir.glob("*.md")) if strat_dir.exists() else []
    if sfiles:
        extra.append(f"\nStrategy files: {', '.join(f.name for f in sfiles)}")

    full_prompt = prompt_text + "\n".join(extra)

    messages = [
        {"role": "system", "content": full_prompt},
        {"role": "user", "content": (
            "Новое сообщение в inbox.md. "
            "Прочитай файл, пойми что нужно, прими решение и действуй. "
            "После завершения пиши ответы в outbox.md.")}
    ]

    # Run conversation (max 8 iterations)
    resp, _ = run_conversation(messages)

    if resp:
        log(f"BSA trigger response: {resp[:300]}...")
        print(resp)
    else:
        log("BSA trigger: completed (tool calls only)")
        print("BSA trigger: completed")

    # Auto-commit outbox.md changes if BSA wrote via write_file
    try:
        subprocess.run(["git", "-C", str(VAULT_DIR), "add", "outbox.md"], capture_output=True, timeout=15)
        r = subprocess.run(["git", "-C", str(VAULT_DIR), "diff", "--cached", "--quiet"], capture_output=True, timeout=15)
        if r.returncode != 0:
            now = datetime.now().strftime("%Y-%m-%d %H:%M")
            subprocess.run(["git", "-C", str(VAULT_DIR), "commit", "-m", "bizzy: auto-commit " + now], capture_output=True, timeout=15)
            subprocess.run(["git", "-C", str(VAULT_DIR), "pull", "--rebase"], capture_output=True, timeout=15)
            subprocess.run(["git", "-C", str(VAULT_DIR), "push"], capture_output=True, timeout=15)
    except Exception as e:
        log("auto-commit error: " + str(e))

    log("BSA trigger mode completed")

def discuss_mode(question):
    """BSA discussion mode: answer user question, write to outbox.md.
    ээ = continue thread (pass history from outbox.md)
    эээ = new thread (fresh context, skip idempotency)"""
    if not load_key():
        log("ERROR: No API key in discuss mode")
        sys.exit(1)
    log("BSA discuss mode started")

    is_new_tread = question.strip().startswith("\u044d\u044d\u044d")
    
    # Idempotency: skip for new threads (\u044d\u044d\u044d)
    if not is_new_tread:
        try:
            if INBOX_FILE.exists():
                inbox = INBOX_FILE.read_text(encoding="utf-8")
                last_inbox_question = ""
                for line in reversed(inbox.split("\n")):
                    stripped = line.strip()
                    if stripped.startswith("\u044d\u044d"):
                        last_inbox_question = stripped
                        break

                if last_inbox_question and OUTBOX_FILE.exists():
                    outbox = OUTBOX_FILE.read_text(encoding="utf-8")
                    last_outbox_question = ""
                    for line in reversed(outbox.split("\n")):
                        if line.strip().startswith("**\u0422\u044b:**"):
                            parts = line.split("**\u0422\u044b:**", 1)
                            if len(parts) > 1:
                                last_outbox_question = parts[1].strip()
                            break

                    if last_inbox_question and last_outbox_question:
                        import unicodedata
                        n_in = unicodedata.normalize("NFC", last_inbox_question.strip())
                        n_out = unicodedata.normalize("NFC", last_outbox_question.strip())
                        if n_in == n_out:
                            log("Idempotency: last question already answered in outbox.md, skipping")
                            print("Already answered in outbox.md, skipping")
                            return
        except Exception as e:
            log("Idempotency check failed (non-critical): " + str(e))

    # For continue thread (\u044d\u044d): add history from outbox.md
    if not is_new_tread:
        try:
            if OUTBOX_FILE.exists():
                outbox_history = OUTBOX_FILE.read_text(encoding="utf-8").strip()
                if outbox_history:
                    history_note = "\n\n## \u0418\u0441\u0442\u043e\u0440\u0438\u044f \u043e\u0431\u0441\u0443\u0436\u0434\u0435\u043d\u0438\u044f (\u0438\u0437 outbox.md):\n" + outbox_history + "\n\n\u042d\u0442\u043e \u043f\u0440\u043e\u0448\u043b\u044b\u0435 \u043e\u0442\u0432\u0435\u0442\u044b. \u041e\u0442\u0432\u0435\u0442\u044c \u043d\u0430 \u043d\u043e\u0432\u044b\u0439 \u0432\u043e\u043f\u0440\u043e\u0441 \u043d\u0438\u0436\u0435."
                    discuss_prompt_text += history_note
        except Exception as e:
            log("History read failed (non-critical): " + str(e))

    discuss_prompt_file = BASE / "bsa_prompt_discuss.txt"
    discuss_prompt_text = discuss_prompt_file.read_text(encoding="utf-8") if discuss_prompt_file.exists() else "You are BSA. Answer the user's question."

    messages = [
        {"role": "system", "content": discuss_prompt_text},
        {"role": "user", "content": question}
    ]

    resp, messages = run_conversation(messages)
    if resp:
        log("BSA discuss response: " + resp[:300] + "...")
        # Check if BSA already called discuss_reply tool during conversation
        bsa_used_tool = any(
            msg.get("role") == "assistant" and 
            any(tc["function"]["name"] == "discuss_reply" for tc in msg.get("tool_calls", []))
            for msg in messages
        )
        if not bsa_used_tool:
            try:
                tool_discuss_reply(resp)
                log("Response written to outbox.md (auto-fallback)")
            except Exception as e:
                log("Write to outbox.md failed: " + str(e))
        else:
            log("BSA already used discuss_reply tool, skipping auto-write")
        print(resp)
    else:
        log("BSA discuss: completed (tool calls only)")
        print("BSA discuss: completed")
    log("BSA discuss mode completed")

def main():
    # Handle --mode trigger
    if "--mode" in sys.argv:
        idx = sys.argv.index("--mode")
        mode = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "chat"
        if mode == "trigger":
            trigger_mode()
            return
        if mode == "discuss":
            question = " ".join(sys.argv[idx+2:]) if len(sys.argv) > idx + 2 else ""
            discuss_mode(question)
            return
        # else fall through to chat (for future modes)

    # Check API key first
    if not load_key():
        print("ERROR: DeepSeek API key not found. Check Bitwarden or DEEPSEEK_API_KEY env var.")
        sys.exit(1)

    print("\033[1;31m" + "=" * 60)
    print("  BSA (Business Strategy Advisor) — @eddytester")
    print("=" * 60 + "\033[0m")
    print("  Commands: /new — новый разговор  /exit — выход")
    print("  Инструменты: read/write файлы, исследование, агенты, email\n")

    prompt = build_prompt()
    messages = [{"role": "system", "content": prompt}]

    # Pipe mode: if stdin has data, read all and send as first message
    piped_input = ""
    if not sys.stdin.isatty():
        try:
            import select
            if select.select([sys.stdin], [], [], 0.5)[0]:
                piped_input = sys.stdin.read().strip()
                print(f"\033[1;32m[Piped {len(piped_input)} chars]\033[0m")
        except: pass

    while True:
        if piped_input:
            user = piped_input
            piped_input = ""
        else:
            try:
                user = input("\x01\033[1;33m\x02You:\x01\033[0m\x02 ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye.")
                break

        if not user: continue
        if user == "/exit": break
        if user == "/new":
            messages = [{"role": "system", "content": build_prompt()}]
            print("\033[1;32m[New session started]\033[0m")
            continue

        messages.append({"role": "user", "content": user})
        print("\033[1;34mBSA:\033[0m")
        resp, messages = run_conversation(messages)

        if resp:
            print("\033[0;37m" + resp + "\033[0m")
            messages.append({"role": "assistant", "content": resp})
        print()


if __name__ == "__main__":
    main()

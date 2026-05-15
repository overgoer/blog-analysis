#!/usr/bin/env python3
"""
BSA Chat — терминальный чат с Business Strategy Advisor @eddytester.

Запуск: python3 bsa_chat.py

Весь контекст, все инструменты, никаких костылей.
"""

import hashlib, json, os, subprocess, sys, readline, shutil
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
ORCH_DIR = BASE.parent / "orchestrator"
AGENTS_DIR = BASE.parent
VAULT = Path("/root/obsidian-vault/eddytester")
OBSIDIAN_STRAT = VAULT / "Стратегия"
CONTENT_MAP = Path("/root/blog-analysis/data/content_map_index.json")
PROMPT_FILE = BASE / "bsa_prompt.txt"
LOG_FILE = Path("/root/blog-analysis/logs/bsa_chat.log")
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


def tool_read_file(filepath):
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

def tool_list_dir(dirpath):
    if not _is_allowed(dirpath, ALLOWED_READ_DIRS): return "Error: access denied"
    try:
        p = Path(dirpath)
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
    "name": "run_agent",
    "description": "Run agent: bsa (audit) or pm (product)",
    "parameters": {"type": "object", "properties": {"agent_name": {"type": "string", "enum": ["bsa", "pm"]}}, "required": ["agent_name"]}
}}, {"type": "function", "function": {
    "name": "send_email",
    "description": "Send email to eddy.super1@gmail.com",
    "parameters": {"type": "object", "properties": {"subject": {"type": "string"}, "body": {"type": "string"}, "to": {"type": "string"}}, "required": ["subject", "body"]}
}}]

TOOL_MAP = {"read_file": tool_read_file, "write_file": tool_write_file,
            "list_dir": tool_list_dir, "run_researcher": tool_run_researcher,
            "run_agent": tool_run_agent, "send_email": tool_send_email}


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
    for _ in range(8):
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


def main():
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

    while True:
        try:
            user = input("\033[1;33mYou:\033[0m ").strip()
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

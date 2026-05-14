#!/usr/bin/env python3
"""
BSA Web — стратегический чат-советник @eddytester.

Запуск:
  python3 bsa_web.py                    # первый запуск — сгенерирует пароль
  python3 bsa_web.py --set-password     # сменить пароль
  python3 bsa_web.py [--port 3000]      # указать порт

Flask + DeepSeek function calling. BSA может читать/писать Obsidian,
запускать ресерчер и агентов.
"""

import hashlib, json, os, secrets, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path
from http import HTTPStatus
from flask import Flask, request, jsonify, session, render_template_string
from functools import wraps

# ── Paths ───────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent
ORCH_DIR = BASE.parent / "orchestrator"
AGENTS_DIR = BASE.parent
VAULT = Path("/root/obsidian-vault/eddytester")
CONTENT_MAP = Path("/root/blog-analysis/data/content_map_index.json")
OBSIDIAN_STRAT = VAULT / "Стратегия"
CONFIG = BASE / "bsa_web_config.json"
PROMPT_FILE = BASE / "bsa_prompt.txt"
SESSIONS_DIR = BASE / "sessions"
LOG_FILE = Path("/root/blog-analysis/logs/bsa_web.log")
SESSIONS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)


# ── Logging ──────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")


# ── Config ───────────────────────────────────────────────────────────────
def load_config():
    if CONFIG.exists():
        return json.loads(CONFIG.read_text())
    return {"password_hash": "", "port": 3000, "debug": False}


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


def set_password(plain):
    cfg = load_config()
    cfg["password_hash"] = hashlib.sha256(plain.encode()).hexdigest()
    save_config(cfg)
    log("Password updated")


def check_password(plain):
    cfg = load_config()
    if not cfg.get("password_hash"):
        return True  # no password set = open
    return hashlib.sha256(plain.encode()).hexdigest() == cfg["password_hash"]


# ── DeepSeek call ────────────────────────────────────────────────────────
def load_key():
    try:
        sys.path.insert(0, str(ORCH_DIR))
        from bw_helper import BWVault
        key = BWVault().get_password("DeepSeek API Key")
        if key:
            return key
    except Exception:
        pass
    env_file = AGENTS_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DEEPSEEK_API_KEY")


def call_deepseek(messages, tools=None, temp=0.5, max_tokens=4096):
    key = load_key()
    if not key:
        return None, "No DeepSeek API key"

    payload = {
        "model": "deepseek-v4-flash",
        "messages": messages,
        "temperature": temp,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    try:
        r = subprocess.run(
            ["curl", "-s", "https://api.deepseek.com/chat/completions",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=120,
        )
        resp = json.loads(r.stdout)
        choice = resp["choices"][0]
        msg = choice["message"]
        if msg.get("tool_calls"):
            return msg, None
        return msg, msg["content"]
    except Exception as e:
        log(f"DeepSeek call error: {e}")
        return None, f"Error: {e}"


# ── Tool implementations ─────────────────────────────────────────────────
ALLOWED_READ_DIRS = [
    str(VAULT),
    str(OBSIDIAN_STRAT),
    str(Path("/root/blog-analysis/data")),
    str(Path("/root/blog-analysis/agents/orchestrator")),
    str(Path("/root/blog-analysis/agents/researcher")),
    str(Path("/root/blog-analysis/agents/bsa")),
]
ALLOWED_WRITE_DIRS = [str(OBSIDIAN_STRAT)]
ALLOWED_AGENTS = {"bsa": "/root/blog-analysis/agents/bsa/bsa_agent.py",
                  "pm": "/root/blog-analysis/agents/orchestrator/pm_agent.py"}


def _is_allowed(path, allowed):
    real = os.path.realpath(str(path))
    for d in allowed:
        if real.startswith(os.path.realpath(d)):
            return True
    return False


def tool_read_file(filepath):
    if not _is_allowed(filepath, ALLOWED_READ_DIRS):
        return "Error: access denied"
    try:
        p = Path(filepath)
        if not p.exists():
            return "File not found"
        if p.stat().st_size > 100_000:
            return p.read_text(encoding="utf-8", errors="replace")[:50000] + "\n\n[... truncated at 50KB]"
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"


def tool_write_file(filepath, content):
    if not _is_allowed(filepath, ALLOWED_WRITE_DIRS):
        return "Error: can only write to Стратегия/ directory"
    try:
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        log(f"Wrote {len(content)} bytes to {filepath}")
        return f"Saved ({len(content)} bytes)"
    except Exception as e:
        return f"Error writing file: {e}"


def tool_list_dir(dirpath):
    if not _is_allowed(dirpath, ALLOWED_READ_DIRS):
        return "Error: access denied"
    try:
        p = Path(dirpath)
        if not p.is_dir():
            return "Not a directory"
        items = []
        for f in p.iterdir():
            items.append(f.name + ("/" if f.is_dir() else f"  ({f.stat().st_size} bytes)"))
        return "\n".join(items)
    except Exception as e:
        return f"Error listing dir: {e}"


def tool_run_researcher(topic):
    if len(topic) > 500:
        return "Error: topic too long"
    try:
        log(f"Running researcher on: {topic[:80]}...")
        r = subprocess.run(
            [str(AGENTS_DIR / ".venv/bin/python3"),
             str(AGENTS_DIR / "researcher/researcher.py"), topic],
            capture_output=True, text=True, timeout=300,
            cwd=str(AGENTS_DIR / "researcher"),
        )
        out = r.stdout[-5000:] if len(r.stdout) > 5000 else r.stdout
        err = r.stderr[-1000:] if len(r.stderr) > 1000 else r.stderr
        result = out
        if err.strip():
            result += f"\n\nSTDERR:\n{err}"
        return result
    except subprocess.TimeoutExpired:
        return "Error: researcher timed out after 300s"
    except Exception as e:
        return f"Error running researcher: {e}"


def tool_run_agent(agent_name):
    script = ALLOWED_AGENTS.get(agent_name)
    if not script:
        return f"Error: unknown agent '{agent_name}'. Allowed: {', '.join(ALLOWED_AGENTS.keys())}"
    try:
        log(f"Running agent: {agent_name}")
        r = subprocess.run(
            [str(AGENTS_DIR / ".venv/bin/python3"), script],
            capture_output=True, text=True, timeout=300,
        )
        out = r.stdout[-5000:] if len(r.stdout) > 5000 else r.stdout
        err = r.stderr[-1000:] if len(r.stderr) > 1000 else r.stderr
        result = out
        if err.strip():
            result += f"\n\nSTDERR:\n{err}"
        return result
    except subprocess.TimeoutExpired:
        return f"Error: agent {agent_name} timed out"
    except Exception as e:
        return f"Error running agent: {e}"


def tool_send_email(subject, body, to="eddy.super1@gmail.com"):
    try:
        import sys as _sys
        _sys.path.insert(0, str(AGENTS_DIR.parent / "lib"))
        from mailer import load_config, send
        cfg = load_config(str(AGENTS_DIR / ".mailcfg"))
        send(subject, body, cfg=cfg)
        log(f"Email sent to {to}: {subject[:60]}")
        return f"Email sent to {to}"
    except Exception as e:
        return f"Error sending email: {e}"


# ── Tool definitions (OpenAI format) ─────────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from allowed directories: Obsidian vault, blog-analysis data, agents config",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Absolute path to the file"}
                },
                "required": ["filepath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write/update a file in Obsidian Стратегия/ directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Absolute path in Obsidian Стратегия/"},
                    "content": {"type": "string", "description": "Full file content"}
                },
                "required": ["filepath", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List contents of a directory (Obsidian, data, agents config)",
            "parameters": {
                "type": "object",
                "properties": {
                    "dirpath": {"type": "string", "description": "Absolute path to the directory"}
                },
                "required": ["dirpath"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_researcher",
            "description": "Run the researcher agent on a topic to generate a research brief",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Research topic (max 500 chars)"}
                },
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_agent",
            "description": "Run a full agent: bsa (strategic audit), pm (product analysis)",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "enum": ["bsa", "pm"],
                        "description": "Agent to run: bsa or pm"
                    }
                },
                "required": ["agent_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email to eddy.super1@gmail.com",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body (plain text)"},
                    "to": {"type": "string", "description": "Recipient (default: eddy.super1@gmail.com)"}
                },
                "required": ["subject", "body"]
            }
        }
    }
]

TOOL_MAP = {
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "list_dir": tool_list_dir,
    "run_researcher": tool_run_researcher,
    "run_agent": tool_run_agent,
    "send_email": tool_send_email,
}


# ── Conversation loop ────────────────────────────────────────────────────
def build_system_prompt():
    prompt = PROMPT_FILE.read_text(encoding="utf-8") if PROMPT_FILE.exists() else "You are BSA."
    # Add recent context
    extra = []
    if CONTENT_MAP.exists():
        try:
            posts = json.loads(CONTENT_MAP.read_text())
            recent = posts[-5:] if len(posts) > 5 else posts
            extra.append(f"\n\nRecent posts:\n" + "\n".join(
                f"- {p['title']} ({p['date']})" for p in recent if 'date' in p and 'title' in p
            ))
        except Exception:
            pass
    if OBSIDIAN_STRAT.exists():
        files = [f.name for f in OBSIDIAN_STRAT.iterdir() if f.suffix == ".md"]
        if files:
            extra.append(f"\nStrategy files available: {', '.join(files)}")
    return prompt + "\n".join(extra)


def run_conversation(messages):
    """Run BSA conversation with tool calling loop. Returns (response_text, updated_messages)."""
    max_iterations = 8  # safety limit
    for _ in range(max_iterations):
        msg, text = call_deepseek(messages, tools=TOOLS)
        if msg is None:
            return f"Error: {text}", messages

        if msg.get("tool_calls"):
            messages.append(msg)
            for tc in msg["tool_calls"]:
                fn = tc["function"]
                fn_name = fn["name"]
                try:
                    args = json.loads(fn["arguments"])
                except json.JSONDecodeError:
                    args = {}
                log(f"Tool call: {fn_name}({json.dumps(args)[:200]})")

                result = TOOL_MAP.get(fn_name, lambda **_: f"Unknown tool: {fn_name}")(**args)
                if not isinstance(result, str):
                    result = json.dumps(result, ensure_ascii=False)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": str(result)[:10000],
                })
            continue  # let the model respond with tool results in context

        # No tool calls — this is the final response
        return text, messages

    return "Reached iteration limit. Please try a simpler query.", messages


# ── Auth ─────────────────────────────────────────────────────────────────
HTML_LOGIN = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>BSA Login</title><style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#1a1a2e;display:flex;justify-content:center;align-items:center;min-height:100vh}
.login{background:#16213e;padding:2rem;border-radius:12px;width:90%;max-width:360px;text-align:center}
h1{color:#e94560;font-size:1.3rem;margin-bottom:1.5rem}
input{width:100%;padding:12px;margin-bottom:12px;border:1px solid #333;border-radius:8px;background:#0f3460;color:#fff;font-size:1rem}
button{width:100%;padding:12px;background:#e94560;color:#fff;border:none;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer}
.error{color:#e94560;font-size:.85rem;margin-bottom:1rem}
</style></head><body>
<div class="login">
<h1>BSA Advisor</h1>
<form method="post" action="/login">
<input type="password" name="password" placeholder="Password" autofocus>
<button type="submit">Enter</button>
</form></div></body></html>"""


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"error": "unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return HTML_LOGIN
    pw = request.form.get("password", "")
    if check_password(pw):
        session["authenticated"] = True
        session.permanent = True
        return "", 204
    return HTML_LOGIN.replace('class="login"',
                              'class="login"><div class="error">Wrong password</div><div class="login"'), 401


@app.route("/")
@login_required
def index():
    return render_template_string(HTML_CHAT)


@app.route("/api/chat", methods=["POST"])
@login_required
def chat():
    data = request.get_json(force=True)
    user_msg = data.get("message", "").strip()
    token = data.get("token", "anon")

    if not user_msg:
        return jsonify({"error": "empty message"}), 400

    # Load or create conversation
    session_file = SESSIONS_DIR / f"{token}.json"
    if session_file.exists():
        try:
            conv = json.loads(session_file.read_text())
        except Exception:
            conv = []
    else:
        system_prompt = build_system_prompt()
        conv = [{"role": "system", "content": system_prompt}]

    conv.append({"role": "user", "content": user_msg})

    # Run conversation with tool calling
    response_text, updated_conv = run_conversation(conv)

    if response_text:
        updated_conv.append({"role": "assistant", "content": response_text})
        # Save (keep last 50 messages to avoid bloat)
        trimmed = [updated_conv[0]] + updated_conv[-50:] if len(updated_conv) > 50 else updated_conv
        session_file.write_text(json.dumps(trimmed, ensure_ascii=False))
        log(f"Chat: {token[:8]} | user({len(user_msg)}) bsa({len(response_text)})")

    return jsonify({"response": response_text or "No response"})


@app.route("/api/new", methods=["POST"])
@login_required
def new_session():
    token = secrets.token_hex(16)
    system_prompt = build_system_prompt()
    conv = [{"role": "system", "content": system_prompt}]
    (SESSIONS_DIR / f"{token}.json").write_text(json.dumps(conv, ensure_ascii=False))
    return jsonify({"token": token})


# ── HTML Chat Template ───────────────────────────────────────────────────
HTML_CHAT = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>BSA Advisor</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#1a1a2e;color:#e0e0e0;display:flex;flex-direction:column;height:100dvh;overflow:hidden}
.header{background:#16213e;padding:12px 16px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #0f3460}
.header h1{font-size:1rem;color:#e94560}
.header button{background:#0f3460;color:#e94560;border:1px solid #e94560;padding:4px 12px;border-radius:6px;font-size:.8rem;cursor:pointer}
#chat{flex:1;overflow-y:auto;padding:12px 16px;scroll-behavior:smooth}
.msg{margin-bottom:12px;max-width:88%;line-height:1.45;font-size:.95rem}
.msg.user{margin-left:auto;text-align:right}
.msg.bsa{margin-right:auto}
.msg .bubble{display:inline-block;padding:10px 14px;border-radius:12px;text-align:left;word-wrap:break-word;white-space:pre-wrap}
.msg.user .bubble{background:#e94560;color:#fff;border-bottom-right-radius:4px}
.msg.bsa .bubble{background:#16213e;color:#e0e0e0;border-bottom-left-radius:4px}
.msg.bsa .bubble code{background:#0f3460;padding:1px 4px;border-radius:4px;font-size:.85rem}
.msg.bsa .bubble pre{background:#0f3460;padding:10px;border-radius:8px;overflow-x:auto;margin:6px 0;font-size:.85rem}
.msg.bsa .bubble pre code{background:none;padding:0}
.msg .time{font-size:.7rem;color:#666;margin-top:4px}
.input-area{background:#16213e;padding:10px 16px;display:flex;gap:8px;border-top:1px solid #0f3460}
.input-area input{flex:1;padding:10px 14px;border:1px solid #0f3460;border-radius:8px;background:#0f3460;color:#fff;font-size:1rem;outline:none}
.input-area input:focus{border-color:#e94560}
.input-area button{padding:10px 18px;background:#e94560;color:#fff;border:none;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer;white-space:nowrap}
.input-area button:disabled{opacity:.5}
.loading{text-align:center;color:#666;font-size:.85rem;padding:8px}
</style></head><body>
<div class="header">
<h1>BSA Advisor</h1>
<button onclick="newSession()">New chat</button>
</div>
<div id="chat"></div>
<div class="loading" id="loading" style="display:none">BSA is thinking...</div>
<div class="input-area">
<input id="input" type="text" placeholder="Ask BSA..." autofocus>
<button id="sendBtn" onclick="send()">Send</button>
</div>
<script>
let token = localStorage.getItem('bsa_token');
let sending = false;
if(!token) newSession();
else loadHistory();
document.getElementById('input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});
async function newSession(){
  const r=await fetch('/api/new',{method:'POST'});
  const d=await r.json();
  token=d.token;
  localStorage.setItem('bsa_token',token);
  document.getElementById('chat').innerHTML='';
  document.getElementById('input').value='';
  document.getElementById('input').focus();
}
async function loadHistory(){
  // history loaded from storage on each message
}
async function send(){
  if(sending) return;
  const input=document.getElementById('input');
  const msg=input.value.trim();
  if(!msg) return;
  input.value='';
  addMessage('user',msg);
  sending=true;
  document.getElementById('sendBtn').disabled=true;
  document.getElementById('loading').style.display='block';
  try{
    const r=await fetch('/api/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({message:msg,token:token})
    });
    if(r.status===401){window.location.reload();return}
    const d=await r.json();
    if(d.response) addMessage('bsa',d.response);
  }catch(e){
    addMessage('bsa','Error: connection failed. Try again.');
  }
  sending=false;
  document.getElementById('sendBtn').disabled=false;
  document.getElementById('loading').style.display='none';
}
function addMessage(role,text){
  const chat=document.getElementById('chat');
  const div=document.createElement('div');
  div.className='msg '+role;
  const now=new Date();
  const time=now.getHours().toString().padStart(2,'0')+':'+now.getMinutes().toString().padStart(2,'0');
  div.innerHTML='<div class="bubble">'+escapeHtml(text)+'</div><div class="time">'+time+'</div>';
  chat.appendChild(div);
  chat.scrollTop=chat.scrollHeight;
}
function escapeHtml(text){
  return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/```([\\s\\S]*?)```/g,'<pre><code>$1</code></pre>')
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\\*\\*(.+?)\\*\\*/g,'<b>$1</b>')
    .replace(/\\n/g,'<br>');
}
</script></body></html>"""


# ── CLI ──────────────────────────────────────────────────────────────────
def cli():
    import argparse
    parser = argparse.ArgumentParser(description="BSA Web Advisor")
    parser.add_argument("--set-password", action="store_true", help="Set a new password")
    parser.add_argument("--port", type=int, default=0, help="Port to listen on")
    args = parser.parse_args()

    if args.set_password:
        pw = input("New password: ")
        pw2 = input("Confirm: ")
        if pw != pw2:
            print("Passwords don't match")
            sys.exit(1)
        if len(pw) < 4:
            print("Password too short (min 4 chars)")
            sys.exit(1)
        set_password(pw)
        print("Password updated.")
        return

    cfg = load_config()
    if not cfg.get("password_hash"):
        pw = secrets.token_hex(8)
        set_password(pw)
        print(f"╔══════════════════════════════════════╗")
        print(f"║  PASSWORD: {pw}            ║")
        print(f"║  Save this! You'll need it to login. ║")
        print(f"╚══════════════════════════════════════╝")

    port = args.port or cfg.get("port", 3000)
    debug = cfg.get("debug", False)
    log(f"BSA Web starting on port {port}")
    print(f"BSA Web: http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)


if __name__ == "__main__":
    cli()

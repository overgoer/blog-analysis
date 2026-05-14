#!/usr/bin/env python3
"""
BSA Agent — Business Strategy Audit (еженедельный стратегический аудит).

Режимы:
  python3 bsa_agent.py                          # еженедельный аудит
  python3 bsa_agent.py --feedback <msg_id> --body-file <path> [--in-reply-to <id>]
  python3 bsa_agent.py --auto-finalize           # принудительная финализация
  python3 bsa_agent.py --dry-run                 # тест без API/сохранения/email

Генерирует State of Business + 3-5 Strategic Bets,
отправляет на почту, поддерживает диалог до 3 раундов.
Последнее слово всегда за Эдди.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent
ORCH_DIR = BASE.parent / "orchestrator"
AGENTS_DIR = BASE.parent
LOG_FILE = Path("/root/blog-analysis/logs/bsa.log")
VAULT_DIR = Path("/root/obsidian/notes/eddytester/Стратегия")
THREAD_FILE = BASE / "bsa_thread.json"
LOCK_FILE = BASE / ".bsa.lock"

os.makedirs(VAULT_DIR, exist_ok=True)
os.makedirs(LOG_FILE.parent, exist_ok=True)

# ── Logging ─────────────────────────────────────────────────────────────


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ── Lock ────────────────────────────────────────────────────────────────


def acquire_lock():
    if LOCK_FILE.exists():
        mtime = os.path.getmtime(LOCK_FILE)
        age = datetime.now().timestamp() - mtime
        if age < 3600:
            log("Lock file exists (< 1h). Another BSA may be running. Exiting.")
            return False
        log(f"Lock file stale ({age/3600:.1f}h). Removing.")
        LOCK_FILE.unlink()
    LOCK_FILE.touch()
    return True


def release_lock():
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()


# ── Key Loading ─────────────────────────────────────────────────────────


def load_deepseek_key():
    """Load DeepSeek API key from Bitwarden or .env."""
    try:
        sys.path.insert(0, str(ORCH_DIR))
        from bw_helper import BWVault
        vault = BWVault()
        key = vault.get_password("DeepSeek API Key")
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


def load_mail_cfg():
    """Load mail config (Resend key)."""
    cfg_file = AGENTS_DIR / ".mailcfg"
    if cfg_file.exists():
        with open(cfg_file) as f:
            return json.load(f)
    return {}


# ── DeepSeek Call ────────────────────────────────────────────────────────


def call_deepseek(system_prompt, user_prompt, temperature=0.5, max_tokens=4096):
    """Call DeepSeek API and return response text."""
    key = load_deepseek_key()
    if not key:
        log("ERROR: No DeepSeek API key available")
        return None

    payload = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    })

    try:
        r = subprocess.run(
            ["curl", "-s", "https://api.deepseek.com/chat/completions",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, text=True, timeout=120,
        )
        resp = json.loads(r.stdout)
        return resp["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"DeepSeek call failed: {e}")
        return None


# ── Context Loading ─────────────────────────────────────────────────────


def load_json(path):
    """Load and return JSON from a file, or default on error."""
    if not os.path.exists(path):
        log(f"  (file not found: {path})")
        return {} if path.endswith(".json") else []
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        log(f"  (error reading {path}: {e})")
        return {} if path.endswith(".json") else []


def load_git_logs(repos):
    """Fetch git logs (last 14 days) for each repo in the list."""
    result = {}
    for repo in repos:
        path = repo.get("path", "")
        name = repo.get("name", "?")
        if not path or not os.path.isdir(path):
            result[name] = "(no local path)"
            continue
        try:
            r = subprocess.run(
                ["git", "log", "--since=14 days ago", "--oneline", "--no-decorate"],
                capture_output=True, text=True, timeout=30, cwd=path,
            )
            output = r.stdout.strip()
            result[name] = output if output else "(no commits in 14 days)"
        except Exception as e:
            result[name] = f"(error: {e})"
    return result


def collect_context():
    """Collect all business context for the audit."""
    log("Collecting business context...")

    pm_ctx = load_json(ORCH_DIR / "pm_context.json")
    wishlist = load_json(ORCH_DIR / "wishlist.json")
    pm_history = load_json(ORCH_DIR / "pm_history.json")
    topics_file = AGENTS_DIR / "researcher" / "topics.json"
    topics = load_json(topics_file)

    repos = pm_ctx.get("repositories", [])
    git_logs = load_git_logs(repos)

    log(f"  pm_context.json: loaded")
    log(f"  wishlist.json: {len(wishlist) if isinstance(wishlist, list) else '?'} items")
    log(f"  pm_history.json: {len(pm_history) if isinstance(pm_history, list) else '?'} entries")
    log(f"  topics: {len(topics.get('pool', [])) if isinstance(topics, dict) else '?'} topics")
    log(f"  repos checked: {len(repos)}")

    return pm_ctx, wishlist, pm_history, topics, git_logs


# ── Prompt Builder ──────────────────────────────────────────────────────


def build_audit_prompt(pm_ctx, wishlist, pm_history, topics, git_logs):
    """Build system + user prompts for the weekly audit."""
    # ── System prompt ──
    lines = []
    lines.append("You are BSA (Business Strategy Agent) — a strategic auditor for the @eddytester ecosystem.")
    lines.append("")
    lines.append("Your role: analyze the full business state, identify gaps and opportunities,")
    lines.append("and produce 3-5 Strategic Bets for the coming week.")
    lines.append("")
    lines.append("## Core Principles")
    lines.append("- Think like a CEO, not a project manager. Focus on OUTCOMES, not tasks.")
    lines.append("- Every Strategic Bet must tie to: content growth, product monetization, or operational leverage.")
    lines.append("- Be specific and cynical. 'Improve quality' is not a bet — 'Ship free-trial API with Stripe checkout' is.")
    lines.append("- Prioritize bets that unblock other work (foundation first, features second).")
    lines.append("- The audience is juniors doing manual backend testing. Content must serve them.")
    lines.append("- Eddy runs everything solo. Time is the scarcest resource.")
    lines.append("")
    lines.append("## Language")
    lines.append("- Output ALL text in Russian, except for proper names and technical terms (e.g. API, Stripe, YooKassa).")
    lines.append("- Strategic Bet titles can mix Russian and English for clarity, but rationale and impact must be in Russian.")
    lines.append("")

    mission = pm_ctx.get("mission", {})
    lines.append(f"## Mission")
    lines.append(f"{mission.get('tagline', '')}")
    if mission.get("not_about"):
        lines.append(f"NOT about: {', '.join(mission['not_about'])}")
    lines.append("")

    products = pm_ctx.get("products", [])
    lines.append("## Products")
    for p in products:
        name = p.get("name", "?")
        desc = p.get("description", p.get("niche", ""))
        status = p.get("status", "")
        priority = p.get("priority", "")
        funnel = p.get("funnel_status", "")
        gaps = p.get("gaps", [])
        lines.append(f"  - {name}: {desc} [{status}] priority={priority}")
        if gaps:
            lines.append(f"    Gaps: {', '.join(gaps)}")
        if funnel:
            lines.append(f"    Funnel: {funnel}")
    lines.append("")

    servers = pm_ctx.get("servers", [])
    lines.append("## Infrastructure")
    for s in servers:
        name = s.get("name", "?")
        ip = s.get("ip", "?")
        lines.append(f"  - {name} ({ip})")
    lines.append("")

    repos = pm_ctx.get("repositories", [])
    lines.append("## Repositories & Recent Git Activity")
    for r in repos:
        name = r.get("name", "?")
        desc = r.get("description", "")
        status = r.get("status", "")
        lines.append(f"  - {name} [{status}]: {desc}")
        log_line = git_logs.get(name, "")
        if log_line:
            lines.append(f"    Recent: {log_line[:200]}")
    lines.append("")

    criteria = pm_ctx.get("decision_criteria", [])
    lines.append("## Decision Criteria (for evaluating any idea)")
    for c in criteria:
        c_id = c.get("id", "?")
        c_q = c.get("question", "")
        lines.append(f"  - {c_id}: {c_q}")
    lines.append("")

    rejection = pm_ctx.get("rejection_examples", [])
    if rejection:
        lines.append("## Anti-Patterns (what gets rejected)")
        for ex in rejection:
            lines.append(f"  - {ex}")
        lines.append("")

    system_prompt = "\n".join(lines)

    # ── User prompt ──
    user_lines = []
    user_lines.append("Выполни еженедельный стратегический аудит экосистемы @eddytester.")
    user_lines.append("")
    user_lines.append("Проанализируй текущее состояние, активность в git, элементы wishlist и прошлые вердикты PM Agent.")
    user_lines.append("")

    if isinstance(wishlist, list) and wishlist:
        user_lines.append("## Wishlist (ожидающие идеи)")
        for item in wishlist[:20]:
            idea = item.get("idea", "")
            verdict = item.get("verdict", "new")
            status = item.get("status", "")
            user_lines.append(f"  - {idea} [{verdict}] ({status})")
        user_lines.append("")

    if isinstance(pm_history, list) and pm_history:
        recent = pm_history[-10:]
        user_lines.append("## Последние вердикты PM Agent (последние 10)")
        for entry in recent:
            task = entry.get("task", "?")
            verdict = entry.get("verdict", "?")
            date = entry.get("assessed_at", "")[:10]
            user_lines.append(f"  - {date}: {verdict} — {task[:80]}")
        user_lines.append("")

    user_lines.append("## Формат ответа (только JSON, без markdown-обёртки)")
    user_lines.append("""{
  "state_of_business": {
    "summary": "2-3 предложения об общем состоянии",
    "done": ["что сделано за неделю", "..."],
    "gaps": ["критические пробелы", "..."],
    "risks": ["что может пойти не так", "..."],
    "metrics": "ключевые метрики"
  },
  "strategic_bets": [
    {
      "title": "Короткий заголовок действия",
      "rationale": "Почему это важно сейчас (2-3 предложения)",
      "expected_impact": "Что изменится в результате",
      "effort_estimate": "L | M | H (часы/дни)",
      "category": "content | product | operations | growth",
      "success_criteria": "Как поймём, что сработало"
    }
  ],
  "recommendations": ["быстрые победы", "отложенные задачи"]
}""")

    return system_prompt, "\n".join(user_lines)


# ── Parsing ──────────────────────────────────────────────────────────────


def parse_audit_response(raw_text):
    """Parse the JSON response from DeepSeek. Returns dict."""
    if not raw_text:
        return None
    try:
        # Strip markdown code fences if present
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip())
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return json.loads(cleaned)
    except json.JSONDecodeError:
        log(f"Failed to parse DeepSeek response as JSON")
        log(f"Raw (first 500): {raw_text[:500]}")
        return None


# ── Vault ────────────────────────────────────────────────────────────────


def save_audit_to_vault(audit_date, audit_data):
    """Write the audit as markdown into the Obsidian vault."""
    if not audit_data:
        return

    filename = VAULT_DIR / f"BSA_{audit_date}.md"
    bets = audit_data.get("strategic_bets", [])
    state = audit_data.get("state_of_business", {})
    recommendations = audit_data.get("recommendations", [])

    lines = []
    lines.append(f"# BSA — Стратегический аудит #{audit_date}")
    lines.append("")
    lines.append(f"**Сгенерировано:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Статус:** Черновик (ожидает утверждения)")
    lines.append("")

    # State of Business
    summary = state.get("summary", "")
    if summary:
        lines.append("## State of Business")
        lines.append(f"{summary}")
        lines.append("")

    done_list = state.get("done", [])
    if done_list:
        lines.append("### Что сделано")
        for item in done_list:
            lines.append(f"- {item}")
        lines.append("")

    gaps = state.get("gaps", [])
    if gaps:
        lines.append("### Gaps")
        for item in gaps:
            lines.append(f"- {item}")
        lines.append("")

    risks = state.get("risks", [])
    if risks:
        lines.append("### Риски")
        for item in risks:
            lines.append(f"- {item}")
        lines.append("")

    metrics = state.get("metrics", "")
    if metrics:
        lines.append(f"**Метрики:** {metrics}")
        lines.append("")

    # Strategic Bets
    lines.append("---")
    lines.append("")
    lines.append("## Strategic Bets (3-5 на неделю)")
    lines.append("")

    for i, bet in enumerate(bets, 1):
        title = bet.get("title", f"Bet #{i}")
        rationale = bet.get("rationale", "")
        impact = bet.get("expected_impact", "")
        effort = bet.get("effort_estimate", "?")
        category = bet.get("category", "")
        success = bet.get("success_criteria", "")

        lines.append(f"### {i}. {title}")
        lines.append(f"**Категория:** {category} | **Effort:** {effort}")
        if rationale:
            lines.append(f"\n{rationale}")
        if impact:
            lines.append(f"\n**Ожидаемый эффект:** {impact}")
        if success:
            lines.append(f"\n**Критерий успеха:** {success}")
        lines.append("")

    if recommendations:
        lines.append("## Рекомендации")
        for r in recommendations:
            lines.append(f"- {r}")
        lines.append("")

    lines.append("---")
    lines.append("> Последнее слово за Эдди. Ответь на это письмо, чтобы обсудить.")
    lines.append(f"> Автор: BSA Agent ({datetime.now().strftime('%Y-%m-%d %H:%M')})")

    with open(filename, "w") as f:
        f.write("\n".join(lines))
    log(f"Saved to vault: {filename}")

    return filename


def save_final_to_vault(audit_date, audit_data):
    """Rewrite vault file as finalized."""
    filename = VAULT_DIR / f"BSA_{audit_date}.md"
    if not filename.exists():
        return

    content = filename.read_text()
    content = content.replace("**Статус:** Черновик (ожидает утверждения)",
                              "**Статус:** ✅ Утверждено")
    filename.write_text(content)
    log(f"Finalized vault file: {filename}")


# ── Thread State ─────────────────────────────────────────────────────────


def load_thread():
    """Load BSA thread state from JSON file."""
    if not THREAD_FILE.exists():
        return None
    try:
        with open(THREAD_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception):
        return None


def save_thread(state):
    """Save BSA thread state."""
    with open(THREAD_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


# ── Email ────────────────────────────────────────────────────────────────


def send_email(subject, body, cfg=None, in_reply_to=None, references=None):
    """Send email via mailer module. Supports threading headers."""
    try:
        sys.path.insert(0, str(AGENTS_DIR.parent / "lib"))
        from mailer import load_config, send

        if cfg is None:
            cfg = load_config(str(AGENTS_DIR / ".mailcfg"))

        # Build plain text body (strip markdown for email)
        plain = re.sub(r"\*\*(.*?)\*\*", r"\1", body)
        plain = re.sub(r"#{1,6}\s+", "", plain)
        plain = re.sub(r"`([^`]+)`", r"\1", plain)
        plain = re.sub(r"\|.*\|", "", plain)
        plain = re.sub(r"^[-*]\s+", "  \u2022 ", plain, flags=re.MULTILINE)
        plain = re.sub(r"\n{3,}", "\n\n", plain).strip()

        # Send with threading headers via Resend API
        import requests as req

        api_key = cfg.get("resend_api_key")
        if not api_key:
            log("No resend_api_key in config, skipping email")
            return None

        payload = {
            "from": "onboarding@resend.dev",
            "to": [cfg.get("to_addr", "eddy.super1@gmail.com")],
            "subject": subject,
            "text": plain,
        }
        if in_reply_to or references:
            payload["headers"] = {}
            if in_reply_to:
                payload["headers"]["In-Reply-To"] = in_reply_to
            if references:
                payload["headers"]["References"] = references

        try:
            r = req.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=15,
            )
            if r.status_code == 200:
                resp_data = r.json()
                msg_id = resp_data.get("id", "")
                log(f"Email sent: {subject} (id={msg_id})")
                return msg_id
            else:
                log(f"Resend API error {r.status_code}: {r.text[:200]}")
                # Fallback to local save
                archive = Path("/root/blog-analysis/agents/email_archive")
                archive.mkdir(exist_ok=True)
                (archive / f"bsa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt").write_text(
                    f"Subject: {subject}\n\n{plain}")
                return None
        except Exception as e:
            log(f"Email send failed: {e}")
            return None

    except Exception as e:
        log(f"Email module error: {e}")
        return None


# ── Feedback Analysis ────────────────────────────────────────────────────


def build_feedback_prompt(current_bets, feedback_text, pm_ctx):
    """Build prompt for analyzing feedback on strategic bets."""
    bets_text = json.dumps(current_bets, indent=2, ensure_ascii=False)

    lines = []
    lines.append("You are BSA (Business Strategy Agent) analyzing feedback on your strategic bets.")
    lines.append("")
    lines.append("ВАЖНО: Все тексты (feedback_analysis, rationale, expected_impact, message) — на русском языке.")
    lines.append("")
    lines.append("## Current Strategic Bets")
    lines.append(bets_text)
    lines.append("")
    lines.append("## User Feedback")
    lines.append(feedback_text)
    lines.append("")
    lines.append("## Your Task")
    lines.append("1. Determine which bets are accepted, which need changes, which should be rejected.")
    lines.append("2. If the user signals approval (принято, ok, утверждаю, всё верно, good, давай так), set consensus=true.")
    lines.append("3. Otherwise, produce revised versions of the bets based on the feedback.")
    lines.append("")
    lines.append("## Output Format (JSON ONLY)")
    lines.append("""{
  "consensus": false,
  "consensus_signal": null,
  "feedback_analysis": "Краткое описание того, что хочет пользователь (на русском)",
  "strategic_bets": [
    {
      "title": "...",
      "rationale": "...",
      "expected_impact": "...",
      "effort_estimate": "L|M|H",
      "category": "content|product|operations|growth",
      "success_criteria": "...",
      "version": 2,
      "changes": "what changed from previous version"
    }
  ],
  "message": "Your response to the user in first person"
}""")

    return "\n".join(lines)


def detect_consensus(feedback_text):
    """Quick keyword check for consensus signals before calling DeepSeek."""
    text = feedback_text.lower().strip()
    consensus_words = [
        "принято", "утверждаю", "всё верно", "давай так",
        "ok", "good", "согласен", "отлично", "супер",
        "да, так", "все ок", "в порядке",
    ]
    for word in consensus_words:
        if word in text:
            return True
    return False


# ── Main Routines ────────────────────────────────────────────────────────


def run_weekly_audit(dry_run=False):
    """Full weekly audit: collect context → call DeepSeek → save → email."""
    log("=== BSA WEEKLY AUDIT ===")
    audit_date = datetime.now().strftime("%Y-%m-%d")

    pm_ctx, wishlist, pm_history, topics, git_logs = collect_context()
    system_prompt, user_prompt = build_audit_prompt(
        pm_ctx, wishlist, pm_history, topics, git_logs
    )

    if dry_run:
        log("[DRY RUN] Would call DeepSeek with context:")
        log(f"  System prompt: {len(system_prompt)} chars")
        log(f"  User prompt: {len(user_prompt)} chars")
        log(f"  Git logs: {json.dumps({k: len(v) for k, v in git_logs.items()})}")
        return True

    log("Calling DeepSeek for strategic audit...")
    raw = call_deepseek(system_prompt, user_prompt)
    if not raw:
        log("ERROR: DeepSeek returned no response")
        return False

    audit_data = parse_audit_response(raw)
    if not audit_data:
        log("ERROR: Could not parse DeepSeek response")
        return False

    num_bets = len(audit_data.get("strategic_bets", []))
    log(f"Parsed: {num_bets} strategic bets, {audit_data.get('state_of_business', {}).get('summary', 'no summary')[:80]}")

    save_audit_to_vault(audit_date, audit_data)

    # Save thread state
    thread = {
        "status": "awaiting_feedback",
        "audit_date": audit_date,
        "round": 0,
        "max_rounds": 3,
        "current_bets": audit_data.get("strategic_bets", []),
        "state_of_business": audit_data.get("state_of_business", {}),
        "recommendations": audit_data.get("recommendations", []),
        "feedback_history": [],
        "last_message_id": "",
        "finalized": False,
    }
    save_thread(thread)

    # Build email body
    email_body = []
    state = audit_data.get("state_of_business", {})
    email_body.append(f"📊 State of Business")
    email_body.append(f"{state.get('summary', '')}")
    email_body.append("")
    done = state.get("done", [])
    if done:
        email_body.append("✅ Что сделано:")
        for item in done:
            email_body.append(f"  • {item}")
        email_body.append("")
    gaps = state.get("gaps", [])
    if gaps:
        email_body.append("⚠️ Gaps:")
        for item in gaps:
            email_body.append(f"  • {item}")
        email_body.append("")

    email_body.append("🎯 Strategic Bets")
    for i, bet in enumerate(audit_data.get("strategic_bets", []), 1):
        email_body.append(f"\n[{i}] {bet.get('title', '')}")
        email_body.append(f"    Effort: {bet.get('effort_estimate', '?')} | {bet.get('category', '')}")
        email_body.append(f"    {bet.get('rationale', '')[:200]}")
        email_body.append(f"    → {bet.get('expected_impact', '')[:150]}")

    email_body.append("")
    email_body.append("—")
    email_body.append("Ответь на это письмо, чтобы обсудить стратегию.")
    email_body.append("Если всё ок — напиши 'принято'.")

    msg_id = send_email(
        f"[BSA] Стратегический аудит #{audit_date}",
        "\n".join(email_body),
    )
    if msg_id:
        thread["last_message_id"] = msg_id
        save_thread(thread)

    log("=== BSA WEEKLY AUDIT COMPLETE ===")
    return True


def handle_feedback(message_id, body_file, in_reply_to, dry_run=False):
    """Process a feedback email from Eddy and update strategic bets."""
    log(f"=== BSA FEEDBACK ROUND ===")
    log(f"  message_id: {message_id}")
    log(f"  in_reply_to: {in_reply_to}")

    # Read feedback body
    try:
        with open(body_file) as f:
            feedback_text = f.read().strip()
    except Exception as e:
        log(f"ERROR: Cannot read body file: {e}")
        return False

    log(f"  feedback: {feedback_text[:200]}")

    # Load thread state
    thread = load_thread()
    if not thread:
        log("ERROR: No active BSA thread. Run weekly audit first.")
        return False

    if thread.get("finalized"):
        log("Thread already finalized. Ignoring feedback.")
        return False

    if thread.get("round", 0) >= thread.get("max_rounds", 3):
        log(f"Max rounds ({thread.get('max_rounds')}) reached. Run --auto-finalize.")
        return False

    pm_ctx, _, _, _, _ = collect_context()

    # Quick consensus check
    if detect_consensus(feedback_text):
        log("Consensus detected (keyword match). Finalizing.")
        thread["status"] = "finalized"
        thread["finalized"] = True
        thread["feedback_history"].append({
            "round": thread["round"] + 1,
            "message_id": message_id,
            "feedback": feedback_text[:500],
            "timestamp": datetime.now().isoformat(),
        })
        save_thread(thread)
        save_final_to_vault(thread["audit_date"], thread)
        send_email(
            f"Re: [BSA] Стратегический аудит #{thread['audit_date']} — ПРИНЯТО",
            "Стратегия утверждена. Финальная версия сохранена в Obsidian.\n\n"
            "Если потребуется пересмотр — напиши об этом в новом письме.",
        )
        log("=== BSA FEEDBACK COMPLETE (finalized) ===")
        return True

    if dry_run:
        log("[DRY RUN] Would call DeepSeek with feedback analysis")
        return True

    # Build feedback analysis prompt
    prompt = build_feedback_prompt(thread.get("current_bets", []), feedback_text, pm_ctx)

    log("Calling DeepSeek for feedback analysis...")
    raw = call_deepseek(prompt, "Analyze the feedback and update the strategic bets accordingly.", temperature=0.4)
    if not raw:
        log("ERROR: DeepSeek returned no response")
        return False

    result = parse_audit_response(raw)
    if not result:
        log("ERROR: Could not parse feedback response")
        return False

    # Check for consensus from DeepSeek's analysis
    if result.get("consensus"):
        log("DeepSeek detected consensus. Finalizing.")
        thread["status"] = "finalized"
        thread["finalized"] = True
        thread["current_bets"] = result.get("strategic_bets", thread["current_bets"])
    else:
        # Update bets with revised versions
        new_bets = result.get("strategic_bets", [])
        if new_bets:
            thread["current_bets"] = new_bets
        thread["round"] = thread.get("round", 0) + 1
        thread["status"] = "awaiting_feedback"

    # Record feedback
    thread["feedback_history"].append({
        "round": thread.get("round", 1),
        "message_id": message_id,
        "feedback": feedback_text[:500],
        "response_summary": result.get("feedback_analysis", "")[:200],
        "timestamp": datetime.now().isoformat(),
    })

    save_thread(thread)

    # Build response message
    response_lines = []
    if thread.get("finalized"):
        response_lines.append("✅ Стратегия утверждена. Финальная версия:")
        response_lines.append("")
        for i, bet in enumerate(thread["current_bets"], 1):
            response_lines.append(f"{i}. {bet.get('title', '')}")
        response_lines.append("")
        response_lines.append("Сохранено в Obsidian.")
        subject = f"Re: [BSA] Стратегический аудит #{thread['audit_date']} — ПРИНЯТО"
    else:
        msg = result.get("message", "Обновил стратегию с учётом твоего фидбека.")
        response_lines.append(f"Версия {thread['round']} (уточнённая):")
        response_lines.append("")
        for i, bet in enumerate(thread["current_bets"], 1):
            response_lines.append(f"[{i}] {bet.get('title', '')}")
            changes = bet.get("changes", "")
            if changes:
                response_lines.append(f"    Изменения: {changes}")
        response_lines.append("")
        response_lines.append(msg)
        response_lines.append("")
        response_lines.append("Что думаешь? Если всё ок — напиши 'принято'.")
        subject = f"Re: [BSA] Стратегический аудит #{thread['audit_date']} (раунд {thread['round']})"

    send_email(subject, "\n".join(response_lines),
               in_reply_to=in_reply_to or message_id,
               references=in_reply_to or message_id)

    log(f"=== BSA FEEDBACK COMPLETE (round {thread['round']}) ===")
    return True


def auto_finalize(dry_run=False):
    """Auto-finalize thread that's been awaiting feedback for too long."""
    thread = load_thread()
    if not thread:
        log("No active thread to auto-finalize.")
        return False

    if thread.get("finalized"):
        log("Thread already finalized.")
        return False

    if thread.get("status") != "awaiting_feedback":
        log(f"Thread status is '{thread.get('status')}', not awaiting_feedback.")
        return False

    if dry_run:
        log(f"[DRY RUN] Would finalize thread from {thread.get('audit_date')}")
        return True

    thread["status"] = "finalized"
    thread["finalized"] = True
    save_thread(thread)
    save_final_to_vault(thread["audit_date"], thread)

    send_email(
        f"[BSA] Стратегический аудит #{thread['audit_date']} — АВТОМАТИЧЕСКИ УТВЕРЖДЁН",
        "Ответа не последовало в течение 3 дней. Текущая версия стратегии сохранена "
        "как утверждённая.\n\nЧтобы пересмотреть — напиши новое письмо с темой [BSA].",
    )
    log("=== BSA AUTO-FINALIZE COMPLETE ===")
    return True


# ── CLI ──────────────────────────────────────────────────────────────────


def main():
    args = sys.argv[1:]

    if "--dry-run" in args:
        args.remove("--dry-run")
        dry_run = True
    else:
        dry_run = False

    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    # Feedback mode
    if "--feedback" in args and "--body-file" in args:
        fb_idx = args.index("--feedback")
        bf_idx = args.index("--body-file")
        message_id = args[fb_idx + 1] if fb_idx + 1 < len(args) else ""
        body_file = args[bf_idx + 1] if bf_idx + 1 < len(args) else ""
        in_reply_to = ""
        if "--in-reply-to" in args:
            ir_idx = args.index("--in-reply-to")
            in_reply_to = args[ir_idx + 1] if ir_idx + 1 < len(args) else ""

        if not message_id or not body_file:
            log("ERROR: --feedback requires message_id, --body-file requires path")
            sys.exit(1)

        if not acquire_lock():
            sys.exit(0)
        try:
            handle_feedback(message_id, body_file, in_reply_to, dry_run)
        finally:
            release_lock()
        return

    # Auto-finalize mode
    if "--auto-finalize" in args:
        if not acquire_lock():
            sys.exit(0)
        try:
            auto_finalize(dry_run)
        finally:
            release_lock()
        return

    # Default: weekly audit
    if not acquire_lock():
        sys.exit(0)
    try:
        success = run_weekly_audit(dry_run)
        if not success:
            sys.exit(1)
    finally:
        release_lock()


if __name__ == "__main__":
    main()

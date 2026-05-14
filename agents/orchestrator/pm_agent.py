"""
PM Agent — Project Manager / Validator for incoming dev: tasks.

Business-aware gatekeeper: reads pm_context.json, evaluates incoming tasks
against business goals (content, product, audience, operations, cost, stack, maintenance)
and returns a structured GO / NO_GO / NEED_MORE_INFO verdict.

Usage:
  echo "dev: установи grafana на сервер" | python3 pm_agent.py
  echo "dev: посмотри какие есть аналоги serpapi" | python3 pm_agent.py --classify
  python3 pm_agent.py --classify "dev: добавь JWT auth в v0-test-api"
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from bw_helper import BWVault

BASE = Path(__file__).resolve().parent
CONTEXT_FILE = BASE / "pm_context.json"
HISTORY_FILE = BASE / "pm_history.json"
VAULT_DIR = Path("/root/obsidian-vault/eddytester/PM Agent")

RESEARCH_KEYWORDS = [
    "посмотр", "найд", "исслед", "поищ", "проанализ",
    "изучи", "оцен", "сравн", "разбери",
]
CODE_KEYWORDS = [
    "добав", "установ", "настрой", "создай", "напиш",
    "интегрир", "разверн", "задепло", "сделай", "реализу",
    "исправ", "почин", "обнов", "мигрир",
]

def classify_task(task_text):
    """Classify task as RESEARCH or CODE based on keywords."""
    text_lower = task_text.lower()

    found_research = any(kw in text_lower for kw in RESEARCH_KEYWORDS)
    found_code = any(kw in text_lower for kw in CODE_KEYWORDS)

    # If both match (e.g. "посмотри как установить"), prefer research
    if found_research and not found_code:
        return "RESEARCH"
    if found_code and not found_research:
        return "CODE"
    if found_research and found_code:
        # Ambiguous — check which keyword is closer to start
        min_res = min((text_lower.find(kw) for kw in RESEARCH_KEYWORDS if kw in text_lower), default=999)
        min_code = min((text_lower.find(kw) for kw in CODE_KEYWORDS if kw in text_lower), default=999)
        return "RESEARCH" if min_res < min_code else "CODE"

    # No keywords — could be anything, let the LLM decide
    return "CODE"

# ── Context Loading ──────────────────────────────────────────────────────

def load_context():
    """Load pm_context.json. Returns dict or None."""
    if not CONTEXT_FILE.exists():
        print(f"ERROR: {CONTEXT_FILE} not found")
        return None
    with open(CONTEXT_FILE) as f:
        return json.load(f)

def load_history():
    """Load pm_history.json. Returns list."""
    if not HISTORY_FILE.exists():
        return []
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def save_assessment(assessment):
    """Append assessment to pm_history.json."""
    history = load_history()
    history.append(assessment)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    save_to_vault(assessment)

def save_to_vault(assessment):
    """Write assessment as a markdown file in the Obsidian vault."""
    try:
        VAULT_DIR.mkdir(parents=True, exist_ok=True)
        verdict = assessment.get("verdict", "?")
        ts = assessment.get("assessed_at", "")[:10]
        task_slug = assessment.get("task", "unknown")[:40]
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in f"{ts}_PM_{verdict}_{task_slug}")[:80]
        filename = VAULT_DIR / f"{safe_name}.md"

        lines = [
            f"# PM Agent Verdict: {verdict}\n",
            f"**Date:** {assessment.get('assessed_at', '?')}\n",
            f"**Task:** {assessment.get('task', '?')}\n",
            f"**Classification:** {assessment.get('classified_as', '?')}\n",
            f"**Source:** {assessment.get('source', '?')}\n",
            "\n---\n",
            "## Reasoning\n",
            f"{assessment.get('reasoning', '')}\n",
            "\n---\n",
        ]

        research = assessment.get("research_summary", "")
        if research:
            lines.append("## Research Summary\n")
            lines.append(f"{research}\n")
            lines.append("---\n")

        analysis = assessment.get("fit_analysis", [])
        if analysis:
            lines.append("## Fit Analysis\n")
            for item in analysis:
                c = item.get("criterion", "")
                color = item.get("color", "")
                note = item.get("note", "")
                icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(color, "⚪")
                lines.append(f"- {icon} **{c}**: {note}")
            lines.append("\n---\n")

        nxt = assessment.get("next_step", "")
        if nxt:
            lines.append("## Next Step\n")
            lines.append(f"{nxt}\n")

        with open(filename, "w") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"  [vault write skipped: {e}]")

# ── DeepSeek Call ────────────────────────────────────────────────────────

def load_deepseek_key():
    """Load DeepSeek API key from Bitwarden or .env."""
    vault = BWVault()
    key = vault.get_password("DeepSeek API Key")
    if key:
        return key

    env_file = BASE / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    env_key = os.environ.get("DEEPSEEK_API_KEY")
    if env_key:
        return env_key

    return None

def call_deepseek(system_prompt, user_prompt, temperature=0.3, max_tokens=2048):
    """Call DeepSeek API and return response text."""
    key = load_deepseek_key()
    if not key:
        return json.dumps({
            "verdict": "NEED_MORE_INFO",
            "reasoning": "No DeepSeek API key available",
            "fit_analysis": [],
            "next_step": "Set up DeepSeek API key in Bitwarden or .env"
        })

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
        content = resp["choices"][0]["message"]["content"]
        # Parse the JSON response
        parsed = json.loads(content)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "verdict": "NEED_MORE_INFO",
            "reasoning": f"DeepSeek call failed: {e}",
            "fit_analysis": [],
            "next_step": "Retry or check API connectivity"
        })

# ── System Prompt Builder ────────────────────────────────────────────────

def build_system_prompt(ctx):
    """Build full system prompt from business context."""
    if not ctx:
        return "You are a project manager evaluating incoming tasks."

    servers_text = ""
    servers_list = ctx.get("servers", [])
    for srv in servers_list:
        srv_name = srv.get("name", "?")
        srv_ip = srv.get("ip", "?")
        srv_os = srv.get("os", "unknown")
        srv_services = srv.get("services", {})
        srv_stack = srv.get("stack", {})

        servers_text += f"\n  - {srv_name} ({srv_ip}, {srv_os})"
        docker_list = srv_services.get("docker", [])
        if docker_list:
            servers_text += f"\n    Docker: {', '.join(docker_list)}"
        systemd_list = srv_services.get("systemd", [])
        if systemd_list:
            servers_text += f"\n    Systemd: {', '.join(systemd_list)}"
        cron_list = srv_services.get("cron", [])
        if cron_list:
            servers_text += f"\n    Cron: {', '.join(cron_list)}"

        llm_val = srv_stack.get("llm", "")
        search_val = srv_stack.get("search", "")
        if llm_val or search_val:
            servers_text += f"\n    Stack: LLM={llm_val}, Search={search_val}"

    products_text = ""
    for p in ctx.get("products", []):
        prod_name = p.get("name", "?")
        prod_type = p.get("type", "?")
        prod_desc = p.get("description", p.get("niche", ""))
        prod_priority = p.get("priority", "")
        products_text += f"\n  - {prod_name} ({prod_type}): {prod_desc}"
        if prod_priority:
            products_text += f" [priority: {prod_priority}]"
        gaps_list = p.get("gaps", [])
        if gaps_list:
            products_text += f"\n    Gaps: {', '.join(gaps_list)}"

    repos_text = ""
    for r in ctx.get("repositories", []):
        repo_name = r.get("name", "?")
        repo_desc = r.get("description", "")
        repo_stack = r.get("stack", "")
        repo_status = r.get("status", "")
        repos_text += f"\n  - {repo_name} [{repo_status}] ({repo_stack}): {repo_desc}"

    agents_text = ""
    for a in ctx.get("agents", []):
        agents_text += f"\n  - {a.get('name', '?')}: {a.get('role', '')}"

    criteria_text = ""
    for c in ctx.get("decision_criteria", []):
        c_id = c.get("id", "?")
        c_q = c.get("question", "")
        c_w = c.get("weight", "medium")
        criteria_text += f"\n  {c_id} [{c_w}]: {c_q}"

    rejection_list = ctx.get("rejection_examples", [])

    mission = ctx.get("mission", {})
    tagline = mission.get("tagline", "")
    how_txt = mission.get("how", "")
    not_about_list = mission.get("not_about", [])

    lines = []
    lines.append("You are PM Agent — a project manager and business validator for @eddytester ecosystem.")
    lines.append("")
    lines.append("## Mission")
    lines.append(f"{tagline}")
    lines.append(f"{how_txt}")
    if not_about_list:
        lines.append(f"We do NOT do: {', '.join(not_about_list)}")
    lines.append("")

    lines.append("## Products")
    lines.append(products_text)
    lines.append("")

    lines.append("## Infrastructure (Server)")
    lines.append(servers_text)
    lines.append("")

    lines.append("## Repositories")
    lines.append(repos_text)
    lines.append("")

    lines.append("## Agents")
    lines.append(agents_text)
    lines.append("")

    lines.append("## Decision Criteria (evaluate each)")
    lines.append(criteria_text)
    lines.append("")
    if rejection_list:
        lines.append("## Examples of what gets rejected")
        for ex in rejection_list:
            lines.append(f"- {ex}")
        lines.append("")

    lines.append("## Principles")
    lines.append("- Free/open-source strongly preferred. Paid tools need clear ROI justification.")
    lines.append("- Python and shell are preferred. Node.js acceptable. Java/.NET are NO_GO unless critical.")
    lines.append("- Time budget is limited — Eddy runs everything solo. Every tool adds maintenance cost.")
    lines.append("- Content > Infrastructure. If it doesn't help create content or sell the product, it's low priority.")
    lines.append("- The server is not a playground. Every new service consumes RAM, disk, and attention.")
    lines.append("")

    lines.append("## Response Format")
    lines.append('Respond with JSON only (no markdown wrapper):')
    rf = ctx.get("response_format", {})
    for key, val in rf.items():
        lines.append(f'  "{key}": "{val}"')
    lines.append("")
    lines.append("fit_analysis is an array of objects:")
    lines.append('  [{"criterion": "content_value", "color": "green|yellow|red", "note": "..."}, ...]')
    lines.append("")
    lines.append("IMPORTANT:")
    lines.append("- Be critical. Not every idea needs to be built.")
    lines.append("- If unsure about feasibility or value, use NEED_MORE_INFO.")
    lines.append("- Last word is always Eddy's — this assessment is advisory.")
    lines.append("- Research the idea before judging — don't reject out of hand, but also don't rubber-stamp.")

    return "\n".join(lines)

def assess_task(task_text, source="email"):
    """Full assessment: load context → build prompt → call DeepSeek → save → print."""
    ctx = load_context()
    if not ctx:
        print(json.dumps({"error": "Context not available"}, indent=2))
        return

    system_prompt = build_system_prompt(ctx)

    user_prompt = (
        f"Evaluate this incoming task:\n\n{task_text}\n\n"
        f"Source: {source}\n\n"
        "Provide a structured assessment in JSON format."
    )

    result_json = call_deepseek(system_prompt, user_prompt)

    try:
        assessment = json.loads(result_json)
    except json.JSONDecodeError:
        assessment = {"verdict": "NEED_MORE_INFO", "raw_response": result_json}

    assessment["task"] = task_text
    assessment["source"] = source
    assessment["classified_as"] = classify_task(task_text)
    assessment["assessed_at"] = __import__("datetime").datetime.now().isoformat()

    save_assessment(assessment)
    print(json.dumps(assessment, indent=2, ensure_ascii=False))

def print_assessment(assessment):
    """Pretty-print assessment to console."""
    try:
        if isinstance(assessment, str):
            assessment = json.loads(assessment)
    except json.JSONDecodeError:
        print(assessment)
        return

    verdict = assessment.get("verdict", "?")
    print(f"\n{'='*60}")
    print(f"  PM AGENT VERDICT: {verdict}")
    print(f"{'='*60}")

    task = assessment.get("task", "")
    if task:
        print(f"  Task: {task}")

    classified = assessment.get("classified_as", "")
    if classified:
        print(f"  Classification: {classified}")

    reasoning = assessment.get("reasoning", "")
    if reasoning:
        print(f"\n  Reasoning: {reasoning}")

    research = assessment.get("research_summary", "")
    if research:
        print(f"\n  Research: {research}")

    analysis = assessment.get("fit_analysis", [])
    if analysis:
        print(f"\n  Fit Analysis:")
        for item in analysis:
            criterion = item.get("criterion", "")
            color = item.get("color", "")
            note = item.get("note", "")
            color_sym = {"green": "✓", "yellow": "~", "red": "✗"}.get(color, "?")
            print(f"    {color_sym} {criterion}: {note}")

    effort = assessment.get("estimated_effort", "")
    if effort:
        print(f"\n  Estimated Effort: {effort}")

    nxt = assessment.get("next_step", "")
    if nxt:
        print(f"  Next Step: {nxt}")

    print(f"{'='*60}\n")

def main():
    args = sys.argv[1:]

    do_classify = "--classify" in args
    if do_classify:
        args = [a for a in args if a != "--classify"]

    task_text = None

    if args:
        task_text = " ".join(args)
    elif not sys.stdin.isatty():
        task_text = sys.stdin.read().strip()

    if not task_text:
        print("Usage:")
        print("  echo \"dev: install grafana\" | python3 pm_agent.py")
        print("  echo \"dev: посмотри serpapi\" | python3 pm_agent.py --classify")
        print("  python3 pm_agent.py --classify \"dev: добавь JWT\"")
        sys.exit(1)

    if do_classify:
        classification = classify_task(task_text)
        print(f"Classification: {classification}")
        return

    assess_task(task_text)

if __name__ == "__main__":
    main()

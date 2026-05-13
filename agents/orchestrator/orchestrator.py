#!/usr/bin/env python3
"""
Orchestrator — PraisonAI-powered multi-agent system for @eddytester content.

Phases:
  1. GA picks topic from pool
  2. Researcher researches (calls researcher.py)
  3. GA reviews brief, decides if post-worthy
  3.5 RAW WRITER extracts dense content layer
  4. STYLE ADAPTER adapts posts to channel style
  5. Digest emailed to eddy.super1@gmail.com

Usage:
  python3 orchestrator.py                          # pick topic, research, digest
  python3 orchestrator.py --topic "..."             # force specific topic
  python3 orchestrator.py --email                   # send email (default: console)
  python3 orchestrator.py --no-email                # console only
"""

import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
BASE = Path("/root/blog-analysis/agents")
RESEARCHER_DIR = BASE / "researcher"
ORCHESTRATOR_DIR = BASE / "orchestrator"
TOPICS_FILE = RESEARCHER_DIR / "topics.json"
VENV_PYTHON = BASE / ".venv" / "bin" / "python3"
MAILER = BASE.parent / "lib" / "mailer.py"
GA_PROMPT_FILE = ORCHESTRATOR_DIR / "ga_prompt.txt"
LOG_FILE = Path("/root/blog-analysis/logs/orchestrator.log")

os.makedirs(LOG_FILE.parent, exist_ok=True)

# ── Helpers ──────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_env():
    """Load DeepSeek key from .env."""
    env_file = BASE / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DEEPSEEK_API_KEY", "")


def dk(system, user, temperature=0.7, max_tokens=1024):
    """Call DeepSeek v4 Flash, return response text."""
    import json as _json
    import subprocess as _sp

    key = load_env()
    if not key:
        return "ERROR: No DeepSeek API key"

    payload = _json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    })

    try:
        r = _sp.run(
            ["curl", "-s", "https://api.deepseek.com/chat/completions",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, text=True, timeout=120,
        )
        resp = _json.loads(r.stdout)
        return resp["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"  DeepSeek error: {e}")
        return f"ERROR: {e}"


def load_topics():
    """Load topics.json and return pool."""
    with open(TOPICS_FILE) as f:
        data = json.load(f)
    return data


def save_topics(data):
    """Save updated topics.json."""
    with open(TOPICS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def pick_topic(data):
    """GA picks the best next topic from pool."""
    pool = data.get("pool", [])
    researched = {r["topic"] for r in data.get("researched", [])}
    available = [t for t in pool if t not in researched]

    if not available:
        return None

    if len(available) == 1:
        return available[0]

    # GA picks the best topic for current context
    system = (
        "You are a content strategist for a QA testing channel (@eddytester). "
        "Pick the BEST topic from the list for a post RIGHT NOW.\n\n"
        "Criteria:\n"
        "- Practical value for manual/mid-level API testers\n"
        "- Specific angle (not generic overview)\n"
        "- Audience hasn't seen this angle before\n"
        "- Potential for concrete bugs, curl commands, checklists\n\n"
        "Output ONLY the complete topic text, nothing else."
    )
    user = (
        f"Today: {datetime.now().strftime('%Y-%m-%d')}\n\n"
        f"Available topics:\n" + "\n".join(f"- {t}" for t in available[:10])
    )
    chosen = dk(system, user, temperature=0.3, max_tokens=200)
    chosen = chosen.strip().strip('"').strip("'")

    # Verify chosen topic is in available list
    for t in available:
        if t.lower() == chosen.lower() or t.startswith(chosen[:30]):
            return t

    # Fallback: first available
    log(f"  GA chose '{chosen[:60]}...', but not in pool. Using: {available[0][:60]}...")
    return available[0]


def run_researcher(topic):
    """Run researcher.py on the topic, return path to report."""
    log(f"  Running researcher on: {topic[:60]}...")
    result = subprocess.run(
        [str(VENV_PYTHON), str(RESEARCHER_DIR / "researcher.py"), topic],
        capture_output=True, text=True, timeout=300,
        cwd=str(RESEARCHER_DIR),
    )

    # Find the report file from output
    report_path = None
    for line in result.stdout.splitlines():
        if "Report saved:" in line or "Full report:" in line:
            report_path = line.split(": ", 1)[-1].strip()

    if result.returncode != 0:
        log(f"  Researcher ERROR: {result.stderr[:300]}")
        return None

    if report_path and Path(report_path).exists():
        log(f"  Report generated: {report_path}")
        return report_path

    # Fallback: find latest .md file
    log("  ERR: Report file not found in output, trying fallback...")
    briefs = sorted(RESEARCHER_DIR.glob("research_*.md"), key=os.path.getmtime, reverse=True)
    if briefs:
        return str(briefs[0])
    return None


def ga_review_brief(topic, brief_text):
    """General Analyst reviews the brief and decides if it's post-worthy."""
    ga_prompt = GA_PROMPT_FILE.read_text() if GA_PROMPT_FILE.exists() else ""

    system = textwrap.dedent(f"""\
        {ga_prompt}

        TASK: Review a research brief and decide if the topic is WORTH a post.

        Analyze:
        1. Is the angle specific enough? (not generic overview)
        2. Are there concrete bugs, cases, or commands?
        3. Does it match the channel's voice and audience?
        4. What's the best angle for a post from this material?
        5. Rating: MUST POST / GOOD / WEAK / SKIP

        Output format:
        RATING: [MUST POST | GOOD | WEAK | SKIP]
        VERDICT: 1-2 sentences
        BEST_ANGLE: 1 sentence describing the post angle
        POST_IDEA: 1-sentence title for the post
        WHY: brief justification
    """)

    user = (
        f"Topic: {topic}\n\n"
        f"Research brief:\n{brief_text[:4000]}"
    )
    return dk(system, user, temperature=0.3, max_tokens=1000)

def raw_write_content(topic, brief_text, ga_verdict):
    # Phase 3.5: RAW WRITER - dump all useful material without style constraints
    system = (
        'You are a RAW WRITER for @eddytester. Your ONLY job: extract every useful '
        'fact, bug, case, command, and argument from the research brief.'
        '\n\nRULES:\n'
        '- Write in RUSSIAN\n'
        '- Do NOT worry about style, structure, or readability\n'
        '- Do NOT add intros, conclusions, or transitions\n'
        '- Just dump the material: technical details, curl commands, HTTP quirks, '
        'real bugs, edge cases, quotes from sources, data points, specific numbers\n'
        '- If the brief is thin, say what\'s missing\n'
        '- If you know more context from training data, add it (date it if possible)\n'
        '- Length: as long as it needs to be (no limit)\n\n'
        'Think of this as your notes for the post. Dump everything useful.'
    )
    user = (
        f'Topic: {topic}\n\n'
        f'GA Verdict (key angle): {ga_verdict[:1000]}\n\n'
        f'Research brief:\n{brief_text}'
    )
    return dk(system, user, temperature=0.6, max_tokens=4096)


def style_adapter(topic, raw_content, ga_verdict):
    # Phase 4: STYLE ADAPTER - adapt raw content to channel style (replaces channel_write_post)
    best_angle = ''
    for line in ga_verdict.split('\n'):
        if line.startswith('BEST_ANGLE') or line.startswith('**BEST_ANGLE'):
            best_angle = line.split(':', 1)[-1].strip() if ':' in line else line
            break

    system = (
        'You are STYLE ADAPTER for @eddytester - a QA testing channel.\n'
        'Your job: take RAW content and adapt it to the channel\'s voice.'
        '\n\nCRITICAL RULES:\n'
        '1. NO template headers. NO Situation/Analysis/Verdict/Takeaway/Realy.\n'
        '   The post should read as natural connected text, not a form.\n'
        '2. NO em dashes. Use regular hyphens (-) instead.\n'
        '3. Short paragraphs. 1-3 sentences each. Lots of whitespace.\n'
        '4. Natural flow: start with a hook, unpack technically, end with a takeaway.\n'
        '5. Natural slang: "kejc", "prod", "bag", "zashkvar"\n'
        '6. No emoji abuse (1-2 max)\n'
        '7. ~500-800 chars total (can go to 1200 if BEST_ANGLE has many points)\n'
        '8. Explain key terms INLINE\n'
        '9. When useful: add 1-2 links at end\n'
        '10. Write in RUSSIAN\n'
        '11. NEVER preface the post with any meta-commentary. Start directly.\n'
        '12. GA verdict provides BEST_ANGLE - this MUST be the core.\n'
        '13. CRITICAL: NEVER use em dash (\u2014). Always use regular hyphen (-).\n'
        '14. Replace every em dash with hyphen before output.\n\n'
        'OUTPUT ONLY THE POST. No meta-text, no explanations.'
    )
    user = (
        f'Topic: {topic}\n\n'
        f'BEST_ANGLE: {best_angle}\n\n'
        f'RAW CONTENT (dense material):\n{raw_content}\n\n'
        f'GA Review:\n{ga_verdict}'
    )
    result = dk(system, user, temperature=0.5, max_tokens=2000)
    return result.replace('\u2014', '-')

def channel_write_post(topic, brief_text, ga_verdict):
    """Channel Agent writes a post draft from the brief."""
    # Extract BEST_ANGLE from GA verdict
    best_angle = ""
    for line in ga_verdict.split("\n"):
        if line.startswith("BEST_ANGLE") or line.startswith("**BEST_ANGLE"):
            best_angle = line.split(":", 1)[-1].strip() if ":" in line else line
            break

    system = textwrap.dedent("""\
        You are a Channel Agent for @eddytester — a QA testing channel.
        Your job: Write a post draft based on a research brief.

        CRITICAL: The GA review provides a BEST_ANGLE — a specific angle for the post.
        Your post MUST cover the BEST_ANGLE, NOT just the first thing from the brief.
        If BEST_ANGLE describes a multi-point checklist (e.g., "5 bugs"), write ALL points.

        FORMAT (exact):
        - Situation: 1-2 sentences describing the problem or question
        - Analysis: the technical core — what's happening, why it matters
        - Verdict: bug or not? what should a tester do?
        - Takeaway: 1 rule for the future
        - Реалы: 1-2 honest remarks (this part is critical — adds authenticity)

        STYLE RULES:
        - Short sentences. Mix of punchy and explanatory.
        - Natural slang: "кейс", "прод", "баг", "зашквар"
        - No emoji abuse (1-2 max)
        - No clickbait. No "90% тестировщиков..."
        - ~500-800 chars total. If BEST_ANGLE has multiple points, can go up to 1200.
        - CRITICAL: Assume the reader knows terms exist but not the details.
          Briefly explain key terms INLINE (1-2 words in parentheses or a short clause).
          Example: "ставит `alg:none`" → "ставит `alg:none` (алгоритм без подписи)"
          Example: "измени payload" → "измени payload (тело токена — данные пользователя)"
          Example: "ETag — это хеш контента" → add "хеш (отпечаток данных)"
          The goal: reader nods "ага, понятно" instead of googling mid-post.
        - NOT an encyclopedia. No long theory blocks. Just 1-2 word clarifications inline.
        - When appropriate, add 1-2 USEFUL LINKS for further reading.
          Examples: ссылка на MDN для HTTP-заголовков, Stripe docs для платёжных кейсов,
          RFC/спецификацию для спорных моментов, статью на Habr если есть хорошая.
          Links go at the end of the post: "Полезно: [MDN: ETag](url)"
          ONLY add links when they genuinely add value. Don't force it.
        - Write in RUSSIAN
    """)

    user = (
        f"Topic: {topic}\n\n"
        f"BEST_ANGLE to cover: {best_angle}\n\n"
        f"Research brief:\n{brief_text[:4000]}\n\n"
        f"Full GA review for context:\n{ga_verdict}"
    )
    return dk(system, user, temperature=0.5, max_tokens=2000)


def md_to_html(text):
    """Convert simple markdown to HTML for email."""
    lines = text.splitlines()
    html_parts = []
    in_list = False

    for line in lines:
        if line.startswith("### "):
            if in_list: html_parts.append("</ul>"); in_list = False
            html_parts.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            if in_list: html_parts.append("</ul>"); in_list = False
            html_parts.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            if in_list: html_parts.append("</ul>"); in_list = False
            html_parts.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("- "):
            if not in_list: html_parts.append("<ul>"); in_list = True
            html_parts.append(f"<li>{line[2:]}</li>")
        elif line.startswith("  - "):
            html_parts.append(f"<li style='margin-left:20px;'>{line[4:]}</li>")
        elif line.startswith("---") or line.startswith("\u2500"):
            if in_list: html_parts.append("</ul>"); in_list = False
            html_parts.append("<hr>")
        elif not line.strip():
            if in_list: html_parts.append("</ul>"); in_list = False
            html_parts.append("<br>")
        else:
            if in_list: html_parts.append("</ul>"); in_list = False
            line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
            line = re.sub(r"`(.+?)`", r"<code>\1</code>", line)
            html_parts.append(f"<p>{line}</p>")

    if in_list:
        html_parts.append("</ul>")
    return "\n".join(html_parts)


def format_email_html(topic, ga_review_result, post_draft_old, post_draft_new, brief_path):
    """Build HTML email body with old and new post versions for comparison."""
    ga_html = md_to_html(ga_review_result)
    post_old_html = md_to_html(post_draft_old)
    post_new_html = md_to_html(post_draft_new)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:15px;line-height:1.5;color:#1a1a1a;max-width:600px;margin:0 auto;padding:16px;">
<div style="background:#f8f9fa;border-radius:12px;padding:16px;margin-bottom:16px;">
  <div style="font-size:11px;color:#666;margin-bottom:4px;">\u0414\u0430\u0439\u0434\u0436\u0435\u0441\u0442 \u041e\u0440\u043a\u0435\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430</div>
  <div style="font-size:12px;color:#999;">{datetime.now().strftime('%Y-%m-%d %H:%M')}</div>
</div>

<h1 style="font-size:18px;font-weight:600;margin:0 0 16px 0;">{topic[:80]}</h1>

{ga_html}

<hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0;">

<h2 style="font-size:15px;font-weight:600;margin:12px 0 8px 0;color:#666;">\u0421\u0422\u0410\u0420\u042b\u0419 \u0424\u041e\u0420\u041c\u0410\u0422 (Channel Agent)</h2>
{post_old_html}

<hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0;">

<h2 style="font-size:15px;font-weight:600;margin:12px 0 8px 0;color:#059669;">\u041d\u041e\u0412\u042b\u0419 \u0424\u041e\u0420\u041c\u0410\u0422 (Style Adapter)</h2>
{post_new_html}

<hr style="border:none;border-top:1px solid #e5e7eb;margin:16px 0;">

<div style="background:#f0fdf4;border-radius:8px;padding:12px;font-size:12px;color:#166534;">
  <b>\u041f\u043e\u043b\u043d\u044b\u0439 \u0431\u0440\u0438\u0444:</b> {brief_path.split('/')[-1]}
</div>

<div style="background:#fef3c7;border-radius:8px;padding:12px;margin-top:12px;font-size:12px;color:#92400e;">
  <b>\u041a\u043e\u043c\u0430\u043d\u0434\u044b \u0434\u043b\u044f \u043e\u0442\u0432\u0435\u0442\u0430:</b><br>
  <b>\u0442\u0433 1</b> - \u043f\u043e\u0441\u0442 \u043e\u0434\u043e\u0431\u0440\u0435\u043d, \u043f\u0443\u0431\u043b\u0438\u043a\u0443\u0439<br>
  <b>\u0437\u0430\u0448\u043a\u0432\u0430\u0440: ...</b> - \u0442\u0435\u043c\u0430 \u043d\u0435 \u043d\u0443\u0436\u043d\u0430<br>
  <b>\u0432 \u043f\u0443\u043b: ...</b> - \u0434\u043e\u0431\u0430\u0432\u044c \u0442\u0435\u043c\u0443<br>
  <b>\u0431\u044d\u043a\u043b\u043e\u0433 &lt;\u0438\u0434\u0435\u044f&gt;</b> - \u0434\u043e\u0431\u0430\u0432\u044c \u0438\u0434\u0435\u044e \u0432 \u0431\u044d\u043a\u043b\u043e\u0433
</div>

<div style="text-align:center;font-size:11px;color:#999;margin-top:16px;">
  \u041e\u0440\u043a\u0435\u0441\u0442\u0440\u0430\u0442\u043e\u0440 @eddytester
</div>
</body></html>"""


def format_email_plain(topic, ga_review_result, post_draft_old, post_draft_new, brief_path):
    """Build plain text fallback with both versions."""
    return f"""\u0414\u0430\u0439\u0434\u0436\u0435\u0441\u0442 \u041e\u0440\u043a\u0435\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430
\u0414\u0430\u0442\u0430: {datetime.now().strftime('%Y-%m-%d %H:%M')}

\u0422\u0435\u043c\u0430: {topic}

-- GA Review --
{ga_review_result}

-- \u0421\u0422\u0410\u0420\u042b\u0419 \u0424\u041e\u0420\u041c\u0410\u0422 (Channel Agent) --
{post_draft_old}

-- \u041d\u041e\u0412\u042b\u0419 \u0424\u041e\u0420\u041c\u0410\u0422 (Style Adapter) --
{post_draft_new}

-- \u0411\u0440\u0438\u0444 --
{brief_path.split('/')[-1]}

\u041a\u043e\u043c\u0430\u043d\u0434\u044b:
  "\u0442\u0433 1" - \u043f\u043e\u0441\u0442 \u043e\u0434\u043e\u0431\u0440\u0435\u043d
  "\u0437\u0430\u0448\u043a\u0432\u0430\u0440: ..." - \u0442\u0435\u043c\u0430 \u043d\u0435 \u043d\u0443\u0436\u043d\u0430
  "\u0432 \u043f\u0443\u043b: ..." - \u0434\u043e\u0431\u0430\u0432\u044c \u0442\u0435\u043c\u0443
  "\u0431\u044d\u043a\u043b\u043e\u0433 <\u0438\u0434\u0435\u044f>" - \u0434\u043e\u0431\u0430\u0432\u044c \u0438\u0434\u0435\u044e \u0432 \u0431\u044d\u043a\u043b\u043e\u0433
"""


def send_email(topic, ga_review_result, post_draft_old, post_draft_new, brief_path):
    """Send digest email via mailer with HTML formatting (old + new style)."""
    subject = f"\u0414\u0430\u0439\u0434\u0436\u0435\u0441\u0442 \u041e\u0440\u043a\u0435\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430: {topic[:50]}"
    html = format_email_html(topic, ga_review_result, post_draft_old, post_draft_new, brief_path)
    plain = format_email_plain(topic, ga_review_result, post_draft_old, post_draft_new, brief_path)

    try:
        import sys as _sys
        _sys.path.insert(0, str(BASE.parent / "lib"))
        from mailer import load_config, send
        cfg = load_config(str(BASE / ".mailcfg"))
        send(subject, plain, html=html, cfg=cfg)
        log("Email sent to eddy.super1@gmail.com")
    except Exception as e:
        log(f"  Email failed: {e}, saving locally")
        archive = BASE.parent / "logs" / "email_archive"
        os.makedirs(archive, exist_ok=True)
        (archive / f"digest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html").write_text(html)
        (archive / f"digest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt").write_text(plain)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    send_email_flag = "--no-email" not in sys.argv
    force_topic = None

    if "--topic" in sys.argv:
        idx = sys.argv.index("--topic")
        if idx + 1 < len(sys.argv):
            force_topic = sys.argv[idx + 1]

    log("=" * 50)
    log("ORCHESTRATOR START")
    log("=" * 50)

    # Phase 0: Check email commands
    log("Phase 0: Checking email commands...")
    try:
        sys.path.insert(0, str(BASE / "orchestrator"))
        from orchestrator_cmds import check_mail
        cmds_processed = check_mail()
        if cmds_processed:
            log(f"Processed {len(cmds_processed)} email commands")
    except Exception as e:
        log(f"  Email check skipped: {e}")

    # Phase 1: Pick topic
    log("Phase 1: Picking topic...")
    data = load_topics()
    topic = force_topic or pick_topic(data)
    if not topic:
        log("ERROR: No topics available")
        print("No topics to research. Add topics via email or update topics.json.")
        sys.exit(1)
    log(f"Picked: {topic}")

    # Phase 2: Research
    log("Phase 2: Researching...")
    brief_path = run_researcher(topic)
    if not brief_path:
        log("ERROR: Research failed")
        sys.exit(1)

    brief_text = Path(brief_path).read_text()

    # Phase 3: GA Review
    log("Phase 3: GA reviewing brief...")
    ga_verdict = ga_review_brief(topic, brief_text)
    log(f"GA verdict:\n{ga_verdict[:300]}...")

    # Phase 3.5: RAW WRITER
    log("Phase 3.5: RAW WRITER extracting dense content...")
    raw_content = raw_write_content(topic, brief_text, ga_verdict)

    # Phase 4: STYLE ADAPTER (new pipeline)
    log("Phase 4: STYLE ADAPTER writing post...")
    post_draft_new = style_adapter(topic, raw_content, ga_verdict)

    # Phase 4 (old): Channel Agent for comparison
    log("Phase 4 (old): Channel Agent writing post for comparison...")
    post_draft_old = channel_write_post(topic, brief_text, ga_verdict)

    # Phase 5: Send digest
    log("Phase 5: Sending digest...")
    print(f"\n{'='*60}")
    print(f"  TOPIC: {topic}")
    print(f"{'='*60}")
    print(f"\n── GA Review ──\n{ga_verdict}")
    print(f"\n── Post Draft (old style) ──\n{post_draft_old}")
    print(f"\n── Post Draft (new style) ──\n{post_draft_new}")
    print(f"\n── Brief saved: {brief_path}")

    if send_email_flag:
        send_email(topic, ga_verdict, post_draft_old, post_draft_new, brief_path)

    # Mark topic as researched
    data["researched"].append({"topic": topic, "date": datetime.now().strftime("%Y-%m-%d")})
    save_topics(data)
    log(f"Topic '{topic[:50]}...' marked as researched")

    log("=" * 50)
    log("ORCHESTRATOR COMPLETE")
    log("=" * 50)


if __name__ == "__main__":
    main()

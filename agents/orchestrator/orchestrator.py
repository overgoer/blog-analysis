#!/usr/bin/env python3
"""
Orchestrator — PraisonAI-powered multi-agent system for @eddytester content.

Phases:
  1. GA picks topic from pool
  2. Researcher researches (calls researcher.py)
  3. GA reviews brief, decides if post-worthy
  4. Channel Agent writes post draft
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


def channel_write_post(topic, brief_text, ga_verdict):
    """Channel Agent writes a post draft from the brief."""
    system = textwrap.dedent("""\
        You are a Channel Agent for @eddytester — a QA testing channel.
        Your job: Write a Telegram post draft from a research brief.

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
        - ~500-800 chars total
        - Write in RUSSIAN
    """)

    user = (
        f"Topic: {topic}\n\n"
        f"Research brief:\n{brief_text[:4000]}\n\n"
        f"GA review:\n{ga_verdict}"
    )
    return dk(system, user, temperature=0.5, max_tokens=1500)


def send_email(topic, ga_review_result, post_draft, brief_path):
    """Send digest email via mailer."""
    subject = f"\u0414\u0430\u0439\u0434\u0436\u0435\u0441\u0442 \u041e\u0440\u043a\u0435\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430: {topic[:50]}"

    body = f"""\u0414\u0430\u0439\u0434\u0436\u0435\u0441\u0442 \u041e\u0440\u043a\u0435\u0441\u0442\u0440\u0430\u0442\u043e\u0440\u0430
\u0414\u0430\u0442\u0430: {datetime.now().strftime('%Y-%m-%d %H:%M')}

\u0422\u0435\u043c\u0430: {topic}

\u2500\u2500 GA Review \u2500\u2500
{ga_review_result}

\u2500\u2500 \u041f\u0440\u043e\u0435\u043a\u0442 \u043f\u043e\u0441\u0442\u0430 \u2500\u2500
{post_draft}

\u2500\u2500 \u0411\u0440\u0438\u0444 \u2500\u2500
\u041f\u043e\u043b\u043d\u044b\u0439 \u0431\u0440\u0438\u0444 \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d: {brief_path}

\u041e\u0442\u0432\u0435\u0442\u044c \u043d\u0430 \u044d\u0442\u043e \u043f\u0438\u0441\u044c\u043c\u043e \u043a\u043e\u043c\u0430\u043d\u0434\u0430\u043c\u0438:
  "\u0442\u0433 1" \u2014 \u043f\u043e\u0441\u0442 \u043e\u0434\u043e\u0431\u0440\u0435\u043d, \u043f\u0443\u0431\u043b\u0438\u043a\u0443\u0439
  "\u0437\u0430\u0448\u043a\u0432\u0430\u0440: ..." \u2014 \u0442\u0435\u043c\u0430 \u043d\u0435 \u043d\u0443\u0436\u043d\u0430, \u0434\u043e\u0431\u0430\u0432\u044c \u043f\u0440\u0438\u0447\u0438\u043d\u0443
  "\u0432 \u043f\u0443\u043b: ..." \u2014 \u0434\u043e\u0431\u0430\u0432\u044c \u0442\u0435\u043c\u0443 \u0432 \u043f\u0443\u043b
"""

    try:
        import sys as _sys
        _sys.path.insert(0, str(BASE.parent / "lib"))
        from mailer import load_config, send
        cfg = load_config(str(BASE / ".mailcfg"))
        send(subject, body, cfg=cfg)
        log("Email sent to eddy.super1@gmail.com")
    except Exception as e:
        log(f"  Email failed: {e}, saving locally")
        archive = BASE.parent / "logs" / "email_archive"
        os.makedirs(archive, exist_ok=True)
        (archive / f"digest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt").write_text(
            f"Subject: {subject}\n\n{body}"
        )


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

    # Phase 4: Channel Agent writes post
    log("Phase 4: Channel Agent writing post...")
    post_draft = channel_write_post(topic, brief_text, ga_verdict)

    # Phase 5: Send digest
    log("Phase 5: Sending digest...")
    print(f"\n{'='*60}")
    print(f"  TOPIC: {topic}")
    print(f"{'='*60}")
    print(f"\n── GA Review ──\n{ga_verdict}")
    print(f"\n── Post Draft ──\n{post_draft}")
    print(f"\n── Brief saved: {brief_path}")

    if send_email_flag:
        send_email(topic, ga_verdict, post_draft, brief_path)

    # Mark topic as researched
    data["researched"].append({"topic": topic, "date": datetime.now().strftime("%Y-%m-%d")})
    save_topics(data)
    log(f"Topic '{topic[:50]}...' marked as researched")

    log("=" * 50)
    log("ORCHESTRATOR COMPLETE")
    log("=" * 50)


if __name__ == "__main__":
    main()

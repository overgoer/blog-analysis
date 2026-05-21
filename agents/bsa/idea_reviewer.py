#!/usr/bin/env python3
"""
idea_reviewer.py — ночной обзор идей постов из _IDEAS.md.

Каждую ночь (в nightly.sh) оценивает новые идеи:
- Читает стратегию, календарь
- Спрашивает DeepSeek: стоит ли писать, когда публиковать?
- Пишет вердикт в _IDEAS.md
- Выводит сводку для дайджеста

Запуск: python3 idea_reviewer.py
"""

import json, os, re, subprocess, sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
ORCH_DIR = BASE.parent / "orchestrator"
IDEAS_FILE = Path("/root/obsidian-vault/eddytester/Идеи/_IDEAS.md")
STRAT_FILE = Path("/root/obsidian-vault/eddytester/Стратегия/_СТРАТЕГИЯ.md")
CALENDAR_FILE = Path("/root/obsidian-vault/eddytester/Стратегия/Календарь.md")
LOG_FILE = Path("/root/blog-analysis/logs/idea_reviewer.log")


def log(msg):
    os.makedirs(LOG_FILE.parent, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, file=sys.stderr)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def load_key():
    try:
        sys.path.insert(0, str(ORCH_DIR))
        from bw_helper import BWVault
        key = BWVault().get_password("DeepSeek API Key")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("DEEPSEEK_API_KEY") or ""


def call_deepseek(prompt):
    """Call DeepSeek Flash with a prompt, return text response."""
    key = load_key()
    if not key:
        return "Error: no API key"
    payload = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1024,
    })
    try:
        r = subprocess.run(
            ["curl", "-s", "https://api.deepseek.com/chat/completions",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, text=True, timeout=60,
        )
        resp = json.loads(r.stdout)
        return resp["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"API call failed: {e}")
        return f"Error: {e}"


def parse_ideas(content):
    """Parse _IDEAS.md into list of (date, text, status) entries."""
    entries = []
    current_date = ""
    current_text = ""
    current_status = "новая"
    for line in content.split("\n"):
        m = re.match(r"^##\s+(.+)", line)
        if m:
            if current_text and current_status == "новая":
                entries.append((current_date, current_text.strip(), current_status))
            current_date = m.group(1).strip()
            current_text = ""
            current_status = "новая"
        elif line.strip().startswith("Статус:"):
            current_status = line.split(":", 1)[1].strip()
        else:
            current_text += line + "\n"
    if current_text and current_status == "новая":
        entries.append((current_date, current_text.strip(), current_status))
    return entries


def evaluate_idea(date, text, strategy, calendar):
    """Ask DeepSeek to evaluate a single idea."""
    cal_text = calendar[:1000] if calendar else "(нет календаря)"
    prompt = (
        f"Ты Bizzy. Вот идея поста (предложена {date}):\n\n"
        f"{text}\n\n"
        f"Стратегия:\n{strategy[:2000]}\n\n"
        f"Календарь публикаций:\n{cal_text}\n\n"
        f"Оцени идею в 2-3 предложения:\n"
        f"1. Соответствует ли стратегии? (да/нет)\n"
        f"2. Если да — когда публиковать (какой день, почему)?\n"
        f"3. Если нет — почему не подходит?\n\n"
        f"Формат ответа: ✅/❌ + краткий вердикт (1-2 предложения)"
    )
    verdict = call_deepseek(prompt)
    return verdict[:300]


def write_verdict(content, date, verdict):
    """Append verdict to the matching entry in _IDEAS.md content."""
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == f"## {date}":
            # Find where to insert — after the text, before next ##
            status = "✅ одобрена" if verdict.startswith("✅") else "❌"
            insert_at = i + 1
            while insert_at < len(lines) and not lines[insert_at].startswith("## "):
                insert_at += 1
            # Insert status + verdict before the next entry
            status_line = f"Статус: {status}"
            verdict_line = f"Вердикт: {verdict}"
            lines.insert(insert_at, verdict_line)
            lines.insert(insert_at, status_line)
            break
    return "\n".join(lines)


def main():
    if not IDEAS_FILE.exists():
        log("_IDEAS.md not found, nothing to review")
        print("📝 Идеи постов: нет")
        return

    content = IDEAS_FILE.read_text(encoding="utf-8")
    ideas = parse_ideas(content)
    if not ideas:
        log("No new ideas to review")
        print("📝 Идеи постов: нет новых")
        return

    strategy = STRAT_FILE.read_text(encoding="utf-8") if STRAT_FILE.exists() else ""
    calendar = CALENDAR_FILE.read_text(encoding="utf-8") if CALENDAR_FILE.exists() else ""

    log(f"Reviewing {len(ideas)} new idea(s)")
    results = []
    for date, text, status in ideas:
        log(f"Evaluating idea from {date}: {text[:80]}...")
        verdict = evaluate_idea(date, text, strategy, calendar)
        content = write_verdict(content, date, verdict)
        preview = text.strip().split("\n")[0][:80]
        results.append(f"  - {preview} → {verdict[:60]}...")
        log(f"  Verdict: {verdict[:100]}")

    IDEAS_FILE.write_text(content, encoding="utf-8")
    log(f"Updated _IDEAS.md with {len(ideas)} verdict(s)")

    # Output summary for digest
    print("📝 **Идеи постов:**")
    for r in results:
        print(r)


if __name__ == "__main__":
    main()

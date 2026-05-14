#!/usr/bin/env python3
"""
BSA Mini-Session: Instagram Content Strategy Hypothesis.

BSA receives context about @eddytester + the Instagram hypothesis.
Multi-round: analyze -> challenge -> synthesize.
Saves result to Obsidian.
"""

import json, os, subprocess, sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
ORCH_DIR = BASE.parent / "orchestrator"
AGENTS_DIR = BASE.parent
VAULT_DIR = Path("/root/obsidian-vault/eddytester/Стратегия")
LOG_FILE = Path("/root/blog-analysis/logs/bsa.log")
os.makedirs(VAULT_DIR, exist_ok=True)
os.makedirs(LOG_FILE.parent, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[{ts}] {msg}")

def load_deepseek_key():
    vault_file = ORCH_DIR / "bw_helper.py"
    if vault_file.exists():
        sys.path.insert(0, str(ORCH_DIR))
        try:
            from bw_helper import BWVault
            key = BWVault().get_password("DeepSeek API Key")
            if key: return key
        except: pass
    env_file = AGENTS_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=",1)[1].strip().strip('"').strip("'")
    return os.environ.get("DEEPSEEK_API_KEY")

def call_ds(system, user, temp=0.5, max_tokens=4096, json_mode=False):
    key = load_deepseek_key()
    if not key: return None
    payload = {
        "model": "deepseek-v4-flash",
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temp, "max_tokens": max_tokens,
    }
    if json_mode: payload["response_format"] = {"type": "json_object"}
    r = subprocess.run(
        ["curl", "-s", "https://api.deepseek.com/chat/completions",
         "-H", f"Authorization: Bearer {key}",
         "-H", "Content-Type: application/json", "-d", json.dumps(payload)],
        capture_output=True, text=True, timeout=120)
    return json.loads(r.stdout)["choices"][0]["message"]["content"]

def load_context():
    ctx = {"business": "", "posts": "", "bets": ""}
    pm_file = ORCH_DIR / "pm_context.json"
    if pm_file.exists():
        ctx["business"] = json.loads(pm_file.read_text())
    content_map = Path("/root/blog-analysis/data/content_map_index.json")
    if content_map.exists():
        posts = json.loads(content_map.read_text())
        ctx["posts"] = [{"title": p["title"], "angle": p.get("angle",""), "tags": p.get("tags",[]), "summary": p.get("summary","")} for p in posts[-10:]]
    bsa_thread = BASE / "bsa_thread.json"
    if bsa_thread.exists():
        data = json.loads(bsa_thread.read_text())
        ctx["bets"] = data.get("strategic_bets", [])
    return ctx

log("=== BSA Mini-Session: Instagram Strategy ===")
ctx = load_context()

system_prompt = f"""You are BSA (Business Strategy Advisor) for @eddytester — a QA/backend testing Telegram channel (1500+ subs) by Eddy, an experienced QA engineer.

YOUR PERSONALITY:
- Strategic thinker who challenges assumptions
- You doubt everything, especially Eddy's own hypotheses
- You think in bets, not certainties
- You balance product goals (API Practicum sales) with content quality
- You understand the audience deeply: junior manual QA, aspiring testers

BUSINESS CONTEXT:
- Product: API Practicum (REST API simulator v1=bugs, v2=fixed)
- Funnel: TG channel -> TG bot -> purchase
- Audience: juniors who lack confidence, want practical backend testing skills
- Current content: deep technical posts about API testing, bugs, tools

CURRENT STRATEGIC BETS (from last audit):
{json.dumps(ctx.get("bets", []), indent=2, ensure_ascii=False)[:2000]}

RECENT POSTS:
{json.dumps(ctx.get("posts", []), indent=2, ensure_ascii=False)[:2000]}

YOUR TASK: Analyze Eddy's Instagram hypothesis, challenge it, form your own opinion."""

hypothesis = """Eddy's hypothesis about Instagram content for @eddytester:

CORE IDEA: Make Instagram content SIMPLER and LIGHTER than Telegram content.
- Telegram = deep technical dives (specific bugs, curl commands, architecture)
- Instagram = hooks, clear thoughts, simpler format
- Still about testing/QA, but not the same as Telegram
- Target audience: junior QA + people wanting to get into IT via testing

CONTEXT FROM RESEARCH (already done):
- Instagram algorithm 2026 punishes static slideshows
- 70% Reels (15sec bug -> fix -> emotion) + 30% Carousels (checklists)
- Retention > 70% in first 3 sec is critical
- Conversion funnel: IG -> TG -> API Practicum
- B2B EdTech in IG = niche, slow growth

YOUR JOB:
1. First pass: Analyze the hypothesis. What's strong? What's weak? What's missing?
2. Second pass: Challenge your own analysis. Find the counterarguments.
3. Third pass: Synthesize a final recommendation with concrete Strategic Bets.

Be critical. Don't just agree. Think like a business strategist."""

log("Round 1: Initial analysis...")
r1 = call_ds(system_prompt, f"FIRST PASS — Analyze this hypothesis critically:\n\n{hypothesis}", temp=0.5, max_tokens=4096)

if r1:
    log("Round 2: Challenging...")
    r2 = call_ds(system_prompt,
        f"SECOND PASS — Challenge and critique your own analysis below. Find the flaws, blind spots, and counterarguments. Be brutal.\n\nYOUR FIRST ANALYSIS:\n{r1}",
        temp=0.7, max_tokens=4096)

    if r2:
        log("Round 3: Synthesis...")
        r3 = call_ds(system_prompt,
            f"THIRD PASS — Synthesize everything into a final recommendation. Include concrete Strategic Bets (3-5) for how @eddytester should approach Instagram.\n\nFIRST ANALYSIS:\n{r1}\n\nCOUNTERARGUMENTS / CHALLENGES:\n{r2}\n\nOutput format: start with a clear verdict on Eddy's hypothesis (AGREE/PARTIALLY AGREE/DISAGREE + why), then list 3-5 Strategic Bets with: Bet name, Rationale, Success metric, Risk.",
            temp=0.5, max_tokens=4096)

date_str = datetime.now().strftime("%Y-%m-%d")
doc = f"""---
created: {date_str}
tags: bsa, instagram, strategy, content
---

# BSA Mini-Session: Instagram Content Strategy

> Business Strategy Advisor — анализ гипотезы контента для Instagram.
> Дата: {date_str}

---

## Контекст

Эдди хочет адаптировать контент @eddytester для Instagram:
- Telegram: глубокие технические разборы
- Instagram: проще, легче, но про тестирование
- Аудитория: начинающие QA + желающие войти в IT

## Round 1: Анализ гипотезы

{r1 if r1 else '(API error)'}

---

## Round 2: Критика и вызовы

{r2 if r2 else '(API error)'}

---

## Round 3: Синтез и Strategic Bets

{r3 if r3 else '(API error)'}

---

## Резюме

*BSA Mini-Session. Метод: hypothesis → challenge → synthesize. 3 раунда.*
"""

out = VAULT_DIR / f"BSA Instagram Strategy {date_str}.md"
out.write_text(doc)
log(f"Saved to: {out}")
print(f"\n\n=== RESULT SAVED TO: {out} ===")

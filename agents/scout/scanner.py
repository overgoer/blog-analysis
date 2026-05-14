#!/usr/bin/env python3
"""SCOUT Agent — Nightly Competitor Monitor.
NOTE: tdl export does not provide views/forwards. Analysis is category-based.
"""

import json
import subprocess
import os
import re
import sys
from datetime import datetime, timezone
from collections import Counter

BASE_DIR = "/root/blog-analysis"
DATA_DIR = os.path.join(BASE_DIR, "data")
SCOUT_DIR = os.path.join(BASE_DIR, "agents", "scout")
COMPETITORS_FILE = os.path.join(SCOUT_DIR, "competitors.json")
EDDYTESTER_FILE = os.path.join(DATA_DIR, "eddytester_raw.json")
OUT_DIR = os.path.join(SCOUT_DIR, "reports")
RAW_DIR = os.path.join(SCOUT_DIR, "raw")

# Obsidian vault for sync to Mac
OBSIDIAN_DIR = "/root/obsidian-vault/eddytester"
SCOUT_OBSIDIAN_DIR = os.path.join(OBSIDIAN_DIR, "Стратегия", "Конкуренты")
SCOUT_HUB_FILE = os.path.join(OBSIDIAN_DIR, "Стратегия", "SCOUT.md")

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(RAW_DIR, exist_ok=True)

TDL = "/usr/local/bin/tdl"
TDL_TIMEOUT = 90


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_competitors():
    with open(COMPETITORS_FILE) as f:
        return json.load(f)


def load_eddytester_posts():
    """Load all eddytester messages for gap analysis."""
    if not os.path.exists(EDDYTESTER_FILE):
        log(f"WARN: eddytester data not found at {EDDYTESTER_FILE}")
        return []
    with open(EDDYTESTER_FILE) as f:
        data = json.load(f)
    messages = data.get("messages", []) if isinstance(data, dict) else data
    log(f"Loaded {len(messages)} eddytester posts total for gap analysis")
    return messages


def run_tdl_export(channel_id, count=15):
    """Export posts from a channel using tdl. Returns path to output file."""
    out_file = os.path.join(RAW_DIR, f"{channel_id}.json")
    cmd = [
        TDL, "chat", "export",
        "--type", "last",
        "--with-content",
        "-c", channel_id,
        "-i", str(count),
        "-o", out_file,
        "--pool", "1",
        "--delay", "200ms"
    ]
    log(f"  tdl export -c {channel_id} -j {count}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TDL_TIMEOUT)
        if r.returncode != 0:
            log(f"  WARN: tdl exit code {r.returncode}: {r.stderr[200]}")
            return None
        if os.path.exists(out_file) and os.path.getsize(out_file) > 10:
            return out_file
        log(f"  WARN: output empty or missing")
        return None
    except subprocess.TimeoutExpired:
        log(f"  ERROR: tdl timed out after {TDL_TIMEOUT}s")
        return None
    except Exception as e:
        log(f"  ERROR: {e}")
        return None


def load_tdl_output(filepath):
    """Load and parse tdl JSON export (format: {id, messages: [...]})."""
    if not filepath or not os.path.exists(filepath):
        return []
    try:
        with open(filepath) as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("messages", [])
        return []
    except json.JSONDecodeError as e:
        log(f"  ERROR parsing {filepath}: {e}")
        return []


def extract_text(post):
    """Extract clean text from a tdl post."""
    text = post.get("text", "")
    if isinstance(text, list):
        parts = []
        for item in text:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", ""))
        text = " ".join(parts)
    return (text or "").strip()


def categorize_post(text):
    """Categorize a post by content keywords."""
    text_lower = text.lower()
    categories = {
        "AI/LLM": ["ai", "gpt", "chatgpt", "claude", "openai", "llm", "нейросхт", "ai assistant",
                    "copilot", "midjourney", "prompt", "grok", "deepseek", "gemini"],
        "career": ["собесед", "резюме", "ваканс", "зарплат", "оффер", "карьер", "грейд",
                    "джу", "мидл", "синьор", "лид", "найм", "увол", "повышен"],
        "automation": ["автотест", "selenium", "playwright", "cypress", "pytest", "testng",
                        "junit", "allure", "framework", "page object", "ci/cd", "jenkins"],
        "API": ["api", "rest", "graphql", "grpc", "postman", "soap", "endpoint", "swagger",
                "http", "запрос", "response"],
        "guide": ["гайд", "шпаргалк", "инструкц", "туториал", "совет", "лайфхак", "книг",
                   "курс", "урок", "пример", "шаблон", "чеклист"],
        "bugs": ["баг", "баги", "багом", "багов", "ошибк", "дефект", "bug", "bug report",
                  "багрепорт", "регресс"],
        "education": ["курс", "обучен", "школ", "лекц", "вебинар", "мастер-класс",
                       "тренинг", "ментор"],
        "meme": ["мем", "meme", "шутк", "прикол", "юмор", "смешн"],
        "news": ["новост", "вышл", "запустил", "релиз", "анонс", "обновлен", "выпустил",
                  "news", "announce"],
        "engagement": ["опрос", "вопрос", "что думае", "а у тебя", "как у вас", "делис",
                        "голосова", "тест", "quiz", "что выберешь"],
        "practicum/portfolio": ["пактикуф", "практик", "pet project", "пет", "проект",
                                 "portfolio", "портфолио", "стажировк", "стажи"],
    }
    scores = {}
    for cat, keywords in categories.items():
        score = 0
        for kw in keywords:
            count = text_lower.count(kw)
            if count > 0:
                score += count
        if score > 0:
            scores[cat] = score
    if not scores:
        return "other"
    return max(scores, key=scores.get)


def analyze_competitor(posts, channel_info):
    """Analyze a single competitor's posts (category-based only, tdl has no views)."""
    total = len(posts)
    if total == 0:
        return {"total": 0, "error": "no posts"}

    texts = [extract_text(p) for p in posts]
    non_empty = [t for t in texts if t]

    categories = Counter()
    for t in non_empty:
        categories[categorize_post(t)] += 1

    # Note: tdl export does not include views or forwards
    cat_pct = {}
    for cat, count in categories.most_common():
        cat_pct[cat] = {"count": count, "pct": round(count / len(non_empty) * 100, 1) if non_empty else 0}

    # Use post text length and file presence as simple engagement proxy
    posts_with_file = [p for p in posts if p.get("file")]
    file_ratio = round(len(posts_with_file) / total * 100, 1) if total else 0

    return {
        "total": total,
        "non_empty": len(non_empty),
        "categories": cat_pct,
        "file_ratio": file_ratio
    }


def find_gaps(eddytester_posts, competitor_results):
    """Identify content gaps — what competitors post about that eddytester doesn't."""
    eddy_texts = [extract_text(p) for p in eddytester_posts]
    eddy_cats = Counter()
    for t in eddy_texts:
        eddy_cats[categorize_post(t)] += 1
    total_eddy = len([t for t in eddy_texts if t]) or 1

    # Aggregate competitor categories
    comp_cats = Counter()
    for ch, result in competitor_results.items():
        if "categories" in result:
            for cat, info in result["categories"].items():
                comp_cats[cat] += info["count"]

    # Find categories where competitors post more
    gaps = []
    all_cats = set(list(eddy_cats.keys()) + list(comp_cats.keys()))
    for cat in all_cats:
        eddy_pct = round(eddy_cats.get(cat, 0) / total_eddy * 100, 1)
        comp_pct = 0
        for ch, result in competitor_results.items():
            if "categories" in result and cat in result["categories"]:
                comp_pct += result["categories"][cat]["pct"]
        if len(competitor_results) > 0:
            comp_pct = round(comp_pct / len(competitor_results), 1)

        if comp_pct > eddy_pct + 5:
            gaps.append({
                "category": cat,
                "eddy_pct": eddy_pct,
                "competitor_avg_pct": comp_pct,
                "gap": round(comp_pct - eddy_pct, 1)
            })

    gaps.sort(key=lambda x: x["gap"], reverse=True)
    return gaps


def get_keywords_for_category(cat):
    """Return example keywords for a category (for recommendations)."""
    kw_map = {
        "AI/LLM": "AI- тестирования, нейросети",
        "career": "инструменты для тестирования",
        "automation": "Selenium, Playwright, автотесты",
        "API": "Postman, REST API, Swagger",
        "guide": "гайды, чеклисты, шпаргалки",
        "bugs": "багим буг report и ошибки",
        "education": "курсы, вебинары, мастеаты",
        "engagement": "опросы, викторины, вопросл подписки",
        "news": "новости индустрии, релизы",
        "practicum/portfolio": "pet-projects, портфолио, практикум"
    }
    return kw_map.get(cat, cat)



def get_gap_topic_words(competitor_results, gap_category):
    """Extract actual topic keywords from competitor posts in a gap category."""
    from collections import Counter
    all_words = Counter()
    stop_words = {"что", "как", "для", "это", "не", "на", "с", "в", "по", "и",
                   "да", "нет", "уже", "еще", "бы", "от", "о", "к", "а", "из",
                   "или", "то", "но", "так", "все", "если", "чтобы", "можно",
                   "будет", "когда", "даже", "где", "надо", "нужно", "очень",
                   "просто", "работе", "работа", "делать", "себя", "свои",
                   "время", "после", "перед", "тебя", "меня", "который", "только", "больше", "потому", "сегодня", "можно", "будет", "когда", "очень", "просто", "тоже", "этот", "свои", "такие", "значит", "самое", "inside", "often", "great", "first", "check", "need", "might", "best", "good", "well", "much", "many", "some", "also", "really", "quite", "still", "even", "always"}
    for ch_id, result in competitor_results.items():
        if "error" in result:
            continue
        raw_file = os.path.join(RAW_DIR, ch_id + ".json")
        if not os.path.exists(raw_file):
            continue
        try:
            with open(raw_file) as f:
                data = json.load(f)
            msgs = data.get("messages", []) if isinstance(data, dict) else data
        except Exception:
            continue
        for m in msgs:
            t = m.get("text", "")
            if isinstance(t, list):
                t = " ".join(x if isinstance(x, str) else x.get("text", "") for x in t)
            t = t.strip()
            if not t:
                continue
            if categorize_post(t) == gap_category:
                for w in t.lower().split():
                    w = w.strip(".,!?()[]{}:;\"\'-#@*/")
                    if len(w) > 4 and w not in stop_words and not w.startswith("http") and not w.startswith("@"):
                        all_words[w] += 1
    return [w for w, c in all_words.most_common(10) if c >= 2][:5]


def generate_report(competitor_results, gaps, date_str):
    """Generate markdown report."""
    lines = []
    lines.append(f"# SCOUT Report | {date_str}")
    lines.append("")
    lines.append("## Competitor Activity Overview")
    lines.append("")
    lines.append("| Channel | Posts | Top Categories |")
    lines.append("|---------|-------|-----------------|")

    for ch, r in sorted(competitor_results.items(), key=lambda x: x[1].get("total", 0), reverse=True):
        if "error" in r:
            continue
        top_cats = list(r.get("categories", {}).keys())[:3]
        top_str = ", ".join(top_cats) if top_cats else "N/A"
        lines.append(f"| {ch} | {r['total']} | {top_str} |")

    lines.append("")
    lines.append("> Note: tdl export does not provide view/forward counts. Analysis is category-based.")
    lines.append("")

    lines.append("## Category Distribution per Channel")
    lines.append("")
    for ch, r in sorted(competitor_results.items(), key=lambda x: x[1].get("total", 0), reverse=True):
        if "error" in r:
            lines.append(f"### {ch}")
            lines.append(f"Error: {r['error']}")
            lines.append("")
            continue
        lines.append(f"### {ch}")
        lines.append(f"Total posts: {r['total']} | Images: {r.get('file_ratio', 0)}%")
        lines.append("")
        lines.append("| Category | Count | % |")
        lines.append("|----------|-------|---|")
        for cat, info in r.get("categories", {}).items():
            lines.append(f"| {cat} | {info['count']} | {info['pct']}% |")
        lines.append("")

    lines.append("## Content Gaps (vs eddytester)")
    lines.append("")
    if not gaps:
        lines.append("No significant content gaps detected.")
    else:
        lines.append("| Category | eddytester % | Competitor avg % | Gap |")
        lines.append("|----------|-------------|-----------------|-----|")
        for g in gaps:
            lines.append(f"| {g['category']} | {g['eddy_pct']}% | {g['competitor_avg_pct']}% | +{g['gap']}% |")
        lines.append("")

    lines.append("### Recommendations")
    lines.append("")
    for g in gaps[:5]:
        topic_words = get_gap_topic_words(competitor_results, g["category"])
        if topic_words:
            lines.append(f"- **{g['category']}** (gap +{g['gap']}%) -- "
                         f"У конкурентов в этой теме: {', '.join(topic_words)}")
        else:
            lines.append(f"- **{g['category']}** (gap +{g['gap']}%) -- "
                         f"Обрати внимание на эту категорию")
    if not gaps:
        lines.append("- Content mix is well-aligned with competitors.")

    lines.append("")
    lines.append("---")
    lines.append(f"*Report generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    return "\n".join(lines)



REPORT_COUNTER_FILE = os.path.join(SCOUT_DIR, "report_counter.txt")


def generate_format_suggestions():
    """Generate content format suggestions to test on audience (every ~3 reports)."""
    return [
        "1. 🆬 **Short Video / Reels** — 30-60s bug-hunt breakdown (\"How I found a bug in auth in 2 min\")",
        "2. 📊 **Comparison Tables** — Postman vs Insomnia, SQLite vs PostgreSQL for testing",
        "3. 🧪 **Weekly Test Challenge** — \"Find the bug in this API\" with breakdown next post",
        "4. 📋 **Cheat Sheets** — HTTP codes, SQL JOIN types, Git commands as card format",
        "5. 🔍 **Real Case Study** — How a feature was tested end-to-end (with screenshots)",
        "6. 🎯 **Audience Polls** — \"Which DB is hardest to test?\" — engages + gives content ideas",
        "7. 🎚 **Monthly Resource Digest** — Collection of useful QA articles/tools",
    ]


def should_suggest_formats():
    """Check if it's time for format suggestions (every 3rd run)."""
    count = 0
    if os.path.exists(REPORT_COUNTER_FILE):
        try:
            with open(REPORT_COUNTER_FILE) as f:
                count = int(f.read().strip() or "0")
        except ValueError:
            count = 0
    count += 1
    with open(REPORT_COUNTER_FILE, "w") as f:
        f.write(str(count))
    return count & 3 == 0

def main():
    date_str = datetime.now().strftime("%Y-%m-%d")

    log("=== SCOUT Agent Start ===")

    # Load config
    competitors = load_competitors()
    all_channels = []
    for group in ["primary", "extended"]:
        for ch in competitors.get(group, []):
            all_channels.append((ch["id"], ch.get("name", ch["id"]), group))

    log(f"Competitors configured: {len(all_channels)} channels")

    # Load eddytester data for gap analysis (all posts)
    eddy_posts = load_eddytester_posts()

    # Fetch and analyze each competitor
    competitor_results = {}
    for ch_id, ch_name, group in all_channels:
        log(f"Fetching: {ch_id} ({ch_name}) [{group}]")
        out_file = run_tdl_export(ch_id, count=15)
        posts = load_tdl_output(out_file)
        log(f"  Got {len(posts)} posts")
        if posts:
            result = analyze_competitor(posts, {"id": ch_id, "name": ch_name})
            competitor_results[ch_id] = result
            top = list(result.get("categories", {}).keys())[:3]
            log(f"  Top cats: {top}")
        else:
            competitor_results[ch_id] = {"total": 0, "error": "no_data"}
            log(f"  No data")

    # Gap analysis
    log("Finding content gaps...")
    gaps = find_gaps(eddy_posts, competitor_results)
    log(f"Found {len(gaps)} content gaps")

    # Generate report
    report = generate_report(competitor_results, gaps, date_str)

    report_file = os.path.join(OUT_DIR, f"report_{date_str}.md")
    latest_file = os.path.join(OUT_DIR, "latest_report.md")
    with open(report_file, "w") as f:
        f.write(report)
    with open(latest_file, "w") as f:
        f.write(report)

    log(f"Report: {report_file}")

    # Add format suggestions every ~3 reports
    if should_suggest_formats():
        formats = generate_format_suggestions()
        report += "\n## New Format Suggestions\n\n"
        report += "Try these content formats on your audience (biweekly suggestion):\n\n"
        for f in formats:
            report += f + "\n"
        report += "\n---\n"
        with open(report_file, "w") as rf:
            rf.write(report)
        with open(latest_file, "w") as lf:
            lf.write(report)
        log("Format suggestions added to report")

    # Write to Obsidian vault for sync to Mac
    write_obsidian_report(report, gaps, date_str, competitor_results)

    # Save summary JSON
    summary = {
        "date": date_str,
        "channels_analyzed": len(competitor_results),
        "competitor_results": {k: {
            "total": v.get("total"),
            "categories": list(v.get("categories", {}).keys()),
            "error": v.get("error")
        } for k, v in competitor_results.items()},
        "gaps": gaps
    }
    summary_file = os.path.join(OUT_DIR, f"summary_{date_str}.json")
    with open(summary_file, "w") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    log("=== SCOUT Agent Complete ===")
    sys.exit(0)

def write_obsidian_report(report, gaps, date_str, competitor_results):
    """Write SCOUT report to Obsidian vault for sync to Mac."""
    os.makedirs(SCOUT_OBSIDIAN_DIR, exist_ok=True)

    # Full report as dated page
    report_file = os.path.join(SCOUT_OBSIDIAN_DIR, f"SCOUT_{date_str}.md")
    with open(report_file, "w") as f:
        f.write(report)
    log(f"Obsidian report: {report_file}")

    # Update hub page: add link to this report, keep key metrics at top
    top_gaps_text = ""
    if gaps:
        top_gaps_text = "\n".join(
            f"  - **{g['category']}**: gap +{g['gap']}%"
            for g in gaps[:5]
        )
        top_gaps_text = "\n\n#### Текущие разрывы\n" + top_gaps_text

    channels_count = len([v for v in competitor_results.values() if not v.get("error")])

    hub_entry = f"- [{date_str}](Конкуренты/SCOUT_{date_str}.md) — {channels_count} каналов, {len(gaps)} gaps"

    if os.path.exists(SCOUT_HUB_FILE):
        with open(SCOUT_HUB_FILE) as f:
            hub_content = f.read()
        # Add entry after the header
        lines = hub_content.split("\n")
        # Find the entry section or append
        insert_idx = len(lines)
        for i, line in enumerate(lines):
            if line.startswith("## Последние отчёты"):
                insert_idx = i + 1
                break
        lines.insert(insert_idx, hub_entry)
        hub_content = "\n".join(lines)
    else:
        hub_content = (
            f"# SCOUT — Анализ конкурентов\n\n"
            f"Автоматический мониторинг QA-каналов. Отчёты пишутся при каждом запуске SCOUT.\n"
            f"Данные используются BSA для стратегических ставок и GA для выбора угла.\n"
            f"{top_gaps_text}\n\n"
            f"## Последние отчёты\n"
            f"{hub_entry}\n"
        )

    with open(SCOUT_HUB_FILE, "w") as f:
        f.write(hub_content)
    log(f"Obsidian hub: {SCOUT_HUB_FILE}")


if __name__ == "__main__":
    main()


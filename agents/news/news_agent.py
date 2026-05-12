#!/usr/bin/env python3
"""
NEWS Agent — weekly tech news digest for video commentary podcast.

Searches multiple categories, filters out AI/layoffs, picks top stories,
enriches with commentary angles and event connections, sends as HTML email.
Optionally captures article screenshots via Playwright.

Usage:
  python3 news_agent.py              # run, console output only
  python3 news_agent.py --email      # run and send email report
"""

import base64
import html as html_mod
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

AGENT_DIR = Path("/root/blog-analysis/agents/news")
ENV_FILE = Path("/root/blog-analysis/agents/.env")

AGENT_DIR.mkdir(parents=True, exist_ok=True)

DEEPSEEK_KEY = None
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

# Hard blocklist — stories matching these are filtered out immediately
BLOCK_KEYWORDS = [
    "ai model", "llm", "gpt-", "openai", "anthropic", "claude", "gemini",
    "layoff", "fired", "裁员", "mass layoff", "ai startup",
    "ai funding", "ai investment", "ai regulation", "ai safety",
    "ai assistant", "chatbot", "large language model", "generative ai",
    "midjourney", "stable diffusion", "ai art", "ai image",
    "ai training", "machine learning model", "deep learning",
]

# Search queries organised by categories
SEARCH_QUERIES = [
    ("outages",    "major cloud outage incident downtime postmortem this week"),
    ("outages",    "production outage software failure site down this week"),
    ("bigtech",    "Google Microsoft Amazon Apple Meta news this week"),
    ("bigtech",    "big tech company announcement update"),
    ("products",   "new product launch release announcement tech hardware software"),
    ("security",   "cybersecurity breach data leak vulnerability exploit"),
    ("security",   "supply chain attack zero day vulnerability disclosure"),
    ("stories",    "interesting tech story software engineering culture"),
    ("acquire",    "tech acquisition merger deal announcement"),
    ("platform",   "platform change breaking change deprecation migration"),
]


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# -- DeepSeek -------------------------------------------------

def load_deepseek_key():
    global DEEPSEEK_KEY
    if DEEPSEEK_KEY:
        return DEEPSEEK_KEY
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                DEEPSEEK_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                return DEEPSEEK_KEY
    DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY")
    return DEEPSEEK_KEY


def dk(system, user, temperature=0.7, max_tokens=1024):
    """Call DeepSeek, return response text."""
    key = load_deepseek_key()
    if not key:
        return "ERROR: No DeepSeek API key"
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    })
    try:
        r = subprocess.run(
            ["curl", "-s", DEEPSEEK_URL,
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, text=True, timeout=60,
        )
        resp = json.loads(r.stdout)
        return resp["choices"][0]["message"]["content"]
    except json.JSONDecodeError:
        log(f"  DeepSeek JSON error: {r.stdout[:200]}")
        return "ERROR: API response parse failed"
    except Exception as e:
        log(f"  DeepSeek error: {e}")
        return f"ERROR: {e}"


# -- Search ----------------------------------------------------

def search_duckduckgo(query, max_results=8):
    """DuckDuckGo search via ddgs library."""
    try:
        import warnings
        warnings.filterwarnings("ignore")
        from ddgs import DDGS
        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results, timelimit="w"))
        results = []
        for r in raw:
            results.append({
                "url": r.get("href", ""),
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
            })
        return results if results else []
    except Exception as e:
        log(f"  Search failed: {e}")
        return []


def search_all_news():
    """Search all categories, return deduplicated list of {category, title, snippet, url}."""
    all_results = []
    seen_urls = set()

    for category, query in SEARCH_QUERIES:
        log(f"Search [{category}]: {query[:70]}...")
        results = search_duckduckgo(query, max_results=6)
        log(f"  -> {len(results)} results")
        for r in results:
            url = r.get("url", "").strip()
            if not url or url in seen_urls:
                continue
            # Skip obvious non-articles
            if any(s in url for s in ("youtube.com", "youtu.be", "reddit.com/r/")):
                continue
            seen_urls.add(url)
            all_results.append({
                "category": category,
                "title": r.get("title", "").strip(),
                "snippet": r.get("snippet", "").strip(),
                "url": url,
            })

    log(f"Total unique raw results: {len(all_results)}")
    return all_results


def keyword_filter(results):
    """Remove results whose title matches block keywords."""
    filtered = []
    killed = 0
    for r in results:
        lower = (r["title"] + " " + r["snippet"]).lower()
        if any(kw in lower for kw in BLOCK_KEYWORDS):
            killed += 1
            continue
        filtered.append(r)
    log(f"Keyword filter: removed {killed}, remaining {len(filtered)}")
    return filtered


def deduplicate(results):
    """Deduplicate by URL + near-duplicate titles in same category."""
    seen_urls = set()
    seen_norm = set()
    unique = []
    for r in results:
        key = r["url"].rstrip("/")
        if key in seen_urls:
            continue
        seen_urls.add(key)
        # Near-dedup by normalized title (first ~40 chars)
        norm = re.sub(r'[^a-z0-9]', '', r['title'].lower())[:40]
        if norm and norm in seen_norm:
            continue
        seen_norm.add(norm)
        unique.append(r)
    return unique


# -- Selection Phase -------------------------------------------

def select_top_stories(results, max_stories=12):
    """DeepSeek picks the most interesting stories for a tech commentary podcast."""
    if not results:
        log("No results to select from!")
        return []

    # Format items for DeepSeek
    items_text = ""
    for i, r in enumerate(results, 1):
        items_text += f"{i}. [{r['category']}] {r['title']}\n   {r['snippet'][:150]}\n   {r['url']}\n\n"

    system = (
        "You are a tech news editor for a weekend podcast about big tech and software engineering. "
        "Your audience: senior engineers who want to know what's happening in the industry.\n\n"
        "Pick 8-12 MOST INTERESTING stories from the list for a 15-20 minute podcast episode. "
        "Rules:\n"
        "- PREFER: major outages / incidents, interesting product launches, security breaches with real impact, "
        "big tech company drama / decisions, platform changes that affect developers, engineering culture stories\n"
        "- LIMIT: AI model releases, layoffs news, funding rounds, crypto/NFT stories — at most 20-30% of the selection. If a story is genuinely huge (e.g. major outage caused by AI, or a once-in-industry layoff event), include it. Otherwise deprioritise these topics in favour of more varied stories.\n"
        "- Prioritise stories with a clear narrative: something happened, here's why it matters\n"
        "- DISCARD any story older than 7 days. If the title or snippet mentions a date older than April 2026, skip it. Only keep FRESH news.\n"
        "- Pick stories from different categories — variety is good\n"
        "- If multiple sources cover the same event, pick the best one\n"
        "Output EXACTLY:\n"
        "PICK: <number>, <number>, <number>, ... (comma-separated numbers from the list)\n"
        "No other text."
    )
    user = f"Today: {datetime.now().strftime('%Y-%m-%d')}\n\nNews items to choose from:\n\n{items_text[:8000]}"

    raw = dk(system, user, temperature=0.3, max_tokens=200)
    log(f"Selection raw: {raw[:200]}")

    # Parse the PICK line
    pick_line = ""
    for line in raw.strip().split("\n"):
        lower = line.strip().lower()
        if lower.startswith("pick:") or lower.startswith("pick :"):
            pick_line = line.split(":", 1)[1].strip()
            break

    if not pick_line:
        log("WARNING: Could not parse selection, taking first items")
        return results[:max_stories]

    # Parse numbers
    indices = []
    for part in pick_line.split(","):
        part = part.strip()
        try:
            idx = int(part)
            indices.append(idx)
        except ValueError:
            try:
                # Try to find a number in the string
                nums = re.findall(r"\d+", part)
                if nums:
                    indices.append(int(nums[0]))
            except ValueError:
                pass

    selected = []
    for idx in indices:
        if 1 <= idx <= len(results):
            selected.append(results[idx - 1])

    if not selected:
        log("WARNING: Selection parsing failed, falling back")
        return results[:max_stories]

    log(f"DeepSeek selected {len(selected)} stories")
    return selected[:max_stories]


# -- Enrichment Phase ------------------------------------------

def enrich_story(story):
    """DeepSeek writes a brief summary + why it matters for one story."""
    system = (
        "You are a tech news analyst. For the given news item, write:\n"
        "1. Суть (1-2 предложения) — что произошло, простым языком\n"
        "2. Почему интересно (1 предложение) — почему это стоит обсудить в подкасте\n\n"
        "Пиши на русском. Без воды, без вступлений. Формат:\n"
        "Суть: ...\n"
        "Почему интересно: ..."
    )
    user = f"Title: {story['title']}\nSnippet: {story['snippet']}\nURL: {story['url']}"
    raw = dk(system, user, temperature=0.3, max_tokens=300)
    story["enrichment"] = raw.strip()
    return story


def enrich_all_stories(stories):
    """Enrich all selected stories in parallel (sequential calls to DeepSeek)."""
    for i, story in enumerate(stories):
        log(f"  Enriching [{i+1}/{len(stories)}]: {story['title'][:50]}...")
        enrich_story(story)
    return stories


# -- Connections Phase -----------------------------------------

def find_connections(stories):
    """DeepSeek looks for event connections / patterns across selected stories."""
    stories_text = ""
    for i, s in enumerate(stories, 1):
        stories_text += f"{i}. {s['title']}\n   {s.get('enrichment', s['snippet'][:100])}\n\n"

    system = (
        "You are a tech analyst looking for patterns across weekly news. "
        "Given the list of stories, identify:\n"
        "- Are any of these events connected? (cascading failures, same company, related tech)\n"
        "- Is there a narrative arc? (event A → consequence B)\n"
        "- Any broader industry trends visible in this week's news?\n\n"
        "Write 2-4 bullet points in Russian, short and punchy. "
        "If no connections found, just say 'Связей между событиями этой недели не обнаружено.'\n\n"
        "Output format:\n"
        "### Связи и паттерны\n"
        "- ...\n"
        "- ..."
    )
    user = f"Stories this week:\n\n{stories_text[:4000]}"
    raw = dk(system, user, temperature=0.4, max_tokens=500)
    return raw.strip()


# -- Screenshots (nice-to-have) --------------------------------

def capture_screenshot(url, output_path, max_width=600):
    """Capture a webpage screenshot via Playwright, resize to max_width."""
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            try:
                page.goto(url, timeout=15000, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                # Scroll to capture relevant content
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=output_path, full_page=False)
                browser.close()
            except Exception as e:
                browser.close()
                log(f"  Screenshot goto failed: {e}")
                return False

        # Resize via Pillow
        try:
            from PIL import Image
            img = Image.open(output_path)
            w, h = img.size
            if w > max_width:
                ratio = max_width / w
                new_h = int(h * ratio)
                img = img.resize((max_width, new_h), Image.LANCZOS)
                img.save(output_path, optimize=True, quality=75)
            elif h > 720:
                # Crop height if needed
                img = img.crop((0, 0, w, min(h, 720)))
                img.save(output_path, optimize=True, quality=75)
        except ImportError:
            pass

        return True
    except Exception as e:
        log(f"  Screenshot failed: {e}")
        return False


def capture_screenshots(stories, max_screenshots=6):
    """Capture screenshots for top stories. Returns list of (story_index, b64_data)."""
    screenshots = []
    screenshots_dir = AGENT_DIR / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    for i, story in enumerate(stories[:max_screenshots]):
        log(f"  Screenshot [{i+1}/{min(len(stories), max_screenshots)}]: {story['title'][:50]}...")
        fname = f"ss_{i}_{uuid.uuid4().hex[:8]}.jpg"
        fpath = screenshots_dir / fname
        ok = capture_screenshot(story["url"], str(fpath))
        if ok and fpath.exists() and fpath.stat().st_size > 1000:
            b64 = base64.b64encode(fpath.read_bytes()).decode()
            # Check size — skip if > 300KB
            if len(b64) > 400000:
                log(f"    Screenshot too large ({len(b64)} bytes base64), skipping")
                fpath.unlink()
                continue
            screenshots.append((i, b64, fname))
            log(f"    OK ({fpath.stat().st_size} bytes)")
        else:
            log(f"    Skipped")

    # Cleanup screenshot dir
    for f in screenshots_dir.glob("*.jpg"):
        f.unlink()
    screenshots_dir.rmdir() if screenshots_dir.exists() else None

    return screenshots


# -- Markdown → HTML (from researcher, standalone) -------------

def md_to_html(text):
    """Convert basic markdown to HTML."""
    placeholders = {}
    def _save(content, tag):
        pid = f"__MD_{uuid.uuid4().hex[:8]}__"
        placeholders[pid] = (tag, content)
        return pid

    # 1. Extract code blocks
    text = re.sub(
        r"```(\w*)\n(.*?)```",
        lambda m: _save(m.group(2), "codeblock"),
        text, flags=re.DOTALL,
    )
    # 2. Inline code
    text = re.sub(
        r"`([^`]+)`",
        lambda m: _save(m.group(1), "code"),
        text,
    )
    # 3. Links
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: _save((m.group(1), m.group(2)), "link"),
        text,
    )
    # 4. Bold
    text = re.sub(
        r"\*\*(.+?)\*\*",
        lambda m: _save(m.group(1), "bold"),
        text,
    )
    # 5. HTML-escape remaining
    text = html_mod.escape(text)
    # 6. Restore placeholders
    for pid, (tag, content) in placeholders.items():
        if tag == "codeblock":
            replacement = f"<pre><code>{html_mod.escape(content)}</code></pre>"
        elif tag == "code":
            replacement = f"<code>{html_mod.escape(content)}</code>"
        elif tag == "link":
            link_text, url = content
            replacement = f'<a href="{html_mod.escape(url)}">{html_mod.escape(link_text)}</a>'
        elif tag == "bold":
            replacement = f"<strong>{html_mod.escape(content)}</strong>"
        else:
            replacement = html_mod.escape(str(content))
        text = text.replace(pid, replacement)

    # 7. Process structure
    lines = text.split("\n")
    result = []
    in_list = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_list:
                result.append("</ul>")
                in_list = False
            result.append("<br>")
            continue
        if stripped.startswith("<pre>") or stripped.startswith("<code>"):
            if in_list:
                result.append("</ul>"); in_list = False
            result.append(stripped)
            continue
        h_match = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if h_match:
            if in_list:
                result.append("</ul>"); in_list = False
            level = len(h_match.group(1))
            result.append(f"<h{level}>{h_match.group(2)}</h{level}>")
            continue
        if stripped.startswith("- "):
            if not in_list:
                result.append("<ul>"); in_list = True
            result.append(f"<li>{stripped[2:]}</li>")
            continue
        if in_list:
            result.append("</ul>"); in_list = False
        result.append(f"<p>{stripped}</p>")
    if in_list:
        result.append("</ul>")
    return "".join(result)


# -- Email -----------------------------------------------------

def email_report(subject, body, html=None):
    """Send report via email using shared mailer."""
    try:
        sys.path.insert(0, str(Path("/root/blog-analysis/lib")))
        from mailer import send
        result = send(subject, body, html=html)
        log(f"Email sent: {result}")
        return result
    except Exception as e:
        log(f"Email failed: {e}")
        return False


def build_html_email(date_str, stories, connections_text, screenshots):
    """Build HTML email body with stories, connections, and screenshots."""
    parts = []

    # Header
    parts.append(f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; max-width: 680px; margin: 0 auto; padding: 20px; color: #1a1a1a; line-height: 1.6;">
<div style="margin-bottom: 24px;">
<h1 style="font-size: 24px; margin-bottom: 2px;">🗞 NEWS Digest</h1>
<p style="color: #666; font-size: 14px; margin-top: 2px;">{date_str}</p>
</div>
<hr style="border: none; border-top: 2px solid #e0e0e0;">""")

    # Stories
    for i, s in enumerate(stories, 1):
        parts.append(f"""
<div style="margin: 20px 0; padding: 16px; background: #f8f9fa; border-radius: 8px;">
<div style="display: flex; align-items: baseline; gap: 8px; margin-bottom: 8px;">
<span style="font-size: 12px; color: #888; text-transform: uppercase;">{html_mod.escape(s['category'])}</span>
</div>
<h3 style="margin: 0 0 6px 0; font-size: 16px;">
<a href="{html_mod.escape(s['url'])}" style="color: #1a73e8; text-decoration: none;">{html_mod.escape(s['title'][:100])}</a>
</h3>""")

        # Enrichment
        enrichment = s.get("enrichment", "")
        if enrichment:
            enrichment_html = md_to_html(enrichment)
            parts.append(f"""<div style="font-size: 14px; color: #333;">{enrichment_html}</div>""")

        # Screenshot for this story
        for idx, b64, fname in screenshots:
            if idx == i - 1:
                parts.append(f"""<div style="margin-top: 10px;">
<img src="data:image/jpeg;base64,{b64}" alt="Screenshot" style="max-width: 100%; height: auto; border-radius: 4px; border: 1px solid #ddd;">
</div>""")
                break

        parts.append(f"""<div style="margin-top: 8px;">
<a href="{html_mod.escape(s['url'])}" style="font-size: 12px; color: #1a73e8;">Читать оригинал →</a>
</div></div>""")

    # Connections section
    if connections_text and "не обнаружено" not in connections_text:
        connections_html = md_to_html(connections_text)
        parts.append(f"""
<hr style="border: none; border-top: 1px solid #ddd;">
<div style="margin: 20px 0; padding: 16px; background: #fffbe6; border-radius: 8px; border-left: 4px solid #f0c040;">
{connections_html}
</div>""")

    # Footer
    parts.append(f"""
<hr style="border: none; border-top: 2px solid #e0e0e0;">
<p style="color: #999; font-size: 12px;">
NEWS Agent<br>
<em>Generated {date_str}</em>
</p>
</body>
</html>""")

    return "\n".join(parts)


def build_plain_body(date_str, stories, connections_text):
    """Build plain text body."""
    lines = []
    lines.append(f"NEWS Digest")
    lines.append(f"{date_str}")
    lines.append("=" * 50)
    lines.append("")

    for i, s in enumerate(stories, 1):
        lines.append(f"[{s['category'].upper()}] {s['title']}")
        lines.append(f"  {s['url']}")
        enrichment = s.get("enrichment", "")
        if enrichment:
            lines.append(f"  {enrichment}")
        lines.append("")

    if connections_text:
        lines.append("")
        lines.append("=" * 50)
        lines.append("СВЯЗИ И ПАТТЕРНЫ")
        lines.append("-" * 20)
        # Strip markdown from connections
        clean = re.sub(r"\*\*(.*?)\*\*", r"\1", connections_text)
        clean = re.sub(r"###\s+", "", clean)
        lines.append(clean)

    return "\n".join(lines)


# -- Main Flow -------------------------------------------------

def main():
    send_email = "--email" in sys.argv
    date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"  NEWS AGENT — weekly tech digest")
    print(f"  Date: {date_str}")
    print(f"{'='*60}\n")

    # ---- Phase 1: Search ----
    log("Phase 1: Searching news categories...")
    raw_results = search_all_news()
    if not raw_results:
        log("ERROR: No search results at all")
        sys.exit(1)

    # ---- Phase 2: Filter & Dedup ----
    log("Phase 2: Filtering...")
    # Soft-filter: let DeepSeek decide the ratio (20-30% max for AI/layoffs)
    filtered = deduplicate(raw_results)
    log(f"After filter/dedup: {len(filtered)} stories")

    # ---- Phase 3: Select Top Stories ----
    log("Phase 3: DeepSeek selecting top stories...")
    selected = select_top_stories(filtered, max_stories=12)
    if not selected:
        log("ERROR: No stories selected")
        sys.exit(1)

    # ---- Phase 4: Enrich ----
    log("Phase 4: Enriching stories...")
    selected = enrich_all_stories(selected)

    # ---- Phase 5: Connections ----
    log("Phase 5: Finding event connections...")
    connections = find_connections(selected)

    # ---- Phase 6: Screenshots (nice-to-have) ----
    screenshots = []
    if send_email:
        log("Phase 6: Capturing screenshots...")
        screenshots = capture_screenshots(selected, max_screenshots=6)

    # ---- Phase 7: Build output ----
    log("Phase 7: Building report...")

    # Console output
    print(f"\n{'='*60}")
    print("  TOP STORIES THIS WEEK")
    print(f"{'='*60}\n")
    for i, s in enumerate(selected, 1):
        print(f"{i}. [{s['category']}] {s['title']}")
        print(f"   {s['url']}")
        enrichment = s.get("enrichment", "")
        if enrichment:
            for line in enrichment.strip().split("\n"):
                print(f"   {line.strip()}")
        print()

    if connections:
        print(f"\n{'='*60}")
        print("  CONNECTIONS")
        print(f"{'='*60}")
        clean = re.sub(r"\*\*(.*?)\*\*", r"\1", connections)
        clean = re.sub(r"###\s+", "", clean)
        print(f"\n{clean}\n")

    # Save report locally
    safe_ts = date_str
    out_file = AGENT_DIR / f"news_digest_{safe_ts}.md"
    out_file.write_text(
        f"# NEWS Digest: {date_str}\n\n"
        + "\n\n".join(
            f"## {i}. [{s['category']}] {s['title']}\n"
            f"URL: {s['url']}\n"
            f"{s.get('enrichment', '')}"
            for i, s in enumerate(selected, 1)
        )
        + f"\n\n---\n## Connections\n{connections}"
    )
    log(f"Report saved: {out_file}")

    # ---- Phase 8: Email ----
    if send_email:
        log("Phase 8: Sending email...")
        html_body = build_html_email(date_str, selected, connections, screenshots)
        plain_body = build_plain_body(date_str, selected, connections)
        email_report(f"🗞 NEWS Digest: {date_str}", plain_body, html=html_body)

    print(f"\n{'='*60}")
    print(f"  Done. {len(selected)} stories.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()

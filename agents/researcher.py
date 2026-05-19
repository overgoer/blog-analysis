#!/usr/bin/env python3
"""
RESEARCHER Agent v3 -- question-driven topic research for @eddytester.

Generates 6-7 questions about a topic, researches each via Serper.dev + SearXNG,
fetches full article content, produces structured research brief.

Usage:
  python3 researcher.py "topic"
  python3 researcher.py --pick
  python3 researcher.py --pick --email
"""

import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import concurrent.futures
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from pathlib import Path

AGENT_DIR = Path("/root/blog-analysis/agents/researcher")
ENV_FILE = Path("/root/blog-analysis/agents/.env")
EDDY_FILE = Path("/root/blog-analysis/data/eddytester_raw.json")
CACHE_DIR = AGENT_DIR / "search_cache"
CACHE_TTL = 86400  # 24 hours
DUMP_FILE = Path("/root/blog-analysis/agents/bsa/dump.md")

AGENT_DIR.mkdir(parents=True, exist_ok=True)

DEEPSEEK_KEY = None
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

_CHANNEL_POSTS_CACHE = None


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


def load_serper_key():
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("SERPER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("SERPER_API_KEY")


def dk(system, user, temperature=0.7, max_tokens=1024):
    """Call DeepSeek, return response text."""
    key = load_deepseek_key()
    if not key:
        return "ERROR: No DeepSeek API key"

    payload = json.dumps({
        "model": "deepseek-v4-flash",
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
            capture_output=True, text=True, timeout=120,
        )
        resp = json.loads(r.stdout)
        return resp["choices"][0]["message"]["content"]
    except json.JSONDecodeError:
        log(f"  DeepSeek JSON error: {r.stdout[:200]}")
        return "ERROR: API response parse failed"
    except Exception as e:
        log(f"  DeepSeek error: {e}")
        return f"ERROR: {e}"


# -- Search Cache -------------------------------------------------


def _cache_key(query):
    return hashlib.md5(query.encode("utf-8")).hexdigest()


def _cache_get(query):
    """Get cached search results if fresh."""
    key = _cache_key(query)
    path = CACHE_DIR / f"{key}.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            age = time.time() - data.get("ts", 0)
            if age < CACHE_TTL:
                log(f"  Cache HIT: {query[:60]}")
                return data.get("results")
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _cache_set(query, results):
    """Cache search results with timestamp."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(query)
    path = CACHE_DIR / f"{key}.json"
    path.write_text(json.dumps({
        "ts": time.time(),
        "query": query,
        "results": results,
    }, ensure_ascii=False))


# -- Full-page Fetching --------------------------------------------


def fetch_page_content(url, timeout=15):
    """Fetch URL and extract main article content.

    Tries trafilatura first, falls back to basic text extraction.
    Returns (title, text) tuple or None on failure.
    """
    if not url:
        return None
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; ResearcherBot/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        resp = urllib.request.urlopen(req, timeout=timeout)
        raw = resp.read()
        # Detect encoding
        content_type = resp.headers.get("Content-Type", "")
        encoding = "utf-8"
        if "charset=" in content_type:
            encoding = content_type.split("charset=")[-1].split(";")[0].strip()
        html_text = raw.decode(encoding, errors="replace")

        # Attempt 1: trafilatura
        text = _extract_with_trafilatura(html_text, url)
        if text:
            return text[:5000]

        # Attempt 2: readability-lxml
        text = _extract_with_readability(html_text, url)
        if text:
            return text[:5000]

        # Attempt 3: basic HTML tag stripping (last resort)
        text = _extract_basic_html(html_text)
        if text and len(text) > 200:
            return text[:5000]

        return None
    except urllib.error.HTTPError as e:
        if e.code == 403:
            return None  # blocked, skip silently
        log(f"  Page fetch HTTP {e.code}: {url[:60]}")
        return None
    except Exception as e:
        log(f"  Page fetch failed: {url[:60]} — {type(e).__name__}")
        return None


def _extract_with_trafilatura(html_text, url):
    try:
        import trafilatura
        text = trafilatura.extract(html_text, url=url, include_links=True)
        if text and len(text.strip()) > 100:
            return text.strip()
    except ImportError:
        pass
    except Exception:
        pass
    return None


def _extract_with_readability(html_text, url):
    try:
        from readability import Document
        doc = Document(html_text, url=url)
        summary = doc.summary()
        # Strip HTML tags from summary
        import html.parser
        class TagStripper(html.parser.HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = []
            def handle_data(self, data):
                self.text.append(data)
        stripper = TagStripper()
        stripper.feed(summary)
        text = " ".join(stripper.text).strip()
        if len(text) > 100:
            return text
    except ImportError:
        pass
    except Exception:
        pass
    return None


def _extract_basic_html(html_text):
    """Remove script/style tags and tags, return text."""
    text = re.sub(r'<script[^>]*>.*?</script>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<nav[^>]*>.*?</nav>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<footer[^>]*>.*?</footer>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<header[^>]*>.*?</header>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# -- Web Search ------------------------------------------------


def search_searxng(query, max_results=15, language="all", engines=""):
    """Search via self-hosted SearXNG."""
    params_dict = {
        "q": query,
        "format": "json",
        "language": language,
        "pageno": 1,
    }
    if engines:
        params_dict["engines"] = engines
    url = f"http://localhost:4000/search?{urllib.parse.urlencode(params_dict)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode())
        raw_results = data.get("results", [])
        results = []
        seen_urls = set()
        for r in raw_results:
            u = r.get("url", "")
            if u in seen_urls or not u:
                continue
            seen_urls.add(u)
            results.append({
                "url": u,
                "title": r.get("title", ""),
                "snippet": r.get("content", ""),
                "engine": r.get("engine", "web"),
            })
        return results[:max_results]
    except Exception as e:
        log(f"  SearXNG search failed: {e}")
        return [{"title": "Search error", "snippet": str(e), "url": "", "engine": "web"}]



def search_serper(query, max_results=10):
    """Search via Serper.dev (Google Search API)."""
    key = load_serper_key()
    if not key:
        log("  Serper.dev: no API key, skipping")
        return []

    payload = json.dumps({"q": query, "num": max_results, "gl": "us", "hl": "en"})
    try:
        r = subprocess.run(
            ["curl", "-s", "-X", "POST", "https://google.serper.dev/search",
             "-H", f"x-api-key: {key}",
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(r.stdout)
        raw_results = data.get("organic", [])
        results = []
        seen_urls = set()
        for item in raw_results:
            u = item.get("link", "")
            if u in seen_urls or not u:
                continue
            seen_urls.add(u)
            results.append({
                "url": u,
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "engine": "google",
            })
        return results[:max_results]
    except Exception as e:
        log(f"  Serper.dev search failed: {e}")
        return []



def search_all(query):
    """Search via Serper.dev + SearXNG fallback, cached."""
    # Check cache first
    cached = _cache_get(query)
    if cached:
        return cached

    results = []
    seen_urls = set()

    # Primary: Serper.dev (Google Search — best quality)
    serper_results = search_serper(query, max_results=10)
    if serper_results:
        for r in serper_results:
            if r["url"] and r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                r["engine"] = "web"
                results.append(r)
        log(f"  Serper.dev: {len(serper_results)} results")
    else:
        log("  Serper.dev failed, falling back to SearXNG")

        # Fallback: SearXNG — Bing (English)
        for r in search_searxng(query, max_results=8, language="en-US", engines="bing"):
            if r["url"] and r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                r["engine"] = "web-en"
                results.append(r)

        # Fallback: SearXNG — Mojeek (RU / independent)
        for r in search_searxng(query, max_results=8, language="ru-RU", engines="mojeek"):
            if r["url"] and r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                r["engine"] = "web-ru"
                results.append(r)

        # Fallback: SearXNG — HackerNews (tech discussions)
        for r in search_searxng(query, max_results=4, language="en-US", engines="hackernews"):
            if r["url"] and r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                r["engine"] = "web-hn"
                results.append(r)

    # Cache results before returning
    _cache_set(query, results)
    return results


# -- Reference Posts Loading -----------------------------------


def load_channel_posts(limit=8):
    """Load best eddytester posts for style reference."""
    global _CHANNEL_POSTS_CACHE
    if _CHANNEL_POSTS_CACHE is not None:
        return _CHANNEL_POSTS_CACHE
    if not EDDY_FILE.exists():
        log(f"  No eddytester data at {EDDY_FILE}")
        _CHANNEL_POSTS_CACHE = ""
        return ""
    try:
        data = json.loads(EDDY_FILE.read_text())
        messages = data.get("messages", [])
        texts = []
        for m in messages:
            t = m.get("text", "")
            if isinstance(t, list):
                t = " ".join(
                    item if isinstance(item, str) else item.get("text", "")
                    for item in t
                )
            if len(t) > 150:
                texts.append(t)
            if len(texts) >= limit:
                break
        _CHANNEL_POSTS_CACHE = "\n\n---\n\n".join(texts)
        return _CHANNEL_POSTS_CACHE
    except Exception as e:
        log(f"  Error loading posts: {e}")
        _CHANNEL_POSTS_CACHE = ""
        return ""


def load_dump(limit=2000):
    """Load recent dump entries for context. Returns last N chars."""
    if not DUMP_FILE.exists():
        return ""
    try:
        text = DUMP_FILE.read_text(encoding="utf-8")
        if len(text) > limit:
            text = "..." + text[-limit:]
        return text.strip()
    except Exception as e:
        log(f"  Error loading dump: {e}")
        return ""


def parse_aspect_response(text):
    """Parse DeepSeek response into aspect description and search query."""
    lines = text.strip().split("\n")
    aspect_parts = []
    search_q = None
    for line in lines:
        lower = line.strip().lower()
        if lower.startswith("search:") or lower.startswith("search :"):
            search_q = line.split(":", 1)[1].strip()
        elif lower.startswith("aspect:") or lower.startswith("aspect :"):
            aspect_parts.append(line.split(":", 1)[1].strip())
        else:
            aspect_parts.append(line)
    aspect = " ".join(aspect_parts).strip()
    if not aspect:
        aspect = text
    return aspect, search_q


# -- Topic Management ------------------------------------------

TOPICS_FILE = AGENT_DIR / "topics.json"


def load_topics():
    if TOPICS_FILE.exists():
        return json.loads(TOPICS_FILE.read_text())
    return {"pool": [], "researched": [], "suggested": []}


def save_topics(data):
    TOPICS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def pick_topic():
    """Use DeepSeek to pick the best next topic from the pool."""
    data = load_topics()
    pool = data["pool"]
    researched = data["researched"]
    suggested = data["suggested"]

    if not pool:
        log("Topic pool is empty!")
        return None

    ref_posts = load_channel_posts(5)
    researched_topics = [r["topic"] for r in researched]

    system_prompt = (
        "You are a senior QA and content strategist for @eddytester testing channel. "
        "Your task: pick the BEST next topic from the pool to research.\n\n"
        "Output FORMAT (exactly):\n"
        "PICK: <exact topic text from the pool>\n"
        "SUGGEST: <new topic suggestion, in Russian, 5-15 words>\n"
        "SUGGEST: <another new topic suggestion>\n\n"
        "Rules:\n"
        "- Pick ONE topic from the pool to research NOW\n"
        "- Suggest 2 NEW topics that were NOT in the pool (fresh ideas)\n"
        "- New topics should match the channel style: deep practical QA content\n"
        "- Consider: what hasn't been researched yet vs what has\n"
        "- Prioritize topics with testing focus over generic ones\n"
        "- New topics should be specific, not generic"
    )

    user_prompt = (
        f"Topic pool:\n" + "\n".join(f"- {t}" for t in pool) + "\n\n"
        f"Already researched:\n" + "\n".join(f"- {r['topic']} ({r['date']})" for r in researched[-10:]) + "\n\n"
        f"Channel post examples (for style):\n{ref_posts[:2000]}\n\n"
        "Pick the best topic. Suggest 2 new topics."
    )

    raw = dk(system_prompt, user_prompt, temperature=0.7, max_tokens=400)
    lines = raw.strip().split("\n")

    picked = None
    new_suggestions = []

    for line in lines:
        lower = line.strip().lower()
        if lower.startswith("pick:") or lower.startswith("pick :"):
            picked = line.split(":", 1)[1].strip()
        elif lower.startswith("suggest:") or lower.startswith("suggest :"):
            sug = line.split(":", 1)[1].strip()
            new_suggestions.append(sug)

    picked_topic = None
    if picked:
        for t in pool:
            if picked.lower().strip() == t.lower().strip()[:len(picked)] or \
               t.lower().strip()[:len(picked)] == picked.lower().strip():
                picked_topic = t
                break
        if not picked_topic:
            for t in pool:
                words = set(picked.lower().split())
                twords = set(t.lower().split())
                overlap = len(words & twords)
                if overlap >= 3:
                    picked_topic = t
                    break

    if not picked_topic:
        picked_topic = pool[0]

    log(f"Picked topic: {picked_topic}")
    log(f"New suggestions: {new_suggestions}")

    if picked_topic in pool:
        pool.remove(picked_topic)
    data["researched"].append({
        "topic": picked_topic,
        "date": datetime.now().strftime("%Y-%m-%d"),
    })
    for sug in new_suggestions:
        if sug and len(sug) > 10:
            if sug not in pool and not any(r["topic"] == sug for r in data["researched"]):
                pool.append(sug)
                data["suggested"].append(sug)

    save_topics(data)
    return picked_topic


# -- Save & Send ------------------------------------------------


def save_brief_to_obsidian(topic, brief, date_str):
    """Save research brief to Obsidian vault."""
    try:
        obsidian_dir = Path("/root/obsidian-vault/eddytester/Стратегия/Исследования")
        obsidian_dir.mkdir(parents=True, exist_ok=True)
        safe_topic = re.sub(r"[^a-zA-Zа-яА-Я0-9_\-]", "_", topic)[:50]
        filename = obsidian_dir / f"{date_str}_{safe_topic}.md"
        content = f"# Research: {topic}\n\n**Date:** {date_str}\n\n---\n\n{brief}"
        filename.write_text(content)
        log(f"Brief saved to Obsidian: {filename}")
        return True
    except Exception as e:
        log(f"Obsidian save failed: {e}")
        return False


def email_report(subject, body, html=None):
    try:
        sys.path.insert(0, str(Path("/root/blog-analysis/lib")))
        from mailer import send
        result = send(subject, body, html=html)
        log(f"Email sent: {result}")
        return result
    except Exception as e:
        log(f"Email failed: {e}")
        return False


# -- Question Generation ---------------------------------------


def generate_questions(topic, ref_posts, count=7):
    """DeepSeek generates N engaging questions about the topic for QA audience."""
    system = (
        "You are a senior QA editor for a testing channel (@eddytester). "
        "Generate questions about the given topic that would engage manual and mid-level testers.\n\n"
        "Output FORMAT: one question per line, no numbering.\n"
        "Each question should make a tester think: 'huh, never considered that'.\n\n"
        "Types of questions to generate (mix them):\n"
        "- Real incidents: when did this topic cause a major outage or bug in well-known services?\n"
        "- Why it matters: why should a tester care about this specific topic?\n"
        "- Ideal world: how should this be implemented ideally?\n"
        "- Testing: how to test this so you don't miss critical bugs?\n\n"
        "Example questions (for style reference):\n"
        "- Когда PUT/PATCH в Stripe привёл к двойному списанию — как тестировать идемпотентность на уровне платёжного шлюза?\n"
        "- Если сервер меняет updated_at при каждом PUT, это нарушает идемпотентность — почему это критично для аудита данных?\n"
        "- В идеале PUT должен быть идемпотентен: отправляешь одни и те же данные дважды — состояние не меняется. Как этого добиться на практике?\n\n"
        "Output 7 questions. In Russian. Make them specific, not generic."
    )
    user = f"Topic: {topic}\n\nChannel examples (for style context):\n{ref_posts[:1000]}"
    raw = dk(system, user, temperature=0.7, max_tokens=2500)

    questions = [q.strip("- 1234567890.\t ") for q in raw.strip().split("\n") if q.strip()]
    questions = [q for q in questions if len(q) > 20 and "?" in q]
    log(f"Generated {len(questions)} questions")
    for i, q in enumerate(questions, 1):
        log(f"  Q{i}: {q[:100]}")
    return questions[:count]


# -- Research Brief Generation ---------------------------------


def generate_brief(topic, accumulated, date_str, dump_context=""):
    """Generate structured research brief from accumulated findings."""
    research_data = ""
    for a in accumulated:
        research_data += f"\n## Question: {a['aspect']}\n\n"
        for r in a["results"][:3]:
            eng = r.get("engine", "web")
            research_data += f"[{eng}] {r['title']}\n  {r['snippet'][:150]}\n  {r['url']}\n\n"
        # Include full page content for top 2 results
        if a.get("pages"):
            for pg in a["pages"][:2]:
                research_data += f"Full page content:\n  {pg['content'][:2000]}\n\n"
        research_data += f"Analysis: {a['analysis']}\n\n"

    dump_section = ""
    if dump_context:
        dump_section = (
            "\n\n---\n"
            "Заметки и мнения Эдди (автора канала) по разным темам. "
            "Учитывай их при формировании brief — подсвечивай если тема пересекается.\n"
            "Важно: не всегда соглашайся с его позицией. Если видишь что мнение "
            "спорное или контринтуитивное — отметь это и приведи контраргумент. "
            "Эдди ценит когда его переубеждают аргументированно.\n"
            f"{dump_context}\n"
        )

    system = (
        "You are a senior QA compiling a research brief for a colleague who runs a testing channel. "
        "Write IN RUSSIAN.\n\n"
        "Structure the brief EXACTLY as follows (use markdown):\n\n"
        "For EACH question, provide 3 sections:\n"
        "### [short version of question]\n\n"
        "**Links & Sources**\n"
        "- [title](url) — конкретная суть статьи одним предложением (НЕ общее описание вроде 'разбор проблемы', а соль: 'причиной пятисоток было взаимодействие с бд при одновременных транзакциях')\n\n"
        "**Багы и реальные кейсы**\n"
        "- конкретный баг или случай, что произошло, почему\n\n"
        "**Технические детали**\n"
        "- команды, curl, чек-листы, что именно проверять\n\n"
        "After all questions, add a final section:\n"
        "### Идеи для постов\n"
        "- тезисно, 2-3 угла для постов, без воды, без формулировок \"как стать лучше\"\n\n"
        "Rules:\n"
        "- NO long introductions. NO fluff. Straight to facts.\n"
        "- If a question has little data, write 'По этому углу информации почти нет'.\n"
        "- Each section concrete: specific bugs, specific commands, specific links.\n"
        "- Keep total brief under 5000 chars."
    ) + dump_section
    user = (
        f"Topic: {topic}\nDate: {date_str}\n\n"
        f"Research data by question:\n{research_data[:8000]}"
    )
    return dk(system, user, temperature=0.4, max_tokens=6000)


# -- Markdown to HTML ------------------------------------------


def md_to_html(text):
    """Convert basic markdown to HTML."""
    import uuid

    placeholders = {}
    def _save(content, tag):
        pid = f"__MD_{uuid.uuid4().hex[:8]}__"
        placeholders[pid] = (tag, content)
        return pid

    text = re.sub(
        r"```(\w*)\n(.*?)```",
        lambda m: _save(m.group(2), "codeblock"),
        text, flags=re.DOTALL,
    )

    text = re.sub(
        r"`([^`]+)`",
        lambda m: _save(m.group(1), "code"),
        text,
    )

    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda m: _save((m.group(1), m.group(2)), "link"),
        text,
    )

    text = re.sub(
        r"\*\*(.+?)\*\*",
        lambda m: _save(m.group(1), "bold"),
        text,
    )

    text = html.escape(text)

    for pid, (tag, content) in placeholders.items():
        if tag == "codeblock":
            replacement = f"<pre><code>{html.escape(content)}</code></pre>"
        elif tag == "code":
            replacement = f"<code>{html.escape(content)}</code>"
        elif tag == "link":
            link_text, url = content
            replacement = f'<a href="{html.escape(url)}">{html.escape(link_text)}</a>'
        elif tag == "bold":
            replacement = f"<strong>{html.escape(content)}</strong>"
        else:
            replacement = html.escape(str(content))
        text = text.replace(pid, replacement)

    lines = text.split("\n")
    result = []
    in_list = False
    in_ordered_list = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if in_list:
                result.append("</ul>")
                in_list = False
            if in_ordered_list:
                result.append("</ol>")
                in_ordered_list = False
            result.append("<br>")
            continue

        if stripped.startswith("<pre>") or stripped.startswith("<code>"):
            if in_list:
                result.append("</ul>"); in_list = False
            if in_ordered_list:
                result.append("</ol>"); in_ordered_list = False
            result.append(stripped)
            continue

        h_match = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if h_match:
            if in_list:
                result.append("</ul>"); in_list = False
            if in_ordered_list:
                result.append("</ol>"); in_ordered_list = False
            level = len(h_match.group(1))
            result.append(f"<h{level}>{h_match.group(2)}</h{level}>")
            continue

        if stripped.startswith("- "):
            if in_ordered_list:
                result.append("</ol>"); in_ordered_list = False
            if not in_list:
                result.append("<ul>"); in_list = True
            result.append(f"<li>{stripped[2:]}</li>")
            continue

        ol_match = re.match(r"^(\d+)\.\s+(.+)$", stripped)
        if ol_match:
            if in_list:
                result.append("</ul>"); in_list = False
            if not in_ordered_list:
                result.append("<ol>"); in_ordered_list = True
            result.append(f"<li>{ol_match.group(2)}</li>")
            continue

        if in_list:
            result.append("</ul>"); in_list = False
        if in_ordered_list:
            result.append("</ol>"); in_ordered_list = False
        result.append(f"<p>{stripped}</p>")

    if in_list: result.append("</ul>")
    if in_ordered_list: result.append("</ol>")

    return "".join(result)


# -- Single-question Research -----------------------------------


def research_question(topic, question, ref_posts):
    """Research a single question: build query, search, fetch pages, analyze.

    Returns dict {aspect, search_query, results, pages, analysis} or None.
    """
    try:
        # Step A: Build keyword search query from the question
        search_q = dk(
            "Extract 5-8 ENGLISH KEYWORDS (not a sentence) from this question for a technical web search. "
            "Output ONLY the keywords in English, space-separated, no punctuation, no explanation.",
            f"Question: {question}\n\nTopic: {topic}",
            temperature=0.1,
            max_tokens=500,
        )
        search_q = search_q.strip().strip('"').strip("'").replace('\n', ' ')
        import re as _re
        search_q = _re.sub(r'[^\w\s-]', ' ', search_q)
        search_q = _re.sub(r'\s+', ' ', search_q).strip()
        if len(search_q) < 5 or "ERROR" in search_q:
            search_q = " ".join(topic.split()[:6])
        log(f"  Query: {search_q[:120]}")

        # Step B: Multi-engine search
        results = search_all(search_q)
        log(f"  Results: {len(results)} total")
        for r in results:
            log(f"    [{r.get('engine','?')}] {r['title'][:70]}")

        # Step C: Fetch full-page content for top results
        pages = []
        fetched = 0
        for r in results:
            if fetched >= 3:
                break
            url = r.get("url", "")
            if not url:
                continue
            content = fetch_page_content(url)
            if content:
                pages.append({"url": url, "title": r.get("title", ""), "content": content})
                fetched += 1
                log(f"  Fetched page: {url[:60]} ({len(content)} chars)")
        log(f"  Pages fetched: {fetched}")

        # Step D: Analyze findings including full-page content
        results_text = "\n".join(
            f"[{r.get('engine','web')}] {r['title']}: {r['snippet'][:250]}"
            for r in results if r.get("snippet")
        )

        if pages:
            pages_text = "\n\n".join(
                f"--- Full article: {p['title']} ---\n{p['content'][:3000]}"
                for p in pages
            )
        else:
            pages_text = ""

        combined_text = results_text
        if pages_text:
            combined_text += "\n\n" + pages_text

        if combined_text.strip():
            analysis = dk(
                "You are a QA analyst. Brief analysis in Russian for this question (2-3 bullet points). "
                "What specific bugs, cases or insights? What is most valuable for a tester? "
                "If results are weak, say so honestly.",
                f"Topic: {topic}\nQuestion: {question}\n\nSearch results and articles:\n{combined_text[:3500]}",
                temperature=0.3,
                max_tokens=400,
            )
        else:
            analysis = "По этому вопросу релевантных результатов не найдено."

        log(f"  Analysis: {analysis[:150]}")

        return {
            "aspect": question,
            "search_query": search_q,
            "results": results,
            "pages": pages,
            "analysis": analysis,
        }
    except Exception as e:
        log(f"  Research question failed: {e}")
        return None


# -- Main Research Loop ----------------------------------------


def main():
    send_email_flag = False

    if "--email" in sys.argv:
        send_email_flag = True
        sys.argv.remove("--email")

    if "--pick" in sys.argv:
        sys.argv.remove("--pick")
        topic = pick_topic()
        if not topic:
            print("ERROR: No topic to research")
            sys.exit(1)
    elif len(sys.argv) < 2:
        print("Usage: python3 researcher.py <topic>")
        print("       python3 researcher.py --pick")
        print("       python3 researcher.py --pick --email")
        sys.exit(1)
    else:
        topic = " ".join(sys.argv[1:])

    date_str = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"  RESEARCHER v3: {topic}")
    print(f"  Date: {date_str}")
    print(f"{'='*60}\n")

    ref_posts = load_channel_posts(8)

    # -- Phase 1: Generate questions --------------------------------
    log("Phase 1: Generating questions...")
    questions = generate_questions(topic, ref_posts)
    if not questions:
        log("WARNING: No questions generated, using defaults")
        questions = [
            f"Какие массовые сбои или баги были связаны с {topic}?",
            f"Почему {topic} важно тестировать?",
            f"Как должна быть реализована {topic} идеально?",
            f"Как тестировать {topic} чтобы не упустить багов?",
            f"Какие инструменты помогают тестировать {topic}?",
            f"Какие курьезные случаи связаны с {topic}?"
        ]

    # -- Phase 2: Research ALL questions in parallel ----------------
    log(f"Phase 2: Researching {len(questions)} questions (parallel)...")
    accumulated = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(questions), 7)) as executor:
        futures = {
            executor.submit(research_question, topic, q, ref_posts): q
            for q in questions[:6]
        }
        for future in concurrent.futures.as_completed(futures):
            q = futures[future]
            try:
                result = future.result()
                if result:
                    accumulated.append(result)
                    log(f"  ✓ Completed: {q[:60]}")
                else:
                    log(f"  ✗ Failed: {q[:60]}")
            except Exception as e:
                log(f"  ✗ Exception: {q[:60]} — {e}")

    # Sort accumulated by original question order
    q_order = {q: i for i, q in enumerate(questions)}
    accumulated.sort(key=lambda a: q_order.get(a.get("aspect", ""), 999))

    log(f"Phase 2 complete: {len(accumulated)}/{len(questions)} questions researched")

    # -- Phase 3: Generate Research Brief ---------------------------
    log("Phase 3: Generating research brief...")
    dump_ctx = load_dump()
    if dump_ctx:
        log(f"  Loaded dump context ({len(dump_ctx)} chars)")
    brief = generate_brief(topic, accumulated, date_str, dump_context=dump_ctx)

    # Format and save report
    report_lines = []
    report_lines.append(f"# Research Brief: {topic}")
    report_lines.append(f"Date: {date_str}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")
    report_lines.append("### Questions explored")
    report_lines.append("")
    for i, q in enumerate(questions, 1):
        report_lines.append(f"{i}. {q}")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    report_lines.append("## Detailed Findings")
    report_lines.append("")
    for a in accumulated:
        report_lines.append(f"### Iteration (q): {a['aspect']}")
        report_lines.append("")
        report_lines.append(f"**Search query:** {a.get('search_query', '')}")
        report_lines.append("")
        for r in a["results"][:6]:
            eng = r.get("engine", "web")
            report_lines.append(f"- [{eng}] [{r['title'][:70]}]({r['url']})")
            if r.get("snippet"):
                report_lines.append(f"  {r['snippet'][:120]}")
        report_lines.append("")
        # Log fetched pages
        if a.get("pages"):
            report_lines.append("**Полные тексты:**")
            for p in a["pages"]:
                report_lines.append(f"- [{p['title'][:50]}]({p['url']}) — {len(p['content'])} chars")
            report_lines.append("")
        report_lines.append(f"**Анализ:** {a['analysis']}")
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("")

    report_lines.append("## Research Brief")
    report_lines.append("")
    report_lines.append(brief)
    report_lines.append("")
    report_lines.append("---")
    report_lines.append(f"*Research completed: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    report_lines.append("*RESEARCHER Agent v3*")

    report_text = "\n".join(report_lines)

    # Save local report
    safe_topic = re.sub(r"[^a-zA-Z0-9Ѐ-ӿ_-]", "_", topic.lower())[:40]
    out_file = AGENT_DIR / f"research_{safe_topic}_{date_str}.md"
    out_file.write_text(report_text)

    log(f"Report saved: {out_file}")

    # Print the research brief
    print("\n" + "=" * 60)
    print("  RESEARCH BRIEF")
    print("=" * 60)
    print()
    print(brief)
    print()
    print("=" * 60)
    print(f"  Full report: {out_file}")
    print("=" * 60)

    # Save brief to Obsidian
    log("Saving brief to Obsidian...")
    save_brief_to_obsidian(topic, brief, date_str)

    # Email if requested
    if send_email_flag:
        html_brief = md_to_html(brief)
        email_report(f"Research: {topic}", brief, html=html_brief)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""BACKEND EDUCATOR Agent — generates backend tips for manual testers.

Topics focus on backend nuances: Postman, databases, HTTP, API design, etc.
No programming instruction. Two modes: daily tip and weekly digest.
"""

import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

AGENT_DIR = Path(__file__).parent
HISTORY_FILE = AGENT_DIR / "history.json"
OUTPUT_DIR = AGENT_DIR / "tips"
TOPICS_FILE = AGENT_DIR / "topics.json"


# -- Channel context --------------------------------------------------
def get_channel_posts(count=15):
    """Read last N posts from eddytester channel."""
    raw_file = Path("/root/blog-analysis/data/eddytester_raw.json")
    if not raw_file.exists():
        return []
    try:
        data = json.loads(raw_file.read_text())
        msgs = data.get("messages", []) if isinstance(data, dict) else data
    except Exception:
        return []
    texts = []
    for m in reversed(msgs):
        t = m.get("text", "")
        if isinstance(t, list):
            t = " ".join(x if isinstance(x, str) else x.get("text", "") for x in t)
        t = t.strip()
        if t:
            texts.append(t)
        if len(texts) >= count:
            break
    return texts


def get_content_plan():
    """Read this week's content plan if it exists."""
    plans = sorted(Path("/root/blog-analysis/data").glob("eddytester-content-plan-*.md"))
    if not plans:
        return ""
    return plans[-1].read_text()


def score_topic_relevance(topic, posts, plan):
    """Score how relevant a topic is to recent posts + content plan."""
    text_lower = (topic["topic"] + " " + topic["why"] + " " + topic["tip"]).lower()
    score = 0
    for p in posts:
        p_lower = p.lower()
        for word in text_lower.split():
            if len(word) > 3 and word in p_lower:
                score += 1
    if plan:
        plan_lower = plan.lower()
        for word in text_lower.split():
            if len(word) > 3 and word in plan_lower:
                score += 2
    return score


def pick_best_topic(available, posts, plan):
    """Pick the most relevant topic, fall back to random."""
    scored = [(t, score_topic_relevance(t, posts, plan)) for t in available]
    scored.sort(key=lambda x: -x[1])
    if scored and scored[0][1] >= 3:
        return scored[0][0]
    return random.choice(available)
# ------------------------------------------------------------------
TOPICS = [
    {
        "topic": "Postman: Collections & Environments",
        "why": "Organize API tests, switch between dev/staging/prod without editing URLs manually",
        "tip": "Use environment variables ({{base_url}}, {{token}}) in collections. Export/import collections to share test suites with the team.",
        "tags": ["postman", "api", "basics"],
    },
    {
        "topic": "Postman: Pre-request Scripts",
        "why": "Automate setup logic (auth tokens, timestamps, dynamic data) before each request",
        "tip": "Use pm.variables.set() in Pre-request Script to compute request payloads. Great for generating unique test data on each run.",
        "tags": ["postman", "api", "automation"],
    },
    {
        "topic": "Postman: Tests Tab & Assertions",
        "why": "Validate API responses automatically without manual checking",
        "tip": "Use pm.test() and pm.expect() in the Tests tab. Check status codes, response time (< 200ms), and JSON body structure.",
        "tags": ["postman", "api", "testing"],
    },
    {
        "topic": "Postman: Newman CLI Runner",
        "why": "Run Postman collections in CI/CD pipelines or cron jobs",
        "tip": "newman run collection.json -e env.json --reporters cli,junit. Use --iteration-count to repeat tests, --timeout-request for SLAs.",
        "tags": ["postman", "automation", "devops"],
    },
    {
        "topic": "SQL: INNER JOIN vs LEFT JOIN",
        "why": "Wrong join type = missing or duplicate data in test results",
        "tip": "INNER JOIN returns only matching rows in both tables. LEFT JOIN returns ALL left-table rows + matches from right (NULLs where no match). Always check which you need in test assertions.",
        "tags": ["sql", "database", "basics"],
    },
    {
        "topic": "SQL: EXPLAIN Query Plan",
        "why": "See how the DB actually executes your query, spot missing indexes",
        "tip": "Run EXPLAIN ANALYZE SELECT ... (PostgreSQL). Look for 'Seq Scan' on large tables — that means a full table scan. Add indexes for WHERE/ JOIN columns.",
        "tags": ["sql", "database", "performance"],
    },
    {
        "topic": "SQL: GROUP BY & Aggregation Gotchas",
        "why": "Most common SQL mistakes in test validation come from misunderstanding GROUP BY",
        "tip": "Every column in SELECT must be either in GROUP BY or wrapped in an aggregate (COUNT, SUM, MAX, etc.). PostgreSQL is strict; MySQL is lenient (silent wrong data!).",
        "tags": ["sql", "database", "gotchas"],
    },
    {
        "topic": "SQL: Transactions & Rollback",
        "why": "Understand how atomic operations work — critical for testing payment/order flows",
        "tip": "BEGIN; ... COMMIT; makes multiple operations atomic. ROLLBACK; undoes all changes. Test that partial failures don't leave half-applied data (e.g., payment captured but order not created).",
        "tags": ["sql", "database", "testing"],
    },
    {
        "topic": "Database Migrations",
        "why": "Migrations change schema — tests must account for backward compatibility",
        "tip": "Test that rollback (down migration) works before deploying. Check that adding a NOT NULL column with existing data doesn't fail. New columns should have defaults or allow NULLs initially.",
        "tags": ["database", "devops", "testing"],
    },
    {
        "topic": "N+1 Query Problem",
        "why": "The most common performance bug in ORM-based apps (Rails, Django, Hibernate)",
        "tip": "1 query for parent list + N queries for each child = terrible performance. Signs: API returns fast for 1 item but slow for 100. Fix: use eager loading (.includes, .select_related). Test by checking DB log.",
        "tags": ["sql", "database", "performance", "gotchas"],
    },
    {
        "topic": "HTTP Status Codes: 2xx & 3xx",
        "why": "Knowing status codes helps you catch backend misconfigurations fast",
        "tip": "200 OK (success), 201 Created (POST resource), 204 No Content (DELETE), 301 Moved Permanently, 302 Found (temporary redirect), 304 Not Modified (caching). 2xx doesn't mean data is correct — always validate body too!",
        "tags": ["http", "api", "basics"],
    },
    {
        "topic": "HTTP Status Codes: 4xx & 5xx",
        "why": "Distinguish client vs server errors — tells you who to blame",
        "tip": "400 Bad Request (client sent bad data), 401 Unauthorized (no auth), 403 Forbidden (no permission), 404 Not Found, 409 Conflict (duplicate/state conflict), 422 Unprocessable (validation failed), 429 Too Many Requests, 500 Internal Server Error (backend bug), 502 Bad Gateway, 503 Service Unavailable.",
        "tags": ["http", "api", "basics"],
    },
    {
        "topic": "CORS (Cross-Origin Resource Sharing)",
        "why": "Frontend can't call API = your ticket will say 'CORS error' not 'backend bug'",
        "tip": "CORS headers (Access-Control-Allow-Origin) come from the server. Preflight OPTIONS request happens before actual request for non-simple methods. Test with curl -H 'Origin: https://example.com' -X OPTIONS.",
        "tags": ["http", "api", "security"],
    },
    {
        "topic": "Content Negotiation (Accept / Content-Type)",
        "why": "API can return JSON, XML, or something else — test that right format comes back",
        "tip": "Client sends Accept: application/json → server should return Content-Type: application/json. If Accept is missing, what does the server default to? Test with different Accept values including */*.",
        "tags": ["http", "api", "testing"],
    },
    {
        "topic": "API Idempotency",
        "why": "Retrying a request shouldn't create duplicate orders/payments",
        "tip": "Idempotency key (Idempotency-Key header): client sends unique key, server ignores duplicate requests. Critical for payment APIs. Test: send same request twice with same key → expect same response, no side effects.",
        "tags": ["api", "design", "testing"],
    },
    {
        "topic": "API Pagination",
        "why": "APIs limit results — find ALL items across pages",
        "tip": "Common patterns: page/limit, cursor-based, offset. Test: page 1 returns first N items, requesting page beyond last returns empty. Try negative page numbers, string page params, huge page sizes.",
        "tags": ["api", "design", "testing"],
    },
    {
        "topic": "Rate Limiting (429 Too Many Requests)",
        "why": "Apps break when hitting rate limits in production",
        "tip": "Check Retry-After header in 429 responses. Test: send requests above limit → verify 429 + retry time. Rate limits may be per-IP, per-user, or per-endpoint. Know which applies to your test scenario.",
        "tags": ["api", "security", "testing"],
    },
    {
        "topic": "API Versioning",
        "why": "Backward compatibility — old clients should still work after updates",
        "tip": "Versions in URL (/v1/, /v2/) or header (Accept: application/vnd.api+json;version=2). Test: old version still returns expected format, deprecation warnings appear in headers (Sunset, Deprecation).",
        "tags": ["api", "design", "testing"],
    },
    {
        "topic": "HATEOAS & REST Discovery",
        "why": "Some APIs return links for next actions — test the full flow",
        "tip": "Response includes 'links' object with 'self', 'next', 'related' URLs. Test: follow the links programmatically instead of hardcoding URLs. Break a link → check that error is handled gracefully.",
        "tags": ["api", "design", "advanced"],
    },
    {
        "topic": "ETag & Conditional Requests",
        "why": "Caching headers that save bandwidth and speed up your app",
        "tip": "Server returns ETag (hash of resource). Client sends If-None-Match with that hash → server returns 304 Not Modified if unchanged. Test: verify 304 has no body, verify ETag changes when resource updates.",
        "tags": ["http", "api", "performance"],
    },
    {
        "topic": "WebSocket Basics",
        "why": "Real-time features (chats, notifications) use WebSocket, not HTTP",
        "tip": "WebSocket connection starts as HTTP upgrade (101 Switching Protocols). Messages are frames, not HTTP requests. Test: use wscat or Postman WebSocket. Check reconnection behavior on disconnect.",
        "tags": ["websocket", "api", "testing"],
    },
    {
        "topic": "Webhook Testing",
        "why": "Async callbacks from external services (payments, deliveries)",
        "tip": "Webhooks POST to your callback URL with event data. Test: use webhook.site or ngrok to receive. Check: retry policy on failure, signature verification (HMAC), idempotency, timeout handling.",
        "tags": ["webhook", "api", "testing"],
    },
    {
        "topic": "gRPC Basics for Testers",
        "why": "gRPC is replacing REST in microservices — different testing approach",
        "tip": "gRPC uses Protocol Buffers (protobuf) for serialization, HTTP/2 for transport. Tools: grpcurl, Postman gRPC, BloomRPC. Messages are binary, not JSON. Check service reflection for discovery.",
        "tags": ["grpc", "api", "advanced"],
    },
    {
        "topic": "JWT (JSON Web Tokens)",
        "why": "Most common auth mechanism — understand what's in the token",
        "tip": "JWT has 3 parts: header.payload.signature (base64url-encoded). Decode at jwt.io. Check: token expiration (exp claim), algorithm confusion attacks (change alg to 'none'), signature validation failures.",
        "tags": ["auth", "security", "api"],
    },
    {
        "topic": "Sessions vs Tokens",
        "why": "Two fundamentally different auth models — each affects testing differently",
        "tip": "Session: server stores session, client sends cookie. Token (JWT): everything in token, server is stateless. Sessions are easier to revoke (delete server-side), tokens need a blocklist. Test: logout, token refresh, session expiry.",
        "tags": ["auth", "api", "design"],
    },
    {
        "topic": "Connection Pooling",
        "why": "Why your test might pass locally but fail on staging with DB errors",
        "tip": "DB connections are pooled (reused). Symptoms of pool exhaustion: occasional 'timeout' errors under load, 'too many connections' error. Test: open many concurrent requests, check that connections are released. Default pool is often too small.",
        "tags": ["database", "performance", "gotchas"],
    },
    {
        "topic": "Circuit Breaker Pattern",
        "why": "When external service fails, your app should degrade gracefully, not hang",
        "tip": "Circuit breaker: CLOSED (normal) → OPEN (failing) → HALF-OPEN (testing). Test: disable downstream service → verify fallback response (not 500). Check recovery after service comes back.",
        "tags": ["api", "design", "advanced"],
    },
    {
        "topic": "Logging & Correlation IDs",
        "why": "Debug production issues by tracing a request across multiple services",
        "tip": "Correlation ID (X-Request-ID) is passed through all services in a request chain. Test: send request with your own X-Request-ID → find it in all service logs. If missing, bug report filed.",
        "tags": ["api", "testing", "devops"],
    },
    {
        "topic": "Message Queues (RabbitMQ, Kafka)",
        "why": "Async processing — user gets response immediately, work happens later",
        "tip": "Messages are published to queues/exchanges, consumed asynchronously. Test: publish a message, verify consumer processes it (may take seconds). Check: message persistence, dead letter queues (failed messages), delivery guarantees (at-most-once, at-least-once).",
        "tags": ["queue", "api", "advanced"],
    },
    {
        "topic": "HTTP Method Semantics",
        "why": "GET/POST/PUT/PATCH/DELETE have specific meanings — wrong method = wrong behavior",
        "tip": "GET = read (idempotent, safe — no side effects). POST = create (not idempotent). PUT = full replace (idempotent). PATCH = partial update. DELETE = remove. Test: send GET with body, POST without body, PUT missing fields, PATCH with read-only fields.",
        "tags": ["http", "api", "basics"],
    },
]


def load_history():
    """Load history of previously sent topics to avoid repeats."""
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE) as f:
            return json.load(f)
    return {"sent_topics": [], "last_digest": None}


def save_history(history):
    """Save history."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)


def get_available_topics(history):
    """Return topics not yet sent (or reset if all sent)."""
    sent = set(history.get("sent_topics", []))
    available = [t for t in TOPICS if t["topic"] not in sent]
    if not available:
        # All topics sent — reset history
        history["sent_topics"] = []
        save_history(history)
        available = list(TOPICS)
    return available


def generate_tip(topic):
    """Generate a formatted tip from a topic dict."""
    now = datetime.now().strftime("%Y-%m-%d")
    return f"""# Backend Tip: {topic['topic']}
📅 {now}

## Зачем это нужно
{topic['why']}

## Совет
{topic['tip']}

## Теги
{' '.join(f'#{t}' for t in topic['tags'])}
"""


def generate_weekly_digest(topics):
    """Generate a weekly digest from multiple topics."""
    now = datetime.now().strftime("%Y-%m-%d")
    lines = [f"# Weekly Backend Digest ({now})", ""]
    lines.append(f"## Содержание ({len(topics)} тем)")
    for i, t in enumerate(topics, 1):
        tags_str = " ".join(f"#{tag}" for tag in t["tags"])
        lines.append(f"{i}. **{t['topic']}** ({tags_str})")
    lines.append("")
    lines.append("---")
    lines.append("")

    for t in topics:
        lines.append(f"## {t['topic']}")
        lines.append("")
        lines.append(f"**Зачем:** {t['why']}")
        lines.append("")
        lines.append(f"**Совет:** {t['tip']}")
        lines.append("")
        tags_str = " ".join(f"#{tag}" for tag in t["tags"])
        lines.append(f"Теги: {tags_str}")
        lines.append("")
        lines.append("----")
        lines.append("")

    return "\n".join(lines)


def run_daily():
    """Generate and save a daily tip with channel context."""
    posts = get_channel_posts(15)
    plan = get_content_plan()
    history = load_history()
    available = get_available_topics(history)
    if posts or plan:
        choice = pick_best_topic(available, posts, plan)
    else:
        choice = random.choice(available)
    tip = generate_tip(choice)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    filepath = OUTPUT_DIR / f"tip_{date}.md"
    with open(filepath, "w") as f:
        f.write(tip)

    # Mark as sent
    history.setdefault("sent_topics", []).append(choice["topic"])
    save_history(history)

    print(f"[educator] Daily tip saved: {filepath}")
    print(tip)
    return tip


def run_weekly():
    """Generate and save a weekly digest (5-7 topics)."""
    history = load_history()
    available = get_available_topics(history)
    count = min(random.randint(5, 7), len(available))
    chosen = random.sample(available, count)
    digest = generate_weekly_digest(chosen)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    filepath = OUTPUT_DIR / f"weekly_{date}.md"
    with open(filepath, "w") as f:
        f.write(digest)

    history.setdefault("sent_topics", []).extend(t["topic"] for t in chosen)
    save_history(history)

    print(f"[educator] Weekly digest saved: {filepath}")
    print(digest)
    return digest


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if mode == "weekly":
        run_weekly()
    else:
        run_daily()


if __name__ == "__main__":
    main()

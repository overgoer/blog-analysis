#!/usr/bin/env python3
"""Insights — DeepSeek-powered analysis of high-engagement posts."""
import json, os, subprocess
from config import ENGAGEMENT_WEIGHTS, NOTABLE_PERCENTILE


def _compute_engagement(post: dict) -> float:
    w = ENGAGEMENT_WEIGHTS
    return post.get("views", 0) * w["views"] \
         + post.get("replies_count", 0) * w["replies"] \
         + post.get("forwards", 0) * w["forwards"]


def _call_deepseek(text: str, context: str = "") -> dict:
    """Analyze a post via DeepSeek. Returns {analysis, why_works}."""
    prompt = f"""Ты — аналитик Telegram-каналов в нише QA / API-тестирования.

Проанализируй этот пост и ответь строго в JSON:
{{"analysis": "краткий анализ (2-3 предложения на русском)", "why_works": "почему пост залетел/не залетел (1-2 предложения)"}}

Контекст канала: {context}

Текст поста:
{text[:1500]}"""

    try:
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            # Try .env
            env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
            if os.path.exists(env_path):
                for line in open(env_path):
                    if line.startswith("DEEPSEEK_API_KEY="):
                        key = line.strip().split("=", 1)[1]
                        break

        if not key:
            return {"analysis": "Нет API ключа", "why_works": "Не удалось проанализировать"}

        payload = json.dumps({
            "model": "deepseek-v4-flash",
            "messages": [{"role": "system", "content": "Ты аналитик контента. Отвечай только в JSON."},
                         {"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
        })

        result = subprocess.run(
            ["curl", "-s", "-X", "POST", "https://api.deepseek.com/chat/completions",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, text=True, timeout=30
        )

        resp = json.loads(result.stdout)
        content = resp["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        return {"analysis": f"Ошибка анализа: {e}", "why_works": "Причина не определена"}


def _get_category(text: str) -> str:
    """Keyword-based category detection."""
    from config import CATEGORY_KEYWORDS
    text_lower = text.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                return cat
    return "other"


def analyze_channel(channel_id: int, channel_name: str, posts: list, category_map: dict = None) -> list:
    """Analyze posts: classify, rank by engagement, DeepSeek top percentile."""
    from db import mark_notable, get_posts_for_analysis

    if not posts:
        return []

    # Classify all posts
    for p in posts:
        if not p.get("category") or p["category"] == "other":
            p["category"] = _get_category(p.get("text", ""))

    # Rank by engagement
    ranked = sorted(posts, key=_compute_engagement, reverse=True)
    top_n = max(1, len(ranked) * NOTABLE_PERCENTILE // 100)

    notable_results = []
    for p in ranked[:top_n]:
        engagement = _compute_engagement(p)
        # Skip if engagement is zero
        if engagement == 0:
            continue

        context = f"Канал: {channel_name}"
        analysis = _call_deepseek(p.get("text", ""), context)

        marked = mark_notable(
            post_id=p["id"],
            analysis=analysis.get("analysis", ""),
            why_works=analysis.get("why_works", ""),
            category=p.get("category", "other"),
        )

        if marked:
            notable_results.append(marked)

    return notable_results

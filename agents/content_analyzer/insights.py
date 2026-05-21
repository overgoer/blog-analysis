#!/usr/bin/env python3
"""Insights — DeepSeek-powered analysis of high-engagement posts."""
import json, os, subprocess
from config import ENGAGEMENT_WEIGHTS, NOTABLE_PERCENTILE


def _compute_engagement(post: dict) -> float:
    w = ENGAGEMENT_WEIGHTS
    return post.get("views", 0) * w["views"] \
         + post.get("replies_count", 0) * w["replies"] \
         + post.get("forwards", 0) * w["forwards"]


def _call_deepseek(text: str, context: str = "", media_type: str = "text") -> dict:
    """Analyze a post via DeepSeek. Returns {analysis, why_works}."""
    media_note = ""
    if media_type != "text":
        media_note = f"\n⚠️ ВАЖНО: Этот пост содержит {media_type}. Ты видишь только подпись, а не сам {media_type}. Не придумывай анализ того, чего не видел."
    prompt = f"""Ты — аналитик Telegram-каналов в нише QA / API-тестирования.

Проанализируй этот пост и ответь строго в JSON:
{{"analysis": "краткий анализ (2-3 предложения на русском)", "why_works": "почему пост залетел/не залетел (1-2 предложения)"}}

ПРАВИЛА:
1. Если в посте есть медиа (видео/фото), а ты видишь только текст — скажи честно: "пост содержит [media], текст не позволяет оценить"
2. Не пиши "пост залетает из-за юмора/релевантности", если это пустая общая фраза
3. Если пост не набрал реакций — скажи "пост не залетел"
4. Отвечай только на русском
5. Говори коротко и по делу, без воды{media_note}

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
        views = p.get("views", 0) or 0
        # Skip posts with very low true engagement — views alone don't count
        if engagement < 100 and views < 500:
            continue

        context = f"Канал: {channel_name}"
        media_type = p.get("media_type", "text")
        analysis = _call_deepseek(p.get("text", ""), context, media_type)

        marked = mark_notable(
            post_id=p["id"],
            analysis=analysis.get("analysis", ""),
            why_works=analysis.get("why_works", ""),
            category=p.get("category", "other"),
        )

        if marked:
            notable_results.append(marked)

    return notable_results

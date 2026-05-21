#!/usr/bin/env python3
"""Categorizer — keyword-based post classification. No API calls.

Classifies posts by:
- topic category (api/bugs, tools, career, etc.)
- intent goal (прогрев, экспертиза, продажа, hot_take, news, meta)

Can run standalone:  python3 categorizer.py  (classifies all uncategorized posts)
"""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from config import CATEGORY_KEYWORDS, GOAL_KEYWORDS


def _merged_keywords(category_type: str, base: dict) -> dict:
    """Merge runtime keyword overrides with base config, excluding suppressed keywords."""
    from runtime_config import get_keyword_overrides, get_suppressed_keywords
    merged = {k: list(v) for k, v in base.items()}
    # Add runtime overrides
    overrides = get_keyword_overrides(category_type)
    for cat, extra_kws in overrides.items():
        if cat in merged:
            for kw in extra_kws:
                if kw.lower() not in [w.lower() for w in merged[cat]]:
                    merged[cat].append(kw)
        else:
            merged[cat] = list(extra_kws)
    # Remove suppressed keywords
    suppressed = get_suppressed_keywords(category_type)
    for cat, sup_kws in suppressed.items():
        if cat in merged:
            for sk in sup_kws:
                merged[cat] = [kw for kw in merged[cat] if kw.lower() != sk.lower()]
    return merged


def classify_topic(text: str) -> str:
    """Classify post text into a topic category by keywords."""
    if not text:
        return "other"
    text_lower = text.lower()
    merged = _merged_keywords("CATEGORY_KEYWORDS", CATEGORY_KEYWORDS)
    for cat, keywords in merged.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                return cat
    return "other"


def classify_goal(text: str) -> str:
    """Classify post text into an intent goal by keywords."""
    if not text:
        return "other"
    text_lower = text.lower()
    merged = _merged_keywords("GOAL_KEYWORDS", GOAL_KEYWORDS)
    for goal, keywords in merged.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                return goal
    return "other"


def classify(text: str) -> dict:
    """Full classification of a post text. Returns {topic, goal}."""
    return {
        "topic": classify_topic(text),
        "goal": classify_goal(text),
    }


def batch_categorize(limit: int = 500) -> dict:
    """Classify all uncategorized posts in the database."""
    from db import get_uncategorized_posts, update_post_goal

    posts = get_uncategorized_posts(limit=limit)
    results = {"total": len(posts), "topic": {}, "goal": {}}
    db_updated = 0

    for p in posts:
        text = p.get("text", "") or ""
        topic = classify_topic(text)
        goal = classify_goal(text)

        if topic != "other" or goal != "other":
            from db import get_conn
            conn = get_conn()
            conn.execute(
                "UPDATE posts SET category = COALESCE(NULLIF(category, 'other'), ?), "
                "goal = COALESCE(NULLIF(goal, 'other'), ?), "
                "updated_at = datetime('now') WHERE id = ?",
                (topic if p.get("category", "other") in ("other", "", None) else p["category"],
                 goal if p.get("goal", "other") in ("other", "", None) else p["goal"],
                 p["id"])
            )
            conn.commit()
            conn.close()
            db_updated += 1

        results["topic"][topic] = results["topic"].get(topic, 0) + 1
        results["goal"][goal] = results["goal"].get(goal, 0) + 1

    return results


def main():
    """Standalone: classify uncategorized posts."""
    import db
    db.init_db()

    print("📊 Batch categorizing posts...")
    r = batch_categorize(limit=2000)
    print(f"  Posts checked: {r['total']}")
    print(f"  Topic distribution: {dict(sorted(r['topic'].items(), key=lambda x: -x[1]))}")
    print(f"  Goal distribution: {dict(sorted(r['goal'].items(), key=lambda x: -x[1]))}")
    return r


if __name__ == "__main__":
    main()

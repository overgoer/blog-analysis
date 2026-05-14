#!/usr/bin/env python3
"""
Content Map — post index for cross-referencing.

Tracks all posts by tags + summary. GA uses this to find
relevant past posts when writing new content.

Usage:
    from content_map import ContentMap, tag_post
    cm = ContentMap()
    cm.update_index(date, title, angle, ["api", "testing"], "summary", "/path/to/post.md")
    relevant = cm.find_relevant(["api", "testing"])
"""

import json
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent  # /tmp/blog-analysis
INDEX_FILE = BASE / "data" / "content_map_index.json"


class ContentMap:
    """Persistent index of posts with tags for relevance queries."""

    def __init__(self):
        self.index = self._load()

    def _load(self):
        if INDEX_FILE.exists():
            try:
                return json.loads(INDEX_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _save(self):
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        INDEX_FILE.write_text(
            json.dumps(self.index, indent=2, ensure_ascii=False)
        )

    def update_index(self, date, title, angle, tags, summary, file_path):
        """Add or update an entry. Avoids duplicates by file_path."""
        file_path = str(file_path)
        for entry in self.index:
            if entry["file_path"] == file_path:
                entry.update({
                    "date": date,
                    "title": title,
                    "angle": angle,
                    "tags": tags,
                    "summary": summary,
                })
                self._save()
                return entry
        entry = {
            "date": date,
            "title": title,
            "angle": angle,
            "tags": tags,
            "summary": summary,
            "file_path": file_path,
        }
        self.index.append(entry)
        self._save()
        return entry

    def find_relevant(self, words, top_n=3):
        """Find top-N posts by tag overlap with given words/tags."""
        if not self.index or not words:
            return []
        query = set(w.lower().strip(",.!?") for w in words if len(w) > 2)
        scored = []
        for entry in self.index:
            entry_tags = set(t.lower() for t in entry.get("tags", []))
            matches = 0
            for tag in entry_tags:
                for q in query:
                    if q in tag or tag in q:
                        matches += 1
                        break
            if matches > 0:
                scored.append((matches, entry))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:top_n]]


def tag_post(post_title, post_content, dk_func):
    """Generate tags + summary for a post via DeepSeek.

    Args:
        post_title: Title/topic of the post
        post_content: Full post text
        dk_func: A callable(system, user, temperature, max_tokens) -> str

    Returns:
        dict with "tags" (list) and "summary" (str), or None on failure.
    """
    system = (
        "You are a content tagger. Given a post, generate 3-5 tags "
        "(lowercase, hyphen-separated if multi-word) and a 1-line summary in Russian.\n\n"
        "Format:\n"
        "TAGS: tag1, tag2, tag3\n"
        "SUMMARY: one-line summary of the post\n\n"
        "Rules:\n"
        "- Tags should reflect the post's technical category (e.g. http, api, testing, bugs, tools)\n"
        "- Summary: 1 sentence in Russian, what the post is about\n"
        "- No other text."
    )
    user = (
        f"Title: {post_title[:200]}\n\n"
        f"Content:\n{post_content[:3000]}"
    )
    result = dk_func(system, user, temperature=0.3, max_tokens=200)
    if not result or result.startswith("ERROR"):
        return None

    tags = []
    summary = ""
    for line in result.strip().split("\n"):
        line = line.strip()
        if line.upper().startswith("TAGS:") or line.upper().startswith("TAGS :"):
            raw = line.split(":", 1)[1].strip()
            tags = [t.strip().lower() for t in raw.split(",") if t.strip()]
        elif line.upper().startswith("SUMMARY:") or line.upper().startswith("SUMMARY :"):
            summary = line.split(":", 1)[1].strip()

    if not tags and not summary:
        return None
    return {"tags": tags, "summary": summary}

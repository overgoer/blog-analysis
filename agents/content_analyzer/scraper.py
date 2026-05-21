#!/usr/bin/env python3
"""Scraper — Telegram channel scraper via tdl."""
import subprocess, json, re
from datetime import datetime
from pathlib import Path
from typing import Optional

TDL = "/usr/local/bin/tdl"


def _parse_tdl_post(raw: dict) -> Optional[dict]:
    """Parse a single tdl post dict into our schema."""
    try:
        msg = raw.get("message", raw)
        msg_id = msg.get("id", 0)
        if not msg_id:
            return None

        text = ""
        content = msg.get("content", {})
        media_type = "text"

        if "text" in content:
            txt_parts = content["text"]
            if isinstance(txt_parts, list):
                text = "".join(p if isinstance(p, str) else p.get("text", "") for p in txt_parts)
            else:
                text = str(txt_parts)
        if not text and "caption" in content:
            text = content["caption"].get("text", "")

        if "photo" in content:
            media_type = "photo"
        elif any(k in content for k in ("video", "animation", "voice", "video_note")):
            media_type = "video"
        elif "document" in content:
            media_type = "document"

        views = msg.get("views", 0)
        forwards = msg.get("forwards", 0)
        reply_count = 0
        if "interaction_info" in msg:
            reply_info = msg["interaction_info"].get("reply_info", {})
            reply_count = reply_info.get("reply_count", 0)

        posted_at = msg.get("date", "")
        if isinstance(posted_at, int):
            posted_at = datetime.utcfromtimestamp(posted_at).isoformat()

        return {
            "tg_post_id": msg_id,
            "posted_at": posted_at,
            "text": text.strip()[:1000],
            "views": views or 0,
            "forwards": forwards or 0,
            "replies_count": reply_count or 0,
            "media_type": media_type,
        }
    except Exception:
        return None


def export_messages(channel: str, limit: int = 50) -> list:
    """Export messages from a Telegram channel via tdl."""
    cmd = [TDL, "chat", "export", "-c", channel, "-n", str(limit), "--format", "json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"tdl error: {result.stderr[:500]}")

    posts = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            parsed = _parse_tdl_post(raw)
            if parsed:
                posts.append(parsed)
        except json.JSONDecodeError:
            continue

    return posts


def scrape_channel(channel_name: str) -> tuple:
    """Scrape a channel and save posts to DB. Returns (new_count, total_count)."""
    from db import get_channel_by_name, upsert_post, update_channel_scrape, get_posts_for_analysis

    ch = get_channel_by_name(channel_name)
    if not ch:
        raise ValueError(f"Channel {channel_name} not found in DB")

    posts = export_messages(channel_name, limit=50)
    new = 0
    for p in posts:
        if upsert_post(
            ch["id"], p["tg_post_id"], p["posted_at"], p["text"],
            p["views"], p["forwards"], p["replies_count"], p["media_type"],
        ):
            new += 1

    update_channel_scrape(ch["id"])
    total = len(get_posts_for_analysis(ch["id"], limit=999999))
    return new, len(posts)

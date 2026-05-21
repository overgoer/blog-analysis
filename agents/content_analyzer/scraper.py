#!/usr/bin/env python3
"""Scraper — Telegram channel scraper via tdl (tdl 0.20.2+)."""
import json, subprocess, tempfile, os
from datetime import datetime
from pathlib import Path
from typing import Optional

TDL = "/usr/local/bin/tdl"


def _parse_tdl_post(msg: dict) -> Optional[dict]:
    """Parse a tdl 0.20.2 message dict into our schema."""
    try:
        msg_id = msg.get("id", 0)
        if not msg_id:
            return None

        text = msg.get("text", "") or ""
        media_type = "photo" if msg.get("file") else "text"

        posted_at = msg.get("date", "")
        if isinstance(posted_at, (int, float)):
            posted_at = datetime.utcfromtimestamp(posted_at).isoformat()

        return {
            "tg_post_id": msg_id,
            "posted_at": posted_at,
            "text": text.strip()[:1000],
            "views": msg.get("views", 0) or 0,
            "forwards": msg.get("forwards", 0) or 0,
            "replies_count": 0,
            "media_type": media_type,
        }
    except Exception:
        return None


def export_messages(channel: str, limit: int = 50) -> list:
    """Export messages from a Telegram channel via tdl 0.20.2."""
    tmp = tempfile.mktemp(suffix=".json")
    try:
        cmd = [TDL, "chat", "export", "-c", channel,
               "--type", "last", "--input", str(limit),
               "--output", tmp, "--with-content"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise RuntimeError(f"tdl error: {result.stderr[:500]}")

        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            return []

        data = json.loads(open(tmp, encoding="utf-8").read())
        raw_messages = data.get("messages", [])

        posts = []
        for msg in raw_messages:
            parsed = _parse_tdl_post(msg)
            if parsed:
                posts.append(parsed)
        return posts
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


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

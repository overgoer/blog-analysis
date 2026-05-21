#!/usr/bin/env python3
"""Scraper — Telegram channel scraper via Telethon (replaces tdl)."""
import os, asyncio
from datetime import datetime
from typing import Optional


def export_messages(channel: str, limit: int = 50) -> list:
    """Export messages from a Telegram channel via Telethon."""
    async def _fetch():
        from telethon import TelegramClient

        client = TelegramClient("/root/.telethon_edtext", 5, "1c5c96d5edd401b1ed40db3fb5633e2d")
        await client.start()
        try:
            entity = await client.get_entity(channel)
            messages = await client.get_messages(entity, limit=limit)
            posts = []
            for msg in messages:
                if not msg:
                    continue
                msg_id = msg.id
                posted_at = msg.date.isoformat() if msg.date else datetime.utcnow().isoformat()
                text = (msg.text or "").strip()[:1000]
                views = getattr(msg, "views", 0) or 0
                forwards = getattr(msg, "forwards", 0) or 0
                replies_count = msg.replies.replies if msg.replies else 0
                media_type = "text"
                if msg.photo:
                    media_type = "photo"
                elif msg.video:
                    media_type = "video"
                elif msg.document:
                    media_type = "document"
                posts.append({
                    "tg_post_id": msg_id,
                    "posted_at": posted_at,
                    "text": text,
                    "views": views,
                    "forwards": forwards,
                    "replies_count": replies_count,
                    "media_type": media_type,
                })
            return posts
        finally:
            await client.disconnect()

    try:
        return asyncio.run(_fetch())
    except Exception as e:
        raise RuntimeError(f"Telethon export failed: {e}")


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

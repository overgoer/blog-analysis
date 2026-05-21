#!/usr/bin/env python3
"""
Telegram Channel Downloader — скачивает посты из ЛЮБОГО Telegram канала.
Telethon-версия (replaces tdl). Для tdl-версии см. channel_downloader_legacy.py.

Возможности:
  - Любой канал (@username, ID)
  - Пакетная загрузка с паузами + offset_id пагинация
  - Поиск конкретного поста + комментарии
  - Экспорт в JSON и читаемый текст

Использование:
  python3 channel_downloader.py --channel @rvtsakunov --posts 200
  python3 channel_downloader.py --channel @rvtsakunov --posts 5000 --batch-size 200 --delay 2
  python3 channel_downloader.py --channel @eddytester --post 414
  python3 channel_downloader.py --channel @eddytester --post 414 --comments
  python3 channel_downloader.py --channel @channel --posts 50 --format text
"""

import argparse, asyncio, json, os, sys, time
from datetime import datetime

API_ID = 5
API_HASH = "1c5c96d5edd401b1ed40db3fb5633e2d"
SESSION = "/root/.telethon_edtext"

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "scout", "raw")


# ── helpers ──────────────────────────────────────────────────────────────────


def _msg_to_dict(msg, chat=None):
    """Convert a Telethon Message to a plain dict for JSON + formatting."""
    text = (msg.text or "").strip()
    reacts = []
    if msg.reactions and msg.reactions.results:
        for r in msg.reactions.results:
            emoji = getattr(r.reaction, "emoticon", "?") if r.reaction else "?"
            reacts.append({"emoji": emoji, "count": r.count or 0})
    has_media = bool(msg.photo or msg.video or msg.document)
    media_type = None
    if msg.photo:
        media_type = "photo"
    elif msg.video:
        media_type = "video"
    elif msg.document:
        media_type = "document"

    d = {
        "id": msg.id,
        "text": text,
        "date": msg.date.timestamp() if msg.date else 0,
        "date_iso": msg.date.isoformat() if msg.date else "",
        "views": getattr(msg, "views", 0) or 0,
        "forwards": getattr(msg, "forwards", 0) or 0,
        "reactions": reacts,
        "has_media": has_media,
        "media_type": media_type,
    }
    if chat:
        d["chat_id"] = chat
    return d


# ── single post ──────────────────────────────────────────────────────────────


def find_post(chat, target_id):
    """Find a specific post by ID via Telethon. Returns dict or {'error': ...}."""
    async def _run():
        from telethon import TelegramClient
        client = TelegramClient(SESSION, API_ID, API_HASH)
        await client.start()
        try:
            entity = await client.get_entity(chat)
            msg = await client.get_messages(entity, ids=target_id)
            if msg is None:
                return {"error": f"Post #{target_id} not found"}
            d = _msg_to_dict(msg, chat=chat)
            if msg.replies and msg.replies.channel_id:
                d["_replies_channel_id"] = msg.replies.channel_id
            return d
        finally:
            await client.disconnect()

    return asyncio.run(_run())


def fetch_comments(post_chat, post_id):
    """Fetch comments for a channel post. Returns {'messages': [...]} or {'error': ...}."""
    async def _run():
        from telethon import TelegramClient
        from telethon.tl.types import PeerChannel

        client = TelegramClient(SESSION, API_ID, API_HASH)
        await client.start()
        try:
            # Get the post to find discussion group
            entity = await client.get_entity(post_chat)
            msg = await client.get_messages(entity, ids=post_id)
            if not msg:
                return {"error": f"Post #{post_id} not found"}
            if not msg.replies or not msg.replies.channel_id:
                return {"error": "No discussion group"}

            # Fetch discussion group messages
            try:
                discussion = await client.get_entity(PeerChannel(msg.replies.channel_id))
                group_msgs = await client.get_messages(discussion, limit=500)
            except Exception as e:
                return {"error": f"Discussion group error: {e}"}

            # Find forwarded post in group
            thread_id = None
            for gm in group_msgs:
                if gm.fwd_from and gm.fwd_from.channel_post == post_id:
                    thread_id = gm.id
                    break

            if not thread_id:
                return {"messages": [], "meta": {"error": "No thread found"}}

            # Collect replies to that thread
            comments = []
            for gm in group_msgs:
                if gm.reply_to and gm.reply_to.reply_to_msg_id == thread_id:
                    comments.append(_msg_to_dict(gm))

            return {"messages": comments}
        finally:
            await client.disconnect()

    return asyncio.run(_run())


# ── batch download ──────────────────────────────────────────────────────────


def download_channel(chat, total_needed, batch_size=200, delay=2):
    """Download posts with batching and offset_id pagination via Telethon."""
    async def _run():
        from telethon import TelegramClient

        client = TelegramClient(SESSION, API_ID, API_HASH)
        await client.start()
        try:
            entity = await client.get_entity(chat)
            all_msgs = []
            last_id = None

            print(f"📥 {chat}: {total_needed} постов, пакетами по {batch_size}, "
                  f"пауза {delay}с", file=sys.stderr)

            while len(all_msgs) < total_needed:
                remaining = total_needed - len(all_msgs)
                limit = min(batch_size, remaining)

                kwargs = {"limit": limit}
                if last_id:
                    kwargs["offset_id"] = last_id

                messages = await client.get_messages(entity, **kwargs)
                if not messages:
                    print(f"  ✅ Все посты скачаны (пакет пуст)", file=sys.stderr)
                    break

                # Deduplicate by ID
                existing_ids = {m["id"] for m in all_msgs}
                new_msgs = []
                for msg in messages:
                    if msg and msg.id not in existing_ids:
                        new_msgs.append(_msg_to_dict(msg, chat=chat))
                        existing_ids.add(msg.id)

                if not new_msgs:
                    print(f"  ✅ Начало канала (нет новых ID)", file=sys.stderr)
                    break

                batch_num = len(all_msgs) // batch_size + 1
                all_msgs.extend(new_msgs)
                oldest_id = min(m["id"] for m in new_msgs)

                print(f"  ✅ Пакет #{batch_num}: +{len(new_msgs)} постов "
                      f"(всего {len(all_msgs)}/{total_needed}, "
                      f"старый ID: {oldest_id})", file=sys.stderr)

                if len(new_msgs) < limit:
                    print(f"  ✅ Начало канала достигнуто", file=sys.stderr)
                    break

                last_id = oldest_id

                if len(all_msgs) < total_needed:
                    time.sleep(delay)

            return all_msgs
        finally:
            await client.disconnect()

    return asyncio.run(_run())


# ── formatting ──────────────────────────────────────────────────────────────


def format_post(d):
    """Format a post dict (from _msg_to_dict) for text display."""
    post_id = d["id"]
    text = d["text"][:1000] if d["text"] else "(no text)"
    date_str = datetime.fromtimestamp(d["date"]).strftime("%d.%m %H:%M") if d.get("date") else "?"
    media_flag = " 📸" if d.get("has_media") else ""

    reacts = d.get("reactions", [])
    react_str = " ".join(f"{r['emoji']}{r['count']}" for r in reacts) if reacts else ""

    lines = [
        f"📝 **Пост #{post_id}** ({date_str}){media_flag}",
        f"👁 {d['views']} просмотров · 🔁 {d['forwards']} репостов",
    ]
    if react_str:
        lines.append(react_str)
    lines.append("")
    lines.append(text)
    return "\n".join(lines)


def format_comment(d):
    """Format a comment dict for display."""
    text = d.get("text", "")
    text = text[:500] if text else "(no text)"
    if not d.get("text") and d.get("has_media"):
        text = "(media)"
    msg_id = d["id"]
    date_str = datetime.fromtimestamp(d["date"]).strftime("%d.%m %H:%M") if d.get("date") else "?"
    return f"  💬 **#{msg_id}** ({date_str}): {text}"


# ── high-level ──────────────────────────────────────────────────────────────


def download_single_post(chat, post_id, with_comments=False):
    """Download a specific post by ID + optionally comments."""
    data = find_post(chat, post_id)
    if isinstance(data, dict) and "error" in data:
        return f"❌ {data['error']}"
    if not data or "id" not in data:
        return "❌ Пост не найден"

    result = [format_post(data)]

    if with_comments:
        discussion_id = data.get("_replies_channel_id")
        if discussion_id:
            try:
                comments_data = fetch_comments(chat, post_id)
                if "error" not in comments_data:
                    comments = comments_data.get("messages", [])
                    if comments:
                        parts = [f"\n💬 **Комментарии ({len(comments)}):**"]
                        for c in comments:
                            parts.append(format_comment(c))
                        result.append("\n".join(parts))
                    else:
                        result.append("\n💬 Комментариев нет")
                else:
                    result.append(f"\n💬 Ошибка: {comments_data['error']}")
            except Exception as e:
                result.append(f"\n💬 Ошибка чтения комментариев: {e}")
        else:
            result.append("\n💬 Комментарии недоступны (нет группы обсуждения)")

    return "\n\n".join(result)


# ── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Telegram Channel Downloader (Telethon)")
    parser.add_argument("--channel", "-c", default="@eddytester",
                        help="Channel username (@name) or ID")
    parser.add_argument("--posts", "-p", type=int, default=0,
                        help="Number of recent posts to download (0 = disabled)")
    parser.add_argument("--batch-size", type=int, default=200,
                        help="Posts per batch (default: 200)")
    parser.add_argument("--delay", type=int, default=2,
                        help="Delay between batches in seconds (default: 2)")
    parser.add_argument("--post", type=int, default=None,
                        help="Download a specific post by ID")
    parser.add_argument("--comments", action="store_true",
                        help="Include comments (only with --post)")
    parser.add_argument("--format", choices=["text", "json", "summary"],
                        default="text",
                        help="Output format (default: text)")

    args = parser.parse_args()
    channel = args.channel

    if not channel.startswith("@") and not channel.lstrip("-").isdigit():
        channel = f"@{channel}"

    # Mode: specific post
    if args.post:
        result = download_single_post(channel, args.post, args.comments)
        print(result)
        return

    # Mode: batch download
    if args.posts <= 0:
        parser.print_help()
        return

    messages = download_channel(channel, args.posts, args.batch_size, args.delay)
    if not messages:
        print("❌ Нет постов")
        return

    # Save to raw directory for persistence
    os.makedirs(RAW_DIR, exist_ok=True)
    safe_name = channel.strip("@").replace(".", "_")
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(RAW_DIR, f"{safe_name}_{date_str}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"channel": channel, "total": len(messages),
                    "date": date_str, "messages": messages},
                  f, ensure_ascii=False, indent=2)

    if args.format == "json":
        print(json.dumps({"channel": channel, "total": len(messages),
                          "file": json_path}, ensure_ascii=False))

    elif args.format == "summary":
        newest = messages[0]
        newest_date = datetime.fromtimestamp(newest["date"]).strftime("%d.%m %H:%M") if newest.get("date") else "?"
        oldest = messages[-1]
        oldest_date = datetime.fromtimestamp(oldest["date"]).strftime("%d.%m %H:%M") if oldest.get("date") else "?"
        media_count = sum(1 for m in messages if m.get("has_media"))
        total_views = sum(m.get("views", 0) for m in messages)

        print(f"📊 **{channel}** — {len(messages)} постов")
        print(f"📅 {newest_date} → {oldest_date}")
        print(f"📸 {media_count} с медиа · 👁 {total_views} просмотров всего")
        print(f"💾 Сохранено: `{json_path}`")

    else:  # text — show first 50 posts
        formatted = [format_post(m) for m in messages[:50]]
        if len(messages) > 50:
            formatted.append(f"\n... и ещё {len(messages) - 50} постов")
            formatted.append(f"\n💾 Полный файл: `{json_path}`")
        print("\n\n---\n\n".join(formatted))


if __name__ == "__main__":
    main()

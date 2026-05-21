#!/usr/bin/env python3
"""
Channel Checker — читает посты из Telegram каналов через Telethon.

Поддерживает @eddytester и любые публичные каналы по ссылке.
Данные: текст, просмотры, репосты, реакции, комментарии.

Использование:
    python3 channel_checker.py                          # последний пост @eddytester
    python3 channel_checker.py --posts 3                # последние 3 поста
    python3 channel_checker.py --post 414               # конкретный пост
    python3 channel_checker.py --post 414 --comments    # пост + комментарии
    python3 channel_checker.py --url https://t.me/qa_channell/123  # любой канал
"""

import asyncio, sys, re
from datetime import datetime

from telethon import TelegramClient

API_ID = 5
API_HASH = "1c5c96d5edd401b1ed40db3fb5633e2d"
SESSION = "/root/.telethon_edtext"
CHANNEL = "@eddytester"
DISCUSSION_GROUP_ID = 1948889455


def parse_url(url):
    """Parse t.me URL into (chat_username, post_id) or (None, None)."""
    if not url:
        return None, None
    url = url.strip().replace("https://", "").replace("http://", "")
    m = re.match(r"t\.me/([^/\s?]+)/?(\d+)?", url)
    if m:
        chat = "@" + m.group(1)
        post_id = int(m.group(2)) if m.group(2) else None
        return chat, post_id
    return None, None


def format_post(msg):
    """Format a Telethon Message for display."""
    text = msg.text or ""
    text = text[:500] if text else "(media or no text)"

    date_str = msg.date.strftime("%d.%m %H:%M") if msg.date else "?"
    views = getattr(msg, "views", 0) or 0
    forwards = getattr(msg, "forwards", 0) or 0

    lines = [
        f"📝 **Пост #{msg.id}** ({date_str})",
        f"👁 {views} просмотров · 🔁 {forwards} репостов",
    ]

    reacts = []
    if msg.reactions and msg.reactions.results:
        for r in msg.reactions.results:
            emoticon = getattr(r.reaction, "emoticon", "?")
            reacts.append(f"{emoticon}{r.count}")
    if reacts:
        lines.append(f"❤️ {' '.join(reacts)}")

    if msg.replies and hasattr(msg.replies, "replies") and msg.replies.replies:
        lines.append(f"💬 Комментарии: {msg.replies.replies}")

    lines.append("")
    lines.append(text)
    return "\n".join(lines)


def format_comment(msg):
    """Format a single comment from Telethon Message."""
    text = msg.text or ""
    text = text[:500] if text else "(media or no text)"
    date_str = msg.date.strftime("%d.%m %H:%M") if msg.date else "?"
    return f"  💬 **Комментарий #{msg.id}** ({date_str}):\n  {text}"


async def get_comments(client, post_msg, source_channel=""):
    """Get comments for a channel post via its discussion group."""
    group_id = None
    if post_msg.replies and hasattr(post_msg.replies, "channel_id") and post_msg.replies.channel_id:
        group_id = post_msg.replies.channel_id

    if not group_id and source_channel == CHANNEL:
        group_id = DISCUSSION_GROUP_ID

    if not group_id:
        return []

    try:
        group_entity = await client.get_entity(group_id)
    except Exception:
        return []

    thread_starter_id = None
    async for grp_msg in client.iter_messages(group_entity, limit=100):
        fwd = getattr(grp_msg, "fwd_from", None)
        if fwd and getattr(fwd, "channel_post", None) == post_msg.id:
            thread_starter_id = grp_msg.id
            break

    if not thread_starter_id:
        return []

    comments = []
    async for grp_msg in client.iter_messages(group_entity, limit=200):
        if grp_msg.is_reply and grp_msg.reply_to:
            if getattr(grp_msg.reply_to, "reply_to_msg_id", None) == thread_starter_id:
                comments.append(grp_msg)

    comments.sort(key=lambda m: m.id)
    return comments


async def run_check(posts=1, post_id=None, url=None, with_comments=False):
    """Main logic: fetch post(s) and return formatted text."""
    client = TelegramClient(SESSION, API_ID, API_HASH)
    try:
        await client.start()
    except Exception as e:
        return f"❌ Ошибка подключения Telegram: {e}"

    try:
        if url:
            chat, url_post_id = parse_url(url)
            if not chat:
                return "❌ Не удалось разобрать URL. Пример: https://t.me/channel/123"
            target_post_id = post_id or url_post_id
            if not target_post_id:
                return "❌ Укажите номер поста в URL"

            try:
                msg = await client.get_messages(chat, ids=target_post_id)
            except ValueError as e:
                return f"❌ Канал {chat} не найден: {e}"
            except Exception as e:
                return f"❌ Ошибка доступа к {chat}: {e}"
            if not msg:
                return f"❌ Пост {target_post_id} не найден в {chat}"

            result = [format_post(msg)]

            if with_comments:
                try:
                    comments = await get_comments(client, msg, source_channel=chat)
                    if comments:
                        header = f"💬 Комментарии ({len(comments)}):"
                        parts = [header] + [format_comment(c) for c in comments]
                        result.append("\n".join(parts))
                    else:
                        result.append("\n💬 Комментариев нет")
                except Exception as e:
                    result.append(f"\n💬 Ошибка комментариев: {e}")

            return "\n\n---\n\n".join(result)

        elif post_id is not None:
            try:
                msg = await client.get_messages(CHANNEL, ids=post_id)
            except Exception as e:
                return f"❌ Ошибка доступа к каналу: {e}"
            if not msg:
                return f"❌ Пост {post_id} не найден"

            result = [format_post(msg)]

            if with_comments:
                try:
                    comments = await get_comments(client, msg, source_channel=CHANNEL)
                    if comments:
                        header = f"💬 Комментарии ({len(comments)}):"
                        parts = [header] + [format_comment(c) for c in comments]
                        result.append("\n".join(parts))
                    else:
                        result.append("\n💬 Комментариев нет")
                except Exception as e:
                    result.append(f"\n💬 Ошибка комментариев: {e}")

            return "\n\n---\n\n".join(result)

        else:
            try:
                msgs = await client.get_messages(CHANNEL, limit=posts)
            except Exception as e:
                return f"❌ Ошибка доступа к каналу: {e}"
            if not msgs:
                return "❌ Нет постов"
            return "\n\n---\n\n".join(format_post(m) for m in msgs)

    finally:
        await client.disconnect()


def main():
    args = sys.argv[1:]
    posts = 1
    post_id = None
    url = None
    with_comments = "--comments" in args

    if "--posts" in args:
        idx = args.index("--posts")
        if idx + 1 < len(args):
            posts = int(args[idx + 1])

    if "--post" in args:
        idx = args.index("--post")
        if idx + 1 < len(args):
            post_id = int(args[idx + 1])

    if "--url" in args:
        idx = args.index("--url")
        if idx + 1 < len(args):
            url = args[idx + 1]

    result = asyncio.run(run_check(posts=posts, post_id=post_id, url=url, with_comments=with_comments))
    print(result)


if __name__ == "__main__":
    main()

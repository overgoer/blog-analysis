#!/usr/bin/env python3
"""
Channel Checker — читает последние посты из @eddytester и комментарии.

Использование:
    python3 channel_checker.py                    # последний пост
    python3 channel_checker.py --posts 3          # последние 3 поста
    python3 channel_checker.py --post 414         # конкретный пост
    python3 channel_checker.py --post 414 --comments  # пост + комментарии
"""

import json, subprocess, sys
from datetime import datetime

TDL = "tdl"
CHANNEL = "@eddytester"
DISCUSSION_GROUP_ID = 1948889455  # из Replies.ChannelID


def _tdl_export(args, out):
    """Run tdl export and return parsed JSON."""
    cmd = [TDL] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return {"error": r.stderr[-300:]}
        return json.loads(open(out).read())
    except Exception as e:
        return {"error": str(e)}


def _find_post_by_id(chat, target_id, raw=True):
    """Fetch last 200 posts and filter by ID (--type id is unreliable in tdl)."""
    out = f"/tmp/tdl_filter_{chat.strip('@')}_{target_id}.json"
    args = ["chat", "export", "-c", chat, "--type", "last", "-i", "200",
            "-o", out, "--with-content"]
    if raw:
        args.append("--raw")
    data = _tdl_export(args, out)
    if isinstance(data, dict) and "error" in data:
        return data
    messages = data.get("messages", [])
    for m in messages:
        if m.get("id") == target_id:
            return {"messages": [m]}
    return {"error": f"Post {target_id} not found in recent history (last {len(messages)} posts)"}


def export_messages(chat, limit=1, post_id=None, raw=True):
    """Export messages from a chat using tdl."""
    out = f"/tmp/tdl_{chat.strip('@')}_{post_id or 'latest'}.json"
    if post_id:
        return _find_post_by_id(chat, post_id, raw=raw)
    else:
        args = ["chat", "export", "-c", chat, "--type", "last", "-i", str(limit),
                "-o", out, "--with-content"]
        if raw:
            args.append("--raw")
        return _tdl_export(args, out)


def export_replies(chat, post_id):
    """Get comments for a channel post via the discussion group.

    Approach: fetch group messages with --raw, find the forwarded post
    (FwdFrom.ChannelPost == post_id), then filter replies to that thread.
    """
    out = f"/tmp/tdl_group_{post_id}.json"
    args = ["chat", "export", "-c", str(chat), "--type", "last", "-i", "500",
            "-o", out, "--with-content", "--raw"]
    data = _tdl_export(args, out)
    if isinstance(data, dict) and "error" in data:
        return data

    messages = data.get("messages", [])

    # Find the discussion thread message for this channel post
    thread_msg_id = None
    for m in messages:
        fwd = m.get("raw", {}).get("FwdFrom", {})
        if fwd and fwd.get("ChannelPost") == post_id:
            thread_msg_id = m.get("id")
            break

    if not thread_msg_id:
        return {"messages": [], "meta": {"error": f"No thread for post {post_id}"}}

    # Collect replies to that thread
    comments = []
    for m in messages:
        reply_to = m.get("raw", {}).get("ReplyTo", {})
        if reply_to and reply_to.get("ReplyToMsgID") == thread_msg_id:
            comments.append(m)

    return {"messages": comments}


def format_post(msg):
    """Format a single post for display."""
    raw = msg.get("raw", msg)
    text = raw.get("Message") or raw.get("text", "")
    text = text[:500] if text else "(no text)"
    post_id = msg.get("id", "?")
    views = raw.get("Views", 0)
    forwards = raw.get("Forwards", 0)
    date_ts = raw.get("Date") or msg.get("date", 0)
    date_str = datetime.fromtimestamp(date_ts).strftime("%d.%m %H:%M") if date_ts else "?"
    media = raw.get("Media") or {}
    has_media = "Photo" in str(media) or "Video" in str(media)
    replies = raw.get("Replies") or {}
    comments = replies.get("Comments", False)
    reply_count = replies.get("Replies", 0)

    # Reactions (can be None for new posts with 0 reactions)
    reactions = raw.get("Reactions") or {}
    reacts = []
    for r in reactions.get("Results", []):
        emoji = r.get("Reaction", {}).get("Emoticon", "?")
        count = r.get("Count", 0)
        reacts.append(f"{emoji}{count}")

    lines = [
        f"📝 **Пост #{post_id}** ({date_str})",
        f"👁 {views} просмотров · 🔁 {forwards} репостов",
    ]
    if reacts:
        lines.append(f"❤️ {' '.join(reacts)}")
    if comments:
        lines.append(f"💬 Комментарии: {reply_count}")
    lines.append("")
    lines.append(text)
    return "\n".join(lines)


def format_comment(msg):
    """Format a single comment."""
    raw = msg.get("raw", msg)
    text = raw.get("Message") or msg.get("text", "")
    text = text[:500] if text else "(no text)"
    if not text and "file" in msg:
        text = "(media)"
    msg_id = msg.get("id", "?")
    date_ts = raw.get("Date") or msg.get("date", 0)
    date_str = datetime.fromtimestamp(date_ts).strftime("%d.%m %H:%M") if date_ts else "?"
    return f"  💬 **Комментарий #{msg_id}** ({date_str}):\n  {text}"


def check_channel(posts=1, with_comments=False, post_id=None):
    """Main function: get latest posts from @eddytester."""
    if post_id:
        # Specific post by ID
        data = export_messages(CHANNEL, limit=1, post_id=post_id)
        if isinstance(data, dict) and "error" in data:
            return f"❌ {data['error']}"
        messages = data.get("messages", [])
        if not messages:
            return "❌ Пост не найден"
        result = [format_post(messages[0])]

        if with_comments:
            try:
                comments_data = export_replies(DISCUSSION_GROUP_ID, post_id)
                if isinstance(comments_data, dict) and "error" in comments_data:
                    result.append(f"\n💬 Комментарии недоступны: {comments_data['error']}")
                else:
                    comments = comments_data.get("messages", [])
                    if comments:
                        parts = [f"💬 **Комментарии ({len(comments)}):**"]
                        for c in comments:
                            parts.append(format_comment(c))
                        result.append("\n".join(parts))
                    else:
                        result.append("\n💬 Комментариев нет")
            except Exception as e:
                result.append(f"\n💬 Ошибка чтения комментариев: {e}")
    else:
        # Latest posts
        data = export_messages(CHANNEL, limit=posts)
        if isinstance(data, dict) and "error" in data:
            return f"❌ {data['error']}"
        messages = data.get("messages", [])
        if not messages:
            return "❌ Нет постов"
        result = [format_post(m) for m in messages]

    return "\n\n---\n\n".join(result)


def main():
    args = sys.argv[1:]
    posts = 1
    with_comments = "--comments" in args
    post_id = None

    if "--posts" in args:
        idx = args.index("--posts")
        posts = int(args[idx + 1]) if idx + 1 < len(args) else 1

    if "--post" in args:
        idx = args.index("--post")
        post_id = int(args[idx + 1]) if idx + 1 < len(args) else None

    result = check_channel(posts=posts, with_comments=with_comments, post_id=post_id)
    print(result)


if __name__ == "__main__":
    main()

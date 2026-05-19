#!/usr/bin/env python3
"""
Telegram Channel Downloader — скачивает посты из ЛЮБОГО Telegram канала.

Возможности:
  - Любой канал (@username, ID)
  - Пакетная загрузка с паузами (защита от бана)
  - Нет жёсткого лимита на общее число постов
  - Поиск конкретного поста + комментарии
  - Экспорт в JSON и читаемый текст

Использование:
  python3 channel_downloader.py --channel @rvtsakunov --posts 200
  python3 channel_downloader.py --channel @rvtsakunov --posts 5000 --batch-size 200 --delay 2
  python3 channel_downloader.py --channel @eddytester --post 414
  python3 channel_downloader.py --channel @eddytester --post 414 --comments
  python3 channel_downloader.py --channel @channel --posts 50 --format text
"""

import argparse, json, os, subprocess, sys, time
from datetime import datetime

TDL = "tdl"
TDL_TIMEOUT = 120  # 2 min per batch

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "scout", "raw")


def tdl_export(chat, limit, out_file, offset_id=None):
    """Run tdl chat export, return parsed JSON or dict with 'error'."""
    args = [TDL, "chat", "export", "-c", chat, "--type", "last", "-i", str(limit),
            "-o", out_file, "--with-content", "--raw"]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=TDL_TIMEOUT)
        if r.returncode != 0:
            return {"error": r.stderr[-500:]}
        if not os.path.exists(out_file) or os.path.getsize(out_file) < 10:
            return {"error": "Empty output"}
        with open(out_file) as f:
            return json.load(f)
    except subprocess.TimeoutExpired:
        return {"error": f"tdl timeout after {TDL_TIMEOUT}s"}
    except json.JSONDecodeError as e:
        return {"error": f"JSON parse error: {e}"}
    except Exception as e:
        return {"error": str(e)}


def find_post_by_id(chat, target_id, raw=True):
    """Fetch last 200 posts, find specific post by ID."""
    out = f"/tmp/tdl_find_{chat.strip('@')}_{target_id}.json"
    data = tdl_export(chat, 200, out)
    if isinstance(data, dict) and "error" in data:
        return data
    messages = data.get("messages", [])
    for m in messages:
        if m.get("id") == target_id:
            return {"messages": [m]}
    return {"error": f"Post #{target_id} not found in last {len(messages)} posts"}


def export_replies(chat, post_id):
    """Get comments for a channel post via the discussion group."""
    out = f"/tmp/tdl_replies_{post_id}.json"
    data = tdl_export(str(chat), 500, out)
    if isinstance(data, dict) and "error" in data:
        return data

    messages = data.get("messages", [])
    thread_msg_id = None
    for m in messages:
        fwd = m.get("raw", {}).get("FwdFrom", {})
        if fwd and fwd.get("ChannelPost") == post_id:
            thread_msg_id = m.get("id")
            break

    if not thread_msg_id:
        return {"messages": [], "meta": {"error": f"No thread for post {post_id}"}}

    comments = []
    for m in messages:
        reply_to = m.get("raw", {}).get("ReplyTo", {})
        if reply_to and reply_to.get("ReplyToMsgID") == thread_msg_id:
            comments.append(m)

    return {"messages": comments}


def format_post(msg):
    """Format a single post for text display."""
    raw = msg.get("raw", msg)
    text = raw.get("Message") or raw.get("text", "")
    text = text[:1000] if text else "(no text)"
    post_id = msg.get("id", "?")
    views = raw.get("Views", 0)
    forwards = raw.get("Forwards", 0)
    date_ts = raw.get("Date") or msg.get("date", 0)
    date_str = datetime.fromtimestamp(date_ts).strftime("%d.%m %H:%M") if date_ts else "?"
    has_media = bool(raw.get("Media"))
    media_flag = " 📸" if has_media else ""

    reactions = raw.get("Reactions", {})
    reacts = []
    for r in reactions.get("Results", []):
        emoji = r.get("Reaction", {}).get("Emoticon", "?")
        count = r.get("Count", 0)
        reacts.append(f"{emoji}{count}")

    lines = [
        f"📝 **Пост #{post_id}** ({date_str}){media_flag}",
        f"👁 {views} просмотров · 🔁 {forwards} репостов",
    ]
    if reacts:
        lines.append(f"{' '.join(reacts)}")
    lines.append("")
    lines.append(text)
    return "\n".join(lines)


def format_comment(msg):
    """Format a single comment."""
    raw = msg.get("raw", msg)
    text = raw.get("Message") or raw.get("text", "")
    text = text[:500] if text else "(no text)"
    if not text and raw.get("Media"):
        text = "(media)"
    msg_id = msg.get("id", "?")
    date_ts = raw.get("Date") or msg.get("date", 0)
    date_str = datetime.fromtimestamp(date_ts).strftime("%d.%m %H:%M") if date_ts else "?"
    return f"  💬 **#{msg_id}** ({date_str}): {text}"


def download_single_post(chat, post_id, with_comments=False):
    """Download a specific post by ID + optionally comments."""
    data = find_post_by_id(chat, post_id)
    if isinstance(data, dict) and "error" in data:
        return f"❌ {data['error']}"
    messages = data.get("messages", [])
    if not messages:
        return "❌ Пост не найден"

    result = [format_post(messages[0])]

    if with_comments:
        try:
            # Try to find discussion group from the post
            raw = messages[0].get("raw", {})
            replies_info = raw.get("Replies", {})
            discussion_id = replies_info.get("ChannelID") or replies_info.get("ChatID")

            if discussion_id:
                comments_data = export_replies(discussion_id, post_id)
                if isinstance(comments_data, dict) and "error" not in comments_data:
                    comments = comments_data.get("messages", [])
                    if comments:
                        parts = [f"\n💬 **Комментарии ({len(comments)}):**"]
                        for c in comments:
                            parts.append(format_comment(c))
                        result.append("\n".join(parts))
                    else:
                        result.append("\n💬 Комментариев нет")
                else:
                    result.append(f"\n💬 Ошибка: {comments_data.get('error', 'неизвестна')}")
            else:
                result.append("\n💬 Комментарии недоступны (нет группы обсуждения)")
        except Exception as e:
            result.append(f"\n💬 Ошибка: {e}")

    return "\n\n".join(result)


def download_batch(chat, posts_needed, batch_size=200, delay=2):
    """Download posts with batching and delays."""
    all_messages = []
    oldest_id = None
    batch_num = 0
    batches_needed = (posts_needed + batch_size - 1) // batch_size

    print(f"📥 {chat}: {posts_needed} постов, пакетами по {batch_size}, пауза {delay}с",
          file=sys.stderr)

    while len(all_messages) < posts_needed:
        batch_num += 1
        remaining = posts_needed - len(all_messages)
        limit = min(batch_size, remaining)

        out = f"/tmp/tdl_batch_{chat.strip('@')}_{batch_num}.json"
        data = tdl_export(chat, limit, out)

        if isinstance(data, dict) and "error" in data:
            print(f"  ❌ Пакет #{batch_num}: {data['error']}", file=sys.stderr)
            break

        messages = data.get("messages", [])
        if not messages:
            print(f"  ✅ Все посты скачаны (пакет #{batch_num} пуст)", file=sys.stderr)
            break

        # Deduplicate by ID
        existing_ids = {m.get("id") for m in all_messages}
        new_messages = [m for m in messages if m.get("id") not in existing_ids]

        if not new_messages:
            print(f"  ✅ Достигли начала канала (нет новых ID)", file=sys.stderr)
            break

        all_messages.extend(new_messages)
        ids = [m.get("id", 0) for m in new_messages]
        oldest_id = min(ids)

        print(f"  ✅ Пакет #{batch_num}: +{len(new_messages)} постов "
              f"(всего {len(all_messages)}/{posts_needed}, "
              f"старый ID: {oldest_id})", file=sys.stderr)

        # If we got fewer than requested, we've hit the beginning
        if len(new_messages) < limit:
            print(f"  ✅ Начало канала достигнуто", file=sys.stderr)
            break

        if len(all_messages) < posts_needed:
            time.sleep(delay)

    return all_messages


def main():
    parser = argparse.ArgumentParser(description="Telegram Channel Downloader")
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

    messages = download_batch(channel, args.posts, args.batch_size, args.delay)
    if not messages:
        print("❌ Нет постов")
        return

    # Save to raw directory for persistence
    os.makedirs(RAW_DIR, exist_ok=True)
    safe_name = channel.strip("@").replace(".", "_")
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = os.path.join(RAW_DIR, f"{safe_name}_{date_str}.json")
    with open(json_path, "w") as f:
        json.dump({"channel": channel, "total": len(messages),
                    "date": date_str, "messages": messages}, f,
                  ensure_ascii=False, indent=2)

    if args.format == "json":
        print(json.dumps({"channel": channel, "total": len(messages),
                          "file": json_path}, ensure_ascii=False))

    elif args.format == "summary":
        # Brief summary
        raw = messages[0].get("raw", messages[0])
        newest_ts = raw.get("Date")
        newest_date = datetime.fromtimestamp(newest_ts).strftime("%d.%m %H:%M") if newest_ts else "?"
        oldest_raw = messages[-1].get("raw", messages[-1])
        oldest_ts = oldest_raw.get("Date")
        oldest_date = datetime.fromtimestamp(oldest_ts).strftime("%d.%m %H:%M") if oldest_ts else "?"
        media_count = sum(1 for m in messages if m.get("raw", m).get("Media"))
        total_views = sum(m.get("raw", m).get("Views", 0) for m in messages)

        print(f"📊 **{channel}** — {len(messages)} постов")
        print(f"📅 {newest_date} → {oldest_date}")
        print(f"📸 {media_count} с медиа · 👁 {total_views} просмотров всего")
        print(f"💾 Сохранено: `{json_path}`")

    else:  # text — show all posts formatted
        formatted = [format_post(m) for m in messages[:50]]  # Show first 50 in text
        if len(messages) > 50:
            formatted.append(f"\n... и ещё {len(messages) - 50} постов")
            formatted.append(f"\n💾 Полный файл: `{json_path}`")
        print("\n\n---\n\n".join(formatted))


if __name__ == "__main__":
    main()

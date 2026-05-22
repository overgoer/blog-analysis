#!/usr/bin/env python3
"""Subscriber Tracker — daily subscriber count logging via Telegram Bot API.

Fetches @eddytester's subscriber count via Bot API getChat method,
logs it to SQLite via db.log_subscriber_count().

Run once via cron daily:
  0 6 * * * cd /root/blog-analysis/agents/content_analyzer && python3 subscriber_tracker.py

Also logs known competitor channels if available.
"""

import json, os, sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from db import log_subscriber_count, get_channel_by_name, init_db

# Ensure subscriber_log table exists
init_db()

# Token source: same as telegram_bot.py
TOKEN_FILE = BASE.parent / "bsa" / ".tg_token"

CHANNELS_TO_TRACK = [
    "@eddytester",
    "@qachanell",
    "@qabigtech",
    "@rvtsakunov",
    "@rvtsakunov_manual",
    "@burning_tester",
    "@protestinginfo",
    "@qa_chillout",
    "@testerlib",
    "@serious_tester",
    "@qa_and_it",
]


def load_token():
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    token = os.environ.get("TG_BOT_TOKEN", "")
    if token:
        TOKEN_FILE.write_text(token)
    return token


def get_member_count(chat_id: str) -> int | None:
    """Fetch subscriber count via Bot API getChatMemberCount."""
    token = load_token()
    if not token:
        print("ERROR: No TG_BOT_TOKEN")
        return None
    url = f"https://api.telegram.org/bot{token}/getChatMemberCount?chat_id={chat_id}"
    try:
        req = Request(url)
        resp = urlopen(req, timeout=15)
        data = json.loads(resp.read())
        if data.get("ok"):
            return data["result"]
        print(f"API error for {chat_id}: {data.get('description', 'unknown')}")
        return None
    except (URLError, json.JSONDecodeError, OSError) as e:
        print(f"Error fetching {chat_id}: {e}")
        return None


def main():
    """Fetch subscriber counts and log to DB."""
    tracked = 0
    for name in CHANNELS_TO_TRACK:
        ch = get_channel_by_name(name)
        if not ch:
            print(f"Channel {name} not in DB, skipping")
            continue

        count = get_member_count(name)
        if count is None:
            print(f"  {name}: failed to fetch")
            continue

        log_subscriber_count(ch["id"], count)
        print(f"  {name}: {count} subscribers")
        tracked += 1

    if tracked > 0:
        print(f"Done: {tracked} channels updated.")
    else:
        print("No channels tracked.")


if __name__ == "__main__":
    main()

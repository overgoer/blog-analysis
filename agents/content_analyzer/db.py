import sqlite3
import os
from datetime import datetime
from pathlib import Path
from config import DB_PATH, NOTABLE_POSTS_DIR


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate_db():
    """Add new columns that may not exist in older DBs."""
    conn = get_conn()
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(posts)").fetchall()]
        if "goal" not in cols:
            conn.execute("ALTER TABLE posts ADD COLUMN goal TEXT DEFAULT 'other'")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_goal ON posts(goal)")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS subscriber_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                subscribers INTEGER NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(channel_id, date),
                FOREIGN KEY(channel_id) REFERENCES channels(id)
            );
            CREATE INDEX IF NOT EXISTS idx_sub_log_channel ON subscriber_log(channel_id);
            CREATE INDEX IF NOT EXISTS idx_sub_log_date ON subscriber_log(date);
        """)
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            active INTEGER DEFAULT 1,
            added_at TEXT DEFAULT (datetime('now')),
            last_scraped_at TEXT
        );
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            tg_post_id INTEGER NOT NULL,
            posted_at TEXT,
            text TEXT,
            views INTEGER DEFAULT 0,
            forwards INTEGER DEFAULT 0,
            replies_count INTEGER DEFAULT 0,
            media_type TEXT DEFAULT 'text',
            category TEXT DEFAULT 'other',
            notable INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(channel_id, tg_post_id),
            FOREIGN KEY(channel_id) REFERENCES channels(id)
        );
        CREATE TABLE IF NOT EXISTS daily_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            total_posts INTEGER DEFAULT 0,
            total_views INTEGER DEFAULT 0,
            total_forwards INTEGER DEFAULT 0,
            total_replies INTEGER DEFAULT 0,
            avg_views REAL DEFAULT 0,
            avg_forwards REAL DEFAULT 0,
            avg_replies REAL DEFAULT 0,
            notable_count INTEGER DEFAULT 0,
            UNIQUE(channel_id, date),
            FOREIGN KEY(channel_id) REFERENCES channels(id)
        );
        CREATE TABLE IF NOT EXISTS hourly_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            hour TEXT NOT NULL,
            post_count INTEGER DEFAULT 0,
            UNIQUE(channel_id, hour),
            FOREIGN KEY(channel_id) REFERENCES channels(id)
        );
        CREATE TABLE IF NOT EXISTS notable_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL UNIQUE,
            analysis TEXT,
            why_works TEXT,
            category TEXT,
            FOREIGN KEY(post_id) REFERENCES posts(id)
        );
        CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts(channel_id);
        CREATE INDEX IF NOT EXISTS idx_posts_notable ON posts(notable);
        CREATE INDEX IF NOT EXISTS idx_posts_category ON posts(category);
    """)
    conn.commit()
    conn.close()
    migrate_db()


def add_channel(name):
    conn = get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO channels (name) VALUES (?)", (name,))
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    finally:
        conn.close()


def remove_channel(name):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM channels WHERE name = ?", (name,))
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0] > 0
    finally:
        conn.close()


def activate_channel(name):
    conn = get_conn()
    conn.execute("UPDATE channels SET active = 1 WHERE name = ?", (name,))
    conn.commit()
    conn.close()


def list_channels(active_only=False):
    conn = get_conn()
    try:
        q = "SELECT * FROM channels"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY name"
        return [dict(r) for r in conn.execute(q).fetchall()]
    finally:
        conn.close()


def get_channel_by_name(name):
    conn = get_conn()
    try:
        r = conn.execute("SELECT * FROM channels WHERE name = ?", (name,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def ensure_channels(channel_names):
    conn = get_conn()
    for name in channel_names:
        conn.execute("INSERT OR IGNORE INTO channels (name) VALUES (?)", (name,))
    conn.commit()
    conn.close()


def update_channel_scrape(channel_id):
    conn = get_conn()
    conn.execute("UPDATE channels SET last_scraped_at = datetime('now') WHERE id = ?", (channel_id,))
    conn.commit()
    conn.close()


def upsert_post(channel_id, tg_post_id, posted_at, text, views, forwards, replies_count, media_type="text"):
    conn = get_conn()
    existing = conn.execute(
        "SELECT id, views, forwards, replies_count FROM posts WHERE channel_id = ? AND tg_post_id = ?",
        (channel_id, tg_post_id)
    ).fetchone()
    if existing:
        conn.execute("""
            UPDATE posts SET views=?, forwards=?, replies_count=?, updated_at=datetime('now')
            WHERE id=?
        """, (views, forwards, replies_count, existing["id"]))
        conn.commit()
        conn.close()
        return False
    else:
        conn.execute("""
            INSERT INTO posts (channel_id, tg_post_id, posted_at, text, views, forwards, replies_count, media_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (channel_id, tg_post_id, posted_at, text, views, forwards, replies_count, media_type))
        conn.commit()
        conn.close()
        return True


def get_posts_for_analysis(channel_id, limit=50, include_notable=False, days=None):
    conn = get_conn()
    try:
        q = "SELECT * FROM posts WHERE channel_id = ?"
        params = [channel_id]
        if days:
            q += " AND posted_at >= datetime('now', ?)"
            params.append(f"-{days} days")
        if not include_notable:
            q += " AND notable = 0"
        q += " ORDER BY tg_post_id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(q, params).fetchall()]
    finally:
        conn.close()


def mark_notable(post_id, analysis="", why_works="", category=""):
    conn = get_conn()
    conn.execute("UPDATE posts SET notable = 1, category = COALESCE(NULLIF(?, ''), category) WHERE id = ?",
                 (category, post_id))
    conn.execute("""
        INSERT OR REPLACE INTO notable_posts (post_id, analysis, why_works, category)
        VALUES (?, ?, ?, ?)
    """, (post_id, analysis, why_works, category))
    conn.commit()

    post = conn.execute("SELECT p.*, c.name as channel_name FROM posts p JOIN channels c ON p.channel_id = c.id WHERE p.id = ?",
                        (post_id,)).fetchone()
    conn.close()

    if post:
        os.makedirs(NOTABLE_POSTS_DIR, exist_ok=True)
        safe_name = post["channel_name"].replace("@", "").replace("/", "_")
        fname = NOTABLE_POSTS_DIR / f"{safe_name}_tg{post['tg_post_id']}.md"
        content = f"""---
channel: {post['channel_name']}
tg_post_id: {post['tg_post_id']}
posted_at: {post['posted_at']}
views: {post['views']}
forwards: {post['forwards']}
replies: {post['replies_count']}
category: {post['category']}
---

## Post

{post['text'][:500]}

## Analysis

{analysis}

## Why Works

{why_works}
"""
        fname.write_text(content, encoding="utf-8")

    return post


def get_notable_posts(limit=20, category=None, days=None):
    conn = get_conn()
    try:
        q = """
            SELECT p.*, c.name as channel_name, n.analysis, n.why_works
            FROM posts p
            JOIN channels c ON p.channel_id = c.id
            JOIN notable_posts n ON p.id = n.post_id
            WHERE p.notable = 1
        """
        params = []
        if days:
            q += " AND p.posted_at >= datetime('now', ?)"
            params.append(f"-{days} days")
        if category:
            q += " AND p.category = ?"
            params.append(category)
        q += " ORDER BY (p.views * 1 + p.replies_count * 3 + p.forwards * 5) DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(q, params).fetchall()]
    finally:
        conn.close()


def search_posts_by_text(query, limit=10):
    conn = get_conn()
    try:
        q = """
            SELECT p.*, c.name as channel_name
            FROM posts p
            JOIN channels c ON p.channel_id = c.id
            WHERE p.text LIKE ?
            ORDER BY (p.views * 1 + p.replies_count * 3 + p.forwards * 5) DESC
            LIMIT ?
        """
        like = f"%{query}%"
        return [dict(r) for r in conn.execute(q, (like, limit)).fetchall()]
    finally:
        conn.close()


def update_post_goal(post_id, goal):
    """Set the goal (intent) category for a post."""
    conn = get_conn()
    conn.execute("UPDATE posts SET goal = ?, updated_at = datetime('now') WHERE id = ?", (goal, post_id))
    conn.commit()
    conn.close()


def get_uncategorized_posts(limit=500):
    """Get posts missing category or goal classification."""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT p.*, c.name as channel_name
            FROM posts p
            JOIN channels c ON p.channel_id = c.id
            WHERE (p.category IS NULL OR p.category = '' OR p.category = 'other'
                   OR p.goal IS NULL OR p.goal = '' OR p.goal = 'other')
            ORDER BY p.posted_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_category_distribution(days=7, channel_id=None):
    """Get topic category post counts & avg engagement, optionally per channel."""
    conn = get_conn()
    try:
        q = """
            SELECT p.category,
                   COUNT(*) as posts,
                   COALESCE(AVG(p.views), 0) as avg_v,
                   COALESCE(AVG(p.forwards), 0) as avg_f,
                   COALESCE(AVG(p.replies_count), 0) as avg_r
            FROM posts p
            WHERE p.posted_at >= datetime('now', ?)
        """
        params = [f"-{days} days"]
        if channel_id:
            q += " AND p.channel_id = ?"
            params.append(channel_id)
        q += " GROUP BY p.category ORDER BY COUNT(*) DESC"
        return [dict(r) for r in conn.execute(q, params).fetchall()]
    finally:
        conn.close()


def get_goal_distribution(days=7, channel_id=None):
    """Get intent (goal) category post counts & avg engagement, optionally per channel."""
    conn = get_conn()
    try:
        q = """
            SELECT p.goal,
                   COUNT(*) as posts,
                   COALESCE(AVG(p.views), 0) as avg_v,
                   COALESCE(AVG(p.forwards), 0) as avg_f,
                   COALESCE(AVG(p.replies_count), 0) as avg_r
            FROM posts p
            WHERE p.goal != 'other' AND p.posted_at >= datetime('now', ?)
        """
        params = [f"-{days} days"]
        if channel_id:
            q += " AND p.channel_id = ?"
            params.append(channel_id)
        q += " GROUP BY p.goal ORDER BY COUNT(*) DESC"
        return [dict(r) for r in conn.execute(q, params).fetchall()]
    finally:
        conn.close()


def log_subscriber_count(channel_id, subscribers):
    """Log today's subscriber count for a channel (upsert)."""
    conn = get_conn()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        conn.execute("""
            INSERT INTO subscriber_log (channel_id, date, subscribers)
            VALUES (?, ?, ?)
            ON CONFLICT(channel_id, date) DO UPDATE SET subscribers = excluded.subscribers
        """, (channel_id, today, subscribers))
        conn.commit()
    finally:
        conn.close()


def get_subscriber_trend(channel_id, days=30):
    """Get subscriber counts per day for a channel."""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT date, subscribers
            FROM subscriber_log
            WHERE channel_id = ? AND date >= datetime('now', ?)
            ORDER BY date
        """, (channel_id, f"-{days} days")).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_subscriber_impact(channel_id, days=14):
    """Daily subscriber deltas with posts published that day — approximate per-post unsubscribe analysis."""
    conn = get_conn()
    try:
        rows = conn.execute("""
            WITH daily_subs AS (
                SELECT date, subscribers,
                       LAG(subscribers) OVER (ORDER BY date) AS prev_subs,
                       (subscribers - LAG(subscribers) OVER (ORDER BY date)) AS delta
                FROM subscriber_log
                WHERE channel_id = ? AND date >= datetime('now', ?)
            )
            SELECT ds.date, ds.subscribers, ds.delta,
                   GROUP_CONCAT(p.tg_post_id || ':' || COALESCE(p.views, 0) || 'v' || COALESCE(p.forwards, 0) || 'f', ', ') AS posts_today
            FROM daily_subs ds
            LEFT JOIN posts p ON p.channel_id = ? AND date(p.posted_at) = ds.date
            GROUP BY ds.date
            ORDER BY ds.date
        """, (channel_id, f"-{days} days", channel_id)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_daily_metrics(channel_id, date, total_posts, total_views, total_forwards, total_replies,
                       avg_views, avg_forwards, avg_replies, notable_count):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO daily_metrics
        (channel_id, date, total_posts, total_views, total_forwards, total_replies,
         avg_views, avg_forwards, avg_replies, notable_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (channel_id, date, total_posts, total_views, total_forwards, total_replies,
          avg_views, avg_forwards, avg_replies, notable_count))
    conn.commit()
    conn.close()


def get_aggregate_metrics(days=7):
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT c.name, COUNT(p.id) as posts, SUM(p.views) as views,
                   SUM(p.forwards) as forwards, SUM(p.replies_count) as replies,
                   SUM(CASE WHEN p.notable = 1 THEN 1 ELSE 0 END) as notable
            FROM posts p
            JOIN channels c ON p.channel_id = c.id
            WHERE p.created_at >= datetime('now', ?)
            GROUP BY c.id
            ORDER BY views DESC
        """, (f"-{days} days",)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

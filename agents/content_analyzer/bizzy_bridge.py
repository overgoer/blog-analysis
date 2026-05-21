#!/usr/bin/env python3
"""Content Analyzer — Bizzy bridge.

Bizzy imports this module for:
- requesting competitor analysis
- managing channel pool
- getting notable post summaries
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# Add analyzer to path
ANALYZER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ANALYZER_DIR))

import db
from db import init_db
from config import DEFAULT_CHANNELS

# Ensure DB tables exist when Bizzy loads this module
init_db()


def add_channel(name: str) -> str:
    """Add a channel to the monitoring pool. Called by Bizzy."""
    name = name.strip()
    if not name.startswith("@"):
        name = f"@{name}"
    ok = db.add_channel(name)
    db.activate_channel(name)
    if ok:
        return f"✅ {name} добавлен в пул мониторинга. Подхватится ночным анализом."
    else:
        ch = db.get_channel_by_name(name)
        if ch and not ch["active"]:
            db.activate_channel(name)
            return f"✅ {name} уже был в БД, реактивирован."
        return f"ℹ️ {name} уже в пуле."


def remove_channel(name: str) -> str:
    """Remove a channel from monitoring."""
    name = name.strip()
    if not name.startswith("@"):
        name = f"@{name}"
    ok = db.remove_channel(name)
    return f"✅ {name} удалён из пула." if ok else f"❌ {name} не найден."


def list_channels() -> str:
    """List all monitored channels with stats."""
    channels = db.list_channels(active_only=True)
    lines = ["📡 **Пул мониторинга:**", ""]
    for ch in channels:
        posts = db.get_posts_for_analysis(ch["id"], limit=1)
        notable = db.get_notable_posts(limit=100)
        notable_count = sum(1 for n in notable if str(n.get("channel_name", "")) == str(ch["id"]))
        last = ch.get("last_scraped_at", "никогда")
        lines.append(f"  • {ch['name']} — {last}")
    return "\n".join(lines)


def get_channel_stats(name: str) -> str:
    """Get stats for a specific channel."""
    name = name.strip()
    if not name.startswith("@"):
        name = f"@{name}"
    ch = db.get_channel_by_name(name)
    if not ch:
        return f"❌ Канал {name} не найден в пуле."

    posts = db.get_posts_for_analysis(ch["id"], limit=50)
    if not posts:
        return f"ℹ️ {name}: нет данных (ещё не скрапили)."

    total = len(posts)
    avg_v = sum(p.get("views", 0) for p in posts) / total
    avg_f = sum(p.get("forwards", 0) for p in posts) / total
    avg_r = sum(p.get("replies_count", 0) for p in posts) / total
    notable = [p for p in posts if p.get("notable")]

    cats = {}
    for p in posts:
        c = p.get("category", "other")
        cats[c] = cats.get(c, 0) + 1

    lines = [
        f"📊 **{name}** — {total} постов в базе",
        f"",
        f"  • Средние просмотры: {avg_v:.0f}",
        f"  • Средние репосты: {avg_f:.1f}",
        f"  • Средние комменты: {avg_r:.1f}",
        f"  • Notable: {len(notable)}",
        f"",
        f"**Категории:**",
    ]
    for cat, cnt in sorted(cats.items(), key=lambda x: -x[1]):
        lines.append(f"  • {cat}: {cnt} ({cnt*100//total}%)")

    if notable:
        lines.append("")
        lines.append("**Лучшие посты:**")
        for n in notable[:3]:
            why = (n.get("notable_reason") or "")[:100]
            lines.append(f"  • tg#{n['tg_post_id']}: {why}")

    return "\n".join(lines)


def get_notable_summary(category: str = None) -> str:
    """Get summary of notable posts, optionally filtered by category."""
    notable = db.get_notable_posts(limit=20, category=category)
    if not notable:
        return "📭 Нет notable постов."

    lines = ["⭐ **Notable посты:**", ""]
    for n in notable[:10]:
        emoji = "🏠" if n.get("channel_name") == "11" else "📌"
        lines.append(
            f"  {emoji} {n.get('channel_name', '?')} #{n['tg_post_id']} — "
            f"👁{n.get('views', 0)} 🔁{n.get('forwards', 0)} 💬{n.get('replies_count', 0)}"
        )
        if n.get("why_works"):
            lines.append(f"    _{n['why_works'][:80]}_")
        lines.append("")
    return "\n".join(lines)


def search_posts(query: str) -> str:
    """Search posts by text across all channels."""
    results = db.search_posts_by_text(query, limit=10)
    if not results:
        return f"🔍 Ничего не найдено по запросу «{query}»."

    lines = [f"🔍 **Результаты по «{query}»:**", ""]
    for r in results:
        text = (r.get("text") or "")[:100]
        lines.append(
            f"  • {r.get('channel_name', '?')} #{r['tg_post_id']} — "
            f"👁{r.get('views', 0)} 🔁{r.get('forwards', 0)} 💬{r.get('replies_count', 0)}"
        )
        lines.append(f"    {text}")
        lines.append("")
    return "\n".join(lines)


def get_daily_report() -> str:
    """Get today's analysis report content."""
    today = date.today()
    report_path = Path("/root/obsidian-vault/eddytester/Стратегия/Анализ/Ежедневный") / f"{today.isoformat()}.md"
    if report_path.exists():
        return report_path.read_text(encoding="utf-8")
    yesterday = today - timedelta(days=1)
    report_path = Path("/root/obsidian-vault/eddytester/Стратегия/Анализ/Ежедневный") / f"{yesterday.isoformat()}.md"
    if report_path.exists():
        return report_path.read_text(encoding="utf-8")
    return "📭 Отчёт за сегодня ещё не сгенерирован (ночной анализ в 02:00 UTC)."


# ── SQL query tools for Bizzy ──────────────────────────────────────────
# These let Bizzy ask direct questions about the data instead of reading
# pre-generated text reports.

def _fmt(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000: return f"{n/1_000:.1f}K"
    return str(n)


def _custom_metrics_block(vals: dict) -> str:
    """Append custom metrics as additional output lines."""
    from runtime_config import get_custom_metrics
    metrics = get_custom_metrics()
    if not metrics:
        return ""
    lines = []
    for m in metrics:
        try:
            # Safe: formula can reference keys in vals dict
            formula = m["formula"]
            safe = formula
            for k, v in vals.items():
                safe = safe.replace(k, str(v))
            result = eval(safe, {"__builtins__": {}}, {"round": round, "max": max, "min": min, "abs": abs,
                                                       "float": float, "int": int})
            lines.append(f"  • {m['name']}: {_fmt(round(result, 2) if isinstance(result, float) else result)}")
        except Exception:
            lines.append(f"  • {m['name']}: ошибка вычисления")
    return "\n".join(lines)


def query_channel_metrics(channel_name: str, days: int = 7) -> str:
    """Bizzy tool: get avg views/forwards/replies/engagement for a channel."""
    import db
    ch = db.get_channel_by_name(channel_name)
    if not ch:
        return f"Канал {channel_name} не найден в БД."

    conn = db.get_conn()
    try:
        row = conn.execute("""
            SELECT COUNT(*) as posts,
                   COALESCE(AVG(views), 0) as avg_v,
                   COALESCE(AVG(forwards), 0) as avg_f,
                   COALESCE(AVG(replies_count), 0) as avg_r,
                   SUM(CASE WHEN notable=1 THEN 1 ELSE 0 END) as notable
            FROM posts
            WHERE channel_id=? AND posted_at >= datetime('now', ?)
        """, (ch["id"], f"-{days} days")).fetchone()
        if not row or row["posts"] == 0:
            return f"Нет данных для {channel_name} за последние {days} дн."

        d = dict(row)
        from channel_goals import SUBSCRIBERS
        engage = d["avg_v"] + d["avg_r"] * 3 + d["avg_f"] * 5

        from runtime_config import get_custom_metrics
        custom = _custom_metrics_block({
            "avg_views": d["avg_v"], "avg_forwards": d["avg_f"], "avg_replies": d["avg_r"],
            "posts": d["posts"], "subscribers": SUBSCRIBERS.get(channel_name, 0),
            "notable": d["notable"],
        })
        result = (
            f"📊 {channel_name} за {days} дн:\n"
            f"  • Постов: {d['posts']}\n"
            f"  • Средние просмотры: {_fmt(round(d['avg_v']))}\n"
            f"  • Средние репосты: {_fmt(round(d['avg_f']))}\n"
            f"  • Средние комменты: {_fmt(round(d['avg_r']))}\n"
            f"  • Среднее вовлечение: {_fmt(round(engage))}\n"
            f"  • Notable: {d['notable']}"
        )
        if custom:
            result += "\n" + custom
        return result
    finally:
        conn.close()


def query_top_posts(channel_name: str, limit: int = 5, days: int = 7) -> str:
    """Bizzy tool: get top posts by engagement for a channel."""
    import db
    from config import ENGAGEMENT_WEIGHTS as W
    ch = db.get_channel_by_name(channel_name)
    if not ch:
        return f"Канал {channel_name} не найден."

    conn = db.get_conn()
    try:
        rows = conn.execute("""
            SELECT id, tg_post_id, text, views, forwards, replies_count, category, media_type, posted_at
            FROM posts
            WHERE channel_id=? AND posted_at >= datetime('now', ?)
            ORDER BY (views * ? + replies_count * ? + forwards * ?) DESC
            LIMIT ?
        """, (ch["id"], f"-{days} days", W["views"], W["replies"], W["forwards"], limit)).fetchall()
        if not rows:
            return f"Нет постов для {channel_name} за {days} дн."

        lines = [f"🏆 Топ-{limit} постов {channel_name} за {days} дн:", ""]
        for r in rows:
            text = (r["text"] or "")[:120]
            engage = r["views"] + r["replies_count"] * 3 + r["forwards"] * 5
            media = f" [{r['media_type']}]" if r["media_type"] != "text" else ""
            lines.append(
                f"  #{r['tg_post_id']}{media} | 👁{_fmt(r['views'])} 🔁{_fmt(r['forwards'])} "
                f"💬{_fmt(r['replies_count'])} | 💥{_fmt(engage)}"
            )
            lines.append(f"    {text}")
            lines.append("")
        return "\n".join(lines)
    finally:
        conn.close()


def query_category_performance(channel_name: str, days: int = 7) -> str:
    """Bizzy tool: how posts perform by category."""
    import db
    from config import ENGAGEMENT_WEIGHTS as W
    ch = db.get_channel_by_name(channel_name)
    if not ch:
        return f"Канал {channel_name} не найден."

    conn = db.get_conn()
    try:
        rows = conn.execute("""
            SELECT category,
                   COUNT(*) as posts,
                   COALESCE(AVG(views), 0) as avg_v,
                   COALESCE(AVG(forwards), 0) as avg_f,
                   COALESCE(AVG(replies_count), 0) as avg_r,
                   SUM(CASE WHEN notable=1 THEN 1 ELSE 0 END) as notable
            FROM posts
            WHERE channel_id=? AND posted_at >= datetime('now', ?)
            GROUP BY category
            ORDER BY COUNT(*) DESC
        """, (ch["id"], f"-{days} days")).fetchall()
        if not rows:
            return f"Нет категорий для {channel_name} за {days} дн."

        lines = [f"📂 Категории постов {channel_name} за {days} дн:", ""]
        lines.append(f"  {'Категория':<20} {'Постов':>6} {'Просм':>8} {'Репост':>6} {'Комм':>5} {'Notable':>7}")
        lines.append(f"  {'─'*20} {'─'*6} {'─'*8} {'─'*6} {'─'*5} {'─'*7}")
        for r in rows:
            engage = r["avg_v"] + r["avg_r"] * 3 + r["avg_f"] * 5
            lines.append(
                f"  {r['category']:<20} {r['posts']:>6} {_fmt(round(r['avg_v'])):>8} "
                f"{_fmt(round(r['avg_f'])):>6} {_fmt(round(r['avg_r'])):>5} {r['notable']:>7}"
            )
        lines.append("")
        lines.append("💡 engagement = просмотры + комменты*3 + репосты*5")
        return "\n".join(lines)
    finally:
        conn.close()


def query_competitor_comparison(days: int = 7) -> str:
    """Bizzy tool: compare all active channels side by side."""
    import db
    from config import ENGAGEMENT_WEIGHTS as W
    from channel_goals import SUBSCRIBERS

    conn = db.get_conn()
    try:
        rows = conn.execute("""
            SELECT c.name as channel,
                   COUNT(p.id) as posts,
                   COALESCE(AVG(p.views), 0) as avg_v,
                   COALESCE(AVG(p.forwards), 0) as avg_f,
                   COALESCE(AVG(p.replies_count), 0) as avg_r,
                   SUM(CASE WHEN p.notable=1 THEN 1 ELSE 0 END) as notable
            FROM posts p
            JOIN channels c ON p.channel_id = c.id
            WHERE p.posted_at >= datetime('now', ?) AND c.active = 1
            GROUP BY c.id
            ORDER BY avg_v DESC
        """, (f"-{days} days",)).fetchall()
        if not rows:
            return f"Нет данных за {days} дн."

        lines = [f"📊 Сравнение каналов за {days} дн:", ""]
        lines.append(f"  {'Канал':<20} {'Постов':>6} {'Просм':>8} {'Вовл':>8} {'Охват':>8} {'Notable':>7}")
        lines.append(f"  {'─'*20} {'─'*6} {'─'*8} {'─'*8} {'─'*8} {'─'*7}")
        for r in rows:
            engage = r["avg_v"] + r["avg_r"] * 3 + r["avg_f"] * 5
            subs = SUBSCRIBERS.get(r["channel"], 0)
            reach = f"{round(r['avg_v'] / subs * 100, 1)}%" if subs else "—"
            marker = " ⬅️" if r["channel"] == "@eddytester" else ""
            lines.append(
                f"  {r['channel']:<20}{marker} {r['posts']:>6} {_fmt(round(r['avg_v'])):>8} "
                f"{_fmt(round(engage)):>8} {reach:>8} {r['notable']:>7}"
            )
        return "\n".join(lines)
    finally:
        conn.close()


def query_content_profile(days: int = 7) -> str:
    """Bizzy tool: compare topic categories across ALL channels — what each channel posts about."""
    import db
    conn = db.get_conn()
    try:
        rows = conn.execute("""
            SELECT c.name as channel,
                   p.category,
                   COUNT(*) as posts
            FROM posts p
            JOIN channels c ON p.channel_id = c.id
            WHERE p.posted_at >= datetime('now', ?) AND c.active = 1
            GROUP BY c.id, p.category
            ORDER BY c.name, COUNT(*) DESC
        """, (f"-{days} days",)).fetchall()
        if not rows:
            return f"Нет данных за {days} дн."

        channels = {}
        cats_set = set()
        for r in rows:
            ch = r["channel"]
            cat = r["category"] or "other"
            channels.setdefault(ch, {})[cat] = r["posts"]
            cats_set.add(cat)

        all_cats = sorted(cats_set)
        lines = [f"📂 Контент-профиль каналов за {days} дн:", ""]
        header = f"  {'Канал':<20}"
        for c in all_cats:
            header += f" {c:<14}"
        header += "  Всего"
        lines.append(header)
        lines.append(f"  {'─'*20} {'─'*14}" * len(all_cats) + " ───")

        for ch, cats in sorted(channels.items()):
            total = sum(cats.values())
            row = f"  {ch:<20}"
            for c in all_cats:
                cnt = cats.get(c, 0)
                pct = f"{cnt*100//total}%" if total else ""
                row += f" {pct:>14}"
            row += f" {total:>4}"
            lines.append(row)

        return "\n".join(lines)
    finally:
        conn.close()


def query_goal_profile(days: int = 7) -> str:
    """Bizzy tool: compare post INTENT (goal) distribution across all channels."""
    import db
    conn = db.get_conn()
    try:
        rows = conn.execute("""
            SELECT c.name as channel,
                   p.goal,
                   COUNT(*) as posts
            FROM posts p
            JOIN channels c ON p.channel_id = c.id
            WHERE p.posted_at >= datetime('now', ?) AND c.active = 1
                  AND p.goal != 'other' AND p.goal != ''
            GROUP BY c.id, p.goal
            ORDER BY c.name, COUNT(*) DESC
        """, (f"-{days} days",)).fetchall()
        if not rows:
            return "Нет данных по целям постов. Запусти categorizer.py на сервере."

        channels = {}
        goals_set = set()
        for r in rows:
            ch = r["channel"]
            goal = r["goal"]
            channels.setdefault(ch, {})[goal] = r["posts"]
            goals_set.add(goal)

        all_goals = sorted(goals_set)
        lines = [f"🎯 Целевой профиль каналов за {days} дн:", ""]
        header = f"  {'Канал':<20}"
        for g in all_goals:
            header += f" {g:<12}"
        header += "  Всего"
        lines.append(header)
        lines.append(f"  {'─'*20} {'─'*12}" * len(all_goals) + " ───")

        for ch, goals in sorted(channels.items()):
            total = sum(goals.values())
            row = f"  {ch:<20}"
            for g in all_goals:
                cnt = goals.get(g, 0)
                pct = f"{cnt*100//total}%" if total else ""
                row += f" {pct:>12}"
            row += f" {total:>4}"
            lines.append(row)

        return "\n".join(lines)
    finally:
        conn.close()


def query_post_trend(channel_name: str, days: int = 14) -> str:
    """Bizzy tool: daily average views trend."""
    import db
    ch = db.get_channel_by_name(channel_name)
    if not ch:
        return f"Канал {channel_name} не найден."

    conn = db.get_conn()
    try:
        rows = conn.execute("""
            SELECT DATE(posted_at) as day,
                   COUNT(*) as posts,
                   COALESCE(AVG(views), 0) as avg_v
            FROM posts
            WHERE channel_id=? AND posted_at >= datetime('now', ?)
            GROUP BY DATE(posted_at)
            ORDER BY day
        """, (ch["id"], f"-{days} days")).fetchall()
        if not rows:
            return f"Нет тренда для {channel_name} за {days} дн."

        lines = [f"📈 Дневной тренд {channel_name} за {days} дн:", ""]
        for r in rows:
            bar = "█" * max(1, round(r["avg_v"] / max(max(rr["avg_v"] for rr in rows), 1) * 20))
            lines.append(f"  {r['day']} | {bar} {_fmt(round(r['avg_v']))} ({r['posts']}п)")
        return "\n".join(lines)
    finally:
        conn.close()

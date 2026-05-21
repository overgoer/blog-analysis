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
from config import DEFAULT_CHANNELS


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

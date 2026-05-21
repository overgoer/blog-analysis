#!/usr/bin/env python3
"""Reporter — generates daily Obsidian reports."""
import os
from datetime import date, timedelta
from pathlib import Path
from config import OBSIDIAN_STRAT


def _fmt(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def build_daily_report() -> str:
    """Build daily analysis report markdown."""
    from db import get_aggregate_metrics, get_notable_posts, init_db
    init_db()

    today = date.today().isoformat()
    metrics = get_aggregate_metrics(days=7)

    lines = [
        f"# 📊 Ежедневный анализ контента — {today}",
        "",
        "## Общая статистика за 7 дней",
        "",
        "| Канал | Посты | Просмотры | Репосты | Комменты | Notable |",
        "|-------|-------|-----------|---------|----------|---------|",
    ]

    total_posts = total_views = total_fwds = total_replies = total_notable = 0
    for m in metrics:
        lines.append(
            f"| {m['name']} | {m['posts']} | {_fmt(m['views'])} | {_fmt(m['forwards'])} | "
            f"{_fmt(m['replies'])} | {m['notable']} |"
        )
        total_posts += m["posts"]
        total_views += m["views"]
        total_fwds += m["forwards"]
        total_replies += m["replies"]
        total_notable += m["notable"]

    lines.append(f"| **Итого** | **{total_posts}** | **{_fmt(total_views)}** | **{_fmt(total_fwds)}** | **{_fmt(total_replies)}** | **{total_notable}** |")
    lines.append("")

    # Notable posts
    lines.append("## ⭐ Notable посты")
    lines.append("")
    notable = get_notable_posts(limit=20)
    if notable:
        for n in notable:
            why = (n.get("why_works") or "")[:120]
            lines.append(f"- **{n['channel_name']}** tg#{n['tg_post_id']} — 👁{n.get('views',0)} 🔁{n.get('forwards',0)} 💬{n.get('replies_count',0)}")
            lines.append(f"  _{why}_")
            lines.append("")
    else:
        lines.append("_Нет notable постов за период._")
        lines.append("")

    # Recommendations placeholder
    lines.append("## 💡 Рекомендации")
    lines.append("")
    lines.append("_Заполняется после накопления данных (7+ дней)._")
    lines.append("")

    return "\n".join(lines)


def save_report(content: str = None) -> str:
    """Save report to Obsidian vault."""
    ensure_dirs()
    today = date.today().isoformat()
    fpath = OBSIDIAN_STRAT / f"{today}.md"
    if content is None:
        content = build_daily_report()

    # Merge with existing if present
    if fpath.exists():
        existing = fpath.read_text(encoding="utf-8")
        if existing.strip():
            content = existing + "\n\n---\n\n## 🔄 Обновление\n\n" + content.split("## Общая статистика")[0]

    fpath.write_text(content, encoding="utf-8")
    return str(fpath)


def ensure_dirs():
    os.makedirs(OBSIDIAN_STRAT, exist_ok=True)
    from config import NOTABLE_POSTS_DIR
    os.makedirs(NOTABLE_POSTS_DIR, exist_ok=True)

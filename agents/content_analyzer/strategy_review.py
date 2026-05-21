#!/usr/bin/env python3
"""
Strategy Review — еженедельный стратегический обзор с графиками.

Генерирует:
- Сравнение каналов по метрикам за 7 дней
- Анализ форматов с confidence
- Gap analysis с конкурентами
- Рекомендации на неделю
- Графики (matplotlib Agg → PNG → Obsidian)

Запуск:
  python3 strategy_review.py              # вывести в консоль
  python3 strategy_review.py --save        # сохранить в Obsidian
  python3 strategy_review.py --send        # + отправить в Telegram

Cron (воскресенье 23:00):
  0 23 * * 0 cd .../content_analyzer && python3 strategy_review.py --save
"""

import json, os, sys, subprocess
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db
from config import DEFAULT_CHANNELS
from channel_goals import GOALS, PRIMARY_COMPETITORS, CONFIDENCE_THRESHOLDS, ENGAGEMENT_WEIGHTS

# ── Paths ───────────────────────────────────────────────────────────────
WEEKLY_DIR = Path("/root/obsidian-vault/eddytester/Стратегия/Анализ/Weekly")
CHARTS_DIR = WEEKLY_DIR / "charts"

W = ENGAGEMENT_WEIGHTS


# ══════════════════════════════════════════════════════════════════════════
#   DATA QUERIES
# ══════════════════════════════════════════════════════════════════════════


def _engagement(p):
    return p.get("views", 0) * W["views"] \
         + p.get("replies_count", 0) * W["replies"] \
         + p.get("forwards", 0) * W["forwards"]


def get_weekly_posts(days=14) -> list:
    """Get all posts from last N days for ALL channels."""
    conn = db.get_conn()
    try:
        rows = conn.execute("""
            SELECT p.*, c.name as channel_name
            FROM posts p
            JOIN channels c ON p.channel_id = c.id
            WHERE p.posted_at >= datetime('now', ?)
            ORDER BY p.channel_id, p.posted_at
        """, (f"-{days} days",)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_channel_weekly_summary() -> list:
    """Per-channel aggregate for the last 7 days."""
    conn = db.get_conn()
    try:
        rows = conn.execute("""
            SELECT c.name as channel_name,
                   COUNT(p.id) as total_posts,
                   COALESCE(SUM(p.views), 0) as total_views,
                   COALESCE(AVG(p.views), 0) as avg_views,
                   COALESCE(SUM(p.forwards), 0) as total_forwards,
                   COALESCE(AVG(p.forwards), 0) as avg_forwards,
                   COALESCE(SUM(p.replies_count), 0) as total_replies,
                   COALESCE(AVG(p.replies_count), 0) as avg_replies,
                   SUM(CASE WHEN p.notable = 1 THEN 1 ELSE 0 END) as notable_count
            FROM posts p
            JOIN channels c ON p.channel_id = c.id
            WHERE p.posted_at >= datetime('now', '-7 days')
            GROUP BY c.id
            ORDER BY total_views DESC
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_daily_trend(days=14) -> dict:
    """Get daily aggregate per channel for trend chart."""
    conn = db.get_conn()
    try:
        rows = conn.execute("""
            SELECT DATE(p.posted_at) as day, c.name as channel,
                   COUNT(p.id) as posts,
                   AVG(p.views) as avg_views,
                   AVG(p.forwards) as avg_forwards,
                   AVG(p.replies_count) as avg_replies
            FROM posts p
            JOIN channels c ON p.channel_id = c.id
            WHERE p.posted_at >= datetime('now', ?)
            GROUP BY day, c.name
            ORDER BY day
        """, (f"-{days} days",)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_engagement_quality(days=7) -> dict:
    """Classify own-channel posts by engagement quality."""
    conn = db.get_conn()
    try:
        ch = conn.execute(
            "SELECT id FROM channels WHERE name = ?",
            ("@eddytester",)
        ).fetchone()
        if not ch:
            return {}
        rows = conn.execute("""
            SELECT text, views, forwards, replies_count, category, posted_at
            FROM posts
            WHERE channel_id = ? AND posted_at >= datetime('now', ?)
            ORDER BY (views * 1 + replies_count * 3 + forwards * 5) DESC
        """, (ch["id"], f"-{days} days")).fetchall()
        posts = [dict(r) for r in rows]
    finally:
        conn.close()

    result = {"community": [], "viral": [], "read_only": [], "all": posts}
    for p in posts:
        e = _engagement(p)
        if p["replies_count"] > p["forwards"] and e > 0:
            result["community"].append(p)
        elif p["forwards"] > p["replies_count"] and e > 0:
            result["viral"].append(p)
        elif e > 0:
            result["read_only"].append(p)
    return result


# ══════════════════════════════════════════════════════════════════════════
#   CONFIDENCE & ANALYSIS
# ══════════════════════════════════════════════════════════════════════════


def _confidence_label(n: int) -> dict:
    """Return confidence level based on sample count."""
    for level, cfg in reversed(list(CONFIDENCE_THRESHOLDS.items())):
        if n >= cfg["min_samples"]:
            return {"level": level, "label": cfg["label"]}
    return {"level": "LOW", "label": "Мало данных"}


def analyze_format_performance(weekly_posts: list) -> list:
    """Analyze which formats/categories work best with confidence."""
    from collections import defaultdict
    cats = defaultdict(lambda: {"posts": [], "total_engage": 0})
    for p in weekly_posts:
        cat = p.get("category", "other")
        cats[cat]["posts"].append(p)
        cats[cat]["total_engage"] += _engagement(p)

    results = []
    for cat, data in cats.items():
        n = len(data["posts"])
        avg_views = sum(p["views"] for p in data["posts"]) / n if n else 0
        avg_engage = data["total_engage"] / n if n else 0
        confidence = _confidence_label(n)

        # Trend: if avg_views > median of all posts, it's working
        results.append({
            "category": cat,
            "posts": n,
            "avg_views": round(avg_views),
            "avg_engagement": round(avg_engage),
            "notable_count": sum(1 for p in data["posts"] if p.get("notable")),
            "confidence": confidence,
        })

    return sorted(results, key=lambda r: -r["avg_engagement"])


def analyze_best_timing(own_posts: list) -> dict:
    """Analyze best posting day/time from own posts."""
    from collections import defaultdict
    day_stats = defaultdict(lambda: {"count": 0, "total_views": 0, "total_engage": 0})
    hour_stats = defaultdict(lambda: {"count": 0, "total_views": 0})
    day_names = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]

    for p in own_posts:
        ts = p.get("posted_at", "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts)
        except (ValueError, TypeError):
            continue

        day = day_names[dt.weekday()]
        hour = dt.hour

        day_stats[day]["count"] += 1
        day_stats[day]["total_views"] += p.get("views", 0)
        day_stats[day]["total_engage"] += _engagement(p)

        hour_stats[hour]["count"] += 1
        hour_stats[hour]["total_views"] += p.get("views", 0)

    best_day = max(day_stats, key=lambda d: day_stats[d]["total_engage"] / max(day_stats[d]["count"], 1)) \
        if day_stats else "—"
    best_hour = max(hour_stats, key=lambda h: hour_stats[h]["total_views"] / max(hour_stats[h]["count"], 1)) \
        if hour_stats else None

    return {
        "best_day": best_day,
        "best_hour": f"{best_hour}:00" if best_hour is not None else "—",
        "day_stats": dict(day_stats),
        "hour_stats": dict(hour_stats),
    }


def compute_competitor_gap(channel_summary: list) -> list:
    """Compare @eddytester metrics vs primary competitors."""
    our = next((c for c in channel_summary if c["channel_name"] == "@eddytester"), None)
    if not our:
        return []

    gaps = []
    for c in channel_summary:
        if c["channel_name"] == "@eddytester":
            continue
        if c["channel_name"] not in PRIMARY_COMPETITORS:
            continue
        gap = {
            "competitor": c["channel_name"],
            "views_gap": (c["avg_views"] - our["avg_views"]) / max(our["avg_views"], 1),
            "engage_gap": (c["avg_views"] + c["avg_forwards"] + c["avg_replies"])
                          - (our["avg_views"] + our["avg_forwards"] + our["avg_replies"]),
            "post_freq": round(c["total_posts"] / max(our["total_posts"], 1), 1),
            "competitor_avg_views": round(c["avg_views"]),
            "our_avg_views": round(our["avg_views"]),
        }
        gaps.append(gap)

    return sorted(gaps, key=lambda g: -g["views_gap"])


# ══════════════════════════════════════════════════════════════════════════
#   CHARTS
# ══════════════════════════════════════════════════════════════════════════


def _ensure_chart_dir():
    os.makedirs(CHARTS_DIR, exist_ok=True)


def chart_views_trend(daily_data: list, days=14):
    """Line chart: daily avg views per top channel."""
    _ensure_chart_dir()
    from collections import defaultdict

    # Group by channel and day
    series = defaultdict(list)
    for row in daily_data:
        series[row["channel"]].append(row)

    # Pick top channels by data volume
    top = sorted(series.keys(), key=lambda c: sum(r["avg_views"] for r in series[c]), reverse=True)[:6]

    fig, ax = plt.subplots(figsize=(12, 5))
    fig.patch.set_facecolor("#1e1e1e")
    ax.set_facecolor("#1e1e1e")

    colors = ["#ff6b6b", "#4ecdc4", "#45b7d1", "#96ceb4", "#ffeaa7", "#dfe6e9"]
    for i, ch in enumerate(top):
        pts = sorted(series[ch], key=lambda r: r["day"])
        days = [r["day"] for r in pts]
        vals = [r["avg_views"] for r in pts]
        color = colors[i % len(colors)]
        label = ch.replace("@", "")
        ax.plot(days, vals, marker="o", label=label, color=color, linewidth=2, markersize=4)

    ax.tick_params(colors="white", labelsize=9)
    ax.set_ylabel("Средние просмотры", color="white", fontsize=10)
    ax.set_title("Тренд просмотров за 14 дней", color="white", fontsize=13, pad=12)
    ax.legend(fontsize=8, loc="upper left", facecolor="#2d2d2d", labelcolor="white", framealpha=0.8)
    ax.grid(True, alpha=0.15, color="white")
    ax.set_xlabel("")
    plt.xticks(rotation=30, ha="right")
    fig.tight_layout()
    fpath = CHARTS_DIR / f"views_trend_{date.today().isoformat()}.png"
    fig.savefig(fpath, dpi=120, facecolor="#1e1e1e")
    plt.close(fig)
    return fpath


def chart_engagement_comparison(channel_summary: list):
    """Bar chart: avg engagement per channel."""
    _ensure_chart_dir()

    top = sorted(channel_summary, key=lambda r: -(r["avg_views"] + r["avg_replies"] * 3 + r["avg_forwards"] * 5))[:8]

    names = [c["channel_name"].replace("@", "") for c in top]
    avg_engage = [
        round(c["avg_views"] + c["avg_replies"] * 3 + c["avg_forwards"] * 5)
        for c in top
    ]
    notable = [c["notable_count"] for c in top]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    fig.patch.set_facecolor("#1e1e1e")

    bars1 = ax1.barh(names, avg_engage, color="#4ecdc4", height=0.6)
    ax1.set_facecolor("#1e1e1e")
    ax1.tick_params(colors="white", labelsize=9)
    ax1.set_xlabel("Средняя вовлечённость", color="white", fontsize=10)
    ax1.set_title("Вовлечённость по каналам", color="white", fontsize=12)
    ax1.grid(True, alpha=0.1, color="white", axis="x")

    # Highlight @eddytester
    for i, bar in enumerate(bars1):
        if names[i] == "eddytester":
            bar.set_color("#ff6b6b")

    bars2 = ax2.barh(names, notable, color="#45b7d1", height=0.6)
    ax2.set_facecolor("#1e1e1e")
    ax2.tick_params(colors="white", labelsize=9)
    ax2.set_xlabel("Notable постов", color="white", fontsize=10)
    ax2.set_title("Notable посты за неделю", color="white", fontsize=12)
    ax2.grid(True, alpha=0.1, color="white", axis="x")

    for i, bar in enumerate(bars2):
        if names[i] == "eddytester":
            bar.set_color("#ff6b6b")

    fig.tight_layout()
    fpath = CHARTS_DIR / f"engagement_{date.today().isoformat()}.png"
    fig.savefig(fpath, dpi=120, facecolor="#1e1e1e")
    plt.close(fig)
    return fpath


def chart_category_breakdown(own_posts: list):
    """Pie chart: post categories for own channel."""
    _ensure_chart_dir()

    from collections import Counter
    cats = Counter(p.get("category", "other") for p in own_posts)
    if not cats:
        return None

    fig, ax = plt.subplots(figsize=(7, 5))
    fig.patch.set_facecolor("#1e1e1e")
    ax.set_facecolor("#1e1e1e")

    labels = list(cats.keys())
    sizes = list(cats.values())
    colors_list = ["#ff6b6b", "#4ecdc4", "#45b7d1", "#96ceb4", "#ffeaa7", "#dfe6e9", "#a29bfe", "#fd79a8"][:len(labels)]
    explode = [0.05] * len(labels)

    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, autopct="%1.0f%%", colors=colors_list,
        explode=explode, startangle=90, textprops={"color": "white", "fontsize": 9},
    )
    for t in autotexts:
        t.set_color("white")
        t.set_fontsize(8)

    ax.set_title("Категории постов @eddytester", color="white", fontsize=12, pad=12)
    fig.tight_layout()
    fpath = CHARTS_DIR / f"categories_{date.today().isoformat()}.png"
    fig.savefig(fpath, dpi=120, facecolor="#1e1e1e")
    plt.close(fig)
    return fpath


# ══════════════════════════════════════════════════════════════════════════
#   REPORT GENERATION
# ══════════════════════════════════════════════════════════════════════════


def _week_range() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    return f"{monday.isoformat()} — {sunday.isoformat()}"


def _week_number() -> str:
    return f"{date.today():%Y-W%W}"


def _fmt_big(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def _build_goals_section() -> str:
    lines = ["## 🎯 Цели канала", ""]
    for priority in ["P0", "P1", "P2"]:
        goals = [g for g in GOALS if g["priority"] == priority]
        if goals:
            lines.append(f"### {priority}")
            for g in goals:
                lines.append(f"- **{g['name']}** — {g['metric']}")
            lines.append("")
    return "\n".join(lines)


def _build_metrics_section(channel_summary: list) -> str:
    lines = ["## 📊 Метрики за неделю", ""]
    lines.append("| Канал | Посты | Просмотры (средн) | Вовлечение (средн) | Notable |")
    lines.append("|-------|-------|-------------------|-------------------|---------|")

    for c in channel_summary:
        avg_engage = round(c["avg_views"] + c["avg_replies"] * 3 + c["avg_forwards"] * 5)
        marker = " ⬅️" if c["channel_name"] == "@eddytester" else ""
        lines.append(
            f"| {c['channel_name']}{marker} | {c['total_posts']} | "
            f"{_fmt_big(round(c['avg_views']))} | {_fmt_big(avg_engage)} | {c['notable_count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def _build_format_analysis(own_posts: list, weekly_posts: list) -> str:
    lines = ["## 📈 Анализ форматов", ""]
    fmt_perf = analyze_format_performance(own_posts)

    if fmt_perf:
        lines.append("| Категория | Постов | Avg просмотры | Avg вовлечение | Notable | Достоверность |")
        lines.append("|-----------|--------|--------------|----------------|---------|--------------|")
        for f in fmt_perf:
            lines.append(
                f"| {f['category']} | {f['posts']} | {_fmt_big(f['avg_views'])} | "
                f"{_fmt_big(f['avg_engagement'])} | {f['notable_count']} | "
                f"{f['confidence']['label']} |"
            )
        lines.append("")

        # Narrative
        if fmt_perf:
            best = fmt_perf[0]
            lines.append(f"**Лучший формат:** {best['category']} — {best['confidence']['label']}")
            if best['confidence']['level'] == "HIGH":
                lines.append(f"✅ Устойчивый паттерн. Стоит закреплять.")
            elif best['confidence']['level'] == "MEDIUM":
                lines.append(f"📊 Тренд намечается. Ещё 2-3 поста для подтверждения.")
            else:
                lines.append(f"🔬 Мало данных. Отслеживать.")
            lines.append("")
    else:
        lines.append("_Недостаточно данных за неделю._")
        lines.append("")

    # Timing analysis
    timing = analyze_best_timing(own_posts)
    if timing and timing.get("day_stats"):
        lines.append(f"**Лучший день:** {timing['best_day']}")
        lines.append(f"**Лучшее время:** {timing['best_hour']}")
        if timing["day_stats"]:
            days_detail = ", ".join(
                f"{d}: {s['count']}п, {_fmt_big(s['total_views'])}просм"
                for d, s in sorted(timing["day_stats"].items())
                if s["count"] > 0
            )
            lines.append(f"  _Распределение: {days_detail}_")
        lines.append("")
    return "\n".join(lines)


def _build_competitor_gap_section(channel_summary: list) -> str:
    lines = ["## 🔍 Сравнение с конкурентами", ""]
    gaps = compute_competitor_gap(channel_summary)
    if gaps:
        lines.append("| Конкурент | Наши avg просмотры | Их avg просмотры | Разрыв |")
        lines.append("|-----------|-------------------|-----------------|--------|")
        for g in gaps:
            gap_pct = f"+{round(g['views_gap'] * 100)}%" if g["views_gap"] > 0 else f"{round(g['views_gap'] * 100)}%"
            lines.append(
                f"| {g['competitor']} | {_fmt_big(g['our_avg_views'])} | "
                f"{_fmt_big(g['competitor_avg_views'])} | {gap_pct} |"
            )
        lines.append("")
    else:
        lines.append("_Недостаточно данных для сравнения._")
        lines.append("")
    return "\n".join(lines)


def _build_engagement_quality_section(eq: dict) -> str:
    lines = ["## 💬 Качество вовлечения", ""]
    if not eq:
        lines.append("_Нет данных._")
        lines.append("")
        return "\n".join(lines)

    total = len(eq.get("all", []))
    community = len(eq.get("community", []))
    viral = len(eq.get("viral", []))
    read_only = len(eq.get("read_only", []))

    lines.append(f"Всего постов: {total}")
    if total > 0:
        lines.append(f"- 🤝 Комьюнити (реплаи > репосты): {community} ({community*100//total}%)")
        lines.append(f"- 🔄 Виральный (репосты > реплаи): {viral} ({viral*100//total}%)")
        lines.append(f"- 👁 Читают, не реагируют: {read_only} ({read_only*100//total}%)")
    lines.append("")

    if community > viral and community > 0:
        lines.append("**Тип аудитории:** Комьюнити-канал. Люди обсуждают, но не шерят.")
        lines.append("→ Укрепляй связь: больше вопросов, дискуссий, личного опыта.")
    elif viral > community and viral > 0:
        lines.append("**Тип аудитории:** Виральный. Посты расходятся, но не обсуждаются.")
        lines.append("→ Добавь CTA и вопросы, чтобы конвертировать охват в диалог.")
    lines.append("")
    return "\n".join(lines)


def _build_recommendations(gaps: list, fmt_perf: list, eq: dict, goals_review: list) -> str:
    """Generate actionable recommendations based on all data."""
    lines = ["## 💡 Рекомендации на неделю", ""]

    # Goal-based recommendation
    unsold_practicum = any("Practicum" in g.get("name", "") and g.get("status") != "done"
                          for g in goals_review)
    if unsold_practicum:
        lines.append("### 1. Practicum — P0")
        lines.append("Цель недели: продвинуться к продажам. Контент вокруг Practicum:")
        lines.append("- Кейс: как баг из Practicum помог на реальной работе")
        lines.append("- Разбор: что внутри API-симулятора (подогрев)")
        lines.append("- CTA: ссылка на бот в каждом втором посте")
        lines.append("")

    # Format recommendations
    if fmt_perf:
        best = fmt_perf[0]
        if best["confidence"]["level"] in ("HIGH", "MEDIUM"):
            lines.append(f"### 2. Закреплять: {best['category']}")
            lines.append(f"Формат показывает лучший результат. Минимум 2 поста на этой неделе.")
            lines.append("")

    # Gap-based
    if gaps and gaps[0]["views_gap"] > 0.5:
        top_comp = gaps[0]["competitor"]
        lines.append(f"### 3. Смотреть на {top_comp}")
        lines.append(f"Отставание по просмотрам {round(gaps[0]['views_gap']*100)}%. ")
        lines.append(f"Проанализируй 5 их последних постов — что в заголовках, какой CTA?")
        lines.append("")

    # Engagement quality
    if eq:
        community = len(eq.get("community", []))
        viral = len(eq.get("viral", []))
        read_only = len(eq.get("read_only", []))
        if read_only > community + viral and read_only > 0:
            lines.append("### 4. Работа над вовлечением")
            lines.append(f"{read_only} постов без реакции — слишком много.")
            lines.append("Правило: перед публикацией проверить — есть ли вопрос/механика/CTA?")
            lines.append("")

    if not unsold_practicum and not fmt_perf and not gaps:
        lines.append("_Недостаточно данных для рекомендаций._")
        lines.append("")

    return "\n".join(lines)


def _build_notable_summary() -> str:
    """Brief notable post summary."""
    notable_posts = db.get_notable_posts(limit=5)
    if not notable_posts:
        return ""

    lines = ["## ⭐ Notable посты недели", ""]
    for n in notable_posts[:5]:
        why = (n.get("why_works") or "")[:120]
        lines.append(f"- **{n['channel_name']}** tg#{n['tg_post_id']}: {why}")
    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
#   MAIN
# ══════════════════════════════════════════════════════════════════════════


def build_review() -> dict:
    """Build full strategy review. Returns {markdown, charts:[paths]}."""
    chart_paths = []

    # Fetch data
    channel_summary = get_channel_weekly_summary()
    weekly_posts = get_weekly_posts(days=7)
    daily_trend = get_daily_trend(days=14)

    own_posts = [p for p in weekly_posts if p.get("channel_name") == "@eddytester"]
    eq = get_engagement_quality(days=7) if own_posts else {}
    fmt_perf = analyze_format_performance(own_posts) if own_posts else []
    gaps = compute_competitor_gap(channel_summary)

    # Generate charts
    try:
        if daily_trend:
            p = chart_views_trend(daily_trend, days=14)
            chart_paths.append(str(p))
        if channel_summary:
            p = chart_engagement_comparison(channel_summary)
            chart_paths.append(str(p))
        if own_posts:
            p = chart_category_breakdown(own_posts)
            if p:
                chart_paths.append(str(p))
    except Exception as e:
        print(f"[charts] Warning: {e}")

    # Goals status
    goals_review = list(GOALS)

    # Build markdown
    week_label = _week_number()
    sections = [
        f"# Стратегический обзор — {week_label}",
        "",
        f"_{_week_range()}_",
        "",
        "---",
        "",
        _build_goals_section(),
        "---",
        "",
        _build_metrics_section(channel_summary),
        "---",
        "",
        _build_format_analysis(own_posts, weekly_posts),
        "---",
        "",
        _build_competitor_gap_section(channel_summary),
        "---",
        "",
        _build_engagement_quality_section(eq),
        "---",
        "",
        _build_notable_summary(),
        "---",
        "",
        _build_recommendations(gaps, fmt_perf, eq, goals_review),
        "---",
        "",
        "## 📸 Графики",
        "",
    ]

    for cp in chart_paths:
        rel = Path(cp).relative_to(Path("/root/obsidian-vault/eddytester/Стратегия/Анализ/Weekly").parent.parent.parent.parent)
        sections.append(f"![]({rel})")
        sections.append("")

    sections.append(f"\n_Сгенерировано {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n")

    return {"markdown": "\n".join(sections), "charts": chart_paths}


def save_review(review: dict) -> str:
    """Save review markdown to Obsidian."""
    os.makedirs(WEEKLY_DIR, exist_ok=True)
    fpath = WEEKLY_DIR / f"{_week_number()}.md"
    fpath.write_text(review["markdown"], encoding="utf-8")
    return str(fpath)


def get_longread_summary(review: dict) -> str:
    """TG-friendly summary with key findings (~3500 chars)."""
    md = review["markdown"]
    lines = md.split("\n")
    summary = []
    total = len(lines)

    # 1. Header
    for i, line in enumerate(lines):
        if line.startswith("# Стратеги"):
            summary.append(line.replace("# ", "📊 *", 1) + "*")
            if i + 1 < total and lines[i+1].startswith("_"):
                summary.append(lines[i+1])
            break
    summary.append("")

    # 2. Our metrics (first row of metrics table)
    in_metrics = False
    for line in lines:
        if "Метрики за неделю" in line:
            in_metrics = True
            continue
        if in_metrics and line.startswith("| @"):
            summary.append(f"📈 *Канал:* {line}")
            break
    summary.append("")

    # 3. Best format
    in_formats = False
    for line in lines:
        if "Анализ форматов" in line:
            in_formats = True
            continue
        if in_formats and line.startswith("**Лучший"):
            summary.append(f"🏆 {line.strip('*')}")
            # Next non-empty line is confidence follow-up
            continue
        if in_formats and line.startswith("✅") or line.startswith("📊") or line.startswith("🔬"):
            summary.append(f"  {line}")
            summary.append("")
            break

    # 4. Engagement quality (compact)
    in_eq = False
    eq_lines = []
    for line in lines:
        if "Качество вовлечения" in line:
            in_eq = True
            continue
        if in_eq:
            if line.startswith("---") or line.startswith("## 🔍"):
                break
            if line.startswith("- ") or line.startswith("**Тип") or line.startswith("→"):
                eq_lines.append(line)
    if eq_lines:
        summary.append("💬 *Вовлечение:*")
        summary.extend(eq_lines[:4])
        summary.append("")

    # 5. Top recommendation
    in_recs = False
    rec_lines = []
    for line in lines:
        if "Рекомендации на неделю" in line:
            in_recs = True
            continue
        if in_recs:
            if line.startswith("---") or line.startswith("## 📸"):
                break
            if line and not line.startswith("_"):
                rec_lines.append(line)
    if rec_lines:
        summary.append("🎯 *Рекомендации:*")
        for rl in rec_lines[:8]:
            summary.append(rl)
        summary.append("")

    # 6. Footer with charts note + link
    summary.append(f"_Всего {len(review.get('charts', []))} графиков — прикреплены выше_")
    summary.append(f"_Полный обзор: Стратегия/Анализ/Weekly/{_week_number()}.md_")

    return "\n".join(summary)


def main():
    do_save = "--save" in sys.argv
    do_send = "--send" in sys.argv

    review = build_review()
    print(review["markdown"])

    if do_save:
        fpath = save_review(review)
        print(f"\n[save] {fpath}")
        print(f"[save] {len(review['charts'])} charts saved")

    if do_send:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bsa"))
            from telegram_bot import send_message, send_photo

            # Send concise review (fits in TG, ~4K chars)
            summary = get_longread_summary(review)
            send_message(summary)

            # Send charts as photos with captions
            for i, cp in enumerate(review.get("charts", [])):
                chart_path = Path(cp)
                if chart_path.exists():
                    caption = f"📈 График {i+1}/{len(review['charts'])}"
                    send_photo(caption, str(chart_path))

            # If the full review is significantly longer, send last chunk
            full_lines = review["markdown"].split("\n")
            if len(full_lines) > 80 and len(summary) < 1500:
                extra = "\n".join(full_lines[-30:])  # recommendations + footer
                send_message(f"📌 **Ключевые рекомендации:**\n\n{extra[:2000]}")

            print(f"[send] Sent {len(review.get('charts', []))} charts + summary")
        except Exception as e:
            print(f"[send] Failed: {e}")

    return review


if __name__ == "__main__":
    main()

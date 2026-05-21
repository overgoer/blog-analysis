#!/usr/bin/env python3
"""
Content Inspector — инструмент для анализа контента @eddytester.

Используется BSA Agent и BSA API Bridge для анализа:
  - Посты за период (из content_map_index.json)
  - Темы, теги, ER (если есть)
  - Бэклог постов из стратегии

Usage:
    from content_inspector import inspect_posts, inspect_strategy_backlog, format_posts_report
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
INDEX_FILE = BASE / "data" / "content_map_index.json"
VAULT_DIR = Path("/root/obsidian-vault/eddytester/Стратегия")


def inspect_posts(days=30):
    """
    Возвращает посты из content_map_index.json за последние N дней.
    
    Args:
        days: int — период в днях (7 = неделя, 30 = месяц, 90 = квартал)
        
    Returns:
        list[dict] — посты с полями: date, title, angle, tags, summary, file_path
    """
    if not INDEX_FILE.exists():
        return []

    try:
        posts = json.loads(INDEX_FILE.read_text())
    except (json.JSONDecodeError, Exception):
        return []

    if not isinstance(posts, list):
        return []

    cutoff = datetime.now() - timedelta(days=days)
    recent = []
    for p in posts:
        try:
            post_date = datetime.strptime(p.get("date", "2000-01-01"), "%Y-%m-%d")
            if post_date >= cutoff:
                recent.append(p)
        except ValueError:
            continue

    return recent


def inspect_posts_by_tags(tags, days=90):
    """
    Ищет посты по тегам за период.
    
    Args:
        tags: list[str] — теги для поиска
        days: int — период в днях
        
    Returns:
        list[dict] — подходящие посты
    """
    posts = inspect_posts(days=days)
    query = set(t.lower() for t in tags)
    result = []
    for p in posts:
        post_tags = set(t.lower() for t in p.get("tags", []))
        if query & post_tags:  # пересечение множеств
            result.append(p)
    return result


def inspect_strategy_backlog(max_chars=3000):
    """
    Читает бэклог постов из стратегии (Бэклог.md).
    
    Args:
        max_chars: int — макс. длина текста
        
    Returns:
        str — содержимое бэклога
    """
    backlog_file = VAULT_DIR / "Бэклог.md"
    if not backlog_file.exists():
        return ""
    
    text = backlog_file.read_text()
    return text[:max_chars]


def inspect_vault_posts(pattern="*.md", max_files=20):
    """
    Читает последние посты из Obsidian vault (папка Посты).
    
    Args:
        pattern: str — glob-паттерн
        max_files: int — макс. количество файлов
        
    Returns:
        list[dict] — посты с метаданными
    """
    posts_dir = VAULT_DIR.parent / "Посты"
    if not posts_dir.exists():
        return []
    
    files = sorted(posts_dir.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    result = []
    for f in files[:max_files]:
        try:
            text = f.read_text()
            # Пробуем вытащить первую строку как заголовок
            title = text.split("\n")[0].strip("# ").strip() if text else f.stem
            result.append({
                "file": f.name,
                "title": title,
                "path": str(f),
                "preview": text[:500],
            })
        except Exception:
            continue
    return result


def format_posts_report(posts):
    """
    Форматирует список постов для вставки в промпт.
    
    Args:
        posts: list[dict] — посты из inspect_posts()
        
    Returns:
        str — отформатированный текст
    """
    if not posts:
        return "Нет постов за период."
    
    lines = []
    lines.append(f"**Посты ({len(posts)}):**")
    lines.append("")
    for p in posts:
        date = p.get("date", "?")
        title = p.get("title", "?")
        tags = ", ".join(p.get("tags", []))
        summary = p.get("summary", "")[:150]
        lines.append(f"  - **{date}**: {title}")
        if tags:
            lines.append(f"    Теги: {tags}")
        if summary:
            lines.append(f"    {summary}")
        lines.append("")
    
    return "\n".join(lines)


if __name__ == "__main__":
    print("=== Posts last 30 days ===")
    posts = inspect_posts(days=30)
    print(format_posts_report(posts))
    
    print("\n=== Strategy backlog ===")
    backlog = inspect_strategy_backlog()
    print(f"Backlog: {len(backlog)} chars")
    print(backlog[:500])

#!/usr/bin/env python3
"""Runtime config — user-managed category keywords and custom metrics.

Stored in data/runtime_config.json (NOT in git).
Bizzy manages this via tools. User changes persist across restarts.
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
CONFIG_FILE = DATA_DIR / "runtime_config.json"

DEFAULT = {
    "category_overrides": {},    # {"CATEGORY_KEYWORDS": {"api/bugs": ["kw1", "kw2"]}, "GOAL_KEYWORDS": {...}}
    "suppressed_keywords": {},   # {"CATEGORY_KEYWORDS": {"api/bugs": ["ошибк"]}} — remove from base config
    "custom_metrics": [],        # [{"name": "er", "formula": "avg_views / NULLIF(subscribers, 0)", "description": "..."}]
}


def _ensure():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT, ensure_ascii=False, indent=2))


def load():
    _ensure()
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT)


def save(cfg: dict):
    _ensure()
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2))


# ── Category keyword overrides ────────────────────────────────────────

def get_keyword_overrides(category_type: str) -> dict:
    """Get per-category keyword additions. category_type: CATEGORY_KEYWORDS or GOAL_KEYWORDS."""
    cfg = load()
    return cfg.get("category_overrides", {}).get(category_type, {})


def get_suppressed_keywords(category_type: str) -> dict:
    """Get keywords to remove from base config. {category: [keyword, ...]}"""
    cfg = load()
    return cfg.get("suppressed_keywords", {}).get(category_type, {})


def add_keyword(category_type: str, category: str, keyword: str) -> str:
    """Add a keyword to a category. category_type: CATEGORY_KEYWORDS or GOAL_KEYWORDS."""
    cfg = load()
    overrides = cfg.setdefault("category_overrides", {})
    cat_overrides = overrides.setdefault(category_type, {})
    keywords = cat_overrides.setdefault(category, [])
    if keyword.lower() not in [k.lower() for k in keywords]:
        keywords.append(keyword)
        save(cfg)
    return f"✅ Ключевое слово «{keyword}» добавлено в {category_type}.{category}"


def remove_keyword(category_type: str, category: str, keyword: str) -> str:
    """Remove a keyword from a category override."""
    cfg = load()
    overrides = cfg.get("category_overrides", {})
    cat_overrides = overrides.get(category_type, {})
    keywords = cat_overrides.get(category, [])
    before = len(keywords)
    cat_overrides[category] = [k for k in keywords if k.lower() != keyword.lower()]
    if len(cat_overrides[category]) < before:
        save(cfg)
        return f"✅ Ключевое слово «{keyword}» удалено из {category_type}.{category}"
    return f"ℹ️ Ключевое слово «{keyword}» не найдено в {category_type}.{category}"


def suppress_keyword(category_type: str, category: str, keyword: str) -> str:
    """Suppress a base keyword from matching. Removes it from the live keyword list."""
    cfg = load()
    suppressed = cfg.setdefault("suppressed_keywords", {})
    cat_suppressed = suppressed.setdefault(category_type, {})
    kws = cat_suppressed.setdefault(category, [])
    if keyword.lower() not in [k.lower() for k in kws]:
        kws.append(keyword)
        save(cfg)
    return f"✅ Ключевое слово «{keyword}» подавлено в {category_type}.{category}"


def unsuppress_keyword(category_type: str, category: str, keyword: str) -> str:
    """Remove a keyword from the suppression list."""
    cfg = load()
    suppressed = cfg.get("suppressed_keywords", {})
    cat_suppressed = suppressed.get(category_type, {})
    kws = cat_suppressed.get(category, [])
    before = len(kws)
    cat_suppressed[category] = [k for k in kws if k.lower() != keyword.lower()]
    if len(cat_suppressed[category]) < before:
        save(cfg)
        return f"✅ Подавление «{keyword}» снято в {category_type}.{category}"
    return f"ℹ️ Подавление «{keyword}» не найдено."


def list_overrides() -> str:
    """List all keyword overrides AND suppressions."""
    cfg = load()
    lines = []
    overrides = cfg.get("category_overrides", {})
    if overrides:
        lines.append("📋 Добавленные ключевые слова:")
        for ctype, cats in overrides.items():
            lines.append(f"  {ctype}:")
            for cat, kws in cats.items():
                if kws:
                    lines.append(f"    {cat}: {', '.join(kws)}")
    suppressed = cfg.get("suppressed_keywords", {})
    if suppressed:
        lines.append("")
        lines.append("🚫 Подавленные ключевые слова:")
        for ctype, cats in suppressed.items():
            lines.append(f"  {ctype}:")
            for cat, kws in cats.items():
                if kws:
                    lines.append(f"    {cat}: {', '.join(kws)}")
    if not lines:
        return "📭 Нет переопределений категорий."
    return "\n".join(lines)


# ── Custom metrics ────────────────────────────────────────────────────

def get_custom_metrics() -> list:
    cfg = load()
    return cfg.get("custom_metrics", [])


def add_custom_metric(name: str, formula: str, description: str = "") -> str:
    """Add a custom metric. Formula can use: avg_views, avg_forwards, avg_replies, subscribers, posts."""
    cfg = load()
    metrics = cfg.setdefault("custom_metrics", [])
    for m in metrics:
        if m["name"] == name:
            return f"ℹ️ Метрика «{name}» уже существует."
    metrics.append({"name": name, "formula": formula, "description": description})
    save(cfg)
    return f"✅ Метрика «{name}» добавлена: {formula}"


def remove_custom_metric(name: str) -> str:
    cfg = load()
    metrics = cfg.get("custom_metrics", [])
    before = len(metrics)
    cfg["custom_metrics"] = [m for m in metrics if m["name"] != name]
    if len(cfg["custom_metrics"]) < before:
        save(cfg)
        return f"✅ Метрика «{name}» удалена."
    return f"ℹ️ Метрика «{name}» не найдена."


def list_custom_metrics() -> str:
    cfg = load()
    metrics = cfg.get("custom_metrics", [])
    if not metrics:
        return "📭 Нет кастомных метрик."
    lines = ["📊 Кастомные метрики:"]
    for m in metrics:
        lines.append(f"  • {m['name']} = {m['formula']}")
        if m.get("description"):
            lines.append(f"    _{m['description']}_")
    return "\n".join(lines)

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


def list_overrides() -> str:
    """List all keyword overrides."""
    cfg = load()
    overrides = cfg.get("category_overrides", {})
    if not overrides:
        return "📭 Нет переопределений категорий."
    lines = ["📋 Переопределения категорий:"]
    for ctype, cats in overrides.items():
        lines.append(f"\n  {ctype}:")
        for cat, kws in cats.items():
            lines.append(f"    {cat}: {', '.join(kws)}")
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

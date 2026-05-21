#!/usr/bin/env python3
"""
API Inspector — инструмент для анализа API-репозиториев Practicum.

Используется BSA Agent и BSA API Bridge для инспекции кода:
  - Список эндпоинтов (из server.js и src/routes)
  - Баги (аннотации // ❗️БАГ, // БАГ, // BUG)
  - TODO и ISSUE
  - Структура проекта

Usage:
    from api_inspector import inspect_api, inspect_api_v0, inspect_api_free_trial
    
    api_v0 = inspect_api_v0()
    api_free = inspect_api_free_trial()
    # или универсально:
    result = inspect_api("/root/v0-test-api")
"""

import os
import re
from pathlib import Path


def inspect_api(repo_path):
    """
    Универсальная инспекция любого API-репозитория.
    
    Args:
        repo_path: str или Path — путь к репозиторию
        
    Returns:
        dict с ключами: name, endpoints, bugs, todos, readme_summary, structure
    """
    repo = Path(repo_path)
    if not repo.exists():
        return {"error": f"Path not found: {repo_path}"}
    
    result = {
        "name": repo.name,
        "path": str(repo),
        "endpoints": [],
        "bugs": [],
        "todos": [],
        "issues": [],
        "readme_summary": "",
        "structure": [],
    }
    
    # README
    readme = repo / "README.md"
    if readme.exists():
        text = readme.read_text()
        result["readme_summary"] = text[:2000]
        # ISSUE/SUGGEST/TODO аннотации в README
        issues = re.findall(r"\[(ISSUE|SUGGEST|TODO|BUG)\].*?(?=\n\n|\Z)", text, re.DOTALL)
        result["issues"] = [i.strip() for i in issues if i.strip()]
    
    # BACKLOG.md
    backlog = repo / "BACKLOG.md"
    if backlog.exists():
        text = backlog.read_text()
        bugs = re.findall(r"\[BUG\].*?(?=\n###|\Z)", text, re.DOTALL)
        result["bugs"] = [b.strip() for b in bugs if b.strip()]
        todos = re.findall(r"\[ \].*?(?=\n)", text)
        result["todos"] = [t.strip() for t in todos if t.strip()]
    
    # server.js — корневой
    server_js = repo / "server.js"
    if server_js.exists():
        text = server_js.read_text()
        routes = re.findall(r'(?:app|router)\.(get|post|put|patch|delete|all)\([\'"]([^\'"]+)[\'"]', text)
        for m, p in routes:
            ep = f"{m.upper()} {p}"
            if ep not in result["endpoints"]:
                result["endpoints"].append(ep)
        # Баги в коде
        bug_annotations = re.findall(r'// ❗️БАГ|// БАГ|// ❌|// BUG|// bug|// Bug \d', text)
        if bug_annotations:
            result["bugs"].append(f"({len(bug_annotations)} аннотаций в server.js)")
    
    # src/routes — рекурсивно
    for pattern in ["src/routes", "src", "routes"]:
        src_dir = repo / pattern
        if src_dir.exists():
            for fpath in sorted(src_dir.rglob("*.js")):
                rel_path = fpath.relative_to(repo)
                text = fpath.read_text()
                routes = re.findall(r'(?:app|router)\.(get|post|put|patch|delete|all)\([\'"]([^\'"]+)[\'"]', text)
                for m, p in routes:
                    ep = f"{m.upper()} {p}"
                    if ep not in result["endpoints"]:
                        result["endpoints"].append(ep)
                bug_annotations = re.findall(r'// ❗️БАГ|// БАГ|// ❌|// BUG|// bug|// Bug \d', text)
                if bug_annotations:
                    result["bugs"].append(f"({len(bug_annotations)} аннотаций в {rel_path})")
            break  # нашли — выходим
    
    # Структура проекта (топ-уровень)
    for item in sorted(repo.iterdir()):
        if item.name.startswith(".") or item.name == "node_modules":
            continue
        if item.is_dir():
            result["structure"].append(f"📁 {item.name}/")
        else:
            result["structure"].append(f"📄 {item.name}")
    
    return result


def inspect_api_v0():
    """Удобная обёртка для v0-test-api."""
    return inspect_api("/root/v0-test-api")


def inspect_api_free_trial():
    """Удобная обёртка для free-trial-api."""
    return inspect_api("/root/free-trial-api")


def format_inspection_report(result):
    """Форматирует результат инспекции для вставки в промпт."""
    lines = []
    lines.append(f"## {result.get('name', '?')}")
    lines.append(f"**Путь:** {result.get('path', '?')}")
    lines.append("")
    
    endpoints = result.get("endpoints", [])
    lines.append(f"**Эндпоинты ({len(endpoints)}):**")
    for ep in endpoints[:20]:
        lines.append(f"  - {ep}")
    if len(endpoints) > 20:
        lines.append(f"  ... и ещё {len(endpoints) - 20}")
    lines.append("")
    
    bugs = result.get("bugs", [])
    if bugs:
        lines.append(f"**Баги ({len(bugs)}):**")
        for b in bugs[:10]:
            lines.append(f"  - {b[:200]}")
        lines.append("")
    
    issues = result.get("issues", [])
    if issues:
        lines.append(f"**ISSUE/SUGGEST ({len(issues)}):**")
        for i in issues[:10]:
            lines.append(f"  - {i[:200]}")
        lines.append("")
    
    todos = result.get("todos", [])
    if todos:
        lines.append(f"**TODO ({len(todos)}):**")
        for t in todos[:10]:
            lines.append(f"  - {t}")
        lines.append("")
    
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    
    print("=== v0-test-api ===")
    r1 = inspect_api_v0()
    print(format_inspection_report(r1))
    
    print("\n=== free-trial-api ===")
    r2 = inspect_api_free_trial()
    print(format_inspection_report(r2))

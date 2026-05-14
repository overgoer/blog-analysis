#!/usr/bin/env python3
"""
Dev Runner — запускает DeepSeek-TUI для задач в репозиториях.

Поток:
  1. Создаёт feature-ветку от main
  2. Запускает deepseek exec --auto с OS-level timeout
  3. Исключает .deepseek/ мусор, коммитит изменения
  4. Парсит [ISSUE]/[QUESTION]/[SUGGEST] из stdout и диффа
  5. При ошибке — откат ветки
  6. Возвращает структурированный результат
"""

import os
import sys
import subprocess
import json
from datetime import datetime
from pathlib import Path

REPOS = {
    "v0-test-api": {
        "path": "/root/v0-test-api",
        "description": "API для тестирования с известными багами (v1) и исправлениями (v2)",
    },
    "free-trial-api": {
        "path": "/root/free-trial-api",
        "description": "Бесплатное API для контента и демо",
    },
    "api-practicum-bot": {
        "path": "/root/api-practicum-bot",
        "description": "Telegram бот для воронки продаж практикума",
    },
}

DEEPSEEK_CMD = "deepseek"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_TIMEOUT = 600  # OS-level timeout (сек) — DeepSeek exec --auto медленный
IGNORE_PATTERNS = [".deepseek/"]  # не коммитим служебные файлы


def log(msg):
    print(f"[dev_runner] {msg}", flush=True)


def run_git(repo_path, *args):
    """Выполнить git команду в репозитории."""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result


def create_feature_branch(repo_path, branch_name):
    """Создать feature-ветку от main/master."""
    run_git(repo_path, "stash")
    run_git(repo_path, "checkout", "main")
    if run_git(repo_path, "rev-parse", "--verify", "main").returncode != 0:
        run_git(repo_path, "checkout", "master")
    run_git(repo_path, "pull", "--ff-only")
    result = run_git(repo_path, "checkout", "-b", branch_name)
    if result.returncode != 0:
        return {"success": False, "error": result.stderr.strip()}
    return {"success": True, "branch": branch_name}


def rollback_branch(repo_path, branch_name):
    """Откатить ветку — удалить и вернуться на main."""
    run_git(repo_path, "checkout", "main")
    run_git(repo_path, "branch", "-D", branch_name)
    run_git(repo_path, "stash", "pop")


def get_workspace_changes(repo_path):
    """Вернуть список изменённых файлов (исключая IGNORE_PATTERNS)."""
    result = run_git(repo_path, "status", "--porcelain")
    files = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        status = line[:2].strip()
        fname = line[3:].strip()
        # Skip ignored patterns
        if any(fname.startswith(p) for p in IGNORE_PATTERNS):
            continue
        files.append({"status": status, "file": fname})
    return files


def commit_changes(repo_path, message):
    """Добавить и закоммитить изменения (кроме IGNORE_PATTERNS)."""
    # Add all files (git doesn't add .deepseek/ if it's not tracked, but let's be explicit)
    run_git(repo_path, "add", "-A")
    # If .deepseek/ got added, unstage it
    for pattern in IGNORE_PATTERNS:
        run_git(repo_path, "reset", "--", pattern)
    result = run_git(repo_path, "diff", "--cached", "--quiet")
    if result.returncode == 0:
        return {"committed": False, "reason": "no changes to commit"}
    commit_result = run_git(repo_path, "commit", "-m", message[:72])
    if commit_result.returncode != 0:
        return {"committed": False, "reason": commit_result.stderr.strip()}
    return {"committed": True, "hash": commit_result.stdout.strip()}


def get_diff(repo_path, branch_name):
    """Получить diff ветки относительно main/master."""
    parent = "main" if run_git(repo_path, "rev-parse", "--verify", "main").returncode == 0 else "master"
    result = run_git(repo_path, "diff", parent, branch_name, "--", ".", "--", ".deepseek")
    return result.stdout


def parse_feedback(output, diff=""):
    """Извлечь ISSUE, QUESTION, SUGGEST из вывода агента."""
    sources = (output or "") + "\n" + (diff or "")
    issues = []
    questions = []
    suggests = []

    for line in sources.split("\n"):
        stripped = line.strip()
        if stripped.startswith("[ISSUE]"):
            issues.append(stripped.replace("[ISSUE]", "").strip())
        elif stripped.startswith("[QUESTION]"):
            questions.append(stripped.replace("[QUESTION]", "").strip())
        elif stripped.startswith("[SUGGEST]"):
            suggests.append(stripped.replace("[SUGGEST]", "").strip())

    return {"issues": issues, "questions": questions, "suggests": suggests}


def run_deepseek(repo_path, task_description):
    """Запустить DeepSeek-TUI exec --auto с OS-level timeout.

    Используем `timeout DEEPSEEK_TIMEOUT deepseek exec --auto "prompt"`.
    Это надёжнее Python-таймаута — SIGTERM корректно завершает процесс.
    """
    prompt = (
        f"Ты работаешь в репозитории {repo_path}.\n"
        f"{task_description}\n\n"
        "ВАЖНЫЕ ПРАВИЛА:\n"
        "- Если нашел проблему/баг/дыру — начни строку с [ISSUE]\n"
        "- Если есть вопрос — начни строку с [QUESTION]\n"
        "- Если есть предложение — начни строку с [SUGGEST]\n"
        "- Все изменения делай через запись файлов\n"
        "- Не пуши ничего в main/master\n"
    )

    cmd = [
        "timeout", str(DEEPSEEK_TIMEOUT),
        DEEPSEEK_CMD, "--model", DEEPSEEK_MODEL,
        "exec", "--auto",
        prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=DEEPSEEK_TIMEOUT + 30,  # запас 30 сек для самого timeout
            cwd=repo_path,
        )
        return {
            "success": result.returncode in (0, None),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "OS_TIMEOUT", "exit_code": -1}
    except FileNotFoundError:
        return {"success": False, "stdout": "", "stderr": "deepseek not found", "exit_code": -1}


def run_dev_task(repo_name, task_description):
    """Основная функция — запускает dev-задачу.

    Args:
        repo_name: ключ из REPOS
        task_description: текст задачи для агента

    Returns:
        dict с результатом (success, branch, diff, feedback, changes, etc.)
    """
    if repo_name not in REPOS:
        return {"success": False, "error": f"Unknown repo: {repo_name}"}

    repo = REPOS[repo_name]
    repo_path = repo["path"]

    if not os.path.isdir(repo_path):
        return {"success": False, "error": f"Repo path not found: {repo_path}"}

    # Create feature branch
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    branch_name = f"dev/{repo_name}-{timestamp}"

    log(f"Creating branch {branch_name} in {repo_name}...")
    branch_result = create_feature_branch(repo_path, branch_name)
    if not branch_result["success"]:
        return {"success": False, "error": branch_result["error"], "phase": "branch"}

    # Run DeepSeek-TUI
    log(f"Running DeepSeek-TUI in {repo_name}...")
    ai_result = run_deepseek(repo_path, task_description)

    # Check for changes
    changes = get_workspace_changes(repo_path)

    if not ai_result["success"]:
        if not changes:
            log(f"DeepSeek failed with no changes, rolling back {branch_name}...")
            rollback_branch(repo_path, branch_name)
            return {
                "success": False,
                "error": ai_result.get("stderr", "Unknown error")[:500],
                "phase": "deepseek",
                "branch": branch_name,
                "rolled_back": True,
            }
        else:
            log(f"DeepSeek exited with code {ai_result['exit_code']} but changes were made — keeping them")

    # Commit changes
    commit_msg = f"dev({repo_name}): {task_description[:60]}"
    commit_result = commit_changes(repo_path, commit_msg)

    # Get diff
    diff = get_diff(repo_path, branch_name) if commit_result.get("committed") else ""

    # Parse feedback
    feedback = parse_feedback(ai_result.get("stdout", ""), diff)

    log(f"Done — {repo_name}: {'committed' if commit_result.get('committed') else 'no changes'}")
    return {
        "success": True,
        "repo": repo_name,
        "branch": branch_name,
        "diff": diff[:10000],
        "commit": commit_result,
        "changes": changes,
        "feedback": feedback,
        "ai_stdout": (ai_result.get("stdout") or "")[:2000],
        "ai_stderr": (ai_result.get("stderr") or "")[:500],
    }


def list_repos():
    """Список доступных репозиториев."""
    result = []
    for name, info in REPOS.items():
        exists = os.path.isdir(info["path"])
        result.append({"name": name, "path": info["path"], "exists": exists, "desc": info["description"]})
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Dev Runner — DeepSeek-TUI для репозиториев")
    parser.add_argument("repo", nargs="?", choices=list(REPOS.keys()), help="Репозиторий")
    parser.add_argument("task", nargs="?", help="Описание задачи")
    parser.add_argument("--list", action="store_true", help="Список репозиториев")

    args = parser.parse_args()

    if args.list:
        repos = list_repos()
        print(json.dumps(repos, indent=2, ensure_ascii=False))
        sys.exit(0)

    if not args.repo or not args.task:
        parser.print_help()
        sys.exit(1)

    result = run_dev_task(args.repo, args.task)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

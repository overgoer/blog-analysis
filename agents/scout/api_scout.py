#!/usr/bin/env python3
"""
API Scout — Product PM Agent.

Сканирует репозитории, анализирует issues/PRs/код,
сопоставляет с бизнес-контекстом и Strategic Bets от BSA,
предлагает улучшения и создаёт GitHub issues.

Usage:
  python3 api_scout.py --repo v0-test-api
  python3 api_scout.py --repo free-trial-api --create-issues
  python3 api_scout.py --list-repos
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "orchestrator"
sys.path.insert(0, str(BASE))
from bw_helper import BWVault

REPOS = {
    "v0-test-api": {
        "github": "overgoer/v0-test-api",
        "local": "/root/v0-test-api",
        "desc": "API для тестирования (v1 баги, v2 эталон)",
    },
    "free-trial-api": {
        "github": "overgoer/free-trial-api",
        "local": "/root/free-trial-api",
        "desc": "Бесплатное API для контента и демо",
    },
    "api-practicum-bot": {
        "github": "overgoer/api-practicum-bot",
        "local": "/root/api-practicum-bot",
        "desc": "Telegram бот для воронки продаж практикума",
    },
}

OBSIDIAN_DIR = Path("/root/obsidian-vault/eddytester")
PM_CONTEXT = BASE / "pm_context.json"
BSA_THREAD = BASE.parent / "bsa" / "bsa_thread.json"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[api_scout] {ts} {msg}", flush=True)


# ── Bitwarden ────────────────────────────────────────────────────────────────

def load_github_token(vault=None):
    """Load GitHub PAT from Bitwarden."""
    if vault is None:
        vault = BWVault()
    token = vault.get_password("GitHub PAT")
    if token:
        return token
    log("WARN: GitHub PAT not found in Bitwarden")
    return os.environ.get("GITHUB_TOKEN")


def load_deepseek_key(vault=None):
    """Load DeepSeek API key from Bitwarden."""
    if vault is None:
        vault = BWVault()
    key = vault.get_password("DeepSeek API Key")
    if key:
        return key
    log("WARN: DeepSeek key not found in Bitwarden")
    return os.environ.get("DEEPSEEK_API_KEY")


# ── Context Loading ──────────────────────────────────────────────────────────

def load_pm_context():
    """Load pm_context.json. Returns dict or None."""
    if not PM_CONTEXT.exists():
        log("ERROR: pm_context.json not found")
        return None
    with open(PM_CONTEXT) as f:
        return json.load(f)


def load_bsa_bets():
    """Load latest BSA Strategic Bets from bsa_thread.json."""
    if not BSA_THREAD.exists():
        return None
    try:
        with open(BSA_THREAD) as f:
            thread = json.load(f)
        if thread.get("finalized") and thread.get("current_bets"):
            return thread["current_bets"]
        return thread.get("current_bets", [])
    except (json.JSONDecodeError, FileNotFoundError):
        return None


# ── GitHub API ───────────────────────────────────────────────────────────────

def gh_request(token, method, path, body=None):
    """Make a GitHub API request. Returns (status_code, data_dict)."""
    url = f"https://api.github.com{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "api-scout",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read().decode())
            return r.status, resp
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode())
        except Exception:
            err = {"message": str(e)}
        return e.code, err
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, {"error": str(e)}


def fetch_issues(token, repo, state="open", per_page=20):
    """Fetch issues from a GitHub repo."""
    path = f"/repos/{repo}/issues?state={state}&per_page={per_page}&sort=created&direction=desc"
    status, data = gh_request(token, "GET", path)
    if status == 200 and isinstance(data, list):
        return data
    log(f"GitHub issues error ({status}): {data.get('message', '?')}")
    return []


def fetch_pulls(token, repo, state="open", per_page=10):
    """Fetch open PRs."""
    path = f"/repos/{repo}/pulls?state={state}&per_page={per_page}"
    status, data = gh_request(token, "GET", path)
    if status == 200 and isinstance(data, list):
        return data
    log(f"GitHub pulls error ({status}): {data.get('message', '?')}")
    return []


def fetch_commits(token, repo, per_page=10):
    """Fetch recent commits."""
    path = f"/repos/{repo}/commits?per_page={per_page}"
    status, data = gh_request(token, "GET", path)
    if status == 200 and isinstance(data, list):
        return data
    log(f"GitHub commits error ({status}): {data.get('message', '?')}")
    return []


def create_github_issue(token, repo, title, body, labels=None):
    """Create a GitHub issue. Returns (status_code, data_dict)."""
    payload = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    status, data = gh_request(token, "POST", f"/repos/{repo}/issues", payload)
    if status == 201:
        log(f"Issue created: {title[:60]} (#{data.get('number', '?')})")
    else:
        log(f"Issue create error ({status}): {data.get('message', '?')}")
    return status, data


# ── DeepSeek Analysis ────────────────────────────────────────────────────────

def call_deepseek(key, system_prompt, user_prompt, temperature=0.3, max_tokens=4096):
    """Call DeepSeek API. Returns response text or None."""
    import subprocess
    payload = json.dumps({
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    })
    try:
        r = subprocess.run(
            ["curl", "-s", "https://api.deepseek.com/chat/completions",
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "-d", payload],
            capture_output=True, text=True, timeout=120,
        )
        resp = json.loads(r.stdout)
        return resp["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"DeepSeek API error: {e}")
        return None


def build_analysis_prompt(ctx, repo_name, repo_info, issues, pulls, commits, bsa_bets):
    """Build system + user prompt for repo analysis."""
    products_text = ""
    for p in ctx.get("products", []):
        name = p.get("name", "?")
        priority = p.get("priority", "?")
        products_text += f"\n  - {name} [priority: {priority}]"

    criteria_text = ""
    for c in ctx.get("decision_criteria", []):
        cid = c.get("id", "?")
        cq = c.get("question", "")
        criteria_text += f"\n  {cid}: {cq}"

    bets_text = ""
    if bsa_bets:
        for bet in bsa_bets:
            bets_text += f"\n  - {bet.get('title', '?')}: {bet.get('description', '')}"

    issues_text = ""
    for i in issues:
        issues_text += f"\n  - #{i['number']} {i['title']}"

    pulls_text = ""
    for p in pulls:
        pulls_text += f"\n  - !#{p['number']} {p['title']} ({p.get('state', '?')})"

    recent_commits = ""
    for c in commits[:5]:
        msg = c.get("commit", {}).get("message", "").split("\n")[0]
        recent_commits += f"\n  - {msg[:80]}"

    system_prompt = (
        f"Ты API Scout — Product PM Agent для экосистемы @eddytester.\n\n"
        f"Твоя роль: анализировать репозиторий и предлагать улучшения,\n"
        f"которые соответствуют бизнес-целям владельца.\n\n"
        f"## Бизнес-контекст\n"
        f"Продукты:{products_text}\n\n"
        f"## Критерии принятия решений\n"
        f"{criteria_text}\n\n"
        f"## Стратегические ставки (от BSA)\n"
        f"{bets_text or 'Нет активных стратегических ставок'}\n\n"
        f"## Принципы\n"
        f"- Предлагай только то, что помогает бизнесу (контент, продажи, продукт)\n"
        f"- Не предлагай рефакторинг без бизнес-обоснования\n"
        f"- Учитывай, что Эд один — каждое изменение требует его времени\n"
        f"- Приоритет: контент > продукт > инфраструктура\n"
        f"- Бесплатные решения предпочтительнее платных\n\n"
        f"## Формат ответа\n"
        f"Ответь в JSON:\n"
        f"{{\n"
        f'  "summary": "Краткое состояние репозитория",\n'
        f'  "findings": [\n'
        f'    {{"type": "bug|improvement|feature|security|content",\n'
        f'     "title": "Короткий заголовок",\n'
        f'     "description": "Что, почему, бизнес-ценность",\n'
        f'     "priority": "high|medium|low",\n'
        f'     "effort": "minutes|hours|days"}}\n'
        f'  ],\n'
        f'  "relevance_to_bsa": "Как findings связаны с текущими стратегическими ставками",\n'
        f'  "next_steps": ["Шаг 1", "Шаг 2"]\n'
        f"}}\n"
        f"Текст — на русском, термины — на английском."
    )

    user_prompt = (
        f"Проанализируй репозиторий {repo_name} ({repo_info['desc']}).\n\n"
        f"GitHub: {repo_info['github']}\n"
        f"Путь: {repo_info['local']}\n\n"
        f"## Текущие открытые issues\n"
        f"{issues_text or 'Нет открытых issues'}\n\n"
        f"## Текущие PR\n"
        f"{pulls_text or 'Нет открытых PR'}\n\n"
        f"## Последние коммиты\n"
        f"{recent_commits or 'Нет данных'}\n\n"
        f"Найди проблемы и возможности, которые соответствуют бизнес-контексту.\n"
        f"Учитывай стратегические ставки BSA при приоритизации."
    )

    return system_prompt, user_prompt


# ── Main ─────────────────────────────────────────────────────────────────────

def scan_repo(repo_name, create_issues=False, dry_run=False):
    """Main scanning function."""
    if repo_name not in REPOS:
        log(f"Unknown repo: {repo_name}")
        return {"error": f"Unknown repo: {repo_name}"}

    repo_info = REPOS[repo_name]
    vault = BWVault()
    github_token = load_github_token(vault)
    deepseek_key = load_deepseek_key(vault)

    if not github_token:
        log("ERROR: No GitHub token available")
        return {"error": "No GitHub token"}

    if not deepseek_key:
        log("ERROR: No DeepSeek key available")
        return {"error": "No DeepSeek key"}

    # Load context
    ctx = load_pm_context()
    if not ctx:
        return {"error": "No pm_context"}

    bsa_bets = load_bsa_bets()
    if bsa_bets:
        log(f"Loaded {len(bsa_bets)} BSA Strategic Bets")

    # Fetch GitHub data
    log(f"Fetching issues from {repo_info['github']}...")
    issues = fetch_issues(github_token, repo_info["github"])
    log(f"  {len(issues)} open issues")

    log(f"Fetching PRs...")
    pulls = fetch_pulls(github_token, repo_info["github"])
    log(f"  {len(pulls)} open PRs")

    log(f"Fetching recent commits...")
    commits = fetch_commits(github_token, repo_info["github"])
    log(f"  {len(commits)} recent commits")

    # DeepSeek analysis
    log(f"Running DeepSeek analysis for {repo_name}...")
    system_prompt, user_prompt = build_analysis_prompt(
        ctx, repo_name, repo_info, issues, pulls, commits, bsa_bets,
    )

    result = call_deepseek(deepseek_key, system_prompt, user_prompt)
    if not result:
        log("ERROR: DeepSeek returned no result")
        return {"error": "DeepSeek returned no result"}

    # Parse JSON response
    try:
        analysis = json.loads(result)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown
        import re
        m = re.search(r'```(?:json)?\s*([\s\S]*?)```', result)
        if m:
            try:
                analysis = json.loads(m.group(1))
            except json.JSONDecodeError:
                analysis = {"raw": result[:2000]}
        else:
            analysis = {"raw": result[:2000]}

    log(f"Analysis: {len(analysis.get('findings', []))} findings")
    log(f"Summary: {analysis.get('summary', '?')[:100]}")

    # Create issues for findings
    if create_issues and not dry_run:
        findings = analysis.get("findings", [])
        priority_map = {"high": ["api-scout"], "medium": ["api-scout"], "low": ["api-scout"]}
        for finding in findings:
            title = finding.get("title", "")
            desc = finding.get("description", "")
            priority = finding.get("priority", "medium")
            labels = priority_map.get(priority, ["api-scout"])
            create_github_issue(github_token, repo_info["github"], title, desc, labels)

    # Save analysis to Obsidian vault
    date_str = datetime.now().strftime("%Y-%m-%d")
    obsidian_dir = OBSIDIAN_DIR / "API Practicum" / "Scout"
    os.makedirs(obsidian_dir, exist_ok=True)

    md_lines = [
        f"# API Scout Analysis: {repo_name}\n",
        f"**Date:** {date_str}\n",
        f"**Repo:** [{repo_info['github']}](https://github.com/{repo_info['github']})\n",
        f"**Desc:** {repo_info['desc']}\n",
        "\n---\n",
        f"## Summary\n{analysis.get('summary', '')}\n",
        "\n---\n",
    ]

    findings = analysis.get("findings", [])
    if findings:
        md_lines.append(f"## Findings ({len(findings)})\n")
        for f in findings:
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(f.get("priority", "medium"), "⚪")
            md_lines.append(f"### {icon} {f['title']}\n")
            md_lines.append(f"**Priority:** {f.get('priority', '?')} | **Effort:** {f.get('effort', '?')}\n")
            md_lines.append(f"{f.get('description', '')}\n")

    bsa_text = analysis.get("relevance_to_bsa", "")
    if bsa_text:
        md_lines.append(f"\n## Relevance to BSA\n{bsa_text}\n")

    next_steps = analysis.get("next_steps", [])
    if next_steps:
        md_lines.append(f"\n## Next Steps\n")
        for i, step in enumerate(next_steps, 1):
            md_lines.append(f"{i}. {step}")

    obsidian_file = obsidian_dir / f"{repo_name}_{date_str}.md"
    with open(obsidian_file, "w") as f:
        f.write("\n".join(md_lines))
    log(f"Obsidian: {obsidian_file}")

    log(f"Scan complete: {repo_name}")
    return {
        "repo": repo_name,
        "summary": analysis.get("summary", ""),
        "findings_count": len(findings),
        "issues_created": create_issues and not dry_run,
        "obsidian_file": str(obsidian_file),
    }


def list_repos():
    """Print available repos."""
    for name, info in REPOS.items():
        exists = os.path.isdir(info["local"])
        print(f"  {name} -> {info['github']} [local: {'✓' if exists else '✗'}]")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="API Scout — Product PM Agent")
    parser.add_argument("--repo", choices=list(REPOS.keys()), help="Repo to scan")
    parser.add_argument("--list-repos", action="store_true", help="List available repos")
    parser.add_argument("--create-issues", action="store_true", help="Create GitHub issues for findings")
    parser.add_argument("--dry-run", action="store_true", help="Print analysis without creating issues")
    args = parser.parse_args()

    if args.list_repos or not args.repo:
        list_repos()
        return

    result = scan_repo(args.repo, create_issues=args.create_issues, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

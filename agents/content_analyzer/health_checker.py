#!/usr/bin/env python3
"""Health Checker — smoke tests for Practicum + Free Trial APIs.

Tests full CRUD cycle: POST create user → GET verify user exists.

Config:
  PRACTICUM_URL — base URL for v0-test-api on Timeweb
  FREE_TRIAL_URL — base URL for free-trial-api on Timeweb (or local)

Run manually:
  python3 health_checker.py

Writes results to OBSIDIAN_ХЕЛС_СТАТУС.md in vault.
"""

import json, os, sys, time
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

BASE = Path(__file__).resolve().parent

# ── Config ─────────────────────────────────────────────────────────────
PRACTICUM_URL = os.environ.get("PRACTICUM_URL", "http://85.193.81.51:3000")  # Timeweb server
FREE_TRIAL_URL = os.environ.get("FREE_TRIAL_URL", "http://85.193.81.51:3001")  # Timeweb server

OBSIDIAN_VAULT = Path("/root/obsidian-vault/eddytester/Стратегия")
HEALTH_FILE = OBSIDIAN_VAULT / "_ХЕЛС_СТАТУС.md"

# Auth
PRACTICUM_KEY = "test-api-key-123"

GREEN = "🟢"
RED = "🔴"
YELLOW = "🟡"
GRAY = "⚪"


def _req(method, url, headers=None, data=None, timeout=15):
    """Make HTTP request, return (status_code, body_dict or raw text, error)."""
    try:
        if data is not None and isinstance(data, dict):
            data = json.dumps(data).encode()
        r = Request(url, data=data, method=method)
        r.add_header("Content-Type", "application/json")
        if headers:
            for k, v in headers.items():
                r.add_header(k, v)
        resp = urlopen(r, timeout=timeout)
        body = resp.read().decode()
        try:
            return resp.status, json.loads(body), None
        except json.JSONDecodeError:
            return resp.status, body, None
    except URLError as e:
        return 0, None, str(e)
    except Exception as e:
        return 0, None, str(e)


def test_practicum():
    """Smoke test Practicum API: POST create user → GET verify."""
    if not PRACTICUM_URL:
        return {"status": "skipped", "reason": "PRACTICUM_URL not configured"}

    results = []
    headers = {"X-Fix-Bug": PRACTICUM_KEY}
    ts = str(int(time.time()))
    test_user = {"name": f"HealthCheck_{ts}", "age": 25}

    # POST create user
    url = f"{PRACTICUM_URL}/v1/api/users"
    status, body, err = _req("POST", url, headers=headers, data=test_user)
    if err or status >= 400:
        # Try v2
        url = f"{PRACTICUM_URL}/v2/api/users"
        status, body, err = _req("POST", url, headers=headers, data=test_user)

    if err:
        results.append({"test": "POST create user", "status": "fail", "detail": f"Connection error: {err}"})
    elif status >= 400:
        results.append({"test": "POST create user", "status": "fail", "detail": f"HTTP {status}: {body}"})
    else:
        created_id = None
        if isinstance(body, dict):
            created_id = body.get("id") or body.get("user", {}).get("id")
        results.append({
            "test": "POST create user",
            "status": "pass",
            "detail": f"HTTP {status}, user_id={created_id}"
        })

        # GET verify user exists
        if created_id:
            get_url = f"{url}/{created_id}"
        else:
            get_url = url.replace("/users", "/users")  # list all

        status2, body2, err2 = _req("GET", get_url, headers=headers)
        if err2:
            results.append({"test": "GET verify user", "status": "fail", "detail": f"Connection error: {err2}"})
        elif status2 >= 400:
            results.append({"test": "GET verify user", "status": "fail", "detail": f"HTTP {status2}: {body2}"})
        else:
            found = False
            if isinstance(body2, dict):
                found = body2.get("name") == test_user["name"]
            elif isinstance(body2, list):
                found = any(u.get("name") == test_user["name"] for u in body2)
            results.append({
                "test": "GET verify user",
                "status": "pass" if found else "warn",
                "detail": f"HTTP {status2}, user_found={found}"
            })

    return {"status": "completed", "results": results}


def test_free_trial():
    """Smoke test Free Trial API: get key → POST create user → GET verify."""
    results = []

    # Step 1: Get API key
    key_url = f"{FREE_TRIAL_URL}/free/api/keys"
    status, body, err = _req("POST", key_url)

    api_key = None
    if err:
        results.append({"test": "POST /free/api/keys", "status": "fail", "detail": f"Connection error: {err}"})
    elif status >= 400:
        results.append({"test": "POST /free/api/keys", "status": "fail", "detail": f"HTTP {status}: {body}"})
    else:
        if isinstance(body, dict):
            api_key = body.get("key") or body.get("api_key") or body.get("apiKey")
        results.append({
            "test": "POST /free/api/keys",
            "status": "pass" if api_key else "warn",
            "detail": f"HTTP {status}, key={'****' + api_key[-4:] if api_key else 'none'}"
        })

    if not api_key:
        results.append({"test": "POST create user", "status": "skipped", "detail": "No API key"})
        results.append({"test": "GET verify user", "status": "skipped", "detail": "No API key"})
        return {"status": "completed", "results": results}

    headers = {"X-Fix-Bug": api_key}
    ts = str(int(time.time()))
    test_user = {"name": f"HC_{ts}", "age": 30}

    # Step 2: POST create user
    url = f"{FREE_TRIAL_URL}/free/api/users"
    status, body, err = _req("POST", url, headers=headers, data=test_user)

    created_id = None
    if err:
        results.append({"test": "POST create user", "status": "fail", "detail": f"Connection error: {err}"})
    elif status >= 400:
        results.append({"test": "POST create user", "status": "fail", "detail": f"HTTP {status}: {body}"})
    else:
        # Free Trial POST wraps user in {"user": {id, name, ...}, "_upsell": "..."}
        if isinstance(body, dict):
            created_id = body.get("id") or body.get("user", {}).get("id")
        results.append({
            "test": "POST create user",
            "status": "pass",
            "detail": f"HTTP {status}, user_id={created_id}"
        })

    # Step 3: GET verify
    if created_id:
        get_url = f"{url}/{created_id}"
    else:
        get_url = url

    status2, body2, err2 = _req("GET", get_url, headers=headers)
    if err2:
        results.append({"test": "GET verify user", "status": "fail", "detail": f"Connection error: {err2}"})
    elif status2 >= 400:
        results.append({"test": "GET verify user", "status": "fail", "detail": f"HTTP {status2}: {body2}"})
    else:
        found = False
        if isinstance(body2, list):
            found = any(u.get("name") == test_user["name"] for u in body2)
        elif isinstance(body2, dict):
            # Free Trial GET returns {"users": [...], "_upsell": "..."}
            users_list = body2.get("users", body2.get("data", []))
            if isinstance(users_list, list) and users_list:
                found = any(u.get("name") == test_user["name"] for u in users_list)
            else:
                found = body2.get("name") == test_user["name"]
        results.append({
            "test": "GET verify user",
            "status": "pass" if found else "warn",
            "detail": f"HTTP {status2}, user_found={found}"
        })

    return {"status": "completed", "results": results}


def write_report(practicum, free_trial):
    """Write health status to _ХЕЛС_СТАТУС.md."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"# Хелс-статус API",
        f"",
        f"Последняя проверка: {ts}",
        f"",
    ]

    for label, result in [("Practicum API", practicum), ("Free Trial API", free_trial)]:
        if result["status"] == "skipped":
            lines.append(f"## {label} {GRAY} Пропущено")
            lines.append(f"Причина: {result.get('reason', 'не настроен')}")
            lines.append("")
            continue

        all_pass = all(r["status"] == "pass" for r in result.get("results", []))
        all_ok = all(r["status"] in ("pass", "skipped") for r in result.get("results", []))
        emoji = GREEN if all_pass else (YELLOW if all_ok else RED)

        lines.append(f"## {label} {emoji}")
        for r in result.get("results", []):
            s = {"pass": GREEN, "fail": RED, "warn": YELLOW, "skipped": GRAY}.get(r["status"], GRAY)
            lines.append(f"- {s} **{r['test']}** — {r['detail']}")
        lines.append("")

    lines.append("---")
    lines.append(f"*Авто-проверка {ts}*")

    report = "\n".join(lines)

    if HEALTH_FILE.parent.exists():
        HEALTH_FILE.write_text(report, encoding="utf-8")
        print(f"Report written: {HEALTH_FILE}")
    else:
        print(f"Vault path not found: {HEALTH_FILE.parent}")
        print("--- Report ---")
        print(report)

    return report


def main():
    print(f"🩺 Health Checker — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    print("\n📡 Practicum API...")
    practicum = test_practicum()
    for r in practicum.get("results", []):
        s = {"pass": GREEN, "fail": RED, "warn": YELLOW, "skipped": GRAY}[r["status"]]
        print(f"  {s} {r['test']}: {r['detail'][:120]}")

    print("\n📡 Free Trial API...")
    free_trial = test_free_trial()
    for r in free_trial.get("results", []):
        s = {"pass": GREEN, "fail": RED, "warn": YELLOW, "skipped": GRAY}[r["status"]]
        print(f"  {s} {r['test']}: {r['detail'][:120]}")

    print("\n📝 Writing report...")
    write_report(practicum, free_trial)
    print("Done.")


if __name__ == "__main__":
    main()

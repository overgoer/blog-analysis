#!/usr/bin/env python3
"""DEV Agent — Repo Scanner. Runs nightly to map all repos."""

import subprocess, json, datetime, os, sys

OUTPUT_DIR = "/root/blog-analysis/agents/dev"
PRACTICUM_HOST = "85.193.81.51"
PRACTICUM_PORT = "2222"
PRACTICUM_PASS = "tjVJPcQiw-?57b"

def ssh(cmd):
    """Run SSH command on practicum server."""
    full_cmd = f"sshpass -p {PRACTICUM_PASS} ssh -o StrictHostKeyChecking=no -p {PRACTICUM_PORT} root@{PRACTICUM_HOST} {cmd}"
    r = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=60)
    return r.stdout.strip(), r.stderr.strip()

def local(cmd):
    """Run command locally."""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return r.stdout.strip(), r.stderr.strip()

def scan_candidates_api():
    """Scan Candidates API repo."""
    stdout, _ = ssh("cat /home/claude_agent/projects/api-practicum/server.js")
    lines = stdout.split("\n") if stdout else []
    endpoints = []
    for l in lines:
        l = l.strip()
        if l.startswith("app.") and ("(" in l) and ("req, res" in l or "req" in l):
            endpoints.append(l.split("(")[0] if "(" in l else l)
    return {"file": "server.js", "lines": len(lines), "endpoints": list(set(endpoints))[:20]}

def scan_free_trial_api():
    """Scan Free Trial API repo."""
    stdout, _ = ssh("cat /root/free-trial-api/server.js")
    lines = stdout.split("\n") if stdout else []
    return {"file": "server.js", "lines": len(lines)}

def scan_practicum_bot():
    """Scan Practicum Bot repo."""
    stdout, _ = ssh("cat /root/api-practicum-bot/main.py")
    lines = stdout.split("\n") if stdout else []
    # Find bot commands and handlers
    handlers = [l.strip() for l in lines if "def " in l or "Command(" in l or "message" in l.lower()[:10]]
    return {"file": "main.py", "lines": len(lines), "handlers": handlers[:15]}

def scan_bugs():
    """Scan bugs documentation."""
    bugs, _ = ssh("cat /home/claude_agent/projects/api-practicum/docs/bugs.md 2>/dev/null | head -100")
    return bugs

def task_backlog():
    """Read existing task backlog."""
    try:
        with open(os.path.join(OUTPUT_DIR, "task_backlog.json")) as f:
            return json.load(f)
    except:
        return {"tasks": [], "completed": []}

def generate_report():
    """Generate the nightly repo report."""
    report = {
        "timestamp": datetime.datetime.now().isoformat(),
        "candidates_api": scan_candidates_api(),
        "free_trial_api": scan_free_trial_api(),
        "practicum_bot": scan_practicum_bot(),
        "bugs_summary": scan_bugs()[:300],
        "task_backlog": task_backlog()
    }
    out_path = os.path.join(OUTPUT_DIR, f"repo_scan_{datetime.date.today().isoformat()}.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    # Always keep a symlink to latest
    latest_path = os.path.join(OUTPUT_DIR, "latest_scan.json")
    with open(latest_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return report

if __name__ == "__main__":
    report = generate_report()
    print(f"✅ DEV Agent scan complete: {len(json.dumps(report))} chars")

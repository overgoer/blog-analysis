#!/usr/bin/env python3
"""DevOps tools: health check + deploy for Timeweb services."""
import subprocess, json, time, os

TIMEWEB_HOST = "85.193.81.51"
TIMEWEB_PORT = 2222
TIMEWEB_USER = "root"

SERVICES = {
    "v0-test-api": {
        "port": 3000,
        "path": "/var/www/v0-test-api/v0-test-api",
        "pm2_name": "v0-test-api",
        "ping": "/",
    },
    "free-trial-api": {
        "port": 3001,
        "path": "/root/free-trial-api",
        "pm2_name": "free-trial-api",
        "ping": "/",
    },
}

SSH_BASE = ["ssh", "-p", str(TIMEWEB_PORT),
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            f"{TIMEWEB_USER}@{TIMEWEB_HOST}"]


def _ssh(cmd):
    """Run command on Timeweb and return stdout."""
    result = subprocess.run(SSH_BASE + [cmd],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"SSH failed: {result.stderr[:500]}")
    return result.stdout.strip()


def _parse_pm2_table(output, keys):
    """Extract key-value pairs from PM2 table output."""
    vals = {}
    for line in output.split("\n"):
        line = line.strip()
        # Line format: │ key            │ value                                     │
        if "│" not in line:
            continue
        parts = [p.strip() for p in line.split("│") if p.strip()]
        if len(parts) < 2:
            continue
        key = parts[0].lower()
        val = parts[1]
        if key in keys:
            vals[key] = val
    return vals


def list_services():
    """Return available services with status summary."""
    services = []
    for name, info in SERVICES.items():
        services.append({
            "name": name,
            "port": info["port"],
            "path": info["path"],
        })
    return services


def check_service(service_name):
    """Health check: curl the service + verify PM2 status."""
    if service_name not in SERVICES:
        available = ", ".join(SERVICES.keys())
        return {"error": f"Unknown service: {service_name}. Available: {available}", "status": "unknown"}

    info = SERVICES[service_name]
    result = {"service": service_name, "port": info["port"]}

    # PM2 status
    try:
        pm2_out = _ssh(f"pm2 show {info['pm2_name']}")
        vals = _parse_pm2_table(pm2_out, ["status", "pid", "uptime", "restarts", "name"])
        result["pm2_status"] = vals.get("status", "unknown")
        result["pid"] = vals.get("pid", "unknown")
        result["uptime"] = vals.get("uptime", "unknown")
        result["restarts"] = vals.get("restarts", "unknown")
        result["pm2_running"] = vals.get("status") == "online"
    except Exception as e:
        result["pm2_status"] = f"error: {e}"

    # HTTP health check — any response means server is alive
    try:
        start = time.time()
        hc = subprocess.run(
            SSH_BASE + [f"curl -s -o /dev/null -w '%{{http_code}}' --connect-timeout 5 http://localhost:{info['port']}{info['ping']}"],
            capture_output=True, text=True, timeout=15,
        )
        elapsed = round(time.time() - start, 2)
        code = hc.stdout.strip()
        result["http_status"] = code if hc.returncode == 0 else "connection_failed"
        result["response_time"] = f"{elapsed}s"
        # Any HTTP response means server is alive (even 404, 401, 302)
        result["http_ok"] = code not in ("", "connection_failed", "000")
    except subprocess.TimeoutExpired:
        result["http_status"] = "timeout"
        result["response_time"] = ">15s"
        result["http_ok"] = False
    except Exception as e:
        result["http_status"] = f"error: {e}"
        result["http_ok"] = False

    overall = result.get("pm2_running", False) and result.get("http_ok", False)
    result["healthy"] = "✅" if overall else "❌"

    return result


def deploy_service(service_name, branch="main"):
    """Pull latest code from GitHub on Timeweb + restart PM2."""
    if service_name not in SERVICES:
        available = ", ".join(SERVICES.keys())
        return {"error": f"Unknown service: {service_name}. Available: {available}", "success": False}

    info = SERVICES[service_name]
    result = {"service": service_name, "branch": branch}

    # 1. Git stash/pull
    try:
        pull = _ssh(f"cd {info['path']} && git stash 2>/dev/null; git checkout {branch} 2>/dev/null; git pull origin {branch} 2>&1")
        result["pull"] = pull[:500]
    except Exception as e:
        result["error"] = f"git pull failed: {e}"
        result["success"] = False
        return result

    # 2. Restart PM2
    try:
        restart = _ssh(f"pm2 restart {info['pm2_name']} 2>&1")
        result["restart"] = restart[:300]

        # 3. Wait and verify
        time.sleep(3)
        health = check_service(service_name)
        result["health_check"] = health
        result["success"] = health.get("http_ok", False)
    except Exception as e:
        result["error"] = f"restart/verify failed: {e}"
        result["success"] = False

    return result


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        print(json.dumps(list_services(), indent=2, ensure_ascii=False))
    elif cmd == "check":
        name = sys.argv[2] if len(sys.argv) > 2 else "all"
        if name == "all":
            results = {s: check_service(s) for s in SERVICES}
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(check_service(name), indent=2, ensure_ascii=False))
    elif cmd == "deploy":
        name = sys.argv[2]
        branch = sys.argv[3] if len(sys.argv) > 3 else "main"
        print(json.dumps(deploy_service(name, branch), indent=2, ensure_ascii=False))

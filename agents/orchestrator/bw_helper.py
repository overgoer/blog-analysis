"""
Bitwarden helper for AI agents.

Reads/writes credentials via bw serve (localhost:8087).
Usage:
    from bw_helper import BWVault
    vault = BWVault()
    pw = vault.get_password("DeepSeek API Key")
    vault.add_item("my-service", "user", "pass", "notes")
"""

import json
import os
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

BW_SERVE_URL = "http://127.0.0.1:8087"
BW_ENV_FILE = Path("/root/.bw_env")


class BWVault:
    """Interface to Bitwarden vault via bw serve HTTP API."""

    def _get(self, path):
        url = f"{BW_SERVE_URL}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, ConnectionRefusedError) as e:
            return {"success": False, "error": str(e)}

    def list_items(self):
        """Return all items in the vault."""
        resp = self._get("/list/object/items")
        if resp.get("success"):
            return resp["data"]["data"]
        return []

    def find_item(self, name):
        """Find first item whose name matches (case-insensitive substring)."""
        name_lower = name.lower()
        for item in self.list_items():
            if name_lower in item.get("name", "").lower():
                return item
        return None

    def get_password(self, name):
        """Get password from vault by item name. Returns str or None."""
        item = self.find_item(name)
        if item:
            login = item.get("login") or {}
            return login.get("password")
        return None

    def get_username(self, name):
        """Get username from vault by item name. Returns str or None."""
        item = self.find_item(name)
        if item:
            login = item.get("login") or {}
            return login.get("username")
        return None

    def get_item(self, name):
        """Get full item dict by name. Returns dict or None."""
        return self.find_item(name)

    @staticmethod
    def _load_session():
        """Load BW_SESSION from /root/.bw_env. Returns str or None."""
        try:
            if BW_ENV_FILE.exists():
                for line in BW_ENV_FILE.read_text().splitlines():
                    if line.startswith("BW_SESSION="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass
        return os.environ.get("BW_SESSION")

    def add_item(self, name, username=None, password=None, notes=None, uri=None):
        """Add a new login item to the vault.

        Uses bw CLI (requires BW_SESSION env var). Returns item dict or None.
        """
        login = {}
        if username:
            login["username"] = username
        if password:
            login["password"] = password
        if uri:
            login["uris"] = [{"uri": uri}]

        payload = {"type": 1, "name": name, "login": login}
        if notes:
            payload["notes"] = notes

        env = os.environ.copy()
        session = self._load_session()
        if session:
            env["BW_SESSION"] = session

        try:
            proc = subprocess.run(
                ["bw", "encode"],
                input=json.dumps(payload),
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode != 0:
                return None
            encoded = proc.stdout.strip()

            proc2 = subprocess.run(
                ["bw", "create", "item"],
                input=encoded,
                capture_output=True, text=True, timeout=10,
                env=env,
            )
            if proc2.returncode != 0:
                return None
            return json.loads(proc2.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            return None

    def write_credential(self, name, password, username=None, notes=None, uri=None):
        """High-level: upsert credential. If exists, skip; if not, create.

        Returns dict with 'action' ('created'|'exists') and 'item'.
        """
        existing = self.find_item(name)
        if existing:
            return {"action": "exists", "item": existing}
        item = self.add_item(name, username=username, password=password, notes=notes, uri=uri)
        if item:
            return {"action": "created", "item": item}
        return {"action": "error", "detail": "add_item returned None"}


if __name__ == "__main__":
    # CLI test
    import sys
    vault = BWVault()
    if len(sys.argv) > 1:
        pw = vault.get_password(sys.argv[1])
        if pw:
            print(pw)
        else:
            print(f"Not found: {sys.argv[1]}")
            sys.exit(1)
    else:
        items = vault.list_items()
        print(f"Bitwarden vault: {len(items)} items")
        for item in items:
            name = item.get("name", "?")
            org = " [org]" if item.get("organizationId") else ""
            print(f"  {name}{org}")

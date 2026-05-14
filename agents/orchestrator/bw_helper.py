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
import subprocess
import urllib.request
import urllib.error

BW_SERVE_URL = "http://127.0.0.1:8087"


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
            )
            if proc2.returncode != 0:
                return None
            return json.loads(proc2.stdout)
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            return None


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

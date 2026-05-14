"""Obsidian vault sync helper for agents.

Usage:
    from obsidian import vault_path, sync_pull, sync_push

    # Pull latest before reading
    sync_pull()

    # Read or write files in vault_path / "eddytester"
    board = (vault_path / "eddytester" / "Оркестратор Доска.md").read_text()

    # Push changes after writing
    sync_push()
"""

import subprocess
import sys
from pathlib import Path

VAULT_ROOT = Path("/root/obsidian-vault")
SYNC_SCRIPT = Path("/root/blog-analysis/lib/obsidian_sync.sh")


def sync_pull():
    """Pull latest vault state from GitHub."""
    if not VAULT_ROOT.exists():
        print("ERROR: vault not cloned yet", file=sys.stderr)
        return
    subprocess.run(["bash", str(SYNC_SCRIPT), "pull"],
                   capture_output=True, timeout=30)


def sync_push(message=None):
    """Commit and push local vault changes."""
    if not VAULT_ROOT.exists():
        return
    subprocess.run(["bash", str(SYNC_SCRIPT), "push"],
                   capture_output=True, timeout=30)


def full_sync():
    """Pull, then push if there are changes."""
    if not VAULT_ROOT.exists():
        return
    subprocess.run(["bash", str(SYNC_SCRIPT)],
                   capture_output=True, timeout=30)

#!/bin/bash
# git-sync.sh — obsidian-vault git pull every minute via cron
# Uses flock to prevent race with obsidian_sync.sh push.
LOCKFILE="/tmp/git-sync.lock"
VAULT="/root/obsidian-vault"
LOGFILE="/tmp/git-sync.log"
exec 200>"$LOCKFILE"
flock -n 200 || exit 0
cd "$VAULT" 2>/dev/null || exit 1
BEFORE=$(git rev-parse HEAD)
git pull origin main --ff-only 2>/dev/null
AFTER=$(git rev-parse HEAD)
if [ "$BEFORE" != "$AFTER" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] pulled: ${BEFORE:0:7}..${AFTER:0:7}" >> "$LOGFILE"
fi
flock -u 200

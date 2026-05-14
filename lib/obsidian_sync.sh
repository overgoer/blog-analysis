#!/bin/bash
# Obsidian vault sync for agents.
# Pull before reading, push after writing.

VAULT="/root/obsidian-vault"
cd "$VAULT" || exit 1

if [ "$1" = "pull" ]; then
    git pull origin main --ff-only 2>/dev/null || git reset --hard origin/main
elif [ "$1" = "push" ]; then
    git add -A
    if git diff --cached --quiet; then
        echo "Nothing to commit"
        exit 0
    fi
    git commit -m "sync: $(date +%Y-%m-%d_%H:%M)"
    git push origin main 2>&1
else
    git pull origin main --ff-only 2>/dev/null || git reset --hard origin/main
    git add -A
    if ! git diff --cached --quiet; then
        git commit -m "sync: $(date +%Y-%m-%d_%H:%M)"
        git push origin main 2>&1
    fi
fi

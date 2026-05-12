#!/usr/bin/env bash
# Nightly Agent Pipeline
# set -e  (removed - allow all agents to run independently)

LOG="/root/blog-analysis/agents/nightly.log"
echo "===== Nightly Run: $(date) =====" >> "$LOG"

echo "--- SCOUT Agent ---" >> "$LOG"
python3 /root/blog-analysis/agents/scout/scanner.py >> "$LOG" 2>&1

echo "--- EDUCATOR Agent ---" >> "$LOG"
python3 /root/blog-analysis/agents/educator/educator.py daily >> "$LOG" 2>&1

echo "--- Email Digest ---" >> "$LOG"
python3 /root/blog-analysis/agents/email_digest.py --send >> "$LOG" 2>&1

echo "--- Done ---" >> "$LOG"
echo "" >> "$LOG"

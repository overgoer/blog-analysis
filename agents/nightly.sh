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

echo "--- Outbox Cleanup ---" >> "$LOG"
python3 -c "
import re
from pathlib import Path
outbox = Path('/root/obsidian-vault/outbox.md')
content = outbox.read_text(encoding='utf-8')

# Keep only last 10 Дискуссия entries
discuss_marker = '## Дискуссия'
if discuss_marker in content:
    parts = content.split(discuss_marker)
    header = parts[0]
    discuss_section = parts[1] if len(parts) > 1 else ''
    blocks = re.split(r'(?=\*\*Ты:\*\*)', discuss_section)
    if len(blocks) > 12:
        discuss_section = discuss_marker + ''.join(blocks[-10:])
        content = header + discuss_section + ''.join(parts[2:]) if len(parts) > 2 else header + discuss_section

outbox.write_text(content, encoding='utf-8')
print('Outbox cleanup done: ' + str(len(blocks)) + ' -> min(10, ' + str(len(blocks)) + ') entries')
" >> "$LOG" 2>&1
cd /root/obsidian-vault && git add outbox.md && git commit -m "nightly: outbox cleanup" 2>/dev/null && git pull --rebase && git push 2>&1 | head -3 >> "$LOG"

echo "--- Done ---" >> "$LOG"
echo "" >> "$LOG"

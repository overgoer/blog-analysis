#!/bin/bash
# Watchdog — проверяет что все процессы живы, шлёт алерт в Telegram если нет.
# Cron: */5 * * * * /root/blog-analysis/agents/bsa/watchdog.sh

OUTGOING="/root/blog-analysis/agents/bsa/outgoing"
LOG="/tmp/watchdog.log"
NOW=$(date '+%Y%m%d_%H%M%S')
ISSUES=()

# TG bot
if ! pm2 show tg-bizzy 2>/dev/null | grep -q 'online'; then
    ISSUES+=("Telegram bot tg-bizzy не в сети")
    pm2 restart tg-bizzy 2>/dev/null && echo "[$NOW] tg-bizzy restart attempted" >> "$LOG"
fi

# Lock file stale
LOCK="/tmp/requests_listener.lock"
if [ -f "$LOCK" ]; then
    AGE=$(( $(date +%s) - $(stat -c %Y "$LOCK") ))
    if [ "$AGE" -gt 120 ]; then
        ISSUES+=("requests_listener.lock висит ${AGE}с")
        rm -f "$LOCK"
    fi
fi

# Stuck outgoing (>10 min)
for f in "$OUTGOING"/*.json; do
    [ -f "$f" ] || continue
    FILE_AGE=$(( $(date +%s) - $(stat -c %Y "$f") ))
    if [ "$FILE_AGE" -gt 600 ]; then
        ISSUES+=("Застряло сообщение: $(basename $f) (${FILE_AGE}c)")
    fi
done

# Alert if issues found
if [ ${#ISSUES[@]} -gt 0 ]; then
    ALERT="⚠️ *Watchdog alert*\n\n"
    for issue in "${ISSUES[@]}"; do
        ALERT+="• $issue\n"
    done
    # Write to outgoing for TG bot
    TS=$(date '+%Y%m%d_%H%M%S_%N' | cut -c1-20)
    printf '{"text": "%s", "created_at": "%s", "retries": 0, "failed": false}' \
        "$ALERT" "$(date -Iseconds)" > "$OUTGOING/watchdog_${TS}.json"
    echo "[$NOW] Watchdog: issues found" >> "$LOG"
else
    echo "[$NOW] Watchdog: all clear" >> "$LOG"
fi

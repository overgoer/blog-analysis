#!/bin/bash
# RECOVERY.sh — скрипт восстановления после прерывания
# Использование: bash /root/blog-analysis/RECOVERY.sh

echo "=== RECOVERY: eddytester Analysis ==="
echo ""

CHRON_FILE="/root/blog-analysis/CHRON.md"
LAST_STEP_FILE="/root/blog-analysis/LAST_STEP.md"

if [ ! -f "$CHRON_FILE" ]; then
    echo "❌ CHRON.md не найден. Начинаем с нуля."
    exit 1
fi

echo "📋 Последний статус из CHRON.md:"
grep -E "^(###|##|Phase|Status)" "$CHRON_FILE" | tail -5
echo ""

if [ -f "$LAST_STEP_FILE" ]; then
    echo "🔄 Последний выполненный шаг:"
    cat "$LAST_STEP_FILE"
    echo ""
    echo "👉 Продолжить с шага: $(cat $LAST_STEP_FILE)"
else
    echo "⚠️ LAST_STEP.md не найден. Проверь CHRON.md вручную."
    echo "👉 Смотри CHRON.md, ищи последний ✅ чек-поинт"
fi

echo ""
echo "=== КОНТЕКСТ ДЛЯ ВОССТАНОВЛЕНИЯ ==="
echo "Все файлы в /root/blog-analysis/:"
ls -la /root/blog-analysis/
echo ""
echo "Данные:"
ls -la /root/blog-analysis/data/ 2>/dev/null || echo "(нет папки data)"

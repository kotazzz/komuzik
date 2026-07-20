#!/bin/bash
set -e

echo "🔧 Проверка конфигурации бота..."

# Проверка config.yaml
if [ ! -f "config.yaml" ]; then
    echo "❌ Ошибка: config.yaml не найден!"
    exit 1
fi
echo "✓ config.yaml найден"

if [ ! -f "messages.yaml" ]; then
    echo "❌ Ошибка: messages.yaml не найден!"
    exit 1
fi
echo "✓ messages.yaml найден"

# Проверка обязательных переменных окружения
if [ -z "$API_ID" ] || [ -z "$API_HASH" ] || [ -z "$BOT_TOKEN" ]; then
    echo "❌ Ошибка: не установлены обязательные переменные окружения:"
    [ -z "$API_ID" ] && echo "   - API_ID"
    [ -z "$API_HASH" ] && echo "   - API_HASH"
    [ -z "$BOT_TOKEN" ] && echo "   - BOT_TOKEN"
    exit 1
fi
echo "✓ Переменные окружения установлены"

# Проверка компонентов
uv run python << 'PYEOF'
import sys
try:
    from komuzik.config import *
    from komuzik.config_loader import ConfigLoader
    from komuzik.download_limiter import DownloadLimiter
    from komuzik.downloaders import *
    from komuzik.handlers import BotHandlers
    print("✓ Все компоненты загружены успешно")
except Exception as e:
    print(f"❌ Ошибка при загрузке компонентов: {e}")
    sys.exit(1)
PYEOF

echo ""
echo "✅ Все проверки пройдены успешно!"
echo "🤖 Запуск бота..."
echo ""

# Запуск бота
exec uv run python -m komuzik.main

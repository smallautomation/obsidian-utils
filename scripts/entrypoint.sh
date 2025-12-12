#!/bin/bash

set -e

echo "Starting Obsidian Tracker Sync Service"

# Ожидание доступности зависимостей
if [ -n "$WAIT_FOR_HOSTS" ]; then
    for host in $(echo $WAIT_FOR_HOSTS | sed "s/,/ /g"); do
        echo "Waiting for $host..."
        while ! nc -z $(echo $host | sed "s/:/ /"); do
            sleep 1
        done
        echo "$host is available"
    done
fi

# Проверка конфигурации
if [ ! -f "/app/config/.env" ]; then
    echo "Warning: .env file not found. Using environment variables."
fi

if [ ! -f "/app/config/config.yaml" ]; then
    echo "Error: config.yaml not found!"
    exit 1
fi

# Запуск службы
if [ "$RUN_TELEGRAM_BOT" = "true" ]; then
    echo "Starting Telegram bot..."
    exec python src/telegram/bot.py
else
    echo "Starting sync service..."
    exec python src/main.py
fi
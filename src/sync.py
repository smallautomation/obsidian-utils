#!/usr/bin/env python3

import asyncio
import datetime
import signal
import sys
import os
from pathlib import Path
import logging

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

from src.trackers.yandex_tracker import YandexTracker

today = datetime.datetime.now()

# !/usr/bin/env python3
import sys
import os
import asyncio
from datetime import datetime, timedelta

# Добавляем корень проекта в путь
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    """Основная асинхронная функция"""
    # Загружаем конфиг (нужно будет реализовать загрузку конфига)
    config = {
        'trackers': {
            'yandex_tracker': {
                'oauth_token': 'ваш_токен',  # Замените на реальный токен
                'org_id': 'ваш_org_id',  # Замените на реальный org_id
                'api_url': 'https://api.tracker.yandex.net/v2'
            }
        }
    }

    # Создаем объект трекера
    tracker = YandexTracker(config)

    # Получаем работы за текущий день
    today = datetime.now()
    yesterday = datetime.now() - timedelta(days=1)
    print(f"Получаем работы за {yesterday.date()}...")

    try:
        day_worklog = await tracker.get_day_worklog(yesterday)

        if day_worklog:
            print(f"Найдено {len(day_worklog)} записей:")
            print("=" * 50)

            total_hours = 0
            for worklog_id, worklog in day_worklog.items():
                print(f"\n📝 Задача: {worklog.get('issue_id', 'N/A')}")
                print(f"   🏷️  Проект: {worklog.get('project', 'N/A')}")
                print(f"   ⏱️  Время: {worklog.get('duration', 0):.2f}ч")

                comment = worklog.get('comment', '')
                if comment:
                    print(f"   💬 Комментарий: {comment}")

                start_time = worklog.get('start_time')
                if start_time:
                    print(f"   🕐 Начало: {start_time.strftime('%H:%M')}")

                total_hours += worklog.get('duration', 0)

            print(f"\n{'=' * 50}")
            print(f"📊 ИТОГО за день: {total_hours:.2f}ч")
        else:
            print("За сегодня нет записей о работе")

    except Exception as e:
        print(f"Ошибка при получении данных: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # Запускаем асинхронную main функцию
    asyncio.run(main())

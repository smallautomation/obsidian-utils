"""
Шаблоны сообщений для Telegram уведомлений
"""

import os
from datetime import datetime, timedelta
import pytz

# Путь к папке с шаблонами
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')

# Конфигурация шаблонов
TEMPLATE_CONFIG = {
    'time_format': '%Y-%m-%d %H:%M',
    'date_format': '%Y-%m-%d',
    'summary_max_notifications': 5,
    'notification_lead_time_minutes': 5
}


def load_template(template_name):
    """
    Загружает шаблон из файла
    """
    template_path = os.path.join(TEMPLATES_DIR, f"{template_name}.j2")
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Шаблон {template_name} не найден по пути: {template_path}")
    except Exception as e:
        raise Exception(f"Ошибка загрузки шаблона {template_name}: {e}")


def get_template_context(task=None, summary_data=None, error_data=None):
    """
    Создает контекст для рендеринга шаблонов
    """
    context = {}

    if task:
        # Контекст для уведомления о задаче
        context.update({
            'task': task.get('task', 'Неизвестная задача'),
            'notification_time': task.get('notification', 'Не указано'),
            'filename': os.path.basename(task.get('filename', 'Неизвестный файл')),
            'complexity': task.get('complexity'),
            'complexity_emoji': get_complexity_emoji(task.get('complexity')),
            'complexity_name': get_complexity_name(task.get('complexity')),
            'duration': task.get('duration', '0'),
            'status': task.get('status', 'TODO'),
            'raw_line': task.get('raw_line', '')
        })

    if summary_data:
        # Контекст для сводки
        context.update({
            'total_tasks': summary_data.get('total_tasks', 0),
            'completed_tasks': summary_data.get('completed_tasks', 0),
            'pending_tasks': summary_data.get('pending_tasks', 0),
            'upcoming_notifications': summary_data.get('upcoming_notifications', []),
            'current_time': datetime.now().strftime(TEMPLATE_CONFIG['time_format'])
        })

    if error_data:
        # Контекст для ошибок
        context.update({
            'error_type': error_data.get('error_type', 'Неизвестная ошибка'),
            'error_message': error_data.get('error_message', ''),
            'filename': error_data.get('filename'),
            'error_time': datetime.now().strftime(TEMPLATE_CONFIG['time_format'])
        })

    return context


def get_complexity_emoji(complexity: int) -> str:
    """Возвращает emoji для уровня сложности"""
    complexity_map = {
        1: '🟩',
        2: '🟨',
        3: '🟥'
    }
    return complexity_map.get(complexity, '')


def get_complexity_name(complexity: int) -> str:
    """Возвращает название для уровня сложности"""
    complexity_map = {
        1: 'Низкая',
        2: 'Средняя',
        3: 'Высокая'
    }
    return complexity_map.get(complexity, 'Не указана')


def get_summary_data(all_tasks):
    """
    Подготавливает данные для сводки по задачам
    """
    timezone = pytz.timezone('Europe/Samara')
    now = datetime.now(timezone)

    total_tasks = len(all_tasks)
    completed_tasks = len([t for t in all_tasks if t.get('status') == 'DONE'])
    pending_tasks = len([t for t in all_tasks if t.get('status') == 'TODO'])

    # Ближайшие уведомления (в течение 24 часов)
    upcoming_notifications = []

    for task in all_tasks:
        if (task.get('status') == 'TODO' and
                task.get('notification') and
                task.get('task')):
            try:
                notification_time = datetime.strptime(
                    task['notification'],
                    TEMPLATE_CONFIG['time_format']
                )
                notification_time = timezone.localize(notification_time)
                if now <= notification_time <= now + timedelta(hours=24):
                    upcoming_notifications.append({
                        'task': task['task'][:50] + '...' if len(task['task']) > 50 else task['task'],
                        'time': task['notification']
                    })
            except ValueError:
                continue

    # Сортируем и ограничиваем количество
    upcoming_notifications.sort(key=lambda x: x['time'])
    upcoming_notifications = upcoming_notifications[:TEMPLATE_CONFIG['summary_max_notifications']]

    return {
        'total_tasks': total_tasks,
        'completed_tasks': completed_tasks,
        'pending_tasks': pending_tasks,
        'upcoming_notifications': upcoming_notifications
    }
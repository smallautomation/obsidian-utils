import time
import shutil
import os
import re
import json
import asyncio
import aiohttp
import pytz
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta
from pathlib import Path
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler
from jinja2 import Environment, BaseLoader

# Импортируем шаблоны и функции для работы с контекстом
from templates import load_template, get_template_context, get_summary_data

# Создаем директорию для логов, если она не существует
os.makedirs('logs', exist_ok=True)

# Настройка ротации логов
log_handler = TimedRotatingFileHandler(
    filename='logs/task_monitor.log',
    when='midnight',  # Ротация в полночь
    interval=1,  # Каждый день
    backupCount=10,  # Хранить 10 файлов (10 дней)
    encoding='utf-8'
)

# Формат имени для ротированных файлов (добавит дату к имени)
log_handler.suffix = "%Y-%m-%d"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Вывод в консоль
        log_handler  # Ротируемый вывод в файл
    ]
)
logger = logging.getLogger(__name__)

VAULT_PATH = os.getenv('VAULT_PATH', '/home/aborisov/projects/my/obsidian-utils/source/daily')
task_pattern_open = u'- [ ]'
task_pattern_close = u'- [x]'

# Конфигурация Telegram
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', 'your_bot_token_here')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', 'your_chat_id_here')
TIMEZONE = os.getenv('TIMEZONE', 'Europe/Samara')
DURATION_TOMATO = int(os.getenv('TIMEZONE', 30))


timezone = pytz.timezone(TIMEZONE)

# Инициализация Jinja2 environment
jinja_env = Environment(loader=BaseLoader())

# Кэш загруженных шаблонов
template_cache = {}

# Глобальное хранилище задач
all_tasks = []
notification_sent = set()


def get_template(template_name: str) -> str:
    """
    Получает шаблон из кэша или загружает из файла
    """
    if template_name not in template_cache:
        try:
            template_content = load_template(template_name)
            template_cache[template_name] = jinja_env.from_string(template_content)
            logger.debug(f"Шаблон {template_name} загружен из файла")
        except Exception as e:
            logger.error(f"Ошибка загрузки шаблона {template_name}: {e}")
            # Возвращаем простой fallback шаблон
            fallback_template = "{{ task }}"
            template_cache[template_name] = jinja_env.from_string(fallback_template)

    return template_cache[template_name]


def parse_obsidian_task(s: str, filename: str = "") -> dict:
    match = re.search(r"-\s*\[(?P<status>[\w\s\/])\]\s*(?P<data>[^:].*)", s)
    complexity = 0
    if match:
        status = match.group('status')
        data = match.group('data')

        if status == 'x':
            ret = {'status': 'DONE'}
        else:
            ret = {'status': 'TODO'}

        ret['filename'] = filename
        ret['raw_line'] = s.strip()

        if '🟩' in data:
            data = data.replace('🟩', '')
            ret['complexity'] = 1
        if '🟨 ' in data:
            data = data.replace('🟨', '')
            ret['complexity'] = 2
        if '🟥 ' in data:
            data = data.replace('🟥', '')
            ret['complexity'] = 3

        if '📅' in data:
            match_date = re.search(r"📅\s*(?P<date>\d{4}-\d{2}-\d{2})", data)
            if match_date:
                date = match_date.group('date')
                ret['date'] = date
                # Удаляем дату из текста
                date_pattern = re.compile(r"📅\s*\d{4}-\d{2}-\d{2}")
                data = date_pattern.sub('', data)

        if '✅' in data:
            match_completed_date = re.search(r"✅\s*(?P<completed_date>\d{4}-\d{2}-\d{2})", data)
            if match_completed_date:
                completed_date = match_completed_date.group('completed_date')
                ret['completed_date'] = completed_date
                data = data.replace(f"✅ {completed_date}", '')

        if '@completed(' in data:
            match_completed = re.search(r"@completed\((?P<completed>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\)", data)
            if match_completed:
                completed = match_completed.group('completed')
                ret['completed'] = completed
                data = data.replace(f"@completed({completed})", '')

        ret['notification'] = None
        if '(@' in data:
            match_notification = re.search(r"\(@(?P<notification>\d{4}-\d{2}-\d{2}\s\d{1,2}:\d{2})\)", data)
            if match_notification:
                notification = match_notification.group('notification')
                ret['notification'] = notification
                data = data.replace(f"(@{notification})", '')

        if '[🍅' in data:
            match_duration = re.search(r"\[🍅::(?P<duration>\d+)\]", data)
            if match_duration:
                duration = int(match_duration.group('duration'))
                ret['duration'] = duration * DURATION_TOMATO
                # Удаляем помидорку из текста
                data = re.sub(r'\s*\[🍅::\d+\]\s*', ' ', data)
        else:
            ret['duration'] = 0

        # Очищаем лишние пробелы
        data = re.sub(r'\s+', ' ', data).strip()
        ret['task'] = data

        return ret
    return {}


def parse_obsidian_file(filename):
    """Парсит файл и возвращает список задач"""
    file_tasks = []

    if not os.path.isabs(filename):
        base_path = Path(VAULT_PATH)
        filename = str(base_path / filename)

    if filename.endswith(".md") and os.path.exists(filename):
        try:
            with open(filename, encoding="utf8", errors='ignore') as in_put:
                for line in in_put:
                    if task_pattern_open in line or task_pattern_close in line:
                        task = parse_obsidian_task(line, filename)
                        if task:
                            file_tasks.append(task)
            logger.info(f"Файл {filename} обработан, найдено задач: {len(file_tasks)}")
        except Exception as e:
            logger.error(f"Ошибка при чтении файла {filename}: {e}")

    return file_tasks


def scan_all_files():
    """Сканирует все файлы в VAULT_PATH и возвращает все задачи"""
    global all_tasks
    all_tasks = []

    logger.info(f"Начато сканирование всех файлов в {VAULT_PATH}...")

    for root, dirs, files in os.walk(VAULT_PATH):
        for file in files:
            if file.endswith('.md'):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, VAULT_PATH)
                tasks = parse_obsidian_file(rel_path)
                all_tasks.extend(tasks)

    logger.info(f"Сканирование завершено. Найдено задач: {len(all_tasks)}")
    return all_tasks


def render_template(template_name: str, context: dict) -> str:
    """Рендерит шаблон с использованием Jinja2"""
    try:
        template = get_template(template_name)
        return template.render(context).strip()
    except Exception as e:
        logger.error(f"Ошибка при рендеринге шаблона {template_name}: {e}")
        # Возвращаем простой fallback
        return f"Напоминание: {context.get('task', 'Неизвестная задача')}"


async def send_telegram_notification(task):
    """Отправляет уведомление в Telegram с использованием шаблона"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == 'your_bot_token_here':
        logger.warning("Telegram bot token не настроен")
        return

    # Создаем контекст для шаблона
    context = get_template_context(task=task)

    # Рендерим сообщение из шаблона
    message = render_template('notification', context)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    logger.info(f"Уведомление отправлено: {task['task']}")
                else:
                    logger.error(f"Ошибка отправки уведомления: {await response.text()}")
    except Exception as e:
        logger.error(f"Ошибка при отправке в Telegram: {e}")


async def send_task_summary():
    """Отправляет сводку по задачам"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == 'your_bot_token_here':
        logger.warning("Telegram bot token не настроен")
        return

    # Получаем данные для сводки
    summary_data = get_summary_data(all_tasks)

    # Создаем контекст для шаблона
    context = get_template_context(summary_data=summary_data)

    # Рендерим сообщение из шаблона
    message = render_template('task_summary', context)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    logger.info("Сводка по задачам отправлена")
                else:
                    logger.error(f"Ошибка отправки сводки: {await response.text()}")
    except Exception as e:
        logger.error(f"Ошибка при отправке сводки в Telegram: {e}")


async def send_error_notification(error_message: str, filename: str = None):
    """Отправляет уведомление об ошибке"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == 'your_bot_token_here':
        logger.warning("Telegram bot token не настроен")
        return

    error_data = {
        'error_type': 'Ошибка обработки файла',
        'error_message': error_message,
        'filename': filename
    }

    context = get_template_context(error_data=error_data)
    message = render_template('error_notification', context)

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    logger.info("Уведомление об ошибке отправлено")
                else:
                    logger.error(f"Ошибка отправки уведомления об ошибке: {await response.text()}")
    except Exception as e:
        logger.error(f"Ошибка при отправке уведомления об ошибке: {e}")


def check_notifications():
    """Проверяет задачи и отправляет уведомления за 5 минут до времени"""
    global all_tasks, notification_sent

    now = datetime.now(timezone)
    notifications_found = 0

    for task in all_tasks:
        if task['status'] != 'TODO':
            continue

        notification = task.get('notification')
        if not notification:
            continue

        # Создаем уникальный идентификатор для задачи
        task_id = f"{task['filename']}:{task['raw_line']}"

        if task_id in notification_sent:
            continue

        try:
            # Парсим время уведомления
            notification_time = datetime.strptime(notification, '%Y-%m-%d %H:%M')
            notification_time = timezone.localize(notification_time)

            # Проверяем, наступает ли время уведомления в течение 5 минут
            time_diff = notification_time - now
            if timedelta(seconds=0) <= time_diff <= timedelta(minutes=5):
                logger.info(f"Время уведомления! Задача: {task['task']}")
                asyncio.run(send_telegram_notification(task))
                notification_sent.add(task_id)
                notifications_found += 1

        except ValueError as e:
            logger.error(f"Ошибка парсинга времени: {notification}, ошибка: {e}")

    if notifications_found > 0:
        logger.info(f"Обработано уведомлений: {notifications_found}")


class SyncHandler(FileSystemEventHandler):
    def __init__(self, source_dir):
        self.source_dir = source_dir

    def update_file_tasks(self, src_path):
        """Обновляет все задачи из указанного файла"""
        if not os.path.exists(src_path):
            logger.warning(f"Файл не существует: {src_path}")
            return

        # Определяем относительный путь
        # rel_path = os.path.relpath(src_path, self.source_dir)
        rel_path = src_path
        logger.info(f"Обновление задач из файла: {rel_path}")

        # Парсим файл и получаем актуальные задачи
        new_tasks = parse_obsidian_file(rel_path)

        # Обновляем global all_tasks
        global all_tasks

        # Удаляем все старые задачи из этого файла
        initial_count = len(all_tasks)
        all_tasks = [task for task in all_tasks if task.get('filename') != rel_path]
        removed_count = initial_count - len(all_tasks)

        # Добавляем новые задачи
        all_tasks.extend(new_tasks)

        logger.info(
            f"Обновление завершено: удалено {removed_count} задач, добавлено {len(new_tasks)} задач. Всего задач: {len(all_tasks)}")

    def on_created(self, event):
        if not event.is_directory:
            logger.debug(f"Создан файл: {event.src_path}")
            self.update_file_tasks(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            logger.debug(f"Изменен файл: {event.src_path}")
            self.update_file_tasks(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            logger.debug(f"Перемещен файл: {event.src_path} -> {event.dest_path}")
            self.update_file_tasks(event.dest_path)

    def on_deleted(self, event):
        if not event.is_directory:
            logger.debug(f"Удален файл: {event.src_path}")
            # Удаляем задачи из удаленного файла
            global all_tasks
            rel_path = os.path.relpath(event.src_path, self.source_dir)
            initial_count = len(all_tasks)
            all_tasks = [task for task in all_tasks if task.get('filename') != rel_path]
            removed_count = initial_count - len(all_tasks)
            logger.info(f"Удалено {removed_count} задач из файла: {rel_path}")


def start_sync_monitoring(source_dir):
    """Запуск мониторинга для автоматической синхронизации"""

    # Первоначальное сканирование всех файлов
    scan_all_files()

    # Запуск мониторинга
    event_handler = SyncHandler(source_dir)
    observer = PollingObserver()
    observer.schedule(event_handler, source_dir, recursive=True)

    observer.start()
    logger.info(f"Мониторинг запущен: {source_dir}")
    logger.info(f"Всего задач: {len(all_tasks)}")

    try:
        while True:
            # Проверяем уведомления каждые 30 секунд
            check_notifications()
            time.sleep(30)

    except KeyboardInterrupt:
        observer.stop()
        logger.info("Мониторинг остановлен по запросу пользователя")

    observer.join()


if __name__ == "__main__":
    # Для тестирования можно запустить сканирование без мониторинга
    if len(os.sys.argv) > 1:
        if os.sys.argv[1] == 'scan':
            logger.info("Запуск сканирования...")
            scan_all_files()
            logger.info("Сканирование завершено")
        elif os.sys.argv[1] == 'summary':
            logger.info("Отправка сводки...")
            asyncio.run(send_task_summary())
            logger.info("Сводка отправлена")
    else:
        start_sync_monitoring(VAULT_PATH)
import requests
import json
import logging
import unicodedata
from typing import Dict, List
from datetime import datetime, timedelta
from abc import ABC, abstractmethod


# Локальный BaseTracker
class BaseTracker(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def update_time_spent(self, task_id: str, hours: float, date: datetime) -> bool:
        pass

    @abstractmethod
    async def get_month_worklog(self, year: int, month: int) -> Dict[str, float]:
        pass


# Настройка логгера
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class YandexTracker(BaseTracker):
    def __init__(self, config: dict):
        super().__init__(config['trackers']['yandex_tracker'])

        # Очищаем значения от не-ASCII символов для заголовков
        oauth_token = self._safe_string(self.config["oauth_token"])
        org_id = self._safe_string(str(self.config['org_id']))

        self.headers = {
            'Authorization': f'OAuth {oauth_token}',
            'X-Org-ID': org_id,
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _safe_string(self, text: str) -> str:
        """Очищает строку от не-ASCII символов для использования в заголовках HTTP"""
        if not text:
            return text

        try:
            # Пробуем кодировать в latin-1 (то что требует HTTP заголовки)
            text.encode('latin-1')
            return text
        except UnicodeEncodeError:
            # Если есть не-latin символы, удаляем их
            return ''.join(
                char for char in text
                if unicodedata.category(char)[0] != 'C' and ord(char) < 128
            )

    async def update_time_spent(self, task_id: str, hours: float, date: datetime) -> bool:
        try:
            work_items = await self._get_work_items(task_id, date)

            if work_items:
                work_item_id = work_items[0]['id']
                return await self._update_work_item(work_item_id, hours)
            else:
                return await self._create_work_item(task_id, hours, date)

        except Exception as e:
            logger.error(f"Error updating time for {task_id}: {e}")
            return False

    async def _get_work_items(self, task_id: str, date: datetime) -> List[Dict]:
        url = f"{self.config['api_url']}/issues/{task_id}/worklog"

        start_date = date.replace(hour=0, minute=0, second=0)
        end_date = start_date + timedelta(days=1)

        params = {
            'createdBy': 'me',
            'startDateTime': start_date.isoformat(),
            'endDateTime': end_date.isoformat()
        }

        response = self.session.get(url, params=params, timeout=10)
        response.raise_for_status()

        # Явно указываем кодировку для ответа
        if response.encoding is None:
            response.encoding = 'utf-8'

        return response.json()

    async def _update_work_item(self, work_item_id: str, hours: float) -> bool:
        url = f"{self.config['api_url']}/worklog/{work_item_id}"

        data = {
            'duration': f"{hours}h"
        }

        response = self.session.patch(url, json=data, timeout=10)
        return response.status_code == 200

    async def _create_work_item(self, task_id: str, hours: float, date: datetime) -> bool:
        url = f"{self.config['api_url']}/issues/{task_id}/worklog"

        data = {
            'start': date.replace(hour=9, minute=0).isoformat(),
            'duration': f"{hours}h",
            'comment': 'Obsidian'
        }

        response = self.session.post(url, json=data, timeout=10)
        return response.status_code == 201

    async def get_day_worklog(self, date: datetime) -> Dict[str, Dict]:
        """
        Получить работы за конкретный день
        """
        url = f"{self.config['api_url']}/worklog"

        start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=1)

        params = {
            'createdBy': 'me',
            'startDateTime': start_date.isoformat(),
            'endDateTime': end_date.isoformat(),
            'perPage': 100
        }

        try:
            logger.debug(f"Requesting worklog for date: {date.date()}")

            # Используем простой requests без session для теста
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=15
            )

            logger.debug(f"Response status: {response.status_code}")

            response.raise_for_status()

            # Явно указываем кодировку
            if response.encoding is None:
                response.encoding = 'utf-8'

            # Получаем текст с правильной кодировкой
            content = response.text

            # Парсим JSON
            worklogs = json.loads(content)

            logger.debug(f"Received {len(worklogs)} worklog entries")

            result = {}

            for worklog in worklogs:
                try:
                    issue = worklog.get('issue', {})
                    issue_id = issue.get('key', '')

                    if not issue_id:
                        continue

                    project = issue_id.split('-')[0]
                    duration = self._parse_duration(worklog.get('duration', ''))

                    # Безопасное получение комментария
                    comment = worklog.get('comment', '')
                    if comment is None:
                        comment = ''

                    worklog_id = worklog.get('id', '')

                    # Получаем время начала работы
                    start_time_str = worklog.get('start')
                    start_time = None
                    if start_time_str:
                        try:
                            if start_time_str.endswith('Z'):
                                start_time_str = start_time_str[:-1] + '+00:00'
                            start_time = datetime.fromisoformat(start_time_str)
                        except Exception as e:
                            logger.debug(f"Could not parse start time {start_time_str}: {e}")

                    result[worklog_id] = {
                        'issue_id': issue_id,
                        'project': project,
                        'duration': duration,
                        'comment': comment,
                        'created_by': worklog.get('createdBy', {}).get('display', ''),
                        'start_time': start_time,
                    }

                except Exception as e:
                    logger.warning(f"Error processing worklog entry: {e}")
                    continue

            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error getting day worklog for {date.date()}: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for date {date.date()}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error getting day worklog for {date.date()}: {str(e)}")
            return {}

    async def get_day_worklog_summary(self, date: datetime) -> Dict[str, float]:
        """
        Получить суммарное время по проектам за день
        """
        day_worklog = await self.get_day_worklog(date)
        summary = {}

        for worklog_id, worklog in day_worklog.items():
            project = worklog['project']
            duration = worklog['duration']
            summary[project] = summary.get(project, 0) + duration

        return summary

    async def get_day_worklog_for_task(self, task_id: str, date: datetime) -> List[Dict]:
        """
        Получить worklog для конкретной задачи за день
        """
        url = f"{self.config['api_url']}/issues/{task_id}/worklog"

        start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=1)

        params = {
            'createdBy': 'me',
            'startDateTime': start_date.isoformat(),
            'endDateTime': end_date.isoformat()
        }

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            response.raise_for_status()

            if response.encoding is None:
                response.encoding = 'utf-8'

            return response.json()
        except Exception as e:
            logger.error(f"Error getting day worklog for task {task_id}: {e}")
            return []

    async def get_month_worklog(self, year: int, month: int) -> Dict[str, float]:
        url = f"{self.config['api_url']}/worklog"

        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)

        params = {
            'createdBy': 'me',
            'startDateTime': start_date.isoformat(),
            'endDateTime': end_date.isoformat(),
            'perPage': 1000
        }

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()

            if response.encoding is None:
                response.encoding = 'utf-8'

            worklogs = response.json()
            result = {}
            for worklog in worklogs:
                issue_id = worklog.get('issue', {}).get('key', '')
                if issue_id:
                    project = issue_id.split('-')[0]
                    duration = self._parse_duration(worklog.get('duration', ''))
                    result[project] = result.get(project, 0) + duration

            return result

        except Exception as e:
            logger.error(f"Error getting month worklog: {e}")
            return {}

    def _parse_duration(self, duration_str: str) -> float:
        """
        Преобразование строки длительности в часы
        """
        if not duration_str:
            return 0.0

        try:
            # ISO 8601 формат: PT1H30M
            if isinstance(duration_str, str) and duration_str.startswith('PT'):
                duration_str = duration_str[2:]  # Убираем 'PT'

                hours = 0.0
                minutes = 0.0

                if 'H' in duration_str:
                    hours_part = duration_str.split('H')[0]
                    hours = float(hours_part) if hours_part else 0.0
                    # Оставшаяся часть после 'H'
                    if 'H' in duration_str and len(duration_str.split('H')) > 1:
                        duration_str = duration_str.split('H')[1]
                    else:
                        duration_str = ''

                if 'M' in duration_str:
                    minutes_part = duration_str.split('M')[0]
                    minutes = float(minutes_part) if minutes_part else 0.0

                return hours + minutes / 60.0

            # Пробуем парсить как число (часы)
            try:
                return float(duration_str)
            except ValueError:
                # Пробуем удалить 'h' или 'm' и парсить
                if isinstance(duration_str, str):
                    clean_str = duration_str.lower().replace('h', '').replace('m', '').strip()
                    if clean_str:
                        hours = float(clean_str)
                        if 'm' in duration_str.lower():
                            hours = hours / 60.0  # минуты в часы
                        return hours

                return 0.0

        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"Could not parse duration '{duration_str}': {e}")
            return 0.0

    # Дополнительные удобные методы
    async def get_today_worklog(self) -> Dict[str, Dict]:
        """Получить работы за сегодня"""
        return await self.get_day_worklog(datetime.now())

    async def get_yesterday_worklog(self) -> Dict[str, Dict]:
        """Получить работы за вчера"""
        yesterday = datetime.now() - timedelta(days=1)
        return await self.get_day_worklog(yesterday)

    async def get_today_summary(self) -> Dict[str, float]:
        """Получить сводку по проектам за сегодня"""
        return await self.get_day_worklog_summary(datetime.now())

    async def get_yesterday_summary(self) -> Dict[str, float]:
        """Получить сводку по проектам за вчера"""
        yesterday = datetime.now() - timedelta(days=1)
        return await self.get_day_worklog_summary(yesterday)
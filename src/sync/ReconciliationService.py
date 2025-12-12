from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import asyncio

from trackers.yandex_tracker import YandexTracker
from trackers.jira_client import JiraClient
from obsidian.parser import ObsidianParser
from utils.logger import setup_logger

logger = setup_logger(__name__)

class ReconciliationService:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.parser = ObsidianParser(config_path)
        self.yandex_tracker = YandexTracker(config_path)
        self.jira_client = JiraClient(config_path)

    async def reconcile_month(self, year: int, month: int, 
                            tracker_type: str = 'yandex') -> Dict:
        """Сверка данных за месяц"""
        logger.info(f"Starting reconciliation for {year}-{month}")

        # Получение данных из Obsidian
        obsidian_data = await self._get_obsidian_month_data(year, month)
        
        # Получение данных из трекера
        if tracker_type == 'yandex':
            tracker_data = await self.yandex_tracker.get_month_worklog(year, month)
        else:
            tracker_data = await self.jira_client.get_month_worklog(year, month)
        
        # Сравнение данных
        discrepancies = self._compare_data(obsidian_data, tracker_data)
        
        # Генерация отчета
        report = self._generate_report(discrepancies, year, month)
        
        return report
    
    async def _get_obsidian_month_data(self, year: int, month: int) -> Dict:
        """Получение данных из Obsidian за месяц"""
        # Реализация сбора данных из всех файлов vault
        return {}
    
    def _compare_data(self, obsidian_data: Dict, tracker_data: Dict) -> List[Dict]:
        """Сравнение данных и поиск расхождений"""
        discrepancies = []
        
        for project in set(list(obsidian_data.keys()) + list(tracker_data.keys())):
            obsidian_hours = obsidian_data.get(project, 0)
            tracker_hours = tracker_data.get(project, 0)
            
            if abs(obsidian_hours - tracker_hours) > 0.1:  # Порог 6 минут
                discrepancies.append({
                    'project': project,
                    'obsidian_hours': obsidian_hours,
                    'tracker_hours': tracker_hours,
                    'difference': obsidian_hours - tracker_hours
                })
        
        return discrepancies
    
    def _generate_report(self, discrepancies: List[Dict], 
                        year: int, month: int) -> Dict:
        """Генерация отчета о сверке"""
        total_discrepancy = sum(abs(d['difference']) for d in discrepancies)
        
        return {
            'month': f"{year}-{month:02d}",
            'discrepancies': discrepancies,
            'total_discrepancies': len(discrepancies),
            'total_hours_difference': total_discrepancy,
            'has_issues': len(discrepancies) > 0,
            'generated_at': datetime.now().isoformat()
        }
    
    async def sync_discrepancies(self, discrepancies: List[Dict], 
                               tracker_type: str = 'yandex') -> bool:
        """Синхронизация расхождений"""
        # Реализация синхронизации
        return True

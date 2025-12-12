# src/trackers/base_tracker.py
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict


class BaseTracker(ABC):
    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    async def update_time_spent(self, task_id: str, hours: float, date: datetime) -> bool:
        pass

    @abstractmethod
    async def get_month_worklog(self, year: int, month: int) -> Dict[str, float]:
        pass
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import pytz

@dataclass
class Task:
    """Модель задачи из Obsidian"""
    completed: bool
    project: str  # TN или EDWH
    task_id: str  # Номер задачи
    title: str
    pomodoros: int
    scheduled_date: datetime
    completed_date: Optional[datetime]
    tags: List[str]
    raw_text: str
    file_path: Path
    
class ObsidianParser:
    def __init__(self, config: dict):
        self.config = config
        self.task_pattern = re.compile(
            config['obsidian']['task_pattern'],
            re.IGNORECASE
        )
        
    def parse_file(self, file_path: Path) -> List[Task]:
        """Парсинг файла Obsidian и извлечение задач"""
        tasks = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            lines = content.split('\n')
            for line_num, line in enumerate(lines, 1):
                task = self._parse_line(line, file_path, line_num)
                if task:
                    tasks.append(task)
                    
        except Exception as e:
            print(f"Error parsing {file_path}: {e}")
            
        return tasks
    
    def _parse_line(self, line: str, file_path: Path, line_num: int) -> Optional[Task]:
        """Парсинг отдельной строки с задачей"""
        match = self.task_pattern.search(line)
        if not match:
            return None
            
        completed = match.group(1) == 'x'
        project = match.group(2)
        task_id = f"{project}-{match.group(3)}"
        pomodoros = int(match.group(4))
        scheduled_date_str = match.group(5)
        
        # Парсинг дат
        scheduled_date = datetime.strptime(
            scheduled_date_str, 
            self.config['obsidian']['date_format']
        ).replace(tzinfo=pytz.UTC)
        
        # Поиск даты выполнения
        completed_date = None
        if completed:
            completed_match = re.search(r'? (\d{4}-\d{2}-\d{2})', line)
            if completed_match:
                completed_date = datetime.strptime(
                    completed_match.group(1),
                    self.config['obsidian']['date_format']
                ).replace(tzinfo=pytz.UTC)
        
        # Извлечение тегов
        tags = re.findall(r'@\w+', line)
        
        return Task(
            completed=completed,
            project=project,
            task_id=task_id,
            title=line,
            pomodoros=pomodoros,
            scheduled_date=scheduled_date,
            completed_date=completed_date,
            tags=tags,
            raw_text=line,
            file_path=file_path
        )
    
    def calculate_time_spent(self, pomodoros: int) -> float:
        """Конвертация помидорок в часы (1 помидорка = 25 минут)"""
        return round(pomodoros * 25 / 60, 2)
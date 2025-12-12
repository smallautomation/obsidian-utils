import logging
import sys


def setup_logger(name: str, level=logging.INFO):
    """Настройка логгера"""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Создаем обработчик для вывода в консоль
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    # Форматтер для логов
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    handler.setFormatter(formatter)

    # Добавляем обработчик к логгеру
    if not logger.handlers:
        logger.addHandler(handler)

    return logger
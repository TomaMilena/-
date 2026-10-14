"""
logger_config.py
================
Централизованная настройка логирования для системы учёта заказов.

Логи пишутся одновременно:
  * в файл logs/delivery.log (уровень DEBUG, с ротацией);
  * в консоль (уровень INFO).

Использование:
    from logger_config import get_logger
    log = get_logger(__name__)
    log.info("Сообщение")
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# Каталог для логов располагается рядом с этим файлом
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "delivery.log")

# Флаг, чтобы не настраивать корневой логгер повторно
_CONFIGURED = False


def _configure_root() -> None:
    """Однократно настраивает корневой логгер (файл + консоль)."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger("delivery")
    root.setLevel(logging.DEBUG)
    root.propagate = False

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Файловый обработчик с ротацией (до 1 МБ, 3 резервных файла)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    # Консольный обработчик
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    _CONFIGURED = True


def get_logger(name: str = "delivery") -> logging.Logger:
    """
    Возвращает настроенный логгер.

    Все логгеры являются потомками логгера ``delivery``,
    благодаря чему наследуют его обработчики.
    """
    _configure_root()
    if name == "delivery" or name is None:
        return logging.getLogger("delivery")
    return logging.getLogger("delivery." + name)

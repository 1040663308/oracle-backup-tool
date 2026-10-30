# -*- coding: utf-8 -*-
"""日志：文件日志 + 事件总线（GUI 订阅实时显示）"""
from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler

from . import paths

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


class LogBus:
    """简单发布订阅：备份过程日志推送给 GUI"""

    def __init__(self):
        self._subscribers = []
        self._lock = threading.Lock()

    def subscribe(self, callback):
        with self._lock:
            self._subscribers.append(callback)

    def publish(self, level: str, message: str):
        with self._lock:
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(level, message)
            except Exception:
                pass


LOG_BUS = LogBus()
_logger = None


def get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    logger = logging.getLogger("orabackup")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        try:
            log_file = paths.get_log_file()
            handler = RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
            fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            handler.setFormatter(fmt)
            logger.addHandler(handler)
        except Exception:
            pass
    _logger = logger
    return logger


def log(level: str, message: str):
    """记录日志：写文件 + 推送给 GUI"""
    level = (level or "INFO").upper()
    get_logger().log(_LEVELS.get(level, 20), message)
    LOG_BUS.publish(level, message)


def log_info(message: str):
    log("INFO", message)


def log_error(message: str):
    log("ERROR", message)


def log_warning(message: str):
    log("WARNING", message)

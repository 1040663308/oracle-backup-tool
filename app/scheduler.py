# -*- coding: utf-8 -*-
"""定时调度：后台线程，按配置的时间与星期触发备份"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

from . import paths
from .logger import log_error, log_info


def _load_state() -> dict:
    try:
        with open(paths.get_state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state: dict):
    try:
        paths.ensure_app_dir()
        tmp = paths.get_state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, paths.get_state_path())
    except Exception as exc:
        log_error("保存状态文件失败：%s" % exc)


def get_last_run_date() -> str:
    return _load_state().get("last_run_date", "")


def set_last_run_date(date_str: str = None):
    state = _load_state()
    state["last_run_date"] = date_str or datetime.now().strftime("%Y-%m-%d")
    state["last_run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_state(state)


class BackupScheduler(threading.Thread):
    """
    定时调度线程。
    - 每 20 秒检查一次
    - 到达配置时间且当天尚未执行过时触发
    - 若开机时间已晚于计划时间（如凌晨 2 点备份但机器当时关机），启动后自动补跑
    """

    def __init__(self, get_config, trigger):
        super().__init__(daemon=True, name="BackupScheduler")
        self.get_config = get_config
        self.trigger = trigger
        self._stop_event = threading.Event()
        self.last_check = ""

    def stop(self):
        self._stop_event.set()

    def run(self):
        log_info("定时调度线程已启动")
        while not self._stop_event.is_set():
            try:
                self._check()
            except Exception as exc:
                log_error("调度检查异常：%s" % exc)
            self._stop_event.wait(20)

    def _check(self):
        cfg = self.get_config()
        bak = cfg.get("backup", {})
        if not bak.get("schedule_enabled"):
            return
        time_str = (bak.get("schedule_time") or "").strip()
        try:
            hour, minute = [int(x) for x in time_str.split(":")]
        except Exception:
            log_error("定时时间配置无效：%s" % time_str)
            return
        days = bak.get("schedule_days") or [0, 1, 2, 3, 4, 5, 6]
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if now.weekday() not in days:
            return
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if now < target:
            return
        if get_last_run_date() == today:
            return
        log_info("定时备份触发（计划时间 %s）" % time_str)
        set_last_run_date(today)
        try:
            self.trigger()
        except Exception as exc:
            log_error("定时备份执行异常：%s" % exc)

    def next_run_text(self) -> str:
        """返回下一次计划执行的描述（供界面显示）"""
        cfg = self.get_config()
        bak = cfg.get("backup", {})
        if not bak.get("schedule_enabled"):
            return "定时备份未启用"
        time_str = (bak.get("schedule_time") or "").strip()
        days = bak.get("schedule_days") or [0, 1, 2, 3, 4, 5, 6]
        day_names = ["一", "二", "三", "四", "五", "六", "日"]
        if len(days) == 7:
            days_text = "每天"
        else:
            days_text = "每周" + "、".join(day_names[d] for d in sorted(days))
        return "%s %s" % (days_text, time_str)

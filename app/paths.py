# -*- coding: utf-8 -*-
"""应用路径管理：配置文件、日志、状态文件的存放位置"""
from __future__ import annotations

import os
import sys

APP_NAME = "OracleBackup"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包后的 exe 中"""
    return getattr(sys, "frozen", False)


def get_app_dir() -> str:
    """
    应用数据目录：
    1. 环境变量 ORA_BACKUP_HOME（便携/调试用）
    2. 打包后：%APPDATA%\\OracleBackup（避免写入 ProgramFiles 权限问题）
    3. 开发模式：项目根目录
    """
    env = os.environ.get("ORA_BACKUP_HOME")
    if env:
        return env
    if is_frozen():
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ensure_app_dir() -> str:
    path = get_app_dir()
    os.makedirs(path, exist_ok=True)
    return path


def get_config_path() -> str:
    return os.path.join(get_app_dir(), "config.json")


def get_state_path() -> str:
    return os.path.join(get_app_dir(), "state.json")


def get_log_dir() -> str:
    path = os.path.join(get_app_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def get_log_file() -> str:
    return os.path.join(get_log_dir(), "orabackup.log")


def get_exe_path() -> str:
    """当前可执行文件路径（用于开机自启动注册表）"""
    if is_frozen():
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0]) if sys.argv else ""


def get_python_entry() -> str:
    """开发模式下用 python 启动的入口脚本"""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run.py")

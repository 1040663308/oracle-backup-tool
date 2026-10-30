# -*- coding: utf-8 -*-
"""开机自启动：操作 Windows 注册表 Run 项"""
from __future__ import annotations

import os
import sys

APP_NAME = "OracleBackup"

try:
    import winreg
except ImportError:  # 非 Windows 环境
    winreg = None

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_windows() -> bool:
    return os.name == "nt" and winreg is not None


def _launch_command(exe_path: str = None, minimized: bool = False) -> str:
    if not exe_path:
        if getattr(sys, "frozen", False):
            exe_path = os.path.abspath(sys.executable)
        else:
            # 开发模式：用 pythonw 运行 run.py，不弹黑窗
            pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            exe_path = pythonw if os.path.exists(pythonw) else sys.executable
            entry = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run.py")
            cmd = '"%s" "%s"' % (exe_path, entry)
            if minimized:
                cmd += " --minimized"
            return cmd
    cmd = '"%s"' % exe_path
    if minimized:
        cmd += " --minimized"
    return cmd


def is_autostart_enabled() -> bool:
    if not is_windows():
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ)
        try:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
        finally:
            winreg.CloseKey(key)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_autostart(enable: bool, exe_path: str = None, minimized: bool = False) -> bool:
    """设置/取消开机自启动，返回是否成功"""
    if not is_windows():
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE)
        try:
            if enable:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ,
                                  _launch_command(exe_path, minimized))
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except Exception:
        return False


def sync_autostart(enabled: bool, minimized: bool = False, exe_path: str = None):
    """根据系统设置同步注册表状态"""
    if enabled:
        return set_autostart(True, exe_path=exe_path, minimized=minimized)
    if is_autostart_enabled():
        return set_autostart(False)
    return True

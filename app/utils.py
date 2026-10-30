# -*- coding: utf-8 -*-
"""通用工具函数"""
from __future__ import annotations

import re
from datetime import datetime


def shell_quote(value) -> str:
    """使用单引号安全引用 shell 字符串，避免特殊字符导致命令注入或解析错误"""
    if value is None:
        return "''"
    text = str(value)
    return "'" + text.replace("'", "'\\''") + "'"


def format_size(num_bytes) -> str:
    """将字节数格式化为可读大小，如 1.85 GB"""
    try:
        size = float(num_bytes)
    except (TypeError, ValueError):
        return "0 B"
    if size < 0:
        size = 0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            if unit == "B":
                return "%d %s" % (int(size), unit)
            return "%.2f %s" % (size, unit)
        size /= 1024.0
    return "%.2f PB" % size


def parse_size(text: str) -> int:
    """解析如 '1.5GB' 的字符串为字节数；解析失败返回 0"""
    if not text:
        return 0
    m = re.match(r"^\s*([\d.,]+)\s*([KMGT]?B?)\s*$", str(text), re.IGNORECASE)
    if not m:
        return 0
    num = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "B").upper().rstrip("B")
    factor = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}[unit]
    return int(num * factor)


def format_duration(seconds) -> str:
    """将秒数格式化为 '1小时2分3秒'"""
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return "0秒"
    if total < 0:
        total = 0
    if total < 60:
        return "%d秒" % total
    minutes, sec = divmod(total, 60)
    if minutes < 60:
        return "%d分%d秒" % (minutes, sec)
    hours, minutes = divmod(minutes, 60)
    return "%d小时%d分%d秒" % (hours, minutes, sec)


def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return datetime.now().strftime(fmt)


def timestamp_tag() -> str:
    """生成时间戳标签，如 20261023_021530，用于文件名"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def sanitize_name(text: str, maxlen: int = 40) -> str:
    """清理学校名称等用于文件名的字符串"""
    if not text:
        return "school"
    text = re.sub(r'[\\/:*?"<>|\s]+', "_", str(text).strip())
    text = re.sub(r"_+", "_", text).strip("_")
    return (text or "school")[:maxlen]


def disk_free_bytes(path: str) -> int:
    """获取本地磁盘剩余空间（字节）"""
    import shutil
    try:
        return int(shutil.disk_usage(path).free)
    except Exception:
        return 0


def is_valid_time(text: str) -> bool:
    """校验 HH:MM 格式"""
    if not text:
        return False
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", str(text).strip())
    return bool(m)

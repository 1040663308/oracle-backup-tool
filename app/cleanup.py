# -*- coding: utf-8 -*-
"""本地备份文件清理：按保留天数自动删除历史备份"""
from __future__ import annotations

import glob
import os
import re
import time

from .logger import log_info

BACKUP_PATTERN = re.compile(r"^orabackup_.*\.(tar\.gz|tar|dmp|zip)$")


def cleanup_local_backups(local_path: str, keep_days: int, dry_run: bool = False):
    """
    删除 local_path 下修改时间早于 keep_days 天的备份文件。
    keep_days <= 0 表示不清理。返回被删除（或将被删除）的文件路径列表。
    """
    deleted = []
    if not local_path or not os.path.isdir(local_path):
        return deleted
    if keep_days is None or keep_days <= 0:
        return deleted
    cutoff = time.time() - float(keep_days) * 86400
    for path in glob.glob(os.path.join(local_path, "*")):
        try:
            if not os.path.isfile(path):
                continue
            name = os.path.basename(path)
            if not BACKUP_PATTERN.match(name):
                continue
            mtime = os.path.getmtime(path)
            if mtime < cutoff:
                if not dry_run:
                    os.remove(path)
                deleted.append(path)
        except Exception:
            continue
    if deleted:
        log_info("本地清理：删除 %d 个超过 %d 天的历史备份" % (len(deleted), keep_days))
    return deleted


def list_local_backups(local_path: str):
    """列出本地备份文件（名称、大小、修改时间），按时间倒序"""
    items = []
    if not local_path or not os.path.isdir(local_path):
        return items
    for path in glob.glob(os.path.join(local_path, "*")):
        try:
            if not os.path.isfile(path):
                continue
            if not BACKUP_PATTERN.match(os.path.basename(path)):
                continue
            st = os.stat(path)
            items.append({
                "name": os.path.basename(path),
                "size": st.st_size,
                "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items

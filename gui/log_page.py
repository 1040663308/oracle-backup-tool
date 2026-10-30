# -*- coding: utf-8 -*-
"""日志页面：实时显示备份日志（批量刷新，避免高频更新拖垮 GUI）"""
from __future__ import annotations

import os
import time
import tkinter as tk
from tkinter import filedialog, ttk

from app import paths
from app.logger import LOG_BUS
from . import widgets as W

MAX_LINES = 3000          # 界面最多保留行数
FLUSH_INTERVAL_MS = 400   # 批量刷新间隔（毫秒）


class LogPage:
    def __init__(self, parent, app):
        self.app = app
        self.frame = ttk.Frame(parent)
        self._pending = []            # 待显示的 (level, message)
        self._flush_scheduled = False
        self._build()
        LOG_BUS.subscribe(self._on_log)
        self._load_recent_file_log()

    def _build(self):
        bar = ttk.Frame(self.frame)
        bar.pack(fill="x", padx=8, pady=6)
        ttk.Label(bar, text="运行日志", style="Title.TLabel").pack(side="left")
        ttk.Button(bar, text="清空显示", command=self._clear).pack(side="right")
        ttk.Button(bar, text="另存为...", command=self._save_as).pack(
            side="right", padx=6)
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="自动滚动", variable=self.autoscroll).pack(
            side="right", padx=10)

        self.text = tk.Text(self.frame, wrap="word", state="disabled",
                            font=("Consolas", 9), bg="#FFFFFF", fg="#333333",
                            relief="flat", borderwidth=0, padx=4, pady=4)
        sb = ttk.Scrollbar(self.frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        sb.pack(side="right", fill="y", padx=(0, 8), pady=(0, 8))

        # 日志级别颜色
        self.text.tag_configure("INFO", foreground="#1a7f37")
        self.text.tag_configure("WARNING", foreground="#b26a00")
        self.text.tag_configure("ERROR", foreground="#c62828")
        self.text.tag_configure("DEBUG", foreground="#666666")

        hint = ttk.Label(self.frame, text="", style="Hint.TLabel")
        hint.pack(side="bottom", anchor="w", padx=8, pady=(0, 6))
        hint.config(text="日志文件位置：%s" % paths.get_log_file())

    # ------------------------------------------------------------ 显示
    def _on_log(self, level: str, message: str):
        """LOG_BUS 回调（来自备份线程）：只入缓冲，由定时器批量刷新"""
        self._pending.append((level, message))
        if len(self._pending) > 2000:      # 防御：缓冲过大时丢弃最旧的
            del self._pending[:1000]
        if not self._flush_scheduled:
            self._flush_scheduled = True
            try:
                self.frame.after(FLUSH_INTERVAL_MS, self._flush)
            except Exception:
                self._flush_scheduled = False

    def _flush(self):
        """把累积的日志一次性插入（一次重绘，避免逐行刷新卡死界面）"""
        self._flush_scheduled = False
        items = self._pending
        self._pending = []
        if not items:
            return
        try:
            self.text.configure(state="normal")
            stamp = time.strftime("%H:%M:%S")
            for level, message in items:
                self.text.insert("end", "[%s] " % stamp, "DEBUG")
                tag = level if level in ("INFO", "WARNING", "ERROR", "DEBUG") else "INFO"
                self.text.insert("end", message + "\n", tag)
            # 限制行数
            line_count = int(self.text.index("end-1c").split(".")[0])
            if line_count > MAX_LINES:
                self.text.delete("1.0", "%d.0" % (line_count - MAX_LINES))
            if self.autoscroll.get():
                self.text.see("end")
            self.text.configure(state="disabled")
        except Exception:
            pass

    def _load_recent_file_log(self):
        """加载日志文件最后 100 行，方便查看历史"""
        try:
            log_file = paths.get_log_file()
            if not os.path.exists(log_file):
                return
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-100:]
            self.text.configure(state="normal")
            for line in lines:
                line = line.rstrip("\n")
                level = "INFO"
                for lv in ("ERROR", "WARNING", "DEBUG"):
                    if "[%s]" % lv in line:
                        level = lv
                        break
                self.text.insert("end", line + "\n", level)
            self.text.see("end")
            self.text.configure(state="disabled")
        except Exception:
            pass

    def _clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def _save_as(self):
        path = filedialog.asksaveasfilename(
            parent=self.frame, title="保存日志", defaultextension=".log",
            initialfile="orabackup_%s.log" % time.strftime("%Y%m%d_%H%M%S"),
            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt")])
        if path:
            try:
                content = self.text.get("1.0", "end")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                W.show_info(self.frame, "保存成功", "日志已保存到：\n%s" % path)
            except Exception as exc:
                W.show_error(self.frame, "保存失败", str(exc))

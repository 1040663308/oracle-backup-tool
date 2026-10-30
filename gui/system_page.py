# -*- coding: utf-8 -*-
"""系统设置页面：开机自启动、通知开关、目录快捷入口"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app import autostart, paths
from . import widgets as W


class SystemPage:
    def __init__(self, parent, app):
        self.app = app
        self.frame = ttk.Frame(parent)
        self._build()

    def _build(self):
        outer = W.ScrollableFrame(self.frame)
        outer.pack(fill="both", expand=True, padx=8, pady=8)
        f = outer.inner
        row = 0

        def section(title):
            nonlocal row
            box = ttk.LabelFrame(f, text=title)
            box.grid(row=row, column=0, sticky="ew", pady=(4, 8), padx=2)
            box.columnconfigure(1, weight=1)
            row += 1
            return box

        # ---------- 启动 ----------
        box = section("系统启动")
        self.autostart = W.LabeledCheck(box, "开机自动启动（写入当前用户注册表启动项）")
        self.autostart.grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.start_minimized = W.LabeledCheck(box, "启动时最小化到任务栏")
        self.start_minimized.grid(row=1, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(box, text="提示：定时备份依赖程序保持运行，建议开启开机自启动。",
                  style="Hint.TLabel").grid(row=2, column=0, sticky="w", padx=8,
                                            pady=(0, 6))

        # ---------- 通知 ----------
        box = section("通知开关")
        self.notify_on_success = W.LabeledCheck(box, "备份成功后发送通知")
        self.notify_on_success.grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.notify_on_failure = W.LabeledCheck(box, "备份失败后发送通知")
        self.notify_on_failure.grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.notify_on_warning = W.LabeledCheck(
            box, "备份有异常时也发送通知")
        self.notify_on_warning.grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(box, text="异常包括：部分用户导出失败、磁盘空间偏小、目录探测失败等",
                  style="Hint.TLabel").grid(row=2, column=1, sticky="w", padx=8)

        # ---------- 目录 ----------
        box = section("数据目录")
        ttk.Button(box, text="打开配置目录", command=self._open_config_dir
                   ).grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.config_dir_label = ttk.Label(box, text="", style="Hint.TLabel")
        self.config_dir_label.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Button(box, text="打开日志目录", command=self._open_log_dir
                   ).grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Button(box, text="导出示例配置", command=self._export_example
                   ).grid(row=2, column=0, sticky="w", padx=8, pady=6)

        # ---------- 关于 ----------
        box = section("关于")
        from app import APP_TITLE, __version__
        ttk.Label(box, text="%s v%s" % (APP_TITLE, __version__)).grid(
            row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(box, text="通过 SSH 在 Linux 服务器上执行 Oracle Data Pump 导出、"
                            "压缩并下载到 Windows 本地，"
                            "支持定时备份与多渠道通知。",
                  style="Hint.TLabel", wraplength=560, justify="left").grid(
            row=1, column=0, sticky="w", padx=8, pady=(0, 8))

    # ------------------------------------------------------------ 数据
    def load(self, cfg: dict):
        s = cfg.get("system", {})
        self.autostart.set(s.get("autostart", False))
        self.start_minimized.set(s.get("start_minimized", False))
        self.notify_on_success.set(s.get("notify_on_success", True))
        self.notify_on_failure.set(s.get("notify_on_failure", True))
        self.notify_on_warning.set(s.get("notify_on_warning", True))
        self.config_dir_label.config(text=paths.get_app_dir())

    def collect(self, cfg: dict):
        s = cfg.setdefault("system", {})
        s["autostart"] = self.autostart.get()
        s["start_minimized"] = self.start_minimized.get()
        s["notify_on_success"] = self.notify_on_success.get()
        s["notify_on_failure"] = self.notify_on_failure.get()
        s["notify_on_warning"] = self.notify_on_warning.get()
        return cfg

    # ------------------------------------------------------------ 操作
    def _open_config_dir(self):
        W.open_path(paths.get_app_dir())

    def _open_log_dir(self):
        W.open_path(paths.get_log_dir())

    def _export_example(self):
        from tkinter import filedialog
        from app.config import example_config
        path = filedialog.asksaveasfilename(
            parent=self.frame, title="导出示例配置",
            defaultextension=".json", initialfile="config.example.json",
            filetypes=[("JSON 配置文件", "*.json")])
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(example_config())
                W.show_info(self.frame, "导出成功", "示例配置已保存到：\n%s" % path)
            except Exception as exc:
                W.show_error(self.frame, "导出失败", str(exc))

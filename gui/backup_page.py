# -*- coding: utf-8 -*-
"""备份配置页面：导出用户勾选、保留策略、定时计划"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk

from app import oracle
from app.logger import log_error, log_info
from app.ssh import SSHError, SSHConnection
from . import widgets as W

DAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


class SchemaSelectDialog:
    """导出用户（模式）勾选对话框：复选框式多选 + 搜索过滤"""

    def __init__(self, parent, cfg: dict, current: list):
        self.cfg = cfg
        self.current = list(current or [])
        self.result = None
        self.all_users = []            # 全部可选用户
        self.check_vars = {}           # 用户名 -> BooleanVar
        self.win = tk.Toplevel(parent)
        self.win.title("选择需要导出的数据库用户")
        self.win.geometry("520x620")
        self.win.minsize(420, 480)
        self.win.transient(parent)
        self.win.grab_set()
        self._build()
        # 打开后自动获取一次用户列表
        self.win.after(100, self._fetch)
        self.win.wait_window()
        # 关闭后 result 为 None 表示取消

    def _build(self):
        top = ttk.Frame(self.win)
        top.pack(fill="x", padx=10, pady=8)
        ttk.Button(top, text="连接服务器获取用户列表",
                   command=self._fetch).pack(side="left")
        self.status = ttk.Label(top, text="", style="Hint.TLabel")
        self.status.pack(side="left", padx=10)

        # 搜索过滤框
        filter_row = ttk.Frame(self.win)
        filter_row.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(filter_row, text="搜索:").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(filter_row, textvariable=self.filter_var).pack(
            side="left", fill="x", expand=True, padx=6)

        # 复选框列表（可滚动）
        mid = ttk.Frame(self.win)
        mid.pack(fill="both", expand=True, padx=10, pady=4)
        self.canvas = tk.Canvas(mid, borderwidth=0, highlightthickness=0)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.canvas.yview)
        self.list_frame = ttk.Frame(self.canvas)
        self.list_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all(
            "<MouseWheel>", self._on_mousewheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

        # 上下文提示（如 CDB/PDB 提示、错误说明）
        self.hint = ttk.Label(self.win, text="", style="Hint.TLabel",
                              wraplength=480, justify="left")
        self.hint.pack(fill="x", padx=10, pady=(0, 4))

        bottom = ttk.Frame(self.win)
        bottom.pack(fill="x", padx=10, pady=8)
        ttk.Button(bottom, text="全选", width=8,
                   command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(bottom, text="反选", width=8,
                   command=self._invert).pack(side="left", padx=6)
        ttk.Button(bottom, text="清空", width=8,
                   command=lambda: self._set_all(False)).pack(side="left")
        self.count_label = ttk.Label(bottom, text="已选 0 个", style="Hint.TLabel")
        self.count_label.pack(side="left", padx=14)
        ttk.Frame(bottom).pack(side="left", expand=True)
        ttk.Button(bottom, text="确定", width=10,
                   command=self._ok).pack(side="right")
        ttk.Button(bottom, text="取消", width=10,
                   command=self.win.destroy).pack(side="right", padx=6)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ------------------------------------------------------------ 列表渲染
    def _rebuild_list(self):
        """按当前过滤条件渲染复选框列表"""
        for child in self.list_frame.winfo_children():
            child.destroy()
        keyword = self.filter_var.get().strip().upper()
        shown = 0
        for user in self.all_users:
            if keyword and keyword not in user.upper():
                continue
            var = self.check_vars[user]
            ttk.Checkbutton(self.list_frame, text=user,
                            variable=var).pack(anchor="w", padx=4, pady=1)
            shown += 1
        if not self.all_users:
            ttk.Label(self.list_frame, text="（尚未获取用户列表，请点击上方按钮连接服务器）",
                      style="Hint.TLabel").pack(anchor="w", padx=4, pady=8)
        elif shown == 0:
            ttk.Label(self.list_frame, text="（没有匹配的用户）",
                      style="Hint.TLabel").pack(anchor="w", padx=4, pady=8)
        self._update_count()

    def _apply_filter(self):
        self._rebuild_list()

    def _update_count(self):
        count = sum(1 for v in self.check_vars.values() if v.get())
        self.count_label.config(text="已选 %d 个" % count)

    def _set_all(self, value: bool):
        for var in self.check_vars.values():
            var.set(value)
        self._update_count()

    def _invert(self):
        for var in self.check_vars.values():
            var.set(not var.get())
        self._update_count()

    # ------------------------------------------------------------ 数据获取
    def _fetch(self):
        self.status.config(text="正在连接服务器查询用户...")
        self.win.update_idletasks()
        threading.Thread(target=self._fetch_thread, daemon=True).start()

    def _fetch_thread(self):
        try:
            with SSHConnection(self.cfg.get("server", {})) as ssh:
                users = oracle.query_db_users(ssh, self.cfg["server"])
            selectable = [u for u in users if u.upper() not in oracle.SYSTEM_USERS]

            def _done():
                self.all_users = selectable
                self.check_vars = {}
                for u in selectable:
                    var = tk.BooleanVar(value=(u in self.current))
                    var.trace_add("write", lambda *_: self._update_count())
                    self.check_vars[u] = var
                self._rebuild_list()
                if selectable:
                    self.status.config(
                        text="共 %d 个可选用户（已排除系统内置账户）" % len(selectable))
                elif users:
                    # 查到了用户但全是系统账户：典型是连到了 CDB 根容器
                    self.status.config(
                        text="查询到 %d 个用户，但均为系统内置账户" % len(users))
                    self.hint.config(
                        text="提示：可能连接到了 CDB 根容器。若为 12c+ 多租户架构，"
                             "请将「数据库连接名」改为 PDB 服务名"
                             "（如 ORCLPDB1，可用 select name from v$pdbs 查询）",
                        foreground="#B26A00")
                else:
                    self.status.config(text="未查询到任何用户")

            self.win.after(0, _done)
            log_info("用户列表获取成功：%d 个可选" % len(selectable))
        except Exception as exc:
            log_error("获取用户列表失败：%s" % exc)
            first_line = str(exc).split("\n")[0]

            def _fail():
                self.status.config(text="获取失败：%s" % first_line)
                W.show_error(self.win, "获取用户列表失败", str(exc))

            self.win.after(0, _fail)

    def _ok(self):
        self.result = [u for u in self.all_users if self.check_vars[u].get()]
        self.win.destroy()


class BackupPage:
    """备份策略配置"""

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
            row += 1
            return box

        # ---------- 导出内容 ----------
        box = section("导出内容")
        r = ttk.Frame(box)
        r.grid(row=0, column=0, columnspan=3, sticky="ew", padx=8, pady=6)
        r.columnconfigure(1, weight=1)
        ttk.Label(r, text="导出用户(模式)", width=16, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 6))
        self.schemas_var = tk.StringVar()
        self.schemas_entry = ttk.Entry(r, textvariable=self.schemas_var)
        self.schemas_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(r, text="勾选用户...", command=self._select_schemas).grid(
            row=0, column=2, padx=(6, 0))
        ttk.Label(r, text="在服务器上勾选需要导出的数据库用户（模式）",
                  style="Hint.TLabel").grid(row=1, column=1, sticky="w", pady=(2, 0))

        # 打包方式
        r2 = ttk.Frame(box)
        r2.grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 6))
        ttk.Label(r2, text="打包方式", width=16, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 6))
        self.pack_mode = tk.StringVar(value="combined")
        ttk.Radiobutton(r2, text="全部打成一个包", variable=self.pack_mode,
                        value="combined").grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(r2, text="按用户分别打包", variable=self.pack_mode,
                        value="per_schema").grid(row=0, column=2, sticky="w", padx=12)
        ttk.Label(r2, text="按用户打包时每个用户一个 tar.gz，恢复更灵活；"
                           "单个用户导出失败不影响其他用户",
                  style="Hint.TLabel").grid(row=1, column=1, columnspan=2,
                                            sticky="w")

        # ---------- 保留策略 ----------
        box = section("保留策略")
        self.remote_keep = W.LabeledSpin(
            box, "服务器保留天数", from_=0, to=365, width=8,
            hint="服务器上保留最近几天的导出文件，0=不清理")
        self.remote_keep.grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.local_keep = W.LabeledSpin(
            box, "本地保留天数", from_=0, to=3650, width=8,
            hint="本地超过该天数的备份自动删除，如 30")
        self.local_keep.grid(row=0, column=1, sticky="w", padx=8, pady=4)
        self.parallel = W.LabeledSpin(
            box, "导出并行度", from_=1, to=32, width=6,
            hint="按用户分包时按数据量自动调整（小模式自动低并行，避免碎片文件）")
        self.parallel.grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.compress = W.LabeledCheck(box, "导出后压缩为 tar.gz")
        self.compress.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        self.exclude_stats = W.LabeledCheck(
            box, "排除统计信息（减小体积）")
        self.exclude_stats.grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Label(box, text="大库的优化器统计可占数 GB，排除不影响数据恢复"
                            "（恢复后重新收集即可）；需要带走统计时取消勾选",
                  style="Hint.TLabel").grid(row=2, column=1, sticky="w", padx=8)

        # ---------- 本地路径 ----------
        box = section("本地存储")
        self.local_path = W.PathEntry(box, "本地备份路径",
                                      hint="备份文件下载到 Windows 的目录",
                                      on_change=self._refresh_local_space)
        self.local_path.grid(row=0, column=0, columnspan=2, sticky="ew",
                             padx=8, pady=6)
        self.local_space_label = ttk.Label(box, text="", style="Hint.TLabel")
        self.local_space_label.grid(row=1, column=0, columnspan=2, sticky="w",
                                    padx=8, pady=(0, 6))

        # ---------- 定时备份 ----------
        box = section("定时备份")
        self.schedule_enabled = W.LabeledCheck(box, "启用定时备份")
        self.schedule_enabled.grid(row=0, column=0, sticky="w", padx=8, pady=4)
        r = ttk.Frame(box)
        r.grid(row=0, column=1, sticky="w", padx=8, pady=4)
        ttk.Label(r, text="每天执行时间").pack(side="left")
        self.schedule_time = ttk.Entry(r, width=8)
        self.schedule_time.pack(side="left", padx=(4, 0))
        ttk.Label(r, text="（HH:MM，24小时制）", style="Hint.TLabel").pack(side="left",
                                                                        padx=(4, 0))

        ttk.Label(box, text="执行日").grid(row=1, column=0, sticky="e", padx=(8, 6),
                                           pady=4)
        days_frame = ttk.Frame(box)
        days_frame.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        self.day_vars = []
        for i, name in enumerate(DAY_NAMES):
            var = tk.BooleanVar(value=True)
            self.day_vars.append(var)
            ttk.Checkbutton(days_frame, text=name, variable=var).pack(side="left")

        ttk.Label(box, text="提示：若到计划时间计算机关机，开机后将自动补跑当天备份。",
                  style="Hint.TLabel").grid(row=2, column=0, columnspan=2,
                                            sticky="w", padx=8, pady=(0, 6))

    # ------------------------------------------------------------ 数据
    def load(self, cfg: dict):
        bak = cfg.get("backup", {})
        self.schemas_var.set(", ".join(bak.get("schemas") or []))
        self.remote_keep.set(bak.get("remote_keep_days", 3))
        self.local_keep.set(bak.get("local_keep_days", 30))
        self.parallel.set(bak.get("parallel", 1))
        self.compress.set(bak.get("compress", True))
        self.exclude_stats.set(bak.get("exclude_statistics", True))
        self.pack_mode.set(bak.get("pack_mode", "combined"))
        self.local_path.set(bak.get("local_path", ""))
        self.schedule_enabled.set(bak.get("schedule_enabled", True))
        self.schedule_time.delete(0, "end")
        self.schedule_time.insert(0, bak.get("schedule_time", "02:00"))
        days = bak.get("schedule_days") or [0, 1, 2, 3, 4, 5, 6]
        for i, var in enumerate(self.day_vars):
            var.set(i in days)
        self._refresh_local_space()

    def _refresh_local_space(self):
        """本地备份路径的剩余空间与可存天数提示"""
        try:
            path = self.local_path.get().strip()
            if not path or not os.path.isdir(path):
                self.local_space_label.config(text="")
                return
            from app.utils import disk_free_bytes, format_size
            free = disk_free_bytes(path)
            keep_days = max(1, self.local_keep.get())
            # 估算：假设每天一个备份，用当前已有备份的平均大小估算可存天数
            avg_size = self._avg_backup_size(path)
            text = "本地剩余空间：%s" % format_size(free)
            if avg_size and avg_size > 0:
                days = max(1, int(free / avg_size))
                text += "；按当前平均备份大小约可存 %d 天" % days
                if days < keep_days:
                    text += "（⚠ 少于保留天数 %d，可能存不下）" % keep_days
            self.local_space_label.config(text=text)
        except Exception:
            pass

    def _avg_backup_size(self, path: str) -> int:
        try:
            from app.cleanup import list_local_backups
            items = list_local_backups(path)
            if not items:
                return 0
            return sum(i["size"] for i in items) // len(items)
        except Exception:
            return 0

    def collect(self, cfg: dict):
        bak = cfg.setdefault("backup", {})
        schemas = [s.strip() for s in self.schemas_var.get().split(",") if s.strip()]
        bak["schemas"] = schemas
        bak["remote_keep_days"] = self.remote_keep.get()
        bak["local_keep_days"] = self.local_keep.get()
        bak["parallel"] = max(1, self.parallel.get())
        bak["auto_parallel"] = bak.get("auto_parallel", True)  # 自动并行度（无界面开关，默认开）
        bak["compress"] = self.compress.get()
        bak["exclude_statistics"] = self.exclude_stats.get()
        bak["pack_mode"] = self.pack_mode.get()
        bak["local_path"] = self.local_path.get()
        bak["schedule_enabled"] = self.schedule_enabled.get()
        time_str = self.schedule_time.get().strip()
        from app.utils import is_valid_time
        if not is_valid_time(time_str):
            raise ValueError("定时时间格式无效：%s（应为 HH:MM，如 02:00）" % time_str)
        bak["schedule_time"] = time_str
        bak["schedule_days"] = [i for i, var in enumerate(self.day_vars) if var.get()]
        return cfg

    # ------------------------------------------------------------ 用户勾选
    def _select_schemas(self):
        self.app.save_config(silent=True)
        cfg = self.app.cfg
        current = [s.strip() for s in self.schemas_var.get().split(",") if s.strip()]
        dialog = SchemaSelectDialog(self.frame, cfg, current)
        if dialog.result is not None:
            self.schemas_var.set(", ".join(dialog.result))
            log_info("已选择导出用户：%s" % (", ".join(dialog.result) or "无"))

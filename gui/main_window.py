# -*- coding: utf-8 -*-
"""主窗口：标签页管理、备份触发、状态栏"""
from __future__ import annotations

import copy
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

from app import APP_TITLE, autostart, paths, scheduler as sched
from app.backup import BackupRunner
from app.config import ConfigError, load_config, save_config
from app.logger import log_error, log_info
from app.utils import format_duration, format_size, now_str
from . import widgets as W
from .backup_page import BackupPage
from .log_page import LogPage
from .notify_page import NotifyPage
from .server_page import ServerPage
from .system_page import SystemPage


class MainWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1120x800")
        self.root.minsize(1020, 700)

        self.cfg = {}
        self.backup_thread = None
        self.cancel_event = threading.Event()
        self._current_run_scheduled = False
        self._last_progress_pct = -1.0
        self._last_progress_time = 0.0
        self.scheduler = None

        W.setup_styles(root)
        self._build_menu()
        self._build_widgets()
        self._load_config()

        # 启动定时调度线程
        self.scheduler = sched.BackupScheduler(
            get_config=lambda: self.cfg, trigger=self._on_scheduled_backup)
        self.scheduler.start()

        # 同步开机自启动注册表
        try:
            sys_cfg = self.cfg.get("system", {})
            autostart.sync_autostart(
                bool(sys_cfg.get("autostart")),
                bool(sys_cfg.get("start_minimized")))
        except Exception:
            pass

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.set_status("就绪 | %s" % self.scheduler.next_run_text())

        # 命令行 --minimized 支持
        if "--minimized" in sys.argv:
            self.root.after(200, self.root.iconify)

    # ------------------------------------------------------------ 界面
    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="保存配置", command=lambda: self.save_config())
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", command=self._show_help)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.root.config(menu=menubar)

    def _build_widgets(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)

        self.pages = {}
        self.server_page = ServerPage(self.notebook, self)
        self.backup_page = BackupPage(self.notebook, self)
        self.notify_page = NotifyPage(self.notebook, self)
        self.system_page = SystemPage(self.notebook, self)
        self.log_page = LogPage(self.notebook, self)

        self.notebook.add(self.server_page.frame, text=" 数据库服务器 ")
        self.notebook.add(self.backup_page.frame, text=" 备份策略 ")
        self.notebook.add(self.notify_page.frame, text=" 消息通知 ")
        self.notebook.add(self.system_page.frame, text=" 系统设置 ")
        self.notebook.add(self.log_page.frame, text=" 运行日志 ")

        # 底部按钮与状态栏
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=10, pady=(0, 8))
        self.btn_backup = ttk.Button(bottom, text="立即备份", width=12,
                                     style="Primary.TButton",
                                     command=self.start_backup)
        self.btn_backup.pack(side="right")
        self.btn_save = ttk.Button(bottom, text="保存配置", width=12,
                                   command=lambda: self.save_config())
        self.btn_save.pack(side="right", padx=6)
        self.btn_test_notify = ttk.Button(bottom, text="测试通知", width=12,
                                          command=self.notify_page._test_notify)
        self.btn_test_notify.pack(side="right", padx=6)
        self.btn_cancel = ttk.Button(bottom, text="取消备份", width=12,
                                     command=self.cancel_backup, state="disabled")
        self.btn_cancel.pack(side="right", padx=6)

        status = ttk.Frame(self.root, relief="flat")
        status.pack(fill="x", side="bottom", padx=0, pady=0)
        ttk.Separator(self.root, orient="horizontal").pack(
            fill="x", side="bottom", before=status)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status, textvariable=self.status_var, anchor="w",
                  padding=(10, 4)).pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(status, mode="determinate", length=220,
                                        maximum=100)
        self.progress.pack(side="right", padx=10, pady=4)

    # ------------------------------------------------------------ 配置
    def _load_config(self):
        try:
            self.cfg = load_config()
        except ConfigError as exc:
            W.show_error(self.root, "配置加载失败", str(exc))
            from app.config import DEFAULT_CONFIG
            self.cfg = DEFAULT_CONFIG
        for page in (self.server_page, self.backup_page, self.notify_page,
                     self.system_page):
            page.load(self.cfg)
        log_info("配置已加载：%s" % paths.get_config_path())

    def save_config(self, silent: bool = False) -> bool:
        """从各页面收集配置并保存"""
        try:
            cfg = copy.deepcopy(self.cfg)
            for page in (self.server_page, self.backup_page, self.notify_page,
                         self.system_page):
                page.collect(cfg)
        except Exception as exc:
            if not silent:
                W.show_error(self.root, "配置无效", str(exc))
            return False
        old_autostart = self.cfg.get("system", {}).get("autostart")
        try:
            path = save_config(cfg)
        except Exception as exc:
            if not silent:
                W.show_error(self.root, "保存失败", str(exc))
            return False
        self.cfg = cfg
        # 自启动设置变化时同步注册表
        new_autostart = cfg.get("system", {}).get("autostart")
        if bool(old_autostart) != bool(new_autostart):
            ok = autostart.sync_autostart(
                bool(new_autostart), bool(cfg.get("system", {}).get("start_minimized")))
            if not ok and new_autostart:
                W.show_warning(self.root, "开机自启动",
                               "写入注册表失败，请检查系统权限。")
        if not silent:
            W.show_info(self.root, "保存成功", "配置已保存到：\n%s" % path)
            log_info("配置已保存")
        return True

    # ------------------------------------------------------------ 备份
    def start_backup(self, scheduled: bool = False):
        if self.backup_thread and self.backup_thread.is_alive():
            if not scheduled:
                W.show_warning(self.root, "提示", "备份正在进行中，请先等待完成或取消。")
            return
        if not self.save_config(silent=True):
            if not scheduled:
                W.show_error(self.root, "配置无效", "请检查各页配置（如定时时间格式）。")
            return
        cfg = self.cfg
        if not cfg.get("backup", {}).get("schemas"):
            if scheduled:
                log_error("定时备份已跳过：尚未勾选任何导出用户（模式），"
                          "请在「备份策略」页配置。")
                return
            if not W.confirm(self.root, "未选择导出用户",
                             "尚未勾选任何导出用户（模式），"
                             "将无法执行导出。\n\n是否仍要直接继续？\n"
                             "（建议前往「备份策略」页勾选用户）"):
                return
        if not cfg.get("backup", {}).get("local_path"):
            if scheduled:
                log_error("定时备份已跳过：未配置本地备份路径。")
                return
            W.show_error(self.root, "配置缺失", "请先配置本地备份路径。")
            return

        self.cancel_event.clear()
        self._set_running(True)
        self._current_run_scheduled = scheduled
        if scheduled:
            log_info("定时备份开始执行")
        else:
            log_info("手动触发备份")

        def _worker():
            try:
                runner = BackupRunner(
                    cfg, on_log=self._on_backup_log,
                    on_progress=self._on_backup_progress,
                    cancel_event=self.cancel_event)
                result = runner.run()
                if result.success:
                    sched.set_last_run_date()
                self.on_ui(lambda: self._on_backup_done(result))
            except Exception as exc:
                log_error("备份线程异常：%s" % exc)
                self.on_ui(lambda: self._on_backup_done(None, str(exc)))

        self.backup_thread = threading.Thread(target=_worker, daemon=True,
                                              name="BackupRunner")
        self.backup_thread.start()

    def _on_scheduled_backup(self):
        """调度线程触发（已在后台线程中调用）"""
        self.on_ui(lambda: self.start_backup(scheduled=True))

    def cancel_backup(self):
        if self.backup_thread and self.backup_thread.is_alive():
            self.cancel_event.set()
            self.set_status("正在取消备份...")
            log_info("用户请求取消备份")

    def _set_running(self, running: bool):
        self.btn_backup.config(state="disabled" if running else "normal")
        self.btn_cancel.config(state="normal" if running else "disabled")
        self.btn_save.config(state="disabled" if running else "normal")
        if not running:
            self._stop_indeterminate()

    def _on_backup_log(self, level: str, message: str):
        from app.logger import log
        log(level, message)
        # 状态栏阶段提示（轻量匹配，避免逐行刷新界面）
        try:
            if "开始 Data Pump 导出" in message or "开始按用户分别导出" in message:
                self.on_ui(lambda: self.set_status("备份进行中：正在导出数据…"))
                self.on_ui(self._start_indeterminate)
            elif "正在导出用户" in message:
                self.on_ui(lambda: self.set_status("备份进行中：%s" % message[6:60]))
            elif "开始压缩" in message:
                self.on_ui(lambda: self.set_status("备份进行中：正在压缩…"))
            elif "开始下载备份文件" in message or "的备份：" in message:
                self.on_ui(self._stop_indeterminate)
                self.on_ui(lambda: self.set_status("备份进行中：正在下载到本地…"))
            elif "本地清理" in message:
                self.on_ui(lambda: self.set_status("备份进行中：正在清理本地旧备份…"))
            elif "用户" in message and "完成" in message:
                self.on_ui(lambda: self.set_status("备份进行中：%s" % message[6:60]))
        except Exception:
            pass

    def _on_backup_progress(self, done: int, total: int):
        # 进度条节流：每 0.5 秒最多更新一次，变化小于 1% 时跳过
        if total <= 0:
            return
        percent = min(100.0, done * 100.0 / total)
        now = time.time()
        if (now - self._last_progress_time) < 0.5 and abs(
                percent - self._last_progress_pct) < 1.0:
            return
        self._last_progress_time = now
        self._last_progress_pct = percent
        self.on_ui(lambda: self.progress.config(value=percent))

    def _start_indeterminate(self):
        """导出阶段进度未知，切换为滚动动画模式"""
        try:
            self.progress.config(mode="indeterminate")
            self.progress.start(15)
        except Exception:
            pass

    def _stop_indeterminate(self):
        """下载阶段有确定进度，切回确定模式"""
        try:
            self.progress.stop()
            self.progress.config(mode="determinate", value=0)
        except Exception:
            pass

    def _on_backup_done(self, result, error: str = None):
        self._stop_indeterminate()
        self._set_running(False)
        scheduled = getattr(self, "_current_run_scheduled", False)
        if result is not None and result.success:
            if result.mode == "per_schema" and result.files:
                size_text = format_size(result.size)
                file_text = "按用户分包：%d 个用户（共 %s）\n\n" % (
                    len(result.files), size_text)
                for f in result.files[:10]:
                    file_text += "  %s：%s\n" % (f["schema"], format_size(f["size"]))
                if len(result.files) > 10:
                    file_text += "  …（其余 %d 个见日志）\n" % (len(result.files) - 10)
                if result.failed_schemas:
                    file_text += "\n⚠ 失败的用户：%s" % ", ".join(result.failed_schemas)
            else:
                file_text = "文件：%s\n大小：%s\n" % (
                    result.filename, format_size(result.size))
            if getattr(result, "warnings", None):
                file_text += "\n⚠ 异常 %d 条：\n" % len(result.warnings)
                for w in result.warnings[:5]:
                    file_text += "  · %s\n" % w
            self.set_status("备份成功：%s" % result.finished_at)
            # 手动备份完成时弹窗明确告知（定时备份不弹窗打扰）
            if not scheduled:
                W.show_info(
                    self.root, "备份完成",
                    "备份成功！\n\n%s\n耗时：%s\n保存位置：%s\n\n"
                    "通知已按配置发送。" % (
                        file_text,
                        format_duration(result.duration),
                        result.local_path or result.local_file))
        elif result is not None:
            self.set_status("备份失败：%s" % (result.error or "未知错误")[:60])
            if not scheduled:
                W.show_error(self.root, "备份失败",
                             "备份未能完成：\n%s\n\n详细信息请查看「运行日志」标签页。"
                             % (result.error or "未知错误"))
        else:
            # 备份线程意外异常：补发通知（正常失败路径已由 BackupRunner 通知）
            self.set_status("备份异常：%s" % (error or "未知错误"))
            self._notify_unexpected_error(str(error or "未知错误"))
            if not scheduled:
                W.show_error(self.root, "备份异常", str(error or "未知错误"))
        # 仅手动备份时自动切换到日志页，避免定时备份打断用户操作
        if not scheduled:
            self.notebook.select(self.log_page.frame)

    def _notify_unexpected_error(self, message: str):
        """备份线程未捕获异常时，兜底发送失败通知"""
        try:
            from app.backup import BackupResult
            from app import notify as notify_mod
            from app.utils import now_str
            sys_cfg = self.cfg.get("system", {})
            if not sys_cfg.get("notify_on_failure", True):
                return
            result = BackupResult(
                success=False, started_at=now_str(), finished_at=now_str(),
                error="备份程序内部异常：%s" % message,
                local_path=self.cfg.get("backup", {}).get("local_path", ""))
            notifier = notify_mod.Notifier(
                self.cfg.get("notify", {}),
                on_success=bool(sys_cfg.get("notify_on_success", True)),
                on_failure=True,
                on_warning=bool(sys_cfg.get("notify_on_warning", True)))
            notifier.send(result, self.cfg)
            log_info("已发送异常通知")
        except Exception as exc:
            log_error("异常通知发送失败：%s" % exc)

    # ------------------------------------------------------------ 工具
    def on_ui(self, func):
        """在 UI 线程执行回调"""
        try:
            self.root.after(0, func)
        except Exception:
            pass

    def run_async(self, func, *args):
        threading.Thread(target=func, args=args, daemon=True).start()

    def set_status(self, text: str):
        self.status_var.set(text)

    # ------------------------------------------------------------ 对话框
    def _show_help(self):
        W.show_info(self.root, "使用说明",
                    "1. 「数据库服务器」填写 Linux 服务器 SSH 与 Oracle 环境信息；\n"
                    "2. 「备份策略」勾选导出用户、设置本地路径与保留天数、定时时间；\n"
                    "3. 「消息通知」按需启用 PushPlus / 邮件 / 钉钉机器人；\n"
                    "4. 「系统设置」可开启开机自启动；\n"
                    "5. 点击「保存配置」后，可点「立即备份」验证，之后按计划自动执行。\n\n"
                    "详细说明请查看项目目录下的 README.md。")

    def _show_about(self):
        from app import __version__
        W.show_info(self.root, "关于",
                    "%s v%s\n\nOracle 数据库自动备份工具\n"
                    "支持 Data Pump 导出、压缩、下载、定时清理与多渠道通知。"
                    % (APP_TITLE, __version__))

    # ------------------------------------------------------------ 关闭
    def _on_close(self):
        if self.backup_thread and self.backup_thread.is_alive():
            if not W.confirm(self.root, "备份进行中",
                             "备份正在进行，确定要退出吗？\n"
                             "（取消后本次备份将中断）"):
                return
            self.cancel_event.set()
        if self.scheduler:
            self.scheduler.stop()
        self.root.destroy()


def run():
    root = tk.Tk()
    MainWindow(root)
    root.mainloop()

# -*- coding: utf-8 -*-
"""GUI 通用控件与工具"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def setup_styles(root: tk.Tk):
    """统一字体与样式（浅色现代风格）"""
    style = ttk.Style(root)
    # 优先使用 Vista 主题（Win），回退 clam
    try:
        if "vista" in style.theme_names():
            style.theme_use("vista")
        else:
            style.theme_use("clam")
    except Exception:
        pass

    base_font = ("Microsoft YaHei UI", 9)
    for widget in ("TLabel", "TButton", "TEntry", "TCheckbutton", "TRadiobutton",
                   "TCombobox", "TSpinbox", "TLabelframe.Label", "TNotebook.Tab",
                   "Treeview"):
        try:
            style.configure(widget, font=base_font)
        except Exception:
            pass
    try:
        # 标题与提示
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 12, "bold"),
                        foreground="#0C447C")
        style.configure("Hint.TLabel", font=("Microsoft YaHei UI", 8),
                        foreground="#7A7A78")
        # 分区框：蓝色标题 + 细边框
        style.configure("TLabelframe.Label", font=("Microsoft YaHei UI", 9, "bold"),
                        foreground="#185FA5")
        style.configure("TLabelframe", borderwidth=1, relief="solid",
                        bordercolor="#D8DEE6")
        # 主按钮（执行类操作）
        style.configure("Primary.TButton", font=("Microsoft YaHei UI", 9, "bold"),
                        padding=(14, 5))
        # 标签页留白
        style.configure("TNotebook.Tab", padding=(14, 6))
        # 输入框内边距
        style.configure("TEntry", padding=(4, 3))
        style.configure("TCombobox", padding=(4, 3))
        style.configure("TSpinbox", padding=(4, 3))
        # 复选/单选项间距
        style.configure("TCheckbutton", padding=(2, 2))
    except Exception:
        pass


class LabeledEntry(ttk.Frame):
    """标签 + 输入框（可带单位说明）"""

    def __init__(self, master, label, width=28, show=None, hint="", **kw):
        super().__init__(master, **kw)
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=label, width=16, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=3)
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=width, show=show)
        self.entry.grid(row=0, column=1, sticky="ew", pady=3)
        if hint:
            ttk.Label(self, text=hint, style="Hint.TLabel").grid(
                row=0, column=2, sticky="w", padx=(6, 0))
        self.columnconfigure(1, weight=1)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value):
        self.var.set("" if value is None else str(value))


class LabeledCombo(ttk.Frame):
    """标签 + 下拉框"""

    def __init__(self, master, label, values, width=26, **kw):
        super().__init__(master, **kw)
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=label, width=16, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=3)
        self.var = tk.StringVar()
        self.combo = ttk.Combobox(self, textvariable=self.var, width=width,
                                  values=values, state="readonly")
        self.combo.grid(row=0, column=1, sticky="w", pady=3)
        self.columnconfigure(1, weight=1)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value):
        self.var.set("" if value is None else str(value))


class LabeledSpin(ttk.Frame):
    """标签 + 数字输入框"""

    def __init__(self, master, label, from_=0, to=9999, width=8, hint="", **kw):
        super().__init__(master, **kw)
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=label, width=16, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=3)
        self.var = tk.IntVar(value=from_)
        self.spin = ttk.Spinbox(self, textvariable=self.var, from_=from_, to=to,
                                width=width)
        self.spin.grid(row=0, column=1, sticky="w", pady=3)
        if hint:
            ttk.Label(self, text=hint, style="Hint.TLabel").grid(
                row=0, column=2, sticky="w", padx=(6, 0))
        self.columnconfigure(1, weight=1)

    def get(self) -> int:
        try:
            return int(self.var.get())
        except (ValueError, tk.TclError):
            return 0

    def set(self, value):
        try:
            self.var.set(int(value))
        except (ValueError, tk.TclError):
            self.var.set(0)


class LabeledCheck(ttk.Frame):
    """标签 + 复选框"""

    def __init__(self, master, label, **kw):
        super().__init__(master, **kw)
        self.var = tk.BooleanVar(value=False)
        self.check = ttk.Checkbutton(self, text=label, variable=self.var)
        self.check.grid(row=0, column=0, sticky="w", pady=3)

    def get(self) -> bool:
        return bool(self.var.get())

    def set(self, value):
        self.var.set(bool(value))


class PathEntry(ttk.Frame):
    """标签 + 路径输入框 + 浏览按钮（支持 on_change 回调）"""

    def __init__(self, master, label, hint="", on_change=None, **kw):
        super().__init__(master, **kw)
        self.on_change = on_change
        self.columnconfigure(1, weight=1)
        ttk.Label(self, text=label, width=16, anchor="e").grid(
            row=0, column=0, sticky="e", padx=(0, 6), pady=3)
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var)
        self.entry.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Button(self, text="浏览...", width=8,
                   command=self._browse).grid(row=0, column=2, padx=(6, 0))
        if hint:
            ttk.Label(self, text=hint, style="Hint.TLabel").grid(
                row=1, column=1, sticky="w")
        self.columnconfigure(1, weight=1)
        self.var.trace_add("write", self._on_var_change)

    def _on_var_change(self, *args):
        if self.on_change:
            try:
                self.on_change()
            except Exception:
                pass

    def _browse(self):
        path = filedialog.askdirectory(parent=self)
        if path:
            self.var.set(path)

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value):
        self.var.set("" if value is None else str(value))


class ScrollableFrame(ttk.Frame):
    """可垂直滚动的框架"""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vsb.pack(side="right", fill="y")
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _bind_mousewheel(self, _):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_mousewheel(self, _):
        self.canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


def show_info(parent, title, message):
    messagebox.showinfo(title, message, parent=parent)


def show_error(parent, title, message):
    messagebox.showerror(title, message, parent=parent)


def show_warning(parent, title, message):
    messagebox.showwarning(title, message, parent=parent)


def confirm(parent, title, message) -> bool:
    return messagebox.askyesno(title, message, parent=parent)


def open_path(path: str):
    """用资源管理器打开路径"""
    if not path or not os.path.exists(path):
        return False
    try:
        os.startfile(path)  # noqa: Windows only
        return True
    except Exception:
        return False

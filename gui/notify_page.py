# -*- coding: utf-8 -*-
"""通知配置页面：PushPlus、邮件、钉钉机器人"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from . import widgets as W


class NotifyPage:
    def __init__(self, parent, app):
        self.app = app
        self.frame = ttk.Frame(parent)
        self._build()

    def _build(self):
        outer = W.ScrollableFrame(self.frame)
        outer.pack(fill="both", expand=True, padx=8, pady=8)
        f = outer.inner
        row = 0

        def section(title, hint=""):
            nonlocal row
            box = ttk.LabelFrame(f, text=title)
            box.grid(row=row, column=0, sticky="ew", pady=(4, 8), padx=2)
            box.columnconfigure(1, weight=1)
            row += 1
            if hint:
                ttk.Label(box, text=hint, style="Hint.TLabel").grid(
                    row=99, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))
            return box

        # ---------- PushPlus ----------
        box = section("PushPlus（推送加）", "在 pushplus.plus 官网登录后复制 Token 即可")
        self.pp_enabled = W.LabeledCheck(box, "启用 PushPlus")
        self.pp_enabled.grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.pp_token = W.LabeledEntry(box, "Token", width=36)
        self.pp_token.grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.pp_topic = W.LabeledEntry(box, "群组编码(可选)", width=20)
        self.pp_topic.grid(row=1, column=1, sticky="w", padx=8, pady=4)

        # ---------- 邮件 ----------
        box = section("邮件通知（SMTP）", "支持 SSL/TLS，如 QQ 邮箱需使用授权码而非登录密码")
        self.mail_enabled = W.LabeledCheck(box, "启用邮件通知")
        self.mail_enabled.grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.mail_smtp = W.LabeledEntry(box, "SMTP 服务器", width=24)
        self.mail_smtp.grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.mail_port = W.LabeledSpin(box, "端口", from_=1, to=65535, width=8)
        self.mail_port.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        self.mail_ssl = W.LabeledCheck(box, "使用 SSL")
        self.mail_ssl.grid(row=1, column=2, sticky="w", padx=8, pady=4)
        self.mail_user = W.LabeledEntry(box, "登录账号", width=24)
        self.mail_user.grid(row=2, column=0, sticky="w", padx=8, pady=4)
        self.mail_password = W.LabeledEntry(box, "密码/授权码", width=24, show="*")
        self.mail_password.grid(row=2, column=1, sticky="w", padx=8, pady=4)
        self.mail_from = W.LabeledEntry(box, "发件人", width=24)
        self.mail_from.grid(row=3, column=0, sticky="w", padx=8, pady=4)
        self.mail_to = W.LabeledEntry(box, "收件人", width=24,
                                      hint="多个收件人用逗号分隔")
        self.mail_to.grid(row=3, column=1, sticky="w", padx=8, pady=4)

        # ---------- 钉钉 ----------
        box = section("钉钉机器人", "群设置 → 智能群助手 → 添加机器人 → Custom 机器人，"
                                   "安全设置推荐选“加签”")
        self.dt_enabled = W.LabeledCheck(box, "启用钉钉机器人")
        self.dt_enabled.grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.dt_webhook = W.LabeledEntry(box, "Webhook 地址", width=46)
        self.dt_webhook.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        self.dt_secret = W.LabeledEntry(box, "加签密钥", width=36,
                                        hint="SEC 开头的密钥，未设置加签可留空")
        self.dt_secret.grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=4)

        # ---------- 测试 ----------
        ttk.Button(f, text="发送测试通知", command=self._test_notify
                   ).grid(row=row, column=0, sticky="w", padx=12, pady=10)

    # ------------------------------------------------------------ 数据
    def load(self, cfg: dict):
        n = cfg.get("notify", {})
        pp = n.get("pushplus", {})
        self.pp_enabled.set(pp.get("enabled", False))
        self.pp_token.set(pp.get("token", ""))
        self.pp_topic.set(pp.get("topic", ""))
        m = n.get("email", {})
        self.mail_enabled.set(m.get("enabled", False))
        self.mail_smtp.set(m.get("smtp", "smtp.qq.com"))
        self.mail_port.set(m.get("port", 465))
        self.mail_ssl.set(m.get("ssl", True))
        self.mail_user.set(m.get("user", ""))
        self.mail_password.set(m.get("password", ""))
        self.mail_from.set(m.get("from_addr", ""))
        self.mail_to.set(m.get("to_addr", ""))
        d = n.get("dingtalk", {})
        self.dt_enabled.set(d.get("enabled", False))
        self.dt_webhook.set(d.get("webhook", ""))
        self.dt_secret.set(d.get("secret", ""))

    def collect(self, cfg: dict):
        n = cfg.setdefault("notify", {})
        n["pushplus"] = {
            "enabled": self.pp_enabled.get(),
            "token": self.pp_token.get(),
            "topic": self.pp_topic.get(),
        }
        n["email"] = {
            "enabled": self.mail_enabled.get(),
            "smtp": self.mail_smtp.get(),
            "port": self.mail_port.get(),
            "ssl": self.mail_ssl.get(),
            "user": self.mail_user.get(),
            "password": self.mail_password.get(),
            "from_addr": self.mail_from.get(),
            "to_addr": self.mail_to.get(),
        }
        n["dingtalk"] = {
            "enabled": self.dt_enabled.get(),
            "webhook": self.dt_webhook.get(),
            "secret": self.dt_secret.get(),
        }
        return cfg

    # ------------------------------------------------------------ 测试
    def _test_notify(self):
        self.app.save_config(silent=True)
        cfg = self.app.cfg
        self.app.set_status("正在发送测试通知...")

        def _do():
            try:
                from app.notify import Notifier
                notifier = Notifier(cfg.get("notify", {}))
                outcomes = notifier.send_test(cfg)
                if not outcomes:
                    msg = "没有启用任何通知渠道，请先勾选启用。"
                else:
                    lines = []
                    for channel, (ok, detail) in outcomes.items():
                        lines.append("%s：%s（%s）" % (
                            channel, "成功" if ok else "失败", detail))
                    msg = "\n".join(lines)
                self.app.on_ui(lambda: (
                    W.show_info(self.frame, "测试通知", msg),
                    self.app.set_status("就绪"),
                ))
            except Exception as exc:
                self.app.on_ui(lambda: (
                    W.show_error(self.frame, "测试通知失败", str(exc)),
                    self.app.set_status("就绪"),
                ))

        threading.Thread(target=_do, daemon=True).start()

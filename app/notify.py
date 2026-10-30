# -*- coding: utf-8 -*-
"""通知模块：PushPlus（推送加）、邮件（SMTP）、钉钉机器人"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import smtplib
import time
import urllib.parse
import urllib.request
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from .logger import log_error, log_info
from .utils import format_duration, format_size, now_str

USER_AGENT = "OracleBackup/1.0"


def build_message(result, cfg: dict) -> tuple:
    """根据备份结果生成 (标题, 内容)。成功/失败/有异常使用不同文案"""
    school = cfg.get("school_name", "") or "未知学校"
    srv = cfg.get("server", {})
    warnings = getattr(result, "warnings", None) or []
    if result.success:
        if warnings:
            title = "【%s】Oracle备份有异常 %s" % (school, result.started_at[:10])
            head = "⚠ Oracle 数据库备份完成，但有异常需要关注"
        else:
            title = "【%s】Oracle备份成功 %s" % (school, result.started_at[:10])
            head = "✅ Oracle 数据库备份成功"
        if getattr(result, "mode", "combined") == "per_schema" and result.files:
            file_lines = ["  %s：%s" % (f["schema"], format_size(f["size"]))
                          for f in result.files]
            file_text = "\n".join(file_lines)
            file_line = "📦 备份文件（%d 个用户）：\n%s" % (len(result.files), file_text)
            if result.failed_schemas:
                file_line += "\n⚠ 失败用户：%s" % ", ".join(result.failed_schemas)
        else:
            file_line = "📦 备份文件：%s" % result.filename
        lines = [
            head,
            "━━━━━━━━━━━━━━━━",
            "🏫 学校名称：%s" % school,
            "🖥 服务器：%s (%s)" % (srv.get("host", ""), srv.get("db_connect", "")),
            "📅 备份日期：%s" % result.started_at,
            file_line,
            "📏 文件大小：%s" % format_size(result.size),
            "⏱ 备份耗时：%s" % format_duration(result.duration),
            "💾 服务器磁盘剩余：%s（%s）" % (
                format_size(result.server_disk_free), result.server_dump_dir),
            "💻 本地磁盘剩余：%s（%s）" % (
                format_size(result.local_disk_free), result.local_path),
        ]
        if warnings:
            lines.append("")
            lines.append("⚠ 异常记录（%d 条）：" % len(warnings))
            for w in warnings[:10]:
                lines.append("  · %s" % w)
            if len(warnings) > 10:
                lines.append("  …（其余见运行日志）")
    else:
        title = "【%s】Oracle备份失败 %s" % (school, result.started_at[:10])
        lines = [
            "❌ Oracle 数据库备份失败",
            "━━━━━━━━━━━━━━━━",
            "🏫 学校名称：%s" % school,
            "🖥 服务器：%s (%s)" % (srv.get("host", ""), srv.get("db_connect", "")),
            "📅 备份日期：%s" % result.started_at,
            "⏱ 耗时：%s" % format_duration(result.duration),
            "❗ 错误信息：%s" % (result.error or "未知错误"),
        ]
        if warnings:
            lines.append("")
            lines.append("⚠ 异常记录（%d 条）：" % len(warnings))
            for w in warnings[:10]:
                lines.append("  · %s" % w)
            if len(warnings) > 10:
                lines.append("  …（其余见运行日志）")
    return title, "\n".join(lines)


def build_markdown(result, cfg: dict) -> str:
    """钉钉 markdown 格式"""
    school = cfg.get("school_name", "") or "未知学校"
    srv = cfg.get("server", {})
    warnings = getattr(result, "warnings", None) or []
    if result.success:
        if warnings:
            head = "⚠ <b>Oracle 数据库备份完成，但有异常需要关注</b>"
        else:
            head = "✅ <b>Oracle 数据库备份成功</b>"
        if getattr(result, "mode", "combined") == "per_schema" and result.files:
            file_text = "\n\n".join(
                "  %s：%s" % (f["schema"], format_size(f["size"]))
                for f in result.files)
            file_line = "📦 备份文件（%d 个用户）：\n\n%s" % (len(result.files), file_text)
        else:
            file_line = "📦 备份文件：%s" % result.filename
        body = (
            "🏫 学校名称：%s\n\n"
            "🖥 服务器：%s（%s）\n\n"
            "📅 备份日期：%s\n\n"
            "%s\n\n"
            "📏 文件大小：%s\n\n"
            "⏱ 备份耗时：%s\n\n"
            "💾 服务器磁盘剩余：%s\n\n"
            "💻 本地磁盘剩余：%s"
        ) % (
            school, srv.get("host", ""), srv.get("db_connect", ""),
            result.started_at, file_line, format_size(result.size),
            format_duration(result.duration), format_size(result.server_disk_free),
            format_size(result.local_disk_free),
        )
        if warnings:
            body += "\n\n⚠ 异常记录：\n\n" + "\n\n".join(
                "· %s" % w for w in warnings[:10])
    else:
        head = "❌ <b>Oracle 数据库备份失败</b>"
        body = (
            "🏫 学校名称：%s\n\n"
            "🖥 服务器：%s（%s）\n\n"
            "📅 备份日期：%s\n\n"
            "❗ 错误信息：%s"
        ) % (school, srv.get("host", ""), srv.get("db_connect", ""),
             result.started_at, result.error or "未知错误")
        if warnings:
            body += "\n\n⚠ 异常记录：\n\n" + "\n\n".join(
                "· %s" % w for w in warnings[:10])
    return head + "\n\n" + body


def _post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(body)
    except Exception:
        return {"raw": body}


class Notifier:
    """按配置向多个渠道发送通知"""

    def __init__(self, notify_cfg: dict, on_success: bool = True,
                 on_failure: bool = True, on_warning: bool = True):
        self.cfg = notify_cfg or {}
        self.on_success = on_success
        self.on_failure = on_failure
        self.on_warning = on_warning

    # ------------------------------------------------------------ 公共入口
    def send(self, result, cfg: dict) -> dict:
        """发送通知，返回 {渠道: (是否成功, 说明)}。
        三种情况：成功 / 失败 / 成功但有异常（部分失败、空间偏小等）"""
        has_warning = bool(getattr(result, "warnings", None))
        if result.success:
            if has_warning and not self.on_warning:
                return {}
            if not has_warning and not self.on_success:
                return {}
        else:
            if not self.on_failure:
                return {}
        title, content = build_message(result, cfg)
        results = {}
        if self.cfg.get("pushplus", {}).get("enabled"):
            results["PushPlus"] = self._send_pushplus(title, content)
        if self.cfg.get("email", {}).get("enabled"):
            results["邮件"] = self._send_email(title, content)
        if self.cfg.get("dingtalk", {}).get("enabled"):
            results["钉钉"] = self._send_dingtalk(result, cfg)
        return results

    def send_test(self, cfg: dict) -> dict:
        """发送测试通知（不依赖备份结果）"""
        from .backup import BackupResult
        now = now_str()
        result = BackupResult(
            success=True, started_at=now, finished_at=now, duration=65,
            size=1024 ** 3, filename="测试文件.tar.gz",
            local_file="", server_disk_free=50 * 1024 ** 3,
            local_disk_free=120 * 1024 ** 3,
            server_dump_dir=cfg.get("server", {}).get("dump_dir", ""),
            local_path=cfg.get("backup", {}).get("local_path", ""),
        )
        return self.send(result, cfg)

    # ------------------------------------------------------------ PushPlus
    def _send_pushplus(self, title: str, content: str):
        conf = self.cfg.get("pushplus", {})
        token = (conf.get("token") or "").strip()
        if not token:
            return (False, "未配置 PushPlus Token")
        try:
            html = content.replace("\n", "<br>")
            payload = {
                "token": token,
                "title": title,
                "content": html,
                "template": "html",
            }
            topic = (conf.get("topic") or "").strip()
            if topic:
                payload["topic"] = topic
            resp = _post_json("http://www.pushplus.plus/send", payload)
            if resp.get("code") == 200:
                log_info("PushPlus 通知发送成功")
                return (True, "发送成功")
            return (False, "PushPlus 返回：%s" % resp.get("msg", resp))
        except Exception as exc:
            log_error("PushPlus 通知发送失败：%s" % exc)
            return (False, str(exc))

    # ------------------------------------------------------------ 邮件
    def _send_email(self, title: str, content: str):
        conf = self.cfg.get("email", {})
        try:
            msg = MIMEText(content, "plain", "utf-8")
            msg["Subject"] = Header(title, "utf-8")
            from_addr = (conf.get("from_addr") or conf.get("user") or "").strip()
            msg["From"] = formataddr(("Oracle备份", from_addr))
            msg["To"] = (conf.get("to_addr") or "").strip()
            if not msg["To"]:
                return (False, "未配置收件人")

            if conf.get("ssl"):
                server = smtplib.SMTP_SSL(conf.get("smtp"), int(conf.get("port") or 465), timeout=30)
            else:
                server = smtplib.SMTP(conf.get("smtp"), int(conf.get("port") or 25), timeout=30)
                server.starttls()
            server.login(conf.get("user"), conf.get("password"))
            server.sendmail(from_addr, [msg["To"]], msg.as_string())
            server.quit()
            log_info("邮件通知发送成功：%s" % msg["To"])
            return (True, "发送成功")
        except Exception as exc:
            log_error("邮件通知发送失败：%s" % exc)
            return (False, str(exc))

    # ------------------------------------------------------------ 钉钉
    def _send_dingtalk(self, result, cfg: dict):
        conf = self.cfg.get("dingtalk", {})
        webhook = (conf.get("webhook") or "").strip()
        if not webhook:
            return (False, "未配置钉钉 Webhook")
        try:
            url = webhook
            secret = (conf.get("secret") or "").strip()
            if secret:
                timestamp = str(int(round(time.time() * 1000)))
                string_to_sign = "%s\n%s" % (timestamp, secret)
                hmac_code = hmac.new(
                    secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                    digestmod=hashlib.sha256,
                ).digest()
                sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode("utf-8"))
                sep = "&" if "?" in url else "?"
                url = "%s%stimestamp=%s&sign=%s" % (url, sep, timestamp, sign)
            school = cfg.get("school_name", "") or "备份通知"
            markdown = build_markdown(result, cfg)
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": "【%s】Oracle备份%s" % (
                        school, "成功" if result.success else "失败"),
                    "text": markdown,
                },
            }
            resp = _post_json(url, payload)
            if resp.get("errcode") == 0:
                log_info("钉钉通知发送成功")
                return (True, "发送成功")
            return (False, "钉钉返回：%s" % resp.get("errmsg", resp))
        except Exception as exc:
            log_error("钉钉通知发送失败：%s" % exc)
            return (False, str(exc))

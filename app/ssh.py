# -*- coding: utf-8 -*-
"""SSH/SFTP 连接管理（基于 paramiko）"""
from __future__ import annotations

import select
import socket
import time

import paramiko

from .logger import log_error, log_info


class BackupCancelled(Exception):
    """用户取消备份"""


class SSHError(Exception):
    pass


class SSHConnection:
    """对 paramiko 的封装：连接、执行命令（支持流式输出）、sftp 上传下载"""

    def __init__(self, server_cfg: dict):
        self.cfg = server_cfg
        self.client = None

    # ------------------------------------------------------------------ 连接
    def connect(self, timeout: int = 15):
        cfg = self.cfg
        host = cfg.get("host", "").strip()
        port = int(cfg.get("port") or 22)
        user = cfg.get("ssh_user", "").strip()
        if not host or not user:
            raise SSHError("服务器地址或登录用户不能为空")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            if cfg.get("auth_type") == "key":
                key_file = (cfg.get("key_file") or "").strip()
                if not key_file:
                    raise SSHError("使用密钥认证时必须选择密钥文件")
                client.connect(
                    hostname=host,
                    port=port,
                    username=user,
                    key_filename=key_file,
                    passphrase=cfg.get("key_passphrase") or None,
                    timeout=timeout,
                    banner_timeout=timeout,
                    auth_timeout=timeout,
                )
            else:
                client.connect(
                    hostname=host,
                    port=port,
                    username=user,
                    password=cfg.get("password") or "",
                    timeout=timeout,
                    banner_timeout=timeout,
                    auth_timeout=timeout,
                    allow_agent=False,
                    look_for_keys=False,
                )
        except paramiko.AuthenticationException:
            raise SSHError("SSH 认证失败：用户名或密码/密钥错误")
        except socket.timeout:
            raise SSHError("连接超时：请检查服务器地址、端口及网络")
        except Exception as exc:
            raise SSHError("SSH 连接失败：%s" % exc)
        self.client = client
        log_info("SSH 连接成功：%s@%s:%s" % (user, host, port))
        return client

    def close(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    # -------------------------------------------------------------- 执行命令
    def run(self, command: str, timeout: int = 7200, sudo_password: str = None,
            stream=None) -> int:
        """
        执行命令并返回退出码。
        stream: 可选回调 stream(line)，用于实时输出（stdout+stderr 合并）。
        """
        if self.client is None:
            raise SSHError("尚未建立 SSH 连接")
        transport = self.client.get_transport()
        if transport is None or not transport.is_active():
            raise SSHError("SSH 连接已断开")
        chan = transport.open_session()
        chan.settimeout(None)
        chan.exec_command(command)
        if sudo_password:
            time.sleep(0.3)
            try:
                chan.sendall(sudo_password + "\n")
            except Exception:
                pass

        buf_out, buf_err = [], []
        pending = ""          # 尚未流式输出的残留文本（可能含不完整的行）
        start = time.time()
        last_stream = time.time()

        def _flush(final: bool = False):
            """把 pending 中的完整行推送给 stream；final=True 时连同不完整的末行一起输出。
            节流间隔 0.5s：既能实时看到进度，又不会用高频回调拖垮 GUI 线程。"""
            nonlocal pending, last_stream
            if not stream or not pending:
                return
            if not final and (time.time() - last_stream) <= 0.5:
                return
            lines = pending.split("\n")
            remainder = "" if final else lines.pop()
            for line in lines:
                if line.strip():
                    stream(line)
            pending = remainder
            last_stream = time.time()

        while True:
            if timeout and (time.time() - start) > timeout:
                chan.close()
                raise SSHError("命令执行超时（超过 %d 秒）" % timeout)
            readable, _, _ = select.select([chan], [], [], 0.5)
            if chan in readable:
                if chan.recv_ready():
                    data = chan.recv(65536)
                    if data:
                        text = data.decode("utf-8", "replace")
                        buf_out.append(text)
                        pending += text
                        _flush()
                if chan.recv_stderr_ready():
                    data = chan.recv_stderr(65536)
                    if data:
                        text = data.decode("utf-8", "replace")
                        buf_err.append(text)
                        pending += text
                        _flush()
                if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                    break
            if chan.eof_received and not chan.recv_ready() and not chan.recv_stderr_ready():
                break
        status = chan.recv_exit_status()
        chan.close()
        # 刷新残留输出，确保结果标记等末尾内容不丢失
        _flush(final=True)
        if status != 0 and "".join(buf_err).strip():
            log_error("命令 %s 输出错误：%s" % (command[:60], "".join(buf_err)[:500]))
        return status

    def output_of(self, command: str, timeout: int = 120, sudo_password: str = None) -> str:
        """执行命令并返回完整输出文本"""
        if self.client is None:
            raise SSHError("尚未建立 SSH 连接")
        stdin, stdout, stderr = self.client.exec_command(
            command, timeout=timeout
        )
        if sudo_password:
            time.sleep(0.2)
            try:
                stdin.write(sudo_password + "\n")
                stdin.flush()
            except Exception:
                pass
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        return out + (("\n[stderr]\n" + err) if err.strip() else "")

    # -------------------------------------------------------------- SFTP
    def _sftp(self):
        if self.client is None:
            raise SSHError("尚未建立 SSH 连接")
        return self.client.open_sftp()

    def put_file(self, local_path: str, remote_path: str, progress=None):
        sftp = self._sftp()
        try:
            sftp.put(local_path, remote_path)
            if progress:
                progress(1.0)
        finally:
            sftp.close()

    def get_file(self, remote_path: str, local_path: str, progress=None,
                 cancel_check=None):
        """下载文件；progress(done, total)；cancel_check() 返回 True 时中断。
        使用 4MB 大块读取提升大文件下载速度。"""
        sftp = self._sftp()
        try:
            st = sftp.stat(remote_path)
            total = st.st_size if st else 0
            with sftp.open(remote_path, "rb") as rf:
                with open(local_path, "wb") as wf:
                    done = 0
                    last_report = 0.0
                    while True:
                        if cancel_check and cancel_check():
                            raise BackupCancelled("下载已取消")
                        chunk = rf.read(4 * 1024 * 1024)
                        if not chunk:
                            break
                        wf.write(chunk)
                        done += len(chunk)
                        now = time.time()
                        if progress and now - last_report > 0.5:
                            progress(done, total)
                            last_report = now
                    if progress:
                        progress(done, total)
            return total
        finally:
            sftp.close()

    def chmod(self, remote_path: str, mode: int = 0o755):
        sftp = self._sftp()
        try:
            sftp.chmod(remote_path, mode)
        finally:
            sftp.close()

    def stat_size(self, remote_path: str) -> int:
        sftp = self._sftp()
        try:
            return sftp.stat(remote_path).st_size
        finally:
            sftp.close()

# -*- coding: utf-8 -*-
"""备份流程编排：连接服务器 → 执行导出脚本 → 下载 → 本地清理 → 通知"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from dataclasses import dataclass, field

from . import cleanup as cleanup_mod
from . import notify as notify_mod
from . import oracle
from .logger import log_error, log_info, log_warning
from .ssh import BackupCancelled, SSHError, SSHConnection
from .utils import disk_free_bytes, format_duration, format_size, now_str, timestamp_tag


@dataclass
class BackupResult:
    success: bool = False
    started_at: str = ""
    finished_at: str = ""
    duration: float = 0.0
    size: int = 0
    filename: str = ""
    local_file: str = ""
    server_disk_free: int = 0
    server_dump_dir: str = ""
    local_disk_free: int = 0
    local_path: str = ""
    error: str = ""
    deleted_remote: list = field(default_factory=list)
    deleted_local: list = field(default_factory=list)
    mode: str = "combined"                 # combined=单包 / per_schema=按用户分包
    files: list = field(default_factory=list)      # 分包模式：[{schema,filename,size,local_file}]
    failed_schemas: list = field(default_factory=list)
    warnings: list = field(default_factory=list)   # 异常记录（空间偏小、部分失败等）


class BackupRunner:
    """执行一次完整备份流程"""

    def __init__(self, cfg: dict, on_log=None, on_progress=None,
                 cancel_event: threading.Event = None):
        self.cfg = cfg
        self.on_log = on_log
        self.on_progress = on_progress
        self.cancel_event = cancel_event or threading.Event()
        self.result = BackupResult()
        self._warnings = []      # 本次运行的异常记录（WARNING 级日志）

    # ------------------------------------------------------------ 内部工具
    def _log(self, message: str, level: str = "INFO"):
        # WARNING 级日志同时记入异常清单，备份结束后用于判断是否发异常通知
        if level == "WARNING" and message not in self._warnings:
            self._warnings.append(message)
        if self.on_log:
            try:
                self.on_log(level, message)
            except Exception:
                pass
        else:
            from .logger import log
            log(level, message)

    def _check_cancel(self):
        if self.cancel_event.is_set():
            raise BackupCancelled("备份已被用户取消")

    # ------------------------------------------------------------ 目录预处理
    def _probe_directory(self, ssh, srv) -> str:
        """探测目录对象真实路径（失败返回空串）"""
        try:
            return oracle.query_directory_path(
                ssh, srv, srv.get("directory_name")) or ""
        except Exception as exc:
            self._log("目录对象探测失败（将使用配置的导出目录）：%s" % exc, "WARNING")
            return ""

    def _ensure_remote_dirs(self, ssh, srv, paths):
        """root 登录时，提前在服务器上创建导出目录并授权给 oracle 用户。
        expdp 以 oracle 用户运行，通常无权在 /opt、/ 等路径下建目录。
        安全限制：绝不自动创建根分区关键路径（/、/ade、/root 等下的目录）。"""
        if (srv.get("ssh_user") or "").strip() != "root":
            return
        oracle_user = (srv.get("oracle_user") or "oracle").strip()
        if not oracle_user:
            return
        group = ""
        try:
            group = ssh.output_of(
                "id -gn %s 2>/dev/null" % oracle.shell_quote(oracle_user),
                timeout=15).strip()
        except Exception:
            pass
        owner = "%s:%s" % (oracle_user, group) if group else oracle_user
        seen = set()
        for path in paths:
            path = (path or "").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            # 危险路径保护：不自动创建（避免误把 dump 写进根分区）
            if not oracle.is_safe_backup_dir("", path):
                self._log("跳过自动创建目录 %s（位于根分区或危险路径，请改选其他目录对象）"
                          % path, "WARNING")
                continue
            try:
                ssh.run(
                    "mkdir -p %s && chown %s %s" % (
                        oracle.shell_quote(path),
                        oracle.shell_quote(owner),
                        oracle.shell_quote(path)),
                    timeout=60)
                self._log("已确保服务器目录存在并可写：%s（属主 %s）" % (path, owner))
            except Exception as exc:
                self._log("预创建目录 %s 失败（脚本内仍会尝试）：%s"
                          % (path, exc), "WARNING")

    # ------------------------------------------------------------ 空间预检
    def _preflight_space_check(self, ssh, srv, work_dir: str,
                               schema_sizes: dict = None):
        """备份前空间预检：估算所选用户的未压缩数据量，与目标目录剩余空间对比。
        目标在根分区/内存盘(tmpfs)或空间不足时直接中止——
        避免导出一半把磁盘写满（曾把根分区写满、内存盘写爆）。"""
        try:
            if schema_sizes is None:
                schemas = self.cfg.get("backup", {}).get("schemas") or []
                schema_sizes = oracle.estimate_schema_sizes(ssh, srv, schemas)
            sizes = schema_sizes
            out = ssh.output_of(
                "df -PTk %s 2>/dev/null | awk 'NR==2{print $2, $4, $7}'"
                % oracle.shell_quote(work_dir), timeout=30)
            parts = out.split()
            if len(parts) < 3 or not parts[1].isdigit():
                return
            fs_type = parts[0]
            free = int(parts[1]) * 1024
            mount = parts[2]
            if not sizes:
                self._log("空间预检：目标 %s 位于 %s 分区（%s），剩余 %s（未能估算数据量，跳过对比）"
                          % (work_dir, mount, fs_type, format_size(free)))
            else:
                # expdp 先写未压缩 dmp（约 1.0~1.2 倍数据量），tar.gz 只是最终产物
                need = int(sum(sizes.values()) * 1.2)
                self._log("空间预检：%d 个用户约 %s（未压缩，按 1.2 倍估需 %s）；"
                          "目标 %s 位于 %s 分区（%s），剩余 %s"
                          % (len(sizes), format_size(sum(sizes.values())),
                             format_size(need), work_dir, mount, fs_type,
                             format_size(free)))
                if free < need:
                    raise SSHError(
                        "磁盘空间不足，已中止备份（避免写满磁盘）。\n\n"
                        "导出约需：%s（未压缩）\n"
                        "%s 分区剩余：%s\n\n"
                        "处理方式：\n"
                        "1. 在「数据库服务器」页把目录对象改到空间充足的分区"
                        "（点「测试连接并检测环境」可看各目录剩余空间）\n"
                        "2. 或减少勾选的导出用户" % (
                            format_size(need), mount, format_size(free)))
                if free < need * 2:
                    self._log("警告：剩余空间偏小（需 %s / 剩 %s），请关注磁盘"
                              % (format_size(need), format_size(free)), "WARNING")
            if mount == "/":
                raise SSHError(
                    "导出目录 %s 位于根分区(/)，已中止备份。\n"
                    "根分区写满会导致系统故障，请把「目录对象名」改为指向独立分区"
                    "（如 /u01）的目录对象。" % work_dir)
            if fs_type == "tmpfs":
                raise SSHError(
                    "导出目录 %s 位于内存盘(tmpfs)，已中止备份。\n"
                    "往内存盘写导出文件会把服务器内存耗尽，请改用磁盘上的目录对象。"
                    % work_dir)
        except SSHError:
            raise
        except Exception as exc:
            self._log("空间预检跳过（查询失败）：%s" % exc, "WARNING")

    # ------------------------------------------------------------ 主流程
    def run(self) -> BackupResult:
        cfg = self.cfg
        srv = cfg.get("server", {})
        bak = cfg.get("backup", {})
        result = self.result
        result.started_at = now_str()
        result.local_path = bak.get("local_path", "")
        result.server_dump_dir = srv.get("dump_dir", "")
        started_ts = time.time()
        self._log("=" * 56)
        self._log("开始备份：%s" % result.started_at)
        self._log("目标服务器：%s，导出用户：%s" % (
            srv.get("host", ""), ",".join(bak.get("schemas") or []) or "（未勾选）"))

        ssh = None
        remote_path = None
        script_path = None
        probe_path = None
        try:
            self._check_cancel()
            # 1. 建立 SSH 连接
            ssh = SSHConnection(srv)
            ssh.connect()
            self._check_cancel()

            # 2. 探测目录对象真实路径，并以 root 身份预创建导出目录
            #    （oracle 用户通常无权在 /opt、/ 等路径下创建目录）
            probed_dir = self._probe_directory(ssh, srv)
            work_dir = probed_dir or (srv.get("dump_dir") or "").strip() or "/tmp"
            # 先估算各模式数据量：空间预检和并行度分配共用（只查一次）
            schemas = [s for s in (bak.get("schemas") or []) if s]
            schema_sizes = {}
            if schemas:
                try:
                    schema_sizes = oracle.estimate_schema_sizes(ssh, srv, schemas)
                except Exception as exc:
                    self._log("模式大小估算失败（将按固定并行度导出）：%s" % exc,
                              "WARNING")
            self._preflight_space_check(ssh, srv, work_dir, schema_sizes)
            self._ensure_remote_dirs(ssh, srv,
                                     [srv.get("dump_dir"), probed_dir])

            # 3. 生成并上传备份脚本 + 目录对象探测 SQL
            ts = timestamp_tag()
            script_text = oracle.build_backup_script(cfg, ts,
                                                     schema_sizes=schema_sizes)
            probe_sql = oracle.build_probe_sql(cfg, ts)
            fd, local_script = tempfile.mkstemp(suffix=".sh", prefix="orabackup_")
            # 必须用 newline="\n"：Windows 文本模式会把 \n 写成 \r\n，
            # 导致上传到 Linux 的脚本无法执行（bash 报 pipefail 无效等）
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(script_text)
            fd, local_probe = tempfile.mkstemp(suffix=".sql", prefix="orabackup_")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(probe_sql)
            remote_dir = "/tmp"
            script_path = "%s/.orabackup_%s.sh" % (remote_dir, ts)
            probe_path = oracle.probe_sql_path(ts)
            ssh.put_file(local_script, script_path)
            ssh.put_file(local_probe, probe_path)
            ssh.chmod(script_path, 0o755)
            os.remove(local_script)
            os.remove(local_probe)
            self._log("备份脚本已上传至服务器：%s" % script_path)

            # 3. 执行备份脚本（流式输出）
            use_sudo = ((srv.get("switch_method") or "auto").lower() in ("auto", "sudo")
                        and (srv.get("ssh_user") or "").strip()
                        != (srv.get("oracle_user") or "").strip()
                        and (srv.get("ssh_user") or "").strip() != "root")
            sudo_password = srv.get("sudo_password") if use_sudo else None
            cmd = oracle.build_run_command(srv, script_path)
            self._log("服务器开始执行导出与压缩，耗时较长请耐心等待...")

            output_lines = []

            def _stream(line: str):
                output_lines.append(line)
                self._log("[服务器] %s" % line)
                self._check_cancel()

            exit_code = ssh.run(cmd, timeout=6 * 3600, sudo_password=sudo_password,
                                stream=_stream)
            output_text = "\n".join(output_lines)

            if exit_code != 0:
                err = oracle.detect_expdp_error(output_text)
                tail = "\n".join(output_lines[-15:])
                result.error = err or ("服务器脚本执行失败（退出码 %d）：\n%s" % (exit_code, tail))
                result.success = False
                result.finished_at = now_str()
                result.duration = time.time() - started_ts
                self._log("备份失败：%s" % result.error, "ERROR")
                return self._finish(result)

            # 4. 解析结果标记
            markers = oracle.parse_result_markers(output_text)
            work_dir = markers.get("RESULT_WORKDIR") or srv.get("dump_dir", "")
            result.server_dump_dir = work_dir
            try:
                result.server_disk_free = int(markers.get("RESULT_DISKFREE_KB", "0")) * 1024
            except ValueError:
                result.server_disk_free = 0
            pack_mode = (bak.get("pack_mode") or "combined").lower()
            result.mode = pack_mode

            # 5. 下载到本地
            local_dir = bak.get("local_path", "").strip()
            if not local_dir:
                raise SSHError("未配置本地备份路径")
            os.makedirs(local_dir, exist_ok=True)

            def _progress(done, total):
                if self.on_progress:
                    try:
                        self.on_progress(done, total)
                    except Exception:
                        pass

            if pack_mode == "per_schema":
                # ---------- 按用户分包：逐文件下载 ----------
                schemas = [s for s in (bak.get("schemas") or []) if s]
                files = []
                failed = [s.strip() for s in
                          markers.get("RESULT_FAILED_LIST", "").split() if s.strip()]
                for schema in schemas:
                    fname = markers.get("RESULT_FILE_%s" % schema, "")
                    if not fname:
                        continue
                    fsize = 0
                    try:
                        fsize = int(markers.get("RESULT_SIZE_%s" % schema, "0"))
                    except ValueError:
                        pass
                    remote_path = "%s/%s" % (work_dir.rstrip("/"), fname)
                    local_file = os.path.join(local_dir, fname)
                    if os.path.exists(local_file):
                        os.remove(local_file)
                    self._log("开始下载 %s 的备份：%s（%s）" % (
                        schema, fname, format_size(fsize)))
                    downloaded = ssh.get_file(
                        remote_path, local_file, progress=_progress,
                        cancel_check=self.cancel_event.is_set)
                    if downloaded and not fsize:
                        fsize = downloaded
                    files.append({"schema": schema, "filename": fname,
                                  "size": fsize, "local_file": local_file})
                    self._log("已下载 %s：%s" % (schema, format_size(fsize)))
                result.files = files
                result.failed_schemas = failed
                result.size = sum(f["size"] for f in files)
                result.filename = "%d 个用户的备份（共 %s）" % (
                    len(files), format_size(result.size))
                result.local_file = local_dir
                if failed:
                    self._log("有 %d 个用户导出失败：%s" % (len(failed),
                                                              ", ".join(failed)),
                              "WARNING")
                self._log("按用户分包下载完成：%d 个成功，%d 个失败" % (
                    len(files), len(failed)))
            else:
                # ---------- 单包模式 ----------
                tar_name = markers.get("RESULT_FILE", "")
                if not tar_name:
                    result.error = "未能从服务器输出中解析到备份文件名"
                    result.success = False
                    result.finished_at = now_str()
                    result.duration = time.time() - started_ts
                    self._log(result.error, "ERROR")
                    return self._finish(result)
                remote_path = "%s/%s" % (work_dir.rstrip("/"), tar_name)
                result.filename = tar_name
                try:
                    result.size = int(markers.get("RESULT_SIZE", "0"))
                except ValueError:
                    result.size = 0
                local_file = os.path.join(local_dir, tar_name)
                if os.path.exists(local_file):
                    os.remove(local_file)
                self._log("开始下载备份文件到本地：%s" % local_dir)
                downloaded = ssh.get_file(remote_path, local_file,
                                          progress=_progress,
                                          cancel_check=self.cancel_event.is_set)
                if downloaded and not result.size:
                    result.size = downloaded
                result.local_file = local_file
                result.files = [{"schema": "全部", "filename": tar_name,
                                 "size": result.size, "local_file": local_file}]
                self._log("下载完成：%s（%s）" % (local_file, format_size(result.size)))

            # 6. 本地清理（超过保留天数）
            keep_days = int(bak.get("local_keep_days") or 0)
            result.deleted_local = cleanup_mod.cleanup_local_backups(local_dir, keep_days)
            for p in result.deleted_local:
                self._log("已删除本地历史备份：%s" % os.path.basename(p))

            # 7. 汇总
            result.local_disk_free = disk_free_bytes(local_dir)
            result.success = True
            result.finished_at = now_str()
            result.duration = time.time() - started_ts
            self._log("备份成功！%s，大小 %s，耗时 %s" % (
                result.filename, format_size(result.size),
                format_duration(result.duration)))
            self._log("本地磁盘剩余：%s" % format_size(result.local_disk_free))
            return self._finish(result)

        except BackupCancelled as exc:
            result.success = False
            result.error = str(exc)
            result.finished_at = now_str()
            result.duration = time.time() - started_ts
            self._log(str(exc), "WARNING")
            return self._finish(result, notify=False)
        except Exception as exc:
            result.success = False
            result.error = str(exc)
            result.finished_at = now_str()
            result.duration = time.time() - started_ts
            self._log("备份异常：%s" % exc, "ERROR")
            return self._finish(result)
        finally:
            # 清理服务器上的临时脚本与探测 SQL
            if ssh is not None:
                for tmp_file in (script_path, probe_path):
                    if tmp_file:
                        try:
                            ssh.run("rm -f %s" % oracle.shell_quote(tmp_file),
                                    timeout=30)
                        except Exception:
                            pass
                ssh.close()

    # ------------------------------------------------------------ 收尾
    def _finish(self, result: BackupResult, notify: bool = True) -> BackupResult:
        """发送通知（成功/失败/有异常三种情况）"""
        # 汇总异常记录：本次运行的 WARNING + 分包模式下的失败用户
        result.warnings = list(self._warnings)
        if result.success and result.failed_schemas:
            msg = "部分用户导出失败：%s" % ", ".join(result.failed_schemas)
            if msg not in result.warnings:
                result.warnings.append(msg)
        if notify:
            try:
                notify_cfg = self.cfg.get("notify", {})
                sys_cfg = self.cfg.get("system", {})
                notifier = notify_mod.Notifier(
                    notify_cfg,
                    on_success=bool(sys_cfg.get("notify_on_success", True)),
                    on_failure=bool(sys_cfg.get("notify_on_failure", True)),
                    on_warning=bool(sys_cfg.get("notify_on_warning", True)),
                )
                outcomes = notifier.send(result, self.cfg)
                for channel, (ok, msg) in outcomes.items():
                    self._log("通知[%s]：%s（%s）" % (
                        channel, "成功" if ok else "失败", msg),
                        "INFO" if ok else "WARNING")
            except Exception as exc:
                self._log("通知发送异常：%s" % exc, "ERROR")
        return result

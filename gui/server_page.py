# -*- coding: utf-8 -*-
"""服务器配置页面（紧凑布局，默认窗口宽度内完整显示）"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app import oracle
from app.logger import log_error, log_info
from app.ssh import SSHError, SSHConnection
from . import widgets as W


class ServerPage:
    """数据库服务器（Linux）连接与 Oracle 环境配置"""

    def __init__(self, parent, app):
        self.app = app
        self.frame = ttk.Frame(parent)
        self._build()

    # ------------------------------------------------------------ 界面
    def _build(self):
        outer = W.ScrollableFrame(self.frame)
        outer.pack(fill="both", expand=True, padx=8, pady=8)
        f = outer.inner
        f.columnconfigure(0, weight=1)

        self._row = 0

        def section(title, hint=""):
            box = ttk.LabelFrame(f, text=title)
            box.grid(row=self._row, column=0, sticky="ew", pady=(4, 8), padx=2)
            box.columnconfigure(1, weight=1)
            self._row += 1
            r = 0
            if hint:
                ttk.Label(box, text=hint, style="Hint.TLabel").grid(
                    row=r, column=0, columnspan=5, sticky="w", padx=10, pady=(4, 0))
                r += 1
            return box, r

        def label(box, r, c, text, w=14):
            ttk.Label(box, text=text, width=w, anchor="e").grid(
                row=r, column=c, sticky="e", padx=(10, 4), pady=3)

        def hint(box, r, c, text):
            ttk.Label(box, text=text, style="Hint.TLabel").grid(
                row=r, column=c, sticky="w", padx=(6, 0), pady=3)

        # ---------- 学校信息 ----------
        box, r = section("学校信息")
        label(box, r, 0, "学校名称")
        self.school = tk.StringVar()
        ttk.Entry(box, textvariable=self.school, width=36).grid(
            row=r, column=1, sticky="w", pady=3)
        hint(box, r, 2, "用于通知消息与备份文件名")

        # ---------- SSH 连接 ----------
        box, r = section("SSH 连接（Linux 数据库服务器）")
        label(box, r, 0, "服务器地址")
        self.host = tk.StringVar()
        ttk.Entry(box, textvariable=self.host, width=26).grid(
            row=r, column=1, sticky="w", pady=3)
        hint(box, r, 2, "IP 或域名")
        r += 1

        label(box, r, 0, "SSH 端口")
        self.port = tk.IntVar(value=22)
        ttk.Spinbox(box, textvariable=self.port, from_=1, to=65535,
                    width=8).grid(row=r, column=1, sticky="w", pady=3)
        label(box, r, 2, "登录用户", w=10)
        self.ssh_user = tk.StringVar()
        ttk.Entry(box, textvariable=self.ssh_user, width=18).grid(
            row=r, column=3, sticky="w", pady=3)
        r += 1

        label(box, r, 0, "认证方式")
        self.auth_type = tk.StringVar(value="password")
        ttk.Combobox(box, textvariable=self.auth_type, width=20, state="readonly",
                     values=["password", "key"]).grid(
            row=r, column=1, sticky="w", pady=3)
        label(box, r, 2, "登录密码", w=10)
        self.password = tk.StringVar()
        ttk.Entry(box, textvariable=self.password, width=22, show="*").grid(
            row=r, column=3, sticky="w", pady=3)
        r += 1

        label(box, r, 0, "密钥文件")
        self.key_file = tk.StringVar()
        ttk.Entry(box, textvariable=self.key_file, width=30).grid(
            row=r, column=1, sticky="w", pady=3)
        ttk.Button(box, text="浏览...", width=8,
                   command=self._browse_key).grid(row=r, column=2, padx=(6, 0))
        hint(box, r, 3, "仅密钥认证时需要")
        r += 1

        label(box, r, 0, "密钥口令")
        self.key_passphrase = tk.StringVar()
        ttk.Entry(box, textvariable=self.key_passphrase, width=20, show="*").grid(
            row=r, column=1, sticky="w", pady=3)
        r += 1

        # ---------- Oracle 环境 ----------
        box, r = section("Oracle 环境（服务器端）",
                         "工具在服务器上以 oracle 用户执行 expdp；root 登录时自动用 su 切换（不带横杠）")
        label(box, r, 0, "Oracle 运行用户")
        self.oracle_user = tk.StringVar()
        ttk.Entry(box, textvariable=self.oracle_user, width=18).grid(
            row=r, column=1, sticky="w", pady=3)
        hint(box, r, 2, "执行 expdp 的系统用户")
        label(box, r, 3, "用户切换方式", w=12)
        self.switch_var = tk.StringVar(value="auto")
        ttk.Combobox(box, textvariable=self.switch_var, width=16, state="readonly",
                     values=["auto", "direct", "su", "sudo"]).grid(
            row=r, column=4, sticky="w", pady=3)
        r += 1
        ttk.Label(box, text="auto=智能选择 / direct=直连 / su=root切换 / sudo=sudo切换",
                  style="Hint.TLabel").grid(row=r, column=1, columnspan=4,
                                            sticky="w", padx=(6, 0))
        r += 1

        label(box, r, 0, "sudo 密码")
        self.sudo_password = tk.StringVar()
        ttk.Entry(box, textvariable=self.sudo_password, width=20, show="*").grid(
            row=r, column=1, sticky="w", pady=3)
        hint(box, r, 2, "非 root 登录且需 sudo 时填写")
        r += 1

        label(box, r, 0, "ORACLE_HOME")
        self.oracle_home = tk.StringVar()
        ttk.Entry(box, textvariable=self.oracle_home, width=52).grid(
            row=r, column=1, columnspan=2, sticky="w", pady=3)
        hint(box, r, 3, "真实路径可用 cat /etc/oratab 查询")
        r += 1

        label(box, r, 0, "ORACLE_SID")
        self.oracle_sid = tk.StringVar()
        ttk.Entry(box, textvariable=self.oracle_sid, width=16).grid(
            row=r, column=1, sticky="w", pady=3)
        hint(box, r, 2, "实例名，如 zfdb")
        label(box, r, 3, "数据库连接名", w=12)
        self.db_connect = tk.StringVar()
        ttk.Entry(box, textvariable=self.db_connect, width=26).grid(
            row=r, column=4, sticky="w", pady=3)
        r += 1
        ttk.Label(box, text="连接名留空 = 本地 BEQ 连接（推荐，依赖 ORACLE_SID）；"
                            "或填 //localhost:1521/服务名",
                  style="Hint.TLabel").grid(row=r, column=1, columnspan=4,
                                            sticky="w", padx=(6, 0))
        r += 1

        label(box, r, 0, "导出用户")
        self.db_user = tk.StringVar()
        ttk.Entry(box, textvariable=self.db_user, width=18).grid(
            row=r, column=1, sticky="w", pady=3)
        hint(box, r, 2, "需有导出权限，如 system")
        label(box, r, 3, "导出密码", w=10)
        self.db_password = tk.StringVar()
        ttk.Entry(box, textvariable=self.db_password, width=22, show="*").grid(
            row=r, column=4, sticky="w", pady=3)
        r += 1

        label(box, r, 0, "NLS_LANG")
        self.nls_lang = tk.StringVar()
        ttk.Entry(box, textvariable=self.nls_lang, width=30).grid(
            row=r, column=1, sticky="w", pady=3)
        hint(box, r, 2, "中文库建议 AMERICAN_AMERICA.AL32UTF8")
        r += 1

        # ---------- 备份目录 ----------
        box, r = section("备份目录（服务器）",
                         "目录对象名与导出目录可在测试连接后自动填充；root 登录时会自动创建导出目录")
        label(box, r, 0, "目录对象名")
        self.dir_name_var = tk.StringVar()
        self.dir_combo = ttk.Combobox(box, textvariable=self.dir_name_var, width=24)
        self.dir_combo.grid(row=r, column=1, sticky="w", pady=3)
        hint(box, r, 2, "Oracle DIRECTORY 对象")
        r += 1

        label(box, r, 0, "导出目录(OS路径)")
        self.dump_dir_var = tk.StringVar()
        self.dump_combo = ttk.Combobox(box, textvariable=self.dump_dir_var, width=44)
        self.dump_combo.grid(row=r, column=1, columnspan=2, sticky="w", pady=3)
        hint(box, r, 3, "目录对象对应的服务器路径")
        r += 1

        ttk.Button(box, text="测试连接并检测环境", command=self._test_connection
                   ).grid(row=r, column=1, sticky="w", pady=(6, 8))
        ttk.Label(box, text="验证 SSH、ORACLE_HOME、实例进程，列出目录对象及各目录剩余空间",
                  style="Hint.TLabel").grid(row=r, column=2, columnspan=3, sticky="w")

    def _browse_key(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(parent=self.frame)
        if path:
            self.key_file.set(path)

    # ------------------------------------------------------------ 数据
    def load(self, cfg: dict):
        srv = cfg.get("server", {})
        self.school.set(cfg.get("school_name", ""))
        self.host.set(srv.get("host", ""))
        try:
            self.port.set(int(srv.get("port") or 22))
        except (ValueError, tk.TclError):
            self.port.set(22)
        self.ssh_user.set(srv.get("ssh_user", ""))
        self.auth_type.set(srv.get("auth_type", "password"))
        self.password.set(srv.get("password", ""))
        self.key_file.set(srv.get("key_file", ""))
        self.key_passphrase.set(srv.get("key_passphrase", ""))
        self.oracle_user.set(srv.get("oracle_user", "oracle"))
        self.switch_var.set(srv.get("switch_method", "auto"))
        self.sudo_password.set(srv.get("sudo_password", ""))
        self.oracle_home.set(srv.get("oracle_home", ""))
        self.oracle_sid.set(srv.get("oracle_sid", ""))
        self.db_connect.set(srv.get("db_connect", ""))
        self.db_user.set(srv.get("db_user", "system"))
        self.db_password.set(srv.get("db_password", ""))
        self.nls_lang.set(srv.get("nls_lang", "AMERICAN_AMERICA.AL32UTF8"))
        self.dir_name_var.set(srv.get("directory_name", "DATA_PUMP_DIR"))
        self.dump_dir_var.set(srv.get("dump_dir", ""))

    def collect(self, cfg: dict):
        cfg["school_name"] = self.school.get()
        srv = cfg.setdefault("server", {})
        srv["host"] = self.host.get()
        try:
            srv["port"] = int(self.port.get())
        except (ValueError, tk.TclError):
            srv["port"] = 22
        srv["ssh_user"] = self.ssh_user.get()
        srv["auth_type"] = self.auth_type.get() or "password"
        srv["password"] = self.password.get()
        srv["key_file"] = self.key_file.get()
        srv["key_passphrase"] = self.key_passphrase.get()
        srv["oracle_user"] = self.oracle_user.get()
        srv["switch_method"] = self.switch_var.get() or "auto"
        srv["sudo_password"] = self.sudo_password.get()
        srv["oracle_home"] = self.oracle_home.get()
        srv["oracle_sid"] = self.oracle_sid.get()
        srv["db_connect"] = self.db_connect.get()
        srv["db_user"] = self.db_user.get()
        srv["db_password"] = self.db_password.get()
        srv["nls_lang"] = self.nls_lang.get()
        srv["directory_name"] = self.dir_name_var.get().strip()
        srv["dump_dir"] = self.dump_dir_var.get().strip()
        return cfg

    # ------------------------------------------------------------ 测试连接
    def _test_connection(self):
        self.app.save_config(silent=True)
        cfg = self.app.cfg
        self.app.set_status("正在测试服务器连接...")
        self.app.run_async(self._do_test, cfg)

    def _do_test(self, cfg: dict):
        result_text = []
        try:
            srv = cfg.get("server", {})
            with SSHConnection(srv) as ssh:
                # 1. 服务器基本信息
                uname = ssh.output_of("uname -r; id; df -P /tmp | tail -1", timeout=30)
                result_text.append("【服务器信息】\n" + uname.strip())

                # 2. ORACLE_HOME 下的 sqlplus 是否存在（常见配置错误）
                oh = (srv.get("oracle_home") or "").strip()
                if oh:
                    check = ssh.output_of(
                        "ls %s/bin/sqlplus %s/bin/expdp 2>&1 | head -4"
                        % (oracle.shell_quote(oh), oracle.shell_quote(oh)),
                        timeout=30)
                    if "No such file" in check or "cannot access" in check:
                        result_text.append(
                            "\n【ORACLE_HOME 校验】✗ %s 下找不到 sqlplus/expdp！\n"
                            "该目录不是有效的 ORACLE_HOME（真实路径可用 cat /etc/oratab 查询）" % oh)
                    else:
                        result_text.append("\n【ORACLE_HOME 校验】✓ sqlplus/expdp 存在")

                # 3. 实例进程检查
                sid = (srv.get("oracle_sid") or "").strip()
                if sid:
                    pmon = ssh.output_of(
                        "ps -ef | grep -E 'ora_pmon_%s' | grep -v grep" % sid,
                        timeout=30)
                    if pmon.strip():
                        result_text.append("\n【实例进程】✓ ora_pmon_%s 正在运行" % sid)
                    else:
                        result_text.append(
                            "\n【实例进程】✗ 未找到 ora_pmon_%s 进程，请检查 ORACLE_SID" % sid)

                # 4. 目录对象列表（含各目录剩余空间、所在分区）
                dirs = oracle.query_directories(ssh, srv)
                if dirs:
                    free_map = {}
                    mount_map = {}
                    all_paths = " ".join(oracle.shell_quote(p) for _, p in dirs)
                    df_out = ssh.output_of(
                        "df -P %s 2>/dev/null | awk 'NR>1{print $6, $4}'" % all_paths,
                        timeout=30)
                    for line in df_out.splitlines():
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            free_map[parts[0]] = int(parts[1]) * 1024
                    # 单独取挂载点（df -P 对同分区多路径只输出一次，用文件系统反查）
                    mount_out = ssh.output_of(
                        "for p in %s; do echo \"$p $(df -P \"$p\" 2>/dev/null | "
                        "awk 'NR==2{print $6}')\"; done"
                        % " ".join(oracle.shell_quote(p) for _, p in dirs),
                        timeout=30)
                    for line in mount_out.splitlines():
                        parts = line.split()
                        if len(parts) >= 2:
                            mount_map[parts[0]] = parts[1]
                    from app.utils import format_size
                    result_text.append("\n【可用目录对象】（✓=适合备份 ✗=不适合）")
                    for name, path in dirs:
                        free = free_map.get(path.rstrip("/")) or free_map.get(path)
                        mount = mount_map.get(path, "")
                        safe = oracle.is_safe_backup_dir(name, path)
                        mark = "✓" if safe else "✗"
                        info = ""
                        if mount:
                            info += "［%s 分区］" % mount
                        if free:
                            info += " 剩余 %s" % format_size(free)
                            if free < 50 * 1024 ** 3:
                                info += " ⚠偏小"
                        if not safe:
                            info += " （Oracle 内部对象/危险路径，不可作备份目录）"
                        result_text.append("  %s %s → %s%s" % (mark, name, path, info))
                    self.app.on_ui(lambda d=dirs: self._apply_directories(d))

                    # 5. 当前目录对象校验 + 空间推荐
                    dir_path = oracle.query_directory_path(
                        ssh, srv, srv.get("directory_name"))
                    if dir_path:
                        cur_mount = mount_map.get(dir_path, "")
                        cur_free = free_map.get(dir_path.rstrip("/")) or \
                            free_map.get(dir_path)
                        ok = oracle.is_safe_backup_dir(
                            srv.get("directory_name", ""), dir_path)
                        if not ok:
                            result_text.append(
                                "\n【当前目录对象 %s】✗ 路径 %s 不适合备份！\n"
                                "  该目录位于根分区或属于 Oracle 内部对象，"
                                "请从上面 ✓ 的目录中选择" % (
                                    srv.get("directory_name"), dir_path))
                        else:
                            result_text.append("\n【当前目录对象 %s】✓ 真实路径 %s" % (
                                srv.get("directory_name"), dir_path))
                            if cur_free is not None and cur_free < 50 * 1024 ** 3:
                                result_text.append(
                                    "  提示：该目录剩余 %s，若导出量大建议切换到剩余空间更大的目录"
                                    % format_size(cur_free))
                    else:
                        result_text.append(
                            "\n【当前目录对象 %s】✗ 未找到！请从上面的列表中选择"
                            % srv.get("directory_name"))
                else:
                    result_text.append("\n【目录对象】未能获取列表（sysdba 查询失败）")

                # 6. 所选导出用户的数据量估算（备份空间评估）
                schemas = (self.app.cfg.get("backup", {}).get("schemas") or [])
                if schemas:
                    size_text = oracle.query_schema_sizes(ssh, srv, schemas)
                    if size_text:
                        result_text.append(
                            "\n【已选 %d 个用户的数据量（未压缩）】\n%s"
                            % (len(schemas), size_text))
                        result_text.append(
                            "  说明：expdp 导出时会先在服务器上产生未压缩的 dmp 文件，"
                            "所需空间约为上面合计的 1.0~1.2 倍；\n"
                            "  压缩成 tar.gz 后约为 30%~60%。请确保目标目录剩余空间充足。")

            self.app.on_ui(lambda: W.show_info(
                self.frame, "连接测试", "\n".join(result_text)))
            log_info("连接测试完成")
        except SSHError as exc:
            self.app.on_ui(lambda: W.show_error(self.frame, "连接测试失败", str(exc)))
            log_error("连接测试失败：%s" % exc)
        except Exception as exc:
            self.app.on_ui(lambda: W.show_error(self.frame, "连接测试失败", str(exc)))
            log_error("连接测试异常：%s" % exc)
        finally:
            self.app.on_ui(lambda: self.app.set_status("就绪"))

    def _apply_directories(self, dirs):
        """把服务器返回的目录对象填充到下拉框（只列适合备份的）；
        当前值无效或危险时自动改选为安全的目录"""
        try:
            safe = oracle.filter_safe_directories(dirs)
            unsafe = [d for d in dirs if d not in safe]
            names = [name for name, _ in safe]
            paths = [path for _, path in safe]
            # 若过滤后一个不剩（极端情况），退回全部但提示
            if not names:
                safe = dirs
                names = [name for name, _ in safe]
                paths = [path for _, path in safe]
            self.dir_combo["values"] = names
            self.dump_combo["values"] = paths
            current = self.dir_name_var.get().strip()
            if current not in names:
                # 优先选择名字含 PUMP/DUMP 的，否则选第一个
                preferred = next(
                    (n for n in names if "PUMP" in n.upper() or "DUMP" in n.upper()),
                    names[0] if names else "")
                if preferred:
                    self.dir_name_var.set(preferred)
                    for name, path in safe:
                        if name == preferred and path:
                            self.dump_dir_var.set(path)
                            log_info("已自动选择目录对象：%s → %s" % (name, path))
            else:
                # 当前值有效：同步导出目录
                for name, path in safe:
                    if name == current and path:
                        self.dump_dir_var.set(path)
            if unsafe:
                log_info("已过滤 %d 个不适合备份的目录对象（%s）"
                         % (len(unsafe), ", ".join(n for n, _ in unsafe[:5])),
                         "WARNING")
        except Exception as exc:
            log_error("填充目录对象列表失败：%s" % exc)

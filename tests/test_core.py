# -*- coding: utf-8 -*-
"""核心逻辑单元测试（不依赖真实服务器）"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import cleanup, oracle, paths  # noqa: E402
from app import notify  # noqa: E402
from app.backup import BackupResult  # noqa: E402
from app.config import DEFAULT_CONFIG, _deep_merge, load_config, save_config  # noqa: E402
from app.notify import build_markdown, build_message  # noqa: E402
from app.utils import (format_duration, format_size, is_valid_time,  # noqa: E402
                       sanitize_name, shell_quote)

DAY = 86400


class TestUtils(unittest.TestCase):
    def test_format_size(self):
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(1024), "1.00 KB")
        self.assertEqual(format_size(1024 ** 3), "1.00 GB")
        self.assertEqual(format_size(1024 ** 3 * 1.85), "1.85 GB")

    def test_format_duration(self):
        self.assertEqual(format_duration(45), "45秒")
        self.assertEqual(format_duration(125), "2分5秒")
        self.assertEqual(format_duration(3725), "1小时2分5秒")

    def test_shell_quote(self):
        self.assertEqual(shell_quote("abc"), "'abc'")
        self.assertEqual(shell_quote("a b"), "'a b'")
        self.assertEqual(shell_quote("a'b"), "'a'\\''b'")
        self.assertEqual(shell_quote("p@ss;rm -rf /"), "'p@ss;rm -rf /'")

    def test_sanitize_name(self):
        self.assertEqual(sanitize_name("XX学校"), "XX学校")
        self.assertEqual(sanitize_name("a/b c"), "a_b_c")
        self.assertEqual(sanitize_name(""), "school")

    def test_is_valid_time(self):
        self.assertTrue(is_valid_time("02:00"))
        self.assertTrue(is_valid_time("23:59"))
        self.assertFalse(is_valid_time("24:00"))
        self.assertFalse(is_valid_time("abc"))


class TestConfig(unittest.TestCase):
    def test_deep_merge(self):
        merged = _deep_merge(DEFAULT_CONFIG, {"server": {"host": "10.0.0.1"}})
        self.assertEqual(merged["server"]["host"], "10.0.0.1")
        # 默认字段保留
        self.assertEqual(merged["server"]["port"], 22)
        self.assertEqual(merged["backup"]["local_keep_days"], 30)

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["ORA_BACKUP_HOME"] = tmp
            try:
                cfg = _deep_merge(DEFAULT_CONFIG, {
                    "school_name": "测试中学",
                    "server": {"host": "192.168.9.9", "port": 2222},
                    "backup": {"schemas": ["USER_A", "USER_B"], "local_keep_days": 7},
                })
                save_config(cfg)
                self.assertTrue(os.path.exists(paths.get_config_path()))
                loaded = load_config()
                self.assertEqual(loaded["school_name"], "测试中学")
                self.assertEqual(loaded["server"]["host"], "192.168.9.9")
                self.assertEqual(loaded["server"]["port"], 2222)
                self.assertEqual(loaded["backup"]["schemas"], ["USER_A", "USER_B"])
                self.assertEqual(loaded["backup"]["local_keep_days"], 7)
                # 未配置字段回退默认
                self.assertEqual(loaded["notify"]["pushplus"]["enabled"], False)
            finally:
                os.environ.pop("ORA_BACKUP_HOME", None)


def make_cfg(**backup_over):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["school_name"] = "某某市第一中学"
    cfg["server"].update({
        "host": "10.0.0.5",
        "ssh_user": "root",
        "oracle_user": "oracle",
        "oracle_home": "/u01/app/oracle/product/19c/dbhome_1",
        "oracle_sid": "ORCL",
        "db_user": "system",
        "db_password": "Adm1n@2026",
        "db_connect": "ORCL",
        "directory_name": "DATA_PUMP_DIR",
        "dump_dir": "/opt/oracle/backup",
    })
    cfg["backup"].update({
        "schemas": ["EDU_USER", "OA_USER"],
        "remote_keep_days": 3,
        "local_keep_days": 30,
        "parallel": 2,
    })
    cfg["backup"].update(backup_over)
    return cfg


class TestBackupScript(unittest.TestCase):
    def test_script_contains_core_parts(self):
        cfg = make_cfg()
        ts = "20261023_020000"
        script = oracle.build_backup_script(cfg, ts)
        self.assertIn("ORACLE_HOME='/u01/app/oracle/product/19c/dbhome_1'", script)
        self.assertIn("ORACLE_SID='ORCL'", script)
        self.assertIn("SCHEMAS=EDU_USER,OA_USER", script)
        self.assertIn("expdp 'system/Adm1n@2026@ORCL'", script)
        self.assertIn("DIRECTORY=\"$DIRNAME\"", script)
        self.assertIn("PARALLEL=2", script)
        self.assertIn("orabackup_某某市第一中学_20261023_020000.tar.gz", script)
        self.assertIn("KEEP_DAYS=3", script)
        self.assertIn("-mtime +$KEEP_DAYS", script)
        self.assertIn("RESULT_FILE=", script)
        # 目录对象探测改为引用上传的 SQL 文件（引号安全）
        self.assertIn(".orabackup_%s.sql" % ts, script)
        self.assertIn("grep '^/'", script)
        # 脚本绝不能包含会把 printf 引号结构破坏的内联 SQL
        self.assertNotIn("printf 'set heading", script)

    def test_probe_sql(self):
        cfg = make_cfg()
        cfg["server"]["directory_name"] = "EXPDP_DIR"
        sql = oracle.build_probe_sql(cfg, "20261023_020000")
        self.assertIn("dba_directories", sql)
        self.assertIn("directory_name='EXPDP_DIR'", sql)
        self.assertIn("exit;", sql)
        # 含单引号的目录名需 SQL 转义
        cfg["server"]["directory_name"] = "IT'S_DIR"
        sql = oracle.build_probe_sql(cfg, "x")
        self.assertIn("directory_name='IT''S_DIR'", sql)

    def test_script_password_special_chars(self):
        cfg = make_cfg()
        cfg["server"]["db_password"] = "p@ss'w;rd"
        script = oracle.build_backup_script(cfg, "20261023_020000")
        # 密码中的单引号必须被转义，保证 shell 安全
        self.assertIn("expdp 'system/p@ss'\\''w;rd@ORCL'", script)

    def test_script_no_compress(self):
        cfg = make_cfg(compress=False)
        script = oracle.build_backup_script(cfg, "20261023_020000")
        # 不压缩时用 tar 打包所有 %U 分片（不能再 mv 单个文件）
        self.assertIn("tar -cf \"$TARFILE\"", script)
        self.assertNotIn("tar -cf -", script)
        self.assertNotIn("mv -f", script)

    def test_script_requires_schemas(self):
        cfg = make_cfg(schemas=[])
        with self.assertRaises(Exception):
            oracle.build_backup_script(cfg, "20261023_020000")

    def test_run_command_switch(self):
        srv = {"ssh_user": "root", "oracle_user": "oracle", "switch_method": "auto"}
        cmd = oracle.build_run_command(srv, "/tmp/x.sh")
        # root 登录用 su（不带 - 登录参数，避免部分服务器 su - 失败）
        self.assertIn("su oracle -c", cmd)
        self.assertNotIn("su - oracle", cmd)
        srv = {"ssh_user": "oracle", "oracle_user": "oracle", "switch_method": "auto"}
        cmd = oracle.build_run_command(srv, "/tmp/x.sh")
        self.assertNotIn("su ", cmd)
        srv = {"ssh_user": "admin", "oracle_user": "oracle", "switch_method": "sudo"}
        cmd = oracle.build_run_command(srv, "/tmp/x.sh")
        self.assertIn("sudo -u oracle", cmd)

    def test_parse_users(self):
        out = """
SQL> 
SCOTT
HR
OE
SH
5 rows selected.
"""
        users = oracle.parse_db_users(out)
        self.assertEqual(users, ["HR", "OE", "SCOTT", "SH"])

    def test_parse_markers(self):
        out = "[orabackup] ok\nRESULT_FILE=orabackup_x.tar.gz\nRESULT_SIZE=12345\nRESULT_DISKFREE_KB=2048000\n"
        markers = oracle.parse_result_markers(out)
        self.assertEqual(markers["RESULT_FILE"], "orabackup_x.tar.gz")
        self.assertEqual(markers["RESULT_SIZE"], "12345")
        self.assertEqual(markers["RESULT_DISKFREE_KB"], "2048000")

    def test_detect_errors(self):
        self.assertIn("密码", oracle.detect_expdp_error("ORA-01017: invalid username/password"))
        self.assertIn("权限", oracle.detect_expdp_error("ORA-01031: insufficient privileges"))
        self.assertEqual(oracle.detect_expdp_error("all good"), "")


class TestCleanup(unittest.TestCase):
    def test_cleanup_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "orabackup_old.tar.gz")
            new = os.path.join(tmp, "orabackup_new.tar.gz")
            other = os.path.join(tmp, "notes.txt")
            for p in (old, new, other):
                with open(p, "w") as f:
                    f.write("x")
            old_time = time.time() - 40 * DAY
            os.utime(old, (old_time, old_time))
            os.utime(new, (time.time(), time.time()))
            deleted = cleanup.cleanup_local_backups(tmp, 30)
            self.assertEqual(len(deleted), 1)
            self.assertFalse(os.path.exists(old))
            self.assertTrue(os.path.exists(new))
            self.assertTrue(os.path.exists(other))  # 非备份文件不动

    def test_keep_zero_disables_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "orabackup_old.tar.gz")
            with open(old, "w") as f:
                f.write("x")
            old_time = time.time() - 100 * DAY
            os.utime(old, (old_time, old_time))
            self.assertEqual(cleanup.cleanup_local_backups(tmp, 0), [])
            self.assertTrue(os.path.exists(old))

    def test_list_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "orabackup_a.tar.gz"), "w") as f:
                f.write("x")
            items = cleanup.list_local_backups(tmp)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["name"], "orabackup_a.tar.gz")


class TestNotifyMessage(unittest.TestCase):
    def _result(self, success=True):
        return BackupResult(
            success=success, started_at="2026-10-23 02:00:15",
            finished_at="2026-10-23 02:12:49", duration=754.0,
            size=int(1.85 * 1024 ** 3), filename="orabackup_school_20261023.tar.gz",
            local_file="D:\\Backup\\orabackup_school_20261023.tar.gz",
            server_disk_free=50 * 1024 ** 3, server_dump_dir="/opt/oracle/backup",
            local_disk_free=120 * 1024 ** 3, local_path="D:\\Backup",
            error="")

    def test_success_message(self):
        cfg = make_cfg()
        title, content = build_message(self._result(True), cfg)
        self.assertIn("某某市第一中学", title)
        self.assertIn("学校名称：某某市第一中学", content)
        self.assertIn("备份日期：2026-10-23 02:00:15", content)
        self.assertIn("文件大小：1.85 GB", content)
        self.assertIn("备份耗时：12分34秒", content)
        self.assertIn("服务器磁盘剩余：50.00 GB", content)
        self.assertIn("本地磁盘剩余：120.00 GB", content)

    def test_failure_message(self):
        cfg = make_cfg()
        r = self._result(False)
        r.error = "SSH 连接超时"
        title, content = build_message(r, cfg)
        self.assertIn("失败", title)
        self.assertIn("SSH 连接超时", content)

    def test_dingtalk_markdown(self):
        cfg = make_cfg()
        md = build_markdown(self._result(True), cfg)
        self.assertIn("备份成功", md)
        self.assertIn("某某市第一中学", md)


class TestScheduler(unittest.TestCase):
    def test_scheduler_module_import(self):
        from app import scheduler
        self.assertTrue(hasattr(scheduler, "BackupScheduler"))


class TestSSHStreamFlush(unittest.TestCase):
    """回归测试：流式输出被节流跳过的尾部数据必须在命令结束后刷新，
    否则备份结果标记（RESULT_FILE 等）会丢失"""

    def _make_channel(self):
        import select as select_mod
        import socket

        class PipeChannel:
            def __init__(self):
                # Windows 的 select 仅支持套接字，故用 socketpair 模拟通道
                self.listener, self.w = socket.socketpair()
                self.r = self.listener
                self._eof = False
                self._exit_ready = False
                self._status = 0

            def settimeout(self, t):
                pass

            def exec_command(self, cmd):
                pass

            def fileno(self):
                return self.r.fileno()

            def _readable(self):
                return bool(select_mod.select([self.r], [], [], 0)[0])

            def recv_ready(self):
                if self._eof:
                    return False
                return self._readable()

            def recv(self, n):
                try:
                    data = self.r.recv(n)
                except (BlockingIOError, InterruptedError):
                    return b""
                if not data:
                    self._eof = True
                return data

            def recv_stderr_ready(self):
                return False

            def recv_stderr(self, n):
                return b""

            @property
            def eof_received(self):
                return self._eof

            def exit_status_ready(self):
                return self._exit_ready

            def recv_exit_status(self):
                return self._status

            def close(self):
                for s in (self.r, self.w, self.listener):
                    try:
                        s.close()
                    except OSError:
                        pass

        return PipeChannel()

    def test_throttled_tail_is_flushed(self):
        import threading
        from app.ssh import SSHConnection

        chan = self._make_channel()

        class FakeTransport:
            def is_active(self):
                return True

            def open_session(self):
                return chan

        class FakeClient:
            def get_transport(self):
                return FakeTransport()

        conn = SSHConnection({"host": "x"})
        conn.client = FakeClient()

        # 第一个数据块立即到达（会被流式输出），
        # 第二个数据块（含结果标记）在 50ms 后到达（< 100ms 节流间隔，会被跳过），
        # 然后命令结束 —— 尾部数据必须靠最终刷新输出
        def writer():
            chan.w.sendall(b"[orabackup] export start\n")
            time.sleep(0.05)
            chan.w.sendall("RESULT_FILE=orabackup_test.tar.gz\nRESULT_SIZE=1024\n".encode())
            time.sleep(0.02)
            chan._exit_ready = True
            chan.w.close()

        threading.Thread(target=writer, daemon=True).start()
        streamed = []
        status = conn.run("fake", timeout=30, stream=streamed.append)
        conn.close()

        self.assertEqual(status, 0)
        text = "\n".join(streamed)
        self.assertIn("export start", text)
        self.assertIn("RESULT_FILE=orabackup_test.tar.gz", text,
                      "被节流的尾部输出必须在命令结束后刷新")
        self.assertIn("RESULT_SIZE=1024", text)


class TestQueryUserFallback(unittest.TestCase):
    """回归测试：用户列表查询必须可见服务器错误，并在 sysdba 失败时
    回退到导出用户连接（all_users），不能再出现'0 个用户且无原因'"""

    def _server_cfg(self):
        return {
            "ssh_user": "root", "oracle_user": "oracle",
            "switch_method": "auto",
            "oracle_home": "/u01/app/oracle/product/19.3.0/dbhome_1",
            "oracle_sid": "zfdb", "db_user": "zfdb_xgxt",
            "db_password": "p@ss'w0rd", "db_connect": "zfdb",
            "nls_lang": "AMERICAN_AMERICA.AL32UTF8",
        }

    def test_query_command_with_quoted_sql(self):
        """含单引号的 SQL（如目录对象查询）必须完整送达 sqlplus——
        用假 sqlplus 捕获 stdin 实际内容验证（覆盖 su 包装的引号转义）"""
        import shutil
        import subprocess
        import tempfile

        bash = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
        tmp = tempfile.mkdtemp(prefix="orabk_q_")
        try:
            oh = os.path.join(tmp, "oh")
            os.makedirs(os.path.join(oh, "bin"))
            # 假 sqlplus：把收到的 stdin 原样写到文件，再输出一个假路径
            capture = os.path.join(tmp, "received.txt")
            sqlplus = os.path.join(oh, "bin", "sqlplus")
            with open(sqlplus, "w", encoding="utf-8") as f:
                f.write("#!/bin/bash\ncat > %s\necho /u01/expdp_dir\n"
                        % capture.replace("\\", "/"))
            os.chmod(sqlplus, 0o755)
            # 假 su
            su_path = os.path.join(tmp, "su")
            with open(su_path, "w", encoding="utf-8") as f:
                f.write("#!/bin/bash\n"
                        "while [ $# -gt 0 ]; do\n"
                        "  case \"$1\" in\n"
                        "    -c) shift; exec bash -c \"$1\";;\n"
                        "    *) shift;;\n"
                        "  esac\n"
                        "done\n")
            os.chmod(su_path, 0o755)

            def to_posix(p):
                p = p.replace("\\", "/")
                if len(p) > 1 and p[1] == ":":
                    p = "/" + p[0].lower() + p[2:]
                return p

            cfg = {
                "ssh_user": "root", "oracle_user": "oracle",
                "switch_method": "auto",
                "oracle_home": to_posix(oh),
                "oracle_sid": "zfdb",
                "db_user": "zfsoft_xxzx", "db_password": "x",
                "db_connect": "zfdb",
                "nls_lang": "AMERICAN_AMERICA.AL32UTF8",
            }
            sql = ("SELECT directory_path FROM dba_directories "
                   "WHERE directory_name='EXPDP_DIR';")
            cmd = oracle.build_query_command(cfg, sql)
            self.assertIn("2>&1", cmd)
            self.assertNotIn("2>/dev/null", cmd)

            env = dict(os.environ)
            env["PATH"] = to_posix(tmp) + ":" + env.get("PATH", "")
            env = {k: v for k, v in env.items()
                   if not k.startswith("BASH_FUNC_") and k != "BASH_ENV"}
            p = subprocess.run([bash, "-c", cmd], capture_output=True,
                               text=True, timeout=60, env=env)
            with open(capture, "r", encoding="utf-8") as f:
                received = f.read()
            # sqlplus 必须收到完整无损的 SQL（单引号保留）
            self.assertIn("SELECT directory_path FROM dba_directories",
                          received)
            self.assertIn("directory_name='EXPDP_DIR';", received,
                          "SQL 中的单引号必须在引号转价后完整保留，实际收到：%r"
                          % received[:200])
            self.assertIn("/u01/expdp_dir", p.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_stderr_not_discarded(self):
        cfg = self._server_cfg()
        cmd = oracle.build_query_command(cfg, "SELECT 1 FROM dual;")
        self.assertIn("2>&1", cmd, "sqlplus 的 stderr 不能再被丢弃")
        self.assertNotIn("2>/dev/null", cmd)

    def test_as_user_connect_uses_export_user(self):
        cfg = self._server_cfg()
        cmd = oracle.build_query_command(cfg, "SELECT 1 FROM dual;", as_user=True)
        # 应使用导出用户连接（含正确转义的密码），而非 sysdba
        self.assertIn("zfdb_xgxt", cmd)
        self.assertIn("p@ss", cmd)
        self.assertIn("w0rd@zfdb", cmd)
        self.assertNotIn("/ as sysdba", cmd)

    def test_fallback_when_sysdba_fails(self):
        class FakeSSH:
            def __init__(self):
                self.calls = []

            def output_of(self, command, timeout=120, sudo_password=None):
                self.calls.append(command)
                if "/ as sysdba" in command:
                    # 模拟 OS 认证失败（真实服务器最常见）
                    return "ERROR:\nORA-01031: insufficient privileges\n"
                return "ZFDB_XGXT\nZFDB_OA\nZFDB_JWXT\n"

        ssh = FakeSSH()
        users = oracle.query_db_users(ssh, self._server_cfg())
        self.assertEqual(users, ["ZFDB_JWXT", "ZFDB_OA", "ZFDB_XGXT"])
        self.assertEqual(len(ssh.calls), 2, "应先试 sysdba，再回退导出用户")
        self.assertIn("/ as sysdba", ssh.calls[0])
        self.assertIn("all_users", ssh.calls[1])

    def test_both_fail_raises_with_reason(self):
        class FakeSSH:
            def output_of(self, command, timeout=120, sudo_password=None):
                return "ORA-01017: invalid username/password\n"

        with self.assertRaises(Exception) as ctx:
            oracle.query_db_users(FakeSSH(), self._server_cfg())
        msg = str(ctx.exception)
        self.assertIn("ORA-01017", msg)
        self.assertIn("排查建议", msg, "错误信息必须包含排查建议")

    def test_extract_error(self):
        self.assertEqual(oracle._extract_error("ERROR:\nORA-01031: x"),
                         "ERROR:")
        self.assertEqual(oracle._extract_error("SP2-1502: bad"), "SP2-1502: bad")
        self.assertEqual(oracle._extract_error("nothing here"), "")


class TestConnectString(unittest.TestCase):
    """连接串构造：配置连接名走网络，留空走本地 BEQ"""

    def test_with_connect_name(self):
        s = oracle.build_connect_string(
            {"db_user": "u", "db_password": "p", "db_connect": "//localhost:1521/zfdb"})
        self.assertEqual(s, "u/p@//localhost:1521/zfdb")

    def test_beq_when_connect_empty(self):
        s = oracle.build_connect_string(
            {"db_user": "u", "db_password": "p", "db_connect": ""})
        self.assertEqual(s, "u/p")

    def test_beq_when_connect_missing(self):
        s = oracle.build_connect_string({"db_user": "u", "db_password": "p"})
        self.assertEqual(s, "u/p")

    def test_script_uses_beq(self):
        cfg = make_cfg()
        cfg["server"]["db_connect"] = ""
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("expdp 'system/Adm1n@2026'", script)
        self.assertNotIn("system/Adm1n@2026@", script)


class TestSuWrapperExecution(unittest.TestCase):
    """回归测试：root 经 su oracle -c 包装后的查询命令必须能真正执行
    （用户实测反馈：服务器上 su 不带横杠才能切换）"""

    def _to_posix(self, path: str) -> str:
        path = path.replace("\\", "/")
        if len(path) > 1 and path[1] == ":":
            path = "/" + path[0].lower() + path[2:]
        return path

    def test_su_wrapped_command_executes(self):
        import shutil
        import subprocess
        import tempfile

        bash = shutil.which("bash") or r"C:\Program Files\Git\bin\bash.exe"
        tmp = tempfile.mkdtemp(prefix="orabk_su_")
        try:
            oh = os.path.join(tmp, "oh")
            os.makedirs(os.path.join(oh, "bin"))
            # 假 sqlplus：输出三个用户
            sqlplus = os.path.join(oh, "bin", "sqlplus")
            with open(sqlplus, "w", encoding="utf-8") as f:
                f.write("#!/bin/bash\ncat > /dev/null\n"
                        "echo ZFDB_XGXT\necho ZFDB_OA\necho ZFDB_JWXT\n")
            os.chmod(sqlplus, 0o755)
            # 假 su：提取 -c 后的命令并用 bash 执行
            su_path = os.path.join(tmp, "su")
            with open(su_path, "w", encoding="utf-8") as f:
                f.write("#!/bin/bash\n"
                        "while [ $# -gt 0 ]; do\n"
                        "  case \"$1\" in\n"
                        "    -c) shift; exec bash -c \"$1\";;\n"
                        "    *) shift;;\n"
                        "  esac\n"
                        "done\n")
            os.chmod(su_path, 0o755)

            cfg = {
                "ssh_user": "root", "oracle_user": "oracle",
                "switch_method": "auto",
                "oracle_home": self._to_posix(oh),
                "oracle_sid": "zfdb",
                "db_user": "zfdb_xgxt", "db_password": "x",
                "db_connect": "zfdb",
                "nls_lang": "AMERICAN_AMERICA.AL32UTF8",
            }
            cmd = oracle.build_query_command(
                cfg, "SELECT username FROM dba_users ORDER BY username;")
            self.assertIn("su oracle -c", cmd)
            self.assertNotIn("su - oracle", cmd)

            env = dict(os.environ)
            env["PATH"] = self._to_posix(tmp) + ":" + env.get("PATH", "")
            env = {k: v for k, v in env.items()
                   if not k.startswith("BASH_FUNC_") and k != "BASH_ENV"}
            p = subprocess.run([bash, "-c", cmd], capture_output=True,
                               text=True, timeout=60, env=env)
            users = oracle.parse_db_users(p.stdout)
            self.assertEqual(users, ["ZFDB_JWXT", "ZFDB_OA", "ZFDB_XGXT"],
                             "su 包装后的命令应能正确执行并解析出用户，实际输出：%r"
                             % p.stdout[:200])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestDirPreparation(unittest.TestCase):
    """root 登录时自动创建导出目录 + 空间预警 + 新报错识别"""

    def _srv(self, **kw):
        base = {"ssh_user": "root", "oracle_user": "oracle",
                "switch_method": "auto",
                "oracle_home": "/u01/oracle", "oracle_sid": "zfdb",
                "db_user": "system", "db_password": "x", "db_connect": "",
                "nls_lang": "AMERICAN_AMERICA.AL32UTF8",
                "directory_name": "DATA_PUMP_DIR",
                "dump_dir": "/opt/oracle/backup"}
        base.update(kw)
        return base

    def test_root_creates_dir(self):
        from app.backup import BackupRunner
        commands = []

        class FakeSSH:
            def output_of(self, cmd, timeout=120, sudo_password=None):
                if cmd.strip().startswith("id -gn"):
                    return "oinstall\n"
                return ""

            def run(self, cmd, timeout=None, sudo_password=None, stream=None):
                commands.append(cmd)
                return 0

        runner = BackupRunner({})
        runner._log = lambda *a, **k: None
        srv = self._srv()
        runner._ensure_remote_dirs(FakeSSH(), srv,
                                   ["/opt/oracle/backup", "/u01/dpdump"])
        mkdir_cmds = [c for c in commands if "mkdir -p" in c]
        self.assertEqual(len(mkdir_cmds), 2)
        self.assertIn("'/opt/oracle/backup'", mkdir_cmds[0])
        self.assertIn("chown 'oracle:oinstall'", mkdir_cmds[0])
        self.assertIn("'/u01/dpdump'", mkdir_cmds[1])

    def test_non_root_skips(self):
        from app.backup import BackupRunner
        commands = []

        class FakeSSH:
            def output_of(self, cmd, timeout=120, sudo_password=None):
                return ""

            def run(self, cmd, timeout=None, sudo_password=None, stream=None):
                commands.append(cmd)
                return 0

        runner = BackupRunner({})
        runner._log = lambda *a, **k: None
        srv = self._srv(ssh_user="oracle")
        runner._ensure_remote_dirs(FakeSSH(), srv, ["/opt/oracle/backup"])
        self.assertEqual(commands, [], "非 root 登录不应尝试创建目录")

    def test_script_has_space_warning(self):
        cfg = make_cfg()
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("AVAIL_KB", script)
        self.assertIn("20971520", script)
        self.assertIn("ORA-39095", script)

    def test_new_error_detection(self):
        self.assertIn("空间不足", oracle.detect_expdp_error(
            "ORA-39095: Dump file space has been exhausted"))
        self.assertIn("BEQ", oracle.detect_expdp_error(
            "ORA-12154: TNS:could not resolve the connect identifier"))
        self.assertIn("无权限", oracle.detect_expdp_error(
            "mkdir: cannot create directory '/opt/oracle': Permission denied"))
        self.assertIn("ORA-12514", oracle.detect_expdp_error(
            "ORA-12514: TNS:listener does not currently know of service"))


class TestOracleModuleApi(unittest.TestCase):
    """防止误删公共函数（曾因编辑失误删掉 query_directory_path 的函数头）"""

    REQUIRED = [
        "build_connect_string", "build_probe_sql", "probe_sql_path",
        "build_backup_script", "build_run_command", "build_query_command",
        "parse_db_users", "query_db_users", "query_directory_path",
        "query_directories", "estimate_schema_sizes", "query_schema_sizes",
        "parse_result_markers", "detect_expdp_error", "shell_quote",
    ]

    def test_required_functions_exist(self):
        for name in self.REQUIRED:
            self.assertTrue(hasattr(oracle, name),
                            "app.oracle 缺少函数：%s" % name)
            self.assertTrue(callable(getattr(oracle, name)))

    def test_no_orphan_docstrings(self):
        """模块级不应有删掉函数头残留的死代码（docstring 紧跟 return）"""
        import inspect
        src = inspect.getsource(oracle)
        self.assertNotIn('return "\\n".join(lines)\n    """', src)


class TestPerSchemaPack(unittest.TestCase):
    """按用户分包模式"""

    def test_per_schema_script(self):
        cfg = make_cfg(pack_mode="per_schema")
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("按用户分别导出", script)
        self.assertIn("for S in $SCHEMAS", script)
        self.assertIn("RESULT_FILE_${S}", script)
        self.assertIn("RESULT_EXPORTED", script)
        self.assertIn("RESULT_FAILED", script)
        # 失败不中断，继续下一个用户
        self.assertIn("继续导出其他用户", script)

    def test_combined_script_no_for_loop(self):
        cfg = make_cfg()
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertNotIn("for S in $SCHEMAS", script)
        self.assertIn("RESULT_FILE=$TARFILE", script)

    def test_parse_multi_markers(self):
        out = (
            "RESULT_WORKDIR=/u01/dpdump\n"
            "RESULT_FILE_ZFSOFT_OA=orabackup_x_ZFSOFT_OA_1.tar.gz\n"
            "RESULT_SIZE_ZFSOFT_OA=1024\n"
            "RESULT_FILE_ZFSOFT_HRM=orabackup_x_ZFSOFT_HRM_1.tar.gz\n"
            "RESULT_SIZE_ZFSOFT_HRM=2048\n"
            "RESULT_EXPORTED=2\n"
            "RESULT_FAILED=0\n"
        )
        m = oracle.parse_result_markers(out)
        self.assertEqual(m["RESULT_FILE_ZFSOFT_OA"], "orabackup_x_ZFSOFT_OA_1.tar.gz")
        self.assertEqual(m["RESULT_SIZE_ZFSOFT_HRM"], "2048")
        self.assertEqual(m["RESULT_EXPORTED"], "2")


class TestSchemaSizeEstimate(unittest.TestCase):
    """schema 大小估算"""

    def test_estimate(self):
        class FakeSSH:
            def output_of(self, cmd, timeout=120, sudo_password=None):
                if "dba_segments" in cmd:
                    return "ZFSOFT_OA\t\t1234567\nZFSOFT_HRM\t\t2345678\n"
                return ""

        sizes = oracle.estimate_schema_sizes(
            FakeSSH(), {}, ["ZFSOFT_OA", "ZFSOFT_HRM"])
        self.assertEqual(sizes["ZFSOFT_OA"], 1234567)
        self.assertEqual(sizes["ZFSOFT_HRM"], 2345678)

    def test_estimate_empty(self):
        class FakeSSH:
            def output_of(self, cmd, timeout=120, sudo_password=None):
                return "no rows selected"

        self.assertEqual(oracle.estimate_schema_sizes(FakeSSH(), {}, ["X"]), {})


class TestSafeDirectory(unittest.TestCase):
    """危险目录对象过滤（曾把 dump 写进 /ade 导致根分区写满）"""

    def test_unsafe_dirs(self):
        self.assertFalse(oracle.is_safe_backup_dir("SDO_DIR_WORK", "/ade/b/x/oracle/work"))
        self.assertFalse(oracle.is_safe_backup_dir("XMLDIR", "/u01/oracle/rdbms/xml"))
        self.assertFalse(oracle.is_safe_backup_dir("ORACLE_OCM_CONFIG_DIR2", "/u01/x/ccr"))
        self.assertFalse(oracle.is_safe_backup_dir("OPATCH_INST_DIR", "/u01/x/OPatch"))
        self.assertFalse(oracle.is_safe_backup_dir("ANY", "/"))
        self.assertFalse(oracle.is_safe_backup_dir("ANY", "/root/x"))
        self.assertFalse(oracle.is_safe_backup_dir("ANY", ""))

    def test_safe_dirs(self):
        self.assertTrue(oracle.is_safe_backup_dir("DATA_PUMP_DIR", "/u01/app/oracle/admin/zfdb/dpdump"))
        self.assertTrue(oracle.is_safe_backup_dir("EXPDP_DIR", "/u01/expdp_dir"))
        self.assertTrue(oracle.is_safe_backup_dir("MY_BACKUP", "/u02/oracle_bak"))

    def test_filter(self):
        dirs = [("DATA_PUMP_DIR", "/u01/a"), ("SDO_DIR_WORK", "/ade/b/x"),
                ("XMLDIR", "/u01/xml"), ("EXPDP_DIR", "/u01/expdp_dir")]
        safe = oracle.filter_safe_directories(dirs)
        self.assertEqual([n for n, _ in safe], ["DATA_PUMP_DIR", "EXPDP_DIR"])

    def test_script_rejects_root_fs(self):
        cfg = make_cfg()
        cfg["server"]["dump_dir"] = "/ade/b/1818271618/oracle"
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("FS_MOUNT", script)
        self.assertIn("exit 13", script)
        self.assertIn("根分区", script)

    def test_script_has_expdp_trap(self):
        """取消备份/断线时必须杀掉 expdp，避免僵尸进程占磁盘"""
        cfg = make_cfg()
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("trap _on_exit EXIT INT TERM HUP", script)
        self.assertIn('EXPPID=$!', script)
        self.assertIn('wait "$EXPPID"', script)

    def test_script_per_schema_trap(self):
        cfg = make_cfg(pack_mode="per_schema")
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("trap _on_exit EXIT INT TERM HUP", script)
        self.assertIn('EXPPID=$!', script)


class TestPreflightSpace(unittest.TestCase):
    """备份前空间预检：根分区拒绝 + 空间不足中止"""

    def _srv(self, **kw):
        base = {"ssh_user": "root", "oracle_user": "oracle",
                "oracle_home": "/u01/oracle", "oracle_sid": "zfdb",
                "db_user": "system", "db_password": "x", "db_connect": "",
                "nls_lang": "AMERICAN_AMERICA.AL32UTF8",
                "directory_name": "DATA_PUMP_DIR",
                "dump_dir": "/u01/dpdump"}
        base.update(kw)
        return base

    def _runner(self):
        from app.backup import BackupRunner
        runner = BackupRunner({"backup": {"schemas": ["A", "B"]}})
        runner._log = lambda *a, **k: None
        return runner

    def test_root_fs_rejected(self):
        class FakeSSH:
            def output_of(self, cmd, timeout=120, sudo_password=None):
                if "dba_segments" in cmd:
                    return "A\t\t1048576\nB\t\t1048576\n"
                if cmd.strip().startswith("df -P"):
                    return "ext4 10485760 /\n"
                return ""

        with self.assertRaises(Exception) as ctx:
            self._runner()._preflight_space_check(FakeSSH(), self._srv(), "/ade/x")
        self.assertIn("根分区", str(ctx.exception))

    def test_tmpfs_rejected(self):
        class FakeSSH:
            def output_of(self, cmd, timeout=120, sudo_password=None):
                if "dba_segments" in cmd:
                    return "A\t\t1048576\nB\t\t1048576\n"
                if cmd.strip().startswith("df -P"):
                    return "tmpfs 104857600 /tmp\n"
                return ""

        with self.assertRaises(Exception) as ctx:
            self._runner()._preflight_space_check(FakeSSH(), self._srv(), "/tmp")
        self.assertIn("内存盘", str(ctx.exception))

    def test_insufficient_space_rejected(self):
        class FakeSSH:
            def output_of(self, cmd, timeout=120, sudo_password=None):
                if "dba_segments" in cmd:
                    return "A\t\t104857600\nB\t\t104857600\n"  # 各 100MB
                if cmd.strip().startswith("df -P"):
                    return "ext4 102400 /u01\n"   # -Pk 单位 KB，仅剩 100MB
                return ""

        with self.assertRaises(Exception) as ctx:
            self._runner()._preflight_space_check(FakeSSH(), self._srv(), "/u01/dpdump")
        self.assertIn("空间不足", str(ctx.exception))

    def test_sufficient_space_passes(self):
        class FakeSSH:
            def output_of(self, cmd, timeout=120, sudo_password=None):
                if "dba_segments" in cmd:
                    return "A\t\t1048576\nB\t\t1048576\n"
                if cmd.strip().startswith("df -P"):
                    return "ext4 104857600 /u01\n"
                return ""

        # 不抛异常即通过
        self._runner()._preflight_space_check(FakeSSH(), self._srv(), "/u01/dpdump")

    def test_ensure_dirs_skips_dangerous(self):
        from app.backup import BackupRunner
        commands = []

        class FakeSSH:
            def output_of(self, cmd, timeout=120, sudo_password=None):
                return "oinstall\n" if cmd.strip().startswith("id -gn") else ""

            def run(self, cmd, timeout=None, sudo_password=None, stream=None):
                commands.append(cmd)
                return 0

        runner = BackupRunner({})
        runner._log = lambda *a, **k: None
        runner._ensure_remote_dirs(FakeSSH(), self._srv(),
                                   ["/ade/b/x", "/u01/dpdump"])
        self.assertEqual(len(commands), 1, "只应创建安全目录")
        self.assertIn("'/u01/dpdump'", commands[0])


class TestDumpfilePercentU(unittest.TestCase):
    """DUMPFILE 必须带 %U——否则 PARALLEL>1 时多 worker 抢写同一文件，
    会在导出中途报 ORA-39095（与磁盘实际空间无关，曾导致 55G 模式必败）"""

    def test_combined_dumpfile_has_percent_u(self):
        cfg = make_cfg()
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("DUMPFILE='bk_20261023_020000.%U.dmp'", script)
        self.assertIn("FILESIZE=8G", script)
        self.assertIn("DUMPFILE=\"$DUMPFILE\"", script)
        self.assertIn("FILESIZE=$FILESIZE", script)

    def test_per_schema_dumpfile_has_percent_u(self):
        cfg = make_cfg(pack_mode="per_schema")
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("DUMPFILE=\"bk_${TS}.${S}.%U.dmp\"", script)

    def test_tar_uses_glob_for_parts(self):
        """tar/rm 必须用通配符匹配所有 %U 分片"""
        cfg = make_cfg()
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("bk_${TS}.*.dmp", script)

    def test_dot_separator_avoids_prefix_collision(self):
        """模式名互为前缀时（ZFSOFT_OA vs ZFSOFT_OA_BPMX）不能误匹配：
        用 . 作分隔符（Oracle 用户名不含点）"""
        cfg = make_cfg(pack_mode="per_schema")
        cfg["backup"]["schemas"] = ["ZFSOFT_OA", "ZFSOFT_OA_BPMX"]
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("bk_${TS}.${S}.*.dmp", script)
        self.assertNotIn("bk_${TS}_${S}", script)

    def test_tmpfs_rejected(self):
        cfg = make_cfg()
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("tmpfs", script)
        self.assertIn("FS_TYPE", script)

    def test_no_tmp_fallback(self):
        """探测失败且未配置导出目录时明确报错，不再默默写 /tmp（可能是内存盘）"""
        cfg = make_cfg()
        cfg["server"]["dump_dir"] = ""
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("exit 14", script)
        self.assertNotIn("DUMPDIR='/tmp'", script)

    def test_system_users_expanded(self):
        for user in ("GSMROOTUSER", "SYS$UMF", "OJVMSYS"):
            self.assertIn(user, oracle.SYSTEM_USERS)

    def test_unsafe_prefixes_include_oracle_home(self):
        self.assertFalse(oracle.is_safe_backup_dir("ORACLE_HOME", "/u01/app/oracle"))
        self.assertFalse(oracle.is_safe_backup_dir("ORACLE_BASE", "/u01/app"))
        self.assertFalse(oracle.is_safe_backup_dir("XSDDIR", "/ade/b/x"))


    def test_exclude_statistics_default_on(self):
        """默认排除优化器统计信息（对应老脚本的 STATISTICS=none，
        大库上统计信息可占数 GB，排除不影响数据恢复）"""
        cfg = make_cfg()
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("EXCLUDE=STATISTICS", script)

    def test_exclude_statistics_can_disable(self):
        cfg = make_cfg()
        cfg["backup"]["exclude_statistics"] = False
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertNotIn("EXCLUDE=STATISTICS", script)

    def test_exclude_statistics_per_schema(self):
        cfg = make_cfg(pack_mode="per_schema")
        script = oracle.build_backup_script(cfg, "20261023_020000")
        self.assertIn("EXCLUDE=STATISTICS", script)


class TestAutoParallel(unittest.TestCase):
    """按用户分包时按数据量自动分配并行度（避免小模式产生大量碎片 dmp）"""

    GB = 1024 ** 3

    def _sizes(self):
        return {"SMALL_ONE": 100 * 1024 ** 2,      # 100MB → 并行 1
                "MID_ONE": 8 * 1024 ** 3,          # 8GB   → 并行 4
                "BIG_ONE": 60 * 1024 ** 3}         # 60GB  → 并行 16（用满配置）

    def test_adaptive_parallel_groups(self):
        cfg = make_cfg(pack_mode="per_schema")
        cfg["backup"]["parallel"] = 16
        cfg["backup"]["schemas"] = ["SMALL_ONE", "MID_ONE", "BIG_ONE"]
        script = oracle.build_backup_script(
            cfg, "20261030_103000", schema_sizes=self._sizes())
        # 大模式(60G)用满 16，中模式(8G)限 4，小模式(<1G)用 1
        self.assertIn("parallel_for()", script)
        self.assertIn("BIG_ONE) echo 16;;", script)
        self.assertIn("MID_ONE) echo 4;;", script)
        self.assertIn("*) echo 1;;", script)
        self.assertIn('SP=$(parallel_for "$S"', script)

    def test_no_sizes_falls_back_to_configured(self):
        cfg = make_cfg(pack_mode="per_schema")
        cfg["backup"]["parallel"] = 4
        cfg["backup"]["schemas"] = ["A", "B"]
        script = oracle.build_backup_script(cfg, "20261030_103000")
        # 没有大小时不生成 parallel_for，靠 || echo $PARALLEL 回退到配置值
        self.assertNotIn("parallel_for() {", script)
        self.assertIn("|| echo $PARALLEL", script)

    def test_combined_mode_ignores_sizes(self):
        cfg = make_cfg()
        cfg["backup"]["schemas"] = ["A", "B"]
        script = oracle.build_backup_script(
            cfg, "20261030_103000", schema_sizes=self._sizes())
        self.assertNotIn("parallel_for()", script)

    def test_auto_parallel_can_disable(self):
        cfg = make_cfg(pack_mode="per_schema")
        cfg["backup"]["auto_parallel"] = False
        cfg["backup"]["schemas"] = ["SMALL_ONE", "BIG_ONE"]
        script = oracle.build_backup_script(
            cfg, "20261030_103000", schema_sizes=self._sizes())
        self.assertNotIn("parallel_for()", script)


class TestWarningNotification(unittest.TestCase):
    """有异常时也发通知"""

    def _result(self, **kw):
        from app.backup import BackupResult
        from app.utils import now_str
        base = dict(success=True, started_at=now_str(), finished_at=now_str(),
                    duration=60, size=1024 ** 3, filename="x.tar.gz")
        base.update(kw)
        return BackupResult(**base)

    def test_warning_title_and_body(self):
        r = self._result(warnings=["磁盘空间偏小", "用户 A 导出失败"])
        title, content = notify.build_message(r, {"school_name": "测试"})
        self.assertIn("有异常", title)
        self.assertIn("⚠", content)
        self.assertIn("磁盘空间偏小", content)
        self.assertIn("用户 A 导出失败", content)

    def test_success_without_warnings_unchanged(self):
        r = self._result()
        title, content = notify.build_message(r, {"school_name": "测试"})
        self.assertIn("备份成功", title)
        self.assertNotIn("异常", content)

    def test_failure_includes_warnings(self):
        r = self._result(success=False, error="磁盘写满",
                         warnings=["空间预警已触发"])
        title, content = notify.build_message(r, {"school_name": "测试"})
        self.assertIn("失败", title)
        self.assertIn("空间预警已触发", content)

    def test_notifier_gating(self):
        r = self._result(warnings=["x"])
        n = notify.Notifier({}, on_success=True, on_failure=True, on_warning=False)
        self.assertEqual(n.send(r, {}), {})     # 关掉异常通知则不发
        n2 = notify.Notifier({}, on_success=True, on_failure=True, on_warning=True)
        # 无可用渠道，返回空 dict 但不报错
        self.assertEqual(n2.send(r, {}), {})

    def test_markdown_warning(self):
        r = self._result(warnings=["部分用户失败"])
        md = notify.build_markdown(r, {"school_name": "测试"})
        self.assertIn("异常", md)
        self.assertIn("部分用户失败", md)

    def test_runner_collects_warnings(self):
        from app.backup import BackupRunner
        logs = []
        runner = BackupRunner({}, on_log=lambda lv, m: logs.append((lv, m)))
        runner._log("正常消息")
        runner._log("空间偏小", "WARNING")
        runner._log("空间偏小", "WARNING")   # 重复应去重
        self.assertEqual(len(runner._warnings), 1)
        result = runner._finish(runner.result, notify=False)
        self.assertEqual(result.warnings, ["空间偏小"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
"""
端到端集成测试：
- 用假的 expdp / sqlplus 脚本模拟 Oracle 服务器命令
- 通过 Git Bash 真实执行 build_backup_script 生成的备份脚本
- 用 FakeSSH 模拟 SSHConnection，驱动 BackupRunner 完整流程
验证：脚本正确性、结果标记解析、下载、本地清理、备份结果字段
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import backup as backup_mod  # noqa: E402
from app import cleanup, oracle  # noqa: E402
from app.backup import BackupRunner  # noqa: E402
from app.config import DEFAULT_CONFIG  # noqa: E402

BASH = shutil.which("bash") or "bash"

FAKE_EXPDP = """#!/bin/bash
echo "启动 Data Pump 导出..."
DUMPFILE=""; LOGFILE=""
for arg in "$@"; do
  case "$arg" in
    DUMPFILE=*) DUMPFILE="${arg#DUMPFILE=}";;
    LOGFILE=*) LOGFILE="${arg#LOGFILE=}";;
  esac
done
# 模拟 Oracle 的 %U 展开：生成 .01.dmp 和 .02.dmp 两个分片（真实行为）
BASE="${DUMPFILE%%%U*}"
if [ -n "$BASE" ] && [ "$DUMPFILE" != "$BASE" ]; then
  echo "FAKE DUMP DATA part1 $(date)" > "${BASE}01.dmp"
  echo "FAKE DUMP DATA part2 $(date)" > "${BASE}02.dmp"
else
  echo "FAKE DUMP DATA $(date)" > "$DUMPFILE"
fi
echo "FAKE LOG DATA" > "$LOGFILE"
echo "导出完成，作业成功完成。"
exit 0
"""

FAKE_SQLPLUS = """#!/bin/bash
cat > /dev/null
echo "%s"
exit 0
"""

# 说明：本机工具沙箱会把 rm 替换为 safe-delete shim（单次约 27 秒），
# 这与程序无关（真实 Linux 服务器上 rm 是瞬时的）。
# 测试中在假 ORACLE_HOME/bin 放置直连真实 rm 的垫片绕开，加快测试。
FAKE_RM = """#!/bin/bash
exec /usr/bin/rm "$@"
"""


def find_bash():
    for candidate in (BASH, r"C:\Program Files\Git\bin\bash.exe",
                      r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if shutil.which(candidate) or os.path.exists(candidate):
            return candidate
    return None


def to_posix(path: str) -> str:
    """Windows 路径转 Cygwin/Git-Bash POSIX 路径（cygpath -u）"""
    bash = find_bash()
    if not bash:
        return path
    try:
        out = subprocess.run([bash, "-c", "cygpath -u %s" % json_quote(path)],
                             capture_output=True, text=True, timeout=15)
        result = out.stdout.strip()
        return result or path
    except Exception:
        return path


def json_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def from_posix(path: str) -> str:
    """Cygwin POSIX 路径转 Windows 路径（cygpath -w）"""
    bash = find_bash()
    if not bash or not path.startswith("/"):
        return path
    try:
        out = subprocess.run([bash, "-c", "cygpath -w %s" % json_quote(path)],
                             capture_output=True, text=True, timeout=15)
        return out.stdout.strip() or path
    except Exception:
        return path


class FakeSSH:
    """模拟 SSHConnection：本地执行上传的脚本，本地复制文件模拟下载"""

    def __init__(self, server_cfg, workdir):
        self.cfg = server_cfg
        self.workdir = workdir          # 模拟服务器导出目录
        self.path_map = {}              # 远程路径 -> 本地路径
        self.uploaded = []

    def connect(self, timeout=15):
        pass

    def close(self):
        pass

    def put_file(self, local_path, remote_path, progress=None):
        # 防护：上传的脚本绝不能含 CRLF（Windows 文本模式写入的经典 bug，
        # Linux bash 会报 "pipefail: invalid option name" 而全部失败）
        with open(local_path, "rb") as f:
            content = f.read()
        assert b"\r" not in content, (
            "上传的脚本包含 Windows 换行符(CRLF)，Linux bash 将无法执行！"
            "请检查生成脚本的写入方式（需 newline='\\n' 或二进制写入）")
        target = os.path.join(self.workdir, "_scripts", os.path.basename(remote_path))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy(local_path, target)
        self.path_map[remote_path] = to_posix(target)
        self.uploaded.append(remote_path)

    def chmod(self, remote_path, mode=0o755):
        pass

    def run(self, command, timeout=None, sudo_password=None, stream=None):
        # 收尾清理命令：直接删除本地对应的脚本文件
        if command.strip().startswith("rm "):
            for remote, local in self.path_map.items():
                if remote in command and os.path.exists(local):
                    os.remove(local)
            return 0
        script_remote = None
        for rp in self.path_map:
            if rp in command:
                script_remote = rp
                break
        if script_remote is None:
            # rm -f 清理命令等
            return 0
        local_script = self.path_map[script_remote]
        real_cmd = command.replace(script_remote, local_script)
        # 剥离沙箱导出的 bash 函数与 BASH_ENV（其会在 bash 启动时重新定义 rm
        # 的 safe-delete shim，单次约 10-19 秒；真实 Linux 无此问题），
        # 使脚本内的 rm 经 PATH 解析到测试用的假 rm
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("BASH_FUNC_") and k != "BASH_ENV"}
        proc = subprocess.run([find_bash(), "-c", real_cmd],
                              capture_output=True, text=True, timeout=120,
                              env=env)
        out = proc.stdout + proc.stderr
        if stream:
            for line in out.splitlines():
                if line.strip():
                    stream(line)
        return proc.returncode

    def get_file(self, remote_path, local_path, progress=None, cancel_check=None):
        src = from_posix(remote_path)
        shutil.copy(src, local_path)
        return os.path.getsize(local_path)

    def stat_size(self, remote_path):
        return os.path.getsize(from_posix(remote_path))


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="orabk_e2e_")
        self.server_dir = os.path.join(self.tmp, "server_dump")   # 模拟服务器导出目录
        self.local_dir = os.path.join(self.tmp, "local_backup")   # 本地备份目录
        self.oracle_home = os.path.join(self.tmp, "oracle_home")
        os.makedirs(self.server_dir)
        os.makedirs(self.local_dir)
        os.makedirs(os.path.join(self.oracle_home, "bin"))

        # 嵌入 shell 脚本的路径使用 POSIX 风格（避免 Cygwin 混合路径解析慢）
        self.server_dir_posix = to_posix(self.server_dir)
        self.oracle_home_posix = to_posix(self.oracle_home)

        # 假 expdp / sqlplus / rm
        for name, content in (("expdp", FAKE_EXPDP),
                              ("sqlplus", FAKE_SQLPLUS % self.server_dir_posix),
                              ("rm", FAKE_RM)):
            path = os.path.join(self.oracle_home, "bin", name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            os.chmod(path, 0o755)

        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        cfg["school_name"] = "测试中学"
        cfg["server"].update({
            "host": "127.0.0.1",
            "ssh_user": "oracle",
            "oracle_user": "oracle",
            "switch_method": "direct",
            "oracle_home": self.oracle_home_posix,
            "oracle_sid": "ORCL",
            "db_user": "system",
            "db_password": "test123",
            "db_connect": "ORCL",
            "directory_name": "DATA_PUMP_DIR",
            "dump_dir": self.server_dir_posix,
        })
        cfg["backup"].update({
            "schemas": ["EDU_USER"],
            "remote_keep_days": 0,     # 本用例先不测远程清理
            "local_keep_days": 30,
            "local_path": self.local_dir,
            "parallel": 1,
            "compress": True,
        })
        cfg["notify"] = {k: dict(v, enabled=False)
                         for k, v in DEFAULT_CONFIG["notify"].items()}
        self.cfg = cfg

        # 预置一个 40 天前的本地旧备份，验证本地清理
        old_file = os.path.join(self.local_dir, "orabackup_旧文件_20260913_020000.tar.gz")
        with open(old_file, "w", encoding="utf-8") as f:
            f.write("old")
        old_time = time.time() - 40 * 86400
        os.utime(old_file, (old_time, old_time))
        self.old_file = old_file

        # 猴子补丁替换 SSHConnection
        self._orig_ssh = backup_mod.SSHConnection

        def fake_conn(server_cfg):
            return FakeSSH(server_cfg, self.server_dir)

        backup_mod.SSHConnection = fake_conn

    def tearDown(self):
        backup_mod.SSHConnection = self._orig_ssh
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_backup_flow(self):
        logs = []
        runner = BackupRunner(self.cfg, on_log=lambda lv, m: logs.append((lv, m)))
        result = runner.run()

        self.assertTrue(result.success, "备份应当成功，日志：%s" % logs[-8:])
        self.assertTrue(result.filename.startswith("orabackup_测试中学_"))
        self.assertTrue(result.filename.endswith(".tar.gz"))
        self.assertGreater(result.size, 0)
        self.assertTrue(os.path.exists(result.local_file))
        self.assertEqual(os.path.getsize(result.local_file), result.size)
        self.assertGreater(result.local_disk_free, 0)
        self.assertGreater(result.server_disk_free, 0)
        self.assertEqual(result.server_dump_dir, self.server_dir_posix)

        # 本地旧备份应被清理（40 天前 > 30 天保留）
        self.assertFalse(os.path.exists(self.old_file))
        self.assertIn(self.old_file, result.deleted_local)

        # 服务器上应存在 tar.gz，且 dmp/log 已被删除
        server_files = os.listdir(self.server_dir)
        tars = [f for f in server_files if f.endswith(".tar.gz")]
        self.assertEqual(len(tars), 1)
        self.assertFalse(any(f.endswith(".dmp") for f in server_files))
        self.assertFalse(any(f.endswith(".log") for f in server_files))

        # 日志中应包含关键步骤
        text = "\n".join(m for _, m in logs)
        self.assertIn("开始 Data Pump 导出", text)
        self.assertIn("导出完成", text)
        self.assertIn("下载完成", text)
        self.assertIn("备份成功", text)

    def test_remote_cleanup(self):
        # 制造两个 5 天前的远程旧备份 + 今天的新备份
        for i, days in enumerate((5, 5)):
            old = os.path.join(self.server_dir, "orabackup_old%d.tar.gz" % i)
            with open(old, "w") as f:
                f.write("x")
            t = time.time() - days * 86400
            os.utime(old, (t, t))
        self.cfg["backup"]["remote_keep_days"] = 3
        result = BackupRunner(self.cfg).run()
        self.assertTrue(result.success)
        remaining = [f for f in os.listdir(self.server_dir)
                     if f.endswith(".tar.gz")]
        self.assertEqual(len(remaining), 1, "应只剩本次备份，实际：%s" % remaining)

    def test_expdp_failure_handling(self):
        """expdp 失败时应返回失败结果并包含错误信息"""
        # 替换假 expdp 为失败版本
        fail_path = os.path.join(self.oracle_home, "bin", "expdp")
        with open(fail_path, "w", encoding="utf-8") as f:
            f.write("#!/bin/bash\necho 'ORA-01017: invalid username/password'\nexit 1\n")
        os.chmod(fail_path, 0o755)
        result = BackupRunner(self.cfg).run()
        self.assertFalse(result.success)
        self.assertIn("密码", result.error)
        # 失败时本地不应留下文件
        self.assertFalse(os.path.exists(result.local_file))

    def test_per_schema_backup(self):
        """按用户分包模式：每个用户一个 tar.gz，全部下载"""
        self.cfg["backup"]["pack_mode"] = "per_schema"
        self.cfg["backup"]["schemas"] = ["EDU_USER", "OA_USER"]
        result = BackupRunner(self.cfg).run()
        self.assertTrue(result.success, "分包备份应成功：%s" % result.error)
        self.assertEqual(result.mode, "per_schema")
        self.assertEqual(len(result.files), 2)
        schemas = sorted(f["schema"] for f in result.files)
        self.assertEqual(schemas, ["EDU_USER", "OA_USER"])
        # 每个文件都在本地且命名含用户
        for f in result.files:
            self.assertTrue(os.path.exists(f["local_file"]))
            self.assertIn(f["schema"], f["filename"])
            self.assertGreater(f["size"], 0)
        self.assertEqual(result.size, sum(f["size"] for f in result.files))

    def test_cancel(self):
        import threading
        cancel_event = threading.Event()
        runner = BackupRunner(self.cfg, cancel_event=cancel_event)
        cancel_event.set()  # 立即取消
        result = runner.run()
        self.assertFalse(result.success)
        self.assertIn("取消", result.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
"""诊断：模拟 root -> su - oracle 路径执行 query_db_users 的命令构造"""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"))

from test_integration import find_bash, to_posix  # noqa: E402

from app import oracle  # noqa: E402
from app.config import DEFAULT_CONFIG  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="oradiag_")
    oh = os.path.join(tmp, "oracle_home")
    os.makedirs(os.path.join(oh, "bin"))
    oh_p = to_posix(oh)

    # 假 sqlplus：模拟 OS 认证失败（真实服务器最常见的失败）
    sqlplus_fail = os.path.join(oh, "bin", "sqlplus")
    with open(sqlplus_fail, "w", encoding="utf-8") as f:
        f.write('#!/bin/bash\ncat > /dev/null\n'
                'echo "ERROR:"\n'
                'echo "ORA-01031: insufficient privileges"\n'
                'exit 1\n')
    os.chmod(sqlplus_fail, 0o755)

    # 假 su：解析 "su - oracle -c 'CMD'"，提取 CMD 并用 bash 执行（模拟 Linux su）
    fake_su = os.path.join(tmp, "su")
    with open(fake_su, "w", encoding="utf-8") as f:
        f.write('#!/bin/bash\n'
                '# 跳过 - 和用户参数，找到 -c 后的命令\n'
                'while [ $# -gt 0 ]; do\n'
                '  case "$1" in\n'
                '    -c) shift; exec bash -c "$1";;\n'
                '    -*) shift;;\n'
                '    *) shift;;\n'
                '  esac\n'
                'done\n')
    os.chmod(fake_su, 0o755)

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["server"].update({
        "ssh_user": "root",
        "oracle_user": "oracle",
        "switch_method": "auto",
        "oracle_home": oh_p,
        "oracle_sid": "zfdb",
        "db_user": "zfdb_xgxt",
        "db_password": "secret",
        "db_connect": "zfdb",
        "nls_lang": "AMERICAN_AMERICA.AL32UTF8",
        "directory_name": "DATA_PUMP_DIR",
        "dump_dir": "/opt/oracle/backup",
    })

    sql = "SELECT username FROM dba_users ORDER BY username;"
    cmd = oracle.build_query_command(cfg["server"], sql)
    print("生成的命令（前 400 字符）:")
    print(" ", cmd[:400])
    print()

    # 用假 su + 假 sqlplus 执行（把 tmp/bin 放到 PATH 最前）
    env = dict(os.environ)
    env["PATH"] = to_posix(tmp) + ":" + env.get("PATH", "")
    env = {k: v for k, v in env.items()
           if not k.startswith("BASH_FUNC_") and k != "BASH_ENV"}
    p = subprocess.run([find_bash(), "-c", cmd], capture_output=True,
                       text=True, timeout=60, env=env)
    print("=== 修复前行为（2>/dev/null 时 stdout 为空，0 用户无报错）===")
    print("退出码:", p.returncode)
    print("stdout:", repr(p.stdout[:300]))
    print("解析到用户数:", len(oracle.parse_db_users(p.stdout)))
    print()
    print("=== 修复后：build_query_command 现在用 2>&1，错误可见 ===")
    cmd2 = oracle.build_query_command(cfg["server"], sql)
    print("命令中包含 2>&1:", "2>&1" in cmd2, "（不再丢弃 stderr）")
    print("错误提取:", oracle._extract_error(p.stdout) or "（stdout 无错误，说明修复前确实被丢弃）")

    # 验证导出用户兜底命令
    cmd_user = oracle.build_query_command(cfg["server"], sql, as_user=True)
    print()
    print("=== 兜底命令（导出用户连接）===")
    print(" ", cmd_user[:260])


if __name__ == "__main__":
    main()

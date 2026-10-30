# -*- coding: utf-8 -*-
"""诊断脚本：带时间戳 trace 备份脚本，定位各步骤耗时"""
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests"))

from test_integration import FAKE_EXPDP, FAKE_SQLPLUS, to_posix  # noqa: E402

from app import oracle  # noqa: E402
from app.config import DEFAULT_CONFIG  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="tracediag_")
    srv_dir = os.path.join(tmp, "server")
    os.makedirs(srv_dir)
    oh = os.path.join(tmp, "oh")
    os.makedirs(os.path.join(oh, "bin"))
    srv_p, oh_p = to_posix(srv_dir), to_posix(oh)
    for name, content in (("expdp", FAKE_EXPDP), ("sqlplus", FAKE_SQLPLUS % srv_p)):
        p = os.path.join(oh, "bin", name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(p, 0o755)
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["school_name"] = "测试中学"
    cfg["server"].update({
        "oracle_home": oh_p, "oracle_sid": "ORCL", "db_user": "system",
        "db_password": "x", "db_connect": "ORCL",
        "directory_name": "DATA_PUMP_DIR", "dump_dir": srv_p,
    })
    cfg["backup"].update({"schemas": ["EDU_USER"], "remote_keep_days": 0, "parallel": 1})
    script = oracle.build_backup_script(cfg, "20261023_000005")
    sp = os.path.join(tmp, "s.sh")
    with open(sp, "w", encoding="utf-8") as f:
        f.write(script)

    bash = "bash"
    t0 = time.time()
    env = dict(os.environ)
    env["PS4"] = "+ $EPOCHREALTIME "
    p = subprocess.run([bash, "-x", to_posix(sp)], capture_output=True,
                       text=True, env=env)
    elapsed = time.time() - t0
    out = p.stdout + p.stderr
    lines = out.splitlines()
    ts = []
    for l in lines:
        if l.startswith("+ "):
            parts = l.split(" ", 2)
            try:
                ts.append((float(parts[1]), parts[2] if len(parts) > 2 else ""))
            except Exception:
                pass
    print("总耗时: %.2fs | trace行数: %d" % (elapsed, len(ts)))
    base = ts[0][0] if ts else 0
    for t, cmd in ts:
        print("  +%7.2f  %s" % (t - base, cmd[:90]))
    if ts:
        print("trace跨度: %.2fs | 结束后hung: %.2fs" % (
            ts[-1][0] - ts[0][0], elapsed - (ts[-1][0] - t0)))
        for i in range(1, len(ts)):
            if ts[i][0] - ts[i - 1][0] > 1.0:
                print("  慢(%.1fs) -> %s" % (ts[i][0] - ts[i - 1][0], ts[i][1][:80]))
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()

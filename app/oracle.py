# -*- coding: utf-8 -*-
"""Oracle Data Pump 导出：生成服务器端备份脚本、查询用户列表与目录对象"""
from __future__ import annotations

import re

from .logger import log_error, log_info, log_warning
from .ssh import SSHError, SSHConnection
from .utils import sanitize_name, shell_quote

# 这些系统内置模式不参与导出勾选
SYSTEM_USERS = {
    "SYS", "SYSTEM", "SYSAUX", "OUTLN", "DIP", "ORACLE_OCM", "XS$NULL", "MDSYS", "CTXSYS",
    "DBSNMP", "WMSYS", "EXFSYS", "MGMT_VIEW", "ORDDATA", "OLAPSYS", "MDDATA",
    "ORDPLUGINS", "SI_INFORMTN_SCHEMA", "DVSYS", "LBACSYS", "AUDSYS", "GSMADMIN_INTERNAL",
    "XDB", "APPQOSSYS", "APEX_030200", "APEX_040000", "APEX_040100", "APEX_040200",
    "APEX_050000", "OWBSYS", "OWBSYS_AUDIT", "SYSMAN", "SYSMANBACKUP", "SYSMAN_MDS",
    "FLOWS_FILES", "SPATIAL_WFS_ADMIN_USR", "SPATIAL_CSW_ADMIN_USR", "ANONYMOUS",
    "BI", "PM", "IX", "SH", "OE", "HR", "SCOTT", "DBSFWUSER", "GGSYS", "GG_CENTER",
    "REMOTE_SCHEDULER_AGENT", "GSMCATUSER", "MDDATA", "SYSBACKUP", "SYSDG", "SYSKM",
    "SYSRAC", "AUDSYS", "DVF", "ORDSYS", "GSMUSER", "ODM", "ODM_MTR", "TRACESVR",
    # 云/12c+ 新增内部模式（用户勾选时应排除，导了也没用还拖时间）
    "GSMROOTUSER", "SYS$UMF", "OJVMSYS", "PERFSTAT", "DBSFWUSER", "ORCL_BASE",
}

# 输出标记，供本地解析
MARK_FILE = "RESULT_FILE="
MARK_SIZE = "RESULT_SIZE="
MARK_DISK = "RESULT_DISKFREE_KB="
MARK_WORKDIR = "RESULT_WORKDIR="


def _sqlplus_env(cfg: dict) -> str:
    return (
        "export ORACLE_HOME=%s; "
        "export ORACLE_SID=%s; "
        'export PATH="$ORACLE_HOME/bin:$PATH"; '
        "export NLS_LANG=%s;"
        % (
            shell_quote(cfg.get("oracle_home", "")),
            shell_quote(cfg.get("oracle_sid", "")),
            shell_quote(cfg.get("nls_lang") or "AMERICAN_AMERICA.AL32UTF8"),
        )
    )


def build_connect_string(server_cfg: dict) -> str:
    """
    构造 expdp/sqlplus 连接串：
    - 配置了「数据库连接名」：user/pass@连接名（走监听器，如 //localhost:1521/zfdb）
    - 连接名留空：user/pass（本地 BEQ 连接，依赖 ORACLE_SID，服务器本地导出最可靠）
    """
    db_user = (server_cfg.get("db_user") or "").strip()
    db_password = server_cfg.get("db_password") or ""
    db_connect = (server_cfg.get("db_connect") or "").strip()
    if db_connect:
        return "%s/%s@%s" % (db_user, db_password, db_connect)
    return "%s/%s" % (db_user, db_password)


def probe_sql_path(ts: str) -> str:
    """目录对象探测 SQL 文件在服务器上的路径（与备份脚本同批上传）"""
    return "/tmp/.orabackup_%s.sql" % ts


# 不适合作为备份目录的目录对象名前缀（Oracle 内部用途）
_UNSAFE_DIR_NAME_PREFIXES = (
    "SDO_", "ORACLE_OCM", "XMLDIR", "XSDDIR", "OPATCH", "BFILE",
    "LOG_FILE", "ADMIN_DIR", "ORACLE_HOME", "ORACLE_BASE",
)

# 单个 dump 文件的分片大小（配合 %U 使用）：超过则自动开新文件
DUMP_FILESIZE = "8G"


def is_safe_backup_dir(name: str, path: str) -> bool:
    """判断目录对象是否适合作为备份目录。
    排除 Oracle 内部对象和危险路径（/ade、/、/root 等）——
    曾经因把 dump 写进 /ade（根分区）导致服务器磁盘写满。"""
    n = (name or "").upper()
    p = (path or "").rstrip("/")
    if not p or p == "/" or p.startswith("/ade") or p.startswith("/root"):
        return False
    for bad in _UNSAFE_DIR_NAME_PREFIXES:
        if n.startswith(bad):
            return False
    return True


def filter_safe_directories(dirs):
    """从 [(名称, 路径)] 列表中过滤出适合备份的目录对象"""
    return [d for d in dirs if is_safe_backup_dir(d[0], d[1])]


def build_probe_sql(cfg: dict, ts: str) -> str:
    """生成目录对象探测用的 SQL 文件内容（含单引号也安全，因为是文件而非 shell 内联）"""
    dir_name = (cfg["server"].get("directory_name") or "").strip() or "DATA_PUMP_DIR"
    safe_name = dir_name.replace("'", "''")  # SQL 单引号转义
    return (
        "set heading off feedback off pages 0 verify off lines 200\n"
        "SELECT directory_path FROM dba_directories WHERE directory_name='%s';\n"
        "exit;\n" % safe_name
    )


def _run_wrapper(server_cfg: dict, inner_command: str) -> str:
    """
    根据登录用户与 oracle 用户的关系，决定如何执行 inner_command。
    """
    method = (server_cfg.get("switch_method") or "auto").lower()
    ssh_user = (server_cfg.get("ssh_user") or "").strip()
    oracle_user = (server_cfg.get("oracle_user") or "").strip()

    if method == "direct" or not oracle_user or ssh_user == oracle_user:
        return "bash -c %s" % shell_quote(inner_command)

    if method == "sudo" or (method == "auto" and ssh_user != "root"):
        return "bash -c %s" % shell_quote(
            "sudo -u %s bash -c %s" % (oracle_user, shell_quote(inner_command))
        )

    # root 登录：su oracle -c '...'
    # 注意不使用 su -（登录 shell）：Oracle 环境变量由脚本自行 export 设置，
    # 无需登录环境；且部分服务器上 su - 会因 profile/PAM 问题失败或挂起。
    return "bash -c %s" % shell_quote(
        "su %s -c %s" % (oracle_user, shell_quote(inner_command))
    )


def build_backup_script(cfg: dict, ts: str, schema_sizes: dict = None) -> str:
    """
    生成在 Linux 服务器上执行的备份脚本：
    1. 设置 Oracle 环境变量
    2. 探测目录对象真实路径（sqlplus），失败则回退到配置路径
    3. expdp 导出指定 schemas
    4. tar+gzip（优先 pigz）压缩 dmp 和 log
    5. 删除 N 天前的远程备份
    6. 输出 RESULT_* 标记供本地解析

    schema_sizes: {SCHEMA_UPPER: bytes}，按用户分包时按数据量自动分配并行度
    """
    srv = cfg["server"]
    bak = cfg["backup"]
    school = sanitize_name(cfg.get("school_name", ""))
    schemas = [s for s in (bak.get("schemas") or []) if s]
    if not schemas:
        raise SSHError("尚未勾选需要导出的数据库用户（模式）")

    dump_dir = srv.get("dump_dir", "").strip() or ""
    dir_name = srv.get("directory_name", "").strip() or "DATA_PUMP_DIR"
    parallel = int(bak.get("parallel") or 1)
    keep_days = int(bak.get("remote_keep_days") or 0)
    compress = bool(bak.get("compress", True))
    # 排除优化器统计信息：大库上可占数 GB，且对数据恢复无意义
    # （恢复后执行 DBMS_STATS.GATHER_SCHEMA_STATS 重新收集即可）
    exclude_stats = bool(bak.get("exclude_statistics", True))
    # 按用户分包时按数据量自动分配并行度（小模式用低并行，避免大量碎片文件）
    auto_parallel = bool(bak.get("auto_parallel", True))
    connect_str = build_connect_string(srv)
    pack_mode = (bak.get("pack_mode") or "combined").lower()
    stats_clause = " EXCLUDE=STATISTICS" if exclude_stats else ""

    # dump 文件名必须带 %U：PARALLEL>1 时多个 worker 各写各的文件。
    # 若用固定文件名，所有 worker 抢写同一个文件，会在导出中途报
    # ORA-39095(Dump file space exhausted)——与磁盘实际剩余空间无关。
    # 分隔符用 .（Oracle 用户名不可能含点），避免 ZFSOFT_OA 与 ZFSOFT_OA_BPMX
    # 这类互为前缀的模式名在通配时误匹配。
    dumpfile = "bk_%s.%%U.dmp" % ts
    logfile = "bk_%s.log" % ts
    if compress:
        tarfile = "orabackup_%s_%s.tar.gz" % (school, ts)
    else:
        tarfile = "orabackup_%s_%s.tar" % (school, ts)

    lines = [
        "#!/bin/bash",
        "# Oracle 数据库备份脚本（由 OracleBackup 工具自动生成于 %s）" % ts,
        "set -o pipefail",
        _sqlplus_env(srv),
        "DUMPDIR=%s" % shell_quote(dump_dir),
        "DIRNAME=%s" % shell_quote(dir_name),
        "TS=%s" % shell_quote(ts),
        "DUMPFILE=%s" % shell_quote(dumpfile),
        "LOGFILE=%s" % shell_quote(logfile),
        "FILESIZE=%s" % DUMP_FILESIZE,
        "TARFILE=%s" % shell_quote(tarfile),
        "KEEP_DAYS=%d" % keep_days,
        "PARALLEL=%d" % parallel,
        "SCHOOL=%s" % shell_quote(school),
        "SCHEMAS=%s" % shell_quote(" ".join(schemas)),
        "EXPPID=\"\"",
        "# 脚本退出/被中断时杀掉 expdp 子进程（取消备份不会再留下僵尸进程占磁盘）",
        "_on_exit() { [ -n \"$EXPPID\" ] && kill \"$EXPPID\" 2>/dev/null; }",
        "trap _on_exit EXIT INT TERM HUP",
        "mkdir -p \"$DUMPDIR\" || { echo 'ERR: 无法创建目录 ' \"$DUMPDIR\"; exit 10; }",
        "",
        "# 探测目录对象真实路径（通过上传的 SQL 文件执行，失败则回退配置路径）",
        "DPPATH=$($ORACLE_HOME/bin/sqlplus -S / as sysdba @%s < /dev/null 2>/dev/null | tr -d ' \\r' | grep '^/' | head -n 1)" % shell_quote(probe_sql_path(ts)),
        "if [ -z \"$DPPATH\" ]; then",
        "  if [ -z \"$DUMPDIR\" ]; then",
        "    echo 'ERR: 未能探测到目录对象路径，且未配置导出目录。请在软件「数据库服务器」页配置「导出目录(OS路径)」'",
        "    exit 14",
        "  fi",
        "  DPPATH=\"$DUMPDIR\"",
        "fi",
        "WORKDIR=\"$DPPATH\"",
        "mkdir -p \"$WORKDIR\" || { echo 'ERR: 无法创建工作目录 ' \"$WORKDIR\"; exit 11; }",
        "cd \"$WORKDIR\" || exit 12",
        "",
        "# 安全检查 1：拒绝根分区与内存盘(tmpfs)——写满会搞垮系统",
        "FS_TYPE=$(df -PT \"$WORKDIR\" 2>/dev/null | awk 'NR==2{print $2}')",
        "FS_MOUNT=$(df -PT \"$WORKDIR\" 2>/dev/null | awk 'NR==2{print $7}')",
        "if [ \"$FS_MOUNT\" = \"/\" ]; then",
        "  echo \"ERR: 导出目录 $WORKDIR 位于根分区(/)，根分区写满会导致系统故障！请在软件中把目录对象改为指向独立分区的对象（如 /u01 上的目录）\"",
        "  exit 13",
        "fi",
        "if [ \"$FS_TYPE\" = \"tmpfs\" ]; then",
        "  echo \"ERR: 导出目录 $WORKDIR 位于内存盘(tmpfs)，会把内存写满！请改用磁盘上的目录对象\"",
        "  exit 13",
        "fi",
        "",
        "# 安全检查 2：磁盘空间（expdp 先写未压缩 dmp，约需数据量 1.2 倍）",
        "AVAIL_KB=$(df -P \"$WORKDIR\" 2>/dev/null | awk 'NR==2{print $4}')",
        "AVAIL_GB=$((AVAIL_KB/1024/1024))",
        "if [ -n \"$AVAIL_KB\" ] && [ \"$AVAIL_KB\" -lt 20971520 ] 2>/dev/null; then",
        "  echo \"[orabackup] 警告：目标目录剩余空间不足 ${AVAIL_GB} GB，大数据量导出可能失败(ORA-39095)\"",
        "fi",
        "echo \"RESULT_WORKDIR=$WORKDIR\"",
        "echo \"RESULT_FSMOUNT=$FS_MOUNT\"",
        "echo \"RESULT_FSTYPE=$FS_TYPE\"",
        "",
    ]

    if pack_mode == "per_schema":
        # ---------- 按用户分别导出：每个模式一个 expdp + 一个 tar.gz ----------
        # 并行度按数据量自动分配：DUMPFILE 带 %U 后每个 worker 各写各的文件，
        # 小模式用高并行度会产生大量碎片文件（16 个 worker → 最多 16 个 dmp）。
        lines += [
            "echo \"[orabackup] $(date '+%%F %%T') 开始按用户分别导出: $SCHEMAS\"",
            "GZ=gzip",
            "if command -v pigz >/dev/null 2>&1; then GZ=pigz; fi",
            "FAILED=0; EXPORTED=0; FAILED_LIST=\"\"",
        ]
        # 生成按数据量分档的并行度查询函数
        if auto_parallel and schema_sizes:
            GB = 1024 ** 3
            band_full, band_4, band_2 = [], [], []
            for s in schemas:
                size = schema_sizes.get(s.upper(), 0)
                if size >= 20 * GB:
                    band_full.append(s)
                elif size >= 5 * GB:
                    band_4.append(s)
                elif size >= GB:
                    band_2.append(s)
            lines += [
                "# 按模式数据量自动分配并行度（小模式用低并行，避免大量碎片 dump）",
                "parallel_for() {",
                "  case \"$1\" in",
            ]
            if band_full:
                lines.append("    %s) echo %d;;" % ("|".join(band_full), max(1, parallel)))
            if band_4:
                lines.append("    %s) echo %d;;" % ("|".join(band_4), max(1, min(parallel, 4))))
            if band_2:
                lines.append("    %s) echo %d;;" % ("|".join(band_2), max(1, min(parallel, 2))))
            lines += [
                "    *) echo 1;;",
                "  esac",
                "}",
            ]
        lines += [
            "for S in $SCHEMAS; do",
            "  echo \"[orabackup] 正在导出用户 $S ...\"",
            "  SP=$(parallel_for \"$S\" 2>/dev/null || echo $PARALLEL)",
            "  expdp %s SCHEMAS=\"$S\" DIRECTORY=\"$DIRNAME\" DUMPFILE=\"bk_${TS}.${S}.%%U.dmp\" LOGFILE=\"bk_${TS}.${S}.log\" PARALLEL=$SP FILESIZE=$FILESIZE%s &" % (shell_quote(connect_str), stats_clause),
            "  EXPPID=$!",
            "  wait \"$EXPPID\"",
            "  RC=$?",
            "  EXPPID=\"\"",
            "  if [ $RC -ne 0 ]; then",
            "    echo \"ERR: 用户 $S 导出失败，退出码 $RC（继续导出其他用户）\"",
            "    tail -n 30 \"bk_${TS}.${S}.log\" 2>/dev/null",
            "    rm -f bk_${TS}.${S}.*.dmp \"bk_${TS}.${S}.log\"",
            "    FAILED=$((FAILED+1)); FAILED_LIST=\"$FAILED_LIST $S\"",
            "    continue",
            "  fi",
        ]
        if compress:
            lines += [
                "  tar -cf - bk_${TS}.${S}.*.dmp \"bk_${TS}.${S}.log\" | $GZ -c > \"orabackup_${SCHOOL}_${S}_${TS}.tar.gz\"",
                "  RC=$?",
                "  if [ $RC -ne 0 ]; then echo \"ERR: 用户 $S 压缩失败\"; FAILED=$((FAILED+1)); FAILED_LIST=\"$FAILED_LIST $S\"; continue; fi",
                "  rm -f bk_${TS}.${S}.*.dmp \"bk_${TS}.${S}.log\"",
                "  SZ=$(stat -c %s \"orabackup_${SCHOOL}_${S}_${TS}.tar.gz\" 2>/dev/null || echo 0)",
                "  echo \"RESULT_FILE_${S}=orabackup_${SCHOOL}_${S}_${TS}.tar.gz\"",
                "  echo \"RESULT_SIZE_${S}=$SZ\"",
            ]
        else:
            lines += [
                "  tar -cf \"orabackup_${SCHOOL}_${S}_${TS}.tar\" bk_${TS}.${S}.*.dmp \"bk_${TS}.${S}.log\"",
                "  RC=$?",
                "  if [ $RC -ne 0 ]; then echo \"ERR: 用户 $S 打包失败\"; FAILED=$((FAILED+1)); FAILED_LIST=\"$FAILED_LIST $S\"; continue; fi",
                "  rm -f bk_${TS}.${S}.*.dmp \"bk_${TS}.${S}.log\"",
                "  SZ=$(stat -c %s \"orabackup_${SCHOOL}_${S}_${TS}.tar\" 2>/dev/null || echo 0)",
                "  echo \"RESULT_FILE_${S}=orabackup_${SCHOOL}_${S}_${TS}.tar\"",
                "  echo \"RESULT_SIZE_${S}=$SZ\"",
            ]
        lines += [
            "  EXPORTED=$((EXPORTED+1))",
            "  echo \"[orabackup] 用户 $S 完成（$SZ 字节）\"",
            "done",
            "echo \"RESULT_EXPORTED=$EXPORTED\"",
            "echo \"RESULT_FAILED=$FAILED\"",
            "echo \"RESULT_FAILED_LIST=$FAILED_LIST\"",
        ]
    else:
        # ---------- 全部打包成一个文件（默认） ----------
        lines += [
            "echo \"[orabackup] $(date '+%%F %%T') 开始 Data Pump 导出: SCHEMAS=%s\"" % ",".join(schemas),
            "expdp %s SCHEMAS=%s DIRECTORY=\"$DIRNAME\" DUMPFILE=\"$DUMPFILE\" LOGFILE=\"$LOGFILE\" PARALLEL=$PARALLEL FILESIZE=$FILESIZE%s &" % (
                shell_quote(connect_str), ",".join(schemas), stats_clause),
            "EXPPID=$!",
            "wait \"$EXPPID\"",
            "RC=$?",
            "EXPPID=\"\"",
            "if [ $RC -ne 0 ]; then",
            "  echo \"ERR: expdp 导出失败，退出码 $RC\"",
            "  tail -n 60 \"$LOGFILE\" 2>/dev/null",
            "  exit 20",
            "fi",
            "echo '[orabackup] 导出完成，开始压缩...'",
        ]
        if compress:
            lines += [
                "GZ=gzip",
                "if command -v pigz >/dev/null 2>&1; then GZ=pigz; fi",
                "tar -cf - bk_${TS}.*.dmp \"$LOGFILE\" | $GZ -c > \"$TARFILE\"",
                "RC=$?",
                "if [ $RC -ne 0 ]; then echo 'ERR: 压缩失败'; exit 21; fi",
                "rm -f bk_${TS}.*.dmp \"$LOGFILE\"",
            ]
        else:
            lines += [
                "tar -cf \"$TARFILE\" bk_${TS}.*.dmp \"$LOGFILE\"",
                "RC=$?",
                "if [ $RC -ne 0 ]; then echo 'ERR: 打包失败'; exit 21; fi",
                "rm -f bk_${TS}.*.dmp \"$LOGFILE\"",
            ]

    lines += [
        "",
        "# 清理远程 N 天前的备份",
        "if [ \"$KEEP_DAYS\" -gt 0 ] 2>/dev/null; then",
        "  echo \"[orabackup] 清理 ${KEEP_DAYS} 天前的远程备份...\"",
        "  find \"$WORKDIR\" -maxdepth 1 -type f -name 'orabackup_*.tar.gz' -mtime +$KEEP_DAYS -print -delete",
        "  find \"$WORKDIR\" -maxdepth 1 -type f -name 'orabackup_*.tar' -mtime +$KEEP_DAYS -print -delete",
        "  find \"$WORKDIR\" -maxdepth 1 -type f -name 'orabackup_*.dmp' -mtime +$KEEP_DAYS -print -delete",
        "fi",
        "",
        "DFREE=$(df -P \"$WORKDIR\" | awk 'NR==2{print $4}')",
        "echo \"RESULT_DISKFREE_KB=$DFREE\"",
    ]
    if pack_mode != "per_schema":
        lines += [
            "SIZE=$(stat -c %s \"$TARFILE\" 2>/dev/null || echo 0)",
            "echo \"RESULT_FILE=$TARFILE\"",
            "echo \"RESULT_SIZE=$SIZE\"",
        ]
    lines += [
        "echo '[orabackup] 远程处理完成'",
        "exit 0",
    ]
    return "\n".join(lines) + "\n"


def build_run_command(server_cfg: dict, script_path: str, use_sudo_password: bool = False) -> str:
    """生成最终在 SSH 上执行的命令"""
    inner = "bash %s" % shell_quote(script_path)
    return _run_wrapper(server_cfg, inner)


def build_query_command(server_cfg: dict, sql: str, as_user: bool = False) -> str:
    """
    通过 sqlplus 执行查询的命令。
    as_user=False：/ as sysdba（OS 认证，dba_users 全量列表）
    as_user=True ：用配置的导出用户连接（all_users，兼容 OS 认证未开启/CDB+PDB 环境）
    注意：stderr 合并到 stdout（2>&1），确保 ORA- 错误能反馈给用户而不是被丢弃。
    SQL 通过 shell 变量传递（先 shell_quote 赋值再 printf 取值），
    避免 SQL 中的单引号破坏命令引号结构。
    """
    if as_user:
        connect = shell_quote(build_connect_string(server_cfg))
    else:
        connect = "/ as sysdba"
    inner = (
        "%s SQL=%s; printf 'set heading off feedback off pages 0 verify off lines 200\\n%%s\\n' \"$SQL\" | "
        "$ORACLE_HOME/bin/sqlplus -S %s 2>&1"
        % (_sqlplus_env(server_cfg), shell_quote(sql), connect)
    )
    return _run_wrapper(server_cfg, inner)


def _extract_error(output: str) -> str:
    """从 sqlplus 输出中提取第一行 ORA-/SP2-/ERROR 信息"""
    for line in (output or "").splitlines():
        line = line.strip()
        if "ORA-" in line or "ERROR" in line.upper() or "SP2-" in line:
            return line[:200]
    return ""


def _has_oracle_error(output: str) -> bool:
    text = (output or "").upper()
    return "ORA-" in text or "ERROR:" in text or "SP2-" in text


def parse_db_users(output: str):
    """从 sqlplus 输出中解析用户名列表"""
    users = []
    for line in (output or "").splitlines():
        name = line.strip()
        if not name or name.upper() in ("SQL>", "CONNECTED", "DISCONNECTED"):
            continue
        if re.match(r"^[A-Za-z0-9_$#]+$", name) and not name.startswith("--"):
            users.append(name)
    # 去重并排序
    seen, result = set(), []
    for u in users:
        if u.upper() not in seen:
            seen.add(u.upper())
            result.append(u)
    return sorted(result, key=lambda x: x.upper())


def query_db_users(ssh: SSHConnection, server_cfg: dict):
    """
    查询服务器上可导出的数据库用户。
    优先 / as sysdba（dba_users 全量）；失败时回退到配置的导出用户连接
    （all_users），兼容 OS 认证未开启、CDB+PDB 等环境。
    两种方式都失败时抛出带真实错误信息的异常。
    """
    errors = []

    # 方式一：OS 认证 + dba_users（列表最全）
    try:
        out = ssh.output_of(
            build_query_command(server_cfg,
                                "SELECT username FROM dba_users ORDER BY username;"),
            timeout=120)
        users = parse_db_users(out)
        if users:
            log_info("获取到 %d 个数据库用户（sysdba/dba_users）" % len(users))
            return users
        if _has_oracle_error(out):
            errors.append(_extract_error(out) or "sqlplus / as sysdba 连接失败")
    except Exception as exc:
        errors.append(str(exc))

    # 方式二：导出用户连接 + all_users（兼容 OS 认证未开启、PDB 环境）
    try:
        out = ssh.output_of(
            build_query_command(server_cfg,
                                "SELECT username FROM all_users ORDER BY username;",
                                as_user=True),
            timeout=120)
        users = parse_db_users(out)
        if users:
            log_info("获取到 %d 个数据库用户（导出用户连接/all_users）" % len(users))
            return users
        if _has_oracle_error(out):
            errors.append(_extract_error(out) or "导出用户连接查询失败")
    except Exception as exc:
        errors.append(str(exc))

    detail = "；".join(dict.fromkeys(e for e in errors if e)) or "sqlplus 没有任何输出"
    raise SSHError(
        "无法获取数据库用户列表。\n服务器返回：%s\n\n"
        "排查建议：\n"
        "1. 在服务器上执行 su oracle -c \"$ORACLE_HOME/bin/sqlplus / as sysdba\" "
        "验证 OS 认证是否可用\n"
        "2. 检查 oracle 用户是否在 dba 组：groups oracle\n"
        "3. 检查 ORACLE_HOME / ORACLE_SID / 导出用户密码是否配置正确\n"
        "4. 检查 sqlnet.ora 中 SQLNET.AUTHENTICATION_SERVICES（应为 ALL 或 NTS）"
        % detail)


def estimate_schema_sizes(ssh: SSHConnection, server_cfg: dict, schemas) -> dict:
    """
    估算各 schema 的数据量（MB），用于备份前空间评估。
    返回 {schema_upper: bytes}。失败返回空 dict（不阻塞备份）。
    """
    if not schemas:
        return {}
    schema_list = "','".join(s.replace("'", "''") for s in schemas)
    sql = (
        "SELECT owner, SUM(bytes) FROM dba_segments "
        "WHERE owner IN ('%s') GROUP BY owner;" % schema_list
    )
    cmd = build_query_command(server_cfg, sql)
    try:
        out = ssh.output_of(cmd, timeout=120)
    except Exception:
        return {}
    sizes = {}
    for line in out.splitlines():
        line = line.strip()
        if not line or line.upper().startswith(("SELECT", "SET ", "SQL>")):
            continue
        parts = line.split()
        # owner 可能含空格？通常不会；取最后一个 token 作为数值
        if len(parts) >= 2:
            owner = parts[0].upper()
            try:
                value = int(float(parts[-1]))
                if value > 0:
                    sizes[owner] = value
            except ValueError:
                continue
    return sizes


def query_schema_sizes(ssh: SSHConnection, server_cfg: dict, schemas) -> str:
    """返回人类可读的 schema 大小说明（供测试连接/备份前展示）"""
    sizes = estimate_schema_sizes(ssh, server_cfg, schemas)
    if not sizes:
        return ""
    from .utils import format_size
    lines = []
    total = sum(sizes.values())
    for name in sorted(sizes, key=lambda k: -sizes[k]):
        lines.append("  %s：%s" % (name, format_size(sizes[name])))
    lines.append("  合计（未压缩前）：%s" % format_size(total))
    return "\n".join(lines)


def query_directory_path(ssh: SSHConnection, server_cfg: dict, dir_name: str = None):
    """查询 Oracle 目录对象对应的真实 OS 路径"""
    name = (dir_name or server_cfg.get("directory_name") or "").strip()
    if not name:
        return ""
    sql = "SELECT directory_path FROM dba_directories WHERE directory_name='%s';" % name
    cmd = build_query_command(server_cfg, sql)
    out = ssh.output_of(cmd, timeout=60)
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("/"):
            return line
    return ""


def query_directories(ssh: SSHConnection, server_cfg: dict):
    """查询所有目录对象 [(名称, 路径), ...]，供测试连接展示与界面下拉选择。
    使用 || 拼接到单列，避免多列输出格式不确定导致解析失败。"""
    sql = ("SELECT directory_name || '|' || directory_path "
           "FROM dba_directories ORDER BY directory_name;")
    cmd = build_query_command(server_cfg, sql)
    out = ssh.output_of(cmd, timeout=60)
    result = []
    for line in out.splitlines():
        line = line.strip()
        if "|" not in line or line.upper().startswith(("SELECT", "SET ", "SQL>")):
            continue
        name, _, path = line.partition("|")
        name = name.strip()
        path = path.strip()
        if name and path.startswith("/"):
            result.append((name, path))
    return result


def parse_result_markers(output: str) -> dict:
    """从备份脚本输出中解析 RESULT_* 标记（支持按用户分包的 RESULT_FILE_xxx 等）"""
    result = {}
    for line in (output or "").splitlines():
        line = line.strip()
        if not line.startswith("RESULT_"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key] = value.strip()
    return result


def detect_expdp_error(output: str) -> str:
    """检测 expdp 常见错误，返回人类可读的原因说明"""
    text = output or ""
    errors = []
    if "ORA-39002" in text or "ORA-39001" in text:
        errors.append("Data Pump 参数错误")
    if "ORA-01017" in text or "invalid username/password" in text.lower():
        errors.append("数据库用户名或密码错误")
    if "ORA-39070" in text:
        errors.append("日志文件无法打开")
    if "ORA-39087" in text:
        errors.append("目录名或文件名无效")
    if "ORA-39095" in text or "space has been exhausted" in text:
        errors.append("导出目标磁盘空间不足（ORA-39095）——请更换目录对象到空间充足的磁盘"
                      "（点「测试连接并检测环境」可查看各目录剩余空间）")
    if "ORA-12154" in text:
        errors.append("连接名无法解析（ORA-12154）——tnsnames 中没有该服务名，"
                      "建议「数据库连接名」留空使用本地 BEQ 连接")
    if "ORA-12514" in text:
        errors.append("监听器不识别该服务名（ORA-12514）——请核对数据库连接名/端口")
    if "ORA-01031" in text or "insufficient privileges" in text.lower():
        errors.append("权限不足（导出用户需要相应模式的导出权限）")
    if "command not found" in text:
        errors.append("服务器上找不到 expdp，请检查 ORACLE_HOME 配置")
    if "Permission denied" in text:
        errors.append("目录无权限创建或写入——请更换导出目录/目录对象"
                      "（root 登录时工具会自动创建目录）")
    if "No such file or directory" in text:
        errors.append("路径不存在，请检查服务器导出目录配置")
    if errors:
        return "；".join(dict.fromkeys(errors))
    return ""

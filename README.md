# Oracle 数据库备份工具（OracleBackup）

一个运行在 **Windows** 上的 Oracle 数据库自动备份软件：通过 SSH 连接 Linux 数据库服务器，在服务器本地执行 Data Pump（expdp）导出并压缩，自动清理过期文件，下载到 Windows 本地并按保留策略自动清理，支持 **PushPlus / 邮件 / 钉钉机器人** 通知，支持 **定时备份** 与 **开机自启动**。

## 📦 项目地址与下载

- **项目地址**：https://github.com/1040663308/oracle-backup-tool
- **下载地址**（安装包）：https://github.com/1040663308/oracle-backup-tool/releases
  - 下载 `OracleBackup_安装包_vX.Y.Z.zip`，解压后双击 `OracleBackup_Setup_vX.Y.Z.exe` 安装
  - ZIP 内附 `校验说明.txt`（含 SHA256），下载后建议核对校验值防损坏

## 功能特性

| 功能 | 说明 |
| --- | --- |
| 服务器配置 | 配置 Linux 服务器 SSH 地址、端口、用户、密码/密钥 |
| 本地导出压缩 | 在服务器上执行 `expdp` 导出勾选的用户（模式），自动 `tar.gz` 压缩（优先 pigz） |
| 按用户分包 | 可选每个用户一个备份包（恢复更灵活，单个失败不影响其他用户） |
| 并行导出 | `DUMPFILE` 自动 `%U` 分片 + `FILESIZE` 限片，并行度按数据量自动分配（小模式低并行，避免碎片文件） |
| 排除统计信息 | 默认 `EXCLUDE=STATISTICS`（大库省数 GB，恢复后可重新收集） |
| 勾选导出用户 | 复选框式勾选（带搜索过滤/全选/反选/已选计数），系统内置账户自动排除 |
| 安全防护 | 目录对象过滤 Oracle 内部对象与危险路径；拒绝根分区/内存盘(tmpfs)；备份前空间预检（估算×1.2 vs 剩余，不足即中止）；root 自动创建导出目录；取消备份自动杀 expdp |
| 远程清理 | 自动删除服务器上 N 天前的导出文件（可配置） |
| 本地下载 | 通过 SFTP 下载到 Windows，路径可配置，带进度显示 |
| 本地保留策略 | 超过保留天数（如 30 天）的备份自动删除；本地路径显示剩余空间与可存天数 |
| 定时备份 | 每天定时执行，可勾选星期；关机错过时开机后自动补跑 |
| 消息通知 | PushPlus（推送加）、邮件（SMTP/SSL）、钉钉机器人（支持加签） |
| 通知内容 | 成功/失败/**有异常**三态（部分失败、空间偏小等异常也提醒）；含文件大小、耗时、服务器/本地磁盘剩余 |
| 完成提示 | 手动备份完成弹窗告知结果；状态栏分阶段显示（导出中/压缩中/下载中） |
| 开机自启动 | 一键写入当前用户注册表启动项，可最小化启动 |
| 运行日志 | 实时日志（批量刷新不卡界面）+ 滚动文件日志，可导出 |

## 目录结构

```
备份软件/
├── run.py                  # 程序入口
├── orabackup.spec          # PyInstaller 打包配置
├── installer.iss           # Inno Setup 安装包脚本
├── build.bat               # 一键打包 EXE
├── build_installer.bat     # 一键编译安装包
├── requirements.txt        # 依赖清单
├── config.example.json     # 示例配置
├── app/                    # 核心逻辑（SSH/导出/清理/通知/调度/自启动）
├── gui/                    # tkinter 图形界面
├── tests/                  # 单元测试
└── tools/                  # 图标生成等辅助脚本
```

## 环境要求

- Windows 7 / 10 / 11 或 Windows Server
- Python 3.10+（**完整安装版**，需含 tkinter；embeddable 版缺少 tkinter 无法运行）
- Linux 数据库服务器：Oracle 11g+，开放 SSH，安装 Data Pump（expdp/sqlplus）

## 快速开始

### 方式一：直接使用安装包（推荐）

从 [Releases](https://github.com/1040663308/oracle-backup-tool/releases) 下载 `OracleBackup_安装包_vX.Y.Z.zip`（约 12MB），核对 ZIP 内 `校验说明.txt` 中的 SHA256 后解压安装：

- 双击 `OracleBackup_Setup_vX.Y.Z.exe`，默认安装到 `C:\Program Files\OracleBackup\`（可自定义目录）
- 自动创建开始菜单快捷方式和卸载项，安装界面为简体中文
- 支持完整卸载（控制面板 / 设置中的应用列表）

### 方式二：直接运行绿色版

`dist\OracleBackup\OracleBackup.exe` 为免安装版本，双击即用，配置保存到
`%APPDATA%\OracleBackup\config.json`，整个 `dist\OracleBackup\` 目录可一起拷贝分发。

### 方式三：自行重新打包

```bat
build.bat             :: 打包 dist\OracleBackup\（需要 Python 3.10+ 完整版）
build_installer.bat   :: 编译安装包 dist_installer\OracleBackup_Setup_v1.0.0.exe
```

`build_installer.bat` 需要本机已安装 [Inno Setup 6/7](https://jrsoftware.org/isdl.php)
（本项目已用 Inno Setup 6.7.3 编译验证；中文语言文件已随项目附带在
`assets\languages\ChineseSimplified.isl`，任何机器均可编译）。

### 开发模式运行

```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run.py
```

### 运行测试

```bat
.venv\Scripts\python.exe tests\test_core.py         :: 78 个单元测试
.venv\Scripts\python.exe tests\test_integration.py  :: 5 个端到端集成测试（本地 bash 模拟服务器全流程）
```

## 服务器端准备（Linux）

### 1. 确认 Oracle 用户与环境

备份脚本默认以 `oracle` 用户执行，需要能访问 `expdp`/`sqlplus`。在「数据库服务器」页填写：

- **ORACLE_HOME**：如 `/u01/app/oracle/product/19.0.0/dbhome_1`
- **ORACLE_SID**：如 `ORCL`
- **导出用户 / 密码**：建议使用 `system`，并确保具有导出权限：

```sql
-- 以 sysdba 执行：授予导出权限（如使用专用备份用户）
GRANT DATAPUMP_EXP_FULL_DATABASE TO backup_user;
-- 如导出指定模式，还需：
GRANT EXP_FULL_DATABASE TO backup_user;
```

### 2. 创建目录对象（Directory）

```sql
-- 以 sysdba 执行
CREATE OR REPLACE DIRECTORY DATA_PUMP_DIR AS '/opt/oracle/backup';
GRANT READ, WRITE ON DIRECTORY DATA_PUMP_DIR TO system;
```

并在服务器上创建对应目录并授权：

```bash
mkdir -p /opt/oracle/backup
chown oracle:oinstall /opt/oracle/backup
chmod 755 /opt/oracle/backup
```

> 工具会在备份时自动用 `sqlplus` 探测目录对象的真实路径；如果探测失败，则使用界面上配置的「导出目录(OS路径)」。

### 3. SSH 用户与切换方式

| SSH 登录用户 | 切换方式 | 说明 |
| --- | --- | --- |
| `root` | su（默认 auto） | 自动使用 `su - oracle -c` 执行，无需额外配置 |
| `oracle` | 直连（默认 auto） | 登录用户即 oracle 用户，直接执行 |
| 其他用户 | sudo | 需配置免密 sudo，或在界面填写 sudo 密码 |

非 root 用户免密 sudo 配置示例（`/etc/sudoers.d/orabackup`）：

```text
backupadmin ALL=(oracle) NOPASSWD: /bin/bash
```

### 4. 字符集建议

中文数据库建议 `NLS_LANG=AMERICAN_AMERICA.AL32UTF8`（界面默认值）；
若数据库字符集为 `ZHS16GBK`，可相应设置为 `AMERICAN_AMERICA.ZHS16GBK`，避免导出乱码。

## 配置说明

配置保存在 `%APPDATA%\OracleBackup\config.json`（安装版），开发模式保存在项目根目录。

| 页签 | 关键配置 |
| --- | --- |
| 数据库服务器 | 学校名称、SSH 地址/端口/用户/密码（或密钥）、oracle 用户、ORACLE_HOME/SID、导出用户与密码、NLS_LANG、目录对象名、导出目录。**数据库连接名可留空**（本地 BEQ 连接，推荐）或填 `//localhost:1521/服务名` |
| 备份策略 | 勾选导出用户、服务器保留天数、本地备份路径、本地保留天数、导出并行度、压缩开关、定时时间与星期 |
| 消息通知 | PushPlus Token、SMTP 服务器/端口/账号/授权码/收件人、钉钉 Webhook 与加签密钥 |
| 系统设置 | 开机自启动、启动最小化、成功/失败通知开关 |

### 通知渠道获取方式

- **PushPlus（推送加）**：打开 <https://www.pushplus.plus>，微信扫码登录，在「个人中心」复制 Token；一对多推送可填群组编码。
- **钉钉机器人**：群设置 → 智能群助手 → 添加机器人 → 选「自定义（Custom机器人）」→ 安全设置选「加签」，复制 Webhook 与 SEC 开头的密钥。
- **邮件**：以 QQ 邮箱为例，SMTP 服务器 `smtp.qq.com`、端口 `465`、开启 SSL，密码处填写**授权码**（非登录密码）。

## 备份流程与文件命名

1. SSH 连接服务器，上传并执行自动生成的备份脚本；
2. `expdp` 导出勾选模式 → `tar.gz` 压缩（dmp + log 一起打包）；
3. 删除服务器上超过保留天数的旧备份；
4. SFTP 下载到本地目录，删除本地超过保留天数的旧备份；
5. 汇总信息并发送通知。

文件命名：

- 全部打包模式：`orabackup_<学校名称>_<时间戳>.tar.gz`，如
  `orabackup_某某市第一中学_20261023_020015.tar.gz`
- 按用户分包模式：`orabackup_<学校名称>_<用户名>_<时间戳>.tar.gz`，如
  `orabackup_某某市第一中学_ZFSOFT_OA_20261023_020015.tar.gz`（每个用户一个包）

## 通知消息示例

```text
✅ Oracle 数据库备份成功
━━━━━━━━━━━━━━━━
🏫 学校名称：某某市第一中学
🖥 服务器：10.0.0.5 (ORCL)
📅 备份日期：2026-10-23 02:00:15
📦 备份文件：orabackup_某某市第一中学_20261023_020015.tar.gz
📏 文件大小：1.85 GB
⏱ 备份耗时：12分34秒
💾 服务器磁盘剩余：50.00 GB（/opt/oracle/backup）
💻 本地磁盘剩余：120.00 GB（D:\OracleBackup）
```

## 定时与开机自启动

- **定时备份**：在「备份策略」设置执行时间（如 02:00）与星期；程序需保持运行，到点自动执行。
- **补跑机制**：若计划执行时计算机关机，下次开机后会自动补跑当天备份（每天最多一次；手动「立即备份」成功后当天也不再自动跑）。
- **开机自启动**：在「系统设置」勾选后自动写入注册表
  `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run`；
  打包为 exe 后开机自动启动程序，可配合「启动时最小化」使用。

## 常见问题

**1. expdp 报 ORA-39002 / ORA-39070？**
检查目录对象是否存在、路径是否有写权限；确认 `DIRECTORY` 参数名与界面「目录对象名」一致。

**2. 报 ORA-01031: insufficient privileges？**
导出用户缺少 Data Pump 权限，见上文 SQL 授权语句。

**3. 报 ORA-01017: invalid username/password？**
导出用户/密码错误；注意密码中的特殊字符已做转义，如仍有问题可先在服务器上手工执行 expdp 验证。

**4. 连接提示 command not found: expdp？**
ORACLE_HOME 配置错误；SSH 登录后执行 `ls $ORACLE_HOME/bin/expdp` 验证路径。

**5. 导出的数据乱码？**
调整 NLS_LANG 与数据库字符集保持一致。

**6. 非 root 用户执行失败？**
配置免密 sudo（见上文）或在界面填写 sudo 密码。

**7. 定时没有执行？**
确认程序保持运行（可开启开机自启动）、「启用定时备份」已勾选、当天尚未执行过（手动备份成功后当天不再重复）。

**8. 杀毒软件误报？**
PyInstaller 单文件/目录打包的程序偶有误报，可加入白名单；分发建议使用 Inno Setup 安装包并做代码签名（可选）。

**9. 「获取用户列表」为 0 个或失败？**
软件会依次尝试两种方式：① `sqlplus / as sysdba` 查 `dba_users`（列表最全）；
② 用「导出用户」连接查 `all_users`（兼容 OS 认证未开启的环境）。
两者都失败时会弹出**服务器返回的真实错误**（ORA- 编号）。

> **最常见原因是 ORACLE_HOME 配错**：很多服务器真实路径是
> `/u01/app/oracle/product/<版本>/db`，而不是直觉上的 `dbhome_1`。
> 「测试连接并检测环境」会校验 sqlplus/expdp 是否存在、实例进程是否运行、
> 并列出所有可用目录对象——配置前先跑一次测试连接即可避免绝大多数问题。

- **在服务器上手动验证 OS 认证**：
  ```bash
  su oracle -c "$ORACLE_HOME/bin/sqlplus / as sysdba"
  ```
  若报 `ORA-01031`/`ORA-01017`：执行 `groups oracle` 确认在 `dba` 组；
  检查 `$ORACLE_HOME/network/admin/sqlnet.ora` 中
  `SQLNET.AUTHENTICATION_SERVICES`（应为 `ALL` 或 `NTS`）。
- **能查到用户但全是系统账户**：说明连接到了 CDB 根容器，
  把「数据库连接名」改为 PDB 服务名（`select name from v$pdbs;` 查询，如 `ORCLPDB1`）。
- **报 command not found**：ORACLE_HOME 配置错误，在服务器上
  `ls $ORACLE_HOME/bin/sqlplus` 验证路径，或 `cat /etc/oratab` 查看真实路径。

## 恢复备份

备份产物是 tar.gz（内含 expdp 导出的 `.dmp` 分片与 `.log`）。恢复步骤：

```bash
# 1. 传到服务器并解压
tar xzf orabackup_xxx.tar.gz

# 2. 导入（%U 自动读取全部分片；按用户分包则解压对应用户的包后单用户导入）
impdp system/密码 SCHEMAS=用户名 DIRECTORY=DATA_PUMP_DIR \
      DUMPFILE=bk_20261023_020015.%U.dmp LOGFILE=imp.log

# 3. （可选）恢复优化器统计
#    expdp 导出时默认 EXCLUDE=STATISTICS，导入后重新收集：
#    exec DBMS_STATS.GATHER_SCHEMA_STATS('用户名');
```

> `DUMPFILE` 的 `%U` 必须与导出时一致（导出文件名形如 `bk_时间戳.01.dmp`、
> `bk_时间戳.02.dmp`…），impdp 会自动按编号拼接全部分片。

## 安全说明

- `config.json` 中以明文保存服务器与数据库密码，请妥善保管配置文件所在目录（`%APPDATA%\OracleBackup`），必要时通过文件系统权限限制访问。
- 建议为备份创建**专用低权限数据库用户**（仅授予所需模式的导出权限），避免使用高权限账号。

## 技术栈

- Python 3 + tkinter（GUI）
- paramiko（SSH/SFTP）
- Oracle Data Pump（expdp/sqlplus，服务器端）
- PyInstaller（exe 打包）+ Inno Setup（安装包）

## 📅 更新记录

完整变更记录见 [CHANGELOG.md](CHANGELOG.md)。版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)：
主版本.次版本.修订号（功能新增进次版本，缺陷修复进修订号），每次发布同步打 Git 标签。

## 📜 版权

Copyright (c) 2026 我爱向日葵的执着. All rights reserved.

本软件版权归「我爱向日葵的执着」所有，保留一切权利，详见 [LICENSE](LICENSE)。
未经版权人书面许可，不得复制、修改、分发或用于商业用途；仅供授权单位内部备份业务使用。

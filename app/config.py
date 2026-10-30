# -*- coding: utf-8 -*-
"""配置管理：默认配置、加载、保存、合并"""
from __future__ import annotations

import copy
import json
import os

from . import paths

DEFAULT_CONFIG = {
    # 学校名称（用于通知消息与备份文件名）
    "school_name": "XX学校",
    # 数据库服务器（Linux）配置
    "server": {
        "host": "192.168.1.10",
        "port": 22,
        "ssh_user": "root",
        "auth_type": "password",          # password | key
        "password": "",
        "key_file": "",
        "key_passphrase": "",
        "oracle_user": "oracle",           # 服务器上运行 expdp 的系统用户
        "switch_method": "auto",           # auto(同用户直连/root用su/其他用sudo) | su | sudo | direct
        "sudo_password": "",
        "oracle_home": "/u01/app/oracle/product/19.0.0/dbhome_1",
        "oracle_sid": "ORCL",
        "db_connect": "ORCL",              # expdp 连接串 @后面的服务名/SID
        "db_user": "system",               # 执行导出的数据库用户
        "db_password": "",
        "nls_lang": "AMERICAN_AMERICA.AL32UTF8",
        "directory_name": "DATA_PUMP_DIR", # Oracle 目录对象名
        "dump_dir": "/opt/oracle/backup",  # 目录对象对应的 OS 路径（自动探测后可校正）
    },
    # 备份配置
    "backup": {
        "schemas": [],                     # 需要导出的用户/模式（勾选）
        "remote_keep_days": 3,             # 服务器上保留最近几天的导出文件
        "local_path": "D:\\OracleBackup",  # 下载到 Windows 的路径
        "local_keep_days": 30,             # 本地保留天数，超出自动删除
        "schedule_enabled": True,          # 启用定时备份
        "schedule_time": "02:00",          # 每天执行时间 HH:MM
        "schedule_days": [0, 1, 2, 3, 4, 5, 6],  # 0=周一 ... 6=周日
        "parallel": 1,                     # expdp PARALLEL 并行度
        "auto_parallel": True,             # 按用户分包时按数据量自动分配并行度
        "compress": True,                  # 压缩开关（关闭则不打包 tar.gz）
        "exclude_statistics": True,        # 排除优化器统计信息（减小体积，恢复后可重新收集）
        "pack_mode": "combined",           # combined=全部一个包 | per_schema=按用户分包
    },
    # 通知配置
    "notify": {
        "pushplus": {"enabled": False, "token": "", "topic": ""},
        "email": {
            "enabled": False,
            "smtp": "smtp.qq.com",
            "port": 465,
            "ssl": True,
            "user": "",
            "password": "",
            "from_addr": "",
            "to_addr": "",
        },
        "dingtalk": {"enabled": False, "webhook": "", "secret": ""},
    },
    # 系统设置
    "system": {
        "autostart": False,          # 开机自启动
        "start_minimized": False,    # 启动时最小化
        "notify_on_success": True,   # 备份成功后发通知
        "notify_on_failure": True,   # 备份失败后发通知
        "notify_on_warning": True,   # 备份完成但有异常时也发通知（部分失败、空间偏小等）
    },
}


class ConfigError(Exception):
    pass


def _deep_merge(base: dict, override: dict) -> dict:
    """以 base 为模板，用 override 的值覆盖，保留 base 中新增的默认字段"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config() -> dict:
    """加载配置；文件不存在时返回默认配置"""
    cfg_path = paths.get_config_path()
    if not os.path.exists(cfg_path):
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as exc:
        raise ConfigError("读取配置文件失败：%s" % exc)
    return _deep_merge(DEFAULT_CONFIG, data)


def save_config(config: dict) -> str:
    """保存配置到文件，返回文件路径"""
    cfg_path = paths.get_config_path()
    paths.ensure_app_dir()
    tmp = cfg_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cfg_path)
    return cfg_path


def example_config() -> str:
    """导出示例配置 JSON 文本"""
    return json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2)

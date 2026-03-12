# =============================================================================
# nanobot 配置模块
# 文件路径：nanobot/config/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件是 nanobot 配置模块的入口，导出所有配置相关的类和函数。
#
# 配置模块包含哪些文件？
# -------------------
# 1. schema.py - 配置模型定义（Pydantic）
# 2. loader.py - 配置加载逻辑
# 3. paths.py - 路径计算函数
# 4. __init__.py - 模块入口（这个文件）
#
# 导出的内容：
# ---------
# - Config: 根配置模型（包含所有配置段）
# - load_config: 加载配置的函数
# - get_config_path: 获取配置文件路径
# - 各种路径获取函数（日志目录、媒体目录等）
#
# 使用示例：
# --------
# from nanobot.config import Config, load_config
#
# # 加载配置
# config = load_config()
#
# # 访问配置段
# print(config.providers.anthropic.api_key)
# print(config.channels.telegram.enabled)
# =============================================================================

"""Configuration module for nanobot."""
# nanobot 配置模块

# 从 loader 模块导入配置加载函数
from nanobot.config.loader import get_config_path, load_config

# 从 paths 模块导入路径计算函数
from nanobot.config.paths import (
    get_bridge_install_dir,  # 桥接服务安装目录
    get_cli_history_path,  # CLI 历史记录路径
    get_cron_dir,  # 定时任务目录
    get_data_dir,  # 数据目录
    get_legacy_sessions_dir,  # 旧版会话目录
    get_logs_dir,  # 日志目录
    get_media_dir,  # 媒体文件目录
    get_runtime_subdir,  # 运行时子目录
    get_workspace_path,  # 工作空间路径
)

# 从 schema 模块导入配置模型
from nanobot.config.schema import Config  # 根配置模型

# 导出符号列表
# 这些是模块的公共 API，其他模块应该只使用这些导出的内容
__all__ = [
    "Config",  # 根配置模型
    "load_config",  # 加载配置
    "get_config_path",  # 获取配置文件路径
    "get_data_dir",  # 数据目录
    "get_runtime_subdir",  # 运行时子目录
    "get_media_dir",  # 媒体目录
    "get_cron_dir",  # 定时任务目录
    "get_logs_dir",  # 日志目录
    "get_workspace_path",  # 工作空间路径
    "get_cli_history_path",  # CLI 历史路径
    "get_bridge_install_dir",  # 桥接安装目录
    "get_legacy_sessions_dir",  # 旧版会话目录
]

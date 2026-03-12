# =============================================================================
# nanobot 配置加载工具
# 文件路径：nanobot/config/loader.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件提供了配置文件的加载和保存功能。
#
# 什么是配置文件？
# --------------
# 配置文件是 nanobot 的"设置中心"，存储了：
# - API 密钥（OpenAI、Anthropic 等）
# - 渠道配置（Telegram、WhatsApp 等）
# - Agent 设置（模型、温度、最大 token 数等）
# - 工具配置（网络搜索、文件执行等）
#
# 配置文件格式：
# ------------
# 位置：~/.nanobot/config.json
# 格式：JSON
#
# 多实例支持：
# ----------
# 通过 _current_config_path 全局变量，支持运行多个 nanobot 实例，
# 每个实例可以使用不同的配置文件。
# =============================================================================

"""Configuration loading utilities."""
# 配置加载工具函数

import json  # JSON 数据处理
from pathlib import Path  # 路径处理

from nanobot.config.schema import Config  # 配置模型类（使用 Pydantic 定义）


# =============================================================================
# 全局变量：多实例支持
# =============================================================================

# 存储当前配置文件路径的全局变量
# 作用：支持同时运行多个 nanobot 实例，每个实例使用不同的配置
# 默认值：None（使用默认路径 ~/.nanobot/config.json）
_current_config_path: Path | None = None


def set_config_path(path: Path) -> None:
    """
    设置当前配置文件路径。

    这个函数用于多实例场景：
    - 实例 A 使用配置 ~/.nanobot/config_a.json
    - 实例 B 使用配置 ~/.nanobot/config_b.json

    Args:
        path: 配置文件路径
    """
    global _current_config_path  # 声明使用全局变量
    _current_config_path = path


def get_config_path() -> Path:
    """
    获取配置文件路径。

    返回：
    - 如果设置了自定义路径，返回自定义路径
    - 否则返回默认路径 ~/.nanobot/config.json

    Returns:
        Path: 配置文件路径

    示例：
        >>> get_config_path()
        PosixPath('/Users/username/.nanobot/config.json')
    """
    # 如果有自定义路径，返回自定义路径
    if _current_config_path:
        return _current_config_path
    # 否则返回默认路径
    return Path.home() / ".nanobot" / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """
    从文件加载配置，如果文件不存在则创建默认配置。

    加载流程：
    1. 检查配置文件是否存在
    2. 如果存在，读取并解析 JSON
    3. 执行配置迁移（兼容旧版本）
    4. 使用 Pydantic 验证数据
    5. 如果失败，返回默认配置

    Args:
        config_path: 配置文件路径（可选）
            - 如果提供，使用指定路径
            - 如果不提供，使用默认路径

    Returns:
        Config: 加载的配置对象

    异常处理：
    - JSONDecodeError: JSON 格式错误
    - ValueError: Pydantic 验证失败
    - 发生异常时返回默认配置并打印警告
    """
    # 确定配置文件路径
    path = config_path or get_config_path()

    # 检查文件是否存在
    if path.exists():
        try:
            # 打开文件并读取 JSON
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            # 执行配置迁移（兼容旧版本格式）
            data = _migrate_config(data)

            # 使用 Pydantic 验证并转换为 Config 对象
            # model_validate 是 Pydantic v2 的方法
            return Config.model_validate(data)

        except (json.JSONDecodeError, ValueError) as e:
            # 捕获 JSON 解析错误和验证错误
            print(f"Warning: Failed to load config from {path}: {e}")
            print("Using default configuration.")
            # 出错时返回默认配置

    # 文件不存在或出错时，返回默认配置
    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    保存配置到文件。

    保存流程：
    1. 确定保存路径
    2. 确保父目录存在
    3. 将 Config 对象转换为字典
    4. 写入 JSON 文件

    Args:
        config: 要保存的配置对象
        config_path: 保存路径（可选）

    示例：
        >>> config = Config()
        >>> save_config(config)
        # 保存到 ~/.nanobot/config.json
    """
    # 确定保存路径
    path = config_path or get_config_path()

    # 确保父目录存在（如果 ~/.nanobot 不存在，创建它）
    # parents=True: 递归创建所有父目录
    # exist_ok=True: 如果目录已存在，不报错
    path.parent.mkdir(parents=True, exist_ok=True)

    # 将 Config 对象转换为字典
    # by_alias=True: 使用字段别名（如 camelCase）
    # 这样配置文件使用 camelCase，Python 代码使用 snake_case
    data = config.model_dump(by_alias=True)

    # 写入 JSON 文件
    with open(path, "w", encoding="utf-8") as f:
        # indent=2: 格式化缩进
        # ensure_ascii=False: 保留非 ASCII 字符（如中文）
        json.dump(data, f, indent=2, ensure_ascii=False)


def _migrate_config(data: dict) -> dict:
    """
    迁移旧版配置格式到当前版本。

    为什么要迁移？
    -----------
    随着项目发展，配置格式可能会变化。
    这个函数确保旧版配置文件可以升级到新格式。

    当前迁移规则：
    ------------
    - 将 tools.exec.restrictToWorkspace 移动到 tools.restrictToWorkspace
    - 这是为了支持多实例配置隔离

    Args:
        data: 原始配置字典

    Returns:
        dict: 迁移后的配置字典
    """
    # 获取 tools 配置段
    tools = data.get("tools", {})
    # 获取 exec 工具配置
    exec_cfg = tools.get("exec", {})

    # 检查是否有旧字段
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        # 移动字段到新位置
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")

    return data

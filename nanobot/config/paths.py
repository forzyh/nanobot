# =============================================================================
# nanobot 配置路径工具
# 文件路径：nanobot/config/paths.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件定义了 nanobot 运行时用到的所有目录和文件路径。
#
# 为什么需要单独的路径模块？
# -------------------------
# 1. 集中管理：所有路径都在一个地方定义，易于维护和修改
# 2. 一致性：确保不同模块使用相同的路径规则
# 3. 自动创建：路径不存在时自动创建目录
# 4. 跨平台：使用 pathlib 处理不同操作系统的路径差异
#
# nanobot 的目录结构：
# ------------------
# ~/.nanobot/
# ├── config.json      # 主配置文件
# ├── workspace/       # 工作空间目录
# ├── bridge/          # WhatsApp 桥接服务
# ├── media/           # 媒体文件（图片、音频等）
# ├── cron/            # 定时任务数据
# ├── logs/            # 日志文件
# ├── history/         # 命令行历史
# └── sessions/        # 会话数据（旧版，用于迁移）
# =============================================================================

"""Runtime path helpers derived from the active config context."""
# 运行时路径辅助函数，基于当前配置上下文

from __future__ import annotations  # 启用未来版本的注解特性

from pathlib import Path  # 导入路径处理库

from nanobot.config.loader import get_config_path  # 获取配置文件路径的函数
from nanobot.utils.helpers import ensure_dir  # 确保目录存在的辅助函数


def get_data_dir() -> Path:
    """
    返回实例级的运行时数据目录。

    这个目录是 nanobot 所有运行时数据的根目录。
    位于配置文件所在目录，通常是 ~/.nanobot/

    Returns:
        Path: 数据目录路径

    示例：
        >>> get_data_dir()
        PosixPath('/Users/username/.nanobot')
    """
    # 获取配置文件路径，然后取其父目录作为数据目录
    # ensure_dir 确保目录存在，不存在则创建
    return ensure_dir(get_config_path().parent)


def get_runtime_subdir(name: str) -> Path:
    """
    返回实例数据目录下名为 name 的子目录。

    这是一个通用函数，用于获取各种运行时子目录。
    其他具体目录函数（如 get_media_dir、get_cron_dir 等）都基于这个函数。

    Args:
        name: 子目录名称，如 "media"、"cron"、"logs" 等

    Returns:
        Path: 子目录路径

    示例：
        >>> get_runtime_subdir("media")
        PosixPath('/Users/username/.nanobot/media')
    """
    # 先获取数据目录，然后拼接子目录名，最后确保目录存在
    return ensure_dir(get_data_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """
    返回媒体文件存储目录。

    媒体目录用于存储各渠道接收和发送的媒体文件：
    - 图片
    - 音频
    - 视频
    - 文档

    Args:
        channel: 渠道名称（可选）
            - 如果提供，返回渠道专属目录（如 media/telegram/）
            - 如果不提供，返回通用媒体目录（如 media/）

    Returns:
        Path: 媒体目录路径

    示例：
        >>> get_media_dir("telegram")
        PosixPath('/Users/username/.nanobot/media/telegram')
        >>> get_media_dir()
        PosixPath('/Users/username/.nanobot/media')
    """
    # 获取基础媒体目录
    base = get_runtime_subdir("media")
    # 如果指定了渠道，返回渠道子目录；否则返回基础目录
    return ensure_dir(base / channel) if channel else base


def get_cron_dir() -> Path:
    """
    返回定时任务存储目录。

    cron 是 Linux/Unix 的定时任务系统名称，这里借用这个概念。
    目录用于存储：
    - 定时任务定义（jobs.json）
    - 定时任务执行历史

    Returns:
        Path: 定时任务目录路径

    示例：
        >>> get_cron_dir()
        PosixPath('/Users/username/.nanobot/cron')
    """
    return get_runtime_subdir("cron")


def get_logs_dir() -> Path:
    """
    返回日志文件存储目录。

    nanobot 使用 loguru 作为日志库，日志会写入这个目录。
    日志文件通常包括：
    - 运行日志
    - 错误日志
    - 调试日志

    Returns:
        Path: 日志目录路径

    示例：
        >>> get_logs_dir()
        PosixPath('/Users/username/.nanobot/logs')
    """
    return get_runtime_subdir("logs")


def get_workspace_path(workspace: str | None = None) -> Path:
    """
    解析并确保 Agent 工作空间路径存在。

    工作空间是 Agent 操作文件的"根目录"。
    出于安全考虑，可以限制 Agent 只能在这个目录内操作文件。

    Args:
        workspace: 自定义工作空间路径（可选）
            - 如果提供，使用自定义路径
            - 如果不提供，使用默认路径 ~/.nanobot/workspace

    Returns:
        Path: 工作空间路径

    示例：
        >>> get_workspace_path()
        PosixPath('/Users/username/.nanobot/workspace')
        >>> get_workspace_path("/custom/path")
        PosixPath('/custom/path')
    """
    # 如果提供了自定义路径，展开~并转换为 Path 对象
    # 否则使用默认路径 ~/.nanobot/workspace
    path = Path(workspace).expanduser() if workspace else Path.home() / ".nanobot" / "workspace"
    # 确保目录存在
    return ensure_dir(path)


def get_cli_history_path() -> Path:
    """
    返回共享的命令行历史记录文件路径。

    命令行交互模式（nanobot agent）的输入历史会保存到这个文件。
    使用 prompt_toolkit 的 FileHistory 实现持久化。

    Returns:
        Path: CLI 历史文件路径

    示例：
        >>> get_cli_history_path()
        PosixPath('/Users/username/.nanobot/history/cli_history')
    """
    # 历史文件位于 ~/.nanobot/history/cli_history
    return Path.home() / ".nanobot" / "history" / "cli_history"


def get_bridge_install_dir() -> Path:
    """
    返回 WhatsApp 桥接服务的安装目录。

    WhatsApp 需要一个 Node.js 桥接服务来连接 WebSocket。
    这个目录存储桥接服务的源码和构建产物：
    - package.json: Node.js 项目配置
    - src/: TypeScript 源码
    - dist/: 编译后的 JavaScript

    Returns:
        Path: 桥接服务目录路径

    示例：
        >>> get_bridge_install_dir()
        PosixPath('/Users/username/.nanobot/bridge')
    """
    return Path.home() / ".nanobot" / "bridge"


def get_legacy_sessions_dir() -> Path:
    """
    返回旧版全局会话目录，用于迁移回退。

    这是 nanobot 早期版本使用的会话存储位置。
    保留这个函数是为了支持从旧版本迁移到新版本。

    Returns:
        Path: 旧版会话目录路径

    示例：
        >>> get_legacy_sessions_dir()
        PosixPath('/Users/username/.nanobot/sessions')
    """
    return Path.home() / ".nanobot" / "sessions"

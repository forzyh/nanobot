# =============================================================================
# nanobot 配置路径函数测试
# 文件路径：tests/test_config_paths.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对配置路径相关函数的测试。
# 这些函数用于确定 nanobot 各种数据和配置文件的存储位置。
#
# 什么是配置路径函数？
# ---------------
# nanobot 需要在文件系统中存储各种数据（配置、日志、媒体等），
# 配置路径函数提供统一的接口来获取这些路径。主要包括：
# - get_data_dir(): 获取数据目录
# - get_runtime_subdir(): 获取运行时子目录
# - get_cron_dir(): 获取 Cron 任务目录
# - get_logs_dir(): 获取日志目录
# - get_media_dir(): 获取媒体文件目录
# - get_cli_history_path(): 获取 CLI 历史路径
# - get_bridge_install_dir(): 获取桥接安装目录
# - get_legacy_sessions_dir(): 获取旧版会话目录
# - get_workspace_path(): 获取工作区路径
#
# 路径分类：
# - 实例相关路径：基于配置文件所在目录（如 data_dir、cron_dir、logs_dir）
# - 全局共享路径：固定在 ~/.nanobot 下（如 cli_history、bridge、sessions）
#
# 测试场景：
# --------
# 1. 运行时目录跟随配置路径：实例相关路径基于配置文件所在目录
# 2. 媒体目录支持渠道命名空间：媒体目录可以有渠道子目录
# 3. 共享和旧版路径保持全局：全局路径固定在 ~/.nanobot 下
# 4. 工作区路径显式解析：支持自定义工作区路径
#
# 使用示例：
# --------
# pytest tests/test_config_paths.py -v  # 运行所有测试
# =============================================================================

from pathlib import Path

import pytest

from nanobot.config.paths import (
    get_bridge_install_dir,
    get_cli_history_path,
    get_cron_dir,
    get_data_dir,
    get_legacy_sessions_dir,
    get_logs_dir,
    get_media_dir,
    get_runtime_subdir,
    get_workspace_path,
)


def test_runtime_dirs_follow_config_path(monkeypatch, tmp_path: Path) -> None:
    """测试运行时目录跟随配置路径。

    场景说明：
        nanobot 支持多实例配置，每个实例有自己的配置目录。
        运行时目录（数据目录、Cron 目录、日志目录等）应该基于
        配置文件所在的目录，这样可以实现多实例隔离。

    验证点：
        1. get_data_dir() 返回配置文件所在目录
        2. get_runtime_subdir("cron") 返回配置文件目录下的 cron 子目录
        3. get_cron_dir() 返回配置文件目录下的 cron 子目录
        4. get_logs_dir() 返回配置文件目录下的 logs 子目录
    """
    # 模拟配置文件路径：tmp_path/instance-a/config.json
    config_file = tmp_path / "instance-a" / "config.json"
    # 使用 monkeypatch 模拟 get_config_path 函数返回我们的测试路径
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)

    # 验证数据目录是配置文件所在目录
    assert get_data_dir() == config_file.parent
    # 验证运行时子目录正确
    assert get_runtime_subdir("cron") == config_file.parent / "cron"
    # 验证 Cron 目录正确
    assert get_cron_dir() == config_file.parent / "cron"
    # 验证日志目录正确
    assert get_logs_dir() == config_file.parent / "logs"


def test_media_dir_supports_channel_namespace(monkeypatch, tmp_path: Path) -> None:
    """测试媒体目录支持渠道命名空间。

    场景说明：
        媒体文件目录支持按渠道分类存储，
        可以获取通用媒体目录，也可以获取特定渠道的媒体目录。

    验证点：
        1. get_media_dir() 返回配置文件目录下的 media 目录
        2. get_media_dir("telegram") 返回配置文件目录下的 media/telegram 子目录
    """
    # 模拟配置文件路径
    config_file = tmp_path / "instance-b" / "config.json"
    monkeypatch.setattr("nanobot.config.paths.get_config_path", lambda: config_file)

    # 验证通用媒体目录
    assert get_media_dir() == config_file.parent / "media"
    # 验证带渠道命名空间的媒体目录
    assert get_media_dir("telegram") == config_file.parent / "media" / "telegram"


def test_shared_and_legacy_paths_remain_global() -> None:
    """测试共享和旧版路径保持全局。

    场景说明：
        某些路径是全局共享的，不随实例变化：
        - CLI 历史记录：所有实例共享同一个命令行历史
        - 桥接安装目录：桥接程序只需安装一次
        - 旧版会话目录：保留向后兼容性

    验证点：
        1. get_cli_history_path() 返回 ~/.nanobot/history/cli_history
        2. get_bridge_install_dir() 返回 ~/.nanobot/bridge
        3. get_legacy_sessions_dir() 返回 ~/.nanobot/sessions
    """
    # 验证 CLI 历史路径是全局的
    assert get_cli_history_path() == Path.home() / ".nanobot" / "history" / "cli_history"
    # 验证桥接安装目录是全局的
    assert get_bridge_install_dir() == Path.home() / ".nanobot" / "bridge"
    # 验证旧版会话目录是全局的
    assert get_legacy_sessions_dir() == Path.home() / ".nanobot" / "sessions"


def test_workspace_path_is_explicitly_resolved() -> None:
    """测试工作区路径显式解析。

    场景说明：
        工作区路径用于存储用户工作区相关文件。
        支持默认路径（~/.nanobot/workspace）和自定义路径。
        自定义路径中的 ~ 应该被展开为用户主目录。

    验证点：
        1. get_workspace_path() 返回默认路径 ~/.nanobot/workspace
        2. get_workspace_path("~/custom-workspace") 将 ~ 展开为 ~/custom-workspace
    """
    # 验证默认工作区路径
    assert get_workspace_path() == Path.home() / ".nanobot" / "workspace"
    # 验证自定义路径的 ~ 被正确展开
    assert get_workspace_path("~/custom-workspace") == Path.home() / "custom-workspace"

# =============================================================================
# nanobot 渠道注册表
# 文件路径：nanobot/channels/registry.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了渠道自动发现机制，无需硬编码注册表。
#
# 什么是渠道自动发现？
# -----------------
# 自动扫描 nanobot/channels/ 目录下的所有 Python 文件，
# 动态加载继承自 BaseChannel 的类。
#
# 为什么使用自动发现？
# -----------------
# 1. 零配置：添加新渠道无需修改注册表
# 2. 解耦：渠道模块独立，不依赖中央注册表
# 3. 可扩展：第三方可以轻松添加自定义渠道
#
# 工作原理：
# ---------
# 1. 使用 pkgutil.iter_modules() 扫描包
# 2. 排除内部模块（base、manager、registry）
# 3. 使用 importlib 动态导入模块
# 4. 查找第一个 BaseChannel 子类
#
# 使用示例：
# --------
# # 获取所有渠道名称
# names = discover_channel_names()  # ["telegram", "discord", ...]
#
# # 加载渠道类
# TelegramClass = load_channel_class("telegram")
# telegram = TelegramClass(config, bus)
# =============================================================================

"""Auto-discovery for channel modules — no hardcoded registry."""
# 渠道模块的自动发现——无需硬编码注册表

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nanobot.channels.base import BaseChannel

# 内部模块集合（不进行渠道发现）
_INTERNAL = frozenset({"base", "manager", "registry"})


def discover_channel_names() -> list[str]:
    """
    通过扫描包返回所有渠道模块名称（零导入）。

    Returns:
        list[str]: 渠道模块名称列表（如 ["telegram", "discord", ...]）

    工作原理：
    --------
    1. 使用 pkgutil.iter_modules() 扫描 nanobot.channels 包
    2. 排除内部模块（base、manager、registry）
    3. 排除包（ispkg=True）
    4. 返回剩余的模块名称

    使用示例：
    --------
    >>> names = discover_channel_names()
    >>> print(names)
    ['telegram', 'discord', 'whatsapp', 'feishu', ...]
    """
    import nanobot.channels as pkg

    return [
        name
        for _, name, ispkg in pkgutil.iter_modules(pkg.__path__)
        if name not in _INTERNAL and not ispkg
    ]


def load_channel_class(module_name: str) -> type[BaseChannel]:
    """
    导入模块并返回找到的第一个 BaseChannel 子类。

    Args:
        module_name: 模块名称（如 "telegram"）

    Returns:
        type[BaseChannel]: 渠道类

    工作原理：
    --------
    1. 使用 importlib.import_module() 导入模块
    2. 遍历模块的所有属性（dir(mod)）
    3. 查找第一个继承自 BaseChannel 的类（排除 BaseChannel 本身）
    4. 返回找到的类

    错误处理：
    --------
    - 如果没有找到子类，抛出 ImportError

    使用示例：
    --------
    >>> TelegramClass = load_channel_class("telegram")
    >>> telegram = TelegramClass(config, bus)
    """
    from nanobot.channels.base import BaseChannel as _Base

    mod = importlib.import_module(f"nanobot.channels.{module_name}")
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, _Base) and obj is not _Base:
            return obj
    raise ImportError(f"No BaseChannel subclass in nanobot.channels.{module_name}")

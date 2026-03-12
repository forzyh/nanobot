# =============================================================================
# nanobot 渠道管理器
# 文件路径：nanobot/channels/manager.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 ChannelManager 类，负责协调和管理所有聊天渠道。
#
# 什么是渠道管理器？
# ---------------
# 渠道管理器是 nanobot 的"渠道指挥中心"，负责：
# 1. 初始化启用的渠道（Telegram、WhatsApp 等）
# 2. 启动/停止所有渠道
# 3. 路由出站消息到正确的渠道
# 4. 监控渠道状态
#
# 为什么需要渠道管理器？
# -------------------
# 1. 集中管理：统一控制所有渠道的启停
# 2. 消息路由：自动将消息发送到正确的渠道
# 3. 解耦设计：Agent 不需要知道具体有哪些渠道
# 4. 动态扩展：可以轻松添加新渠道
#
# 架构图：
# -------
#                     ChannelManager
#                         │
#         ┌───────────────┼───────────────┐
#         │               │               │
#    Telegram       Discord        WhatsApp
#    Channel        Channel        Channel
#         │               │               │
#         └───────────────┴───────────────┘
#                         │
#                    MessageBus
#                         │
#                    AgentLoop
# =============================================================================

"""Channel manager for coordinating chat channels."""
# 渠道管理器：协调聊天渠道

from __future__ import annotations  # 启用未来版本的类型注解

import asyncio  # 异步编程
from typing import Any  # 任意类型

from loguru import logger  # 日志库

from nanobot.bus.queue import MessageBus  # 消息总线
from nanobot.channels.base import BaseChannel  # 渠道基类
from nanobot.config.schema import Config  # 配置模型


# =============================================================================
# ChannelManager - 渠道管理器
# =============================================================================

class ChannelManager:
    """
    管理聊天渠道并协调消息路由。

    核心职责：
    --------
    1. Initialize enabled channels: 初始化启用的渠道
       - 扫描可用的渠道模块
       - 根据配置启用相应渠道

    2. Start/stop channels: 启动/停止渠道
       - 启动时连接各平台 API
       - 停止时清理资源

    3. Route outbound messages: 路由出站消息
       - 从消息总线接收消息
       - 发送到对应的渠道

    属性说明：
    --------
    config: Config
        全局配置对象

    bus: MessageBus
        消息总线实例

    channels: dict[str, BaseChannel]
        已初始化的渠道字典
        键：渠道名称（如 "telegram"）
        值：渠道实例

    _dispatch_task: asyncio.Task | None
        出站消息分发任务
    """

    def __init__(self, config: Config, bus: MessageBus):
        """
        初始化渠道管理器。

        Args:
            config: 全局配置对象
            bus: 消息总线实例
        """
        self.config = config  # 配置
        self.bus = bus  # 消息总线
        self.channels: dict[str, BaseChannel] = {}  # 渠道字典
        self._dispatch_task: asyncio.Task | None = None  # 分发任务

        # 初始化渠道
        self._init_channels()

    def _init_channels(self) -> None:
        """
        通过 pkgutil 扫描初始化渠道。

        初始化流程：
        --------
        1. 发现所有可用的渠道模块
        2. 检查配置是否启用
        3. 加载渠道类并创建实例
        4. 设置语音转文本 API 密钥
        5. 验证 allow_from 配置

        渠道发现机制：
        -----------
        nanobot 使用 pkgutil 扫描 nanobot.channels 包，
        自动发现所有渠道模块，无需手动注册。
        """
        # 导入渠道注册表函数
        from nanobot.channels.registry import discover_channel_names, load_channel_class

        # 获取 Groq API 密钥（用于语音转文本）
        groq_key = self.config.providers.groq.api_key

        # 遍历所有发现的渠道模块
        for modname in discover_channel_names():
            # 获取对应的配置段
            section = getattr(self.config.channels, modname, None)
            # 如果配置不存在或未启用，跳过
            if not section or not getattr(section, "enabled", False):
                continue
            try:
                # 加载渠道类
                cls = load_channel_class(modname)
                # 创建渠道实例
                channel = cls(section, self.bus)
                # 设置语音转文本 API 密钥
                channel.transcription_api_key = groq_key
                # 注册到渠道字典
                self.channels[modname] = channel
                # 记录日志
                logger.info("{} channel enabled", cls.display_name)
            except ImportError as e:
                # 依赖缺失时记录警告
                logger.warning("{} channel not available: {}", modname, e)

        # 验证 allow_from 配置
        self._validate_allow_from()

    def _validate_allow_from(self) -> None:
        """
        验证 allow_from 配置。

        为什么要验证？
        -----------
        空的 allow_from 列表意味着拒绝所有用户访问。
        这通常不是用户本意（可能是配置遗漏）。
        所以在启动时检查并报错，提醒用户配置。

        错误处理：
        --------
        如果发现空的 allow_from，直接退出程序并提示用户：
        - 设置 ["*"] 允许所有人
        - 或添加具体的用户 ID
        """
        # 遍历所有渠道
        for name, ch in self.channels.items():
            # 检查 allow_from 是否为空列表
            if getattr(ch.config, "allow_from", None) == []:
                # 退出并显示错误信息
                raise SystemExit(
                    f'Error: "{name}" has empty allowFrom (denies all). '
                    f'Set ["*"] to allow everyone, or add specific user IDs.'
                )

    async def _start_channel(self, name: str, channel: BaseChannel) -> None:
        """
        启动渠道并捕获异常。

        这是一个辅助方法，用于安全地启动渠道。
        即使启动失败也不会影响其他渠道。

        Args:
            name: 渠道名称
            channel: 渠道实例
        """
        try:
            # 启动渠道
            await channel.start()
        except Exception as e:
            # 记录错误日志
            logger.error("Failed to start channel {}: {}", name, e)

    async def start_all(self) -> None:
        """
        启动所有渠道和出站分发器。

        启动流程：
        --------
        1. 检查是否有启用的渠道
        2. 创建出站分发任务
        3. 并发启动所有渠道
        4. 等待所有渠道启动完成

        注意：
        ----
        渠道的 start() 方法是长期运行的任务，
        会持续监听消息直到被停止。
        """
        # 没有启用渠道时警告
        if not self.channels:
            logger.warning("No channels enabled")
            return

        # 启动出站分发器
        self._dispatch_task = asyncio.create_task(self._dispatch_outbound())

        # 收集启动任务
        tasks = []
        for name, channel in self.channels.items():
            logger.info("Starting {} channel...", name)
            # 创建启动任务
            tasks.append(asyncio.create_task(self._start_channel(name, channel)))

        # 等待所有任务完成（它们应该长期运行）
        await asyncio.gather(*tasks, return_exceptions=True)

    async def stop_all(self) -> None:
        """
        停止所有渠道和分发器。

        停止流程：
        --------
        1. 取消出站分发任务
        2. 等待任务完全退出
        3. 逐个停止渠道
        4. 记录停止日志
        """
        logger.info("Stopping all channels...")

        # 停止分发器
        if self._dispatch_task:
            self._dispatch_task.cancel()  # 取消任务
            try:
                await self._dispatch_task  # 等待完成
            except asyncio.CancelledError:
                pass  # 取消是正常的

        # 停止所有渠道
        for name, channel in self.channels.items():
            try:
                # 调用渠道的 stop 方法
                await channel.stop()
                logger.info("Stopped {} channel", name)
            except Exception as e:
                # 记录错误
                logger.error("Error stopping {}: {}", name, e)

    async def _dispatch_outbound(self) -> None:
        """
        分发出站消息到相应的渠道。

        这是一个长期运行的任务，持续从消息总线
        消费出站消息并发送到对应的渠道。

        消息过滤：
        --------
        1. 进度消息（_progress=True）：
           - 如果配置禁止 send_progress，跳过

        2. 工具提示消息（_tool_hint=True）：
           - 如果配置禁止 send_tool_hints，跳过

        流程：
        ----
        1. 从出站队列获取消息
        2. 检查是否需要过滤
        3. 查找目标渠道
        4. 调用渠道的 send 方法
        """
        logger.info("Outbound dispatcher started")

        # 主循环
        while True:
            try:
                # 从出站队列消费消息（1 秒超时）
                msg = await asyncio.wait_for(
                    self.bus.consume_outbound(),
                    timeout=1.0
                )

                # 检查是否是进度消息
                if msg.metadata.get("_progress"):
                    # 工具提示且配置禁止 → 跳过
                    if msg.metadata.get("_tool_hint") and not self.config.channels.send_tool_hints:
                        continue
                    # 非工具提示且配置禁止 → 跳过
                    if not msg.metadata.get("_tool_hint") and not self.config.channels.send_progress:
                        continue

                # 获取目标渠道
                channel = self.channels.get(msg.channel)
                if channel:
                    try:
                        # 发送消息
                        await channel.send(msg)
                    except Exception as e:
                        # 记录发送错误
                        logger.error("Error sending to {}: {}", msg.channel, e)
                else:
                    # 渠道不存在
                    logger.warning("Unknown channel: {}", msg.channel)

            except asyncio.TimeoutError:
                # 超时继续循环
                continue
            except asyncio.CancelledError:
                # 被取消，退出循环
                break

    def get_channel(self, name: str) -> BaseChannel | None:
        """
        按名称获取渠道。

        Args:
            name: 渠道名称

        Returns:
            BaseChannel | None: 渠道实例，不存在返回 None
        """
        return self.channels.get(name)

    def get_status(self) -> dict[str, Any]:
        """
        获取所有渠道的状态。

        Returns:
            dict[str, Any]: 状态字典
                键：渠道名称
                值：{"enabled": True, "running": bool}

        示例：
            >>> manager.get_status()
            {
                "telegram": {"enabled": True, "running": True},
                "discord": {"enabled": True, "running": False}
            }
        """
        return {
            name: {
                "enabled": True,  # 已配置启用
                "running": channel.is_running  # 实际运行状态
            }
            for name, channel in self.channels.items()
        }

    @property
    def enabled_channels(self) -> list[str]:
        """
        获取启用的渠道名称列表。

        Returns:
            list[str]: 渠道名称列表

        示例：
            >>> manager.enabled_channels
            ['telegram', 'discord', 'whatsapp']
        """
        return list(self.channels.keys())

# =============================================================================
# nanobot 渠道基类
# 文件路径：nanobot/channels/base.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件定义了 BaseChannel 抽象基类，是所有聊天渠道的"模板"。
#
# 什么是渠道（Channel）？
# -----------------
# 渠道是 nanobot 与各种聊天平台连接的"适配器"：
# - Telegram: 通过 Bot API 连接
# - Discord: 通过 WebSocket Gateway 连接
# - WhatsApp: 通过 WebSocket 桥接服务连接
# - Feishu: 通过 WebSocket 长连接
# - Slack: 通过 Socket Mode 连接
# - 等等...
#
# 为什么需要抽象基类？
# -----------------
# 不同平台的 API 不一样，但核心功能相同：
# 1. 接收消息（start）
# 2. 发送消息（send）
# 3. 停止服务（stop）
#
# 抽象基类定义了统一接口，让上层代码（AgentLoop）
# 不需要关心具体是哪个平台。
#
# 渠道架构图：
# -----------
#   用户 ←→ [Telegram/Discord/WhatsApp...] ←→ BaseChannel ←→ MessageBus ←→ AgentLoop
#      平台 API            渠道实现            消息总线         核心处理
# =============================================================================

"""Base channel interface for chat platforms."""
# 聊天平台的渠道基类

from __future__ import annotations  # 启用未来版本的类型注解

from abc import ABC, abstractmethod  # 抽象基类
from pathlib import Path  # 路径处理
from typing import Any  # 任意类型

from loguru import logger  # 日志库

from nanobot.bus.events import InboundMessage, OutboundMessage  # 消息事件
from nanobot.bus.queue import MessageBus  # 消息总线


# =============================================================================
# BaseChannel - 渠道抽象基类
# =============================================================================

class BaseChannel(ABC):
    """
    聊天渠道实现的抽象基类。

    每个渠道（Telegram、Discord 等）都应该实现这个接口，
    以集成到 nanobot 消息总线。

    继承这个基类需要实现的方法：
    --------------------------
    1. start(): 启动渠道，开始监听消息
    2. stop(): 停止渠道，清理资源
    3. send(): 发送消息到平台

    子类示例：
    --------
    class TelegramChannel(BaseChannel):
        async def start(self):
            # 连接 Telegram Bot API
            # 开始轮询消息

        async def stop(self):
            # 关闭连接

        async def send(self, msg: OutboundMessage):
            # 调用 Telegram API 发送消息
    """

    # 类属性
    name: str = "base"  # 渠道内部名称（如 "telegram"、"discord"）
    display_name: str = "Base"  # 显示名称（如 "Telegram"、"Discord"）
    transcription_api_key: str = ""  # 语音转文本 API 密钥（Groq Whisper）

    def __init__(self, config: Any, bus: MessageBus):
        """
        初始化渠道。

        Args:
            config: 渠道特定配置
                如 TelegramConfig、DiscordConfig 等

            bus: 消息总线实例
                用于接收和发送消息
        """
        self.config = config  # 配置对象
        self.bus = bus  # 消息总线
        self._running = False  # 运行状态标志

    async def transcribe_audio(self, file_path: str | Path) -> str:
        """
        通过 Groq Whisper 转录音频文件。

        这个方法用于将语音消息转换为文本，
        让 AI 能够理解语音内容。

        Args:
            file_path: 音频文件路径
                可以是 str 或 Path 类型

        Returns:
            str: 转录的文本，失败返回空字符串

        转录流程：
        --------
        1. 检查是否配置了 API 密钥
        2. 创建 GroqTranscriptionProvider
        3. 调用 transcribe() 方法
        4. 捕获异常并记录日志

        示例：
            >>> text = await channel.transcribe_audio("/tmp/voice.ogg")
            >>> print(text)
            "你好，我想查询今天的天气"
        """
        # 没有 API 密钥直接返回空字符串
        if not self.transcription_api_key:
            return ""
        try:
            # 导入 Groq 转录提供商
            from nanobot.providers.transcription import GroqTranscriptionProvider

            # 创建提供商实例
            provider = GroqTranscriptionProvider(api_key=self.transcription_api_key)
            # 调用转录方法
            return await provider.transcribe(file_path)
        except Exception as e:
            # 记录警告日志（转录失败不是致命错误）
            logger.warning("{}: audio transcription failed: {}", self.name, e)
            return ""

    @abstractmethod
    async def start(self) -> None:
        """
        启动渠道并开始监听消息。

        这是一个长期运行的异步任务，负责：
        1. 连接到聊天平台（如 Telegram Bot API）
        2. 监听传入的消息
        3. 通过 _handle_message() 将消息转发到消息总线

        注意：
        ----
        这是 @abstractmethod，子类必须实现。

        示例（Telegram）：
            >>> async def start(self):
            ...     self._running = True
            ...     while self._running:
            ...         updates = await self.bot.get_updates()
            ...         for update in updates:
            ...             await self._handle_message(...)
        """
        pass  # 由子类实现

    @abstractmethod
    async def stop(self) -> None:
        """
        停止渠道并清理资源。

        这个方法应该：
        1. 设置 _running = False
        2. 关闭网络连接
        3. 释放其他资源

        注意：
        ----
        这是 @abstractmethod，子类必须实现。
        """
        pass  # 由子类实现

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """
        通过这个渠道发送消息。

        Args:
            msg: 要发送的出站消息

        注意：
        ----
        这是 @abstractmethod，子类必须实现。

        示例（Telegram）：
            >>> async def send(self, msg: OutboundMessage):
            ...     await self.bot.send_message(
            ...         chat_id=msg.chat_id,
            ...         text=msg.content
            ...     )
        """
        pass  # 由子类实现

    def is_allowed(self, sender_id: str) -> bool:
        """
        检查发送者是否被允许。

        权限检查逻辑：
        -----------
        1. 空列表 → 拒绝所有（没有配置允许任何人）
        2. 包含 "*" → 允许所有（开放模式）
        3. 包含 sender_id → 允许特定用户
        4. 其他情况 → 拒绝

        Args:
            sender_id: 发送者 ID

        Returns:
            bool: True 表示允许，False 表示拒绝

        配置示例：
            # config.json
            {
                "telegram": {
                    "allow_from": ["123456", "789012"]  # 只允许这两个用户
                },
                "discord": {
                    "allow_from": ["*"]  # 允许所有用户
                }
            }
        """
        # 获取配置的允许列表
        allow_list = getattr(self.config, "allow_from", [])
        # 空列表 → 拒绝所有
        if not allow_list:
            logger.warning("{}: allow_from is empty — all access denied", self.name)
            return False
        # 包含通配符 → 允许所有
        if "*" in allow_list:
            return True
        # 检查是否在列表中
        return str(sender_id) in allow_list

    async def _handle_message(
        self,
        sender_id: str,
        chat_id: str,
        content: str,
        media: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_key: str | None = None,
    ) -> None:
        """
        处理来自聊天平台的传入消息。

        这个方法由子类调用，用于：
        1. 检查发送者权限
        2. 创建 InboundMessage 对象
        3. 发布到消息总线

        Args:
            sender_id: 发送者的 ID
            chat_id: 聊天/频道的 ID
            content: 消息文本内容
            media: 可选的媒体 URL 列表（图片、音频等）
            metadata: 可选的渠道特定元数据
            session_key: 可选的会话密钥覆盖（如线程范围的会话）

        使用示例（在子类中）：
            >>> # Telegram 收到消息后
            >>> await self._handle_message(
            ...     sender_id=update.message.from_user.id,
            ...     chat_id=str(update.message.chat_id),
            ...     content=update.message.text,
            ...     metadata={"message_id": update.message.message_id}
            ... )
        """
        # 检查权限
        if not self.is_allowed(sender_id):
            # 记录警告日志
            logger.warning(
                "Access denied for sender {} on channel {}. "
                "Add them to allowFrom list in config to grant access.",
                sender_id, self.name,
            )
            return  # 拒绝处理

        # 创建入站消息对象
        msg = InboundMessage(
            channel=self.name,  # 渠道名称
            sender_id=str(sender_id),  # 发送者 ID
            chat_id=str(chat_id),  # 聊天 ID
            content=content,  # 消息内容
            media=media or [],  # 媒体列表
            metadata=metadata or {},  # 元数据
            session_key_override=session_key,  # 会话密钥覆盖
        )

        # 发布到消息总线
        await self.bus.publish_inbound(msg)

    @property
    def is_running(self) -> bool:
        """
        检查渠道是否正在运行。

        Returns:
            bool: True 表示正在运行
        """
        return self._running

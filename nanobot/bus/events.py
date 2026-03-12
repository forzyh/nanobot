# =============================================================================
# nanobot 消息总线事件定义
# 文件路径：nanobot/bus/events.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件定义了消息总线中使用的两种事件类型：
# 1. InboundMessage（入站消息）- 从聊天渠道接收的消息
# 2. OutboundMessage（出站消息）- 要发送到聊天渠道的消息
#
# 什么是消息总线？
# --------------
# 消息总线（Message Bus）是一种软件架构模式，用于组件间的通信。
# 在 nanobot 中：
#
#   聊天渠道 → InboundMessage → Agent → OutboundMessage → 聊天渠道
#      (接收)          (处理)         (发送)
#
# 使用消息总线的好处：
# ------------------
# 1. 解耦：渠道和 Agent 不需要知道对方的存在
# 2. 异步：消息可以排队等待处理
# 3. 扩展：可以轻松添加新的渠道或处理器
#
# dataclass 简介：
# --------------
# @dataclass 是 Python 的装饰器，自动生成常用方法：
# - __init__(): 构造函数
# - __repr__(): 字符串表示
# - __eq__(): 相等比较
# 这样可以用更少的代码定义数据类。
# =============================================================================

"""Event types for the message bus."""
# 消息总线的事件类型定义

from dataclasses import dataclass, field  # 数据类装饰器
from datetime import datetime  # 时间处理
from typing import Any  # 任意类型注解


# =============================================================================
# InboundMessage - 入站消息
# =============================================================================

@dataclass
class InboundMessage:
    """
    从聊天渠道接收的消息。

    当用户发送消息时，渠道模块（如 Telegram、Discord 等）会创建
    一个 InboundMessage 对象，并发布到消息总线。

    属性说明：
    --------
    channel: str
        渠道名称，标识消息来源
        可能的值："telegram", "discord", "slack", "whatsapp", "feishu", "dingtalk" 等

    sender_id: str
        发送者 ID
        - Telegram: 用户 ID 或用户名
        - Discord: 用户 ID
        - WhatsApp: 电话号码

    chat_id: str
        聊天/频道 ID
        - 私聊：用户 ID
        - 群聊：群聊 ID
        用于区分不同的聊天场景

    content: str
        消息文本内容
        用户发送的实际消息内容

    timestamp: datetime
        消息接收时间
        默认值：datetime.now()（创建对象时的当前时间）

    media: list[str]
        媒体文件 URL 列表
        如果消息包含图片、音频、视频等，URL 会存储在这里
        默认值：空列表 []

    metadata: dict[str, Any]
        渠道特定的元数据
        不同渠道可能需要额外信息，如：
        - Telegram: message_id, reply_to_message
        - Discord: message_reference
        默认值：空字典 {}

    session_key_override: str | None
        会话密钥覆盖（可选）
        默认情况下，会话密钥由 channel:chat_id 生成
        如果设置了这个值，使用自定义的会话密钥
        用于特殊的会话管理场景
        默认值：None

    示例：
        >>> msg = InboundMessage(
        ...     channel="telegram",
        ...     sender_id="123456",
        ...     chat_id="123456",
        ...     content="Hello, bot!"
        ... )
        >>> print(msg.session_key)
        'telegram:123456'
    """

    channel: str  # 渠道名称
    sender_id: str  # 发送者 ID
    chat_id: str  # 聊天 ID
    content: str  # 消息内容
    timestamp: datetime = field(default_factory=datetime.now)  # 时间戳
    media: list[str] = field(default_factory=list)  # 媒体 URL 列表
    metadata: dict[str, Any] = field(default_factory=dict)  # 元数据
    session_key_override: str | None = None  # 会话密钥覆盖

    @property
    def session_key(self) -> str:
        """
        获取会话的唯一标识密钥。

        会话密钥用于：
        1. 区分不同用户的对话
        2. 维护对话上下文（历史记忆）
        3. 多聊天场景的会话隔离

        生成规则：
        - 如果设置了 session_key_override，返回自定义值
        - 否则返回 "{channel}:{chat_id}"

        Returns:
            str: 会话密钥

        示例：
            >>> msg.channel = "telegram"
            >>> msg.chat_id = "123456"
            >>> msg.session_key
            'telegram:123456'

            >>> msg.session_key_override = "custom_session"
            >>> msg.session_key
            'custom_session'
        """
        # 如果有自定义覆盖，返回自定义值；否则自动生成
        return self.session_key_override or f"{self.channel}:{self.chat_id}"


# =============================================================================
# OutboundMessage - 出站消息
# =============================================================================

@dataclass
class OutboundMessage:
    """
    要发送到聊天渠道的消息。

    当 Agent 处理完用户消息后，会创建一个 OutboundMessage 对象，
    发布到消息总线，由对应的渠道模块发送到用户。

    属性说明：
    --------
    channel: str
        目标渠道名称
        必须与 InboundMessage 的 channel 匹配，才能发送回正确的渠道

    chat_id: str
        目标聊天 ID
        指定消息发送到哪个聊天（私聊或群聊）

    content: str
        消息文本内容
        Agent 生成的回复内容

    reply_to: str | None
        回复目标消息 ID（可选）
        如果设置，消息会作为对某条消息的回复发送
        用于保持对话连贯性
        默认值：None

    media: list[str]
        要发送的媒体文件 URL 列表
        如果 Agent 生成了图片、音频等，URL 会存储在这里
        默认值：空列表 []

    metadata: dict[str, Any]
        渠道特定的元数据
        可以包含渠道特有的发送选项
        默认值：空字典 {}

    示例：
        >>> msg = OutboundMessage(
        ...     channel="telegram",
        ...     chat_id="123456",
        ...     content="Hello, human!",
        ...     reply_to="987654"
        ... )
    """

    channel: str  # 目标渠道
    chat_id: str  # 目标聊天 ID
    content: str  # 消息内容
    reply_to: str | None = None  # 回复目标
    media: list[str] = field(default_factory=list)  # 媒体 URL 列表
    metadata: dict[str, Any] = field(default_factory=dict)  # 元数据

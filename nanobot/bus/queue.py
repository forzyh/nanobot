# =============================================================================
# nanobot 消息总线（消息队列）
# 文件路径：nanobot/bus/queue.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 MessageBus 类，是一个异步消息队列。
#
# 什么是消息总线？
# --------------
# 消息总线（Message Bus）是 nanobot 的"神经系统"，负责在各个组件之间传递消息。
#
# 消息流向：
# ---------
#
#   Telegram 渠道 ──┐
#   Discord 渠道 ──┤
#   WhatsApp 渠道 ──┼→ Inbound Queue → Agent → Outbound Queue → 各渠道
#   Feishu 渠道 ──┤
#   ...          ──┘
#
# 为什么需要消息总线？
# ------------------
# 1. 解耦：渠道模块和 Agent 模块不需要直接通信
# 2. 缓冲：消息可以排队，防止请求洪峰
# 3. 异步：渠道接收消息和 Agent 处理消息可以并行进行
# 4. 扩展：可以轻松添加新渠道或新处理器
#
# asyncio.Queue 简介：
# ------------------
# asyncio.Queue 是 Python 异步队列，支持：
# - put(): 放入元素（异步）
# - get(): 取出元素（异步，队列为空时等待）
# - qsize(): 获取队列大小
#
# 与同步队列的区别：
# - 同步队列会阻塞线程
# - 异步队列使用 await，不阻塞事件循环
# =============================================================================

"""Async message queue for decoupled channel-agent communication."""
# 异步消息队列，用于渠道和 Agent 之间的解耦通信

import asyncio  # Python 异步编程库

from nanobot.bus.events import InboundMessage, OutboundMessage  # 导入事件类型


class MessageBus:
    """
    异步消息总线，解耦聊天渠道和 Agent 核心。

    工作原理：
    --------
    1. 渠道模块将接收到的消息放入 inbound 队列
    2. Agent 从 inbound 队列获取消息并处理
    3. Agent 将响应放入 outbound 队列
    4. 渠道模块从 outbound 队列获取消息并发送

    队列类型：
    --------
    - inbound: asyncio.Queue[InboundMessage]
      存储从渠道接收的待处理消息

    - outbound: asyncio.Queue[OutboundMessage]
      存储 Agent 生成的待发送消息

    使用场景：
    --------
    1. 用户发送消息 → Telegram 渠道 → bus.publish_inbound()
    2. Agent 运行 → bus.consume_inbound() → 处理 → bus.publish_outbound()
    3. Telegram 渠道 → bus.consume_outbound() → 发送给用户

    示例：
        >>> bus = MessageBus()
        >>> await bus.publish_inbound(msg)
        >>> received = await bus.consume_inbound()
    """

    def __init__(self):
        """
        初始化消息总线。

        创建两个异步队列：
        - inbound: 入站消息队列（渠道 → Agent）
        - outbound: 出站消息队列（Agent → 渠道）
        """
        # 入站队列：存储待处理的入站消息
        # 泛型标注：Queue[InboundMessage] 表示队列中只能放 InboundMessage 对象
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()

        # 出站队列：存储待发送的出站消息
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """
        发布消息到入站队列（渠道 → Agent）。

        使用场景：
        - Telegram 渠道收到用户消息后调用
        - Discord 渠道收到用户消息后调用
        - 任何渠道收到消息后都调用这个函数

        Args:
            msg: InboundMessage 对象

        异步操作：
        --------
        await self.inbound.put(msg)
        - 如果队列未满，立即放入
        - 如果队列已满（有上限时），等待直到有空间

        示例：
            >>> msg = InboundMessage(channel="telegram", ...)
            >>> await bus.publish_inbound(msg)
        """
        await self.inbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        """
        从入站队列消费（获取）下一条消息（Agent 使用）。

        行为特点：
        --------
        - 如果队列有消息：立即返回
        - 如果队列为空：阻塞等待，直到有新消息
        - 这是异步阻塞，不会阻止其他异步任务运行

        Returns:
            InboundMessage: 队列中的下一条消息

        使用场景：
        --------
        Agent 主循环中调用这个函数，等待并处理用户消息。

        示例：
            >>> msg = await bus.consume_inbound()
            >>> print(f"收到来自 {msg.channel} 的消息：{msg.content}")
        """
        return await self.inbound.get()

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """
        发布消息到出站队列（Agent → 渠道）。

        使用场景：
        - Agent 生成回复后调用
        - 系统通知需要发送时调用

        Args:
            msg: OutboundMessage 对象

        示例：
            >>> msg = OutboundMessage(channel="telegram", content="Hello!")
            >>> await bus.publish_outbound(msg)
        """
        await self.outbound.put(msg)

    async def consume_outbound(self) -> OutboundMessage:
        """
        从出站队列消费（获取）下一条消息（渠道使用）。

        行为特点：
        --------
        - 如果队列有消息：立即返回
        - 如果队列为空：阻塞等待，直到有新消息

        Returns:
            OutboundMessage: 队列中的下一条消息

        使用场景：
        --------
        渠道模块在发送循环中调用这个函数，获取要发送的消息。

        示例：
            >>> msg = await bus.consume_outbound()
            >>> await telegram_bot.send_message(msg.chat_id, msg.content)
        """
        return await self.outbound.get()

    @property
    def inbound_size(self) -> int:
        """
        获取入站队列中等待处理的消息数量。

        用途：
        ----
        - 监控系统负载
        - 调试和日志
        - 性能分析

        Returns:
            int: 入站消息数量

        示例：
            >>> bus.inbound_size
            5  # 有 5 条消息等待处理
        """
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        """
        获取出站队列中等待发送的消息数量。

        用途：
        ----
        - 监控系统负载
        - 检测发送延迟
        - 调试和日志

        Returns:
            int: 出站消息数量

        示例：
            >>> bus.outbound_size
            3  # 有 3 条消息等待发送
        """
        return self.outbound.qsize()

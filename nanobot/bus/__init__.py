# =============================================================================
# nanobot 消息总线模块入口
# 文件路径：nanobot/bus/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这是 nanobot 消息总线模块的入口文件，导出消息总线和事件类型。
#
# 什么是消息总线（Message Bus）？
# ----------------------------
# 消息总线是一种软件架构模式，用于组件间的异步通信。
# 在 nanobot 中，消息总线连接了渠道模块和 Agent 核心。
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
#    - 渠道模块只需要知道如何发布消息到总线
#    - Agent 只需要知道如何从总线消费消息
#    - 两者互不依赖，易于扩展和维护
#
# 2. 缓冲：消息可以排队，防止请求洪峰
#    - 当多个渠道同时收到消息时，消息会排队等待处理
#    - Agent 按顺序处理，不会丢失消息
#
# 3. 异步：渠道接收消息和 Agent 处理消息可以并行进行
#    - 渠道可以继续接收新消息， while Agent 在处理之前的消息
#    - 提高整体吞吐量
#
# 4. 扩展：可以轻松添加新渠道或新处理器
#    - 添加新渠道：只需实现渠道模块，发布/消费消息
#    - 添加新处理器：只需消费消息总线，处理消息
#
# 模块结构：
# ---------
# bus/
# ├── __init__.py       # 模块入口（本文件）
# ├── events.py         # 事件类型定义
# │   ├── InboundMessage  # 入站消息（渠道 → Agent）
# │   └── OutboundMessage # 出站消息（Agent → 渠道）
# └── queue.py          # 消息队列实现
#     └── MessageBus      # 消息总线类
#
# 使用示例：
# --------
# from nanobot.bus import MessageBus, InboundMessage, OutboundMessage
#
# # 创建消息总线
# bus = MessageBus()
#
# # 发布入站消息（渠道 → Agent）
# msg = InboundMessage(
#     channel="telegram",
#     sender_id="123456",
#     chat_id="123456",
#     content="Hello, bot!"
# )
# await bus.publish_inbound(msg)
#
# # 消费入站消息（Agent 使用）
# msg = await bus.consume_inbound()
# print(f"收到来自 {msg.channel} 的消息：{msg.content}")
#
# # 发布出站消息（Agent → 渠道）
# response = OutboundMessage(
#     channel="telegram",
#     chat_id="123456",
#     content="Hello, human!"
# )
# await bus.publish_outbound(response)
#
# # 消费出站消息（渠道使用）
# msg = await bus.consume_outbound()
# await telegram_bot.send_message(msg.chat_id, msg.content)
# =============================================================================

"""Message bus module for decoupled channel-agent communication."""
# 消息总线模块：用于渠道和 Agent 之间的解耦通信

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]

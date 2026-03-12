# =============================================================================
# nanobot 消息工具
# 文件路径：nanobot/agent/tools/message.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 MessageTool，让 Agent 能够发送消息给用户。
#
# 什么是 MessageTool？
# -----------------
# MessageTool 是 Agent 用来与用户通信的工具：
# - 发送文本消息
# - 发送带附件的消息（图片、音频、文档）
# - 支持指定目标渠道和聊天 ID
#
# 使用场景：
# --------
# 1. 主动通知：定时任务完成时发送通知
# 2. 后台任务：心跳服务检测到任务时执行并发送结果
# 3. 主动推送：Agent 有重要信息时主动联系用户
#
# 工作原理：
# --------
# 1. 构建 OutboundMessage 对象
# 2. 通过回调函数发送到消息总线
# 3. 消息总线路由到正确的渠道
# 4. 渠道发送到具体的聊天平台
#
# 使用示例：
# --------
# # Agent 调用
# {"content": "任务已完成", "channel": "telegram", "chat_id": "123456"}
#
# # 发送带附件的消息
# {"content": "这是截图", "media": ["/tmp/screenshot.png"]}
# =============================================================================

"""Message tool for sending messages to users."""
# 用于向用户发送消息的工具

from typing import Any, Awaitable, Callable  # 类型注解

from nanobot.agent.tools.base import Tool  # 工具基类
from nanobot.bus.events import OutboundMessage  # 出站消息事件


class MessageTool(Tool):
    """
    用于向聊天渠道用户发送消息的工具。

    这个工具让 Agent 能够主动发送消息给用户：
    1. 文本消息
    2. 带附件的消息（图片、音频、文档）
    3. 支持指定目标渠道和聊天 ID

    核心特性：
    --------
    1. 上下文追踪：记录默认渠道和聊天 ID
    2. 每轮发送标记：追踪每轮对话中是否已发送消息
    3. 回调机制：通过回调函数发送消息（解耦设计）

    属性说明：
    --------
    _send_callback: Callable[[OutboundMessage], Awaitable[None]] | None
        发送消息的回调函数
        通常绑定到消息总线的发送方法

    _default_channel: str
        默认渠道（如 "telegram"）

    _default_chat_id: str
        默认聊天 ID

    _default_message_id: str | None
        默认消息 ID（用于回复）

    _sent_in_turn: bool
        标记当前轮次是否已发送消息

    使用示例：
    --------
    >>> tool = MessageTool(
    ...     send_callback=message_bus.send,
    ...     default_channel="telegram",
    ...     default_chat_id="123456"
    ... )
    >>> result = await tool.execute(content="Hello!")
    >>> print(result)
    Message sent to telegram:123456
    """

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
        default_message_id: str | None = None,
    ):
        """
        初始化消息工具。

        Args:
            send_callback: 发送消息的回调函数
                接收 OutboundMessage，返回 None
            default_channel: 默认渠道
            default_chat_id: 默认聊天 ID
            default_message_id: 默认消息 ID（用于回复）
        """
        self._send_callback = send_callback  # 发送回调
        self._default_channel = default_channel  # 默认渠道
        self._default_chat_id = default_chat_id  # 默认聊天 ID
        self._default_message_id = default_message_id  # 默认消息 ID
        self._sent_in_turn: bool = False  # 当前轮次是否已发送

    def set_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """
        设置当前消息上下文。

        Args:
            channel: 渠道名称（如 "telegram"）
            chat_id: 聊天 ID
            message_id: 消息 ID（可选，用于回复）
        """
        self._default_channel = channel
        self._default_chat_id = chat_id
        self._default_message_id = message_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """
        设置发送消息的回调函数。

        Args:
            callback: 回调函数
        """
        self._send_callback = callback

    def start_turn(self) -> None:
        """
        重置每轮发送标记。

        在每轮对话开始时调用，重置 _sent_in_turn 标志。
        """
        self._sent_in_turn = False

    @property
    def name(self) -> str:
        return "message"

    @property
    def description(self) -> str:
        return "Send a message to the user. Use this when you want to communicate something."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The message content to send"
                },
                "channel": {
                    "type": "string",
                    "description": "Optional: target channel (telegram, discord, etc.)"
                },
                "chat_id": {
                    "type": "string",
                    "description": "Optional: target chat/user ID"
                },
                "media": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: list of file paths to attach (images, audio, documents)"
                }
            },
            "required": ["content"]
        }

    async def execute(
        self,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        media: list[str] | None = None,
        **kwargs: Any
    ) -> str:
        """
        执行发送消息操作。

        Args:
            content: 消息内容
            channel: 目标渠道（可选，默认使用上下文）
            chat_id: 目标聊天 ID（可选，默认使用上下文）
            message_id: 消息 ID（可选，用于回复）
            media: 附件列表（可选）
            **kwargs: 其他参数

        Returns:
            str: 发送成功返回成功信息，失败返回错误

        发送流程：
        --------
        1. 使用传入的或默认的 channel/chat_id
        2. 构建 OutboundMessage 对象
        3. 调用回调函数发送
        4. 记录发送状态
        5. 返回结果

        错误处理：
        --------
        - 没有渠道/聊天 ID：返回错误
        - 回调未配置：返回错误
        - 发送异常：返回错误信息
        """
        # 使用传入的或默认的渠道/聊天 ID
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id
        message_id = message_id or self._default_message_id

        # 检查目标是否有效
        if not channel or not chat_id:
            return "Error: No target channel/chat specified"

        # 检查回调是否配置
        if not self._send_callback:
            return "Error: Message sending not configured"

        # 构建出站消息
        msg = OutboundMessage(
            channel=channel,
            chat_id=chat_id,
            content=content,
            media=media or [],
            metadata={
                "message_id": message_id,  # 用于回复
            },
        )

        try:
            # 调用回调发送消息
            await self._send_callback(msg)
            # 如果是当前会话，标记为已发送
            if channel == self._default_channel and chat_id == self._default_chat_id:
                self._sent_in_turn = True
            # 返回成功信息
            media_info = f" with {len(media)} attachments" if media else ""
            return f"Message sent to {channel}:{chat_id}{media_info}"
        except Exception as e:
            # 返回错误信息
            return f"Error sending message: {str(e)}"

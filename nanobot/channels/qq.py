# =============================================================================
# nanobot QQ 渠道
# 文件路径：nanobot/channels/qq.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 QQChannel 类，让 nanobot 能够通过 QQ 与用户交互。
#
# 什么是 QQChannel？
# ------------------
# QQChannel 是 nanobot 与 QQ 平台的"适配器"：
# 1. 使用 botpy SDK 连接 QQ 开放平台
# 2. 支持 C2C（单聊）和 Group（群聊）消息
# 3. 通过 WebSocket 长连接接收消息
# 4. 通过 HTTP API 发送消息
#
# 为什么需要 QQ 渠道？
# ------------------
# 1. 年轻用户群体：QQ 在中国年轻用户中广泛使用
# 2. 群聊功能：支持 QQ 群机器人
# 3. 多媒体支持：支持文本、图片、表情等
# 4. 官方 SDK：使用腾讯官方 botpy SDK，稳定可靠
#
# 工作原理：
# ---------
# 入站（接收消息）：
# 1. 通过 botpy.Client 建立 WebSocket 连接
# 2. 监听 on_c2c_message_create（单聊消息）
# 3. 监听 on_group_at_message_create（群聊@消息）
# 4. 监听 on_direct_message_create（频道私信）
# 5. 将消息转换为 InboundMessage 发布到消息总线
#
# 出站（发送消息）：
# 1. 从消息总线获取 OutboundMessage
# 2. 根据聊天类型调用 post_c2c_message 或 post_group_message
# 3. 使用 msg_seq 避免被 QQ API 去重
# 4. 支持 Markdown 格式消息
#
# 配置示例：
# --------
# {
#   "channels": {
#     "qq": {
#       "enabled": true,
#       "appId": "your-app-id",
#       "secret": "your-app-secret"
#     }
#   }
# }
#
# 依赖安装：
# --------
# pip install qq-botpy
#
# 注意事项：
# --------
# 1. 需要在 QQ 开放平台创建机器人应用
# 2. 需要配置正确的回调地址和权限
# 3. 群聊需要机器人被添加到群并授予权限
# =============================================================================

"""QQ channel implementation using botpy SDK."""
# QQ 渠道：使用 botpy SDK 实现 QQ 机器人功能

import asyncio
from collections import deque
from typing import TYPE_CHECKING

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import QQConfig

try:
    import botpy
    from botpy.message import C2CMessage, GroupMessage

    QQ_AVAILABLE = True
except ImportError:
    QQ_AVAILABLE = False
    botpy = None
    C2CMessage = None
    GroupMessage = None

if TYPE_CHECKING:
    from botpy.message import C2CMessage, GroupMessage


def _make_bot_class(channel: "QQChannel") -> "type[botpy.Client]":
    """
    创建绑定到指定渠道的 botpy Client 子类。

    此函数动态创建一个 Bot 类，继承自 botpy.Client，
    并重写事件处理方法以调用 QQChannel 的内部方法。

    Args:
        channel: QQChannel 实例

    Returns:
        动态创建的 Bot 类
    """
    intents = botpy.Intents(public_messages=True, direct_message=True)

    class _Bot(botpy.Client):
        def __init__(self):
            # 禁用 botpy 的文件日志 — nanobot 使用 loguru；默认 "botpy.log" 在只读文件系统上会失败
            super().__init__(intents=intents, ext_handlers=False)

        async def on_ready(self):
            logger.info("QQ bot ready: {}", self.robot.name)

        async def on_c2c_message_create(self, message: "C2CMessage"):
            await channel._on_message(message, is_group=False)

        async def on_group_at_message_create(self, message: "GroupMessage"):
            await channel._on_message(message, is_group=True)

        async def on_direct_message_create(self, message):
            await channel._on_message(message, is_group=False)

    return _Bot


class QQChannel(BaseChannel):
    """
    使用 botpy SDK 和 WebSocket 连接的 QQ 渠道。

    支持的消息类型：
    - C2C 消息（单聊）
    - 群聊消息（需要@机器人）
    - 频道私信

    特点：
    - WebSocket 长连接接收消息
    - 自动重连机制
    - 消息去重（基于 message ID）
    - 支持 Markdown 格式发送消息
    """

    name = "qq"
    display_name = "QQ"

    def __init__(self, config: QQConfig, bus: MessageBus):
        """
        初始化 QQ 渠道。

        Args:
            config: QQ 配置对象（包含 app_id 和 secret）
            bus: 消息总线实例
        """
        super().__init__(config, bus)
        self.config: QQConfig = config
        self._client: "botpy.Client | None" = None
        self._processed_ids: deque = deque(maxlen=1000)
        self._msg_seq: int = 1  # 消息序列号，避免被 QQ API 去重
        self._chat_type_cache: dict[str, str] = {}

    async def start(self) -> None:
        """
        启动 QQ 机器人。

        检查 SDK 可用性和配置完整性，然后启动 botpy 客户端。
        如果 SDK 未安装或配置不完整，会记录错误日志并返回。
        """
        if not QQ_AVAILABLE:
            logger.error("QQ SDK not installed. Run: pip install qq-botpy")
            return

        if not self.config.app_id or not self.config.secret:
            logger.error("QQ app_id and secret not configured")
            return

        self._running = True
        BotClass = _make_bot_class(self)
        self._client = BotClass()
        logger.info("QQ bot started (C2C & Group supported)")
        await self._run_bot()

    async def _run_bot(self) -> None:
        """
        运行机器人连接，支持自动重连。

        当连接断开时，等待 5 秒后尝试重新连接。
        此循环会持续运行，直到 _running 标志被设置为 False。
        """
        while self._running:
            try:
                await self._client.start(appid=self.config.app_id, secret=self.config.secret)
            except Exception as e:
                logger.warning("QQ bot error: {}", e)
            if self._running:
                logger.info("Reconnecting QQ bot in 5 seconds...")
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """停止 QQ 机器人，关闭客户端连接。"""
        self._running = False
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
        logger.info("QQ bot stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """
        通过 QQ 发送消息。

        根据聊天类型（单聊或群聊）调用相应的 API：
        - 群聊：post_group_message
        - 单聊：post_c2c_message

        Args:
            msg: 出站消息对象，包含 chat_id、content 和 metadata
        """
        if not self._client:
            logger.warning("QQ client not initialized")
            return

        try:
            msg_id = msg.metadata.get("message_id")
            self._msg_seq += 1
            msg_type = self._chat_type_cache.get(msg.chat_id, "c2c")
            if msg_type == "group":
                await self._client.api.post_group_message(
                    group_openid=msg.chat_id,
                    msg_type=2,
                    markdown={"content": msg.content},
                    msg_id=msg_id,
                    msg_seq=self._msg_seq,
                )
            else:
                await self._client.api.post_c2c_message(
                    openid=msg.chat_id,
                    msg_type=2,
                    markdown={"content": msg.content},
                    msg_id=msg_id,
                    msg_seq=self._msg_seq,
                )
        except Exception as e:
            logger.error("Error sending QQ message: {}", e)

    async def _on_message(self, data: "C2CMessage | GroupMessage", is_group: bool = False) -> None:
        """
        处理来自 QQ 的入站消息。

        1. 消息去重（基于 message ID）
        2. 提取发送者 ID 和聊天 ID
        3. 将消息发布到消息总线

        Args:
            data: botpy 消息对象（C2CMessage 或 GroupMessage）
            is_group: 是否为群聊消息
        """
        try:
            # 基于消息 ID 去重
            if data.id in self._processed_ids:
                return
            self._processed_ids.append(data.id)

            content = (data.content or "").strip()
            if not content:
                return

            if is_group:
                chat_id = data.group_openid
                user_id = data.author.member_openid
                self._chat_type_cache[chat_id] = "group"
            else:
                chat_id = str(getattr(data.author, 'id', None) or getattr(data.author, 'user_openid', 'unknown'))
                user_id = chat_id
                self._chat_type_cache[chat_id] = "c2c"

            await self._handle_message(
                sender_id=user_id,
                chat_id=chat_id,
                content=content,
                metadata={"message_id": data.id},
            )
        except Exception:
            logger.exception("Error handling QQ message")

# =============================================================================
# nanobot WhatsApp 渠道
# 文件路径：nanobot/channels/whatsapp.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 WhatsAppChannel 类，让 nanobot 能够通过 WhatsApp 与用户交互。
#
# 什么是 WhatsAppChannel？
# --------------------
# WhatsAppChannel 是 nanobot 与 WhatsApp 平台的"适配器"：
# 1. 通过 Node.js 桥接服务连接 WhatsApp
# 2. 使用 @whiskeysockets/baileys 处理 WhatsApp Web 协议
# 3. Python 与 Node.js 通过 WebSocket 通信
#
# 为什么需要桥接服务？
# -----------------
# WhatsApp 没有官方 Bot API，需要使用第三方库：
# - @whiskeysockets/baileys: WhatsApp Web 逆向工程库
# - Node.js 桥接：处理 WebSocket 连接和消息转发
#
# 架构设计：
# ---------
#   WhatsApp ←→ Node.js Bridge (Baileys) ←→ WebSocket ←→ Python Channel
#      平台               协议处理            通信         消息总线
#
# 使用示例：
# --------
# # 配置 WhatsApp
# {
#   "channels": {
#     "whatsapp": {
#       "enabled": true,
#       "bridge_url": "ws://localhost:8080",
#       "bridge_token": "your-token",
#       "allow_from": ["*"]
#     }
#   }
# }
# =============================================================================

"""WhatsApp channel implementation using Node.js bridge."""
# 使用 Node.js 桥接实现 WhatsApp 渠道

import asyncio
import json
import mimetypes
from collections import OrderedDict

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import WhatsAppConfig


class WhatsAppChannel(BaseChannel):
    """
    使用 Node.js 桥接的 WhatsApp 渠道实现。

    核心特性：
    --------
    1. WebSocket 桥接：通过 Node.js 服务连接 WhatsApp
    2. 消息去重：使用 OrderedDict 记录已处理的消息 ID
    3. 自动重连：桥接断开后 5 秒自动重连
    4. LID 支持：使用长 ID（LID）替代旧的电话号码格式

    属性说明：
    --------
    name: str
        渠道名称："whatsapp"

    display_name: str
        显示名称："WhatsApp"

    _ws: websockets.WebSocketClientProtocol | None
        与 Node.js 桥接的 WebSocket 连接

    _connected: bool
        桥接连接状态

    _processed_message_ids: OrderedDict[str, None]
        已处理的消息 ID 集合（防止重复处理）
        最多保留 1000 条记录

    使用示例：
    --------
    >>> config = WhatsAppConfig(bridge_url="ws://localhost:8080")
    >>> channel = WhatsAppChannel(config, message_bus)
    >>> await channel.start()  # 启动桥接连接
    """

    name = "whatsapp"
    display_name = "WhatsApp"

    def __init__(self, config: WhatsAppConfig, bus: MessageBus):
        """
        初始化 WhatsApp 渠道。

        Args:
            config: WhatsApp 配置对象（包含 bridge_url、bridge_token 等）
            bus: 消息总线实例
        """
        super().__init__(config, bus)
        self.config: WhatsAppConfig = config  # WhatsApp 配置
        self._ws = None  # WebSocket 连接
        self._connected = False  # 连接状态
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()  # 已处理消息 ID 集合

    async def start(self) -> None:
        """
        启动 WhatsApp 渠道（连接到 Node.js 桥接）。

        启动流程：
        --------
        1. 连接到桥接 WebSocket
        2. 发送认证 token（如果配置）
        3. 监听桥接消息
        4. 处理传入消息
        5. 断线自动重连（5 秒间隔）

        重连机制：
        --------
        - WebSocket 断开时捕获异常
        - 等待 5 秒后重新连接
        - 持续循环直到 stopped

        注意：
        ----
        这是一个长期运行的方法，会持续监听直到 stop() 被调用。
        """
        import websockets

        bridge_url = self.config.bridge_url

        logger.info("Connecting to WhatsApp bridge at {}...", bridge_url)

        self._running = True

        while self._running:
            try:
                async with websockets.connect(bridge_url) as ws:
                    self._ws = ws
                    # 发送认证 token（如果配置）
                    if self.config.bridge_token:
                        await ws.send(json.dumps({"type": "auth", "token": self.config.bridge_token}))
                    self._connected = True
                    logger.info("Connected to WhatsApp bridge")

                    # 监听消息
                    async for message in ws:
                        try:
                            await self._handle_bridge_message(message)
                        except Exception as e:
                            logger.error("Error handling bridge message: {}", e)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._connected = False
                self._ws = None
                logger.warning("WhatsApp bridge connection error: {}", e)

                if self._running:
                    logger.info("Reconnecting in 5 seconds...")
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """
        停止 WhatsApp 渠道。

        停止流程：
        --------
        1. 设置运行标志为 False
        2. 关闭 WebSocket 连接
        3. 清理引用
        """
        self._running = False
        self._connected = False

        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send(self, msg: OutboundMessage) -> None:
        """
        通过 WhatsApp 发送消息。

        发送流程：
        --------
        1. 检查桥接是否连接
        2. 构建 JSON 负载（type、to、text）
        3. 通过 WebSocket 发送

        Args:
            msg: 出站消息对象（包含 chat_id、content 等）
        """
        if not self._ws or not self._connected:
            logger.warning("WhatsApp bridge not connected")
            return

        try:
            payload = {
                "type": "send",
                "to": msg.chat_id,
                "text": msg.content
            }
            await self._ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            logger.error("Error sending WhatsApp message: {}", e)

    async def _handle_bridge_message(self, raw: str) -> None:
        """
        处理来自桥接的消息。

        处理流程：
        --------
        1. 解析 JSON 消息
        2. 消息去重（检查 message_id）
        3. 提取发送者 ID 和内容
        4. 处理媒体文件（图片、文档等）
        5. 转发到消息总线

        消息去重：
        --------
        使用 OrderedDict 记录已处理的消息 ID，最多保留 1000 条。
        如果消息 ID 已存在，直接返回（避免重复处理）。

        Args:
            raw: 桥接发送的原始 JSON 字符串
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON from bridge: {}", raw[:100])
            return

        msg_type = data.get("type")

        if msg_type == "message":
            # 来自 WhatsApp 的传入消息
            # 旧的电话号码格式：<phone>@s.whatsapp.net（已弃用）
            pn = data.get("pn", "")
            # 新的 LID 格式
            sender = data.get("sender", "")
            content = data.get("content", "")
            message_id = data.get("id", "")

            # 消息去重
            if message_id:
                if message_id in self._processed_message_ids:
                    return  # 已处理，跳过
                self._processed_message_ids[message_id] = None
                # 限制缓存大小（最多 1000 条）
                while len(self._processed_message_ids) > 1000:
                    self._processed_message_ids.popitem(last=False)

            # 提取发送者 ID（去除@后缀）
            user_id = pn if pn else sender
            sender_id = user_id.split("@")[0] if "@" in user_id else user_id
            logger.info("Sender {}", sender)

            # 处理语音消息（暂不支持转录）
            if content == "[Voice Message]":
                logger.info("Voice message received from {}, but direct download from bridge is not yet supported.", sender_id)
                content = "[Voice Message: Transcription not available for WhatsApp yet]"

            # 提取媒体路径（桥接下载的图片/文档/视频）
            media_paths = data.get("media") or []

            # 构建内容标签（与 Telegram 格式一致）
            if media_paths:
                for p in media_paths:
                    mime, _ = mimetypes.guess_type(p)
                    media_type = "image" if mime and mime.startswith("image/") else "file"
                    media_tag = f"[{media_type}: {p}]"
                    content = f"{content}\n{media_tag}" if content else media_tag

            # 转发到消息总线
            await self._handle_message(
                sender_id=sender_id,
                chat_id=sender,  # 使用完整 LID 进行回复
                content=content,
                media=media_paths,
                metadata={
                    "message_id": message_id,
                    "timestamp": data.get("timestamp"),
                    "is_group": data.get("isGroup", False)
                }
            )

        elif msg_type == "status":
            # Connection status update
            status = data.get("status")
            logger.info("WhatsApp status: {}", status)

            if status == "connected":
                self._connected = True
            elif status == "disconnected":
                self._connected = False

        elif msg_type == "qr":
            # QR code for authentication
            logger.info("Scan QR code in the bridge terminal to connect WhatsApp")

        elif msg_type == "error":
            logger.error("WhatsApp bridge error: {}", data.get('error'))

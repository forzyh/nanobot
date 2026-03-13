# =============================================================================
# nanobot 企业微信渠道
# 文件路径：nanobot/channels/wecom.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 WecomChannel 类，让 nanobot 能够通过企业微信与用户交互。
#
# 什么是 WecomChannel？
# --------------------
# WecomChannel 是 nanobot 与企业微信平台的"适配器"：
# 1. 通过 WebSocket 长连接接收消息事件（无需公网 IP）
# 2. 使用 wecom_aibot_sdk 处理企业微信 API
# 3. 支持文本、图片、语音、文件、混合内容等多种消息类型
# 4. 支持流式回复和欢迎消息
#
# 为什么需要 WebSocket 长连接？
# -------------------------
# 企业微信支持 WebSocket 长连接推送事件，无需：
# - 配置公网 IP
# - 设置 HTTP 回调地址
# - 处理事件签名验证
#
# 架构设计：
# ---------
#   企业微信 ←→ WebSocket ←→ wecom_aibot_sdk ←→ WecomChannel ←→ MessageBus
#     平台        长连接推送       协议处理         渠道适配         核心处理
#
# 使用示例：
# --------
# # 配置企业微信
# {
#   "channels": {
#     "wecom": {
#       "enabled": true,
#       "bot_id": "xxx",
#       "secret": "xxx",
#       "welcome_message": "你好，我是 AI 助手！"
#       "allow_from": ["*"]
#     }
#   }
# }
# =============================================================================

"""WeCom (Enterprise WeChat) channel implementation using wecom_aibot_sdk."""
# 使用 wecom_aibot_sdk 实现企业微信渠道

import asyncio
import importlib.util
import os
from collections import OrderedDict
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import WecomConfig

WECOM_AVAILABLE = importlib.util.find_spec("wecom_aibot_sdk") is not None

# 消息类型显示映射
# 将企业微信的消息类型转换为可读的文本格式
MSG_TYPE_MAP = {
    "image": "[image]",
    "voice": "[voice]",
    "file": "[file]",
    "mixed": "[mixed content]",
}


class WecomChannel(BaseChannel):
    """
    企业微信渠道实现，使用 WebSocket 长连接。

    功能特点：
    --------
    1. WebSocket 长连接接收事件，无需公网 IP 或 Webhook
    2. 支持多种消息类型：文本、图片、语音、文件、混合内容
    3. 自动消息去重，防止重复处理
    4. 支持流式回复，提升用户体验
    5. 支持欢迎消息（用户打开聊天窗口时自动发送）

    依赖：
    ----
    - wecom_aibot_sdk: 企业微信 AI Bot SDK
    - Bot ID 和 Secret（从企业微信 AI Bot 平台获取）
    """

    name = "wecom"
    display_name = "WeCom"

    def __init__(self, config: WecomConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: WecomConfig = config
        self._client: Any = None  # WebSocket 客户端实例
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()  # 已处理消息 ID 缓存
        self._loop: asyncio.AbstractEventLoop | None = None  # 事件循环
        self._generate_req_id = None  # 请求 ID 生成器
        # 存储每个聊天的帧头，用于支持回复功能
        self._chat_frames: dict[str, Any] = {}

    async def start(self) -> None:
        """
        启动企业微信机器人，建立 WebSocket 长连接。

        启动流程：
        1. 检查 SDK 是否已安装
        2. 验证配置（bot_id 和 secret）
        3. 创建 WebSocket 客户端
        4. 注册事件处理器
        5. 连接到企业微信
        6. 进入主循环等待事件
        """
        if not WECOM_AVAILABLE:
            logger.error("WeCom SDK not installed. Run: pip install nanobot-ai[wecom]")
            return

        if not self.config.bot_id or not self.config.secret:
            logger.error("WeCom bot_id and secret not configured")
            return

        from wecom_aibot_sdk import WSClient, generate_req_id

        self._running = True
        self._loop = asyncio.get_running_loop()
        self._generate_req_id = generate_req_id

        # 创建 WebSocket 客户端
        self._client = WSClient({
            "bot_id": self.config.bot_id,
            "secret": self.config.secret,
            "reconnect_interval": 1000,
            "max_reconnect_attempts": -1,  # 无限重连
            "heartbeat_interval": 30000,
        })

        # 注册事件处理器
        self._client.on("connected", self._on_connected)
        self._client.on("authenticated", self._on_authenticated)
        self._client.on("disconnected", self._on_disconnected)
        self._client.on("error", self._on_error)
        self._client.on("message.text", self._on_text_message)
        self._client.on("message.image", self._on_image_message)
        self._client.on("message.voice", self._on_voice_message)
        self._client.on("message.file", self._on_file_message)
        self._client.on("message.mixed", self._on_mixed_message)
        self._client.on("event.enter_chat", self._on_enter_chat)

        logger.info("WeCom bot starting with WebSocket long connection")
        logger.info("No public IP required - using WebSocket to receive events")

        # 建立连接
        await self._client.connect_async()

        # 持续运行直到被停止
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """
        停止企业微信机器人。

        清理流程：
        1. 设置运行标志为 False
        2. 断开 WebSocket 连接
        3. 记录日志
        """
        self._running = False
        if self._client:
            await self._client.disconnect()
        logger.info("WeCom bot stopped")

    async def _on_connected(self, frame: Any) -> None:
        """处理 WebSocket 连接成功事件。"""
        logger.info("WeCom WebSocket connected")

    async def _on_authenticated(self, frame: Any) -> None:
        """处理认证成功事件。"""
        logger.info("WeCom authenticated successfully")

    async def _on_disconnected(self, frame: Any) -> None:
        """处理 WebSocket 断开连接事件。"""
        reason = frame.body if hasattr(frame, 'body') else str(frame)
        logger.warning("WeCom WebSocket disconnected: {}", reason)

    async def _on_error(self, frame: Any) -> None:
        """处理错误事件。"""
        logger.error("WeCom error: {}", frame)

    async def _on_text_message(self, frame: Any) -> None:
        """处理文本消息。"""
        await self._process_message(frame, "text")

    async def _on_image_message(self, frame: Any) -> None:
        """处理图片消息。"""
        await self._process_message(frame, "image")

    async def _on_voice_message(self, frame: Any) -> None:
        """处理语音消息。"""
        await self._process_message(frame, "voice")

    async def _on_file_message(self, frame: Any) -> None:
        """处理文件消息。"""
        await self._process_message(frame, "file")

    async def _on_mixed_message(self, frame: Any) -> None:
        """处理混合内容消息。"""
        await self._process_message(frame, "mixed")

    async def _on_enter_chat(self, frame: Any) -> None:
        """
        处理用户进入聊天事件（用户打开与机器人的聊天窗口）。

        如果配置了欢迎消息，则自动发送欢迎语。
        """
        try:
            # 从 WsFrame 数据类或字典中提取 body
            if hasattr(frame, 'body'):
                body = frame.body or {}
            elif isinstance(frame, dict):
                body = frame.get("body", frame)
            else:
                body = {}

            chat_id = body.get("chatid", "") if isinstance(body, dict) else ""

            if chat_id and self.config.welcome_message:
                await self._client.reply_welcome(frame, {
                    "msgtype": "text",
                    "text": {"content": self.config.welcome_message},
                })
        except Exception as e:
            logger.error("Error handling enter_chat: {}", e)

    async def _process_message(self, frame: Any, msg_type: str) -> None:
        """
        处理收到的消息并转发到消息总线。

        处理流程：
        1. 从帧中提取消息体
        2. 生成或使用现有消息 ID
        3. 消息去重检查
        4. 提取发送者信息和聊天类型
        5. 根据消息类型提取/下载内容
        6. 构建消息内容并转发到消息总线

        Args:
            frame: WebSocket 帧对象
            msg_type: 消息类型（text/image/voice/file/mixed）
        """
        try:
            # 从 WsFrame 数据类或字典中提取 body
            if hasattr(frame, 'body'):
                body = frame.body or {}
            elif isinstance(frame, dict):
                body = frame.get("body", frame)
            else:
                body = {}

            # 确保 body 是字典类型
            if not isinstance(body, dict):
                logger.warning("Invalid body type: {}", type(body))
                return

            # 提取消息信息
            msg_id = body.get("msgid", "")
            if not msg_id:
                msg_id = f"{body.get('chatid', '')}_{body.get('sendertime', '')}"

            # 去重检查
            if msg_id in self._processed_message_ids:
                return
            self._processed_message_ids[msg_id] = None

            # 修剪缓存（保持最多 1000 条）
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            # 从 "from" 字段提取发送者信息（SDK 格式）
            from_info = body.get("from", {})
            sender_id = from_info.get("userid", "unknown") if isinstance(from_info, dict) else "unknown"

            # 单聊时 chatid 是用户 ID，群聊时 body 中包含 chatid
            chat_type = body.get("chattype", "single")
            chat_id = body.get("chatid", sender_id)

            content_parts = []

            if msg_type == "text":
                text = body.get("text", {}).get("content", "")
                if text:
                    content_parts.append(text)

            elif msg_type == "image":
                image_info = body.get("image", {})
                file_url = image_info.get("url", "")
                aes_key = image_info.get("aeskey", "")

                if file_url and aes_key:
                    file_path = await self._download_and_save_media(file_url, aes_key, "image")
                    if file_path:
                        filename = os.path.basename(file_path)
                        content_parts.append(f"[image: {filename}]\n[Image: source: {file_path}]")
                    else:
                        content_parts.append("[image: download failed]")
                else:
                    content_parts.append("[image: download failed]")

            elif msg_type == "voice":
                voice_info = body.get("voice", {})
                # 语音消息已包含企业微信的转录内容
                voice_content = voice_info.get("content", "")
                if voice_content:
                    content_parts.append(f"[voice] {voice_content}")
                else:
                    content_parts.append("[voice]")

            elif msg_type == "file":
                file_info = body.get("file", {})
                file_url = file_info.get("url", "")
                aes_key = file_info.get("aeskey", "")
                file_name = file_info.get("name", "unknown")

                if file_url and aes_key:
                    file_path = await self._download_and_save_media(file_url, aes_key, "file", file_name)
                    if file_path:
                        content_parts.append(f"[file: {file_name}]\n[File: source: {file_path}]")
                    else:
                        content_parts.append(f"[file: {file_name}: download failed]")
                else:
                    content_parts.append(f"[file: {file_name}: download failed]")

            elif msg_type == "mixed":
                # 混合内容包含多个消息项
                msg_items = body.get("mixed", {}).get("item", [])
                for item in msg_items:
                    item_type = item.get("type", "")
                    if item_type == "text":
                        text = item.get("text", {}).get("content", "")
                        if text:
                            content_parts.append(text)
                    else:
                        content_parts.append(MSG_TYPE_MAP.get(item_type, f"[{item_type}]"))

            else:
                content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))

            content = "\n".join(content_parts) if content_parts else ""

            if not content:
                return

            # 为该聊天存储帧，以便后续回复
            self._chat_frames[chat_id] = frame

            # 转发到消息总线
            # 注意：为了更广泛的模型兼容性，media 路径包含在 content 中
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=content,
                media=None,
                metadata={
                    "message_id": msg_id,
                    "msg_type": msg_type,
                    "chat_type": chat_type,
                }
            )

        except Exception as e:
            logger.error("Error processing WeCom message: {}", e)

    async def _download_and_save_media(
        self,
        file_url: str,
        aes_key: str,
        media_type: str,
        filename: str | None = None,
    ) -> str | None:
        """
        下载并解密企业微信媒体文件。

        流程：
        1. 使用 SDK 下载加密的媒体文件
        2. 使用 AES 密钥解密
        3. 保存到本地媒体目录

        Args:
            file_url: 媒体文件 URL
            aes_key: AES 解密密钥
            media_type: 媒体类型（image/file）
            filename: 可选的文件名
        Returns:
            str | None: 保存的文件路径，如果下载失败则返回 None
        """
        try:
            data, fname = await self._client.download_file(file_url, aes_key)

            if not data:
                logger.warning("Failed to download media from WeCom")
                return None

            media_dir = get_media_dir("wecom")
            if not filename:
                filename = fname or f"{media_type}_{hash(file_url) % 100000}"
            filename = os.path.basename(filename)

            file_path = media_dir / filename
            file_path.write_bytes(data)
            logger.debug("Downloaded {} to {}", media_type, file_path)
            return str(file_path)

        except Exception as e:
            logger.error("Error downloading media: {}", e)
            return None

    async def send(self, msg: OutboundMessage) -> None:
        """
        通过企业微信发送消息。

        发送流程：
        1. 检查客户端是否已初始化
        2. 获取聊天的存储帧（用于回复）
        3. 生成流式 ID
        4. 使用流式回复发送消息（finish=True 表示最后一条）

        Args:
            msg: 出站消息对象，包含 content 和 chat_id
        """
        if not self._client:
            logger.warning("WeCom client not initialized")
            return

        try:
            content = msg.content.strip()
            if not content:
                return

            # 获取该聊天的存储帧
            frame = self._chat_frames.get(msg.chat_id)
            if not frame:
                logger.warning("No frame found for chat {}, cannot reply", msg.chat_id)
                return

            # 使用流式回复提升用户体验
            stream_id = self._generate_req_id("stream")

            # 作为流式消息发送，finish=True 表示结束
            await self._client.reply_stream(
                frame,
                stream_id,
                content,
                finish=True,
            )

            logger.debug("WeCom message sent to {}", msg.chat_id)

        except Exception as e:
            logger.error("Error sending WeCom message: {}", e)

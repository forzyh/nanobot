# =============================================================================
# nanobot 钉钉渠道
# 文件路径：nanobot/channels/dingtalk.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 DingTalkChannel 类，让 nanobot 能够通过钉钉与用户交互。
#
# 什么是 DingTalkChannel？
# --------------------
# DingTalkChannel 是 nanobot 与钉钉平台的"适配器"：
# 1. 通过钉钉 Stream SDK 建立长连接接收消息事件
# 2. 使用钉钉开放平台 API 发送消息
# 3. 支持文本、图片等多种消息类型
#
# 什么是 Stream Mode？
# ------------------
# Stream Mode 是钉钉推送协议的一种模式：
# - 建立长连接接收实时事件推送
# - 无需配置公网 IP 或回调地址
# - 自动处理重连和心跳
#
# 架构设计：
# ---------
#   钉钉 ←→ Stream SDK ←→ CallbackHandler ←→ DingTalkChannel ←→ MessageBus
#   平台     长连接推送      回调处理器        渠道适配         核心处理
#
# 使用示例：
# --------
# # 配置钉钉
# {
#   "channels": {
#     "dingtalk": {
#       "enabled": true,
#       "client_id": "xxx",
#       "client_secret": "xxx",
#       "allow_from": ["*"]
#     }
#   }
# }
# =============================================================================

"""DingTalk/DingDing channel implementation using Stream Mode."""
# 使用 Stream Mode 实现钉钉渠道

import asyncio
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import DingTalkConfig

# SDK 导入检查
# 如果 dingtalk_stream 未安装，使用占位类型避免导入错误
try:
    from dingtalk_stream import (
        AckMessage,
        CallbackHandler,
        CallbackMessage,
        Credential,
        DingTalkStreamClient,
    )
    from dingtalk_stream.chatbot import ChatbotMessage

    DINGTALK_AVAILABLE = True
except ImportError:
    DINGTALK_AVAILABLE = False
    # 回退类型，使类定义不会在模块级别崩溃
    CallbackHandler = object  # type: ignore[assignment,misc]
    CallbackMessage = None  # type: ignore[assignment,misc]
    AckMessage = None  # type: ignore[assignment,misc]
    ChatbotMessage = None  # type: ignore[assignment,misc]


class NanobotDingTalkHandler(CallbackHandler):
    """
    钉钉 Stream SDK 回调处理器。

    功能：
    ----
    1. 解析收到的消息
    2. 提取文本内容
    3. 转发到 Nanobot 渠道处理

    回调流程：
    --------
    钉钉推送消息 → process() → 解析消息 → _on_message() → 消息总线
    """

    def __init__(self, channel: "DingTalkChannel"):
        """
        初始化回调处理器。

        Args:
            channel: DingTalkChannel 实例，用于转发消息
        """
        super().__init__()
        self.channel = channel

    async def process(self, message: CallbackMessage):
        """
        处理收到的 Stream 消息。

        处理流程：
        1. 使用 SDK 的 ChatbotMessage.from_dict() 解析消息
        2. 提取文本内容（支持多种格式回退）
        3. 验证内容非空
        4. 提取发送者信息
        5. 创建异步任务转发到渠道（非阻塞）
        6. 返回 ACK 确认

        Args:
            message: SDK 的回调消息对象
        Returns:
            tuple: (状态码，响应消息)
        """
        try:
            # 使用 SDK 的 ChatbotMessage 解析，确保健壮性
            chatbot_msg = ChatbotMessage.from_dict(message.data)

            # 提取文本内容，多种格式回退
            content = ""
            if chatbot_msg.text:
                content = chatbot_msg.text.content.strip()
            elif chatbot_msg.extensions.get("content", {}).get("recognition"):
                # 语音消息的转录内容
                content = chatbot_msg.extensions["content"]["recognition"].strip()
            if not content:
                # 最后的回退：从原始数据获取
                content = message.data.get("text", {}).get("content", "").strip()

            if not content:
                logger.warning(
                    "Received empty or unsupported message type: {}",
                    chatbot_msg.message_type,
                )
                return AckMessage.STATUS_OK, "OK"

            sender_id = chatbot_msg.sender_staff_id or chatbot_msg.sender_id
            sender_name = chatbot_msg.sender_nick or "Unknown"

            conversation_type = message.data.get("conversationType")
            conversation_id = (
                message.data.get("conversationId")
                or message.data.get("openConversationId")
            )

            logger.info("Received DingTalk message from {} ({}): {}", sender_name, sender_id, content)

            # 转发到 Nanobot（非阻塞异步任务）
            # 存储任务引用防止在完成任务前被 GC 回收
            task = asyncio.create_task(
                self.channel._on_message(
                    content,
                    sender_id,
                    sender_name,
                    conversation_type,
                    conversation_id,
                )
            )
            self.channel._background_tasks.add(task)
            task.add_done_callback(self.channel._background_tasks.discard)

            return AckMessage.STATUS_OK, "OK"

        except Exception as e:
            logger.error("Error processing DingTalk message: {}", e)
            # 返回 OK 避免钉钉服务器重试
            return AckMessage.STATUS_OK, "Error"


class DingTalkChannel(BaseChannel):
    """
    钉钉渠道实现，使用 Stream Mode。

    功能特点：
    --------
    1. 使用 WebSocket 接收事件（通过 dingtalk-stream SDK）
    2. 使用 HTTP API 发送消息（SDK 主要用于接收）
    3. 支持私聊（1:1）和群聊
    4. 群聊 chat_id 带 "group:" 前缀用于路由回复

    依赖：
    ----
    - dingtalk-stream: 钉钉 Stream SDK
    - Client ID 和 Client Secret（从钉钉开放平台获取）
    """

    name = "dingtalk"
    display_name = "DingTalk"
    # 媒体文件扩展名分类
    _IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}  # 图片
    _AUDIO_EXTS = {".amr", ".mp3", ".wav", ".ogg", ".m4a", ".aac"}     # 音频
    _VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}            # 视频

    def __init__(self, config: DingTalkConfig, bus: MessageBus):
        """
        初始化钉钉渠道。

        Args:
            config: 钉钉配置对象（包含 client_id 和 client_secret）
            bus: 消息总线实例，用于消息发布和订阅

        初始化内容：
        - 调用父类构造函数
        - 保存配置引用
        - 初始化 HTTP 客户端（用于发送消息）
        - 初始化 Stream 客户端（用于接收消息）
        - 初始化 Access Token 管理变量
        - 创建后台任务集合（防止被 GC 回收）
        """
        super().__init__(config, bus)
        self.config: DingTalkConfig = config
        self._client: Any = None
        self._http: httpx.AsyncClient | None = None

        # Access Token management for sending messages
        self._access_token: str | None = None
        self._token_expiry: float = 0

        # Hold references to background tasks to prevent GC
        self._background_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """
        启动钉钉机器人，使用 Stream Mode 长连接。

        启动流程：
        1. 检查 SDK 是否已安装（dingtalk-stream）
        2. 验证配置（client_id 和 client_secret）
        3. 创建 HTTP 异步客户端（用于发送消息）
        4. 创建 Credential 凭证对象
        5. 创建 DingTalkStreamClient 实例
        6. 注册回调处理器（用于处理机器人消息）
        7. 启动 Stream 连接并进入长轮询循环
        8. 处理断线重连（5 秒后自动重连）

        异常处理：
        - SDK 未安装：记录错误日志并退出
        - 配置缺失：记录错误日志并退出
        - 连接异常：记录警告日志并尝试重连
        """
        try:
            if not DINGTALK_AVAILABLE:
                logger.error(
                    "DingTalk Stream SDK not installed. Run: pip install dingtalk-stream"
                )
                return

            if not self.config.client_id or not self.config.client_secret:
                logger.error("DingTalk client_id and client_secret not configured")
                return

            self._running = True
            self._http = httpx.AsyncClient()

            logger.info(
                "Initializing DingTalk Stream Client with Client ID: {}...",
                self.config.client_id,
            )
            credential = Credential(self.config.client_id, self.config.client_secret)
            self._client = DingTalkStreamClient(credential)

            # Register standard handler
            handler = NanobotDingTalkHandler(self)
            self._client.register_callback_handler(ChatbotMessage.TOPIC, handler)

            logger.info("DingTalk bot started with Stream Mode")

            # Reconnect loop: restart stream if SDK exits or crashes
            while self._running:
                try:
                    await self._client.start()
                except Exception as e:
                    logger.warning("DingTalk stream error: {}", e)
                if self._running:
                    logger.info("Reconnecting DingTalk stream in 5 seconds...")
                    await asyncio.sleep(5)

        except Exception as e:
            logger.exception("Failed to start DingTalk channel: {}", e)

    async def stop(self) -> None:
        """
        停止钉钉机器人，关闭所有连接和任务。

        停止流程：
        1. 设置运行标志为 False，停止主循环
        2. 关闭 HTTP 异步客户端，释放连接池
        3. 取消所有后台任务（消息处理任务）
        4. 清空后台任务集合

        注意：
        - Stream 客户端会在主循环退出后自动关闭
        - HTTP 客户端需要显式关闭以释放资源
        - 后台任务使用 discard 回调自动清理
        """
        self._running = False
        # Close the shared HTTP client
        if self._http:
            await self._http.aclose()
            self._http = None
        # Cancel outstanding background tasks
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()

    async def _get_access_token(self) -> str | None:
        """
        获取或刷新钉钉 Access Token。

        钉钉 API 调用需要 Access Token 认证，此方法：
        1. 检查缓存的 Token 是否有效（未过期）
        2. 如果过期或不存在，调用钉钉 API 获取新 Token
        3. 缓存新 Token 并记录过期时间（提前 60 秒过期以防边界情况）

        请求详情：
        - URL: https://api.dingtalk.com/v1.0/oauth2/accessToken
        - 方法：POST
        - 参数：appKey（client_id）、appSecret（client_secret）
        - 响应：accessToken、expireIn（通常 7200 秒）

        Returns:
            str | None: 有效的 Access Token，获取失败返回 None

        异常处理：
        - HTTP 请求失败：记录错误日志并返回 None
        - 解析失败：记录错误日志并返回 None
        """
        if self._access_token and time.time() < self._token_expiry:
            return self._access_token

        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        data = {
            "appKey": self.config.client_id,
            "appSecret": self.config.client_secret,
        }

        if not self._http:
            logger.warning("DingTalk HTTP client not initialized, cannot refresh token")
            return None

        try:
            resp = await self._http.post(url, json=data)
            resp.raise_for_status()
            res_data = resp.json()
            self._access_token = res_data.get("accessToken")
            # Expire 60s early to be safe
            self._token_expiry = time.time() + int(res_data.get("expireIn", 7200)) - 60
            return self._access_token
        except Exception as e:
            logger.error("Failed to get DingTalk access token: {}", e)
            return None

    @staticmethod
    def _is_http_url(value: str) -> bool:
        """
        判断字符串是否为 HTTP/HTTPS URL。

        Args:
            value: 待检查的字符串

        Returns:
            bool: 如果是 http:// 或 https:// 开头的 URL 返回 True

        用途：
        - 区分媒体引用是远程 URL 还是本地文件路径
        - 决定使用网络下载还是本地文件读取
        """
        return urlparse(value).scheme in ("http", "https")

    def _guess_upload_type(self, media_ref: str) -> str:
        """
        根据媒体引用的文件扩展名猜测上传类型。

        钉钉媒体上传需要指定类型（image、voice、video、file），
        此方法通过文件扩展名自动判断合适的类型。

        Args:
            media_ref: 媒体引用（URL 或本地文件路径）

        Returns:
            str: 上传类型（"image"、"voice"、"video" 或 "file"）

        类型映射：
        - 图片：.jpg, .jpeg, .png, .gif, .bmp, .webp
        - 音频：.amr, .mp3, .wav, .ogg, .m4a, .aac
        - 视频：.mp4, .mov, .avi, .mkv, .webm
        - 其他：file
        """
        ext = Path(urlparse(media_ref).path).suffix.lower()
        if ext in self._IMAGE_EXTS: return "image"
        if ext in self._AUDIO_EXTS: return "voice"
        if ext in self._VIDEO_EXTS: return "video"
        return "file"

    def _guess_filename(self, media_ref: str, upload_type: str) -> str:
        """
        根据媒体引用和类型猜测文件名。

        钉钉媒体上传需要提供文件名，此方法：
        1. 从 URL 或路径中提取 basename
        2. 如果无法提取，根据类型返回默认文件名

        Args:
            media_ref: 媒体引用（URL 或本地文件路径）
            upload_type: 上传类型（"image"、"voice"、"video" 或 "file"）

        Returns:
            str: 文件名（带扩展名）

        默认文件名：
        - image: image.jpg
        - voice: audio.amr
        - video: video.mp4
        - file: file.bin
        """
        name = os.path.basename(urlparse(media_ref).path)
        return name or {"image": "image.jpg", "voice": "audio.amr", "video": "video.mp4"}.get(upload_type, "file.bin")

    async def _read_media_bytes(
        self,
        media_ref: str,
    ) -> tuple[bytes | None, str | None, str | None]:
        """
        读取媒体文件内容（支持远程 URL 和本地文件）。

        此方法用于获取待上传媒体的二进制数据，支持两种来源：
        1. 远程 HTTP/HTTPS URL：使用 httpx 下载
        2. 本地文件路径：直接读取文件内容

        Args:
            media_ref: 媒体引用，可以是：
                - HTTP/HTTPS URL（如 https://example.com/image.jpg）
                - 本地文件路径（如 /path/to/image.jpg）
                - file://协议路径（如 file:///path/to/image.jpg）

        Returns:
            tuple[bytes | None, str | None, str | None]: 三元组包含：
                - 媒体二进制数据（失败返回 None）
                - 文件名（失败返回 None）
                - MIME 类型（失败返回 None）

        异常处理：
        - 网络请求失败：记录警告日志并返回 None
        - 文件不存在：记录警告日志并返回 None
        - 读取错误：记录错误日志并返回 None
        """
        if not media_ref:
            return None, None, None

        if self._is_http_url(media_ref):
            if not self._http:
                return None, None, None
            try:
                resp = await self._http.get(media_ref, follow_redirects=True)
                if resp.status_code >= 400:
                    logger.warning(
                        "DingTalk media download failed status={} ref={}",
                        resp.status_code,
                        media_ref,
                    )
                    return None, None, None
                content_type = (resp.headers.get("content-type") or "").split(";")[0].strip()
                filename = self._guess_filename(media_ref, self._guess_upload_type(media_ref))
                return resp.content, filename, content_type or None
            except Exception as e:
                logger.error("DingTalk media download error ref={} err={}", media_ref, e)
                return None, None, None

        try:
            if media_ref.startswith("file://"):
                parsed = urlparse(media_ref)
                local_path = Path(unquote(parsed.path))
            else:
                local_path = Path(os.path.expanduser(media_ref))
            if not local_path.is_file():
                logger.warning("DingTalk media file not found: {}", local_path)
                return None, None, None
            data = await asyncio.to_thread(local_path.read_bytes)
            content_type = mimetypes.guess_type(local_path.name)[0]
            return data, local_path.name, content_type
        except Exception as e:
            logger.error("DingTalk media read error ref={} err={}", media_ref, e)
            return None, None, None

    async def _upload_media(
        self,
        token: str,
        data: bytes,
        media_type: str,
        filename: str,
        content_type: str | None,
    ) -> str | None:
        """
        上传媒体文件到钉钉服务器。

        钉钉媒体上传 API 会将文件临时存储在服务器，返回 media_id 用于后续消息发送。
        媒体文件在钉钉服务器存储一定时间（通常几天），过期后自动删除。

        Args:
            token: Access Token（用于 API 认证）
            data: 媒体文件二进制数据
            media_type: 媒体类型（"image"、"voice"、"video"、"file"）
            filename: 文件名（带扩展名）
            content_type: MIME 类型（如 image/jpeg，可为 None）

        Returns:
            str | None: 上传成功返回 media_id，失败返回 None

        API 详情：
        - URL: https://oapi.dingtalk.com/media/upload
        - 参数：access_token、type（媒体类型）
        - 方法：POST（multipart/form-data）

        响应处理：
        - 检查 HTTP 状态码（>=400 表示失败）
        - 检查 errcode（非 0 表示失败）
        - 提取 media_id（兼容多种字段名）

        异常处理：
        - 网络错误：记录错误日志并返回 None
        - 解析错误：记录错误日志并返回 None
        """
        if not self._http:
            return None
        url = f"https://oapi.dingtalk.com/media/upload?access_token={token}&type={media_type}"
        mime = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        files = {"media": (filename, data, mime)}

        try:
            resp = await self._http.post(url, files=files)
            text = resp.text
            result = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            if resp.status_code >= 400:
                logger.error("DingTalk media upload failed status={} type={} body={}", resp.status_code, media_type, text[:500])
                return None
            errcode = result.get("errcode", 0)
            if errcode != 0:
                logger.error("DingTalk media upload api error type={} errcode={} body={}", media_type, errcode, text[:500])
                return None
            sub = result.get("result") or {}
            media_id = result.get("media_id") or result.get("mediaId") or sub.get("media_id") or sub.get("mediaId")
            if not media_id:
                logger.error("DingTalk media upload missing media_id body={}", text[:500])
                return None
            return str(media_id)
        except Exception as e:
            logger.error("DingTalk media upload error type={} err={}", media_type, e)
            return None

    async def _send_batch_message(
        self,
        token: str,
        chat_id: str,
        msg_key: str,
        msg_param: dict[str, Any],
    ) -> bool:
        """
        发送钉钉批量消息（群聊或私聊）。

        钉钉机器人使用统一的批量消息 API 发送消息，根据 chat_id 前缀区分：
        - 群聊：chat_id 以 "group:" 开头，使用 groupMessages/send API
        - 私聊：chat_id 为用户 ID，使用 robot/oToMessages/batchSend API

        Args:
            token: Access Token（用于 API 认证）
            chat_id: 聊天 ID
                - 群聊：group:{conversationId}
                - 私聊：用户 ID
            msg_key: 消息类型关键词
                - sampleMarkdown: Markdown 文本消息
                - sampleImageMsg: 图片消息
                - sampleFile: 文件消息
            msg_param: 消息参数（JSON 对象，不同 msg_key 对应不同结构）

        Returns:
            bool: 发送成功返回 True，失败返回 False

        API 详情：
        - 群聊 URL: https://api.dingtalk.com/v1.0/robot/groupMessages/send
        - 私聊 URL: https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend
        - Header: x-acs-dingtalk-access-token

        异常处理：
        - HTTP 错误：记录错误日志并返回 False
        - API 错误（errcode != 0）：记录错误日志并返回 False
        - 其他异常：记录错误日志并返回 False
        """
        if not self._http:
            logger.warning("DingTalk HTTP client not initialized, cannot send")
            return False

        headers = {"x-acs-dingtalk-access-token": token}
        if chat_id.startswith("group:"):
            # Group chat
            url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
            payload = {
                "robotCode": self.config.client_id,
                "openConversationId": chat_id[6:],  # Remove "group:" prefix,
                "msgKey": msg_key,
                "msgParam": json.dumps(msg_param, ensure_ascii=False),
            }
        else:
            # Private chat
            url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
            payload = {
                "robotCode": self.config.client_id,
                "userIds": [chat_id],
                "msgKey": msg_key,
                "msgParam": json.dumps(msg_param, ensure_ascii=False),
            }

        try:
            resp = await self._http.post(url, json=payload, headers=headers)
            body = resp.text
            if resp.status_code != 200:
                logger.error("DingTalk send failed msgKey={} status={} body={}", msg_key, resp.status_code, body[:500])
                return False
            try: result = resp.json()
            except Exception: result = {}
            errcode = result.get("errcode")
            if errcode not in (None, 0):
                logger.error("DingTalk send api error msgKey={} errcode={} body={}", msg_key, errcode, body[:500])
                return False
            logger.debug("DingTalk message sent to {} with msgKey={}", chat_id, msg_key)
            return True
        except Exception as e:
            logger.error("Error sending DingTalk message msgKey={} err={}", msg_key, e)
            return False

    async def _send_markdown_text(self, token: str, chat_id: str, content: str) -> bool:
        return await self._send_batch_message(
            token,
            chat_id,
            "sampleMarkdown",
            {"text": content, "title": "Nanobot Reply"},
        )

    async def _send_media_ref(self, token: str, chat_id: str, media_ref: str) -> bool:
        media_ref = (media_ref or "").strip()
        if not media_ref:
            return True

        upload_type = self._guess_upload_type(media_ref)
        if upload_type == "image" and self._is_http_url(media_ref):
            ok = await self._send_batch_message(
                token,
                chat_id,
                "sampleImageMsg",
                {"photoURL": media_ref},
            )
            if ok:
                return True
            logger.warning("DingTalk image url send failed, trying upload fallback: {}", media_ref)

        data, filename, content_type = await self._read_media_bytes(media_ref)
        if not data:
            logger.error("DingTalk media read failed: {}", media_ref)
            return False

        filename = filename or self._guess_filename(media_ref, upload_type)
        file_type = Path(filename).suffix.lower().lstrip(".")
        if not file_type:
            guessed = mimetypes.guess_extension(content_type or "")
            file_type = (guessed or ".bin").lstrip(".")
        if file_type == "jpeg":
            file_type = "jpg"

        media_id = await self._upload_media(
            token=token,
            data=data,
            media_type=upload_type,
            filename=filename,
            content_type=content_type,
        )
        if not media_id:
            return False

        if upload_type == "image":
            # Verified in production: sampleImageMsg accepts media_id in photoURL.
            ok = await self._send_batch_message(
                token,
                chat_id,
                "sampleImageMsg",
                {"photoURL": media_id},
            )
            if ok:
                return True
            logger.warning("DingTalk image media_id send failed, falling back to file: {}", media_ref)

        return await self._send_batch_message(
            token,
            chat_id,
            "sampleFile",
            {"mediaId": media_id, "fileName": filename, "fileType": file_type},
        )

    async def send(self, msg: OutboundMessage) -> None:
        """
        通过钉钉发送消息（支持文本和媒体）。

        此方法处理出站消息的发送，支持：
        1. Markdown 文本消息（使用 sampleMarkdown 类型）
        2. 媒体消息（图片、音频、视频、文件）
        3. 混合消息（文本 + 多个媒体附件）

        发送流程：
        1. 获取 Access Token（用于 API 认证）
        2. 如果消息包含文本，发送 Markdown 消息
        3. 遍历媒体列表，逐个发送媒体文件
        4. 媒体发送失败时，发送可见的失败提示（便于用户知晓）

        Args:
            msg: 出站消息对象，包含：
                - chat_id: 聊天 ID（群聊带 group: 前缀）
                - content: Markdown 格式文本内容
                - media: 媒体文件路径列表

        媒体处理：
        - 媒体发送失败会记录错误日志
        - 失败后会发送可见的 fallback 消息告知用户
        - 文件名从媒体引用中提取
        """
        token = await self._get_access_token()
        if not token:
            return

        if msg.content and msg.content.strip():
            await self._send_markdown_text(token, msg.chat_id, msg.content.strip())

        for media_ref in msg.media or []:
            ok = await self._send_media_ref(token, msg.chat_id, media_ref)
            if ok:
                continue
            logger.error("DingTalk media send failed for {}", media_ref)
            # Send visible fallback so failures are observable by the user.
            filename = self._guess_filename(media_ref, self._guess_upload_type(media_ref))
            await self._send_markdown_text(
                token,
                msg.chat_id,
                f"[Attachment send failed: {filename}]",
            )

    async def _on_message(
        self,
        content: str,
        sender_id: str,
        sender_name: str,
        conversation_type: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        """
        处理收到的钉钉消息（由 NanobotDingTalkHandler 调用）。

        此方法是钉钉消息进入 Nanobot 核心处理的入口点，负责：
        1. 记录入站消息日志
        2. 判断聊天类型（群聊或私聊）
        3. 构建 chat_id（群聊添加 group: 前缀用于路由）
        4. 调用基类的 _handle_message() 进行统一处理
        5. 发布消息到消息总线

        Args:
            content: 消息文本内容
            sender_id: 发送者 ID（钉钉用户 ID）
            sender_name: 发送者昵称
            conversation_type: 会话类型
                - "1": 私聊
                - "2": 群聊
            conversation_id: 会话 ID（群聊时使用）

        聊天 ID 规则：
        - 私聊：chat_id = sender_id（用户 ID）
        - 群聊：chat_id = "group:{conversation_id}"（添加前缀区分）

        元数据包含：
        - sender_name: 发送者昵称
        - platform: 平台标识（"dingtalk"）
        - conversation_type: 原始会话类型

        异常处理：
        - 发布失败：记录错误日志，不抛出异常
        """
        try:
            logger.info("DingTalk inbound: {} from {}", content, sender_name)
            is_group = conversation_type == "2" and conversation_id
            chat_id = f"group:{conversation_id}" if is_group else sender_id
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=str(content),
                metadata={
                    "sender_name": sender_name,
                    "platform": "dingtalk",
                    "conversation_type": conversation_type,
                },
            )
        except Exception as e:
            logger.error("Error publishing DingTalk message: {}", e)

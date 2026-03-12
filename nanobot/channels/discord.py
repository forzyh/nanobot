# =============================================================================
# nanobot Discord 渠道
# 文件路径：nanobot/channels/discord.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 DiscordChannel 类，让 nanobot 能够通过 Discord 与用户交互。
#
# 什么是 DiscordChannel？
# --------------------
# DiscordChannel 是 nanobot 与 Discord 平台的"适配器"：
# 1. 通过 Discord Gateway WebSocket 连接接收消息
# 2. 通过 Discord REST API 发送消息和附件
# 3. 支持文本、附件（图片、文档等）消息类型
# 4. 支持群聊提及检测和回复
#
# 核心技术：
# ---------
# - Discord Gateway API: WebSocket 长连接接收实时事件
# - Discord REST API: HTTP 请求发送消息和文件
# - Heartbeat: 定期心跳保持连接活跃
# - Intents: 配置订阅的事件类型
#
# 架构设计：
# ---------
#   Discord ←→ Gateway WebSocket ←→ _gateway_loop() ←→ MessageBus
#      平台         实时事件            事件处理          核心处理
#          ↑
#   REST API (发送消息/文件)
#
# 使用示例：
# --------
# # 配置 Discord
# {
#   "channels": {
#     "discord": {
#       "enabled": true,
#       "token": "BOT_TOKEN",
#       "intents": 32767,
#       "group_policy": "mention",
#       "allow_from": ["*"]
#     }
#   }
# }
# =============================================================================

"""Discord channel implementation using Discord Gateway websocket."""
# 使用 Discord Gateway WebSocket 实现 Discord 渠道

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import websockets
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import DiscordConfig
from nanobot.utils.helpers import split_message

# Discord API 常量
DISCORD_API_BASE = "https://discord.com/api/v10"  # API 基础 URL
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 最大附件大小（20MB）
MAX_MESSAGE_LEN = 2000  # Discord 消息字符上限


class DiscordChannel(BaseChannel):
    """
    使用 Gateway WebSocket 的 Discord 渠道实现。

    核心特性：
    --------
    1. Gateway WebSocket：长连接接收实时消息事件
    2. REST API：发送消息和文件附件
    3. 心跳机制：定期发送心跳保持连接
    4. 自动重连：连接断开后自动重连
    5. 群聊策略：支持 open/mention 两种模式
    6. 附件下载：自动下载消息附件到本地

    属性说明：
    --------
    name: str
        渠道名称："discord"

    display_name: str
        显示名称："Discord"

    _ws: websockets.WebSocketClientProtocol | None
        Gateway WebSocket 连接

    _seq: int | None
        事件序列号（用于心跳和重连）

    _heartbeat_task: asyncio.Task | None
        心跳任务

    _typing_tasks: dict[str, asyncio.Task]
        打字指示任务字典

    _http: httpx.AsyncClient | None
        HTTP 客户端（用于 REST API 和下载附件）

    _bot_user_id: str | None
        机器人用户 ID（用于提及检测）

    使用示例：
    --------
    >>> config = DiscordConfig(token="BOT_TOKEN", intents=32767)
    >>> channel = DiscordChannel(config, message_bus)
    >>> await channel.start()  # 启动 Gateway 连接
    """

    name = "discord"
    display_name = "Discord"

    def __init__(self, config: DiscordConfig, bus: MessageBus):
        """
        初始化 Discord 渠道。

        Args:
            config: Discord 配置对象（包含 token、intents、gateway_url 等）
            bus: 消息总线实例
        """
        super().__init__(config, bus)
        self.config: DiscordConfig = config  # Discord 配置
        self._ws: websockets.WebSocketClientProtocol | None = None  # WebSocket 连接
        self._seq: int | None = None  # 事件序列号
        self._heartbeat_task: asyncio.Task | None = None  # 心跳任务
        self._typing_tasks: dict[str, asyncio.Task] = {}  # 打字指示任务
        self._http: httpx.AsyncClient | None = None  # HTTP 客户端
        self._bot_user_id: str | None = None  # 机器人用户 ID

    async def start(self) -> None:
        """
        启动 Discord Gateway 连接。

        启动流程：
        --------
        1. 检查 bot token 是否配置
        2. 创建 HTTP 客户端
        3. 连接到 Gateway WebSocket
        4. 运行 _gateway_loop() 处理事件
        5. 断线自动重连（5 秒间隔）

        注意：
        ----
        这是一个长期运行的方法，会持续监听直到 stop() 被调用。
        """
        if not self.config.token:
            logger.error("Discord bot token not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)

        while self._running:
            try:
                logger.info("Connecting to Discord gateway...")
                async with websockets.connect(self.config.gateway_url) as ws:
                    self._ws = ws
                    await self._gateway_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Discord gateway error: {}", e)
                if self._running:
                    logger.info("Reconnecting to Discord gateway in 5 seconds...")
                    await asyncio.sleep(5)

    async def stop(self) -> None:
        """
        停止 Discord 渠道。

        停止流程：
        --------
        1. 设置运行标志为 False
        2. 取消心跳任务
        3. 取消所有打字指示任务
        4. 关闭 WebSocket 连接
        5. 关闭 HTTP 客户端
        """
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        for task in self._typing_tasks.values():
            task.cancel()
        self._typing_tasks.clear()
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._http:
            await self._http.aclose()
            self._http = None

    async def send(self, msg: OutboundMessage) -> None:
        """
        通过 Discord REST API 发送消息（包括文件附件）。

        发送流程：
        --------
        1. 检查 HTTP 客户端是否初始化
        2. 构建 API URL 和请求头
        3. 发送文件附件（如果有）
        4. 发送文本内容（分片处理超长消息）
        5. 处理回复引用

        附件处理：
        --------
        - 最大附件大小：20MB
        - 使用 multipart/form-data 上传
        - 失败时记录错误并继续发送其他内容

        消息分片：
        --------
        Discord 消息限制 2000 字符，超长消息会被 split_message() 分割。

        Args:
            msg: 出站消息对象（包含 chat_id、content、media 等）
        """
        if not self._http:
            logger.warning("Discord HTTP client not initialized")
            return

        url = f"{DISCORD_API_BASE}/channels/{msg.chat_id}/messages"
        headers = {"Authorization": f"Bot {self.config.token}"}

        try:
            sent_media = False
            failed_media: list[str] = []

            # 先发送文件附件
            for media_path in msg.media or []:
                if await self._send_file(url, headers, media_path, reply_to=msg.reply_to):
                    sent_media = True
                else:
                    failed_media.append(Path(media_path).name)

            # 发送文本内容
            chunks = split_message(msg.content or "", MAX_MESSAGE_LEN)
            if not chunks and failed_media and not sent_media:
                chunks = split_message(
                    "\n".join(f"[attachment: {name} - send failed]" for name in failed_media),
                    MAX_MESSAGE_LEN,
                )
            if not chunks:
                return

            for i, chunk in enumerate(chunks):
                payload: dict[str, Any] = {"content": chunk}

                # 让第一个成功的附件携带回复信息（如果有）
                if i == 0 and msg.reply_to and not sent_media:
                    payload["message_reference"] = {"message_id": msg.reply_to}
                    payload["allowed_mentions"] = {"replied_user": False}

                if not await self._send_payload(url, headers, payload):
                    break  # 失败时中止剩余分片
        finally:
            await self._stop_typing(msg.chat_id)

    async def _send_payload(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> bool:
        """
        发送 Discord API 负载（遇到限流时重试）。

        Args:
            url: API URL
            headers: 请求头
            payload: 请求负载

        Returns:
            bool: 成功返回 True

        重试机制：
        --------
        - 最多重试 3 次
        - 遇到 429 限流时，等待 retry_after 秒后重试
        - 其他错误等待 1 秒后重试
        """
        for attempt in range(3):
            try:
                response = await self._http.post(url, headers=headers, json=payload)
                if response.status_code == 429:
                    data = response.json()
                    retry_after = float(data.get("retry_after", 1.0))
                    logger.warning("Discord rate limited, retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                return True
            except Exception as e:
                if attempt == 2:
                    logger.error("Error sending Discord message: {}", e)
                else:
                    await asyncio.sleep(1)
        return False

    async def _send_file(
        self,
        url: str,
        headers: dict[str, str],
        file_path: str,
        reply_to: str | None = None,
    ) -> bool:
        """
        通过 multipart/form-data 发送文件附件。

        Args:
            url: API URL
            headers: 请求头
            file_path: 文件路径
            reply_to: 回复的消息 ID（可选）

        Returns:
            bool: 成功返回 True

        文件检查：
        --------
        1. 文件是否存在
        2. 文件大小是否超过 20MB

        重试机制：
        --------
        - 最多重试 3 次
        - 遇到 429 限流时等待 retry_after 秒
        """
        path = Path(file_path)
        if not path.is_file():
            logger.warning("Discord file not found, skipping: {}", file_path)
            return False

        if path.stat().st_size > MAX_ATTACHMENT_BYTES:
            logger.warning("Discord file too large (>20MB), skipping: {}", path.name)
            return False

        payload_json: dict[str, Any] = {}
        if reply_to:
            payload_json["message_reference"] = {"message_id": reply_to}
            payload_json["allowed_mentions"] = {"replied_user": False}

        for attempt in range(3):
            try:
                with open(path, "rb") as f:
                    files = {"files[0]": (path.name, f, "application/octet-stream")}
                    data: dict[str, Any] = {}
                    if payload_json:
                        data["payload_json"] = json.dumps(payload_json)
                    response = await self._http.post(
                        url, headers=headers, files=files, data=data
                    )
                if response.status_code == 429:
                    resp_data = response.json()
                    retry_after = float(resp_data.get("retry_after", 1.0))
                    logger.warning("Discord rate limited, retrying in {}s", retry_after)
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                logger.info("Discord file sent: {}", path.name)
                return True
            except Exception as e:
                if attempt == 2:
                    logger.error("Error sending Discord file {}: {}", path.name, e)
                else:
                    await asyncio.sleep(1)
        return False

    async def _gateway_loop(self) -> None:
        """
        主 gateway 循环：识别、心跳、处理事件。

        这是 Discord 连接的核心循环，负责：
        1. 接收 Gateway 事件
        2. 更新序列号（用于心跳和重连）
        3. 处理操作码（op）和事件类型（t）

        操作码处理：
        ---------
        - op=10 (HELLO): 启动心跳，发送 Identify
        - op=0, t=READY: 准备就绪，捕获机器人 ID
        - op=0, t=MESSAGE_CREATE: 处理新消息
        - op=7 (RECONNECT): 退出循环以重连
        - op=9 (INVALID_SESSION): 无效会话，重连

        注意：
        ----
        这是一个长期运行的循环，直到连接断开或被停止。
        """
        if not self._ws:
            return

        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from Discord gateway: {}", raw[:100])
                continue

            op = data.get("op")
            event_type = data.get("t")
            seq = data.get("s")
            payload = data.get("d")

            if seq is not None:
                self._seq = seq  # 更新序列号

            if op == 10:
                # HELLO: 启动心跳和识别
                interval_ms = payload.get("heartbeat_interval", 45000)
                await self._start_heartbeat(interval_ms / 1000)
                await self._identify()
            elif op == 0 and event_type == "READY":
                logger.info("Discord gateway READY")
                # 捕获机器人用户 ID 用于提及检测
                user_data = payload.get("user") or {}
                self._bot_user_id = user_data.get("id")
                logger.info("Discord bot connected as user {}", self._bot_user_id)
            elif op == 0 and event_type == "MESSAGE_CREATE":
                await self._handle_message_create(payload)
            elif op == 7:
                # RECONNECT: 退出循环以重连
                logger.info("Discord gateway requested reconnect")
                break
            elif op == 9:
                # INVALID_SESSION: 重连
                logger.warning("Discord gateway invalid session")
                break

    async def _identify(self) -> None:
        """
        发送 IDENTIFY 负载。

        Identify 是连接到 Discord Gateway 后的第一步，
        告诉 Discord 机器人使用哪个 token 和 intents。
        """
        if not self._ws:
            return

        identify = {
            "op": 2,  # Identify 操作码
            "d": {
                "token": self.config.token,
                "intents": self.config.intents,
                "properties": {
                    "os": "nanobot",  # 操作系统标识
                    "browser": "nanobot",  # 浏览器标识
                    "device": "nanobot",  # 设备标识
                },
            },
        }
        await self._ws.send(json.dumps(identify))

    async def _start_heartbeat(self, interval_s: float) -> None:
        """
        启动或重启心跳循环。

        Args:
            interval_s: 心跳间隔（秒）

        心跳机制：
        --------
        Discord 要求定期发送心跳以保持连接活跃。
        如果长时间不发送心跳，Gateway 会断开连接。

        心跳负载：
        --------
        {"op": 1, "d": seq}
        - op=1: Heartbeat 操作码
        - d: 最后收到的事件序列号（None 表示新的会话）
        """
        if self._heartbeat_task:
            self._heartbeat_task.cancel()

        async def heartbeat_loop() -> None:
            while self._running and self._ws:
                payload = {"op": 1, "d": self._seq}
                try:
                    await self._ws.send(json.dumps(payload))
                except Exception as e:
                    logger.warning("Discord heartbeat failed: {}", e)
                    break
                await asyncio.sleep(interval_s)

        self._heartbeat_task = asyncio.create_task(heartbeat_loop())

    async def _handle_message_create(self, payload: dict[str, Any]) -> None:
        """
        处理传入的 Discord 消息。

        处理流程：
        --------
        1. 忽略机器人自己的消息（避免循环）
        2. 检查权限（is_allowed）
        3. 检查群聊策略（open/mention）
        4. 下载附件（图片、文档等）
        5. 启动打字指示
        6. 转发到消息总线

        附件处理：
        --------
        - 下载附件到本地媒体目录
        - 超过 20MB 的附件跳过
        - 下载失败时添加错误标记

        Args:
            payload: MESSAGE_CREATE 事件负载
        """
        author = payload.get("author") or {}
        if author.get("bot"):
            return  # 忽略机器人消息

        sender_id = str(author.get("id", ""))
        channel_id = str(payload.get("channel_id", ""))
        content = payload.get("content") or ""
        guild_id = payload.get("guild_id")

        if not sender_id or not channel_id:
            return

        if not self.is_allowed(sender_id):
            return

        # 检查群聊策略（私聊直接响应，群聊根据策略）
        if guild_id is not None:
            if not self._should_respond_in_group(payload, content):
                return

        content_parts = [content] if content else []
        media_paths: list[str] = []
        media_dir = get_media_dir("discord")

        # 下载附件
        for attachment in payload.get("attachments") or []:
            url = attachment.get("url")
            filename = attachment.get("filename") or "attachment"
            size = attachment.get("size") or 0
            if not url or not self._http:
                continue
            if size and size > MAX_ATTACHMENT_BYTES:
                content_parts.append(f"[attachment: {filename} - too large]")
                continue
            try:
                media_dir.mkdir(parents=True, exist_ok=True)
                file_path = media_dir / f"{attachment.get('id', 'file')}_{filename.replace('/', '_')}"
                resp = await self._http.get(url)
                resp.raise_for_status()
                file_path.write_bytes(resp.content)
                media_paths.append(str(file_path))
                content_parts.append(f"[attachment: {file_path}]")
            except Exception as e:
                logger.warning("Failed to download Discord attachment: {}", e)
                content_parts.append(f"[attachment: {filename} - download failed]")

        # 回复消息 ID
        reply_to = (payload.get("referenced_message") or {}).get("id")

        # 启动打字指示
        await self._start_typing(channel_id)

        # 转发到消息总线
        await self._handle_message(
            sender_id=sender_id,
            chat_id=channel_id,
            content="\n".join(p for p in content_parts if p) or "[empty message]",
            media=media_paths,
            metadata={
                "message_id": str(payload.get("id", "")),
                "guild_id": guild_id,
                "reply_to": reply_to,
            },
        )

    def _should_respond_in_group(self, payload: dict[str, Any], content: str) -> bool:
        """
        根据策略检查是否应该在群聊中响应。

        策略说明：
        --------
        - open: 总是响应
        - mention: 仅当机器人被提及时响应

        提及检测：
        --------
        1. 检查 mentions 数组
        2. 检查内容中的提及格式 <@USER_ID> 或 <@!USER_ID>

        Args:
            payload: MESSAGE_CREATE 事件负载
            content: 消息内容

        Returns:
            bool: True 表示应该响应
        """
        if self.config.group_policy == "open":
            return True

        if self.config.group_policy == "mention":
            # 检查消息中是否提及了机器人
            if self._bot_user_id:
                # 检查 mentions 数组
                mentions = payload.get("mentions") or []
                for mention in mentions:
                    if str(mention.get("id")) == self._bot_user_id:
                        return True
                # 检查内容中的提及格式
                if f"<@{self._bot_user_id}>" in content or f"<@!{self._bot_user_id}>" in content:
                    return True
            logger.debug("Discord message in {} ignored (bot not mentioned)", payload.get("channel_id"))
            return False

        return True

    async def _start_typing(self, channel_id: str) -> None:
        """
        启动频道的周期性打字指示。

        Args:
            channel_id: 频道 ID

        打字指示：
        --------
        Discord 通过 POST /channels/{id}/typing 端点发送打字状态。
        需要定期发送以保持打字状态显示。
        """
        await self._stop_typing(channel_id)

        async def typing_loop() -> None:
            url = f"{DISCORD_API_BASE}/channels/{channel_id}/typing"
            headers = {"Authorization": f"Bot {self.config.token}"}
            while self._running:
                try:
                    await self._http.post(url, headers=headers)
                except asyncio.CancelledError:
                    return
                except Exception as e:
                    logger.debug("Discord typing indicator failed for {}: {}", channel_id, e)
                    return
                await asyncio.sleep(8)  # 每 8 秒发送一次

        self._typing_tasks[channel_id] = asyncio.create_task(typing_loop())

    async def _stop_typing(self, channel_id: str) -> None:
        """
        停止频道的打字指示。

        Args:
            channel_id: 频道 ID
        """
        task = self._typing_tasks.pop(channel_id, None)
        if task:
            task.cancel()

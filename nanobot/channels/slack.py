# =============================================================================
# nanobot Slack 渠道
# 文件路径：nanobot/channels/slack.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 SlackChannel 类，让 nanobot 能够通过 Slack 与用户交互。
#
# 什么是 SlackChannel？
# --------------------
# SlackChannel 是 nanobot 与 Slack 平台的"适配器"：
# 1. 使用 Socket Mode 连接 Slack（无需公开回调 URL）
# 2. 支持单聊（DM）、群聊和频道消息
# 3. 支持@提及机器人触发响应
# 4. 支持线程回复和文件上传
#
# 为什么需要 Slack 渠道？
# ----------------------
# 1. 企业用户广泛：Slack 是企业团队协作的主要工具
# 2. 集成生态丰富：可与众多企业服务集成
# 3. 机器人生态成熟：Slack Apps 市场庞大
# 4. 正式沟通：适合工作场景的 AI 助手
#
# 工作原理：
# ---------
# 入站（接收消息）：
# 1. 通过 Socket Mode WebSocket 连接 Slack
# 2. 监听 events_api 事件（message、app_mention）
# 3. 过滤机器人自己的消息和系统消息
# 4. 处理@提及逻辑（频道中需要@机器人）
# 5. 添加:eyes: 表情反应（可选）
# 6. 将消息转换为 InboundMessage 发布到消息总线
#
# 出站（发送消息）：
# 1. 从消息总线获取 OutboundMessage
# 2. 将 Markdown 转换为 Slack mrkdwn 格式
# 3. 调用 chat_postMessage API 发送消息
# 4. 支持线程回复（thread_ts）
# 5. 支持文件上传（files_upload_v2）
#
# 配置示例：
# --------
# {
#   "channels": {
#     "slack": {
#       "enabled": true,
#       "mode": "socket",
#       "botToken": "xoxb-your-bot-token",
#       "appToken": "xapp-your-app-token",
#       "replyInThread": true,
#       "reactEmoji": "eyes",
#       "dm": {
#         "enabled": true,
#         "policy": "open"
#       },
#       "groupPolicy": "mention"
#     }
#   }
# }
#
# Slack 应用权限要求：
# -----------------
# - app_mentions:read - 读取@提及
# - channels:history - 读取频道历史
# - chat:write - 发送消息
# - files:write - 上传文件
# - reactions:write - 添加表情反应
#
# 注意事项：
# --------
# 1. 需要在 Slack API 官网创建应用
# 2. Socket Mode 需要 App-Level Token
# 3. 机器人需要被邀请到频道才能接收消息
# 4. 频道消息需要@机器人才能触发响应（取决于 groupPolicy 配置）
# =============================================================================

"""Slack channel implementation using Socket Mode."""
# Slack 渠道：使用 Socket Mode 实现 Slack 机器人功能

import asyncio
import re
from typing import Any

from loguru import logger
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.websockets import SocketModeClient
from slack_sdk.web.async_client import AsyncWebClient
from slackify_markdown import slackify_markdown

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import SlackConfig


class SlackChannel(BaseChannel):
    """
    使用 Socket Mode 的 Slack 渠道。

    Socket Mode 优势：
    - 无需公开回调 URL
    - 通过 WebSocket 直接接收事件
    - 适合内网部署环境

    支持的功能：
    - 单聊（DM）消息
    - 频道消息（需要@机器人）
    - 线程回复
    - 文件上传
    - Markdown 转 mrkdwn
    - 表情反应
    """

    name = "slack"
    display_name = "Slack"

    def __init__(self, config: SlackConfig, bus: MessageBus):
        """
        初始化 Slack 渠道。

        Args:
            config: Slack 配置对象（包含 bot_token 和 app_token）
            bus: 消息总线实例
        """
        super().__init__(config, bus)
        self.config: SlackConfig = config
        self._web_client: AsyncWebClient | None = None
        self._socket_client: SocketModeClient | None = None
        self._bot_user_id: str | None = None

    async def start(self) -> None:
        """
        启动 Slack Socket Mode 客户端。

        验证配置后：
        1. 创建 AsyncWebClient（用于发送消息）
        2. 创建 SocketModeClient（用于接收事件）
        3. 调用 auth.test 获取机器人用户 ID（用于提及处理）
        4. 启动 Socket Mode 连接
        """
        if not self.config.bot_token or not self.config.app_token:
            logger.error("Slack bot/app token not configured")
            return
        if self.config.mode != "socket":
            logger.error("Unsupported Slack mode: {}", self.config.mode)
            return

        self._running = True

        self._web_client = AsyncWebClient(token=self.config.bot_token)
        self._socket_client = SocketModeClient(
            app_token=self.config.app_token,
            web_client=self._web_client,
        )

        self._socket_client.socket_mode_request_listeners.append(self._on_socket_request)

        # 解析机器人用户 ID 用于提及处理
        try:
            auth = await self._web_client.auth_test()
            self._bot_user_id = auth.get("user_id")
            logger.info("Slack bot connected as {}", self._bot_user_id)
        except Exception as e:
            logger.warning("Slack auth_test failed: {}", e)

        logger.info("Starting Slack Socket Mode client...")
        await self._socket_client.connect()

        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """
        停止 Slack 客户端，关闭 Socket Mode 连接。

        停止流程：
        1. 设置运行标志为 False，停止主循环
        2. 关闭 SocketModeClient 连接
        3. 清理客户端引用

        异常处理：
        - 关闭失败：记录警告日志，不影响清理完成
        """
        self._running = False
        if self._socket_client:
            try:
                await self._socket_client.close()
            except Exception as e:
                logger.warning("Slack socket close failed: {}", e)
            self._socket_client = None

    async def send(self, msg: OutboundMessage) -> None:
        """
        通过 Slack 发送消息。

        功能：
        - 将 Markdown 转换为 mrkdwn 格式
        - 支持线程回复（thread_ts）
        - 支持文件上传
        - 空文本时发送空白消息保持媒体-only 消息格式

        Args:
            msg: 出站消息对象，包含 chat_id、content 和 media
        """
        if not self._web_client:
            logger.warning("Slack client not running")
            return
        try:
            slack_meta = msg.metadata.get("slack", {}) if msg.metadata else {}
            thread_ts = slack_meta.get("thread_ts")
            channel_type = slack_meta.get("channel_type")
            # Slack DM 不使用线程；频道/群聊回复可保留 thread_ts
            thread_ts_param = thread_ts if thread_ts and channel_type != "im" else None

            # Slack 拒绝空文本负载。保持仅媒体消息的格式，
            # 但当机器人没有文本或文件时发送单个空白消息
            if msg.content or not (msg.media or []):
                await self._web_client.chat_postMessage(
                    channel=msg.chat_id,
                    text=self._to_mrkdwn(msg.content) if msg.content else " ",
                    thread_ts=thread_ts_param,
                )

            for media_path in msg.media or []:
                try:
                    await self._web_client.files_upload_v2(
                        channel=msg.chat_id,
                        file=media_path,
                        thread_ts=thread_ts_param,
                    )
                except Exception as e:
                    logger.error("Failed to upload file {}: {}", media_path, e)
        except Exception as e:
            logger.error("Error sending Slack message: {}", e)

    async def _on_socket_request(
        self,
        client: SocketModeClient,
        req: SocketModeRequest,
    ) -> None:
        """
        处理来自 Socket Mode 的入站请求。

        处理流程：
        1. 立即确认请求（发送 SocketModeResponse）
        2. 过滤非 events_api 事件
        3. 过滤非 message/app_mention 事件类型
        4. 忽略机器人自己的消息和系统消息
        5. 避免重复处理（Slack 会同时发送 message 和 app_mention）
        6. 检查权限策略（DM、群聊）
        7. 移除机器人提及前缀
        8. 添加:eyes: 表情反应
        9. 将消息发布到消息总线

        Args:
            client: SocketModeClient 实例
            req: SocketModeRequest 请求对象
        """
        if req.type != "events_api":
            return

        # 立即确认
        await client.send_socket_mode_response(
            SocketModeResponse(envelope_id=req.envelope_id)
        )

        payload = req.payload or {}
        event = payload.get("event") or {}
        event_type = event.get("type")

        # 处理应用提及或普通消息
        if event_type not in ("message", "app_mention"):
            return

        sender_id = event.get("user")
        chat_id = event.get("channel")

        # 忽略机器人/系统消息（任何 subtype = 非正常用户消息）
        if event.get("subtype"):
            return
        if self._bot_user_id and sender_id == self._bot_user_id:
            return

        # 避免重复处理：Slack 会为频道中的提及同时发送 `message` 和 `app_mention`
        # 优先处理 `app_mention`
        text = event.get("text") or ""
        if event_type == "message" and self._bot_user_id and f"<@{self._bot_user_id}>" in text:
            return

        # 调试：记录基本事件形状
        logger.debug(
            "Slack event: type={} subtype={} user={} channel={} channel_type={} text={}",
            event_type,
            event.get("subtype"),
            sender_id,
            chat_id,
            event.get("channel_type"),
            text[:80],
        )
        if not sender_id or not chat_id:
            return

        channel_type = event.get("channel_type") or ""

        if not self._is_allowed(sender_id, chat_id, channel_type):
            return

        if channel_type != "im" and not self._should_respond_in_channel(event_type, text, chat_id):
            return

        text = self._strip_bot_mention(text)

        thread_ts = event.get("thread_ts")
        if self.config.reply_in_thread and not thread_ts:
            thread_ts = event.get("ts")
        # 为触发消息添加:eyes: 表情反应（尽力而为）
        try:
            if self._web_client and event.get("ts"):
                await self._web_client.reactions_add(
                    channel=chat_id,
                    name=self.config.react_emoji,
                    timestamp=event.get("ts"),
                )
        except Exception as e:
            logger.debug("Slack reactions_add failed: {}", e)

        # 频道/群聊消息的线程作用域会话键
        session_key = f"slack:{chat_id}:{thread_ts}" if thread_ts and channel_type != "im" else None

        try:
            await self._handle_message(
                sender_id=sender_id,
                chat_id=chat_id,
                content=text,
                metadata={
                    "slack": {
                        "event": event,
                        "thread_ts": thread_ts,
                        "channel_type": channel_type,
                    },
                },
                session_key=session_key,
            )
        except Exception:
            logger.exception("Error handling Slack message from {}", sender_id)

    def _is_allowed(self, sender_id: str, chat_id: str, channel_type: str) -> bool:
        """
        检查发送者是否被允许发送消息。

        Args:
            sender_id: 发送者用户 ID
            chat_id: 聊天/频道 ID
            channel_type: 频道类型（"im" 表示单聊）

        Returns:
            True 表示允许处理，False 表示忽略
        """
        if channel_type == "im":
            if not self.config.dm.enabled:
                return False
            if self.config.dm.policy == "allowlist":
                return sender_id in self.config.dm.allow_from
            return True

        # 群聊/频道消息
        if self.config.group_policy == "allowlist":
            return chat_id in self.config.group_allow_from
        return True

    def _should_respond_in_channel(self, event_type: str, text: str, chat_id: str) -> bool:
        """
        判断是否应该在频道中响应消息。

        Args:
            event_type: 事件类型（"message" 或 "app_mention"）
            text: 消息文本
            chat_id: 频道 ID

        Returns:
            True 表示应该响应，False 表示忽略
        """
        if self.config.group_policy == "open":
            return True
        if self.config.group_policy == "mention":
            if event_type == "app_mention":
                return True
            return self._bot_user_id is not None and f"<@{self._bot_user_id}>" in text
        if self.config.group_policy == "allowlist":
            return chat_id in self.config.group_allow_from
        return False

    def _strip_bot_mention(self, text: str) -> str:
        """
        移除消息文本中的机器人提及。

        Args:
            text: 原始消息文本

        Returns:
            移除提及后的文本
        """
        if not text or not self._bot_user_id:
            return text
        return re.sub(rf"<@{re.escape(self._bot_user_id)}>\s*", "", text).strip()

    _TABLE_RE = re.compile(r"(?m)^\|.*\|$(?:\n\|[\s:|-]*\|$)(?:\n\|.*\|$)*")
    _CODE_FENCE_RE = re.compile(r"```[\s\S]*?```")
    _INLINE_CODE_RE = re.compile(r"`[^`]+`")
    _LEFTOVER_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
    _LEFTOVER_HEADER_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
    _BARE_URL_RE = re.compile(r"(?<![|<])(https?://\S+)")

    @classmethod
    def _to_mrkdwn(cls, text: str) -> str:
        """
        将 Markdown 转换为 Slack mrkdwn 格式，包括表格。

        Args:
            text: Markdown 格式文本

        Returns:
            Slack mrkdwn 格式文本
        """
        if not text:
            return ""
        text = cls._TABLE_RE.sub(cls._convert_table, text)
        return cls._fixup_mrkdwn(slackify_markdown(text))

    @classmethod
    def _fixup_mrkdwn(cls, text: str) -> str:
        """
        修复 slackify_markdown 忽略的 Markdown 问题。

        处理：
        - 代码块占位符保存和恢复
        - **bold** 转 *bold*
        - # Header 转 *Header*
        - URL &amp; 转 &

        Args:
            text: slackify_markdown 处理后的文本

        Returns:
            修复后的 mrkdwn 文本
        """
        code_blocks: list[str] = []

        def _save_code(m: re.Match) -> str:
            code_blocks.append(m.group(0))
            return f"\x00CB{len(code_blocks) - 1}\x00"

        text = cls._CODE_FENCE_RE.sub(_save_code, text)
        text = cls._INLINE_CODE_RE.sub(_save_code, text)
        text = cls._LEFTOVER_BOLD_RE.sub(r"*\1*", text)
        text = cls._LEFTOVER_HEADER_RE.sub(r"*\1*", text)
        text = cls._BARE_URL_RE.sub(lambda m: m.group(0).replace("&amp;", "&"), text)

        for i, block in enumerate(code_blocks):
            text = text.replace(f"\x00CB{i}\x00", block)
        return text

    @staticmethod
    def _convert_table(match: re.Match) -> str:
        """
        将 Markdown 表格转换为 Slack 可读的列表格式。

        Slack mrkdwn 不支持表格，此方法将表格转换为：
        **列名**: 值 · **列名**: 值

        Args:
            match: 正则表达式匹配对象

        Returns:
            Slack 格式的列表文本
        """
        lines = [ln.strip() for ln in match.group(0).strip().splitlines() if ln.strip()]
        if len(lines) < 2:
            return match.group(0)
        headers = [h.strip() for h in lines[0].strip("|").split("|")]
        start = 2 if re.fullmatch(r"[|\s:\-]+", lines[1]) else 1
        rows: list[str] = []
        for line in lines[start:]:
            cells = [c.strip() for c in line.strip("|").split("|")]
            cells = (cells + [""] * len(headers))[: len(headers)]
            parts = [f"**{headers[i]}**: {cells[i]}" for i in range(len(headers)) if cells[i]]
            if parts:
                rows.append(" · ".join(parts))
        return "\n".join(rows)

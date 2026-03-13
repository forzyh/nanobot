# =============================================================================
# nanobot 飞书渠道
# 文件路径：nanobot/channels/feishu.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 FeishuChannel 类，让 nanobot 能够通过飞书（Lark）与用户交互。
#
# 什么是 FeishuChannel？
# --------------------
# FeishuChannel 是 nanobot 与飞书平台的"适配器"：
# 1. 通过 WebSocket 长连接接收消息事件（无需公网 IP）
# 2. 使用 lark-oapi SDK 处理飞书 API
# 3. 支持文本、图片、文件、语音、富文本卡片等多种消息类型
# 4. 支持 Markdown 表格转换、提及检测、表情回应
#
# 为什么需要 WebSocket 长连接？
# -------------------------
# 飞书支持 WebSocket 长连接推送事件，无需：
# - 配置公网 IP
# - 设置 HTTP 回调地址
# - 处理事件签名验证
#
# 架构设计：
# ---------
#   飞书 ←→ WebSocket ←→ lark-oapi SDK ←→ FeishuChannel ←→ MessageBus
#   平台      长连接推送      协议处理         渠道适配         核心处理
#
# 使用示例：
# --------
# # 配置飞书
# {
#   "channels": {
#     "feishu": {
#       "enabled": true,
#       "app_id": "cli_xxx",
#       "app_secret": "xxx",
#       "encrypt_key": "xxx",
#       "verification_token": "xxx",
#       "group_policy": "mention",
#       "allow_from": ["*"]
#     }
#   }
# }
# =============================================================================

"""Feishu/Lark channel implementation using lark-oapi SDK with WebSocket long connection."""
# 使用 lark-oapi SDK 和 WebSocket 长连接实现飞书渠道

import asyncio
import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import FeishuConfig

import importlib.util

FEISHU_AVAILABLE = importlib.util.find_spec("lark_oapi") is not None  # 检查 SDK 是否已安装

# 消息类型显示映射
MSG_TYPE_MAP = {
    "image": "[image]",
    "audio": "[audio]",
    "file": "[file]",
    "sticker": "[sticker]",
}


def _extract_share_card_content(content_json: dict, msg_type: str) -> str:
    """从分享卡片和交互式消息中提取文本表示。

    处理的卡片类型：
    - share_chat: 分享的聊天会话
    - share_user: 分享的用户名片
    - interactive: 交互式卡片消息
    - share_calendar_event: 分享的日历事件
    - system: 系统消息
    - merge_forward: 合并转发的消息

    Args:
        content_json: 卡片内容 JSON 对象
        msg_type: 消息类型

    Returns:
        str: 提取的文本表示
    """
    parts = []

    if msg_type == "share_chat":
        parts.append(f"[shared chat: {content_json.get('chat_id', '')}]")
    elif msg_type == "share_user":
        parts.append(f"[shared user: {content_json.get('user_id', '')}]")
    elif msg_type == "interactive":
        parts.extend(_extract_interactive_content(content_json))
    elif msg_type == "share_calendar_event":
        parts.append(f"[shared calendar event: {content_json.get('event_key', '')}]")
    elif msg_type == "system":
        parts.append("[system message]")
    elif msg_type == "merge_forward":
        parts.append("[merged forward messages]")

    return "\n".join(parts) if parts else f"[{msg_type}]"


def _extract_interactive_content(content: dict) -> list[str]:
    """递归提取交互式卡片中的文本和链接内容。

    提取的内容包括：
    - 标题（title 字段）
    - 元素内容（elements 数组）
    - 嵌套卡片（card 字段）
    - 头部内容（header 字段）

    Args:
        content: 交互式内容字典（可能是字符串或嵌套字典）

    Returns:
        list[str]: 提取的文本内容列表
    """
    parts = []

    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return [content] if content.strip() else []

    if not isinstance(content, dict):
        return parts

    if "title" in content:
        title = content["title"]
        if isinstance(title, dict):
            title_content = title.get("content", "") or title.get("text", "")
            if title_content:
                parts.append(f"title: {title_content}")
        elif isinstance(title, str):
            parts.append(f"title: {title}")

    for elements in content.get("elements", []) if isinstance(content.get("elements"), list) else []:
        for element in elements:
            parts.extend(_extract_element_content(element))

    card = content.get("card", {})
    if card:
        parts.extend(_extract_interactive_content(card))

    header = content.get("header", {})
    if header:
        header_title = header.get("title", {})
        if isinstance(header_title, dict):
            header_text = header_title.get("content", "") or header_title.get("text", "")
            if header_text:
                parts.append(f"title: {header_text}")

    return parts


def _extract_element_content(element: dict) -> list[str]:
    """从单个卡片元素中提取内容。

    支持的元素标签：
    - markdown/lark_md: Markdown 文本内容
    - div: 文本容器字段
    - a: 链接元素
    - button: 按钮（含文本和 URL）
    - img: 图片
    - note: 备注元素
    - column_set: 列布局容器
    - plain_text: 纯文本

    Args:
        element: 卡片元素字典

    Returns:
        list[str]: 提取的文本内容列表
    """
    parts = []

    if not isinstance(element, dict):
        return parts

    tag = element.get("tag", "")

    if tag in ("markdown", "lark_md"):
        content = element.get("content", "")
        if content:
            parts.append(content)

    elif tag == "div":
        text = element.get("text", {})
        if isinstance(text, dict):
            text_content = text.get("content", "") or text.get("text", "")
            if text_content:
                parts.append(text_content)
        elif isinstance(text, str):
            parts.append(text)
        for field in element.get("fields", []):
            if isinstance(field, dict):
                field_text = field.get("text", {})
                if isinstance(field_text, dict):
                    c = field_text.get("content", "")
                    if c:
                        parts.append(c)

    elif tag == "a":
        href = element.get("href", "")
        text = element.get("text", "")
        if href:
            parts.append(f"link: {href}")
        if text:
            parts.append(text)

    elif tag == "button":
        text = element.get("text", {})
        if isinstance(text, dict):
            c = text.get("content", "")
            if c:
                parts.append(c)
        url = element.get("url", "") or element.get("multi_url", {}).get("url", "")
        if url:
            parts.append(f"link: {url}")

    elif tag == "img":
        alt = element.get("alt", {})
        parts.append(alt.get("content", "[image]") if isinstance(alt, dict) else "[image]")

    elif tag == "note":
        for ne in element.get("elements", []):
            parts.extend(_extract_element_content(ne))

    elif tag == "column_set":
        for col in element.get("columns", []):
            for ce in col.get("elements", []):
                parts.extend(_extract_element_content(ce))

    elif tag == "plain_text":
        content = element.get("content", "")
        if content:
            parts.append(content)

    else:
        for ne in element.get("elements", []):
            parts.extend(_extract_element_content(ne))

    return parts


def _extract_post_content(content_json: dict) -> tuple[str, list[str]]:
    """从飞书富文本（post）消息中提取文本和图片 key。

    支持三种负载格式：
    - 直接格式：{"title": "...", "content": [[...]]}
    - 本地化格式：{"zh_cn": {"title": "...", "content": [...]}}
    - 包装格式：{"post": {"zh_cn": {"title": "...", "content": [...]}}}

    提取的内容：
    - 文本：text 标签、a 标签、at 提及
    - 图片：img 标签的 image_key

    Args:
        content_json: post 消息的 content JSON

    Returns:
        tuple[str, list[str]]: (文本内容，图片 key 列表)
    """

    def _parse_block(block: dict) -> tuple[str | None, list[str]]:
        if not isinstance(block, dict) or not isinstance(block.get("content"), list):
            return None, []
        texts, images = [], []
        if title := block.get("title"):
            texts.append(title)
        for row in block["content"]:
            if not isinstance(row, list):
                continue
            for el in row:
                if not isinstance(el, dict):
                    continue
                tag = el.get("tag")
                if tag in ("text", "a"):
                    texts.append(el.get("text", ""))
                elif tag == "at":
                    texts.append(f"@{el.get('user_name', 'user')}")
                elif tag == "img" and (key := el.get("image_key")):
                    images.append(key)
        return (" ".join(texts).strip() or None), images

    # Unwrap optional {"post": ...} envelope
    root = content_json
    if isinstance(root, dict) and isinstance(root.get("post"), dict):
        root = root["post"]
    if not isinstance(root, dict):
        return "", []

    # Direct format
    if "content" in root:
        text, imgs = _parse_block(root)
        if text or imgs:
            return text or "", imgs

    # Localized: prefer known locales, then fall back to any dict child
    for key in ("zh_cn", "en_us", "ja_jp"):
        if key in root:
            text, imgs = _parse_block(root[key])
            if text or imgs:
                return text or "", imgs
    for val in root.values():
        if isinstance(val, dict):
            text, imgs = _parse_block(val)
            if text or imgs:
                return text or "", imgs

    return "", []


def _extract_post_text(content_json: dict) -> str:
    """从飞书富文本（post）消息中提取纯文本。

    这是 _extract_post_content 的遗留包装器，仅返回文本部分。

    Args:
        content_json: post 消息的 content JSON

    Returns:
        str: 提取的纯文本内容
    """
    text, _ = _extract_post_content(content_json)
    return text


class FeishuChannel(BaseChannel):
    """
    使用 WebSocket 长连接的飞书/Lark 渠道实现。

    核心特性：
    --------
    1. WebSocket 长连接：无需公网 IP 或 webhook 回调
    2. 多格式消息检测：自动识别 text/post/interactive 格式
    3. Markdown 表格转换：转换为飞书卡片表格元素
    4. 媒体上传/下载：支持图片、文件、语音
    5. 语音转录：支持 audio 类型消息的转录
    6. 表情回应：收到消息后自动添加表情回应
    7. 提及检测：支持@_all 和机器人提及检测
    8. 消息去重：使用 OrderedDict 防止重复处理

    属性说明：
    --------
    name: str
        渠道名称："feishu"

    display_name: str
        显示名称："Feishu"

    _client: Any
        飞书 API 客户端（用于发送消息）

    _ws_client: Any
        飞书 WebSocket 客户端（用于接收事件）

    _ws_thread: threading.Thread | None
        WebSocket 线程（运行独立事件循环）

    _processed_message_ids: OrderedDict[str, None]
        已处理消息 ID 集合（防止重复，最多 1000 条）

    _loop: asyncio.AbstractEventLoop | None
        主事件循环（用于线程间调度）

    使用示例：
    --------
    >>> config = FeishuConfig(app_id="cli_xxx", app_secret="xxx")
    >>> channel = FeishuChannel(config, message_bus)
    >>> await channel.start()  # 启动 WebSocket 连接
    """

    name = "feishu"
    display_name = "Feishu"

    def __init__(self, config: FeishuConfig, bus: MessageBus):
        """
        初始化飞书渠道。

        Args:
            config: 飞书配置对象（包含 app_id、app_secret、encrypt_key 等）
            bus: 消息总线实例
        """
        super().__init__(config, bus)
        self.config: FeishuConfig = config  # 飞书配置
        self._client: Any = None  # 飞书 API 客户端
        self._ws_client: Any = None  # WebSocket 客户端
        self._ws_thread: threading.Thread | None = None  # WebSocket 线程
        self._processed_message_ids: OrderedDict[str, None] = OrderedDict()  # 消息去重缓存
        self._loop: asyncio.AbstractEventLoop | None = None  # 主事件循环

    @staticmethod
    def _register_optional_event(builder: Any, method_name: str, handler: Any) -> Any:
        """当 SDK 支持时注册事件处理器（兼容不同 SDK 版本）。

        Args:
            builder: 事件构建器对象
            method_name: 方法名称（如 register_p2_im_message_reaction_created_v1）
            handler: 事件处理函数

        Returns:
            Any: 构建器对象（如果方法存在则返回注册后的结果，否则返回原构建器）
        """
        method = getattr(builder, method_name, None)
        return method(handler) if callable(method) else builder

    async def start(self) -> None:
        """
        启动飞书机器人（WebSocket 长连接）。

        启动流程：
        --------
        1. 检查 SDK 是否已安装
        2. 检查 app_id 和 app_secret 是否配置
        3. 创建飞书 API 客户端（用于发送消息）
        4. 创建事件处理器（注册消息接收、表情回应、消息阅读等事件）
        5. 创建 WebSocket 客户端
        6. 在独立线程中启动 WebSocket 连接（避免事件循环冲突）
        7. 自动重连：连接断开后 5 秒重试

        线程模型：
        ---------
        WebSocket SDK 使用模块级 event loop，需要创建独立线程：
        - 主线程：运行 nanobot 核心 asyncio 事件循环
        - WebSocket 线程：运行独立的 asyncio 事件循环供 SDK 使用
        - asyncio.run_coroutine_threadsafe()：在线程间调度消息处理

        注意：
        ----
        这是一个长期运行的方法，会持续监听直到 stop() 被调用。
        """
        if not FEISHU_AVAILABLE:
            logger.error("Feishu SDK not installed. Run: pip install lark-oapi")
            return

        if not self.config.app_id or not self.config.app_secret:
            logger.error("Feishu app_id and app_secret not configured")
            return

        import lark_oapi as lark
        self._running = True
        self._loop = asyncio.get_running_loop()

        # 创建飞书客户端（用于发送消息）
        self._client = lark.Client.builder() \
            .app_id(self.config.app_id) \
            .app_secret(self.config.app_secret) \
            .log_level(lark.LogLevel.INFO) \
            .build()
        # 创建事件处理器（注册消息接收事件）
        builder = lark.EventDispatcherHandler.builder(
            self.config.encrypt_key or "",
            self.config.verification_token or "",
        ).register_p2_im_message_receive_v1(
            self._on_message_sync
        )
        # 可选事件：表情回应创建
        builder = self._register_optional_event(
            builder, "register_p2_im_message_reaction_created_v1", self._on_reaction_created
        )
        # 可选事件：消息阅读
        builder = self._register_optional_event(
            builder, "register_p2_im_message_message_read_v1", self._on_message_read
        )
        # 可选事件：机器人私聊进入
        builder = self._register_optional_event(
            builder,
            "register_p2_im_chat_access_event_bot_p2p_chat_entered_v1",
            self._on_bot_p2p_chat_entered,
        )
        event_handler = builder.build()

        # 创建 WebSocket 客户端（用于长连接接收事件）
        self._ws_client = lark.ws.Client(
            self.config.app_id,
            self.config.app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.INFO
        )

        # 在独立线程中启动 WebSocket 客户端（带重连循环）
        # 创建独立事件循环以避免 "This event loop is already running" 错误
        def run_ws():
            import time
            import lark_oapi.ws.client as _lark_ws_client
            ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(ws_loop)
            # 修补 lark 的模块级 loop 引用
            _lark_ws_client.loop = ws_loop
            try:
                while self._running:
                    try:
                        self._ws_client.start()
                    except Exception as e:
                        logger.warning("Feishu WebSocket error: {}", e)
                    if self._running:
                        time.sleep(5)  # 重连间隔
            finally:
                ws_loop.close()

        self._ws_thread = threading.Thread(target=run_ws, daemon=True)
        self._ws_thread.start()

        logger.info("Feishu bot started with WebSocket long connection")
        logger.info("No public IP required - using WebSocket to receive events")

        # 保持运行直到被停止
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """
        停止飞书机器人。

        注意：lark.ws.Client 不暴露 stop 方法，直接退出程序会关闭客户端。
        """
        self._running = False
        logger.info("Feishu bot stopped")

    def _is_bot_mentioned(self, message: Any) -> bool:
        """检查消息中是否@了机器人。

        提及检测规则：
        1. 检查是否包含@_all（全员提及）
        2. 检查 mentions 数组中是否有机器人（user_id 为空且 open_id 以 ou_ 开头）

        Args:
            message: 飞书消息对象

        Returns:
            bool: True 表示机器人被提及
        """
        raw_content = message.content or ""
        if "@_all" in raw_content:
            return True

        for mention in getattr(message, "mentions", None) or []:
            mid = getattr(mention, "id", None)
            if not mid:
                continue
            # Bot mentions have no user_id (None or "") but a valid open_id
            if not getattr(mid, "user_id", None) and (getattr(mid, "open_id", None) or "").startswith("ou_"):
                return True
        return False

    def _is_group_message_for_bot(self, message: Any) -> bool:
        """根据群聊策略判断是否处理群消息。

        策略说明：
        - open: 处理所有群消息
        - mention: 仅处理提及机器人的消息

        Args:
            message: 飞书消息对象

        Returns:
            bool: True 表示应该处理
        """
        if self.config.group_policy == "open":
            return True
        return self._is_bot_mentioned(message)

    def _add_reaction_sync(self, message_id: str, emoji_type: str) -> None:
        """添加表情回应的同步辅助方法（在线程池中运行）。

        Args:
            message_id: 消息 ID
            emoji_type: 表情类型（如 THUMBSUP、OK、EYES 等）
        """
        from lark_oapi.api.im.v1 import CreateMessageReactionRequest, CreateMessageReactionRequestBody, Emoji
        try:
            request = CreateMessageReactionRequest.builder() \
                .message_id(message_id) \
                .request_body(
                    CreateMessageReactionRequestBody.builder()
                    .reaction_type(Emoji.builder().emoji_type(emoji_type).build())
                    .build()
                ).build()

            response = self._client.im.v1.message_reaction.create(request)

            if not response.success():
                logger.warning("Failed to add reaction: code={}, msg={}", response.code, response.msg)
            else:
                logger.debug("Added {} reaction to message {}", emoji_type, message_id)
        except Exception as e:
            logger.warning("Error adding reaction: {}", e)

    async def _add_reaction(self, message_id: str, emoji_type: str = "THUMBSUP") -> None:
        """
        给消息添加表情回应（非阻塞）。

        常见表情类型：
        - THUMBSUP: 点赞
        - OK: OK
        - EYES: 关注
        - DONE: 完成
        - OnIt: 处理中
        - HEART: 爱心

        Args:
            message_id: 消息 ID
            emoji_type: 表情类型，默认 THUMBSUP
        """
        if not self._client:
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._add_reaction_sync, message_id, emoji_type)

    # 匹配 Markdown 表格的正则表达式（标题行 + 分隔行 + 数据行）
    _TABLE_RE = re.compile(
        r"((?:^[ \t]*\|.+\|[ \t]*\n)(?:^[ \t]*\|[-:\s|]+\|[ \t]*\n)(?:^[ \t]*\|.+\|[ \t]*\n?)+)",
        re.MULTILINE,
    )

    # 匹配 Markdown 标题的正则表达式
    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    # 匹配 Markdown 代码块的正则表达式
    _CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?```)", re.MULTILINE)

    @staticmethod
    def _parse_md_table(table_text: str) -> dict | None:
        """将 Markdown 表格解析为飞书表格元素。

        Args:
            table_text: Markdown 表格文本

        Returns:
            dict | None: 飞书表格元素字典，解析失败返回 None
        """
        lines = [_line.strip() for _line in table_text.strip().split("\n") if _line.strip()]
        if len(lines) < 3:
            return None
        def split(_line: str) -> list[str]:
            return [c.strip() for c in _line.strip("|").split("|")]
        headers = split(lines[0])
        rows = [split(_line) for _line in lines[2:]]
        columns = [{"tag": "column", "name": f"c{i}", "display_name": h, "width": "auto"}
                   for i, h in enumerate(headers)]
        return {
            "tag": "table",
            "page_size": len(rows) + 1,
            "columns": columns,
            "rows": [{f"c{i}": r[i] if i < len(r) else "" for i in range(len(headers))} for r in rows],
        }

    def _build_card_elements(self, content: str) -> list[dict]:
        """将内容分割为 div/markdown + 表格元素，用于飞书卡片消息。

        处理流程：
        1. 使用 _TABLE_RE 查找所有 Markdown 表格
        2. 表格前的内容使用 _split_headings 处理（分割标题）
        3. 表格转换为飞书表格元素
        4. 剩余内容使用 _split_headings 处理

        Args:
            content: Markdown 内容字符串

        Returns:
            list[dict]: 卡片元素列表
        """
        elements, last_end = [], 0
        for m in self._TABLE_RE.finditer(content):
            before = content[last_end:m.start()]
            if before.strip():
                elements.extend(self._split_headings(before))
            elements.append(self._parse_md_table(m.group(1)) or {"tag": "markdown", "content": m.group(1)})
            last_end = m.end()
        remaining = content[last_end:]
        if remaining.strip():
            elements.extend(self._split_headings(remaining))
        return elements or [{"tag": "markdown", "content": content}]

    @staticmethod
    def _split_elements_by_table_limit(elements: list[dict], max_tables: int = 1) -> list[list[dict]]:
        """将卡片元素分组，每组最多包含 *max_tables* 个表格元素。

        背景：
        飞书卡片有硬性限制：每个卡片只能包含一个表格（API 错误 11310）。
        当渲染内容包含多个 Markdown 表格时，需要将每个表格放在独立的消息卡片中。

        Args:
            elements: 卡片元素列表
            max_tables: 每组最多包含的表格数量，默认 1

        Returns:
            list[list[dict]]: 分组后的元素列表
        """
        if not elements:
            return [[]]
        groups: list[list[dict]] = []
        current: list[dict] = []
        table_count = 0
        for el in elements:
            if el.get("tag") == "table":
                if table_count >= max_tables:
                    if current:
                        groups.append(current)
                    current = []
                    table_count = 0
                current.append(el)
                table_count += 1
            else:
                current.append(el)
        if current:
            groups.append(current)
        return groups or [[]]

    def _split_headings(self, content: str) -> list[dict]:
        """按标题分割内容，将标题转换为 div 元素。

        处理流程：
        1. 保护代码块（避免代码块中的#被误识别为标题）
        2. 使用 _HEADING_RE 查找所有标题
        3. 标题前的内容作为 markdown 元素
        4. 标题本身转换为 div 元素（加粗显示）
        5. 恢复代码块占位符

        Args:
            content: Markdown 内容字符串

        Returns:
            list[dict]: 元素列表（markdown 和 div 交替）
        """
        protected = content
        code_blocks = []
        for m in self._CODE_BLOCK_RE.finditer(content):
            code_blocks.append(m.group(1))
            protected = protected.replace(m.group(1), f"\x00CODE{len(code_blocks)-1}\x00", 1)

        elements = []
        last_end = 0
        for m in self._HEADING_RE.finditer(protected):
            before = protected[last_end:m.start()].strip()
            if before:
                elements.append({"tag": "markdown", "content": before})
            text = m.group(2).strip()
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{text}**",
                },
            })
            last_end = m.end()
        remaining = protected[last_end:].strip()
        if remaining:
            elements.append({"tag": "markdown", "content": remaining})

        for i, cb in enumerate(code_blocks):
            for el in elements:
                if el.get("tag") == "markdown":
                    el["content"] = el["content"].replace(f"\x00CODE{i}\x00", cb)

        return elements or [{"tag": "markdown", "content": content}]

    # ── 智能格式检测 ──────────────────────────────────────────
    # 检测"复杂"Markdown 的正则表达式（需要卡片渲染）
    _COMPLEX_MD_RE = re.compile(
        r"```"                        # fenced 代码块
        r"|^\|.+\|.*\n\s*\|[-:\s|]+\|"  # Markdown 表格（标题行 + 分隔行）
        r"|^#{1,6}\s+"                # 标题
        , re.MULTILINE,
    )

    # 简单 Markdown 模式（粗体、斜体、删除线）
    _SIMPLE_MD_RE = re.compile(
        r"\*\*.+?\*\*"               # **粗体**
        r"|__.+?__"                   # __粗体__
        r"|(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"  # *斜体*（单星号）
        r"|~~.+?~~"                   # ~~删除线~~
        , re.DOTALL,
    )

    # Markdown 链接：[text](url)
    _MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")

    # 无序列表项
    _LIST_RE = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)

    # 有序列表项
    _OLIST_RE = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)

    # 纯文本格式最大长度
    _TEXT_MAX_LEN = 200

    # 富文本（post）格式最大长度，超过此值使用卡片
    _POST_MAX_LEN = 2000

    @classmethod
    def _detect_msg_format(cls, content: str) -> str:
        """确定内容的最优飞书消息格式。

        检测逻辑：
        1. 复杂 Markdown（代码块、表格、标题）→ interactive（卡片）
        2. 长内容（>2000 字符）→ interactive（更好的可读性）
        3. 简单 Markdown（粗体、斜体、删除线）→ interactive（post 不支持这些格式）
        4. 列表项 → interactive（post 不支持列表符号）
        5. 链接 → post（支持<a>标签）
        6. 短纯文本（<=200 字符）→ text
        7. 中等纯文本 → post

        Returns:
            str: "text"（纯文本）、"post"（富文本）或"interactive"（卡片）
        """
        stripped = content.strip()

        # Complex markdown (code blocks, tables, headings) → always card
        if cls._COMPLEX_MD_RE.search(stripped):
            return "interactive"

        # Long content → card (better readability with card layout)
        if len(stripped) > cls._POST_MAX_LEN:
            return "interactive"

        # Has bold/italic/strikethrough → card (post format can't render these)
        if cls._SIMPLE_MD_RE.search(stripped):
            return "interactive"

        # Has list items → card (post format can't render list bullets well)
        if cls._LIST_RE.search(stripped) or cls._OLIST_RE.search(stripped):
            return "interactive"

        # Has links → post format (supports <a> tags)
        if cls._MD_LINK_RE.search(stripped):
            return "post"

        # Short plain text → text format
        if len(stripped) <= cls._TEXT_MAX_LEN:
            return "text"

        # Medium plain text without any formatting → post format
        return "post"

    @classmethod
    def _markdown_to_post(cls, content: str) -> str:
        """将 Markdown 内容转换为飞书 post 消息 JSON。

        转换规则：
        - 链接 [text](url) → a 标签
        - 其他内容 → text 标签
        - 每行转换为一个段落（行）

        Args:
            content: Markdown 内容字符串

        Returns:
            str: post 消息的 JSON 字符串
        """
        lines = content.strip().split("\n")
        paragraphs: list[list[dict]] = []

        for line in lines:
            elements: list[dict] = []
            last_end = 0

            for m in cls._MD_LINK_RE.finditer(line):
                # Text before this link
                before = line[last_end:m.start()]
                if before:
                    elements.append({"tag": "text", "text": before})
                elements.append({
                    "tag": "a",
                    "text": m.group(1),
                    "href": m.group(2),
                })
                last_end = m.end()

            # Remaining text after last link
            remaining = line[last_end:]
            if remaining:
                elements.append({"tag": "text", "text": remaining})

            # Empty line → empty paragraph for spacing
            if not elements:
                elements.append({"tag": "text", "text": ""})

            paragraphs.append(elements)

        post_body = {
            "zh_cn": {
                "content": paragraphs,
            }
        }
        return json.dumps(post_body, ensure_ascii=False)

    # 图片文件扩展名集合
    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"}
    # 音频文件扩展名集合
    _AUDIO_EXTS = {".opus"}
    # 视频文件扩展名集合
    _VIDEO_EXTS = {".mp4", ".mov", ".avi"}
    # 文件类型映射（扩展名 → 飞书文件类型）
    _FILE_TYPE_MAP = {
        ".opus": "opus", ".mp4": "mp4", ".pdf": "pdf", ".doc": "doc", ".docx": "doc",
        ".xls": "xls", ".xlsx": "xls", ".ppt": "ppt", ".pptx": "ppt",
    }

    def _upload_image_sync(self, file_path: str) -> str | None:
        """上传图片到飞书并返回 image_key。

        Args:
            file_path: 图片文件路径

        Returns:
            str | None: 图片 key，上传失败返回 None
        """
        from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody
        try:
            with open(file_path, "rb") as f:
                request = CreateImageRequest.builder() \
                    .request_body(
                        CreateImageRequestBody.builder()
                        .image_type("message")
                        .image(f)
                        .build()
                    ).build()
                response = self._client.im.v1.image.create(request)
                if response.success():
                    image_key = response.data.image_key
                    logger.debug("Uploaded image {}: {}", os.path.basename(file_path), image_key)
                    return image_key
                else:
                    logger.error("Failed to upload image: code={}, msg={}", response.code, response.msg)
                    return None
        except Exception as e:
            logger.error("Error uploading image {}: {}", file_path, e)
            return None

    def _upload_file_sync(self, file_path: str) -> str | None:
        """上传文件到飞书并返回 file_key。

        Args:
            file_path: 文件路径

        Returns:
            str | None: 文件 key，上传失败返回 None
        """
        from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody
        ext = os.path.splitext(file_path)[1].lower()
        file_type = self._FILE_TYPE_MAP.get(ext, "stream")
        file_name = os.path.basename(file_path)
        try:
            with open(file_path, "rb") as f:
                request = CreateFileRequest.builder() \
                    .request_body(
                        CreateFileRequestBody.builder()
                        .file_type(file_type)
                        .file_name(file_name)
                        .file(f)
                        .build()
                    ).build()
                response = self._client.im.v1.file.create(request)
                if response.success():
                    file_key = response.data.file_key
                    logger.debug("Uploaded file {}: {}", file_name, file_key)
                    return file_key
                else:
                    logger.error("Failed to upload file: code={}, msg={}", response.code, response.msg)
                    return None
        except Exception as e:
            logger.error("Error uploading file {}: {}", file_path, e)
            return None

    def _download_image_sync(self, message_id: str, image_key: str) -> tuple[bytes | None, str | None]:
        """根据消息 ID 和图片 key 从飞书下载图片。

        Args:
            message_id: 消息 ID
            image_key: 图片 key

        Returns:
            tuple[bytes | None, str | None]: (图片字节数据，文件名)，下载失败返回 (None, None)
        """
        from lark_oapi.api.im.v1 import GetMessageResourceRequest
        try:
            request = GetMessageResourceRequest.builder() \
                .message_id(message_id) \
                .file_key(image_key) \
                .type("image") \
                .build()
            response = self._client.im.v1.message_resource.get(request)
            if response.success():
                file_data = response.file
                # GetMessageResourceRequest returns BytesIO, need to read bytes
                if hasattr(file_data, 'read'):
                    file_data = file_data.read()
                return file_data, response.file_name
            else:
                logger.error("Failed to download image: code={}, msg={}", response.code, response.msg)
                return None, None
        except Exception as e:
            logger.error("Error downloading image {}: {}", image_key, e)
            return None, None

    def _download_file_sync(
        self, message_id: str, file_key: str, resource_type: str = "file"
    ) -> tuple[bytes | None, str | None]:
        """根据消息 ID 和 file_key 从飞书下载文件/音频/媒体。

        Args:
            message_id: 消息 ID
            file_key: 文件 key
            resource_type: 资源类型（"file"、"audio"、"media"）

        Returns:
            tuple[bytes | None, str | None]: (文件字节数据，文件名)，下载失败返回 (None, None)

        注意：
        ----
        飞书 API 只接受'image'或'file'作为 type 参数，audio 类型需要转换为'file'。
        """
        from lark_oapi.api.im.v1 import GetMessageResourceRequest

        # 飞书 API 只接受'image'或'file'作为 type 参数
        # audio 类型转换为'file'以兼容 API
        if resource_type == "audio":
            resource_type = "file"

        try:
            request = (
                GetMessageResourceRequest.builder()
                .message_id(message_id)
                .file_key(file_key)
                .type(resource_type)
                .build()
            )
            response = self._client.im.v1.message_resource.get(request)
            if response.success():
                file_data = response.file
                if hasattr(file_data, "read"):
                    file_data = file_data.read()
                return file_data, response.file_name
            else:
                logger.error("Failed to download {}: code={}, msg={}", resource_type, response.code, response.msg)
                return None, None
        except Exception:
            logger.exception("Error downloading {} {}", resource_type, file_key)
            return None, None

    async def _download_and_save_media(
        self,
        msg_type: str,
        content_json: dict,
        message_id: str | None = None
    ) -> tuple[str | None, str]:
        """
        从飞书下载媒体并保存到本地磁盘。

        支持的媒体类型：
        - image: 图片
        - audio: 音频（支持转录）
        - file: 文件
        - media: 视频

        Args:
            msg_type: 媒体类型
            content_json: 消息内容 JSON（包含 image_key 或 file_key）
            message_id: 消息 ID（用于下载）

        Returns:
            tuple[str | None, str]: (文件路径，内容文本) - 下载失败时 file_path 为 None
        """
        loop = asyncio.get_running_loop()
        media_dir = get_media_dir("feishu")

        data, filename = None, None

        if msg_type == "image":
            image_key = content_json.get("image_key")
            if image_key and message_id:
                data, filename = await loop.run_in_executor(
                    None, self._download_image_sync, message_id, image_key
                )
                if not filename:
                    filename = f"{image_key[:16]}.jpg"

        elif msg_type in ("audio", "file", "media"):
            file_key = content_json.get("file_key")
            if file_key and message_id:
                data, filename = await loop.run_in_executor(
                    None, self._download_file_sync, message_id, file_key, msg_type
                )
                if not filename:
                    filename = file_key[:16]
                if msg_type == "audio" and not filename.endswith(".opus"):
                    filename = f"{filename}.opus"

        if data and filename:
            file_path = media_dir / filename
            file_path.write_bytes(data)
            logger.debug("Downloaded {} to {}", msg_type, file_path)
            return str(file_path), f"[{msg_type}: {filename}]"

        return None, f"[{msg_type}: download failed]"

    def _send_message_sync(self, receive_id_type: str, receive_id: str, msg_type: str, content: str) -> bool:
        """同步发送单条消息（文本/图片/文件/交互式卡片）。

        Args:
            receive_id_type: 接收者 ID 类型（"open_id"或"chat_id"）
            receive_id: 接收者 ID
            msg_type: 消息类型（"text"、"image"、"file"、"media"、"interactive"、"post"）
            content: 消息内容（JSON 字符串）

        Returns:
            bool: 成功返回 True
        """
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        try:
            request = CreateMessageRequest.builder() \
                .receive_id_type(receive_id_type) \
                .request_body(
                    CreateMessageRequestBody.builder()
                    .receive_id(receive_id)
                    .msg_type(msg_type)
                    .content(content)
                    .build()
                ).build()
            response = self._client.im.v1.message.create(request)
            if not response.success():
                logger.error(
                    "Failed to send Feishu {} message: code={}, msg={}, log_id={}",
                    msg_type, response.code, response.msg, response.get_log_id()
                )
                return False
            logger.debug("Feishu {} message sent to {}", msg_type, receive_id)
            return True
        except Exception as e:
            logger.error("Error sending Feishu {} message: {}", msg_type, e)
            return False

    async def send(self, msg: OutboundMessage) -> None:
        """通过飞书发送消息，包括媒体（图片/文件）。

        发送流程：
        --------
        1. 检查客户端是否初始化
        2. 判断接收者 ID 类型（chat_id 以 oc_开头，否则为 open_id）
        3. 发送媒体文件（如果有）：
           - 图片：上传后发送 image 消息
           - 音频/视频：上传后发送 media 消息
           - 其他文件：上传后发送 file 消息
        4. 发送文本内容：
           - 检测格式（text/post/interactive）
           - 根据格式发送对应类型的消息

        Args:
            msg: 出站消息对象（包含 chat_id、content、media 等）
        """
        if not self._client:
            logger.warning("Feishu client not initialized")
            return

        try:
            receive_id_type = "chat_id" if msg.chat_id.startswith("oc_") else "open_id"
            loop = asyncio.get_running_loop()

            for file_path in msg.media:
                if not os.path.isfile(file_path):
                    logger.warning("Media file not found: {}", file_path)
                    continue
                ext = os.path.splitext(file_path)[1].lower()
                if ext in self._IMAGE_EXTS:
                    # 图片：上传并发送
                    key = await loop.run_in_executor(None, self._upload_image_sync, file_path)
                    if key:
                        await loop.run_in_executor(
                            None, self._send_message_sync,
                            receive_id_type, msg.chat_id, "image", json.dumps({"image_key": key}, ensure_ascii=False),
                        )
                else:
                    # 文件/音频/视频：上传并发送
                    key = await loop.run_in_executor(None, self._upload_file_sync, file_path)
                    if key:
                        # 音频/视频使用"media"类型（支持内联播放）
                        # 其他文件使用"file"类型（文档、压缩包等）
                        if ext in self._AUDIO_EXTS or ext in self._VIDEO_EXTS:
                            media_type = "media"
                        else:
                            media_type = "file"
                        await loop.run_in_executor(
                            None, self._send_message_sync,
                            receive_id_type, msg.chat_id, media_type, json.dumps({"file_key": key}, ensure_ascii=False),
                        )

            if msg.content and msg.content.strip():
                fmt = self._detect_msg_format(msg.content)

                if fmt == "text":
                    # 短纯文本 - 发送简单文本消息
                    text_body = json.dumps({"text": msg.content.strip()}, ensure_ascii=False)
                    await loop.run_in_executor(
                        None, self._send_message_sync,
                        receive_id_type, msg.chat_id, "text", text_body,
                    )

                elif fmt == "post":
                    # 中等长度内容（含链接）- 发送富文本 post 消息
                    post_body = self._markdown_to_post(msg.content)
                    await loop.run_in_executor(
                        None, self._send_message_sync,
                        receive_id_type, msg.chat_id, "post", post_body,
                    )

                else:
                    # 复杂/长内容 - 发送交互式卡片
                    elements = self._build_card_elements(msg.content)
                    for chunk in self._split_elements_by_table_limit(elements):
                        card = {"config": {"wide_screen_mode": True}, "elements": chunk}
                        await loop.run_in_executor(
                            None, self._send_message_sync,
                            receive_id_type, msg.chat_id, "interactive", json.dumps(card, ensure_ascii=False),
                        )

        except Exception as e:
            logger.error("Error sending Feishu message: {}", e)

    def _on_message_sync(self, data: Any) -> None:
        """
        传入消息的同步处理器（从 WebSocket 线程调用）。

        线程调度：
        使用 asyncio.run_coroutine_threadsafe() 将异步处理调度到主事件循环。
        """
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._on_message(data), self._loop)

    async def _on_message(self, data: Any) -> None:
        """处理来自飞书的传入消息。

        处理流程：
        --------
        1. 提取事件数据（message、sender）
        2. 消息去重（检查 message_id）
        3. 忽略机器人自己的消息
        4. 检查群聊策略（open/mention）
        5. 添加表情回应
        6. 解析消息内容（text/post/image/audio/file 等）
        7. 下载媒体文件（如果有）
        8. 音频消息转录
        9. 转发到消息总线

        消息类型处理：
        -----------
        - text: 提取文本内容
        - post: 提取富文本内容和图片
        - image/audio/file/media: 下载媒体文件
        - share_chat/share_user/interactive 等：提取卡片内容
        """
        try:
            event = data.event
            message = event.message
            sender = event.sender

            # 消息去重
            message_id = message.message_id
            if message_id in self._processed_message_ids:
                return  # 已处理，跳过
            self._processed_message_ids[message_id] = None

            # 限制缓存大小（最多 1000 条）
            while len(self._processed_message_ids) > 1000:
                self._processed_message_ids.popitem(last=False)

            # 忽略机器人消息
            if sender.sender_type == "bot":
                return

            sender_id = sender.sender_id.open_id if sender.sender_id else "unknown"
            chat_id = message.chat_id
            chat_type = message.chat_type
            msg_type = message.message_type

            # 检查群聊策略
            if chat_type == "group" and not self._is_group_message_for_bot(message):
                logger.debug("Feishu: skipping group message (not mentioned)")
                return

            # 添加表情回应
            await self._add_reaction(message_id, self.config.react_emoji)

            # 解析内容
            content_parts = []
            media_paths = []

            try:
                content_json = json.loads(message.content) if message.content else {}
            except json.JSONDecodeError:
                content_json = {}

            if msg_type == "text":
                # 文本消息
                text = content_json.get("text", "")
                if text:
                    content_parts.append(text)

            elif msg_type == "post":
                # 富文本消息：提取文本和图片
                text, image_keys = _extract_post_content(content_json)
                if text:
                    content_parts.append(text)
                # 下载 post 中嵌入的图片
                for img_key in image_keys:
                    file_path, content_text = await self._download_and_save_media(
                        "image", {"image_key": img_key}, message_id
                    )
                    if file_path:
                        media_paths.append(file_path)
                    content_parts.append(content_text)

            elif msg_type in ("image", "audio", "file", "media"):
                # 图片/音频/文件/视频消息
                file_path, content_text = await self._download_and_save_media(msg_type, content_json, message_id)
                if file_path:
                    media_paths.append(file_path)

                if msg_type == "audio" and file_path:
                    # 音频消息转录
                    transcription = await self.transcribe_audio(file_path)
                    if transcription:
                        content_text = f"[transcription: {transcription}]"

                content_parts.append(content_text)

            elif msg_type in ("share_chat", "share_user", "interactive", "share_calendar_event", "system", "merge_forward"):
                # 分享卡片和交互式消息
                text = _extract_share_card_content(content_json, msg_type)
                if text:
                    content_parts.append(text)

            else:
                # 其他消息类型
                content_parts.append(MSG_TYPE_MAP.get(msg_type, f"[{msg_type}]"))

            content = "\n".join(content_parts) if content_parts else ""

            if not content and not media_paths:
                return

            # 转发到消息总线
            # 群聊使用 chat_id 回复，私聊使用 sender_id
            reply_to = chat_id if chat_type == "group" else sender_id
            await self._handle_message(
                sender_id=sender_id,
                chat_id=reply_to,
                content=content,
                media=media_paths,
                metadata={
                    "message_id": message_id,
                    "chat_type": chat_type,
                    "msg_type": msg_type,
                }
            )

        except Exception as e:
            logger.error("Error processing Feishu message: {}", e)

    def _on_reaction_created(self, data: Any) -> None:
        """忽略表情回应事件，避免 SDK 噪声。"""
        pass

    def _on_message_read(self, data: Any) -> None:
        """忽略消息阅读事件，避免 SDK 噪声。"""
        pass

    def _on_bot_p2p_chat_entered(self, data: Any) -> None:
        """忽略用户打开机器人私聊窗口的 p2p-enter 事件。"""
        logger.debug("Bot entered p2p chat (user opened chat window)")
        pass

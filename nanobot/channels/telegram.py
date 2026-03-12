# =============================================================================
# nanobot Telegram 渠道
# 文件路径：nanobot/channels/telegram.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 TelegramChannel 类，让 nanobot 能够通过 Telegram 与用户交互。
#
# 什么是 TelegramChannel？
# --------------------
# TelegramChannel 是 nanobot 与 Telegram 平台的"适配器"：
# 1. 接收 Telegram 消息并转发到消息总线
# 2. 从消息总线接收消息并发送到 Telegram
# 3. 支持文本、图片、语音、文档等多种消息类型
# 4. 支持群聊、话题、回复等高级功能
#
# 核心技术：
# ---------
# - python-telegram-bot v20+ (基于 asyncio)
# - Long Polling (无需公网 IP)
# - Markdown → Telegram HTML 转换
# - 流式输出模拟（draft 消息）
# - 媒体群组缓冲聚合
#
# 使用示例：
# --------
# # 配置 Telegram
# {
#   "channels": {
#     "telegram": {
#       "enabled": true,
#       "token": "BOT_TOKEN",
#       "allow_from": ["*"]
#     }
#   }
# }
# =============================================================================

"""Telegram channel implementation using python-telegram-bot."""
# 使用 python-telegram-bot 实现 Telegram 渠道

from __future__ import annotations

import asyncio
import re
import time
import unicodedata

from loguru import logger
from telegram import BotCommand, ReplyParameters, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import TelegramConfig
from nanobot.utils.helpers import split_message

TELEGRAM_MAX_MESSAGE_LEN = 4000  # Telegram 消息字符上限
TELEGRAM_REPLY_CONTEXT_MAX_LEN = TELEGRAM_MAX_MESSAGE_LEN  # 回复上下文最大长度


def _strip_md(s: str) -> str:
    """
    移除 markdown 内联格式。

    用于处理表格渲染等场景，移除格式但保留文本内容。

    支持的格式：
    ----------
    - **bold** → bold
    - __bold__ → bold
    - ~~strikethrough~~ → strikethrough
    - `code` → code

    Args:
        s: 包含 markdown 的字符串

    Returns:
        str: 移除格式后的纯文本
    """
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'~~(.+?)~~', r'\1', s)
    s = re.sub(r'`([^`]+)`', r'\1', s)
    return s.strip()


def _render_table_box(table_lines: list[str]) -> str:
    """
    将 markdown 管道符表格转换为紧凑对齐文本（用于<pre>显示）。

    Telegram 不支持 markdown 表格，此函数将表格转换为
    使用空格对齐的纯文本格式，适合在 <pre> 标签中显示。

    Args:
        table_lines: 表格行列表（每行如 "| 列 1 | 列 2 |"）

    Returns:
        str: 对齐后的文本表格

    示例：
        输入：["| 姓名 | 年龄 |", "|---|---|", "| 小明 | 18 |"]
        输出：
        姓名  年龄
        ────  ────
        小明  18
    """
    def dw(s: str) -> int:
        """计算字符串显示宽度（考虑中文字符占 2 格）"""
        return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in s)

    rows: list[list[str]] = []
    has_sep = False
    for line in table_lines:
        cells = [_strip_md(c) for c in line.strip().strip('|').split('|')]
        if all(re.match(r'^:?-+:?$', c) for c in cells if c):
            has_sep = True  # 分隔行
            continue
        rows.append(cells)
    if not rows or not has_sep:
        return '\n'.join(table_lines)  # 不是有效表格，返回原文本

    ncols = max(len(r) for r in rows)
    for r in rows:
        r.extend([''] * (ncols - len(r)))
    widths = [max(dw(r[c]) for r in rows) for c in range(ncols)]

    def dr(cells: list[str]) -> str:
        """渲染一行：每个单元格右填充到列宽"""
        return '  '.join(f'{c}{" " * (w - dw(c))}' for c, w in zip(cells, widths))

    out = [dr(rows[0])]  # 表头
    out.append('  '.join('─' * w for w in widths))  # 分隔线
    for row in rows[1:]:
        out.append(dr(row))  # 数据行
    return '\n'.join(out)


def _markdown_to_telegram_html(text: str) -> str:
    """
    将 Markdown 转换为 Telegram 安全的 HTML。

    Telegram 支持有限的 HTML 标签：<b>, <i>, <u>, <s>, <code>, <pre>, <a>
    此函数将 Markdown 语法转换为对应的 HTML。

    转换规则：
    --------
    1. 代码块：```code``` → <pre><code>code</code></pre>
    2. 表格：| 列 | → 盒式绘图（通过_render_table_box）
    3. 内联代码：`code` → <code>code</code>
    4. 标题：# Title → Title
    5. 块引用：> text → text
    6. 链接：[text](url) → <a href="url">text</a>
    7. 粗体：**text** 或 __text__ → <b>text</b>
    8. 斜体：_text_ → <i>text</i>
    9. 删除线：~~text~~ → <s>text</s>
    10. 列表：- item → • item

    处理流程：
    --------
    1. 提取并保护代码块（避免其他处理影响）
    2. 转换表格为盒式绘图
    3. 提取并保护内联代码
    4. 处理标题、块引用
    5. 转义 HTML 特殊字符
    6. 处理链接、粗体、斜体、删除线
    7. 恢复内联代码和代码块

    Args:
        text: Markdown 格式文本

    Returns:
        str: Telegram HTML 格式文本
    """
    if not text:
        return ""

    # 1. 提取并保护代码块（保留内容不受其他处理影响）
    code_blocks: list[str] = []
    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)

    # 1.5. 将 markdown 表格转换为盒式绘图（复用 code_block 占位符）
    lines = text.split('\n')
    rebuilt: list[str] = []
    li = 0
    while li < len(lines):
        if re.match(r'^\s*\|.+\|', lines[li]):
            tbl: list[str] = []
            while li < len(lines) and re.match(r'^\s*\|.+\|', lines[li]):
                tbl.append(lines[li])
                li += 1
            box = _render_table_box(tbl)
            if box != '\n'.join(tbl):
                code_blocks.append(box)
                rebuilt.append(f"\x00CB{len(code_blocks) - 1}\x00")
            else:
                rebuilt.extend(tbl)
        else:
            rebuilt.append(lines[li])
            li += 1
    text = '\n'.join(rebuilt)

    # 2. 提取并保护内联代码
    inline_codes: list[str] = []
    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # 3. 标题 # Title → 仅保留标题文本
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

    # 4. 块引用 > text → 仅保留文本（在 HTML 转义之前）
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)

    # 5. 转义 HTML 特殊字符
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. 链接 [text](url) → 必须在粗体/斜体之前处理，避免嵌套问题
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # 7. 粗体 **text** 或 __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # 8. 斜体 _text_（避免匹配变量名如 some_var_name）
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)

    # 9. 删除线 ~~text~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)

    # 10. 列表 - item → • item
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)

    # 11. 恢复内联代码（带 HTML 标签）
    for i, code in enumerate(inline_codes):
        # 转义 HTML 字符
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 12. 恢复代码块（带 HTML 标签）
    for i, code in enumerate(code_blocks):
        # 转义 HTML 字符
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    return text


class TelegramChannel(BaseChannel):
    """
    使用长轮询的 Telegram 渠道实现。

    核心特性：
    --------
    1. 长轮询模式：无需公网 IP，简单可靠
    2. 多媒体支持：文本、图片、语音、文档、视频
    3. Markdown 转换：自动将 Markdown 转为 Telegram HTML
    4. 流式模拟：使用 draft 消息模拟打字机效果
    5. 媒体群组：缓冲聚合媒体群组消息
    6. 话题支持：支持 Telegram Forum 话题
    7. 回复上下文：提取回复消息内容作为上下文

    属性说明：
    --------
    name: str
        渠道名称："telegram"

    display_name: str
        显示名称："Telegram"

    BOT_COMMANDS: list[BotCommand]
        机器人命令菜单

    _app: Application | None
        python-telegram-bot 应用实例

    _chat_ids: dict[str, int]
        发送者 ID 到聊天 ID 的映射（用于回复）

    _typing_tasks: dict[str, asyncio.Task]
        正在输入的打字指示任务

    _media_group_buffers: dict[str, dict]
        媒体群组缓冲（聚合同一群组的消息）

    _message_threads: dict[tuple[str, int], int]
        话题线程 ID 缓存（用于回复）

    _bot_user_id: int | None
        机器人用户 ID（用于提及检测）

    _bot_username: str | None
        机器人用户名（用于提及检测）

    使用示例：
    --------
    >>> config = TelegramConfig(token="BOT_TOKEN", allow_from=["*"])
    >>> channel = TelegramChannel(config, message_bus)
    >>> await channel.start()  # 启动轮询
    """

    name = "telegram"
    display_name = "Telegram"

    # 注册到 Telegram 命令菜单的机器人命令
    BOT_COMMANDS = [
        BotCommand("start", "Start the bot"),
        BotCommand("new", "Start a new conversation"),
        BotCommand("stop", "Stop the current task"),
        BotCommand("help", "Show available commands"),
        BotCommand("restart", "Restart the bot"),
    ]

    def __init__(self, config: TelegramConfig, bus: MessageBus):
        """
        初始化 Telegram 渠道。

        Args:
            config: Telegram 配置对象（包含 token、allow_from 等）
            bus: 消息总线实例
        """
        super().__init__(config, bus)
        self.config: TelegramConfig = config  # Telegram 配置
        self._app: Application | None = None  # python-telegram-bot 应用
        self._chat_ids: dict[str, int] = {}  # 发送者 ID → 聊天 ID 映射
        self._typing_tasks: dict[str, asyncio.Task] = {}  # 打字指示任务
        self._media_group_buffers: dict[str, dict] = {}  # 媒体群组缓冲
        self._media_group_tasks: dict[str, asyncio.Task] = {}  # 媒体群组任务
        self._message_threads: dict[tuple[str, int], int] = {}  # 话题线程缓存
        self._bot_user_id: int | None = None  # 机器人用户 ID
        self._bot_username: str | None = None  # 机器人用户名

    def is_allowed(self, sender_id: str) -> bool:
        """
        检查发送者是否被允许（保留 Telegram 传统 id|username 匹配）。

        Telegram 的 allow_from 配置支持三种匹配方式：
        1. 用户 ID：如 "123456"
        2. 用户名：如 "username"
        3. 组合：如 "123456|username"（内部格式）

        Args:
            sender_id: 发送者 ID（格式："id" 或 "id|username"）

        Returns:
            bool: True 表示允许访问

        匹配逻辑：
        --------
        1. 先调用父类的 is_allowed() 检查基本规则
        2. 如果是 "id|username" 格式，分别检查 id 和 username
        """
        if super().is_allowed(sender_id):
            return True

        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list or "*" in allow_list:
            return False

        sender_str = str(sender_id)
        if sender_str.count("|") != 1:
            return False

        sid, username = sender_str.split("|", 1)
        if not sid.isdigit() or not username:
            return False

        return sid in allow_list or username in allow_list

    async def start(self) -> None:
        """
        启动 Telegram 机器人（长轮询模式）。

        启动流程：
        --------
        1. 检查 bot token 是否配置
        2. 创建 HTTPXRequest（增大连接池避免超时）
        3. 构建 Application 实例
        4. 注册命令处理器（/start, /new, /stop, /help, /restart）
        5. 注册消息处理器（文本、图片、语音、文档）
        6. 初始化应用并获取机器人信息
        7. 注册命令菜单
        8. 启动轮询（长期运行直到被停止）

        连接池配置：
        ---------
        - connection_pool_size: 16（默认更小）
        - pool_timeout: 5.0 秒
        - connect/read_timeout: 30.0 秒

        注意：
        ----
        这是一个长期运行的方法，会持续轮询直到 stop() 被调用。
        """
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return

        self._running = True

        # 构建应用（使用更大的连接池避免长时间运行时超时）
        req = HTTPXRequest(
            connection_pool_size=16,
            pool_timeout=5.0,
            connect_timeout=30.0,
            read_timeout=30.0,
            proxy=self.config.proxy if self.config.proxy else None,
        )
        builder = Application.builder().token(self.config.token).request(req).get_updates_request(req)
        self._app = builder.build()
        self._app.add_error_handler(self._on_error)

        # 添加命令处理器
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("new", self._forward_command))
        self._app.add_handler(CommandHandler("stop", self._forward_command))
        self._app.add_handler(CommandHandler("restart", self._forward_command))
        self._app.add_handler(CommandHandler("help", self._on_help))

        # 添加消息处理器（文本、图片、语音、文档）
        self._app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL)
                & ~filters.COMMAND,
                self._on_message
            )
        )

        logger.info("Starting Telegram bot (polling mode)...")

        # 初始化并启动轮询
        await self._app.initialize()
        await self._app.start()

        # 获取机器人信息并注册命令菜单
        bot_info = await self._app.bot.get_me()
        self._bot_user_id = getattr(bot_info, "id", None)
        self._bot_username = getattr(bot_info, "username", None)
        logger.info("Telegram bot @{} connected", bot_info.username)

        try:
            await self._app.bot.set_my_commands(self.BOT_COMMANDS)
            logger.debug("Telegram bot commands registered")
        except Exception as e:
            logger.warning("Failed to register bot commands: {}", e)

        # 开始轮询（持续运行直到被停止）
        await self._app.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True  # 启动时忽略旧消息
        )

        # 保持运行直到被停止
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """
        停止 Telegram 机器人。

        停止流程：
        --------
        1. 设置运行标志为 False
        2. 取消所有打字指示任务
        3. 取消媒体群组任务并清空缓冲
        4. 停止 updater 和应用
        5. 关闭连接
        """
        self._running = False

        # 取消所有打字指示
        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)

        # 取消媒体群组任务
        for task in self._media_group_tasks.values():
            task.cancel()
        self._media_group_tasks.clear()
        self._media_group_buffers.clear()

        if self._app:
            logger.info("Stopping Telegram bot...")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
            self._app = None

    @staticmethod
    def _get_media_type(path: str) -> str:
        """
        根据文件扩展名猜测媒体类型。

        Args:
            path: 文件路径

        Returns:
            str: 媒体类型（"photo"、"voice"、"audio" 或 "document"）

        扩展名映射：
        ---------
        - jpg, jpeg, png, gif, webp → photo
        - ogg → voice
        - mp3, m4a, wav, aac → audio
        - 其他 → document
        """
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in ("jpg", "jpeg", "png", "gif", "webp"):
            return "photo"
        if ext == "ogg":
            return "voice"
        if ext in ("mp3", "m4a", "wav", "aac"):
            return "audio"
        return "document"

    async def send(self, msg: OutboundMessage) -> None:
        """
        通过 Telegram 发送消息。

        发送流程：
        --------
        1. 检查机器人是否运行
        2. 停止打字指示（仅最终响应）
        3. 解析 chat_id
        4. 获取回复消息 ID 和话题线程 ID
        5. 发送媒体文件（如果有）
        6. 发送文本内容（分片处理超长消息）

        媒体类型支持：
        -----------
        - photo: jpg, jpeg, png, gif, webp
        - voice: ogg
        - audio: mp3, m4a, wav, aac
        - document: 其他文件

        消息分片：
        --------
        Telegram 消息限制 4000 字符，超长消息会被 split_message() 分割。

        Args:
            msg: 出站消息对象（包含 channel, chat_id, content, media 等）
        """
        if not self._app:
            logger.warning("Telegram bot not running")
            return

        # 仅最终响应停止打字指示
        if not msg.metadata.get("_progress", False):
            self._stop_typing(msg.chat_id)

        try:
            chat_id = int(msg.chat_id)
        except ValueError:
            logger.error("Invalid chat_id: {}", msg.chat_id)
            return
        reply_to_message_id = msg.metadata.get("message_id")
        message_thread_id = msg.metadata.get("message_thread_id")
        if message_thread_id is None and reply_to_message_id is not None:
            message_thread_id = self._message_threads.get((msg.chat_id, reply_to_message_id))
        thread_kwargs = {}
        if message_thread_id is not None:
            thread_kwargs["message_thread_id"] = message_thread_id

        reply_params = None
        if self.config.reply_to_message:
            if reply_to_message_id:
                reply_params = ReplyParameters(
                    message_id=reply_to_message_id,
                    allow_sending_without_reply=True
                )

        # 发送媒体文件
        for media_path in (msg.media or []):
            try:
                media_type = self._get_media_type(media_path)
                sender = {
                    "photo": self._app.bot.send_photo,
                    "voice": self._app.bot.send_voice,
                    "audio": self._app.bot.send_audio,
                }.get(media_type, self._app.bot.send_document)
                param = "photo" if media_type == "photo" else media_type if media_type in ("voice", "audio") else "document"
                with open(media_path, 'rb') as f:
                    await sender(
                        chat_id=chat_id,
                        **{param: f},
                        reply_parameters=reply_params,
                        **thread_kwargs,
                    )
            except Exception as e:
                filename = media_path.rsplit("/", 1)[-1]
                logger.error("Failed to send media {}: {}", media_path, e)
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=f"[Failed to send: {filename}]",
                    reply_parameters=reply_params,
                    **thread_kwargs,
                )

        # 发送文本内容
        if msg.content and msg.content != "[empty message]":
            is_progress = msg.metadata.get("_progress", False)

            for chunk in split_message(msg.content, TELEGRAM_MAX_MESSAGE_LEN):
                # 最终响应：模拟流式输出（draft → persist）
                if not is_progress:
                    await self._send_with_streaming(chat_id, chunk, reply_params, thread_kwargs)
                else:
                    await self._send_text(chat_id, chunk, reply_params, thread_kwargs)

    async def _send_text(
        self,
        chat_id: int,
        text: str,
        reply_params=None,
        thread_kwargs: dict | None = None,
    ) -> None:
        """
        发送纯文本消息（HTML 失败时回退到纯文本）。

        Args:
            chat_id: 聊天 ID
            text: 要发送的文本
            reply_params: 回复参数（可选）
            thread_kwargs: 话题线程参数（可选）

        处理流程：
        --------
        1. 将 Markdown 转换为 Telegram HTML
        2. 尝试发送 HTML 格式消息
        3. 如果失败，回退到纯文本发送
        """
        try:
            html = _markdown_to_telegram_html(text)
            await self._app.bot.send_message(
                chat_id=chat_id, text=html, parse_mode="HTML",
                reply_parameters=reply_params,
                **(thread_kwargs or {}),
            )
        except Exception as e:
            logger.warning("HTML parse failed, falling back to plain text: {}", e)
            try:
                await self._app.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_parameters=reply_params,
                    **(thread_kwargs or {}),
                )
            except Exception as e2:
                logger.error("Error sending Telegram message: {}", e2)

    async def _send_with_streaming(
        self,
        chat_id: int,
        text: str,
        reply_params=None,
        thread_kwargs: dict | None = None,
    ) -> None:
        """
        通过 draft 消息模拟流式输出，然后发送完整消息。

        Telegram 不支持真正的流式输出，此方法使用 draft 消息
        模拟打字机效果，让用户感觉消息正在"流式"显示。

        Args:
            chat_id: 聊天 ID
            text: 要发送的文本
            reply_params: 回复参数（可选）
            thread_kwargs: 话题线程参数（可选）

        流式模拟流程：
        -----------
        1. 生成 draft_id（基于时间戳）
        2. 分 8 个步骤发送 draft 消息（每步显示更多内容）
        3. 每次 draft 间隔 40ms
        4. 最后发送完整消息（持久化）
        """
        draft_id = int(time.time() * 1000) % (2**31)
        try:
            step = max(len(text) // 8, 40)
            for i in range(step, len(text), step):
                await self._app.bot.send_message_draft(
                    chat_id=chat_id, draft_id=draft_id, text=text[:i],
                )
                await asyncio.sleep(0.04)
            await self._app.bot.send_message_draft(
                chat_id=chat_id, draft_id=draft_id, text=text,
            )
            await asyncio.sleep(0.15)
        except Exception:
            pass
        await self._send_text(chat_id, text, reply_params, thread_kwargs)

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return

        user = update.effective_user
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! I'm nanobot.\n\n"
            "Send me a message and I'll respond!\n"
            "Type /help to see available commands."
        )

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command, bypassing ACL so all users can access it."""
        if not update.message:
            return
        await update.message.reply_text(
            "🐈 nanobot commands:\n"
            "/new — Start a new conversation\n"
            "/stop — Stop the current task\n"
            "/help — Show available commands"
        )

    @staticmethod
    def _sender_id(user) -> str:
        """Build sender_id with username for allowlist matching."""
        sid = str(user.id)
        return f"{sid}|{user.username}" if user.username else sid

    @staticmethod
    def _derive_topic_session_key(message) -> str | None:
        """Derive topic-scoped session key for non-private Telegram chats."""
        message_thread_id = getattr(message, "message_thread_id", None)
        if message.chat.type == "private" or message_thread_id is None:
            return None
        return f"telegram:{message.chat_id}:topic:{message_thread_id}"

    @staticmethod
    def _build_message_metadata(message, user) -> dict:
        """Build common Telegram inbound metadata payload."""
        reply_to = getattr(message, "reply_to_message", None)
        return {
            "message_id": message.message_id,
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "is_group": message.chat.type != "private",
            "message_thread_id": getattr(message, "message_thread_id", None),
            "is_forum": bool(getattr(message.chat, "is_forum", False)),
            "reply_to_message_id": getattr(reply_to, "message_id", None) if reply_to else None,
        }

    @staticmethod
    def _extract_reply_context(message) -> str | None:
        """Extract text from the message being replied to, if any."""
        reply = getattr(message, "reply_to_message", None)
        if not reply:
            return None
        text = getattr(reply, "text", None) or getattr(reply, "caption", None) or ""
        if len(text) > TELEGRAM_REPLY_CONTEXT_MAX_LEN:
            text = text[:TELEGRAM_REPLY_CONTEXT_MAX_LEN] + "..."
        return f"[Reply to: {text}]" if text else None

    async def _download_message_media(
        self, msg, *, add_failure_content: bool = False
    ) -> tuple[list[str], list[str]]:
        """Download media from a message (current or reply). Returns (media_paths, content_parts)."""
        media_file = None
        media_type = None
        if getattr(msg, "photo", None):
            media_file = msg.photo[-1]
            media_type = "image"
        elif getattr(msg, "voice", None):
            media_file = msg.voice
            media_type = "voice"
        elif getattr(msg, "audio", None):
            media_file = msg.audio
            media_type = "audio"
        elif getattr(msg, "document", None):
            media_file = msg.document
            media_type = "file"
        elif getattr(msg, "video", None):
            media_file = msg.video
            media_type = "video"
        elif getattr(msg, "video_note", None):
            media_file = msg.video_note
            media_type = "video"
        elif getattr(msg, "animation", None):
            media_file = msg.animation
            media_type = "animation"
        if not media_file or not self._app:
            return [], []
        try:
            file = await self._app.bot.get_file(media_file.file_id)
            ext = self._get_extension(
                media_type,
                getattr(media_file, "mime_type", None),
                getattr(media_file, "file_name", None),
            )
            media_dir = get_media_dir("telegram")
            file_path = media_dir / f"{media_file.file_id[:16]}{ext}"
            await file.download_to_drive(str(file_path))
            path_str = str(file_path)
            if media_type in ("voice", "audio"):
                transcription = await self.transcribe_audio(file_path)
                if transcription:
                    logger.info("Transcribed {}: {}...", media_type, transcription[:50])
                    return [path_str], [f"[transcription: {transcription}]"]
                return [path_str], [f"[{media_type}: {path_str}]"]
            return [path_str], [f"[{media_type}: {path_str}]"]
        except Exception as e:
            logger.warning("Failed to download message media: {}", e)
            if add_failure_content:
                return [], [f"[{media_type}: download failed]"]
            return [], []

    async def _ensure_bot_identity(self) -> tuple[int | None, str | None]:
        """Load bot identity once and reuse it for mention/reply checks."""
        if self._bot_user_id is not None or self._bot_username is not None:
            return self._bot_user_id, self._bot_username
        if not self._app:
            return None, None
        bot_info = await self._app.bot.get_me()
        self._bot_user_id = getattr(bot_info, "id", None)
        self._bot_username = getattr(bot_info, "username", None)
        return self._bot_user_id, self._bot_username

    @staticmethod
    def _has_mention_entity(
        text: str,
        entities,
        bot_username: str,
        bot_id: int | None,
    ) -> bool:
        """Check Telegram mention entities against the bot username."""
        handle = f"@{bot_username}".lower()
        for entity in entities or []:
            entity_type = getattr(entity, "type", None)
            if entity_type == "text_mention":
                user = getattr(entity, "user", None)
                if user is not None and bot_id is not None and getattr(user, "id", None) == bot_id:
                    return True
                continue
            if entity_type != "mention":
                continue
            offset = getattr(entity, "offset", None)
            length = getattr(entity, "length", None)
            if offset is None or length is None:
                continue
            if text[offset : offset + length].lower() == handle:
                return True
        return handle in text.lower()

    async def _is_group_message_for_bot(self, message) -> bool:
        """Allow group messages when policy is open, @mentioned, or replying to the bot."""
        if message.chat.type == "private" or self.config.group_policy == "open":
            return True

        bot_id, bot_username = await self._ensure_bot_identity()
        if bot_username:
            text = message.text or ""
            caption = message.caption or ""
            if self._has_mention_entity(
                text,
                getattr(message, "entities", None),
                bot_username,
                bot_id,
            ):
                return True
            if self._has_mention_entity(
                caption,
                getattr(message, "caption_entities", None),
                bot_username,
                bot_id,
            ):
                return True

        reply_user = getattr(getattr(message, "reply_to_message", None), "from_user", None)
        return bool(bot_id and reply_user and reply_user.id == bot_id)

    def _remember_thread_context(self, message) -> None:
        """Cache topic thread id by chat/message id for follow-up replies."""
        message_thread_id = getattr(message, "message_thread_id", None)
        if message_thread_id is None:
            return
        key = (str(message.chat_id), message.message_id)
        self._message_threads[key] = message_thread_id
        if len(self._message_threads) > 1000:
            self._message_threads.pop(next(iter(self._message_threads)))

    async def _forward_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Forward slash commands to the bus for unified handling in AgentLoop."""
        if not update.message or not update.effective_user:
            return
        message = update.message
        user = update.effective_user
        self._remember_thread_context(message)
        await self._handle_message(
            sender_id=self._sender_id(user),
            chat_id=str(message.chat_id),
            content=message.text or "",
            metadata=self._build_message_metadata(message, user),
            session_key=self._derive_topic_session_key(message),
        )

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id
        sender_id = self._sender_id(user)
        self._remember_thread_context(message)

        # Store chat_id for replies
        self._chat_ids[sender_id] = chat_id

        if not await self._is_group_message_for_bot(message):
            return

        # Build content from text and/or media
        content_parts = []
        media_paths = []

        # Text content
        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        # Download current message media
        current_media_paths, current_media_parts = await self._download_message_media(
            message, add_failure_content=True
        )
        media_paths.extend(current_media_paths)
        content_parts.extend(current_media_parts)
        if current_media_paths:
            logger.debug("Downloaded message media to {}", current_media_paths[0])

        # Reply context: text and/or media from the replied-to message
        reply = getattr(message, "reply_to_message", None)
        if reply is not None:
            reply_ctx = self._extract_reply_context(message)
            reply_media, reply_media_parts = await self._download_message_media(reply)
            if reply_media:
                media_paths = reply_media + media_paths
                logger.debug("Attached replied-to media: {}", reply_media[0])
            tag = reply_ctx or (f"[Reply to: {reply_media_parts[0]}]" if reply_media_parts else None)
            if tag:
                content_parts.insert(0, tag)
        content = "\n".join(content_parts) if content_parts else "[empty message]"

        logger.debug("Telegram message from {}: {}...", sender_id, content[:50])

        str_chat_id = str(chat_id)
        metadata = self._build_message_metadata(message, user)
        session_key = self._derive_topic_session_key(message)

        # Telegram media groups: buffer briefly, forward as one aggregated turn.
        if media_group_id := getattr(message, "media_group_id", None):
            key = f"{str_chat_id}:{media_group_id}"
            if key not in self._media_group_buffers:
                self._media_group_buffers[key] = {
                    "sender_id": sender_id, "chat_id": str_chat_id,
                    "contents": [], "media": [],
                    "metadata": metadata,
                    "session_key": session_key,
                }
                self._start_typing(str_chat_id)
            buf = self._media_group_buffers[key]
            if content and content != "[empty message]":
                buf["contents"].append(content)
            buf["media"].extend(media_paths)
            if key not in self._media_group_tasks:
                self._media_group_tasks[key] = asyncio.create_task(self._flush_media_group(key))
            return

        # Start typing indicator before processing
        self._start_typing(str_chat_id)

        # Forward to the message bus
        await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content=content,
            media=media_paths,
            metadata=metadata,
            session_key=session_key,
        )

    async def _flush_media_group(self, key: str) -> None:
        """Wait briefly, then forward buffered media-group as one turn."""
        try:
            await asyncio.sleep(0.6)
            if not (buf := self._media_group_buffers.pop(key, None)):
                return
            content = "\n".join(buf["contents"]) or "[empty message]"
            await self._handle_message(
                sender_id=buf["sender_id"], chat_id=buf["chat_id"],
                content=content, media=list(dict.fromkeys(buf["media"])),
                metadata=buf["metadata"],
                session_key=buf.get("session_key"),
            )
        finally:
            self._media_group_tasks.pop(key, None)

    def _start_typing(self, chat_id: str) -> None:
        """Start sending 'typing...' indicator for a chat."""
        # Cancel any existing typing task for this chat
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    def _stop_typing(self, chat_id: str) -> None:
        """Stop the typing indicator for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _typing_loop(self, chat_id: str) -> None:
        """Repeatedly send 'typing' action until cancelled."""
        try:
            while self._app:
                await self._app.bot.send_chat_action(chat_id=int(chat_id), action="typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Typing indicator stopped for {}: {}", chat_id, e)

    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log polling / handler errors instead of silently swallowing them."""
        logger.error("Telegram error: {}", context.error)

    def _get_extension(
        self,
        media_type: str,
        mime_type: str | None,
        filename: str | None = None,
    ) -> str:
        """Get file extension based on media type or original filename."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]

        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "file": ""}
        if ext := type_map.get(media_type, ""):
            return ext

        if filename:
            from pathlib import Path

            return "".join(Path(filename).suffixes)

        return ""

# =============================================================================
# nanobot Matrix (Element) 渠道
# 文件路径：nanobot/channels/matrix.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 MatrixChannel 类，让 nanobot 能够通过 Matrix 协议与用户交互。
#
# 什么是 MatrixChannel？
# --------------------
# MatrixChannel 是 nanobot 与 Matrix 网络的"适配器"：
# 1. 使用 nio 异步 SDK 连接 Matrix 服务器
# 2. 支持端到端加密（E2EE）
# 3. 支持长轮询同步接收消息
# 4. 支持媒体文件上传下载
# 5. 支持 Markdown 转 HTML 格式化
#
# 为什么需要 Matrix 渠道？
# ----------------------
# 1. 去中心化：Matrix 是开放的去中心化通信协议
# 2. 数据主权：可自建服务器，完全控制数据
# 3. 端到端加密：原生支持 E2EE，保障隐私
# 4. 跨平台互通：可与 Element、FluffyChat 等客户端互通
# 5. 企业私有部署：适合对数据隐私要求高的场景
#
# 工作原理：
# ---------
# 入站（接收消息）：
# 1. 使用 AsyncClient 建立与 homeserver 的连接
# 2. 启动 sync_forever 长轮询循环
# 3. 监听 RoomMessageText（文本消息）
# 4. 监听 RoomMessageMedia/RoomEncryptedMedia（媒体消息）
# 5. 监听 InviteEvent（房间邀请，自动加入）
# 6. 下载并解密媒体附件（如启用 E2EE）
# 7. 发送 typing 指示器
# 8. 将消息发布到消息总线
#
# 出站（发送消息）：
# 1. 从消息总线获取 OutboundMessage
# 2. 将 Markdown 转换为 HTML（使用 mistune）
# 3. 使用 nh3 清理 HTML（安全过滤）
# 4. 调用 room_send 发送消息
# 5. 上传媒体文件并发送
# 6. 支持线程回复（m.thread）
#
# 配置示例：
# --------
# {
#   "channels": {
#     "matrix": {
#       "enabled": true,
#       "homeserver": "https://matrix.org",
#       "userId": "@nanobot:matrix.org",
#       "accessToken": "your-access-token",
#       "deviceId": "nanobot-device",
#       "e2eeEnabled": true,
#       "groupPolicy": "mention",
#       "maxMediaBytes": 10485760
#     }
#   }
# }
#
# 依赖安装：
# --------
# pip install nanobot-ai[matrix]
#
# 注意事项：
# --------
# 1. 需要 Matrix 账户和 access token
# 2. E2EE 需要正确配置 device ID 和 store path
# 3. 媒体文件存储在本地的 media/matrix 目录
# 4. 支持的政策模式：open、mention、allowlist
# =============================================================================

"""Matrix (Element) channel — inbound sync + outbound message/media delivery."""
# Matrix（Element）渠道：入站同步 + 出站消息/媒体投递

import asyncio
import logging
import mimetypes
from pathlib import Path
from typing import Any, TypeAlias

from loguru import logger

try:
    import nh3
    from mistune import create_markdown
    from nio import (
        AsyncClient,
        AsyncClientConfig,
        ContentRepositoryConfigError,
        DownloadError,
        InviteEvent,
        JoinError,
        MatrixRoom,
        MemoryDownloadResponse,
        RoomEncryptedMedia,
        RoomMessage,
        RoomMessageMedia,
        RoomMessageText,
        RoomSendError,
        RoomTypingError,
        SyncError,
        UploadError,
    )
    from nio.crypto.attachments import decrypt_attachment
    from nio.exceptions import EncryptionError
except ImportError as e:
    raise ImportError(
        "Matrix dependencies not installed. Run: pip install nanobot-ai[matrix]"
    ) from e

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_data_dir, get_media_dir
from nanobot.utils.helpers import safe_filename

# Typing 指示器超时时间（毫秒）
TYPING_NOTICE_TIMEOUT_MS = 30_000
# 必须低于 TYPING_NOTICE_TIMEOUT_MS，防止指示器在处理过程中过期
TYPING_KEEPALIVE_INTERVAL_MS = 20_000
# Matrix HTML 格式标识符
MATRIX_HTML_FORMAT = "org.matrix.custom.html"
# 附件标记占位符
_ATTACH_MARKER = "[attachment: {}]"
_ATTACH_TOO_LARGE = "[attachment: {} - too large]"
_ATTACH_FAILED = "[attachment: {} - download failed]"
_ATTACH_UPLOAD_FAILED = "[attachment: {} - upload failed]"
_DEFAULT_ATTACH_NAME = "attachment"
# 消息类型映射
_MSGTYPE_MAP = {"m.image": "image", "m.audio": "audio", "m.video": "video", "m.file": "file"}

# Matrix 媒体事件类型过滤器
MATRIX_MEDIA_EVENT_FILTER = (RoomMessageMedia, RoomEncryptedMedia)
MatrixMediaEvent: TypeAlias = RoomMessageMedia | RoomEncryptedMedia

# 创建 Markdown 渲染器，支持表格、删除线、链接等插件
MATRIX_MARKDOWN = create_markdown(
    escape=True,
    plugins=["table", "strikethrough", "url", "superscript", "subscript"],
)

# Matrix 允许的 HTML 标签白名单
MATRIX_ALLOWED_HTML_TAGS = {
    "p", "a", "strong", "em", "del", "code", "pre", "blockquote",
    "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "br", "table", "thead", "tbody", "tr", "th", "td",
    "caption", "sup", "sub", "img",
}
# Matrix 允许的 HTML 属性白名单
MATRIX_ALLOWED_HTML_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href"}, "code": {"class"}, "ol": {"start"},
    "img": {"src", "alt", "title", "width", "height"},
}
# Matrix 允许的 URL 协议白名单
MATRIX_ALLOWED_URL_SCHEMES = {"https", "http", "matrix", "mailto", "mxc"}


def _filter_matrix_html_attribute(tag: str, attr: str, value: str) -> str | None:
    """
    过滤属性值为 Matrix 兼容的安全子集。

    Args:
        tag: HTML 标签名
        attr: 属性名
        value: 属性值

    Returns:
        过滤后的属性值，或 None 表示移除该属性
    """
    if tag == "a" and attr == "href":
        return value if value.lower().startswith(("https://", "http://", "matrix:", "mailto:")) else None
    if tag == "img" and attr == "src":
        return value if value.lower().startswith("mxc://") else None
    if tag == "code" and attr == "class":
        classes = [c for c in value.split() if c.startswith("language-") and not c.startswith("language-_")]
        return " ".join(classes) if classes else None
    return value


# Matrix HTML 清理器，使用 nh3 进行安全过滤
MATRIX_HTML_CLEANER = nh3.Cleaner(
    tags=MATRIX_ALLOWED_HTML_TAGS,
    attributes=MATRIX_ALLOWED_HTML_ATTRIBUTES,
    attribute_filter=_filter_matrix_html_attribute,
    url_schemes=MATRIX_ALLOWED_URL_SCHEMES,
    strip_comments=True,
    link_rel="noopener noreferrer",
)


def _render_markdown_html(text: str) -> str | None:
    """
    将 Markdown 渲染为经过 sanitization 的 HTML；纯文本返回 None。

    Args:
        text: Markdown 格式文本

    Returns:
        清理后的 HTML 字符串，或 None 表示不需要格式化
    """
    try:
        formatted = MATRIX_HTML_CLEANER.clean(MATRIX_MARKDOWN(text)).strip()
    except Exception:
        return None
    if not formatted:
        return None
    # 为保持负载最小，纯 <p>text</p> 跳过 formatted_body
    if formatted.startswith("<p>") and formatted.endswith("</p>"):
        inner = formatted[3:-4]
        if "<" not in inner and ">" not in inner:
            return None
    return formatted


def _build_matrix_text_content(text: str) -> dict[str, object]:
    """
    构建 Matrix m.text 消息负载，包含可选的 HTML formatted_body。

    Args:
        text: 消息文本

    Returns:
        Matrix 消息内容字典
    """
    content: dict[str, object] = {"msgtype": "m.text", "body": text, "m.mentions": {}}
    if html := _render_markdown_html(text):
        content["format"] = MATRIX_HTML_FORMAT
        content["formatted_body"] = html
    return content


class _NioLoguruHandler(logging.Handler):
    """
    将 matrix-nio 的 stdlib 日志路由到 Loguru。

    此处理器捕获 nio 库的日志记录，并将其重定向到 Loguru，
    以保持日志输出的一致性。
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame, depth = frame.f_back, depth + 1
        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _configure_nio_logging_bridge() -> None:
    """
    桥接 matrix-nio 日志到 Loguru（幂等操作）。

    如果尚未配置，则添加 _NioLoguruHandler 到 nio  logger。
    """
    nio_logger = logging.getLogger("nio")
    if not any(isinstance(h, _NioLoguruHandler) for h in nio_logger.handlers):
        nio_logger.handlers = [_NioLoguruHandler()]
        nio_logger.propagate = False


class MatrixChannel(BaseChannel):
    """
    使用长轮询同步的 Matrix（Element）渠道。

    支持的功能：
    - 文本消息（支持 Markdown 转 HTML）
    - 媒体消息（图片、音频、视频、文件）
    - 端到端加密（E2EE）
    - 线程回复（m.thread）
    - Typing 指示器
    - 自动加入房间邀请
    - 群聊政策控制（open、mention、allowlist）

    安全特性：
    - HTML 标签白名单过滤（使用 nh3）
    - URL 协议白名单检查
    - 工作空间路径限制（防止任意文件上传）
    - 媒体大小限制
    """

    name = "matrix"
    display_name = "Matrix"

    def __init__(self, config: Any, bus: MessageBus):
        """
        初始化 Matrix 渠道。

        Args:
            config: Matrix 配置对象（包含 homeserver、user_id、access_token 等）
            bus: 消息总线实例
        """
        super().__init__(config, bus)
        self.client: AsyncClient | None = None
        self._sync_task: asyncio.Task | None = None
        self._typing_tasks: dict[str, asyncio.Task] = {}
        self._restrict_to_workspace = False
        self._workspace: Path | None = None
        self._server_upload_limit_bytes: int | None = None
        self._server_upload_limit_checked = False

    async def start(self) -> None:
        """
        启动 Matrix 客户端并开始同步循环。

        启动流程：
        1. 配置 nio 日志桥接到 Loguru
        2. 创建数据存储目录（用于 E2EE 状态）
        3. 创建 AsyncClient 实例
        4. 注册事件回调和处理函数
        5. 加载 E2EE 状态（如果启用）
        6. 启动同步任务
        """
        self._running = True
        _configure_nio_logging_bridge()

        store_path = get_data_dir() / "matrix-store"
        store_path.mkdir(parents=True, exist_ok=True)

        self.client = AsyncClient(
            homeserver=self.config.homeserver, user=self.config.user_id,
            store_path=store_path,
            config=AsyncClientConfig(store_sync_tokens=True, encryption_enabled=self.config.e2ee_enabled),
        )
        self.client.user_id = self.config.user_id
        self.client.access_token = self.config.access_token
        self.client.device_id = self.config.device_id

        self._register_event_callbacks()
        self._register_response_callbacks()

        if not self.config.e2ee_enabled:
            logger.warning("Matrix E2EE disabled; encrypted rooms may be undecryptable.")

        if self.config.device_id:
            try:
                self.client.load_store()
            except Exception:
                logger.exception("Matrix store load failed; restart may replay recent messages.")
        else:
            logger.warning("Matrix device_id empty; restart may replay recent messages.")

        self._sync_task = asyncio.create_task(self._sync_loop())

    async def stop(self) -> None:
        """
        停止 Matrix 渠道，优雅关闭同步。

        停止流程：
        1. 停止所有 typing 保持活跃任务
        2. 停止客户端同步
        3. 等待同步任务完成（带超时）
        4. 关闭客户端连接
        """
        self._running = False
        for room_id in list(self._typing_tasks):
            await self._stop_typing_keepalive(room_id, clear_typing=False)
        if self.client:
            self.client.stop_sync_forever()
        if self._sync_task:
            try:
                await asyncio.wait_for(asyncio.shield(self._sync_task),
                                       timeout=self.config.sync_stop_grace_seconds)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._sync_task.cancel()
                try:
                    await self._sync_task
                except asyncio.CancelledError:
                    pass
        if self.client:
            await self.client.close()

    def _is_workspace_path_allowed(self, path: Path) -> bool:
        """
        检查路径是否在工作空间允许范围内。

        当启用工作空间限制时，此方法确保文件上传操作只能访问
        工作空间目录内的文件，防止任意文件读取攻击。

        Args:
            path: 待检查的文件路径

        Returns:
            bool: 如果路径在工作空间内返回 True，否则返回 False

        安全特性：
        - 使用 resolve() 解析绝对路径
        - 使用 relative_to() 检查路径关系
        - 异常处理：路径不存在时不抛出异常（strict=False）
        """
        if not self._restrict_to_workspace or not self._workspace:
            return True
        try:
            path.resolve(strict=False).relative_to(self._workspace)
            return True
        except ValueError:
            return False

    def _collect_outbound_media_candidates(self, media: list[str]) -> list[Path]:
        """
        收集并去重出站媒体附件路径。

        此方法处理出站消息中的媒体引用列表，进行以下处理：
        1. 过滤非字符串和空值
        2. 解析路径（展开 ~ 为用户主目录）
        3. 去重（基于解析后的路径字符串）

        Args:
            media: 媒体引用列表（文件路径字符串）

        Returns:
            list[Path]: 去重后的 Path 对象列表

        处理细节：
        - 使用 expanduser() 展开 ~ 符号
        - 使用 resolve() 解析绝对路径
        - 异常处理：路径不存在时不抛出异常（strict=False）
        """
        seen: set[str] = set()
        candidates: list[Path] = []
        for raw in media:
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = Path(raw.strip()).expanduser()
            try:
                key = str(path.resolve(strict=False))
            except OSError:
                key = str(path)
            if key not in seen:
                seen.add(key)
                candidates.append(path)
        return candidates

    @staticmethod
    def _build_outbound_attachment_content(
        *, filename: str, mime: str, size_bytes: int,
        mxc_url: str, encryption_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        构建 Matrix 媒体消息内容负载。

        此方法根据上传后的媒体信息构建 Matrix 消息内容，支持：
        - 图片（m.image）
        - 音频（m.audio）
        - 视频（m.video）
        - 通用文件（m.file）

        Args:
            filename: 文件名（带扩展名）
            mime: MIME 类型（如 image/jpeg）
            size_bytes: 文件大小（字节）
            mxc_url: Matrix 媒体 URL（mxc:// 格式）
            encryption_info: 加密信息（E2EE 房间需要）

        Returns:
            dict[str, Any]: Matrix 消息内容字典，包含：
                - msgtype: 消息类型
                - body: 消息正文（文件名）
                - filename: 文件名
                - info: 媒体信息（MIME、大小）
                - m.mentions: 提及信息（空对象）
                - url/file: 媒体 URL（加密房间使用 file 字段）

        E2EE 处理：
        - 非加密房间：使用 url 字段存储 mxc://
        - 加密房间：使用 file 字段存储加密信息和 URL
        """
        prefix = mime.split("/")[0]
        msgtype = {"image": "m.image", "audio": "m.audio", "video": "m.video"}.get(prefix, "m.file")
        content: dict[str, Any] = {
            "msgtype": msgtype, "body": filename, "filename": filename,
            "info": {"mimetype": mime, "size": size_bytes}, "m.mentions": {},
        }
        if encryption_info:
            content["file"] = {**encryption_info, "url": mxc_url}
        else:
            content["url"] = mxc_url
        return content

    def _is_encrypted_room(self, room_id: str) -> bool:
        """
        检查房间是否启用了端到端加密。

        Args:
            room_id: 房间 ID

        Returns:
            bool: 如果房间已加密返回 True，否则返回 False

        用途：
        - 决定上传媒体时是否需要加密
        - 决定发送消息时是否使用加密参数
        """
        if not self.client:
            return False
        room = getattr(self.client, "rooms", {}).get(room_id)
        return bool(getattr(room, "encrypted", False))

    async def _send_room_content(self, room_id: str, content: dict[str, Any]) -> None:
        """
        发送 Matrix 房间消息（支持端到端加密）。

        此方法封装了 room_send 调用，根据配置自动处理加密：
        - 启用 E2EE 时：自动加密消息内容
        - 忽略未验证设备：确保消息能够发送到加密房间

        Args:
            room_id: 房间 ID
            content: 消息内容字典（msgtype、body 等）

        加密处理：
        - ignore_unverified_devices: True（允许发送到未验证设备）
        - 消息类型：m.room.message
        """
        if not self.client:
            return
        kwargs: dict[str, Any] = {"room_id": room_id, "message_type": "m.room.message", "content": content}
        if self.config.e2ee_enabled:
            kwargs["ignore_unverified_devices"] = True
        await self.client.room_send(**kwargs)

    async def _resolve_server_upload_limit_bytes(self) -> int | None:
        """
        查询 Matrix 主服务器的上传大小限制。

        此方法在渠道生命周期内只调用一次（缓存结果），
        通过 content_repository_config API 获取服务器配置。

        Returns:
            int | None: 上传大小限制（字节），失败返回 None

        缓存机制：
        - 使用 _server_upload_limit_checked 标志避免重复查询
        - 查询结果保存在 _server_upload_limit_bytes

        异常处理：
        - API 调用失败：返回 None
        - 响应解析失败：返回 None
        """
        if self._server_upload_limit_checked:
            return self._server_upload_limit_bytes
        self._server_upload_limit_checked = True
        if not self.client:
            return None
        try:
            response = await self.client.content_repository_config()
        except Exception:
            return None
        upload_size = getattr(response, "upload_size", None)
        if isinstance(upload_size, int) and upload_size > 0:
            self._server_upload_limit_bytes = upload_size
            return upload_size
        return None

    async def _effective_media_limit_bytes(self) -> int:
        """
        计算有效的媒体大小限制（取本地配置和服务器限制的最小值）。

        限制计算规则：
        1. 获取本地配置限制（max_media_bytes）
        2. 获取服务器限制（通过 API 查询）
        3. 返回两者的较小值
        4. 如果服务器限制不可用，返回本地限制
        5. 如果本地限制为 0，返回 0（禁止所有上传）

        Returns:
            int: 有效的媒体大小限制（字节）

        用途：
        - 上传媒体前检查文件大小是否超限
        - 确保不超出服务器允许的上传限制
        """
        local_limit = max(int(self.config.max_media_bytes), 0)
        server_limit = await self._resolve_server_upload_limit_bytes()
        if server_limit is None:
            return local_limit
        return min(local_limit, server_limit) if local_limit else 0

    async def _upload_and_send_attachment(
        self, room_id: str, path: Path, limit_bytes: int,
        relates_to: dict[str, Any] | None = None,
    ) -> str | None:
        """
        上传本地文件到 Matrix 服务器并发送为媒体消息。

        此方法处理单个媒体文件的上传和发送流程：
        1. 解析并验证文件路径
        2. 检查工作空间权限（如果启用限制）
        3. 检查文件大小是否超限
        4. 检测 MIME 类型
        5. 上传文件到服务器（E2EE 房间自动加密）
        6. 构建媒体消息内容
        7. 发送消息到房间

        Args:
            room_id: 房间 ID
            path: 本地文件路径
            limit_bytes: 上传大小限制（字节）
            relates_to: 线程关系信息（用于回复/线程）

        Returns:
            str | None: 失败时返回错误标记字符串，成功返回 None

        错误标记：
        - 文件过大：[attachment: filename - too large]
        - 上传失败：[attachment: filename - upload failed]
        - 路径不允许：[attachment: filename - upload failed]

        E2EE 处理：
        - 加密房间：自动加密上传内容
        - 非加密房间：直接上传原始内容
        """
        if not self.client:
            return _ATTACH_UPLOAD_FAILED.format(path.name or _DEFAULT_ATTACH_NAME)

        resolved = path.expanduser().resolve(strict=False)
        filename = safe_filename(resolved.name) or _DEFAULT_ATTACH_NAME
        fail = _ATTACH_UPLOAD_FAILED.format(filename)

        if not resolved.is_file() or not self._is_workspace_path_allowed(resolved):
            return fail
        try:
            size_bytes = resolved.stat().st_size
        except OSError:
            return fail
        if limit_bytes <= 0 or size_bytes > limit_bytes:
            return _ATTACH_TOO_LARGE.format(filename)

        mime = mimetypes.guess_type(filename, strict=False)[0] or "application/octet-stream"
        try:
            with resolved.open("rb") as f:
                upload_result = await self.client.upload(
                    f, content_type=mime, filename=filename,
                    encrypt=self.config.e2ee_enabled and self._is_encrypted_room(room_id),
                    filesize=size_bytes,
                )
        except Exception:
            return fail

        upload_response = upload_result[0] if isinstance(upload_result, tuple) else upload_result
        encryption_info = upload_result[1] if isinstance(upload_result, tuple) and isinstance(upload_result[1], dict) else None
        if isinstance(upload_response, UploadError):
            return fail
        mxc_url = getattr(upload_response, "content_uri", None)
        if not isinstance(mxc_url, str) or not mxc_url.startswith("mxc://"):
            return fail

        content = self._build_outbound_attachment_content(
            filename=filename, mime=mime, size_bytes=size_bytes,
            mxc_url=mxc_url, encryption_info=encryption_info,
        )
        if relates_to:
            content["m.relates_to"] = relates_to
        try:
            await self._send_room_content(room_id, content)
        except Exception:
            return fail
        return None

    async def send(self, msg: OutboundMessage) -> None:
        """
        发送出站消息（文本和/或媒体）。

        此方法处理发送到 Matrix 房间的消息，支持：
        1. 文本消息（Markdown 转 HTML）
        2. 媒体附件（图片、音频、视频、文件）
        3. 线程回复（m.thread）
        4. 进度消息（保持 typing 指示器）

        Args:
            msg: 出站消息对象，包含：
                - chat_id: 房间 ID
                - content: 消息文本内容
                - media: 媒体文件路径列表
                - metadata: 元数据（包含线程信息）

        发送流程：
        1. 收集并去重媒体路径
        2. 构建线程关系（如果有）
        3. 上传并发送每个媒体文件
        4. 收集失败标记并附加到文本
        5. 发送文本消息（带 HTML 格式化）
        6. 清除 typing 指示器（非进度消息）

        失败处理：
        - 媒体上传失败：添加可见错误标记到消息
        - 多个失败：每个失败单独一行显示
        """
        if not self.client:
            return
        text = msg.content or ""
        candidates = self._collect_outbound_media_candidates(msg.media)
        relates_to = self._build_thread_relates_to(msg.metadata)
        is_progress = bool((msg.metadata or {}).get("_progress"))
        try:
            failures: list[str] = []
            if candidates:
                limit_bytes = await self._effective_media_limit_bytes()
                for path in candidates:
                    if fail := await self._upload_and_send_attachment(
                        room_id=msg.chat_id,
                        path=path,
                        limit_bytes=limit_bytes,
                        relates_to=relates_to,
                    ):
                        failures.append(fail)
            if failures:
                text = f"{text.rstrip()}\n{chr(10).join(failures)}" if text.strip() else "\n".join(failures)
            if text or not candidates:
                content = _build_matrix_text_content(text)
                if relates_to:
                    content["m.relates_to"] = relates_to
                await self._send_room_content(msg.chat_id, content)
        finally:
            if not is_progress:
                await self._stop_typing_keepalive(msg.chat_id, clear_typing=True)

    def _register_event_callbacks(self) -> None:
        """
        注册 Matrix 事件回调处理器。

        注册以下事件回调：
        1. RoomMessageText: 文本消息处理
        2. RoomMessageMedia/RoomEncryptedMedia: 媒体消息处理
        3. InviteEvent: 房间邀请处理（自动加入）

        用途：
        - 将 Matrix 事件路由到对应的处理方法
        - 在客户端启动前完成注册
        """
        self.client.add_event_callback(self._on_message, RoomMessageText)
        self.client.add_event_callback(self._on_media_message, MATRIX_MEDIA_EVENT_FILTER)
        self.client.add_event_callback(self._on_room_invite, InviteEvent)

    def _register_response_callbacks(self) -> None:
        """
        注册 Matrix 响应错误回调处理器。

        注册以下错误回调：
        1. SyncError: 同步错误处理
        2. JoinError: 加入房间错误处理
        3. RoomSendError: 发送消息错误处理

        用途：
        - 捕获并记录 API 响应错误
        - 统一错误日志格式
        """
        self.client.add_response_callback(self._on_sync_error, SyncError)
        self.client.add_response_callback(self._on_join_error, JoinError)
        self.client.add_response_callback(self._on_send_error, RoomSendError)

    def _log_response_error(self, label: str, response: Any) -> None:
        """
        记录 Matrix 响应错误日志。

        根据错误类型使用不同的日志级别：
        - 认证错误（ERROR 级别）：M_UNKNOWN_TOKEN、M_FORBIDDEN、M_UNAUTHORIZED
        - 其他错误（WARNING 级别）：一般性错误

        Args:
            label: 操作标签（如 "sync"、"join"、"send"）
            response: 错误响应对象

        致命错误检测：
        - status_code 为认证相关错误码
        - soft_logout 为 True（表示会话失效）
        """
        code = getattr(response, "status_code", None)
        is_auth = code in {"M_UNKNOWN_TOKEN", "M_FORBIDDEN", "M_UNAUTHORIZED"}
        is_fatal = is_auth or getattr(response, "soft_logout", False)
        (logger.error if is_fatal else logger.warning)("Matrix {} failed: {}", label, response)

    async def _on_sync_error(self, response: SyncError) -> None:
        self._log_response_error("sync", response)

    async def _on_join_error(self, response: JoinError) -> None:
        self._log_response_error("join", response)

    async def _on_send_error(self, response: RoomSendError) -> None:
        self._log_response_error("send", response)

    async def _set_typing(self, room_id: str, typing: bool) -> None:
        """
        设置房间的 typing 指示器状态（尽力而为）。

        Typing 指示器告诉其他用户当前是否正在输入消息。
        此方法失败时不抛出异常，仅记录调试日志。

        Args:
            room_id: 房间 ID
            typing: True 表示正在输入，False 表示停止输入

        超时设置：
        - TYPING_NOTICE_TIMEOUT_MS: 30 秒（Matrix 协议标准值）

        异常处理：
        - RoomTypingError: 记录调试日志
        - 其他异常：静默忽略
        """
        if not self.client:
            return
        try:
            response = await self.client.room_typing(room_id=room_id, typing_state=typing,
                                                     timeout=TYPING_NOTICE_TIMEOUT_MS)
            if isinstance(response, RoomTypingError):
                logger.debug("Matrix typing failed for {}: {}", room_id, response)
        except Exception:
            pass

    async def _start_typing_keepalive(self, room_id: str) -> None:
        """
        启动周期性 typing 指示器刷新（保活机制）。

        Matrix 协议规定 typing 指示器会在超时后自动过期，
        此方法启动一个后台任务，定期刷新 typing 状态以保持指示器活跃。

        Args:
            room_id: 房间 ID

        刷新机制：
        1. 停止现有的刷新任务（如果有）
        2. 设置 typing 状态为 True
        3. 启动循环任务，每 20 秒刷新一次
        4. 任务引用保存在 _typing_tasks 字典

        超时配置：
        - TYPING_KEEPALIVE_INTERVAL_MS: 20 秒（低于 30 秒超时）
        - TYPING_NOTICE_TIMEOUT_MS: 30 秒（Matrix 协议标准）

        任务清理：
        - 使用 CancelledError 捕获取消事件
        - 停止运行时自动退出循环
        """
        await self._stop_typing_keepalive(room_id, clear_typing=False)
        await self._set_typing(room_id, True)
        if not self._running:
            return

        async def loop() -> None:
            try:
                while self._running:
                    await asyncio.sleep(TYPING_KEEPALIVE_INTERVAL_MS / 1000)
                    await self._set_typing(room_id, True)
            except asyncio.CancelledError:
                pass

        self._typing_tasks[room_id] = asyncio.create_task(loop())

    async def _stop_typing_keepalive(self, room_id: str, *, clear_typing: bool) -> None:
        """
        停止 typing 指示器刷新任务。

        此方法停止并清理指定房间的 typing 保活任务，
        可选择是否发送 clear_typing=False 信号停止输入状态。

        Args:
            room_id: 房间 ID
            clear_typing: 是否发送停止输入信号
                - True: 取消任务并设置 typing=False
                - False: 仅取消任务，不更新状态

        清理流程：
        1. 从字典中移除任务引用
        2. 取消任务（如果存在）
        3. 等待任务完成（捕获 CancelledError）
        4. 可选：发送 typing=False 状态更新
        """
        if task := self._typing_tasks.pop(room_id, None):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if clear_typing:
            await self._set_typing(room_id, False)

    async def _sync_loop(self) -> None:
        """
        Matrix 同步循环（长轮询）。

        此方法运行主要的同步循环，使用 sync_forever 进行长轮询：
        - 接收房间消息、状态更新等事件
        - 触发注册的事件回调
        - 自动处理断线重连（异常后休眠 2 秒）

        退出条件：
        - _running 标志设置为 False
        - 捕获 CancelledError 异常
        """
        while self._running:
            try:
                await self.client.sync_forever(timeout=30000, full_state=True)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(2)

    async def _on_room_invite(self, room: MatrixRoom, event: InviteEvent) -> None:
        """
        处理房间邀请事件。

        当收到房间邀请时，检查发送者是否在允许列表中，
        如果允许则自动加入房间。

        Args:
            room: Matrix 房间对象
            event: 邀请事件对象

        权限检查：
        - 使用 is_allowed() 检查发送者是否在 allow_from 列表中
        - 允许列表包含 "*" 时表示允许所有用户
        """
        if self.is_allowed(event.sender):
            await self.client.join(room.room_id)

    def _is_direct_room(self, room: MatrixRoom) -> bool:
        """
        检查是否为单聊房间（1:1 私聊）。

        Args:
            room: Matrix 房间对象

        Returns:
            bool: 如果房间成员数 <= 2 返回 True（私聊）

        用途：
        - 私聊房间：始终响应（无需@提及）
        - 群聊房间：根据 group_policy 配置决定是否响应
        """
        count = getattr(room, "member_count", None)
        return isinstance(count, int) and count <= 2

    def _is_bot_mentioned(self, event: RoomMessage) -> bool:
        """
        检查消息是否提及了机器人。

        此方法检查消息的 m.mentions 字段，判断是否：
        1. 明确提及了机器人用户 ID
        2. 提及了整个房间（@channel/@here，如果配置允许）

        Args:
            event: Matrix 消息事件对象

        Returns:
            bool: 如果提及机器人返回 True，否则返回 False

        检查逻辑：
        - 从 event.source 获取原始消息内容
        - 检查 m.mentions.user_ids 是否包含机器人 ID
        - 检查 m.mentions.room 是否为 True（房间提及）
        """
        source = getattr(event, "source", None)
        if not isinstance(source, dict):
            return False
        mentions = (source.get("content") or {}).get("m.mentions")
        if not isinstance(mentions, dict):
            return False
        user_ids = mentions.get("user_ids")
        if isinstance(user_ids, list) and self.config.user_id in user_ids:
            return True
        return bool(self.config.allow_room_mentions and mentions.get("room") is True)

    def _should_process_message(self, room: MatrixRoom, event: RoomMessage) -> bool:
        """
        应用发送者和房间政策检查，决定是否处理消息。

        此方法实现完整的消息过滤逻辑：
        1. 首先检查发送者是否在允许列表中
        2. 如果是私聊房间，直接返回 True
        3. 根据群聊政策（group_policy）决定：
           - open: 处理所有群聊消息
           - allowlist: 只处理白名单房间的消息
           - mention: 只处理提及机器人的消息

        Args:
            room: Matrix 房间对象
            event: Matrix 消息事件对象

        Returns:
            bool: 如果应该处理消息返回 True，否则返回 False

        政策模式：
        - open: 开放模式，响应所有消息
        - allowlist: 白名单模式，只响应指定房间
        - mention: 提及模式，需要@机器人
        """
        if not self.is_allowed(event.sender):
            return False
        if self._is_direct_room(room):
            return True
        policy = self.config.group_policy
        if policy == "open":
            return True
        if policy == "allowlist":
            return room.room_id in (self.config.group_allow_from or [])
        if policy == "mention":
            return self._is_bot_mentioned(event)
        return False

    def _media_dir(self) -> Path:
        """
        获取 Matrix 媒体文件存储目录。

        Returns:
            Path: 媒体目录路径（media/matrix）

        用途：
        - 存储下载的媒体附件
        - 按平台分类存储（避免与其他渠道冲突）
        """
        return get_media_dir("matrix")

    @staticmethod
    def _event_source_content(event: RoomMessage) -> dict[str, Any]:
        """
        从 Matrix 事件中提取 source.content 字段。

        Args:
            event: Matrix 消息事件对象

        Returns:
            dict[str, Any]: 内容字典，如果不存在返回空字典

        用途：
        - 提取 m.mentions（提及信息）
        - 提取 msgtype（消息类型）
        - 提取 info（媒体信息）
        - 提取 m.relates_to（线程关系）
        """
        source = getattr(event, "source", None)
        if not isinstance(source, dict):
            return {}
        content = source.get("content")
        return content if isinstance(content, dict) else {}

    def _event_thread_root_id(self, event: RoomMessage) -> str | None:
        """
        从事件中提取线程根事件 ID。

        Args:
            event: Matrix 消息事件对象

        Returns:
            str | None: 线程根事件 ID，如果不是线程消息返回 None

        检查逻辑：
        - 从 m.relates_to 获取线程信息
        - 检查 rel_type 是否为 "m.thread"
        - 返回 event_id 作为根事件 ID
        """
        relates_to = self._event_source_content(event).get("m.relates_to")
        if not isinstance(relates_to, dict) or relates_to.get("rel_type") != "m.thread":
            return None
        root_id = relates_to.get("event_id")
        return root_id if isinstance(root_id, str) and root_id else None

    def _thread_metadata(self, event: RoomMessage) -> dict[str, str] | None:
        """
        从事件中提取线程元数据。

        Args:
            event: Matrix 消息事件对象

        Returns:
            dict[str, str] | None: 线程元数据字典，包含：
                - thread_root_event_id: 线程根事件 ID
                - thread_reply_to_event_id: 回复的目标事件 ID（可选）

        用途：
        - 保存线程关系用于后续回复
        - 在线程中保持对话上下文
        """
        if not (root_id := self._event_thread_root_id(event)):
            return None
        meta: dict[str, str] = {"thread_root_event_id": root_id}
        if isinstance(reply_to := getattr(event, "event_id", None), str) and reply_to:
            meta["thread_reply_to_event_id"] = reply_to
        return meta

    @staticmethod
    def _build_thread_relates_to(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
        """
        根据元数据构建线程关系对象（用于发送回复）。

        Args:
            metadata: 元数据字典（包含线程信息）

        Returns:
            dict[str, Any] | None: 线程关系对象，包含：
                - rel_type: "m.thread"
                - event_id: 线程根事件 ID
                - m.in_reply_to: 回复的目标事件
                - is_falling_back: True（回退显示）
                如果不是有效线程返回 None

        Matrix 线程协议：
        - rel_type: 关系类型为 "m.thread"
        - event_id: 指向线程根事件
        - m.in_reply_to: 指向直接回复的目标
        """
        if not metadata:
            return None
        root_id = metadata.get("thread_root_event_id")
        if not isinstance(root_id, str) or not root_id:
            return None
        reply_to = metadata.get("thread_reply_to_event_id") or metadata.get("event_id")
        if not isinstance(reply_to, str) or not reply_to:
            return None
        return {"rel_type": "m.thread", "event_id": root_id,
                "m.in_reply_to": {"event_id": reply_to}, "is_falling_back": True}

    def _event_attachment_type(self, event: MatrixMediaEvent) -> str:
        """
        从媒体事件中提取附件类型。

        Args:
            event: Matrix 媒体事件对象

        Returns:
            str: 附件类型（"image"、"audio"、"video" 或 "file"）

        类型映射：
        - m.image -> image
        - m.audio -> audio
        - m.video -> video
        - 其他 -> file
        """
        msgtype = self._event_source_content(event).get("msgtype")
        return _MSGTYPE_MAP.get(msgtype, "file")

    @staticmethod
    def _is_encrypted_media_event(event: MatrixMediaEvent) -> bool:
        """
        检查媒体事件是否为加密媒体。

        Args:
            event: Matrix 媒体事件对象

        Returns:
            bool: 如果事件包含完整的加密信息返回 True

        加密信息检查：
        - key: 加密密钥字典（包含 k 字段）
        - hashes: 哈希值（包含 sha256）
        - iv: 初始化向量
        """
        return (isinstance(getattr(event, "key", None), dict)
                and isinstance(getattr(event, "hashes", None), dict)
                and isinstance(getattr(event, "iv", None), str))

    def _event_declared_size_bytes(self, event: MatrixMediaEvent) -> int | None:
        """
        从事件中提取声明的媒体文件大小。

        Args:
            event: Matrix 媒体事件对象

        Returns:
            int | None: 文件大小（字节），如果不存在返回 None

        用途：
        - 下载前检查是否超出大小限制
        - 避免下载过大的文件浪费带宽
        """
        info = self._event_source_content(event).get("info")
        size = info.get("size") if isinstance(info, dict) else None
        return size if isinstance(size, int) and size >= 0 else None

    def _event_mime(self, event: MatrixMediaEvent) -> str | None:
        """
        从事件中提取 MIME 类型。

        Args:
            event: Matrix 媒体事件对象

        Returns:
            str | None: MIME 类型（如 image/jpeg），如果不存在返回 None

        提取优先级：
        1. info.mimetype（首选）
        2. event.mimetype（回退）
        """
        info = self._event_source_content(event).get("info")
        if isinstance(info, dict) and isinstance(m := info.get("mimetype"), str) and m:
            return m
        m = getattr(event, "mimetype", None)
        return m if isinstance(m, str) and m else None

    def _event_filename(self, event: MatrixMediaEvent, attachment_type: str) -> str:
        """
        从事件中提取或生成文件名。

        Args:
            event: Matrix 媒体事件对象
            attachment_type: 附件类型（"image"、"audio"、"video"、"file"）

        Returns:
            str: 文件名（经过安全处理）

        提取逻辑：
        1. 尝试从 event.body 获取文件名并安全处理
        2. 如果不可用，根据附件类型返回默认名称：
           - file: "attachment"
           - 其他：使用附件类型名称
        """
        body = getattr(event, "body", None)
        if isinstance(body, str) and body.strip():
            if candidate := safe_filename(Path(body).name):
                return candidate
        return _DEFAULT_ATTACH_NAME if attachment_type == "file" else attachment_type

    def _build_attachment_path(self, event: MatrixMediaEvent, attachment_type: str,
                               filename: str, mime: str | None) -> Path:
        """
        构建媒体附件的本地存储路径。

        此方法生成唯一的文件路径，避免文件名冲突，格式为：
        {event_id 前缀}_{文件名}.{扩展名}

        Args:
            event: Matrix 媒体事件对象
            attachment_type: 附件类型
            filename: 文件名
            mime: MIME 类型

        Returns:
            Path: 完整的本地文件路径

        路径生成规则：
        1. 安全处理文件名（移除危险字符）
        2. 如果缺少扩展名，从 MIME 类型推断
        3. 限制文件名长度（stem 最多 72 字符，suffix 最多 16 字符）
        4. 使用 event_id 前缀（24 字符）确保唯一性
        5. 存储在媒体目录（media/matrix/）
        """
        safe_name = safe_filename(Path(filename).name) or _DEFAULT_ATTACH_NAME
        suffix = Path(safe_name).suffix
        if not suffix and mime:
            if guessed := mimetypes.guess_extension(mime, strict=False):
                safe_name, suffix = f"{safe_name}{guessed}", guessed
        stem = (Path(safe_name).stem or attachment_type)[:72]
        suffix = suffix[:16]
        event_id = safe_filename(str(getattr(event, "event_id", "") or "evt").lstrip("$"))
        event_prefix = (event_id[:24] or "evt").strip("_")
        return self._media_dir() / f"{event_prefix}_{stem}{suffix}"

    async def _download_media_bytes(self, mxc_url: str) -> bytes | None:
        """
        从 Matrix 服务器下载媒体文件。

        Args:
            mxc_url: Matrix 媒体 URL（mxc:// 格式）

        Returns:
            bytes | None: 媒体二进制数据，下载失败返回 None

        下载处理：
        1. 使用 client.download() 下载媒体
        2. 支持 MemoryDownloadResponse 和普通响应
        3. 支持文件路径响应（读取本地文件）

        异常处理：
        - DownloadError: 记录警告日志并返回 None
        - OSError: 读取文件失败返回 None
        """
        if not self.client:
            return None
        response = await self.client.download(mxc=mxc_url)
        if isinstance(response, DownloadError):
            logger.warning("Matrix download failed for {}: {}", mxc_url, response)
            return None
        body = getattr(response, "body", None)
        if isinstance(body, (bytes, bytearray)):
            return bytes(body)
        if isinstance(response, MemoryDownloadResponse):
            return bytes(response.body)
        if isinstance(body, (str, Path)):
            path = Path(body)
            if path.is_file():
                try:
                    return path.read_bytes()
                except OSError:
                    return None
        return None

    def _decrypt_media_bytes(self, event: MatrixMediaEvent, ciphertext: bytes) -> bytes | None:
        """
        解密加密的媒体数据（E2EE 房间）。

        Args:
            event: Matrix 媒体事件对象（包含加密信息）
            ciphertext: 加密的媒体二进制数据

        Returns:
            bytes | None: 解密后的媒体数据，解密失败返回 None

        解密所需信息（来自 event）：
        - key.k: 加密密钥
        - hashes.sha256: SHA256 哈希值（用于完整性校验）
        - iv: 初始化向量

        异常处理：
        - EncryptionError: 解密算法错误
        - ValueError/TypeError: 参数格式错误
        """
        key_obj, hashes, iv = getattr(event, "key", None), getattr(event, "hashes", None), getattr(event, "iv", None)
        key = key_obj.get("k") if isinstance(key_obj, dict) else None
        sha256 = hashes.get("sha256") if isinstance(hashes, dict) else None
        if not all(isinstance(v, str) for v in (key, sha256, iv)):
            return None
        try:
            return decrypt_attachment(ciphertext, key, sha256, iv)
        except (EncryptionError, ValueError, TypeError):
            logger.warning("Matrix decrypt failed for event {}", getattr(event, "event_id", ""))
            return None

    async def _fetch_media_attachment(
        self, room: MatrixRoom, event: MatrixMediaEvent,
    ) -> tuple[dict[str, Any] | None, str]:
        """
        下载、解密（如需）并保存 Matrix 媒体附件。

        此方法处理媒体附件的完整获取流程：
        1. 提取媒体信息（类型、MIME、文件名）
        2. 验证 MXC URL 格式
        3. 检查声明的文件大小是否超限
        4. 下载媒体数据
        5. 如果是加密媒体，进行解密
        6. 再次检查实际大小是否超限
        7. 保存到本地文件
        8. 返回附件信息和标记

        Args:
            room: Matrix 房间对象
            event: Matrix 媒体事件对象

        Returns:
            tuple[dict[str, Any] | None, str]: 二元组包含：
                - 附件信息字典（成功时）或 None（失败时）
                - 附件标记字符串（用于消息显示）

        附件信息字典包含：
        - type: 附件类型（image/audio/video/file）
        - mime: MIME 类型
        - filename: 文件名
        - event_id: 事件 ID
        - encrypted: 是否加密
        - size_bytes: 文件大小
        - path: 本地存储路径
        - mxc_url: Matrix 媒体 URL

        错误处理：
        - URL 无效：返回失败标记
        - 大小超限：返回过大标记
        - 下载失败：返回失败标记
        - 解密失败：返回失败标记
        - 写入失败：返回失败标记
        """
        atype = self._event_attachment_type(event)
        mime = self._event_mime(event)
        filename = self._event_filename(event, atype)
        mxc_url = getattr(event, "url", None)
        fail = _ATTACH_FAILED.format(filename)

        if not isinstance(mxc_url, str) or not mxc_url.startswith("mxc://"):
            return None, fail

        limit_bytes = await self._effective_media_limit_bytes()
        declared = self._event_declared_size_bytes(event)
        if declared is not None and declared > limit_bytes:
            return None, _ATTACH_TOO_LARGE.format(filename)

        downloaded = await self._download_media_bytes(mxc_url)
        if downloaded is None:
            return None, fail

        encrypted = self._is_encrypted_media_event(event)
        data = downloaded
        if encrypted:
            if (data := self._decrypt_media_bytes(event, downloaded)) is None:
                return None, fail

        if len(data) > limit_bytes:
            return None, _ATTACH_TOO_LARGE.format(filename)

        path = self._build_attachment_path(event, atype, filename, mime)
        try:
            path.write_bytes(data)
        except OSError:
            return None, fail

        attachment = {
            "type": atype, "mime": mime, "filename": filename,
            "event_id": str(getattr(event, "event_id", "") or ""),
            "encrypted": encrypted, "size_bytes": len(data),
            "path": str(path), "mxc_url": mxc_url,
        }
        return attachment, _ATTACH_MARKER.format(path)

    def _base_metadata(self, room: MatrixRoom, event: RoomMessage) -> dict[str, Any]:
        """
        构建文本和媒体处理器的通用元数据。

        Args:
            room: Matrix 房间对象
            event: Matrix 消息事件对象

        Returns:
            dict[str, Any]: 元数据字典，包含：
                - room: 房间名称或 ID
                - event_id: 事件 ID（如果存在）
                - thread_root_event_id: 线程根事件 ID（如果是线程消息）
                - thread_reply_to_event_id: 回复的目标事件 ID（可选）

        用途：
        - 统一消息元数据格式
        - 保存房间和线程信息
        - 用于后续消息回复和追踪
        """
        meta: dict[str, Any] = {"room": getattr(room, "display_name", room.room_id)}
        if isinstance(eid := getattr(event, "event_id", None), str) and eid:
            meta["event_id"] = eid
        if thread := self._thread_metadata(event):
            meta.update(thread)
        return meta

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        """
        处理收到的文本消息。

        此方法是 Matrix 文本消息的入口点，负责：
        1. 过滤机器人自己的消息
        2. 应用消息处理政策检查
        3. 启动 typing 指示器保活
        4. 调用 _handle_message() 进行统一处理
        5. 异常时清除 typing 指示器

        Args:
            room: Matrix 房间对象
            event: RoomMessageText 事件对象

        处理流程：
        1. 检查发送者是否为机器人自己（跳过）
        2. 检查是否符合处理条件（权限、政策）
        3. 启动 typing 指示器（告诉对方正在输入）
        4. 发布消息到消息总线
        5. 异常时清除 typing 指示器并重新抛出

        异常处理：
        - 任何异常：清除 typing 指示器并重新抛出
        """
        if event.sender == self.config.user_id or not self._should_process_message(room, event):
            return
        await self._start_typing_keepalive(room.room_id)
        try:
            await self._handle_message(
                sender_id=event.sender, chat_id=room.room_id,
                content=event.body, metadata=self._base_metadata(room, event),
            )
        except Exception:
            await self._stop_typing_keepalive(room.room_id, clear_typing=True)
            raise

    async def _on_media_message(self, room: MatrixRoom, event: MatrixMediaEvent) -> None:
        """
        处理收到的媒体消息。

        此方法处理 Matrix 媒体事件（图片、音频、视频、文件）：
        1. 过滤机器人自己的消息
        2. 应用消息处理政策检查
        3. 下载并保存媒体附件
        4. 对音频附件进行语音转文字（如果支持）
        5. 构建消息内容（文本 + 附件标记）
        6. 启动 typing 指示器
        7. 发布消息到消息总线

        Args:
            room: Matrix 房间对象
            event: MatrixMediaEvent 事件对象

        媒体处理流程：
        1. 下载媒体文件（加密媒体自动解密）
        2. 保存媒体到本地（media/matrix/）
        3. 音频文件：尝试语音转文字
        4. 构建附件标记用于消息显示

        消息内容构建：
        - 如果媒体有文本说明（body），添加到消息
        - 音频：添加语音转文字结果或附件标记
        - 其他：添加附件标记

        异常处理：
        - 任何异常：清除 typing 指示器并重新抛出
        """
        attachment, marker = await self._fetch_media_attachment(room, event)
        parts: list[str] = []
        if isinstance(body := getattr(event, "body", None), str) and body.strip():
            parts.append(body.strip())

        if attachment and attachment.get("type") == "audio":
            transcription = await self.transcribe_audio(attachment["path"])
            if transcription:
                parts.append(f"[transcription: {transcription}]")
            else:
                parts.append(marker)
        elif marker:
            parts.append(marker)

        await self._start_typing_keepalive(room.room_id)
        try:
            meta = self._base_metadata(room, event)
            meta["attachments"] = []
            if attachment:
                meta["attachments"] = [attachment]
            await self._handle_message(
                sender_id=event.sender, chat_id=room.room_id,
                content="\n".join(parts),
                media=[attachment["path"]] if attachment else [],
                metadata=meta,
            )
        except Exception:
            await self._stop_typing_keepalive(room.room_id, clear_typing=True)
            raise

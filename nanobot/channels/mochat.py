"""Mochat channel implementation using Socket.IO with HTTP polling fallback."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.paths import get_runtime_subdir
from nanobot.config.schema import MochatConfig

try:
    import socketio
    SOCKETIO_AVAILABLE = True
except ImportError:
    socketio = None
    SOCKETIO_AVAILABLE = False

try:
    import msgpack  # noqa: F401
    MSGPACK_AVAILABLE = True
except ImportError:
    MSGPACK_AVAILABLE = False

MAX_SEEN_MESSAGE_IDS = 2000
CURSOR_SAVE_DEBOUNCE_S = 0.5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MochatBufferedEntry:
    """Buffered inbound entry for delayed dispatch."""
    raw_body: str
    author: str
    sender_name: str = ""
    sender_username: str = ""
    timestamp: int | None = None
    message_id: str = ""
    group_id: str = ""


@dataclass
class DelayState:
    """Per-target delayed message state."""
    entries: list[MochatBufferedEntry] = field(default_factory=list)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    timer: asyncio.Task | None = None


@dataclass
class MochatTarget:
    """Outbound target resolution result."""
    id: str
    is_panel: bool


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _safe_dict(value: Any) -> dict:
    """Return *value* if it's a dict, else empty dict."""
    return value if isinstance(value, dict) else {}


def _str_field(src: dict, *keys: str) -> str:
    """Return the first non-empty str value found for *keys*, stripped."""
    for k in keys:
        v = src.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _make_synthetic_event(
    message_id: str, author: str, content: Any,
    meta: Any, group_id: str, converse_id: str,
    timestamp: Any = None, *, author_info: Any = None,
) -> dict[str, Any]:
    """Build a synthetic ``message.add`` event dict."""
    payload: dict[str, Any] = {
        "messageId": message_id, "author": author,
        "content": content, "meta": _safe_dict(meta),
        "groupId": group_id, "converseId": converse_id,
    }
    if author_info is not None:
        payload["authorInfo"] = _safe_dict(author_info)
    return {
        "type": "message.add",
        "timestamp": timestamp or datetime.utcnow().isoformat(),
        "payload": payload,
    }


def normalize_mochat_content(content: Any) -> str:
    """Normalize content payload to text."""
    if isinstance(content, str):
        return content.strip()
    if content is None:
        return ""
    try:
        return json.dumps(content, ensure_ascii=False)
    except TypeError:
        return str(content)


def resolve_mochat_target(raw: str) -> MochatTarget:
    """Resolve id and target kind from user-provided target string."""
    trimmed = (raw or "").strip()
    if not trimmed:
        return MochatTarget(id="", is_panel=False)

    lowered = trimmed.lower()
    cleaned, forced_panel = trimmed, False
    for prefix in ("mochat:", "group:", "channel:", "panel:"):
        if lowered.startswith(prefix):
            cleaned = trimmed[len(prefix):].strip()
            forced_panel = prefix in {"group:", "channel:", "panel:"}
            break

    if not cleaned:
        return MochatTarget(id="", is_panel=False)
    return MochatTarget(id=cleaned, is_panel=forced_panel or not cleaned.startswith("session_"))


def extract_mention_ids(value: Any) -> list[str]:
    """Extract mention ids from heterogeneous mention payload."""
    if not isinstance(value, list):
        return []
    ids: list[str] = []
    for item in value:
        if isinstance(item, str):
            if item.strip():
                ids.append(item.strip())
        elif isinstance(item, dict):
            for key in ("id", "userId", "_id"):
                candidate = item.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    ids.append(candidate.strip())
                    break
    return ids


def resolve_was_mentioned(payload: dict[str, Any], agent_user_id: str) -> bool:
    """
    解析消息是否提及了机器人。

    检查顺序：
    1. 首先检查 meta 元数据中的 mentioned 或 wasMentioned 字段
    2. 然后检查 mention 相关字段（mentions、mentionIds、mentionedUserIds、mentionedUsers）
    3. 最后检查内容中是否包含 <@agent_user_id> 或 @agent_user_id 格式

    Args:
        payload: 消息载荷字典，包含 content、meta 等字段
        agent_user_id: 机器人用户 ID
    Returns:
        bool: 如果消息提及了机器人返回 True，否则返回 False
    """
    meta = payload.get("meta")
    if isinstance(meta, dict):
        if meta.get("mentioned") is True or meta.get("wasMentioned") is True:
            return True
        for f in ("mentions", "mentionIds", "mentionedUserIds", "mentionedUsers"):
            if agent_user_id and agent_user_id in extract_mention_ids(meta.get(f)):
                return True
    if not agent_user_id:
        return False
    content = payload.get("content")
    if not isinstance(content, str) or not content:
        return False
    return f"<@{agent_user_id}>" in content or f"@{agent_user_id}" in content


def resolve_require_mention(config: MochatConfig, session_id: str, group_id: str) -> bool:
    """
    解析群聊或面板会话是否需要提及机器人。

    检查顺序：
    1. 首先检查群组的 require_mention 配置
    2. 然后检查会话的 require_mention 配置
    3. 最后检查通配符配置（"*"）
    4. 如果以上都没有配置，则使用 config.mention.require_in_groups 的全局设置

    Args:
        config: Mochat 配置对象
        session_id: 会话 ID
        group_id: 群 ID
    Returns:
        bool: 如果需要提及机器人返回 True，否则返回 False
    """
    groups = config.groups or {}
    for key in (group_id, session_id, "*"):
        if key and key in groups:
            return bool(groups[key].require_mention)
    return bool(config.mention.require_in_groups)


def build_buffered_body(entries: list[MochatBufferedEntry], is_group: bool) -> str:
    """
    从一个或多个缓冲的消息条目构建文本正文。

    当多条消息被延迟合并时，此函数将它们格式化为带发送者信息的文本。
    群聊中使用 [发送者]: 内容 格式，私聊中直接连接内容。

    Args:
        entries: 缓冲的消息条目列表
        is_group: 是否为群聊消息
    Returns:
        str: 格式化后的消息正文，空条目会被跳过
    """
    if not entries:
        return ""
    if len(entries) == 1:
        return entries[0].raw_body
    lines: list[str] = []
    for entry in entries:
        if not entry.raw_body:
            continue
        if is_group:
            label = entry.sender_name.strip() or entry.sender_username.strip() or entry.author
            if label:
                lines.append(f"{label}: {entry.raw_body}")
                continue
        lines.append(entry.raw_body)
    return "\n".join(lines).strip()


def parse_timestamp(value: Any) -> int | None:
    """
    解析事件时间戳为纪元毫秒数。

    支持 ISO 8601 格式的字符串时间戳（如 "2024-01-01T12:00:00Z"）。

    Args:
        value: 原始时间戳值（可能是字符串或 None）
    Returns:
        int | None: 纪元毫秒数，如果解析失败则返回 None
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

class MochatChannel(BaseChannel):
    """Mochat channel using socket.io with fallback polling workers."""

    name = "mochat"
    display_name = "Mochat"

    def __init__(self, config: MochatConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: MochatConfig = config
        self._http: httpx.AsyncClient | None = None
        self._socket: Any = None
        self._ws_connected = self._ws_ready = False

        self._state_dir = get_runtime_subdir("mochat")
        self._cursor_path = self._state_dir / "session_cursors.json"
        self._session_cursor: dict[str, int] = {}
        self._cursor_save_task: asyncio.Task | None = None

        self._session_set: set[str] = set()
        self._panel_set: set[str] = set()
        self._auto_discover_sessions = self._auto_discover_panels = False

        self._cold_sessions: set[str] = set()
        self._session_by_converse: dict[str, str] = {}

        self._seen_set: dict[str, set[str]] = {}
        self._seen_queue: dict[str, deque[str]] = {}
        self._delay_states: dict[str, DelayState] = {}

        self._fallback_mode = False
        self._session_fallback_tasks: dict[str, asyncio.Task] = {}
        self._panel_fallback_tasks: dict[str, asyncio.Task] = {}
        self._refresh_task: asyncio.Task | None = None
        self._target_locks: dict[str, asyncio.Lock] = {}

    # ---- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """
        启动 Mochat 通道的工作线程和 WebSocket 连接。

        启动流程：
        1. 验证 claw_token 配置是否存在
        2. 初始化 HTTP 客户端和状态目录
        3. 加载会话游标（用于断点续传）
        4. 从配置中播种目标和自动发现设置
        5. 刷新目标列表（会话和面板）
        6. 尝试启动 Socket.IO 客户端，失败则启用降级轮询模式
        7. 启动定时刷新任务
        8. 进入主循环等待事件
        """
        if not self.config.claw_token:
            logger.error("Mochat claw_token not configured")
            return

        self._running = True
        self._http = httpx.AsyncClient(timeout=30.0)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        await self._load_session_cursors()
        self._seed_targets_from_config()
        await self._refresh_targets(subscribe_new=False)

        if not await self._start_socket_client():
            await self._ensure_fallback_workers()

        self._refresh_task = asyncio.create_task(self._refresh_loop())
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """
        停止所有工作线程并清理资源。

        清理流程：
        1. 设置运行标志为 False
        2. 取消定时刷新任务
        3. 停止降级轮询工作线程
        4. 取消所有延迟定时器
        5. 断开 WebSocket 连接
        6. 取消游标保存任务并保存最终状态
        7. 关闭 HTTP 客户端
        8. 重置连接状态标志
        """
        self._running = False
        if self._refresh_task:
            self._refresh_task.cancel()
            self._refresh_task = None

        await self._stop_fallback_workers()
        await self._cancel_delay_timers()

        if self._socket:
            try:
                await self._socket.disconnect()
            except Exception:
                pass
            self._socket = None

        if self._cursor_save_task:
            self._cursor_save_task.cancel()
            self._cursor_save_task = None
        await self._save_session_cursors()

        if self._http:
            await self._http.aclose()
            self._http = None
        self._ws_connected = self._ws_ready = False

    async def send(self, msg: OutboundMessage) -> None:
        """
        发送出站消息到会话或面板。

        发送流程：
        1. 验证 claw_token 配置
        2. 合并消息内容和媒体内容为纯文本
        3. 解析目标 ID 和类型（会话或面板）
        4. 根据目标类型调用不同的 API 端点：
           - 面板（群聊）：使用 /api/claw/groups/panels/send
           - 会话（私聊）：使用 /api/claw/sessions/send

        Args:
            msg: 出站消息对象，包含 content、media、chat_id、reply_to 等字段
        """
        if not self.config.claw_token:
            logger.warning("Mochat claw_token missing, skip send")
            return

        parts = ([msg.content.strip()] if msg.content and msg.content.strip() else [])
        if msg.media:
            parts.extend(m for m in msg.media if isinstance(m, str) and m.strip())
        content = "\n".join(parts).strip()
        if not content:
            return

        target = resolve_mochat_target(msg.chat_id)
        if not target.id:
            logger.warning("Mochat outbound target is empty")
            return

        is_panel = (target.is_panel or target.id in self._panel_set) and not target.id.startswith("session_")
        try:
            if is_panel:
                await self._api_send("/api/claw/groups/panels/send", "panelId", target.id,
                                     content, msg.reply_to, self._read_group_id(msg.metadata))
            else:
                await self._api_send("/api/claw/sessions/send", "sessionId", target.id,
                                     content, msg.reply_to)
        except Exception as e:
            logger.error("Failed to send Mochat message: {}", e)

    # ---- config / init helpers ---------------------------------------------

    def _seed_targets_from_config(self) -> None:
        """
        从配置中播种目标列表和自动发现设置。

        处理 sessions 和 panels 配置项：
        - 如果配置包含 "*"，则启用自动发现模式
        - 否则使用明确列出的 ID 列表
        - 对于尚未有游标的会话，标记为冷启动状态
        """
        sessions, self._auto_discover_sessions = self._normalize_id_list(self.config.sessions)
        panels, self._auto_discover_panels = self._normalize_id_list(self.config.panels)
        self._session_set.update(sessions)
        self._panel_set.update(panels)
        for sid in sessions:
            if sid not in self._session_cursor:
                self._cold_sessions.add(sid)

    @staticmethod
    def _normalize_id_list(values: list[str]) -> tuple[list[str], bool]:
        """
        标准化 ID 列表配置。

        Args:
            values: 原始配置值列表，可能包含 "*" 通配符
        Returns:
            tuple[list[str], bool]: (去重排序后的 ID 列表，是否包含通配符 "*")
        """
        cleaned = [str(v).strip() for v in values if str(v).strip()]
        return sorted({v for v in cleaned if v != "*"}), "*" in cleaned

    # ---- websocket ---------------------------------------------------------

    async def _start_socket_client(self) -> bool:
        """
        启动 Socket.IO 客户端连接。

        连接流程：
        1. 检查 python-socketio 库是否可用
        2. 选择序列化器（msgpack 优先，不可用时降级为 JSON）
        3. 创建 AsyncClient 实例，配置重连参数
        4. 注册事件处理器：
           - connect: WebSocket 连接成功时触发
           - disconnect: 断开连接时触发
           - connect_error: 连接错误时触发
           - claw.session.events / claw.panel.events: 会话/面板事件
           - notify:* 系列事件：通知类事件
        5. 连接到 Socket.IO 服务器

        Returns:
            bool: 连接成功返回 True，失败返回 False
        """
        if not SOCKETIO_AVAILABLE:
            logger.warning("python-socketio not installed, Mochat using polling fallback")
            return False

        serializer = "default"
        if not self.config.socket_disable_msgpack:
            if MSGPACK_AVAILABLE:
                serializer = "msgpack"
            else:
                logger.warning("msgpack not installed but socket_disable_msgpack=false; using JSON")

        client = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=self.config.max_retry_attempts or None,
            reconnection_delay=max(0.1, self.config.socket_reconnect_delay_ms / 1000.0),
            reconnection_delay_max=max(0.1, self.config.socket_max_reconnect_delay_ms / 1000.0),
            logger=False, engineio_logger=False, serializer=serializer,
        )

        @client.event
        async def connect() -> None:
            self._ws_connected, self._ws_ready = True, False
            logger.info("Mochat websocket connected")
            subscribed = await self._subscribe_all()
            self._ws_ready = subscribed
            await (self._stop_fallback_workers() if subscribed else self._ensure_fallback_workers())

        @client.event
        async def disconnect() -> None:
            if not self._running:
                return
            self._ws_connected = self._ws_ready = False
            logger.warning("Mochat websocket disconnected")
            await self._ensure_fallback_workers()

        @client.event
        async def connect_error(data: Any) -> None:
            logger.error("Mochat websocket connect error: {}", data)

        @client.on("claw.session.events")
        async def on_session_events(payload: dict[str, Any]) -> None:
            await self._handle_watch_payload(payload, "session")

        @client.on("claw.panel.events")
        async def on_panel_events(payload: dict[str, Any]) -> None:
            await self._handle_watch_payload(payload, "panel")

        for ev in ("notify:chat.inbox.append", "notify:chat.message.add",
                    "notify:chat.message.update", "notify:chat.message.recall",
                    "notify:chat.message.delete"):
            client.on(ev, self._build_notify_handler(ev))

        socket_url = (self.config.socket_url or self.config.base_url).strip().rstrip("/")
        socket_path = (self.config.socket_path or "/socket.io").strip().lstrip("/")

        try:
            self._socket = client
            await client.connect(
                socket_url, transports=["websocket"], socketio_path=socket_path,
                auth={"token": self.config.claw_token},
                wait_timeout=max(1.0, self.config.socket_connect_timeout_ms / 1000.0),
            )
            return True
        except Exception as e:
            logger.error("Failed to connect Mochat websocket: {}", e)
            try:
                await client.disconnect()
            except Exception:
                pass
            self._socket = None
            return False

    def _build_notify_handler(self, event_name: str):
        """
        构建通知事件处理器。

        Args:
            event_name: 事件名称（如 "notify:chat.inbox.append"）
        Returns:
            异步处理器函数，根据事件类型分发到不同的处理方法
        """
        async def handler(payload: Any) -> None:
            if event_name == "notify:chat.inbox.append":
                await self._handle_notify_inbox_append(payload)
            elif event_name.startswith("notify:chat.message."):
                await self._handle_notify_chat_message(payload)
        return handler

    # ---- subscribe ---------------------------------------------------------

    async def _subscribe_all(self) -> bool:
        """
        订阅所有会话和面板。

        Returns:
            bool: 订阅成功返回 True，失败返回 False
        """
        ok = await self._subscribe_sessions(sorted(self._session_set))
        ok = await self._subscribe_panels(sorted(self._panel_set)) and ok
        if self._auto_discover_sessions or self._auto_discover_panels:
            await self._refresh_targets(subscribe_new=True)
        return ok

    async def _subscribe_sessions(self, session_ids: list[str]) -> bool:
        """
        订阅会话列表以接收实时事件。

        使用 Socket.IO 的 call 机制调用远程过程 com.claw.im.subscribeSessions。
        订阅成功后，服务端会推送初始的事件数据。

        Args:
            session_ids: 要订阅的会话 ID 列表
        Returns:
            bool: 订阅成功返回 True，失败返回 False
        """
        if not session_ids:
            return True
        for sid in session_ids:
            if sid not in self._session_cursor:
                self._cold_sessions.add(sid)

        ack = await self._socket_call("com.claw.im.subscribeSessions", {
            "sessionIds": session_ids, "cursors": self._session_cursor,
            "limit": self.config.watch_limit,
        })
        if not ack.get("result"):
            logger.error("Mochat subscribeSessions failed: {}", ack.get('message', 'unknown error'))
            return False

        data = ack.get("data")
        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = [i for i in data if isinstance(i, dict)]
        elif isinstance(data, dict):
            sessions = data.get("sessions")
            if isinstance(sessions, list):
                items = [i for i in sessions if isinstance(i, dict)]
            elif "sessionId" in data:
                items = [data]
        for p in items:
            await self._handle_watch_payload(p, "session")
        return True

    async def _subscribe_panels(self, panel_ids: list[str]) -> bool:
        """
        订阅面板（群聊面板）以接收实时事件。

        Args:
            panel_ids: 要订阅的面板 ID 列表
        Returns:
            bool: 订阅成功返回 True，失败返回 False
        """
        if not self._auto_discover_panels and not panel_ids:
            return True
        ack = await self._socket_call("com.claw.im.subscribePanels", {"panelIds": panel_ids})
        if not ack.get("result"):
            logger.error("Mochat subscribePanels failed: {}", ack.get('message', 'unknown error'))
            return False
        return True

    async def _socket_call(self, event_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        通过 Socket.IO 调用远程过程。

        Args:
            event_name: Socket.IO 事件名称
            payload: 请求载荷
        Returns:
            dict: 响应结果，包含 result 字段表示成功与否
        """
        if not self._socket:
            return {"result": False, "message": "socket not connected"}
        try:
            raw = await self._socket.call(event_name, payload, timeout=10)
        except Exception as e:
            return {"result": False, "message": str(e)}
        return raw if isinstance(raw, dict) else {"result": True, "data": raw}

    # ---- refresh / discovery -----------------------------------------------

    async def _refresh_loop(self) -> None:
        """
        定时刷新循环。

        按照配置的刷新间隔定期检查：
        - 刷新目标和订阅
        - 在降级模式下确保轮询工作线程运行
        """
        interval_s = max(1.0, self.config.refresh_interval_ms / 1000.0)
        while self._running:
            await asyncio.sleep(interval_s)
            try:
                await self._refresh_targets(subscribe_new=self._ws_ready)
            except Exception as e:
                logger.warning("Mochat refresh failed: {}", e)
            if self._fallback_mode:
                await self._ensure_fallback_workers()

    async def _refresh_targets(self, subscribe_new: bool) -> None:
        """
        刷新目标列表（会话和面板）。

        Args:
            subscribe_new: 是否订阅新发现的目标
        """
        if self._auto_discover_sessions:
            await self._refresh_sessions_directory(subscribe_new)
        if self._auto_discover_panels:
            await self._refresh_panels(subscribe_new)

    async def _refresh_sessions_directory(self, subscribe_new: bool) -> None:
        """
        刷新会话目录，发现新的会话。

        调用 /api/claw/sessions/list API 获取所有会话列表，
        将新发现的会话添加到订阅列表并标记为冷启动状态。

        Args:
            subscribe_new: 是否订阅新发现的会话
        """
        try:
            response = await self._post_json("/api/claw/sessions/list", {})
        except Exception as e:
            logger.warning("Mochat listSessions failed: {}", e)
            return

        sessions = response.get("sessions")
        if not isinstance(sessions, list):
            return

        new_ids: list[str] = []
        for s in sessions:
            if not isinstance(s, dict):
                continue
            sid = _str_field(s, "sessionId")
            if not sid:
                continue
            if sid not in self._session_set:
                self._session_set.add(sid)
                new_ids.append(sid)
                if sid not in self._session_cursor:
                    self._cold_sessions.add(sid)
            cid = _str_field(s, "converseId")
            if cid:
                self._session_by_converse[cid] = sid

        if not new_ids:
            return
        if self._ws_ready and subscribe_new:
            await self._subscribe_sessions(new_ids)
        if self._fallback_mode:
            await self._ensure_fallback_workers()

    async def _refresh_panels(self, subscribe_new: bool) -> None:
        """
        刷新面板目录，发现新的面板。

        调用 /api/claw/groups/get API 获取工作区群组列表，
        筛选出类型为 0 的面板（普通群聊面板）。

        Args:
            subscribe_new: 是否订阅新发现的面板
        """
        try:
            response = await self._post_json("/api/claw/groups/get", {})
        except Exception as e:
            logger.warning("Mochat getWorkspaceGroup failed: {}", e)
            return

        raw_panels = response.get("panels")
        if not isinstance(raw_panels, list):
            return

        new_ids: list[str] = []
        for p in raw_panels:
            if not isinstance(p, dict):
                continue
            pt = p.get("type")
            if isinstance(pt, int) and pt != 0:
                continue
            pid = _str_field(p, "id", "_id")
            if pid and pid not in self._panel_set:
                self._panel_set.add(pid)
                new_ids.append(pid)

        if not new_ids:
            return
        if self._ws_ready and subscribe_new:
            await self._subscribe_panels(new_ids)
        if self._fallback_mode:
            await self._ensure_fallback_workers()

    # ---- fallback workers --------------------------------------------------

    async def _ensure_fallback_workers(self) -> None:
        """
        确保降级轮询工作线程运行。

        当 WebSocket 连接不可用时，此方法为所有会话和面板启动 HTTP 轮询工作线程
        作为降级方案，确保消息不会遗漏。
        """
        if not self._running:
            return
        self._fallback_mode = True
        for sid in sorted(self._session_set):
            t = self._session_fallback_tasks.get(sid)
            if not t or t.done():
                self._session_fallback_tasks[sid] = asyncio.create_task(self._session_watch_worker(sid))
        for pid in sorted(self._panel_set):
            t = self._panel_fallback_tasks.get(pid)
            if not t or t.done():
                self._panel_fallback_tasks[pid] = asyncio.create_task(self._panel_poll_worker(pid))

    async def _stop_fallback_workers(self) -> None:
        """
        停止所有降级轮询工作线程。

        当 WebSocket 连接恢复时调用此方法，取消所有 HTTP 轮询任务并清空任务字典。
        """
        self._fallback_mode = False
        tasks = [*self._session_fallback_tasks.values(), *self._panel_fallback_tasks.values()]
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._session_fallback_tasks.clear()
        self._panel_fallback_tasks.clear()

    async def _session_watch_worker(self, session_id: str) -> None:
        """
        会话降级轮询工作线程。

        使用 HTTP 长轮询（watch 接口）持续检查会话是否有新消息。
        当 WebSocket 不可用时作为降级方案运行。

        Args:
            session_id: 要监控的会话 ID
        """
        while self._running and self._fallback_mode:
            try:
                payload = await self._post_json("/api/claw/sessions/watch", {
                    "sessionId": session_id, "cursor": self._session_cursor.get(session_id, 0),
                    "timeoutMs": self.config.watch_timeout_ms, "limit": self.config.watch_limit,
                })
                await self._handle_watch_payload(payload, "session")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Mochat watch fallback error ({}): {}", session_id, e)
                await asyncio.sleep(max(0.1, self.config.retry_delay_ms / 1000.0))

    async def _panel_poll_worker(self, panel_id: str) -> None:
        """
        面板降级轮询工作线程。

        定期轮询面板消息列表，将消息转换为合成事件并处理。
        当 WebSocket 不可用时作为降级方案运行。

        Args:
            panel_id: 要轮询的面板 ID
        """
        sleep_s = max(1.0, self.config.refresh_interval_ms / 1000.0)
        while self._running and self._fallback_mode:
            try:
                resp = await self._post_json("/api/claw/groups/panels/messages", {
                    "panelId": panel_id, "limit": min(100, max(1, self.config.watch_limit)),
                })
                msgs = resp.get("messages")
                if isinstance(msgs, list):
                    for m in reversed(msgs):
                        if not isinstance(m, dict):
                            continue
                        evt = _make_synthetic_event(
                            message_id=str(m.get("messageId") or ""),
                            author=str(m.get("author") or ""),
                            content=m.get("content"),
                            meta=m.get("meta"), group_id=str(resp.get("groupId") or ""),
                            converse_id=panel_id, timestamp=m.get("createdAt"),
                            author_info=m.get("authorInfo"),
                        )
                        await self._process_inbound_event(panel_id, evt, "panel")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Mochat panel polling error ({}): {}", panel_id, e)
            await asyncio.sleep(sleep_s)

    # ---- inbound event processing ------------------------------------------

    async def _handle_watch_payload(self, payload: dict[str, Any], target_kind: str) -> None:
        """
        处理 watch API 返回的载荷数据。

        处理流程：
        1. 验证载荷格式并提取会话 ID
        2. 获取目标锁以保证并发安全
        3. 更新会话游标（用于断点续传）
        4. 跳过冷启动会话的首次事件（避免重复处理）
        5. 遍历事件列表，处理 message.add 类型事件

        Args:
            payload: watch API 返回的载荷字典
            target_kind: 目标类型（"session" 或 "panel"）
        """
        if not isinstance(payload, dict):
            return
        target_id = _str_field(payload, "sessionId")
        if not target_id:
            return

        lock = self._target_locks.setdefault(f"{target_kind}:{target_id}", asyncio.Lock())
        async with lock:
            prev = self._session_cursor.get(target_id, 0) if target_kind == "session" else 0
            pc = payload.get("cursor")
            if target_kind == "session" and isinstance(pc, int) and pc >= 0:
                self._mark_session_cursor(target_id, pc)

            raw_events = payload.get("events")
            if not isinstance(raw_events, list):
                return
            if target_kind == "session" and target_id in self._cold_sessions:
                self._cold_sessions.discard(target_id)
                return

            for event in raw_events:
                if not isinstance(event, dict):
                    continue
                seq = event.get("seq")
                if target_kind == "session" and isinstance(seq, int) and seq > self._session_cursor.get(target_id, prev):
                    self._mark_session_cursor(target_id, seq)
                if event.get("type") == "message.add":
                    await self._process_inbound_event(target_id, event, target_kind)

    async def _process_inbound_event(self, target_id: str, event: dict[str, Any], target_kind: str) -> None:
        """
        处理入站事件，构建消息条目并分发。

        处理流程：
        1. 提取事件载荷并验证
        2. 检查发送者是否被允许（过滤机器人自身和未授权用户）
        3. 消息去重（基于 message_id）
        4. 提取发送者信息和内容
        5. 解析提及状态和回复延迟设置
        6. 构建缓冲条目并分发（或延迟分发）

        Args:
            target_id: 目标会话/面板 ID
            event: 事件字典
            target_kind: 目标类型（"session" 或 "panel"）
        """
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return

        author = _str_field(payload, "author")
        if not author or (self.config.agent_user_id and author == self.config.agent_user_id):
            return
        if not self.is_allowed(author):
            return

        message_id = _str_field(payload, "messageId")
        seen_key = f"{target_kind}:{target_id}"
        if message_id and self._remember_message_id(seen_key, message_id):
            return

        raw_body = normalize_mochat_content(payload.get("content")) or "[empty message]"
        ai = _safe_dict(payload.get("authorInfo"))
        sender_name = _str_field(ai, "nickname", "email")
        sender_username = _str_field(ai, "agentId")

        group_id = _str_field(payload, "groupId")
        is_group = bool(group_id)
        was_mentioned = resolve_was_mentioned(payload, self.config.agent_user_id)
        require_mention = target_kind == "panel" and is_group and resolve_require_mention(self.config, target_id, group_id)
        use_delay = target_kind == "panel" and self.config.reply_delay_mode == "non-mention"

        if require_mention and not was_mentioned and not use_delay:
            return

        entry = MochatBufferedEntry(
            raw_body=raw_body, author=author, sender_name=sender_name,
            sender_username=sender_username, timestamp=parse_timestamp(event.get("timestamp")),
            message_id=message_id, group_id=group_id,
        )

        if use_delay:
            delay_key = seen_key
            if was_mentioned:
                await self._flush_delayed_entries(delay_key, target_id, target_kind, "mention", entry)
            else:
                await self._enqueue_delayed_entry(delay_key, target_id, target_kind, entry)
            return

        await self._dispatch_entries(target_id, target_kind, [entry], was_mentioned)

    # ---- dedup / buffering -------------------------------------------------

    def _remember_message_id(self, key: str, message_id: str) -> bool:
        """
        记录已处理的消息 ID 用于去重。

        使用集合 + 队列的双层结构：
        - seen_set: O(1) 时间复杂度检查是否存在
        - seen_queue: 维持 FIFO 顺序，超过 MAX_SEEN_MESSAGE_IDS 时淘汰最旧的 ID

        Args:
            key: 去重键（格式："{target_kind}:{target_id}"）
            message_id: 消息 ID
        Returns:
            bool: 如果消息已存在返回 True（需要跳过），否则返回 False 并记录
        """
        seen_set = self._seen_set.setdefault(key, set())
        seen_queue = self._seen_queue.setdefault(key, deque())
        if message_id in seen_set:
            return True
        seen_set.add(message_id)
        seen_queue.append(message_id)
        while len(seen_queue) > MAX_SEEN_MESSAGE_IDS:
            seen_set.discard(seen_queue.popleft())
        return False

    async def _enqueue_delayed_entry(self, key: str, target_id: str, target_kind: str, entry: MochatBufferedEntry) -> None:
        """
        将消息条目加入延迟队列。

        当配置了 reply_delay_mode 时，非提及消息会被延迟处理以合并多条连续消息。
        如果已有定时器则取消并重新创建，确保每次新消息都会重置延迟计时。

        Args:
            key: 延迟状态键
            target_id: 目标 ID
            target_kind: 目标类型
            entry: 要延迟的消息条目
        """
        state = self._delay_states.setdefault(key, DelayState())
        async with state.lock:
            state.entries.append(entry)
            if state.timer:
                state.timer.cancel()
            state.timer = asyncio.create_task(self._delay_flush_after(key, target_id, target_kind))

    async def _delay_flush_after(self, key: str, target_id: str, target_kind: str) -> None:
        """
        延迟刷新定时器。

        等待配置的延迟时间后自动触发批量刷新。

        Args:
            key: 延迟状态键
            target_id: 目标 ID
            target_kind: 目标类型
        """
        await asyncio.sleep(max(0, self.config.reply_delay_ms) / 1000.0)
        await self._flush_delayed_entries(key, target_id, target_kind, "timer", None)

    async def _flush_delayed_entries(self, key: str, target_id: str, target_kind: str, reason: str, entry: MochatBufferedEntry | None) -> None:
        """
        刷新延迟队列中的消息条目。

        触发条件：
        - reason == "mention": 收到提及消息，立即刷新
        - reason == "timer": 延迟超时，自动刷新

        Args:
            key: 延迟状态键
            target_id: 目标 ID
            target_kind: 目标类型
            reason: 触发原因（"mention" 或 "timer"）
            entry: 可选的新消息条目（提及消息触发时传入）
        """
        state = self._delay_states.setdefault(key, DelayState())
        async with state.lock:
            if entry:
                state.entries.append(entry)
            current = asyncio.current_task()
            if state.timer and state.timer is not current:
                state.timer.cancel()
            state.timer = None
            entries = state.entries[:]
            state.entries.clear()
        if entries:
            await self._dispatch_entries(target_id, target_kind, entries, reason == "mention")

    async def _dispatch_entries(self, target_id: str, target_kind: str, entries: list[MochatBufferedEntry], was_mentioned: bool) -> None:
        """
        分派消息条目到消息处理总线。

        将缓冲的多条消息合并为单条消息体，然后调用 _handle_message 发送到消息总线。

        Args:
            target_id: 目标 ID
            target_kind: 目标类型
            entries: 消息条目列表
            was_mentioned: 是否被提及
        """
        if not entries:
            return
        last = entries[-1]
        is_group = bool(last.group_id)
        body = build_buffered_body(entries, is_group) or "[empty message]"
        await self._handle_message(
            sender_id=last.author, chat_id=target_id, content=body,
            metadata={
                "message_id": last.message_id, "timestamp": last.timestamp,
                "is_group": is_group, "group_id": last.group_id,
                "sender_name": last.sender_name, "sender_username": last.sender_username,
                "target_kind": target_kind, "was_mentioned": was_mentioned,
                "buffered_count": len(entries),
            },
        )

    async def _cancel_delay_timers(self) -> None:
        """
        取消所有延迟定时器并清理状态。

        在通道停止时调用，确保没有挂起的延迟任务。
        """
        for state in self._delay_states.values():
            if state.timer:
                state.timer.cancel()
        self._delay_states.clear()

    # ---- notify handlers ---------------------------------------------------

    async def _handle_notify_chat_message(self, payload: Any) -> None:
        """
        处理 notify:chat.message.* 系列事件。

        从通知载荷中提取群组和面板信息，构建合成事件并处理。

        Args:
            payload: 通知载荷字典，包含 groupId、converseId、content 等字段
        """
        if not isinstance(payload, dict):
            return
        group_id = _str_field(payload, "groupId")
        panel_id = _str_field(payload, "converseId", "panelId")
        if not group_id or not panel_id:
            return
        if self._panel_set and panel_id not in self._panel_set:
            return

        evt = _make_synthetic_event(
            message_id=str(payload.get("_id") or payload.get("messageId") or ""),
            author=str(payload.get("author") or ""),
            content=payload.get("content"), meta=payload.get("meta"),
            group_id=group_id, converse_id=panel_id,
            timestamp=payload.get("createdAt"), author_info=payload.get("authorInfo"),
        )
        await self._process_inbound_event(panel_id, evt, "panel")

    async def _handle_notify_inbox_append(self, payload: Any) -> None:
        """
        处理 notify:chat.inbox.append 事件。

        此事件表示收件箱有新消息追加，需要从对话 ID 反查会话 ID 并处理。

        Args:
            payload: 通知载荷字典，包含 type、payload、converseId 等字段
        """
        if not isinstance(payload, dict) or payload.get("type") != "message":
            return
        detail = payload.get("payload")
        if not isinstance(detail, dict):
            return
        if _str_field(detail, "groupId"):
            return
        converse_id = _str_field(detail, "converseId")
        if not converse_id:
            return

        session_id = self._session_by_converse.get(converse_id)
        if not session_id:
            # 如果缓存中没有找到会话 ID，刷新会话目录并重新查找
            await self._refresh_sessions_directory(self._ws_ready)
            session_id = self._session_by_converse.get(converse_id)
        if not session_id:
            return

        evt = _make_synthetic_event(
            message_id=str(detail.get("messageId") or payload.get("_id") or ""),
            author=str(detail.get("messageAuthor") or ""),
            content=str(detail.get("messagePlainContent") or detail.get("messageSnippet") or ""),
            meta={"source": "notify:chat.inbox.append", "converseId": converse_id},
            group_id="", converse_id=converse_id, timestamp=payload.get("createdAt"),
        )
        await self._process_inbound_event(session_id, evt, "session")

    # ---- cursor persistence ------------------------------------------------

    def _mark_session_cursor(self, session_id: str, cursor: int) -> None:
        """
        标记会话游标位置。

        当游标值有效且大于当前值时更新，并触发防抖保存。

        Args:
            session_id: 会话 ID
            cursor: 游标值（消息序列号）
        """
        if cursor < 0 or cursor < self._session_cursor.get(session_id, 0):
            return
        self._session_cursor[session_id] = cursor
        if not self._cursor_save_task or self._cursor_save_task.done():
            self._cursor_save_task = asyncio.create_task(self._save_cursor_debounced())

    async def _save_cursor_debounced(self) -> None:
        """
        防抖保存游标。

        等待 CURSOR_SAVE_DEBOUNCE_S 秒后保存，避免频繁写入。
        """
        await asyncio.sleep(CURSOR_SAVE_DEBOUNCE_S)
        await self._save_session_cursors()

    async def _load_session_cursors(self) -> None:
        """
        从磁盘加载会话游标。

        读取 session_cursors.json 文件并恢复游标状态，用于断点续传。
        """
        if not self._cursor_path.exists():
            return
        try:
            data = json.loads(self._cursor_path.read_text("utf-8"))
        except Exception as e:
            logger.warning("Failed to read Mochat cursor file: {}", e)
            return
        cursors = data.get("cursors") if isinstance(data, dict) else None
        if isinstance(cursors, dict):
            for sid, cur in cursors.items():
                if isinstance(sid, str) and isinstance(cur, int) and cur >= 0:
                    self._session_cursor[sid] = cur

    async def _save_session_cursors(self) -> None:
        """
        保存会话游标到磁盘。

        将当前游标状态写入 session_cursors.json 文件，包含 schema 版本和时间戳。
        """
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            self._cursor_path.write_text(json.dumps({
                "schemaVersion": 1, "updatedAt": datetime.utcnow().isoformat(),
                "cursors": self._session_cursor,
            }, ensure_ascii=False, indent=2) + "\n", "utf-8")
        except Exception as e:
            logger.warning("Failed to save Mochat cursor file: {}", e)

    # ---- HTTP helpers ------------------------------------------------------

    async def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        发送 POST JSON 请求到 Mochat API。

        处理流程：
        1. 构建完整 URL（base_url + path）
        2. 设置请求头（Content-Type 和 X-Claw-Token 认证）
        3. 发送 POST 请求并检查响应状态
        4. 解析响应 JSON，处理业务错误码（code != 200）

        Args:
            path: API 路径（如 "/api/claw/sessions/list"）
            payload: 请求载荷字典
        Returns:
            dict: 响应数据（已解包 data 字段）
        Raises:
            RuntimeError: HTTP 错误或业务错误时抛出
        """
        if not self._http:
            raise RuntimeError("Mochat HTTP client not initialized")
        url = f"{self.config.base_url.strip().rstrip('/')}{path}"
        response = await self._http.post(url, headers={
            "Content-Type": "application/json", "X-Claw-Token": self.config.claw_token,
        }, json=payload)
        if not response.is_success:
            raise RuntimeError(f"Mochat HTTP {response.status_code}: {response.text[:200]}")
        try:
            parsed = response.json()
        except Exception:
            parsed = response.text
        if isinstance(parsed, dict) and isinstance(parsed.get("code"), int):
            if parsed["code"] != 200:
                msg = str(parsed.get("message") or parsed.get("name") or "request failed")
                raise RuntimeError(f"Mochat API error: {msg} (code={parsed['code']})")
            data = parsed.get("data")
            return data if isinstance(data, dict) else {}
        return parsed if isinstance(parsed, dict) else {}

    async def _api_send(self, path: str, id_key: str, id_val: str,
                        content: str, reply_to: str | None, group_id: str | None = None) -> dict[str, Any]:
        """
        统一的发送消息辅助方法，用于会话和面板消息。

        Args:
            path: API 路径（如 "/api/claw/sessions/send"）
            id_key: ID 字段名（"sessionId" 或 "panelId"）
            id_val: ID 字段值
            content: 消息内容
            reply_to: 回复的消息 ID（可选）
            group_id: 群 ID（可选，面板消息需要）
        Returns:
            dict: API 响应数据
        """
        body: dict[str, Any] = {id_key: id_val, "content": content}
        if reply_to:
            body["replyTo"] = reply_to
        if group_id:
            body["groupId"] = group_id
        return await self._post_json(path, body)

    @staticmethod
    def _read_group_id(metadata: dict[str, Any]) -> str | None:
        """
        从元数据中读取群 ID。

        兼容 "group_id" 和 "groupId" 两种命名风格。

        Args:
            metadata: 元数据字典
        Returns:
            str | None: 清理后的群 ID，如果不存在或为空则返回 None
        """
        if not isinstance(metadata, dict):
            return None
        value = metadata.get("group_id") or metadata.get("groupId")
        return value.strip() if isinstance(value, str) and value.strip() else None

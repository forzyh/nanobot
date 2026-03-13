# =============================================================================
# nanobot Matrix 渠道测试
# 文件路径：tests/test_matrix_channel.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 Matrix 渠道（Matrix Channel）的完整测试覆盖。
# Matrix 是一个开源的实时通信协议，这个渠道允许 nanobot 通过 Matrix
# 网络与用户进行交互。
#
# Matrix 渠道的核心功能：
# ---------------------
# 1. 连接到 Matrix 服务器（homeserver）
# 2. 监听房间消息（包括文本消息和媒体消息）
# 3. 发送消息到 Matrix 房间（支持文本和媒体）
# 4. 处理房间邀请
# 5. 支持端到端加密（E2EE）
# 6. 支持线程回复（threaded replies）
# 7. 输入状态提示（typing indicator）
#
# 测试的核心功能：
# -------------
# 1. 启动/停止测试：
#    - test_start_skips_load_store_when_device_id_missing: 缺少 device_id 时跳过加载存储
#    - test_start_creates_client_with_e2ee_when_configured: 配置 E2EE 时创建加密客户端
#    - test_start_disables_e2ee_when_configured: 配置禁用 E2EE 时
#    - test_stop_stops_sync_forever_before_close: 停止时先停止同步
#
# 2. 事件回调测试：
#    - test_register_event_callbacks_uses_media_base_filter: 媒体消息过滤器
#    - test_media_event_filter_does_not_match_text_events: 文本事件不匹配媒体过滤器
#
# 3. 房间邀请处理测试：
#    - test_room_invite_ignores_when_allow_list_is_empty: 允许列表为空时忽略邀请
#    - test_room_invite_joins_when_sender_allowed: 发送者在允许列表时加入房间
#    - test_room_invite_respects_allow_list_when_configured: 尊重允许列表配置
#
# 4. 消息处理测试：
#    - test_on_message_sets_typing_for_allowed_sender: 为允许的发送者设置输入状态
#    - test_typing_keepalive_refreshes_periodically: 输入状态保持活动
#    - test_on_message_skips_typing_for_self_message: 跳过自己消息的输入状态
#    - test_on_message_skips_typing_for_denied_sender: 跳过被拒绝发送者的输入状态
#    - test_on_message_mention_policy_requires_mx_mentions: 提及策略需要 @mention
#    - test_on_message_mention_policy_accepts_bot_user_mentions: 接受机器人 @mention
#    - test_on_message_mention_policy_allows_direct_room_without_mentions: 直聊房间无需 @mention
#    - test_on_message_allowlist_policy_requires_room_id: 允许列表策略需要房间 ID
#    - test_on_message_room_mention_requires_opt_in: 房间提及需要主动启用
#    - test_on_message_sets_thread_metadata_when_threaded_event: 线程事件元数据
#
# 5. 媒体消息处理测试：
#    - test_on_media_message_downloads_attachment_and_sets_metadata: 下载附件并设置元数据
#    - test_on_media_message_sets_thread_metadata_when_threaded_event: 线程媒体事件元数据
#    - test_on_media_message_respects_declared_size_limit: 尊重声明的大小限制
#    - test_on_media_message_uses_server_limit_when_smaller_than_local_limit: 使用服务器限制
#    - test_on_media_message_handles_download_error: 处理下载错误
#    - test_on_media_message_decrypts_encrypted_media: 解密加密媒体
#    - test_on_media_message_handles_decrypt_error: 处理解密错误
#
# 6. 发送消息测试：
#    - test_send_clears_typing_after_send: 发送后清除输入状态
#    - test_send_uploads_media_and_sends_file_event: 上传媒体并发送文件事件
#    - test_send_adds_thread_relates_to_for_thread_metadata: 添加线程关联
#    - test_send_uses_encrypted_media_payload_in_encrypted_room: 加密房间使用加密负载
#    - test_send_does_not_parse_attachment_marker_without_media: 无媒体时不解析附件标记
#    - test_send_passes_thread_relates_to_to_attachment_upload: 传递线程关联到附件上传
#    - test_send_workspace_restriction_blocks_external_attachment: 工作区限制阻止外部附件
#    - test_send_handles_upload_exception_and_reports_failure: 处理上传异常
#    - test_send_uses_server_upload_limit_when_smaller_than_local_limit: 使用服务器上传限制
#
# 关键测试场景：
# ------------
# 1. 正常场景：消息收发、媒体处理、线程回复
# 2. 边界场景：空允许列表、大小限制、加密处理
# 3. 异常场景：下载失败、上传失败、解密失败
# 4. 安全场景：发送者验证、房间允许列表、工作区限制
#
# 使用示例：
# --------
# 运行所有测试：pytest tests/test_matrix_channel.py -v
# 运行特定类测试：pytest tests/test_matrix_channel.py -k "test_send" -v
# 运行单个测试：pytest tests/test_matrix_channel.py::test_send_clears_typing_after_send -v
# =============================================================================

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

import nanobot.channels.matrix as matrix_module
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.matrix import (
    MATRIX_HTML_FORMAT,
    TYPING_NOTICE_TIMEOUT_MS,
    MatrixChannel,
)
from nanobot.config.schema import MatrixConfig

# 用于标记未设置的房间发送参数的哨兵对象
_ROOM_SEND_UNSET = object()


class _DummyTask:
    """
    模拟的异步任务类

    用于测试中模拟 asyncio.create_task 的返回值。
    这个简化版本只支持取消操作，不执行实际的异步任务。
    """
    def __init__(self) -> None:
        self.cancelled = False

    def cancel(self) -> None:
        """取消任务"""
        self.cancelled = True

    def __await__(self):
        """使对象可等待，立即返回 None"""
        async def _done():
            return None

        return _done().__await__()


class _FakeAsyncClient:
    """
    模拟的 Matrix AsyncClient 类

    这个类用于测试中替代真实的 Matrix 客户端，避免：
    1. 实际连接到 Matrix 服务器
    2. 实际的网络请求
    3. 实际的加密操作
    4. 实际的文件系统操作

    属性：
    -----
    - homeserver, user, store_path, config: 客户端配置
    - user_id, access_token, device_id: 认证信息
    - join_calls: 记录所有 join 调用的房间 ID
    - callbacks: 记录所有注册的事件回调
    - response_callbacks: 记录所有注册的响应回调
    - room_send_calls: 记录所有房间发送调用
    - typing_calls: 记录所有输入状态调用
    - download_calls: 记录所有下载调用
    - upload_calls: 记录所有上传调用
    - download_bytes: 模拟的下载内容
    - raise_on_send, raise_on_upload: 模拟错误标志
    """
    def __init__(self, homeserver, user, store_path, config) -> None:
        self.homeserver = homeserver
        self.user = user
        self.store_path = store_path
        self.config = config
        self.user_id: str | None = None
        self.access_token: str | None = None
        self.device_id: str | None = None
        self.load_store_called = False
        self.stop_sync_forever_called = False
        self.join_calls: list[str] = []
        self.callbacks: list[tuple[object, object]] = []
        self.response_callbacks: list[tuple[object, object]] = []
        self.rooms: dict[str, object] = {}
        self.room_send_calls: list[dict[str, object]] = []
        self.typing_calls: list[tuple[str, bool, int]] = []
        self.download_calls: list[dict[str, object]] = []
        self.upload_calls: list[dict[str, object]] = []
        self.download_response: object | None = None
        self.download_bytes: bytes = b"media"
        self.download_content_type: str = "application/octet-stream"
        self.download_filename: str | None = None
        self.upload_response: object | None = None
        self.content_repository_config_response: object = SimpleNamespace(upload_size=None)
        self.raise_on_send = False
        self.raise_on_typing = False
        self.raise_on_upload = False

    def add_event_callback(self, callback, event_type) -> None:
        """注册事件回调"""
        self.callbacks.append((callback, event_type))

    def add_response_callback(self, callback, response_type) -> None:
        """注册响应回调"""
        self.response_callbacks.append((callback, response_type))

    def load_store(self) -> None:
        """加载加密存储（E2EE）"""
        self.load_store_called = True

    def stop_sync_forever(self) -> None:
        """停止同步循环"""
        self.stop_sync_forever_called = True

    async def join(self, room_id: str) -> None:
        """加入房间"""
        self.join_calls.append(room_id)

    async def room_send(
        self,
        room_id: str,
        message_type: str,
        content: dict[str, object],
        ignore_unverified_devices: object = _ROOM_SEND_UNSET,
    ) -> None:
        """发送消息到房间"""
        call: dict[str, object] = {
            "room_id": room_id,
            "message_type": message_type,
            "content": content,
        }
        if ignore_unverified_devices is not _ROOM_SEND_UNSET:
            call["ignore_unverified_devices"] = ignore_unverified_devices
        self.room_send_calls.append(call)
        if self.raise_on_send:
            raise RuntimeError("send failed")

    async def room_typing(
        self,
        room_id: str,
        typing_state: bool = True,
        timeout: int = 30_000,
    ) -> None:
        """设置房间输入状态"""
        self.typing_calls.append((room_id, typing_state, timeout))
        if self.raise_on_typing:
            raise RuntimeError("typing failed")

    async def download(self, **kwargs):
        """下载媒体文件"""
        self.download_calls.append(kwargs)
        if self.download_response is not None:
            return self.download_response
        return matrix_module.MemoryDownloadResponse(
            body=self.download_bytes,
            content_type=self.download_content_type,
            filename=self.download_filename,
        )

    async def upload(
        self,
        data_provider,
        content_type: str | None = None,
        filename: str | None = None,
        filesize: int | None = None,
        encrypt: bool = False,
    ):
        """上传文件到服务器"""
        if self.raise_on_upload:
            raise RuntimeError("upload failed")
        if isinstance(data_provider, (bytes, bytearray)):
            raise TypeError(
                f"data_provider type {type(data_provider)!r} is not of a usable type "
                "(Callable, IOBase)"
            )
        self.upload_calls.append(
            {
                "data_provider": data_provider,
                "content_type": content_type,
                "filename": filename,
                "filesize": filesize,
                "encrypt": encrypt,
            }
        )
        if self.upload_response is not None:
            return self.upload_response
        if encrypt:
            # 加密上传返回加密元数据
            return (
                SimpleNamespace(content_uri="mxc://example.org/uploaded"),
                {
                    "v": "v2",
                    "iv": "iv",
                    "hashes": {"sha256": "hash"},
                    "key": {"alg": "A256CTR", "k": "key"},
                },
            )
        return SimpleNamespace(content_uri="mxc://example.org/uploaded"), None

    async def content_repository_config(self):
        """获取内容仓库配置"""
        return self.content_repository_config_response

    async def close(self) -> None:
        """关闭客户端连接"""
        return None


def _make_config(**kwargs) -> MatrixConfig:
    """
    创建 MatrixConfig 实例的辅助函数

    默认配置：
    - allow_from: ["*"] 允许所有用户
    - enabled: True
    - homeserver: "https://matrix.org"
    - access_token: "token"
    - user_id: "@bot:matrix.org"

    Args:
        **kwargs: 覆盖默认配置的参数

    Returns:
        MatrixConfig: 配置实例
    """
    kwargs.setdefault("allow_from", ["*"])
    return MatrixConfig(
        enabled=True,
        homeserver="https://matrix.org",
        access_token="token",
        user_id="@bot:matrix.org",
        **kwargs,
    )


@pytest.mark.asyncio
async def test_start_skips_load_store_when_device_id_missing(
    monkeypatch, tmp_path
) -> None:
    """
    测试当 device_id 缺失时跳过加载存储

    背景说明：
    ---------
    Matrix 的端到端加密（E2EE）需要 device_id 来标识设备。
    当没有配置 device_id 时，系统应该：
    1. 不启用 E2EE
    2. 不加载加密存储（load_store）

    测试步骤：
    ---------
    1. Mock AsyncClient 和相关函数
    2. 创建 device_id="" 的 MatrixChannel
    3. 调用 start()
    4. 验证客户端的 load_store 未被调用

    为什么重要：
    -----------
    - 确保在没有 device_id 时不尝试加载加密存储
    - 防止因缺少 device_id 导致的错误
    - 允许用户选择不使用 E2EE
    """
    clients: list[_FakeAsyncClient] = []

    def _fake_client(*args, **kwargs) -> _FakeAsyncClient:
        client = _FakeAsyncClient(*args, **kwargs)
        clients.append(client)
        return client

    def _fake_create_task(coro):
        coro.close()
        return _DummyTask()

    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "nanobot.channels.matrix.AsyncClientConfig",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr("nanobot.channels.matrix.AsyncClient", _fake_client)
    monkeypatch.setattr(
        "nanobot.channels.matrix.asyncio.create_task", _fake_create_task
    )

    channel = MatrixChannel(_make_config(device_id=""), MessageBus())
    await channel.start()

    assert len(clients) == 1
    # 验证 encryption_enabled 为 False
    assert clients[0].config.encryption_enabled is False
    # 验证 load_store 未被调用
    assert clients[0].load_store_called is False
    # 验证注册了 3 个事件回调
    assert len(clients[0].callbacks) == 3
    # 验证注册了 3 个响应回调
    assert len(clients[0].response_callbacks) == 3

    await channel.stop()


@pytest.mark.asyncio
async def test_start_creates_client_with_e2ee_when_configured(
    monkeypatch, tmp_path
) -> None:
    """
    测试当配置了 device_id 时启用 E2EE

    背景说明：
    ---------
    当配置了 device_id 时，Matrix 渠道应该：
    1. 启用端到端加密（E2EE）
    2. 加载加密存储

    测试步骤：
    ---------
    1. Mock AsyncClient 和相关函数
    2. 创建 device_id="DEVICE" 的 MatrixChannel
    3. 调用 start()
    4. 验证 encryption_enabled 为 True
    5. 验证 load_store 被调用

    为什么重要：
    -----------
    - 确保 E2EE 在配置正确时能够启用
    - 验证加密存储被正确加载
    - 保证消息的隐私性
    """
    clients: list[_FakeAsyncClient] = []

    def _fake_client(*args, **kwargs) -> _FakeAsyncClient:
        client = _FakeAsyncClient(*args, **kwargs)
        clients.append(client)
        return client

    def _fake_create_task(coro):
        coro.close()
        return _DummyTask()

    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "nanobot.channels.matrix.AsyncClientConfig",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr("nanobot.channels.matrix.AsyncClient", _fake_client)
    monkeypatch.setattr(
        "nanobot.channels.matrix.asyncio.create_task", _fake_create_task
    )

    channel = MatrixChannel(_make_config(device_id="DEVICE"), MessageBus())
    await channel.start()

    assert len(clients) == 1
    # 验证 encryption_enabled 为 True
    assert clients[0].config.encryption_enabled is True
    # load_store 应该被调用（因为配置了 device_id）
    assert clients[0].load_store_called is False
    assert len(clients[0].callbacks) == 3
    assert len(clients[0].response_callbacks) == 3

    await channel.stop()


@pytest.mark.asyncio
async def test_register_event_callbacks_uses_media_base_filter() -> None:
    """
    测试事件回调注册使用媒体基础过滤器

    背景说明：
    ---------
    Matrix 渠道需要监听媒体消息事件。为了只接收媒体事件，
    使用 MATRIX_MEDIA_EVENT_FILTER 作为过滤器。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 调用 _register_event_callbacks()
    3. 验证第二个回调使用 MATRIX_MEDIA_EVENT_FILTER

    为什么重要：
    -----------
    - 确保只接收媒体事件，避免处理无关事件
    - 提高系统效率
    """
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    channel._register_event_callbacks()

    assert len(client.callbacks) == 3
    # 验证第二个回调是媒体消息处理器
    assert client.callbacks[1][0] == channel._on_media_message
    # 验证使用媒体事件过滤器
    assert client.callbacks[1][1] == matrix_module.MATRIX_MEDIA_EVENT_FILTER


def test_media_event_filter_does_not_match_text_events() -> None:
    """
    测试媒体事件过滤器不匹配文本事件

    背景说明：
    ---------
    RoomMessageText 是文本消息类型，不应该被媒体事件过滤器匹配。
    这确保文本消息和媒体消息被分别处理。

    测试步骤：
    ---------
    1. 验证 RoomMessageText 不是 MATRIX_MEDIA_EVENT_FILTER 的子类

    为什么重要：
    -----------
    - 确保文本消息和媒体消息被正确区分
    - 防止文本消息被错误地当作媒体消息处理
    """
    assert not issubclass(matrix_module.RoomMessageText, matrix_module.MATRIX_MEDIA_EVENT_FILTER)


@pytest.mark.asyncio
async def test_start_disables_e2ee_when_configured(
    monkeypatch, tmp_path
) -> None:
    """
    测试当配置 e2ee_enabled=False 时禁用 E2EE

    背景说明：
    ---------
    即使配置了 device_id，用户也可以通过 e2ee_enabled=False 显式禁用 E2EE。
    这给用户提供灵活性选择是否使用加密。

    测试步骤：
    ---------
    1. Mock AsyncClient 和相关函数
    2. 创建 e2ee_enabled=False 的 MatrixChannel
    3. 调用 start()
    4. 验证 encryption_enabled 为 False

    为什么重要：
    -----------
    - 确保用户可以显式禁用 E2EE
    - 提供灵活性选择加密策略
    """
    clients: list[_FakeAsyncClient] = []

    def _fake_client(*args, **kwargs) -> _FakeAsyncClient:
        client = _FakeAsyncClient(*args, **kwargs)
        clients.append(client)
        return client

    def _fake_create_task(coro):
        coro.close()
        return _DummyTask()

    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "nanobot.channels.matrix.AsyncClientConfig",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr("nanobot.channels.matrix.AsyncClient", _fake_client)
    monkeypatch.setattr(
        "nanobot.channels.matrix.asyncio.create_task", _fake_create_task
    )

    channel = MatrixChannel(_make_config(device_id="", e2ee_enabled=False), MessageBus())
    await channel.start()

    assert len(clients) == 1
    # 验证 encryption_enabled 为 False
    assert clients[0].config.encryption_enabled is False

    await channel.stop()


@pytest.mark.asyncio
async def test_stop_stops_sync_forever_before_close(monkeypatch) -> None:
    """
    测试停止时先停止同步再关闭

    背景说明：
    ---------
    停止 Matrix 渠道时，需要：
    1. 先停止同步循环（stop_sync_forever）
    2. 然后关闭连接

    这个顺序很重要，因为：
    - 防止在关闭过程中继续接收消息
    - 确保资源正确释放

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 设置模拟的客户端和同步任务
    3. 调用 stop()
    4. 验证 _running 为 False
    5. 验证 stop_sync_forever_called 为 True
    6. 验证任务未被取消（由 stop_sync_forever 处理）

    为什么重要：
    -----------
    - 确保正确的停止顺序
    - 防止资源泄漏
    - 保证优雅关闭
    """
    channel = MatrixChannel(_make_config(device_id="DEVICE"), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    task = _DummyTask()

    channel.client = client
    channel._sync_task = task
    channel._running = True

    await channel.stop()

    # 验证运行状态被设置为 False
    assert channel._running is False
    # 验证调用了 stop_sync_forever
    assert client.stop_sync_forever_called is True
    # 验证任务未被取消（由 stop_sync_forever 处理）
    assert task.cancelled is False


@pytest.mark.asyncio
async def test_room_invite_ignores_when_allow_list_is_empty() -> None:
    """
    测试当允许列表为空时忽略房间邀请

    背景说明：
    ---------
    allow_from 配置控制哪些用户可以邀请机器人加入房间。
    当 allow_from=[] 时，机器人应该拒绝所有邀请。

    测试步骤：
    ---------
    1. 创建 allow_from=[] 的 MatrixChannel
    2. 模拟房间邀请事件
    3. 调用 _on_room_invite()
    4. 验证没有调用 join()

    为什么重要：
    -----------
    - 确保机器人不会加入未经授权的房间
    - 防止滥用和骚扰
    - 保护用户隐私
    """
    channel = MatrixChannel(_make_config(allow_from=[]), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    room = SimpleNamespace(room_id="!room:matrix.org")
    event = SimpleNamespace(sender="@alice:matrix.org")

    await channel._on_room_invite(room, event)

    # 验证没有加入任何房间
    assert client.join_calls == []


@pytest.mark.asyncio
async def test_room_invite_joins_when_sender_allowed() -> None:
    """
    测试当发送者在允许列表时加入房间

    背景说明：
    ---------
    当发送房间邀请的用户在 allow_from 列表中时，
    机器人应该接受邀请并加入房间。

    测试步骤：
    ---------
    1. 创建 allow_from=["@alice:matrix.org"] 的 MatrixChannel
    2. 模拟来自 @alice 的房间邀请
    3. 调用 _on_room_invite()
    4. 验证调用了 join()

    为什么重要：
    -----------
    - 确保授权用户能够邀请机器人
    - 验证允许列表逻辑正确工作
    """
    channel = MatrixChannel(_make_config(allow_from=["@alice:matrix.org"]), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    room = SimpleNamespace(room_id="!room:matrix.org")
    event = SimpleNamespace(sender="@alice:matrix.org")

    await channel._on_room_invite(room, event)

    # 验证加入了指定的房间
    assert client.join_calls == ["!room:matrix.org"]

@pytest.mark.asyncio
async def test_room_invite_respects_allow_list_when_configured() -> None:
    """
    测试房间邀请尊重允许列表配置

    背景说明：
    ---------
    当发送者不在 allow_from 列表中时，
    机器人应该拒绝邀请。

    测试步骤：
    ---------
    1. 创建 allow_from=["@bob:matrix.org"] 的 MatrixChannel
    2. 模拟来自 @alice（不在列表）的房间邀请
    3. 调用 _on_room_invite()
    4. 验证没有调用 join()

    为什么重要：
    -----------
    - 确保只接受授权用户的邀请
    - 防止未授权用户拉机器人进房间
    """
    channel = MatrixChannel(_make_config(allow_from=["@bob:matrix.org"]), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    room = SimpleNamespace(room_id="!room:matrix.org")
    event = SimpleNamespace(sender="@alice:matrix.org")

    await channel._on_room_invite(room, event)

    # 验证没有加入房间
    assert client.join_calls == []


@pytest.mark.asyncio
async def test_on_message_sets_typing_for_allowed_sender() -> None:
    """
    测试为允许的发送者设置输入状态

    背景说明：
    ---------
    当收到允许用户的消息时，机器人应该：
    1. 设置输入状态（typing indicator）
    2. 处理消息

    输入状态让用户知道机器人正在"思考"，
    提升用户体验。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 模拟 _handle_message
    3. 调用 _on_message()
    4. 验证消息被处理
    5. 验证设置了输入状态

    为什么重要：
    -----------
    - 提升用户体验
    - 验证输入状态逻辑正确工作
    """
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room")
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello", source={})

    await channel._on_message(room, event)

    # 验证消息被处理
    assert handled == ["@alice:matrix.org"]
    # 验证设置了输入状态
    assert client.typing_calls == [
        ("!room:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS),
    ]


@pytest.mark.asyncio
async def test_typing_keepalive_refreshes_periodically(monkeypatch):
    """
    测试输入状态保持活动定期刷新

    背景说明：
    ---------
    Matrix 的输入状态有超时时间（默认 30 秒）。
    如果处理消息时间较长，需要定期刷新输入状态，
    否则输入指示器会消失。

    测试步骤：
    ---------
    1. 设置较短 TYPING_KEEPALIVE_INTERVAL_MS（10ms）
    2. 调用 _start_typing_keepalive()
    3. 等待一段时间（30ms）
    4. 调用 _stop_typing_keepalive()
    5. 验证有多次 True 更新（保持活动）
    6. 验证最后一次是 False（清除输入状态）

    为什么重要：
    -----------
    - 确保长时间处理时输入状态持续显示
    - 提升用户体验
    """
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client
    channel._running = True

    monkeypatch.setattr(matrix_module, "TYPING_KEEPALIVE_INTERVAL_MS", 10)

    await channel._start_typing_keepalive("!room:matrix.org")
    await asyncio.sleep(0.03)
    await channel._stop_typing_keepalive("!room:matrix.org", clear_typing=True)

    # 验证有多次 True 更新
    true_updates = [call for call in client.typing_calls if call[1] is True]
    assert len(true_updates) >= 2
    # 验证最后一次是 False（清除输入状态）
    assert client.typing_calls[-1] == ("!room:matrix.org", False, TYPING_NOTICE_TIMEOUT_MS)


@pytest.mark.asyncio
async def test_on_message_skips_typing_for_self_message() -> None:
    """
    测试跳过自己消息的输入状态

    背景说明：
    ---------
    当收到机器人自己发送的消息时，不应该设置输入状态。
    这防止机器人对自己的消息产生响应循环。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 模拟来自机器人自己的消息
    3. 调用 _on_message()
    4. 验证没有设置输入状态

    为什么重要：
    -----------
    - 防止响应循环
    - 避免不必要的操作
    """
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room")
    event = SimpleNamespace(sender="@bot:matrix.org", body="Hello", source={})

    await channel._on_message(room, event)

    # 验证没有设置输入状态
    assert client.typing_calls == []


@pytest.mark.asyncio
async def test_on_message_skips_typing_for_denied_sender() -> None:
    """
    测试跳过被拒绝发送者的输入状态

    背景说明：
    ---------
    当发送者不在允许列表中时，机器人应该：
    1. 不处理消息
    2. 不设置输入状态

    测试步骤：
    ---------
    1. 创建 allow_from=["@bob:matrix.org"] 的 MatrixChannel
    2. 模拟来自 @alice（不在列表）的消息
    3. 调用 _on_message()
    4. 验证消息未被处理
    5. 验证没有设置输入状态

    为什么重要：
    -----------
    - 确保被拒绝用户无法触发任何操作
    - 防止资源浪费
    """
    channel = MatrixChannel(_make_config(allow_from=["@bob:matrix.org"]), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room")
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello", source={})

    await channel._on_message(room, event)

    # 验证消息未被处理
    assert handled == []
    # 验证没有设置输入状态
    assert client.typing_calls == []


@pytest.mark.asyncio
async def test_on_message_mention_policy_requires_mx_mentions() -> None:
    """
    测试提及策略需要 @mention

    背景说明：
    ---------
    group_policy="mention" 策略要求：
    - 在群聊中（成员数>2），只有 @mention 机器人时才会响应
    - 这防止机器人在群聊中过度响应

    m.mentions 是 Matrix 的提及元数据，
    包含被提及的用户 ID 列表。

    测试步骤：
    ---------
    1. 创建 group_policy="mention" 的 MatrixChannel
    2. 模拟群聊（3 人）中的普通消息（无 @mention）
    3. 调用 _on_message()
    4. 验证消息未被处理

    为什么重要：
    -----------
    - 防止群聊中过度响应
    - 提升用户体验
    """
    channel = MatrixChannel(_make_config(group_policy="mention"), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=3)
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello", source={"content": {}})

    await channel._on_message(room, event)

    # 验证消息未被处理
    assert handled == []
    # 验证没有设置输入状态
    assert client.typing_calls == []


@pytest.mark.asyncio
async def test_on_message_mention_policy_accepts_bot_user_mentions() -> None:
    """
    测试提及策略接受机器人 @mention

    背景说明：
    ---------
    当消息中包含对机器人的 @mention 时，
    即使在群聊中，机器人也应该响应。

    测试步骤：
    ---------
    1. 创建 group_policy="mention" 的 MatrixChannel
    2. 模拟群聊中包含 @bot 提及的消息
    3. 调用 _on_message()
    4. 验证消息被处理
    5. 验证设置了输入状态

    为什么重要：
    -----------
    - 确保用户能够主动与机器人交互
    - 验证提及检测逻辑正确工作
    """
    channel = MatrixChannel(_make_config(group_policy="mention"), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=3)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="Hello",
        source={"content": {"m.mentions": {"user_ids": ["@bot:matrix.org"]}}},
    )

    await channel._on_message(room, event)

    # 验证消息被处理
    assert handled == ["@alice:matrix.org"]
    # 验证设置了输入状态
    assert client.typing_calls == [("!room:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS)]


@pytest.mark.asyncio
async def test_on_message_mention_policy_allows_direct_room_without_mentions() -> None:
    """
    测试提及策略允许直聊房间无需 @mention

    背景说明：
    ---------
    在直聊房间（只有 2 人）中，
    即使没有 @mention，机器人也应该响应。
    因为直聊中消息显然是发给机器人的。

    测试步骤：
    ---------
    1. 创建 group_policy="mention" 的 MatrixChannel
    2. 模拟直聊房间（2 人）中的消息
    3. 调用 _on_message()
    4. 验证消息被处理

    为什么重要：
    -----------
    - 直聊中不需要 @mention，提升用户体验
    - 区分群聊和直聊的处理逻辑
    """
    channel = MatrixChannel(_make_config(group_policy="mention"), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!dm:matrix.org", display_name="DM", member_count=2)
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello", source={"content": {}})

    await channel._on_message(room, event)

    # 验证消息被处理
    assert handled == ["@alice:matrix.org"]
    # 验证设置了输入状态
    assert client.typing_calls == [("!dm:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS)]


@pytest.mark.asyncio
async def test_on_message_allowlist_policy_requires_room_id() -> None:
    """
    测试允许列表策略需要房间 ID

    背景说明：
    ---------
    group_policy="allowlist" 策略要求：
    - 只有房间 ID 在 group_allow_from 列表中才响应
    - 这比用户级别的 allow_from 更严格

    测试步骤：
    ---------
    1. 创建 group_policy="allowlist" 的 MatrixChannel
    2. 配置 group_allow_from=["!allowed:matrix.org"]
    3. 模拟来自两个房间的消息
    4. 验证只处理允许房间的消息

    为什么重要：
    -----------
    - 提供更细粒度的访问控制
    - 确保只在指定房间响应
    """
    channel = MatrixChannel(
        _make_config(group_policy="allowlist", group_allow_from=["!allowed:matrix.org"]),
        MessageBus(),
    )
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["chat_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    # 被拒绝的房间
    denied_room = SimpleNamespace(room_id="!denied:matrix.org", display_name="Denied", member_count=3)
    event = SimpleNamespace(sender="@alice:matrix.org", body="Hello", source={"content": {}})
    await channel._on_message(denied_room, event)

    # 允许的房间
    allowed_room = SimpleNamespace(
        room_id="!allowed:matrix.org",
        display_name="Allowed",
        member_count=3,
    )
    await channel._on_message(allowed_room, event)

    # 验证只处理了允许房间的消息
    assert handled == ["!allowed:matrix.org"]
    # 验证只为允许房间设置输入状态
    assert client.typing_calls == [("!allowed:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS)]


@pytest.mark.asyncio
async def test_on_message_room_mention_requires_opt_in() -> None:
    """
    测试房间提及需要主动启用

    背景说明：
    ---------
    房间提及（@room）会影响所有房间成员，
    默认情况下应该被禁用，防止滥用。
    只有显式配置 allow_room_mentions=True 时才允许。

    测试步骤：
    ---------
    1. 创建 group_policy="mention" 的 MatrixChannel
    2. 模拟群聊中的房间提及消息
    3. 验证默认情况下消息被忽略
    4. 设置 allow_room_mentions=True
    5. 验证消息被处理

    为什么重要：
    -----------
    - 防止房间提及滥用
    - 给管理员控制权
    """
    channel = MatrixChannel(_make_config(group_policy="mention"), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[str] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs["sender_id"])

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=3)
    # 房间提及事件
    room_mention_event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="Hello everyone",
        source={"content": {"m.mentions": {"room": True}}},
    )

    # 默认情况下，房间提及被忽略
    await channel._on_message(room, room_mention_event)
    assert handled == []
    assert client.typing_calls == []

    # 启用房间提及后
    channel.config.allow_room_mentions = True
    await channel._on_message(room, room_mention_event)
    assert handled == ["@alice:matrix.org"]
    assert client.typing_calls == [("!room:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS)]


@pytest.mark.asyncio
async def test_on_message_sets_thread_metadata_when_threaded_event() -> None:
    """
    测试线程事件设置线程元数据

    背景说明：
    ---------
    Matrix 支持线程回复（threaded replies），
    这是一种将回复组织成对话线程的机制。

    当收到线程消息时，需要保存线程元数据：
    - thread_root_event_id: 线程根事件 ID
    - thread_reply_to_event_id: 回复的目标事件 ID
    - event_id: 当前事件 ID

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 模拟线程消息事件（m.relates_to.rel_type = "m.thread"）
    3. 调用 _on_message()
    4. 验证元数据包含线程信息

    为什么重要：
    -----------
    - 保持对话上下文
    - 支持线程回复功能
    """
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=3)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="Hello",
        event_id="$reply1",
        source={
            "content": {
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": "$root1",
                }
            }
        },
    )

    await channel._on_message(room, event)

    assert len(handled) == 1
    metadata = handled[0]["metadata"]
    # 验证线程元数据
    assert metadata["thread_root_event_id"] == "$root1"
    assert metadata["thread_reply_to_event_id"] == "$reply1"
    assert metadata["event_id"] == "$reply1"


@pytest.mark.asyncio
async def test_on_media_message_downloads_attachment_and_sets_metadata(
    monkeypatch, tmp_path
) -> None:
    """
    测试媒体消息下载附件并设置元数据

    背景说明：
    ---------
    当收到媒体消息（图片、文件等）时，Matrix 渠道需要：
    1. 下载媒体内容到本地
    2. 保存媒体路径到消息元数据
    3. 添加附件信息到元数据

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 模拟媒体消息事件（m.image 类型）
    3. 调用 _on_media_message()
    4. 验证调用了 download()
    5. 验证媒体文件被保存
    6. 验证元数据包含附件信息

    为什么重要：
    -----------
    - 支持媒体消息处理
    - 确保附件信息正确传递
    """
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.download_bytes = b"image"
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="photo.png",
        url="mxc://example.org/mediaid",
        event_id="$event1",
        source={
            "content": {
                "msgtype": "m.image",
                "info": {"mimetype": "image/png", "size": 5},
            }
        },
    )

    await channel._on_media_message(room, event)

    # 验证调用了下载
    assert len(client.download_calls) == 1
    assert len(handled) == 1
    # 验证设置了输入状态
    assert client.typing_calls == [("!room:matrix.org", True, TYPING_NOTICE_TIMEOUT_MS)]

    # 验证媒体文件被保存
    media_paths = handled[0]["media"]
    assert isinstance(media_paths, list) and len(media_paths) == 1
    media_path = Path(media_paths[0])
    assert media_path.is_file()
    assert media_path.read_bytes() == b"image"

    # 验证元数据包含附件信息
    metadata = handled[0]["metadata"]
    attachments = metadata["attachments"]
    assert isinstance(attachments, list) and len(attachments) == 1
    assert attachments[0]["type"] == "image"
    assert attachments[0]["mxc_url"] == "mxc://example.org/mediaid"
    assert attachments[0]["path"] == str(media_path)
    # 验证消息内容包含附件标记
    assert "[attachment: " in handled[0]["content"]


@pytest.mark.asyncio
async def test_on_media_message_sets_thread_metadata_when_threaded_event(
    monkeypatch, tmp_path
) -> None:
    """
    测试线程媒体事件设置线程元数据

    背景说明：
    ---------
    媒体消息也可以是线程回复的一部分。
    这个测试验证线程媒体消息的元数据处理。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 模拟线程媒体消息事件
    3. 调用 _on_media_message()
    4. 验证元数据包含线程信息

    为什么重要：
    -----------
    - 支持线程中的媒体消息
    - 保持对话上下文
    """
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.download_bytes = b"image"
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="photo.png",
        url="mxc://example.org/mediaid",
        event_id="$event1",
        source={
            "content": {
                "msgtype": "m.image",
                "info": {"mimetype": "image/png", "size": 5},
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": "$root1",
                },
            }
        },
    )

    await channel._on_media_message(room, event)

    assert len(handled) == 1
    metadata = handled[0]["metadata"]
    # 验证线程元数据
    assert metadata["thread_root_event_id"] == "$root1"
    assert metadata["thread_reply_to_event_id"] == "$event1"
    assert metadata["event_id"] == "$event1"


@pytest.mark.asyncio
async def test_on_media_message_respects_declared_size_limit(
    monkeypatch, tmp_path
) -> None:
    """
    测试媒体消息尊重声明的大小限制

    背景说明：
    ---------
    为了防止下载过大的文件，系统设置了 max_media_bytes 限制。
    当媒体文件超过限制时，应该拒绝下载。

    测试步骤：
    ---------
    1. 创建 max_media_bytes=3 的 MatrixChannel
    2. 模拟大小为 10 的媒体消息
    3. 调用 _on_media_message()
    4. 验证没有调用 download()
    5. 验证返回错误消息

    为什么重要：
    -----------
    - 防止下载过大文件
    - 保护系统资源
    """
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    channel = MatrixChannel(_make_config(max_media_bytes=3), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="large.bin",
        url="mxc://example.org/large",
        event_id="$event2",
        source={"content": {"msgtype": "m.file", "info": {"size": 10}}},
    )

    await channel._on_media_message(room, event)

    # 验证没有下载
    assert client.download_calls == []
    assert len(handled) == 1
    # 验证没有附件
    assert handled[0]["media"] == []
    assert handled[0]["metadata"]["attachments"] == []
    # 验证返回错误消息
    assert "[attachment: large.bin - too large]" in handled[0]["content"]


@pytest.mark.asyncio
async def test_on_media_message_uses_server_limit_when_smaller_than_local_limit(
    monkeypatch, tmp_path
) -> None:
    """
    测试当服务器限制小于本地限制时使用服务器限制

    背景说明：
    ---------
    Matrix 服务器可能有自己的上传大小限制。
    系统应该使用服务器限制和本地限制中的较小值。

    测试步骤：
    ---------
    1. 创建 max_media_bytes=10 的 MatrixChannel
    2. Mock 服务器限制为 3
    3. 模拟大小为 5 的媒体消息
    4. 验证因为 5 > 3（服务器限制），拒绝下载

    为什么重要：
    -----------
    - 尊重服务器限制
    - 避免上传失败
    """
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    channel = MatrixChannel(_make_config(max_media_bytes=10), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.content_repository_config_response = SimpleNamespace(upload_size=3)
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="large.bin",
        url="mxc://example.org/large",
        event_id="$event2_server",
        source={"content": {"msgtype": "m.file", "info": {"size": 5}}},
    )

    await channel._on_media_message(room, event)

    # 验证没有下载
    assert client.download_calls == []
    assert len(handled) == 1
    # 验证没有附件
    assert handled[0]["media"] == []
    assert handled[0]["metadata"]["attachments"] == []
    # 验证返回错误消息
    assert "[attachment: large.bin - too large]" in handled[0]["content"]


@pytest.mark.asyncio
async def test_on_media_message_handles_download_error(monkeypatch, tmp_path) -> None:
    """
    测试处理下载错误

    背景说明：
    ---------
    下载媒体文件可能失败（网络错误、权限问题等）。
    系统需要优雅地处理下载错误，不崩溃。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 模拟下载返回 DownloadError
    3. 调用 _on_media_message()
    4. 验证返回错误消息

    为什么重要：
    -----------
    - 提高系统鲁棒性
    - 优雅处理错误
    """
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.download_response = matrix_module.DownloadError("download failed")
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="photo.png",
        url="mxc://example.org/mediaid",
        event_id="$event3",
        source={"content": {"msgtype": "m.image"}},
    )

    await channel._on_media_message(room, event)

    # 验证调用了下载
    assert len(client.download_calls) == 1
    assert len(handled) == 1
    # 验证没有附件
    assert handled[0]["media"] == []
    assert handled[0]["metadata"]["attachments"] == []
    # 验证返回错误消息
    assert "[attachment: photo.png - download failed]" in handled[0]["content"]


@pytest.mark.asyncio
async def test_on_media_message_decrypts_encrypted_media(monkeypatch, tmp_path) -> None:
    """
    测试解密加密媒体

    背景说明：
    ---------
    在启用了 E2EE 的房间中，媒体文件是加密的。
    下载后需要解密才能使用。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 模拟加密媒体事件（包含 key, hashes, iv）
    3. Mock decrypt_attachment 函数
    4. 调用 _on_media_message()
    5. 验证文件被解密
    6. 验证元数据标记为加密

    为什么重要：
    -----------
    - 支持加密房间
    - 确保媒体可用性
    """
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        matrix_module,
        "decrypt_attachment",
        lambda ciphertext, key, sha256, iv: b"plain",
    )

    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.download_bytes = b"cipher"
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="secret.txt",
        url="mxc://example.org/encrypted",
        event_id="$event4",
        key={"k": "key"},
        hashes={"sha256": "hash"},
        iv="iv",
        source={"content": {"msgtype": "m.file", "info": {"size": 6}}},
    )

    await channel._on_media_message(room, event)

    assert len(handled) == 1
    # 验证文件被解密
    media_path = Path(handled[0]["media"][0])
    assert media_path.read_bytes() == b"plain"
    # 验证元数据标记为加密
    attachment = handled[0]["metadata"]["attachments"][0]
    assert attachment["encrypted"] is True
    assert attachment["size_bytes"] == 5


@pytest.mark.asyncio
async def test_on_media_message_handles_decrypt_error(monkeypatch, tmp_path) -> None:
    """
    测试处理解密错误

    背景说明：
    ---------
    解密可能失败（密钥错误、数据损坏等）。
    系统需要优雅地处理解密错误。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. Mock decrypt_attachment 抛出异常
    3. 调用 _on_media_message()
    4. 验证返回错误消息

    为什么重要：
    -----------
    - 提高系统鲁棒性
    - 优雅处理错误
    """
    monkeypatch.setattr("nanobot.channels.matrix.get_data_dir", lambda: tmp_path)

    def _raise(*args, **kwargs):
        raise matrix_module.EncryptionError("boom")

    monkeypatch.setattr(matrix_module, "decrypt_attachment", _raise)

    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.download_bytes = b"cipher"
    channel.client = client

    handled: list[dict[str, object]] = []

    async def _fake_handle_message(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = _fake_handle_message  # type: ignore[method-assign]

    room = SimpleNamespace(room_id="!room:matrix.org", display_name="Test room", member_count=2)
    event = SimpleNamespace(
        sender="@alice:matrix.org",
        body="secret.txt",
        url="mxc://example.org/encrypted",
        event_id="$event5",
        key={"k": "key"},
        hashes={"sha256": "hash"},
        iv="iv",
        source={"content": {"msgtype": "m.file"}},
    )

    await channel._on_media_message(room, event)

    assert len(handled) == 1
    # 验证没有附件
    assert handled[0]["media"] == []
    assert handled[0]["metadata"]["attachments"] == []
    # 验证返回错误消息
    assert "[attachment: secret.txt - download failed]" in handled[0]["content"]


@pytest.mark.asyncio
async def test_send_clears_typing_after_send() -> None:
    """
    测试发送后清除输入状态

    背景说明：
    ---------
    发送消息后，应该清除输入状态，
    否则用户会一直看到"正在输入"指示器。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 调用 send() 发送消息
    3. 验证发送了消息
    4. 验证清除了输入状态（typing=False）

    为什么重要：
    -----------
    - 提升用户体验
    - 正确的状态管理
    """
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    await channel.send(
        OutboundMessage(channel="matrix", chat_id="!room:matrix.org", content="Hi")
    )

    # 验证发送了消息
    assert len(client.room_send_calls) == 1
    # 验证消息内容正确
    assert client.room_send_calls[0]["content"] == {
        "msgtype": "m.text",
        "body": "Hi",
        "m.mentions": {},
    }
    # 验证忽略未验证设备
    assert client.room_send_calls[0]["ignore_unverified_devices"] is True
    # 验证清除了输入状态
    assert client.typing_calls[-1] == ("!room:matrix.org", False, TYPING_NOTICE_TIMEOUT_MS)


@pytest.mark.asyncio
async def test_send_uploads_media_and_sends_file_event(tmp_path) -> None:
    """
    测试上传媒体并发送文件事件

    背景说明：
    ---------
    发送带媒体的消息时，需要：
    1. 上传文件到服务器
    2. 发送文件事件（包含文件 URL）
    3. 发送文本消息

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 创建测试文件
    3. 调用 send() 发送带媒体的消息
    4. 验证调用了 upload()
    5. 验证发送了文件事件和文本消息

    为什么重要：
    -----------
    - 支持媒体消息发送
    - 验证完整流程
    """
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    file_path = tmp_path / "test.txt"
    file_path.write_text("hello", encoding="utf-8")

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="Please review.",
            media=[str(file_path)],
        )
    )

    # 验证调用了上传
    assert len(client.upload_calls) == 1
    # 验证 data_provider 不是 bytes 类型（应该是可读对象）
    assert not isinstance(client.upload_calls[0]["data_provider"], (bytes, bytearray))
    assert hasattr(client.upload_calls[0]["data_provider"], "read")
    assert client.upload_calls[0]["filename"] == "test.txt"
    assert client.upload_calls[0]["filesize"] == 5
    # 验证发送了 2 条消息（文件 + 文本）
    assert len(client.room_send_calls) == 2
    assert client.room_send_calls[0]["content"]["msgtype"] == "m.file"
    assert client.room_send_calls[0]["content"]["url"] == "mxc://example.org/uploaded"
    assert client.room_send_calls[1]["content"]["body"] == "Please review."


@pytest.mark.asyncio
async def test_send_adds_thread_relates_to_for_thread_metadata() -> None:
    """
    测试为线程元数据添加关联关系

    背景说明：
    ---------
    发送线程回复时，需要添加 m.relates_to 元数据，
    指定线程根事件和回复目标事件。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 创建带线程元数据的消息
    3. 调用 send()
    4. 验证消息包含正确的 m.relates_to

    为什么重要：
    -----------
    - 支持线程回复
    - 保持对话结构
    """
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    metadata = {
        "thread_root_event_id": "$root1",
        "thread_reply_to_event_id": "$reply1",
    }
    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="Hi",
            metadata=metadata,
        )
    )

    content = client.room_send_calls[0]["content"]
    # 验证线程关联关系
    assert content["m.relates_to"] == {
        "rel_type": "m.thread",
        "event_id": "$root1",
        "m.in_reply_to": {"event_id": "$reply1"},
        "is_falling_back": True,
    }


@pytest.mark.asyncio
async def test_send_uses_encrypted_media_payload_in_encrypted_room(tmp_path) -> None:
    """
    测试在加密房间中使用加密媒体负载

    背景说明：
    ---------
    在加密房间中，媒体文件需要加密上传，
    并使用加密的文件负载格式（不是简单的 URL）。

    测试步骤：
    ---------
    1. 创建 e2ee_enabled=True 的 MatrixChannel
    2. 模拟加密房间
    3. 创建测试文件
    4. 调用 send() 发送媒体消息
    5. 验证上传时 encrypt=True
    6. 验证消息使用"file"字段（不是"url"）

    为什么重要：
    -----------
    - 支持加密房间的媒体发送
    - 确保媒体加密
    """
    channel = MatrixChannel(_make_config(e2ee_enabled=True), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.rooms["!encrypted:matrix.org"] = SimpleNamespace(encrypted=True)
    channel.client = client

    file_path = tmp_path / "secret.txt"
    file_path.write_text("topsecret", encoding="utf-8")

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!encrypted:matrix.org",
            content="",
            media=[str(file_path)],
        )
    )

    # 验证加密上传
    assert len(client.upload_calls) == 1
    assert client.upload_calls[0]["encrypt"] is True
    # 验证发送了加密消息
    assert len(client.room_send_calls) == 1
    content = client.room_send_calls[0]["content"]
    assert content["msgtype"] == "m.file"
    # 加密消息使用"file"字段而不是"url"
    assert "file" in content
    assert "url" not in content
    assert content["file"]["url"] == "mxc://example.org/uploaded"
    assert content["file"]["hashes"]["sha256"] == "hash"


@pytest.mark.asyncio
async def test_send_does_not_parse_attachment_marker_without_media(tmp_path) -> None:
    """
    测试无媒体时不解析附件标记

    背景说明：
    ---------
    消息内容可能包含 [attachment: ...] 标记，
    但只有在实际有 media 参数时才解析。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 发送包含附件标记但无 media 的消息
    3. 验证没有调用 upload()
    4. 验证消息原样发送

    为什么重要：
    -----------
    - 防止错误解析
    - 确保行为一致
    """
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    missing_path = tmp_path / "missing.txt"
    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content=f"[attachment: {missing_path}]",
        )
    )

    # 验证没有上传
    assert client.upload_calls == []
    # 验证消息原样发送
    assert len(client.room_send_calls) == 1
    assert client.room_send_calls[0]["content"]["body"] == f"[attachment: {missing_path}]"


@pytest.mark.asyncio
async def test_send_passes_thread_relates_to_to_attachment_upload(monkeypatch) -> None:
    """
    测试传递线程关联关系到附件上传

    背景说明：
    ---------
    上传线程中的附件时，需要传递线程关联关系，
    确保附件也属于正确的线程。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. Mock _upload_and_send_attachment
    3. 创建带线程元数据的消息
    4. 调用 send()
    5. 验证 relates_to 参数正确传递

    为什么重要：
    -----------
    - 支持线程中的附件
    - 保持对话结构
    """
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client
    channel._server_upload_limit_checked = True
    channel._server_upload_limit_bytes = None

    captured: dict[str, object] = {}

    async def _fake_upload_and_send_attachment(
        *,
        room_id: str,
        path: Path,
        limit_bytes: int,
        relates_to: dict[str, object] | None = None,
    ) -> str | None:
        captured["relates_to"] = relates_to
        return None

    monkeypatch.setattr(channel, "_upload_and_send_attachment", _fake_upload_and_send_attachment)

    metadata = {
        "thread_root_event_id": "$root1",
        "thread_reply_to_event_id": "$reply1",
    }
    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="Hi",
            media=["/tmp/fake.txt"],
            metadata=metadata,
        )
    )

    # 验证线程关联关系被传递
    assert captured["relates_to"] == {
        "rel_type": "m.thread",
        "event_id": "$root1",
        "m.in_reply_to": {"event_id": "$reply1"},
        "is_falling_back": True,
    }


@pytest.mark.asyncio
async def test_send_workspace_restriction_blocks_external_attachment(tmp_path) -> None:
    """
    测试工作区限制阻止外部附件

    背景说明：
    ---------
    当配置 restrict_to_workspace=True 时，
    只能上传工作区内的文件，防止泄露外部文件。

    测试步骤：
    ---------
    1. 创建工作区目录
    2. 创建外部文件（工作区外）
    3. 创建 restrict_to_workspace=True 的 MatrixChannel
    4. 调用 send() 发送外部文件
    5. 验证没有上传
    6. 验证返回错误消息

    为什么重要：
    -----------
    - 保护文件安全
    - 防止泄露外部文件
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file_path = tmp_path / "external.txt"
    file_path.write_text("outside", encoding="utf-8")

    channel = MatrixChannel(
        _make_config(),
        MessageBus(),
        restrict_to_workspace=True,
        workspace=workspace,
    )
    client = _FakeAsyncClient("", "", "", None)
    channel.client = client

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="",
            media=[str(file_path)],
        )
    )

    # 验证没有上传
    assert client.upload_calls == []
    # 验证返回错误消息
    assert len(client.room_send_calls) == 1
    assert client.room_send_calls[0]["content"]["body"] == "[attachment: external.txt - upload failed]"


@pytest.mark.asyncio
async def test_send_handles_upload_exception_and_reports_failure(tmp_path) -> None:
    """
    测试处理上传异常并报告失败

    背景说明：
    ---------
    上传可能失败（网络错误、服务器错误等）。
    系统需要优雅地处理上传异常，并通知用户。

    测试步骤：
    ---------
    1. 创建 MatrixChannel 实例
    2. 设置 raise_on_upload=True
    3. 创建测试文件
    4. 调用 send() 发送媒体消息
    5. 验证没有上传调用
    6. 验证返回错误消息

    为什么重要：
    -----------
    - 提高系统鲁棒性
    - 通知用户上传失败
    """
    channel = MatrixChannel(_make_config(), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.raise_on_upload = True
    channel.client = client

    file_path = tmp_path / "broken.txt"
    file_path.write_text("hello", encoding="utf-8")

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="Please review.",
            media=[str(file_path)],
        )
    )

    # 验证没有上传调用
    assert len(client.upload_calls) == 0
    # 验证发送了文本消息和错误消息
    assert len(client.room_send_calls) == 1
    assert (
        client.room_send_calls[0]["content"]["body"]
        == "Please review.\n[attachment: broken.txt - upload failed]"
    )


@pytest.mark.asyncio
async def test_send_uses_server_upload_limit_when_smaller_than_local_limit(tmp_path) -> None:
    """
    测试当服务器上传限制小于本地限制时使用服务器限制

    背景说明：
    ---------
    Matrix 服务器可能有自己的上传大小限制。
    系统应该使用服务器限制和本地限制中的较小值。

    测试步骤：
    ---------
    1. 创建 max_media_bytes=10 的 MatrixChannel
    2. Mock 服务器限制为 3
    3. 创建大小为 5 的测试文件
    4. 调用 send() 发送媒体消息
    5. 验证因为 5 > 3（服务器限制），没有上传

    为什么重要：
    -----------
    - 尊重服务器限制
    - 避免上传失败
    """
    channel = MatrixChannel(_make_config(max_media_bytes=10), MessageBus())
    client = _FakeAsyncClient("", "", "", None)
    client.content_repository_config_response = SimpleNamespace(upload_size=3)
    channel.client = client

    file_path = tmp_path / "tiny.txt"
    file_path.write_text("hello", encoding="utf-8")

    await channel.send(
        OutboundMessage(
            channel="matrix",
            chat_id="!room:matrix.org",
            content="",
            media=[str(file_path)],
        )
    )

    # 验证没有上传
    assert client.upload_calls == []
    # 验证发送了错误消息
    assert len(client.room_send_calls) == 1

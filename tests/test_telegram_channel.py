# =============================================================================
# nanobot Telegram 渠道测试
# 文件路径：tests/test_telegram_channel.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件测试了 nanobot 的 Telegram 渠道（TelegramChannel）功能。
# Telegram 渠道是 nanobot 与 Telegram 平台集成的接口模块。
#
# 测试的核心功能：
# -------------------------
# - 测试 Telegram 渠道启动时的代理配置
# - 测试主题（topic）会话密钥的生成
# - 测试文件扩展名获取逻辑
# - 测试群组策略（group_policy）配置
# - 测试用户权限验证（is_allowed）
# - 测试消息发送时的线程处理
# - 测试回复消息的上下文提取
# - 测试媒体文件下载功能
# - 测试斜杠命令转发
#
# 关键测试场景：
# -------------------------
# 1. 代理配置：验证启动时使用 HTTPXRequest 配置代理
# 2. 主题会话：验证从消息 ID 缓存推断主题线程 ID
# 3. 群组策略 mention：验证只有提及机器人时才处理消息
# 4. 群组策略 open：验证处理所有群消息
# 5. 回复上下文：验证提取回复消息的文本/说明作为上下文
# 6. 媒体下载：验证下载回复消息中的媒体文件
# 7. 命令转发：验证斜杠命令不包含回复上下文
#
# 使用示例：
# -------------------------
# 运行测试：pytest tests/test_telegram_channel.py -v
#
# 相关模块：
# - nanobot/channels/telegram.py - Telegram 渠道实现
# - nanobot/config/schema.py - TelegramConfig 配置类
#
# Telegram 渠道说明：
# -------------------------
# Telegram 渠道支持多种消息类型：
# - 私聊消息（Direct Message）
# - 群聊消息（Group/Supergroup）
# - 频道消息（Channel）
# - 主题消息（Topics，超级群组的线程功能）
#
# group_policy 配置说明：
# - "mention"（默认）：只有当消息提及机器人时才处理
# - "open"：处理所有群消息
# - "off"：不处理任何群消息
#
# TELEGRAM_REPLY_CONTEXT_MAX_LEN：
# - 回复消息上下文的最大长度（默认为 200 字符）
# - 超过长度的回复内容会被截断
# =============================================================================

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.telegram import TELEGRAM_REPLY_CONTEXT_MAX_LEN, TelegramChannel
from nanobot.config.schema import TelegramConfig


class _FakeHTTPXRequest:
    """
    伪造的 HTTPXRequest 类

    用于替代 python-telegram-bot 使用的 HTTPXRequest
    记录所有实例化调用，验证代理配置是否正确传递
    """
    # 类变量，记录所有实例
    instances: list["_FakeHTTPXRequest"] = []

    def __init__(self, **kwargs) -> None:
        # 保存初始化参数，用于验证
        self.kwargs = kwargs
        # 将实例添加到记录列表
        self.__class__.instances.append(self)


class _FakeUpdater:
    """
    伪造的 Updater 类

    模拟 python-telegram-bot 的 Updater
    用于控制轮询启动行为
    """

    def __init__(self, on_start_polling) -> None:
        # 保存启动轮询时的回调函数
        self._on_start_polling = on_start_polling

    async def start_polling(self, **kwargs) -> None:
        """启动轮询时调用回调函数"""
        self._on_start_polling()


class _FakeBot:
    """
    伪造的 Bot 类

    模拟 python-telegram-bot 的 Bot
    记录所有 API 调用以便验证
    """

    def __init__(self) -> None:
        # 记录所有发送的消息
        self.sent_messages: list[dict] = []
        # 记录 get_me() 调用次数
        self.get_me_calls = 0

    async def get_me(self):
        """
        获取机器人自身信息

        返回伪造的机器人信息：
        - id: 999（机器人 ID）
        - username: nanobot_test（机器人用户名）
        """
        self.get_me_calls += 1
        return SimpleNamespace(id=999, username="nanobot_test")

    async def set_my_commands(self, commands) -> None:
        """设置机器人命令列表"""
        self.commands = commands

    async def send_message(self, **kwargs) -> None:
        """发送消息，记录调用参数"""
        self.sent_messages.append(kwargs)

    async def send_chat_action(self, **kwargs) -> None:
        """发送聊天动作（如"typing"），空实现"""
        pass

    async def get_file(self, file_id: str):
        """
        获取文件对象（用于回复消息中的媒体下载）

        返回一个伪造的文件对象，包含 download_to_drive 方法
        """
        async def _fake_download(path) -> None:
            pass
        return SimpleNamespace(download_to_drive=_fake_download)


class _FakeApp:
    """
    伪造的 Application 类

    模拟 python-telegram-bot 的 Application
    包含 Bot 和 Updater 实例
    """

    def __init__(self, on_start_polling) -> None:
        self.bot = _FakeBot()
        self.updater = _FakeUpdater(on_start_polling)
        # 记录注册的消息处理器
        self.handlers = []
        # 记录注册的错误处理器
        self.error_handlers = []

    def add_error_handler(self, handler) -> None:
        """添加错误处理器"""
        self.error_handlers.append(handler)

    def add_handler(self, handler) -> None:
        """添加消息处理器"""
        self.handlers.append(handler)

    async def initialize(self) -> None:
        """初始化应用，空实现"""
        pass

    async def start(self) -> None:
        """启动应用，空实现"""
        pass


class _FakeBuilder:
    """
    伪造的 ApplicationBuilder 类

    模拟 python-telegram-bot 的 ApplicationBuilder
    用于验证代理配置方式
    """

    def __init__(self, app: _FakeApp) -> None:
        self.app = app
        self.token_value = None
        self.request_value = None
        self.get_updates_request_value = None

    def token(self, token: str):
        """设置 Bot Token"""
        self.token_value = token
        return self

    def request(self, request):
        """设置主请求对象（用于发送消息）"""
        self.request_value = request
        return self

    def get_updates_request(self, request):
        """设置获取更新的请求对象（用于长轮询）"""
        self.get_updates_request_value = request
        return self

    def proxy(self, _proxy):
        """
        设置代理

        这个测试期望当已经设置 request 时，proxy 不应该被调用
        所以这里抛出断言错误
        """
        raise AssertionError("builder.proxy should not be called when request is set")

    def get_updates_proxy(self, _proxy):
        """
        设置获取更新的代理

        同样期望不被调用
        """
        raise AssertionError("builder.get_updates_proxy should not be called when request is set")

    def build(self):
        """构建并返回 Application 实例"""
        return self.app


def _make_telegram_update(
    *,
    chat_type: str = "group",
    text: str | None = None,
    caption: str | None = None,
    entities=None,
    caption_entities=None,
    reply_to_message=None,
):
    """
    辅助函数：构造一个伪造的 Telegram Update 对象

    参数：
        chat_type: 聊天类型（"group", "supergroup", "private" 等）
        text: 消息文本内容
        caption: 媒体附件的说明文字
        entities: 文本实体列表（如 @mention）
        caption_entities: 说明文字实体列表
        reply_to_message: 被回复的消息对象

    返回：
        SimpleNamespace: 模拟的 Update 对象，包含 message 和 effective_user
    """
    # 创建用户对象
    user = SimpleNamespace(id=12345, username="alice", first_name="Alice")
    # 创建消息对象
    message = SimpleNamespace(
        chat=SimpleNamespace(type=chat_type, is_forum=False),
        chat_id=-100123,
        text=text,
        caption=caption,
        entities=entities or [],
        caption_entities=caption_entities or [],
        reply_to_message=reply_to_message,
        photo=None,
        voice=None,
        audio=None,
        document=None,
        media_group_id=None,
        message_thread_id=None,
        message_id=1,
    )
    return SimpleNamespace(message=message, effective_user=user)


@pytest.mark.asyncio
async def test_start_uses_request_proxy_without_builder_proxy(monkeypatch) -> None:
    """
    测试 Telegram 渠道启动时使用 HTTPXRequest 配置代理，而不是使用 builder.proxy

    验证点：
    - HTTPXRequest 被实例化一次
    - HTTPXRequest 的 proxy 参数等于配置的代理地址
    - builder.request 和 builder.get_updates_request 被设置

    为什么这样做？
    - python-telegram-bot v20+ 使用 HTTPXRequest 配置网络和代理
    - 不应再使用旧版的 builder.proxy 方式
    """
    # 创建 Telegram 配置，启用代理
    config = TelegramConfig(
        enabled=True,
        token="123:abc",
        allow_from=["*"],
        proxy="http://127.0.0.1:7890",
    )
    bus = MessageBus()
    channel = TelegramChannel(config, bus)
    # 创建伪造的 App，启动轮询时停止渠道
    app = _FakeApp(lambda: setattr(channel, "_running", False))
    builder = _FakeBuilder(app)

    # 使用 monkeypatch 替换 HTTPXRequest 和 Application
    monkeypatch.setattr("nanobot.channels.telegram.HTTPXRequest", _FakeHTTPXRequest)
    monkeypatch.setattr(
        "nanobot.channels.telegram.Application",
        SimpleNamespace(builder=lambda: builder),
    )

    # 启动渠道
    await channel.start()

    # 验证 HTTPXRequest 被实例化了一次
    assert len(_FakeHTTPXRequest.instances) == 1
    # 验证代理地址正确传递
    assert _FakeHTTPXRequest.instances[0].kwargs["proxy"] == config.proxy
    # 验证 builder.request 被设置
    assert builder.request_value is _FakeHTTPXRequest.instances[0]
    # 验证 builder.get_updates_request 被设置
    assert builder.get_updates_request_value is _FakeHTTPXRequest.instances[0]


def test_derive_topic_session_key_uses_thread_id() -> None:
    """
    测试从 Telegram 消息派生主题（topic）会话密钥时使用 thread_id

    验证点：
    - 会话密钥格式为 "telegram:{chat_id}:topic:{thread_id}"

    Telegram Topic 说明：
    - Telegram 超级群组支持 Topic（话题）功能
    - 每个 Topic 有独立的 message_thread_id
    - 会话密钥用于在同一个 Topic 内保持对话上下文
    """
    message = SimpleNamespace(
        chat=SimpleNamespace(type="supergroup"),
        chat_id=-100123,
        message_thread_id=42,
    )

    # 验证会话密钥格式正确
    assert TelegramChannel._derive_topic_session_key(message) == "telegram:-100123:topic:42"


def test_get_extension_falls_back_to_original_filename() -> None:
    """
    测试获取文件扩展名时回退到原始文件名

    验证点：
    - 当 mime_type 为 None 时，从文件名提取扩展名
    - 支持复合扩展名（如 .tar.gz）
    """
    channel = TelegramChannel(TelegramConfig(), MessageBus())

    # 验证普通扩展名提取
    assert channel._get_extension("file", None, "report.pdf") == ".pdf"
    # 验证复合扩展名提取
    assert channel._get_extension("file", None, "archive.tar.gz") == ".tar.gz"


def test_telegram_group_policy_defaults_to_mention() -> None:
    """
    测试 TelegramConfig 的 group_policy 默认值为 "mention"

    验证点：
    - 不指定 group_policy 时，默认为 "mention"
    - "mention" 策略：只有当消息提及机器人时才处理
    """
    assert TelegramConfig().group_policy == "mention"


def test_is_allowed_accepts_legacy_telegram_id_username_formats() -> None:
    """
    测试 is_allowed 方法接受旧版 Telegram ID/用户名格式

    验证点：
    - 允许列表中只有数字 ID（如 "12345"）：匹配任意该 ID 的用户
    - 允许列表中只有用户名（如 "alice"）：匹配任意该用户名的用户
    - 允许列表中有 "ID|username" 格式：精确匹配

    Telegram 用户标识格式说明：
    - 旧版格式："{user_id}|{username}"（如 "12345|alice"）
    - 只填 ID：允许该 ID 的所有用户（不管用户名变化）
    - 只填用户名：允许该用户名的所有用户（不管 ID 变化）
    """
    # 创建允许列表包含多种格式
    channel = TelegramChannel(TelegramConfig(allow_from=["12345", "alice", "67890|bob"]), MessageBus())

    # 验证：允许列表中只有 ID "12345"，输入 "12345|carol" 应该通过（ID 匹配）
    assert channel.is_allowed("12345|carol") is True
    # 验证：允许列表中只有用户名 "alice"，输入 "99999|alice" 应该通过（用户名匹配）
    assert channel.is_allowed("99999|alice") is True
    # 验证：允许列表中有 "67890|bob"，输入完全匹配才通过
    assert channel.is_allowed("67890|bob") is True


def test_is_allowed_rejects_invalid_legacy_telegram_sender_shapes() -> None:
    """
    测试 is_allowed 方法拒绝无效的旧版 Telegram 发送者格式

    验证点：
    - 格式 "attacker|alice|extra"（多段）应该被拒绝
    - 格式 "not-a-number|alice"（ID 不是数字）应该被拒绝
    """
    # 创建允许列表只包含用户名 "alice"
    channel = TelegramChannel(TelegramConfig(allow_from=["alice"]), MessageBus())

    # 验证：多段格式应该被拒绝
    assert channel.is_allowed("attacker|alice|extra") is False
    # 验证：ID 不是数字应该被拒绝
    assert channel.is_allowed("not-a-number|alice") is False


@pytest.mark.asyncio
async def test_send_progress_keeps_message_in_topic() -> None:
    """
    测试发送进度消息时保持在同一个主题（topic）线程中

    验证点：
    - 进度消息的 message_thread_id 正确传递

    测试场景：
    - 当 metadata 包含 "_progress": True 和 message_thread_id 时
    - 发送的消息应该保持相同的 message_thread_id
    """
    config = TelegramConfig(enabled=True, token="123:abc", allow_from=["*"])
    channel = TelegramChannel(config, MessageBus())
    channel._app = _FakeApp(lambda: None)

    # 发送进度消息
    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="hello",
            metadata={"_progress": True, "message_thread_id": 42},
        )
    )

    # 验证发送的消息保持了 message_thread_id
    assert channel._app.bot.sent_messages[0]["message_thread_id"] == 42


@pytest.mark.asyncio
async def test_send_reply_infers_topic_from_message_id_cache() -> None:
    """
    测试发送回复消息时从消息 ID 缓存推断主题线程 ID

    验证点：
    - message_thread_id 从缓存中正确获取
    - reply_parameters.message_id 正确设置

    测试场景：
    - 配置 reply_to_message=True
    - _message_threads 缓存了 (chat_id, message_id) -> thread_id 的映射
    - 发送回复时应该从缓存中获取 thread_id
    """
    # 配置回复功能
    config = TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], reply_to_message=True)
    channel = TelegramChannel(config, MessageBus())
    channel._app = _FakeApp(lambda: None)
    # 设置缓存：chat_id="123", message_id=10 对应的 thread_id=42
    channel._message_threads[("123", 10)] = 42

    # 发送回复消息
    await channel.send(
        OutboundMessage(
            channel="telegram",
            chat_id="123",
            content="hello",
            metadata={"message_id": 10},  # 回复的消息 ID
        )
    )

    # 验证从缓存中获取了正确的 thread_id
    assert channel._app.bot.sent_messages[0]["message_thread_id"] == 42
    # 验证回复参数正确设置
    assert channel._app.bot.sent_messages[0]["reply_parameters"].message_id == 10


@pytest.mark.asyncio
async def test_group_policy_mention_ignores_unmentioned_group_message() -> None:
    """
    测试群组策略为 "mention" 时，忽略未提及机器人的群消息

    验证点：
    - 没有提及机器人的消息不被处理
    - get_me() 被调用一次（获取机器人用户名用于匹配）

    测试场景：
    - group_policy="mention"
    - 消息内容 "hello everyone" 没有 @mention
    - 预期不被处理
    """
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="mention"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    handled = []

    async def capture_handle(**kwargs) -> None:
        """捕获 _handle_message 调用"""
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    # 发送未提及机器人的消息
    await channel._on_message(_make_telegram_update(text="hello everyone"), None)

    # 验证消息未被处理
    assert handled == []
    # 验证 get_me() 被调用了一次（获取机器人用户名）
    assert channel._app.bot.get_me_calls == 1


@pytest.mark.asyncio
async def test_group_policy_mention_accepts_text_mention_and_caches_bot_identity() -> None:
    """
    测试群组策略为 "mention" 时，接受文本提及（@mention）并缓存机器人身份

    验证点：
    - 提及机器人的消息被处理
    - get_me() 只被调用一次（缓存机器人身份）
    - 两次提及都能正确处理

    测试场景：
    - group_policy="mention"
    - 消息内容 "@nanobot_test hi" 包含 @mention
    - 连续两次提及都应该被处理
    """
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="mention"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    # 创建提及实体（@nanobot_test 占 13 个字符）
    mention = SimpleNamespace(type="mention", offset=0, length=13)
    # 第一次提及
    await channel._on_message(_make_telegram_update(text="@nanobot_test hi", entities=[mention]), None)
    # 第二次提及
    await channel._on_message(_make_telegram_update(text="@nanobot_test again", entities=[mention]), None)

    # 验证两次消息都被处理
    assert len(handled) == 2
    # 验证 get_me() 只调用了一次（缓存了机器人身份）
    assert channel._app.bot.get_me_calls == 1


@pytest.mark.asyncio
async def test_group_policy_mention_accepts_caption_mention() -> None:
    """
    测试群组策略为 "mention" 时，接受媒体说明文字（caption）中的提及

    验证点：
    - caption 中的 @mention 被正确识别
    - 消息内容包含完整的 caption

    测试场景：
    - 发送带有 @mention 的图片/视频
    - caption="@nanobot_test photo"
    """
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="mention"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    # 创建提及实体
    mention = SimpleNamespace(type="mention", offset=0, length=13)
    # 发送带 caption 提及的消息
    await channel._on_message(
        _make_telegram_update(caption="@nanobot_test photo", caption_entities=[mention]),
        None,
    )

    # 验证消息被处理
    assert len(handled) == 1
    # 验证消息内容正确
    assert handled[0]["content"] == "@nanobot_test photo"


@pytest.mark.asyncio
async def test_group_policy_mention_accepts_reply_to_bot() -> None:
    """
    测试群组策略为 "mention" 时，接受回复机器人的消息

    验证点：
    - 回复给机器人的消息被处理
    - reply_to_message.from_user.id 等于机器人 ID 时通过

    测试场景：
    - 用户回复机器人的消息
    - reply_to_message.from_user.id = 999（机器人 ID）
    """
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="mention"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    # 创建回复消息，from_user.id=999 是机器人
    reply = SimpleNamespace(from_user=SimpleNamespace(id=999))
    # 发送回复给机器人的消息
    await channel._on_message(_make_telegram_update(text="reply", reply_to_message=reply), None)

    # 验证消息被处理
    assert len(handled) == 1


@pytest.mark.asyncio
async def test_group_policy_open_accepts_plain_group_message() -> None:
    """
    测试群组策略为 "open" 时，接受普通群消息

    验证点：
    - 所有群消息都被处理
    - get_me() 不被调用（不需要检查是否提及机器人）

    测试场景：
    - group_policy="open"
    - 消息内容 "hello group" 没有 @mention
    - 预期被处理
    """
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)

    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    # 发送普通群消息
    await channel._on_message(_make_telegram_update(text="hello group"), None)

    # 验证消息被处理
    assert len(handled) == 1
    # 验证 get_me() 未被调用
    assert channel._app.bot.get_me_calls == 0


def test_extract_reply_context_no_reply() -> None:
    """
    测试没有回复消息时，_extract_reply_context 返回 None

    验证点：
    - reply_to_message 为 None 时返回 None
    """
    message = SimpleNamespace(reply_to_message=None)
    assert TelegramChannel._extract_reply_context(message) is None


def test_extract_reply_context_with_text() -> None:
    """
    测试回复消息有文本时，返回带前缀的字符串

    验证点：
    - 返回格式为 "[Reply to: {text}]"
    """
    reply = SimpleNamespace(text="Hello world", caption=None)
    message = SimpleNamespace(reply_to_message=reply)
    assert TelegramChannel._extract_reply_context(message) == "[Reply to: Hello world]"


def test_extract_reply_context_with_caption_only() -> None:
    """
    测试回复消息只有说明文字（caption）时，使用 caption

    验证点：
    - 当 text 为 None 但 caption 有值时，使用 caption
    """
    reply = SimpleNamespace(text=None, caption="Photo caption")
    message = SimpleNamespace(reply_to_message=reply)
    assert TelegramChannel._extract_reply_context(message) == "[Reply to: Photo caption]"


def test_extract_reply_context_truncation() -> None:
    """
    测试回复文本被截断到 TELEGRAM_REPLY_CONTEXT_MAX_LEN

    验证点：
    - 超过最大长度的文本被截断
    - 截断后添加 "..." 后缀
    - 总长度计算正确
    """
    # 创建超长文本
    long_text = "x" * (TELEGRAM_REPLY_CONTEXT_MAX_LEN + 100)
    reply = SimpleNamespace(text=long_text, caption=None)
    message = SimpleNamespace(reply_to_message=reply)
    result = TelegramChannel._extract_reply_context(message)

    # 验证结果不为空
    assert result is not None
    # 验证前缀正确
    assert result.startswith("[Reply to: ")
    # 验证有截断标记
    assert result.endswith("...]")
    # 验证总长度计算正确
    assert len(result) == len("[Reply to: ]") + TELEGRAM_REPLY_CONTEXT_MAX_LEN + len("...")


def test_extract_reply_context_no_text_returns_none() -> None:
    """
    测试回复消息没有文本/说明时，_extract_reply_context 返回 None

    验证点：
    - 纯媒体回复（无文字）返回 None
    - 媒体内容会单独处理
    """
    reply = SimpleNamespace(text=None, caption=None)
    message = SimpleNamespace(reply_to_message=reply)
    assert TelegramChannel._extract_reply_context(message) is None


@pytest.mark.asyncio
async def test_on_message_includes_reply_context() -> None:
    """
    测试用户回复消息时，传递给总线的内容包含回复上下文

    验证点：
    - 回复内容以 "[Reply to: ...]" 开头
    - 用户消息内容也包含在内

    测试场景：
    - 用户回复消息 "Hello"
    - 用户新消息 "translate this"
    - 最终内容应该包含回复上下文和新消息
    """
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    # 创建被回复的消息
    reply = SimpleNamespace(text="Hello", message_id=2, from_user=SimpleNamespace(id=1))
    # 创建包含回复的更新
    update = _make_telegram_update(text="translate this", reply_to_message=reply)
    await channel._on_message(update, None)

    # 验证处理了一次
    assert len(handled) == 1
    # 验证内容以回复上下文开头
    assert handled[0]["content"].startswith("[Reply to: Hello]")
    # 验证包含新消息内容
    assert "translate this" in handled[0]["content"]


@pytest.mark.asyncio
async def test_download_message_media_returns_path_when_download_succeeds(
    monkeypatch, tmp_path
) -> None:
    """
    测试 _download_message_media 在下载成功时返回 (paths, content_parts)

    验证点：
    - 返回的 paths 包含下载的文件路径
    - 返回的 content_parts 包含媒体描述（如 "[image: ...]"）
    - 文件路径包含 file_id

    测试场景：
    - 消息包含一张图片
    - bot.get_file 和下载都成功
    """
    # 设置媒体目录
    media_dir = tmp_path / "media" / "telegram"
    media_dir.mkdir(parents=True)
    # 模拟 get_media_dir 函数
    monkeypatch.setattr(
        "nanobot.channels.telegram.get_media_dir",
        lambda channel=None: media_dir if channel else tmp_path / "media",
    )

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"]),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    # 模拟 get_file 成功
    channel._app.bot.get_file = AsyncMock(
        return_value=SimpleNamespace(download_to_drive=AsyncMock(return_value=None))
    )

    # 创建包含图片的消息
    msg = SimpleNamespace(
        photo=[SimpleNamespace(file_id="fid123", mime_type="image/jpeg")],
        voice=None,
        audio=None,
        document=None,
        video=None,
        video_note=None,
        animation=None,
    )
    paths, parts = await channel._download_message_media(msg)

    # 验证返回了一个文件路径
    assert len(paths) == 1
    # 验证返回了一个内容部分
    assert len(parts) == 1
    # 验证文件路径包含 file_id
    assert "fid123" in paths[0]
    # 验证内容部分包含媒体类型标记
    assert "[image:" in parts[0]


@pytest.mark.asyncio
async def test_on_message_attaches_reply_to_media_when_available(monkeypatch, tmp_path) -> None:
    """
    测试用户回复带媒体的消息时，下载并附加该媒体

    验证点：
    - 回复内容以 "[Reply to: [image:...]" 开头
    - 用户消息内容包含在内
    - media 列表包含下载的文件

    测试场景：
    - 用户回复一张图片
    - 用户新消息 "what is the image?"
    - 图片应该被下载并附加
    """
    # 设置媒体目录
    media_dir = tmp_path / "media" / "telegram"
    media_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "nanobot.channels.telegram.get_media_dir",
        lambda channel=None: media_dir if channel else tmp_path / "media",
    )

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    app = _FakeApp(lambda: None)
    # 模拟 get_file 成功
    app.bot.get_file = AsyncMock(
        return_value=SimpleNamespace(download_to_drive=AsyncMock(return_value=None))
    )
    channel._app = app
    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    # 创建带图片的回复消息
    reply_with_photo = SimpleNamespace(
        text=None,
        caption=None,
        photo=[SimpleNamespace(file_id="reply_photo_fid", mime_type="image/jpeg")],
        document=None,
        voice=None,
        audio=None,
        video=None,
        video_note=None,
        animation=None,
    )
    update = _make_telegram_update(
        text="what is the image?",
        reply_to_message=reply_with_photo,
    )
    await channel._on_message(update, None)

    # 验证处理了一次
    assert len(handled) == 1
    # 验证回复内容包含媒体标记
    assert handled[0]["content"].startswith("[Reply to: [image:")
    # 验证包含用户消息
    assert "what is the image?" in handled[0]["content"]
    # 验证媒体列表包含一个文件
    assert len(handled[0]["media"]) == 1
    # 验证媒体路径包含 file_id
    assert "reply_photo_fid" in handled[0]["media"][0]


@pytest.mark.asyncio
async def test_on_message_reply_to_media_fallback_when_download_fails() -> None:
    """
    测试回复消息有媒体但下载失败时的降级处理

    验证点：
    - 没有附加媒体
    - 没有回复标签
    - 用户消息仍然被处理

    测试场景：
    - 回复消息包含图片
    - bot.get_file 为 None（下载失败）
    - 预期只处理用户消息，不附加媒体
    """
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    # 模拟 get_file 不可用
    channel._app.bot.get_file = None
    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    # 创建带图片的回复消息
    reply_with_photo = SimpleNamespace(
        text=None,
        caption=None,
        photo=[SimpleNamespace(file_id="x", mime_type="image/jpeg")],
        document=None,
        voice=None,
        audio=None,
        video=None,
        video_note=None,
        animation=None,
    )
    update = _make_telegram_update(text="what is this?", reply_to_message=reply_with_photo)
    await channel._on_message(update, None)

    # 验证处理了一次
    assert len(handled) == 1
    # 验证包含用户消息
    assert "what is this?" in handled[0]["content"]
    # 验证没有附加媒体
    assert handled[0]["media"] == []


@pytest.mark.asyncio
async def test_on_message_reply_to_caption_and_media(monkeypatch, tmp_path) -> None:
    """
    测试回复带说明文字 + 图片的消息时，同时包含文本上下文和媒体

    验证点：
    - 回复内容包含 caption 文本
    - 用户消息内容包含在内
    - media 列表包含下载的文件

    测试场景：
    - 回复消息 caption="A cute cat" + 图片
    - 用户新消息 "what breed is this?"
    - 预期 caption 和媒体都被附加
    """
    # 设置媒体目录
    media_dir = tmp_path / "media" / "telegram"
    media_dir.mkdir(parents=True)
    monkeypatch.setattr(
        "nanobot.channels.telegram.get_media_dir",
        lambda channel=None: media_dir if channel else tmp_path / "media",
    )

    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    app = _FakeApp(lambda: None)
    # 模拟 get_file 成功
    app.bot.get_file = AsyncMock(
        return_value=SimpleNamespace(download_to_drive=AsyncMock(return_value=None))
    )
    channel._app = app
    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle
    channel._start_typing = lambda _chat_id: None

    # 创建带 caption 和图片的回复消息
    reply_with_caption_and_photo = SimpleNamespace(
        text=None,
        caption="A cute cat",
        photo=[SimpleNamespace(file_id="cat_fid", mime_type="image/jpeg")],
        document=None,
        voice=None,
        audio=None,
        video=None,
        video_note=None,
        animation=None,
    )
    update = _make_telegram_update(
        text="what breed is this?",
        reply_to_message=reply_with_caption_and_photo,
    )
    await channel._on_message(update, None)

    # 验证处理了一次
    assert len(handled) == 1
    # 验证回复内容包含 caption
    assert "[Reply to: A cute cat]" in handled[0]["content"]
    # 验证包含用户消息
    assert "what breed is this?" in handled[0]["content"]
    # 验证媒体列表包含一个文件
    assert len(handled[0]["media"]) == 1
    # 验证媒体路径包含 file_id
    assert "cat_fid" in handled[0]["media"][0]


@pytest.mark.asyncio
async def test_forward_command_does_not_inject_reply_context() -> None:
    """
    测试通过 _forward_command 转发的斜杠命令不包含回复上下文

    验证点：
    - 即使用户在回复消息时发送命令
    - 命令内容也不包含回复上下文

    为什么这样做？
    - 斜杠命令（如 /new）应该独立处理
    - 不应该被之前的回复消息干扰

    测试场景：
    - 用户回复消息 "some old message"
    - 用户发送 "/new" 命令
    - 预期命令内容只是 "/new"，不包含回复上下文
    """
    channel = TelegramChannel(
        TelegramConfig(enabled=True, token="123:abc", allow_from=["*"], group_policy="open"),
        MessageBus(),
    )
    channel._app = _FakeApp(lambda: None)
    handled = []

    async def capture_handle(**kwargs) -> None:
        handled.append(kwargs)

    channel._handle_message = capture_handle

    # 创建被回复的消息
    reply = SimpleNamespace(text="some old message", message_id=2, from_user=SimpleNamespace(id=1))
    # 创建包含回复的命令更新
    update = _make_telegram_update(text="/new", reply_to_message=reply)
    await channel._forward_command(update, None)

    # 验证处理了一次
    assert len(handled) == 1
    # 验证命令内容纯净，不包含回复上下文
    assert handled[0]["content"] == "/new"

# =============================================================================
# 邮件渠道测试
# 文件路径：tests/test_email_channel.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了邮件 (Email) 渠道的测试功能，主要测试：
# 1. IMAP 收取邮件和标记已读
# 2. SMTP 发送邮件和回复主题
# 3. 自动回复开关和同意授权
# 4. HTML 邮件文本提取
# 5. 按日期范围收取邮件
#
# 测试场景：
# --------
# 1. test_fetch_new_messages_parses_unseen_and_marks_seen
#    - 测试收取未读邮件并标记为已读
#    - 验证 UIDs 去重机制
#
# 2. test_extract_text_body_falls_back_to_html
#    - 测试 HTML 邮件的文本提取
#
# 3. test_start_returns_immediately_without_consent
#    - 测试未授权同意时立即返回
#
# 4. test_send_uses_smtp_and_reply_subject
#    - 测试 SMTP 发送和回复主题格式
#    - 验证 In-Reply-To 头设置
#
# 5. test_send_skips_reply_when_auto_reply_disabled
#    - 测试自动回复禁用时跳过回复
#    - 验证 force_send=True 可强制发送
#
# 6. test_send_proactive_email_when_auto_reply_disabled
#    - 测试自动回复禁用时允许主动发送
#
# 7. test_send_skips_when_consent_not_granted
#    - 测试未授权同意时跳过发送
#
# 8. test_fetch_messages_between_dates_uses_imap_since_before
#    - 测试按日期范围收取邮件
#    - 验证不标记已读（只读操作）
#
# 使用示例：
# --------
# pytest tests/test_email_channel.py -v
# =============================================================================

from email.message import EmailMessage
from datetime import date

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.email import EmailChannel
from nanobot.config.schema import EmailConfig


def _make_config() -> EmailConfig:
    """创建测试用的邮件配置对象。

    返回一个启用的、已授权的邮件配置，使用示例域名和凭据。

    Returns:
        EmailConfig 对象，包含 IMAP 和 SMTP 配置

    配置说明:
        - enabled=True: 渠道启用
        - consent_granted=True: 用户已授权
        - imap_*: IMAP 服务器配置（收件）
        - smtp_*: SMTP 服务器配置（发件）
        - mark_seen=True: 收取后标记为已读
    """
    return EmailConfig(
        enabled=True,
        consent_granted=True,
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="bot@example.com",
        imap_password="secret",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="bot@example.com",
        smtp_password="secret",
        mark_seen=True,
    )


def _make_raw_email(
    from_addr: str = "alice@example.com",
    subject: str = "Hello",
    body: str = "This is the body.",
) -> bytes:
    """创建原始邮件字节用于测试。

    使用 email.message.EmailMessage 构建标准格式的邮件，
    返回可用于 IMAP 测试的原始字节。

    Args:
        from_addr: 发件人地址
        subject: 邮件主题
        body: 邮件正文

    Returns:
        原始邮件字节
    """
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = "bot@example.com"
    msg["Subject"] = subject
    msg["Message-ID"] = "<m1@example.com>"
    msg.set_content(body)
    return msg.as_bytes()


def test_fetch_new_messages_parses_unseen_and_marks_seen(monkeypatch) -> None:
    """测试收取新邮件解析未读邮件并标记为已读。

    验证场景：
    1. IMAP 搜索未读邮件
    2. 解析邮件内容（发件人、主题、正文）
    3. 标记邮件为已读（\\Seen 标志）
    4. 相同 UID 的邮件在进程内去重

    测试方法：
    - 使用 FakeIMAP 模拟 IMAP 服务器
    - 记录 store() 调用验证标记已读操作
    - 第二次调用验证去重机制
    """
    raw = _make_raw_email(subject="Invoice", body="Please pay")

    class FakeIMAP:
        """模拟 IMAP 服务器用于测试。

        Attributes:
            store_calls: 记录所有 store() 调用，用于验证标记已读操作
        """

        def __init__(self) -> None:
            self.store_calls: list[tuple[bytes, str, str]] = []

        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            return "OK", [b"1"]  # 找到 1 封邮件

        def fetch(self, _imap_id: bytes, _parts: str):
            # 返回邮件原始数据
            return "OK", [(b"1 (UID 123 BODY[] {200})", raw), b")"]

        def store(self, imap_id: bytes, op: str, flags: str):
            """记录标记已读操作。

            Args:
                imap_id: 邮件 IMAP ID
                op: 操作类型（如 "+FLAGS"）
                flags: 标志（如 "\\Seen"）
            """
            self.store_calls.append((imap_id, op, flags))
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    fake = FakeIMAP()
    # 注入伪造的 IMAP 客户端
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    channel = EmailChannel(_make_config(), MessageBus())
    items = channel._fetch_new_messages()

    # 验证解析结果
    assert len(items) == 1
    assert items[0]["sender"] == "alice@example.com"
    assert items[0]["subject"] == "Invoice"
    assert "Please pay" in items[0]["content"]
    # 验证标记已读操作
    assert fake.store_calls == [(b"1", "+FLAGS", "\\Seen")]

    # 验证相同 UID 去重
    items_again = channel._fetch_new_messages()
    assert items_again == []  # 第二次返回空列表


def test_extract_text_body_falls_back_to_html() -> None:
    """测试 HTML 邮件的文本提取回退机制。

    验证场景：
    1. 邮件只有 HTML 部分，没有纯文本
    2. _extract_text_body() 应该从 HTML 提取文本
    3. HTML 标签应该被正确解析

    注意：这个测试验证了 HTML 到纯文本的转换功能。
    """
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = "bot@example.com"
    msg["Subject"] = "HTML only"
    # 添加 HTML 部分（没有纯文本部分）
    msg.add_alternative("<p>Hello<br>world</p>", subtype="html")

    text = EmailChannel._extract_text_body(msg)
    assert "Hello" in text
    assert "world" in text


@pytest.mark.asyncio
async def test_start_returns_immediately_without_consent(monkeypatch) -> None:
    """测试未授权同意时 start() 立即返回。

    验证场景：
    1. consent_granted = False
    2. start() 应该立即返回，不启动监听循环
    3. is_running 应该为 False
    4. 不应该调用 _fetch_new_messages()

    这是重要的安全检查，确保未经用户同意的情况下
    不会收取或发送邮件。
    """
    cfg = _make_config()
    cfg.consent_granted = False  # 未授权
    channel = EmailChannel(cfg, MessageBus())

    called = {"fetch": False}

    def _fake_fetch():
        called["fetch"] = True
        return []

    monkeypatch.setattr(channel, "_fetch_new_messages", _fake_fetch)
    await channel.start()
    assert channel.is_running is False  # 未启动
    assert called["fetch"] is False  # 未收取邮件


@pytest.mark.asyncio
async def test_send_uses_smtp_and_reply_subject(monkeypatch) -> None:
    """测试发送邮件使用 SMTP 和正确的回复主题格式。

    验证场景：
    1. 发送邮件到 alice@example.com
    2. 主题应该是 "Re: {原主题}" 格式
    3. 应该设置 In-Reply-To 头
    4. SMTP 连接应该正确建立（TLS、登录）

    邮件回复规范:
    - Subject: Re: {原主题}
    - In-Reply-To: {原 Message-ID}
    - References: {原 Message-ID}（可选）
    """
    class FakeSMTP:
        """模拟 SMTP 服务器用于测试。

        Attributes:
            timeout: 连接超时时间
            started_tls: 是否启动了 TLS
            logged_in: 是否已登录
            sent_messages: 记录所有发送的邮件
        """

        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.timeout = timeout
            self.started_tls = False
            self.logged_in = False
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            """启动 TLS 加密。"""
            self.started_tls = True

        def login(self, _user: str, _pw: str):
            """登录 SMTP 服务器。"""
            self.logged_in = True

        def send_message(self, msg: EmailMessage):
            """记录发送的邮件。"""
            self.sent_messages.append(msg)

    fake_instances: list[FakeSMTP] = []

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        instance = FakeSMTP(host, port, timeout=timeout)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", _smtp_factory)

    channel = EmailChannel(_make_config(), MessageBus())
    # 设置之前的通信记录（模拟收到过邮件）
    channel._last_subject_by_chat["alice@example.com"] = "Invoice #42"
    channel._last_message_id_by_chat["alice@example.com"] = "<m1@example.com>"

    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Acknowledged.",
        )
    )

    # 验证 SMTP 连接
    assert len(fake_instances) == 1
    smtp = fake_instances[0]
    assert smtp.started_tls is True  # 启用了 TLS
    assert smtp.logged_in is True  # 已登录
    # 验证发送的邮件
    assert len(smtp.sent_messages) == 1
    sent = smtp.sent_messages[0]
    assert sent["Subject"] == "Re: Invoice #42"  # 回复主题格式正确
    assert sent["To"] == "alice@example.com"
    assert sent["In-Reply-To"] == "<m1@example.com>"  # 回复引用正确


@pytest.mark.asyncio
async def test_send_skips_reply_when_auto_reply_disabled(monkeypatch) -> None:
    """测试自动回复禁用时跳过回复，但允许主动发送。

    验证场景：
    1. auto_reply_enabled = False
    2. alice@example.com 之前发过邮件（这是回复）
    3. 普通回复应该被跳过
    4. force_send=True 应该强制发送

    设计说明:
    - auto_reply_enabled 控制是否回复收到过的邮件
    - 主动发送（给没发过邮件的地址）不受此限制
    - force_send 可以绕过所有限制
    """
    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            self.sent_messages.append(msg)

    fake_instances: list[FakeSMTP] = []

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        instance = FakeSMTP(host, port, timeout=timeout)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", _smtp_factory)

    cfg = _make_config()
    cfg.auto_reply_enabled = False  # 禁用自动回复
    channel = EmailChannel(cfg, MessageBus())

    # 标记 alice 为发过邮件的人（使这次发送成为"回复"）
    channel._last_subject_by_chat["alice@example.com"] = "Previous email"

    # 普通回复应该被跳过
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Should not send.",
        )
    )
    assert fake_instances == []  # 没有 SMTP 连接，说明被跳过

    # 使用 force_send=True 应该发送
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Force send.",
            metadata={"force_send": True},
        )
    )
    assert len(fake_instances) == 1
    assert len(fake_instances[0].sent_messages) == 1


@pytest.mark.asyncio
async def test_send_proactive_email_when_auto_reply_disabled(monkeypatch) -> None:
    """测试自动回复禁用时允许主动发送邮件。

    验证场景：
    1. auto_reply_enabled = False
    2. bob@example.com 从未发过邮件（这是主动发送）
    3. 应该正常发送

    设计说明:
    - auto_reply_enabled 只控制"回复"行为
    - 主动发送邮件（给新地址）不受此限制
    - 这样可以实现：不自动回复，但可以主动通知用户
    """
    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            self.sent_messages.append(msg)

    fake_instances: list[FakeSMTP] = []

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        instance = FakeSMTP(host, port, timeout=timeout)
        fake_instances.append(instance)
        return instance

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", _smtp_factory)

    cfg = _make_config()
    cfg.auto_reply_enabled = False  # 禁用自动回复
    channel = EmailChannel(cfg, MessageBus())

    # bob@example.com 从未发过邮件（主动发送）
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="bob@example.com",
            content="Hello, this is a proactive email.",
        )
    )
    assert len(fake_instances) == 1
    assert len(fake_instances[0].sent_messages) == 1
    sent = fake_instances[0].sent_messages[0]
    assert sent["To"] == "bob@example.com"


@pytest.mark.asyncio
async def test_send_skips_when_consent_not_granted(monkeypatch) -> None:
    """测试未授权同意时跳过发送。

    验证场景：
    1. consent_granted = False
    2. 即使 force_send = True
    3. 也不应该建立 SMTP 连接

    这是最重要的安全检查：未经用户同意，绝对不能发送邮件。
    force_send 不能绕过 consent_granted 检查。
    """
    class FakeSMTP:
        def __init__(self, _host: str, _port: int, timeout: int = 30) -> None:
            self.sent_messages: list[EmailMessage] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, context=None):
            return None

        def login(self, _user: str, _pw: str):
            return None

        def send_message(self, msg: EmailMessage):
            self.sent_messages.append(msg)

    called = {"smtp": False}

    def _smtp_factory(host: str, port: int, timeout: int = 30):
        called["smtp"] = True
        return FakeSMTP(host, port, timeout=timeout)

    monkeypatch.setattr("nanobot.channels.email.smtplib.SMTP", _smtp_factory)

    cfg = _make_config()
    cfg.consent_granted = False  # 未授权
    channel = EmailChannel(cfg, MessageBus())
    await channel.send(
        OutboundMessage(
            channel="email",
            chat_id="alice@example.com",
            content="Should not send.",
            metadata={"force_send": True},  # 即使强制发送
        )
    )
    assert called["smtp"] is False  # SMTP 连接未建立


def test_fetch_messages_between_dates_uses_imap_since_before_without_mark_seen(monkeypatch) -> None:
    """测试按日期范围收取邮件使用 IMAP SINCE/BEFORE 且不标记已读。

    验证场景：
    1. 收取 2026-02-06 到 2026-02-07 之间的邮件
    2. IMAP search 使用 "SINCE" 和 "BEFORE" 参数
    3. 这是只读操作，不应该标记邮件为已读

    IMAP 日期格式:
    - "06-Feb-2026" 格式
    - SINCE: 包含指定日期
    - BEFORE: 不包含指定日期（开区间）
    """
    raw = _make_raw_email(subject="Status", body="Yesterday update")

    class FakeIMAP:
        def __init__(self) -> None:
            self.search_args = None
            self.store_calls: list[tuple[bytes, str, str]] = []

        def login(self, _user: str, _pw: str):
            return "OK", [b"logged in"]

        def select(self, _mailbox: str):
            return "OK", [b"1"]

        def search(self, *_args):
            self.search_args = _args  # 记录搜索参数
            return "OK", [b"5"]

        def fetch(self, _imap_id: bytes, _parts: str):
            return "OK", [(b"5 (UID 999 BODY[] {200})", raw), b")"]

        def store(self, imap_id: bytes, op: str, flags: str):
            self.store_calls.append((imap_id, op, flags))
            return "OK", [b""]

        def logout(self):
            return "BYE", [b""]

    fake = FakeIMAP()
    monkeypatch.setattr("nanobot.channels.email.imaplib.IMAP4_SSL", lambda _h, _p: fake)

    channel = EmailChannel(_make_config(), MessageBus())
    items = channel.fetch_messages_between_dates(
        start_date=date(2026, 2, 6),
        end_date=date(2026, 2, 7),
        limit=10,
    )

    assert len(items) == 1
    assert items[0]["subject"] == "Status"
    # 验证 IMAP 搜索参数：SINCE 06-Feb-2026, BEFORE 07-Feb-2026
    assert fake.search_args is not None
    assert fake.search_args[1:] == ("SINCE", "06-Feb-2026", "BEFORE", "07-Feb-2026")
    # 验证没有标记已读（只读操作）
    assert fake.store_calls == []

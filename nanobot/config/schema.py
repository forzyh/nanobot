# =============================================================================
# nanobot 配置模型定义
# 文件路径：nanobot/config/schema.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件使用 Pydantic 定义了 nanobot 的所有配置模型。
#
# 什么是 Pydantic？
# --------------
# Pydantic 是 Python 的数据验证库，基于类型注解提供：
# 1. 数据验证：自动检查数据类型和格式
# 2. 自动转换：字符串转整数等类型转换
# 3. 序列化：对象转 JSON/字典
# 4. 默认值：字段默认值管理
#
# 为什么使用 Pydantic？
# ------------------
# 1. 类型安全：配置文件数据自动验证，避免运行时错误
# 2. 自动补全：IDE 可以提供字段提示
# 3. 错误提示：配置错误时给出清晰的错误信息
# 4. 兼容性：支持 camelCase 和 snake_case 两种命名风格
#
# 配置模型层次结构：
# ----------------
# Config (根配置)
# ├── agents: AgentsConfig (Agent 配置)
# │   └── defaults: AgentDefaults (默认 Agent)
# ├── channels: ChannelsConfig (渠道配置)
# │   ├── telegram: TelegramConfig
# │   ├── discord: DiscordConfig
# │   ├── whatsapp: WhatsAppConfig
# │   ├── feishu: FeishuConfig
# │   ├── dingtalk: DingTalkConfig
# │   ├── slack: SlackConfig
# │   ├── mochat: MochatConfig
# │   ├── email: EmailConfig
# │   ├── matrix: MatrixConfig
# │   ├── qq: QQConfig
# │   └── wecom: WecomConfig
# ├── providers: ProvidersConfig (LLM 提供商配置)
# │   ├── openai, anthropic, azure_openai, etc.
# │   └── custom: ProviderConfig
# ├── gateway: GatewayConfig (网关配置)
# │   └── heartbeat: HeartbeatConfig
# └── tools: ToolsConfig (工具配置)
#     ├── web: WebToolsConfig
#     ├── exec: ExecToolConfig
#     └── mcp_servers: dict[MCP 服务器]
# =============================================================================

"""Configuration schema using Pydantic."""
# 使用 Pydantic 的配置模型定义

from pathlib import Path  # 路径处理
from typing import Literal  # 字面量类型，限制值为指定集合

from pydantic import BaseModel, ConfigDict, Field  # Pydantic 核心类
from pydantic.alias_generators import to_camel  # camelCase 别名生成器
from pydantic_settings import BaseSettings  # 支持环境变量读取的配置类


# =============================================================================
# Base - 基础模型
# =============================================================================

class Base(BaseModel):
    """
    基础模型，同时支持 camelCase 和 snake_case 键。

    为什么需要支持两种命名？
    ---------------------
    - JSON 配置文件通常使用 camelCase（JavaScript 风格）
      例如：{"apiKey": "...", "apiBase": "..."}
    - Python 代码使用 snake_case（PEP 8 规范）
      例如：api_key, api_base

    ConfigDict 配置说明：
    -------------------
    - alias_generator=to_camel: 自动将 snake_case 字段转为 camelCase 别名
    - populate_by_name=True: 允许通过原始名称或别名访问字段

    示例：
        >>> class MyConfig(Base):
        ...     api_key: str
        ...     api_base: str
        >>> cfg = MyConfig.model_validate({"apiKey": "sk-123", "api_base": "http://..."})
        >>> cfg.api_key  # 可以通过 snake_case 访问
        'sk-123'
        >>> cfg.model_dump(by_alias=True)  # 导出时使用 camelCase
        {'apiKey': 'sk-123', 'apiBase': 'http://...'}
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# =============================================================================
# 聊天渠道配置
# =============================================================================

class WhatsAppConfig(Base):
    """
    WhatsApp 渠道配置。

    WhatsApp 通过 WebSocket 桥接服务连接（需要额外的 Node.js 服务）。

    属性说明：
    --------
    enabled: bool
        是否启用 WhatsApp 渠道
        默认值：False

    bridge_url: str
        桥接服务的 WebSocket URL
        桥接服务负责与 WhatsApp Web 通信
        默认值："ws://localhost:3001"

    bridge_token: str
        桥接服务的认证令牌（可选，推荐设置）
        用于验证连接请求的合法性

    allow_from: list[str]
        允许的电话号码列表
        空列表表示不限制
        例如：["+8613800138000", "+1234567890"]
    """

    enabled: bool = False
    bridge_url: str = "ws://localhost:3001"
    bridge_token: str = ""  # 桥接服务认证令牌（可选，推荐）
    allow_from: list[str] = Field(default_factory=list)  # 允许的电话号码


class TelegramConfig(Base):
    """
    Telegram 渠道配置。

    Telegram 通过 Bot API 连接，需要 Bot Token。

    获取 Bot Token：
    ------------
    1. 在 Telegram 中搜索 @BotFather
    2. 发送 /newbot 创建机器人
    3. 按提示设置名称和用户名
    4. BotFather 返回的 token 即为此处所需

    属性说明：
    --------
    enabled: bool
        是否启用 Telegram 渠道

    token: str
        Bot Token，从 @BotFather 获取
        格式类似："123456789:ABCdEfGhIjKlMnOpQrStUvWxYz"

    allow_from: list[str]
        允许的用户 ID 或用户名列表
        - 用户 ID：数字，如 "123456789"
        - 用户名：带@，如 "@username"
        空列表表示不限制

    proxy: str | None
        HTTP/SOCKS5 代理 URL
        在中国大陆等地区可能需要代理连接 Telegram
        格式示例：
        - HTTP 代理："http://127.0.0.1:7890"
        - SOCKS5 代理："socks5://127.0.0.1:1080"

    reply_to_message: bool
        是否以引用方式回复原消息
        True: 回复时引用原消息（显示上下文）
        False: 发送普通消息
        默认值：False

    group_policy: Literal["open", "mention"]
        群组响应策略
        - "mention": 仅在机器人被 @ 或被回复时响应
        - "open": 响应群组中的所有消息
        默认值："mention"（避免打扰）
    """

    enabled: bool = False
    token: str = ""  # @BotFather 获取的 Bot Token
    allow_from: list[str] = Field(default_factory=list)  # 允许的用户 ID 或用户名
    proxy: str | None = (
        None  # HTTP/SOCKS5 代理 URL，如 "http://127.0.0.1:7890" 或 "socks5://127.0.0.1:1080"
    )
    reply_to_message: bool = False  # True 则以引用方式回复
    group_policy: Literal["open", "mention"] = "mention"  # "mention" 仅在@或回复时响应，"open" 响应所有消息


class FeishuConfig(Base):
    """
    飞书/Lark 渠道配置，使用 WebSocket 长连接。

    飞书开放平台：https://open.feishu.cn/

    配置步骤：
    --------
    1. 创建企业应用
    2. 获取 App ID 和 App Secret
    3. 配置事件订阅（填写机器人 URL）
    4. 获取 Encrypt Key 和 Verification Token

    属性说明：
    --------
    enabled: bool
        是否启用飞书渠道

    app_id: str
        飞书开放平台的应用 ID
        例如："cli_a1b2c3d4e5f6"

    app_secret: str
        飞书开放平台的应用密钥
        用于验证请求合法性

    encrypt_key: str
        事件订阅的加密密钥（可选）
        用于解密飞书发送的加密消息

    verification_token: str
        事件订阅的验证令牌（可选）
        用于验证回调请求

    allow_from: list[str]
        允许的用户 open_id 列表
        open_id 是飞书用户的唯一标识
        空列表表示不限制

    react_emoji: str
        消息反应的 Emoji 类型
        机器人处理消息时会添加表情作为反馈
        可选值：THUMBSUP, OK, DONE, SMILE 等
        默认值："THUMBSUP"（点赞）

    group_policy: Literal["open", "mention"]
        群组响应策略
        - "mention": 仅在机器人被 @ 时响应
        - "open": 响应群组中的所有消息
        默认值："mention"
    """

    enabled: bool = False
    app_id: str = ""  # 飞书开放平台的 App ID
    app_secret: str = ""  # 飞书开放平台的 App Secret
    encrypt_key: str = ""  # 事件订阅的加密密钥（可选）
    verification_token: str = ""  # 事件订阅的验证令牌（可选）
    allow_from: list[str] = Field(default_factory=list)  # 允许的用户 open_ids
    react_emoji: str = (
        "THUMBSUP"  # 消息反应的 Emoji 类型（如 THUMBSUP, OK, DONE, SMILE）
    )
    group_policy: Literal["open", "mention"] = "mention"  # "mention" 仅在@时响应，"open" 响应所有消息


class DingTalkConfig(Base):
    """
    钉钉渠道配置，使用 Stream 模式。

    钉钉开放平台：https://open.dingtalk.com/

    配置步骤：
    --------
    1. 创建企业内部应用
    2. 获取 AppKey 和 AppSecret
    3. 配置机器人回调地址

    属性说明：
    --------
    enabled: bool
        是否启用钉钉渠道

    client_id: str
        AppKey，钉钉开放平台的应用标识

    client_secret: str
        AppSecret，钉钉开放平台的应用密钥

    allow_from: list[str]
        允许的工作人员 ID 列表
        staff_id 是钉钉用户的唯一标识
        空列表表示不限制
    """

    enabled: bool = False
    client_id: str = ""  # AppKey
    client_secret: str = ""  # AppSecret
    allow_from: list[str] = Field(default_factory=list)  # 允许的 staff_ids


class DiscordConfig(Base):
    """
    Discord 渠道配置。

    Discord Developer Portal：https://discord.com/developers/applications

    配置步骤：
    --------
    1. 创建应用并添加 Bot
    2. 获取 Bot Token
    3. 配置 Intents（消息内容权限）
    4. 邀请机器人到服务器

    属性说明：
    --------
    enabled: bool
        是否启用 Discord 渠道

    token: str
        Bot Token，从 Discord Developer Portal 获取
        用于认证机器人身份

    allow_from: list[str]
        允许的用户 ID 列表
        空列表表示不限制

    gateway_url: str
        Discord Gateway URL
        Gateway 是 Discord 的实时通信接口
        默认值："wss://gateway.discord.gg/?v=10&encoding=json"
        - v=10: API 版本 10
        - encoding=json: JSON 格式编码

    intents: int
        Gateway Intents 位掩码
        用于声明机器人需要的事件类型
        默认值：37377
        计算方式：
        - GUILDS (1 << 0) = 1
        - GUILD_MESSAGES (1 << 9) = 512
        - DIRECT_MESSAGES (1 << 12) = 4096
        - MESSAGE_CONTENT (1 << 15) = 32768
        合计：1 + 512 + 4096 + 32768 = 37377

    group_policy: Literal["mention", "open"]
        群组响应策略
        - "mention": 仅在机器人被 @ 时响应
        - "open": 响应群组中的所有消息
        默认值："mention"
    """

    enabled: bool = False
    token: str = ""  # Discord Developer Portal 的 Bot Token
    allow_from: list[str] = Field(default_factory=list)  # 允许的用户 ID
    gateway_url: str = "wss://gateway.discord.gg/?v=10&encoding=json"
    intents: int = 37377  # GUILDS + GUILD_MESSAGES + DIRECT_MESSAGES + MESSAGE_CONTENT
    group_policy: Literal["mention", "open"] = "mention"


class MatrixConfig(Base):
    """
    Matrix (Element) 渠道配置。

    Matrix 是一个开放的去中心化通信协议。
    Element 是流行的 Matrix 客户端。

    属性说明：
    --------
    enabled: bool
        是否启用 Matrix 渠道

    homeserver: str
        Matrix 家庭服务器 URL
        常用公共服务器：
        - matrix.org (官方)
        - gnupg.de
        - 自建服务器
        默认值："https://matrix.org"

    access_token: str
        Matrix 访问令牌
        用于认证 API 请求

    user_id: str
        机器人用户 ID
        格式：@bot:matrix.org

    device_id: str
        设备 ID
        用于标识登录设备

    e2ee_enabled: bool
        是否启用端到端加密（E2EE）
        Matrix 支持端到端加密的私密通信
        默认值：True

    sync_stop_grace_seconds: int
        优雅停止同步的等待时间（秒）
        sync_forever() 停止前的最大等待时间
        超时后使用取消回退
        默认值：2

    max_media_bytes: int
        媒体附件的最大大小（字节）
        适用于 inbound 和 outbound 双向媒体处理
        默认值：20MB (20 * 1024 * 1024)

    allow_from: list[str]
        允许的用户 ID 列表
        空列表表示不限制

    group_policy: Literal["open", "mention", "allowlist"]
        群组响应策略
        - "open": 响应所有群组消息
        - "mention": 仅在机器人被 @ 时响应
        - "allowlist": 仅在允许列表中响应

    group_allow_from: list[str]
        允许的群组/房间 ID 列表
        仅在 group_policy="allowlist" 时使用

    allow_room_mentions: bool
        是否允许房间 @（@room）
        True: 响应 @room 提及
        False: 忽略房间 @
        默认值：False
    """

    enabled: bool = False
    homeserver: str = "https://matrix.org"
    access_token: str = ""
    user_id: str = ""  # @bot:matrix.org
    device_id: str = ""
    e2ee_enabled: bool = True  # 启用 Matrix E2EE 支持（加密 + 加密房间处理）
    sync_stop_grace_seconds: int = (
        2  # sync_forever 优雅停止前等待的最大秒数，超时后使用取消回退
    )
    max_media_bytes: int = (
        20 * 1024 * 1024
    )  # Matrix 媒体处理（入站 + 出站）接受的最大附件大小（字节）
    allow_from: list[str] = Field(default_factory=list)
    group_policy: Literal["open", "mention", "allowlist"] = "open"
    group_allow_from: list[str] = Field(default_factory=list)
    allow_room_mentions: bool = False


class EmailConfig(Base):
    """
    Email 渠道配置（IMAP 接收 + SMTP 发送）。

    Email 渠道将邮件通信转换为消息总线事件：
    - 接收：定期轮询 IMAP 邮箱，读取新邮件
    - 发送：通过 SMTP 发送回复邮件

    属性说明：
    --------
    enabled: bool
        是否启用 Email 渠道

    consent_granted: bool
        是否已获所有者明确同意访问邮箱数据
        隐私保护标志，确保合法授权
        默认值：False

    IMAP 配置（接收）：
    ----------------
    imap_host: str
        IMAP 服务器地址
        例如："imap.gmail.com", "imap.qq.com"

    imap_port: int
        IMAP 服务器端口
        默认值：993（IMAPS 加密端口）

    imap_username: str
        IMAP 登录用户名（通常是邮箱地址）

    imap_password: str
        IMAP 登录密码
        注意：Gmail 等可能需要应用专用密码

    imap_mailbox: str
        要监控的邮箱文件夹
        默认值："INBOX"（收件箱）

    imap_use_ssl: bool
        是否使用 SSL/TLS 加密连接
        默认值：True（推荐）

    SMTP 配置（发送）：
    ----------------
    smtp_host: str
        SMTP 服务器地址
        例如："smtp.gmail.com", "smtp.qq.com"

    smtp_port: int
        SMTP 服务器端口
        默认值：587（STARTTLS 端口）

    smtp_username: str
        SMTP 登录用户名

    smtp_password: str
        SMTP 登录密码

    smtp_use_tls: bool
        是否使用 TLS 加密
        默认值：True

    smtp_use_ssl: bool
        是否使用 SSL 加密
        默认值：False

    from_address: str
        发件人地址（邮件显示的发送者）

    行为配置：
    --------
    auto_reply_enabled: bool
        是否启用自动回复
        True: 收到邮件后自动发送回复
        False: 只读取邮件，不发送回复
        默认值：True

    poll_interval_seconds: int
        IMAP 轮询间隔（秒）
        每隔多久检查一次新邮件
        默认值：30

    mark_seen: bool
        是否将已读邮件标记为已读
        True: 处理过的邮件标记为已读
        False: 保持未读状态
        默认值：True

    max_body_chars: int
        邮件正文最大字符数
        超过此长度的正文会被截断
        默认值：12000

    subject_prefix: str
        回复邮件的主题前缀
        例如："Re: " 表示回复
        默认值："Re: "

    allow_from: list[str]
        允许的发件人邮箱地址列表
        空列表表示不限制
        例如：["friend@example.com"]
    """

    enabled: bool = False
    consent_granted: bool = False  # 明确的 owner 许可以访问邮箱数据

    # IMAP (接收)
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"
    imap_use_ssl: bool = True

    # SMTP (发送)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    from_address: str = ""

    # 行为
    auto_reply_enabled: bool = (
        True  # False 则只读取入站邮件，不发送自动回复
    )
    poll_interval_seconds: int = 30
    mark_seen: bool = True
    max_body_chars: int = 12000
    subject_prefix: str = "Re: "
    allow_from: list[str] = Field(default_factory=list)  # 允许的发件人邮箱地址


class MochatMentionConfig(Base):
    """
    Mochat @ 行为配置。

    Mochat 是一个企业聊天平台。

    属性说明：
    --------
    require_in_groups: bool
        是否要求仅在群组中需要 @
        True: 群组中必须 @ 机器人才响应
        False: 私聊和群组都响应
        默认值：False
    """

    require_in_groups: bool = False


class MochatGroupRule(Base):
    """
    Mochat 每个群组的 @ 要求规则。

    属性说明：
    --------
    require_mention: bool
        是否要求必须 @ 机器人
        True: 群组中必须 @ 机器人才响应
        False: 无需 @ 也响应
    """

    require_mention: bool = False


class MochatConfig(Base):
    """
    Mochat 渠道配置。

    Mochat 是企业级聊天机器人平台。

    属性说明：
    --------
    enabled: bool
        是否启用 Mochat 渠道

    base_url: str
        Mochat API 基础 URL
        默认值："https://mochat.io"

    socket_url: str
        WebSocket 服务器 URL
        用于实时通信

    socket_path: str
        WebSocket 路径
        默认值："/socket.io"

    socket_disable_msgpack: bool
        是否禁用 MessagePack 编码
        MessagePack 是一种高效的二进制序列化格式

    socket_reconnect_delay_ms: int
        重连延迟（毫秒）
        连接断开后等待多久再重试
        默认值：1000ms (1 秒)

    socket_max_reconnect_delay_ms: int
        最大重连延迟（毫秒）
        重连延迟的上限，防止过长等待
        默认值：10000ms (10 秒)

    socket_connect_timeout_ms: int
        连接超时（毫秒）
        建立连接的最大等待时间
        默认值：10000ms (10 秒)

    refresh_interval_ms: int
        刷新间隔（毫秒）
        定期刷新连接的间隔
        默认值：30000ms (30 秒)

    watch_timeout_ms: int
        监视超时（毫秒）
        单次监视操作的最大时间
        默认值：25000ms (25 秒)

    watch_limit: int
        每次监视的事件数量上限
        默认值：100

    retry_delay_ms: int
        重试延迟（毫秒）
        失败后等待多久重试
        默认值：500ms (0.5 秒)

    max_retry_attempts: int
        最大重试次数
        0 表示无限重试
        默认值：0

    claw_token: str
        Claw Token（认证令牌）

    agent_user_id: str
        Agent 用户 ID

    sessions: list[str]
        会话 ID 列表

    panels: list[str]
        面板 ID 列表

    allow_from: list[str]
        允许的用户 ID 列表

    mention: MochatMentionConfig
        @ 行为配置

    groups: dict[str, MochatGroupRule]
        每个群组的规则配置
        键：群组 ID，值：规则配置

    reply_delay_mode: str
        回复延迟模式
        - "off": 无延迟
        - "non-mention": 非@消息延迟
        默认值："non-mention"

    reply_delay_ms: int
        回复延迟（毫秒）
        默认值：120000ms (2 分钟)
    """

    enabled: bool = False
    base_url: str = "https://mochat.io"
    socket_url: str = ""
    socket_path: str = "/socket.io"
    socket_disable_msgpack: bool = False
    socket_reconnect_delay_ms: int = 1000
    socket_max_reconnect_delay_ms: int = 10000
    socket_connect_timeout_ms: int = 10000
    refresh_interval_ms: int = 30000
    watch_timeout_ms: int = 25000
    watch_limit: int = 100
    retry_delay_ms: int = 500
    max_retry_attempts: int = 0  # 0 表示无限重试
    claw_token: str = ""
    agent_user_id: str = ""
    sessions: list[str] = Field(default_factory=list)
    panels: list[str] = Field(default_factory=list)
    allow_from: list[str] = Field(default_factory=list)
    mention: MochatMentionConfig = Field(default_factory=MochatMentionConfig)
    groups: dict[str, MochatGroupRule] = Field(default_factory=dict)
    reply_delay_mode: str = "non-mention"  # off | non-mention
    reply_delay_ms: int = 120000


class SlackDMConfig(Base):
    """
    Slack 私信（Direct Message）策略配置。

    属性说明：
    --------
    enabled: bool
        是否启用私信响应
        默认值：True

    policy: str
        私信策略
        - "open": 允许所有用户私信
        - "allowlist": 仅允许列表中的用户
        默认值："open"

    allow_from: list[str]
        允许的 Slack 用户 ID 列表
        仅在 policy="allowlist" 时使用
    """

    enabled: bool = True
    policy: str = "open"  # "open" 或 "allowlist"
    allow_from: list[str] = Field(default_factory=list)  # 允许的 Slack 用户 ID


class SlackConfig(Base):
    """
    Slack 渠道配置。

    Slack API：https://api.slack.com/

    配置步骤：
    --------
    1. 创建 Slack App
    2. 添加 Bot 用户
    3. 获取 Bot Token (xoxb-...)
    4. 获取 App Token (xapp-...)
    5. 邀请机器人到频道

    属性说明：
    --------
    enabled: bool
        是否启用 Slack 渠道

    mode: str
        连接模式
        当前仅支持 "socket"（Socket Mode）
        Socket Mode 通过 WebSocket 连接 Slack

    webhook_path: str
        Webhook 路径（用于 HTTP 模式）
        默认值："/slack/events"

    bot_token: str
        Bot Token，格式为 "xoxb-..."
        从 Slack App 设置页面获取

    app_token: str
        App Token，格式为 "xapp-..."
        Socket Mode 所需的认证令牌

    user_token_read_only: bool
        用户令牌是否只读模式
        默认值：True

    reply_in_thread: bool
        是否在主题线程中回复
        True: 回复在主题线程内（保持整洁）
        False: 回复在频道主线程
        默认值：True

    react_emoji: str
        反应表情
        机器人处理消息时添加的表情
        默认值："eyes"（眼睛）

    allow_from: list[str]
        允许的 Slack 用户 ID 列表（发送者级别）
        空列表表示不限制

    group_policy: str
        群组响应策略
        - "mention": 仅在@时响应
        - "open": 响应所有消息
        - "allowlist": 仅在允许列表中响应
        默认值："mention"

    group_allow_from: list[str]
        允许的频道 ID 列表
        仅在 group_policy="allowlist" 时使用

    dm: SlackDMConfig
        私信策略配置
    """

    enabled: bool = False
    mode: str = "socket"  # 当前支持 "socket"
    webhook_path: str = "/slack/events"
    bot_token: str = ""  # xoxb-...
    app_token: str = ""  # xapp-...
    user_token_read_only: bool = True
    reply_in_thread: bool = True
    react_emoji: str = "eyes"
    allow_from: list[str] = Field(default_factory=list)  # 允许的 Slack 用户 ID（发送者级别）
    group_policy: str = "mention"  # "mention", "open", "allowlist"
    group_allow_from: list[str] = Field(default_factory=list)  # group_policy=allowlist 时允许的频道 ID
    dm: SlackDMConfig = Field(default_factory=SlackDMConfig)


class QQConfig(Base):
    """
    QQ 渠道配置，使用 botpy SDK。

    QQ 机器人平台：https://q.qq.com/

    配置步骤：
    --------
    1. 创建机器人应用
    2. 获取 AppID 和 Secret
    3. 配置机器人能力
    4. 部署并启动机器人

    属性说明：
    --------
    enabled: bool
        是否启用 QQ 渠道

    app_id: str
        机器人 ID (AppID)，从 q.qq.com 获取
        应用的唯一标识

    secret: str
        机器人密钥 (AppSecret)，从 q.qq.com 获取
        用于认证 API 请求

    allow_from: list[str]
        允许的用户 openid 列表
        openid 是 QQ 用户的匿名标识
        空列表表示公开访问
    """

    enabled: bool = False
    app_id: str = ""  # 机器人 ID (AppID) from q.qq.com
    secret: str = ""  # 机器人密钥 (AppSecret) from q.qq.com
    allow_from: list[str] = Field(
        default_factory=list
    )  # 允许的用户 openids（空=公开访问）


class WecomConfig(Base):
    """
    企业微信 AI Bot 渠道配置。

    企业微信 AI Bot 平台：https://work.weixin.qq.com/

    配置步骤：
    --------
    1. 创建企业微信应用
    2. 添加 AI Bot 能力
    3. 获取 Bot ID 和 Secret

    属性说明：
    --------
    enabled: bool
        是否启用企业微信渠道

    bot_id: str
        Bot ID，从企业微信 AI Bot 平台获取

    secret: str
        Bot Secret，从企业微信 AI Bot 平台获取
        用于认证 API 请求

    allow_from: list[str]
        允许的用户 ID 列表
        空列表表示不限制

    welcome_message: str
        进入聊天时的欢迎消息
        用户首次与机器人对话时发送
        例如："你好！我是 AI 助手，有什么可以帮你的？"
    """

    enabled: bool = False
    bot_id: str = ""  # 企业微信 AI Bot 平台的 Bot ID
    secret: str = ""  # 企业微信 AI Bot 平台的 Bot Secret
    allow_from: list[str] = Field(default_factory=list)  # 允许的用户 ID
    welcome_message: str = ""  # enter_chat 事件的欢迎消息


class ChannelsConfig(Base):
    """
    聊天渠道的总配置。

    这个类聚合了所有聊天渠道的配置。
    每个渠道都有独立的启用开关和配置项。

    属性说明：
    --------
    send_progress: bool
        是否将 Agent 的文本进度流式发送到渠道
        True: 实时显示 AI 思考过程（如"正在搜索..."）
        False: 只在完成时发送最终结果
        默认值：True

    send_tool_hints: bool
        是否发送工具调用的提示
        True: 显示工具调用信息（如 read_file("...")）
        False: 隐藏工具调用细节
        默认值：False（避免信息过多）

    whatsapp: WhatsAppConfig
        WhatsApp 渠道配置

    telegram: TelegramConfig
        Telegram 渠道配置

    discord: DiscordConfig
        Discord 渠道配置

    feishu: FeishuConfig
        飞书渠道配置

    mochat: MochatConfig
        Mochat 渠道配置

    dingtalk: DingTalkConfig
        钉钉渠道配置

    email: EmailConfig
        Email 渠道配置

    slack: SlackConfig
        Slack 渠道配置

    qq: QQConfig
        QQ 渠道配置

    matrix: MatrixConfig
        Matrix 渠道配置

    wecom: WecomConfig
        企业微信渠道配置
    """

    send_progress: bool = True  # 将 Agent 的文本进度流式发送到渠道
    send_tool_hints: bool = False  # 流式发送工具调用提示（如 read_file("…"）
    whatsapp: WhatsAppConfig = Field(default_factory=WhatsAppConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    mochat: MochatConfig = Field(default_factory=MochatConfig)
    dingtalk: DingTalkConfig = Field(default_factory=DingTalkConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    slack: SlackConfig = Field(default_factory=SlackConfig)
    qq: QQConfig = Field(default_factory=QQConfig)
    matrix: MatrixConfig = Field(default_factory=MatrixConfig)
    wecom: WecomConfig = Field(default_factory=WecomConfig)


# =============================================================================
# Agent 配置
# =============================================================================

class AgentDefaults(Base):
    """
    Agent 默认配置。

    这个类定义了 Agent 的核心参数，
    包括使用的模型、token 限制、温度等。

    属性说明：
    --------
    workspace: str
        Agent 工作空间路径
        Agent 操作文件的根目录（出于安全考虑）
        支持~表示用户主目录
        默认值："~/.nanobot/workspace"

    model: str
        使用的 LLM 模型标识符
        格式："provider/model-name"
        例如：
        - "anthropic/claude-opus-4-5"
        - "openai/gpt-4o"
        - "deepseek/deepseek-chat"
        默认值："anthropic/claude-opus-4-5"

    provider: str
        LLM 提供商名称
        - "auto": 自动根据模型名称匹配
        - 具体名称："anthropic", "openrouter" 等
        默认值："auto"

    max_tokens: int
        每次响应的最大 token 数
        限制 AI 回复的长度
        默认值：8192

    context_window_tokens: int
        上下文窗口大小（token 数）
        决定 Agent 能"记住"多少对话历史
        较大的窗口 = 更多上下文，但成本更高
        默认值：65,536 (64K)

    temperature: float
        采样温度，控制输出的随机性
        范围：0.0 - 2.0
        - 越低（0.1-0.3）：输出确定、保守、聚焦
        - 越高（0.7-1.0）：输出多样、有创意
        默认值：0.1（聚焦、准确，适合代码任务）

    max_tool_iterations: int
        工具调用的最大迭代次数
        防止无限循环（如工具反复调用）
        默认值：40

    memory_window: int | None
        【已弃用】记忆窗口大小
        旧版字段，为了兼容旧配置保留
        运行时不使用，由 context_window_tokens 替代
        默认值：None

    reasoning_effort: str | None
        推理努力程度（某些模型支持）
        启用 LLM 思考模式
        可选值：
        - "low": 低推理强度，快速响应
        - "medium": 中等推理强度
        - "high": 高推理强度，深度思考
        默认值：None（不使用）

    属性方法：
    --------
    should_warn_deprecated_memory_window: bool
        当存在旧的 memoryWindow 但没有 contextWindowTokens 时返回 True
        用于提示用户配置已弃用
    """

    workspace: str = "~/.nanobot/workspace"
    model: str = "anthropic/claude-opus-4-5"
    provider: str = (
        "auto"  # 提供商名称（如 "anthropic", "openrouter"）或 "auto" 表示自动检测
    )
    max_tokens: int = 8192
    context_window_tokens: int = 65_536
    temperature: float = 0.1
    max_tool_iterations: int = 40
    # 已弃用的兼容字段：旧配置接受但运行时不使用
    memory_window: int | None = Field(default=None, exclude=True)
    reasoning_effort: str | None = None  # low / medium / high — 启用 LLM 思考模式

    @property
    def should_warn_deprecated_memory_window(self) -> bool:
        """
        当旧版 memoryWindow 存在但缺少 contextWindowTokens 时返回 True。

        这个属性用于检测是否需要警告用户配置已弃用。

        Returns:
            bool: True 表示需要警告
        """
        # memory_window 被显式设置，但 context_window_tokens 没有显式设置
        return self.memory_window is not None and "context_window_tokens" not in self.model_fields_set


class AgentsConfig(Base):
    """
    Agent 配置。

    这个类是 Agent 配置的根容器。

    属性说明：
    --------
    defaults: AgentDefaults
        默认 Agent 配置
        包含模型、温度、max_tokens 等核心参数
    """

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


# =============================================================================
# LLM 提供商配置
# =============================================================================

class ProviderConfig(Base):
    """
    LLM 提供商配置。

    每个 LLM 提供商（OpenAI、Anthropic 等）都需要配置
    API 密钥和端点信息。

    属性说明：
    --------
    api_key: str
        API 密钥
        用于认证 API 请求
        例如："sk-abc123..."

    api_base: str | None
        API 基础 URL（可选）
        用于自定义端点
        例如：
        - "https://api.openai.com/v1"
        - "http://localhost:11434/v1"（本地部署）
        默认值：None（使用提供商默认端点）

    extra_headers: dict[str, str] | None
        自定义请求头（可选）
        用于传递额外的认证或配置信息
        例如：{"APP-Code": "xxx"}（AiHubMix 需要）
        默认值：None
    """

    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None  # 自定义请求头（如 AiHubMix 的 APP-Code）


class ProvidersConfig(Base):
    """
    LLM 提供商配置集合。

    这个类聚合了所有支持的 LLM 提供商配置。
    可以同时配置多个提供商，运行时根据模型名称自动匹配。

    支持的提供商：
    ------------
    - custom: 任意 OpenAI 兼容端点
    - azure_openai: Azure OpenAI（模型=部署名称）
    - anthropic: Anthropic（Claude 系列）
    - openai: OpenAI（GPT 系列）
    - openrouter: OpenRouter（聚合平台）
    - deepseek: DeepSeek（深度求索）
    - groq: Groq（高速推理）
    - zhipu: 智谱 AI
    - dashscope: 阿里云百炼（通义千问）
    - vllm: vLLM（本地部署）
    - ollama: Ollama（本地部署）
    - gemini: Google Gemini
    - moonshot: 月之暗面（Kimi）
    - minimax: MiniMax
    - aihubmix: AiHubMix API 网关
    - siliconflow: 硅基流动
    - volcengine: 火山引擎
    - volcengine_coding_plan: 火山引擎 Coding Plan
    - byteplus: BytePlus（火山引擎国际版）
    - byteplus_coding_plan: BytePlus Coding Plan
    - openai_codex: OpenAI Codex（OAuth）
    - github_copilot: Github Copilot（OAuth）

    属性说明：
    --------
    每个属性都是一个 ProviderConfig 对象，
    可以配置 api_key、api_base 和 extra_headers。
    """

    custom: ProviderConfig = Field(default_factory=ProviderConfig)  # 任意 OpenAI 兼容端点
    azure_openai: ProviderConfig = Field(default_factory=ProviderConfig)  # Azure OpenAI（模型=部署名称）
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    dashscope: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    ollama: ProviderConfig = Field(default_factory=ProviderConfig)  # Ollama 本地模型
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    minimax: ProviderConfig = Field(default_factory=ProviderConfig)
    aihubmix: ProviderConfig = Field(default_factory=ProviderConfig)  # AiHubMix API 网关
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig)  # 硅基流动
    volcengine: ProviderConfig = Field(default_factory=ProviderConfig)  # 火山引擎
    volcengine_coding_plan: ProviderConfig = Field(default_factory=ProviderConfig)  # 火山引擎 Coding Plan
    byteplus: ProviderConfig = Field(default_factory=ProviderConfig)  # BytePlus（火山引擎国际版）
    byteplus_coding_plan: ProviderConfig = Field(default_factory=ProviderConfig)  # BytePlus Coding Plan
    openai_codex: ProviderConfig = Field(default_factory=ProviderConfig)  # OpenAI Codex（OAuth）
    github_copilot: ProviderConfig = Field(default_factory=ProviderConfig)  # Github Copilot（OAuth）


# =============================================================================
# 网关/服务器配置
# =============================================================================

class HeartbeatConfig(Base):
    """
    心跳服务配置。

    心跳服务定期检查系统健康状态。

    属性说明：
    --------
    enabled: bool
        是否启用心跳服务
        默认值：True

    interval_s: int
        心跳间隔（秒）
        每隔多久检查一次健康状态
        默认值：1800 秒（30 分钟）
    """

    enabled: bool = True
    interval_s: int = 30 * 60  # 30 分钟


class GatewayConfig(Base):
    """
    网关/服务器配置。

    网关是 nanobot 的 HTTP 服务入口，
    提供 API 端点和 WebSocket 连接。

    属性说明：
    --------
    host: str
        服务器监听地址
        "0.0.0.0" 表示监听所有网络接口
        默认值："0.0.0.0"

    port: int
        服务器监听端口
        默认值：18790

    heartbeat: HeartbeatConfig
        心跳服务配置
    """

    host: str = "0.0.0.0"
    port: int = 18790
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)


# =============================================================================
# 工具配置
# =============================================================================

class WebSearchConfig(Base):
    """
    网络搜索工具配置。

    配置 web_search 工具的参数，
    用于让 AI 能够搜索实时信息。

    属性说明：
    --------
    api_key: str
        Brave Search API 密钥
        获取方式：https://brave.com/search/api/
        免费套餐：每月 2000 次搜索

    max_results: int
        最大搜索结果数量
        每次搜索返回的最多结果数
        默认值：5
    """

    api_key: str = ""  # Brave Search API 密钥
    max_results: int = 5


class WebToolsConfig(Base):
    """
    网络工具配置。

    包含所有网络相关工具的配置。

    属性说明：
    --------
    proxy: str | None
        HTTP/SOCKS5 代理 URL
        用于网络请求经过代理
        在中国大陆等地区可能需要代理访问某些 API
        格式示例：
        - HTTP 代理："http://127.0.0.1:7890"
        - SOCKS5 代理："socks5://127.0.0.1:1080"
        默认值：None

    search: WebSearchConfig
        网络搜索配置
    """

    proxy: str | None = (
        None  # HTTP/SOCKS5 代理 URL，如 "http://127.0.0.1:7890" 或 "socks5://127.0.0.1:1080"
    )
    search: WebSearchConfig = Field(default_factory=WebSearchConfig)


class ExecToolConfig(Base):
    """
    Shell exec 工具配置。

    exec 工具允许 AI 执行 Shell 命令。
    出于安全考虑，可以配置超时和路径限制。

    属性说明：
    --------
    timeout: int
        命令执行超时（秒）
        超过此时间的命令会被强制终止
        默认值：60 秒

    path_append: str
        添加到 PATH 环境变量的路径
        用于让 exec 工具找到自定义命令
        例如："/usr/local/bin:/opt/bin"
        默认值：""（不添加）
    """

    timeout: int = 60
    path_append: str = ""


class MCPServerConfig(Base):
    """
    MCP 服务器连接配置（stdio 或 HTTP）。

    MCP（Model Context Protocol）是一种协议，
    允许 AI 模型与外部工具和服务通信。

    连接模式：
    --------
    1. stdio：通过标准输入/输出通信
       - 适合本地进程
       - 例如：运行 npx 命令启动 MCP 服务器

    2. sse：Server-Sent Events
       - 通过 HTTP SSE 端点通信
       - 适合远程服务

    3. streamableHttp：流式 HTTP
       - 通过 HTTP 流式端点通信
       - 适合远程服务

    属性说明：
    --------
    type: Literal["stdio", "sse", "streamableHttp"] | None
        连接类型
        - "stdio": 标准输入/输出
        - "sse": Server-Sent Events
        - "streamableHttp": 流式 HTTP
        - None: 自动检测
        默认值：None

    command: str
        stdio 模式：要运行的命令
        例如："npx", "node", "python"
        默认值：""

    args: list[str]
        stdio 模式：命令参数列表
        例如：["-y", "-p", "@modelcontextprotocol/server-filesystem"]
        默认值：[]

    env: dict[str, str]
        stdio 模式：额外的环境变量
        例如：{"NODE_ENV": "production"}
        默认值：{}

    url: str
        HTTP/SSE模式：端点URL
        例如："http://localhost:8080/sse"
        默认值：""

    headers: dict[str, str]
        HTTP/SSE模式：自定义请求头
        例如：{"Authorization": "Bearer xxx"}
        默认值：{}

    tool_timeout: int
        工具调用超时（秒）
        超过此时间的工具调用会被取消
        默认值：30 秒
    """

    type: Literal["stdio", "sse", "streamableHttp"] | None = None  # 不传则自动检测
    command: str = ""  # Stdio：要运行的命令（如 "npx"）
    args: list[str] = Field(default_factory=list)  # Stdio：命令参数
    env: dict[str, str] = Field(default_factory=dict)  # Stdio：额外环境变量
    url: str = ""  # HTTP/SSE：端点 URL
    headers: dict[str, str] = Field(default_factory=dict)  # HTTP/SSE：自定义请求头
    tool_timeout: int = 30  # 工具调用超时（秒）


class ToolsConfig(Base):
    """
    工具配置。

    这个类聚合了所有 Agent 工具的配置。

    属性说明：
    --------
    web: WebToolsConfig
        网络工具配置
        包含搜索、代理等设置

    exec: ExecToolConfig
        Shell exec 工具配置
        控制命令执行的超时和路径

    restrict_to_workspace: bool
        是否限制所有工具访问工作空间目录
        True: 工具只能访问 workspace 内的文件
        False: 工具可以访问任意路径
        默认值：False

    mcp_servers: dict[str, MCPServerConfig]
        MCP 服务器配置字典
        键：服务器名称，值：服务器配置
        例如：{"filesystem": MCPServerConfig(...)}
    """

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False  # True 则限制所有工具访问工作空间目录
    mcp_servers: dict[str, MCPServerConfig] = Field(default_factory=dict)


# =============================================================================
# Config - 根配置
# =============================================================================

class Config(BaseSettings):
    """
    nanobot 的根配置类。

    这个类是所有配置的入口，聚合了：
    - Agent 配置
    - 渠道配置
    - 提供商配置
    - 网关配置
    - 工具配置

    BaseSettings 的特性：
    ------------------
    - 支持从环境变量读取配置
    - 支持从 JSON 文件加载配置
    - 自动类型验证和转换

    属性说明：
    --------
    agents: AgentsConfig
        Agent 配置
        包含模型、温度、工作空间等

    channels: ChannelsConfig
        聊天渠道配置
        包含 Telegram、Discord 等所有渠道

    providers: ProvidersConfig
        LLM 提供商配置
        包含 OpenAI、Anthropic 等所有提供商

    gateway: GatewayConfig
        网关/服务器配置
        包含端口、心跳等

    tools: ToolsConfig
        工具配置
        包含网络搜索、exec、MCP 等

    属性方法：
    --------
    workspace_path: Path
        获取展开后的工作空间路径
        将~转换为用户主目录

    方法说明：
    --------
    _match_provider(model: str) -> tuple[ProviderConfig | None, str | None]
        根据模型名称匹配提供商配置
        返回 (配置对象，注册名称)

    get_provider(model: str) -> ProviderConfig | None
        获取匹配模型提供商的配置对象

    get_provider_name(model: str) -> str | None
        获取匹配模型的提供商注册名称

    get_api_key(model: str) -> str | None
        获取模型的 API 密钥

    get_api_base(model: str) -> str | None
        获取模型的 API 基础 URL
    """

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    @property
    def workspace_path(self) -> Path:
        """
        获取展开后的工作空间路径。

        将配置中的 workspace 字符串转换为 Path 对象，
        并将~展开为用户主目录。

        Returns:
            Path: 工作空间路径对象

        示例：
            >>> config.workspace_path
            PosixPath('/home/user/.nanobot/workspace')
        """
        return Path(self.agents.defaults.workspace).expanduser()

    def _match_provider(
        self, model: str | None = None
    ) -> tuple["ProviderConfig | None", str | None]:
        """
        根据模型名称匹配提供商配置和注册名称。

        匹配逻辑：
        --------
        1. 如果配置了强制提供商（provider != "auto"），直接返回
        2. 根据模型名称前缀匹配（如 "openai/..." 匹配 openai）
        3. 根据模型名称关键字匹配（如 "gpt" 匹配 openai）
        4. 本地提供商回退（如 Ollama）
        5. 网关回退（有 API 密钥的网关）

        Args:
            model: 模型名称（可选）
                不提供则使用配置的默认模型

        Returns:
            tuple[ProviderConfig | None, str | None]:
                - 第一项：提供商配置对象（api_key, api_base, extra_headers）
                - 第二项：注册名称（如 "deepseek", "openrouter"）

        示例：
            >>> config._match_provider("openai/gpt-4o")
            (ProviderConfig(api_key="sk-..."), "openai")
        """
        from nanobot.providers.registry import PROVIDERS

        # 检查是否配置了强制提供商
        forced = self.agents.defaults.provider
        if forced != "auto":
            # 获取强制提供商的配置
            p = getattr(self.providers, forced, None)
            # 如果配置存在，返回；否则返回 None
            return (p, forced) if p else (None, None)

        # 将模型名称转为小写用于匹配
        model_lower = (model or self.agents.defaults.model).lower()
        model_normalized = model_lower.replace("-", "_")  # 统一分隔符
        # 提取提供商前缀（如 "openai/gpt-4o" -> "openai"）
        model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
        normalized_prefix = model_prefix.replace("-", "_")

        def _kw_matches(kw: str) -> bool:
            """检查关键字是否匹配模型名称。"""
            kw = kw.lower()
            return kw in model_lower or kw.replace("-", "_") in model_normalized

        # 优先匹配显式提供商前缀
        # 这可以防止 `github-copilot/...codex` 错误匹配到 openai_codex
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and model_prefix and normalized_prefix == spec.name:
                # OAuth 提供商需要有 API 密钥，本地提供商不需要
                if spec.is_oauth or spec.is_local or p.api_key:
                    return p, spec.name

        # 按关键字匹配（顺序遵循 PROVIDERS 注册表）
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and any(_kw_matches(kw) for kw in spec.keywords):
                # OAuth/本地提供商需要有 API 密钥，其他直接返回
                if spec.is_oauth or spec.is_local or p.api_key:
                    return p, spec.name

        # 回退：配置的本地提供商可以路由没有提供商特定关键字的模型
        # 例如纯 "llama3.2" 在 Ollama 上运行
        # 优先返回 detect_by_base_keyword 匹配 api_base 的提供商
        # 例如 Ollama 的 "11434" 在 "http://localhost:11434"
        local_fallback: tuple[ProviderConfig, str] | None = None
        for spec in PROVIDERS:
            if not spec.is_local:
                continue
            p = getattr(self.providers, spec.name, None)
            if not (p and p.api_base):
                continue
            # 如果 api_base 包含特征关键字，优先返回
            if spec.detect_by_base_keyword and spec.detect_by_base_keyword in p.api_base:
                return p, spec.name
            # 否则记录第一个本地提供商作为回退
            if local_fallback is None:
                local_fallback = (p, spec.name)
        if local_fallback:
            return local_fallback

        # 回退：网关优先，然后其他（遵循注册表顺序）
        # OAuth 提供商不是有效的回退——它们需要显式的模型选择
        for spec in PROVIDERS:
            if spec.is_oauth:
                continue
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p, spec.name
        return None, None

    def get_provider(self, model: str | None = None) -> ProviderConfig | None:
        """
        获取匹配模型的提供商配置对象。

        Args:
            model: 模型名称（可选）

        Returns:
            ProviderConfig | None: 提供商配置对象
                包含 api_key, api_base, extra_headers
        """
        p, _ = self._match_provider(model)
        return p

    def get_provider_name(self, model: str | None = None) -> str | None:
        """
        获取匹配模型的提供商注册名称。

        Args:
            model: 模型名称（可选）

        Returns:
            str | None: 注册名称
                如 "deepseek", "openrouter", "anthropic"

        示例：
            >>> config.get_provider_name("claude-3-5-sonnet")
            'anthropic'
        """
        _, name = self._match_provider(model)
        return name

    def get_api_key(self, model: str | None = None) -> str | None:
        """
        获取给定模型的 API 密钥。

        Args:
            model: 模型名称（可选）

        Returns:
            str | None: API 密钥
                如果未配置返回 None
        """
        p = self.get_provider(model)
        return p.api_key if p else None

    def get_api_base(self, model: str | None = None) -> str | None:
        """
        获取给定模型的 API 基础 URL。

        为网关和本地提供商应用默认 URL。

        Args:
            model: 模型名称（可选）

        Returns:
            str | None: API 基础 URL
                如果未配置返回 None

        注意：
        ----
        标准提供商（如 Moonshot）通过 _setup_env 中的
        环境变量设置 base URL，避免污染全局 litellm.api_base
        """
        from nanobot.providers.registry import find_by_name

        p, name = self._match_provider(model)
        # 如果配置了 api_base，直接返回
        if p and p.api_base:
            return p.api_base
        # 只有网关和本地提供商在这里获取默认 api_base
        if name:
            spec = find_by_name(name)
            # 网关或本地提供商，且有默认 API 端点
            if spec and (spec.is_gateway or spec.is_local) and spec.default_api_base:
                return spec.default_api_base
        return None

    # BaseSettings 配置：支持从环境变量读取
    # env_prefix="NANOBOT_": 环境变量前缀
    #   例如：NANOBOT_AGENTS__DEFAULTS__MODEL=anthropic/claude-3
    # env_nested_delimiter="__": 嵌套配置分隔符
    #   例如：NANOBOT_PROVIDERS__OPENAI__API_KEY=sk-123
    model_config = ConfigDict(env_prefix="NANOBOT_", env_nested_delimiter="__")

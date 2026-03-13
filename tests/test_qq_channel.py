# =============================================================================
# nanobot QQ 渠道测试
# 文件路径：tests/test_qq_channel.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件测试了 nanobot 的 QQ 渠道（QQChannel）功能。
# QQ 渠道是 nanobot 与 QQ 机器人平台集成的接口模块。
#
# 测试的核心功能：
# -------------------------
# - 测试 QQ 群消息的处理逻辑
# - 测试 QQ 消息发送时使用正确的 API（群 API vs C2C API）
# - 测试 msg_seq 参数的正确使用（QQ API 要求的消息序列号）
#
# 关键测试场景：
# -------------------------
# 1. 群消息路由：验证群消息能够正确路由到群 chat_id
# 2. 群消息发送：验证发送群消息时使用群 API 并设置 msg_seq
#
# 使用示例：
# -------------------------
# 运行测试：pytest tests/test_qq_channel.py -v
#
# 相关模块：
# - nanobot/channels/qq.py - QQ 渠道实现
# - nanobot/config/schema.py - QQConfig 配置类
#
# QQ 渠道说明：
# -------------------------
# QQ 渠道支持两种消息类型：
# - C2C 消息（用户对机器人私聊）
# - 群消息（QQ 群内的消息）
#
# QQ API 要求：
# - 群消息需要使用 post_group_message 接口
# - C2C 消息需要使用 post_c2c_message 接口
# - 回复消息时需要设置 msg_seq 参数（消息序列号）
# =============================================================================

from types import SimpleNamespace

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.qq import QQChannel
from nanobot.config.schema import QQConfig


class _FakeApi:
    """
    伪造的 QQ API 客户端

    用于替代真实的 QQ API 客户端，记录所有 API 调用
    以便在测试中断言验证 API 是否被正确调用
    """

    def __init__(self) -> None:
        # 记录所有 C2C 消息发送调用
        self.c2c_calls: list[dict] = []
        # 记录所有群消息发送调用
        self.group_calls: list[dict] = []

    async def post_c2c_message(self, **kwargs) -> None:
        """伪造 C2C 消息发送 API 调用"""
        self.c2c_calls.append(kwargs)

    async def post_group_message(self, **kwargs) -> None:
        """伪造群消息发送 API 调用"""
        self.group_calls.append(kwargs)


class _FakeClient:
    """
    伪造的 QQ 客户端

    包含伪造的 API 对象，用于模拟 QQ 客户端的行为
    """

    def __init__(self) -> None:
        self.api = _FakeApi()


@pytest.mark.asyncio
async def test_on_group_message_routes_to_group_chat_id() -> None:
    """
    测试 QQ 群消息能够正确路由到群 chat_id

    验证点：
    - 群消息的 sender_id 应该是消息作者的 member_openid
    - 群消息的 chat_id 应该是群的 group_openid

    测试步骤：
    1. 创建 QQ 渠道实例，配置允许 user1 发送消息
    2. 模拟一个群消息数据（包含 group_openid 和 author 信息）
    3. 调用 _on_message 处理消息
    4. 从消息总线消费入站消息并验证字段
    """
    # 创建 QQ 渠道实例
    # app_id 和 secret 是 QQ 机器人应用的凭证
    # allow_from=["user1"] 表示只允许 user1 发送消息
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus())

    # 构造模拟的群消息数据
    # id: 消息 ID
    # content: 消息内容
    # group_openid: 群的 openid（群聊唯一标识）
    # author.member_openid: 消息作者的 member openid（群成员唯一标识）
    data = SimpleNamespace(
        id="msg1",
        content="hello",
        group_openid="group123",
        author=SimpleNamespace(member_openid="user1"),
    )

    # 调用消息处理函数，is_group=True 表示这是群消息
    await channel._on_message(data, is_group=True)

    # 从消息总线消费入站消息
    msg = await channel.bus.consume_inbound()
    # 验证发送者 ID 是作者的 member_openid
    assert msg.sender_id == "user1"
    # 验证聊天 ID 是群的 group_openid
    assert msg.chat_id == "group123"


@pytest.mark.asyncio
async def test_send_group_message_uses_group_api_with_msg_seq() -> None:
    """
    测试发送 QQ 群消息时使用群 API 并正确设置 msg_seq 参数

    验证点：
    - 调用的是群 API（post_group_message）而非 C2C API
    - group_openid 参数正确
    - msg_id 参数正确（用于回复消息）
    - msg_seq 参数为 2（QQ API 要求：首条消息为 1，回复消息从 2 开始）

    QQ API msg_seq 说明：
    - msg_seq 是消息序列号，用于标识消息的顺序
    - 主动发送消息时 msg_seq 从 1 开始
    - 回复消息时 msg_seq 应该设置为 2（表示这是对前一条消息的回复）
    """
    # 创建 QQ 渠道实例，allow_from=["*"] 表示允许所有用户
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["*"]), MessageBus())
    # 注入伪造的客户端
    channel._client = _FakeClient()
    # 设置聊天类型缓存，表示 group123 是一个群聊
    channel._chat_type_cache["group123"] = "group"

    # 发送群消息
    await channel.send(
        OutboundMessage(
            channel="qq",  # 渠道类型
            chat_id="group123",  # 目标群 ID
            content="hello",  # 消息内容
            metadata={"message_id": "msg1"},  # 元数据，包含原消息 ID（用于回复）
        )
    )

    # 验证调用了 1 次群 API
    assert len(channel._client.api.group_calls) == 1
    # 获取第一次调用群 API 的参数
    call = channel._client.api.group_calls[0]
    # 验证群 openid 参数正确
    assert call["group_openid"] == "group123"
    # 验证原消息 ID 正确（用于回复）
    assert call["msg_id"] == "msg1"
    # 验证消息序列号为 2（表示这是回复消息）
    assert call["msg_seq"] == 2
    # 验证没有调用 C2C API
    assert not channel._client.api.c2c_calls

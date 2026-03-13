# =============================================================================
# 钉钉渠道测试
# 文件路径：tests/test_dingtalk_channel.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了钉钉 (DingTalk) 渠道的测试功能，主要测试：
# 1. 群消息的发送和接收逻辑
# 2. 消息路由和聊天 ID 处理
# 3. 语音识别文本的回退处理
#
# 测试场景：
# --------
# 1. test_group_message_keeps_sender_id_and_routes_chat_id
#    - 测试群聊消息正确保留发送者 ID
#    - 测试聊天 ID 正确路由为 "group:conv123" 格式
#    - 验证 conversation_type 元数据正确传递
#
# 2. test_group_send_uses_group_messages_api
#    - 测试群消息发送使用正确的钉钉 API 端点
#    - 验证 API 请求参数格式正确
#
# 3. test_handler_uses_voice_recognition_text_when_text_is_empty
#    - 测试当消息文本为空时，使用语音识别结果作为替代
#    - 验证扩展字段 (extensions) 中的语音转录内容
#
# 使用示例：
# --------
# pytest tests/test_dingtalk_channel.py -v
# =============================================================================

import asyncio
from types import SimpleNamespace

import pytest

from nanobot.bus.queue import MessageBus
import nanobot.channels.dingtalk as dingtalk_module
from nanobot.channels.dingtalk import DingTalkChannel, NanobotDingTalkHandler
from nanobot.config.schema import DingTalkConfig


class _FakeResponse:
    """模拟 HTTP 响应对象。

    用于测试中替代真实的 HTTP 响应，避免发起实际的网络请求。

    Attributes:
        status_code: HTTP 状态码，默认为 200
        _json_body: JSON 响应体，默认为空字典
        text: 原始响应文本，默认为空字符串
    """

    def __init__(self, status_code: int = 200, json_body: dict | None = None) -> None:
        self.status_code = status_code
        self._json_body = json_body or {}
        self.text = "{}"

    def json(self) -> dict:
        """返回 JSON 响应体。"""
        return self._json_body


class _FakeHttp:
    """模拟 HTTP 客户端对象。

    用于测试中替代真实的 HTTP 客户端，记录所有 POST 请求的参数，
    以便后续验证 API 调用是否正确。

    Attributes:
        calls: 记录所有 post() 调用的列表，每个元素包含 url、json、headers
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def post(self, url: str, json=None, headers=None):
        """模拟异步 POST 请求。

        记录请求参数并返回伪造的响应。

        Args:
            url: 请求 URL
            json: JSON 请求体
            headers: HTTP 请求头

        Returns:
            _FakeResponse 对象
        """
        self.calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse()


@pytest.mark.asyncio
async def test_group_message_keeps_sender_id_and_routes_chat_id() -> None:
    """测试群消息正确保留发送者 ID 并路由聊天 ID。

    验证场景：
    1. 用户 "user1" 在钉钉群聊中发送消息
    2. conversation_type="2" 表示群聊（1 表示单聊）
    3. 消息的 chat_id 应该是 "group:conv123" 格式
    4. sender_id 应该保持为 "user1"
    5. metadata 应该包含 conversation_type

    钉钉消息类型说明:
    - conversation_type="1": 单聊
    - conversation_type="2": 群聊
    """
    # 创建钉钉配置，允许 user1 发送消息
    config = DingTalkConfig(client_id="app", client_secret="secret", allow_from=["user1"])
    bus = MessageBus()
    channel = DingTalkChannel(config, bus)

    # 模拟接收群聊消息
    await channel._on_message(
        "hello",  # 消息内容
        sender_id="user1",  # 发送者 ID
        sender_name="Alice",  # 发送者昵称
        conversation_type="2",  # 群聊类型
        conversation_id="conv123",  # 会话 ID
    )

    # 从消息总线获取处理后的消息
    msg = await bus.consume_inbound()
    assert msg.sender_id == "user1"  # 发送者 ID 保持不变
    assert msg.chat_id == "group:conv123"  # 群聊 ID 添加 "group:" 前缀
    assert msg.metadata["conversation_type"] == "2"  # 元数据保留会话类型


@pytest.mark.asyncio
async def test_group_send_uses_group_messages_api() -> None:
    """测试群消息发送使用正确的钉钉 API 端点。

    验证场景：
    1. 发送消息到群聊 "group:conv123"
    2. 应该调用钉钉的 groupMessages/send API
    3. API 请求参数 openConversationId 应该是会话 ID（不含 "group:" 前缀）
    4. msgKey 应该是消息类型，如 "sampleMarkdown"

    钉钉群消息 API:
    - URL: https://api.dingtalk.com/v1.0/robot/groupMessages/send
    - 关键参数:
      - openConversationId: 群会话 ID
      - msgKey: 消息类型（如 sampleText, sampleMarkdown, sampleLink 等）
      - msgParam: 消息内容参数
    """
    # 创建配置，允许所有人发送消息（"*" 表示通配符）
    config = DingTalkConfig(client_id="app", client_secret="secret", allow_from=["*"])
    channel = DingTalkChannel(config, MessageBus())
    # 注入伪造的 HTTP 客户端，用于捕获 API 调用
    channel._http = _FakeHttp()

    # 发送群消息
    ok = await channel._send_batch_message(
        "token",  # 访问令牌
        "group:conv123",  # 群聊 ID
        "sampleMarkdown",  # 消息类型
        {"text": "hello", "title": "Nanobot Reply"},  # 消息参数
    )

    # 验证发送成功
    assert ok is True
    call = channel._http.calls[0]
    # 验证 API 端点正确
    assert call["url"] == "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
    # 验证请求参数正确（去除 "group:" 前缀）
    assert call["json"]["openConversationId"] == "conv123"
    # 验证消息类型正确
    assert call["json"]["msgKey"] == "sampleMarkdown"


@pytest.mark.asyncio
async def test_handler_uses_voice_recognition_text_when_text_is_empty(monkeypatch) -> None:
    """测试当消息文本为空时，处理器使用语音识别结果。

    验证场景：
    1. 用户发送语音消息，text.content 为空
    2. extensions.content.recognition 包含语音转录文本
    3. 处理器应该使用语音转录文本作为消息内容
    4. sender_id 应该优先使用 staff_id（如果存在）

    钉钉语音消息处理:
    - 当用户发送语音时，消息类型为 "audio"
    - text.content 可能为空
    - extensions.content.recognition 包含语音识别结果
    - sender_staff_id 优先于 sender_id（企业内部用户有 staff_id）
    """
    bus = MessageBus()
    channel = DingTalkChannel(
        DingTalkConfig(client_id="app", client_secret="secret", allow_from=["user1"]),
        bus,
    )
    handler = NanobotDingTalkHandler(channel)

    # 伪造 ChatbotMessage 类，模拟语音消息
    class _FakeChatbotMessage:
        text = None  # 文本内容为空
        extensions = {"content": {"recognition": "voice transcript"}}  # 语音识别结果
        sender_staff_id = "user1"  # 员工 ID（优先使用）
        sender_id = "fallback-user"  # 备用 ID
        sender_nick = "Alice"  # 昵称
        message_type = "audio"  # 消息类型：音频

        @staticmethod
        def from_dict(_data):
            return _FakeChatbotMessage()

    # 使用 monkeypatch 替换原始类
    monkeypatch.setattr(dingtalk_module, "ChatbotMessage", _FakeChatbotMessage)
    monkeypatch.setattr(dingtalk_module, "AckMessage", SimpleNamespace(STATUS_OK="OK"))

    # 处理消息（text.content 为空）
    status, body = await handler.process(
        SimpleNamespace(
            data={
                "conversationType": "2",  # 群聊
                "conversationId": "conv123",
                "text": {"content": ""},  # 空文本
            }
        )
    )

    # 等待后台任务完成
    await asyncio.gather(*list(channel._background_tasks))
    msg = await bus.consume_inbound()

    # 验证处理结果
    assert (status, body) == ("OK", "OK")  # 响应状态正常
    assert msg.content == "voice transcript"  # 使用语音识别结果
    assert msg.sender_id == "user1"  # 使用 staff_id
    assert msg.chat_id == "group:conv123"  # 群聊 ID 正确

# =============================================================================
# nanobot Slack 渠道测试
# 文件路径：tests/test_slack_channel.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件测试了 nanobot 的 Slack 渠道（SlackChannel）功能。
# Slack 渠道是 nanobot 与 Slack 平台集成的接口模块。
#
# 测试的核心功能：
# -------------------------
# - 测试 Slack 渠道发送消息时使用 Slack Web API
# - 测试频道（channel）消息使用线程（thread）回复
# - 测试私信（DM/im）消息不使用线程回复
#
# 关键测试场景：
# -------------------------
# 1. 频道消息：验证发送频道消息时使用 thread_ts 保持对话上下文
# 2. 私信消息：验证发送私信时不使用 thread_ts（私信不需要线程）
#
# 使用示例：
# -------------------------
# 运行测试：pytest tests/test_slack_channel.py -v
#
# 相关模块：
# - nanobot/channels/slack.py - Slack 渠道实现
# - nanobot/config/schema.py - SlackConfig 配置类
#
# Slack 渠道说明：
# -------------------------
# Slack 渠道支持两种消息类型：
# - Channel 消息（公共频道或私有频道内的消息）
# - DM/IM 消息（直接消息/私信）
#
# Slack API 说明：
# - chat.postMessage: 发送消息到频道或私信
# - files.upload_v2: 上传文件到 Slack
#
# thread_ts 说明：
# - thread_ts 是 Slack 的线程时间戳
# - 当设置 thread_ts 时，消息会作为回复添加到线程中
# - 私信（DM）不需要 thread_ts，因为私信本身就是单线对话
#
# chat_id 命名规则：
# - 频道 ID 以 "C" 开头（如 C123）
# - 私信 ID 以 "D" 开头（如 D123）
# =============================================================================

from __future__ import annotations

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.slack import SlackChannel
from nanobot.config.schema import SlackConfig


class _FakeAsyncWebClient:
    """
    伪造的 Slack AsyncWebClient

    用于替代真实的 Slack Web API 客户端，记录所有 API 调用
    以便在测试中断言验证 API 是否被正确调用

    这个伪造客户端模拟了两个核心 API：
    1. chat_postMessage - 发送消息
    2. files_upload_v2 - 上传文件
    """

    def __init__(self) -> None:
        # 记录所有 chat.postMessage API 调用
        # 每个调用记录包含：channel, text, thread_ts
        self.chat_post_calls: list[dict[str, object | None]] = []
        # 记录所有 files.upload_v2 API 调用
        # 每个调用记录包含：channel, file, thread_ts
        self.file_upload_calls: list[dict[str, object | None]] = []

    async def chat_postMessage(
        self,
        *,
        channel: str,
        text: str,
        thread_ts: str | None = None,
    ) -> None:
        """
        伪造 chat.postMessage API 调用

        参数：
            channel: 目标频道 ID（如 C123）或私信 ID（如 D123）
            text: 消息文本内容
            thread_ts: 可选，线程时间戳（用于回复到线程）
        """
        self.chat_post_calls.append(
            {
                "channel": channel,
                "text": text,
                "thread_ts": thread_ts,
            }
        )

    async def files_upload_v2(
        self,
        *,
        channel: str,
        file: str,
        thread_ts: str | None = None,
    ) -> None:
        """
        伪造 files.upload_v2 API 调用

        参数：
            channel: 目标频道 ID 或私信 ID
            file: 文件路径
            thread_ts: 可选，线程时间戳（用于回复到线程）
        """
        self.file_upload_calls.append(
            {
                "channel": channel,
                "file": file,
                "thread_ts": thread_ts,
            }
        )


@pytest.mark.asyncio
async def test_send_uses_thread_for_channel_messages() -> None:
    """
    测试 Slack 渠道发送频道消息时使用线程（thread）回复

    验证点：
    - 调用 chat.postMessage API 发送消息
    - 消息文本末尾添加了换行符（"hello\n"）
    - thread_ts 正确传递给 API（保持在原线程中回复）
    - 调用 files.upload_v2 API 上传文件
    - 文件上传也使用相同的 thread_ts

    测试场景说明：
    - chat_id="C123" 表示这是一个频道消息（C 开头表示 Channel）
    - channel_type="channel" 明确表示这是频道类型
    - 频道消息应该保持在原线程中回复，所以 thread_ts 应该被传递
    """
    # 创建 Slack 渠道实例
    # SlackConfig(enabled=True) 表示启用 Slack 渠道
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    # 创建伪造的 Web 客户端
    fake_web = _FakeAsyncWebClient()
    # 注入伪造的 Web 客户端
    channel._web_client = fake_web

    # 发送 Slack 消息
    await channel.send(
        OutboundMessage(
            channel="slack",  # 渠道类型
            chat_id="C123",  # 目标频道 ID（C 开头表示 Channel）
            content="hello",  # 消息内容
            media=["/tmp/demo.txt"],  # 附件文件列表
            metadata={
                "slack": {
                    # 线程时间戳，用于在原线程中回复
                    "thread_ts": "1700000000.000100",
                    # 频道类型：channel 表示公共/私有频道
                    "channel_type": "channel",
                }
            },
        )
    )

    # 验证调用了 1 次 chat.postMessage API
    assert len(fake_web.chat_post_calls) == 1
    # 验证消息文本正确（末尾添加了换行符）
    assert fake_web.chat_post_calls[0]["text"] == "hello\n"
    # 验证 thread_ts 正确传递（保持在原线程中回复）
    assert fake_web.chat_post_calls[0]["thread_ts"] == "1700000000.000100"
    # 验证调用了 1 次 files.upload_v2 API
    assert len(fake_web.file_upload_calls) == 1
    # 验证文件上传也使用相同的 thread_ts
    assert fake_web.file_upload_calls[0]["thread_ts"] == "1700000000.000100"


@pytest.mark.asyncio
async def test_send_omits_thread_for_dm_messages() -> None:
    """
    测试 Slack 渠道发送私信（DM）消息时不使用线程回复

    验证点：
    - 调用 chat.postMessage API 发送消息
    - thread_ts 为 None（私信不需要线程回复）
    - 调用 files.upload_v2 API 上传文件
    - 文件上传的 thread_ts 也为 None

    测试场景说明：
    - chat_id="D123" 表示这是一个私信消息（D 开头表示 DM/IM）
    - channel_type="im" 明确表示这是私信类型
    - 私信消息不需要 thread_ts，因为私信本身就是单线对话

    为什么私信不需要 thread_ts？
    - Slack 的私信（Direct Message / Instant Message）是单线对话
    - 没有线程（thread）的概念
    - 所有消息都直接显示在对话窗口中
    """
    # 创建 Slack 渠道实例
    channel = SlackChannel(SlackConfig(enabled=True), MessageBus())
    # 创建伪造的 Web 客户端
    fake_web = _FakeAsyncWebClient()
    # 注入伪造的 Web 客户端
    channel._web_client = fake_web

    # 发送 Slack 私信消息
    await channel.send(
        OutboundMessage(
            channel="slack",  # 渠道类型
            chat_id="D123",  # 目标私信 ID（D 开头表示 DM）
            content="hello",  # 消息内容
            media=["/tmp/demo.txt"],  # 附件文件列表
            metadata={
                "slack": {
                    # 虽然有 thread_ts，但私信不应该使用
                    "thread_ts": "1700000000.000100",
                    # 频道类型：im 表示私信（Instant Message）
                    "channel_type": "im",
                }
            },
        )
    )

    # 验证调用了 1 次 chat.postMessage API
    assert len(fake_web.chat_post_calls) == 1
    # 验证消息文本正确
    assert fake_web.chat_post_calls[0]["text"] == "hello\n"
    # 验证 thread_ts 为 None（私信不使用线程回复）
    assert fake_web.chat_post_calls[0]["thread_ts"] is None
    # 验证调用了 1 次 files.upload_v2 API
    assert len(fake_web.file_upload_calls) == 1
    # 验证文件上传的 thread_ts 也为 None
    assert fake_web.file_upload_calls[0]["thread_ts"] is None

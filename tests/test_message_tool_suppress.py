# =============================================================================
# nanobot MessageTool 抑制逻辑测试
# 文件路径：tests/test_message_tool_suppress.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件测试了 AgentLoop 中 MessageTool 的抑制逻辑（suppress logic）。
# 当机器人使用 message 工具发送消息到与用户相同的渠道/聊天时，
# 最终回复应该被抑制（不再发送一条重复的回复消息）。
#
# 测试的核心功能：
# -------------------------
# - 测试当 message tool 发送到相同目标时，最终回复被抑制
# - 测试当 message tool 发送到不同目标时，最终回复不被抑制
# - 测试当没有使用 message tool 时，正常返回回复
# - 测试进度消息隐藏内部推理内容（<think> 标签等）
# - 测试 MessageTool 的 turn 追踪功能
#
# 关键测试场景：
# -------------------------
# 1. 抑制场景：发送到相同渠道/聊天 ID 时抑制回复
# 2. 不抑制场景：发送到不同渠道时不抑制回复
# 3. 不抑制场景：未使用 message tool 时正常回复
# 4. 进度消息：隐藏 <think> 标签和 reasoning_content
# 5. Turn 追踪：测试 _sent_in_turn 和 start_turn 方法
#
# 使用示例：
# -------------------------
# 运行测试：pytest tests/test_message_tool_suppress.py -v
#
# 相关模块：
# - nanobot/agent/loop.py - AgentLoop 类，包含 _process_message 方法
# - nanobot/agent/tools/message.py - MessageTool 类
# - nanobot/bus/events.py - InboundMessage、OutboundMessage 事件类
#
# 抑制逻辑说明：
# -------------------------
# 当用户让机器人发送消息时：
# 1. 用户：「给张三发个消息说你好」
# 2. 机器人调用 message tool 发送消息给张三
# 3. 如果回复也发送到相同渠道，用户会看到两条消息
#
# 抑制逻辑确保：
# - 当 message tool 发送到相同目标时，不再发送最终回复
# - 当 message tool 发送到不同目标时，仍发送回复告知用户
#
# 例如：
# - 用户在飞书让机器人发送邮件 -> 回复应该发送（告知用户已发送）
# - 用户在飞书让机器人发飞书消息 -> 回复应该抑制（避免重复）
# =============================================================================

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.message import MessageTool
from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse, ToolCallRequest


def _make_loop(tmp_path: Path) -> AgentLoop:
    """
    辅助函数：创建一个最小化的 AgentLoop 实例用于测试

    参数：
        tmp_path: pytest 提供的临时目录路径

    返回：
        AgentLoop: 配置了模拟依赖的 AgentLoop 实例
    """
    # 创建消息总线
    bus = MessageBus()
    # 创建模拟的 LLM Provider
    provider = MagicMock()
    # 配置默认模型返回值
    provider.get_default_model.return_value = "test-model"
    # 创建并返回 AgentLoop 实例
    return AgentLoop(bus=bus, provider=provider, workspace=tmp_path, model="test-model")


class TestMessageToolSuppressLogic:
    """
    测试 MessageTool 抑制逻辑

    验证最终回复只在 message tool 发送到相同目标渠道时被抑制
    """

    @pytest.mark.asyncio
    async def test_suppress_when_sent_to_same_target(self, tmp_path: Path) -> None:
        """
        测试当 message tool 发送到相同目标时，最终回复被抑制

        验证点：
        - 发送了一条出站消息（通过 message tool）
        - _process_message 返回 None（表示回复被抑制）

        测试场景：
        - 用户在 feishu 渠道发送「Send」
        - 机器人调用 message tool 发送消息到 feishu 渠道的相同 chat_id
        - 预期最终回复被抑制（返回 None）
        """
        # 创建 AgentLoop 实例
        loop = _make_loop(tmp_path)
        # 创建 tool call 请求，发送到相同的 feishu 渠道和 chat_id
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Hello", "channel": "feishu", "chat_id": "chat123"},
        )
        # 创建迭代器，模拟两次 LLM 响应
        # 第一次：调用 message tool
        # 第二次：返回 "Done"（但没有 tool_calls，表示结束）
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        # 配置 mock 的 chat_with_retry 方法
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        # 配置 tools.get_definitions 返回空列表
        loop.tools.get_definitions = MagicMock(return_value=[])

        # 记录发送的消息列表
        sent: list[OutboundMessage] = []
        # 获取 message tool 并设置发送回调
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        # 创建入站消息（来自 feishu 渠道的 chat123）
        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send")
        # 处理消息
        result = await loop._process_message(msg)

        # 验证发送了一条消息
        assert len(sent) == 1
        # 验证最终回复被抑制（返回 None）
        assert result is None  # suppressed

    @pytest.mark.asyncio
    async def test_not_suppress_when_sent_to_different_target(self, tmp_path: Path) -> None:
        """
        测试当 message tool 发送到不同目标时，最终回复不被抑制

        验证点：
        - 发送了一条出站消息（通过 message tool）
        - 消息发送到不同的渠道（email）
        - _process_message 返回非 None（表示回复不被抑制）
        - 回复发送回原始渠道（feishu）

        测试场景：
        - 用户在 feishu 渠道发送「Send email」
        - 机器人调用 message tool 发送邮件到 email 渠道
        - 预期最终回复不被抑制，告知用户已发送
        """
        # 创建 AgentLoop 实例
        loop = _make_loop(tmp_path)
        # 创建 tool call 请求，发送到不同的 email 渠道
        tool_call = ToolCallRequest(
            id="call1", name="message",
            arguments={"content": "Email content", "channel": "email", "chat_id": "user@example.com"},
        )
        # 创建迭代器，模拟两次 LLM 响应
        calls = iter([
            LLMResponse(content="", tool_calls=[tool_call]),
            LLMResponse(content="I've sent the email.", tool_calls=[]),
        ])
        # 配置 mock 的 chat_with_retry 方法
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        # 配置 tools.get_definitions 返回空列表
        loop.tools.get_definitions = MagicMock(return_value=[])

        # 记录发送的消息列表
        sent: list[OutboundMessage] = []
        # 获取 message tool 并设置发送回调
        mt = loop.tools.get("message")
        if isinstance(mt, MessageTool):
            mt.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        # 创建入站消息（来自 feishu 渠道）
        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Send email")
        # 处理消息
        result = await loop._process_message(msg)

        # 验证发送了一条消息
        assert len(sent) == 1
        # 验证消息发送到 email 渠道
        assert sent[0].channel == "email"
        # 验证最终回复不被抑制
        assert result is not None  # not suppressed
        # 验证回复发送回原始渠道（feishu）
        assert result.channel == "feishu"

    @pytest.mark.asyncio
    async def test_not_suppress_when_no_message_tool_used(self, tmp_path: Path) -> None:
        """
        测试当没有使用 message tool 时，正常返回回复

        验证点：
        - 没有发送任何出站消息
        - _process_message 返回包含回复内容的消息

        测试场景：
        - 用户在 feishu 渠道发送「Hi」
        - 机器人直接回复「Hello!」
        - 预期正常返回回复
        """
        # 创建 AgentLoop 实例
        loop = _make_loop(tmp_path)
        # 配置 mock 的 chat_with_retry 方法，直接返回回复
        loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="Hello!", tool_calls=[]))
        # 配置 tools.get_definitions 返回空列表
        loop.tools.get_definitions = MagicMock(return_value=[])

        # 创建入站消息
        msg = InboundMessage(channel="feishu", sender_id="user1", chat_id="chat123", content="Hi")
        # 处理消息
        result = await loop._process_message(msg)

        # 验证返回了回复
        assert result is not None
        # 验证回复内容正确
        assert "Hello" in result.content

    async def test_progress_hides_internal_reasoning(self, tmp_path: Path) -> None:
        """
        测试进度消息隐藏内部推理内容

        验证点：
        - <think> 标签内的内容不显示在进度中
        - <think> 标签外的内容显示在进度中
        - reasoning_content 不显示
        - thinking_blocks 不显示
        - tool calls 显示为工具调用格式

        测试场景：
        - LLM 返回包含 <think> 标签的响应
        - 进度消息应该只显示可见内容
        """
        # 创建 AgentLoop 实例
        loop = _make_loop(tmp_path)
        # 创建 tool call 请求
        tool_call = ToolCallRequest(id="call1", name="read_file", arguments={"path": "foo.txt"})
        # 创建迭代器，模拟两次 LLM 响应
        # 第一次响应包含：
        # - content: "Visible<think>hidden</think>"（<think> 标签包裹隐藏内容）
        # - reasoning_content: 秘密推理内容（不显示）
        # - thinking_blocks: 秘密思考块（不显示）
        # - tool_calls: 工具调用（显示为工具提示）
        calls = iter([
            LLMResponse(
                content="Visible<think>hidden</think>",
                tool_calls=[tool_call],
                reasoning_content="secret reasoning",
                thinking_blocks=[{"signature": "sig", "thought": "secret thought"}],
            ),
            LLMResponse(content="Done", tool_calls=[]),
        ])
        # 配置 mock 的 chat_with_retry 方法
        loop.provider.chat_with_retry = AsyncMock(side_effect=lambda *a, **kw: next(calls))
        # 配置 tools.get_definitions 返回空列表
        loop.tools.get_definitions = MagicMock(return_value=[])
        # 配置工具执行返回 "ok"
        loop.tools.execute = AsyncMock(return_value="ok")

        # 记录进度消息列表
        progress: list[tuple[str, bool]] = []

        async def on_progress(content: str, *, tool_hint: bool = False) -> None:
            """捕获进度回调"""
            progress.append((content, tool_hint))

        # 运行 agent 循环
        final_content, _, _ = await loop._run_agent_loop([], on_progress=on_progress)

        # 验证最终内容正确
        assert final_content == "Done"
        # 验证进度消息只包含可见内容和工具调用
        assert progress == [
            ("Visible", False),  # <think> 标签外的可见内容
            ('read_file("foo.txt")', True),  # 工具调用（tool_hint=True）
        ]


class TestMessageToolTurnTracking:
    """
    测试 MessageTool 的 turn（轮次）追踪功能

    MessageTool 使用 _sent_in_turn 追踪在当前 turn 中是否已经发送了消息
    start_turn() 方法在每次 turn 开始时重置这个标志
    """

    def test_sent_in_turn_tracks_same_target(self) -> None:
        """
        测试 _sent_in_turn 属性追踪当前 turn 中是否发送了消息

        验证点：
        - 初始时 _sent_in_turn 为 False
        - 设置 _sent_in_turn 为 True 后，值为 True
        """
        # 创建 MessageTool 实例
        tool = MessageTool()
        # 设置上下文（渠道和聊天 ID）
        tool.set_context("feishu", "chat1")
        # 验证初始时 _sent_in_turn 为 False
        assert not tool._sent_in_turn
        # 设置 _sent_in_turn 为 True
        tool._sent_in_turn = True
        # 验证 _sent_in_turn 为 True
        assert tool._sent_in_turn

    def test_start_turn_resets(self) -> None:
        """
        测试 start_turn() 方法重置 _sent_in_turn 标志

        验证点：
        - 设置 _sent_in_turn 为 True 后
        - 调用 start_turn() 后，_sent_in_turn 重置为 False
        """
        # 创建 MessageTool 实例
        tool = MessageTool()
        # 设置 _sent_in_turn 为 True
        tool._sent_in_turn = True
        # 调用 start_turn() 重置标志
        tool.start_turn()
        # 验证 _sent_in_turn 重置为 False
        assert not tool._sent_in_turn

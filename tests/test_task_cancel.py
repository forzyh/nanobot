# =============================================================================
# nanobot 任务取消功能测试
# 文件路径：tests/test_task_cancel.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 nanobot 任务取消功能（/stop 命令）的单元测试。
# 主要测试 AgentLoop 中的 _handle_stop 方法以及相关的任务管理功能。
#
# 测试的核心功能：
# -------------------------
# 1. 任务取消功能：测试 /stop 命令如何取消正在运行的任务
# 2. 消息分发：测试消息如何被正确处理和发布
# 3. 子代理管理：测试子代理任务的管理和取消
#
# 关键测试场景：
# --------
# 1. 没有活动任务时调用 /stop 的情况
# 2. 取消单个活动任务的场景
# 3. 取消多个活动任务的场景
# 4. 消息分发确保消息被正确处理和发布
# 5. 处理锁确保消息串行化处理
# 6. 子代理按会话取消功能
# 7. 子代理保留推理字段（reasoning_content 和 thinking_blocks）
#
# 使用示例：
# --------
# pytest tests/test_task_cancel.py -v           # 运行所有测试
# pytest tests/test_task_cancel.py::TestHandleStop -v  # 运行特定测试类
# =============================================================================

"""Tests for /stop task cancellation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_loop():
    """创建带有模拟依赖的最小化 AgentLoop 实例。

    Returns:
        tuple: 包含 (AgentLoop 实例，MessageBus 实例)
    """
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    bus = MessageBus()
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    workspace = MagicMock()
    # 模拟工作区的路径除法运算（/ 运算符）
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    # 使用模拟对象替换依赖，避免真实初始化
    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager") as MockSubMgr:
        MockSubMgr.return_value.cancel_by_session = AsyncMock(return_value=0)
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


class TestHandleStop:
    """测试 AgentLoop 的 /stop 命令处理功能。

    这个测试类验证当用户发送 /stop 命令时，系统如何响应：
    - 没有活动任务时的提示
    - 成功取消单个任务
    - 成功取消多个任务
    """
    @pytest.mark.asyncio
    async def test_stop_no_active_task(self):
        """测试没有活动任务时调用 /stop 的情况。

        当用户发送 /stop 命令但没有正在运行的任务时，
        系统应该回复提示消息告知用户没有活动任务。
        """
        from nanobot.bus.events import InboundMessage

        loop, bus = _make_loop()
        # 创建模拟的入站消息（/stop 命令）
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        await loop._handle_stop(msg)
        # 从消息总线获取出站消息并验证内容
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "No active task" in out.content

    @pytest.mark.asyncio
    async def test_stop_cancels_active_task(self):
        """测试 /stop 命令成功取消单个活动任务。

        验证当有任务正在运行时，/stop 命令能够：
        1. 触发任务的 CancelledError 异常
        2. 设置取消标志
        3. 发布确认消息
        """
        from nanobot.bus.events import InboundMessage

        loop, bus = _make_loop()
        cancelled = asyncio.Event()

        # 模拟一个长时间运行的任务
        async def slow_task():
            try:
                await asyncio.sleep(60)  # 模拟长时间任务
            except asyncio.CancelledError:
                cancelled.set()  # 设置取消标志
                raise

        task = asyncio.create_task(slow_task())
        await asyncio.sleep(0)  # 确保任务开始运行
        loop._active_tasks["test:c1"] = [task]

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        await loop._handle_stop(msg)

        # 验证任务被取消
        assert cancelled.is_set()
        # 验证发布了停止确认消息
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "stopped" in out.content.lower()

    @pytest.mark.asyncio
    async def test_stop_cancels_multiple_tasks(self):
        """测试 /stop 命令成功取消多个活动任务。

        验证当同一会话有多个任务在运行时，
        /stop 命令能够取消所有任务并报告取消数量。
        """
        from nanobot.bus.events import InboundMessage

        loop, bus = _make_loop()
        # 为每个任务创建独立的取消事件
        events = [asyncio.Event(), asyncio.Event()]

        async def slow(idx):
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                events[idx].set()  # 设置对应任务的取消标志
                raise

        # 创建两个并行任务
        tasks = [asyncio.create_task(slow(i)) for i in range(2)]
        await asyncio.sleep(0)
        loop._active_tasks["test:c1"] = tasks

        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="/stop")
        await loop._handle_stop(msg)

        # 验证所有任务都被取消
        assert all(e.is_set() for e in events)
        # 验证消息报告了取消的任务数量
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert "2 task" in out.content


class TestDispatch:
    """测试 AgentLoop 的消息分发功能。

    验证消息分发机制确保：
    1. 消息被正确处理和发布到消息总线
    2. 处理锁确保消息串行化处理，避免并发问题
    """
    @pytest.mark.asyncio
    async def test_dispatch_processes_and_publishes(self):
        """测试消息分发正确处理消息并发布到消息总线。

        验证 _dispatch 方法调用 _process_message 处理消息，
        并将处理结果发布到出站消息队列。
        """
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        msg = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="hello")
        # 模拟消息处理返回预设结果
        loop._process_message = AsyncMock(
            return_value=OutboundMessage(channel="test", chat_id="c1", content="hi")
        )
        await loop._dispatch(msg)
        # 验证处理结果被发布到消息总线
        out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
        assert out.content == "hi"

    @pytest.mark.asyncio
    async def test_processing_lock_serializes(self):
        """测试处理锁确保消息串行化处理。

        验证当多个消息同时到达时，处理锁确保它们按顺序处理，
        而不是并发处理，避免状态竞争问题。
        """
        from nanobot.bus.events import InboundMessage, OutboundMessage

        loop, bus = _make_loop()
        order = []  # 记录处理顺序

        async def mock_process(m, **kwargs):
            order.append(f"start-{m.content}")  # 记录开始处理
            await asyncio.sleep(0.05)  # 模拟处理延迟
            order.append(f"end-{m.content}")  # 记录处理结束
            return OutboundMessage(channel="test", chat_id="c1", content=m.content)

        loop._process_message = mock_process
        msg1 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="a")
        msg2 = InboundMessage(channel="test", sender_id="u1", chat_id="c1", content="b")

        # 并发启动两个任务
        t1 = asyncio.create_task(loop._dispatch(msg1))
        t2 = asyncio.create_task(loop._dispatch(msg2))
        await asyncio.gather(t1, t2)
        # 验证处理顺序是串行的：a 开始->a 结束->b 开始->b 结束
        assert order == ["start-a", "end-a", "start-b", "end-b"]


class TestSubagentCancellation:
    """测试子代理管理器的任务取消功能。

    验证 SubagentManager 如何管理子代理任务：
    1. 按会话取消子代理任务
    2. 处理没有任务的情况
    3. 保留推理字段（reasoning_content 和 thinking_blocks）
    """
    @pytest.mark.asyncio
    async def test_cancel_by_session(self):
        """测试按会话取消子代理任务。

        验证 cancel_by_session 方法能够：
        1. 找到指定会话的所有子代理任务
        2. 取消这些任务
        3. 返回取消的任务数量
        """
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)

        cancelled = asyncio.Event()

        # 模拟长时间运行的子代理任务
        async def slow():
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        task = asyncio.create_task(slow())
        await asyncio.sleep(0)
        mgr._running_tasks["sub-1"] = task  # 注册任务
        mgr._session_tasks["test:c1"] = {"sub-1"}  # 关联会话

        count = await mgr.cancel_by_session("test:c1")
        assert count == 1  # 验证取消了 1 个任务
        assert cancelled.is_set()  # 验证任务被取消

    @pytest.mark.asyncio
    async def test_cancel_by_session_no_tasks(self):
        """测试按会话取消时没有任务的情况。

        验证当指定会话没有关联任务时，
        cancel_by_session 方法返回 0 而不抛出异常。
        """
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        mgr = SubagentManager(provider=provider, workspace=MagicMock(), bus=bus)
        # 验证不存在的会话返回 0
        assert await mgr.cancel_by_session("nonexistent") == 0

    @pytest.mark.asyncio
    async def test_subagent_preserves_reasoning_fields_in_tool_turn(self, monkeypatch, tmp_path):
        """测试子代理在工具调用时保留推理字段。

        验证当子代理调用工具并继续对话时，
        推理字段（reasoning_content 和 thinking_blocks）被正确传递到下一次调用。
        这对于保持模型的推理链一致性很重要。
        """
        from nanobot.agent.subagent import SubagentManager
        from nanobot.bus.queue import MessageBus
        from nanobot.providers.base import LLMResponse, ToolCallRequest

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"

        captured_second_call: list[dict] = []  # 捕获第二次调用的消息

        call_count = {"n": 0}  # 计数器，跟踪调用次数

        # 模拟分阶段的聊天响应
        async def scripted_chat_with_retry(*, messages, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # 第一次调用：返回带工具调用和推理字段的响应
                return LLMResponse(
                    content="thinking",
                    tool_calls=[ToolCallRequest(id="call_1", name="list_dir", arguments={})],
                    reasoning_content="hidden reasoning",  # 隐藏推理内容
                    thinking_blocks=[{"type": "thinking", "thinking": "step"}],  # 思考块
                )
            # 第二次调用：捕获传入的消息用于验证
            captured_second_call[:] = messages
            return LLMResponse(content="done", tool_calls=[])
        provider.chat_with_retry = scripted_chat_with_retry
        mgr = SubagentManager(provider=provider, workspace=tmp_path, bus=bus)

        # 模拟工具执行
        async def fake_execute(self, name, arguments):
            return "tool result"

        monkeypatch.setattr("nanobot.agent.tools.registry.ToolRegistry.execute", fake_execute)

        # 运行子代理
        await mgr._run_subagent("sub-1", "do task", "label", {"channel": "test", "chat_id": "c1"})

        # 过滤出包含工具调用的助手消息
        assistant_messages = [
            msg for msg in captured_second_call
            if msg.get("role") == "assistant" and msg.get("tool_calls")
        ]
        assert len(assistant_messages) == 1
        # 验证推理字段被保留并传递到下一次调用
        assert assistant_messages[0]["reasoning_content"] == "hidden reasoning"
        assert assistant_messages[0]["thinking_blocks"] == [{"type": "thinking", "thinking": "step"}]

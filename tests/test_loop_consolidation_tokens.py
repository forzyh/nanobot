# =============================================================================
# nanobot Loop 巩固 Token 测试
# 文件路径：tests/test_loop_consolidation_tokens.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 AgentLoop 中内存巩固（consolidation）功能的测试，
# 主要验证基于 token 数量的内存巩固逻辑是否正确工作。
#
# 内存巩固是什么？
# -------------
# 当 Agent 与用户的对话越来越长时，token 数量会逐渐接近模型的上下文窗口限制。
# 为了避免超出限制，系统需要将早期的对话内容进行"巩固"（consolidation）：
# - 将早期对话归档到长期记忆
# - 保留最近的对话在短期记忆
# - 确保总 token 数量在安全范围内
#
# 测试的核心功能：
# -------------
# 1. test_prompt_below_threshold_does_not_consolidate:
#    - 验证当 token 数量低于阈值时，不触发巩固
#
# 2. test_prompt_above_threshold_triggers_consolidation:
#    - 验证当 token 数量超过阈值时，触发巩固
#
# 3. test_prompt_above_threshold_archives_until_next_user_boundary:
#    - 验证巩固会归档到下一个用户消息边界
#    - 确保对话的完整性（不截断在用户消息中间）
#
# 4. test_consolidation_loops_until_target_met:
#    - 验证巩固会循环执行直到达到目标 token 数量
#
# 5. test_consolidation_continues_below_trigger_until_half_target:
#    - 验证一旦触发巩固，会继续执行直到低于一半阈值
#    - 防止频繁触发巩固
#
# 6. test_preflight_consolidation_before_llm_call:
#    - 验证在 LLM 调用之前执行巩固
#    - 确保发送给 LLM 的 prompt 不超过上下文窗口
#
# 关键测试场景：
# ------------
# 1. 阈值以下场景：不触发巩固，节省资源
# 2. 阈值以上场景：触发巩固，释放 token 空间
# 3. 边界处理：在用户消息边界处截断，保持对话完整性
# 4. 循环巩固：一次巩固不够时，继续执行直到达标
# 5. 滞后效应：巩固到一半阈值，防止频繁触发
# 6. 时机验证：在 LLM 调用前巩固，确保 prompt 不超限
#
# 关键参数：
# ---------
# - context_window_tokens: 上下文窗口大小（如 200 tokens）
# - 触发阈值：通常是 context_window_tokens 的一定比例
# - 目标阈值：通常是 context_window_tokens 的一半
#
# 使用示例：
# --------
# 运行所有测试：pytest tests/test_loop_consolidation_tokens.py -v
# 运行单个测试：pytest tests/test_loop_consolidation_tokens.py::test_prompt_below_threshold_does_not_consolidate -v
# =============================================================================

import pytest

from nanobot.agent.loop import AgentLoop
import nanobot.agent.memory as memory_module
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMResponse


def _make_loop(tmp_path, *, estimated_tokens: int, context_window_tokens: int) -> AgentLoop:
    """
    创建用于测试的 AgentLoop 实例的辅助函数

    这个函数创建一个模拟的 AgentLoop 实例，用于测试内存巩固功能。
    它使用 Mock 对象来模拟依赖项，避免真实的 LLM 调用和文件 I/O。

    Args:
        tmp_path: pytest 提供的临时目录路径，用于工作空间
        estimated_tokens: 模拟的当前 token 数量估计值
        context_window_tokens: 上下文窗口大小（tokens）

    Returns:
        AgentLoop: 配置好的测试用 AgentLoop 实例

    模拟的组件：
    -----------
    - provider: 使用 MagicMock 模拟
      - get_default_model() 返回 "test-model"
      - estimate_prompt_tokens() 返回指定的 estimated_tokens
      - chat_with_retry() 是异步 Mock，返回简单的 LLMResponse
    - tools: 返回空列表（测试不需要真实工具）
    - bus: 使用 MessageBus 进行消息队列管理
    """
    # 创建模拟的 provider
    provider = MagicMock()
    provider.get_default_model.return_value = "test-model"
    # 配置 token 估计器返回指定的值
    provider.estimate_prompt_tokens.return_value = (estimated_tokens, "test-counter")
    # 配置 LLM 调用返回简单的响应
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))

    # 创建 AgentLoop 实例
    loop = AgentLoop(
        bus=MessageBus(),
        provider=provider,
        workspace=tmp_path,
        model="test-model",
        context_window_tokens=context_window_tokens,
    )
    # 配置 tools 返回空列表（测试不需要真实工具）
    loop.tools.get_definitions = MagicMock(return_value=[])
    return loop


@pytest.mark.asyncio
async def test_prompt_below_threshold_does_not_consolidate(tmp_path) -> None:
    """
    测试当 token 数量低于阈值时不触发巩固

    这个测试验证当当前 token 数量低于触发阈值时，
    系统不会执行内存巩固操作，避免不必要的资源消耗。

    测试步骤：
    ---------
    1. 创建 AgentLoop 实例，配置：
       - estimated_tokens=100（当前 token 数）
       - context_window_tokens=200（上下文窗口大小）
       - 触发阈值通常是 80%，即 160 tokens
    2. Mock consolidate_messages 方法
    3. 调用 process_direct 处理用户消息
    4. 验证 consolidate_messages 未被调用

    为什么重要：
    -----------
    - 避免在不需要时执行巩固操作，节省计算资源
    - 确保系统只在真正需要时才进行内存管理
    """
    # 创建 AgentLoop 实例
    # estimated_tokens=100 < context_window_tokens=200 的阈值（约 160）
    loop = _make_loop(tmp_path, estimated_tokens=100, context_window_tokens=200)
    # Mock consolidate_messages 方法
    loop.memory_consolidator.consolidate_messages = AsyncMock(return_value=True)  # type: ignore[method-assign]

    # 处理用户消息
    await loop.process_direct("hello", session_key="cli:test")

    # 验证 consolidate_messages 未被调用
    # 因为 token 数量低于阈值，不需要巩固
    loop.memory_consolidator.consolidate_messages.assert_not_awaited()


@pytest.mark.asyncio
async def test_prompt_above_threshold_triggers_consolidation(tmp_path, monkeypatch) -> None:
    """
    测试当 token 数量超过阈值时触发巩固

    这个测试验证当当前 token 数量超过触发阈值时，
    系统会执行内存巩固操作。

    测试步骤：
    ---------
    1. 创建 AgentLoop 实例，配置：
       - estimated_tokens=1000（当前 token 数）
       - context_window_tokens=200（上下文窗口大小）
       - 1000 > 200，远超阈值
    2. 准备 session 消息（3 条消息）
    3. Mock estimate_message_tokens 返回 500 tokens/消息
    4. 调用 process_direct 处理用户消息
    5. 验证 consolidate_messages 被调用

    为什么重要：
    -----------
    - 确保系统在需要时能够正确触发巩固
    - 防止超出上下文窗口限制
    """
    # 创建 AgentLoop 实例
    # estimated_tokens=1000 >> context_window_tokens=200，远超阈值
    loop = _make_loop(tmp_path, estimated_tokens=1000, context_window_tokens=200)
    # Mock consolidate_messages 方法
    loop.memory_consolidator.consolidate_messages = AsyncMock(return_value=True)  # type: ignore[method-assign]

    # 获取或创建 session
    session = loop.sessions.get_or_create("cli:test")
    # 准备 3 条历史消息
    session.messages = [
        {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
    ]
    loop.sessions.save(session)
    # Mock 每条消息估计为 500 tokens
    monkeypatch.setattr(memory_module, "estimate_message_tokens", lambda _message: 500)

    # 处理用户消息
    await loop.process_direct("hello", session_key="cli:test")

    # 验证 consolidate_messages 被调用至少一次
    assert loop.memory_consolidator.consolidate_messages.await_count >= 1


@pytest.mark.asyncio
async def test_prompt_above_threshold_archives_until_next_user_boundary(tmp_path, monkeypatch) -> None:
    """
    测试巩固会归档到下一个用户消息边界

    这个测试验证当执行巩固时，系统会在用户消息边界处截断，
    而不是在对话中间截断，保持对话的完整性。

    测试步骤：
    ---------
    1. 创建 AgentLoop 实例，配置 5 条消息：
       - u1, a1, u2, a2, u3（user-assistant 交替）
    2. 每条消息 120 tokens
    3. 调用 maybe_consolidate_by_tokens
    4. 验证归档的消息是 ["u1", "a1", "u2", "a2"]
       - 在 u3（用户消息）之前截断
    5. 验证 last_consolidated = 4（归档了 4 条消息）

    为什么重要：
    -----------
    - 保持对话的完整性，不截断在用户消息中间
    - 确保归档后的对话仍然有意义
    - 用户消息是对话的自然边界点
    """
    # 创建 AgentLoop 实例
    loop = _make_loop(tmp_path, estimated_tokens=1000, context_window_tokens=200)
    # Mock consolidate_messages 方法
    loop.memory_consolidator.consolidate_messages = AsyncMock(return_value=True)  # type: ignore[method-assign]

    # 创建 session 并设置 5 条消息
    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
        {"role": "assistant", "content": "a2", "timestamp": "2026-01-01T00:00:03"},
        {"role": "user", "content": "u3", "timestamp": "2026-01-01T00:00:04"},
    ]
    loop.sessions.save(session)

    # 配置每条消息 120 tokens
    token_map = {"u1": 120, "a1": 120, "u2": 120, "a2": 120, "u3": 120}
    monkeypatch.setattr(memory_module, "estimate_message_tokens", lambda message: token_map[message["content"]])

    # 执行巩固
    await loop.memory_consolidator.maybe_consolidate_by_tokens(session)

    # 获取传递给 consolidate_messages 的消息块
    archived_chunk = loop.memory_consolidator.consolidate_messages.await_args.args[0]
    # 验证归档的是前 4 条消息（在 u3 之前截断）
    assert [message["content"] for message in archived_chunk] == ["u1", "a1", "u2", "a2"]
    # 验证 last_consolidated 指向第 4 条消息之后
    assert session.last_consolidated == 4


@pytest.mark.asyncio
async def test_consolidation_loops_until_target_met(tmp_path, monkeypatch) -> None:
    """
    验证 maybe_consolidate_by_tokens 会循环执行直到达到目标

    这个测试验证当一次巩固不足以将 token 数量降到目标以下时，
    系统会循环执行巩固，直到达到目标。

    测试步骤：
    ---------
    1. 创建 AgentLoop 实例，配置 7 条消息
    2. 配置 estimate_session_prompt_tokens 模拟 token 变化：
       - 第 1 次调用：500 tokens（超过阈值 200）
       - 第 2 次调用：300 tokens（仍超过阈值）
       - 第 3 次调用：80 tokens（低于阈值，停止）
    3. 调用 maybe_consolidate_by_tokens
    4. 验证 consolidate_messages 被调用 2 次
    5. 验证 last_consolidated = 6（归档了 6 条消息）

    为什么重要：
    -----------
    - 确保系统能够处理需要多次巩固的情况
    - 防止一次巩固后仍然超出阈值
    - 保证最终 token 数量在安全范围内
    """
    # 创建 AgentLoop 实例
    loop = _make_loop(tmp_path, estimated_tokens=0, context_window_tokens=200)
    # Mock consolidate_messages 方法
    loop.memory_consolidator.consolidate_messages = AsyncMock(return_value=True)  # type: ignore[method-assign]

    # 创建 session 并设置 7 条消息
    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
        {"role": "assistant", "content": "a2", "timestamp": "2026-01-01T00:00:03"},
        {"role": "user", "content": "u3", "timestamp": "2026-01-01T00:00:04"},
        {"role": "assistant", "content": "a3", "timestamp": "2026-01-01T00:00:05"},
        {"role": "user", "content": "u4", "timestamp": "2026-01-01T00:00:06"},
    ]
    loop.sessions.save(session)

    # 跟踪调用次数
    call_count = [0]
    # 模拟 token 估计器
    def mock_estimate(_session):
        call_count[0] += 1
        if call_count[0] == 1:
            return (500, "test")  # 第 1 次：500 tokens
        if call_count[0] == 2:
            return (300, "test")  # 第 2 次：300 tokens
        return (80, "test")  # 第 3 次：80 tokens（低于阈值）

    loop.memory_consolidator.estimate_session_prompt_tokens = mock_estimate  # type: ignore[method-assign]
    # Mock 每条消息 100 tokens
    monkeypatch.setattr(memory_module, "estimate_message_tokens", lambda _m: 100)

    # 执行巩固
    await loop.memory_consolidator.maybe_consolidate_by_tokens(session)

    # 验证 consolidate_messages 被调用 2 次
    assert loop.memory_consolidator.consolidate_messages.await_count == 2
    # 验证 last_consolidated = 6
    assert session.last_consolidated == 6


@pytest.mark.asyncio
async def test_consolidation_continues_below_trigger_until_half_target(tmp_path, monkeypatch) -> None:
    """
    验证一旦触发巩固，会继续执行直到低于一半阈值

    这个测试验证系统的"滞后效应"（hysteresis）设计：
    - 触发阈值：context_window_tokens（如 200）
    - 目标阈值：context_window_tokens / 2（如 100）

    设计目的：
    - 防止在阈值附近频繁触发巩固
    - 巩固一次后，确保有足够的余量

    测试步骤：
    ---------
    1. 创建 AgentLoop 实例，配置 7 条消息
    2. 配置 estimate_session_prompt_tokens 模拟 token 变化：
       - 第 1 次调用：500 tokens（超过阈值 200，触发巩固）
       - 第 2 次调用：150 tokens（低于阈值但高于半阈值 100，继续巩固）
       - 第 3 次调用：80 tokens（低于半阈值 100，停止）
    3. 调用 maybe_consolidate_by_tokens
    4. 验证 consolidate_messages 被调用 2 次
    5. 验证 last_consolidated = 6

    为什么重要：
    -----------
    - 防止频繁触发巩固，影响性能
    - 确保巩固后有足够的余量容纳新消息
    - 实现"滞后效应"，提高系统稳定性
    """
    # 创建 AgentLoop 实例
    loop = _make_loop(tmp_path, estimated_tokens=0, context_window_tokens=200)
    # Mock consolidate_messages 方法
    loop.memory_consolidator.consolidate_messages = AsyncMock(return_value=True)  # type: ignore[method-assign]

    # 创建 session 并设置 7 条消息
    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
        {"role": "assistant", "content": "a2", "timestamp": "2026-01-01T00:00:03"},
        {"role": "user", "content": "u3", "timestamp": "2026-01-01T00:00:04"},
        {"role": "assistant", "content": "a3", "timestamp": "2026-01-01T00:00:05"},
        {"role": "user", "content": "u4", "timestamp": "2026-01-01T00:00:06"},
    ]
    loop.sessions.save(session)

    # 跟踪调用次数
    call_count = [0]

    # 模拟 token 估计器
    def mock_estimate(_session):
        call_count[0] += 1
        if call_count[0] == 1:
            return (500, "test")  # 第 1 次：500 tokens（超过阈值 200）
        if call_count[0] == 2:
            return (150, "test")  # 第 2 次：150 tokens（低于阈值但高于半阈值 100）
        return (80, "test")  # 第 3 次：80 tokens（低于半阈值 100）

    loop.memory_consolidator.estimate_session_prompt_tokens = mock_estimate  # type: ignore[method-assign]
    # Mock 每条消息 100 tokens
    monkeypatch.setattr(memory_module, "estimate_message_tokens", lambda _m: 100)

    # 执行巩固
    await loop.memory_consolidator.maybe_consolidate_by_tokens(session)

    # 验证 consolidate_messages 被调用 2 次
    assert loop.memory_consolidator.consolidate_messages.await_count == 2
    # 验证 last_consolidated = 6
    assert session.last_consolidated == 6


@pytest.mark.asyncio
async def test_preflight_consolidation_before_llm_call(tmp_path, monkeypatch) -> None:
    """
    验证在 LLM 调用之前执行巩固

    这个测试验证 process_direct 方法的执行顺序：
    1. 先执行内存巩固
    2. 再调用 LLM

    这确保发送给 LLM 的 prompt 不会超出上下文窗口限制。

    测试步骤：
    ---------
    1. 创建 AgentLoop 实例
    2. 配置 session 有 3 条消息，每条 500 tokens
    3. 配置 estimate_session_prompt_tokens：
       - 第 1 次调用：1000 tokens（超过阈值）
       - 第 2 次调用：80 tokens（巩固后低于阈值）
    4. 调用 process_direct
    5. 验证执行顺序：先"consolidate"后"llm"

    为什么重要：
    -----------
    - 确保 LLM 调用前 prompt 不超过上下文窗口
    - 防止因 prompt 过长导致的 LLM 调用失败
    - 保证系统稳定性
    """
    # 跟踪执行顺序
    order: list[str] = []

    # 创建 AgentLoop 实例
    loop = _make_loop(tmp_path, estimated_tokens=0, context_window_tokens=200)

    # 定义巩固跟踪函数
    async def track_consolidate(messages):
        order.append("consolidate")
        return True
    loop.memory_consolidator.consolidate_messages = track_consolidate  # type: ignore[method-assign]

    # 定义 LLM 调用跟踪函数
    async def track_llm(*args, **kwargs):
        order.append("llm")
        return LLMResponse(content="ok", tool_calls=[])
    loop.provider.chat_with_retry = track_llm

    # 创建 session 并设置 3 条消息
    session = loop.sessions.get_or_create("cli:test")
    session.messages = [
        {"role": "user", "content": "u1", "timestamp": "2026-01-01T00:00:00"},
        {"role": "assistant", "content": "a1", "timestamp": "2026-01-01T00:00:01"},
        {"role": "user", "content": "u2", "timestamp": "2026-01-01T00:00:02"},
    ]
    loop.sessions.save(session)
    # Mock 每条消息 500 tokens
    monkeypatch.setattr(memory_module, "estimate_message_tokens", lambda _m: 500)

    # 配置 token 估计器
    call_count = [0]
    def mock_estimate(_session):
        call_count[0] += 1
        return (1000 if call_count[0] <= 1 else 80, "test")
    loop.memory_consolidator.estimate_session_prompt_tokens = mock_estimate  # type: ignore[method-assign]

    # 处理用户消息
    await loop.process_direct("hello", session_key="cli:test")

    # 验证执行顺序
    assert "consolidate" in order
    assert "llm" in order
    # 验证先巩固后调用 LLM
    assert order.index("consolidate") < order.index("llm")

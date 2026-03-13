# =============================================================================
# nanobot 心跳服务测试
# 文件路径：tests/test_heartbeat_service.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 HeartbeatService 心跳服务的测试。
# 心跳服务定期触发 LLM 决策，根据决策结果执行相应任务。
#
# 什么是 HeartbeatService？
# ---------------
# HeartbeatService 是 nanobot 的定时心跳服务，主要功能：
# 1. 按指定间隔定期触发（如每小时一次）
# 2. 读取 HEARTBEAT.md 文件中的待办任务
# 3. 调用 LLM 决定是否需要执行任务
# 4. 根据 LLM 决策执行相应操作（run/skip）
# 5. 支持重试机制处理瞬时错误
#
# 核心概念：
# - start(): 启动心跳服务（幂等操作）
# - trigger_now(): 立即触发一次心跳
# - _decide(): 调用 LLM 决定是否执行任务
# - on_execute: 任务执行回调函数
#
# 测试场景：
# --------
# 1. start 幂等性：多次调用 start 不会创建多个任务
# 2. 无工具调用时返回 skip：LLM 没有调用工具时跳过
# 3. 决策为 run 时执行任务：LLM 决定执行时调用回调
# 4. 决策为 skip 时返回 None：LLM 决定跳过时不执行
# 5. _decide 重试瞬时错误：决策时遇到瞬时错误会重试
#
# 使用示例：
# --------
# pytest tests/test_heartbeat_service.py -v  # 运行所有测试
# =============================================================================

import asyncio

import pytest

from nanobot.heartbeat.service import HeartbeatService
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class DummyProvider(LLMProvider):
    """虚拟测试 Provider。

    这个类用于模拟 LLM Provider 的行为，可以预设一系列响应，
    每次调用 chat 方法时按顺序返回预设的响应。

    属性：
        calls (int): 记录 chat 方法被调用的次数
    """

    def __init__(self, responses: list[LLMResponse]):
        """初始化虚拟 Provider。

        Args:
            responses: 预设的 LLMResponse 响应列表
        """
        super().__init__()
        self._responses = list(responses)
        self.calls = 0

    async def chat(self, *args, **kwargs) -> LLMResponse:
        """模拟聊天请求。

        每次调用时：
        1. 增加调用计数
        2. 返回下一个预设响应（如果没有则返回空响应）
        """
        self.calls += 1
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])

    def get_default_model(self) -> str:
        """返回默认模型名称。"""
        return "test-model"


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    """测试 start 方法的幂等性。

    场景说明：
        HeartbeatService.start() 方法应该是幂等的，
        即多次调用 start() 不会创建多个后台任务，
        只有第一次调用会创建任务，后续调用直接返回。

    验证点：
        1. 第二次调用 start() 后，_task 属性不变
        2. 服务可以正常停止
    """
    # 创建空的 DummyProvider（这个测试不需要 LLM 响应）
    provider = DummyProvider([])

    # 创建心跳服务实例
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        interval_s=9999,  # 设置很长的间隔，避免自动触发
        enabled=True,
    )

    # 第一次启动服务
    await service.start()
    # 保存第一次创建的任务引用
    first_task = service._task
    # 第二次启动服务（应该不创建新任务）
    await service.start()

    # 验证任务引用相同，证明是幂等的
    assert service._task is first_task

    # 清理：停止服务
    service.stop()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_decide_returns_skip_when_no_tool_call(tmp_path) -> None:
    """测试无工具调用时返回 skip。

    场景说明：
        当 LLM 响应中没有工具调用（tool_calls 为空）时，
        _decide 方法应该返回 "skip" 动作，表示不需要执行任务。

    验证点：
        1. 返回的动作是 "skip"
        2. 返回的任务字符串为空
    """
    # 创建返回空工具调用的 Provider
    provider = DummyProvider([LLMResponse(content="no tool call", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    # 调用 _decide 方法进行决策
    action, tasks = await service._decide("heartbeat content")
    # 验证返回 skip
    assert action == "skip"
    assert tasks == ""


@pytest.mark.asyncio
async def test_trigger_now_executes_when_decision_is_run(tmp_path) -> None:
    """测试决策为 run 时执行任务。

    场景说明：
        当 LLM 决定执行任务（返回 heartbeat 工具调用，action="run"）时，
        trigger_now() 方法应该调用 on_execute 回调函数执行任务。

    测试流程：
        1. 创建 HEARTBEAT.md 文件，包含待办任务
        2. 配置 Provider 返回 run 决策
        3. 调用 trigger_now()
        4. 验证 on_execute 被正确调用

    验证点：
        1. trigger_now() 返回 on_execute 的返回值 "done"
        2. on_execute 被调用，参数是 LLM 返回的 tasks 内容
    """
    # 创建 HEARTBEAT.md 文件，包含一个待办任务
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    # 配置 Provider 返回 run 决策
    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        )
    ])

    # 记录 on_execute 调用参数的列表
    called_with: list[str] = []

    # 定义 on_execute 回调函数
    async def _on_execute(tasks: str) -> str:
        called_with.append(tasks)
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    # 触发心跳
    result = await service.trigger_now()
    # 验证返回结果
    assert result == "done"
    # 验证 on_execute 被正确调用
    assert called_with == ["check open tasks"]


@pytest.mark.asyncio
async def test_trigger_now_returns_none_when_decision_is_skip(tmp_path) -> None:
    """测试决策为 skip 时返回 None。

    场景说明：
        当 LLM 决定跳过任务（返回 heartbeat 工具调用，action="skip"）时，
        trigger_now() 方法应该返回 None，表示没有执行任何操作。

    验证点：
        1. trigger_now() 返回 None
    """
    # 创建 HEARTBEAT.md 文件
    (tmp_path / "HEARTBEAT.md").write_text("- [ ] do thing", encoding="utf-8")

    # 配置 Provider 返回 skip 决策
    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "skip"},
                )
            ],
        )
    ])

    async def _on_execute(tasks: str) -> str:
        return tasks

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    # 验证返回 None
    assert await service.trigger_now() is None


@pytest.mark.asyncio
async def test_decide_retries_transient_error_then_succeeds(tmp_path, monkeypatch) -> None:
    """测试 _decide 重试瞬时错误后成功。

    场景说明：
        当 _decide 方法调用 LLM 时遇到瞬时错误（如 429 限流），
        应该自动重试，重试成功后返回正确结果。

    测试流程：
        1. 配置 Provider 先返回 429 错误，再返回成功的工具调用
        2. 使用假的 sleep 函数记录延迟时间
        3. 调用 _decide 方法
        4. 验证重试行为和最终结果

    验证点：
        1. 最终返回的动作是 "run"
        2. 最终返回的任务内容是 "check open tasks"
        3. Provider 被调用了 2 次（第一次失败 + 第二次成功）
        4. 延迟列表为 [1]，表示重试前等待了 1 秒
    """
    # 配置 Provider：先返回 429 错误，再返回成功的工具调用
    provider = DummyProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        ),
    ])

    delays: list[int] = []

    # 创建假的 sleep 函数记录延迟
    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    action, tasks = await service._decide("heartbeat content")

    # 验证最终结果
    assert action == "run"
    assert tasks == "check open tasks"
    # 验证重试了 2 次
    assert provider.calls == 2
    # 验证延迟时间为 [1] 秒
    assert delays == [1]

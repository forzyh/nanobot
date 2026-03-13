# =============================================================================
# nanobot 记忆巩固类型处理测试
# 文件路径：tests/test_memory_consolidation_types.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 MemoryStore.consolidate() 方法的类型处理测试。
# 这是一个回归测试，修复 issue #1042 中报告的问题。
#
# 什么是记忆巩固（Memory Consolidation）？
# ---------------
# 记忆巩固是 nanobot 将对话历史摘要并保存到长期记忆的过程：
# 1. 当对话消息达到一定数量时触发
# 2. 调用 LLM 分析消息，生成历史摘要和记忆更新
# 3. 使用 save_memory 工具保存结果到文件
#
# 问题背景（Issue #1042）：
# ---------------
# 某些 LLM Provider 返回的工具调用参数可能不是字符串，而是：
# - 字典（dict）
# - JSON 字符串
# - 列表（list）
# 原来的代码假设参数总是字符串，导致 TypeError 异常。
#
# 测试场景：
# --------
# 1. 字符串参数正常工作：LLM 返回字符串参数的正常情况
# 2. 字典参数序列化为 JSON：LLM 返回 dict 时自动序列化为 JSON
# 3. 字符串参数作为原始 JSON：某些 Provider 返回 JSON 字符串
# 4. 无工具调用返回 False：LLM 没有使用 save_memory 工具
# 5. 消息块为空时跳过：没有消息时不执行巩固
# 6. 列表参数提取第一个字典：Provider 返回 list 时提取第一个元素
# 7. 列表为空返回 False：空列表参数无法处理
# 8. 列表包含非字典返回 False：列表元素不是字典时无法处理
# 9. 重试瞬时错误后成功：LLLM API 瞬时错误时自动重试
# 10. 巩固使用 Provider 默认配置：不再传递 generation 参数
#
# 使用示例：
# --------
# pytest tests/test_memory_consolidation_types.py -v  # 运行所有测试
# =============================================================================

"""Test MemoryStore.consolidate() handles non-string tool call arguments.

Regression test for https://github.com/HKUDS/nanobot/issues/1042
When memory consolidation receives dict values instead of strings from the LLM
tool call response, it should serialize them to JSON instead of raising TypeError.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.memory import MemoryStore
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


def _make_messages(message_count: int = 30):
    """创建模拟消息列表。

    Args:
        message_count: 消息数量，默认 30 条

    Returns:
        包含指定数量消息的列表，每条消息包含 role、content 和 timestamp
    """
    return [
        {"role": "user", "content": f"msg{i}", "timestamp": "2026-01-01 00:00"}
        for i in range(message_count)
    ]


def _make_tool_response(history_entry, memory_update):
    """创建包含 save_memory 工具调用的 LLMResponse。

    Args:
        history_entry: 历史摘要内容
        memory_update: 记忆更新内容

    Returns:
        包含 save_memory 工具调用的 LLMResponse 对象
    """
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallRequest(
                id="call_1",
                name="save_memory",
                arguments={
                    "history_entry": history_entry,
                    "memory_update": memory_update,
                },
            )
        ],
    )


class ScriptedProvider(LLMProvider):
    """脚本化的测试 Provider。

    这个类用于模拟 LLM Provider 的行为，可以预设一系列响应，
    每次调用 chat 方法时按顺序返回预设的响应。

    属性：
        calls (int): 记录 chat 方法被调用的次数
    """

    def __init__(self, responses: list[LLMResponse]):
        """初始化脚本化 Provider。

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


class TestMemoryConsolidationTypeHandling:
    """测试记忆巩固处理各种参数类型的正确性。

    这个测试类验证 MemoryStore.consolidate() 方法能够正确处理
    LLM 返回的不同类型的工具调用参数。
    """

    @pytest.mark.asyncio
    async def test_string_arguments_work(self, tmp_path: Path) -> None:
        """正常情况：LLM 返回字符串参数。

        场景说明：
            这是最常见的情况，LLM 返回的工具调用参数是字符串类型。
            consolidate 方法应该正常处理并保存到文件。

        验证点：
            1. consolidate 返回 True 表示成功
            2. history 文件被创建
            3. history 文件包含正确的历史摘要
            4. memory 文件包含正确的记忆更新
        """
        # 创建 MemoryStore 实例
        store = MemoryStore(tmp_path)
        # 创建模拟的 Provider，返回字符串参数
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=_make_tool_response(
                history_entry="[2026-01-01] User discussed testing.",
                memory_update="# Memory\nUser likes testing.",
            )
        )
        provider.chat_with_retry = provider.chat
        # 创建 60 条消息
        messages = _make_messages(message_count=60)

        # 执行记忆巩固
        result = await store.consolidate(messages, provider, "test-model")

        # 验证结果
        assert result is True
        assert store.history_file.exists()
        assert "[2026-01-01] User discussed testing." in store.history_file.read_text()
        assert "User likes testing." in store.memory_file.read_text()

    @pytest.mark.asyncio
    async def test_dict_arguments_serialized_to_json(self, tmp_path: Path) -> None:
        """Issue #1042: LLM 返回字典而不是字符串 —— 不应抛出 TypeError。

        场景说明：
            某些 LLM Provider 可能返回字典类型的参数，而不是字符串。
            consolidate 方法应该自动将字典序列化为 JSON 格式保存。

        验证点：
            1. consolidate 返回 True 表示成功
            2. history 文件被创建
            3. history 文件内容是有效的 JSON，包含正确的 summary 字段
            4. memory 文件内容是有效的 JSON，包含正确的 facts 字段
        """
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        # Provider 返回字典类型的参数
        provider.chat = AsyncMock(
            return_value=_make_tool_response(
                history_entry={"timestamp": "2026-01-01", "summary": "User discussed testing."},
                memory_update={"facts": ["User likes testing"], "topics": ["testing"]},
            )
        )
        provider.chat_with_retry = provider.chat
        messages = _make_messages(message_count=60)

        result = await store.consolidate(messages, provider, "test-model")

        # 验证结果
        assert result is True
        assert store.history_file.exists()
        # 验证 history 文件是 JSON 格式
        history_content = store.history_file.read_text()
        parsed = json.loads(history_content.strip())
        assert parsed["summary"] == "User discussed testing."

        # 验证 memory 文件是 JSON 格式
        memory_content = store.memory_file.read_text()
        parsed_mem = json.loads(memory_content)
        assert "User likes testing" in parsed_mem["facts"]

    @pytest.mark.asyncio
    async def test_string_arguments_as_raw_json(self, tmp_path: Path) -> None:
        """某些 Provider 返回 JSON 字符串而不是解析后的字典。

        场景说明：
            某些 Provider 可能将参数作为 JSON 字符串返回（未被解析成字典）。
            consolidate 方法应该先解析 JSON 字符串，然后再处理。

        验证点：
            1. consolidate 返回 True 表示成功
            2. history 文件包含正确的内容
        """
        store = MemoryStore(tmp_path)
        provider = AsyncMock()

        # 模拟参数是 JSON 字符串（还未解析）
        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="save_memory",
                    arguments=json.dumps({
                        "history_entry": "[2026-01-01] User discussed testing.",
                        "memory_update": "# Memory\nUser likes testing.",
                    }),
                )
            ],
        )
        provider.chat = AsyncMock(return_value=response)
        provider.chat_with_retry = provider.chat
        messages = _make_messages(message_count=60)

        result = await store.consolidate(messages, provider, "test-model")

        # 验证结果
        assert result is True
        assert "User discussed testing." in store.history_file.read_text()

    @pytest.mark.asyncio
    async def test_no_tool_call_returns_false(self, tmp_path: Path) -> None:
        """当 LLM 没有使用 save_memory 工具时，返回 False。

        场景说明：
            如果 LLM 没有调用 save_memory 工具（可能是它认为不需要保存记忆），
            consolidate 方法应该返回 False，表示没有执行任何操作。

        验证点：
            1. consolidate 返回 False
            2. history 文件没有被创建
        """
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        # Provider 返回没有工具调用的响应
        provider.chat = AsyncMock(
            return_value=LLMResponse(content="I summarized the conversation.", tool_calls=[])
        )
        provider.chat_with_retry = provider.chat
        messages = _make_messages(message_count=60)

        result = await store.consolidate(messages, provider, "test-model")

        # 验证结果
        assert result is False
        assert not store.history_file.exists()

    @pytest.mark.asyncio
    async def test_skips_when_message_chunk_is_empty(self, tmp_path: Path) -> None:
        """当消息块为空时，巩固操作不执行任何操作。

        场景说明：
            如果没有消息需要处理（空列表），
            consolidate 方法应该直接返回 True，不调用 LLM。

        验证点：
            1. consolidate 返回 True
            2. Provider 的 chat 方法没有被调用
        """
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat_with_retry = provider.chat
        # 空消息列表
        messages: list[dict] = []

        result = await store.consolidate(messages, provider, "test-model")

        # 验证结果
        assert result is True
        # 验证没有调用 LLM
        provider.chat.assert_not_called()

    @pytest.mark.asyncio
    async def test_list_arguments_extracts_first_dict(self, tmp_path: Path) -> None:
        """某些 Provider 返回列表参数 —— 如果是字典则提取第一个元素。

        场景说明：
            某些 Provider 可能将参数包装在列表中返回。
            consolidate 方法应该提取列表中的第一个字典元素进行处理。

        验证点：
            1. consolidate 返回 True 表示成功
            2. history 文件包含正确的内容
            3. memory 文件包含正确的内容
        """
        store = MemoryStore(tmp_path)
        provider = AsyncMock()

        # 模拟参数是一个包含字典的列表
        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="save_memory",
                    arguments=[{
                        "history_entry": "[2026-01-01] User discussed testing.",
                        "memory_update": "# Memory\nUser likes testing.",
                    }],
                )
            ],
        )
        provider.chat = AsyncMock(return_value=response)
        provider.chat_with_retry = provider.chat
        messages = _make_messages(message_count=60)

        result = await store.consolidate(messages, provider, "test-model")

        # 验证结果
        assert result is True
        assert "User discussed testing." in store.history_file.read_text()
        assert "User likes testing." in store.memory_file.read_text()

    @pytest.mark.asyncio
    async def test_list_arguments_empty_list_returns_false(self, tmp_path: Path) -> None:
        """空列表参数应该返回 False。

        场景说明：
            如果 Provider 返回空的列表作为参数，
            consolidate 方法无法提取有效内容，应该返回 False。

        验证点：
            1. consolidate 返回 False
        """
        store = MemoryStore(tmp_path)
        provider = AsyncMock()

        # 模拟参数是空列表
        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="save_memory",
                    arguments=[],
                )
            ],
        )
        provider.chat = AsyncMock(return_value=response)
        provider.chat_with_retry = provider.chat
        messages = _make_messages(message_count=60)

        result = await store.consolidate(messages, provider, "test-model")

        # 验证结果
        assert result is False

    @pytest.mark.asyncio
    async def test_list_arguments_non_dict_content_returns_false(self, tmp_path: Path) -> None:
        """列表包含非字典内容应该返回 False。

        场景说明：
            如果列表中的元素不是字典（如字符串列表），
            consolidate 方法无法处理，应该返回 False。

        验证点：
            1. consolidate 返回 False
        """
        store = MemoryStore(tmp_path)
        provider = AsyncMock()

        # 模拟参数是包含字符串的列表
        response = LLMResponse(
            content=None,
            tool_calls=[
                ToolCallRequest(
                    id="call_1",
                    name="save_memory",
                    arguments=["string", "content"],
                )
            ],
        )
        provider.chat = AsyncMock(return_value=response)
        provider.chat_with_retry = provider.chat
        messages = _make_messages(message_count=60)

        result = await store.consolidate(messages, provider, "test-model")

        # 验证结果
        assert result is False

    @pytest.mark.asyncio
    async def test_retries_transient_error_then_succeeds(self, tmp_path: Path, monkeypatch) -> None:
        """测试重试瞬时错误后成功。

        场景说明：
            当 LLM API 返回瞬时错误（如 503 服务不可用）时，
            consolidate 方法应该自动重试，重试成功后返回正确结果。

        验证点：
            1. consolidate 返回 True 表示成功
            2. Provider 被调用了 2 次（第一次失败 + 第二次成功）
            3. 延迟列表为 [1]，表示重试前等待了 1 秒
        """
        store = MemoryStore(tmp_path)
        # 使用 ScriptedProvider 来模拟先错误后成功的行为
        provider = ScriptedProvider([
            LLMResponse(content="503 server error", finish_reason="error"),
            _make_tool_response(
                history_entry="[2026-01-01] User discussed testing.",
                memory_update="# Memory\nUser likes testing.",
            ),
        ])
        messages = _make_messages(message_count=60)
        delays: list[int] = []

        async def _fake_sleep(delay: int) -> None:
            delays.append(delay)

        monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

        result = await store.consolidate(messages, provider, "test-model")

        # 验证结果
        assert result is True
        # 验证重试了 2 次
        assert provider.calls == 2
        # 验证延迟时间为 [1] 秒
        assert delays == [1]

    @pytest.mark.asyncio
    async def test_consolidation_delegates_to_provider_defaults(self, tmp_path: Path) -> None:
        """巩固不再传递 generation 参数 —— Provider 自己管理这些配置。

        场景说明：
            consolidate 方法不再显式传递 generation 参数（如 temperature、max_tokens 等），
            而是由 Provider 使用自己的默认配置。

        验证点：
            1. consolidate 返回 True 表示成功
            2. chat_with_retry 被调用了一次
            3. 调用参数中包含 model 参数
            4. 调用参数中不包含 temperature、max_tokens、reasoning_effort 等 generation 参数
        """
        store = MemoryStore(tmp_path)
        provider = AsyncMock()
        provider.chat_with_retry = AsyncMock(
            return_value=_make_tool_response(
                history_entry="[2026-01-01] User discussed testing.",
                memory_update="# Memory\nUser likes testing.",
            )
        )
        messages = _make_messages(message_count=60)

        result = await store.consolidate(messages, provider, "test-model")

        # 验证结果
        assert result is True
        # 验证调用了一次
        provider.chat_with_retry.assert_awaited_once()
        # 获取调用参数
        _, kwargs = provider.chat_with_retry.await_args
        # 验证 model 参数正确
        assert kwargs["model"] == "test-model"
        # 验证不再传递 generation 参数
        assert "temperature" not in kwargs
        assert "max_tokens" not in kwargs
        assert "reasoning_effort" not in kwargs

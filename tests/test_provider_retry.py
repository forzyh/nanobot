# =============================================================================
# nanobot LLM Provider 重试机制测试
# 文件路径：tests/test_provider_retry.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 LLM Provider 重试机制的测试。
# 主要测试 chat_with_retry 方法在面对不同类型的错误时的行为。
#
# 什么是 LLM Provider 重试机制？
# ---------------
# 当调用大语言模型 API 时，可能会遇到各种错误：
# - 瞬时错误（Transient Error）：如 429 限流、503 服务不可用等，这些错误通常是暂时的，重试可能成功
# - 非瞬时错误（Non-Transient Error）：如 401 认证失败，这类错误重试也不会成功
# 重试机制会自动处理瞬时错误，通过指数退避策略进行重试。
#
# 测试场景：
# --------
# 1. 瞬时错误后重试成功：先返回 429 限流错误，第二次返回成功响应
# 2. 非瞬时错误不重试：返回 401 认证错误，直接返回不重试
# 3. 多次重试后返回最终错误：连续多次瞬时错误后，返回最终错误
# 4. 保留 CancelledError：异步取消错误应该直接抛出，不被捕获
# 5. 使用 Provider 默认配置：当调用者不指定参数时，使用 provider.generation 的默认值
# 6. 显式参数覆盖默认值：调用者显式指定的参数应该覆盖 provider 的默认配置
#
# 使用示例：
# --------
# pytest tests/test_provider_retry.py -v  # 运行所有测试
# pytest tests/test_provider_retry.py::test_chat_with_retry_retries_transient_error_then_succeeds -v  # 运行单个测试
# =============================================================================

import asyncio

import pytest

from nanobot.providers.base import GenerationSettings, LLMProvider, LLMResponse


class ScriptedProvider(LLMProvider):
    """脚本化的测试 Provider。

    这个类用于模拟 LLM Provider 的行为，可以预设一系列响应，
    每次调用 chat 方法时按顺序返回预设的响应。

    属性：
        calls (int): 记录 chat 方法被调用的次数
        last_kwargs (dict): 记录最后一次调用时的关键字参数
    """

    def __init__(self, responses):
        """初始化脚本化 Provider。

        Args:
            responses: 预设的响应列表，可以是 LLMResponse 对象或异常
        """
        super().__init__()
        self._responses = list(responses)
        self.calls = 0
        self.last_kwargs: dict = {}

    async def chat(self, *args, **kwargs) -> LLMResponse:
        """模拟聊天请求。

        每次调用时：
        1. 增加调用计数
        2. 记录最后的参数
        3. 返回下一个预设响应（如果是异常则抛出）
        """
        self.calls += 1
        self.last_kwargs = kwargs
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get_default_model(self) -> str:
        """返回默认模型名称。"""
        return "test-model"


@pytest.mark.asyncio
async def test_chat_with_retry_retries_transient_error_then_succeeds(monkeypatch) -> None:
    """测试瞬时错误后重试成功。

    场景说明：
        当第一次调用返回 429 限流错误（瞬时错误）时，
        重试机制应该等待一段时间后再次尝试，
        第二次调用返回成功响应。

    验证点：
        1. 最终响应是成功的（finish_reason == "stop"）
        2. 响应内容是第二次的成功响应
        3. Provider 被调用了 2 次（第一次失败 + 第二次成功）
        4. 延迟列表为 [1]，表示重试前等待了 1 秒（指数退避的第一次）
    """
    # 创建脚本化 Provider，预设两个响应：先返回 429 错误，再返回成功响应
    provider = ScriptedProvider([
        LLMResponse(content="429 rate limit", finish_reason="error"),
        LLMResponse(content="ok"),
    ])
    delays: list[int] = []

    # 创建假的 sleep 函数，记录延迟时间而不是真的等待
    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    # 用假的 sleep 函数替换真实的 asyncio.sleep
    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    # 调用 chat_with_retry，应该会自动重试
    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    # 验证最终响应是成功的
    assert response.finish_reason == "stop"
    assert response.content == "ok"
    # 验证调用了 2 次
    assert provider.calls == 2
    # 验证延迟时间为 [1] 秒
    assert delays == [1]


@pytest.mark.asyncio
async def test_chat_with_retry_does_not_retry_non_transient_error(monkeypatch) -> None:
    """测试非瞬时错误不重试。

    场景说明：
        当返回 401 认证错误（非瞬时错误）时，
        重试机制不应该重试，直接返回错误响应。

    验证点：
        1. 响应内容是 401 错误
        2. Provider 只被调用了 1 次（没有重试）
        3. 延迟列表为空，表示没有等待
    """
    # 创建脚本化 Provider，预设一个 401 错误响应
    provider = ScriptedProvider([
        LLMResponse(content="401 unauthorized", finish_reason="error"),
    ])
    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    # 验证返回的是 401 错误
    assert response.content == "401 unauthorized"
    # 验证只调用了 1 次，没有重试
    assert provider.calls == 1
    # 验证没有延迟
    assert delays == []


@pytest.mark.asyncio
async def test_chat_with_retry_returns_final_error_after_retries(monkeypatch) -> None:
    """测试多次重试后返回最终错误。

    场景说明：
        当连续遇到多次瞬时错误（429、503 等）时，
        重试机制会按照指数退避策略进行多次重试，
        重试次数用完后返回最终的错误。

    验证点：
        1. 最终响应是最后一次错误
        2. Provider 被调用了 4 次
        3. 延迟列表为 [1, 2, 4]，表示指数退避（2 的幂次）
    """
    # 创建脚本化 Provider，预设 4 个响应：3 次 429 错误 + 1 次 503 错误
    provider = ScriptedProvider([
        LLMResponse(content="429 rate limit a", finish_reason="error"),
        LLMResponse(content="429 rate limit b", finish_reason="error"),
        LLMResponse(content="429 rate limit c", finish_reason="error"),
        LLMResponse(content="503 final server error", finish_reason="error"),
    ])
    delays: list[int] = []

    async def _fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr("nanobot.providers.base.asyncio.sleep", _fake_sleep)

    response = await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    # 验证返回的是最终错误
    assert response.content == "503 final server error"
    # 验证调用了 4 次
    assert provider.calls == 4
    # 验证延迟时间为 [1, 2, 4]，指数退避
    assert delays == [1, 2, 4]


@pytest.mark.asyncio
async def test_chat_with_retry_preserves_cancelled_error() -> None:
    """测试保留 CancelledError 异常。

    场景说明：
        当遇到 asyncio.CancelledError 时，
        这通常表示任务被取消，不应该重试，
        而是直接抛出异常让调用者处理。

    验证点：
        1. 应该抛出 asyncio.CancelledError 异常
    """
    # 创建脚本化 Provider，预设一个 CancelledError 异常
    provider = ScriptedProvider([asyncio.CancelledError()])

    # 验证会抛出 CancelledError 异常
    with pytest.raises(asyncio.CancelledError):
        await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])


@pytest.mark.asyncio
async def test_chat_with_retry_uses_provider_generation_defaults() -> None:
    """测试使用 Provider 默认配置。

    场景说明：
        当调用者不显式指定 generation 参数时，
        chat_with_retry 应该使用 provider.generation 中配置的默认值。

    验证点：
        1. 使用的 temperature 是 provider.generation 中的 0.2
        2. 使用的 max_tokens 是 provider.generation 中的 321
        3. 使用的 reasoning_effort 是 provider.generation 中的 "high"
    """
    # 当调用者不指定参数时，provider 应使用默认配置
    provider = ScriptedProvider([LLMResponse(content="ok")])
    # 配置 provider 的默认生成参数
    provider.generation = GenerationSettings(temperature=0.2, max_tokens=321, reasoning_effort="high")

    await provider.chat_with_retry(messages=[{"role": "user", "content": "hello"}])

    # 验证使用了 provider 的默认配置
    assert provider.last_kwargs["temperature"] == 0.2
    assert provider.last_kwargs["max_tokens"] == 321
    assert provider.last_kwargs["reasoning_effort"] == "high"


@pytest.mark.asyncio
async def test_chat_with_retry_explicit_override_beats_defaults() -> None:
    """测试显式参数覆盖默认值。

    场景说明：
        当调用者显式指定 generation 参数时，
        这些参数应该覆盖 provider.generation 中的默认配置。

    验证点：
        1. 使用的 temperature 是显式指定的 0.9，而不是默认的 0.2
        2. 使用的 max_tokens 是显式指定的 9999，而不是默认的 321
        3. 使用的 reasoning_effort 是显式指定的 "low"，而不是默认的 "high"
    """
    # 显式指定的参数应该覆盖 provider 的默认配置
    provider = ScriptedProvider([LLMResponse(content="ok")])
    provider.generation = GenerationSettings(temperature=0.2, max_tokens=321, reasoning_effort="high")

    # 显式指定不同的参数值
    await provider.chat_with_retry(
        messages=[{"role": "user", "content": "hello"}],
        temperature=0.9,
        max_tokens=9999,
        reasoning_effort="low",
    )

    # 验证显式参数覆盖了默认配置
    assert provider.last_kwargs["temperature"] == 0.9
    assert provider.last_kwargs["max_tokens"] == 9999
    assert provider.last_kwargs["reasoning_effort"] == "low"

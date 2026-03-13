# =============================================================================
# nanobot Azure OpenAI 提供商测试
# 文件路径：tests/test_azure_openai_provider.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 Azure OpenAI 提供商实现的单元测试。
# Azure OpenAI 是微软 Azure 云提供的 OpenAI API 兼容服务，
# 使用不同于标准 OpenAI API 的认证方式和 URL 格式。
#
# 测试的核心功能：
# -------------------------
# 1. AzureOpenAIProvider 初始化：验证配置参数和默认值
# 2. URL 构建：测试 Azure OpenAI API 端点 URL 的正确生成
# 3. 请求头构建：测试 Azure 特定的 api-key 认证头
# 4. 请求载荷准备：测试符合 Azure API 规范的请求体生成
# 5. 聊天请求：测试成功的聊天响应和错误处理
# 6. 工具调用：测试带有工具调用的聊天请求
# 7. 响应解析：测试 Azure API 响应的解析
#
# 关键测试场景：
# --------
# 1. 提供商初始化（不带 deployment_name 参数）
# 2. 初始化参数验证（api_key 和 api_base 必填）
# 3. URL 构建（不同 deployment 名称格式）
# 4. URL 构建（api_base 有无尾部斜杠的处理）
# 5. 请求头构建（api-key 认证）
# 6. 请求载荷准备（max_completion_tokens、temperature、tools 等）
# 7. 请求载荷中的消息清理（移除 reasoning_content 等非标准字段）
# 8. 聊天成功响应
# 9. 使用默认模型的聊天请求
# 10. 带工具调用的聊天响应
# 11. API 错误处理（401 等）
# 12. 连接错误处理
# 13. 畸形响应处理
# 14. get_default_model 方法
#
# 使用示例：
# --------
# pytest tests/test_azure_openai_provider.py -v           # 运行所有测试
# pytest tests/test_azure_openai_provider.py::test_azure_openai_provider_init -v  # 运行特定测试
# =============================================================================

"""Test Azure OpenAI provider implementation (updated for model-based deployment names)."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.base import LLMResponse


def test_azure_openai_provider_init():
    """测试 AzureOpenAIProvider 初始化（不带 deployment_name 参数）。

    验证提供商初始化时正确设置 api_key、api_base、default_model 和 api_version。
    注意：新版实现不再需要 deployment_name 参数，直接使用 model 名称作为 deployment 名称。
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o-deployment",
    )

    assert provider.api_key == "test-key"
    assert provider.api_base == "https://test-resource.openai.azure.com/"  # 自动添加尾部斜杠
    assert provider.default_model == "gpt-4o-deployment"
    assert provider.api_version == "2024-10-21"  # Azure OpenAI API 版本


def test_azure_openai_provider_init_validation():
    """测试 AzureOpenAIProvider 初始化参数验证。

    验证必填参数缺失时抛出适当的错误：
    1. api_key 为空时抛出 ValueError
    2. api_base 为空时抛出 ValueError
    """
    # Missing api_key
    with pytest.raises(ValueError, match="Azure OpenAI api_key is required"):
        AzureOpenAIProvider(api_key="", api_base="https://test.com")

    # Missing api_base
    with pytest.raises(ValueError, match="Azure OpenAI api_base is required"):
        AzureOpenAIProvider(api_key="test", api_base="")


def test_build_chat_url():
    """测试 Azure OpenAI URL 构建（不同 deployment 名称）。

    验证 _build_chat_url 方法能够正确构建各种 deployment 名称的 API URL。
    Azure OpenAI 的 URL 格式与标准 OpenAI 不同，需要包含 deployment 名称。
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )

    # 测试不同的 deployment 名称格式
    test_cases = [
        ("gpt-4o-deployment", "https://test-resource.openai.azure.com/openai/deployments/gpt-4o-deployment/chat/completions?api-version=2024-10-21"),
        ("gpt-35-turbo", "https://test-resource.openai.azure.com/openai/deployments/gpt-35-turbo/chat/completions?api-version=2024-10-21"),
        ("custom-model", "https://test-resource.openai.azure.com/openai/deployments/custom-model/chat/completions?api-version=2024-10-21"),
    ]

    for deployment_name, expected_url in test_cases:
        url = provider._build_chat_url(deployment_name)
        assert url == expected_url


def test_build_chat_url_api_base_without_slash():
    """测试 api_base 不以斜杠结尾时的 URL 构建。

    验证当 api_base 没有尾部斜杠时，
    _build_chat_url 方法能够自动添加斜杠以构建正确的 URL。
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",  # No trailing slash
        default_model="gpt-4o",
    )

    url = provider._build_chat_url("test-deployment")
    expected = "https://test-resource.openai.azure.com/openai/deployments/test-deployment/chat/completions?api-version=2024-10-21"
    assert url == expected


def test_build_headers():
    """测试 Azure OpenAI 请求头构建（api-key 认证）。

    Azure OpenAI 使用 api-key 头部进行认证，
    不同于标准 OpenAI 的 Authorization: Bearer 头部。
    """
    provider = AzureOpenAIProvider(
        api_key="test-api-key-123",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )

    headers = provider._build_headers()
    assert headers["Content-Type"] == "application/json"
    assert headers["api-key"] == "test-api-key-123"  # Azure OpenAI 特定的认证头
    assert "x-session-affinity" in headers  # 会话亲和性头


def test_prepare_request_payload():
    """测试 Azure OpenAI 请求载荷准备（符合 2024-10-21 API 规范）。

    验证 _prepare_request_payload 方法正确构建请求体：
    1. 使用 max_completion_tokens 而不是 max_tokens（Azure API 2024-10-21 规范）
    2. 正确处理 tools 参数
    3. 正确处理 reasoning_effort 参数（推理模型）
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )

    messages = [{"role": "user", "content": "Hello"}]
    payload = provider._prepare_request_payload("gpt-4o", messages, max_tokens=1500, temperature=0.8)

    assert payload["messages"] == messages
    assert payload["max_completion_tokens"] == 1500  # Azure API 2024-10-21 使用 max_completion_tokens
    assert payload["temperature"] == 0.8
    assert "tools" not in payload

    # 测试带工具的情况
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
    payload_with_tools = provider._prepare_request_payload("gpt-4o", messages, tools=tools)
    assert payload_with_tools["tools"] == tools
    assert payload_with_tools["tool_choice"] == "auto"

    # 测试带 reasoning_effort（推理模型参数）
    payload_with_reasoning = provider._prepare_request_payload(
        "gpt-5-chat", messages, reasoning_effort="medium"
    )
    assert payload_with_reasoning["reasoning_effort"] == "medium"
    assert "temperature" not in payload_with_reasoning  # 推理模型不使用 temperature


def test_prepare_request_payload_sanitizes_messages():
    """测试 Azure 请求载荷清理消息中的非标准字段。

    Azure OpenAI API 不接受 reasoning_content 等非标准字段，
    需要在发送前移除这些字段。
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )

    messages = [
        {
            "role": "assistant",
            "tool_calls": [{"id": "call_123", "type": "function", "function": {"name": "x"}}],
            "reasoning_content": "hidden chain-of-thought",  # 应被移除
        },
        {
            "role": "tool",
            "tool_call_id": "call_123",
            "name": "x",
            "content": "ok",
            "extra_field": "should be removed",  # 应被移除
        },
    ]

    payload = provider._prepare_request_payload("gpt-4o", messages)

    # 验证清理后的消息
    assert payload["messages"] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_123", "type": "function", "function": {"name": "x"}}],
        },
        {
            "role": "tool",
            "tool_call_id": "call_123",
            "name": "x",
            "content": "ok",
        },
    ]


@pytest.mark.asyncio
async def test_chat_success():
    """测试聊天请求成功（使用 model 作为 deployment 名称）。

    验证 chat 方法能够：
    1. 使用提供的 model 参数作为 deployment 名称构建 URL
    2. 正确解析 API 响应
    3. 返回 LLMResponse 对象
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o-deployment",
    )

    # 模拟 API 响应数据
    mock_response_data = {
        "choices": [{
            "message": {
                "content": "Hello! How can I help you today?",
                "role": "assistant"
            },
            "finish_reason": "stop"
        }],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 18,
            "total_tokens": 30
        }
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value=mock_response_data)

        mock_context = AsyncMock()
        mock_context.post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value = mock_context

        # 测试使用特定的 model（deployment 名称）
        messages = [{"role": "user", "content": "Hello"}]
        result = await provider.chat(messages, model="custom-deployment")

        assert isinstance(result, LLMResponse)
        assert result.content == "Hello! How can I help you today?"
        assert result.finish_reason == "stop"
        assert result.usage["prompt_tokens"] == 12
        assert result.usage["completion_tokens"] == 18
        assert result.usage["total_tokens"] == 30

        # 验证 URL 使用了提供的 model 作为 deployment 名称
        call_args = mock_context.post.call_args
        expected_url = "https://test-resource.openai.azure.com/openai/deployments/custom-deployment/chat/completions?api-version=2024-10-21"
        assert call_args[0][0] == expected_url


@pytest.mark.asyncio
async def test_chat_uses_default_model_when_no_model_provided():
    """测试当没有提供 model 参数时使用 default_model。

    验证 chat 方法在没有指定 model 参数时，
    使用构造时设置的 default_model 作为 deployment 名称。
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="default-deployment",
    )

    mock_response_data = {
        "choices": [{
            "message": {"content": "Response", "role": "assistant"},
            "finish_reason": "stop"
        }],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value=mock_response_data)

        mock_context = AsyncMock()
        mock_context.post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value = mock_context

        messages = [{"role": "user", "content": "Test"}]
        await provider.chat(messages)  # 没有指定 model

        # 验证 URL 使用了 default_model 作为 deployment 名称
        call_args = mock_context.post.call_args
        expected_url = "https://test-resource.openai.azure.com/openai/deployments/default-deployment/chat/completions?api-version=2024-10-21"
        assert call_args[0][0] == expected_url


@pytest.mark.asyncio
async def test_chat_with_tool_calls():
    """测试带工具调用的聊天请求。

    验证当 API 响应包含工具调用时，
    chat 方法能够正确解析并返回 tool_calls 信息。
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )

    # 模拟带工具调用的 API 响应
    mock_response_data = {
        "choices": [{
            "message": {
                "content": None,
                "role": "assistant",
                "tool_calls": [{
                    "id": "call_12345",
                    "function": {
                        "name": "get_weather",
                        "arguments": '{"location": "San Francisco"}'
                    }
                }]
            },
            "finish_reason": "tool_calls"
        }],
        "usage": {
            "prompt_tokens": 20,
            "completion_tokens": 15,
            "total_tokens": 35
        }
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = Mock(return_value=mock_response_data)

        mock_context = AsyncMock()
        mock_context.post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value = mock_context

        messages = [{"role": "user", "content": "What's the weather?"}]
        tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]
        result = await provider.chat(messages, tools=tools, model="weather-model")

        assert isinstance(result, LLMResponse)
        assert result.content is None  # 工具调用时 content 为 None
        assert result.finish_reason == "tool_calls"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].arguments == {"location": "San Francisco"}


@pytest.mark.asyncio
async def test_chat_api_error():
    """测试聊天请求 API 错误处理。

    验证当 API 返回错误状态码（如 401）时，
    chat 方法能够正确解析错误并返回包含错误信息的 LLMResponse。
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_response = AsyncMock()
        mock_response.status_code = 401
        mock_response.text = "Invalid authentication credentials"

        mock_context = AsyncMock()
        mock_context.post = AsyncMock(return_value=mock_response)
        mock_client.return_value.__aenter__.return_value = mock_context

        messages = [{"role": "user", "content": "Hello"}]
        result = await provider.chat(messages)

        assert isinstance(result, LLMResponse)
        assert "Azure OpenAI API Error 401" in result.content
        assert "Invalid authentication credentials" in result.content
        assert result.finish_reason == "error"


@pytest.mark.asyncio
async def test_chat_connection_error():
    """测试聊天请求连接错误处理。

    验证当发生网络错误（如连接失败）时，
    chat 方法能够捕获异常并返回包含错误信息的 LLMResponse。
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )

    with patch("httpx.AsyncClient") as mock_client:
        mock_context = AsyncMock()
        mock_context.post = AsyncMock(side_effect=Exception("Connection failed"))
        mock_client.return_value.__aenter__.return_value = mock_context

        messages = [{"role": "user", "content": "Hello"}]
        result = await provider.chat(messages)

        assert isinstance(result, LLMResponse)
        assert "Error calling Azure OpenAI: Exception('Connection failed')" in result.content
        assert result.finish_reason == "error"


def test_parse_response_malformed():
    """测试畸形响应的解析处理。

    验证当 API 响应缺少必需字段（如 choices）时，
    _parse_response 方法能够返回包含错误信息的 LLMResponse。
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o",
    )

    # 测试缺少 choices 字段的响应
    malformed_response = {"usage": {"prompt_tokens": 10}}
    result = provider._parse_response(malformed_response)

    assert isinstance(result, LLMResponse)
    assert "Error parsing Azure OpenAI response" in result.content
    assert result.finish_reason == "error"


def test_get_default_model():
    """测试 get_default_model 方法。

    验证 get_default_model 返回构造时设置的 default_model 值。
    """
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="my-custom-deployment",
    )

    assert provider.get_default_model() == "my-custom-deployment"


if __name__ == "__main__":
    # 运行基本测试
    print("Running basic Azure OpenAI provider tests...")

    # 测试初始化
    provider = AzureOpenAIProvider(
        api_key="test-key",
        api_base="https://test-resource.openai.azure.com",
        default_model="gpt-4o-deployment",
    )
    print("✅ Provider initialization successful")

    # 测试 URL 构建
    url = provider._build_chat_url("my-deployment")
    expected = "https://test-resource.openai.azure.com/openai/deployments/my-deployment/chat/completions?api-version=2024-10-21"
    assert url == expected
    print("✅ URL building works correctly")

    # 测试请求头构建
    headers = provider._build_headers()
    assert headers["api-key"] == "test-key"
    assert headers["Content-Type"] == "application/json"
    print("✅ Header building works correctly")

    # 测试载荷准备
    messages = [{"role": "user", "content": "Test"}]
    payload = provider._prepare_request_payload("gpt-4o-deployment", messages, max_tokens=1000)
    assert payload["max_completion_tokens"] == 1000  # Azure 2024-10-21 格式
    print("✅ Payload preparation works correctly")

    print("✅ All basic tests passed! Updated test file is working correctly.")
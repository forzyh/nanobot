# =============================================================================
# nanobot Gemini 思考签名测试
# 文件路径：tests/test_gemini_thought_signature.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 Gemini 模型的 provider 特定字段（provider_specific_fields）
# 的测试，特别是验证"思考签名"（thought_signature）字段在以下场景中
# 的正确传递：
# 1. LLM 响应解析时保留 tool_call 的 provider_specific_fields
# 2. ToolCallRequest 序列化时保留 provider_specific_fields
#
# 测试的核心功能：
# -------------
# 1. LiteLLMProvider._parse_response() 方法：
#    - 验证解析 LLM 响应时，tool_calls 的 provider_specific_fields 被正确保留
#    - 验证 function 级别的 provider_specific_fields 也被正确保留
#
# 2. ToolCallRequest.to_openai_tool_call() 方法：
#    - 验证序列化为 OpenAI 工具调用格式时，provider_specific_fields 被正确传递
#    - 验证 function_provider_specific_fields 也被正确传递
#
# 关键测试场景：
# ------------
# 1. LLM 响应解析场景：
#    - LLM 返回包含 tool_calls 的响应
#    - 每个 tool_call 可能包含 provider_specific_fields（如 thought_signature）
#    - 每个 tool_call 的 function 也可能包含 provider_specific_fields
#    - 验证 _parse_response 方法正确保留这些字段
#
# 2. ToolCallRequest 序列化场景：
#    - 创建包含 provider_specific_fields 的 ToolCallRequest
#    - 调用 to_openai_tool_call() 序列化为 OpenAI 格式
#    - 验证序列化后的消息包含所有 provider_specific_fields
#
# 背景说明：
# ---------
# Gemini 模型在某些场景下会返回"思考签名"（thought_signature），
# 这是一个 provider 特定的字段，用于：
# - 验证 tool_call 的合法性
# - 追踪模型的思考过程
# - 确保 tool_call 没有被篡改
#
# 使用示例：
# --------
# 运行所有测试：pytest tests/test_gemini_thought_signature.py -v
# 运行单个测试：pytest tests/test_gemini_thought_signature.py::test_litellm_parse_response_preserves_tool_call_provider_fields -v
# =============================================================================

from types import SimpleNamespace

from nanobot.providers.base import ToolCallRequest
from nanobot.providers.litellm_provider import LiteLLMProvider


def test_litellm_parse_response_preserves_tool_call_provider_fields() -> None:
    """
    测试 LiteLLMProvider._parse_response 方法保留 tool_call 的 provider_specific_fields

    这个测试验证当 LLM 返回包含 tool_calls 的响应时，
    _parse_response 方法能够正确保留以下字段：
    1. tool_call 级别的 provider_specific_fields（如 thought_signature）
    2. function 级别的 provider_specific_fields

    测试步骤：
    ---------
    1. 创建 LiteLLMProvider 实例
    2. 创建模拟的 LLM 响应对象（使用 SimpleNamespace）
       - 响应包含一个 tool_call
       - tool_call 的 provider_specific_fields 包含 thought_signature
       - function 的 provider_specific_fields 包含自定义字段
    3. 调用 _parse_response 解析响应
    4. 验证解析结果包含所有 provider_specific_fields

    为什么重要：
    -----------
    - 确保 Gemini 模型的 thought_signature 不会在解析过程中丢失
    - 确保 provider 特定字段能够在系统中正确传递
    - 防止因字段丢失导致的验证失败或功能异常
    """
    # 创建 LiteLLMProvider 实例，使用 Gemini 模型
    provider = LiteLLMProvider(default_model="gemini/gemini-3-flash")

    # 创建模拟的 LLM 响应对象
    # 使用 SimpleNamespace 模拟 LiteLLM 的响应结构
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                # finish_reason 为"tool_calls"表示 LLM 决定调用工具
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    # 没有文本内容，只有工具调用
                    content=None,
                    # tool_calls 列表包含所有要调用的工具
                    tool_calls=[
                        SimpleNamespace(
                            # tool_call 的唯一标识符
                            id="call_123",
                            function=SimpleNamespace(
                                # 要调用的函数名
                                name="read_file",
                                # 函数参数（JSON 字符串格式）
                                arguments='{"path":"todo.md"}',
                                # function 级别的 provider 特定字段
                                provider_specific_fields={"inner": "value"},
                            ),
                            # tool_call 级别的 provider 特定字段
                            # thought_signature 用于验证 tool_call 的合法性
                            provider_specific_fields={"thought_signature": "signed-token"},
                        )
                    ],
                ),
            )
        ],
        # usage 为 None（此测试不关注 token 使用情况）
        usage=None,
    )

    # 调用 _parse_response 解析响应
    parsed = provider._parse_response(response)

    # 验证解析结果
    # 1. 验证只有一个 tool_call
    assert len(parsed.tool_calls) == 1
    # 2. 验证 tool_call 级别的 provider_specific_fields 被保留
    assert parsed.tool_calls[0].provider_specific_fields == {"thought_signature": "signed-token"}
    # 3. 验证 function 级别的 provider_specific_fields 被保留
    assert parsed.tool_calls[0].function_provider_specific_fields == {"inner": "value"}


def test_tool_call_request_serializes_provider_fields() -> None:
    """
    测试 ToolCallRequest.to_openai_tool_call 方法序列化 provider_specific_fields

    这个测试验证当创建 ToolCallRequest 并序列化为 OpenAI 工具调用格式时，
    provider_specific_fields 能够被正确传递。

    测试步骤：
    ---------
    1. 创建 ToolCallRequest 实例，包含：
       - provider_specific_fields（thought_signature）
       - function_provider_specific_fields（自定义字段）
    2. 调用 to_openai_tool_call() 序列化为 OpenAI 格式
    3. 验证序列化后的消息包含所有 provider_specific_fields

    为什么重要：
    -----------
    - 确保在将 tool_call 传递回 LLM 时，provider 特定字段不会丢失
    - 确保 Gemini 模型能够接收到正确的 thought_signature
    - 防止因字段丢失导致的工具调用失败
    """
    # 创建 ToolCallRequest 实例
    # 包含所有必要的字段，特别是 provider 特定字段
    tool_call = ToolCallRequest(
        # tool_call 的唯一标识符
        id="abc123xyz",
        # 要调用的工具名称
        name="read_file",
        # 工具参数（字典格式）
        arguments={"path": "todo.md"},
        # tool_call 级别的 provider 特定字段
        # thought_signature 是 Gemini 模型特有的字段
        provider_specific_fields={"thought_signature": "signed-token"},
        # function 级别的 provider 特定字段
        function_provider_specific_fields={"inner": "value"},
    )

    # 调用 to_openai_tool_call() 序列化为 OpenAI 工具调用格式
    message = tool_call.to_openai_tool_call()

    # 验证序列化结果
    # 1. 验证 tool_call 级别的 provider_specific_fields 被保留
    assert message["provider_specific_fields"] == {"thought_signature": "signed-token"}
    # 2. 验证 function 级别的 provider_specific_fields 被保留
    assert message["function"]["provider_specific_fields"] == {"inner": "value"}
    # 3. 验证 arguments 被正确序列化为 JSON 字符串
    #    OpenAI API 要求 arguments 是 JSON 字符串格式
    assert message["function"]["arguments"] == '{"path": "todo.md"}'

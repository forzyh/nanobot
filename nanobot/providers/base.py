# =============================================================================
# nanobot LLM 提供商基类
# 文件路径：nanobot/providers/base.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件定义了 LLMProvider 抽象基类，是所有 AI 模型提供商的"模板"。
#
# 什么是 LLM Provider？
# ------------------
# LLM Provider 是连接不同 AI 模型的"适配器"。nanobot 支持多种 AI 模型：
# - OpenAI (GPT-4, GPT-3.5)
# - Anthropic (Claude)
# - Azure OpenAI
# - 本地部署 (Ollama, LM Studio)
# - 其他兼容服务 (Groq, DeepSeek, 月之暗面等)
#
# 为什么需要抽象基类？
# ------------------
# 不同提供商的 API 不一样，但功能相同（聊天、工具调用）。
# 抽象基类定义了统一接口，让上层代码不需要关心具体是哪个提供商。
#
# 这种设计模式叫"策略模式"（Strategy Pattern）：
# - 定义一族算法（各提供商的 API 调用）
# - 封装每个算法（具体实现类）
# - 统一接口调用（抽象基类）
# =============================================================================

"""Base LLM provider interface."""
# LLM 提供商的基础接口

import asyncio  # 异步编程
import json  # JSON 处理
from abc import ABC, abstractmethod  # 抽象基类
from dataclasses import dataclass, field  # 数据类
from typing import Any  # 任意类型

from loguru import logger  # 日志库


# =============================================================================
# ToolCallRequest - 工具调用请求
# =============================================================================

@dataclass
class ToolCallRequest:
    """
    来自 LLM 的工具调用请求。

    当 AI 模型决定使用工具时，会返回一个工具调用请求。
    例如：用户问"今天的天气怎么样？"，AI 可能调用 weather_tool。

    属性说明：
    --------
    id: str
        工具调用的唯一标识符
        用于将调用与结果匹配

    name: str
        工具名称
        如 "web_search"、"read_file"、"exec" 等

    arguments: dict[str, Any]
        工具调用参数
        如 {"query": "今天天气", "location": "北京"}

    provider_specific_fields: dict | None
        提供商特有的字段（可选）
        不同提供商可能需要额外信息

    function_specific_fields: dict | None
        function 对象内的特有字段（可选）

    示例：
        >>> tool_call = ToolCallRequest(
        ...     id="call_123",
        ...     name="web_search",
        ...     arguments={"query": "Python 教程"}
        ... )
    """

    id: str
    name: str
    arguments: dict[str, Any]
    provider_specific_fields: dict[str, Any] | None = None
    function_provider_specific_fields: dict[str, Any] | None = None

    def to_openai_tool_call(self) -> dict[str, Any]:
        """
        序列化为 OpenAI 风格的 tool_call 格式。

        OpenAI 的工具调用格式是行业标准，许多其他提供商也兼容。
        这个方法将内部表示转换为标准格式。

        OpenAI 格式：
        ---------
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "web_search",
                "arguments": "{\"query\": \"Python 教程\"}"
            }
        }

        Returns:
            dict: OpenAI 格式的 tool_call 字典
        """
        # 构建基础结构
        tool_call = {
            "id": self.id,
            "type": "function",  # 目前只支持 function 类型
            "function": {
                "name": self.name,
                # 参数需要 JSON 序列化为字符串
                "arguments": json.dumps(self.arguments, ensure_ascii=False),
            },
        }

        # 如果有提供商特有字段，添加到顶层
        if self.provider_specific_fields:
            tool_call["provider_specific_fields"] = self.provider_specific_fields

        # 如果有 function 内的特有字段，添加到 function 对象内
        if self.function_provider_specific_fields:
            tool_call["function"]["provider_specific_fields"] = self.function_provider_specific_fields

        return tool_call


# =============================================================================
# LLMResponse - LLM 响应
# =============================================================================

@dataclass
class LLMResponse:
    """
    来自 LLM 提供商的响应。

    这是对 AI 模型响应的统一封装，无论底层是哪个提供商，
    上层代码都通过 LLMResponse 获取结果。

    属性说明：
    --------
    content: str | None
        AI 的文本回复内容
        如果 AI 只调用工具不回复，可能为 None

    tool_calls: list[ToolCallRequest]
        工具调用请求列表
        AI 可能一次调用多个工具

    finish_reason: str
        结束原因
        可能的值：
        - "stop": 正常完成
        - "length": 达到 token 限制
        - "tool_calls": 需要执行工具
        - "error": 发生错误

    usage: dict[str, int]
        Token 使用统计
        如 {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

    reasoning_content: str | None
        推理内容（某些模型特有）
        如 Kimi、DeepSeek-R1 等模型会返回思考过程

    thinking_blocks: list | None
        思考块（Anthropic 特有）
        Anthropic 的"Extended Thinking"功能

    示例：
        >>> response = LLMResponse(
        ...     content="今天北京晴天，气温 25 度。",
        ...     finish_reason="stop"
        ... )
    """

    content: str | None  # 文本内容
    tool_calls: list[ToolCallRequest] = field(default_factory=list)  # 工具调用
    finish_reason: str = "stop"  # 结束原因
    usage: dict[str, int] = field(default_factory=dict)  # Token 统计
    reasoning_content: str | None = None  # 推理内容
    thinking_blocks: list[dict] | None = None  # 思考块

    @property
    def has_tool_calls(self) -> bool:
        """
        检查响应是否包含工具调用。

        这是常用判断：
        - 如果有工具调用，需要执行工具
        - 如果没有，直接返回 content

        Returns:
            bool: True 表示有工具调用
        """
        return len(self.tool_calls) > 0


# =============================================================================
# GenerationSettings - 生成配置
# =============================================================================

@dataclass(frozen=True)
class GenerationSettings:
    """
    LLM 调用的默认生成配置。

    为什么需要这个类？
    ----------------
    每次调用 LLM 都需要指定 temperature、max_tokens 等参数。
    把这些参数集中存储，避免在每个调用处都传递一遍。

    frozen=True 的含义：
    ------------------
    数据类实例化后不能修改（不可变对象）。
    这是为了防止意外修改配置。

    属性说明：
    --------
    temperature: float
        采样温度，控制输出的随机性
        范围：0.0 - 2.0
        - 越低（如 0.2）：输出确定、保守
        - 越高（如 1.0）：输出多样、有创意
        默认值：0.7（平衡）

    max_tokens: int
        最大 token 数，限制回复长度
        1 个 token ≈ 4 个英文字符或 1.5 个汉字
        默认值：4096（约 3000-6000 字）

    reasoning_effort: str | None
        推理努力程度（某些模型支持）
        如 o1 模型支持："low"、"medium"、"high"
        默认值：None（不使用）
    """

    temperature: float = 0.7
    max_tokens: int = 4096
    reasoning_effort: str | None = None


# =============================================================================
# LLMProvider - 抽象基类
# =============================================================================

class LLMProvider(ABC):
    """
    LLM 提供商的抽象基类。

    所有具体的提供商（OpenAI、Anthropic、Azure 等）都必须继承这个类，
    并实现抽象方法（chat、get_default_model）。

    继承示例：
    --------
    class OpenAIProvider(LLMProvider):
        async def chat(self, ...):
            # 实现 OpenAI API 调用
            pass

        def get_default_model(self):
            return "gpt-4"
    """

    # 类常量：重试延迟（秒）
    # 当 API 调用失败时，按这个序列延迟重试
    # 第 1 次：等 1 秒，第 2 次：等 2 秒，第 3 次：等 4 秒
    _CHAT_RETRY_DELAYS = (1, 2, 4)

    # 类常量：临时错误标识符
    # 错误信息中包含这些词，认为是临时错误（可重试）
    _TRANSIENT_ERROR_MARKERS = (
        "429",  # Too Many Requests
        "rate limit",  # 速率限制
        "500", "502", "503", "504",  # 服务器错误
        "overloaded",  # 服务过载
        "timeout", "timed out",  # 超时
        "connection",  # 连接问题
        "server error",  # 服务器错误
        "temporarily unavailable",  # 暂时不可用
    )

    # 哨兵对象：用于检测参数是否显式传递
    # 如果参数值是 _SENTINEL，表示没有显式传递，使用默认值
    _SENTINEL = object()

    def __init__(self, api_key: str | None = None, api_base: str | None = None):
        """
        初始化 LLM 提供商。

        Args:
            api_key: API 密钥（可选）
                有些提供商需要（如 OpenAI）
                有些不需要（如本地部署）

            api_base: API 基础 URL（可选）
                用于自定义端点
                如 "https://api.openai.com/v1"
        """
        self.api_key = api_key  # API 密钥
        self.api_base = api_base  # API 端点

        # 生成配置：存储默认参数
        # 调用 chat_with_retry 时会自动使用这些默认值
        self.generation: GenerationSettings = GenerationSettings()

    @staticmethod
    def _sanitize_empty_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        替换空文本内容，防止提供商返回 400 错误。

        为什么需要这个？
        --------------
        某些 AI 提供商（如 OpenAI）不允许空字符串内容。
        当工具返回空结果时，需要特殊处理。

        处理规则：
        --------
        1. 空字符串 → None 或 "(empty)"
        2. 空文本块 → 过滤或替换
        3. 单字典内容 → 转为列表

        Args:
            messages: 消息列表

        Returns:
            list: 清理后的消息列表
        """
        result: list[dict[str, Any]] = []

        for msg in messages:
            content = msg.get("content")

            # 处理空字符串
            if isinstance(content, str) and not content:
                clean = dict(msg)
                # assistant + tool_calls 时设为 None，否则设为 "(empty)"
                clean["content"] = None if (msg.get("role") == "assistant" and msg.get("tool_calls")) else "(empty)"
                result.append(clean)
                continue

            # 处理列表内容（多模态消息）
            if isinstance(content, list):
                # 过滤空文本块
                filtered = [
                    item for item in content
                    if not (
                        isinstance(item, dict)
                        and item.get("type") in ("text", "input_text", "output_text")
                        and not item.get("text")
                    )
                ]
                if len(filtered) != len(content):
                    clean = dict(msg)
                    if filtered:
                        clean["content"] = filtered
                    elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                        clean["content"] = None
                    else:
                        clean["content"] = "(empty)"
                    result.append(clean)
                    continue

            # 处理单字典内容
            if isinstance(content, dict):
                clean = dict(msg)
                clean["content"] = [content]  # 转为列表
                result.append(clean)
                continue

            result.append(msg)

        return result

    @staticmethod
    def _sanitize_request_messages(
        messages: list[dict[str, Any]],
        allowed_keys: frozenset[str],
    ) -> list[dict[str, Any]]:
        """
        清理消息，只保留提供商安全的键。

        某些提供商对消息字段有限制，这个方法过滤掉不支持的字段。

        Args:
            messages: 消息列表
            allowed_keys: 允许的键集合

        Returns:
            list: 清理后的消息列表
        """
        sanitized = []
        for msg in messages:
            # 只保留允许的键
            clean = {k: v for k, v in msg.items() if k in allowed_keys}
            # 如果 assistant 没有 content，设为 None
            if clean.get("role") == "assistant" and "content" not in clean:
                clean["content"] = None
            sanitized.append(clean)
        return sanitized

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """
        发送聊天完成请求（抽象方法）。

        这是核心方法，每个提供商必须实现自己的版本。

        Args:
            messages: 消息列表
                格式：[{"role": "user", "content": "Hello"}, ...]

            tools: 工具定义列表（可选）
                告诉 AI 可以使用哪些工具

            model: 模型标识（可选）
                如 "gpt-4"、"claude-3" 等
                不传则使用提供商默认

            max_tokens: 最大 token 数

            temperature: 采样温度

            reasoning_effort: 推理努力（某些模型支持）

            tool_choice: 工具选择策略
                - "auto": 自动决定是否使用工具
                - "required": 必须使用工具
                - 具体工具字典：指定使用哪个工具

        Returns:
            LLMResponse: 包含内容和/或工具调用的响应

        注意：
        ----
        这是 @abstractmethod，子类必须实现。
        """
        pass  # 由子类实现

    @classmethod
    def _is_transient_error(cls, content: str | None) -> bool:
        """
        判断错误是否是临时错误（可重试）。

        临时错误：网络波动、限流、服务器临时故障等
        永久错误：认证失败、参数错误、余额不足等

        Args:
            content: 错误信息内容

        Returns:
            bool: True 表示是临时错误
        """
        err = (content or "").lower()
        # 检查是否包含任何临时错误标识
        return any(marker in err for marker in cls._TRANSIENT_ERROR_MARKERS)

    async def chat_with_retry(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: object = _SENTINEL,
        temperature: object = _SENTINEL,
        reasoning_effort: object = _SENTINEL,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        """
        调用 chat() 方法，对临时错误自动重试。

        为什么需要重试？
        --------------
        AI API 可能因为网络、限流等原因临时失败。
        自动重试可以提高成功率。

        重试策略：
        --------
        - 最多重试 3 次
        - 延迟递增：1 秒 → 2 秒 → 4 秒
        - 只重试临时错误

        参数默认值：
        ---------
        如果没有显式传递参数，使用 self.generation 中的默认值。
        这样调用方不需要每次都传递 temperature、max_tokens 等。

        Args:
            messages: 消息列表
            tools: 工具定义
            model: 模型
            max_tokens: 最大 token 数（默认用 generation.max_tokens）
            temperature: 温度（默认用 generation.temperature）
            reasoning_effort: 推理努力（默认用 generation.reasoning_effort）
            tool_choice: 工具选择策略

        Returns:
            LLMResponse: 响应结果

        示例：
            >>> response = await provider.chat_with_retry(
            ...     messages=[{"role": "user", "content": "Hello"}]
            ... )
        """
        # 如果参数没有显式传递，使用 generation 中的默认值
        if max_tokens is self._SENTINEL:
            max_tokens = self.generation.max_tokens
        if temperature is self._SENTINEL:
            temperature = self.generation.temperature
        if reasoning_effort is self._SENTINEL:
            reasoning_effort = self.generation.reasoning_effort

        # 重试循环
        for attempt, delay in enumerate(self._CHAT_RETRY_DELAYS, start=1):
            try:
                # 调用实际的 chat 方法
                response = await self.chat(
                    messages=messages,
                    tools=tools,
                    model=model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    reasoning_effort=reasoning_effort,
                    tool_choice=tool_choice,
                )
            except asyncio.CancelledError:
                # 被取消的任务直接抛出异常
                raise
            except Exception as exc:
                # 其他异常转为 LLMResponse
                response = LLMResponse(
                    content=f"Error calling LLM: {exc}",
                    finish_reason="error",
                )

            # 如果不是错误，直接返回
            if response.finish_reason != "error":
                return response
            # 如果不是临时错误，也不再重试
            if not self._is_transient_error(response.content):
                return response

            # 记录重试日志
            err = (response.content or "").lower()
            logger.warning(
                "LLM transient error (attempt {}/{}), retrying in {}s: {}",
                attempt,
                len(self._CHAT_RETRY_DELAYS),
                delay,
                err[:120],  # 只记录前 120 字符
            )
            # 等待指定时间后重试
            await asyncio.sleep(delay)

        # 所有重试都失败后，最后一次尝试
        try:
            return await self.chat(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return LLMResponse(
                content=f"Error calling LLM: {exc}",
                finish_reason="error",
            )

    @abstractmethod
    def get_default_model(self) -> str:
        """
        获取这个提供商的默认模型（抽象方法）。

        Returns:
            str: 默认模型标识

        示例：
            >>> provider.get_default_model()
            'gpt-4'
        """
        pass

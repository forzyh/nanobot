# =============================================================================
# nanobot 自定义 LLM 提供商
# 文件路径：nanobot/providers/custom_provider.py
#
# 这个文件的作用是什么？
# -------------------------
# 实现了 CustomProvider 类，用于连接任何 OpenAI 兼容的 API 端点。
#
# 什么是 CustomProvider？
# --------------------
# CustomProvider 是一个轻量级的 OpenAI 兼容 API 适配器：
# 1. 直接使用 OpenAI SDK，不经过 LiteLLM
# 2. 支持任何 OpenAI 兼容的 API（如 vLLM、Ollama、LocalAI 等）
# 3. 通过 session affinity 头提高后端缓存局部性
#
# 为什么需要 CustomProvider？
# ------------------------
# 1. 本地模型部署：连接本地运行的 LLM 服务（如 Ollama）
# 2. 私有云部署：连接企业内部的 OpenAI 兼容服务
# 3. 成本优化：使用更便宜的替代服务
# 4. 数据隐私：完全控制数据流向
#
# 工作原理：
# ---------
# 1. 初始化 AsyncOpenAI 客户端，指向自定义端点
# 2. 添加 x-session-affinity 头，提高缓存命中率
# 3. 调用 chat.completions.create() 发送请求
# 4. 解析响应，转换为标准 LLMResponse 格式
#
# 配置示例：
# --------
# {
#   "provider": {
#     "type": "custom",
#     "apiKey": "no-key",
#     "apiBase": "http://localhost:11434/v1",
#     "defaultModel": "llama2"
#   }
# }
#
# 支持的 OpenAI 兼容服务：
# ---------------------
# - Ollama (http://localhost:11434/v1)
# - vLLM (http://localhost:8000/v1)
# - LocalAI (http://localhost:8080/v1)
# - LM Studio (http://localhost:1234/v1)
# - 任何 OpenAI 兼容的 API 端点
# =============================================================================

"""Direct OpenAI-compatible provider — bypasses LiteLLM."""
# 自定义 OpenAI 兼容提供商：直接使用 OpenAI SDK，不经过 LiteLLM

from __future__ import annotations

import uuid
from typing import Any

import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest


class CustomProvider(LLMProvider):
    """
    自定义 OpenAI 兼容提供商。

    用于连接任何 OpenAI 兼容的 API 端点，如：
    - Ollama (本地模型运行器)
    - vLLM (高性能推理服务)
    - LocalAI (本地 AI 服务)
    - LM Studio (桌面模型运行器)
    - 其他 OpenAI 兼容服务

    特点：
    - 直接使用 OpenAI SDK，无需 LiteLLM 适配层
    - 通过 x-session-affinity 头提高后端缓存局部性
    - 支持工具调用（function calling）
    - 支持推理模型（reasoning_effort 参数）
    """

    def __init__(self, api_key: str = "no-key", api_base: str = "http://localhost:8000/v1", default_model: str = "default"):
        """
        初始化自定义提供商。

        Args:
            api_key: API 密钥（本地服务通常不需要，可设为 "no-key"）
            api_base: API 基础 URL（如 http://localhost:11434/v1）
            default_model: 默认模型名称（如 "llama2"、"qwen2.5"）
        """
        super().__init__(api_key, api_base)
        self.default_model = default_model
        # 保持 session affinity 稳定，提高后端缓存局部性
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers={"x-session-affinity": uuid.uuid4().hex},
        )

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
                   reasoning_effort: str | None = None,
                   tool_choice: str | dict[str, Any] | None = None) -> LLMResponse:
        """
        发送聊天完成请求到自定义 API 端点。

        Args:
            messages: 消息列表，每个消息包含 'role' 和 'content'
            tools: 工具定义列表（OpenAI 格式），用于函数调用
            model: 模型标识符（覆盖默认模型）
            max_tokens: 响应最大 token 数
            temperature: 采样温度（0-2，越高越随机）
            reasoning_effort: 推理努力程度（仅推理模型支持）
            tool_choice: 工具选择策略（"auto"、"required" 或指定工具）

        Returns:
            LLMResponse 对象，包含回复内容、工具调用和 token 使用量
        """
        kwargs: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs.update(tools=tools, tool_choice=tool_choice or "auto")
        try:
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    def _parse(self, response: Any) -> LLMResponse:
        """
        解析 API 响应并转换为标准 LLMResponse 格式。

        Args:
            response: OpenAI API 原始响应对象

        Returns:
            LLMResponse 对象，包含：
            - content: 文本回复内容
            - tool_calls: 工具调用列表（如果有）
            - finish_reason: 结束原因（stop、length、tool_calls 等）
            - usage: token 使用量统计
            - reasoning_content: 推理过程内容（仅推理模型）
        """
        choice = response.choices[0]
        msg = choice.message
        tool_calls = [
            ToolCallRequest(id=tc.id, name=tc.function.name,
                            arguments=json_repair.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments)
            for tc in (msg.tool_calls or [])
        ]
        u = response.usage
        return LLMResponse(
            content=msg.content, tool_calls=tool_calls, finish_reason=choice.finish_reason or "stop",
            usage={"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "total_tokens": u.total_tokens} if u else {},
            reasoning_content=getattr(msg, "reasoning_content", None) or None,
        )

    def get_default_model(self) -> str:
        """获取默认模型名称。"""
        return self.default_model


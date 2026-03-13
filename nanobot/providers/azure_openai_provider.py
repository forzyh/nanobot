# =============================================================================
# nanobot Azure OpenAI 提供商
# 文件路径：nanobot/providers/azure_openai_provider.py
#
# 这个文件的作用是什么？
# -------------------------
# 实现了 AzureOpenAIProvider 类，用于连接微软 Azure OpenAI 服务。
#
# 什么是 Azure OpenAI Provider？
# ---------------------------
# AzureOpenAIProvider 是微软 Azure 云 OpenAI 服务的专用适配器：
# 1. 使用 Azure OpenAI API 格式（URL、认证头、参数名）
# 2. 直接使用 HTTP 请求，不经过 LiteLLM
# 3. 符合 Azure OpenAI API 2024-10-21 版本规范
#
# 为什么需要 Azure OpenAI Provider？
# --------------------------------
# 1. 企业合规：Azure 提供企业级数据保护和合规认证
# 2. 数据主权：数据存储在指定的 Azure 区域
# 3. 私有网络：可通过 VNet 私有访问
# 4. 统一计费：与现有 Azure 账户统一结算
# 5. SLA 保障：99.9% 可用性保证
#
# Azure OpenAI 与 OpenAI 的区别：
# -----------------------------
# | 项目           | OpenAI              | Azure OpenAI           |
# |--------------|---------------------|------------------------|
# | URL 格式      | api.openai.com      | {resource}.openai.azure.com |
# | 认证方式      | Bearer Token        | api-key Header         |
# | 模型参数      | model               | deployment（部署名）    |
# | Token 限制    | max_tokens          | max_completion_tokens  |
# | API 版本      | 无                  | api-version 查询参数   |
#
# 工作原理：
# ---------
# 1. 构建 Azure OpenAI URL：
#    https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version=2024-10-21
# 2. 设置认证头：api-key: {key}
# 3. 发送 HTTP POST 请求，payload 符合 Azure 格式
# 4. 解析响应，转换为标准 LLMResponse 格式
#
# 配置示例：
# --------
# {
#   "provider": {
#     "type": "azure-openai",
#     "apiKey": "your-azure-api-key",
#     "apiBase": "https://your-resource.openai.azure.com/",
#     "defaultModel": "gpt-4"  # 这里是 Azure 部署名
#   }
# }
#
# 注意事项：
# --------
# 1. API Base URL 必须以 / 结尾（自动补充）
# 2. defaultModel 字段填写 Azure 门户中的"部署名"，不是模型名
# 3. 部分推理模型（gpt-5、o1 等）不支持 temperature 参数
# =============================================================================

"""Azure OpenAI provider implementation with API version 2024-10-21."""
# Azure OpenAI 提供商实现，符合 API 2024-10-21 版本规范

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urljoin

import httpx
import json_repair

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

# Azure 消息键白名单，用于过滤无效字段
_AZURE_MSG_KEYS = frozenset({"role", "content", "tool_calls", "tool_call_id", "name"})


class AzureOpenAIProvider(LLMProvider):
    """
    Azure OpenAI 提供商，符合 API 2024-10-21 规范。

    特点：
    - 硬编码 API 版本 2024-10-21
    - 使用 model 字段作为 Azure 部署名（用于 URL 路径）
    - 使用 api-key 头进行认证（而非 Authorization Bearer）
    - 使用 max_completion_tokens 而非 max_tokens
    - 直接 HTTP 请求，不经过 LiteLLM

    Azure OpenAI URL 格式：
    https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version={version}
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        default_model: str = "gpt-5.2-chat",
    ):
        """
        初始化 Azure OpenAI 提供商。

        Args:
            api_key: Azure OpenAI API 密钥（必填）
            api_base: Azure OpenAI 资源 URL（必填，如 https://my-resource.openai.azure.com/）
            default_model: Azure 部署名（必填，对应 Azure 门户中的 Deployment 名称）

        Raises:
            ValueError: 当 api_key 或 api_base 为空时抛出
        """
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.api_version = "2024-10-21"

        # 验证必需参数
        if not api_key:
            raise ValueError("Azure OpenAI api_key is required")
        if not api_base:
            raise ValueError("Azure OpenAI api_base is required")

        # 确保 api_base 以 / 结尾
        if not api_base.endswith('/'):
            api_base += '/'
        self.api_base = api_base

    def _build_chat_url(self, deployment_name: str) -> str:
        """
        构建 Azure OpenAI 聊天完成 URL。

        Azure OpenAI URL 格式：
        https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version={version}

        Args:
            deployment_name: Azure 部署名（即模型名称）

        Returns:
            完整的 API URL，包含 api-version 查询参数
        """
        # Azure OpenAI URL 格式：
        # https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version={version}
        base_url = self.api_base
        if not base_url.endswith('/'):
            base_url += '/'

        url = urljoin(
            base_url,
            f"openai/deployments/{deployment_name}/chat/completions"
        )
        return f"{url}?api-version={self.api_version}"

    def _build_headers(self) -> dict[str, str]:
        """
        构建 Azure OpenAI API 请求头。

        Returns:
            包含 Content-Type、api-key 和 session-affinity 的字典
        """
        return {
            "Content-Type": "application/json",
            "api-key": self.api_key,  # Azure OpenAI 使用 api-key 头，而非 Authorization
            "x-session-affinity": uuid.uuid4().hex,  # 用于缓存局部性
        }

    @staticmethod
    def _supports_temperature(
        deployment_name: str,
        reasoning_effort: str | None = None,
    ) -> bool:
        """
        判断部署是否支持 temperature 参数。

        推理模型（如 gpt-5、o1、o3、o4）不支持 temperature 参数。

        Args:
            deployment_name: 部署名称
            reasoning_effort: 推理努力参数（如果设置则不支持 temperature）

        Returns:
            True 表示支持 temperature，False 表示不支持
        """
        if reasoning_effort:
            return False
        name = deployment_name.lower()
        return not any(token in name for token in ("gpt-5", "o1", "o3", "o4"))

    def _prepare_request_payload(
        self,
        deployment_name: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        准备 Azure OpenAI 请求负载，符合 2024-10-21 API 规范。

        Args:
            deployment_name: Azure 部署名
            messages: 消息列表
            tools: 工具定义列表（可选）
            max_tokens: 最大完成 token 数
            temperature: 采样温度
            reasoning_effort: 推理努力程度
            tool_choice: 工具选择策略

        Returns:
            符合 Azure OpenAI API 格式的请求负载字典
        """
        payload: dict[str, Any] = {
            "messages": self._sanitize_request_messages(
                self._sanitize_empty_content(messages),
                _AZURE_MSG_KEYS,
            ),
            "max_completion_tokens": max(1, max_tokens),  # Azure API 2024-10-21 使用 max_completion_tokens
        }

        if self._supports_temperature(deployment_name, reasoning_effort):
            payload["temperature"] = temperature

        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        return payload

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
        向 Azure OpenAI 发送聊天完成请求。

        Args:
            messages: 消息列表，每个消息包含 'role' 和 'content'
            tools: 工具定义列表（OpenAI 格式），用于函数调用
            model: 模型标识符（用作部署名）
            max_tokens: 响应最大 token 数（映射为 max_completion_tokens）
            temperature: 采样温度
            reasoning_effort: 推理努力程度（可选）
            tool_choice: 工具选择策略

        Returns:
            LLMResponse 对象，包含回复内容和/或工具调用
        """
        deployment_name = model or self.default_model
        url = self._build_chat_url(deployment_name)
        headers = self._build_headers()
        payload = self._prepare_request_payload(
            deployment_name, messages, tools, max_tokens, temperature, reasoning_effort,
            tool_choice=tool_choice,
        )

        try:
            async with httpx.AsyncClient(timeout=60.0, verify=True) as client:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code != 200:
                    return LLMResponse(
                        content=f"Azure OpenAI API Error {response.status_code}: {response.text}",
                        finish_reason="error",
                    )

                response_data = response.json()
                return self._parse_response(response_data)

        except Exception as e:
            return LLMResponse(
                content=f"Error calling Azure OpenAI: {repr(e)}",
                finish_reason="error",
            )

    def _parse_response(self, response: dict[str, Any]) -> LLMResponse:
        """
        解析 Azure OpenAI 响应并转换为标准格式。

        Args:
            response: Azure OpenAI API 原始响应字典

        Returns:
            LLMResponse 对象，包含：
            - content: 文本回复内容
            - tool_calls: 工具调用列表（如果有）
            - finish_reason: 结束原因
            - usage: token 使用量统计
            - reasoning_content: 推理过程内容（仅推理模型）
        """
        try:
            choice = response["choices"][0]
            message = choice["message"]

            tool_calls = []
            if message.get("tool_calls"):
                for tc in message["tool_calls"]:
                    # 如果需要，从 JSON 字符串解析参数
                    args = tc["function"]["arguments"]
                    if isinstance(args, str):
                        args = json_repair.loads(args)

                    tool_calls.append(
                        ToolCallRequest(
                            id=tc["id"],
                            name=tc["function"]["name"],
                            arguments=args,
                        )
                    )

            usage = {}
            if response.get("usage"):
                usage_data = response["usage"]
                usage = {
                    "prompt_tokens": usage_data.get("prompt_tokens", 0),
                    "completion_tokens": usage_data.get("completion_tokens", 0),
                    "total_tokens": usage_data.get("total_tokens", 0),
                }

            reasoning_content = message.get("reasoning_content") or None

            return LLMResponse(
                content=message.get("content"),
                tool_calls=tool_calls,
                finish_reason=choice.get("finish_reason", "stop"),
                usage=usage,
                reasoning_content=reasoning_content,
            )

        except (KeyError, IndexError) as e:
            return LLMResponse(
                content=f"Error parsing Azure OpenAI response: {str(e)}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        """获取默认模型（也用作默认部署名）。"""
        return self.default_model
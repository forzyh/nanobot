# =============================================================================
# nanobot OpenAI Codex 提供商
# 文件路径：nanobot/providers/openai_codex_provider.py
#
# 这个文件的作用是什么？
# -------------------------
# 实现了 OpenAICodexProvider 类，用于通过 OAuth 连接 ChatGPT Codex API。
#
# 什么是 OpenAI Codex Provider？
# ---------------------------
# OpenAICodexProvider 是 ChatGPT Codex Responses API 的专用适配器：
# 1. 使用 OAuth 2.0 认证（通过 oauth_cli_kit）
# 2. 直接调用 Codex Responses API（非标准 OpenAI API）
# 3. 处理 SSE（Server-Sent Events）流式响应
#
# 为什么需要 OpenAI Codex Provider？
# --------------------------------
# 1. 访问最新模型：Codex 是 OpenAI 最新的代码专用模型
# 2. 增强功能：支持更复杂的代码理解和生成任务
# 3. ChatGPT 集成：通过 ChatGPT 后端访问，无需独立 API 密钥
#
# 工作原理：
# ---------
# 1. 使用 oauth_cli_kit 获取 OAuth token
# 2. 构建 Codex Responses API 请求（特殊格式）
# 3. 发送 HTTP POST 请求到 chatgpt.com/backend-api/codex/responses
# 4. 解析 SSE 流式响应
# 5. 将事件转换为标准 LLMResponse 格式
#
# Codex API 与标准 OpenAI API 的区别：
# ----------------------------------
# 1. 认证方式：OAuth 2.0（而非 API Key）
# 2. 请求格式：使用 "input" 数组而非 "messages"
# 3. 响应格式：SSE 流式，事件类型多样
# 4. 功能支持：支持 reasoning.encrypted_content
#
# 配置示例：
# --------
# {
#   "provider": {
#     "type": "openai-codex",
#     "defaultModel": "openai-codex/gpt-5.1-codex"
#   }
# }
#
# 注意事项：
# --------
# 1. 需要用户先通过 ChatGPT 网页登录
# 2. oauth_cli_kit 会读取本地缓存的 token
# 3. 如果 SSL 证书验证失败，会自动重试（verify=False）
# =============================================================================

"""OpenAI Codex Responses Provider."""
# OpenAI Codex Responses 提供商：通过 OAuth 访问 ChatGPT Codex API

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, AsyncGenerator

import httpx
from loguru import logger
from oauth_cli_kit import get_token as get_codex_token

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

# Codex API 默认端点
DEFAULT_CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
# 请求来源标识
DEFAULT_ORIGINATOR = "nanobot"


class OpenAICodexProvider(LLMProvider):
    """
    使用 Codex OAuth 调用 Responses API。

    特点：
    - 通过 oauth_cli_kit 获取 ChatGPT OAuth token
    - 直接调用 Codex Responses API（非标准 OpenAI API 格式）
    - 支持流式 SSE 响应解析
    - 支持 reasoning.encrypted_content（推理内容加密）
    - 自动处理 SSL 证书验证失败的情况
    """

    def __init__(self, default_model: str = "openai-codex/gpt-5.1-codex"):
        """
        初始化 OpenAI Codex 提供商。

        Args:
            default_model: 默认模型名称（如 "gpt-5.1-codex"）
        """
        super().__init__(api_key=None, api_base=None)
        self.default_model = default_model

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
        发送聊天完成请求到 Codex Responses API。

        Args:
            messages: 消息列表，每个消息包含 'role' 和 'content'
            tools: 工具定义列表（可选）
            model: 模型标识符（覆盖默认模型）
            max_tokens: 响应最大 token 数
            temperature: 采样温度
            reasoning_effort: 推理努力程度（可选）
            tool_choice: 工具选择策略

        Returns:
            LLMResponse 对象，包含回复内容和/或工具调用
        """
        model = model or self.default_model
        system_prompt, input_items = _convert_messages(messages)

        token = await asyncio.to_thread(get_codex_token)
        headers = _build_headers(token.account_id, token.access)

        body: dict[str, Any] = {
            "model": _strip_model_prefix(model),
            "store": False,
            "stream": True,
            "instructions": system_prompt,
            "input": input_items,
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": _prompt_cache_key(messages),
            "tool_choice": tool_choice or "auto",
            "parallel_tool_calls": True,
        }

        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}

        if tools:
            body["tools"] = _convert_tools(tools)

        url = DEFAULT_CODEX_URL

        try:
            try:
                content, tool_calls, finish_reason = await _request_codex(url, headers, body, verify=True)
            except Exception as e:
                if "CERTIFICATE_VERIFY_FAILED" not in str(e):
                    raise
                logger.warning("SSL certificate verification failed for Codex API; retrying with verify=False")
                content, tool_calls, finish_reason = await _request_codex(url, headers, body, verify=False)
            return LLMResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
            )
        except Exception as e:
            return LLMResponse(
                content=f"Error calling Codex: {str(e)}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        """获取默认模型名称。"""
        return self.default_model


def _strip_model_prefix(model: str) -> str:
    """
    移除模型名称的前缀。

    Args:
        model: 原始模型名称（如 "openai-codex/gpt-5.1-codex"）

    Returns:
        去除前缀后的模型名称（如 "gpt-5.1-codex"）
    """
    if model.startswith("openai-codex/") or model.startswith("openai_codex/"):
        return model.split("/", 1)[1]
    return model


def _build_headers(account_id: str, token: str) -> dict[str, str]:
    """
    构建 Codex API 请求头。

    Args:
        account_id: ChatGPT 账户 ID
        token: OAuth access token

    Returns:
        包含认证和格式信息的请求头字典
    """
    return {
        "Authorization": f"Bearer {token}",
        "chatgpt-account-id": account_id,
        "OpenAI-Beta": "responses=experimental",
        "originator": DEFAULT_ORIGINATOR,
        "User-Agent": "nanobot (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }


async def _request_codex(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    verify: bool,
) -> tuple[str, list[ToolCallRequest], str]:
    """
    向 Codex API 发送 HTTP 请求并解析 SSE 响应。

    Args:
        url: API 端点 URL
        headers: 请求头
        body: 请求体
        verify: 是否验证 SSL 证书

    Returns:
        三元组：(文本内容，工具调用列表，结束原因)
    """
    async with httpx.AsyncClient(timeout=60.0, verify=verify) as client:
        async with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                text = await response.aread()
                raise RuntimeError(_friendly_error(response.status_code, text.decode("utf-8", "ignore")))
            return await _consume_sse(response)


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    将 OpenAI 函数调用模式转换为 Codex 扁平格式。

    Codex 的工具格式与标准 OpenAI 格式略有不同，此函数负责转换。

    Args:
        tools: OpenAI 格式的工具定义列表

    Returns:
        Codex 格式的工具定义列表
    """
    converted: list[dict[str, Any]] = []
    for tool in tools:
        fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
        name = fn.get("name")
        if not name:
            continue
        params = fn.get("parameters") or {}
        converted.append({
            "type": "function",
            "name": name,
            "description": fn.get("description") or "",
            "parameters": params if isinstance(params, dict) else {},
        })
    return converted


def _convert_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """
    将标准消息格式转换为 Codex input_items 格式。

    Codex Responses API 使用不同的消息格式：
    - system 消息转换为 instructions
    - user 消息转换为 input 数组项
    - assistant 消息转换为已完成的消息或工具调用
    - tool 消息转换为 function_call_output

    Args:
        messages: 标准消息列表（包含 role 和 content）

    Returns:
        二元组：(系统提示，input_items 列表)
    """
    system_prompt = ""
    input_items: list[dict[str, Any]] = []

    for idx, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            system_prompt = content if isinstance(content, str) else ""
            continue

        if role == "user":
            input_items.append(_convert_user_message(content))
            continue

        if role == "assistant":
            # 首先处理文本内容
            if isinstance(content, str) and content:
                input_items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                        "status": "completed",
                        "id": f"msg_{idx}",
                    }
                )
            # 然后处理工具调用
            for tool_call in msg.get("tool_calls", []) or []:
                fn = tool_call.get("function") or {}
                call_id, item_id = _split_tool_call_id(tool_call.get("id"))
                call_id = call_id or f"call_{idx}"
                item_id = item_id or f"fc_{idx}"
                input_items.append(
                    {
                        "type": "function_call",
                        "id": item_id,
                        "call_id": call_id,
                        "name": fn.get("name"),
                        "arguments": fn.get("arguments") or "{}",
                    }
                )
            continue

        if role == "tool":
            call_id, _ = _split_tool_call_id(msg.get("tool_call_id"))
            output_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output_text,
                }
            )
            continue

    return system_prompt, input_items


def _convert_user_message(content: Any) -> dict[str, Any]:
    """
    转换用户消息为 Codex 格式。

    支持文本和图片内容：
    - 文本转换为 input_text
    - 图片转换为 input_image

    Args:
        content: 用户消息内容（字符串或内容数组）

    Returns:
        Codex 格式的用户消息字典
    """
    if isinstance(content, str):
        return {"role": "user", "content": [{"type": "input_text", "text": content}]}
    if isinstance(content, list):
        converted: list[dict[str, Any]] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                converted.append({"type": "input_text", "text": item.get("text", "")})
            elif item.get("type") == "image_url":
                url = (item.get("image_url") or {}).get("url")
                if url:
                    converted.append({"type": "input_image", "image_url": url, "detail": "auto"})
        if converted:
            return {"role": "user", "content": converted}
    return {"role": "user", "content": [{"type": "input_text", "text": ""}]}


def _split_tool_call_id(tool_call_id: Any) -> tuple[str, str | None]:
    """
    分割工具调用 ID。

    Codex 工具调用 ID 可能包含 call_id 和 item_id，用 | 分隔。

    Args:
        tool_call_id: 原始工具调用 ID

    Returns:
        二元组：(call_id, item_id 或 None)
    """
    if isinstance(tool_call_id, str) and tool_call_id:
        if "|" in tool_call_id:
            call_id, item_id = tool_call_id.split("|", 1)
            return call_id, item_id or None
        return tool_call_id, None
    return "call_0", None


def _prompt_cache_key(messages: list[dict[str, Any]]) -> str:
    """
    为消息列表生成提示缓存键。

    使用 SHA256 哈希值作为缓存键，用于提示缓存优化。

    Args:
        messages: 消息列表

    Returns:
        SHA256 哈希值（十六进制字符串）
    """
    raw = json.dumps(messages, ensure_ascii=True, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _iter_sse(response: httpx.Response) -> AsyncGenerator[dict[str, Any], None]:
    """
    迭代 SSE（Server-Sent Events）响应流。

    SSE 格式：
    data: {"type": "event_type", ...}

    Args:
        response: HTTP 响应对象

    Yields:
        解析后的事件字典
    """
    buffer: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if buffer:
                data_lines = [l[5:].strip() for l in buffer if l.startswith("data:")]
                buffer = []
                if not data_lines:
                    continue
                data = "\n".join(data_lines).strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    yield json.loads(data)
                except Exception:
                    continue
            continue
        buffer.append(line)


async def _consume_sse(response: httpx.Response) -> tuple[str, list[ToolCallRequest], str]:
    """
    消费 SSE 流并提取完整响应。

    处理的事件类型：
    - response.output_item.added: 添加输出项（文本或工具调用）
    - response.output_text.delta: 文本增量
    - response.function_call_arguments.delta: 工具调用参数增量
    - response.function_call_arguments.done: 工具调用参数完成
    - response.output_item.done: 输出项完成
    - response.completed: 响应完成

    Args:
        response: HTTP 响应对象

    Returns:
        三元组：(文本内容，工具调用列表，结束原因)
    """
    content = ""
    tool_calls: list[ToolCallRequest] = []
    tool_call_buffers: dict[str, dict[str, Any]] = {}
    finish_reason = "stop"

    async for event in _iter_sse(response):
        event_type = event.get("type")
        if event_type == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                tool_call_buffers[call_id] = {
                    "id": item.get("id") or "fc_0",
                    "name": item.get("name"),
                    "arguments": item.get("arguments") or "",
                }
        elif event_type == "response.output_text.delta":
            content += event.get("delta") or ""
        elif event_type == "response.function_call_arguments.delta":
            call_id = event.get("call_id")
            if call_id and call_id in tool_call_buffers:
                tool_call_buffers[call_id]["arguments"] += event.get("delta") or ""
        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id")
            if call_id and call_id in tool_call_buffers:
                tool_call_buffers[call_id]["arguments"] = event.get("arguments") or ""
        elif event_type == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                buf = tool_call_buffers.get(call_id) or {}
                args_raw = buf.get("arguments") or item.get("arguments") or "{}"
                try:
                    args = json.loads(args_raw)
                except Exception:
                    args = {"raw": args_raw}
                tool_calls.append(
                    ToolCallRequest(
                        id=f"{call_id}|{buf.get('id') or item.get('id') or 'fc_0'}",
                        name=buf.get("name") or item.get("name"),
                        arguments=args,
                    )
                )
        elif event_type == "response.completed":
            status = (event.get("response") or {}).get("status")
            finish_reason = _map_finish_reason(status)
        elif event_type in {"error", "response.failed"}:
            raise RuntimeError("Codex response failed")

    return content, tool_calls, finish_reason


# 结束原因映射表：将 Codex 状态映射为标准 finish_reason
_FINISH_REASON_MAP = {"completed": "stop", "incomplete": "length", "failed": "error", "cancelled": "error"}


def _map_finish_reason(status: str | None) -> str:
    """
    将 Codex 响应状态映射为标准结束原因。

    Args:
        status: Codex 响应状态（如 "completed"、"incomplete"）

    Returns:
        标准结束原因（stop、length、error 等）
    """
    return _FINISH_REASON_MAP.get(status or "completed", "stop")


def _friendly_error(status_code: int, raw: str) -> str:
    """
    生成友好的错误消息。

    Args:
        status_code: HTTP 状态码
        raw: 原始响应文本

    Returns:
        友好的错误描述字符串
    """
    if status_code == 429:
        return "ChatGPT usage quota exceeded or rate limit triggered. Please try again later."
    return f"HTTP {status_code}: {raw}"

# =============================================================================
# nanobot LiteLLM 提供商实现
# 文件路径：nanobot/providers/litellm_provider.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 LiteLLMProvider 类，通过 LiteLLM 库支持多 LLM 提供商。
#
# 什么是 LiteLLM？
# --------------
# LiteLLM 是一个统一的 LLM 调用库，它提供了统一的接口来调用各种 LLM 提供商：
# - OpenAI、Anthropic、Gemini 等主流提供商
# - OpenRouter、AiHubMix 等网关服务
# - vLLM、Ollama 等本地部署
#
# LiteLLMProvider 的作用：
# -------------------
# 1. 统一接口：将所有提供商的调用封装成统一的 chat() 方法
# 2. 自动路由：根据模型名自动添加提供商前缀（如 "dashscope/qwen-max"）
# 3. 环境配置：自动设置 LiteLLM 需要的环境变量
# 4. 参数覆盖：某些模型需要特殊参数（如 Kimi K2.5 强制 temperature=1.0）
# 5. Prompt 缓存：支持 Anthropic 等提供商的 cache_control 功能
# 6. 工具调用 ID 标准化：生成所有提供商兼容的 9 位字母数字 ID
#
# 依赖的模块：
# ---------
# - providers/registry.py: 提供商注册表，定义所有提供商元数据
# - providers/base.py: LLMProvider 基类，定义统一接口
# =============================================================================

"""LiteLLM provider implementation for multi-provider support."""
# LiteLLM 提供商实现，支持多提供商调用

import hashlib  # 哈希算法（用于生成工具调用 ID）
import os  # 操作系统接口
import secrets  # 安全随机数生成
import string  # 字符串常量
from typing import Any

import json_repair  # JSON 修复库（解析可能不规范的 JSON）
import litellm  # LiteLLM 库
from litellm import acompletion  # 异步补全 API
from loguru import logger  # 日志库

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest  # 基类和响应类型
from nanobot.providers.registry import find_by_model, find_gateway  # 提供商注册表

# 标准聊天完成消息的允许键
_ALLOWED_MSG_KEYS = frozenset({"role", "content", "tool_calls", "tool_call_id", "name", "reasoning_content"})
# Anthropic 特有的额外键（如 thinking_blocks）
_ANTHROPIC_EXTRA_KEYS = frozenset({"thinking_blocks"})
# 字母数字字符集（用于生成工具调用 ID）
_ALNUM = string.ascii_letters + string.digits

def _short_tool_id() -> str:
    """
    生成一个 9 位字母数字 ID，兼容所有提供商（包括 Mistral）。

    为什么需要标准化 ID？
    -----------------
    某些提供商（如 Mistral）对 tool_call_id 有严格限制：
    - 必须是字母数字
    - 长度不能超过 9 位

    这个函数生成的 ID 保证：
    1. 9 位长度
    2. 只包含字母和数字
    3. 加密安全的随机性

    Returns:
        str: 9 位字母数字 ID

    示例:
        >>> _short_tool_id()
        'aB3xK9mQ2'
    """
    return "".join(secrets.choice(_ALNUM) for _ in range(9))


class LiteLLMProvider(LLMProvider):
    """
    使用 LiteLLM 的多 LLM 提供商实现。

    通过 LiteLLM 库支持多家 LLM 提供商，包括：
    - OpenRouter、Anthropic、OpenAI、Gemini、MiniMax 等主流提供商
    - SiliconFlow、VolcEngine、BytePlus 等网关服务
    - vLLM、Ollama 等本地部署

    提供商特定逻辑由注册表（providers/registry.py）驱动，
    无需在这里编写 if-elif 条件链。

    核心功能：
    --------
    1. 统一接口：所有提供商使用相同的 chat() 方法
    2. 自动路由：根据模型名自动添加提供商前缀
    3. 环境配置：自动设置 LiteLLM 需要的环境变量
    4. 参数覆盖：某些模型需要特殊参数
    5. Prompt 缓存：支持 Anthropic 等的 cache_control 功能
    6. 工具调用 ID 标准化：生成所有提供商兼容的 ID

    使用示例：
    --------
    >>> provider = LiteLLMProvider(
    ...     api_key="sk-xxx",
    ...     default_model="claude-3-5-sonnet"
    ... )
    >>> response = await provider.chat(messages=[{"role": "user", "content": "Hello"}])
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-opus-4-5",
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
    ):
        """
        初始化 LiteLLM 提供商。

        Args:
            api_key: API 密钥（可选，某些提供商如 OAuth 不需要）
            api_base: API 基础 URL（可选，用于自定义端点）
            default_model: 默认模型标识符
                例如："anthropic/claude-opus-4-5"、"dashscope/qwen-max"
            extra_headers: 额外请求头（可选）
                例如：{"APP-Code": "xxx"} 用于 AiHubMix
            provider_name: 提供商名称（可选，用于显式指定）
                例如："openrouter"、"vllm"
        """
        super().__init__(api_key, api_base)
        self.default_model = default_model
        self.extra_headers = extra_headers or {}

        # 检测网关/本地部署提供商
        # provider_name（来自配置 key）是主要信号
        # api_key/api_base 是自动检测的后备
        self._gateway = find_gateway(provider_name, api_key, api_base)

        # 配置环境变量
        if api_key:
            self._setup_env(api_key, api_base, default_model)

        if api_base:
            litellm.api_base = api_base

        # 禁用 LiteLLM 的调试信息（减少日志噪音）
        litellm.suppress_debug_info = True
        # 丢弃不支持的参数（例如 gpt-5 拒绝某些参数）
        litellm.drop_params = True

    def _setup_env(self, api_key: str, api_base: str | None, model: str) -> None:
        """
        根据检测到的提供商设置环境变量。

        LiteLLM 依赖环境变量来识别提供商和配置端点。
        这个方法会根据注册表中的 ProviderSpec 配置相应环境变量。

        Args:
            api_key: 用户的 API 密钥
            api_base: 用户的 API 基础 URL
            model: 模型名称

        环境配置逻辑：
        -----------
        1. 网关/本地部署：覆盖现有环境变量
        2. 标准提供商：使用 setdefault（不覆盖已存在的）
        3. env_extras：解析占位符 {api_key} 和 {api_base}

        示例：
        -----
        Moonshot 需要 MOONSHOT_API_BASE：
        env_extras=(("MOONSHOT_API_BASE", "{api_base}"),)
        → os.environ["MOONSHOT_API_BASE"] = "https://api.moonshot.ai/v1"
        """
        spec = self._gateway or find_by_model(model)
        if not spec:
            return
        if not spec.env_key:
            # OAuth/仅提供商的规格（如 openai_codex）不需要 API Key
            return

        # 网关/本地部署：覆盖现有环境变量
        # 标准提供商：保留已存在的环境变量
        if self._gateway:
            os.environ[spec.env_key] = api_key
        else:
            os.environ.setdefault(spec.env_key, api_key)

        # 解析 env_extras 中的占位符：
        #   {api_key}  → 用户的 API 密钥
        #   {api_base} → 用户的 api_base，或 spec.default_api_base
        effective_base = api_base or spec.default_api_base
        for env_name, env_val in spec.env_extras:
            resolved = env_val.replace("{api_key}", api_key)
            resolved = resolved.replace("{api_base}", effective_base)
            os.environ.setdefault(env_name, resolved)

    def _resolve_model(self, model: str) -> str:
        """
        解析模型名称，应用提供商/网关前缀。

        LiteLLM 要求模型名包含提供商前缀才能正确路由。
        例如："qwen-max" → "dashscope/qwen-max"

        Args:
            model: 原始模型名称

        Returns:
            str: 带前缀的模型名称

        网关模式：
        -------
        1. 如果网关配置了 strip_model_prefix=True，先剥离原有前缀
        2. 应用网关的 litellm_prefix

        标准模式：
        -------
        1. 通过模型名匹配提供商
        2. 规范化显式前缀（如 github-copilot/... → github_copilot/...）
        3. 添加 litellm_prefix（如果尚未包含）
        """
        if self._gateway:
            # 网关模式：应用网关前缀，跳过特定提供商前缀
            prefix = self._gateway.litellm_prefix
            if self._gateway.strip_model_prefix:
                model = model.split("/")[-1]  # 剥离到 bare 模型名
            if prefix and not model.startswith(f"{prefix}/"):
                model = f"{prefix}/{model}"
            return model

        # 标准模式：为已知提供商自动添加前缀
        spec = find_by_model(model)
        if spec and spec.litellm_prefix:
            model = self._canonicalize_explicit_prefix(model, spec.name, spec.litellm_prefix)
            if not any(model.startswith(s) for s in spec.skip_prefixes):
                model = f"{spec.litellm_prefix}/{model}"

        return model

    @staticmethod
    def _canonicalize_explicit_prefix(model: str, spec_name: str, canonical_prefix: str) -> str:
        """
        规范化显式提供商前缀，如 `github-copilot/...`。

        为什么要规范化？
        ---------------
        用户可能使用不同的前缀变体：
        - "github-copilot/model"（连字符）
        - "github_copilot/model"（下划线）

        这个方法将它们统一为 LiteLLM 使用的标准前缀。

        Args:
            model: 模型名称（可能包含前缀）
            spec_name: 规格名称（如 "github_copilot"）
            canonical_prefix: 标准前缀（如 "github_copilot"）

        Returns:
            str: 规范化后的模型名称

        示例：
        -----
        >>> _canonicalize_explicit_prefix("github-copilot/model", "github_copilot", "github_copilot")
        'github_copilot/model'
        """
        if "/" not in model:
            return model
        prefix, remainder = model.split("/", 1)
        if prefix.lower().replace("-", "_") != spec_name:
            return model  # 前缀不匹配，保持原样
        return f"{canonical_prefix}/{remainder}"

    def _supports_cache_control(self, model: str) -> bool:
        """
        检查提供商是否支持 cache_control（prompt 缓存）。

        Args:
            model: 模型名称

        Returns:
            bool: True 表示支持 prompt 缓存
        """
        if self._gateway is not None:
            return self._gateway.supports_prompt_caching
        spec = find_by_model(model)
        return spec is not None and spec.supports_prompt_caching

    def _apply_cache_control(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
        """
        为消息和工具注入 cache_control 字段（用于 prompt 缓存）。

        什么是 prompt 缓存？
        -----------------
        Anthropic 等提供商支持缓存 system prompt 和工具定义，
        通过 cache_control: {"type": "ephemeral"} 标记。

        缓存策略：
        --------
        1. system 消息的最后一个文本块
        2. 工具定义的最后一个工具

        Args:
            messages: 消息列表
            tools: 工具定义列表

        Returns:
            tuple: (注入缓存的消息，注入缓存的工具)
        """
        new_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg["content"]
                if isinstance(content, str):
                    # 字符串内容：转为带 cache_control 的文本块
                    new_content = [{"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}]
                else:
                    # 已有多块：标记最后一块
                    new_content = list(content)
                    new_content[-1] = {**new_content[-1], "cache_control": {"type": "ephemeral"}}
                new_messages.append({**msg, "content": new_content})
            else:
                new_messages.append(msg)

        new_tools = tools
        if tools:
            new_tools = list(tools)
            # 标记最后一个工具用于缓存
            new_tools[-1] = {**new_tools[-1], "cache_control": {"type": "ephemeral"}}

        return new_messages, new_tools

    def _apply_model_overrides(self, model: str, kwargs: dict[str, Any]) -> None:
        """
        应用注册表中定义的模型特定参数覆盖。

        某些模型需要特殊的参数配置：
        - Kimi K2.5: 强制 temperature >= 1.0
        - 其他模型可能也有类似要求

        Args:
            model: 模型名称
            kwargs: 当前参数字典（会被就地修改）

        示例：
        -----
        >>> kwargs = {"temperature": 0.7}
        >>> provider._apply_model_overrides("kimi-k2.5", kwargs)
        >>> kwargs
        {"temperature": 1.0}  # 被覆盖
        """
        model_lower = model.lower()
        spec = find_by_model(model)
        if spec:
            for pattern, overrides in spec.model_overrides:
                if pattern in model_lower:
                    kwargs.update(overrides)
                    return

    @staticmethod
    def _extra_msg_keys(original_model: str, resolved_model: str) -> frozenset[str]:
        """
        返回特定于提供商的额外消息键。

        不同提供商支持的消息字段不同：
        - Anthropic: 支持 thinking_blocks（推理思考块）
        - 其他提供商：只支持标准字段

        Args:
            original_model: 原始模型名称
            resolved_model: 解析后的模型名称（带前缀）

        Returns:
            frozenset[str]: 允许的消息键集合

        示例：
        -----
        >>> LiteLLMProvider._extra_msg_keys("claude-3-5-sonnet", "claude-3-5-sonnet")
        frozenset({"thinking_blocks"})
        """
        spec = find_by_model(original_model) or find_by_model(resolved_model)
        if (spec and spec.name == "anthropic") or "claude" in original_model.lower() or resolved_model.startswith("anthropic/"):
            return _ANTHROPIC_EXTRA_KEYS
        return frozenset()

    @staticmethod
    def _normalize_tool_call_id(tool_call_id: Any) -> Any:
        """
        将 tool_call_id 标准化为提供商安全的 9 位字母数字形式。

        为什么要标准化？
        ---------------
        某些提供商（如 Mistral）对 tool_call_id 有严格要求：
        - 必须是 9 位字母数字
        - 超出长度会被拒绝

        标准化策略：
        -----------
        1. 如果已经是 9 位字母数字，保持不变
        2. 否则使用 SHA1 哈希截取前 9 位

        Args:
            tool_call_id: 原始工具调用 ID

        Returns:
            Any: 标准化后的 ID（9 位字母数字）

        示例：
        -----
        >>> LiteLLMProvider._normalize_tool_call_id("call_abc123")
        'a1b2c3d4e'  # SHA1 哈希前 9 位
        >>> LiteLLMProvider._normalize_tool_call_id("aB3xK9mQ2")
        'aB3xK9mQ2'  # 已经是 9 位字母数字，保持不变
        """
        if not isinstance(tool_call_id, str):
            return tool_call_id
        if len(tool_call_id) == 9 and tool_call_id.isalnum():
            return tool_call_id
        # 使用 SHA1 哈希确保唯一性，截取前 9 位
        return hashlib.sha1(tool_call_id.encode()).hexdigest()[:9]

    @staticmethod
    def _sanitize_messages(messages: list[dict[str, Any]], extra_keys: frozenset[str] = frozenset()) -> list[dict[str, Any]]:
        """
        清理消息：剥离非标准键，确保 assistant 消息有 content 键。

        清理内容：
        --------
        1. 移除不允许的键（只保留 role, content, tool_calls 等）
        2. 标准化 tool_call_id（映射为 9 位字母数字 ID）
        3. 保持 assistant 的 tool_calls[].id 和 tool 的 tool_call_id 同步

        为什么要映射同步？
        ---------------
        如果 assistant 消息中的 tool_calls[].id 被缩短，
        对应的 tool 消息的 tool_call_id 也必须使用相同的缩短 ID，
        否则严格提供商会拒绝工具调用链路断裂。

        Args:
            messages: 原始消息列表
            extra_keys: 额外允许的键（如 thinking_blocks）

        Returns:
            list[dict[str, Any]]: 清理后的消息列表
        """
        allowed = _ALLOWED_MSG_KEYS | extra_keys
        sanitized = LLMProvider._sanitize_request_messages(messages, allowed)
        id_map: dict[str, str] = {}  # 记录原始 ID 到缩短 ID 的映射

        def map_id(value: Any) -> Any:
            """映射工具调用 ID，确保同一原始 ID 映射到同一缩短 ID。"""
            if not isinstance(value, str):
                return value
            return id_map.setdefault(value, LiteLLMProvider._normalize_tool_call_id(value))

        for clean in sanitized:
            # 处理 assistant 消息的 tool_calls[].id
            if isinstance(clean.get("tool_calls"), list):
                normalized_tool_calls = []
                for tc in clean["tool_calls"]:
                    if not isinstance(tc, dict):
                        normalized_tool_calls.append(tc)
                        continue
                    tc_clean = dict(tc)
                    tc_clean["id"] = map_id(tc_clean.get("id"))  # 映射 ID
                    normalized_tool_calls.append(tc_clean)
                clean["tool_calls"] = normalized_tool_calls

            # 处理 tool 消息的 tool_call_id
            if "tool_call_id" in clean and clean["tool_call_id"]:
                clean["tool_call_id"] = map_id(clean["tool_call_id"])  # 同步映射

        return sanitized

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
        通过 LiteLLM 发送聊天完成请求。

        这是 LiteLLMProvider 的核心方法，负责：
        1. 解析模型名称（添加提供商前缀）
        2. 应用 prompt 缓存（如果支持）
        3. 清理和标准化消息
        4. 应用模型特定参数覆盖
        5. 调用 LiteLLM API
        6. 解析响应为标准格式

        Args:
            messages: 消息列表，每个消息是包含 'role' 和 'content' 的字典
                例如：[{"role": "user", "content": "Hello"}]
            tools: 可选的工具定义列表（OpenAI 格式）
                用于函数调用/工具使用
            model: 模型标识符（可选）
                例如："anthropic/claude-sonnet-4-5"
                如果不提供，使用默认模型
            max_tokens: 响应最大 token 数（默认 4096）
            temperature: 采样温度（默认 0.7）
                越高越随机，越低越确定
            reasoning_effort: 推理努力程度（可选）
                用于支持推理的模型（如 o1、o3）
            tool_choice: 工具选择策略（可选）
                - "auto": 自动决定是否使用工具
                - "none": 不使用工具
                - "required": 必须使用工具
                - dict: 指定特定工具

        Returns:
            LLMResponse: 标准格式的响应对象
                包含 content（文本内容）和/或 tool_calls（工具调用）

        处理流程：
        --------
        1. 解析模型名 → "qwen-max" → "dashscope/qwen-max"
        2. 检查 prompt 缓存支持 → 注入 cache_control
        3. 清理消息 → 移除不支持的字段，标准化 tool_call_id
        4. 应用模型覆盖 → kimi-k2.5 → temperature=1.0
        5. 调用 acompletion(**kwargs)
        6. 解析响应 → LLMResponse

        错误处理：
        --------
        所有异常都会被捕获，错误信息作为 content 返回：
        "Error calling LLM: [错误详情]"
        这样上层代码可以统一处理错误。

        示例：
        -----
        >>> response = await provider.chat(
        ...     messages=[{"role": "user", "content": "Hello"}],
        ...     tools=[...],
        ...     model="claude-3-5-sonnet"
        ... )
        >>> print(response.content)
        "Hello! How can I help you?"
        >>> print(response.tool_calls)
        [ToolCallRequest(id="...", name="search", arguments={...})]
        """
        original_model = model or self.default_model
        # 解析模型名称（添加提供商前缀）
        model = self._resolve_model(original_model)
        # 获取提供商特定的额外消息键
        extra_msg_keys = self._extra_msg_keys(original_model, model)

        # 应用 prompt 缓存（如果支持）
        if self._supports_cache_control(original_model):
            messages, tools = self._apply_cache_control(messages, tools)

        # 确保 max_tokens >= 1 —— 负值或零值会被 LiteLLM 拒绝
        max_tokens = max(1, max_tokens)

        # 构建请求参数
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": self._sanitize_messages(self._sanitize_empty_content(messages), extra_keys=extra_msg_keys),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        # 应用模型特定参数覆盖（如 kimi-k2.5 temperature=1.0）
        self._apply_model_overrides(model, kwargs)

        # 直接传递 api_key —— 比仅依赖环境变量更可靠
        if self.api_key:
            kwargs["api_key"] = self.api_key

        # 传递 api_base 用于自定义端点
        if self.api_base:
            kwargs["api_base"] = self.api_base

        # 传递额外请求头（如 AiHubMix 的 APP-Code）
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers

        # 推理努力程度（用于 o1、o3 等推理模型）
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
            kwargs["drop_params"] = True  # 丢弃不支持的参数

        # 工具定义
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        try:
            # 调用 LiteLLM 异步完成 API
            response = await acompletion(**kwargs)
            return self._parse_response(response)
        except Exception as e:
            # 将错误作为 content 返回，便于上层统一处理
            return LLMResponse(
                content=f"Error calling LLM: {str(e)}",
                finish_reason="error",
            )

    def _parse_response(self, response: Any) -> LLMResponse:
        """
        将 LiteLLM 响应解析为标准格式。

        这个方法负责：
        1. 提取文本内容
        2. 合并多 choice 的工具调用（某些提供商如 GitHub Copilot 会分散在多个 choice 中）
        3. 解析工具调用参数（从 JSON 字符串）
        4. 标准化工具调用 ID（9 位字母数字）
        5. 提取使用量统计
        6. 提取推理内容（reasoning_content/thinking_blocks）

        Args:
            response: LiteLLM 原始响应对象

        Returns:
            LLMResponse: 标准格式的响应对象

        多 Choice 合并：
        -------------
        某些提供商（如 GitHub Copilot）会将 content 和 tool_calls
        分散在多个 choice 中。这个方法会合并所有 choice 的 tool_calls，
        确保工具调用不丢失。

        工具调用处理：
        -----------
        1. 生成新的 9 位字母数字 ID（替换提供商原始的 ID）
        2. 从 JSON 字符串解析参数（如果需要）
        3. 提取 provider_specific_fields（提供商特定字段）

        示例：
        -----
        >>> response = await litellm.acompletion(...)
        >>> parsed = provider._parse_response(response)
        >>> parsed.content
        "好的，我来帮你查询天气。"
        >>> parsed.tool_calls
        [ToolCallRequest(id="aB3xK9mQ2", name="search", arguments={"query": "北京天气"})]
        """
        choice = response.choices[0]
        message = choice.message
        content = message.content
        finish_reason = choice.finish_reason

        # 合并多 choice 的工具调用（某些提供商如 GitHub Copilot 会分散）
        raw_tool_calls = []
        for ch in response.choices:
            msg = ch.message
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                raw_tool_calls.extend(msg.tool_calls)
                if ch.finish_reason in ("tool_calls", "stop"):
                    finish_reason = ch.finish_reason
            if not content and msg.content:
                content = msg.content

        # 记录多 choice 合并日志
        if len(response.choices) > 1:
            logger.debug("LiteLLM response has {} choices, merged {} tool_calls",
                         len(response.choices), len(raw_tool_calls))

        tool_calls = []
        for tc in raw_tool_calls:
            # 从 JSON 字符串解析参数（如果需要）
            args = tc.function.arguments
            if isinstance(args, str):
                args = json_repair.loads(args)  # 修复并解析 JSON

            # 提取提供商特定字段
            provider_specific_fields = getattr(tc, "provider_specific_fields", None) or None
            function_provider_specific_fields = (
                getattr(tc.function, "provider_specific_fields", None) or None
            )

            # 创建标准工具调用请求（使用新生成的 9 位 ID）
            tool_calls.append(ToolCallRequest(
                id=_short_tool_id(),  # 生成新的标准化 ID
                name=tc.function.name,
                arguments=args,
                provider_specific_fields=provider_specific_fields,
                function_provider_specific_fields=function_provider_specific_fields,
            ))

        # 提取使用量统计
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        # 提取推理内容（某些推理模型特有）
        reasoning_content = getattr(message, "reasoning_content", None) or None
        thinking_blocks = getattr(message, "thinking_blocks", None) or None

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            usage=usage,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        )

    def get_default_model(self) -> str:
        """
        获取默认模型名称。

        Returns:
            str: 默认模型标识符
        """
        return self.default_model

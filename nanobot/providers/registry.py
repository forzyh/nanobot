# =============================================================================
# nanobot LLM 提供商注册表
# 文件路径：nanobot/providers/registry.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件定义了 LLM 提供商的"中央登记处"，是所有提供商元数据的单一事实来源。
#
# 什么是 ProviderSpec？
# -----------------
# ProviderSpec 是一个数据类，描述了每个 LLM 提供商的元数据信息：
# - 如何识别该提供商（通过模型名称关键词、API Key 前缀等）
# - 如何配置环境变量
# - 如何处理模型名称前缀
# - 是否支持特殊功能（如 prompt 缓存）
#
# 为什么需要注册表？
# ----------------
# 1. 统一管理：所有提供商信息集中在一个地方
# 2. 自动匹配：根据模型名称自动识别提供商
# 3. 自动检测：根据 API Key 前缀检测网关提供商
# 4. 易于扩展：添加新提供商只需修改这里和 config/schema.py
#
# 添加新提供商的步骤：
# ----------------
# 1. 在 PROVIDERS 元组中添加一个 ProviderSpec
# 2. 在 config/schema.py 的 ProvidersConfig 中添加对应字段
# 完成！环境变量、前缀处理、配置匹配、状态显示都会自动生效
#
# 匹配优先级：
# ---------
# 1. 网关提供商优先（OpenRouter、AiHubMix 等）
# 2. 标准提供商（Anthropic、OpenAI 等）
# 3. 本地部署（vLLM、Ollama 等）
# =============================================================================

"""Provider Registry — single source of truth for LLM provider metadata."""
# 提供商注册表 — LLM 提供商元数据的单一事实来源

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderSpec:
    """
    单个 LLM 提供商的元数据规格。

    这个数据类描述了 nanobot 如何识别和配置一个 LLM 提供商。
    所有 PROVIDERS 中的字段都應該完整填写，便于复制粘贴作为模板。

    env_extras 中的占位符：
    -----------------
    {api_key}  — 用户的 API 密钥
    {api_base} — 来自配置的 api_base，或该规格的 default_api_base

    属性说明：
    --------
    name: str
        配置字段名称，如 "dashscope"、"openai"
        用于在配置文件中识别该提供商

    keywords: tuple[str, ...]
        模型名称匹配关键词（小写）
        例如：("qwen", "dashscope") 可以匹配 "qwen-max"、"dashscope/qwen-turbo"

    env_key: str
        LiteLLM 使用的环境变量名
        例如："DASHSCOPE_API_KEY"、"OPENAI_API_KEY"

    display_name: str
        显示名称，用于 `nanobot status` 命令
        例如："DashScope"、"OpenAI"

    litellm_prefix: str
        LiteLLM 路由前缀
        例如："dashscope" → 模型名变为 "dashscope/qwen-max"

    skip_prefixes: tuple[str, ...]
        如果模型名已包含这些前缀，不再重复添加
        例如：("dashscope/", "openrouter/") 避免重复前缀

    env_extras: tuple[tuple[str, str], ...]
        额外环境变量
        例如：(("ZHIPUAI_API_KEY", "{api_key}"),) 将 API Key 复制到另一个变量

    is_gateway: bool
        是否是网关型提供商（可以路由任意模型）
        例如：OpenRouter、AiHubMix 是网关，可以访问多家模型

    is_local: bool
        是否是本地部署
        例如：vLLM、Ollama 是本地部署

    detect_by_key_prefix: str
        通过 API Key 前缀检测
        例如："sk-or-" → OpenRouter

    detect_by_base_keyword: str
        通过 api_base URL 关键词检测
        例如："openrouter" 匹配到 openrouter.ai

    default_api_base: str
        默认 API 基础 URL
        用于网关型提供商

    strip_model_prefix: bool
        是否剥离模型名中的提供商前缀
        例如：AiHubMix 不理解 "anthropic/claude-3"，
        需要先剥离为 "claude-3" 再重新前缀为 "openai/claude-3"

    model_overrides: tuple[tuple[str, dict[str, Any]], ...]
        特定模型的参数覆盖
        例如：(("kimi-k2.5", {"temperature": 1.0}),) Kimi K2.5 强制 temperature=1.0

    is_oauth: bool
        是否使用 OAuth 认证（不使用 API Key）
        例如：OpenAI Codex、GitHub Copilot 使用 OAuth

    is_direct: bool
        是否直接调用（绕过 LiteLLM）
        例如：CustomProvider、AzureOpenAIProvider 直接调用 API

    supports_prompt_caching: bool
        是否支持 prompt 缓存（cache_control）
        例如：Anthropic 支持缓存系统 prompt 和工具定义

    label: property
        显示标签，优先使用 display_name，否则用 name 的首字母大写
    """

    # 身份标识
    name: str  # 配置字段名称，例如 "dashscope"
    keywords: tuple[str, ...]  # 模型名称匹配关键词（小写）
    env_key: str  # LiteLLM 环境变量名，例如 "DASHSCOPE_API_KEY"
    display_name: str = ""  # 显示名称，用于 `nanobot status`

    # 模型前缀处理
    litellm_prefix: str = ""  # "dashscope" → 模型名变为 "dashscope/{model}"
    skip_prefixes: tuple[str, ...] = ()  # 如果模型已包含这些前缀，不再重复添加

    # 额外环境变量，例如：(("ZHIPUAI_API_KEY", "{api_key}"),)
    env_extras: tuple[tuple[str, str], ...] = ()

    # 网关/本地检测
    is_gateway: bool = False  # 网关型，可路由任意模型（OpenRouter、AiHubMix）
    is_local: bool = False  # 本地部署（vLLM、Ollama）
    detect_by_key_prefix: str = ""  # API Key 前缀匹配，例如 "sk-or-"
    detect_by_base_keyword: str = ""  # api_base URL 关键词匹配
    default_api_base: str = ""  # 默认 API 基础 URL

    # 网关行为
    strip_model_prefix: bool = False  # 是否先剥离 "provider/" 再重新前缀

    # 特定模型参数覆盖，例如：(("kimi-k2.5", {"temperature": 1.0}),)
    model_overrides: tuple[tuple[str, dict[str, Any]], ...] = ()

    # OAuth 认证提供商（如 OpenAI Codex）不使用 API Key
    is_oauth: bool = False  # True 表示使用 OAuth 流程而非 API Key

    # 直接调用提供商（绕过 LiteLLM，如 CustomProvider）
    is_direct: bool = False

    # 提供商支持 prompt 缓存（如 Anthropic 的 cache_control）
    supports_prompt_caching: bool = False

    @property
    def label(self) -> str:
        """获取显示标签。"""
        return self.display_name or self.name.title()


# ---------------------------------------------------------------------------
# PROVIDERS — 提供商注册表，按优先级排序，任何条目都可作为模板复制
# ---------------------------------------------------------------------------

PROVIDERS: tuple[ProviderSpec, ...] = (
    # === Custom（直接调用 OpenAI 兼容端点，绕过 LiteLLM）===================
    ProviderSpec(
        name="custom",
        keywords=(),
        env_key="",
        display_name="Custom",
        litellm_prefix="",
        is_direct=True,  # 直接调用，不经过 LiteLLM
    ),

    # === Azure OpenAI（直接 API 调用，API version 2024-10-21）=============
    ProviderSpec(
        name="azure_openai",
        keywords=("azure", "azure-openai"),
        env_key="",
        display_name="Azure OpenAI",
        litellm_prefix="",
        is_direct=True,  # 直接调用
    ),

    # === 网关型提供商（通过 api_key/api_base 检测，而非模型名称）===========
    # 网关型可以路由任意模型，所以在 fallback 中优先级最高
    # OpenRouter: 全球网关，API Key 以 "sk-or-" 开头
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        env_key="OPENROUTER_API_KEY",
        display_name="OpenRouter",
        litellm_prefix="openrouter",  # claude-3 → openrouter/claude-3
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="sk-or-",  # API Key 前缀检测
        detect_by_base_keyword="openrouter",  # URL 关键词检测
        default_api_base="https://openrouter.ai/api/v1",
        strip_model_prefix=False,
        model_overrides=(),
        supports_prompt_caching=True,  # 支持 prompt 缓存
    ),

    # AiHubMix: 全球网关，OpenAI 兼容接口
    # strip_model_prefix=True: 它不理解 "anthropic/claude-3"，
    # 所以先剥离为 "claude-3" 再重新前缀为 "openai/claude-3"
    ProviderSpec(
        name="aihubmix",
        keywords=("aihubmix",),
        env_key="OPENAI_API_KEY",  # OpenAI 兼容
        display_name="AiHubMix",
        litellm_prefix="openai",  # → openai/{model}
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="aihubmix",
        default_api_base="https://aihubmix.com/v1",
        strip_model_prefix=True,  # anthropic/claude-3 → claude-3 → openai/claude-3
        model_overrides=(),
    ),

    # SiliconFlow (硅基流动): OpenAI 兼容网关，模型名保留机构前缀
    ProviderSpec(
        name="siliconflow",
        keywords=("siliconflow",),
        env_key="OPENAI_API_KEY",
        display_name="SiliconFlow",
        litellm_prefix="openai",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="siliconflow",
        default_api_base="https://api.siliconflow.cn/v1",
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # VolcEngine (火山引擎): OpenAI 兼容网关，按量付费模型
    ProviderSpec(
        name="volcengine",
        keywords=("volcengine", "volces", "ark"),
        env_key="OPENAI_API_KEY",
        display_name="VolcEngine",
        litellm_prefix="volcengine",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="volces",
        default_api_base="https://ark.cn-beijing.volces.com/api/v3",
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # VolcEngine Coding Plan (火山引擎 Coding Plan): 与 volcengine 使用相同的 API Key
    ProviderSpec(
        name="volcengine_coding_plan",
        keywords=("volcengine-plan",),
        env_key="OPENAI_API_KEY",
        display_name="VolcEngine Coding Plan",
        litellm_prefix="volcengine",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="https://ark.cn-beijing.volces.com/api/coding/v3",
        strip_model_prefix=True,
        model_overrides=(),
    ),

    # BytePlus: 火山引擎国际版，按量付费模型
    ProviderSpec(
        name="byteplus",
        keywords=("byteplus",),
        env_key="OPENAI_API_KEY",
        display_name="BytePlus",
        litellm_prefix="volcengine",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="bytepluses",
        default_api_base="https://ark.ap-southeast.bytepluses.com/api/v3",
        strip_model_prefix=True,
        model_overrides=(),
    ),

    # BytePlus Coding Plan: 与 byteplus 使用相同的 API Key
    ProviderSpec(
        name="byteplus_coding_plan",
        keywords=("byteplus-plan",),
        env_key="OPENAI_API_KEY",
        display_name="BytePlus Coding Plan",
        litellm_prefix="volcengine",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=True,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="https://ark.ap-southeast.bytepluses.com/api/coding/v3",
        strip_model_prefix=True,
        model_overrides=(),
    ),


    # === 标准提供商（通过模型名称关键词匹配）===============================
    # Anthropic: LiteLLM 原生识别 "claude-*"，无需前缀
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        litellm_prefix="",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
        supports_prompt_caching=True,  # 支持 prompt 缓存
    ),

    # OpenAI: LiteLLM 原生识别 "gpt-*"，无需前缀
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        litellm_prefix="",
        skip_prefixes=(),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # OpenAI Codex: 使用 OAuth，不使用 API Key
    ProviderSpec(
        name="openai_codex",
        keywords=("openai-codex",),
        env_key="",  # OAuth 认证，无 API Key
        display_name="OpenAI Codex",
        litellm_prefix="",  # 不经过 LiteLLM 路由
        skip_prefixes=(),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="codex",
        default_api_base="https://chatgpt.com/backend-api",
        strip_model_prefix=False,
        model_overrides=(),
        is_oauth=True,  # OAuth 认证
    ),

    # Github Copilot: 使用 OAuth，不使用 API Key
    ProviderSpec(
        name="github_copilot",
        keywords=("github_copilot", "copilot"),
        env_key="",  # OAuth 认证，无 API Key
        display_name="Github Copilot",
        litellm_prefix="github_copilot",  # github_copilot/model → github_copilot/model
        skip_prefixes=("github_copilot/",),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
        is_oauth=True,  # OAuth 认证
    ),

    # DeepSeek: 需要 "deepseek/" 前缀用于 LiteLLM 路由
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        litellm_prefix="deepseek",  # deepseek-chat → deepseek/deepseek-chat
        skip_prefixes=("deepseek/",),  # 避免重复前缀
        env_extras=(),
        is_gateway=False,
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # Gemini: 需要 "gemini/" 前缀用于 LiteLLM 路由
    ProviderSpec(
        name="gemini",
        keywords=("gemini",),
        env_key="GEMINI_API_KEY",
        display_name="Gemini",
        litellm_prefix="gemini",  # gemini-pro → gemini/gemini-pro
        skip_prefixes=("gemini/",),  # 避免重复前缀
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # Zhipu（智谱）: LiteLLM 使用 "zai/" 前缀
    # 同时镜像 Key 到 ZHIPUAI_API_KEY（某些 LiteLLM 路径检查该变量）
    # skip_prefixes: 当已经通过网关路由时，不再添加 "zai/"
    ProviderSpec(
        name="zhipu",
        keywords=("zhipu", "glm", "zai"),
        env_key="ZAI_API_KEY",
        display_name="Zhipu AI",
        litellm_prefix="zai",  # glm-4 → zai/glm-4
        skip_prefixes=("zhipu/", "zai/", "openrouter/", "hosted_vllm/"),
        env_extras=(("ZHIPUAI_API_KEY", "{api_key}"),),  # 镜像 API Key
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # DashScope（阿里云）: Qwen 模型，需要 "dashscope/" 前缀
    ProviderSpec(
        name="dashscope",
        keywords=("qwen", "dashscope"),
        env_key="DASHSCOPE_API_KEY",
        display_name="DashScope",
        litellm_prefix="dashscope",  # qwen-max → dashscope/qwen-max
        skip_prefixes=("dashscope/", "openrouter/"),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # Moonshot（月之暗面）: Kimi 模型，需要 "moonshot/" 前缀
    # LiteLLM 需要 MOONSHOT_API_BASE 环境变量来找到端点
    # Kimi K2.5 API 强制 temperature >= 1.0
    ProviderSpec(
        name="moonshot",
        keywords=("moonshot", "kimi"),
        env_key="MOONSHOT_API_KEY",
        display_name="Moonshot",
        litellm_prefix="moonshot",  # kimi-k2.5 → moonshot/kimi-k2.5
        skip_prefixes=("moonshot/", "openrouter/"),
        env_extras=(("MOONSHOT_API_BASE", "{api_base}"),),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="https://api.moonshot.ai/v1",  # 国际版；中国区使用 api.moonshot.cn
        strip_model_prefix=False,
        model_overrides=(("kimi-k2.5", {"temperature": 1.0}),),  # Kimi K2.5 强制 temperature=1.0
    ),

    # MiniMax（迷你万）: 需要 "minimax/" 前缀用于 LiteLLM 路由
    # 使用 OpenAI 兼容 API，端点为 api.minimax.io/v1
    ProviderSpec(
        name="minimax",
        keywords=("minimax",),
        env_key="MINIMAX_API_KEY",
        display_name="MiniMax",
        litellm_prefix="minimax",  # MiniMax-M2.1 → minimax/MiniMax-M2.1
        skip_prefixes=("minimax/", "openrouter/"),
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="https://api.minimax.io/v1",
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # === 本地部署（通过配置 key 匹配，而非 api_base）========================
    # vLLM / 任何 OpenAI 兼容的本地服务器
    # 当配置 key 为 "vllm" 时检测（provider_name="vllm"）
    ProviderSpec(
        name="vllm",
        keywords=("vllm",),
        env_key="HOSTED_VLLM_API_KEY",
        display_name="vLLM/Local",
        litellm_prefix="hosted_vllm",  # Llama-3-8B → hosted_vllm/Llama-3-8B
        skip_prefixes=(),
        env_extras=(),
        is_gateway=False,
        is_local=True,  # 本地部署
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",  # 用户必须在配置中提供
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # === Ollama（本地，OpenAI 兼容）========================================
    ProviderSpec(
        name="ollama",
        keywords=("ollama", "nemotron"),
        env_key="OLLAMA_API_KEY",
        display_name="Ollama",
        litellm_prefix="ollama_chat",  # model → ollama_chat/model
        skip_prefixes=("ollama/", "ollama_chat/"),
        env_extras=(),
        is_gateway=False,
        is_local=True,  # 本地部署
        detect_by_key_prefix="",
        detect_by_base_keyword="11434",  # 默认端口 11434
        default_api_base="http://localhost:11434",
        strip_model_prefix=False,
        model_overrides=(),
    ),

    # === 辅助（不是主要的 LLM 提供商）=====================================
    # Groq: 主要用于 Whisper 语音转录，也可用于 LLM
    # 需要 "groq/" 前缀用于 LiteLLM 路由
    # 排在最后 —— 很少在 fallback 中胜出
    ProviderSpec(
        name="groq",
        keywords=("groq",),
        env_key="GROQ_API_KEY",
        display_name="Groq",
        litellm_prefix="groq",  # llama3-8b-8192 → groq/llama3-8b-8192
        skip_prefixes=("groq/",),  # 避免重复前缀
        env_extras=(),
        is_gateway=False,
        is_local=False,
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        default_api_base="",
        strip_model_prefix=False,
        model_overrides=(),
    ),
)


# ---------------------------------------------------------------------------
# 查找辅助函数
# ---------------------------------------------------------------------------


def find_by_model(model: str) -> ProviderSpec | None:
    """
    通过模型名称关键词匹配标准提供商（不区分大小写）。

    跳过网关型和本地部署 —— 它们通过 api_key/api_base 匹配。

    匹配逻辑：
    --------
    1. 首先检查显式前缀（如 "github-copilot/..."）
       - 防止 `github-copilot/...codex` 错误匹配到 openai_codex

    2. 然后检查关键词匹配
       - 支持两种形式：原始模型名和连字符转下划线的变体
       - 例如："claude-3" 和 "claude_3" 都能匹配到 Anthropic

    Args:
        model: 模型名称，如 "claude-3-5-sonnet"、"gpt-4"

    Returns:
        ProviderSpec | None: 匹配的提供商规格，无匹配返回 None

    示例：
        >>> find_by_model("claude-3-5-sonnet")
        ProviderSpec(name="anthropic", ...)
        >>> find_by_model("qwen-max")
        ProviderSpec(name="dashscope", ...)
    """
    model_lower = model.lower()
    model_normalized = model_lower.replace("-", "_")  # 连字符转下划线
    # 提取模型前缀（如 "github-copilot/model" → "github-copilot"）
    model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
    normalized_prefix = model_prefix.replace("-", "_")
    # 只考虑标准提供商（排除网关和本地）
    std_specs = [s for s in PROVIDERS if not s.is_gateway and not s.is_local]

    # 优先匹配显式前缀
    for spec in std_specs:
        if model_prefix and normalized_prefix == spec.name:
            return spec

    # 关键词匹配
    for spec in std_specs:
        if any(
            kw in model_lower or kw.replace("-", "_") in model_normalized for kw in spec.keywords
        ):
            return spec
    return None


def find_gateway(
    provider_name: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
) -> ProviderSpec | None:
    """
    检测网关型/本地部署提供商。

    检测优先级：
    ---------
    1. provider_name — 如果配置 key 直接映射到网关/本地规格，直接使用
       例如：provider_name="openrouter" → OpenRouter

    2. api_key 前缀 — 例如："sk-or-" → OpenRouter
       通过 detect_by_key_prefix 字段匹配

    3. api_base 关键词 — 例如：URL 包含 "aihubmix" → AiHubMix
       通过 detect_by_base_keyword 字段匹配

    重要说明：
    --------
    使用自定义 api_base 的标准提供商（如通过代理的 DeepSeek）
    不会被误判为 vLLM —— 旧的 fallback 逻辑已移除。

    Args:
        provider_name: 配置中的提供商名称（如 "openrouter"）
        api_key: API 密钥
        api_base: API 基础 URL

    Returns:
        ProviderSpec | None: 匹配的网关/本地提供商，无匹配返回 None

    示例：
        >>> find_gateway(provider_name="vllm")
        ProviderSpec(name="vllm", is_local=True, ...)
        >>> find_gateway(api_key="sk-or-123456")
        ProviderSpec(name="openrouter", is_gateway=True, ...)
    """
    # 1. 通过配置 key 直接匹配
    if provider_name:
        spec = find_by_name(provider_name)
        if spec and (spec.is_gateway or spec.is_local):
            return spec

    # 2. 通过 api_key 前缀/api_base 关键词自动检测
    for spec in PROVIDERS:
        if spec.detect_by_key_prefix and api_key and api_key.startswith(spec.detect_by_key_prefix):
            return spec
        if spec.detect_by_base_keyword and api_base and spec.detect_by_base_keyword in api_base:
            return spec

    return None


def find_by_name(name: str) -> ProviderSpec | None:
    """
    通过配置字段名称查找提供商规格。

    Args:
        name: 配置字段名称，如 "dashscope"、"openai"

    Returns:
        ProviderSpec | None: 匹配的提供商规格，无匹配返回 None

    示例：
        >>> find_by_name("dashscope")
        ProviderSpec(name="dashscope", display_name="DashScope", ...)
    """
    for spec in PROVIDERS:
        if spec.name == name:
            return spec
    return None

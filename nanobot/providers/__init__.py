# =============================================================================
# nanobot LLM 提供商模块入口
# 文件路径：nanobot/providers/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这是 nanobot LLM（大语言模型）提供商模块的入口文件。
#
# 什么是 LLM Provider？
# ------------------
# LLM Provider 是连接不同 AI 模型的"适配器"。
# nanobot 支持多种 AI 模型提供商，每个提供商有自己的 API 接口。
#
# 支持的提供商：
# ------------
# 1. LiteLLMProvider: 通过 LiteLLM 支持 100+ 种模型
#    - OpenAI (GPT-4, GPT-3.5)
#    - Anthropic (Claude)
#    - Google (Gemini)
#    - 月之暗面 (Kimi)
#    - DeepSeek
#    - Groq
#    - 等...
#
# 2. OpenAICodexProvider: OpenAI Codex 专用
#    使用 OAuth 认证，连接 ChatGPT Codex API
#
# 3. AzureOpenAIProvider: Azure OpenAI 专用
#    微软 Azure 云上的 OpenAI 服务
#
# 4. CustomProvider: 自定义 OpenAI 兼容服务
#    用于连接任何 OpenAI 兼容的 API 端点
#
# 为什么需要多个 Provider？
# ----------------------
# 不同提供商的 API 接口不同：
# - 请求格式不同
# - 认证方式不同（API Key、OAuth、Azure AD）
# - 响应格式不同
# - 特有功能不同（如 Claude 的思考块）
#
# Provider 层统一了这些差异，让上层代码不需要关心具体是哪个提供商。
#
# 使用示例：
# --------
# from nanobot.providers import LLMProvider, LiteLLMProvider
#
# # 创建提供商实例
# provider = LiteLLMProvider(
#     api_key="sk-xxx",
#     default_model="openai/gpt-4"
# )
#
# # 调用 LLM
# response = await provider.chat_with_retry(
#     messages=[{"role": "user", "content": "Hello"}]
# )
# print(response.content)
# =============================================================================

"""LLM provider abstraction module."""
# LLM 提供商抽象模块：统一不同 AI 模型的接口

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.openai_codex_provider import OpenAICodexProvider
from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

__all__ = ["LLMProvider", "LLMResponse", "LiteLLMProvider", "OpenAICodexProvider", "AzureOpenAIProvider"]

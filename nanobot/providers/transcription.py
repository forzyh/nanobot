# =============================================================================
# nanobot Groq 语音转文本提供商
# 文件路径：nanobot/providers/transcription.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 GroqTranscriptionProvider 类，用于通过 Groq 的 Whisper API
# 将语音消息转换为文本。
#
# 什么是 Groq Transcription？
# -------------------------
# Groq 提供了一个超快的 Whisper 语音转文本服务：
# - 使用 whisper-large-v3 模型
# - 支持多种语言（包括中文）
# - 免费额度充足
# - 速度极快（利用 Groq 的 LPU 加速）
#
# 为什么需要语音转文本？
# -------------------
# nanobot 支持多个聊天平台（Telegram、WhatsApp 等），
# 这些平台允许用户发送语音消息。为了理解语音内容，
# 需要将语音转换为文本，然后交给 LLM 处理。
#
# 使用示例：
# --------
# >>> provider = GroqTranscriptionProvider(api_key="gsk_...")
# >>> text = await provider.transcribe("/tmp/voice.ogg")
# >>> print(text)
# "你好，我想查询今天的天气"
# =============================================================================

"""Voice transcription provider using Groq."""
# 使用 Groq 的语音转文本提供商

import os  # 操作系统接口
from pathlib import Path  # 路径处理

import httpx  # 异步 HTTP 客户端
from loguru import logger  # 日志库


class GroqTranscriptionProvider:
    """
    使用 Groq Whisper API 的语音转文本提供商。

    Groq 提供极快的转录速度（利用 LPU 加速），
    并且有慷慨的免费额度。

    API 端点：
    --------
    https://api.groq.com/openai/v1/audio/transcriptions

    使用的模型：
    ---------
    whisper-large-v3 - OpenAI 的开源语音识别模型
    - 支持 100+ 种语言
    - 高准确率
    - 支持背景噪音处理

    属性说明：
    --------
    api_key: str | None
        Groq API 密钥
        优先使用传入的 api_key，否则从环境变量 GROQ_API_KEY 读取

    api_url: str
        Groq 转录 API 端点 URL

    使用示例：
    --------
    >>> provider = GroqTranscriptionProvider(api_key="gsk_xxx")
    >>> text = await provider.transcribe("voice_message.ogg")
    >>> print(f"转录结果：{text}")
    """

    def __init__(self, api_key: str | None = None):
        """
        初始化 Groq 转文本提供商。

        Args:
            api_key: Groq API 密钥（可选）
                如果不提供，会从环境变量 GROQ_API_KEY 读取
        """
        # 优先使用传入的 API Key，否则从环境变量读取
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        # Groq 转录 API 端点
        self.api_url = "https://api.groq.com/openai/v1/audio/transcriptions"

    async def transcribe(self, file_path: str | Path) -> str:
        """
        使用 Groq 转录音频文件。

        这个方法将音频文件发送到 Groq API，
        返回转录的文本结果。

        Args:
            file_path: 音频文件路径
                支持常见的音频格式（ogg、wav、mp3 等）
                可以是 str 或 Path 类型

        Returns:
            str: 转录的文本内容
                失败时返回空字符串（不会抛出异常）

        转录流程：
        --------
        1. 检查 API Key 是否配置
        2. 检查文件是否存在
        3. 构建 multipart/form-data 请求
        4. 发送 POST 请求到 Groq API
        5. 解析 JSON 响应，提取 text 字段

        错误处理：
        --------
        - API Key 未配置：记录警告，返回空字符串
        - 文件不存在：记录错误，返回空字符串
        - HTTP 错误：记录错误，返回空字符串
        - 其他异常：记录错误，返回空字符串

        这种"静默失败"的设计是因为语音转文本是辅助功能，
        失败不应影响主要功能。

        示例：
        -----
        >>> provider = GroqTranscriptionProvider(api_key="gsk_xxx")
        >>> text = await provider.transcribe("/tmp/voice.ogg")
        >>> if text:
        ...     print(f"转录成功：{text}")
        ... else:
        ...     print("转录失败")
        """
        # 检查 API Key 是否配置
        if not self.api_key:
            logger.warning("Groq API key not configured for transcription")
            return ""

        path = Path(file_path)
        # 检查文件是否存在
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        try:
            # 使用 httpx 异步客户端发送请求
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    # 构建 multipart/form-data 请求
                    files = {
                        # 音频文件（使用原始文件名）
                        "file": (path.name, f),
                        # 使用的模型
                        "model": (None, "whisper-large-v3"),
                    }
                    headers = {
                        # 认证头
                        "Authorization": f"Bearer {self.api_key}",
                    }

                    # 发送 POST 请求
                    response = await client.post(
                        self.api_url,
                        headers=headers,
                        files=files,
                        timeout=60.0  # 60 秒超时（音频文件可能较大）
                    )

                    # 检查 HTTP 状态码
                    response.raise_for_status()
                    # 解析 JSON 响应
                    data = response.json()
                    # 提取转录文本
                    return data.get("text", "")

        except Exception as e:
            # 记录错误并返回空字符串（静默失败）
            logger.error("Groq transcription error: {}", e)
            return ""

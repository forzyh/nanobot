# =============================================================================
# nanobot 工具辅助函数
# 文件路径：nanobot/utils/helpers.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件提供了 nanobot 运行时用到的各种辅助函数。
#
# 包含的工具函数：
# -------------
# 1. detect_image_mime() - 从魔数检测图片 MIME 类型
# 2. ensure_dir() - 确保目录存在
# 3. timestamp() - 获取当前 ISO 时间戳
# 4. safe_filename() - 生成安全的文件名
# 5. split_message() - 分割长消息
# 6. build_assistant_message() - 构建助手消息
# 7. estimate_prompt_tokens() - 估算 prompt token 数
# 8. estimate_message_tokens() - 估算单条消息 token 数
# 9. estimate_prompt_tokens_chain() - 链式估算（支持回退）
# 10. sync_workspace_templates() - 同步工作空间模板
#
# 为什么需要辅助函数？
# -----------------
# 将通用的、可复用的逻辑提取为独立函数：
# 1. 避免重复代码
# 2. 便于测试
# 3. 提高可读性
# =============================================================================

"""Utility functions for nanobot."""
# nanobot 的工具辅助函数

import json  # JSON 处理
import re  # 正则表达式
from datetime import datetime  # 时间处理
from pathlib import Path  # 路径处理
from typing import Any  # 任意类型

import tiktoken  # token 估算库


def detect_image_mime(data: bytes) -> str | None:
    """
    从魔数（magic bytes）检测图片 MIME 类型，忽略文件扩展名。

    什么是魔数？
    ----------
    魔数是文件开头的几个字节，用于标识文件类型。
    相比文件扩展名，魔数更可靠（不会被欺骗）。

    支持的图片类型：
    ------------
    - PNG:  89 50 4E 47 0D 0A 1A 0A (\\x89PNG\\r\\n\\x1a\\n)
    - JPEG: FF D8 FF
    - GIF:  47 49 46 38 37 61 或 47 49 46 38 39 61 (GIF87a/GIF89a)
    - WEBP: RIFF....WEBP

    Args:
        data: 文件的原始字节（通常读取前 8-12 字节即可）

    Returns:
        str | None: MIME 类型，如 "image/png"，无法识别返回 None

    示例：
        >>> with open("test.png", "rb") as f:
        ...     data = f.read(8)
        >>> detect_image_mime(data)
        'image/png'
    """
    # PNG 魔数
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    # JPEG 魔数
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    # GIF 魔数（87a 和 89a 两种）
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    # WEBP 魔数（RIFF 容器 + WEBP 标识）
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # 无法识别
    return None


def ensure_dir(path: Path) -> Path:
    """
    确保目录存在，如果不存在则创建。

    这是一个便捷函数，封装了 mkdir 的常用模式。

    Args:
        path: 目录路径

    Returns:
        Path: 同一个路径对象（便于链式调用）

    参数说明：
    --------
    parents=True: 递归创建所有父目录
      例如：/a/b/c 不存在时，会先创建/a、/a/b、再创建/a/b/c

    exist_ok=True: 如果目录已存在，不报错
      这样多次调用 ensure_dir 是安全的

    示例：
        >>> ensure_dir(Path("/tmp/test"))
        PosixPath('/tmp/test')
        >>> ensure_dir(Path("~/.nanobot")).expanduser()
        PosixPath('/home/user/.nanobot')
    """
    # 创建目录（包括父目录，存在时不报错）
    path.mkdir(parents=True, exist_ok=True)
    return path


def timestamp() -> str:
    """
    获取当前 ISO 格式时间戳。

    Returns:
        str: ISO 8601 格式的时间字符串

    示例：
        >>> timestamp()
        '2024-01-15T10:30:45.123456'

    用途：
    ----
    - 消息时间戳
    - 日志时间戳
    - 文件命名（避免重复）
    """
    return datetime.now().isoformat()


# 匹配不安全文件名字符的正则表达式
# 这些字符在文件系统中可能有特殊含义或导致问题
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')

def safe_filename(name: str) -> str:
    """
    将不安全的文件名字符替换为下划线。

    为什么需要这个函数？
    -----------------
    不同操作系统对文件名有不同的限制：
    - Windows: 不允许 <>:"/\\|?*
    - macOS: 不允许 :/
    - Linux: 只不允许/和空字符

    这个函数将所有不安全字符替换为下划线，
    确保文件名在所有平台都安全。

    Args:
        name: 原始名称（如会话密钥 "cli:direct"）

    Returns:
        str: 安全的文件名

    示例：
        >>> safe_filename("cli:direct")
        'cli_direct'
        >>> safe_filename('test<1>"2"/3')
        'test_1__2__3'
    """
    # 替换不安全字符并去除首尾空白
    return _UNSAFE_CHARS.sub("_", name).strip()


def split_message(content: str, max_len: int = 2000) -> list[str]:
    """
    将内容分割为多个块，每块不超过 max_len。

    为什么要分割消息？
    --------------
    某些平台（如 Discord）有消息长度限制：
    - Discord: 2000 字符
    - Telegram: 4096 字符
    - WhatsApp: 65536 字符

    这个函数确保消息不超过限制。

    分割策略（优先级从高到低）：
    ------------------------
    1. 在换行符处分割（保持段落完整）
    2. 在空格处分割（保持单词完整）
    3. 强制分割（超过 max_len 则硬拆分）

    Args:
        content: 要分割的文本内容
        max_len: 每块的最大长度（默认 2000，Discord 兼容）

    Returns:
        list[str]: 分割后的消息块列表

    示例：
        >>> split_message("Hello\\nWorld", max_len=10)
        ['Hello', 'World']
    """
    # 空内容返回空列表
    if not content:
        return []
    # 不超过限制直接返回
    if len(content) <= max_len:
        return [content]

    chunks: list[str] = []
    while content:
        # 剩余内容不超过限制，直接添加
        if len(content) <= max_len:
            chunks.append(content)
            break

        # 尝试在合适的位置分割
        cut = content[:max_len]
        # 优先找换行符
        pos = cut.rfind('\n')
        if pos <= 0:
            # 其次找空格
            pos = cut.rfind(' ')
        if pos <= 0:
            # 都没有则强制在 max_len 处分割
            pos = max_len

        # 添加当前块
        chunks.append(content[:pos])
        # 继续处理剩余内容（跳过开头的空白）
        content = content[pos:].lstrip()

    return chunks


def build_assistant_message(
    content: str | None,
    tool_calls: list[dict[str, Any]] | None = None,
    reasoning_content: str | None = None,
    thinking_blocks: list[dict] | None = None,
) -> dict[str, Any]:
    """
    构建提供商安全的助手消息，包含可选的推理字段。

    助手消息是 LLM 的回复，可能包含：
    - 文本内容（content）
    - 工具调用（tool_calls）
    - 推理内容（reasoning_content，某些模型特有）
    - 思考块（thinking_blocks，Anthropic 特有）

    Args:
        content: 助手回复文本（可能为 None）
        tool_calls: 工具调用列表（可选）
        reasoning_content: 推理内容（可选）
        thinking_blocks: 思考块列表（可选）

    Returns:
        dict[str, Any]: 格式化的助手消息字典

    返回格式：
    --------
    {
        "role": "assistant",
        "content": "好的，我来帮你...",
        "tool_calls": [...],  # 可选
        "reasoning_content": "让我想想...",  # 可选
        "thinking_blocks": [...]  # 可选
    }
    """
    # 基础消息
    msg: dict[str, Any] = {"role": "assistant", "content": content}
    # 添加工具调用
    if tool_calls:
        msg["tool_calls"] = tool_calls
    # 添加推理内容
    if reasoning_content is not None:
        msg["reasoning_content"] = reasoning_content
    # 添加思考块
    if thinking_blocks:
        msg["thinking_blocks"] = thinking_blocks
    return msg


def estimate_prompt_tokens(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """
    使用 tiktoken 估算 prompt 的 token 数。

    什么是 token？
    -----------
    Token 是 LLM 处理文本的基本单位。
    - 英文：约 4 个字符 = 1 token，或 0.75 个单词 = 1 token
    - 中文：约 1.5 个汉字 = 1 token

    为什么要估算？
    -----------
    1. 防止超出上下文窗口限制
    2. 预估 API 调用成本
    3. 决定是否需要压缩/截断

    Args:
        messages: 消息列表
        tools: 工具定义列表（可选，也会消耗 token）

    Returns:
        int: 估算的 token 数，失败返回 0

    估算方法：
    --------
    1. 提取所有文本内容
    2. 添加工具定义（如果有）
    3. 使用 cl100k_base 编码（GPT-4/3.5 使用）
    4. 计算编码后的长度
    """
    try:
        # 获取 cl100k_base 编码器（GPT-4/3.5 使用）
        enc = tiktoken.get_encoding("cl100k_base")
        parts: list[str] = []
        # 遍历所有消息
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, str):
                # 纯文本直接添加
                parts.append(content)
            elif isinstance(content, list):
                # 多模态内容，提取文本块
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        txt = part.get("text", "")
                        if txt:
                            parts.append(txt)
        # 添加工具定义
        if tools:
            parts.append(json.dumps(tools, ensure_ascii=False))
        # 计算总 token 数
        return len(enc.encode("\n".join(parts)))
    except Exception:
        # 失败返回 0
        return 0


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """
    估算单条持久化消息贡献的 prompt token 数。

    这个方法用于计算会话历史中每条消息的 token 消耗，
    帮助决定哪些消息需要被归档。

    Args:
        message: 消息字典
            包含 role, content, tool_calls 等字段

    Returns:
        int: 估算的 token 数（至少为 1）

    考虑的因素：
    ----------
    1. 文本内容（包括多模态中的文本块）
    2. 工具调用（tool_calls）
    3. 工具调用 ID（tool_call_id）
    4. 名称（name）
    """
    content = message.get("content")
    parts: list[str] = []

    # 处理内容
    if isinstance(content, str):
        # 纯文本
        parts.append(content)
    elif isinstance(content, list):
        # 多模态内容
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    parts.append(text)
            else:
                # 非文本块转为 JSON（如图片）
                parts.append(json.dumps(part, ensure_ascii=False))
    elif content is not None:
        # 其他类型转 JSON
        parts.append(json.dumps(content, ensure_ascii=False))

    # 添加元数据字段
    for key in ("name", "tool_call_id"):
        value = message.get(key)
        if isinstance(value, str) and value:
            parts.append(value)

    # 添加工具调用
    if message.get("tool_calls"):
        parts.append(json.dumps(message["tool_calls"], ensure_ascii=False))

    # 合并所有内容
    payload = "\n".join(parts)
    if not payload:
        return 1  # 空消息也至少算 1 token

    try:
        enc = tiktoken.get_encoding("cl100k_base")
        return max(1, len(enc.encode(payload)))
    except Exception:
        # 回退估算（4 字符≈1 token）
        return max(1, len(payload) // 4)


def estimate_prompt_tokens_chain(
    provider: Any,
    model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> tuple[int, str]:
    """
    通过提供商计数器优先，然后 tiktoken 回退，估算 prompt token 数。

    为什么需要链式估算？
    ----------------
    不同提供商可能有自己的 token 计算方式：
    - Anthropic: 使用自己的计数器
    - OpenAI: 提供官方 API
    - 其他：可能使用 tiktoken

    链式策略：
    --------
    1. 先尝试提供商的 estimate_prompt_tokens 方法
    2. 如果失败或返回 0，回退到 tiktoken
    3. 如果都失败，返回 0

    Args:
        provider: LLM 提供商实例
        model: 模型名称
        messages: 消息列表
        tools: 工具定义列表

    Returns:
        tuple[int, str]: (token 数，估算方法来源)
        来源可能值："provider_counter"、"tiktoken"、"none"
    """
    # 尝试获取提供商的计数器方法
    provider_counter = getattr(provider, "estimate_prompt_tokens", None)
    if callable(provider_counter):
        try:
            # 调用提供商计数器
            tokens, source = provider_counter(messages, tools, model)
            if isinstance(tokens, (int, float)) and tokens > 0:
                return int(tokens), str(source or "provider_counter")
        except Exception:
            # 失败继续回退
            pass

    # 回退到 tiktoken
    estimated = estimate_prompt_tokens(messages, tools)
    if estimated > 0:
        return int(estimated), "tiktoken"

    # 全部失败
    return 0, "none"


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """
    同步内置模板到工作空间，只创建缺失的文件。

    这个函数用于初始化新工作空间，将 nanobot 内置的
    模板文件复制到用户工作空间。

    模板文件包括：
    ------------
    - AGENTS.md: Agent 行为指南
    - SOUL.md: Agent 个性设定
    - USER.md: 用户偏好
    - TOOLS.md: 工具使用说明
    - memory/MEMORY.md: 长期记忆文件
    - memory/HISTORY.md: 历史日志文件
    - skills/: 技能目录

    Args:
        workspace: 工作空间路径
        silent: 是否静默模式（不输出日志）

    Returns:
        list[str]: 新创建的文件路径列表
    """
    # 导入资源文件函数
    from importlib.resources import files as pkg_files
    try:
        # 获取 nanobot.templates 包路径
        tpl = pkg_files("nanobot") / "templates"
    except Exception:
        # 导入失败返回空列表
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []  # 记录新创建的文件

    def _write(src, dest: Path):
        """辅助函数：如果目标不存在则写入。"""
        if dest.exists():
            return  # 已存在，跳过
        # 确保父目录存在
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 写入内容（源文件可能不存在）
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    # 复制所有.md 模板文件
    for item in tpl.iterdir():
        if item.name.endswith(".md") and not item.name.startswith("."):
            _write(item, workspace / item.name)

    # 创建记忆文件
    _write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md")
    _write(None, workspace / "memory" / "HISTORY.md")  # 空文件

    # 创建技能目录
    (workspace / "skills").mkdir(exist_ok=True)

    # 输出日志（非静默模式）
    if added and not silent:
        from rich.console import Console
        for name in added:
            Console().print(f"  [dim]Created {name}[/dim]")

    return added

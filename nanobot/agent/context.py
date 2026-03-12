# =============================================================================
# nanobot 上下文构建器
# 文件路径：nanobot/agent/context.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 ContextBuilder 类，负责为 LLM 调用构建完整的上下文。
#
# 什么是上下文（Context）？
# ---------------------
# 上下文是 LLM 调用时需要的所有信息，包括：
# 1. 系统提示（System Prompt）- AI 的身份和行为准则
# 2. 历史消息 - 之前的对话记录
# 3. 当前用户消息 - 本次需要处理的问题
# 4. 运行时上下文 - 时间、渠道等元数据
# 5. 媒体内容 - 图片等多模态输入
#
# 为什么需要 ContextBuilder？
# -------------------------
# LLM 本身没有记忆，每次调用都需要"重新介绍背景"。
# ContextBuilder 负责组装这些信息，确保 AI 理解：
# - 它是谁（nanobot 身份）
# - 在哪运行（工作空间、平台）
# - 之前聊了什么（历史）
# - 用户现在要什么（当前消息）
#
# 消息格式示例：
# ------------
# [
#   {"role": "system", "content": "你是 nanobot..."},
#   {"role": "user", "content": "你好"},
#   {"role": "assistant", "content": "你好！有什么可以帮你的？"},
#   {"role": "user", "content": "[运行时上下文] 请帮我写个文件"},
# ]
# =============================================================================

"""Context builder for assembling agent prompts."""
# 上下文构建器：组装 Agent 提示

import base64  # Base64 编码（用于图片）
import mimetypes  # MIME 类型检测
import platform  # 平台信息
import time  # 时间处理
from datetime import datetime  # 日期时间
from pathlib import Path  # 路径处理
from typing import Any  # 任意类型

from nanobot.agent.memory import MemoryStore  # 记忆存储
from nanobot.agent.skills import SkillsLoader  # 技能加载器
from nanobot.utils.helpers import build_assistant_message, detect_image_mime  # 辅助函数


# =============================================================================
# ContextBuilder - 上下文构建器
# =============================================================================

class ContextBuilder:
    """
    为 Agent 构建上下文（系统提示 + 消息列表）。

    ContextBuilder 的作用是将各种信息组装成 LLM 能理解的格式。

    构建流程：
    --------
    1. 加载身份定义（_get_identity）
    2. 加载引导文件（AGENTS.md, SOUL.md 等）
    3. 加载记忆上下文
    4. 加载技能列表
    5. 合并为系统提示
    6. 添加历史消息
    7. 添加当前用户消息（含运行时上下文）

    属性说明：
    --------
    workspace: Path
        工作空间路径
        用于加载引导文件、记忆、技能等

    memory: MemoryStore
        记忆存储实例
        负责加载长期记忆

    skills: SkillsLoader
        技能加载器实例
        负责加载技能定义

    类常量：
    --------
    BOOTSTRAP_FILES: list[str]
        引导文件列表
        这些文件在工作空间根目录定义 Agent 行为

    _RUNTIME_CONTEXT_TAG: str
        运行时上下文标签
        用于标记元数据块，避免被误认为指令
    """

    # 引导文件列表
    # 这些文件在工作空间根目录，定义 Agent 的行为和知识
    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    # 运行时上下文标签
    # 用于标记元数据块，LLM 知道这部分不是指令
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(self, workspace: Path):
        """
        初始化上下文构建器。

        Args:
            workspace: 工作空间路径
        """
        self.workspace = workspace  # 工作空间
        # 记忆存储：加载长期记忆
        self.memory = MemoryStore(workspace)
        # 技能加载器：加载技能定义
        self.skills = SkillsLoader(workspace)

    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        """
        从身份、引导文件、记忆和技能构建系统提示。

        系统提示（System Prompt）是 LLM 的"人格设定"，
        告诉 AI 它是谁、应该怎么做。

        系统提示结构：
        ------------
        1. Identity（身份）- 核心身份定义
        2. Bootstrap Files（引导文件）- 用户自定义规则
        3. Memory（记忆）- 长期记忆
        4. Active Skills（活跃技能）- 总是可用的技能
        5. Skills Summary（技能摘要）- 可选技能列表

        Args:
            skill_names: 技能名称列表（可选）
                用于过滤只显示特定技能

        Returns:
            str: 完整的系统提示

        示例：
            >>> builder.build_system_prompt()
            "# nanobot 🐈\n\n你是 nanobot, 一个 helpful AI 助手...\n\n---\n\n## AGENTS.md\n\n..."
        """
        # 各部分收集到列表
        parts = [self._get_identity()]  # 身份定义

        # 加载引导文件
        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        # 加载记忆
        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        # 加载常驻技能（always=True 的技能）
        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        # 技能摘要（所有可用技能）
        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        # 用分隔符连接各部分
        return "\n\n---\n\n".join(parts)

    def _get_identity(self) -> str:
        """
        获取核心身份定义部分。

        身份定义包含：
        1. 基本信息（nanobot 身份）
        2. 运行时环境（操作系统、Python 版本）
        3. 工作空间路径
        4. 平台策略（Windows/POSIX 差异）
        5. 行为准则

        Returns:
            str: 身份定义文本
        """
        # 解析工作空间路径
        workspace_path = str(self.workspace.expanduser().resolve())
        # 获取系统信息
        system = platform.system()
        # 运行时描述
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        # 平台策略
        platform_policy = ""
        if system == "Windows":
            # Windows 平台策略
            # Windows 没有 GNU 工具（grep, sed, awk），需要使用 Windows 原生命令
            platform_policy = """## Platform Policy (Windows)
- You are running on Windows. Do not assume `grep`, `sed`, or `awk` exist.
- Prefer Windows-native commands or file tools when they are more reliable.
- If terminal output is garbled, retry with UTF-8 output enabled.
"""
        else:
            # POSIX 平台策略（Linux/macOS）
            # 支持标准 Unix 工具
            platform_policy = """## Platform Policy (POSIX)
- You are running on a POSIX system. Prefer UTF-8 and standard shell tools.
- Use file tools when they are simpler or more reliable than shell commands.
"""

        # 返回完整的身份定义
        return f"""# nanobot 🐈

You are nanobot, a helpful AI assistant.

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md (write important facts here)
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable). Each entry starts with [YYYY-MM-DD HH:MM].
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

{platform_policy}

## nanobot Guidelines
- State intent before tool calls, but NEVER predict or claim results before receiving them.
- Before modifying a file, read it first. Do not assume files or directories exist.
- After writing or editing a file, re-read it if accuracy matters.
- If a tool call fails, analyze the error before retrying with a different approach.
- Ask for clarification when the request is ambiguous.

Reply directly with text for conversations. Only use the 'message' tool to send to a specific chat channel."""

    @staticmethod
    def _build_runtime_context(channel: str | None, chat_id: str | None) -> str:
        """
        构建不可信的运行时元数据块，用于注入到用户消息前。

        运行时上下文包含：
        - 当前时间（日期 + 时区）
        - 渠道信息（来源）
        - 聊天 ID（哪个对话）

        为什么叫"不可信"？
        ---------------
        因为这是元数据，不是用户指令。
        LLM 应该参考这些信息，但不应该将其作为指令执行。

        Args:
            channel: 渠道名称（如 telegram, discord）
            chat_id: 聊天 ID

        Returns:
            str: 运行时上下文文本

        示例：
            >>> ContextBuilder._build_runtime_context("telegram", "123456")
            '[Runtime Context — metadata only, not instructions]\nCurrent Time: 2024-01-01 12:00 (Monday) (CST)\nChannel: telegram\nChat ID: 123456'
        """
        # 当前时间格式化
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        # 时区
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        # 添加渠道和聊天 ID
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        # 拼接并添加标签前缀
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n".join(lines)

    def _load_bootstrap_files(self) -> str:
        """
        从工作空间加载所有引导文件。

        引导文件（Bootstrap Files）是用户自定义的 Agent 行为规则。
        这些文件在工作空间根目录，LLM 会在每次调用时读取。

        引导文件说明：
        ------------
        - AGENTS.md: Agent 行为规范和编码风格
        - SOUL.md: Agent 的"灵魂"设定（个性、偏好）
        - USER.md: 用户偏好和使用习惯
        - TOOLS.md: 工具使用说明和限制

        Returns:
            str: 所有引导文件内容（用## 分隔）

        示例：
            >>> builder._load_bootstrap_files()
            '## AGENTS.md\n\n# Agent Guidelines\n...'
        """
        parts = []

        # 遍历每个引导文件
        for filename in self.BOOTSTRAP_FILES:
            file_path = self.workspace / filename
            # 如果文件存在，读取内容
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                parts.append(f"## {filename}\n\n{content}")

        # 用空行连接所有文件
        return "\n\n".join(parts) if parts else ""

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        构建完整的消息列表用于 LLM 调用。

        这是 ContextBuilder 的核心方法，将：
        1. 系统提示
        2. 历史消息
        3. 当前用户消息（含运行时上下文和媒体）

        合并为 LLM API 所需的格式。

        Args:
            history: 历史消息列表
                格式：[{"role": "user", "content": "Hello"}, ...]

            current_message: 当前用户消息文本

            skill_names: 技能名称列表（可选）
                传递给系统提示

            media: 媒体文件路径列表（可选）
                如图片路径

            channel: 渠道名称（可选）

            chat_id: 聊天 ID（可选）

        Returns:
            list[dict[str, Any]]: 完整的消息列表

        消息结构：
        --------
        [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "历史消息 1"},
            {"role": "assistant", "content": "历史消息 2"},
            ...,
            {"role": "user", "content": "运行时上下文 + 当前消息"},
        ]

        注意：
        ----
        运行时上下文与用户内容合并为单条 user 消息，
        避免出现连续的同角色消息（某些提供商会拒绝）。
        """
        # 构建运行时上下文
        runtime_ctx = self._build_runtime_context(channel, chat_id)
        # 构建用户消息内容（含媒体）
        user_content = self._build_user_content(current_message, media)

        # 合并运行时上下文和用户内容
        # 如果是纯文本，直接拼接
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            # 如果是多模态内容（含图片），运行时上下文作为第一个文本块
            merged = [{"type": "text", "text": runtime_ctx}] + user_content

        # 返回完整消息列表
        return [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *history,  # 展开历史消息
            {"role": "user", "content": merged},  # 当前消息
        ]

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """
        构建用户消息内容，包含可选的 base64 编码图片。

        这个方法处理多模态输入：
        - 纯文本：直接返回
        - 文本 + 图片：返回多模态格式

        图片处理流程：
        ------------
        1. 读取图片文件为字节
        2. 从魔数（magic bytes）检测真实 MIME 类型
        3. Base64 编码
        4. 格式化为 data URI

        Args:
            text: 用户消息文本

            media: 媒体文件路径列表（可选）
                如 ["/path/to/image.jpg", ...]

        Returns:
            str | list[dict[str, Any]]:
                - 纯文本：返回字符串
                - 含图片：返回多模态列表

        多模态格式示例：
        --------------
        [
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,/9j/4AAQSk..."}},
            {"type": "text", "text": "这张图片展示了什么？"},
        ]
        """
        # 如果没有媒体，直接返回文本
        if not media:
            return text

        # 收集有效图片
        images = []
        for path in media:
            p = Path(path)
            # 跳过不存在的文件
            if not p.is_file():
                continue
            # 读取文件字节
            raw = p.read_bytes()
            # 从魔数检测真实 MIME 类型（比文件扩展名可靠）
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            # 跳过非图片文件
            if not mime or not mime.startswith("image/"):
                continue
            # Base64 编码
            b64 = base64.b64encode(raw).decode()
            # 格式化为 data URI
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        # 如果没有有效图片，返回文本
        if not images:
            return text
        # 返回多模态内容：图片 + 文本
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: str,
    ) -> list[dict[str, Any]]:
        """
        将工具结果添加到消息列表。

        当 LLM 调用工具后，需要将执行结果反馈给 LLM。
        这个方法创建一条 "tool" 角色的消息。

        Args:
            messages: 当前消息列表

            tool_call_id: 工具调用 ID
                与 tool_call 的 id 匹配，用于关联

            tool_name: 工具名称
                如 "web_search", "read_file"

            result: 工具执行结果
                字符串格式

        Returns:
            list[dict[str, Any]]: 添加结果后的消息列表

        工具结果格式：
        ------------
        {
            "role": "tool",
            "tool_call_id": "call_123",
            "name": "web_search",
            "content": "搜索结果...",
        }
        """
        # 添加工具结果消息
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages

    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """
        将助手消息添加到消息列表。

        助手消息是 LLM 的回复，可能包含：
        - 文本内容（content）
        - 工具调用（tool_calls）
        - 推理内容（reasoning_content，某些模型特有）
        - 思考块（thinking_blocks，Anthropic 特有）

        Args:
            messages: 当前消息列表

            content: 助手回复文本
                如 "好的，我来帮你..."
                可能为 None（如果只调用工具）

            tool_calls: 工具调用列表（可选）
                OpenAI 格式的 tool_call 字典

            reasoning_content: 推理内容（可选）
                某些模型（如 Kimi、DeepSeek-R1）的思考过程

            thinking_blocks: 思考块列表（可选）
                Anthropic 模型的"Extended Thinking"功能

        Returns:
            list[dict[str, Any]]: 添加助手消息后的列表

        助手消息格式：
        ------------
        {
            "role": "assistant",
            "content": "好的，我来帮你...",
            "tool_calls": [...],  # 可选
            "reasoning_content": "让我想想...",  # 可选
        }
        """
        # 使用辅助函数构建助手消息
        messages.append(build_assistant_message(
            content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        ))
        return messages

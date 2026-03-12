# =============================================================================
# nanobot 记忆系统
# 文件路径：nanobot/agent/memory.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 nanobot 的记忆系统，包括两个核心类：
# 1. MemoryStore - 记忆存储（两层记忆：长期记忆 + 历史日志）
# 2. MemoryConsolidator - 记忆巩固器（负责将短期记忆转化为长期记忆）
#
# 什么是记忆系统？
# --------------
# LLM 本身没有长期记忆，每次对话都是"失忆"的。
# 记忆系统的作用是：
# 1. 长期记忆（MEMORY.md）- 存储重要事实和用户偏好
# 2. 历史日志（HISTORY.md）- 可 grep 搜索的对话摘要
#
# 记忆巩固流程：
# ------------
# 用户对话 → 短期记忆（会话历史） → [LLM  consolidation] → 长期记忆
#
# 为什么需要记忆巩固？
# -----------------
# 1. 上下文窗口有限：不能无限存储所有对话
# 2. 成本优化：压缩旧对话减少 token 消耗
# 3. 个性化：记住用户偏好和历史决策
# 4. 可搜索：HISTORY.md 支持 grep 快速检索
#
# 触发条件：
# --------
# - Token 阈值：当会话 prompt 超过 context_window_tokens/2 时
# - 手动触发：用户执行 /new 命令时
# =============================================================================

"""Memory system for persistent agent memory."""
# 记忆系统：持久化 Agent 记忆

from __future__ import annotations  # 启用未来版本的类型注解

import asyncio  # 异步编程
import json  # JSON 处理
import weakref  # 弱引用（用于缓存）
from pathlib import Path  # 路径处理
from typing import TYPE_CHECKING, Any, Callable  # 类型注解

from loguru import logger  # 日志库

from nanobot.utils.helpers import ensure_dir, estimate_message_tokens, estimate_prompt_tokens_chain  # 辅助函数

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider  # LLM 提供商
    from nanobot.session.manager import Session, SessionManager  # 会话管理


# =============================================================================
# save_memory 工具定义
# =============================================================================

# save_memory 工具的定义（用于 LLM 调用）
# 这个工具让 LLM 能够将记忆巩固结果保存到持久化存储
_SAVE_MEMORY_TOOL = [
    {
        "type": "function",  # 工具类型：函数调用
        "function": {
            "name": "save_memory",  # 工具名称
            "description": "Save the memory consolidation result to persistent storage.",  # 工具描述
            "parameters": {  # 参数定义（JSON Schema）
                "type": "object",
                "properties": {
                    "history_entry": {
                        "type": "string",
                        "description": "A paragraph summarizing key events/decisions/topics. "
                        "Start with [YYYY-MM-DD HH:MM]. Include detail useful for grep search.",  # 历史条目：对话摘要
                    },
                    "memory_update": {
                        "type": "string",
                        "description": "Full updated long-term memory as markdown. Include all existing "
                        "facts plus new ones. Return unchanged if nothing new.",  # 记忆更新：完整的长期记忆
                    },
                },
                "required": ["history_entry", "memory_update"],  # 必填参数
            },
        },
    }
]


# =============================================================================
# 辅助函数
# =============================================================================

def _ensure_text(value: Any) -> str:
    """
    将工具调用负载值标准化为文本，用于文件存储。

    LLM 返回的参数可能是任意类型（字符串、数字、列表等），
    这个方法确保最终存储的是文本格式。

    Args:
        value: 任意类型的值

    Returns:
        str: 文本格式的字符串

    示例：
        >>> _ensure_text("hello")
        'hello'
        >>> _ensure_text({"key": "value"})
        '{"key": "value"}'
    """
    # 如果已经是字符串，直接返回
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _normalize_save_memory_args(args: Any) -> dict[str, Any] | None:
    """
    将提供商的工具调用参数标准化为预期的字典格式。

    不同 LLM 提供商返回的参数格式可能不同：
    - 有些返回字符串（需要 JSON 解析）
    - 有些返回列表（第一个元素是参数）
    - 有些返回字典（直接使用）

    Args:
        args: 原始参数（可能是 str/list/dict）

    Returns:
        dict[str, Any] | None: 标准化后的字典，或 None（如果格式错误）

    示例：
        >>> _normalize_save_memory_args('{"history_entry": "..."}')
        {'history_entry': '...'}
        >>> _normalize_save_memory_args([{"history_entry": "..."}])
        {'history_entry': '...'}
    """
    # 如果是字符串，JSON 解析
    if isinstance(args, str):
        args = json.loads(args)
    # 如果是列表，取第一个元素
    if isinstance(args, list):
        return args[0] if args and isinstance(args[0], dict) else None
    # 如果是字典，直接返回
    return args if isinstance(args, dict) else None


# =============================================================================
# MemoryStore - 记忆存储
# =============================================================================

class MemoryStore:
    """
    两层记忆系统：
    1. MEMORY.md - 长期记忆（持久化事实）
    2. HISTORY.md - 历史日志（可 grep 搜索的摘要）

    为什么需要两层记忆？
    -----------------
    1. 长期记忆：
       - 存储用户偏好、项目信息、重要决策
       - 类似人类的"长期记忆"
       - 文件：memory/MEMORY.md

    2. 历史日志：
       - 按时间顺序记录对话摘要
       - 支持 grep 快速搜索
       - 类似人类的"日记"
       - 文件：memory/HISTORY.md

    属性说明：
    --------
    memory_dir: Path
        记忆目录（workspace/memory/）

    memory_file: Path
        长期记忆文件（MEMORY.md）

    history_file: Path
        历史日志文件（HISTORY.md）
    """

    def __init__(self, workspace: Path):
        """
        初始化记忆存储。

        Args:
            workspace: 工作空间路径
        """
        # 确保记忆目录存在
        self.memory_dir = ensure_dir(workspace / "memory")
        # 记忆文件路径
        self.memory_file = self.memory_dir / "MEMORY.md"
        # 历史文件路径
        self.history_file = self.memory_dir / "HISTORY.md"

    def read_long_term(self) -> str:
        """
        读取长期记忆。

        Returns:
            str: MEMORY.md 的内容，如果文件不存在返回空字符串
        """
        # 如果文件存在，读取内容
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def write_long_term(self, content: str) -> None:
        """
        写入长期记忆。

        Args:
            content: 要写入的记忆内容（Markdown 格式）
        """
        # 覆盖写入
        self.memory_file.write_text(content, encoding="utf-8")

    def append_history(self, entry: str) -> None:
        """
        追加历史条目。

        Args:
            entry: 历史条目文本
                格式：[YYYY-MM-DD HH:MM] 摘要内容
        """
        # 以追加模式打开文件
        with open(self.history_file, "a", encoding="utf-8") as f:
            # 写入条目（去除末尾空白，添加两个换行分隔）
            f.write(entry.rstrip() + "\n\n")

    def get_memory_context(self) -> str:
        """
        获取记忆上下文，用于注入系统提示。

        Returns:
            str: 格式化后的记忆上下文，如果没有记忆返回空字符串

        示例：
            >>> store.get_memory_context()
            '## Long-term Memory\n用户偏好使用 TypeScript...\n'
        """
        # 读取长期记忆
        long_term = self.read_long_term()
        # 如果有内容，格式化返回
        return f"## Long-term Memory\n{long_term}" if long_term else ""

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        """
        将消息列表格式化为文本，用于记忆巩固。

        这个方法将结构化的消息列表转换为可读的文本格式，
        方便 LLM 理解和总结。

        Args:
            messages: 消息列表
                格式：[{"role": "user", "content": "...", "timestamp": "...", "tools_used": [...]}, ...]

        Returns:
            str: 格式化后的文本

        输出格式示例：
        ------------
        [2024-01-01 12:00] USER: 帮我写个文件
        [2024-01-01 12:01] ASSISTANT [tools: write_file]: 好的...
        """
        lines = []
        for message in messages:
            # 跳过没有内容的消息
            if not message.get("content"):
                continue
            # 格式化使用的工具列表
            tools = f" [tools: {', '.join(message['tools_used'])}]" if message.get("tools_used") else ""
            # 格式化单条消息
            lines.append(
                f"[{message.get('timestamp', '?')[:16]}] {message['role'].upper()}{tools}: {message['content']}"
            )
        return "\n".join(lines)

    async def consolidate(
        self,
        messages: list[dict],
        provider: LLMProvider,
        model: str,
    ) -> bool:
        """
        将提供的消息块巩固到 MEMORY.md 和 HISTORY.md。

        记忆巩固流程：
        ------------
        1. 读取当前长期记忆
        2. 构建提示（当前记忆 + 对话内容）
        3. 调用 LLM，要求调用 save_memory 工具
        4. LLM 返回总结的历史条目和更新后的记忆
        5. 写入文件

        Args:
            messages: 要巩固的消息列表
            provider: LLM 提供商实例
            model: 模型名称

        Returns:
            bool: True 表示成功，False 表示失败

        示例：
            >>> await store.consolidate(messages, provider, "gpt-4")
            True
        """
        # 空消息列表直接返回
        if not messages:
            return True

        # 读取当前长期记忆
        current_memory = self.read_long_term()
        # 构建提示词
        prompt = f"""Process this conversation and call the save_memory tool with your consolidation.

## Current Long-term Memory
{current_memory or "(empty)"}

## Conversation to Process
{self._format_messages(messages)}"""

        try:
            # 调用 LLM，强制要求使用工具
            response = await provider.chat_with_retry(
                messages=[
                    {"role": "system", "content": "You are a memory consolidation agent. Call the save_memory tool with your consolidation of the conversation."},
                    {"role": "user", "content": prompt},
                ],
                tools=_SAVE_MEMORY_TOOL,
                model=model,
                tool_choice="required",  # 强制使用工具
            )

            # 如果 LLM 没有调用工具，记录警告
            if not response.has_tool_calls:
                logger.warning("Memory consolidation: LLM did not call save_memory, skipping")
                return False

            # 标准化参数
            args = _normalize_save_memory_args(response.tool_calls[0].arguments)
            if args is None:
                logger.warning("Memory consolidation: unexpected save_memory arguments")
                return False

            # 写入历史条目
            if entry := args.get("history_entry"):
                self.append_history(_ensure_text(entry))
            # 更新长期记忆
            if update := args.get("memory_update"):
                update = _ensure_text(update)
                # 只有内容变化时才写入
                if update != current_memory:
                    self.write_long_term(update)

            # 记录成功日志
            logger.info("Memory consolidation done for {} messages", len(messages))
            return True
        except Exception:
            # 记录异常日志
            logger.exception("Memory consolidation failed")
            return False


# =============================================================================
# MemoryConsolidator - 记忆巩固器
# =============================================================================

class MemoryConsolidator:
    """
    负责记忆巩固的策略、锁和会话偏移更新。

    MemoryConsolidator 是 MemoryStore 的"智能层"，负责：
    1. 决定何时进行记忆巩固（基于 token 数量）
    2. 选择合适的消息边界（在用户消息处切分）
    3. 并发控制（每会话一把锁）
    4. 更新会话状态（last_consolidated 偏移）

    为什么需要独立的 Consolidator？
    -----------------------------
    - MemoryStore 负责"存储"（读写文件）
    - MemoryConsolidator 负责"策略"（何时巩固、巩固多少）

    属性说明：
    --------
    store: MemoryStore
        底层记忆存储

    provider: LLMProvider
        LLM 提供商实例

    model: str
        用于记忆巩固的模型

    sessions: SessionManager
        会话管理器

    context_window_tokens: int
        上下文窗口大小（token 数）

    _build_messages: Callable
        构建消息上下文的函数

    _get_tool_definitions: Callable
        获取工具定义的函数

    _locks: WeakValueDictionary
        每会话的异步锁缓存
    """

    # 最大记忆巩固轮次数
    # 防止无限循环（每次巩固一部分，直到低于目标）
    _MAX_CONSOLIDATION_ROUNDS = 5

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        sessions: SessionManager,
        context_window_tokens: int,
        build_messages: Callable[..., list[dict[str, Any]]],
        get_tool_definitions: Callable[[], list[dict[str, Any]]],
    ):
        """
        初始化记忆巩固器。

        Args:
            workspace: 工作空间路径
            provider: LLM 提供商
            model: 模型名称
            sessions: 会话管理器
            context_window_tokens: 上下文窗口 token 数
            build_messages: 构建消息上下文的函数
            get_tool_definitions: 获取工具定义的函数
        """
        # 创建记忆存储
        self.store = MemoryStore(workspace)
        # LLM 提供商
        self.provider = provider
        # 模型名称
        self.model = model
        # 会话管理器
        self.sessions = sessions
        # 上下文窗口
        self.context_window_tokens = context_window_tokens
        # 构建消息的函数（从 ContextBuilder 注入）
        self._build_messages = build_messages
        # 获取工具定义的函数（从 ToolRegistry 注入）
        self._get_tool_definitions = get_tool_definitions
        # 每会话锁缓存（弱引用，避免内存泄漏）
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()

    def get_lock(self, session_key: str) -> asyncio.Lock:
        """
        获取指定会话的共享巩固锁。

        为什么需要锁？
        -----------
        防止同一会话并发进行记忆巩固，导致：
        - 文件写入冲突
        - last_consolidated 偏移错乱

        为什么用 WeakValueDictionary？
        ---------------------------
        弱引用字典会在锁不再被使用时自动回收，
        避免内存泄漏。

        Args:
            session_key: 会话密钥

        Returns:
            asyncio.Lock: 会话专属的异步锁
        """
        # 如果锁不存在则创建，否则返回已存在的
        return self._locks.setdefault(session_key, asyncio.Lock())

    async def consolidate_messages(self, messages: list[dict[str, object]]) -> bool:
        """
        归档选定的消息块到持久化记忆。

        这是一个便捷方法，直接调用 MemoryStore.consolidate。

        Args:
            messages: 要巩固的消息列表

        Returns:
            bool: 是否成功
        """
        return await self.store.consolidate(messages, self.provider, self.model)

    def pick_consolidation_boundary(
        self,
        session: Session,
        tokens_to_remove: int,
    ) -> tuple[int, int] | None:
        """
        选择一个用户消息边界，移除足够的旧 prompt token。

        为什么需要找边界？
        ----------------
        不能随意截断消息列表，因为：
        - 必须在完整的"用户 - 助手"回合处切分
        - 避免切断工具调用的连续性

        切分策略：
        --------
        从 last_consolidated 开始累加 token，
        当达到目标数量时，返回最后一个用户消息位置。

        Args:
            session: 会话对象
            tokens_to_remove: 需要移除的 token 数

        Returns:
            tuple[int, int] | None: (边界索引，已移除 token 数)，如果无法切分返回 None
        """
        # 从上次巩固位置开始
        start = session.last_consolidated
        # 如果已超出范围或不需要移除 token，返回 None
        if start >= len(session.messages) or tokens_to_remove <= 0:
            return None

        removed_tokens = 0  # 已移除 token 计数
        last_boundary: tuple[int, int] | None = None  # 最后一个有效边界
        # 遍历消息
        for idx in range(start, len(session.messages)):
            message = session.messages[idx]
            # 在用户消息处记录边界（回合开始）
            if idx > start and message.get("role") == "user":
                last_boundary = (idx, removed_tokens)
                # 如果已达到目标，返回
                if removed_tokens >= tokens_to_remove:
                    return last_boundary
            # 累加 token
            removed_tokens += estimate_message_tokens(message)

        # 返回最后一个边界（可能不足但最接近）
        return last_boundary

    def estimate_session_prompt_tokens(self, session: Session) -> tuple[int, str]:
        """
        估算当前会话历史视图的 prompt 大小。

        这个方法构建完整的 prompt（系统提示 + 历史 + 当前消息），
        然后使用链式估算方法计算 token 数。

        Args:
            session: 会话对象

        Returns:
            tuple[int, str]: (token 数，估算方法来源)

        示例：
            >>> tokens, source = consolidator.estimate_session_prompt_tokens(session)
            >>> print(f"Prompt size: {tokens} tokens ({source})")
        """
        # 获取会话历史
        history = session.get_history(max_messages=0)
        # 解析渠道和聊天 ID
        channel, chat_id = (session.key.split(":", 1) if ":" in session.key else (None, None))
        # 构建完整的消息列表（含系统提示）
        probe_messages = self._build_messages(
            history=history,
            current_message="[token-probe]",  # 占位符
            channel=channel,
            chat_id=chat_id,
        )
        # 估算 token 数
        return estimate_prompt_tokens_chain(
            self.provider,
            self.model,
            probe_messages,
            self._get_tool_definitions(),
        )

    async def archive_unconsolidated(self, session: Session) -> bool:
        """
        为 /new 风格的会话轮换归档未巩固的完整尾部。

        当用户执行 /new 命令时，需要将之前未巩固的记忆全部归档，
        避免丢失重要信息。

        Args:
            session: 会话对象

        Returns:
            bool: 是否成功
        """
        # 获取会话锁
        lock = self.get_lock(session.key)
        async with lock:
            # 快照未巩固的消息
            snapshot = session.messages[session.last_consolidated:]
            # 如果没有未巩固消息，直接返回
            if not snapshot:
                return True
            # 巩固这些消息
            return await self.consolidate_messages(snapshot)

    async def maybe_consolidate_by_tokens(self, session: Session) -> None:
        """
        循环：归档旧消息，直到 prompt 适应上下文窗口的一半。

        这是记忆巩固的主入口方法，在以下时机调用：
        1. 每次处理用户消息前
        2. /new 命令后

        巩固策略：
        --------
        - 目标阈值：context_window_tokens / 2
        - 原因：预留足够空间给工具调用和多轮对话
        - 多轮巩固：每次巩固一部分，可能需要多轮

        Args:
            session: 会话对象
        """
        # 空会话或禁用 token 限制时跳过
        if not session.messages or self.context_window_tokens <= 0:
            return

        # 获取会话锁
        lock = self.get_lock(session.key)
        async with lock:
            # 目标阈值（上下文窗口的一半）
            target = self.context_window_tokens // 2
            # 估算当前 prompt 大小
            estimated, source = self.estimate_session_prompt_tokens(session)
            # 估算失败跳过
            if estimated <= 0:
                return
            # 如果已经低于阈值，无需巩固
            if estimated < self.context_window_tokens:
                logger.debug(
                    "Token consolidation idle {}: {}/{} via {}",
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                )
                return

            # 多轮巩固循环
            for round_num in range(self._MAX_CONSOLIDATION_ROUNDS):
                # 如果已低于目标，退出
                if estimated <= target:
                    return

                # 选择切分边界
                boundary = self.pick_consolidation_boundary(session, max(1, estimated - target))
                # 如果无法找到边界，退出
                if boundary is None:
                    logger.debug(
                        "Token consolidation: no safe boundary for {} (round {})",
                        session.key,
                        round_num,
                    )
                    return

                # 边界索引
                end_idx = boundary[0]
                # 要巩固的消息块
                chunk = session.messages[session.last_consolidated:end_idx]
                # 空块退出
                if not chunk:
                    return

                # 记录日志
                logger.info(
                    "Token consolidation round {} for {}: {}/{} via {}, chunk={} msgs",
                    round_num,
                    session.key,
                    estimated,
                    self.context_window_tokens,
                    source,
                    len(chunk),
                )
                # 执行巩固
                if not await self.consolidate_messages(chunk):
                    return
                # 更新偏移
                session.last_consolidated = end_idx
                # 保存会话
                self.sessions.save(session)

                # 重新估算
                estimated, source = self.estimate_session_prompt_tokens(session)
                # 估算失败退出
                if estimated <= 0:
                    return

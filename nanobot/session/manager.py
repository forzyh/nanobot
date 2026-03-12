# =============================================================================
# nanobot 会话管理器
# 文件路径：nanobot/session/manager.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了会话管理功能，包括：
# 1. Session 数据类 - 表示一个会话
# 2. SessionManager 类 - 管理所有会话
#
# 什么是会话（Session）？
# -----------------
# 会话是用户与 Agent 之间的一次完整对话。
# 例如：
# - 用户在 Telegram 中给机器人发消息 → 创建一个会话
# - 用户在 CLI 中与 Agent 交互 → 创建一个会话
# - 每个会话有独立的对话历史
#
# 为什么需要会话管理？
# -----------------
# 1. 上下文保持：LLM 需要知道之前的对话内容
# 2. 多用户支持：不同用户的对话互不干扰
# 3. 持久化：对话历史保存到磁盘，重启后不丢失
# 4. 记忆巩固：将旧对话归档到 MEMORY.md/HISTORY.md
#
# 会话存储格式：JSONL
# ---------------
# JSONL（JSON Lines）是一种每行一个 JSON 对象的格式。
# 例如 sessions/cli_direct.jsonl：
#
# {"_type": "metadata", "key": "cli:direct", "created_at": "...", ...}
# {"role": "user", "content": "Hello", "timestamp": "..."}
# {"role": "assistant", "content": "Hi!", "timestamp": "..."}
#
# 相比 JSON 的优势：
# - 追加写入无需读取整个文件
# - 易于流式读取
# - 损坏风险低（单行损坏不影响其他行）
# =============================================================================

"""Session management for conversation history."""
# 会话管理：对话历史记录

import json  # JSON 处理
import shutil  # 文件操作（用于迁移旧会话）
from dataclasses import dataclass, field  # 数据类
from datetime import datetime  # 时间处理
from pathlib import Path  # 路径处理
from typing import Any  # 任意类型

from loguru import logger  # 日志库

from nanobot.config.paths import get_legacy_sessions_dir  # 获取旧版会话目录
from nanobot.utils.helpers import ensure_dir, safe_filename  # 辅助函数


# =============================================================================
# Session - 会话数据类
# =============================================================================

@dataclass
class Session:
    """
    会话数据类。

    存储对话历史的会话。

    重要特性：
    --------
    消息是"追加式"的（append-only），这是为了 LLM 缓存效率。
    记忆巩固过程会将摘要写入 MEMORY.md/HISTORY.md，
    但不会修改 messages 列表或 get_history() 的输出。

    为什么需要追加式？
    ---------------
    1. 性能：追加比修改快得多
    2. LLM 缓存：某些 LLM API 会缓存消息列表，修改会失效
    3. 简单：无需处理复杂的索引更新

    属性说明：
    --------
    key: str
        会话唯一标识
        格式："channel:chat_id"
        例如："telegram:123456"、"cli:direct"

    messages: list[dict[str, Any]]
        消息历史列表
        每个消息是一个字典，包含：
        - role: "user" | "assistant" | "tool"
        - content: 消息内容
        - timestamp: 时间戳
        - tool_calls: 工具调用（可选）
        - tool_call_id: 工具调用 ID（可选）

    created_at: datetime
        会话创建时间

    updated_at: datetime
        最后更新时间

    metadata: dict[str, Any]
        元数据（可选）
        可存储任意附加信息

    last_consolidated: int
        已巩固的消息数量
        用于追踪哪些消息已归档到 MEMORY.md/HISTORY.md
        例如：last_consolidated=10 表示前 10 条消息已归档
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # 已巩固的消息数量

    def add_message(self, role: str, content: str, **kwargs: Any) -> None:
        """
        添加消息到会话。

        Args:
            role: 消息角色
                - "user": 用户消息
                - "assistant": 助手回复
                - "tool": 工具结果

            content: 消息内容

            **kwargs: 其他字段
                如 tool_calls, tool_call_id, name 等

        示例：
            >>> session.add_message("user", "Hello")
            >>> session.add_message("assistant", "Hi!", tools_used=["search"])
        """
        # 构建消息字典
        msg = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            **kwargs  # 合并其他字段
        }
        # 追加到列表
        self.messages.append(msg)
        # 更新时间
        self.updated_at = datetime.now()

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """
        返回未巩固的消息用于 LLM 输入，对齐到用户回合。

        这个方法的作用是：
        1. 获取未巩固的消息（last_consolidated 之后）
        2. 限制最大消息数（避免超出上下文窗口）
        3. 删除开头非用户消息（避免孤立的 tool_result）
        4. 简化消息格式（只保留必要字段）

        Args:
            max_messages: 最大消息数
                默认 500，防止过多

        Returns:
            list[dict[str, Any]]: 简化后的消息列表

        为什么需要删除开头非用户消息？
        ---------------------------
        如果开头是 tool 消息，LLM 会困惑（没有对应的 tool_call）。
        删除它们可以避免"孤儿"tool_result 块。
        """
        # 获取未巩固的消息
        unconsolidated = self.messages[self.last_consolidated:]
        # 限制数量
        sliced = unconsolidated[-max_messages:]

        # 删除开头非用户消息
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]  # 从第一个 user 消息开始
                break

        # 简化消息格式
        out: list[dict[str, Any]] = []
        for m in sliced:
            # 只保留必要字段
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            # 添加工具相关字段（如果有）
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out

    def clear(self) -> None:
        """
        清空会话的所有消息并重置状态。

        使用场景：
        - 用户执行 /new 命令，开始新对话
        - 测试需要干净的状态
        """
        self.messages = []  # 清空消息
        self.last_consolidated = 0  # 重置巩固计数
        self.updated_at = datetime.now()  # 更新时间


# =============================================================================
# SessionManager - 会话管理器
# =============================================================================

class SessionManager:
    """
    管理会话的生命周期。

    核心职责：
    1. 创建/获取会话（get_or_create）
    2. 保存会话到磁盘（save）
    3. 从磁盘加载会话（_load）
    4. 列出所有会话（list_sessions）
    5. 迁移旧版会话（从~/.nanobot/sessions/）

    会话存储：
    --------
    会话以 JSONL 文件形式存储在 sessions 目录中。
    例如：
    - sessions/cli_direct.jsonl
    - sessions/telegram_123456.jsonl
    """

    def __init__(self, workspace: Path):
        """
        初始化会话管理器。

        Args:
            workspace: 工作空间路径
        """
        self.workspace = workspace
        # 会话目录：{workspace}/sessions/
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        # 旧版会话目录：~/.nanobot/sessions/
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        # 内存缓存：key -> Session
        # 避免每次都从磁盘读取
        self._cache: dict[str, Session] = {}

    def _get_session_path(self, key: str) -> Path:
        """
        获取会话文件路径。

        Args:
            key: 会话密钥（如 "cli:direct"）

        Returns:
            Path: 会话文件路径

        路径生成规则：
        1. 将":"替换为"_"（文件系统不支持冒号）
        2. 使用 safe_filename 确保文件名安全
        3. 添加.jsonl 扩展名

        示例：
            >>> manager._get_session_path("cli:direct")
            Path('/workspace/sessions/cli_direct.jsonl')
        """
        # 安全处理 key
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        """
        获取旧版全局会话路径。

        这是 nanobot 早期版本使用的路径：~/.nanobot/sessions/
        保留这个方法是为了支持从旧版本迁移。

        Args:
            key: 会话密钥

        Returns:
            Path: 旧版会话路径
        """
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        """
        获取现有会话或创建新会话。

        这是最常用的方法，流程：
        1. 检查缓存
        2. 如果缓存没有，从磁盘加载
        3. 如果磁盘也没有，创建新会话
        4. 放入缓存并返回

        Args:
            key: 会话密钥（通常是 channel:chat_id）

        Returns:
            Session: 会话对象

        示例：
            >>> session = manager.get_or_create("telegram:123456")
            >>> session.add_message("user", "Hello")
        """
        # 先检查缓存
        if key in self._cache:
            return self._cache[key]

        # 从磁盘加载
        session = self._load(key)
        if session is None:
            # 不存在则创建新的
            session = Session(key=key)

        # 放入缓存
        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """
        从磁盘加载会话。

        加载流程：
        1. 检查新路径是否存在
        2. 如果不存在，检查旧路径（迁移）
        3. 读取 JSONL 文件
        4. 解析元数据和消息
        5. 返回 Session 对象

        Args:
            key: 会话密钥

        Returns:
            Session | None: 加载的会话，失败返回 None
        """
        # 获取路径
        path = self._get_session_path(key)
        # 检查是否存在
        if not path.exists():
            # 检查旧路径
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    # 迁移到新路径
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)

        # 文件不存在返回 None
        if not path.exists():
            return None

        try:
            messages = []  # 消息列表
            metadata = {}  # 元数据
            created_at = None  # 创建时间
            last_consolidated = 0  # 已巩固计数

            # 读取 JSONL 文件
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    # 元数据行
                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        # 消息行
                        messages.append(data)

            # 返回 Session 对象
            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            # 加载失败记录警告
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    def save(self, session: Session) -> None:
        """
        保存会话到磁盘。

        保存格式（JSONL）：
        ---------------
        第 1 行：元数据
        {"_type": "metadata", "key": "...", "created_at": "...", ...}

        第 2 行起：消息
        {"role": "user", "content": "Hello", "timestamp": "..."}
        {"role": "assistant", "content": "Hi!", "timestamp": "..."}

        Args:
            session: 要保存的会话对象
        """
        # 获取路径
        path = self._get_session_path(session.key)

        # 写入 JSONL 文件
        with open(path, "w", encoding="utf-8") as f:
            # 写入元数据行
            metadata_line = {
                "_type": "metadata",
                "key": session.key,
                "created_at": session.created_at.isoformat(),
                "updated_at": session.updated_at.isoformat(),
                "metadata": session.metadata,
                "last_consolidated": session.last_consolidated
            }
            f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
            # 写入消息行
            for msg in session.messages:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        # 更新缓存
        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        """
        从内存缓存中移除会话。

        使用场景：
        - 用户执行 /new 命令后
        - 需要强制重新加载会话时

        Args:
            key: 会话密钥
        """
        self._cache.pop(key, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        列出所有会话。

        Returns:
            list[dict[str, Any]]: 会话信息列表
                每个元素包含：key, created_at, updated_at, path

        实现细节：
        --------
        只读取每个文件的第一行（元数据），
        无需读取整个文件，提高效率。
        """
        sessions = []

        # 遍历所有.jsonl 文件
        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                # 只读取第一行（元数据）
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            # 解析 key（兼容旧格式）
                            key = data.get("key") or path.stem.replace("_", ":", 1)
                            sessions.append({
                                "key": key,
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "path": str(path)
                            })
            except Exception:
                # 读取失败跳过
                continue

        # 按更新时间排序（最新的在前）
        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)

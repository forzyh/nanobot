# =============================================================================
# nanobot Spawn 工具
# 文件路径：nanobot/agent/tools/spawn.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 SpawnTool，让 Agent 能够创建后台子 Agent 执行任务。
#
# 什么是 SpawnTool？
# ----------------
# SpawnTool 是一个 Agent 工具，用于：
# 1. 创建后台子 Agent 处理复杂任务
# 2. 子 Agent 独立运行，不阻塞主 Agent
# 3. 任务完成后向用户汇报结果
#
# 使用场景：
# ---------
# 1. 长时间任务：代码重构、文件搜索、批量处理
# 2. 独立任务：可以并行处理的任务
# 3. 复杂任务：需要多步骤完成的任务
#
# 子 Agent 特性：
# ------------
# 1. 继承上下文：继承主 Agent 的渠道、聊天 ID、会话密钥
# 2. 独立工具集：拥有自己的工具实例
# 3. 结果汇报：任务完成后通过消息通知用户
#
# 使用示例：
# --------
# # 创建子 Agent 执行代码重构
# {"task": "重构 user_service.py 中的认证逻辑"}
#
# # 带标签的子 Agent
# {"task": "分析日志文件", "label": "日志分析"}
# =============================================================================

"""Spawn tool for creating background subagents."""
# 用于创建后台子 Agent 的 Spawn 工具

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """
    用于创建后台子 Agent 的工具。

    这个工具让 Agent 能够：
    1. spawn 子 Agent 处理复杂或耗时的任务
    2. 子 Agent 在后台独立运行
    3. 任务完成后向用户汇报结果

    使用场景：
    --------
    1. 长时间任务：代码重构、文件搜索、批量处理
    2. 独立任务：可以并行处理的任务
    3. 复杂任务：需要多步骤完成的任务

    子 Agent 特性：
    ------------
    1. 继承上下文：继承主 Agent 的渠道、聊天 ID、会话密钥
    2. 独立工具集：拥有自己的工具实例
    3. 结果汇报：任务完成后通过消息通知用户

    属性说明：
    --------
    _manager: SubagentManager
        子 Agent 管理器，负责创建和管理子 Agent

    _origin_channel: str
        原始渠道（如 "telegram"），用于子 Agent 汇报

    _origin_chat_id: str
        原始聊天 ID，用于子 Agent 汇报

    _session_key: str
        会话密钥（格式："{channel}:{chat_id}"），用于会话追踪

    使用示例：
    --------
    >>> from nanobot.agent.subagent import SubagentManager
    >>> manager = SubagentManager(...)
    >>> spawn_tool = SpawnTool(manager)
    >>> spawn_tool.set_context("telegram", "123456")
    >>> result = await spawn_tool.execute(
    ...     task="重构 user_service.py 中的认证逻辑",
    ...     label="代码重构"
    ... )
    >>> print(result)
    "Spawned subagent '代码重构' (id: agent_123)"
    """

    def __init__(self, manager: "SubagentManager"):
        """
        初始化 SpawnTool。

        Args:
            manager: SubagentManager 实例，用于创建子 Agent
        """
        self._manager = manager  # 子 Agent 管理器
        self._origin_channel = "cli"  # 默认原始渠道
        self._origin_chat_id = "direct"  # 默认原始聊天 ID
        self._session_key = "cli:direct"  # 默认会话密钥

    def set_context(self, channel: str, chat_id: str) -> None:
        """
        设置子 Agent 汇报的上下文。

        这个方法在 Agent 循环中被调用，确保子 Agent 知道
        向哪个渠道和聊天 ID 汇报任务结果。

        Args:
            channel: 渠道名称（如 "telegram"）
            chat_id: 聊天 ID
        """
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the subagent to complete",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the task (for display)",
                },
            },
            "required": ["task"],
        }

    async def execute(self, task: str, label: str | None = None, **kwargs: Any) -> str:
        """
        Spawn 一个子 Agent 来执行给定任务。

        Args:
            task: 子 Agent 要完成的任务描述
            label: 可选的短标签，用于显示（如 "日志分析"）
            **kwargs: 其他参数

        Returns:
            str: SubagentManager.spawn() 的返回结果

        执行流程：
        --------
        1. 调用 SubagentManager.spawn() 创建子 Agent
        2. 传入任务描述和标签
        3. 传入 origin_channel/origin_chat_id 用于汇报
        4. 传入 session_key 用于会话追踪

        子 Agent 生命周期：
        ----------------
        1. 创建：SubagentManager 创建新的 AgentLoop 实例
        2. 执行：子 Agent 运行自己的消息循环，处理任务
        3. 汇报：任务完成后，通过原始渠道发送结果
        4. 清理：子 Agent 结束运行，释放资源

        示例：
        -----
        >>> result = await spawn_tool.execute(
        ...     task="分析项目中的 TODO 注释",
        ...     label="TODO 分析"
        ... )
        """
        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            session_key=self._session_key,
        )

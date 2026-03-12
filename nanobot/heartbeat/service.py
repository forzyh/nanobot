# =============================================================================
# nanobot 心跳服务
# 文件路径：nanobot/heartbeat/service.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 HeartbeatService 类，用于定期唤醒 Agent 检查是否有新任务。
#
# 什么是心跳服务？
# ---------------
# 心跳服务是一个定时任务，每隔固定时间（默认 30 分钟）唤醒一次 Agent：
# 1. 读取 HEARTBEAT.md 文件（用户写入待办事项的的地方）
# 2. 让 LLM 决定是否有活跃任务需要处理
# 3. 如果有任务，执行回调函数运行完整 Agent 循环
# 4. 将结果通过通知回调发送给用户
#
# 为什么需要心跳服务？
# -----------------
# 1. 后台任务处理：用户可以在 HEARTBEAT.md 中写入任务，Agent 会自动处理
# 2. 避免轮询：使用 LLM 决策而非简单的文本解析，更可靠
# 3. 工具调用决策：通过虚拟工具调用（heartbeat tool）获得结构化决策
# 4. 灵活调度：用户可以通过修改 HEARTBEAT.md 控制 Agent 行为
#
# 两阶段设计：
# ----------
# Phase 1（决策）：读取 HEARTBEAT.md，让 LLM 通过工具调用决定 skip/run
# Phase 2（执行）：仅当 Phase 1 返回 run 时，执行任务并发送结果
#
# 使用示例：
# --------
# # 用户写入 HEARTBEAT.md
# "帮我检查昨天的日志，看看有没有错误"
#
# # Agent 定时唤醒后
# 1. 读取 HEARTBEAT.md
# 2. LLM 决策：run（有任务）
# 3. 执行：检查日志文件
# 4. 通知：发送结果给用户
# =============================================================================

"""Heartbeat service - periodic agent wake-up to check for tasks."""
# 心跳服务 - 定期唤醒 Agent 检查任务

from __future__ import annotations

import asyncio  # 异步编程
from pathlib import Path  # 路径处理
from typing import TYPE_CHECKING, Any, Callable, Coroutine  # 类型注解

from loguru import logger  # 日志库

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider  # LLM 提供商基类

# 心跳工具定义（OpenAI 格式）
# 用于让 LLM 通过结构化方式返回决策（skip 或 run）
_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],  # skip=无任务，run=有活跃任务
                        "description": "skip = nothing to do, run = has active tasks",
                    },
                    "tasks": {
                        "type": "string",
                        "description": "Natural-language summary of active tasks (required for run)",
                    },
                },
                "required": ["action"],  # action 是必填字段
            },
        },
    }
]


class HeartbeatService:
    """
    定期心跳服务，唤醒 Agent 检查是否有任务。

    这个服务实现了一个两阶段的决策 - 执行流程：

    Phase 1（决策阶段）：
    -----------------
    1. 读取 HEARTBEAT.md 文件
    2. 构建系统 prompt 和用户消息
    3. 调用 LLM（使用虚拟工具调用）
    4. 解析工具调用参数，获取 action 和 tasks
    5. 返回 (action, tasks) 元组

    Phase 2（执行阶段）：
    -----------------
    仅当 Phase 1 返回 action="run" 时触发：
    1. 调用 on_execute 回调，传入任务描述
    2. on_execute 运行完整的 Agent 循环
    3. 获取执行结果
    4. 调用 on_notify 回调发送结果

    属性说明：
    --------
    workspace: Path
        工作空间路径（HEARTBEAT.md 所在目录）

    provider: LLMProvider
        LLM 提供商实例（用于调用 chat_with_retry）

    model: str
        使用的模型名称

    on_execute: Callable[[str], Coroutine[Any, Any, str]] | None
        执行回调函数，接收任务描述，返回执行结果
        通常绑定到 AgentLoop 的处理方法

    on_notify: Callable[[str], Coroutine[Any, Any, None]] | None
        通知回调函数，接收执行结果并发送给用户
        通常绑定到消息发送方法

    interval_s: int
        心跳间隔（秒），默认 30 分钟（1800 秒）

    enabled: bool
        是否启用心跳服务

    _running: bool
        服务运行状态标志

    _task: asyncio.Task | None
        后台运行的任务对象

    使用示例：
    --------
    >>> service = HeartbeatService(
    ...     workspace=Path("/workspace"),
    ...     provider=llm_provider,
    ...     model="claude-3-5-sonnet",
    ...     on_execute=agent_loop.run_task,
    ...     on_notify=send_message,
    ...     interval_s=1800  # 30 分钟
    ... )
    >>> await service.start()  # 启动心跳服务
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,  # 默认 30 分钟
        enabled: bool = True,
    ):
        """
        初始化心跳服务。

        Args:
            workspace: 工作空间路径
            provider: LLM 提供商实例
            model: 使用的模型名称
            on_execute: 执行回调（可选）
                接收任务描述字符串，返回执行结果
            on_notify: 通知回调（可选）
                接收执行结果，负责发送给用户
            interval_s: 心跳间隔（秒），默认 1800 秒（30 分钟）
            enabled: 是否启用心跳服务（默认 True）
        """
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute  # 执行回调
        self.on_notify = on_notify  # 通知回调
        self.interval_s = interval_s  # 心跳间隔
        self.enabled = enabled  # 启用状态
        self._running = False  # 运行标志
        self._task: asyncio.Task | None = None  # 后台任务

    @property
    def heartbeat_file(self) -> Path:
        """
        获取心跳文件路径。

        Returns:
            Path: HEARTBEAT.md 的完整路径
        """
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        """
        读取心跳文件内容。

        Returns:
            str | None: 文件内容，文件不存在或读取失败返回 None
        """
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    async def _decide(self, content: str) -> tuple[str, str]:
        """
        Phase 1：通过虚拟工具调用让 LLM 决定 skip 或 run。

        这个方法构建 LLM 请求，让模型审查 HEARTBEAT.md 内容
        并通过 heartbeat 工具调用返回结构化决策。

        Args:
            content: HEARTBEAT.md 的内容

        Returns:
            tuple[str, str]: (action, tasks)
                action: "skip" 或 "run"
                tasks: 活跃任务的自然语言描述（当 action="run" 时）

        LLM 请求构建：
        -----------
        System prompt: "You are a heartbeat agent..."
        User message: 审查 HEARTBEAT.md 并决定是否有活跃任务

        工具调用解析：
        -----------
        - action: 从工具参数中提取（skip 或 run）
        - tasks: 从工具参数中提取任务描述

        示例：
        -----
        >>> action, tasks = await service._decide("帮我检查日志文件")
        >>> print(action)
        'run'
        >>> print(tasks)
        '检查日志文件中的错误'
        """
        response = await self.provider.chat_with_retry(
            messages=[
                {"role": "system", "content": "You are a heartbeat agent. Call the heartbeat tool to report your decision."},
                {"role": "user", "content": (
                    "Review the following HEARTBEAT.md and decide whether there are active tasks.\n\n"
                    f"{content}"
                )},
            ],
            tools=_HEARTBEAT_TOOL,  # 使用心跳工具定义
            model=self.model,
        )

        # 没有工具调用，默认 skip
        if not response.has_tool_calls:
            return "skip", ""

        # 提取工具调用参数
        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", "")

    async def start(self) -> None:
        """
        启动心跳服务。

        启动流程：
        --------
        1. 检查是否已启用
        2. 检查是否已在运行（避免重复启动）
        3. 设置运行标志
        4. 创建后台任务（运行 _run_loop）
        5. 记录启动日志

        注意：
        ----
        这是一个异步方法，但返回很快（不阻塞等待循环）。
        实际的心跳循环在后台任务中运行。

        示例：
        -----
        >>> await service.start()
        [INFO] Heartbeat started (every 1800s)
        """
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return
        if self._running:
            logger.warning("Heartbeat already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)

    def stop(self) -> None:
        """
        停止心跳服务。

        停止流程：
        --------
        1. 设置运行标志为 False
        2. 取消后台任务
        3. 清空任务引用

        注意：
        ----
        取消任务时，_run_loop 会捕获 CancelledError 并优雅退出。

        示例：
        -----
        >>> service.stop()
        [INFO] Stopping all channels...
        """
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """
        心跳服务主循环。

        这是一个长期运行的异步任务：
        1. 等待间隔时间（interval_s）
        2. 检查是否仍在运行（避免取消后继续）
        3. 执行心跳检查（_tick）
        4. 重复步骤 1-3

        错误处理：
        --------
        - CancelledError: 优雅退出循环
        - 其他异常：记录错误日志，继续下一次循环

        注意：
        ----
        即使某次心跳失败，服务也会继续运行。
        """
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)  # 等待间隔时间
                if self._running:
                    await self._tick()  # 执行心跳检查
            except asyncio.CancelledError:
                break  # 被取消时退出
            except Exception as e:
                logger.error("Heartbeat error: {}", e)  # 记录错误，继续运行

    async def _tick(self) -> None:
        """
        执行单次心跳检查。

        心跳检查流程：
        -----------
        1. 读取 HEARTBEAT.md 文件
        2. 如果文件为空或不存在，跳过
        3. 调用 _decide 让 LLM 决策
        4. 如果 action != "run"，记录日志并返回
        5. 如果 action == "run"：
           - 调用 on_execute 执行任务
           - 调用 on_notify 发送结果

        日志输出：
        --------
        - 文件缺失：DEBUG 级别
        - 无任务：INFO 级别 "Heartbeat: OK"
        - 有任务：INFO 级别 "Heartbeat: tasks found"
        - 完成：INFO 级别 "Heartbeat: completed"
        """
        content = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            return

        logger.info("Heartbeat: checking for tasks...")

        try:
            action, tasks = await self._decide(content)

            if action != "run":
                logger.info("Heartbeat: OK (nothing to report)")
                return

            logger.info("Heartbeat: tasks found, executing...")
            if self.on_execute:
                response = await self.on_execute(tasks)
                if response and self.on_notify:
                    logger.info("Heartbeat: completed, delivering response")
                    await self.on_notify(response)
        except Exception:
            logger.exception("Heartbeat execution failed")

    async def trigger_now(self) -> str | None:
        """
        手动触发一次心跳检查。

        这个方法用于立即执行心跳检查，而不需要等待定时器。
        适用于测试或用户手动触发的场景。

        Returns:
            str | None: 执行结果（如果有），否则返回 None

        使用示例：
        --------
        >>> result = await service.trigger_now()
        >>> if result:
        ...     print("Heartbeat completed:", result)
        """
        content = self._read_heartbeat_file()
        if not content:
            return None
        action, tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None
        return await self.on_execute(tasks)

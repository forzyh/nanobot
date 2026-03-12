# =============================================================================
# nanobot Cron 定时任务工具
# 文件路径：nanobot/agent/tools/cron.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 CronTool，让 Agent 能够创建和管理定时任务。
#
# 什么是 CronTool？
# ---------------
# CronTool 是一个 Agent 工具，用于：
# 1. 添加定时任务（一次性/周期性/Cron 表达式）
# 2. 列出所有任务
# 3. 删除任务
#
# 支持的调度类型：
# -------------
# 1. "at": 一次性执行（指定具体时间）
# 2. "every": 周期性执行（指定间隔秒数）
# 3. "cron": Cron 表达式（如 "0 9 * * *" 每天 9 点）
#
# 使用示例：
# --------
# # 添加一次性提醒
# {"action": "add", "message": "开会", "at": "2026-03-12T10:30:00"}
#
# # 添加周期性任务
# {"action": "add", "message": "喝水", "every_seconds": 3600}
#
# # 添加 Cron 任务
# {"action": "add", "message": "日报", "cron_expr": "0 18 * * *"}
#
# # 列出任务
# {"action": "list"}
#
# # 删除任务
# {"action": "remove", "job_id": "job_123"}
# =============================================================================

"""Cron tool for scheduling reminders and tasks."""
# 用于调度提醒和定时任务的 Cron 工具

from contextvars import ContextVar  # 上下文变量
from typing import Any

from nanobot.agent.tools.base import Tool  # 工具基类
from nanobot.cron.service import CronService  # Cron 服务
from nanobot.cron.types import CronSchedule  # Cron 调度类型


class CronTool(Tool):
    """
    用于调度提醒和周期性任务的工具。

    这个工具让 Agent 能够：
    1. 创建定时任务（提醒、周期性任务等）
    2. 查看已创建的任务列表
    3. 删除任务

    核心特性：
    --------
    1. 支持三种调度类型：
       - at: 一次性执行
       - every: 周期性执行
       - cron: Cron 表达式

    2. 上下文追踪：
       - 使用 contextvars 防止任务中创建新任务（避免无限循环）
       - 追踪 channel/chat_id 用于消息投递

    属性说明：
    --------
    _cron: CronService
        Cron 服务实例，用于实际的调度操作

    _channel: str
        当前会话的渠道（如 "telegram"）

    _chat_id: str
        当前会话的聊天 ID

    _in_cron_context: ContextVar[bool]
        上下文变量，标记是否在任务执行中
        用于防止任务中创建新任务

    使用示例：
    --------
    >>> cron_tool = CronTool(cron_service)
    >>> cron_tool.set_context("telegram", "123456")
    >>> result = await cron_tool.execute(
    ...     action="add",
    ...     message="每天喝水",
    ...     every_seconds=3600
    ... )
    >>> print(result)
    Created job '每天喝水' (id: job_123)
    """

    def __init__(self, cron_service: CronService):
        """
        初始化 Cron 工具。

        Args:
            cron_service: Cron 服务实例
        """
        self._cron = cron_service  # Cron 服务
        self._channel = ""  # 渠道
        self._chat_id = ""  # 聊天 ID
        # 上下文变量：标记是否在任务执行中
        self._in_cron_context: ContextVar[bool] = ContextVar("cron_in_context", default=False)

    def set_context(self, channel: str, chat_id: str) -> None:
        """
        设置当前会话上下文用于消息投递。

        Args:
            channel: 渠道名称（如 "telegram"）
            chat_id: 聊天 ID
        """
        self._channel = channel
        self._chat_id = chat_id

    def set_cron_context(self, active: bool):
        """
        标记工具是否在任务回调中执行。

        这是为了防止在任务执行中创建新任务（可能导致无限循环）。

        Args:
            active: 是否在任务上下文中

        Returns:
            ContextVar token: 用于恢复之前的状态
        """
        return self._in_cron_context.set(active)

    def reset_cron_context(self, token) -> None:
        """
        恢复之前的 cron 上下文。

        Args:
            token: 之前 save 的 token
        """
        self._in_cron_context.reset(token)

    @property
    def name(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return "Schedule reminders and recurring tasks. Actions: add, list, remove."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "list", "remove"],
                    "description": "Action to perform",
                },
                "message": {"type": "string", "description": "Reminder message (for add)"},
                "every_seconds": {
                    "type": "integer",
                    "description": "Interval in seconds (for recurring tasks)",
                },
                "cron_expr": {
                    "type": "string",
                    "description": "Cron expression like '0 9 * * *' (for scheduled tasks)",
                },
                "tz": {
                    "type": "string",
                    "description": "IANA timezone for cron expressions (e.g. 'America/Vancouver')",
                },
                "at": {
                    "type": "string",
                    "description": "ISO datetime for one-time execution (e.g. '2026-02-12T10:30:00')",
                },
                "job_id": {"type": "string", "description": "Job ID (for remove)"},
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        message: str = "",
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        tz: str | None = None,
        at: str | None = None,
        job_id: str | None = None,
        **kwargs: Any,
    ) -> str:
        """
        执行 Cron 工具操作。

        Args:
            action: 操作类型（add/list/remove）
            message: 任务消息（添加时用）
            every_seconds: 间隔秒数（周期性任务）
            cron_expr: Cron 表达式（定时任务）
            tz: 时区（仅用于 cron 表达式）
            at: ISO 格式时间（一次性任务）
            job_id: 任务 ID（删除时用）
            **kwargs: 其他参数

        Returns:
            str: 操作结果或错误信息

        操作类型：
        --------
        add: 创建新任务
            - 需要 message
            - 需要 every_seconds/cron_expr/at 之一

        list: 列出所有任务
            - 不需要额外参数

        remove: 删除任务
            - 需要 job_id

        安全检查：
        --------
        在任务执行中不允许创建新任务（防止无限循环）
        """
        if action == "add":
            # 检查是否在任务执行中（防止无限循环）
            if self._in_cron_context.get():
                return "Error: cannot schedule new jobs from within a cron job execution"
            return self._add_job(message, every_seconds, cron_expr, tz, at)
        elif action == "list":
            return self._list_jobs()
        elif action == "remove":
            return self._remove_job(job_id)
        return f"Unknown action: {action}"

    def _add_job(
        self,
        message: str,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        at: str | None,
    ) -> str:
        """
        添加新的定时任务。

        Args:
            message: 任务消息（提醒内容）
            every_seconds: 间隔秒数（周期性任务）
            cron_expr: Cron 表达式（定时任务）
            tz: 时区（仅用于 cron 表达式）
            at: ISO 格式时间（一次性任务）

        Returns:
            str: 创建成功返回任务信息，失败返回错误

        调度类型优先级：
        -------------
        1. every_seconds: 周期性任务（如每 3600 秒）
        2. cron_expr: Cron 表达式（如每天 9 点）
        3. at: 一次性任务（如 2026-03-12T10:30:00）

        错误检查：
        --------
        - message 不能为空
        - 必须有会话上下文（channel/chat_id）
        - tz 只能与 cron_expr 一起使用
        - at 必须是有效的 ISO 格式
        """
        if not message:
            return "Error: message is required for add"
        if not self._channel or not self._chat_id:
            return "Error: no session context (channel/chat_id)"
        if tz and not cron_expr:
            return "Error: tz can only be used with cron_expr"
        if tz:
            from zoneinfo import ZoneInfo

            try:
                ZoneInfo(tz)
            except (KeyError, Exception):
                return f"Error: unknown timezone '{tz}'"

        # 构建调度对象
        delete_after = False
        if every_seconds:
            # 周期性任务
            schedule = CronSchedule(kind="every", every_ms=every_seconds * 1000)
        elif cron_expr:
            # Cron 表达式任务
            schedule = CronSchedule(kind="cron", expr=cron_expr, tz=tz)
        elif at:
            # 一次性任务
            from datetime import datetime

            try:
                dt = datetime.fromisoformat(at)
            except ValueError:
                return f"Error: invalid ISO datetime format '{at}'. Expected format: YYYY-MM-DDTHH:MM:SS"
            at_ms = int(dt.timestamp() * 1000)
            schedule = CronSchedule(kind="at", at_ms=at_ms)
            delete_after = True  # 一次性任务执行后删除
        else:
            return "Error: either every_seconds, cron_expr, or at is required"

        # 创建任务
        job = self._cron.add_job(
            name=message[:30],  # 任务名（截断到 30 字符）
            schedule=schedule,
            message=message,
            deliver=True,  # 启用消息投递
            channel=self._channel,
            to=self._chat_id,
            delete_after_run=delete_after,  # 一次性任务执行后删除
        )
        return f"Created job '{job.name}' (id: {job.id})"

    def _list_jobs(self) -> str:
        """
        列出所有定时任务。

        Returns:
            str: 任务列表或"无任务"提示
        """
        jobs = self._cron.list_jobs()
        if not jobs:
            return "No scheduled jobs."
        # 格式化输出
        lines = [f"- {j.name} (id: {j.id}, {j.schedule.kind})" for j in jobs]
        return "Scheduled jobs:\n" + "\n".join(lines)

    def _remove_job(self, job_id: str | None) -> str:
        """
        删除定时任务。

        Args:
            job_id: 任务 ID

        Returns:
            str: 删除成功返回成功信息，失败返回错误
        """
        if not job_id:
            return "Error: job_id is required for remove"
        if self._cron.remove_job(job_id):
            return f"Removed job {job_id}"
        return f"Job {job_id} not found"

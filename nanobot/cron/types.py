# =============================================================================
# nanobot 定时任务类型定义
# 文件路径：nanobot/cron/types.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件使用 dataclass 定义了 nanobot 定时任务系统的数据结构。
#
# 什么是定时任务（Cron Job）？
# -------------------------
# 定时任务是按预定时间或间隔自动执行的任务。例如：
# - 每天早上 9 点发送日报
# - 每 30 分钟检查一次待办事项
# - 每周一上午 10 点开周会
#
# 支持的调度类型：
# --------------
# 1. at: 在特定时间点执行一次
# 2. every: 按固定间隔重复执行
# 3. cron: 使用标准的 cron 表达式（如 "0 9 * * *" 表示每天 9 点）
#
# 数据结构：
# ---------
# CronSchedule: 调度计划（何时执行）
# CronPayload: 任务负载（执行什么）
# CronJobState: 运行状态（执行情况）
# CronJob: 完整的任务定义
# CronStore: 持久化存储
# =============================================================================

"""Cron types for scheduled task definitions."""
# 定时任务类型定义

from dataclasses import dataclass, field  # 数据类装饰器
from typing import Literal  # 字面量类型，限制值为指定集合


# =============================================================================
# CronSchedule - 调度计划
# =============================================================================

@dataclass
class CronSchedule:
    """
    定时任务的调度计划定义。

    这个类定义了任务何时执行。支持三种调度类型：

    调度类型（kind 字段）：
    -------------------
    1. "at": 在特定时间点执行一次
       - 适用场景：一次性提醒、倒计时任务
       - 使用字段：at_ms（毫秒时间戳）
       - 示例：at_ms=1704067200000（2024-01-01 00:00:00）

    2. "every": 按固定间隔重复执行
       - 适用场景：定期检查、心跳任务
       - 使用字段：every_ms（间隔毫秒数）
       - 示例：every_ms=1800000（每 30 分钟）

    3. "cron": 使用标准 cron 表达式
       - 适用场景：固定时间点（如每天 9 点、每周一）
       - 使用字段：expr（cron 表达式）、tz（时区）
       - 示例：expr="0 9 * * *"（每天 9:00）

    属性说明：
    --------
    kind: Literal["at", "every", "cron"]
        调度类型
        三选一：
        - "at": 一次性执行
        - "every": 间隔重复
        - "cron": cron 表达式

    at_ms: int | None
        执行时间戳（毫秒），仅用于 kind="at"
        时间戳是从 1970-01-01 00:00:00 UTC 开始的毫秒数

    every_ms: int | None
        执行间隔（毫秒），仅用于 kind="every"
        示例：
        - 60000 = 1 分钟
        - 3600000 = 1 小时
        - 86400000 = 1 天

    expr: str | None
        Cron 表达式，仅用于 kind="cron"
        标准 5 段格式：分 时 日 月 周
        示例：
        - "0 9 * * *" = 每天 9:00
        - "0 0 * * 1" = 每周一 0:00
        - "*/30 * * * *" = 每 30 分钟

    tz: str | None
        时区，仅用于 kind="cron"
        示例："Asia/Shanghai"（中国标准时间）
        默认使用系统时区

    示例：
        >>> # 每天早上 9 点执行
        >>> schedule = CronSchedule(kind="cron", expr="0 9 * * *", tz="Asia/Shanghai")

        >>> # 每 30 分钟执行一次
        >>> schedule = CronSchedule(kind="every", every_ms=1800000)

        >>> # 2024-01-01 00:00:00 执行一次
        >>> schedule = CronSchedule(kind="at", at_ms=1704067200000)
    """
    kind: Literal["at", "every", "cron"]  # 调度类型
    # 用于 kind="at"：执行时间戳（毫秒）
    at_ms: int | None = None
    # 用于 kind="every"：间隔毫秒数
    every_ms: int | None = None
    # 用于 kind="cron"：cron 表达式（如 "0 9 * * *" 表示每天 9 点）
    expr: str | None = None
    # 用于 kind="cron"：时区（如 "Asia/Shanghai"）
    tz: str | None = None


# =============================================================================
# CronPayload - 任务负载
# =============================================================================

@dataclass
class CronPayload:
    """
    定时任务执行时的负载定义。

    这个类定义了当任务触发时要做什么。

    负载类型（kind 字段）：
    -------------------
    1. "agent_turn": 让 Agent 执行一轮对话
       - 适用场景：定期检查待办事项、发送提醒
       - message 字段包含要处理的指令

    2. "system_event": 系统事件（暂未实现）
       - 预留类型，未来可能用于系统级事件

    属性说明：
    --------
    kind: Literal["system_event", "agent_turn"]
        负载类型
        - "agent_turn": Agent 执行（默认）
        - "system_event": 系统事件

    message: str
        要执行的指令或消息
        示例：
        - "检查今天的待办事项并发送提醒"
        - "发送日报给所有用户"

    deliver: bool
        是否将响应发送到渠道
        - True: 执行完成后将结果发送给用户
        - False: 静默执行，不发送结果
        默认值：False

    channel: str | None
        目标渠道名称
        示例："whatsapp"、"telegram"、"discord"
        默认值：None

    to: str | None
        目标聊天 ID
        - WhatsApp: 电话号码（如 "+8613800138000"）
        - Telegram: 用户 ID（如 "123456789"）
        默认值：None

    示例：
        >>> # 定时任务：检查待办事项
        >>> payload = CronPayload(
        ...     kind="agent_turn",
        ...     message="检查今天的待办事项",
        ...     deliver=True,
        ...     channel="whatsapp",
        ...     to="+8613800138000"
        ... )
    """
    kind: Literal["system_event", "agent_turn"] = "agent_turn"  # 负载类型
    message: str = ""  # 要执行的指令
    # 是否将响应发送到渠道
    deliver: bool = False
    channel: str | None = None  # 目标渠道，如 "whatsapp"
    to: str | None = None  # 目标聊天 ID，如电话号码


# =============================================================================
# CronJobState - 任务运行状态
# =============================================================================

@dataclass
class CronJobState:
    """
    定时任务的运行时状态。

    这个类记录了任务的执行情况，用于：
    1. 追踪下次执行时间
    2. 记录历史执行结果
    3. 错误诊断

    属性说明：
    --------
    next_run_at_ms: int | None
        下次执行时间（毫秒时间戳）
        系统根据调度类型计算得出
        示例：1704067200000 = 2024-01-01 00:00:00

    last_run_at_ms: int | None
        上次执行时间（毫秒时间戳）
        用于计算实际执行间隔

    last_status: Literal["ok", "error", "skipped"] | None
        上次执行状态
        - "ok": 成功执行
        - "error": 执行出错
        - "skipped": 被跳过（如任务被禁用）

    last_error: str | None
        上次执行的错误信息
        仅当 last_status="error" 时有值

    示例：
        >>> state = CronJobState(
        ...     next_run_at_ms=1704067200000,
        ...     last_run_at_ms=1704063600000,
        ...     last_status="ok"
        ... )
    """
    next_run_at_ms: int | None = None  # 下次执行时间
    last_run_at_ms: int | None = None  # 上次执行时间
    last_status: Literal["ok", "error", "skipped"] | None = None  # 上次执行状态
    last_error: str | None = None  # 上次错误信息


# =============================================================================
# CronJob - 定时任务
# =============================================================================

@dataclass
class CronJob:
    """
    完整的定时任务定义。

    这是定时任务的核心数据结构，包含：
    1. 基本信息（id, name）
    2. 调度计划（schedule）
    3. 执行内容（payload）
    4. 运行状态（state）
    5. 元数据（created_at, updated_at）

    属性说明：
    --------
    id: str
        任务唯一标识符
        通常使用 UUID 或自增 ID

    name: str
        任务名称
        用于显示和管理

    enabled: bool
        是否启用
        - True: 正常执行
        - False: 暂停执行
        默认值：True

    schedule: CronSchedule
        调度计划
        定义任务何时执行

    payload: CronPayload
        任务负载
        定义任务执行什么

    state: CronJobState
        运行状态
        记录执行情况

    created_at_ms: int
        创建时间（毫秒时间戳）

    updated_at_ms: int
        最后更新时间（毫秒时间戳）

    delete_after_run: bool
        是否在执行后删除
        - True: 一次性任务，执行后自动删除
        - False: 重复执行
        默认值：False

    完整示例：
        >>> job = CronJob(
        ...     id="daily-reminder",
        ...     name="每日待办提醒",
        ...     enabled=True,
        ...     schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="Asia/Shanghai"),
        ...     payload=CronPayload(
        ...         kind="agent_turn",
        ...         message="发送今日待办提醒",
        ...         deliver=True,
        ...         channel="whatsapp",
        ...         to="+8613800138000"
        ...     ),
        ...     delete_after_run=False
        ... )
    """
    id: str  # 任务 ID
    name: str  # 任务名称
    enabled: bool = True  # 是否启用
    schedule: CronSchedule = field(default_factory=lambda: CronSchedule(kind="every"))  # 调度计划
    payload: CronPayload = field(default_factory=CronPayload)  # 任务负载
    state: CronJobState = field(default_factory=CronJobState)  # 运行状态
    created_at_ms: int = 0  # 创建时间
    updated_at_ms: int = 0  # 更新时间
    delete_after_run: bool = False  # 执行后是否删除


# =============================================================================
# CronStore - 定时任务存储
# =============================================================================

@dataclass
class CronStore:
    """
    定时任务的持久化存储。

    这个类用于将所有定时任务序列化并保存到文件。

    属性说明：
    --------
    version: int
        存储格式版本号
        用于配置迁移和兼容性
        当前版本：1

    jobs: list[CronJob]
        任务列表
        包含所有已配置的定时任务

    示例：
        >>> store = CronStore(
        ...     version=1,
        ...     jobs=[job1, job2, job3]
        ... )
        # 保存为 JSON
        >>> import json
        >>> with open("cron.json", "w") as f:
        ...     json.dump(dataclasses.asdict(store), f)
    """
    version: int = 1  # 存储格式版本
    jobs: list[CronJob] = field(default_factory=list)  # 任务列表

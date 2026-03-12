# =============================================================================
# nanobot 定时任务服务
# 文件路径：nanobot/cron/service.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 CronService 类，是一个定时任务调度器。
#
# 什么是定时任务（Cron Job）？
# -----------------------
# 定时任务是在指定时间自动执行的任务，例如：
# - 每天早上 8 点发送天气提醒
# - 每小时检查一次系统状态
# - 每周一生成周报
#
# 支持的调度类型：
# ------------
# 1. at: 在特定时间点执行（一次性）
#    例如：2024-01-15 10:30:00 执行
#
# 2. every: 每隔一段时间执行（周期性）
#    例如：每 30 分钟执行一次
#
# 3. cron: 使用 Cron 表达式（灵活调度）
#    例如："0 8 * * *" 表示每天早上 8 点
#
# 为什么需要定时任务服务？
# ---------------------
# 1. 自动化：无需手动触发，到点自动执行
# 2. 持久化：任务定义保存到磁盘，重启后不丢失
# 3. 可管理：支持添加、删除、启用、禁用任务
# 4. 灵活性：支持多种调度模式
#
# Cron 表达式示例：
# --------------
# "0 8 * * *"    → 每天早上 8 点
# "0 */30 * * *"  → 每 30 分钟
# "0 9 * * 1"    → 每周一上午 9 点
# "0 0 1 * *"    → 每月 1 号零点
# =============================================================================

"""Cron service for scheduling agent tasks."""
# 定时任务服务：调度 Agent 任务

import asyncio  # 异步编程
import json  # JSON 处理
import time  # 时间处理
import uuid  # 唯一 ID 生成
from datetime import datetime  # 日期时间
from pathlib import Path  # 路径处理
from typing import Any, Callable, Coroutine  # 类型注解

from loguru import logger  # 日志库

from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore  # 定时任务类型
# 类型说明：
# - CronJob: 任务定义（名称、调度、负载等）
# - CronSchedule: 调度规则（kind、at_ms、every_ms、expr 等）
# - CronPayload: 任务负载（要执行的消息）
# - CronJobState: 任务状态（下次执行时间、上次执行时间等）
# - CronStore: 任务存储（包含所有任务）


# =============================================================================
# 辅助函数
# =============================================================================

def _now_ms() -> int:
    """
    获取当前时间的毫秒戳。

    Returns:
        int: 从 Unix 纪元到现在的毫秒数

    示例：
        >>> _now_ms()
        1705312200000
    """
    return int(time.time() * 1000)


def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """
    计算下次执行时间（毫秒）。

    根据调度类型计算下次执行时间：

    1. at 类型（一次性）：
       - 如果 at_ms > 现在，返回 at_ms
       - 否则返回 None（已过期）

    2. every 类型（周期性）：
       - 返回 现在 + every_ms

    3. cron 类型（Cron 表达式）：
       - 使用 croniter 库计算下次执行时间
       - 支持时区

    Args:
        schedule: 调度规则对象
        now_ms: 当前时间（毫秒）

    Returns:
        int | None: 下次执行时间（毫秒），无法计算返回 None
    """
    # at 类型：一次性执行
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None

    # every 类型：周期性执行
    if schedule.kind == "every":
        # 无效的间隔
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        # 下次执行 = 现在 + 间隔
        return now_ms + schedule.every_ms

    # cron 类型：Cron 表达式
    if schedule.kind == "cron" and schedule.expr:
        try:
            from zoneinfo import ZoneInfo  # 时区支持
            from croniter import croniter  # Cron 表达式解析

            # 使用调用者提供的时间作为基准（确保调度一致性）
            base_time = now_ms / 1000
            # 解析时区
            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
            # 转换为带时区的 datetime
            base_dt = datetime.fromtimestamp(base_time, tz=tz)
            # 创建 croniter 实例
            cron = croniter(schedule.expr, base_dt)
            # 计算下次执行时间
            next_dt = cron.get_next(datetime)
            return int(next_dt.timestamp() * 1000)
        except Exception:
            # 解析失败返回 None
            return None

    # 未知类型
    return None


def _validate_schedule_for_add(schedule: CronSchedule) -> None:
    """
    验证调度字段，防止创建无法执行的任务。

    验证规则：
    --------
    1. tz（时区）只能与 cron 调度一起使用
       - every 和 at 不支持时区

    2. cron 调用的时区必须是有效的
       - 使用 zoneinfo.ZoneInfo 验证

    Args:
        schedule: 要验证的调度规则

    Raises:
        ValueError: 验证失败时抛出
    """
    # 时区只能用于 cron 调度
    if schedule.tz and schedule.kind != "cron":
        raise ValueError("tz can only be used with cron schedules")

    # 验证 cron 调用的时区是否有效
    if schedule.kind == "cron" and schedule.tz:
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(schedule.tz)  # 尝试创建时区对象，无效会抛出异常
        except Exception:
            raise ValueError(f"unknown timezone '{schedule.tz}'") from None


# =============================================================================
# CronService - 定时任务服务
# =============================================================================

class CronService:
    """
    用于管理和执行定时任务的服务。

    核心职责：
    --------
    1. 存储管理：从磁盘加载/保存任务定义
    2. 调度计算：计算每个任务的下次执行时间
    3. 定时器：在适当的时间触发任务
    4. 任务执行：调用回调函数执行任务
    5. 状态跟踪：记录任务的执行状态

    属性说明：
    --------
    store_path: Path
        任务存储文件路径（jobs.json）

    on_job: Callable | None
        任务执行时的回调函数
        用于实际执行任务逻辑（如调用 Agent）

    _store: CronStore | None
        内存中的任务存储（缓存）

    _last_mtime: float
        文件最后修改时间（用于检测外部修改）

    _timer_task: asyncio.Task | None
        定时器任务（等待下次执行）

    _running: bool
        服务运行状态
    """

    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None
    ):
        """
        初始化定时任务服务。

        Args:
            store_path: 任务存储文件路径
            on_job: 任务执行回调（可选）
                当任务触发时调用，传入 CronJob 对象
        """
        self.store_path = store_path  # 存储路径
        self.on_job = on_job  # 任务回调
        self._store: CronStore | None = None  # 内存缓存
        self._last_mtime: float = 0.0  # 文件修改时间
        self._timer_task: asyncio.Task | None = None  # 定时器
        self._running = False  # 运行状态

    def _load_store(self) -> CronStore:
        """
        从磁盘加载任务存储，如果文件被外部修改则自动重新加载。

        自动重载机制：
        ------------
        通过比较文件修改时间（mtime）检测外部修改。
        如果 mtime 变化，说明文件被其他进程修改，需要重新加载。

        Returns:
            CronStore: 任务存储对象

        加载流程：
        --------
        1. 检查缓存是否存在
        2. 检查文件是否被外部修改
        3. 读取 JSON 文件
        4. 解析为 CronJob 对象
        5. 返回 CronStore
        """
        # 检查是否需要重新加载
        if self._store and self.store_path.exists():
            mtime = self.store_path.stat().st_mtime
            # 文件修改时间变化，说明被外部修改
            if mtime != self._last_mtime:
                logger.info("Cron: jobs.json modified externally, reloading")
                self._store = None  # 清空缓存

        # 缓存命中
        if self._store:
            return self._store

        # 文件存在则读取
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text(encoding="utf-8"))
                jobs = []
                # 解析每个任务
                for j in data.get("jobs", []):
                    jobs.append(CronJob(
                        id=j["id"],
                        name=j["name"],
                        enabled=j.get("enabled", True),
                        schedule=CronSchedule(
                            kind=j["schedule"]["kind"],
                            at_ms=j["schedule"].get("atMs"),
                            every_ms=j["schedule"].get("everyMs"),
                            expr=j["schedule"].get("expr"),
                            tz=j["schedule"].get("tz"),
                        ),
                        payload=CronPayload(
                            kind=j["payload"].get("kind", "agent_turn"),
                            message=j["payload"].get("message", ""),
                            deliver=j["payload"].get("deliver", False),
                            channel=j["payload"].get("channel"),
                            to=j["payload"].get("to"),
                        ),
                        state=CronJobState(
                            next_run_at_ms=j.get("state", {}).get("nextRunAtMs"),
                            last_run_at_ms=j.get("state", {}).get("lastRunAtMs"),
                            last_status=j.get("state", {}).get("lastStatus"),
                            last_error=j.get("state", {}).get("lastError"),
                        ),
                        created_at_ms=j.get("createdAtMs", 0),
                        updated_at_ms=j.get("updatedAtMs", 0),
                        delete_after_run=j.get("deleteAfterRun", False),
                    ))
                self._store = CronStore(jobs=jobs)
            except Exception as e:
                # 加载失败记录警告
                logger.warning("Failed to load cron store: {}", e)
                self._store = CronStore()  # 空存储
        else:
            # 文件不存在，创建空存储
            self._store = CronStore()

        return self._store

    def _save_store(self) -> None:
        """
        保存任务存储到磁盘。

        保存格式（JSON）：
        --------------
        {
            "version": 1,
            "jobs": [
                {
                    "id": "abc12345",
                    "name": "morning_weather",
                    "enabled": true,
                    "schedule": {"kind": "cron", "expr": "0 8 * * *", ...},
                    "payload": {"kind": "agent_turn", "message": "天气...", ...},
                    "state": {"nextRunAtMs": ..., "lastRunAtMs": ..., ...},
                    "createdAtMs": ...,
                    "updatedAtMs": ...,
                    "deleteAfterRun": false
                }
            ]
        }
        """
        if not self._store:
            return

        # 确保父目录存在
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        # 构建 JSON 数据
        data = {
            "version": self._store.version,
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "enabled": j.enabled,
                    "schedule": {
                        "kind": j.schedule.kind,
                        "atMs": j.schedule.at_ms,
                        "everyMs": j.schedule.every_ms,
                        "expr": j.schedule.expr,
                        "tz": j.schedule.tz,
                    },
                    "payload": {
                        "kind": j.payload.kind,
                        "message": j.payload.message,
                        "deliver": j.payload.deliver,
                        "channel": j.payload.channel,
                        "to": j.payload.to,
                    },
                    "state": {
                        "nextRunAtMs": j.state.next_run_at_ms,
                        "lastRunAtMs": j.state.last_run_at_ms,
                        "lastStatus": j.state.last_status,
                        "lastError": j.state.last_error,
                    },
                    "createdAtMs": j.created_at_ms,
                    "updatedAtMs": j.updated_at_ms,
                    "deleteAfterRun": j.delete_after_run,
                }
                for j in self._store.jobs
            ]
        }

        # 写入文件
        self.store_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # 更新修改时间
        self._last_mtime = self.store_path.stat().st_mtime

    async def start(self) -> None:
        """
        启动定时任务服务。

        启动流程：
        --------
        1. 设置运行标志
        2. 加载任务存储
        3. 重新计算所有任务的下次执行时间
        4. 保存到磁盘
        5. 启动定时器
        """
        self._running = True  # 设置运行标志
        self._load_store()  # 加载存储
        self._recompute_next_runs()  # 计算下次执行时间
        self._save_store()  # 保存
        self._arm_timer()  # 启动定时器
        logger.info("Cron service started with {} jobs", len(self._store.jobs if self._store else []))

    def stop(self) -> None:
        """
        停止定时任务服务。

        停止流程：
        --------
        1. 设置停止标志
        2. 取消定时器任务
        """
        self._running = False  # 设置停止标志
        if self._timer_task:
            self._timer_task.cancel()  # 取消定时器
            self._timer_task = None

    def _recompute_next_runs(self) -> None:
        """
        重新计算所有启用任务的下次执行时间。

        使用场景：
        --------
        1. 服务启动时
        2. 添加新任务后
        3. 修改任务调度后
        """
        if not self._store:
            return
        now = _now_ms()
        # 遍历所有启用的任务
        for job in self._store.jobs:
            if job.enabled:
                # 计算下次执行时间
                job.state.next_run_at_ms = _compute_next_run(job.schedule, now)

    def _get_next_wake_ms(self) -> int | None:
        """
        获取所有任务中最早的下次执行时间。

        Returns:
            int | None: 下次唤醒时间（毫秒），没有任务返回 None

        用途：
        ----
        用于设置定时器的等待时间。
        """
        if not self._store:
            return None
        # 收集所有启用任务的下次执行时间
        times = [j.state.next_run_at_ms for j in self._store.jobs
                 if j.enabled and j.state.next_run_at_ms]
        # 返回最小值（最早的）
        return min(times) if times else None

    def _arm_timer(self) -> None:
        """
        设置下一个定时器。

        定时器逻辑：
        --------
        1. 取消现有定时器
        2. 获取下次执行时间
        3. 计算延迟
        4. 创建异步任务
        """
        # 取消现有定时器
        if self._timer_task:
            self._timer_task.cancel()

        # 获取下次执行时间
        next_wake = self._get_next_wake_ms()
        # 没有任务或已停止
        if not next_wake or not self._running:
            return

        # 计算延迟（毫秒转秒）
        delay_ms = max(0, next_wake - _now_ms())
        delay_s = delay_ms / 1000

        # 定时器回调
        async def tick():
            await asyncio.sleep(delay_s)  # 等待
            if self._running:
                await self._on_timer()  # 执行任务

        # 创建定时器任务
        self._timer_task = asyncio.create_task(tick())

    async def _on_timer(self) -> None:
        """
        处理定时器触发——执行到期的任务。

        执行流程：
        --------
        1. 重新加载存储（检测外部修改）
        2. 获取当前时间
        3. 找出所有到期的任务
        4. 逐个执行
        5. 保存状态
        6. 重新设置定时器
        """
        # 重新加载存储
        self._load_store()
        if not self._store:
            return

        now = _now_ms()
        # 找出所有到期的任务
        due_jobs = [
            j for j in self._store.jobs
            if j.enabled and j.state.next_run_at_ms and now >= j.state.next_run_at_ms
        ]

        # 执行每个到期的任务
        for job in due_jobs:
            await self._execute_job(job)

        # 保存状态变化
        self._save_store()
        # 重新设置定时器
        self._arm_timer()

    async def _execute_job(self, job: CronJob) -> None:
        """
        执行单个任务。

        执行流程：
        --------
        1. 记录开始时间
        2. 调用回调函数
        3. 记录执行状态
        4. 处理一次性任务（执行后删除或禁用）
        5. 计算下次执行时间

        Args:
            job: 要执行的任务对象
        """
        start_ms = _now_ms()
        logger.info("Cron: executing job '{}' ({})", job.name, job.id)

        try:
            response = None
            # 调用任务回调
            if self.on_job:
                response = await self.on_job(job)

            # 执行成功
            job.state.last_status = "ok"
            job.state.last_error = None
            logger.info("Cron: job '{}' completed", job.name)

        except Exception as e:
            # 执行失败
            job.state.last_status = "error"
            job.state.last_error = str(e)
            logger.error("Cron: job '{}' failed: {}", job.name, e)

        # 更新执行时间
        job.state.last_run_at_ms = start_ms
        job.updated_at_ms = _now_ms()

        # 处理一次性任务
        if job.schedule.kind == "at":
            if job.delete_after_run:
                # 执行后删除
                self._store.jobs = [j for j in self._store.jobs if j.id != job.id]
            else:
                # 执行后禁用
                job.enabled = False
                job.state.next_run_at_ms = None
        else:
            # 周期性任务，计算下次执行时间
            job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())

    # ========== 公共 API ==========

    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """
        列出所有任务。

        Args:
            include_disabled: 是否包含已禁用的任务
                False: 只返回启用的任务
                True: 返回所有任务

        Returns:
            list[CronJob]: 任务列表，按下次执行时间排序
        """
        store = self._load_store()
        # 过滤任务
        jobs = store.jobs if include_disabled else [j for j in store.jobs if j.enabled]
        # 按下次执行时间排序（None 排最后）
        return sorted(jobs, key=lambda j: j.state.next_run_at_ms or float('inf'))

    def add_job(
        self,
        name: str,
        schedule: CronSchedule,
        message: str,
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        delete_after_run: bool = False,
    ) -> CronJob:
        """
        添加新任务。

        Args:
            name: 任务名称
            schedule: 调度规则
            message: 要执行的消息内容
            deliver: 是否发送消息（vs 仅执行）
            channel: 目标渠道（可选）
            to: 目标用户/聊天 ID（可选）
            delete_after_run: 执行后是否删除（一次性任务）

        Returns:
            CronJob: 创建的任务对象
        """
        store = self._load_store()
        # 验证调度规则
        _validate_schedule_for_add(schedule)
        now = _now_ms()

        # 创建任务对象
        job = CronJob(
            id=str(uuid.uuid4())[:8],  # 短 ID
            name=name,
            enabled=True,
            schedule=schedule,
            payload=CronPayload(
                kind="agent_turn",
                message=message,
                deliver=deliver,
                channel=channel,
                to=to,
            ),
            state=CronJobState(next_run_at_ms=_compute_next_run(schedule, now)),
            created_at_ms=now,
            updated_at_ms=now,
            delete_after_run=delete_after_run,
        )

        # 添加到存储
        store.jobs.append(job)
        self._save_store()
        self._arm_timer()

        logger.info("Cron: added job '{}' ({})", name, job.id)
        return job

    def remove_job(self, job_id: str) -> bool:
        """
        按 ID 移除任务。

        Args:
            job_id: 任务 ID

        Returns:
            bool: True 表示成功移除，False 表示未找到
        """
        store = self._load_store()
        before = len(store.jobs)
        # 过滤掉指定 ID 的任务
        store.jobs = [j for j in store.jobs if j.id != job_id]
        removed = len(store.jobs) < before

        if removed:
            self._save_store()
            self._arm_timer()
            logger.info("Cron: removed job {}", job_id)

        return removed

    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        """
        启用或禁用任务。

        Args:
            job_id: 任务 ID
            enabled: True 启用，False 禁用

        Returns:
            CronJob | None: 任务对象，未找到返回 None

        启用时：
        ------
        - 重新计算下次执行时间

        禁用时：
        ------
        - 清除下次执行时间
        """
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                job.enabled = enabled
                job.updated_at_ms = _now_ms()
                if enabled:
                    # 启用时重新计算
                    job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
                else:
                    # 禁用时清除
                    job.state.next_run_at_ms = None
                self._save_store()
                self._arm_timer()
                return job
        return None

    async def run_job(self, job_id: str, force: bool = False) -> bool:
        """
        手动执行任务。

        Args:
            job_id: 任务 ID
            force: 是否强制执行（即使任务已禁用）

        Returns:
            bool: True 表示成功执行，False 表示未找到或被跳过
        """
        store = self._load_store()
        for job in store.jobs:
            if job.id == job_id:
                # 非强制且任务禁用，跳过
                if not force and not job.enabled:
                    return False
                # 执行任务
                await self._execute_job(job)
                self._save_store()
                self._arm_timer()
                return True
        return False

    def status(self) -> dict:
        """
        获取服务状态。

        Returns:
            dict: 状态字典
                - enabled: 服务是否运行
                - jobs: 任务数量
                - next_wake_at_ms: 下次唤醒时间
        """
        store = self._load_store()
        return {
            "enabled": self._running,
            "jobs": len(store.jobs),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }

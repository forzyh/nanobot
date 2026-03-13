# =============================================================================
# nanobot Cron 定时服务测试
# 文件路径：tests/test_cron_service.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 CronService 定时任务服务的测试。
# 主要测试定时任务的添加、时区验证和外部禁用功能。
#
# 什么是 CronService？
# ---------------
# CronService 是 nanobot 的定时任务调度服务，支持：
# - Cron 表达式调度（如 "0 9 * * *" 表示每天 9 点）
# - 固定间隔调度（如每 200 毫秒）
# - 时区支持
# - 任务的启用/禁用
# - 外部配置文件同步（通过监控配置文件修改时间）
#
# 测试场景：
# --------
# 1. 拒绝未知时区：添加任务时使用不存在的时区应抛出异常
# 2. 接受有效时区：添加任务时使用有效的时区应成功
# 3. 遵守外部禁用：当外部配置文件禁用任务时，运行中的服务应停止执行该任务
#
# 使用示例：
# --------
# pytest tests/test_cron_service.py -v  # 运行所有测试
# =============================================================================

import asyncio

import pytest

from nanobot.cron.service import CronService
from nanobot.cron.types import CronSchedule


def test_add_job_rejects_unknown_timezone(tmp_path) -> None:
    """测试添加任务时拒绝未知时区。

    场景说明：
        当添加定时任务时，如果指定的时区名称不存在（如拼写错误），
        系统应该抛出 ValueError 异常，防止任务以错误的时区运行。

    验证点：
        1. 抛出 ValueError 异常，错误信息包含 "unknown timezone"
        2. 任务列表为空，表示失败的任务没有被添加
    """
    # 创建 CronService 实例，使用临时目录存储任务配置
    service = CronService(tmp_path / "cron" / "jobs.json")

    # 尝试验证添加一个时区拼写错误的任务（"Vancovuer" 应为 "Vancouver"）
    with pytest.raises(ValueError, match="unknown timezone 'America/Vancovuer'"):
        service.add_job(
            name="tz typo",
            # CronSchedule 定义定时任务，expr 是 Cron 表达式，tz 是时区
            schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="America/Vancovuer"),
            message="hello",
        )

    # 验证任务没有被添加，列表为空
    assert service.list_jobs(include_disabled=True) == []


def test_add_job_accepts_valid_timezone(tmp_path) -> None:
    """测试添加任务时接受有效时区。

    场景说明：
        当添加定时任务时，如果指定的时区名称有效，
        系统应该成功添加任务，并正确设置时区。

    验证点：
        1. 任务的时区设置正确
        2. 任务状态包含下次运行时间（next_run_at_ms）
    """
    # 创建 CronService 实例
    service = CronService(tmp_path / "cron" / "jobs.json")

    # 添加一个使用有效时区的任务
    job = service.add_job(
        name="tz ok",
        # 使用正确的时区名称 "America/Vancouver"（温哥华）
        schedule=CronSchedule(kind="cron", expr="0 9 * * *", tz="America/Vancouver"),
        message="hello",
    )

    # 验证时区设置正确
    assert job.schedule.tz == "America/Vancouver"
    # 验证任务状态包含下次运行时间
    assert job.state.next_run_at_ms is not None


@pytest.mark.asyncio
async def test_running_service_honors_external_disable(tmp_path) -> None:
    """测试运行中的服务遵守外部禁用。

    场景说明：
        CronService 支持外部配置修改，
        当一个任务正在运行时，如果外部配置文件禁用了该任务，
        服务应该检测到并停止执行该任务。

        测试流程：
        1. 启动服务并添加一个每 200ms 执行一次的任务
        2. 等待片刻后，通过另一个服务实例禁用该任务
        3. 等待 350ms（足够任务触发两次的时间）
        4. 验证任务没有被执行

    验证点：
        1. 外部禁用操作成功，任务 enabled 变为 False
        2. 任务回调列表为空，表示任务没有被执行
    """
    # 创建任务存储路径
    store_path = tmp_path / "cron" / "jobs.json"
    # 用于记录任务执行的列表
    called: list[str] = []

    # 定义任务执行回调函数
    async def on_job(job) -> None:
        called.append(job.id)

    # 创建 CronService 实例
    service = CronService(store_path, on_job=on_job)
    # 添加一个每 200 毫秒执行一次的任务
    job = service.add_job(
        name="external-disable",
        # kind="every" 表示固定间隔调度，every_ms=200 表示每 200 毫秒
        schedule=CronSchedule(kind="every", every_ms=200),
        message="hello",
    )
    # 启动服务
    await service.start()
    try:
        # 等待片刻以确保文件修改时间明显不同
        await asyncio.sleep(0.05)
        # 创建另一个服务实例来模拟外部修改
        external = CronService(store_path)
        # 通过外部实例禁用任务
        updated = external.enable_job(job.id, enabled=False)
        assert updated is not None
        assert updated.enabled is False

        # 等待 350ms，足够让任务触发近 2 次（200ms 间隔）
        await asyncio.sleep(0.35)
        # 验证任务没有被执行，因为已被禁用
        assert called == []
    finally:
        # 停止服务
        service.stop()

# =============================================================================
# nanobot 定时任务模块入口
# 文件路径：nanobot/cron/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这是 nanobot 定时任务模块的入口文件，用于导出核心类和函数。
#
# 什么是定时任务模块？
# ------------------
# 定时任务模块负责管理和执行预定的任务，例如：
# - 每天早上 9 点发送日报
# - 每 30 分钟检查一次待办事项
# - 在特定时间执行提醒
#
# 模块结构：
# ---------
# - service.py: CronService - 定时任务服务（核心逻辑）
# - types.py: 数据类型定义（CronJob, CronSchedule 等）
#
# 使用示例：
# --------
# from nanobot.cron import CronService, CronJob, CronSchedule
#
# # 创建定时任务服务
# service = CronService("/path/to/store.json")
#
# # 添加每天 9 点执行的任务
# job = CronJob(
#     id="daily-reminder",
#     name="每日提醒",
#     schedule=CronSchedule(kind="cron", expr="0 9 * * *"),
#     payload=CronPayload(kind="agent_turn", message="发送提醒")
# )
# service.add_job(job)
# =============================================================================

"""Cron service for scheduled agent tasks."""
# 定时任务服务：用于按计划执行 Agent 任务

from nanobot.cron.service import CronService
from nanobot.cron.types import CronJob, CronSchedule

__all__ = ["CronService", "CronJob", "CronSchedule"]

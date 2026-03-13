# =============================================================================
# nanobot 心跳服务模块入口
# 文件路径：nanobot/heartbeat/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这是 nanobot 心跳服务模块的入口文件，用于导出 HeartbeatService 类。
#
# 什么是心跳服务？
# --------------
# 心跳服务是一个后台服务，定期"唤醒"Agent 执行一些例行任务。
# 就像心脏跳动一样，按照固定节律执行任务。
#
# 心跳任务示例：
# ------------
# 1. 整理记忆：将短期记忆巩固为长期记忆
# 2. 检查待办：查看是否有需要处理的事项
# 3. 主动提醒：到点了提醒用户开会、吃药等
# 4. 状态同步：同步各渠道的状态
#
# 与定时任务的区别：
# ----------------
# - 心跳任务：固定间隔执行（如每 30 分钟），任务内容动态生成
# - 定时任务：按计划执行（如每天 9 点），任务内容预先定义
#
# 使用示例：
# --------
# from nanobot.heartbeat import HeartbeatService
#
# # 创建心跳服务
# heartbeat = HeartbeatService(
#     workspace=Path("/workspace"),
#     provider=llm_provider,
#     model="gpt-4",
#     on_execute=handle_heartbeat,
#     interval_s=1800  # 每 30 分钟执行一次
# )
#
# # 启动服务
# await heartbeat.start()
# =============================================================================

"""Heartbeat service for periodic agent wake-ups."""
# 心跳服务：定期唤醒 Agent 执行例行任务

from nanobot.heartbeat.service import HeartbeatService

__all__ = ["HeartbeatService"]

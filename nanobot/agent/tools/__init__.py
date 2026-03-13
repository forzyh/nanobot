# =============================================================================
# nanobot Agent 工具模块入口
# 文件路径：nanobot/agent/tools/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这是 nanobot Agent 工具模块的入口文件，导出核心工具类和注册表。
#
# 什么是工具（Tool）？
# ------------------
# 工具是 Agent 可以使用的能力，让 Agent 能够与环境交互。
# nanobot 的内置工具包括：
#
# 文件系统工具：
# - read_file: 读取文件内容
# - write_file: 写入文件（创建或覆盖）
# - edit_file: 编辑文件（精确修改）
# - list_dir: 列出目录内容
#
# 执行工具：
# - exec: 执行 Shell 命令
#
# 网络工具：
# - web_search: 网络搜索（使用 Brave Search）
# - web_fetch: 获取网页内容
#
# 通信工具：
# - message: 发送消息到聊天渠道
#
# Agent 工具：
# - spawn: 生成子 Agent（后台任务）
# - cron: 创建定时任务
#
# MCP 工具：
# - 通过 MCP 协议连接外部工具服务器
#
# 工具基类和注册表：
# ----------------
# Tool: 所有工具的抽象基类，定义统一接口
# ToolRegistry: 工具注册表，管理工具的注册、查找和执行
#
# 使用示例：
# --------
# from nanobot.agent.tools import Tool, ToolRegistry
#
# # 创建工具注册表
# registry = ToolRegistry()
#
# # 注册工具
# registry.register(ReadFileTool(workspace=Path("/workspace")))
#
# # 执行工具
# result = await registry.execute("read_file", {"path": "/workspace/test.txt"})
# =============================================================================

"""Agent tools module."""
# Agent 工具模块

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry

__all__ = ["Tool", "ToolRegistry"]

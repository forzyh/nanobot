# =============================================================================
# nanobot Agent 核心模块入口
# 文件路径：nanobot/agent/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这是 nanobot Agent 核心模块的入口文件，导出核心的 Agent 组件。
#
# 什么是 Agent？
# ------------
# Agent 是 nanobot 的"大脑"，负责：
# 1. 理解用户消息
# 2. 调用工具执行任务
# 3. 生成回复
#
# Agent 模块结构：
# --------------
# agent/
# ├── __init__.py       # 模块入口（本文件）
# ├── loop.py           # AgentLoop - 核心处理循环
# ├── context.py        # ContextBuilder - 上下文构建器
# ├── memory.py         # MemoryStore - 记忆存储
# ├── skills.py         # SkillsLoader - 技能加载器
# ├── subagent.py       # SubagentManager - 子 Agent 管理器
# └── tools/            # 工具目录
#     ├── base.py       # Tool - 工具基类
#     ├── registry.py   # ToolRegistry - 工具注册表
#     ├── mcp.py        # MCP 工具集成
#     ├── filesystem.py # 文件系统工具
#     ├── shell.py      # Shell 执行工具
#     ├── web.py        # 网络工具
#     ├── message.py    # 消息工具
#     ├── spawn.py      # 子 Agent 工具
#     └── cron.py       # 定时任务工具
#
# 核心组件说明：
# ------------
# 1. AgentLoop: Agent 的核心处理引擎
#    - 从消息总线接收消息
#    - 构建上下文（历史、记忆、工具）
#    - 调用 LLM 进行推理
#    - 执行工具调用
#    - 将响应发送回消息总线
#
# 2. ContextBuilder: 上下文构建器
#    - 构建系统提示（身份、引导文件、记忆、技能）
#    - 组装消息历史
#    - 添加运行时上下文
#
# 3. MemoryStore: 记忆存储
#    - 长期记忆（MEMORY.md）
#    - 历史日志（HISTORY.md）
#    - 记忆巩固（将短期记忆转为长期记忆）
#
# 4. SkillsLoader: 技能加载器
#    - 扫描工作空间技能
#    - 加载技能定义（SKILL.md）
#    - 检查依赖（环境变量、CLI 工具）
#
# 5. SubagentManager: 子 Agent 管理器
#    - 创建后台任务
#    - 管理子 Agent 生命周期
#    - 汇总执行结果
#
# 使用示例：
# --------
# from nanobot.agent import AgentLoop, ContextBuilder, MemoryStore, SkillsLoader
#
# # 创建组件
# context = ContextBuilder(workspace=Path("/workspace"))
# memory = MemoryStore(workspace=Path("/workspace"))
# skills = SkillsLoader(workspace=Path("/workspace"))
#
# agent = AgentLoop(
#     bus=message_bus,
#     provider=llm_provider,
#     workspace=Path("/workspace"),
#     model="gpt-4"
# )
#
# # 运行 Agent
# await agent.run()
# =============================================================================

"""Agent core module."""
# Agent 核心模块

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader

__all__ = ["AgentLoop", "ContextBuilder", "MemoryStore", "SkillsLoader"]

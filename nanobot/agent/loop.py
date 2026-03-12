# =============================================================================
# nanobot Agent 核心循环
# 文件路径：nanobot/agent/loop.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 AgentLoop 类，是 nanobot 的"大脑"和"指挥中心"。
#
# 什么是 Agent Loop？
# -----------------
# Agent Loop 是 nanobot 的核心处理引擎，负责：
# 1. 从消息总线接收用户消息
# 2. 构建包含历史、记忆、工具的上下文
# 3. 调用 LLM（AI 模型）进行推理
# 4. 执行 AI 返回的工具调用
# 5. 将响应发送回消息总线
#
# 为什么需要 Agent Loop？
# ---------------------
# Agent Loop 是连接各个组件的枢纽：
#
#   用户 → 渠道 → MessageBus → AgentLoop → LLM → 工具执行 → 响应 → 渠道 → 用户
#                              ↑
#                        Session（会话记忆）
#                        Memory（长期记忆）
#                        Tools（工具集）
#
# 核心设计模式：
# ------------
# 1. 事件驱动：通过消息总线接收/发送消息
# 2. 异步并发：使用 asyncio 处理多任务
# 3. 迭代执行：LLM 调用→工具执行→LLM 调用的循环
# 4. 会话管理：每个用户有独立的会话状态
# =============================================================================

"""Agent loop: the core processing engine."""
# Agent 循环：核心处理引擎

from __future__ import annotations  # 启用未来版本的类型注解

import asyncio  # 异步编程
import json  # JSON 处理
import os  # 操作系统接口
import re  # 正则表达式
import sys  # 系统相关
from contextlib import AsyncExitStack  # 异步上下文管理
from pathlib import Path  # 路径处理
from typing import TYPE_CHECKING, Any, Awaitable, Callable  # 类型注解

from loguru import logger  # 日志库

# 导入 nanobot 内部模块
from nanobot.agent.context import ContextBuilder  # 上下文构建器
from nanobot.agent.memory import MemoryConsolidator  # 记忆巩固器
from nanobot.agent.subagent import SubagentManager  # 子 Agent 管理器
from nanobot.agent.tools.cron import CronTool  # 定时任务工具
from nanobot.agent.tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool  # 文件系统工具
from nanobot.agent.tools.message import MessageTool  # 消息工具
from nanobot.agent.tools.registry import ToolRegistry  # 工具注册表
from nanobot.agent.tools.shell import ExecTool  # Shell 执行工具
from nanobot.agent.tools.spawn import SpawnTool  # 生成子 Agent 工具
from nanobot.agent.tools.web import WebFetchTool, WebSearchTool  # 网络工具
from nanobot.bus.events import InboundMessage, OutboundMessage  # 消息事件
from nanobot.bus.queue import MessageBus  # 消息总线
from nanobot.providers.base import LLMProvider  # LLM 提供商基类
from nanobot.session.manager import Session, SessionManager  # 会话管理器

# 类型检查时导入（避免循环依赖）
if TYPE_CHECKING:
    from nanobot.config.schema import ChannelsConfig, ExecToolConfig  # 渠道和工具配置
    from nanobot.cron.service import CronService  # 定时任务服务


# =============================================================================
# AgentLoop - Agent 核心循环
# =============================================================================

class AgentLoop:
    """
    Agent 循环核心处理引擎。

    AgentLoop 是 nanobot 的"大脑"，负责：
    1. 从消息总线接收消息 (Receives messages from the bus)
    2. 构建包含历史、记忆、工具的上下文 (Builds context with history, memory, skills)
    3. 调用 LLM 进行推理 (Calls the LLM)
    4. 执行工具调用 (Executes tool calls)
    5. 将响应发送回消息总线 (Sends responses back)

    属性说明：
    --------
    bus: MessageBus
        消息总线实例
        用于接收用户消息和发送响应

    provider: LLMProvider
        LLM 提供商实例
        如 OpenAIProvider、AnthropicProvider 等

    workspace: Path
        Agent 工作空间路径
        Agent 操作文件的根目录（安全限制）

    model: str | None
        使用的模型名称
        如 "gpt-4"、"claude-3" 等
        不传则使用提供商默认

    max_iterations: int
        工具调用的最大迭代次数
        防止无限循环
        默认值：40

    context_window_tokens: int
        上下文窗口大小（token 数）
        决定能记住多少对话历史
        默认值：65,536 (64K)

    brave_api_key: str | None
        Brave Search API 密钥
        用于网络搜索功能

    web_proxy: str | None
        网络代理 URL
        用于网络请求经过代理

    exec_config: ExecToolConfig | None
        Shell exec 工具配置
        包含超时、路径等设置

    cron_service: CronService | None
        定时任务服务实例
        用于管理定时任务

    restrict_to_workspace: bool
        是否限制工具访问工作空间
        True: 工具只能访问 workspace 内的文件
        False: 工具可以访问任意路径
        默认值：False

    session_manager: SessionManager | None
        会话管理器实例
        用于管理用户会话

    mcp_servers: dict | None
        MCP 服务器配置字典
        MCP（Model Context Protocol）服务器

    channels_config: ChannelsConfig | None
        渠道配置实例
    """

    # 类常量：工具结果最大字符数
    # 用于截断过长的工具返回结果，防止上下文爆炸
    _TOOL_RESULT_MAX_CHARS = 16_000

    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        context_window_tokens: int = 65_536,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        channels_config: ChannelsConfig | None = None,
    ):
        """
        初始化 Agent Loop。

        Args:
            bus: 消息总线实例
            provider: LLM 提供商实例
            workspace: 工作空间路径
            model: 模型名称（可选，默认使用提供商默认）
            max_iterations: 最大迭代次数
            context_window_tokens: 上下文窗口 token 数
            brave_api_key: Brave Search API 密钥
            web_proxy: 网络代理 URL
            exec_config: Shell exec 工具配置
            cron_service: 定时任务服务
            restrict_to_workspace: 是否限制工具访问工作空间
            session_manager: 会话管理器
            mcp_servers: MCP 服务器配置
            channels_config: 渠道配置
        """
        from nanobot.config.schema import ExecToolConfig
        self.bus = bus  # 消息总线
        self.channels_config = channels_config  # 渠道配置
        self.provider = provider  # LLM 提供商
        self.workspace = workspace  # 工作空间
        # 模型名称：如果未提供则使用提供商默认
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations  # 最大迭代次数
        self.context_window_tokens = context_window_tokens  # 上下文窗口
        self.brave_api_key = brave_api_key  # Brave API 密钥
        self.web_proxy = web_proxy  # 网络代理
        self.exec_config = exec_config or ExecToolConfig()  # exec 配置
        self.cron_service = cron_service  # 定时任务服务
        self.restrict_to_workspace = restrict_to_workspace  # 限制工作空间

        # 上下文构建器：负责构建 LLM 消息上下文
        self.context = ContextBuilder(workspace)
        # 会话管理器：管理用户会话历史和记忆
        self.sessions = session_manager or SessionManager(workspace)
        # 工具注册表：注册和管理可用工具
        self.tools = ToolRegistry()
        # 子 Agent 管理器：管理子 Agent 的创建和调度
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
        )

        self._running = False  # 运行状态标志
        self._mcp_servers = mcp_servers or {}  # MCP 服务器配置
        self._mcp_stack: AsyncExitStack | None = None  # MCP 上下文栈
        self._mcp_connected = False  # MCP 连接状态
        self._mcp_connecting = False  # MCP 连接中状态
        self._active_tasks: dict[str, list[asyncio.Task]] = {}  # session_key -> 活跃任务列表
        self._processing_lock = asyncio.Lock()  # 处理锁，防止并发处理同一会话
        # 记忆巩固器：负责将短期记忆转化为长期记忆
        self.memory_consolidator = MemoryConsolidator(
            workspace=workspace,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
        )
        # 注册默认工具集
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """
        注册默认工具集。

        这个函数在 AgentLoop 初始化时调用，
        将所有内置工具注册到工具注册表中。

        注册的默认工具：
        --------------
        1. 文件系统工具：
           - ReadFileTool: 读取文件
           - WriteFileTool: 写入文件
           - EditFileTool: 编辑文件
           - ListDirTool: 列出目录

        2. 执行工具：
           - ExecTool: 执行 Shell 命令

        3. 网络工具：
           - WebSearchTool: 网络搜索
           - WebFetchTool: 获取网页内容

        4. 通信工具：
           - MessageTool: 发送消息

        5. Agent 工具：
           - SpawnTool: 生成子 Agent

        6. 定时工具（如果可用）：
           - CronTool: 定时任务
        """
        # 确定允许访问的目录（如果限制工作空间）
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        # 注册文件系统工具
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        # 注册 Shell exec 工具
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
            path_append=self.exec_config.path_append,
        ))
        # 注册网络工具
        self.tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
        self.tools.register(WebFetchTool(proxy=self.web_proxy))
        # 注册消息工具
        self.tools.register(MessageTool(send_callback=self.bus.publish_outbound))
        # 注册生成子 Agent 工具
        self.tools.register(SpawnTool(manager=self.subagents))
        # 如果配置了定时任务服务，注册 Cron 工具
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))

    async def _connect_mcp(self) -> None:
        """
        连接到配置的 MCP 服务器（一次性，惰性连接）。

        MCP（Model Context Protocol）是一种协议，
        允许 AI 与外部工具和服务通信。

        为什么需要惰性连接？
        ------------------
        1. 性能优化：只在需要时才建立连接
        2. 容错处理：连接失败不影响主功能
        3. 资源节约：不使用时不占用资源

        连接流程：
        --------
        1. 检查是否已连接或正在连接
        2. 创建异步上下文栈
        3. 连接所有配置的 MCP 服务器
        4. 注册 MCP 工具到工具注册表
        """
        # 如果已连接或正在连接，或没有配置 MCP 服务器，直接返回
        if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
            return
        self._mcp_connecting = True
        from nanobot.agent.tools.mcp import connect_mcp_servers  # 导入 MCP 连接函数
        try:
            # 创建异步上下文栈
            self._mcp_stack = AsyncExitStack()
            await self._mcp_stack.__aenter__()
            # 连接 MCP 服务器并注册工具
            await connect_mcp_servers(self._mcp_servers, self.tools, self._mcp_stack)
            self._mcp_connected = True
        except Exception as e:
            # 记录错误日志
            logger.error("Failed to connect MCP servers (will retry next message): {}", e)
            # 清理上下文栈
            if self._mcp_stack:
                try:
                    await self._mcp_stack.aclose()
                except Exception:
                    pass
                self._mcp_stack = None
        finally:
            self._mcp_connecting = False

    def _set_tool_context(self, channel: str, chat_id: str, message_id: str | None = None) -> None:
        """
        更新所有需要路由信息的工具的上下文。

        为什么需要设置工具上下文？
        -----------------------
        某些工具（如 message、spawn、cron）需要知道：
        - channel: 消息来自哪个渠道
        - chat_id: 消息来自哪个聊天
        - message_id: 消息 ID（用于回复）

        这样工具才能正确发送消息到正确的地方。

        Args:
            channel: 渠道名称
            chat_id: 聊天 ID
            message_id: 消息 ID（可选，仅 message 工具需要）
        """
        # 遍历需要上下文的工具
        for name in ("message", "spawn", "cron"):
            if tool := self.tools.get(name):
                if hasattr(tool, "set_context"):
                    # message 工具需要 message_id，其他不需要
                    tool.set_context(channel, chat_id, *([message_id] if name == "message" else []))

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """
        移除某些模型嵌入在内容中的 <think>...</think> 块。

        为什么需要移除 <think> 块？
        ---------------------
        某些思考模型（如 DeepSeek-R1）会在回复中包含思考过程：
        <think>
        这是模型的内部思考...
        </think>

        这是最终回复内容...

        思考过程对调试有用，但不应展示给用户。

        Args:
            text: 原始文本

        Returns:
            str | None: 移除思考块后的文本
        """
        if not text:
            return None
        # 使用正则表达式移除 <think>...</think> 块
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """
        将工具调用格式化为简洁提示。

        例如：'web_search("query")'

        为什么需要工具提示？
        -----------------
        - 实时反馈：让用户知道 AI 正在做什么
        - 进度显示：在流式响应中显示工具调用
        - 简洁性：只显示关键信息，不显示完整参数

        Args:
            tool_calls: 工具调用列表

        Returns:
            str: 格式化后的工具提示
        """
        def _fmt(tc):
            # 处理参数（可能是列表或字典）
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            # 获取第一个参数值
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            # 如果参数过长，截断显示
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'
        # 将所有工具调用格式化为字符串
        return ", ".join(_fmt(tc) for tc in tool_calls)

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
    ) -> tuple[str | None, list[str], list[dict]]:
        """
        运行 Agent 迭代循环。

        这是 Agent 的核心执行逻辑：
        1. 调用 LLM
        2. 检查是否有工具调用
        3. 执行工具
        4. 将结果反馈给 LLM
        5. 重复直到完成或达到最大迭代次数

        迭代示例：
        --------
        用户："今天北京的天气怎么样？"

        迭代 1:
        - LLM → 决定调用 web_search 工具
        - 执行：web_search("北京 天气")
        - 结果："北京今天晴天，气温 25 度"

        迭代 2:
        - LLM → 整合结果，生成回复
        - 回复："北京今天晴天，气温 25 度"

        Args:
            initial_messages: 初始消息列表
            on_progress: 进度回调函数（可选）
                用于流式显示思考和工具调用

        Returns:
            tuple[str | None, list[str], list[dict]]:
                - 最终回复内容
                - 使用的工具列表
                - 所有消息历史
        """
        messages = initial_messages  # 消息历史
        iteration = 0  # 迭代计数器
        final_content = None  # 最终回复内容
        tools_used: list[str] = []  # 记录使用的工具

        # 迭代循环，直到达到最大迭代次数
        while iteration < self.max_iterations:
            iteration += 1

            # 获取工具定义（告诉 LLM 可用哪些工具）
            tool_defs = self.tools.get_definitions()

            # 调用 LLM
            response = await self.provider.chat_with_retry(
                messages=messages,
                tools=tool_defs,
                model=self.model,
            )

            # 检查是否有工具调用
            if response.has_tool_calls:
                # 如果有进度回调，发送思考内容和工具提示
                if on_progress:
                    # 移除思考块
                    thought = self._strip_think(response.content)
                    if thought:
                        await on_progress(thought)
                    # 发送工具调用提示
                    await on_progress(self._tool_hint(response.tool_calls), tool_hint=True)

                # 将工具调用转换为 OpenAI 格式
                tool_call_dicts = [
                    tc.to_openai_tool_call()
                    for tc in response.tool_calls
                ]
                # 将助手消息（含工具调用）添加到历史
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts,
                    reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )

                # 执行每个工具调用
                for tool_call in response.tool_calls:
                    tools_used.append(tool_call.name)  # 记录使用的工具
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info("Tool call: {}({})", tool_call.name, args_str[:200])
                    # 执行工具
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    # 将工具结果添加到历史
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # 没有工具调用，处理最终回复
                clean = self._strip_think(response.content)
                # 错误响应不保存到会话历史——防止污染上下文导致永久 400 循环
                if response.finish_reason == "error":
                    logger.error("LLM returned error: {}", (clean or "")[:200])
                    final_content = clean or "Sorry, I encountered an error calling the AI model."
                    break
                # 将助手消息添加到历史
                messages = self.context.add_assistant_message(
                    messages, clean, reasoning_content=response.reasoning_content,
                    thinking_blocks=response.thinking_blocks,
                )
                final_content = clean
                break

        # 如果达到最大迭代次数仍未完成
        if final_content is None and iteration >= self.max_iterations:
            logger.warning("Max iterations ({}) reached", self.max_iterations)
            final_content = (
                f"I reached the maximum number of tool call iterations ({self.max_iterations}) "
                "without completing the task. You can try breaking the task into smaller steps."
            )

        return final_content, tools_used, messages

    async def run(self) -> None:
        """
        运行 Agent 循环，将消息分发为任务以保持对 /stop 的响应。

        这是 Agent 的主循环，持续监听消息总线：
        1. 从消息总线接收消息
        2. 检查是否是命令（/stop、/restart）
        3. 否则创建任务处理消息
        4. 将任务添加到活跃任务列表

        为什么使用任务分发？
        -----------------
        1. 并发性：多个消息可以同时处理
        2. 响应性：/stop 命令可以立即响应
        3. 隔离性：任务之间互不影响

        示例：
            >>> await agent_loop.run()
            # 开始监听消息总线...
        """
        self._running = True  # 设置运行标志
        # 连接 MCP 服务器（如果配置）
        await self._connect_mcp()
        logger.info("Agent loop started")

        # 主循环
        while self._running:
            try:
                # 从消息总线消费消息（1 秒超时）
                msg = await asyncio.wait_for(self.bus.consume_inbound(), timeout=1.0)
            except asyncio.TimeoutError:
                # 超时继续循环
                continue

            # 检查是否是命令
            cmd = msg.content.strip().lower()
            if cmd == "/stop":
                # 处理停止命令
                await self._handle_stop(msg)
            elif cmd == "/restart":
                # 处理重启命令
                await self._handle_restart(msg)
            else:
                # 创建任务处理消息
                task = asyncio.create_task(self._dispatch(msg))
                # 添加到活跃任务列表
                self._active_tasks.setdefault(msg.session_key, []).append(task)
                # 任务完成后从列表中移除
                task.add_done_callback(lambda t, k=msg.session_key: self._active_tasks.get(k, []) and self._active_tasks[k].remove(t) if t in self._active_tasks.get(k, []) else None)

    async def _handle_stop(self, msg: InboundMessage) -> None:
        """
        取消会话的所有活跃任务和子 Agent。

        这个函数用于响应用户的 /stop 命令，
        停止当前正在执行的任务。

        Args:
            msg: 入站消息（包含会话信息）
        """
        # 获取会话的活跃任务
        tasks = self._active_tasks.pop(msg.session_key, [])
        # 取消未完成的任务
        cancelled = sum(1 for t in tasks if not t.done() and t.cancel())
        # 等待所有任务完成
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        # 取消子 Agent
        sub_cancelled = await self.subagents.cancel_by_session(msg.session_key)
        # 计算总取消数量
        total = cancelled + sub_cancelled
        # 发送确认消息
        content = f"Stopped {total} task(s)." if total else "No active task to stop."
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=content,
        ))

    async def _handle_restart(self, msg: InboundMessage) -> None:
        """
        通过 os.execv 原地重启进程。

        为什么使用 os.execv？
        ------------------
        os.execv 会用新进程替换当前进程，
        实现"原地重启"而不需要外部脚本。

        Args:
            msg: 入站消息
        """
        # 发送重启通知
        await self.bus.publish_outbound(OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content="Restarting...",
        ))

        async def _do_restart():
            # 等待 1 秒让消息发送完成
            await asyncio.sleep(1)
            # 原地重启进程
            # sys.executable: Python 解释器路径
            # sys.argv: 命令行参数
            os.execv(sys.executable, [sys.executable] + sys.argv)

        # 创建重启任务
        asyncio.create_task(_do_restart())

    async def _dispatch(self, msg: InboundMessage) -> None:
        """
        在全局锁下处理消息。

        为什么需要全局锁？
        ----------------
        _processing_lock 确保同一时间只处理一个消息，
        防止并发处理导致状态混乱。

        Args:
            msg: 入站消息
        """
        async with self._processing_lock:
            try:
                # 处理消息
                response = await self._process_message(msg)
                # 如果有响应，发送
                if response is not None:
                    await self.bus.publish_outbound(response)
                # CLI 渠道的特殊处理
                elif msg.channel == "cli":
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel, chat_id=msg.chat_id,
                        content="", metadata=msg.metadata or {},
                    ))
            except asyncio.CancelledError:
                # 任务被取消
                logger.info("Task cancelled for session {}", msg.session_key)
                raise
            except Exception:
                # 处理异常
                logger.exception("Error processing message for session {}", msg.session_key)
                await self.bus.publish_outbound(OutboundMessage(
                    channel=msg.channel, chat_id=msg.chat_id,
                    content="Sorry, I encountered an error.",
                ))

    async def close_mcp(self) -> None:
        """
        关闭 MCP 连接。

        在 AgentLoop 关闭时调用，清理 MCP 资源。
        """
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except (RuntimeError, BaseExceptionGroup):
                # MCP SDK 取消范围清理可能报错但无害
                pass
            self._mcp_stack = None

    def stop(self) -> None:
        """
        停止 Agent 循环。

        设置 _running 标志为 False，主循环会退出。
        """
        self._running = False
        logger.info("Agent loop stopping")

    async def _process_message(
        self,
        msg: InboundMessage,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> OutboundMessage | None:
        """
        处理单个入站消息并返回响应。

        这是消息处理的核心逻辑：

        处理流程：
        --------
        1. 系统消息特殊处理（从 chat_id 解析来源）
        2. 获取或创建会话
        3. 检查斜杠命令（/new、/help）
        4. 记忆巩固
        5. 设置工具上下文
        6. 获取会话历史
        7. 构建消息上下文
        8. 运行 Agent 循环
        9. 保存回合到会话
        10. 返回响应

        Args:
            msg: 入站消息
            session_key: 会话密钥（可选，默认使用 msg.session_key）
            on_progress: 进度回调函数（可选）

        Returns:
            OutboundMessage | None: 出站消息或 None
        """
        # 系统消息：从 chat_id 解析来源 ("channel:chat_id")
        if msg.channel == "system":
            # 解析渠道和聊天 ID
            channel, chat_id = (msg.chat_id.split(":", 1) if ":" in msg.chat_id
                                else ("cli", msg.chat_id))
            logger.info("Processing system message from {}", msg.sender_id)
            # 生成会话密钥
            key = f"{channel}:{chat_id}"
            # 获取或创建会话
            session = self.sessions.get_or_create(key)
            # 记忆巩固
            await self.memory_consolidator.maybe_consolidate_by_tokens(session)
            # 设置工具上下文
            self._set_tool_context(channel, chat_id, msg.metadata.get("message_id"))
            # 获取会话历史
            history = session.get_history(max_messages=0)
            # 构建消息上下文
            messages = self.context.build_messages(
                history=history,
                current_message=msg.content, channel=channel, chat_id=chat_id,
            )
            # 运行 Agent 循环
            final_content, _, all_msgs = await self._run_agent_loop(messages)
            # 保存回合到会话
            self._save_turn(session, all_msgs, 1 + len(history))
            self.sessions.save(session)
            # 再次记忆巩固
            await self.memory_consolidator.maybe_consolidate_by_tokens(session)
            # 返回响应
            return OutboundMessage(channel=channel, chat_id=chat_id,
                                  content=final_content or "Background task completed.")

        # 日志记录（预览消息内容）
        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info("Processing message from {}:{}: {}", msg.channel, msg.sender_id, preview)

        # 获取会话密钥
        key = session_key or msg.session_key
        # 获取或创建会话
        session = self.sessions.get_or_create(key)

        # 处理斜杠命令
        cmd = msg.content.strip().lower()
        if cmd == "/new":
            # 开启新会话
            try:
                # 归档未巩固的记忆
                if not await self.memory_consolidator.archive_unconsolidated(session):
                    return OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content="Memory archival failed, session not cleared. Please try again.",
                    )
            except Exception:
                logger.exception("/new archival failed for {}", session.key)
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="Memory archival failed, session not cleared. Please try again.",
                )

            # 清空会话
            session.clear()
            self.sessions.save(session)
            self.sessions.invalidate(session.key)
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id,
                                  content="New session started.")
        if cmd == "/help":
            # 显示帮助信息
            lines = [
                "🐈 nanobot commands:",
                "/new — Start a new conversation",
                "/stop — Stop the current task",
                "/restart — Restart the bot",
                "/help — Show available commands",
            ]
            return OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content="\n".join(lines),
            )
        # 记忆巩固
        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

        # 设置工具上下文
        self._set_tool_context(msg.channel, msg.chat_id, msg.metadata.get("message_id"))
        # 通知消息工具新回合开始
        if message_tool := self.tools.get("message"):
            if isinstance(message_tool, MessageTool):
                message_tool.start_turn()

        # 获取会话历史
        history = session.get_history(max_messages=0)
        # 构建消息上下文
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel, chat_id=msg.chat_id,
        )

        # 定义进度回调函数
        async def _bus_progress(content: str, *, tool_hint: bool = False) -> None:
            # 创建元数据
            meta = dict(msg.metadata or {})
            meta["_progress"] = True
            meta["_tool_hint"] = tool_hint
            # 发布进度消息
            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id, content=content, metadata=meta,
            ))

        # 运行 Agent 循环
        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages, on_progress=on_progress or _bus_progress,
        )

        # 如果没有最终内容，设置默认
        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        # 保存回合到会话
        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)
        # 记忆巩固
        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

        # 如果消息工具已发送消息，不再返回响应
        if (mt := self.tools.get("message")) and isinstance(mt, MessageTool) and mt._sent_in_turn:
            return None

        # 日志记录（预览响应内容）
        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info("Response to {}:{}: {}", msg.channel, msg.sender_id, preview)
        # 返回响应
        return OutboundMessage(
            channel=msg.channel, chat_id=msg.chat_id, content=final_content,
            metadata=msg.metadata or {},
        )

    def _save_turn(self, session: Session, messages: list[dict], skip: int) -> None:
        """
        将新回合消息保存到会话，截断过大的工具结果。

        为什么需要截断工具结果？
        ---------------------
        某些工具返回大量数据（如列出整个目录），
        如果不截断会快速消耗上下文窗口。

        截断规则：
        --------
        - 工具结果 > 16,000 字符 → 截断并添加 "... (truncated)"

        Args:
            session: 会话对象
            messages: 消息列表
            skip: 跳过的消息数量（之前的消息已保存）
        """
        from datetime import datetime
        # 遍历新消息
        for m in messages[skip:]:
            entry = dict(m)
            role, content = entry.get("role"), entry.get("content")
            # 跳过空的助手消息（没有内容也没有工具调用）
            # 这些消息会污染会话上下文
            if role == "assistant" and not content and not entry.get("tool_calls"):
                continue
            # 工具结果截断
            if role == "tool" and isinstance(content, str) and len(content) > self._TOOL_RESULT_MAX_CHARS:
                entry["content"] = content[:self._TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"
            elif role == "user":
                # 处理用户消息
                if isinstance(content, str) and content.startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                    # 移除运行时上下文前缀，只保留用户文本
                    parts = content.split("\n\n", 1)
                    if len(parts) > 1 and parts[1].strip():
                        entry["content"] = parts[1]
                    else:
                        continue
                # 处理多模态消息
                if isinstance(content, list):
                    filtered = []
                    for c in content:
                        # 移除运行时上下文
                        if c.get("type") == "text" and isinstance(c.get("text"), str) and c["text"].startswith(ContextBuilder._RUNTIME_CONTEXT_TAG):
                            continue
                        # 将内联图片转为占位符
                        if (c.get("type") == "image_url"
                                and c.get("image_url", {}).get("url", "").startswith("data:image/")):
                            filtered.append({"type": "text", "text": "[image]"})
                        else:
                            filtered.append(c)
                    if not filtered:
                        continue
                    entry["content"] = filtered
            # 添加时间戳
            entry.setdefault("timestamp", datetime.now().isoformat())
            # 添加到会话
            session.messages.append(entry)
        # 更新会话时间
        session.updated_at = datetime.now()

    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """
        直接处理消息（用于 CLI 或定时任务）。

        这个函数用于直接调用，不通过消息总线。
        适用于：
        - CLI 交互模式
        - 定时任务触发

        Args:
            content: 消息内容
            session_key: 会话密钥
            channel: 渠道名称
            chat_id: 聊天 ID
            on_progress: 进度回调

        Returns:
            str: 响应内容
        """
        # 连接 MCP 服务器
        await self._connect_mcp()
        # 创建入站消息
        msg = InboundMessage(channel=channel, sender_id="user", chat_id=chat_id, content=content)
        # 处理消息
        response = await self._process_message(msg, session_key=session_key, on_progress=on_progress)
        return response.content if response else ""

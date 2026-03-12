# =============================================================================
# nanobot 子 Agent 管理器 - 详细中文注释版
# 文件路径：nanobot/agent/subagent.py
#
# 这个文件的作用是什么？
#
# 想象一下你在做一个复杂的任务，比如"帮我分析这个项目的所有 Python 文件，
# 写一份报告并保存到 docs 目录"。这个任务需要：
# 1. 扫描所有 .py 文件
# 2. 统计代码行数
# 3. 分析报告结构
# 4. 写入文件
#
# 如果让主 Agent 做这件事，它会一直被占用，无法回复你的其他消息。
#
# SubagentManager 就是为了解决这个问题：
# - 它可以在后台创建一个"子 Agent"来专门执行这个任务
# - 主 Agent 可以继续处理其他请求
# - 子 Agent 完成后，把结果报告给主 Agent
#
# 这就是"后台任务执行"的概念。
# =============================================================================

"""Subagent manager for background task execution."""

# =============================================================================
# 第一部分：导入模块
# =============================================================================

# --- 标准库导入 ---
import asyncio    # Python 异步编程库
# 什么是异步编程？
# 简单说就是"同时做多件事而不互相等待"
# 比如：主 Agent 在聊天时，子 Agent 在后台分析文件，互不干扰

import json       # JSON 数据处理库
# 用于解析和生成 JSON 格式的数据
# 比如工具调用的参数需要用 JSON 格式传递

import uuid       # 生成唯一 ID 的库
# UUID: Universally Unique Identifier
# 每个子 Agent 任务都需要一个唯一的 ID 来标识

from pathlib import Path  # 路径处理库
# 比 os.path 更好用的文件路径操作工具

from typing import Any    # 类型注解
# Any 表示"可以是任何类型"，用于复杂类型标注

# --- 第三方库导入 ---
from loguru import logger  # 日志库
# 用于记录程序运行日志，比如"子 Agent 已启动"、"任务完成"等

# --- 项目内部模块导入 ---
# 导入各种工具类，子 Agent 可以使用这些工具完成任务
from nanobot.agent.tools.filesystem import (
    EditFileTool,    # 编辑文件工具
    ListDirTool,     # 列出目录工具
    ReadFileTool,    # 读取文件工具
    WriteFileTool,   # 写入文件工具
)
from nanobot.agent.tools.registry import ToolRegistry  # 工具注册表
from nanobot.agent.tools.shell import ExecTool         # Shell 命令执行工具
from nanobot.agent.tools.web import (
    WebFetchTool,   # 网页抓取工具
    WebSearchTool,  # 网络搜索工具
)

# 导入消息总线相关
from nanobot.bus.events import InboundMessage  # 入站消息事件
from nanobot.bus.queue import MessageBus       # 消息队列

# 导入配置和提供商
from nanobot.config.schema import ExecToolConfig  # Shell 工具配置
from nanobot.providers.base import LLMProvider    # LLM 提供商基类

# 导入辅助函数
from nanobot.utils.helpers import build_assistant_message
# 用于构建助手消息的辅助函数


# =============================================================================
# 第二部分：SubagentManager 类定义
# =============================================================================

class SubagentManager:
    """
    管理后台子 Agent 的执行。

    核心职责：
    1. 创建子 Agent 任务（spawn）
    2. 运行子 Agent（_run_subagent）
    3. 发布子 Agent 结果（_announce_result）
    4. 管理任务生命周期（取消、清理）

    类比理解：
    SubagentManager 就像一个"项目经理"：
    - 你告诉项目经理"我要做一个 XX 任务"
    - 项目经理创建一个子团队（子 Agent）去执行
    - 子团队在后台工作，完成后汇报结果
    - 项目经理告诉你"任务完成了，结果是 XXX"
    """

    def __init__(
        self,
        # 参数 1: LLM 提供商，用于调用 AI 模型
        # 比如 OpenAIProvider、LiteLLMProvider 等
        provider: LLMProvider,

        # 参数 2: 工作空间路径
        # 子 Agent 操作文件的"根目录"，出于安全考虑会限制访问范围
        workspace: Path,

        # 参数 3: 消息总线
        # 用于组件间通信，子 Agent 通过它向主 Agent 汇报结果
        bus: MessageBus,

        # 参数 4: 模型名称（可选）
        # 如果不传，就使用提供商的默认模型
        model: str | None = None,

        # 参数 5: Brave 搜索 API 密钥（可选）
        # 用于网络搜索功能，没有则不能搜索
        brave_api_key: str | None = None,

        # 参数 6: 网络代理（可选）
        # 如果需要通过代理访问网络
        web_proxy: str | None = None,

        # 参数 7: Shell 工具配置（可选）
        # 控制 Shell 命令执行的超时时间、允许的命令等
        exec_config: "ExecToolConfig | None" = None,

        # 参数 8: 是否限制在工作空间内
        # True: 子 Agent 只能操作 workspace 目录下的文件
        # False: 可以访问任意文件（有安全风险）
        restrict_to_workspace: bool = False,
    ):
        """
        初始化子 Agent 管理器。

        初始化做了什么？
        1. 保存传入的配置参数
        2. 创建任务追踪字典（用于管理运行中的任务）
        """
        from nanobot.config.schema import ExecToolConfig

        # 保存配置参数
        self.provider = provider           # LLM 提供商
        self.workspace = workspace         # 工作空间
        self.bus = bus                     # 消息总线
        self.model = model or provider.get_default_model()  # 模型名称
        self.brave_api_key = brave_api_key  # 搜索 API 密钥
        self.web_proxy = web_proxy         # 网络代理
        self.exec_config = exec_config or ExecToolConfig()  # Shell 配置
        self.restrict_to_workspace = restrict_to_workspace  # 是否限制访问范围

        # --- 任务追踪数据结构 ---

        # 运行中的任务字典：task_id -> asyncio.Task
        # 用于追踪哪些任务正在运行，可以随时查询或取消
        self._running_tasks: dict[str, asyncio.Task[None]] = {}

        # 会话 - 任务映射：session_key -> {task_id, ...}
        # 一个会话可能有多个子任务，这个字典用于批量管理
        # 比如用户说"取消所有任务"，就可以通过这个字典找到所有相关任务
        self._session_tasks: dict[str, set[str]] = {}

    # =========================================================================
    # 第三部分：spawn 方法 - 创建子 Agent 任务
    # =========================================================================

    async def spawn(
        self,
        # 参数 1: 任务描述
        # 比如"分析所有 Python 文件并生成报告"
        task: str,

        # 参数 2: 任务标签（可选）
        # 用于显示的简短描述，不传则用任务内容的前 30 个字符
        label: str | None = None,

        # 参数 3: 来源渠道
        # 比如 "cli"（命令行）、"telegram"、"whatsapp" 等
        origin_channel: str = "cli",

        # 参数 4: 来源聊天 ID
        # 用于确定结果发送到哪个聊天
        origin_chat_id: str = "direct",

        # 参数 5: 会话密钥（可选）
        # 用于关联多个任务，便于批量管理
        session_key: str | None = None,
    ) -> str:
        """
        生成一个子 Agent 来执行后台任务。

        返回值：
        一个字符串，告知用户子 Agent 已启动

        这个方法做了什么？（一步步解析）
        1. 生成唯一的任务 ID
        2. 创建后台任务
        3. 注册任务到追踪字典
        4. 设置清理回调
        5. 返回启动消息
        """

        # --- 步骤 1: 生成唯一任务 ID ---
        # uuid.uuid4() 生成一个随机 UUID，如 "f47ac10b-58cc-4372-a567-0e02b2c3d479"
        # [:8] 取前 8 个字符，如 "f47ac10b"
        task_id = str(uuid.uuid4())[:8]

        # --- 步骤 2: 创建显示标签 ---
        # 如果没提供 label，就用 task 的前 30 个字符作为显示名
        # 如果 task 超过 30 字符，就加上 "..." 表示截断
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")

        # --- 步骤 3: 记录来源信息 ---
        # 用于确定结果发送回哪里
        origin = {"channel": origin_channel, "chat_id": origin_chat_id}

        # --- 步骤 4: 创建后台任务 ---
        # asyncio.create_task() 创建一个异步任务在后台运行
        # 它不会阻塞当前代码，任务会在后台独立执行
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin)
        )

        # --- 步骤 5: 注册任务到追踪字典 ---
        # 这样可以通过 task_id 找到正在运行的任务
        self._running_tasks[task_id] = bg_task

        # --- 步骤 6: 关联到会话（如果提供了 session_key）---
        # setdefault 的作用：如果 key 不存在，先创建一个空集合，然后返回集合
        # add 把 task_id 加入集合
        if session_key:
            self._session_tasks.setdefault(session_key, set()).add(task_id)

        # --- 步骤 7: 设置清理回调 ---
        # 回调函数：当任务完成（无论成功或失败）时自动执行
        def _cleanup(_: asyncio.Task) -> None:
            """
            清理已完成的任务记录。

            参数 _: 完成的 Task 对象（我们不需要用它，所以用 _ 表示忽略）
            """
            # 从运行任务字典中移除
            self._running_tasks.pop(task_id, None)  # None 是默认值，防止 key 不存在报错

            # 从会话任务映射中移除
            if session_key and (ids := self._session_tasks.get(session_key)):
                # := 是海象运算符（Python 3.8+），在表达式中赋值
                # 等价于：ids = self._session_tasks.get(session_key); if ids:
                ids.discard(task_id)  # discard 和 remove 类似，但元素不存在时不报错

                # 如果这个会话的任务都完成了，删除整个记录
                if not ids:  # 集合为空
                    del self._session_tasks[session_key]

        # add_done_callback 注册回调
        # 当任务完成时，_cleanup 函数会自动被调用
        bg_task.add_done_callback(_cleanup)

        # --- 步骤 8: 记录日志 ---
        # logger.info 记录信息级别日志
        # {} 是占位符，format 会自动填入参数
        logger.info("Spawned subagent [{}]: {}", task_id, display_label)

        # --- 步骤 9: 返回启动消息 ---
        # 告知用户子 Agent 已启动
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."

    # =========================================================================
    # 第四部分：_run_subagent 方法 - 执行子 Agent 任务
    # =========================================================================
    # 这是子 Agent 的核心执行逻辑

    async def _run_subagent(
        self,
        task_id: str,       # 任务 ID
        task: str,          # 任务描述
        label: str,         # 显示标签
        origin: dict[str, str],  # 来源信息
    ) -> None:
        """
        执行子 Agent 任务并宣布结果。

        这个方法做了什么？（详细流程）

        1. 创建工具集（没有消息工具和 spawn 工具）
           - 为什么没有？因为子 Agent 不需要发消息或创建更多子 Agent

        2. 构建系统提示词
           - 告诉子 Agent 它的身份和任务

        3. 运行 Agent 循环
           - 调用 LLM → 执行工具 → 循环，最多 15 次迭代

        4. 发布结果
           - 成功：发送结果给主 Agent
           - 失败：发送错误信息给主 Agent
        """

        logger.info("Subagent [{}] starting task: {}", task_id, label)

        try:
            # --- 步骤 1: 创建工具注册表 ---
            tools = ToolRegistry()

            # --- 步骤 2: 确定允许的目录 ---
            # 如果限制了工作空间，子 Agent 只能访问这个目录
            allowed_dir = self.workspace if self.restrict_to_workspace else None

            # --- 步骤 3: 注册文件操作工具 ---
            # 这些工具让子 Agent 可以读写文件
            tools.register(ReadFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(WriteFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(EditFileTool(workspace=self.workspace, allowed_dir=allowed_dir))
            tools.register(ListDirTool(workspace=self.workspace, allowed_dir=allowed_dir))

            # --- 步骤 4: 注册 Shell 执行工具 ---
            tools.register(ExecTool(
                working_dir=str(self.workspace),  # 工作目录
                timeout=self.exec_config.timeout,  # 超时时间（秒）
                restrict_to_workspace=self.restrict_to_workspace,  # 是否限制访问
                path_append=self.exec_config.path_append,  # 追加的 PATH
            ))

            # --- 步骤 5: 注册网络工具 ---
            tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
            tools.register(WebFetchTool(proxy=self.web_proxy))

            # 注意：没有注册 MessageTool 和 SpawnTool
            # 为什么？
            # - MessageTool: 子 Agent 不需要直接发消息，它通过 _announce_result 汇报
            # - SpawnTool: 防止子 Agent 无限创建更多子 Agent（会出乱子）

            # --- 步骤 6: 构建系统提示词 ---
            # 告诉子 Agent 它的身份、任务和环境
            system_prompt = self._build_subagent_prompt()

            # --- 步骤 7: 初始化消息列表 ---
            # 这是对话历史，格式是 OpenAI 兼容的格式
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},  # 系统提示
                {"role": "user", "content": task},  # 用户任务
            ]

            # --- 步骤 8: 运行 Agent 循环 ---
            max_iterations = 15  # 最多迭代 15 次，防止死循环
            iteration = 0        # 当前迭代计数
            final_result: str | None = None  # 最终结果

            # 主循环
            while iteration < max_iterations:
                iteration += 1

                # --- 调用 LLM ---
                # 发送当前消息历史和可用工具给 AI 模型
                # 模型会决定：是调用工具还是直接回复
                response = await self.provider.chat_with_retry(
                    messages=messages,           # 对话历史
                    tools=tools.get_definitions(),  # 工具定义列表
                    model=self.model,            # 模型名称
                )

                # --- 判断是否有工具调用 ---
                if response.has_tool_calls:
                    # 有工具调用，说明 AI 决定使用工具

                    # 将工具调用转换为 OpenAI 格式
                    tool_call_dicts = [
                        tc.to_openai_tool_call()
                        for tc in response.tool_calls
                    ]

                    # 将助手消息（包含工具调用）添加到历史
                    messages.append(build_assistant_message(
                        response.content or "",  # 助手回复内容
                        tool_calls=tool_call_dicts,  # 工具调用列表
                        reasoning_content=response.reasoning_content,  # 推理内容
                        thinking_blocks=response.thinking_blocks,  # 思考块
                    ))

                    # --- 执行工具 ---
                    for tool_call in response.tool_calls:
                        # 将参数转换为 JSON 字符串（用于日志）
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)

                        logger.debug(
                            "Subagent [{}] executing: {} with arguments: {}",
                            task_id,
                            tool_call.name,
                            args_str
                        )

                        # 执行工具
                        result = await tools.execute(tool_call.name, tool_call.arguments)

                        # 将工具结果添加到消息历史
                        # 这样 AI 可以看到工具执行的结果，决定下一步行动
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    # 没有工具调用，说明 AI 给出了最终回复
                    final_result = response.content
                    break  # 退出循环

            # --- 检查是否有结果 ---
            if final_result is None:
                # 理论上不应该发生，但以防万一
                final_result = "Task completed but no final response was generated."

            logger.info("Subagent [{}] completed successfully", task_id)

            # --- 发布成功结果 ---
            await self._announce_result(
                task_id, label, task, final_result, origin, "ok"
            )

        except Exception as e:
            # --- 异常处理 ---
            # 如果发生任何错误，记录日志并发布错误信息
            error_msg = f"Error: {str(e)}"
            logger.error("Subagent [{}] failed: {}", task_id, e)

            await self._announce_result(
                task_id, label, task, error_msg, origin, "error"
            )

    # =========================================================================
    # 第五部分：_announce_result 方法 - 发布结果
    # =========================================================================

    async def _announce_result(
        self,
        task_id: str,       # 任务 ID
        label: str,         # 显示标签
        task: str,          # 任务描述
        result: str,        # 执行结果
        origin: dict[str, str],  # 来源信息
        status: str,        # 状态："ok" 或 "error"
    ) -> None:
        """
        通过消息总线将子 Agent 结果通知给主 Agent。

        这个方法做了什么？
        1. 构建通知消息
        2. 通过消息总线发送给主 Agent
        3. 主 Agent 会处理这个消息并回复用户

        关键点：
        - 消息类型是 InboundMessage（入站消息）
        - channel 是 "system"，表示这是系统消息
        - 消息内容包含任务结果和一个提示，让主 Agent 自然地告诉用户
        """

        # 根据状态生成状态文本
        status_text = "completed successfully" if status == "ok" else "failed"

        # --- 构建通知内容 ---
        # 这是一个模板字符串，包含：
        # 1. 任务状态
        # 2. 任务描述
        # 3. 执行结果
        # 4. 给主 Agent 的提示（如何回复用户）
        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""

        # --- 创建入站消息 ---
        msg = InboundMessage(
            channel="system",  # 系统渠道
            sender_id="subagent",  # 发送者是子 Agent
            chat_id=f"{origin['channel']}:{origin['chat_id']}",  # 目标聊天
            content=announce_content,  # 消息内容
        )

        # --- 发布到消息总线 ---
        # 主 Agent 会订阅这个消息总线，收到后处理
        await self.bus.publish_inbound(msg)

        logger.debug(
            "Subagent [{}] announced result to {}:{}",
            task_id,
            origin['channel'],
            origin['chat_id']
        )

    # =========================================================================
    # 第六部分：_build_subagent_prompt 方法 - 构建系统提示词
    # =========================================================================

    def _build_subagent_prompt(self) -> str:
        """
        为子 Agent 构建系统提示词。

        系统提示词是什么？
        它是告诉 AI"你是谁"、"你能做什么"、"你的环境是什么"的一段话。

        比如给子 Agent 的提示词：
        - 你是一个子 Agent，负责完成特定任务
        - 你的工作空间是 XXX
        - 你可以使用这些技能...
        """
        from nanobot.agent.context import ContextBuilder
        from nanobot.agent.skills import SkillsLoader

        # --- 构建运行时上下文 ---
        # 包含当前时间、日期等信息
        time_ctx = ContextBuilder._build_runtime_context(None, None)

        # --- 构建提示词各部分 ---
        parts = [f"""# Subagent

{time_ctx}

You are a subagent spawned by the main agent to complete a specific task.
Stay focused on the assigned task. Your final response will be reported back to the main agent.

## Workspace
{self.workspace}"""]

        # --- 添加技能信息（如果有）---
        # SkillsLoader 读取工作空间中的 SKILL.md 文件
        skills_summary = SkillsLoader(self.workspace).build_skills_summary()
        if skills_summary:
            parts.append(
                f"## Skills\n\nRead SKILL.md with read_file to use a skill.\n\n{skills_summary}"
            )

        # --- 合并所有部分 ---
        return "\n\n".join(parts)

    # =========================================================================
    # 第七部分：任务管理方法
    # =========================================================================

    async def cancel_by_session(self, session_key: str) -> int:
        """
        取消指定会话的所有子 Agent。

        参数：
        session_key: 会话密钥，比如 "cli:direct"

        返回：
        取消的任务数量

        使用场景：
        用户说"取消所有任务"时，调用这个方法
        """
        # 找出这个会话所有正在运行的任务
        tasks = [
            self._running_tasks[tid]
            for tid in self._session_tasks.get(session_key, [])
            if tid in self._running_tasks and not self._running_tasks[tid].done()
        ]

        # 取消所有任务
        for t in tasks:
            t.cancel()  # Task.cancel() 是 asyncio 的取消方法

        # 等待所有任务清理完成
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return len(tasks)

    def get_running_count(self) -> int:
        """
        返回当前运行中的子 Agent 数量。

        使用场景：
        用户问"现在有多少任务在运行？"时调用
        """
        return len(self._running_tasks)

# =============================================================================
# nanobot CLI 命令行入口 - 详细中文注释版
# 文件路径：nanobot/cli/commands.py
# 作用：这是 nanobot 程序的"大门"，所有命令都从这里开始执行
# =============================================================================

"""
CLI commands for nanobot.
nanobot 的命令行界面
"""

# =============================================================================
# 第一部分：导入模块（Import）
# =============================================================================
# Python 程序开始时都需要导入需要的功能模块
# 就像做饭前要先准备好锅碗瓢盆一样

# --- 标准库导入（Python 自带的功能）---
import asyncio      # 异步编程库，用于同时处理多个任务（比如同时接收消息和处理消息）
import os           # 操作系统接口，可以访问环境变量、文件系统等
import select       # 用于监控多个文件描述符，这里用来检测键盘输入
import signal       # 信号处理，用于捕获 Ctrl+C 等中断信号
import sys          # 系统相关功能，比如判断操作系统类型、退出程序等
from pathlib import Path  # 路径处理库，比 os.path 更好用的文件路径操作工具

# --- Windows 兼容性处理 ---
# 这段代码是为了解决 Windows 系统下中文显示乱码的问题
if sys.platform == "win32":  # 如果是 Windows 系统
    if sys.stdout.encoding != "utf-8":  # 如果输出编码不是 UTF-8
        os.environ["PYTHONIOENCODING"] = "utf-8"  # 设置环境变量为 UTF-8
        try:
            # 重新配置标准输出和标准错误，使用 UTF-8 编码
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass  # 如果失败也不影响程序运行

# --- 第三方库导入（需要 pip 安装的包）---
import typer  # 命令行框架，快速创建命令行工具
# PromptSession：交互式输入会话，支持历史记录、自动补全等功能
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML  # 支持 HTML 格式的提示文本
from prompt_toolkit.history import FileHistory  # 文件历史存储，退出后历史记录不丢失
from prompt_toolkit.patch_stdout import patch_stdout  # 修复输出显示问题
from rich.console import Console  # 富文本控制台，可以输出彩色文字、表格等
from rich.markdown import Markdown  # Markdown 渲染，可以把 Markdown 文本美化显示
from rich.table import Table  # 表格组件
from rich.text import Text  # 文本组件

# --- 项目内部模块导入 ---
# 从 nanobot 包中导入版本号和 logo
from nanobot import __logo__, __version__
# 导入配置路径工具函数
from nanobot.config.paths import get_workspace_path
# 导入配置模型类
from nanobot.config.schema import Config
# 导入工作空间模板同步函数
from nanobot.utils.helpers import sync_workspace_templates

# =============================================================================
# 第二部分：创建应用实例和全局变量
# =============================================================================

# 创建 Typer 应用实例
# Typer 是一个命令行框架，类似 Flask 之于 Web 应用
app = typer.Typer(
    name="nanobot",  # 应用名称
    help=f"{__logo__} nanobot - Personal AI Assistant",  # 帮助信息
    no_args_is_help=True,  # 没有参数时自动显示帮助信息
)

# 创建控制台实例，用于输出彩色文字
console = Console()

# 定义退出命令集合
# 当用户输入这些命令时，程序会退出交互模式
# 使用集合（{}）而不是列表（[]）是因为集合的查找速度更快
EXIT_COMMANDS = {"exit", "quit", "/exit", "/quit", ":q"}

# =============================================================================
# 第三部分：终端输入处理相关函数
# =============================================================================
# 这些函数用于处理用户输入，保证良好的交互体验

# 全局变量：存储当前的输入会话实例
_PROMPT_SESSION: PromptSession | None = None
# 全局变量：保存终端的原始设置，用于退出时恢复
_SAVED_TERM_ATTRS = None


def _flush_pending_tty_input() -> None:
    """
    清除未读的键盘输入。

    为什么需要这个函数？
    当 AI 正在思考并输出内容时，用户可能会无意识地敲击键盘。
    这些按键会被缓存起来，在 AI 输出完后被程序读取，造成意外输入。
    这个函数就是用来清除这些"误触"的按键。

    技术细节：
    - TTY 是终端设备的缩写（Teletype）
    - tcflush 是 Unix/Linux 的终端控制函数
    """
    try:
        fd = sys.stdin.fileno()  # 获取标准输入的文件描述符
        if not os.isatty(fd):  # 如果不是终端设备（比如是管道输入）
            return  # 直接返回，不需要清除
    except Exception:
        return

    try:
        import termios  # Unix/Linux 终端控制模块
        # tcflush 清除输入队列，TCIFLUSH 表示清除已接收但未读取的数据
        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    # 备选方案：手动读取并丢弃数据
    try:
        while True:
            # select 用于检测是否有数据可读
            ready, _, _ = select.select([fd], [], [], 0)
            if not ready:  # 没有数据可读
                break
            if not os.read(fd, 4096):  # 读取并丢弃最多 4096 字节
                break
    except Exception:
        return


def _restore_terminal() -> None:
    """
    恢复终端到原始状态。

    为什么需要这个函数？
    程序运行时可能会修改终端的某些设置（比如关闭回显、改变输入模式等）。
    退出时如果不恢复，可能导致终端"异常"（比如输入不显示、需要按两次回车等）。
    """
    if _SAVED_TERM_ATTRS is None:  # 如果没有保存过设置
        return

    try:
        import termios
        # tcsetattr 设置终端属性
        # TCSADRAIN 表示等待输出队列空后再更改设置
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _SAVED_TERM_ATTRS)
    except Exception:
        pass


def _init_prompt_session() -> None:
    """
    初始化输入会话，创建带有历史记录的交互式输入环境。

    prompt_toolkit 是一个强大的交互式输入库，提供：
    - 历史记录（上下箭头翻看历史输入）
    - 语法高亮
    - 自动补全
    - 粘贴板支持
    """
    global _PROMPT_SESSION, _SAVED_TERM_ATTRS  # 声明使用全局变量

    # 保存终端当前状态，以便退出时恢复
    try:
        import termios
        _SAVED_TERM_ATTRS = termios.tcgetattr(sys.stdin.fileno())
    except Exception:
        pass

    # 获取 CLI 历史文件路径
    from nanobot.config.paths import get_cli_history_path
    history_file = get_cli_history_path()

    # 确保历史文件的父目录存在
    history_file.parent.mkdir(parents=True, exist_ok=True)

    # 创建输入会话
    _PROMPT_SESSION = PromptSession(
        history=FileHistory(str(history_file)),  # 使用文件存储历史记录
        enable_open_in_editor=False,  # 禁用在编辑器中打开
        multiline=False,  # 单行模式（按 Enter 直接提交）
    )


def _print_agent_response(response: str, render_markdown: bool) -> None:
    """
    打印 AI 助手的回复。

    参数：
    - response: AI 回复的文本内容
    - render_markdown: 是否渲染 Markdown 格式
    """
    content = response or ""  # 如果是 None 则用空字符串代替

    # 根据是否渲染 Markdown 来选择不同的显示方式
    body = Markdown(content) if render_markdown else Text(content)

    console.print()  # 空一行
    console.print(f"[cyan]{__logo__} nanobot[/cyan]")  # 打印带颜色的标题
    console.print(body)  # 打印回复内容
    console.print()  # 空一行


def _is_exit_command(command: str) -> bool:
    """
    判断是否是退出命令。

    参数：
    - command: 用户输入的命令
    """
    return command.lower() in EXIT_COMMANDS  # 转为小写后判断是否在退出命令集合中


async def _read_interactive_input_async() -> str:
    """
    异步读取用户输入。

    async/await 是 Python 的异步编程语法：
    - async def 定义异步函数
    - await 等待异步操作完成

    这个函数使用 prompt_toolkit 读取输入，支持：
    - 多行粘贴
    - 历史记录导航（上下箭头）
    - 干净的显示（无乱码）
    """
    if _PROMPT_SESSION is None:
        raise RuntimeError("Call _init_prompt_session() first")

    try:
        # patch_stdout 确保输出不会干扰输入显示
        with patch_stdout():
            # prompt_async 显示提示符并等待用户输入
            return await _PROMPT_SESSION.prompt_async(
                HTML("<b fg='ansiblue'>You:</b> "),  # 蓝色加粗的 "You:" 提示符
            )
    except EOFError as exc:
        # EOFError 通常由 Ctrl+D 触发，转为 KeyboardInterrupt 处理
        raise KeyboardInterrupt from exc


# =============================================================================
# 第四部分：版本回调和主回调
# =============================================================================

def version_callback(value: bool):
    """
    版本号回调函数。

    当用户运行 `nanobot --version` 时会被调用。
    """
    if value:  # 如果 --version 被指定
        console.print(f"{__logo__} nanobot v{__version__}")
        raise typer.Exit()  # 显示版本后退出


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True
    ),
):
    """
    主回调函数。

    @app.callback() 装饰器标记的是"全局回调"：
    - 在任何一个子命令执行前都会先运行这个函数
    - 通常用于处理全局选项（如 --version）

    is_eager=True 表示这个选项要优先处理
    """
    # 这个函数什么都不做，只是占位
    # 因为 --version 的回调已经处理了版本显示和退出
    pass


# =============================================================================
# 第五部分：初始化命令（onboard）
# =============================================================================

@app.command()
def onboard():
    """
    初始化 nanobot 配置和工作空间。

    这是用户第一次使用 nanobot 时必须运行的命令。
    它会：
    1. 创建配置文件
    2. 创建工作空间目录
    3. 复制模板文件
    """
    # 在函数内部导入模块是 Python 的一种优化技巧
    # 可以加快程序启动速度（只有真正用到时才导入）
    from nanobot.config.loader import get_config_path, load_config, save_config
    from nanobot.config.schema import Config

    config_path = get_config_path()  # 获取配置文件路径

    if config_path.exists():  # 如果配置文件已存在
        console.print(f"[yellow]Config already exists at {config_path}[/yellow]")
        console.print("  [bold]y[/bold] = 覆盖为默认值（会丢失现有设置）")
        console.print("  [bold]N[/bold] = 刷新配置（保留现有值并添加新字段）")

        if typer.confirm("Overwrite?"):  # 询问用户是否确认覆盖
            config = Config()  # 创建新的默认配置
            save_config(config)  # 保存到文件
            console.print(f"[green]✓[/green] Config reset to defaults at {config_path}")
        else:
            config = load_config()  # 加载现有配置
            save_config(config)  # 重新保存（会添加新字段）
            console.print(f"[green]✓[/green] Config refreshed at {config_path} (existing values preserved)")
    else:
        # 配置文件不存在，创建新的
        save_config(Config())
        console.print(f"[green]✓[/green] Created config at {config_path}")

    console.print("[dim]Config template now uses `maxTokens` + `contextWindowTokens`; `memoryWindow` is no longer a runtime setting.[/dim]")

    # 创建工作空间目录
    workspace = get_workspace_path()

    if not workspace.exists():  # 如果工作空间不存在
        workspace.mkdir(parents=True, exist_ok=True)  # 创建目录
        console.print(f"[green]✓[/green] Created workspace at {workspace}")

    # 同步模板文件到工作空间
    sync_workspace_templates(workspace)

    # 显示成功信息和下一步指引
    console.print(f"\n{__logo__} nanobot is ready!")
    console.print("\nNext steps:")
    console.print("  1. Add your API key to [cyan]~/.nanobot/config.json[/cyan]")
    console.print("     Get one at: https://openrouter.ai/keys")
    console.print("  2. Chat: [cyan]nanobot agent -m \"Hello!\"[/cyan]")
    console.print("\n[dim]Want Telegram/WhatsApp? See: https://github.com/HKUDS/nanobot#-chat-apps[/dim]")


# =============================================================================
# 第六部分：LLM 提供商创建函数
# =============================================================================
# 这个函数根据配置文件创建合适的 AI 模型连接

def _make_provider(config: Config):
    """
    根据配置创建合适的 LLM（大语言模型）提供商实例。

    什么是 LLM Provider？
    简单说，Provider 就是连接不同 AI 模型的"适配器"。
    nanobot 支持多种 AI 模型（OpenAI、Azure、Anthropic 等），
    每种模型的 API 接口不一样，Provider 就是统一这些接口的中间层。
    """
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.openai_codex_provider import OpenAICodexProvider
    from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

    model = config.agents.defaults.model  # 获取配置的模型名称
    provider_name = config.get_provider_name(model)  # 获取提供商名称
    p = config.get_provider(model)  # 获取该模型的配置

    # --- 情况 1: OpenAI Codex（需要 OAuth 认证）---
    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        provider = OpenAICodexProvider(default_model=model)

    # --- 情况 2: 自定义提供商（兼容 OpenAI 接口的其他服务）---
    # 比如一些自建的 AI 服务，虽然接口和 OpenAI 一样但不是 OpenAI 官方
    elif provider_name == "custom":
        from nanobot.providers.custom_provider import CustomProvider
        provider = CustomProvider(
            api_key=p.api_key if p else "no-key",  # API 密钥，如果没有就用占位符
            api_base=config.get_api_base(model) or "http://localhost:8000/v1",  # API 地址
            default_model=model,
        )

    # --- 情况 3: Azure OpenAI（微软 Azure 云上的 OpenAI 服务）---
    # Azure OpenAI 需要额外的 api_base 配置
    elif provider_name == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            console.print("[red]Error: Azure OpenAI requires api_key and api_base.[/red]")
            console.print("Set them in ~/.nanobot/config.json under providers.azure_openai section")
            console.print("Use the model field to specify the deployment name.")
            raise typer.Exit(1)  # 配置错误，退出程序
        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )

    # --- 情况 4: 其他提供商（通过 LiteLLM 支持）---
    # LiteLLM 是一个统一的 AI 模型接口，支持 100+ 种模型
    else:
        from nanobot.providers.litellm_provider import LiteLLMProvider
        from nanobot.providers.registry import find_by_name
        spec = find_by_name(provider_name)

        # 检查 API 密钥配置
        # bedrock/ 开头的模型使用 AWS 认证，不需要 API 密钥
        # OAuth 提供商和本地部署也不需要传统 API 密钥
        if not model.startswith("bedrock/") and not (p and p.api_key) and not (spec and (spec.is_oauth or spec.is_local)):
            console.print("[red]Error: No API key configured.[/red]")
            console.print("Set one in ~/.nanobot/config.json under providers section")
            raise typer.Exit(1)

        provider = LiteLLMProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            provider_name=provider_name,
        )

    # 设置生成参数（温度、最大 token 数、推理努力程度）
    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,  # 温度：控制输出的随机性
        max_tokens=defaults.max_tokens,  # 最大 token 数：限制回复长度
        reasoning_effort=defaults.reasoning_effort,  # 推理努力：控制思考深度
    )
    return provider


def _load_runtime_config(config: str | None = None, workspace: str | None = None) -> Config:
    """
    加载运行时配置，可选地覆盖工作空间设置。

    参数：
    - config: 配置文件路径（可选，不传则用默认路径）
    - workspace: 工作空间路径（可选，会覆盖配置中的设置）
    """
    from nanobot.config.loader import load_config, set_config_path

    config_path = None

    if config:  # 如果指定了配置文件
        config_path = Path(config).expanduser().resolve()  # 转换为绝对路径
        if not config_path.exists():  # 检查文件是否存在
            console.print(f"[red]Error: Config file not found: {config_path}[/red]")
            raise typer.Exit(1)  # 文件不存在，退出
        set_config_path(config_path)  # 设置配置路径
        console.print(f"[dim]Using config: {config_path}[/dim]")

    loaded = load_config(config_path)  # 加载配置

    if workspace:  # 如果指定了工作空间
        loaded.agents.defaults.workspace = workspace  # 覆盖工作空间设置

    return loaded


def _print_deprecated_memory_window_notice(config: Config) -> None:
    """
    当使用旧版配置时显示警告。

    旧版配置使用 `memoryWindow` 参数，新版已废弃，改用 `contextWindowTokens`。
    """
    if config.agents.defaults.should_warn_deprecated_memory_window:
        console.print(
            "[yellow]Hint:[/yellow] Detected deprecated `memoryWindow` without "
            "`contextWindowTokens`. `memoryWindow` is ignored; run "
            "[cyan]nanobot onboard[/cyan] to refresh your config template."
        )


# =============================================================================
# 第七部分：网关命令（gateway）
# =============================================================================
# 网关模式是 nanobot 的"服务器模式"，可以同时连接多个聊天平台

@app.command()
def gateway(
    port: int | None = typer.Option(None, "--port", "-p", help="Gateway port"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config file"),
):
    """
    启动 nanobot 网关。

    网关模式 vs 命令行模式：
    - gateway：服务器模式，持续运行，连接 Telegram/WhatsApp 等外部平台
    - agent：交互模式，一对一聊天，适合本地使用
    """
    # 导入需要的模块（网关模式需要更多组件）
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.channels.manager import ChannelManager
    from nanobot.config.paths import get_cron_dir
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.session.manager import SessionManager

    # 如果开启详细输出，设置日志级别为 DEBUG
    if verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    # 加载配置
    config = _load_runtime_config(config, workspace)
    _print_deprecated_memory_window_notice(config)
    port = port if port is not None else config.gateway.port  # 优先使用命令行参数

    console.print(f"{__logo__} Starting nanobot gateway on port {port}...")
    sync_workspace_templates(config.workspace_path)

    # 创建核心组件
    bus = MessageBus()  # 消息总线：组件间通信的"邮局"
    provider = _make_provider(config)  # AI 模型提供商
    session_manager = SessionManager(config.workspace_path)  # 会话管理器

    # --- 创建定时任务服务 ---
    cron_store_path = get_cron_dir() / "jobs.json"  # 定时任务存储路径
    cron = CronService(cron_store_path)  # 定时任务服务

    # --- 创建 Agent 主循环 ---
    agent = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        brave_api_key=config.tools.web.search.api_key or None,  # 网络搜索 API 密钥
        web_proxy=config.tools.web.proxy or None,  # 网络代理
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,  # 限制在工作空间内操作
        session_manager=session_manager,
        mcp_servers=config.tools.mcp_servers,  # MCP 服务器配置
        channels_config=config.channels,  # 渠道配置
    )

    # --- 设置定时任务回调 ---
    # 当定时任务触发时，通过这个函数执行
    async def on_cron_job(job: CronJob) -> str | None:
        """执行定时任务。"""
        from nanobot.agent.tools.cron import CronTool
        from nanobot.agent.tools.message import MessageTool

        # 构建提醒消息
        reminder_note = (
            "[Scheduled Task] Timer finished.\n\n"
            f"Task '{job.name}' has been triggered.\n"
            f"Scheduled instruction: {job.payload.message}"
        )

        # 防止 Agent 在执行定时任务时又创建新的定时任务（避免死循环）
        cron_tool = agent.tools.get("cron")
        cron_token = None
        if isinstance(cron_tool, CronTool):
            cron_token = cron_tool.set_cron_context(True)  # 设置"正在执行定时任务"标志

        try:
            response = await agent.process_direct(
                reminder_note,
                session_key=f"cron:{job.id}",  # 使用定时任务 ID 作为会话 key
                channel=job.payload.channel or "cli",  # 发送到指定渠道
                chat_id=job.payload.to or "direct",
            )
        finally:
            # 无论成功失败都要恢复原状态
            if isinstance(cron_tool, CronTool) and cron_token is not None:
                cron_tool.reset_cron_context(cron_token)

        # 检查消息是否已发送
        message_tool = agent.tools.get("message")
        if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
            return response

        # 如果需要发送回复，发布到消息总线
        if job.payload.deliver and job.payload.to and response:
            from nanobot.bus.events import OutboundMessage
            await bus.publish_outbound(OutboundMessage(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                content=response
            ))
        return response

    cron.on_job = on_cron_job  # 设置回调

    # --- 创建渠道管理器 ---
    channels = ChannelManager(config, bus)

    # --- 选择心跳消息发送目标 ---
    # 心跳服务定期执行任务，需要知道发送到哪个渠道
    def _pick_heartbeat_target() -> tuple[str, str]:
        """选择一个有效的渠道/聊天目标。"""
        enabled = set(channels.enabled_channels)

        # 优先选择最近使用的非 CLI 会话
        for item in session_manager.list_sessions():
            key = item.get("key") or ""
            if ":" not in key:  # 无效的 key 格式
                continue
            channel, chat_id = key.split(":", 1)  # 解析 channel:chat_id 格式
            if channel in {"cli", "system"}:  # 跳过内部渠道
                continue
            if channel in enabled and chat_id:  # 渠道已启用且有 chat_id
                return channel, chat_id

        # 降级方案：返回 CLI
        return "cli", "direct"

    # --- 创建心跳服务 ---
    # 心跳服务定期执行一些后台任务（比如检查待办事项、整理记忆等）
    async def on_heartbeat_execute(tasks: str) -> str:
        """执行心跳任务。"""
        channel, chat_id = _pick_heartbeat_target()

        async def _silent(*_args, **_kwargs):
            pass  # 空函数，用于禁用进度输出

        return await agent.process_direct(
            tasks,
            session_key="heartbeat",
            channel=channel,
            chat_id=chat_id,
            on_progress=_silent,  # 不显示进度
        )

    async def on_heartbeat_notify(response: str) -> None:
        """将心跳响应发送给用户。"""
        from nanobot.bus.events import OutboundMessage
        channel, chat_id = _pick_heartbeat_target()
        if channel == "cli":
            return  # CLI 渠道不发送通知
        await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=response))

    hb_cfg = config.gateway.heartbeat
    heartbeat = HeartbeatService(
        workspace=config.workspace_path,
        provider=provider,
        model=agent.model,
        on_execute=on_heartbeat_execute,
        on_notify=on_heartbeat_notify,
        interval_s=hb_cfg.interval_s,  # 心跳间隔（秒）
        enabled=hb_cfg.enabled,  # 是否启用
    )

    # 显示启动信息
    if channels.enabled_channels:
        console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
    else:
        console.print("[yellow]Warning: No channels enabled[/yellow]")

    cron_status = cron.status()
    if cron_status["jobs"] > 0:
        console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")

    console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")

    # --- 主运行循环 ---
    async def run():
        try:
            await cron.start()  # 启动定时任务服务
            await heartbeat.start()  # 启动心跳服务
            # 同时运行 Agent 和所有渠道
            await asyncio.gather(
                agent.run(),
                channels.start_all(),
            )
        except KeyboardInterrupt:  # 用户按 Ctrl+C
            console.print("\nShutting down...")
        finally:
            # 清理资源
            await agent.close_mcp()  # 关闭 MCP 连接
            heartbeat.stop()  # 停止心跳
            cron.stop()  # 停止定时任务
            agent.stop()  # 停止 Agent
            await channels.stop_all()  # 停止所有渠道

    asyncio.run(run())  # 启动异步运行循环


# =============================================================================
# 第八部分：Agent 命令（核心交互功能）
# =============================================================================

@app.command()
def agent(
    message: str = typer.Option(None, "--message", "-m", help="Message to send to the agent"),
    session_id: str = typer.Option("cli:direct", "--session", "-s", help="Session ID"),
    workspace: str | None = typer.Option(None, "--workspace", "-w", help="Workspace directory"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
    markdown: bool = typer.Option(True, "--markdown/--no-markdown", help="Render assistant output as Markdown"),
    logs: bool = typer.Option(False, "--logs/--no-logs", help="Show nanobot runtime logs during chat"),
):
    """
    与 Agent 直接交互。

    支持两种模式：
    1. 单次消息模式：nanobot agent -m "你好"
    2. 交互模式：nanobot（然后持续对话）
    """
    from loguru import logger
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.config.paths import get_cron_dir
    from nanobot.cron.service import CronService

    # 加载配置
    config = _load_runtime_config(config, workspace)
    _print_deprecated_memory_window_notice(config)
    sync_workspace_templates(config.workspace_path)

    # 创建核心组件
    bus = MessageBus()
    provider = _make_provider(config)

    # 创建定时任务服务（CLI 模式不需要回调）
    cron_store_path = get_cron_dir() / "jobs.json"
    cron = CronService(cron_store_path)

    # 设置日志
    if logs:
        logger.enable("nanobot")  # 启用 nanobot 日志
    else:
        logger.disable("nanobot")  # 禁用 nanobot 日志

    # 创建 Agent 主循环
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=config.workspace_path,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        brave_api_key=config.tools.web.search.api_key or None,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
    )

    # --- 思考状态指示器 ---
    # 当 AI 正在思考时显示动画
    def _thinking_ctx():
        if logs:
            from contextlib import nullcontext
            return nullcontext()  # 有日志时不显示动画（避免干扰）
        # 显示"正在思考..."动画
        return console.status("[dim]nanobot is thinking...[/dim]", spinner="dots")

    # --- 进度输出函数 ---
    async def _cli_progress(content: str, *, tool_hint: bool = False) -> None:
        """显示 Agent 执行进度。"""
        ch = agent_loop.channels_config
        # 根据配置决定是否显示提示
        if ch and tool_hint and not ch.send_tool_hints:
            return
        if ch and not tool_hint and not ch.send_progress:
            return
        console.print(f"  [dim]↳ {content}[/dim]")

    # --- 判断是单次消息还是交互模式 ---
    if message:
        # 单次消息模式：发送一条消息，得到回复，然后退出
        async def run_once():
            with _thinking_ctx():
                response = await agent_loop.process_direct(message, session_id, on_progress=_cli_progress)
            _print_agent_response(response, render_markdown=markdown)
            await agent_loop.close_mcp()

        asyncio.run(run_once())
    else:
        # 交互模式：持续对话
        from nanobot.bus.events import InboundMessage
        _init_prompt_session()  # 初始化输入会话
        console.print(f"{__logo__} Interactive mode (type [bold]exit[/bold] or [bold]Ctrl+C[/bold] to quit)\n")

        # 解析 session_id（格式：channel:chat_id）
        if ":" in session_id:
            cli_channel, cli_chat_id = session_id.split(":", 1)
        else:
            cli_channel, cli_chat_id = "cli", session_id

        # --- 信号处理器 ---
        # 捕获 Ctrl+C 等信号，优雅退出
        def _handle_signal(signum, frame):
            sig_name = signal.Signals(signum).name
            _restore_terminal()  # 恢复终端设置
            console.print(f"\nReceived {sig_name}, goodbye!")
            sys.exit(0)

        signal.signal(signal.SIGINT, _handle_signal)   # Ctrl+C
        signal.signal(signal.SIGTERM, _handle_signal)  # kill 命令
        if hasattr(signal, 'SIGHUP'):  # 终端断开（仅 Unix）
            signal.signal(signal.SIGHUP, _handle_signal)
        if hasattr(signal, 'SIGPIPE'):  # 管道破裂（仅 Unix）
            signal.signal(signal.SIGPIPE, signal.SIG_IGN)  # 忽略

        # --- 主交互循环 ---
        async def run_interactive():
            # 启动 Agent 后台任务
            bus_task = asyncio.create_task(agent_loop.run())

            # 用于等待每轮对话完成
            turn_done = asyncio.Event()
            turn_done.set()  # 初始化为完成状态
            turn_response: list[str] = []  # 存储回复

            # --- 消费出站消息 ---
            # 这个后台任务持续监听消息总线，处理 AI 的回复和进度更新
            async def _consume_outbound():
                while True:
                    try:
                        # 等待出站消息，超时 1 秒
                        msg = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)

                        if msg.metadata.get("_progress"):  # 进度消息
                            is_tool_hint = msg.metadata.get("_tool_hint", False)
                            ch = agent_loop.channels_config
                            # 根据配置决定是否显示
                            if ch and is_tool_hint and not ch.send_tool_hints:
                                pass
                            elif ch and not is_tool_hint and not ch.send_progress:
                                pass
                            else:
                                console.print(f"  [dim]↳ {msg.content}[/dim]")
                        elif not turn_done.is_set():  # 当前回复
                            if msg.content:
                                turn_response.append(msg.content)
                            turn_done.set()  # 标记完成
                        elif msg.content:  # 额外消息（比如工具输出）
                            console.print()
                            _print_agent_response(msg.content, render_markdown=markdown)
                    except asyncio.TimeoutError:
                        continue  # 超时继续等待
                    except asyncio.CancelledError:
                        break  # 被取消则退出

            outbound_task = asyncio.create_task(_consume_outbound())

            try:
                # --- 主输入循环 ---
                while True:
                    try:
                        _flush_pending_tty_input()  # 清除未读输入

                        # 读取用户输入
                        user_input = await _read_interactive_input_async()
                        command = user_input.strip()

                        if not command:  # 空输入
                            continue

                        # 检查退出命令
                        if _is_exit_command(command):
                            _restore_terminal()
                            console.print("\nGoodbye!")
                            break

                        # 重置轮次状态
                        turn_done.clear()
                        turn_response.clear()

                        # 发布消息到总线
                        await bus.publish_inbound(InboundMessage(
                            channel=cli_channel,
                            sender_id="user",
                            chat_id=cli_chat_id,
                            content=user_input,
                        ))

                        # 等待回复
                        with _thinking_ctx():
                            await turn_done.wait()

                        # 显示回复
                        if turn_response:
                            _print_agent_response(turn_response[0], render_markdown=markdown)

                    except KeyboardInterrupt:  # Ctrl+C
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
                    except EOFError:  # Ctrl+D
                        _restore_terminal()
                        console.print("\nGoodbye!")
                        break
            finally:
                # 清理资源
                agent_loop.stop()
                outbound_task.cancel()
                await asyncio.gather(bus_task, outbound_task, return_exceptions=True)
                await agent_loop.close_mcp()

        asyncio.run(run_interactive())


# =============================================================================
# 第九部分：渠道管理命令
# =============================================================================

# 创建渠道管理子命令组
channels_app = typer.Typer(help="Manage channels")
app.add_typer(channels_app, name="channels")  # 注册为子命令：nanobot channels ...


@channels_app.command("status")
def channels_status():
    """显示渠道状态。"""
    from nanobot.channels.registry import discover_channel_names, load_channel_class
    from nanobot.config.loader import load_config

    config = load_config()

    # 创建表格
    table = Table(title="Channel Status")
    table.add_column("Channel", style="cyan")  # 渠道名列
    table.add_column("Enabled", style="green")  # 启用状态列

    # 遍历所有渠道
    for modname in sorted(discover_channel_names()):
        section = getattr(config.channels, modname, None)
        enabled = section and getattr(section, "enabled", False)

        try:
            cls = load_channel_class(modname)
            display = cls.display_name  # 使用显示名称
        except ImportError:
            display = modname.title()  # 如果导入失败，用模块名代替

        table.add_row(
            display,
            "[green]✓[/green]" if enabled else "[dim]✗[/dim]",  # ✓ 或 ✗
        )

    console.print(table)


def _get_bridge_dir() -> Path:
    """
    获取桥接目录，必要时会自动搭建。

    什么是 Bridge？
    WhatsApp 等渠道需要一个 Node.js 桥接服务来连接 WebSocket。
    这个函数负责设置和返回桥接服务目录。
    """
    import shutil
    import subprocess
    from nanobot.config.paths import get_bridge_install_dir

    user_bridge = get_bridge_install_dir()  # 用户桥接目录

    # 如果已经构建完成，直接返回
    if (user_bridge / "dist" / "index.js").exists():
        return user_bridge

    # 检查 npm 是否安装
    if not shutil.which("npm"):
        console.print("[red]npm not found. Please install Node.js >= 18.[/red]")
        raise typer.Exit(1)

    # 查找桥接源码位置
    pkg_bridge = Path(__file__).parent.parent / "bridge"  # 安装后的位置
    src_bridge = Path(__file__).parent.parent.parent / "bridge"  # 开发位置

    source = None
    if (pkg_bridge / "package.json").exists():
        source = pkg_bridge
    elif (src_bridge / "package.json").exists():
        source = src_bridge

    if not source:
        console.print("[red]Bridge source not found.[/red]")
        console.print("Try reinstalling: pip install --force-reinstall nanobot")
        raise typer.Exit(1)

    console.print(f"{__logo__} Setting up bridge...")

    # 复制源码到用户目录
    user_bridge.parent.mkdir(parents=True, exist_ok=True)
    if user_bridge.exists():
        shutil.rmtree(user_bridge)  # 删除旧的
    shutil.copytree(source, user_bridge, ignore=shutil.ignore_patterns("node_modules", "dist"))

    # 安装依赖并构建
    try:
        console.print("  Installing dependencies...")
        subprocess.run(["npm", "install"], cwd=user_bridge, check=True, capture_output=True)

        console.print("  Building...")
        subprocess.run(["npm", "run", "build"], cwd=user_bridge, check=True, capture_output=True)

        console.print("[green]✓[/green] Bridge ready\n")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        if e.stderr:
            console.print(f"[dim]{e.stderr.decode()[:500]}[/dim]")
        raise typer.Exit(1)

    return user_bridge


@channels_app.command("login")
def channels_login():
    """通过二维码连接设备（WhatsApp）。"""
    import subprocess
    from nanobot.config.loader import load_config
    from nanobot.config.paths import get_runtime_subdir

    config = load_config()
    bridge_dir = _get_bridge_dir()

    console.print(f"{__logo__} Starting bridge...")
    console.print("Scan the QR code to connect.\n")

    # 设置环境变量
    env = {**os.environ}
    if config.channels.whatsapp.bridge_token:
        env["BRIDGE_TOKEN"] = config.channels.whatsapp.bridge_token
    env["AUTH_DIR"] = str(get_runtime_subdir("whatsapp-auth"))

    # 启动桥接服务
    try:
        subprocess.run(["npm", "start"], cwd=bridge_dir, check=True, env=env)
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Bridge failed: {e}[/red]")
    except FileNotFoundError:
        console.print("[red]npm not found. Please install Node.js.[/red]")


# =============================================================================
# 第十部分：状态命令
# =============================================================================

@app.command()
def status():
    """显示 nanobot 状态。"""
    from nanobot.config.loader import get_config_path, load_config

    config_path = get_config_path()
    config = load_config()
    workspace = config.workspace_path

    console.print(f"{__logo__} nanobot Status\n")

    # 检查配置文件和工作空间
    console.print(f"Config: {config_path} {'[green]✓[/green]' if config_path.exists() else '[red]✗[/red]'}")
    console.print(f"Workspace: {workspace} {'[green]✓[/green]' if workspace.exists() else '[red]✗[/red]'}")

    if config_path.exists():
        from nanobot.providers.registry import PROVIDERS

        console.print(f"Model: {config.agents.defaults.model}")

        # 检查各提供商的 API 密钥配置
        for spec in PROVIDERS:
            p = getattr(config.providers, spec.name, None)
            if p is None:
                continue

            if spec.is_oauth:  # OAuth 认证
                console.print(f"{spec.label}: [green]✓ (OAuth)[/green]")
            elif spec.is_local:  # 本地部署
                if p.api_base:
                    console.print(f"{spec.label}: [green]✓ {p.api_base}[/green]")
                else:
                    console.print(f"{spec.label}: [dim]not set[/dim]")
            else:  # API 密钥认证
                has_key = bool(p.api_key)
                console.print(f"{spec.label}: {'[green]✓[/green]' if has_key else '[dim]not set[/dim]'}")


# =============================================================================
# 第十一部分：OAuth 登录命令
# =============================================================================

# 创建提供商管理子命令组
provider_app = typer.Typer(help="Manage providers")
app.add_typer(provider_app, name="provider")

# 存储登录处理器的字典
_LOGIN_HANDLERS: dict[str, callable] = {}


def _register_login(name: str):
    """
    注册登录处理器的装饰器。

    装饰器是 Python 的一种语法糖，可以在不修改原函数的情况下添加功能。
    这里用于将登录函数注册到字典中。
    """
    def decorator(fn):
        _LOGIN_HANDLERS[name] = fn  # 将函数存入字典
        return fn
    return decorator


@provider_app.command("login")
def provider_login(
    provider: str = typer.Argument(..., help="OAuth provider (e.g. 'openai-codex', 'github-copilot')"),
):
    """使用 OAuth 认证提供商。"""
    from nanobot.providers.registry import PROVIDERS

    key = provider.replace("-", "_")  # 将横杠转为下划线（Python 命名习惯）

    # 查找对应的提供商规格
    spec = next((s for s in PROVIDERS if s.name == key and s.is_oauth), None)

    if not spec:
        # 列出支持的 OAuth 提供商
        names = ", ".join(s.name.replace("_", "-") for s in PROVIDERS if s.is_oauth)
        console.print(f"[red]Unknown OAuth provider: {provider}[/red]  Supported: {names}")
        raise typer.Exit(1)

    handler = _LOGIN_HANDLERS.get(spec.name)
    if not handler:
        console.print(f"[red]Login not implemented for {spec.label}[/red]")
        raise typer.Exit(1)

    console.print(f"{__logo__} OAuth Login - {spec.label}\n")
    handler()  # 调用登录处理器


@_register_login("openai_codex")
def _login_openai_codex() -> None:
    """OpenAI Codex OAuth 登录实现。"""
    try:
        from oauth_cli_kit import get_token, login_oauth_interactive

        token = None
        try:
            token = get_token()  # 尝试获取已存储的 token
        except Exception:
            pass

        if not (token and token.access):  # 没有有效 token
            console.print("[cyan]Starting interactive OAuth login...[/cyan]\n")
            token = login_oauth_interactive(
                print_fn=lambda s: console.print(s),  # 打印函数
                prompt_fn=lambda s: typer.prompt(s),  # 输入函数
            )

        if not (token and token.access):  # 认证失败
            console.print("[red]✗ Authentication failed[/red]")
            raise typer.Exit(1)

        console.print(f"[green]✓ Authenticated with OpenAI Codex[/green]  [dim]{token.account_id}[/dim]")
    except ImportError:
        console.print("[red]oauth_cli_kit not installed. Run: pip install oauth-cli-kit[/red]")
        raise typer.Exit(1)


@_register_login("github_copilot")
def _login_github_copilot() -> None:
    """GitHub Copilot 登录实现。"""
    import asyncio

    console.print("[cyan]Starting GitHub Copilot device flow...[/cyan]\n")

    async def _trigger():
        from litellm import acompletion
        # 通过一次 API 调用触发 OAuth 流程
        await acompletion(
            model="github_copilot/gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1
        )

    try:
        asyncio.run(_trigger())
        console.print("[green]✓ Authenticated with GitHub Copilot[/green]")
    except Exception as e:
        console.print(f"[red]Authentication error: {e}[/red]")
        raise typer.Exit(1)


# =============================================================================
# 程序入口
# =============================================================================
# 当这个文件被直接运行时（python commands.py），执行这里
# 当这个文件被导入时（from nanobot.cli import commands），不执行这里

if __name__ == "__main__":
    app()  # 启动 Typer 应用

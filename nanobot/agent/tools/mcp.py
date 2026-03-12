# =============================================================================
# nanobot MCP 工具
# 文件路径：nanobot/agent/tools/mcp.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 MCP (Model Context Protocol) 客户端，用于连接 MCP 服务器
# 并将 MCP 服务器的工具封装为 nanobot 的原生工具。
#
# 什么是 MCP？
# -----------
# MCP (Model Context Protocol) 是一个开放协议，用于：
# 1. 连接 LLM 应用到外部数据源和工具
# 2. 标准化的工具发现和执行接口
# 3. 支持多种传输层：stdio、SSE、streamableHttp
#
# 核心组件：
# ---------
# 1. MCPToolWrapper：封装单个 MCP 工具为 nanobot Tool
# 2. connect_mcp_servers：连接多个 MCP 服务器并注册工具
#
# 传输类型：
# ---------
# 1. stdio：通过子进程 stdin/stdout 通信
# 2. SSE：Server-Sent Events，基于 HTTP 长连接
# 3. streamableHttp：新型 HTTP 传输（默认）
#
# 使用示例：
# --------
# # 配置 MCP 服务器
# {
#   "mcpServers": {
#     "filesystem": {
#       "command": "npx",
#       "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
#       "tool_timeout": 60
#     },
#     "github": {
#       "url": "https://github-mcp-server.sse.example.com",
#       "headers": {"Authorization": "Bearer token"}
#     }
#   }
# }
# =============================================================================

import asyncio
from contextlib import AsyncExitStack
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry


class MCPToolWrapper(Tool):
    """
    封装单个 MCP 服务器工具为 nanobot Tool。

    这个类实现了适配器模式，将 MCP 工具转换为 nanobot 工具接口：
    1. 工具名称：添加前缀 "mcp_{server_name}_{tool_name}"
    2. 工具描述：使用 MCP 工具的 description 字段
    3. 参数 schema：使用 MCP 工具的 inputSchema
    4. 执行：通过 MCP session.call_tool() 调用

    属性说明：
    --------
    _session: mcp.ClientSession
        MCP 客户端会话

    _original_name: str
        MCP 工具的原始名称

    _name: str
        nanobot 工具名称（添加服务器名前缀）

    _description: str
        工具描述

    _parameters: dict
        输入参数 schema

    _tool_timeout: int
        工具调用超时（秒）

    使用示例：
    --------
    >>> wrapper = MCPToolWrapper(session, "filesystem", tool_def)
    >>> print(wrapper.name)
    "mcp_filesystem_list_directory"
    >>> result = await wrapper.execute(path="/workspace")
    """

    def __init__(self, session, server_name: str, tool_def, tool_timeout: int = 30):
        """
        初始化 MCP 工具封装器。

        Args:
            session: MCP 客户端会话
            server_name: MCP 服务器名称（用于工具名前缀）
            tool_def: MCP 工具定义（包含 name, description, inputSchema）
            tool_timeout: 工具调用超时（秒），默认 30 秒
        """
        self._session = session  # MCP 会话
        self._original_name = tool_def.name  # 原始工具名
        self._name = f"mcp_{server_name}_{tool_def.name}"  # 添加服务器名前缀
        self._description = tool_def.description or tool_def.name  # 工具描述
        self._parameters = tool_def.inputSchema or {"type": "object", "properties": {}}  # 参数 schema
        self._tool_timeout = tool_timeout  # 超时时间

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, Any]:
        return self._parameters

    async def execute(self, **kwargs: Any) -> str:
        """
        执行 MCP 工具调用。

        Args:
            **kwargs: 工具调用参数

        Returns:
            str: 工具执行结果（文本内容）或错误信息

        执行流程：
        --------
        1. 使用 asyncio.wait_for 设置超时
        2. 调用 session.call_tool() 执行 MCP 工具
        3. 解析结果内容为文本

        错误处理：
        --------
        - TimeoutError: 超时后返回超时消息
        - CancelledError: 如果是外部取消（如/stop）则重新抛出，否则返回取消消息
        - Exception: 记录异常日志，返回失败信息

        结果处理：
        --------
        - TextContent: 提取 text 字段
        - 其他类型：转换为字符串
        - 多个块：用换行符连接
        """
        from mcp import types

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(self._original_name, arguments=kwargs),
                timeout=self._tool_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("MCP tool '{}' timed out after {}s", self._name, self._tool_timeout)
            return f"(MCP tool call timed out after {self._tool_timeout}s)"
        except asyncio.CancelledError:
            # MCP SDK 的 anyio cancel scopes 可能在超时/失败时泄漏 CancelledError
            # 仅在任务被外部取消时重新抛出（如/stop 命令）
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            logger.warning("MCP tool '{}' was cancelled by server/SDK", self._name)
            return "(MCP tool call was cancelled)"
        except Exception as exc:
            logger.exception(
                "MCP tool '{}' failed: {}: {}",
                self._name,
                type(exc).__name__,
                exc,
            )
            return f"(MCP tool call failed: {type(exc).__name__})"

        parts = []
        for block in result.content:
            if isinstance(block, types.TextContent):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no output)"


async def connect_mcp_servers(
    mcp_servers: dict, registry: ToolRegistry, stack: AsyncExitStack
) -> None:
    """
    连接配置的 MCP 服务器并注册其工具。

    这个函数是 MCP 集成的入口点，负责：
    1. 遍历所有配置的 MCP 服务器
    2. 根据传输类型建立连接
    3. 初始化 MCP 会话
    4. 获取并注册所有工具

    Args:
        mcp_servers: MCP 服务器配置字典
            格式：{name: {type, command, args, url, headers, tool_timeout}}
        registry: 工具注册表，用于注册封装后的工具
        stack: 异步退出栈，用于管理资源生命周期

    连接流程：
    --------
    1. 确定传输类型：
       - 有 command → stdio
       - 有 url 且以/sse 结尾 → SSE
       - 有 url 但不以/sse 结尾 → streamableHttp

    2. 建立连接：
       - stdio: 创建子进程，通过 stdin/stdout 通信
       - SSE: 使用 httpx_client_factory 创建 HTTP 客户端
       - streamableHttp: 显式提供 httpx 客户端（避免默认 5s 超时）

    3. 初始化会话：
       - 创建 ClientSession
       - 调用 initialize()
       - 获取工具列表 list_tools()
       - 封装并注册每个工具

    错误处理：
    --------
    - 缺少 command/url: 跳过该服务器
    - 未知传输类型：记录警告，跳过
    - 连接失败：记录错误，继续处理其他服务器

    使用示例：
    --------
    >>> mcp_servers = {
    ...     "filesystem": {
    ...         "command": "npx",
    ...         "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
    ...         "tool_timeout": 60
    ...     }
    ... }
    >>> await connect_mcp_servers(mcp_servers, tool_registry, exit_stack)
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamable_http_client

    for name, cfg in mcp_servers.items():
        try:
            # 确定传输类型
            transport_type = cfg.type
            if not transport_type:
                if cfg.command:
                    transport_type = "stdio"  # 有命令，使用 stdio
                elif cfg.url:
                    # 约定：URL 以/sse 结尾使用 SSE 传输，否则使用 streamableHttp
                    transport_type = (
                        "sse" if cfg.url.rstrip("/").endswith("/sse") else "streamableHttp"
                    )
                else:
                    logger.warning("MCP server '{}': no command or url configured, skipping", name)
                    continue

            if transport_type == "stdio":
                # stdio 传输：创建子进程通过 stdin/stdout 通信
                params = StdioServerParameters(
                    command=cfg.command, args=cfg.args, env=cfg.env or None
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif transport_type == "sse":
                # SSE 传输：使用自定义 httpx 客户端工厂
                def httpx_client_factory(
                    headers: dict[str, str] | None = None,
                    timeout: httpx.Timeout | None = None,
                    auth: httpx.Auth | None = None,
                ) -> httpx.AsyncClient:
                    merged_headers = {**(cfg.headers or {}), **(headers or {})}
                    return httpx.AsyncClient(
                        headers=merged_headers or None,
                        follow_redirects=True,
                        timeout=timeout,
                        auth=auth,
                    )

                read, write = await stack.enter_async_context(
                    sse_client(cfg.url, httpx_client_factory=httpx_client_factory)
                )
            elif transport_type == "streamableHttp":
                # streamableHttp 传输：提供显式 httpx 客户端避免默认 5s 超时
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(
                        headers=cfg.headers or None,
                        follow_redirects=True,
                        timeout=None,  # 无超时，由工具层控制
                    )
                )
                read, write, _ = await stack.enter_async_context(
                    streamable_http_client(cfg.url, http_client=http_client)
                )
            else:
                logger.warning("MCP server '{}': unknown transport type '{}'", name, transport_type)
                continue

            # 创建并初始化 MCP 会话
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            # 获取工具列表并注册
            tools = await session.list_tools()
            for tool_def in tools.tools:
                wrapper = MCPToolWrapper(session, name, tool_def, tool_timeout=cfg.tool_timeout)
                registry.register(wrapper)
                logger.debug("MCP: registered tool '{}' from server '{}'", wrapper.name, name)

            logger.info("MCP server '{}': connected, {} tools registered", name, len(tools.tools))
        except Exception as e:
            logger.error("MCP server '{}': failed to connect: {}", name, e)

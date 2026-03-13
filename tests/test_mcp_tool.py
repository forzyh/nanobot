# =============================================================================
# nanobot MCP 工具测试
# 文件路径：tests/test_mcp_tool.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 MCP（Model Context Protocol）工具包装器
# MCPToolWrapper 的完整测试覆盖。
#
# MCP 是什么？
# -----------
# MCP（Model Context Protocol）是一个用于 AI 模型与外部工具/服务
# 交互的协议。通过这个协议，AI 模型可以：
# - 发现可用的工具
# - 调用工具执行操作
# - 获取工具执行结果
#
# MCPToolWrapper 的作用：
# ---------------------
# MCPToolWrapper 是 nanobot 中封装 MCP 工具的类，负责：
# 1. 调用 MCP 工具
# 2. 处理超时
# 3. 处理各种异常情况
# 4. 格式化返回结果
#
# 测试的核心功能：
# -------------
# 1. test_execute_returns_text_blocks:
#    - 验证工具执行返回文本块
#    - 验证 TextContent 被正确提取
#    - 验证非文本内容被转换为字符串
#
# 2. test_execute_returns_timeout_message:
#    - 验证工具调用超时返回超时消息
#    - 验证超时时间配置正确
#
# 3. test_execute_handles_server_cancelled_error:
#    - 验证处理服务器取消错误
#    - 验证返回取消消息
#
# 4. test_execute_re_raises_external_cancellation:
#    - 验证外部取消请求被重新抛出
#    - 验证不被内部超时处理捕获
#
# 5. test_execute_handles_generic_exception:
#    - 验证处理通用异常
#    - 验证返回错误消息
#
# 关键测试场景：
# ------------
# 1. 正常场景：
#    - 工具正常执行并返回结果
#    - 结果包含文本和非文本内容
#
# 2. 超时场景：
#    - 工具执行时间超过配置的超时时间
#    - 返回超时消息而不是结果
#
# 3. 取消场景：
#    - 服务器取消工具执行
#    - 外部取消请求
#
# 4. 异常场景：
#    - 工具执行抛出异常
#    - 返回错误消息
#
# 测试技术说明：
# -------------
# 1. 模块 Mocking：
#    - 使用 _fake_mcp_module 夹具模拟 mcp 模块
#    - 避免实际依赖 MCP 库
#
# 2. 异步测试：
#    - 所有测试都是异步的（@pytest.mark.asyncio）
#    - 使用 asyncio 进行超时和取消测试
#
# 使用示例：
# --------
# 运行所有测试：pytest tests/test_mcp_tool.py -v
# 运行单个测试：pytest tests/test_mcp_tool.py::test_execute_returns_text_blocks -v
# =============================================================================

from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from nanobot.agent.tools.mcp import MCPToolWrapper


class _FakeTextContent:
    """
    模拟的 TextContent 类

    用于模拟 MCP 库中的 TextContent 类型。
    MCP 工具返回的结果可能包含多个内容块，
    TextContent 是其中一种，包含文本数据。

    属性：
    -----
    text: str - 文本内容
    """
    def __init__(self, text: str) -> None:
        self.text = text


@pytest.fixture(autouse=True)
def _fake_mcp_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    夹具：模拟 mcp 模块

    这个夹具在测试开始前自动执行（autouse=True），
    用于模拟 MCP 库的模块结构，避免实际安装 MCP 库。

    模拟的内容：
    ----------
    - mcp.types.TextContent: 模拟的 TextContent 类

    实现方式：
    ---------
    1. 创建一个名为"mcp"的虚拟模块
    2. 创建 types 子模块，包含 TextContent
    3. 将虚拟模块注册到 sys.modules

    Args:
        monkeypatch: pytest 的 monkeypatch 夹具，用于临时修改系统状态
    """
    # 创建虚拟的 mcp 模块
    mod = ModuleType("mcp")
    # 创建 types 子模块，包含 TextContent
    mod.types = SimpleNamespace(TextContent=_FakeTextContent)
    # 注册到 sys.modules，使 import mcp 返回我们的虚拟模块
    monkeypatch.setitem(sys.modules, "mcp", mod)


def _make_wrapper(session: object, *, timeout: float = 0.1) -> MCPToolWrapper:
    """
    创建 MCPToolWrapper 实例的辅助函数

    这个函数创建一个配置好的 MCPToolWrapper 实例，
    用于测试。

    Args:
        session: MCP 会话对象（通常是 mock 对象）
        timeout: 工具调用超时时间（秒），默认 0.1 秒

    Returns:
        MCPToolWrapper: 配置好的工具包装器实例

    示例：
    -----
    ```python
    wrapper = _make_wrapper(
        SimpleNamespace(call_tool=mock_call),
        timeout=1.0
    )
    ```
    """
    # 定义工具元数据
    tool_def = SimpleNamespace(
        # 工具名称
        name="demo",
        # 工具描述
        description="demo tool",
        # 输入参数 schema（JSON Schema 格式）
        inputSchema={"type": "object", "properties": {}},
    )
    # 创建工具包装器
    return MCPToolWrapper(session, "test", tool_def, tool_timeout=timeout)


@pytest.mark.asyncio
async def test_execute_returns_text_blocks() -> None:
    """
    测试工具执行返回文本块

    这个测试验证 MCPToolWrapper.execute() 方法正确处理
    工具返回的结果，包括：
    1. TextContent 类型的文本内容
    2. 非文本内容（转换为字符串）
    3. 多个内容块的拼接

    测试步骤：
    ---------
    1. 定义模拟的 call_tool 函数
       - 验证传入的参数正确
       - 返回包含 TextContent 和非文本内容的结果
    2. 创建 MCPToolWrapper 实例
    3. 调用 execute() 执行工具
    4. 验证返回结果是文本拼接结果

    预期行为：
    ---------
    - TextContent.text 被提取
    - 非文本内容使用 str() 转换
    - 多个内容块用换行符拼接

    为什么重要：
    -----------
    - 验证工具结果的正确格式化
    - 确保 AI 模型能理解工具返回的内容
    """
    # 定义模拟的工具调用函数
    async def call_tool(_name: str, arguments: dict) -> object:
        # 验证传入的参数正确
        assert arguments == {"value": 1}
        # 返回包含文本和非文本内容的结果
        return SimpleNamespace(content=[_FakeTextContent("hello"), 42])

    # 创建工具包装器
    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    # 执行工具
    result = await wrapper.execute(value=1)

    # 验证结果：文本内容 + 换行 + 非文本内容的字符串形式
    assert result == "hello\n42"


@pytest.mark.asyncio
async def test_execute_returns_timeout_message() -> None:
    """
    测试工具执行超时返回超时消息

    这个测试验证当工具执行时间超过配置的超时时间时，
    MCPToolWrapper 能够：
    1. 捕获超时异常
    2. 返回友好的超时消息
    3. 不抛出异常

    测试步骤：
    ---------
    1. 定义模拟的 call_tool 函数
       - 休眠 1 秒（超过超时时间）
       - 返回空结果
    2. 创建 MCPToolWrapper 实例，配置超时 0.01 秒
    3. 调用 execute() 执行工具
    4. 验证返回超时消息

    超时机制：
    ---------
    MCPToolWrapper 使用 asyncio.wait_for() 实现超时：
    - 如果在指定时间内未完成，抛出 TimeoutError
    - 捕获 TimeoutError 并返回超时消息

    为什么重要：
    -----------
    - 防止工具调用无限期阻塞
    - 保护系统资源
    - 提供友好的错误提示
    """
    # 定义模拟的工具调用函数（会超时）
    async def call_tool(_name: str, arguments: dict) -> object:
        # 休眠 1 秒，模拟长时间运行的工具
        await asyncio.sleep(1)
        return SimpleNamespace(content=[])

    # 创建工具包装器，配置超时 0.01 秒
    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool), timeout=0.01)

    # 执行工具（会超时）
    result = await wrapper.execute()

    # 验证返回超时消息
    assert result == "(MCP tool call timed out after 0.01s)"


@pytest.mark.asyncio
async def test_execute_handles_server_cancelled_error() -> None:
    """
    测试处理服务器取消错误

    这个测试验证当 MCP 服务器取消工具执行时
    （抛出 asyncio.CancelledError），
    MCPToolWrapper 能够：
    1. 捕获取消异常
    2. 返回友好的取消消息
    3. 不抛出异常

    测试步骤：
    ---------
    1. 定义模拟的 call_tool 函数
       - 直接抛出 CancelledError
    2. 创建 MCPToolWrapper 实例
    3. 调用 execute() 执行工具
    4. 验证返回取消消息

    CancelledError 来源：
    ------------------
    asyncio.CancelledError 可能在以下情况发生：
    - 服务器主动取消任务
    - 连接断开
    - 资源不足

    为什么重要：
    -----------
    - 优雅处理服务器取消
    - 防止程序崩溃
    - 提供清晰的错误信息
    """
    # 定义模拟的工具调用函数（抛出取消错误）
    async def call_tool(_name: str, arguments: dict) -> object:
        # 直接抛出取消错误
        raise asyncio.CancelledError()

    # 创建工具包装器
    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    # 执行工具
    result = await wrapper.execute()

    # 验证返回取消消息
    assert result == "(MCP tool call was cancelled)"


@pytest.mark.asyncio
async def test_execute_re_raises_external_cancellation() -> None:
    """
    测试重新抛出外部取消请求

    这个测试验证当外部代码取消工具执行任务时，
    MCPToolWrapper 能够：
    1. 识别是外部取消（非内部超时）
    2. 重新抛出 CancelledError
    3. 让调用者处理取消

    测试步骤：
    ---------
    1. 定义模拟的 call_tool 函数
       - 设置事件标记已开始
       - 休眠 60 秒（模拟长时间运行）
    2. 创建 MCPToolWrapper 实例，配置超时 10 秒
    3. 创建异步任务执行工具
    4. 等待工具开始执行
    5. 取消任务
    6. 验证抛出 CancelledError

    外部取消 vs 内部超时：
    -------------------
    - 内部超时：由工具执行超时触发，返回超时消息
    - 外部取消：由调用者主动取消，重新抛出异常

    为什么重要：
    -----------
    - 支持调用者控制执行
    - 正确的取消传播
    - 防止取消被吞掉
    """
    # 用于跟踪工具是否开始执行
    started = asyncio.Event()

    # 定义模拟的工具调用函数
    async def call_tool(_name: str, arguments: dict) -> object:
        # 标记已开始执行
        started.set()
        # 休眠 60 秒，模拟长时间运行
        await asyncio.sleep(60)
        return SimpleNamespace(content=[])

    # 创建工具包装器，配置超时 10 秒
    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool), timeout=10)
    # 创建异步任务
    task = asyncio.create_task(wrapper.execute())
    # 等待工具开始执行
    await started.wait()

    # 取消任务
    task.cancel()

    # 验证抛出 CancelledError
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_execute_handles_generic_exception() -> None:
    """
    测试处理通用异常

    这个测试验证当工具执行抛出普通异常时
    （如 RuntimeError），
    MCPToolWrapper 能够：
    1. 捕获异常
    2. 返回友好的错误消息
    3. 不抛出异常

    测试步骤：
    ---------
    1. 定义模拟的 call_tool 函数
       - 抛出 RuntimeError
    2. 创建 MCPToolWrapper 实例
    3. 调用 execute() 执行工具
    4. 验证返回错误消息

    错误消息格式：
    -------------
    "(MCP tool call failed: {异常类型名})"

    例如：
    - RuntimeError -> "(MCP tool call failed: RuntimeError)"
    - ValueError -> "(MCP tool call failed: ValueError)"

    为什么重要：
    -----------
    - 优雅处理工具错误
    - 防止程序崩溃
    - 提供清晰的错误信息
    - 帮助调试问题
    """
    # 定义模拟的工具调用函数（抛出异常）
    async def call_tool(_name: str, arguments: dict) -> object:
        # 抛出运行时错误
        raise RuntimeError("boom")

    # 创建工具包装器
    wrapper = _make_wrapper(SimpleNamespace(call_tool=call_tool))

    # 执行工具
    result = await wrapper.execute()

    # 验证返回错误消息
    assert result == "(MCP tool call failed: RuntimeError)"

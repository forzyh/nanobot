# =============================================================================
# nanobot CLI 输入测试
# 文件路径：tests/test_cli_input.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 nanobot CLI 交互式输入功能的单元测试。
# 主要测试 CLI 中的用户输入处理功能，包括 prompt_toolkit 集成。
#
# 测试的核心功能：
# -------------------------
# 1. 交互式输入读取：测试 _read_interactive_input_async 函数
# 2. EOF 处理：测试文件结束符（EOF）转换为 KeyboardInterrupt
# 3. PromptSession 初始化：测试全局 prompt session 的创建
#
# 关键测试场景：
# --------
# 1. 正常输入：验证用户输入能够被正确读取和返回
# 2. EOFError 处理：验证 EOF 错误被转换为 KeyboardInterrupt
# 3. PromptSession 创建：验证 session 使用正确的配置初始化
#
# 使用示例：
# --------
# pytest tests/test_cli_input.py -v           # 运行所有测试
# pytest tests/test_cli_input.py::test_read_interactive_input_async_returns_input -v  # 运行特定测试
# =============================================================================

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.formatted_text import HTML

from nanobot.cli import commands


@pytest.fixture
def mock_prompt_session():
    """模拟全局 prompt session。

    这个 fixture 创建一个模拟的 PromptSession 对象，
    用于测试 CLI 输入功能而不需要真实的用户交互。

    Yields:
        MagicMock: 模拟的 prompt session 对象
    """
    mock_session = MagicMock()
    mock_session.prompt_async = AsyncMock()
    with patch("nanobot.cli.commands._PROMPT_SESSION", mock_session), \
         patch("nanobot.cli.commands.patch_stdout"):
        yield mock_session


@pytest.mark.asyncio
async def test_read_interactive_input_async_returns_input(mock_prompt_session):
    """测试 _read_interactive_input_async 返回用户输入。

    验证函数能够：
    1. 调用 prompt_session.prompt_async 获取用户输入
    2. 返回获取到的输入字符串
    3. 使用 HTML 格式的提示语
    """
    mock_prompt_session.prompt_async.return_value = "hello world"

    result = await commands._read_interactive_input_async()

    assert result == "hello world"
    mock_prompt_session.prompt_async.assert_called_once()
    args, _ = mock_prompt_session.prompt_async.call_args
    assert isinstance(args[0], HTML)  # 验证使用 HTML 格式的提示语


@pytest.mark.asyncio
async def test_read_interactive_input_async_handles_eof(mock_prompt_session):
    """测试 EOFError 被转换为 KeyboardInterrupt。

    验证当用户按下 Ctrl+D（EOF）时，
    EOFError 异常被捕获并转换为 KeyboardInterrupt，
    以便上层代码统一处理中断。
    """
    mock_prompt_session.prompt_async.side_effect = EOFError()

    with pytest.raises(KeyboardInterrupt):
        await commands._read_interactive_input_async()


def test_init_prompt_session_creates_session():
    """测试 _init_prompt_session 初始化全局 session。

    验证函数使用正确的配置创建 PromptSession：
    1. multiline=False：不支持多行输入
    2. enable_open_in_editor=False：不启用编辑器
    """
    # 确保测试前全局为 None
    commands._PROMPT_SESSION = None

    with patch("nanobot.cli.commands.PromptSession") as MockSession, \
         patch("nanobot.cli.commands.FileHistory") as MockHistory, \
         patch("pathlib.Path.home") as mock_home:

        mock_home.return_value = MagicMock()

        commands._init_prompt_session()

        assert commands._PROMPT_SESSION is not None
        MockSession.assert_called_once()
        _, kwargs = MockSession.call_args
        assert kwargs["multiline"] is False
        assert kwargs["enable_open_in_editor"] is False

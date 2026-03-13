# =============================================================================
# nanobot MessageTool 测试
# 文件路径：tests/test_message_tool.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 MessageTool 工具的基本测试。
# MessageTool 是用于发送消息的工具，需要指定目标渠道或聊天。
#
# 什么是 MessageTool？
# ---------------
# MessageTool 是 nanobot agent 系统中的一个工具，
# 允许机器人向指定的渠道或聊天发送消息。
# 在使用时必须指定目标（渠道或聊天），否则会返回错误。
#
# 测试场景：
# --------
# 1. 未指定目标时返回错误：当 execute 方法没有指定 target 参数时，应返回错误信息
#
# 使用示例：
# --------
# pytest tests/test_message_tool.py -v  # 运行所有测试
# =============================================================================

import pytest

from nanobot.agent.tools.message import MessageTool


@pytest.mark.asyncio
async def test_message_tool_returns_error_when_no_target_context() -> None:
    """测试未指定目标时返回错误。

    场景说明：
        MessageTool 在执行时必须指定目标渠道或聊天，
        如果没有指定，应该返回清晰的错误信息，
        告知用户需要指定 target 参数。

    验证点：
        1. 返回错误信息包含 "No target channel/chat specified"
    """
    # 创建 MessageTool 实例
    tool = MessageTool()
    # 在不指定 target 的情况下执行工具
    result = await tool.execute(content="test")
    # 验证返回了预期的错误信息
    assert result == "Error: No target channel/chat specified"

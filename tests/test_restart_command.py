# =============================================================================
# nanobot 重启命令测试
# 文件路径：tests/test_restart_command.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件测试了 nanobot 的 /restart 斜杠命令功能。
# /restart 命令用于重启 nanobot 机器人进程。
#
# 测试的核心功能：
# -------------------------
# - 测试 /restart 命令能够发送重启消息并调用 os.execv 进行进程替换
# - 测试 /restart 命令在运行循环级别被拦截处理
# - 测试 /help 命令的输出包含 /restart 命令说明
#
# 关键测试场景：
# -------------------------
# 1. 重启执行：验证 /restart 能够发送消息并调用 os.execv
# 2. 运行循环拦截：验证 /restart 在 run() 循环级别被处理，而不是在 _dispatch 内部
# 3. 帮助文档：验证 /help 输出包含 /restart 命令说明
#
# 使用示例：
# -------------------------
# 运行测试：pytest tests/test_restart_command.py -v
#
# 相关模块：
# - nanobot/agent/loop.py - AgentLoop 类，包含 _handle_restart 方法
# - nanobot/bus/events.py - InboundMessage 事件类
#
# 重启命令说明：
# -------------------------
# /restart 命令的工作流程：
# 1. 用户发送 /restart 消息
# 2. AgentLoop._handle_restart 被调用
# 3. 发送 "Restarting..." 出站消息通知用户
# 4. 调用 os.execv 替换当前进程（实现重启）
#
# os.execv 说明：
# - execv 会用新进程替换当前进程映像
# - 这是 Unix/Linux 系统调用，实现无缝重启
# - 第一个参数是程序路径，第二个参数是参数列表
# =============================================================================

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from nanobot.bus.events import InboundMessage


def _make_loop():
    """
    创建一个最小化的 AgentLoop 实例，带有模拟的依赖项

    这个辅助函数的作用：
    - 创建 MessageBus 用于消息传递
    - 创建模拟的 LLM Provider
    - 创建模拟的 workspace 对象
    - 使用 patch 屏蔽外部依赖（ContextBuilder、SessionManager、SubagentManager）

    返回：
        tuple: (AgentLoop 实例，MessageBus 实例)
    """
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus

    # 创建消息总线实例，用于入站和出站消息传递
    bus = MessageBus()
    # 创建模拟的 LLM Provider
    provider = MagicMock()
    # 配置 Provider 的默认模型返回值为 "test-model"
    provider.get_default_model.return_value = "test-model"
    # 创建模拟的 workspace 对象
    workspace = MagicMock()
    # 配置 workspace 的路径除法运算符（__truediv__）返回 MagicMock
    # 这样 workspace / "some/path" 会返回一个 MagicMock 对象
    workspace.__truediv__ = MagicMock(return_value=MagicMock())

    # 使用 patch 屏蔽 AgentLoop 的外部依赖
    # ContextBuilder、SessionManager、SubagentManager 都需要被模拟
    # 否则 AgentLoop 初始化会失败
    with patch("nanobot.agent.loop.ContextBuilder"), \
         patch("nanobot.agent.loop.SessionManager"), \
         patch("nanobot.agent.loop.SubagentManager"):
        # 创建 AgentLoop 实例
        loop = AgentLoop(bus=bus, provider=provider, workspace=workspace)
    return loop, bus


class TestRestartCommand:
    """
    测试 /restart 斜杠命令的功能

    这个测试类验证：
    1. 重启命令能够正确发送消息并调用 os.execv
    2. 重启命令在运行循环级别被拦截处理
    3. 帮助命令输出包含 /restart 命令说明
    """

    @pytest.mark.asyncio
    async def test_restart_sends_message_and_calls_execv(self):
        """
        测试 /restart 命令能够发送重启消息并调用 os.execv 进行进程替换

        验证点：
        - 调用 _handle_restart 后会发送包含 "Restarting" 的出站消息
        - 调用 _handle_restart 后会调用 os.execv 进行进程替换

        测试步骤：
        1. 创建 AgentLoop 实例
        2. 创建 /restart 入站消息
        3. 使用 patch 模拟 os.execv
        4. 调用 _handle_restart 方法
        5. 从消息总线消费出站消息并验证内容
        6. 等待一段时间后验证 execv 被调用了一次
        """
        # 创建 AgentLoop 和 MessageBus 实例
        loop, bus = _make_loop()
        # 创建 /restart 入站消息
        # channel="cli" 表示来自命令行渠道
        # sender_id="user" 表示发送者 ID
        # chat_id="direct" 表示私聊
        # content="/restart" 表示消息内容是重启命令
        msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content="/restart")

        # 使用 patch 模拟 os.execv 函数
        # os.execv 用于替换当前进程（实现重启）
        with patch("nanobot.agent.loop.os.execv") as mock_execv:
            # 调用重启处理函数
            await loop._handle_restart(msg)
            # 从消息总线消费出站消息（超时 1 秒）
            # wait_for 确保不会因为阻塞而无限等待
            out = await asyncio.wait_for(bus.consume_outbound(), timeout=1.0)
            # 验证出站消息内容包含 "Restarting"
            assert "Restarting" in out.content

            # 等待 1.5 秒，让重启逻辑有时间执行
            await asyncio.sleep(1.5)
            # 验证 os.execv 被调用了一次
            mock_execv.assert_called_once()

    @pytest.mark.asyncio
    async def test_restart_intercepted_in_run_loop(self):
        """
        验证 /restart 命令在运行循环（run-loop）级别被拦截处理，而不是在 _dispatch 内部

        这个测试的目的：
        - 确保 /restart 命令的处理位置正确（在 run() 方法中）
        - 确保 /restart 不会被当作普通消息传递给 LLM 处理

        验证点：
        - _handle_restart 方法被调用了一次

        测试步骤：
        1. 创建 AgentLoop 实例
        2. 创建 /restart 入站消息
        3. 使用 patch 模拟 _handle_restart 方法
        4. 发布入站消息到消息总线
        5. 启动 run() 循环
        6. 等待短暂时间后停止循环
        7. 验证 _handle_restart 被调用了一次
        """
        # 创建 AgentLoop 和 MessageBus 实例
        loop, bus = _make_loop()
        # 创建 /restart 入站消息（来自 Telegram 渠道）
        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/restart")

        # 使用 patch 模拟 _handle_restart 方法
        with patch.object(loop, "_handle_restart") as mock_handle:
            # 配置模拟方法返回 None
            mock_handle.return_value = None
            # 发布入站消息到消息总线
            await bus.publish_inbound(msg)

            # 设置循环运行状态为 True
            loop._running = True
            # 创建 run() 协程任务
            run_task = asyncio.create_task(loop.run())
            # 等待 0.1 秒，让 run 循环有时间处理消息
            await asyncio.sleep(0.1)
            # 设置循环运行状态为 False，停止循环
            loop._running = False
            # 取消 run 任务
            run_task.cancel()
            try:
                # 等待任务取消完成
                await run_task
            except asyncio.CancelledError:
                # 预期会抛出 CancelledError 异常
                pass

            # 验证 _handle_restart 被调用了一次
            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_help_includes_restart(self):
        """
        测试 /help 命令的输出包含 /restart 命令说明

        验证点：
        - /help 命令的响应不为空
        - 响应内容包含 "/restart" 字符串

        这个测试确保用户在使用 /help 时能够看到 /restart 命令的说明
        """
        # 创建 AgentLoop 和 MessageBus 实例
        loop, bus = _make_loop()
        # 创建 /help 入站消息
        msg = InboundMessage(channel="telegram", sender_id="u1", chat_id="c1", content="/help")

        # 调用 _process_message 处理消息
        response = await loop._process_message(msg)

        # 验证响应不为空
        assert response is not None
        # 验证响应内容包含 "/restart" 命令说明
        assert "/restart" in response.content

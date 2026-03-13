# =============================================================================
# 上下文提示缓存测试
# 文件路径：tests/test_context_prompt_cache.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了缓存友好的提示词构建测试，主要测试 ContextBuilder 的
# 系统提示词稳定性和运行时上下文处理机制。
#
# 核心概念：
# - 系统提示词稳定性：系统提示词不应随时间变化，以利用缓存
# - 运行时上下文：会话元数据（时间、渠道等）应与用户消息合并
# - 缓存效率：相同的提示词前缀可以命中 LLM 缓存，减少 token 消耗
#
# 测试场景：
# --------
# 1. test_bootstrap_files_are_backed_by_templates
#    - 验证所有引导文件都有对应的模板
#
# 2. test_system_prompt_stays_stable_when_clock_changes
#    - 测试系统提示词不随时间变化
#    - 即使时钟从 13:59 变到 14:00，提示词也应保持不变
#
# 3. test_runtime_context_is_separate_untrusted_user_message
#    - 测试运行时元数据与用户消息合并
#    - 验证当前时间、渠道、聊天 ID 等信息正确包含
#
# 使用示例：
# --------
# pytest tests/test_context_prompt_cache.py -v
# =============================================================================

"""Tests for cache-friendly prompt construction."""

from __future__ import annotations

from datetime import datetime as real_datetime
from importlib.resources import files as pkg_files
from pathlib import Path
import datetime as datetime_module

from nanobot.agent.context import ContextBuilder


class _FakeDatetime(real_datetime):
    """伪造的 datetime 类，用于固定测试时间。

    通过继承真实 datetime 类并重写 now() 方法，
    使测试可以在固定时间点运行，避免时间变化影响测试结果。

    Attributes:
        current: 类变量，存储伪造的当前时间，可在测试中修改
    """

    current = real_datetime(2026, 2, 24, 13, 59)

    @classmethod
    def now(cls, tz=None):  # type: ignore[override]
        """返回伪造的当前时间。

        Args:
            tz: 时区参数（被忽略，始终返回固定时间）

        Returns:
            固定的 _FakeDatetime.current 时间
        """
        return cls.current


def _make_workspace(tmp_path: Path) -> Path:
    """创建临时工作目录用于测试。

    Args:
        tmp_path: pytest 提供的临时目录路径

    Returns:
        工作目录路径（tmp_path/workspace）
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    return workspace


def test_bootstrap_files_are_backed_by_templates() -> None:
    """测试所有引导文件都有对应的模板文件。

    验证 ContextBuilder.BOOTSTRAP_FILES 中列出的所有文件
    都存在于 nanobot/templates 目录中。

    这确保系统启动时可以正确加载所有必需的模板文件。
    """
    # 获取 nanobot/templates 目录
    template_dir = pkg_files("nanobot") / "templates"

    # 验证每个引导文件都存在
    for filename in ContextBuilder.BOOTSTRAP_FILES:
        assert (template_dir / filename).is_file(), f"missing bootstrap template: {filename}"


def test_system_prompt_stays_stable_when_clock_changes(tmp_path, monkeypatch) -> None:
    """测试系统提示词不随时间变化，确保缓存友好。

    核心验证点：
    - 系统提示词不应该包含易变的时间信息
    - 即使时钟从 13:59 跨小时到 14:00，提示词也应完全相同
    - 这样可以利用 LLM 的提示词缓存功能，减少 token 消耗

    测试方法：
    1. 使用 _FakeDatetime 固定时间
    2. 在 13:59 构建系统提示词
    3. 修改时间到 14:00
    4. 再次构建系统提示词
    5. 验证两次结果完全相同
    """
    # 替换 datetime 模块为伪造版本
    monkeypatch.setattr(datetime_module, "datetime", _FakeDatetime)

    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    # 第一次：13:59
    _FakeDatetime.current = real_datetime(2026, 2, 24, 13, 59)
    prompt1 = builder.build_system_prompt()

    # 第二次：14:00（跨小时）
    _FakeDatetime.current = real_datetime(2026, 2, 24, 14, 0)
    prompt2 = builder.build_system_prompt()

    # 验证两次提示词完全相同
    assert prompt1 == prompt2


def test_runtime_context_is_separate_untrusted_user_message(tmp_path) -> None:
    """测试运行时上下文作为独立的用户消息处理。

    验证点：
    1. 系统提示词不包含 "## Current Session" 等运行时信息
    2. 运行时元数据（时间、渠道、聊天 ID）与用户消息合并为一条
    3. 合并后的消息角色为 "user"
    4. 包含 ContextBuilder._RUNTIME_CONTEXT_TAG 标记

    设计说明：
    - 系统提示词：稳定不变，可命中缓存
    - 运行时上下文：每条消息都可能不同，与用户消息合并
    - 这种设计平衡了缓存效率和信息完整性
    """
    workspace = _make_workspace(tmp_path)
    builder = ContextBuilder(workspace)

    # 构建消息列表
    messages = builder.build_messages(
        history=[],  # 空历史
        current_message="Return exactly: OK",  # 当前用户消息
        channel="cli",  # 渠道：命令行
        chat_id="direct",  # 聊天 ID：直聊
    )

    # 验证系统提示词
    assert messages[0]["role"] == "system"
    assert "## Current Session" not in messages[0]["content"]

    # 验证运行时上下文与用户消息合并
    assert messages[-1]["role"] == "user"
    user_content = messages[-1]["content"]
    assert isinstance(user_content, str)
    assert ContextBuilder._RUNTIME_CONTEXT_TAG in user_content  # 包含标记
    assert "Current Time:" in user_content  # 包含当前时间
    assert "Channel: cli" in user_content  # 包含渠道信息
    assert "Chat ID: direct" in user_content  # 包含聊天 ID
    assert "Return exactly: OK" in user_content  # 包含用户消息

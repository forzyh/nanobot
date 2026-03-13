# =============================================================================
# nanobot Loop 保存轮次测试
# 文件路径：tests/test_loop_save_turn.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 AgentLoop._save_turn 方法的测试，
# 主要验证在保存对话轮次（turn）到 session 时的特殊处理逻辑。
#
# _save_turn 方法的作用：
# ---------------------
# _save_turn 方法负责将一轮对话（包括用户消息、助手响应、工具调用结果等）
# 保存到 session 的消息历史中。在保存过程中，需要进行一些特殊处理：
#
# 1. 运行时上下文（runtime context）处理：
#    - 系统会在用户消息前注入运行时上下文（如当前时间、系统状态等）
#    - 这些上下文只用于当次对话，不应该保存到历史中
#    - 测试验证纯运行时上下文的用户消息会被跳过
#
# 2. 多模态内容处理：
#    - 用户消息可能包含图片等多模态内容
#    - 保存时需要将图片替换为占位符 "[image]"
#    - 测试验证图片占位符的正确处理
#
# 3. 工具结果处理：
#    - 工具调用结果（如文件读取内容）可能很大
#    - 需要验证大内容（<16KB）能够正确保存
#
# 测试的核心功能：
# -------------
# 1. test_save_turn_skips_multimodal_user_when_only_runtime_context:
#    - 验证当用户消息只包含运行时上下文时，不保存到历史
#
# 2. test_save_turn_keeps_image_placeholder_after_runtime_strip:
#    - 验证移除运行时上下文后，图片占位符 "[image]" 被正确保留
#
# 3. test_save_turn_keeps_tool_results_under_16k:
#    - 验证工具结果（<16KB）能够完整保存
#
# 关键测试场景：
# ------------
# 1. 纯运行时上下文场景：
#    - 用户消息只包含运行时上下文标签和内容
#    - 这种消息不应该保存到历史，避免冗余
#
# 2. 运行时上下文 + 多模态内容场景：
#    - 用户消息包含运行时上下文和图片
#    - 保存时移除运行时上下文，保留图片占位符
#
# 3. 大工具结果场景：
#    - 工具返回大量内容（如 12KB 的文件内容）
#    - 验证能够完整保存（<16KB 限制）
#
# 关键常量：
# ---------
# - ContextBuilder._RUNTIME_CONTEXT_TAG: 运行时上下文标签
# - AgentLoop._TOOL_RESULT_MAX_CHARS: 工具结果最大字符数
#
# 使用示例：
# --------
# 运行所有测试：pytest tests/test_loop_save_turn.py -v
# 运行单个测试：pytest tests/test_loop_save_turn.py::test_save_turn_skips_multimodal_user_when_only_runtime_context -v
# =============================================================================

from nanobot.agent.context import ContextBuilder
from nanobot.agent.loop import AgentLoop
from nanobot.session.manager import Session


def _mk_loop() -> AgentLoop:
    """
    创建用于测试的 AgentLoop 实例的辅助函数

    这个函数创建一个最小化的 AgentLoop 实例，只包含
    _save_turn 方法所需的属性。

    为什么使用 __new__ 而不是构造函数？
    -----------------------------------
    - AgentLoop 的构造函数需要多个依赖项（bus, provider, workspace 等）
    - 这些测试只关心 _save_turn 方法的行为
    - 使用 __new__ 可以避免创建不必要的依赖项
    - 简化测试设置，提高测试速度

    Returns:
        AgentLoop: 最小化的 AgentLoop 实例，包含 _TOOL_RESULT_MAX_CHARS 属性
    """
    # 使用 __new__ 创建实例，不调用 __init__
    loop = AgentLoop.__new__(AgentLoop)
    # 设置 _save_turn 方法需要的唯一属性
    loop._TOOL_RESULT_MAX_CHARS = AgentLoop._TOOL_RESULT_MAX_CHARS
    return loop


def test_save_turn_skips_multimodal_user_when_only_runtime_context() -> None:
    """
    测试当用户消息只包含运行时上下文时被跳过

    这个测试验证 _save_turn 方法的一个特殊行为：
    当用户消息的内容只包含运行时上下文（runtime context）时，
    这条消息不会被保存到 session 历史中。

    背景说明：
    ---------
    在 Agent 系统中，运行时上下文（如当前时间、系统状态）会在每次
    用户消息前自动注入。这些上下文信息：
    - 只用于当次对话的参考
    - 不应该保存到历史中（会重复且无意义）
    - 在保存前需要被过滤掉

    测试步骤：
    ---------
    1. 创建 AgentLoop 实例
    2. 创建 Session，key 为 "test:runtime-only"
    3. 创建纯运行时上下文的_content:
       - 以 RUNTIME_CONTEXT_TAG 开头
       - 包含 "Current Time: now (UTC)"
    4. 调用 _save_turn 保存消息
    5. 验证 session.messages 为空列表（消息被跳过）

    为什么重要：
    -----------
    - 防止冗余的运行时上下文污染历史
    - 确保历史消息都是有意义的对话内容
    - 节省存储空间和 token
    """
    # 创建最小化的 AgentLoop 实例
    loop = _mk_loop()
    # 创建 Session
    session = Session(key="test:runtime-only")
    # 创建运行时上下文内容
    # 格式：以 RUNTIME_CONTEXT_TAG 开头，后跟具体的上下文信息
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    # 调用 _save_turn 保存消息
    # 消息格式：包含一个 user 角色的消息，content 是多模态格式
    loop._save_turn(
        session,
        [{"role": "user", "content": [{"type": "text", "text": runtime}]}],
        skip=0,  # 跳过前 0 条消息（正常保存）
    )

    # 验证消息被跳过，session.messages 为空
    assert session.messages == []


def test_save_turn_keeps_image_placeholder_after_runtime_strip() -> None:
    """
    测试移除运行时上下文后保留图片占位符

    这个测试验证当用户消息包含运行时上下文和图片时，
    _save_turn 方法会：
    1. 移除运行时上下文
    2. 保留图片，并替换为占位符 "[image]"

    背景说明：
    ---------
    多模态消息（包含图片、文件等）的处理逻辑：
    - 图片数据（base64 编码）占用大量 token
    - 保存到历史时，使用占位符 "[image]" 代替
    - 既保留消息结构，又节省 token

    测试步骤：
    ---------
    1. 创建 AgentLoop 实例
    2. 创建 Session，key 为 "test:image"
    3. 创建包含运行时上下文和图片的消息：
       - 第一部分：运行时上下文（text 类型）
       - 第二部分：图片（image_url 类型，base64 编码）
    4. 调用 _save_turn 保存消息
    5. 验证保存的消息只包含 "[image]" 占位符

    为什么重要：
    -----------
    - 节省 token：图片 base64 编码占用大量 token
    - 保持结构：保留消息的多模态结构信息
    - 一致性：统一使用 "[image]" 占位符
    """
    # 创建最小化的 AgentLoop 实例
    loop = _mk_loop()
    # 创建 Session
    session = Session(key="test:image")
    # 创建运行时上下文内容
    runtime = ContextBuilder._RUNTIME_CONTEXT_TAG + "\nCurrent Time: now (UTC)"

    # 调用 _save_turn 保存消息
    # 消息包含两部分：运行时上下文和图片
    loop._save_turn(
        session,
        [{
            "role": "user",
            "content": [
                # 第一部分：运行时上下文（会被移除）
                {"type": "text", "text": runtime},
                # 第二部分：图片（base64 编码的 PNG 数据）
                # 保存时会被替换为 "[image]" 占位符
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        }],
        skip=0,
    )

    # 验证保存的消息
    # 运行时上下文被移除，图片被替换为占位符
    assert session.messages[0]["content"] == [{"type": "text", "text": "[image]"}]


def test_save_turn_keeps_tool_results_under_16k() -> None:
    """
    测试工具结果（<16KB）能够完整保存

    这个测试验证当工具调用返回大量内容时（如读取大文件），
    _save_turn 方法能够完整保存这些内容（在 16KB 限制内）。

    背景说明：
    ---------
    工具调用结果（如 read_file 工具返回的文件内容）可能很大：
    - 需要设置合理的上限，防止占用过多 token
    - 16KB 是一个合理的限制，能容纳大多数文件内容
    - 超过限制的内容需要截断处理（此测试不验证）

    测试步骤：
    ---------
    1. 创建 AgentLoop 实例
    2. 创建 Session，key 为 "test:tool-result"
    3. 创建 12KB 的工具结果内容（12000 个 "x" 字符）
    4. 调用 _save_turn 保存工具结果消息
    5. 验证内容被完整保存

    消息格式说明：
    -----------
    工具结果消息的格式：
    {
        "role": "tool",           # 角色为 "tool"
        "tool_call_id": "call_1", # 关联的工具调用 ID
        "name": "read_file",      # 工具名称
        "content": "..."          # 工具返回的内容
    }

    为什么重要：
    -----------
    - 确保工具结果能够完整保存（在限制内）
    - 验证 16KB 限制的设置是否合理
    - 防止因内容截断导致的信息丢失
    """
    # 创建最小化的 AgentLoop 实例
    loop = _mk_loop()
    # 创建 Session
    session = Session(key="test:tool-result")
    # 创建 12KB 的内容（12000 个字符）
    content = "x" * 12_000

    # 调用 _save_turn 保存工具结果
    # 消息格式：role="tool", 包含 tool_call_id, name, content
    loop._save_turn(
        session,
        [{"role": "tool", "tool_call_id": "call_1", "name": "read_file", "content": content}],
        skip=0,
    )

    # 验证内容被完整保存
    assert session.messages[0]["content"] == content

# =============================================================================
# 记忆巩固偏移测试
# 文件路径：tests/test_consolidate_offset.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了会话管理中的记忆巩固（memory consolidation）功能的测试，
# 主要测试会话消息的缓存友好型处理机制。
#
# 核心概念：
# - last_consolidated: 记录最后已巩固的消息索引，避免重复处理
# - MEMORY_WINDOW: 记忆窗口大小（50 条消息）
# - KEEP_COUNT: 保留的最近消息数量（25 条，即 MEMORY_WINDOW 的一半）
# - 消息切片：messages[last_consolidated:-keep_count] 用于获取待巩固的消息
#
# 测试场景：
# --------
# 1. TestSessionLastConsolidated - last_consolidated 跟踪测试
#    - 初始值为 0
#    - 持久化保存/加载
#    - clear() 后重置为 0
#
# 2. TestSessionImmutableHistory - 消息历史不可变性测试
#    - 确保消息列表只追加不修改
#    - get_history() 不影响原始消息
#    - 缓存安全性验证
#
# 3. TestSessionPersistence - 会话持久化测试
#    - 保存/加载往返测试
#    - get_history 在 reload 后正常工作
#
# 4. TestConsolidationTriggerConditions - 巩固触发条件测试
#    - 消息超出窗口时触发
#    - 消息在 keep_count 内时跳过
#    - 无新消息时跳过
#
# 5. TestLastConsolidatedEdgeCases - 边界情况测试
#    - last_consolidated 超过消息总数（数据损坏）
#    - last_consolidated 为负值（无效状态）
#    - 巩固后添加新消息
#
# 6. TestArchiveAllMode - 归档所有模式测试（/new 命令使用）
#    - archive_all=True 时巩固所有消息
#    - 重置 last_consolidated 为 0
#
# 7. TestCacheImmutability - 缓存不可变性测试
#    - 巩固不修改 messages 列表
#    - 只更新 last_consolidated 字段
#
# 8. TestSliceLogic - 切片逻辑测试
#    - 验证切片提取正确的消息范围
#    - 部分巩固时的切片行为
#
# 9. TestEmptyAndBoundarySessions - 空会话和边界条件测试
#    - 空会话、单消息会话
#    - 正好 keep_count 条消息
#    - 超大会话（1000 条消息）
#
# 10. TestNewCommandArchival - /new 命令归档行为测试
#     - 归档失败时不清除会话
#     - 只归档未巩固的消息
#     - 成功后清除会话并响应
#
# 使用示例：
# --------
# pytest tests/test_consolidate_offset.py -v
# =============================================================================

"""Test session management with cache-friendly message handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pathlib import Path
from nanobot.session.manager import Session, SessionManager

# 测试常量
# MEMORY_WINDOW: 记忆窗口大小，当消息总数超过此值时触发巩固
MEMORY_WINDOW = 50
# KEEP_COUNT: 保留的最近消息数量（窗口大小的一半）
# 巩固时会保留最近的 KEEP_COUNT 条消息不被归档
KEEP_COUNT = MEMORY_WINDOW // 2  # 25


def create_session_with_messages(key: str, count: int, role: str = "user") -> Session:
    """创建会话并添加指定数量的消息。

    辅助函数，用于快速创建包含测试数据的会话对象。

    Args:
        key: 会话标识符，格式通常为 "test:name"
        count: 要添加的消息数量
        role: 消息角色，默认为 "user"，可选 "assistant"

    Returns:
        包含指定数量消息的 Session 对象

    使用示例:
        session = create_session_with_messages("test:my", 10, "user")
        # 创建一个包含 10 条用户消息的会话
    """
    session = Session(key=key)
    for i in range(count):
        session.add_message(role, f"msg{i}")
    return session


def assert_messages_content(messages: list, start_index: int, end_index: int) -> None:
    """断言消息内容包含预期的起始和结束索引。

    辅助函数，用于验证消息列表的内容是否正确。

    Args:
        messages: 消息字典列表
        start_index: 期望的第一条消息索引
        end_index: 期望的最后一条消息索引

    使用示例:
        old_messages = session.messages[0:35]
        assert_messages_content(old_messages, 0, 34)
        # 验证消息内容为 msg0 到 msg34
    """
    assert len(messages) > 0
    assert messages[0]["content"] == f"msg{start_index}"
    assert messages[-1]["content"] == f"msg{end_index}"


def get_old_messages(session: Session, last_consolidated: int, keep_count: int) -> list:
    """使用标准切片逻辑提取待巩固的消息。

    这是核心的切片逻辑：messages[last_consolidated:-keep_count]
    - 从 last_consolidated 索引开始（已巩固消息之后）
    - 到 -keep_count 结束（保留最近的 keep_count 条消息）

    Args:
        session: 包含消息的 Session 对象
        last_consolidated: 最后已巩固的消息索引
        keep_count: 要保留的最近消息数量

    Returns:
        待巩固的消息列表

    切片行为说明:
        - 当 last_consolidated=0, keep_count=25, 总消息数=60 时:
          messages[0:-25] 返回前 35 条消息（索引 0-34）
        - 当 last_consolidated=30, keep_count=25, 总消息数=70 时:
          messages[30:-25] 返回索引 30-44 的 15 条消息
        - 当 last_consolidated >= total - keep_count 时:
          返回空列表（无需巩固）
    """
    return session.messages[last_consolidated:-keep_count]


class TestSessionLastConsolidated:
    """测试 last_consolidated 跟踪机制，避免重复处理消息。

    last_consolidated 字段记录最后已巩固的消息索引，确保：
    1. 不会重复巩固同一条消息
    2. 巩固状态在保存/加载后保持不变
    3. 会话重置时正确初始化
    """

    def test_initial_last_consolidated_zero(self) -> None:
        """测试新建会话的 last_consolidated 初始值为 0。

        验证：新创建的会话没有已巩固的消息，last_consolidated 从 0 开始。
        """
        session = Session(key="test:initial")
        assert session.last_consolidated == 0

    def test_last_consolidated_persistence(self, tmp_path) -> None:
        """测试 last_consolidated 在保存/加载后保持不变。

        验证：last_consolidated 字段正确持久化到磁盘，
        重新加载会话后值不变。
        """
        manager = SessionManager(Path(tmp_path))
        session1 = create_session_with_messages("test:persist", 20)
        session1.last_consolidated = 15  # 模拟已巩固 15 条消息
        manager.save(session1)

        session2 = manager.get_or_create("test:persist")
        assert session2.last_consolidated == 15
        assert len(session2.messages) == 20

    def test_clear_resets_last_consolidated(self) -> None:
        """测试 clear() 方法重置 last_consolidated 为 0。

        验证：当会话被清空时，last_consolidated 也重置为 0，
        确保状态一致性。
        """
        session = create_session_with_messages("test:clear", 10)
        session.last_consolidated = 5  # 设置非零值

        session.clear()  # 清空会话
        assert len(session.messages) == 0
        assert session.last_consolidated == 0  # 验证重置为 0


class TestSessionImmutableHistory:
    """测试 Session 消息的不可变性，确保缓存效率。

    为了支持提示词缓存（prompt caching），消息历史必须是稳定的：
    - 已存在的消息永远不被修改
    - 只允许追加新消息
    - get_history() 不改变内部状态

    这样，相同的消息前缀可以命中缓存，减少 token 消耗。
    """

    def test_initial_state(self) -> None:
        """测试新建会话的消息列表为空。"""
        session = Session(key="test:initial")
        assert len(session.messages) == 0

    def test_add_messages_appends_only(self) -> None:
        """测试添加消息只会追加，从不修改已有消息。

        验证：每次 add_message 都在末尾追加，
        已存在的消息内容保持不变。
        """
        session = Session(key="test:preserve")
        session.add_message("user", "msg1")
        session.add_message("assistant", "resp1")
        session.add_message("user", "msg2")
        assert len(session.messages) == 3
        assert session.messages[0]["content"] == "msg1"  # 第一条消息未被修改

    def test_get_history_returns_most_recent(self) -> None:
        """测试 get_history 返回最近的消息。

        验证：get_history(max_messages=N) 返回最近的 N 条消息，
        按时间顺序排列。
        """
        session = Session(key="test:history")
        for i in range(10):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")

        # 获取最近 6 条消息（应该是 msg7, resp7, msg8, resp8, msg9, resp9）
        history = session.get_history(max_messages=6)
        assert len(history) == 6
        assert history[0]["content"] == "msg7"  # 第 7 轮的第一条
        assert history[-1]["content"] == "resp9"  # 最后一轮的最后一条

    def test_get_history_with_all_messages(self) -> None:
        """测试 max_messages 大于实际消息数时返回所有消息。"""
        session = create_session_with_messages("test:all", 5)
        history = session.get_history(max_messages=100)  # 请求 100 条，实际只有 5 条
        assert len(history) == 5
        assert history[0]["content"] == "msg0"

    def test_get_history_stable_for_same_session(self) -> None:
        """测试 get_history 对相同的 max_messages 返回相同内容。

        验证：多次调用 get_history 不会改变返回结果，
        这对缓存一致性很重要。
        """
        session = create_session_with_messages("test:stable", 20)
        history1 = session.get_history(max_messages=10)
        history2 = session.get_history(max_messages=10)
        assert history1 == history2  # 两次结果完全相同

    def test_messages_list_never_modified(self) -> None:
        """测试消息列表在 get_history 调用后不被修改。

        验证：无论调用多少次 get_history，
        消息列表的长度和内容都保持不变。
        """
        session = create_session_with_messages("test:immutable", 5)
        original_len = len(session.messages)

        session.get_history(max_messages=2)
        assert len(session.messages) == original_len

        # 多次调用也不影响
        for _ in range(10):
            session.get_history(max_messages=3)
        assert len(session.messages) == original_len


class TestSessionPersistence:
    """测试 Session 的持久化和重新加载功能。

    验证：
    1. 消息可以正确保存到磁盘
    2. 重新加载后消息内容不变
    3. get_history 在 reload 后正常工作
    """

    @pytest.fixture
    def temp_manager(self, tmp_path):
        """创建临时的 SessionManager 用于测试。"""
        return SessionManager(Path(tmp_path))

    def test_persistence_roundtrip(self, temp_manager):
        """测试消息在保存/加载往返后保持不变。

        验证：保存的 20 条消息重新加载后数量和顺序都正确。
        """
        session1 = create_session_with_messages("test:persistence", 20)
        temp_manager.save(session1)

        session2 = temp_manager.get_or_create("test:persistence")
        assert len(session2.messages) == 20
        assert session2.messages[0]["content"] == "msg0"
        assert session2.messages[-1]["content"] == "msg19"

    def test_get_history_after_reload(self, temp_manager):
        """测试 get_history 在重新加载后正确工作。

        验证：保存 30 条消息后重新加载，
        get_history 能正确获取最近的消息。
        """
        session1 = create_session_with_messages("test:reload", 30)
        temp_manager.save(session1)

        session2 = temp_manager.get_or_create("test:reload")
        history = session2.get_history(max_messages=10)
        assert len(history) == 10
        assert history[0]["content"] == "msg20"  # 第 21 条是最近 10 条的第一条
        assert history[-1]["content"] == "msg29"  # 最后一条

    def test_clear_resets_session(self, temp_manager):
        """测试 clear() 正确重置会话。

        验证：clear() 后消息列表为空。
        """
        session = create_session_with_messages("test:clear", 10)
        assert len(session.messages) == 10

        session.clear()
        assert len(session.messages) == 0


class TestConsolidationTriggerConditions:
    """测试记忆巩固的触发条件和逻辑。

    巩固逻辑：
    1. 当总消息数 > MEMORY_WINDOW (50) 时，需要巩固
    2. 当总消息数 <= KEEP_COUNT (25) 时，跳过巩固
    3. 当没有新消息需要巩固时，跳过巩固
    """

    def test_consolidation_needed_when_messages_exceed_window(self):
        """测试当消息数超出记忆窗口时触发巩固。

        验证：
        - 60 条消息 > 50 (MEMORY_WINDOW)，需要巩固
        - 应巩固 35 条（60 - 25 = 35）
        - 保留最近 25 条
        """
        session = create_session_with_messages("test:trigger", 60)

        total_messages = len(session.messages)
        messages_to_process = total_messages - session.last_consolidated

        assert total_messages > MEMORY_WINDOW
        assert messages_to_process > 0

        expected_consolidate_count = total_messages - KEEP_COUNT
        assert expected_consolidate_count == 35

    def test_consolidation_skipped_when_within_keep_count(self):
        """测试当消息数在 keep_count 内时跳过巩固。

        验证：20 条消息 <= 25 (KEEP_COUNT)，无需巩固。
        """
        session = create_session_with_messages("test:skip", 20)

        total_messages = len(session.messages)
        assert total_messages <= KEEP_COUNT  # 20 <= 25

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 0  # 没有消息需要巩固

    def test_consolidation_skipped_when_no_new_messages(self):
        """测试当没有新消息需要巩固时跳过。

        模拟场景：last_consolidated 已经追上最新消息，
        无需再次巩固。
        """
        session = create_session_with_messages("test:already_consolidated", 40)
        session.last_consolidated = len(session.messages) - KEEP_COUNT  # 15

        # 添加少量新消息
        for i in range(40, 42):
            session.add_message("user", f"msg{i}")

        total_messages = len(session.messages)
        messages_to_process = total_messages - session.last_consolidated
        assert messages_to_process > 0

        # 模拟 last_consolidated 追上
        session.last_consolidated = total_messages - KEEP_COUNT
        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 0  # 没有消息需要巩固


class TestLastConsolidatedEdgeCases:
    """测试 last_consolidated 的边界情况和数据损坏场景。

    这些测试确保即使出现异常数据，系统也能正确处理：
    - last_consolidated 超过消息总数（数据损坏）
    - last_consolidated 为负值（无效状态）
    - 巩固后添加新消息的正常流程
    """

    def test_last_consolidated_exceeds_message_count(self):
        """测试 last_consolidated > len(messages) 的行为（数据损坏场景）。

        可能原因：手动修改会话文件、代码 bug 等
        预期行为：返回空列表，不会崩溃
        """
        session = create_session_with_messages("test:corruption", 10)
        session.last_consolidated = 20  # 超过消息总数 10

        total_messages = len(session.messages)
        messages_to_process = total_messages - session.last_consolidated
        assert messages_to_process <= 0

        old_messages = get_old_messages(session, session.last_consolidated, 5)
        assert len(old_messages) == 0  # 安全处理，返回空列表

    def test_last_consolidated_negative_value(self):
        """测试 last_consolidated 为负值的行为（无效状态）。

        Python 切片支持负索引，这里测试其行为：
        messages[-5:-3] 返回索引 5, 6 的消息
        """
        session = create_session_with_messages("test:negative", 10)
        session.last_consolidated = -5

        keep_count = 3
        old_messages = get_old_messages(session, session.last_consolidated, keep_count)

        # messages[-5:-3] 在 10 条消息中返回索引 5, 6
        assert len(old_messages) == 2
        assert old_messages[0]["content"] == "msg5"
        assert old_messages[-1]["content"] == "msg6"

    def test_messages_added_after_consolidation(self):
        """测试巩固后添加新消息的正确行为。

        场景：
        1. 会话有 40 条消息，last_consolidated = 15
        2. 添加 10 条新消息（索引 40-49）
        3. 待巩固的应该是索引 15-24 的消息
        """
        session = create_session_with_messages("test:new_messages", 40)
        session.last_consolidated = len(session.messages) - KEEP_COUNT  # 15

        # 巩固后添加新消息
        for i in range(40, 50):
            session.add_message("user", f"msg{i}")

        total_messages = len(session.messages)
        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        expected_consolidate_count = total_messages - KEEP_COUNT - session.last_consolidated

        assert len(old_messages) == expected_consolidate_count
        assert_messages_content(old_messages, 15, 24)

    def test_slice_behavior_when_indices_overlap(self):
        """测试当 last_consolidated >= total - keep_count 时的切片行为。

        此时切片起始索引大于等于结束索引，返回空列表。
        """
        session = create_session_with_messages("test:overlap", 30)
        session.last_consolidated = 12

        old_messages = get_old_messages(session, session.last_consolidated, 20)
        assert len(old_messages) == 0  # 30 - 20 = 10, 12 >= 10, 返回空


class TestArchiveAllMode:
    """测试 archive_all 模式（/new 命令使用）。

    /new 命令用于开始新会话，它会：
    1. 归档所有未巩固的消息
    2. 清空当前会话
    3. last_consolidated 重置为 0
    """

    def test_archive_all_consolidates_everything(self):
        """测试 archive_all=True 时巩固所有消息。

        验证：当 archive_all 为真时，所有 50 条消息都会被归档。
        """
        session = create_session_with_messages("test:archive_all", 50)

        archive_all = True
        if archive_all:
            old_messages = session.messages
            assert len(old_messages) == 50  # 所有消息都被归档

        assert session.last_consolidated == 0

    def test_archive_all_resets_last_consolidated(self):
        """测试 archive_all 模式重置 last_consolidated 为 0。

        验证：归档所有消息后，last_consolidated 从 15 重置为 0。
        """
        session = create_session_with_messages("test:reset", 40)
        session.last_consolidated = 15

        archive_all = True
        if archive_all:
            session.last_consolidated = 0

        assert session.last_consolidated == 0
        assert len(session.messages) == 40

    def test_archive_all_vs_normal_consolidation(self):
        """测试 archive_all 和普通巩固的区别。

        普通巩固：
        - last_consolidated = total - KEEP_COUNT（只保留最近的）
        archive_all:
        - last_consolidated = 0（所有消息都待归档）
        """
        # 普通巩固
        session1 = create_session_with_messages("test:normal", 60)
        session1.last_consolidated = len(session1.messages) - KEEP_COUNT  # 35

        # archive_all 模式
        session2 = create_session_with_messages("test:all", 60)
        session2.last_consolidated = 0

        assert session1.last_consolidated == 35  # 普通模式：已巩固 35 条
        assert len(session1.messages) == 60
        assert session2.last_consolidated == 0  # archive_all: 从 0 开始
        assert len(session2.messages) == 60


class TestCacheImmutability:
    """测试巩固不修改 session.messages（缓存安全性）。

    为了支持 LLM 的提示词缓存功能，必须确保：
    1. messages 列表本身不被修改
    2. 只有 last_consolidated 字段被更新
    3. get_history 不影响原始数据
    """

    def test_consolidation_does_not_modify_messages_list(self):
        """测试巩固操作不修改消息列表。

        验证：更新 last_consolidated 不影响 messages 列表。
        """
        session = create_session_with_messages("test:immutable", 50)

        original_messages = session.messages.copy()
        original_len = len(session.messages)
        session.last_consolidated = original_len - KEEP_COUNT

        assert len(session.messages) == original_len
        assert session.messages == original_messages

    def test_get_history_does_not_modify_messages(self):
        """测试 get_history 不修改消息列表。

        验证：多次调用 get_history 后，
        消息列表的长度和每条消息的内容都不变。
        """
        session = create_session_with_messages("test:history_immutable", 40)
        original_messages = [m.copy() for m in session.messages]

        for _ in range(5):
            history = session.get_history(max_messages=10)
            assert len(history) == 10

        assert len(session.messages) == 40
        for i, msg in enumerate(session.messages):
            assert msg["content"] == original_messages[i]["content"]

    def test_consolidation_only_updates_last_consolidated(self):
        """测试巩固只更新 last_consolidated 字段。

        验证：更新 last_consolidated 后，
        messages、key、metadata 都保持不变。
        """
        session = create_session_with_messages("test:field_only", 60)

        original_messages = session.messages.copy()
        original_key = session.key
        original_metadata = session.metadata.copy()

        session.last_consolidated = len(session.messages) - KEEP_COUNT

        assert session.messages == original_messages
        assert session.key == original_key
        assert session.metadata == original_metadata
        assert session.last_consolidated == 35


class TestSliceLogic:
    """测试切片逻辑：messages[last_consolidated:-keep_count]。

    这是巩固功能的核心逻辑，需要验证：
    1. 正确提取待巩固的消息范围
    2. 部分巩固时的行为
    3. 不同 keep_count 值的影响
    4. keep_count 超过消息数时的边界情况
    """

    def test_slice_extracts_correct_range(self):
        """测试切片提取正确的消息范围。

        场景：60 条消息，last_consolidated=0, keep_count=25
        预期：提取索引 0-34（35 条消息）用于巩固
        保留：索引 35-59（25 条消息）
        """
        session = create_session_with_messages("test:slice", 60)

        old_messages = get_old_messages(session, 0, KEEP_COUNT)

        assert len(old_messages) == 35
        assert_messages_content(old_messages, 0, 34)

        remaining = session.messages[-KEEP_COUNT:]
        assert len(remaining) == 25
        assert_messages_content(remaining, 35, 59)

    def test_slice_with_partial_consolidation(self):
        """测试部分巩固时的切片行为。

        场景：70 条消息，last_consolidated=30（已巩固前 30 条）, keep_count=25
        预期：提取索引 30-44（15 条消息）用于巩固
        """
        session = create_session_with_messages("test:partial", 70)

        last_consolidated = 30
        old_messages = get_old_messages(session, last_consolidated, KEEP_COUNT)

        assert len(old_messages) == 15
        assert_messages_content(old_messages, 30, 44)

    def test_slice_with_various_keep_counts(self):
        """测试不同 keep_count 值的切片行为。

        验证各种 keep_count 下，切片长度的正确性。
        """
        session = create_session_with_messages("test:keep_counts", 50)

        test_cases = [(10, 40), (20, 30), (30, 20), (40, 10)]

        for keep_count, expected_count in test_cases:
            old_messages = session.messages[0:-keep_count]
            assert len(old_messages) == expected_count

    def test_slice_when_keep_count_exceeds_messages(self):
        """测试 keep_count > len(messages) 时的切片行为。

        当保留数量超过总消息数时，返回空列表。
        """
        session = create_session_with_messages("test:exceed", 10)

        old_messages = session.messages[0:-20]  # 保留 20 条，但只有 10 条
        assert len(old_messages) == 0


class TestEmptyAndBoundarySessions:
    """测试空会话和边界条件。

    覆盖场景：
    1. 空会话（0 条消息）
    2. 单消息会话
    3. 正好 keep_count 条消息
    4. 比 keep_count 多 1 条
    5. 超大会话（1000 条）
    6. 巩固历史中有间隔的会话
    """

    def test_empty_session_consolidation(self):
        """测试空会话的巩固行为。

        验证：空会话无需巩固，所有值为 0。
        """
        session = Session(key="test:empty")

        assert len(session.messages) == 0
        assert session.last_consolidated == 0

        messages_to_process = len(session.messages) - session.last_consolidated
        assert messages_to_process == 0

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 0

    def test_single_message_session(self):
        """测试单消息会话的巩固行为。

        验证：1 条消息 < keep_count (25)，无需巩固。
        """
        session = Session(key="test:single")
        session.add_message("user", "only message")

        assert len(session.messages) == 1

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 0  # 无需巩固

    def test_exactly_keep_count_messages(self):
        """测试正好 keep_count 条消息的会话。

        验证：25 条消息 = keep_count，无需巩固。
        """
        session = create_session_with_messages("test:exact", KEEP_COUNT)

        assert len(session.messages) == KEEP_COUNT

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 0  # 正好等于 keep_count，无需巩固

    def test_just_over_keep_count(self):
        """测试比 keep_count 多 1 条消息的会话。

        验证：26 条消息 > keep_count (25)，巩固 1 条。
        """
        session = create_session_with_messages("test:over", KEEP_COUNT + 1)

        assert len(session.messages) == 26

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 1  # 只有第 1 条需要巩固
        assert old_messages[0]["content"] == "msg0"

    def test_very_large_session(self):
        """测试超大会话（1000 条消息）的巩固行为。

        验证：
        - 总消息数：1000
        - 待巩固：975 条（1000 - 25）
        - 保留：25 条
        """
        session = create_session_with_messages("test:large", 1000)

        assert len(session.messages) == 1000

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)
        assert len(old_messages) == 975  # 1000 - 25
        assert_messages_content(old_messages, 0, 974)

        remaining = session.messages[-KEEP_COUNT:]
        assert len(remaining) == 25
        assert_messages_content(remaining, 975, 999)

    def test_session_with_gaps_in_consolidation(self):
        """测试巩固历史中有间隔的场景。

        场景：
        1. 初始 50 条消息，last_consolidated = 10（手动设置，模拟间隔）
        2. 添加 10 条新消息（索引 50-59）
        3. 待巩固：索引 10-34（25 条消息）
        """
        session = create_session_with_messages("test:gaps", 50)
        session.last_consolidated = 10  # 模拟部分巩固

        # 添加更多消息
        for i in range(50, 60):
            session.add_message("user", f"msg{i}")

        old_messages = get_old_messages(session, session.last_consolidated, KEEP_COUNT)

        expected_count = 60 - KEEP_COUNT - 10  # 60 - 25 - 10 = 25
        assert len(old_messages) == expected_count
        assert_messages_content(old_messages, 10, 34)


class TestNewCommandArchival:
    """测试 /new 命令的归档行为。

    /new 命令用于开始新会话，它会：
    1. 调用 consolidate_messages 归档未巩固的消息
    2. 如果归档成功，清空会话
    3. 如果归档失败，保留原会话
    4. 返回适当的响应消息

    这些测试使用 Mock 对象模拟 AgentLoop 和相关组件。
    """

    @staticmethod
    def _make_loop(tmp_path: Path):
        """创建用于测试的 AgentLoop Mock 对象。

        使用 MagicMock 和 AsyncMock 模拟：
        - LLM Provider：返回固定的 token 估算
        - chat_with_retry：返回固定的 LLMResponse
        - tools.get_definitions：返回空列表
        """
        from nanobot.agent.loop import AgentLoop
        from nanobot.bus.queue import MessageBus
        from nanobot.providers.base import LLMResponse

        bus = MessageBus()
        provider = MagicMock()
        provider.get_default_model.return_value = "test-model"
        provider.estimate_prompt_tokens.return_value = (10_000, "test")
        loop = AgentLoop(
            bus=bus,
            provider=provider,
            workspace=tmp_path,
            model="test-model",
            context_window_tokens=1,
        )
        loop.provider.chat_with_retry = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
        loop.tools.get_definitions = MagicMock(return_value=[])
        return loop

    @pytest.mark.asyncio
    async def test_new_does_not_clear_session_when_archive_fails(self, tmp_path: Path) -> None:
        """测试当归档失败时，/new 不清除会话。

        场景：
        1. 会话有 10 条消息（5 轮对话）
        2. consolidate_messages 返回 False（失败）
        3. 预期：会话保持不变，响应包含 "failed"
        """
        from nanobot.bus.events import InboundMessage

        loop = self._make_loop(tmp_path)
        session = loop.sessions.get_or_create("cli:test")
        for i in range(5):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        loop.sessions.save(session)
        before_count = len(session.messages)

        # Mock 失败的 consolidate
        async def _failing_consolidate(_messages) -> bool:
            return False

        loop.memory_consolidator.consolidate_messages = _failing_consolidate  # type: ignore[method-assign]

        new_msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/new")
        response = await loop._process_message(new_msg)

        assert response is not None
        assert "failed" in response.content.lower()
        assert len(loop.sessions.get_or_create("cli:test").messages) == before_count  # 会话未变

    @pytest.mark.asyncio
    async def test_new_archives_only_unconsolidated_messages(self, tmp_path: Path) -> None:
        """测试 /new 只归档未巩固的消息。

        场景：
        1. 会话有 30 条消息（15 轮对话）
        2. last_consolidated = 27（只有 3 条未巩固）
        3. 预期：只归档 3 条消息
        """
        from nanobot.bus.events import InboundMessage

        loop = self._make_loop(tmp_path)
        session = loop.sessions.get_or_create("cli:test")
        for i in range(15):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        session.last_consolidated = len(session.messages) - 3  # 27，只有 3 条未巩固
        loop.sessions.save(session)

        archived_count = -1

        async def _fake_consolidate(messages) -> bool:
            nonlocal archived_count
            archived_count = len(messages)  # 记录归档的消息数
            return True

        loop.memory_consolidator.consolidate_messages = _fake_consolidate  # type: ignore[method-assign]

        new_msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/new")
        response = await loop._process_message(new_msg)

        assert response is not None
        assert "new session started" in response.content.lower()
        assert archived_count == 3  # 只归档了 3 条未巩固的消息

    @pytest.mark.asyncio
    async def test_new_clears_session_and_responds(self, tmp_path: Path) -> None:
        """测试 /new 成功归档后清除会话并响应。

        场景：
        1. 会话有 6 条消息（3 轮对话）
        2. consolidate_messages 返回 True（成功）
        3. 预期：会话被清空，响应包含 "new session started"
        """
        from nanobot.bus.events import InboundMessage

        loop = self._make_loop(tmp_path)
        session = loop.sessions.get_or_create("cli:test")
        for i in range(3):
            session.add_message("user", f"msg{i}")
            session.add_message("assistant", f"resp{i}")
        loop.sessions.save(session)

        async def _ok_consolidate(_messages) -> bool:
            return True

        loop.memory_consolidator.consolidate_messages = _ok_consolidate  # type: ignore[method-assign]

        new_msg = InboundMessage(channel="cli", sender_id="user", chat_id="test", content="/new")
        response = await loop._process_message(new_msg)

        assert response is not None
        assert "new session started" in response.content.lower()
        assert loop.sessions.get_or_create("cli:test").messages == []  # 会话已清空

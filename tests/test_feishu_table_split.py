# =============================================================================
# 飞书表格分割测试
# 文件路径：tests/test_feishu_table_split.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了飞书 (Feishu) 渠道的表格分割功能测试，主要测试
# FeishuChannel._split_elements_by_table_limit 辅助函数。
#
# 核心问题：
# 飞书卡片 API 限制每条消息只能包含一个 table 元素。
# 如果消息包含多个表格，API 会返回错误：
#   API error 11310: card table number over limit
#
# 解决方案：
# _split_elements_by_table_limit 函数将包含多个表格的元素列表
# 分割成多个组，每组最多包含一个表格，然后发送多张卡片。
#
# 测试场景：
# --------
# 1. test_empty_list_returns_single_empty_group
#    - 空列表返回单个空组
#
# 2. test_no_tables_returns_single_group
#    - 没有表格时返回单个组（无需分割）
#
# 3. test_single_table_stays_in_one_group
#    - 单个表格保持在单个组内
#
# 4. test_two_tables_split_into_two_groups
#    - 两个表格分割成两个组
#
# 5. test_three_tables_split_into_three_groups
#    - 三个表格分割成三个组
#
# 6. test_leading_markdown_stays_with_first_table
#    - 表格前的文本与第一个表格同组
#
# 7. test_trailing_markdown_after_second_table
#    - 第二个表格后的文本与第二个表格同组
#
# 8. test_non_table_elements_before_first_table_kept_in_first_group
#    - 第一个表格前的非表格元素保留在第一个组
#
# 分割算法说明:
# ------------
# 1. 遍历元素列表
# 2. 遇到表格元素时，如果当前组已有表格，则创建新组
# 3. 非表格元素添加到当前组
# 4. 返回至少包含一个空组的列表（即使输入为空）
#
# 使用示例：
# --------
# pytest tests/test_feishu_table_split.py -v
# =============================================================================

"""Tests for FeishuChannel._split_elements_by_table_limit.

飞书卡片拒绝包含超过一个表格元素的消息
(API 错误 11310: 卡片表格数量超限)。该辅助函数将扁平的
卡片元素列表分割成多个组，每组最多包含一个表格，
使 nanobot 可以发送多张卡片而不是失败。
"""

from nanobot.channels.feishu import FeishuChannel


def _md(text: str) -> dict:
    """创建 markdown 元素用于测试。

    辅助函数，简化测试中 markdown 元素的创建。

    Args:
        text: markdown 文本内容

    Returns:
        飞书 markdown 元素字典

    飞书 markdown 元素格式:
        {"tag": "markdown", "content": "文本内容"}
    """
    return {"tag": "markdown", "content": text}


def _table() -> dict:
    """创建 table 元素用于测试。

    辅助函数，简化测试中表格元素的创建。
    每次调用返回一个新的表格，避免引用相等问题。

    Returns:
        飞书 table 元素字典

    飞书 table 元素格式:
        {
            "tag": "table",
            "columns": [{"tag": "column", "name": "c0", "display_name": "A", "width": "auto"}],
            "rows": [{"c0": "值"}],
            "page_size": 2,
        }
    """
    return {
        "tag": "table",
        "columns": [{"tag": "column", "name": "c0", "display_name": "A", "width": "auto"}],
        "rows": [{"c0": "v"}],
        "page_size": 2,
    }


# 获取待测试的函数引用
# _split_elements_by_table_limit 是 FeishuChannel 的静态方法
# 用于将元素列表分割成多个组，每组最多包含一个表格
split = FeishuChannel._split_elements_by_table_limit


def test_empty_list_returns_single_empty_group() -> None:
    """测试空列表返回单个空组。

    验证场景：
    1. 输入空列表 []
    2. 返回 [[]]（包含一个空组的列表）

    设计说明:
    - 返回至少一个组，确保调用方不需要特殊处理空输入
    - 空组表示"没有要发送的内容"，但仍是一个有效的结果
    """
    assert split([]) == [[]]


def test_no_tables_returns_single_group() -> None:
    """测试没有表格时返回单个组（无需分割）。

    验证场景：
    1. 元素列表只包含 markdown 元素
    2. 没有表格，无需分割
    3. 返回包含原始列表的单组

    这是常见场景：大多数消息只包含文本，没有表格。
    """
    els = [_md("hello"), _md("world")]
    result = split(els)
    assert result == [els]  # 返回单组，包含所有元素


def test_single_table_stays_in_one_group() -> None:
    """测试单个表格保持在单个组内。

    验证场景：
    1. 元素列表包含 markdown + 表格 + markdown
    2. 只有一个表格，无需分割
    3. 所有元素保持在同一组

    这是常见场景：单表格消息是飞书 API 允许的最大复杂度。
    """
    els = [_md("intro"), _table(), _md("outro")]
    result = split(els)
    assert len(result) == 1  # 单组
    assert result[0] == els  # 包含所有元素


def test_two_tables_split_into_two_groups() -> None:
    """测试两个表格分割成两个组。

    验证场景：
    1. 元素列表包含：markdown + 表格 1 + markdown + 表格 2 + markdown
    2. 需要分割成两组，每组一个表格
    3. 分割点：第一个表格后

    分割规则:
    - 第一个表格前的所有元素 + 表格 1 = 组 0
    - 表格 1 后到表格 2 的元素 + 表格 2 = 组 1
    - 表格 2 后的元素跟随表格 2

    注意：
    两个表格使用不同的行值，确保它们不相等（避免引用比较问题）。
    """
    # 使用不同的行值，确保两个表格不相等
    t1 = {
        "tag": "table",
        "columns": [{"tag": "column", "name": "c0", "display_name": "A", "width": "auto"}],
        "rows": [{"c0": "table-one"}],
        "page_size": 2,
    }
    t2 = {
        "tag": "table",
        "columns": [{"tag": "column", "name": "c0", "display_name": "B", "width": "auto"}],
        "rows": [{"c0": "table-two"}],
        "page_size": 2,
    }
    els = [_md("before"), t1, _md("between"), t2, _md("after")]
    result = split(els)
    assert len(result) == 2  # 两组
    # 第一组：表格 1 前的文本 + 表格 1
    assert t1 in result[0]
    assert t2 not in result[0]
    # 第二组：表格间的文本 + 表格 2 + 表格后的文本
    assert t2 in result[1]
    assert t1 not in result[1]


def test_three_tables_split_into_three_groups() -> None:
    """测试三个表格分割成三个组。

    验证场景：
    1. 元素列表只包含三个表格
    2. 每个表格单独成组
    3. 验证可扩展性

    这个测试确保算法可以处理任意数量的表格。
    """
    tables = [
        {"tag": "table", "columns": [], "rows": [{"c0": f"t{i}"}], "page_size": 1}
        for i in range(3)
    ]
    els = tables[:]
    result = split(els)
    assert len(result) == 3  # 三组
    for i, group in enumerate(result):
        assert tables[i] in group  # 每个组包含对应的表格


def test_leading_markdown_stays_with_first_table() -> None:
    """测试表格前的 markdown 与第一个表格同组。

    验证场景：
    1. 元素列表：intro markdown + 表格
    2. intro 应该与表格在同一组
    3. 不需要分割

    这是边界情况测试：确保前置元素正确分组。
    """
    intro = _md("intro")
    t = _table()
    result = split([intro, t])
    assert len(result) == 1  # 单组
    assert result[0] == [intro, t]  # intro 和表格同组


def test_trailing_markdown_after_second_table() -> None:
    """测试第二个表格后的 markdown 与第二个表格同组。

    验证场景：
    1. 元素列表：表格 1 + 表格 2 + tail markdown
    2. tail 应该与表格 2 在同一组
    3. 表格 1 单独成组

    分割规则：
    - 组 0: [表格 1]
    - 组 1: [表格 2, tail]

    这确保后置元素不会丢失。
    """
    t1, t2 = _table(), _table()
    tail = _md("end")
    result = split([t1, t2, tail])
    assert len(result) == 2  # 两组
    # tail 与第二个表格同组
    assert result[1] == [t2, tail]


def test_non_table_elements_before_first_table_kept_in_first_group() -> None:
    """测试第一个表格前的非表格元素保留在第一个组。

    验证场景：
    1. 元素列表：head markdown + 表格 1 + 表格 2
    2. head 应该与表格 1 同组
    3. 表格 2 单独成组

    分割规则:
    - 组 0: [head, 表格 1]
    - 组 1: [表格 2]

    这确保前置元素正确跟随它们后面的表格。
    """
    head = _md("head")
    t1, t2 = _table(), _table()
    result = split([head, t1, t2])
    # head + 表格 1 在组 0；表格 2 在组 1
    assert result[0] == [head, t1]
    assert result[1] == [t2]

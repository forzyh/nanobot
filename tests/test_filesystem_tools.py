# =============================================================================
# nanobot 文件系统工具测试
# 文件路径：tests/test_filesystem_tools.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 nanobot 增强的文件系统工具的完整测试覆盖，包括：
# - ReadFileTool：读取文件内容的工具
# - EditFileTool：编辑文件内容的工具
# - ListDirTool：列出目录内容的工具
# - _find_match：辅助函数，用于查找文本匹配
#
# 测试的核心功能：
# -------------
# 1. ReadFileTool 测试：
#    - 基本读取功能，验证行号显示
#    - 偏移量和限制参数（offset/limit）
#    - 超出文件末尾的错误处理
#    - 空文件处理
#    - 文件不存在错误处理
#    - 字符预算截断（当文件过大时）
#
# 2. _find_match 辅助函数测试：
#    - 精确匹配
#    - 无匹配情况
#    - CRLF 行标准化处理
#    - 行缩进处理（trim fallback）
#    - 多个候选匹配项
#    - 空字符串处理
#
# 3. EditFileTool 测试：
#    - 精确匹配替换
#    - CRLF 行标准化
#    - 缩进处理回退
#    - 歧义匹配警告
#    - 全部替换（replace_all）
#    - 未找到匹配项的错误处理
#
# 4. ListDirTool 测试：
#    - 基本目录列表
#    - 递归列表
#    - 最大条目数截断
#    - 空目录处理
#    - 目录不存在的错误处理
#
# 关键测试场景：
# ------------
# 1. 正常场景：文件读取、编辑、目录列表的基本功能
# 2. 边界场景：空文件、超出文件末尾、大文件截断
# 3. 异常场景：文件不存在、目录不存在、匹配失败
# 4. 特殊场景：CRLF 行标准化、缩进处理、歧义匹配
#
# 使用示例：
# --------
# 运行所有测试：pytest tests/test_filesystem_tools.py -v
# 运行特定类测试：pytest tests/test_filesystem_tools.py::TestReadFileTool -v
# 运行单个测试：pytest tests/test_filesystem_tools.py::TestReadFileTool::test_basic_read_has_line_numbers -v
# =============================================================================

import pytest

from nanobot.agent.tools.filesystem import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    _find_match,
)


# ---------------------------------------------------------------------------
# ReadFileTool 测试类
# ---------------------------------------------------------------------------
# 测试 ReadFileTool 工具的各种功能，包括：
# - 基本文件读取
# - 行号显示
# - 偏移量和限制
# - 错误处理（文件不存在、空文件、超出范围等）
# - 大文件截断

class TestReadFileTool:
    """
    ReadFileTool 工具测试类

    这个类测试 ReadFileTool 的核心功能：
    1. 读取文件时显示行号，便于用户定位
    2. 支持 offset 和 limit 参数进行分页读取
    3. 当文件过大时自动截断，提示用户继续读取
    4. 完善的错误处理（文件不存在、空文件等）
    """

    @pytest.fixture()
    def tool(self, tmp_path):
        """
        创建 ReadFileTool 实例的夹具

        Args:
            tmp_path: pytest 提供的临时目录路径

        Returns:
            ReadFileTool: 使用临时目录作为工作空间的工具实例
        """
        return ReadFileTool(workspace=tmp_path)

    @pytest.fixture()
    def sample_file(self, tmp_path):
        """
        创建包含 20 行文本的示例文件

        每行格式为：line 0, line 1, line 2, ... line 19
        用于测试基本的读取功能

        Args:
            tmp_path: pytest 提供的临时目录路径

        Returns:
            Path: 示例文件的路径
        """
        f = tmp_path / "sample.txt"
        # 生成 20 行文本，每行格式为 "line {序号}"
        f.write_text("\n".join(f"line {i}" for i in range(1, 21)), encoding="utf-8")
        return f

    @pytest.mark.asyncio
    async def test_basic_read_has_line_numbers(self, tool, sample_file):
        """
        测试基本读取功能包含行号

        验证读取文件时，每行前面都有行号前缀（如 "1| line 1"）
        这有助于用户在对话中准确引用文件的特定行

        测试步骤：
        1. 读取示例文件的全部内容
        2. 验证第一行有行号 "1| line 1"
        3. 验证最后一行有行号 "20| line 20"
        """
        result = await tool.execute(path=str(sample_file))
        assert "1| line 1" in result
        assert "20| line 20" in result

    @pytest.mark.asyncio
    async def test_offset_and_limit(self, tool, sample_file):
        """
        测试偏移量 (offset) 和限制 (limit) 参数

        验证通过 offset 和 limit 可以分页读取文件内容
        这对于处理大文件非常有用，可以逐步读取

        测试步骤：
        1. 从第 5 行开始读取 3 行（offset=5, limit=3）
        2. 验证包含第 5、6、7 行
        3. 验证不包含第 8 行
        4. 验证提示用户继续使用 offset=8 读取后续内容
        """
        result = await tool.execute(path=str(sample_file), offset=5, limit=3)
        assert "5| line 5" in result
        assert "7| line 7" in result
        assert "8| line 8" not in result
        # 验证提示用户继续读取的信息
        assert "Use offset=8 to continue" in result

    @pytest.mark.asyncio
    async def test_offset_beyond_end(self, tool, sample_file):
        """
        测试偏移量超出文件末尾的错误处理

        当 offset 参数超出文件总行数时，应该返回错误信息
        这防止用户尝试读取不存在的行

        测试步骤：
        1. 使用 offset=999（远超文件的 20 行）读取
        2. 验证返回结果包含 "Error"
        3. 验证返回结果包含 "beyond end" 提示
        """
        result = await tool.execute(path=str(sample_file), offset=999)
        assert "Error" in result
        assert "beyond end" in result

    @pytest.mark.asyncio
    async def test_end_of_file_marker(self, tool, sample_file):
        """
        测试文件结束标记

        当读取接近或到达文件末尾时，应该显示 "End of file" 标记
        这告知用户已经读取完整个文件

        测试步骤：
        1. 从第 1 行开始读取大量行（offset=1, limit=9999）
        2. 验证返回结果包含 "End of file" 标记
        """
        result = await tool.execute(path=str(sample_file), offset=1, limit=9999)
        assert "End of file" in result

    @pytest.mark.asyncio
    async def test_empty_file(self, tool, tmp_path):
        """
        测试空文件处理

        当尝试读取空文件时，应该友好地提示用户文件为空
        而不是返回空字符串或错误

        测试步骤：
        1. 创建一个空文件
        2. 尝试读取该文件
        3. 验证返回结果包含 "Empty file" 提示
        """
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")
        result = await tool.execute(path=str(f))
        assert "Empty file" in result

    @pytest.mark.asyncio
    async def test_file_not_found(self, tool, tmp_path):
        """
        测试文件不存在的错误处理

        当尝试读取不存在的文件时，应该返回清晰的错误信息
        这有助于用户了解问题所在

        测试步骤：
        1. 尝试读取一个不存在的文件
        2. 验证返回结果包含 "Error"
        3. 验证返回结果包含 "not found" 提示
        """
        result = await tool.execute(path=str(tmp_path / "nope.txt"))
        assert "Error" in result
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_char_budget_trims(self, tool, tmp_path):
        """
        测试字符预算截断功能

        当文件内容超过最大字符限制 (_MAX_CHARS) 时，
        工具应该自动截断输出，并提示用户继续读取剩余部分

        这对于处理超大文件非常重要，防止：
        1. 占用过多的 token 预算
        2. 响应过长导致超时
        3. 用户体验下降

        测试步骤：
        1. 创建一个大约 220KB 的大文件（2000 行，每行约 110 字符）
        2. 读取整个文件
        3. 验证输出不超过最大字符限制 + 小余量
        4. 验证提示用户继续使用 offset 读取
        """
        f = tmp_path / "big.txt"
        # 每行约 110 字符，2000 行 ≈ 220KB > 128KB 限制
        f.write_text("\n".join("x" * 110 for _ in range(2000)), encoding="utf-8")
        result = await tool.execute(path=str(f))
        # 验证输出长度不超过最大字符限制（加小余量）
        assert len(result) <= ReadFileTool._MAX_CHARS + 500  # 小余量
        assert "Use offset=" in result


# ---------------------------------------------------------------------------
# _find_match 辅助函数测试类
# ---------------------------------------------------------------------------
# _find_match 是 EditFileTool 的内部辅助函数，用于：
# 1. 在文件内容中查找要替换的文本
# 2. 处理行标准化（CRLF 转 LF）
# 3. 处理缩进差异
# 4. 检测歧义匹配（多个匹配项）

class TestFindMatch:
    """
    _find_match 辅助函数测试类

    _find_match 函数是 EditFileTool 的核心，负责：
    1. 在文件内容中查找要替换的旧文本
    2. 返回匹配位置和匹配次数
    3. 处理各种边界情况（CRLF、缩进、歧义等）

    函数签名：_find_match(content: str, old_text: str) -> tuple[str | None, int]
    返回值：(匹配的文本，匹配次数)
    """

    def test_exact_match(self):
        """
        测试精确匹配

        当 old_text 在 content 中精确存在时，应该返回匹配结果
        """
        match, count = _find_match("hello world", "world")
        assert match == "world"
        assert count == 1

    def test_exact_no_match(self):
        """
        测试精确无匹配

        当 old_text 不在 content 中时，应该返回 None 和 0
        """
        match, count = _find_match("hello world", "xyz")
        assert match is None
        assert count == 0

    def test_crlf_normalisation(self):
        """
        测试 CRLF 行标准化处理

        Windows 系统使用 CRLF (\\r\\n) 作为行结束符，
        Unix/Linux/Mac 使用 LF (\\n)。

        调用者在调用 _find_match 之前会标准化 CRLF，
        所以这个测试验证标准化后的精确匹配仍然有效。
        """
        content = "line1\nline2\nline3"
        old_text = "line1\nline2\nline3"
        match, count = _find_match(content, old_text)
        assert match is not None
        assert count == 1

    def test_line_trim_fallback(self):
        """
        测试行缩进处理回退

        当用户提供的 old_text 缩进与文件实际缩进不匹配时，
        _find_match 应该能够智能地处理这种情况。

        例如：
        - 文件内容：有 4 空格缩进的 "def foo():"
        - 用户提供：无缩进的 "def foo():"
        - 期望：能够匹配并返回原始缩进的内容
        """
        content = "    def foo():\n        pass\n"
        old_text = "def foo():\n    pass"
        match, count = _find_match(content, old_text)
        assert match is not None
        assert count == 1
        # 验证返回的匹配保留原始缩进
        assert "    def foo():" in match

    def test_line_trim_multiple_candidates(self):
        """
        测试行缩进处理的多个候选匹配项

        当有 multi 个相同的代码块时，_find_match 应该返回匹配次数
        这用于检测歧义匹配，提醒用户明确指定要替换的内容
        """
        content = "  a\n  b\n  a\n  b\n"
        old_text = "a\nb"
        match, count = _find_match(content, old_text)
        assert count == 2

    def test_empty_old_text(self):
        """
        测试空字符串处理

        空字符串在任何字符串中都 "匹配"（从技术上讲是前缀）
        这是一个边界情况测试
        """
        match, count = _find_match("hello", "")
        # 空字符串通过精确匹配总是 "在" 任何字符串中
        assert match == ""


# ---------------------------------------------------------------------------
# EditFileTool 测试类
# ---------------------------------------------------------------------------
# 测试 EditFileTool 工具的各种编辑场景，包括：
# - 精确匹配替换
# - CRLF 行标准化
# - 缩进处理
# - 歧义匹配警告
# - 全部替换
# - 错误处理

class TestEditFileTool:
    """
    EditFileTool 工具测试类

    EditFileTool 用于编辑文件内容，支持：
    1. 精确文本替换
    2. 智能处理 CRLF 行标准化
    3. 自动处理缩进差异
    4. 检测歧义匹配并警告
    5. 全部替换模式（replace_all）
    6. 完善的错误处理
    """

    @pytest.fixture()
    def tool(self, tmp_path):
        """
        创建 EditFileTool 实例的夹具

        Args:
            tmp_path: pytest 提供的临时目录路径

        Returns:
            EditFileTool: 使用临时目录作为工作空间的工具实例
        """
        return EditFileTool(workspace=tmp_path)

    @pytest.mark.asyncio
    async def test_exact_match(self, tool, tmp_path):
        """
        测试精确匹配替换

        当 old_text 在文件中精确匹配时，应该成功替换为 new_text

        测试步骤：
        1. 创建包含 "hello world" 的文件
        2. 将 "world" 替换为 "earth"
        3. 验证返回结果包含 "Successfully"
        4. 验证文件内容变为 "hello earth"
        """
        f = tmp_path / "a.py"
        f.write_text("hello world", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="world", new_text="earth")
        assert "Successfully" in result
        assert f.read_text() == "hello earth"

    @pytest.mark.asyncio
    async def test_crlf_normalisation(self, tool, tmp_path):
        """
        测试 CRLF 行标准化处理

        编辑文件时，应该能够正确处理不同平台的行结束符：
        - Windows: CRLF (\\r\\n)
        - Unix/Linux/Mac: LF (\\n)

        测试步骤：
        1. 创建使用 CRLF 行结束符的文件
        2. 使用 LF 格式的 old_text 进行替换
        3. 验证替换成功
        4. 验证文件保持 CRLF 行结束符
        """
        f = tmp_path / "crlf.py"
        # 使用 CRLF 行结束符创建文件
        f.write_bytes(b"line1\r\nline2\r\nline3")
        result = await tool.execute(
            path=str(f), old_text="line1\nline2", new_text="LINE1\nLINE2",
        )
        assert "Successfully" in result
        raw = f.read_bytes()
        assert b"LINE1" in raw
        # 验证整个文件保持 CRLF 行结束符
        assert b"\r\n" in raw

    @pytest.mark.asyncio
    async def test_trim_fallback(self, tool, tmp_path):
        """
        测试缩进处理回退

        当用户提供的 old_text 缩进与文件实际缩进不一致时，
        EditFileTool 应该能够智能地处理并找到匹配。

        测试步骤：
        1. 创建有 4 空格缩进的 Python 函数
        2. 使用无缩进的 old_text 进行替换
        3. 验证替换成功
        4. 验证文件包含新的函数名 "bar"
        """
        f = tmp_path / "indent.py"
        f.write_text("    def foo():\n        pass\n", encoding="utf-8")
        result = await tool.execute(
            path=str(f), old_text="def foo():\n    pass", new_text="def bar():\n    return 1",
        )
        assert "Successfully" in result
        assert "bar" in f.read_text()

    @pytest.mark.asyncio
    async def test_ambiguous_match(self, tool, tmp_path):
        """
        测试歧义匹配警告

        当 old_text 在文件中出现多次时，
        EditFileTool 应该警告用户匹配不唯一。

        这防止意外替换错误的位置。

        测试步骤：
        1. 创建包含重复模式的文件（"aaa\nbbb\naaa\nbbb"）
        2. 尝试替换 "aaa\nbbb"
        3. 验证返回结果包含警告信息（"appears" 或 "Warning"）
        """
        f = tmp_path / "dup.py"
        f.write_text("aaa\nbbb\naaa\nbbb\n", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="aaa\nbbb", new_text="xxx")
        # 验证返回歧义警告
        assert "appears" in result.lower() or "Warning" in result

    @pytest.mark.asyncio
    async def test_replace_all(self, tool, tmp_path):
        """
        测试全部替换模式（replace_all）

        当设置 replace_all=True 时，
        EditFileTool 应该替换文件中所有的匹配项。

        测试步骤：
        1. 创建包含多个 "foo" 的文件
        2. 使用 replace_all=True 将所有 "foo" 替换为 "baz"
        3. 验证替换成功
        4. 验证文件内容所有 "foo" 都变成了 "baz"
        """
        f = tmp_path / "multi.py"
        f.write_text("foo bar foo bar foo", encoding="utf-8")
        result = await tool.execute(
            path=str(f), old_text="foo", new_text="baz", replace_all=True,
        )
        assert "Successfully" in result
        assert f.read_text() == "baz bar baz bar baz"

    @pytest.mark.asyncio
    async def test_not_found(self, tool, tmp_path):
        """
        测试未找到匹配的错误处理

        当 old_text 在文件中不存在时，
        EditFileTool 应该返回清晰的错误信息。

        测试步骤：
        1. 创建包含 "hello" 的文件
        2. 尝试替换不存在的 "xyz"
        3. 验证返回结果包含 "Error"
        4. 验证返回结果包含 "not found"
        """
        f = tmp_path / "nf.py"
        f.write_text("hello", encoding="utf-8")
        result = await tool.execute(path=str(f), old_text="xyz", new_text="abc")
        assert "Error" in result
        assert "not found" in result


# ---------------------------------------------------------------------------
# ListDirTool 测试类
# ---------------------------------------------------------------------------
# 测试 ListDirTool 工具的目录列表功能，包括：
# - 基本目录列表
# - 递归列表
# - 最大条目数截断
# - 空目录处理
# - 错误处理
# - 忽略特殊目录（.git, node_modules 等）

class TestListDirTool:
    """
    ListDirTool 工具测试类

    ListDirTool 用于列出目录内容，支持：
    1. 基本目录列表
    2. 递归列表（包括子目录）
    3. 最大条目数限制和截断提示
    4. 自动忽略特殊目录（.git, node_modules 等）
    5. 完善的错误处理
    """

    @pytest.fixture()
    def tool(self, tmp_path):
        """
        创建 ListDirTool 实例的夹具

        Args:
            tmp_path: pytest 提供的临时目录路径

        Returns:
            ListDirTool: 使用临时目录作为工作空间的工具实例
        """
        return ListDirTool(workspace=tmp_path)

    @pytest.fixture()
    def populated_dir(self, tmp_path):
        """
        创建包含多种文件/目录结构的测试目录

        创建以下结构：
        tmp_path/
        ├── src/
        │   ├── main.py
        │   └── utils.py
        ├── README.md
        ├── .git/
        │   └── config
        └── node_modules/
            └── pkg/

        用于测试目录列表的各种功能，
        特别是忽略 .git 和 node_modules 等特殊目录。

        Args:
            tmp_path: pytest 提供的临时目录路径

        Returns:
            Path: 测试目录的路径
        """
        # 创建 src 目录及其文件
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("pass")
        (tmp_path / "src" / "utils.py").write_text("pass")
        # 创建 README 文件
        (tmp_path / "README.md").write_text("hi")
        # 创建 .git 目录（应该被忽略）
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x")
        # 创建 node_modules 目录（应该被忽略）
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg").mkdir()
        return tmp_path

    @pytest.mark.asyncio
    async def test_basic_list(self, tool, populated_dir):
        """
        测试基本目录列表

        验证列出目录内容时：
        1. 显示普通文件和目录（README.md, src）
        2. 忽略 .git 和 node_modules 等特殊目录

        测试步骤：
        1. 列出 populated_dir 的内容
        2. 验证包含 README.md 和 src
        3. 验证不包含 .git 和 node_modules
        """
        result = await tool.execute(path=str(populated_dir))
        assert "README.md" in result
        assert "src" in result
        # .git 和 node_modules 应该被忽略
        assert ".git" not in result
        assert "node_modules" not in result

    @pytest.mark.asyncio
    async def test_recursive(self, tool, populated_dir):
        """
        测试递归目录列表

        当设置 recursive=True 时，应该列出所有子目录中的文件。

        测试步骤：
        1. 递归列出 populated_dir 的内容
        2. 验证包含 src/main.py 和 src/utils.py
        3. 验证包含 README.md
        4. 验证不包含 .git 和 node_modules 中的文件
        """
        result = await tool.execute(path=str(populated_dir), recursive=True)
        assert "src/main.py" in result
        assert "src/utils.py" in result
        assert "README.md" in result
        # 忽略的目录不应该出现
        assert ".git" not in result
        assert "node_modules" not in result

    @pytest.mark.asyncio
    async def test_max_entries_truncation(self, tool, tmp_path):
        """
        测试最大条目数截断

        当目录包含的文件数超过 max_entries 时，
        ListDirTool 应该截断输出并提示用户。

        测试步骤：
        1. 创建包含 10 个文件的目录
        2. 设置 max_entries=3 列出目录
        3. 验证返回结果包含 "truncated" 提示
        4. 验证返回结果包含 "3 of 10" 的截断信息
        """
        # 创建 10 个测试文件
        for i in range(10):
            (tmp_path / f"file_{i}.txt").write_text("x")
        result = await tool.execute(path=str(tmp_path), max_entries=3)
        assert "truncated" in result
        assert "3 of 10" in result

    @pytest.mark.asyncio
    async def test_empty_dir(self, tool, tmp_path):
        """
        测试空目录处理

        当列出空目录时，应该友好地提示用户目录为空。

        测试步骤：
        1. 创建一个空目录
        2. 列出该目录内容
        3. 验证返回结果包含 "empty" 提示
        """
        d = tmp_path / "empty"
        d.mkdir()
        result = await tool.execute(path=str(d))
        assert "empty" in result.lower()

    @pytest.mark.asyncio
    async def test_not_found(self, tool, tmp_path):
        """
        测试目录不存在的错误处理

        当尝试列出不存在的目录时，
        ListDirTool 应该返回清晰的错误信息。

        测试步骤：
        1. 尝试列出不存在的目录
        2. 验证返回结果包含 "Error"
        3. 验证返回结果包含 "not found"
        """
        result = await tool.execute(path=str(tmp_path / "nope"))
        assert "Error" in result
        assert "not found" in result

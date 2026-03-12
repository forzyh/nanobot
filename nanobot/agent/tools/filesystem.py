# =============================================================================
# nanobot 文件系统工具
# 文件路径：nanobot/agent/tools/filesystem.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 nanobot 的文件系统操作工具，让 Agent 能够读写和编辑文件。
#
# 包含的工具：
# ---------
# 1. ReadFileTool - 读取文件内容（支持分页）
# 2. WriteFileTool - 写入文件（创建父目录）
# 3. EditFileTool - 编辑文件（智能匹配文本）
# 4. ListDirTool - 列出目录内容（支持递归）
#
# 核心功能：
# --------
# 1. 路径解析：将相对路径解析为绝对路径（相对于 workspace）
# 2. 目录限制：可选地限制操作只能在特定目录内（安全沙箱）
# 3. 智能匹配：EditFileTool 支持空白字符/行尾差异的容错匹配
# 4. 噪声过滤：自动忽略.git、node_modules、__pycache__等目录
#
# 使用示例：
# --------
# # 读取文件
# read_tool = ReadFileTool(workspace=Path("/project"))
# content = await read_tool.execute("src/main.py", offset=1, limit=100)
#
# # 编辑文件
# edit_tool = EditFileTool(workspace=Path("/project"))
# result = await edit_tool.execute(
#     "src/main.py",
#     old_text="def hello():",
#     new_text="def hello_world():"
# )
# =============================================================================

"""File system tools: read, write, edit, list."""
# 文件系统工具：读取、写入、编辑、列出

import difflib  # 差异比较（用于编辑文件时显示差异）
from pathlib import Path  # 路径处理
from typing import Any  # 任意类型

from nanobot.agent.tools.base import Tool  # 工具基类


def _resolve_path(
    path: str, workspace: Path | None = None, allowed_dir: Path | None = None
) -> Path:
    """
    解析路径：将相对路径解析为绝对路径，并执行目录限制检查。

    路径解析规则：
    -----------
    1. 如果是相对路径且有 workspace，则拼接为绝对路径
    2. 调用 resolve() 解析符号链接，获取规范路径
    3. 如果配置了 allowed_dir，检查结果是否在其中（安全沙箱）

    Args:
        path: 路径字符串（可以是相对路径或绝对路径）
        workspace: 工作空间路径（用于解析相对路径）
        allowed_dir: 允许的目录（可选，用于限制操作范围）

    Returns:
        Path: 解析后的绝对路径

    Raises:
        PermissionError: 如果路径超出 allowed_dir 限制

    示例：
    -----
    >>> _resolve_path("src/main.py", workspace=Path("/project"))
    Path('/project/src/main.py')
    >>> _resolve_path("/etc/passwd", allowed_dir=Path("/project"))
    PermissionError: Path /etc/passwd is outside allowed directory
    """
    p = Path(path).expanduser()  # 展开~为用户主目录
    if not p.is_absolute() and workspace:
        p = workspace / p  # 相对路径拼接 workspace
    resolved = p.resolve()  # 解析符号链接，获取规范路径
    if allowed_dir:
        try:
            # 检查是否在允许的目录内
            resolved.relative_to(allowed_dir.resolve())
        except ValueError:
            # 超出允许范围，抛出权限错误
            raise PermissionError(f"Path {path} is outside allowed directory {allowed_dir}")
    return resolved


class _FsTool(Tool):
    """
    文件系统工具的共享基类。

    提供通用的初始化逻辑和路径解析方法。
    所有文件系统工具（ReadFileTool、WriteFileTool 等）都继承自这个基类。

    属性说明：
    --------
    _workspace: Path | None
        工作空间路径，用于解析相对路径

    _allowed_dir: Path | None
        允许的目录，用于限制操作范围（安全沙箱）

    使用示例：
    --------
    class ReadFileTool(_FsTool):
        @property
        def name(self):
            return "read_file"

        async def execute(self, path: str, **kwargs):
            fp = self._resolve(path)  # 解析路径
            return fp.read_text()
    """

    def __init__(self, workspace: Path | None = None, allowed_dir: Path | None = None):
        """
        初始化文件系统工具。

        Args:
            workspace: 工作空间路径（可选）
            allowed_dir: 允许的目录（可选）
        """
        self._workspace = workspace  # 工作空间
        self._allowed_dir = allowed_dir  # 允许的目录

    def _resolve(self, path: str) -> Path:
        """
        解析路径。

        Args:
            path: 路径字符串

        Returns:
            Path: 解析后的绝对路径
        """
        return _resolve_path(path, self._workspace, self._allowed_dir)



# ---------------------------------------------------------------------------
# read_file - 读取文件工具
# ---------------------------------------------------------------------------

class ReadFileTool(_FsTool):
    """
    读取文件内容，支持可选的行级分页。

    这个工具让 Agent 能够读取文件内容，并以带行号的格式返回。
    对于大文件，可以使用 offset 和 limit 参数进行分页读取。

    核心功能：
    --------
    1. 行号显示：返回的内容带行号（格式：`行号 | 内容`）
    2. 分页读取：支持 offset（起始行）和 limit（最大行数）
    3. 字符限制：超过 128,000 字符自动截断
    4. 错误处理：文件不存在/不是文件/权限错误等

    使用示例：
    --------
    >>> tool = ReadFileTool(workspace=Path("/project"))
    >>> content = await tool.execute("src/main.py", offset=1, limit=100)
    >>> print(content)
    1| def main():
    2|     print("Hello")
    ...
    100|     return 0

    (Showing lines 1-100 of 500. Use offset=101 to continue.)
    """

    _MAX_CHARS = 128_000  # 最大字符数限制
    _DEFAULT_LIMIT = 2000  # 默认最大读取行数

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a file. Returns numbered lines. "
            "Use offset and limit to paginate through large files."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to read"},
                "offset": {
                    "type": "integer",
                    "description": "Line number to start reading from (1-indexed, default 1)",
                    "minimum": 1,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (default 2000)",
                    "minimum": 1,
                },
            },
            "required": ["path"],
        }

    async def execute(self, path: str, offset: int = 1, limit: int | None = None, **kwargs: Any) -> str:
        """
        执行文件读取操作。

        Args:
            path: 文件路径
            offset: 起始行号（1-indexed，默认 1）
            limit: 最大读取行数（默认 2000）
            **kwargs: 其他参数（忽略）

        Returns:
            str: 带行号的文件内容，或错误信息

        返回格式：
        --------
        - 成功：带行号的内容 + 分页提示
        - 空文件："(Empty file: {path})"
        - 错误：错误信息字符串
        """
        try:
            fp = self._resolve(path)  # 解析路径
            if not fp.exists():
                return f"Error: File not found: {path}"
            if not fp.is_file():
                return f"Error: Not a file: {path}"

            all_lines = fp.read_text(encoding="utf-8").splitlines()
            total = len(all_lines)  # 总行数

            # 边界检查
            if offset < 1:
                offset = 1
            if total == 0:
                return f"(Empty file: {path})"
            if offset > total:
                return f"Error: offset {offset} is beyond end of file ({total} lines)"

            # 计算读取范围
            start = offset - 1
            end = min(start + (limit or self._DEFAULT_LIMIT), total)
            # 添加行号
            numbered = [f"{start + i + 1}| {line}" for i, line in enumerate(all_lines[start:end])]
            result = "\n".join(numbered)

            # 超过最大字符数则截断
            if len(result) > self._MAX_CHARS:
                trimmed, chars = [], 0
                for line in numbered:
                    chars += len(line) + 1
                    if chars > self._MAX_CHARS:
                        break
                    trimmed.append(line)
                end = start + len(trimmed)
                result = "\n".join(trimmed)

            # 添加分页提示
            if end < total:
                result += f"\n\n(Showing lines {offset}-{end} of {total}. Use offset={end + 1} to continue.)"
            else:
                result += f"\n\n(End of file — {total} lines total)"
            return result
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error reading file: {e}"


# ---------------------------------------------------------------------------
# write_file - 写入文件工具
# ---------------------------------------------------------------------------

class WriteFileTool(_FsTool):
    """
    写入内容到文件。

    这个工具让 Agent 能够创建或覆盖文件。
    如果父目录不存在，会自动创建。

    核心功能：
    --------
    1. 自动创建父目录
    2. UTF-8 编码写入
    3. 覆盖模式（如果文件已存在则覆盖）

    使用示例：
    --------
    >>> tool = WriteFileTool(workspace=Path("/project"))
    >>> result = await tool.execute("src/new_file.py", content="print('Hello')")
    >>> print(result)
    Successfully wrote 17 bytes to /project/src/new_file.py
    """

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return "Write content to a file at the given path. Creates parent directories if needed."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to write to"},
                "content": {"type": "string", "description": "The content to write"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, path: str, content: str, **kwargs: Any) -> str:
        """
        执行文件写入操作。

        Args:
            path: 文件路径
            content: 要写入的内容
            **kwargs: 其他参数（忽略）

        Returns:
            str: 成功信息或错误信息
        """
        try:
            fp = self._resolve(path)  # 解析路径
            # 创建父目录（如果不存在）
            fp.parent.mkdir(parents=True, exist_ok=True)
            # 写入内容
            fp.write_text(content, encoding="utf-8")
            return f"Successfully wrote {len(content)} bytes to {fp}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error writing file: {e}"


# ---------------------------------------------------------------------------
# edit_file - 编辑文件工具
# ---------------------------------------------------------------------------

def _find_match(content: str, old_text: str) -> tuple[str | None, int]:
    """
    在内容中查找匹配的文本：先精确匹配，然后按行 trimmed 滑动窗口匹配。

    这个函数用于 EditFileTool 的智能匹配功能，可以容忍空白字符的差异。

    匹配策略（优先级从高到低）：
    -----------------------
    1. 精确匹配：old_text 完全匹配 content 中的文本
    2. 行 trimmed 匹配：忽略每行首尾空白后匹配

    Args:
        content: 文件原始内容（使用 LF 行结尾）
        old_text: 要查找的文本（使用 LF 行结尾）

    Returns:
        tuple[str | None, int]: (匹配的文本片段，出现次数)，找不到返回 (None, 0)

    示例：
    -----
    # 精确匹配
    >>> _find_match("def hello():\\n    pass", "def hello():")
    ('def hello():', 1)

    # 行 trimmed 匹配（忽略缩进差异）
    >>> _find_match("    def hello():\\n        pass", "def hello():")
    ('    def hello():', 1)
    """
    # 精确匹配
    if old_text in content:
        return old_text, content.count(old_text)

    # 按行分割
    old_lines = old_text.splitlines()
    if not old_lines:
        return None, 0
    stripped_old = [l.strip() for l in old_lines]  # 去除每行首尾空白
    content_lines = content.splitlines()

    # 滑动窗口匹配
    candidates = []
    for i in range(len(content_lines) - len(stripped_old) + 1):
        window = content_lines[i : i + len(stripped_old)]
        if [l.strip() for l in window] == stripped_old:
            candidates.append("\n".join(window))

    if candidates:
        return candidates[0], len(candidates)  # 返回第一个匹配
    return None, 0


class EditFileTool(_FsTool):
    """
    通过替换文本来编辑文件。

    这个工具让 Agent 能够编辑文件内容，通过指定要替换的旧文本和新文本。
    支持智能匹配（容忍空白字符/行结尾的差异）。

    核心功能：
    --------
    1. 精确匹配：优先查找完全匹配的文本
    2. 智能匹配：如果精确匹配失败，尝试忽略行首尾空白后匹配
    3. 多次出现处理：如果文本出现多次，提示用户提供更多上下文或使用 replace_all
    4. 行结尾保留：自动检测并保留原文件的行结尾风格（CRLF/LF）

    使用示例：
    --------
    >>> tool = EditFileTool(workspace=Path("/project"))
    >>> result = await tool.execute(
    ...     "src/main.py",
    ...     old_text="def hello():",
    ...     new_text="def hello_world():"
    ... )
    >>> print(result)
    Successfully edited /project/src/main.py

    如果未找到文本：
    --------------
    工具会返回一个错误信息，包括最相似的文本片段及其位置，
    帮助用户了解实际内容是什么。
    """

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Edit a file by replacing old_text with new_text. "
            "Supports minor whitespace/line-ending differences. "
            "Set replace_all=true to replace every occurrence."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to edit"},
                "old_text": {"type": "string", "description": "The text to find and replace"},
                "new_text": {"type": "string", "description": "The text to replace with"},
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default false)",
                },
            },
            "required": ["path", "old_text", "new_text"],
        }

    async def execute(
        self, path: str, old_text: str, new_text: str,
        replace_all: bool = False, **kwargs: Any,
    ) -> str:
        """
        执行文件编辑操作。

        Args:
            path: 文件路径
            old_text: 要查找和替换的文本
            new_text: 替换后的新文本
            replace_all: 是否替换所有出现（默认 False，只替换第一个）
            **kwargs: 其他参数（忽略）

        Returns:
            str: 成功信息或错误信息

        编辑流程：
        --------
        1. 读取文件原始字节（保留行结尾格式）
        2. 检测是否使用 CRLF（Windows 风格）
        3. 转换为 LF 统一处理
        4. 使用 _find_match 查找匹配文本
        5. 执行替换（单次或全部）
        6. 恢复原始行结尾格式
        7. 写回文件

        行结尾处理：
        ---------
        工具会自动检测并保留原文件的行结尾风格：
        - CRLF（\\r\\n）：Windows 风格
        - LF（\\n）：Unix/Linux/Mac 风格

        示例：
        -----
        >>> result = await tool.execute("src/main.py", "def hello():", "def hello_world():")
        >>> print(result)
        Successfully edited /project/src/main.py
        """
        try:
            fp = self._resolve(path)
            if not fp.exists():
                return f"Error: File not found: {path}"

            # 读取原始字节（保留行结尾格式）
            raw = fp.read_bytes()
            uses_crlf = b"\r\n" in raw  # 检测是否使用 CRLF
            content = raw.decode("utf-8").replace("\r\n", "\n")  # 统一转为 LF
            # 查找匹配（同样将 old_text 转为 LF）
            match, count = _find_match(content, old_text.replace("\r\n", "\n"))

            if match is None:
                # 未找到匹配文本，返回详细错误信息
                return self._not_found_msg(old_text, content, path)
            if count > 1 and not replace_all:
                # 多次出现且未启用全部替换，提示用户
                return (
                    f"Warning: old_text appears {count} times. "
                    "Provide more context to make it unique, or set replace_all=true."
                )

            # 执行替换
            norm_new = new_text.replace("\r\n", "\n")  # 新文本也转为 LF
            new_content = content.replace(match, norm_new) if replace_all else content.replace(match, norm_new, 1)
            if uses_crlf:
                # 恢复 CRLF 格式
                new_content = new_content.replace("\n", "\r\n")

            # 写回文件
            fp.write_bytes(new_content.encode("utf-8"))
            return f"Successfully edited {fp}"
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error editing file: {e}"

    @staticmethod
    def _not_found_msg(old_text: str, content: str, path: str) -> str:
        """
        生成未找到匹配文本时的详细错误信息。

        这个静态方法使用 difflib 查找最相似的文本片段，
        帮助用户了解实际内容是什么，便于调试。

        Args:
            old_text: 用户提供的要查找的文本
            content: 文件实际内容
            path: 文件路径

        Returns:
            str: 错误信息，包含最相似片段的位置和差异对比

        算法说明：
        --------
        使用 SequenceMatcher 计算相似度：
        1. 滑动窗口遍历文件内容
        2. 计算每个窗口与 old_text 的相似度
        3. 返回相似度最高的片段（如果 > 50%）

        示例：
        -----
        >>> _not_found_msg("def hello():", "def hallo():\\n    pass", "test.py")
        "Error: old_text not found in test.py.\\nBest match (80% similar) at line 1:\\n..."
        """
        lines = content.splitlines(keepends=True)
        old_lines = old_text.splitlines(keepends=True)
        window = len(old_lines)

        best_ratio, best_start = 0.0, 0
        # 滑动窗口查找最相似片段
        for i in range(max(1, len(lines) - window + 1)):
            ratio = difflib.SequenceMatcher(None, old_lines, lines[i : i + window]).ratio()
            if ratio > best_ratio:
                best_ratio, best_start = ratio, i

        if best_ratio > 0.5:
            # 相似度超过 50%，返回差异对比
            diff = "\n".join(difflib.unified_diff(
                old_lines, lines[best_start : best_start + window],
                fromfile="old_text (provided)",
                tofile=f"{path} (actual, line {best_start + 1})",
                lineterm="",
            ))
            return f"Error: old_text not found in {path}.\\nBest match ({best_ratio:.0%} similar) at line {best_start + 1}:\\n{diff}"
        return f"Error: old_text not found in {path}. No similar text found. Verify the file content."


# ---------------------------------------------------------------------------
# list_dir - 列出目录工具
# ---------------------------------------------------------------------------

class ListDirTool(_FsTool):
    """
    列出目录内容，支持可选的递归模式。

    这个工具让 Agent 能够浏览目录结构。
    自动忽略常见的噪声目录（.git、node_modules、__pycache__等）。

    核心功能：
    --------
    1. 非递归模式：只列出直接子项，带图标（📁 目录/📄 文件）
    2. 递归模式：列出所有嵌套文件，相对路径显示
    3. 噪声过滤：自动忽略.git、node_modules 等目录
    4. 数量限制：默认最多 200 个条目，防止输出过大

    使用示例：
    --------
    >>> tool = ListDirTool(workspace=Path("/project"))
    >>> result = await tool.execute("src")
    >>> print(result)
    📁 utils
    📄 main.py
    📄 config.py

    递归模式：
    --------
    >>> result = await tool.execute("src", recursive=True)
    >>> print(result)
    main.py
    config.py
    utils/helper.py
    utils/parser.py
    """

    _DEFAULT_MAX = 200  # 默认最大条目数
    # 忽略的目录集合
    _IGNORE_DIRS = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        "dist", "build", ".tox", ".mypy_cache", ".pytest_cache",
        ".ruff_cache", ".coverage", "htmlcov",
    }

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return (
            "List the contents of a directory. "
            "Set recursive=true to explore nested structure. "
            "Common noise directories (.git, node_modules, __pycache__, etc.) are auto-ignored."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The directory path to list"},
                "recursive": {
                    "type": "boolean",
                    "description": "Recursively list all files (default false)",
                },
                "max_entries": {
                    "type": "integer",
                    "description": "Maximum entries to return (default 200)",
                    "minimum": 1,
                },
            },
            "required": ["path"],
        }

    async def execute(
        self, path: str, recursive: bool = False,
        max_entries: int | None = None, **kwargs: Any,
    ) -> str:
        """
        执行目录列表操作。

        Args:
            path: 目录路径
            recursive: 是否递归列出所有子文件（默认 False）
            max_entries: 最大返回条目数（默认 200）
            **kwargs: 其他参数（忽略）

        Returns:
            str: 目录内容列表，或错误信息

        非递归模式：
        ---------
        - 使用 📁 标识目录
        - 使用 📄 标识文件
        - 按名称排序

        递归模式：
        -------
        - 显示相对于起始目录的相对路径
        - 按路径排序
        - 自动忽略噪声目录
        """
        try:
            dp = self._resolve(path)
            if not dp.exists():
                return f"Error: Directory not found: {path}"
            if not dp.is_dir():
                return f"Error: Not a directory: {path}"

            cap = max_entries or self._DEFAULT_MAX
            items: list[str] = []
            total = 0

            if recursive:
                # 递归模式：列出所有子文件
                for item in sorted(dp.rglob("*")):
                    # 跳过噪声目录
                    if any(p in self._IGNORE_DIRS for p in item.parts):
                        continue
                    total += 1
                    if len(items) < cap:
                        rel = item.relative_to(dp)
                        items.append(f"{rel}/" if item.is_dir() else str(rel))
            else:
                # 非递归模式：只列出直接子项
                for item in sorted(dp.iterdir()):
                    if item.name in self._IGNORE_DIRS:
                        continue
                    total += 1
                    if len(items) < cap:
                        pfx = "📁 " if item.is_dir() else "📄 "
                        items.append(f"{pfx}{item.name}")

            if not items and total == 0:
                return f"Directory {path} is empty"

            result = "\n".join(items)
            if total > cap:
                result += f"\n\n(truncated, showing first {cap} of {total} entries)"
            return result
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error listing directory: {e}"

            if recursive:
                for item in sorted(dp.rglob("*")):
                    if any(p in self._IGNORE_DIRS for p in item.parts):
                        continue
                    total += 1
                    if len(items) < cap:
                        rel = item.relative_to(dp)
                        items.append(f"{rel}/" if item.is_dir() else str(rel))
            else:
                for item in sorted(dp.iterdir()):
                    if item.name in self._IGNORE_DIRS:
                        continue
                    total += 1
                    if len(items) < cap:
                        pfx = "📁 " if item.is_dir() else "📄 "
                        items.append(f"{pfx}{item.name}")

            if not items and total == 0:
                return f"Directory {path} is empty"

            result = "\n".join(items)
            if total > cap:
                result += f"\n\n(truncated, showing first {cap} of {total} entries)"
            return result
        except PermissionError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error listing directory: {e}"

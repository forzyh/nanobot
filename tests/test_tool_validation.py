# =============================================================================
# nanobot 工具参数验证测试
# 文件路径：tests/test_tool_validation.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 nanobot 工具参数验证功能的单元测试。
# 主要测试工具类（Tool）的参数验证、类型转换和 ExecTool 的安全防护功能。
#
# 测试的核心功能：
# -------------------------
# 1. 参数验证（validate_params）：验证工具参数是否符合 JSON Schema 定义
# 2. 类型转换（cast_params）：将字符串类型的参数转换为正确的数据类型
# 3. ExecTool 路径提取：从命令中提取绝对路径用于安全检查
# 4. ExecTool 安全守卫：阻止访问工作区外的路径
#
# 关键测试场景：
# --------
# 1. 必填参数缺失的验证
# 2. 参数类型和范围验证（整数、浮点数、字符串长度）
# 3. 枚举值验证
# 4. 嵌套对象和数组的验证
# 5. 未知字段的处理（应该被忽略）
# 6. 类型转换：字符串转整数、浮点数、布尔值
# 7. 嵌套对象和数组的类型转换
# 8. 布尔值的特殊处理（false/0/no 转 False）
# 9. 无效字符串的处理（保持原值，由验证捕获）
# 10. None 值的处理
# 11. ExecTool 路径提取和安全守卫
# 12. ExecTool 输出截断和超时控制
#
# 使用示例：
# --------
# pytest tests/test_tool_validation.py -v           # 运行所有测试
# pytest tests/test_tool_validation.py::test_validate_params_missing_required -v  # 运行特定测试
# =============================================================================

from typing import Any

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.shell import ExecTool


class SampleTool(Tool):
    """示例工具类，用于演示参数验证功能。

    这个工具定义了复杂的参数结构，用于测试各种验证场景：
    - 必填参数（query, count）
    - 字符串最小长度（query）
    - 整数范围（count: 1-10）
    - 枚举值（mode: fast/full）
    - 嵌套对象（meta）
    """
    @property
    def name(self) -> str:
        return "sample"

    @property
    def description(self) -> str:
        return "sample tool"

    @property
    def parameters(self) -> dict[str, Any]:
        # 定义工具的 JSON Schema 参数
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2},  # 字符串，最小长度 2
                "count": {"type": "integer", "minimum": 1, "maximum": 10},  # 整数，范围 1-10
                "mode": {"type": "string", "enum": ["fast", "full"]},  # 枚举值
                "meta": {  # 嵌套对象
                    "type": "object",
                    "properties": {
                        "tag": {"type": "string"},  # 必填字符串
                        "flags": {
                            "type": "array",
                            "items": {"type": "string"},  # 字符串数组
                        },
                    },
                    "required": ["tag"],
                },
            },
            "required": ["query", "count"],  # 必填参数
        }

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


def test_validate_params_missing_required() -> None:
    """测试必填参数缺失时的验证。

    验证当缺少必填参数 count 时，
    validate_params 方法返回包含错误信息的列表。
    """
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi"})  # 缺少 count 参数
    assert "missing required count" in "; ".join(errors)


def test_validate_params_type_and_range() -> None:
    """测试参数类型和范围验证。

    验证：
    1. count 小于最小值（0 < 1）时报错
    2. count 是字符串类型时报错（应该是整数）
    """
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 0})  # count 小于最小值
    assert any("count must be >= 1" in e for e in errors)

    errors = tool.validate_params({"query": "hi", "count": "2"})  # count 是字符串
    assert any("count should be integer" in e for e in errors)


def test_validate_params_enum_and_min_length() -> None:
    """测试枚举值和字符串最小长度验证。

    验证：
    1. query 长度小于 2 时报错
    2. mode 不是枚举值（fast/full）时报错
    """
    tool = SampleTool()
    errors = tool.validate_params({"query": "h", "count": 2, "mode": "slow"})  # query 太短，mode 无效
    assert any("query must be at least 2 chars" in e for e in errors)
    assert any("mode must be one of" in e for e in errors)


def test_validate_params_nested_object_and_array() -> None:
    """测试嵌套对象和数组的验证。

    验证：
    1. 嵌套对象缺少必填字段 tag 时报错
    2. 数组元素类型错误时报错（flags[0] 应该是字符串）
    """
    tool = SampleTool()
    errors = tool.validate_params(
        {
            "query": "hi",
            "count": 2,
            "meta": {"flags": [1, "ok"]},  # 缺少 tag，flags 包含非字符串元素
        }
    )
    assert any("missing required meta.tag" in e for e in errors)
    assert any("meta.flags[0] should be string" in e for e in errors)


def test_validate_params_ignores_unknown_fields() -> None:
    """测试未知字段的处理。

    验证 Schema 中未定义的字段应该被忽略，
    不产生验证错误。
    """
    tool = SampleTool()
    errors = tool.validate_params({"query": "hi", "count": 2, "extra": "x"})  # extra 是未知字段
    assert errors == []  # 未知字段不产生错误


async def test_registry_returns_validation_error() -> None:
    """测试工具注册表返回验证错误。

    验证当工具参数验证失败时，
    ToolRegistry.execute 返回包含错误信息的字符串。
    """
    reg = ToolRegistry()
    reg.register(SampleTool())
    result = await reg.execute("sample", {"query": "hi"})  # 缺少必填参数 count
    assert "Invalid parameters" in result


def test_exec_extract_absolute_paths_keeps_full_windows_path() -> None:
    """测试 ExecTool 提取 Windows 绝对路径。

    验证 _extract_absolute_paths 方法能够正确识别
    Windows 风格的绝对路径（如 C:\user\workspace\txt）。
    """
    cmd = r"type C:\user\workspace\txt"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert paths == [r"C:\user\workspace\txt"]


def test_exec_extract_absolute_paths_ignores_relative_posix_segments() -> None:
    """测试 ExecTool 忽略相对路径。

    验证相对路径（如.venv/bin/python）不会被误识别为绝对路径。
    """
    cmd = ".venv/bin/python script.py"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert "/bin/python" not in paths  # 相对路径不应被提取


def test_exec_extract_absolute_paths_captures_posix_absolute_paths() -> None:
    """测试 ExecTool 提取 POSIX 绝对路径。

    验证类 Unix 系统的绝对路径（以/开头）被正确提取。
    """
    cmd = "cat /tmp/data.txt > /tmp/out.txt"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert "/tmp/data.txt" in paths
    assert "/tmp/out.txt" in paths


def test_exec_extract_absolute_paths_captures_home_paths() -> None:
    """测试 ExecTool 提取家目录路径（~开头）。

    验证以~开头的路径（如~/.nanobot/config.json）被正确识别。
    """
    cmd = "cat ~/.nanobot/config.json > ~/out.txt"
    paths = ExecTool._extract_absolute_paths(cmd)
    assert "~/.nanobot/config.json" in paths
    assert "~/out.txt" in paths


def test_exec_extract_absolute_paths_captures_quoted_paths() -> None:
    """测试 ExecTool 提取引号内的路径。

    验证被引号包围的路径也能被正确提取。
    """
    cmd = 'cat "/tmp/data.txt" "~/.nanobot/config.json"'
    paths = ExecTool._extract_absolute_paths(cmd)
    assert "/tmp/data.txt" in paths
    assert "~/.nanobot/config.json" in paths


def test_exec_guard_blocks_home_path_outside_workspace(tmp_path) -> None:
    """测试 ExecTool 安全守卫阻止访问家目录路径。

    验证当 restrict_to_workspace=True 时，
    访问工作区外路径（如~/.nanobot/config.json）的命令被阻止。
    """
    tool = ExecTool(restrict_to_workspace=True)
    error = tool._guard_command("cat ~/.nanobot/config.json", str(tmp_path))
    assert error == "Error: Command blocked by safety guard (path outside working dir)"


def test_exec_guard_blocks_quoted_home_path_outside_workspace(tmp_path) -> None:
    """测试 ExecTool 安全守卫阻止访问引号内的家目录路径。

    验证即使路径被引号包围，安全守卫也能识别并阻止。
    """
    tool = ExecTool(restrict_to_workspace=True)
    error = tool._guard_command('cat "~/.nanobot/config.json"', str(tmp_path))
    assert error == "Error: Command blocked by safety guard (path outside working dir)"


# --- cast_params tests ---


class CastTestTool(Tool):
    """用于测试 cast_params 功能的最小化工具类。

    这个工具允许动态传入 Schema，用于测试不同类型参数的转换。
    """

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = schema

    @property
    def name(self) -> str:
        return "cast_test"

    @property
    def description(self) -> str:
        return "test tool for casting"

    @property
    def parameters(self) -> dict[str, Any]:
        return self._schema

    async def execute(self, **kwargs: Any) -> str:
        return "ok"


def test_cast_params_string_to_int() -> None:
    """测试字符串转整数。

    验证 cast_params 方法将字符串"42"正确转换为整数 42。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
    )
    result = tool.cast_params({"count": "42"})
    assert result["count"] == 42
    assert isinstance(result["count"], int)


def test_cast_params_string_to_number() -> None:
    """测试字符串转浮点数。

    验证 cast_params 方法将字符串"3.14"正确转换为浮点数 3.14。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"rate": {"type": "number"}},
        }
    )
    result = tool.cast_params({"rate": "3.14"})
    assert result["rate"] == 3.14
    assert isinstance(result["rate"], float)


def test_cast_params_string_to_bool() -> None:
    """测试字符串转布尔值（真值）。

    验证"true"、"false"、"1"等字符串正确转换为布尔值。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"enabled": {"type": "boolean"}},
        }
    )
    assert tool.cast_params({"enabled": "true"})["enabled"] is True
    assert tool.cast_params({"enabled": "false"})["enabled"] is False
    assert tool.cast_params({"enabled": "1"})["enabled"] is True


def test_cast_params_array_items() -> None:
    """测试数组元素的类型转换。

    验证数组中的字符串元素被逐个转换为整数。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {
                "nums": {"type": "array", "items": {"type": "integer"}},
            },
        }
    )
    result = tool.cast_params({"nums": ["1", "2", "3"]})
    assert result["nums"] == [1, 2, 3]


def test_cast_params_nested_object() -> None:
    """测试嵌套对象的类型转换。

    验证嵌套对象内的参数也被正确转换。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "port": {"type": "integer"},
                        "debug": {"type": "boolean"},
                    },
                },
            },
        }
    )
    result = tool.cast_params({"config": {"port": "8080", "debug": "true"}})
    assert result["config"]["port"] == 8080
    assert result["config"]["debug"] is True


def test_cast_params_bool_not_cast_to_int() -> None:
    """布尔值不应被静默转换为整数。

    验证当传入布尔值 True 时，不会被转换为整数 1，
    而是保持原值并在验证时报错。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
    )
    result = tool.cast_params({"count": True})
    assert result["count"] is True
    errors = tool.validate_params(result)
    assert any("count should be integer" in e for e in errors)


def test_cast_params_preserves_empty_string() -> None:
    """空字符串应该被保留。

    验证当传入空字符串时，cast_params 不会将其转换为 None 或其他值。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
    )
    result = tool.cast_params({"name": ""})
    assert result["name"] == ""


def test_cast_params_bool_string_false() -> None:
    """测试'false'、'0'、'no' 等字符串转换为 False。

    验证多种表示假的字符串都被正确转换为布尔值 False。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"flag": {"type": "boolean"}},
        }
    )
    assert tool.cast_params({"flag": "false"})["flag"] is False
    assert tool.cast_params({"flag": "False"})["flag"] is False  # 大小写不敏感
    assert tool.cast_params({"flag": "0"})["flag"] is False
    assert tool.cast_params({"flag": "no"})["flag"] is False
    assert tool.cast_params({"flag": "NO"})["flag"] is False


def test_cast_params_bool_string_invalid() -> None:
    """无效的布尔值字符串不应被转换。

    验证无法识别的布尔值字符串保持原值，
    由后续的 validate_params 捕获错误。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"flag": {"type": "boolean"}},
        }
    )
    # 无效字符串应保持原值（验证时会捕获）
    result = tool.cast_params({"flag": "random"})
    assert result["flag"] == "random"
    result = tool.cast_params({"flag": "maybe"})
    assert result["flag"] == "maybe"


def test_cast_params_invalid_string_to_int() -> None:
    """无效的字符串不应被转换为整数。

    验证无法解析为整数的字符串保持原值。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
        }
    )
    result = tool.cast_params({"count": "abc"})
    assert result["count"] == "abc"  # 原值保留
    result = tool.cast_params({"count": "12.5.7"})
    assert result["count"] == "12.5.7"


def test_cast_params_invalid_string_to_number() -> None:
    """无效的字符串不应被转换为数字。

    验证无法解析为数字的字符串保持原值。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"rate": {"type": "number"}},
        }
    )
    result = tool.cast_params({"rate": "not_a_number"})
    assert result["rate"] == "not_a_number"


def test_validate_params_bool_not_accepted_as_number() -> None:
    """布尔值不应通过数字验证。

    验证布尔值 False 不能作为 number 类型参数使用。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"rate": {"type": "number"}},
        }
    )
    errors = tool.validate_params({"rate": False})
    assert any("rate should be number" in e for e in errors)


def test_cast_params_none_values() -> None:
    """测试 None 值在不同类型中的处理。

    验证 None 值在所有类型中都被保留，不进行转换。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "count": {"type": "integer"},
                "items": {"type": "array"},
                "config": {"type": "object"},
            },
        }
    )
    result = tool.cast_params(
        {
            "name": None,
            "count": None,
            "items": None,
            "config": None,
        }
    )
    # None 值在所有类型中都应保持原值
    assert result["name"] is None
    assert result["count"] is None
    assert result["items"] is None
    assert result["config"] is None


def test_cast_params_single_value_not_auto_wrapped_to_array() -> None:
    """单个值不应自动包装为数组。

    验证非数组值保持原值，由 validate_params 捕获类型错误。
    """
    tool = CastTestTool(
        {
            "type": "object",
            "properties": {"items": {"type": "array"}},
        }
    )
    # 非数组值应保持原值（验证时会捕获）
    result = tool.cast_params({"items": 5})
    assert result["items"] == 5  # 不自动包装为 [5]
    result = tool.cast_params({"items": "text"})
    assert result["items"] == "text"  # 不自动包装为 ["text"]


# --- ExecTool enhancement tests ---


async def test_exec_always_returns_exit_code() -> None:
    """退出码应该出现在输出中（即使是成功的 exit 0）。

    验证 ExecTool.execute 的返回结果始终包含退出码信息。
    """
    tool = ExecTool()
    result = await tool.execute(command="echo hello")
    assert "Exit code: 0" in result
    assert "hello" in result


async def test_exec_head_tail_truncation() -> None:
    """长输出应该保留头部和尾部。

    验证当命令输出超过_MAX_OUTPUT 限制时，
    结果保留头部和尾部内容，并显示截断提示。
    """
    tool = ExecTool()
    # 生成超过_MAX_OUTPUT 的输出
    big = "A" * 6000 + "\n" + "B" * 6000
    result = await tool.execute(command=f"echo '{big}'")
    assert "chars truncated" in result  # 验证有截断提示
    # 头部应该以 A 开头
    assert result.startswith("A")
    # 尾部应该包含退出码（在 B 之后）
    assert "Exit code:" in result


async def test_exec_timeout_parameter() -> None:
    """LLM 提供的超时值应该覆盖构造函数默认值。

    验证 execute 方法的 timeout 参数能够覆盖构造时设置的默认值。
    """
    tool = ExecTool(timeout=60)
    # 很短的超时应该导致命令被终止
    result = await tool.execute(command="sleep 10", timeout=1)
    assert "timed out" in result
    assert "1 seconds" in result


async def test_exec_timeout_capped_at_max() -> None:
    """超过_MAX_TIMEOUT 的超时值应该被限制。

    验证当传入的 timeout 超过最大值时，自动钳制到最大值而不抛出异常。
    """
    tool = ExecTool()
    # 不应抛出异常——自动钳制到 600
    result = await tool.execute(command="echo ok", timeout=9999)
    assert "Exit code: 0" in result

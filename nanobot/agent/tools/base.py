# =============================================================================
# nanobot 工具基类
# 文件路径：nanobot/agent/tools/base.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件定义了 Tool 抽象基类，是所有 Agent 工具的"模板"。
#
# 什么是工具（Tool）？
# ----------------
# 工具是 Agent 可以使用的能力，如：
# - read_file: 读取文件内容
# - write_file: 写入文件
# - exec: 执行 Shell 命令
# - web_search: 网络搜索
# - message: 发送消息到聊天渠道
#
# 为什么需要抽象基类？
# -----------------
# 1. 统一接口：所有工具都有 name, description, parameters, execute
# 2. 参数验证：内置参数验证逻辑，所有工具共享
# 3. 类型转换：自动将 LLM 返回的参数转为目标类型
# 4. Schema 生成：自动生成 OpenAI 格式的工具定义
#
# 工具继承示例：
# ------------
# class ReadFileTool(Tool):
#     @property
#     def name(self) -> str:
#         return "read_file"
#
#     @property
#     def description(self) -> str:
#         return "读取文件内容"
#
#     @property
#     def parameters(self) -> dict:
#         return {
#             "type": "object",
#             "properties": {
#                 "path": {"type": "string", "description": "文件路径"}
#             },
#             "required": ["path"]
#         }
#
#     async def execute(self, path: str) -> str:
#         with open(path) as f:
#             return f.read()
# =============================================================================

"""Base class for agent tools."""
# 工具基类

from abc import ABC, abstractmethod  # 抽象基类
from typing import Any  # 任意类型


# =============================================================================
# Tool - 工具抽象基类
# =============================================================================

class Tool(ABC):
    """
    Agent 工具的抽象基类。

    工具是 Agent 用来与环境交互的能力，如：
    - 读取文件（reading files）
    - 执行命令（executing commands）
    - 网络搜索（web search）
    - 发送消息（sending messages）

    所有具体工具都必须继承这个类并实现抽象方法。

    类属性：
    --------
    _TYPE_MAP: dict[str, type]
        JSON Schema 类型到 Python 类型的映射
        用于参数类型转换和验证

    抽象方法（子类必须实现）：
    ----------------------
    1. name: 工具名称
    2. description: 工具描述
    3. parameters: JSON Schema 参数定义
    4. execute: 执行逻辑

    继承示例：
    --------
    class ReadFileTool(Tool):
        @property
        def name(self) -> str:
            return "read_file"

        @property
        def description(self) -> str:
            return "读取文件内容"

        @property
        def parameters(self) -> dict:
            return {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"}
                },
                "required": ["path"]
            }

        async def execute(self, path: str) -> str:
            with open(path, encoding="utf-8") as f:
                return f.read()
    """

    # JSON Schema 类型到 Python 类型的映射
    # 用于参数类型转换
    _TYPE_MAP = {
        "string": str,       # 字符串
        "integer": int,      # 整数
        "number": (int, float),  # 数字（整数或浮点数）
        "boolean": bool,     # 布尔值
        "array": list,       # 数组
        "object": dict,      # 对象
    }

    @property
    @abstractmethod
    def name(self) -> str:
        """
        工具名称，用于函数调用。

        Returns:
            str: 工具名称

        示例：
            >>> tool.name
            'read_file'
        """
        pass  # 由子类实现

    @property
    @abstractmethod
    def description(self) -> str:
        """
        工具描述，说明工具的用途。

        这个描述会展示给 LLM，帮助它理解何时使用这个工具。

        Returns:
            str: 工具描述

        示例：
            >>> tool.description
            '读取文件内容'
        """
        pass  # 由子类实现

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """
        JSON Schema 参数定义。

        这个 Schema 用于：
        1. 告诉 LLM 工具接受什么参数
        2. 参数验证
        3. 类型转换

        Returns:
            dict[str, Any]: JSON Schema 格式的参数字典

        Schema 格式示例：
        --------------
        {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径"
                },
                "limit": {
                    "type": "integer",
                    "description": "最大读取行数",
                    "default": 100
                }
            },
            "required": ["path"]
        }
        """
        pass  # 由子类实现

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """
        执行工具，使用给定的参数。

        Args:
            **kwargs: 工具特定的参数
                子类根据需要定义参数名称和类型

        Returns:
            str: 执行结果的字符串表示

        示例：
            >>> result = await tool.execute(path="/tmp/test.txt", limit=50)
            >>> print(result)
            '文件内容...'
        """
        pass  # 由子类实现

    def cast_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """
        在验证前应用安全的 Schema 驱动类型转换。

        为什么需要类型转换？
        -----------------
        LLM 返回的参数可能类型不正确：
        - 数字可能返回字符串："123" 而不是 123
        - 布尔值可能返回字符串："true" 而不是 True
        这个方法负责转换这些值。

        Args:
            params: 原始参数字典

        Returns:
            dict[str, Any]: 转换后的参数字典

        示例：
            >>> tool.cast_params({"limit": "123"})
            {'limit': 123}
            >>> tool.cast_params({"enabled": "true"})
            {'enabled': True}
        """
        schema = self.parameters or {}
        # 非对象类型直接返回
        if schema.get("type", "object") != "object":
            return params

        return self._cast_object(params, schema)

    def _cast_object(self, obj: Any, schema: dict[str, Any]) -> dict[str, Any]:
        """
        根据 Schema 转换对象（字典）。

        Args:
            obj: 要转换的对象
            schema: JSON Schema 定义

        Returns:
            dict[str, Any]: 转换后的字典
        """
        # 非字典返回原样
        if not isinstance(obj, dict):
            return obj

        props = schema.get("properties", {})  # 属性定义
        result = {}

        # 遍历每个键值对
        for key, value in obj.items():
            if key in props:
                # 如果键在 Schema 中，转换值
                result[key] = self._cast_value(value, props[key])
            else:
                # 否则保留原值
                result[key] = value

        return result

    def _cast_value(self, val: Any, schema: dict[str, Any]) -> Any:
        """
        根据 Schema 转换单个值。

        转换规则：
        --------
        1. 类型匹配：如果已经是目标类型，保持不变
        2. 字符串转整数："123" → 123
        3. 字符串转浮点数："3.14" → 3.14
        4. 字符串转布尔值："true" → True
        5. 任意转字符串：None → "None"

        Args:
            val: 要转换的值
            schema: 值的 JSON Schema 定义

        Returns:
            Any: 转换后的值
        """
        target_type = schema.get("type")  # 目标类型

        # 布尔值已经是目标类型
        if target_type == "boolean" and isinstance(val, bool):
            return val
        # 整数已经是目标类型（排除 bool，因为 bool 是 int 的子类）
        if target_type == "integer" and isinstance(val, int) and not isinstance(val, bool):
            return val
        # 其他基础类型检查
        if target_type in self._TYPE_MAP and target_type not in ("boolean", "integer", "array", "object"):
            expected = self._TYPE_MAP[target_type]
            if isinstance(val, expected):
                return val

        # 字符串转整数
        if target_type == "integer" and isinstance(val, str):
            try:
                return int(val)
            except ValueError:
                return val  # 转换失败返回原值

        # 字符串转浮点数
        if target_type == "number" and isinstance(val, str):
            try:
                return float(val)
            except ValueError:
                return val  # 转换失败返回原值

        # 任意转字符串
        if target_type == "string":
            return val if val is None else str(val)

        # 字符串转布尔值
        if target_type == "boolean" and isinstance(val, str):
            val_lower = val.lower()
            # 真值
            if val_lower in ("true", "1", "yes"):
                return True
            # 假值
            if val_lower in ("false", "0", "no"):
                return False
            return val  # 无法识别返回原值

        # 数组递归转换
        if target_type == "array" and isinstance(val, list):
            item_schema = schema.get("items")
            # 递归转换每个元素
            return [self._cast_value(item, item_schema) for item in val] if item_schema else val

        # 对象递归转换
        if target_type == "object" and isinstance(val, dict):
            return self._cast_object(val, schema)

        # 其他情况返回原值
        return val

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """
        根据 JSON Schema 验证工具参数。

        验证项目：
        --------
        1. 类型检查：参数是否是字典
        2. 必填字段：required 中的字段是否存在
        3. 类型匹配：值是否符合 Schema 定义的类型
        4. 枚举值：值是否在 enum 列表中
        5. 数值范围：minimum/maximum 检查
        6. 字符串长度：minLength/maxLength 检查

        Args:
            params: 参数字典

        Returns:
            list[str]: 错误列表，空列表表示验证通过

        示例：
            >>> errors = tool.validate_params({"path": 123})
            >>> errors
            ['path should be string']
        """
        # 参数必须是字典
        if not isinstance(params, dict):
            return [f"parameters must be an object, got {type(params).__name__}"]

        schema = self.parameters or {}
        # Schema 必须是 object 类型
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")

        # 调用递归验证
        return self._validate(params, {**schema, "type": "object"}, "")

    def _validate(self, val: Any, schema: dict[str, Any], path: str) -> list[str]:
        """
        递归验证值是否符合 Schema。

        Args:
            val: 要验证的值
            schema: JSON Schema 定义
            path: 当前路径（用于错误定位）

        Returns:
            list[str]: 错误列表

        验证逻辑：
        --------
        1. 类型检查（integer, number, string, boolean, array, object）
        2. 枚举检查（enum）
        3. 数值范围（minimum, maximum）
        4. 字符串长度（minLength, maxLength）
        5. 必填字段（required）
        6. 递归验证嵌套对象和数组
        """
        t, label = schema.get("type"), path or "parameter"

        # 整数检查（排除 bool，因为 bool 是 int 的子类）
        if t == "integer" and (not isinstance(val, int) or isinstance(val, bool)):
            return [f"{label} should be integer"]

        # 数字检查
        if t == "number" and (
            not isinstance(val, self._TYPE_MAP[t]) or isinstance(val, bool)
        ):
            return [f"{label} should be number"]

        # 其他类型检查
        if t in self._TYPE_MAP and t not in ("integer", "number") and not isinstance(val, self._TYPE_MAP[t]):
            return [f"{label} should be {t}"]

        errors = []

        # 枚举检查
        if "enum" in schema and val not in schema["enum"]:
            errors.append(f"{label} must be one of {schema['enum']}")

        # 数值范围检查
        if t in ("integer", "number"):
            if "minimum" in schema and val < schema["minimum"]:
                errors.append(f"{label} must be >= {schema['minimum']}")
            if "maximum" in schema and val > schema["maximum"]:
                errors.append(f"{label} must be <= {schema['maximum']}")

        # 字符串长度检查
        if t == "string":
            if "minLength" in schema and len(val) < schema["minLength"]:
                errors.append(f"{label} must be at least {schema['minLength']} chars")
            if "maxLength" in schema and len(val) > schema["maxLength"]:
                errors.append(f"{label} must be at most {schema['maxLength']} chars")

        # 对象验证
        if t == "object":
            props = schema.get("properties", {})
            # 检查必填字段
            for k in schema.get("required", []):
                if k not in val:
                    errors.append(f"missing required {path + '.' + k if path else k}")
            # 递归验证每个属性
            for k, v in val.items():
                if k in props:
                    errors.extend(self._validate(v, props[k], path + "." + k if path else k))

        # 数组验证
        if t == "array" and "items" in schema:
            for i, item in enumerate(val):
                # 递归验证每个数组元素
                errors.extend(
                    self._validate(item, schema["items"], f"{path}[{i}]" if path else f"[{i}]")
                )

        return errors

    def to_schema(self) -> dict[str, Any]:
        """
        将工具转换为 OpenAI 函数 Schema 格式。

        这是工具定义的标准化输出，用于传递给 LLM。

        Returns:
            dict[str, Any]: OpenAI 格式的工具定义

        返回格式：
        --------
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "读取文件内容",
                "parameters": {...}  # JSON Schema
            }
        }
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

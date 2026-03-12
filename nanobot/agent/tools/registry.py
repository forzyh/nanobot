# =============================================================================
# nanobot 工具注册表
# 文件路径：nanobot/agent/tools/registry.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 ToolRegistry 类，是 Agent 工具的"注册中心"。
#
# 什么是工具注册表？
# ---------------
# 工具注册表是一个中心化的工具管理器，负责：
# 1. 注册工具：将工具实例添加到可用列表
# 2. 查找工具：按名称获取工具实例
# 3. 执行工具：调用工具的 execute 方法
# 4. 获取定义：返回工具的 JSON Schema（给 LLM 使用）
#
# 为什么需要注册表？
# ---------------
# 1. 解耦：工具的实现和使用分离
# 2. 动态：运行时可以添加/移除工具
# 3. 统一：所有工具通过同一接口调用
# 4. 发现：LLM 可以查询有哪些工具可用
#
# 工具注册流程：
# ------------
# 1. AgentLoop 初始化时注册默认工具
#    read_file, write_file, edit_file, exec, web_search, message...
# 2. MCP 连接时注册 MCP 工具
# 3. 运行时可以通过 register() 添加新工具
#
# 工具执行流程：
# ------------
# LLM 决定调用工具 → ToolRegistry.execute() → 参数验证 → 工具.execute() → 返回结果
# =============================================================================

"""Tool registry for dynamic tool management."""
# 工具注册表：动态工具管理

from typing import Any  # 任意类型

from nanobot.agent.tools.base import Tool  # 工具基类


# =============================================================================
# ToolRegistry - 工具注册表
# =============================================================================

class ToolRegistry:
    """
    Agent 工具注册表。

    允许动态注册和执行工具。

    数据结构：
    --------
    self._tools: dict[str, Tool]
        键：工具名称（如 "read_file"）
        值：工具实例（Tool 子类对象）

    主要功能：
    --------
    1. register(): 注册工具
    2. unregister(): 移除工具
    3. get(): 获取工具
    4. has(): 检查工具是否存在
    5. get_definitions(): 获取所有工具定义（给 LLM）
    6. execute(): 执行工具
    """

    def __init__(self):
        """
        初始化工具注册表。

        创建空的工具字典。
        """
        # 工具字典：名称 → 实例
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """
        注册工具。

        Args:
            tool: 工具实例
                必须是 Tool 基类的子类实例

        示例：
            >>> registry.register(ReadFileTool(workspace=Path("/tmp")))
            # 工具现在可以通过 "read_file" 名称访问
        """
        # 使用工具的名称作为键
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """
        按名称移除工具。

        Args:
            name: 工具名称

        注意：
        ----
        使用 pop(name, None) 确保工具不存在时不报错。

        示例：
            >>> registry.unregister("read_file")
        """
        # 移除工具，不存在时返回 None（不报错）
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """
        按名称获取工具。

        Args:
            name: 工具名称

        Returns:
            Tool | None: 工具实例，如果未找到返回 None

        示例：
            >>> tool = registry.get("read_file")
            >>> if tool:
            ...     result = await tool.execute(path="/tmp/test.txt")
        """
        # 字典查找
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """
        检查工具是否已注册。

        Args:
            name: 工具名称

        Returns:
            bool: True 表示工具已注册

        示例：
            >>> if registry.has("web_search"):
            ...     print("网络搜索可用")
        """
        # 成员检查
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """
        获取所有工具定义（OpenAI 格式）。

        这些定义用于告诉 LLM 有哪些工具可用，
        以及每个工具接受什么参数。

        Returns:
            list[dict[str, Any]]: 工具定义列表

        返回格式示例：
        ------------
        [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "读取文件内容",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "文件路径"}
                        },
                        "required": ["path"]
                    }
                }
            },
            ...
        ]
        """
        # 调用每个工具的 to_schema() 方法
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """
        按名称执行工具。

        这是工具调用的核心方法，流程：
        1. 查找工具
        2. 类型转换参数
        3. 验证参数
        4. 执行工具
        5. 处理错误

        Args:
            name: 工具名称
            params: 工具参数字典

        Returns:
            str: 执行结果（成功或错误信息）

        错误处理：
        --------
        - 工具不存在：返回可用工具列表
        - 参数无效：返回验证错误
        - 执行异常：返回异常信息 + 分析提示

        _HINT 的作用：
        -----------
        当工具执行失败时，添加提示告诉 LLM：
        "分析上面的错误，尝试不同的方法"
        这有助于 LLM 从错误中学习并调整策略。
        """
        # 错误提示后缀，引导 LLM 分析错误并尝试新方法
        _HINT = "\n\n[Analyze the error above and try a different approach.]"

        # 查找工具
        tool = self._tools.get(name)
        # 工具不存在，返回错误和可用工具列表
        if not tool:
            return f"Error: Tool '{name}' not found. Available: {', '.join(self.tool_names)}"

        try:
            # 类型转换参数
            # 将 LLM 返回的参数转换为工具期望的类型
            params = tool.cast_params(params)

            # 验证参数
            errors = tool.validate_params(params)
            # 参数验证失败，返回错误
            if errors:
                return f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors) + _HINT

            # 执行工具
            result = await tool.execute(**params)

            # 如果结果以 "Error" 开头，添加提示
            if isinstance(result, str) and result.startswith("Error"):
                return result + _HINT

            # 返回成功结果
            return result
        except Exception as e:
            # 捕获异常，返回错误信息
            return f"Error executing {name}: {str(e)}" + _HINT

    @property
    def tool_names(self) -> list[str]:
        """
        获取所有已注册工具的名称列表。

        Returns:
            list[str]: 工具名称列表

        示例：
            >>> registry.tool_names
            ['read_file', 'write_file', 'exec', 'web_search']
        """
        # 返回字典的所有键
        return list(self._tools.keys())

    def __len__(self) -> int:
        """
        获取已注册工具数量。

        Returns:
            int: 工具数量

        示例：
            >>> len(registry)
            8
        """
        # 字典长度
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        """
        检查工具是否在注册表中（支持 `in` 操作符）。

        Args:
            name: 工具名称

        Returns:
            bool: True 表示工具已注册

        示例：
            >>> "read_file" in registry
            True
        """
        # 成员检查
        return name in self._tools

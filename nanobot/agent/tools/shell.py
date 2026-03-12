# =============================================================================
# nanobot Shell 工具
# 文件路径：nanobot/agent/tools/shell.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 ExecTool，让 Agent 能够执行 shell 命令。
#
# 什么是 ExecTool？
# ---------------
# ExecTool 是一个 Agent 工具，用于：
# 1. 执行安全的 shell 命令
# 2. 获取命令输出（stdout/stderr）
# 3. 返回退出码和执行时间
#
# 安全机制：
# ---------
# 1. 危险命令拦截：使用正则表达式匹配危险命令
# 2. 路径遍历防护：阻止 cd 到工作空间外的路径
# 3. 超时限制：默认 60 秒，最长 600 秒
# 4. 输出截断：过长输出只保留头尾
#
# 危险命令示例：
# -----------
# - rm -rf /          # 删除文件
# - dd if=/dev/zero   # 磁盘操作
# - shutdown/reboot   # 系统电源
# - :(){ :|:& };:     # fork bomb
#
# 使用示例：
# --------
# # 执行安全命令
# {"command": "ls -la"}
# {"command": "git status"}
#
# # 被拦截的危险命令
# {"command": "rm -rf ."}  # 错误：rm -rf 被禁止
# =============================================================================

"""Shell execution tool."""
# Shell 执行工具

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool


class ExecTool(Tool):
    """
    用于执行 shell 命令的工具。

    这个工具让 Agent 能够：
    1. 执行安全的 shell 命令
    2. 获取命令输出（stdout/stderr）
    3. 返回退出码和执行时间

    安全机制：
    ---------
    1. 危险命令拦截：使用正则表达式匹配危险命令模式
    2. 路径遍历防护：阻止 cd 到工作空间外的路径
    3. 超时限制：默认 60 秒，最长 600 秒
    4. 输出截断：过长输出只保留头尾（各一半）

    危险命令模式：
    -----------
    - rm -rf, del /q: 删除文件
    - format, mkfs, diskpart: 磁盘格式化
    - dd if=: 磁盘写入
    - shutdown, reboot, poweroff: 系统电源
    - :(){ :|:& };: : fork bomb

    属性说明：
    --------
    timeout: int
        默认超时时间（秒），默认 60 秒

    working_dir: str | None
        默认工作目录

    deny_patterns: list[str]
        禁止的命令模式（正则表达式）

    allow_patterns: list[str]
        允许的命令模式（白名单模式）

    restrict_to_workspace: bool
        是否限制在工作空间内执行

    path_append: str
        添加到 PATH 环境变量的路径

    使用示例：
    --------
    >>> tool = ExecTool(timeout=60, working_dir="/workspace")
    >>> result = await tool.execute("git status")
    >>> print(result)
    On branch main
    Your branch is up to date.

    Exit code: 0
    """

    def __init__(
        self,
        timeout: int = 60,
        working_dir: str | None = None,
        deny_patterns: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        restrict_to_workspace: bool = False,
        path_append: str = "",
    ):
        """
        初始化 ExecTool。

        Args:
            timeout: 默认超时时间（秒），默认 60
            working_dir: 默认工作目录
            deny_patterns: 禁止的命令模式列表（默认包含危险命令）
            allow_patterns: 允许的命令模式列表（白名单，默认无）
            restrict_to_workspace: 是否限制在工作空间内
            path_append: 要追加到 PATH 的路径
        """
        self.timeout = timeout  # 默认超时
        self.working_dir = working_dir  # 默认工作目录
        # 默认禁止的危险命令模式
        self.deny_patterns = deny_patterns or [
            r"\brm\s+-[rf]{1,2}\b",          # rm -r, rm -rf, rm -fr
            r"\bdel\s+/[fq]\b",              # del /f, del /q
            r"\brmdir\s+/s\b",               # rmdir /s
            r"(?:^|[;&|]\s*)format\b",       # format (as standalone command only)
            r"\b(mkfs|diskpart)\b",          # disk operations
            r"\bdd\s+if=",                   # dd
            r">\s*/dev/sd",                  # write to disk
            r"\b(shutdown|reboot|poweroff)\b",  # system power
            r":\(\)\s*\{.*\};\s*:",          # fork bomb
        ]
        self.allow_patterns = allow_patterns or []  # 白名单
        self.restrict_to_workspace = restrict_to_workspace  # 限制工作空间
        self.path_append = path_append  # PATH 追加

    @property
    def name(self) -> str:
        return "exec"

    _MAX_TIMEOUT = 600  # 最大超时时间（秒）
    _MAX_OUTPUT = 10_000  # 最大输出长度（字符）

    @property
    def description(self) -> str:
        return "Execute a shell command and return its output. Use with caution."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "working_dir": {
                    "type": "string",
                    "description": "Optional working directory for the command",
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Timeout in seconds. Increase for long-running commands "
                        "like compilation or installation (default 60, max 600)."
                    ),
                    "minimum": 1,
                    "maximum": 600,
                },
            },
            "required": ["command"],
        }

    async def execute(
        self, command: str, working_dir: str | None = None,
        timeout: int | None = None, **kwargs: Any,
    ) -> str:
        """
        执行 shell 命令并返回输出。

        Args:
            command: 要执行的 shell 命令
            working_dir: 工作目录（可选，默认使用初始化时设置的目录）
            timeout: 超时时间（秒），可选，最大 600 秒
            **kwargs: 其他参数

        Returns:
            str: 命令输出（包含 stdout、stderr 和退出码），或错误信息

        执行流程：
        --------
        1. 安全检查：调用 _guard_command 检查命令是否安全
        2. 设置超时：使用传入的 timeout 或默认值，上限 600 秒
        3. 设置环境变量：追加 path_append 到 PATH
        4. 创建子进程：使用 asyncio.create_subprocess_shell
        5. 等待完成：等待命令完成或超时
        6. 处理输出：合并 stdout/stderr，添加退出码
        7. 输出截断：如果输出过长，保留头尾各一半

        错误处理：
        --------
        - 安全检查失败：返回错误信息
        - 超时：终止进程，返回超时错误
        - 异常：返回异常信息

        输出格式：
        --------
        stdout 内容
        STDERR:
        stderr 内容（如果有）

        Exit code: 0
        """
        # 确定工作目录
        cwd = working_dir or self.working_dir or os.getcwd()
        # 安全检查
        guard_error = self._guard_command(command, cwd)
        if guard_error:
            return guard_error

        # 设置有效超时（不超过最大值）
        effective_timeout = min(timeout or self.timeout, self._MAX_TIMEOUT)

        # 设置环境变量
        env = os.environ.copy()
        if self.path_append:
            env["PATH"] = env.get("PATH", "") + os.pathsep + self.path_append

        try:
            # 创建异步子进程
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            try:
                # 等待命令完成（带超时）
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError:
                # 超时后强制终止进程
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass  # 等待进程结束超时，继续
                return f"Error: Command timed out after {effective_timeout} seconds"

            # 构建输出
            output_parts = []

            if stdout:
                output_parts.append(stdout.decode("utf-8", errors="replace"))

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if stderr_text.strip():
                    output_parts.append(f"STDERR:\n{stderr_text}")

            output_parts.append(f"\nExit code: {process.returncode}")

            result = "\n".join(output_parts) if output_parts else "(no output)"

            # 输出截断：保留头尾各一半
            max_len = self._MAX_OUTPUT
            if len(result) > max_len:
                half = max_len // 2
                result = (
                    result[:half]
                    + f"\n\n... ({len(result) - max_len:,} chars truncated) ...\n\n"
                    + result[-half:]
                )

            return result

        except Exception as e:
            return f"Error executing command: {str(e)}"

    def _guard_command(self, command: str, cwd: str) -> str | None:
        """
        检查命令是否安全（最佳努力防护）。

        Args:
            command: 要检查的命令
            cwd: 当前工作目录

        Returns:
            str | None: 如果不安全返回错误信息，否则返回 None

        检查项目：
        --------
        1. deny_patterns: 匹配危险命令模式
        2. allow_patterns: 如果配置了白名单，命令必须匹配
        3. 路径遍历：如果 restrict_to_workspace 为 True，阻止 .. 路径
        4. 绝对路径：检查命令中的绝对路径是否在工作空间外
        """
        cmd = command.strip()
        lower = cmd.lower()

        # 检查危险命令模式
        for pattern in self.deny_patterns:
            if re.search(pattern, lower):
                return "Error: Command blocked by safety guard (dangerous pattern detected)"

        # 检查白名单（如果配置了）
        if self.allow_patterns:
            if not any(re.search(p, lower) for p in self.allow_patterns):
                return "Error: Command blocked by safety guard (not in allowlist)"

        # 检查工作空间限制
        if self.restrict_to_workspace:
            # 检查路径遍历
            if "..\\" in cmd or "../" in cmd:
                return "Error: Command blocked by safety guard (path traversal detected)"

            cwd_path = Path(cwd).resolve()

            # 检查绝对路径
            for raw in self._extract_absolute_paths(cmd):
                try:
                    expanded = os.path.expandvars(raw.strip())
                    p = Path(expanded).expanduser().resolve()
                except Exception:
                    continue
                # 检查路径是否在工作空间外
                if p.is_absolute() and cwd_path not in p.parents and p != cwd_path:
                    return "Error: Command blocked by safety guard (path outside working dir)"

        return None

    @staticmethod
    def _extract_absolute_paths(command: str) -> list[str]:
        """
        从命令中提取绝对路径。

        Args:
            command: shell 命令字符串

        Returns:
            list[str]: 提取到的路径列表

        支持的路径格式：
        -------------
        1. Windows: C:\\... (如 C:\\Users\\file.txt)
        2. POSIX: /absolute/path (如 /usr/bin/python)
        3. Home: ~/... (如 ~/Documents/file.txt)

        正则说明：
        --------
        - win_paths: 匹配 Windows 盘符路径
        - posix_paths: 匹配 POSIX 绝对路径（排除 URL 中的 /）
        - home_paths: 匹配 home 目录路径
        """
        # Windows 路径：C:\...
        win_paths = re.findall(r"[A-Za-z]:\\[^\s\"'|><;]+", command)
        # POSIX 绝对路径：/...（排除 URL 协议）
        posix_paths = re.findall(r"(?:^|[\s|>'\"])(/[^\s\"'>;|<]+)", command)
        # Home 路径：~/...
        home_paths = re.findall(r"(?:^|[\s|>'\"])(~[^\s\"'>;|<]*)", command)
        return win_paths + posix_paths + home_paths

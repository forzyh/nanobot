# =============================================================================
# nanobot 技能加载器
# 文件路径：nanobot/agent/skills.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了 SkillsLoader 类，负责加载和管理 Agent 的"技能"。
#
# 什么是技能（Skills）？
# -----------------
# 技能是 markdown 文件（SKILL.md），用于：
# 1. 教会 Agent 如何使用特定工具
# 2. 定义特定任务的执行流程
# 3. 扩展 Agent 的能力边界
#
# 技能的来源：
# -----------
# 1. 内置技能（Builtin Skills）- nanobot 自带的技能
#    位置：nanobot/skills/{skill-name}/SKILL.md
# 2. 工作空间技能（Workspace Skills）- 用户自定义技能
#    位置：{workspace}/skills/{skill-name}/SKILL.md
#
# 技能示例结构：
# ------------
# skills/
# └── web-search/
#     └── SKILL.md  # 技能定义文件
#
# SKILL.md 内容示例：
# ----------------
# ---
# description: 使用 Brave Search 进行网络搜索
# nanobot:
#   requires:
#     env: ["BRAVE_API_KEY"]
# ---
#
# # Web Search Skill
# 当用户需要查找实时信息时，使用 web_search 工具...
#
# 技能加载策略：
# ------------
# - 工作空间技能优先级高于内置技能（同名时覆盖）
# - 支持依赖检查（环境变量、CLI 工具）
# - 支持"常驻技能"（always=true，每次对话都加载）
# =============================================================================

"""Skills loader for agent capabilities."""
# 技能加载器：Agent 能力加载

import json  # JSON 处理
import os  # 操作系统接口
import re  # 正则表达式
import shutil  # 高级文件操作
from pathlib import Path  # 路径处理

# 默认内置技能目录（相对于当前文件）
# nanobot/skills/ 目录
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


# =============================================================================
# SkillsLoader - 技能加载器
# =============================================================================

class SkillsLoader:
    """
    Agent 技能加载器。

    技能（Skills）是 markdown 文件（SKILL.md），用于：
    - 教会 Agent 如何使用特定工具
    - 定义特定任务的执行流程
    - 扩展 Agent 的能力边界

    技能加载流程：
    ------------
    1. 扫描工作空间技能目录（{workspace}/skills/）
    2. 扫描内置技能目录（nanobot/skills/）
    3. 检查每个技能的依赖要求
    4. 过滤出可用的技能

    属性说明：
    --------
    workspace: Path
        工作空间路径

    workspace_skills: Path
        工作空间技能目录（{workspace}/skills/）
        用户自定义技能优先级更高

    builtin_skills: Path
        内置技能目录（nanobot/skills/）
        nanobot 自带的技能库
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        """
        初始化技能加载器。

        Args:
            workspace: 工作空间路径
            builtin_skills_dir: 内置技能目录（可选，默认使用 nanobot/skills/）
        """
        self.workspace = workspace  # 工作空间
        # 工作空间技能目录
        self.workspace_skills = workspace / "skills"
        # 内置技能目录
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        列出所有可用的技能。

        这个方法扫描两个目录（工作空间 + 内置），
        返回所有找到的技能信息。

        Args:
            filter_unavailable: 是否过滤掉不满足依赖的技能
                True: 只返回可用的技能
                False: 返回所有技能（包括依赖不满足的）

        Returns:
            list[dict[str, str]]: 技能信息列表
                每个元素包含：name, path, source

        返回格式示例：
        ------------
        [
            {"name": "web-search", "path": "/workspace/skills/web-search/SKILL.md", "source": "workspace"},
            {"name": "git-helper", "path": "nanobot/skills/git-helper/SKILL.md", "source": "builtin"},
        ]
        """
        skills = []

        # 1. 扫描工作空间技能（优先级高）
        if self.workspace_skills.exists():
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    # 只添加存在 SKILL.md 的技能
                    if skill_file.exists():
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})

        # 2. 扫描内置技能
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    # 检查工作空间是否已有同名技能（避免重复）
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})

        # 3. 根据依赖过滤
        if filter_unavailable:
            # 只返回依赖满足的技能
            return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
        # 返回所有技能
        return skills

    def load_skill(self, name: str) -> str | None:
        """
        按名称加载技能。

        加载优先级：
        --------
        1. 工作空间技能（用户自定义）
        2. 内置技能（nanobot 自带）

        Args:
            name: 技能名称（目录名）
                如 "web-search"、"git-helper"

        Returns:
            str | None: 技能内容（SKILL.md 全文），如果未找到返回 None

        示例：
            >>> loader.load_skill("web-search")
            '---\ndescription: 网络搜索\n---\n\n# Web Search Skill\n...'
        """
        # 优先检查工作空间技能
        workspace_skill = self.workspace_skills / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill.read_text(encoding="utf-8")

        # 检查工作空间没有则查找内置技能
        if self.builtin_skills:
            builtin_skill = self.builtin_skills / name / "SKILL.md"
            if builtin_skill.exists():
                return builtin_skill.read_text(encoding="utf-8")

        # 未找到
        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        加载指定技能用于 Agent 上下文。

        这个方法在构建系统提示时调用，
        将选定的技能内容注入到 LLM 上下文。

        Args:
            skill_names: 要加载的技能名称列表
                如 ["web-search", "git-helper"]

        Returns:
            str: 格式化后的技能内容

        输出格式示例：
        ------------
        ### Skill: web-search

        # Web Search Skill
        当用户需要查找实时信息时...

        ---

        ### Skill: git-helper

        # Git Helper Skill
        ...
        """
        parts = []
        # 遍历每个技能名称
        for name in skill_names:
            # 加载技能内容
            content = self.load_skill(name)
            if content:
                # 移除 YAML frontmatter（只保留正文）
                content = self._strip_frontmatter(content)
                # 格式化
                parts.append(f"### Skill: {name}\n\n{content}")

        # 用分隔符连接所有技能
        return "\n\n---\n\n".join(parts) if parts else ""

    def build_skills_summary(self) -> str:
        """
        构建所有技能的摘要（名称、描述、路径、可用性）。

        这个摘要用于"渐进式加载"策略：
        - Agent 先看到技能列表和简介
        - 需要时使用 read_file 工具读取完整内容

        这样做的好处：
        ------------
        1. 节省 token：不一次性加载所有技能
        2. 按需加载：只在需要时读取详情
        3. 清晰索引：Agent 知道有哪些技能可用

        Returns:
            str: XML 格式的技能摘要

        XML 格式示例：
        ------------
        <skills>
          <skill available="true">
            <name>web-search</name>
            <description>使用 Brave Search 进行网络搜索</description>
            <location>/path/to/skill/SKILL.md</location>
          </skill>
          <skill available="false">
            <name>git-helper</name>
            <description>Git 操作助手</description>
            <location>/path/to/skill/SKILL.md</location>
            <requires>CLI: git</requires>
          </skill>
        </skills>
        """
        # 获取所有技能（不过滤）
        all_skills = self.list_skills(filter_unavailable=False)
        # 空列表返回空字符串
        if not all_skills:
            return ""

        def escape_xml(s: str) -> str:
            """XML 转义特殊字符。"""
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        # 遍历每个技能
        for s in all_skills:
            name = escape_xml(s["name"])
            path = s["path"]
            # 获取技能描述
            desc = escape_xml(self._get_skill_description(s["name"]))
            # 获取技能元数据
            skill_meta = self._get_skill_meta(s["name"])
            # 检查依赖
            available = self._check_requirements(skill_meta)

            lines.append(f"  <skill available=\"{str(available).lower()}\">")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")

            # 显示不满足的依赖（用于调试）
            if not available:
                missing = self._get_missing_requirements(skill_meta)
                if missing:
                    lines.append(f"    <requires>{escape_xml(missing)}</requires>")

            lines.append("  </skill>")
        lines.append("</skills>")

        return "\n".join(lines)

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """
        获取缺失的依赖要求描述。

        当技能不可用时，这个方法生成人类可读的
        缺失依赖说明，方便用户排查。

        Args:
            skill_meta: 技能元数据（含 requires 字段）

        Returns:
            str: 缺失依赖的描述

        示例：
            >>> _get_missing_requirements({"requires": {"bins": ["git"], "env": ["API_KEY"]}})
            'CLI: git, ENV: API_KEY'
        """
        missing = []
        requires = skill_meta.get("requires", {})
        # 检查缺失的 CLI 工具
        for b in requires.get("bins", []):
            if not shutil.which(b):
                missing.append(f"CLI: {b}")
        # 检查缺失的环境变量
        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")
        # 拼接描述
        return ", ".join(missing)

    def _get_skill_description(self, name: str) -> str:
        """
        从技能 frontmatter 中获取描述。

        Args:
            name: 技能名称

        Returns:
            str: 技能描述，如果没有则返回技能名称

        示例：
            >>> _get_skill_description("web-search")
            '使用 Brave Search 进行网络搜索'
        """
        # 获取技能元数据
        meta = self.get_skill_metadata(name)
        # 如果有 description 字段，返回
        if meta and meta.get("description"):
            return meta["description"]
        # 回退到技能名称
        return name

    def _strip_frontmatter(self, content: str) -> str:
        """
        从 markdown 内容中移除 YAML frontmatter。

        Frontmatter 格式：
        ---------------
        ---
        description: 技能描述
        nanobot:
          requires:
            env: ["API_KEY"]
        ---

        # 技能正文
        ...

        Args:
            content: 含 frontmatter 的 markdown 内容

        Returns:
            str: 移除 frontmatter 后的正文
        """
        # 检查是否以 --- 开头
        if content.startswith("---"):
            # 匹配 frontmatter 块
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                # 返回 frontmatter 之后的内容
                return content[match.end():].strip()
        # 没有 frontmatter，返回原内容
        return content

    def _parse_nanobot_metadata(self, raw: str) -> dict:
        """
        从 frontmatter 解析技能元数据 JSON。

        支持两种 key 名称：
        - nanobot（新版本）
        - openclaw（旧版本，兼容）

        Args:
            raw: JSON 格式的元数据字符串

        Returns:
            dict: 解析后的元数据，解析失败返回空字典

        示例：
            >>> _parse_nanobot_metadata('{"nanobot": {"requires": {"env": ["API_KEY"]}}}')
            {'requires': {'env': ['API_KEY']}}
        """
        try:
            data = json.loads(raw)
            # 优先使用 nanobot key，兼容 openclaw
            return data.get("nanobot", data.get("openclaw", {})) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            # 解析失败返回空字典
            return {}

    def _check_requirements(self, skill_meta: dict) -> bool:
        """
        检查技能依赖是否满足（CLI 工具、环境变量）。

        依赖类型：
        --------
        1. bins: CLI 工具（如 git, docker）
           使用 shutil.which() 检查是否在 PATH 中

        2. env: 环境变量（如 API_KEY）
           使用 os.environ.get() 检查是否已设置

        Args:
            skill_meta: 技能元数据（含 requires 字段）

        Returns:
            bool: True 表示所有依赖满足，技能可用
        """
        requires = skill_meta.get("requires", {})
        # 检查 CLI 工具
        for b in requires.get("bins", []):
            # shutil.which() 返回命令路径，找不到返回 None
            if not shutil.which(b):
                return False
        # 检查环境变量
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        # 所有依赖满足
        return True

    def _get_skill_meta(self, name: str) -> dict:
        """
        获取技能的 nanobot 元数据（来自 frontmatter）。

        Args:
            name: 技能名称

        Returns:
            dict: 技能元数据（requires, always 等字段）
        """
        # 获取技能完整元数据
        meta = self.get_skill_metadata(name) or {}
        # 解析 nanobot 元数据
        return self._parse_nanobot_metadata(meta.get("metadata", ""))

    def get_always_skills(self) -> list[str]:
        """
        获取标记为 always=true 且满足依赖的技能。

        Always Skills 是什么？
        -------------------
        某些技能是核心功能（如基础工具使用），
        需要在每次对话中都加载到上下文。

        这些技能在 SKILL.md 的 frontmatter 中标记：
        ---
        nanobot:
          always: true
        ---

        Returns:
            list[str]: always 技能名称列表

        示例：
            >>> loader.get_always_skills()
            ['basic-tools', 'file-operations']
        """
        result = []
        # 遍历所有可用技能
        for s in self.list_skills(filter_unavailable=True):
            # 获取技能元数据
            meta = self.get_skill_metadata(s["name"]) or {}
            skill_meta = self._parse_nanobot_metadata(meta.get("metadata", ""))
            # 检查 always 标记（支持两种位置）
            if skill_meta.get("always") or meta.get("always"):
                result.append(s["name"])
        return result

    def get_skill_metadata(self, name: str) -> dict | None:
        """
        从技能 frontmatter 获取元数据。

        Frontmatter 格式（简易 YAML）：
        --------------------------
        ---
        description: 技能描述
        nanobot:
          requires:
            env: ["API_KEY"]
        ---

        Args:
            name: 技能名称

        Returns:
            dict | None: 元数据字典，如果未找到返回 None

        注意：
        ----
        这里使用简易的 YAML 解析（split 方式），
        只支持简单的 key: value 格式。
        复杂 YAML 需要使用专业库（如 pyyaml）。
        """
        # 加载技能内容
        content = self.load_skill(name)
        # 未找到返回 None
        if not content:
            return None

        # 检查是否以 --- 开头（frontmatter 标记）
        if content.startswith("---"):
            # 匹配 frontmatter 内容
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                metadata = {}
                # 逐行解析 YAML
                for line in match.group(1).split("\n"):
                    if ":" in line:
                        # 分割 key: value
                        key, value = line.split(":", 1)
                        # 去除引号和空白
                        metadata[key.strip()] = value.strip().strip('"\'')
                return metadata

        # 没有 frontmatter
        return None

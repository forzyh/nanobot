# Nanobot 记忆系统技术分析报告

## 目录

1. [概述](#1-概述)
2. [记忆系统架构设计](#2-记忆系统架构设计)
3. [LLM 调用时的记忆串联机制](#3-llm-调用时的记忆串联机制)
4. [提示词加载机制](#4-提示词加载机制)
5. [代码实现细节](#5-代码实现细节)
6. [总结与可扩展点](#6-总结与可扩展点)

---

## 1. 概述

### 1.1 项目背景

nanobot 是一个基于 LLM 的 AI Agent 框架，支持多渠道（Telegram、WhatsApp、Slack、Discord 等）交互。由于 LLM 本身没有长期记忆，每次对话都是"失忆"的，因此需要一套完整的记忆系统来：

1. 存储用户偏好和项目信息
2. 保持对话上下文的连贯性
3. 在上下文窗口限制内最大化有效信息
4. 支持历史对话的快速检索

### 1.2 记忆系统设计目标

| 目标 | 说明 |
|------|------|
| **持久化** | 重要的用户信息在重启后不丢失 |
| **分层存储** | 区分长期记忆和短期会话历史 |
| **成本控制** | 通过记忆巩固减少 token 消耗 |
| **可搜索** | 支持 grep 方式快速检索历史 |
| **自动化** | 基于 token 阈值自动触发记忆巩固 |

---

## 2. 记忆系统架构设计

### 2.1 核心组件和模块

nanobot 的记忆系统由以下核心组件构成：

```
nanobot/
├── agent/
│   ├── memory.py          # MemoryStore + MemoryConsolidator
│   ├── context.py         # ContextBuilder - 上下文组装
│   ├── loop.py            # AgentLoop - 核心处理引擎
│   └── skills.py          # SkillsLoader - 技能加载器
├── session/
│   ├── manager.py         # SessionManager - 会话管理
│   └── __init__.py        # 模块入口
├── templates/
│   ├── memory/
│   │   └── MEMORY.md      # 长期记忆模板
│   └── *.md               # 引导文件模板
└── skills/
    └── memory/SKILL.md    # 记忆使用技能说明
```

#### 2.1.1 核心类关系图

```
┌─────────────────────────────────────────────────────────────────┐
│                         AgentLoop                               │
│  - 接收消息总线消息                                              │
│  - 调用 ContextBuilder 构建上下文                                  │
│  - 调用 LLM 进行推理                                                │
│  - 执行工具调用                                                  │
│  - 调用 MemoryConsolidator 进行记忆巩固                            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ 使用
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       ContextBuilder                            │
│  - build_system_prompt(): 构建系统提示                           │
│  - build_messages(): 组装完整消息列表                            │
│  - _load_bootstrap_files(): 加载引导文件                         │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ 包含
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        MemoryStore                              │
│  - read_long_term(): 读取 MEMORY.md                             │
│  - append_history(): 追加 HISTORY.md                            │
│  - consolidate(): 调用 LLM 进行记忆巩固                           │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ 使用
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MemoryConsolidator                           │
│  - maybe_consolidate_by_tokens(): 基于 token 阈值触发巩固         │
│  - pick_consolidation_boundary(): 选择消息切分边界              │
│  - archive_unconsolidated(): /new 命令时归档                     │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ 管理
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SessionManager                             │
│  - get_or_create(): 获取/创建会话                                │
│  - save(): 保存会话到 JSONL 文件                                  │
│  - _load(): 从磁盘加载会话                                       │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 记忆的存储结构和数据模型

#### 2.2.1 两层记忆结构

nanobot 采用**两层记忆架构**：

| 层级 | 文件 | 作用 | 加载时机 |
|------|------|------|----------|
| **长期记忆** | `memory/MEMORY.md` | 存储持久化事实（用户偏好、项目信息、重要决策） | 每次 LLM 调用时加载到系统提示 |
| **历史日志** | `memory/HISTORY.md` | 按时间顺序记录对话摘要，支持 grep 搜索 | 不加载到 context，需要时手动检索 |

#### 2.2.2 MEMORY.md 结构

```markdown
# Long-term Memory

## User Information
(关于用户的重要事实)

## Preferences
(用户偏好)

## Project Context
(项目相关信息)

## Important Notes
(其他需要记住的内容)
```

#### 2.2.3 HISTORY.md 结构

```markdown
[2024-01-01 10:00] 用户询问如何创建 Python 文件，助手展示了使用 write_file 工具的方法。

[2024-01-01 11:00] 用户要求解释异步编程，助手详细解释了 async/await 的用法。

[2024-01-01 12:00] 讨论了记忆系统的设计，决定采用两层架构。
```

**设计亮点**：
- 每个条目以 `[YYYY-MM-DD HH:MM]` 开头，便于时间定位
- 条目之间用空行分隔，便于 grep 搜索
- 使用描述性语言，包含关键词便于检索

#### 2.2.4 会话数据结构 (Session)

```python
@dataclass
class Session:
    key: str                          # 会话密钥："channel:chat_id"
    messages: list[dict[str, Any]]    # 消息历史列表
    created_at: datetime              # 创建时间
    updated_at: datetime              # 最后更新时间
    metadata: dict[str, Any]          # 元数据
    last_consolidated: int            # 已巩固的消息数量
```

**消息格式**：
```json
{
    "role": "user|assistant|tool",
    "content": "消息内容",
    "timestamp": "2024-01-01T12:00:00",
    "tool_calls": [...],              // 可选
    "tool_call_id": "..."             // 可选
}
```

#### 2.2.5 会话存储格式 (JSONL)

会话以 **JSONL (JSON Lines)** 格式存储在 `sessions/{key}.jsonl`：

```jsonl
{"_type": "metadata", "key": "cli:direct", "created_at": "...", "updated_at": "...", "last_consolidated": 10}
{"role": "user", "content": "Hello", "timestamp": "..."}
{"role": "assistant", "content": "Hi!", "timestamp": "..."}
{"role": "user", "content": "帮我写个文件", "timestamp": "..."}
```

**JSONL 格式优势**：
- 追加写入无需读取整个文件
- 单行损坏不影响其他数据
- 支持流式读取大文件

### 2.3 记忆的分类

nanobot 将记忆分为三个层次：

```
┌──────────────────────────────────────────────────────────────┐
│                         工作记忆                              │
│                    (Working Memory)                           │
│   当前 LLM 上下文窗口中的内容（系统提示 + 会话历史）              │
│   - 系统提示（身份、引导文件、记忆、技能）                     │
│   - 未巩固的会话历史（last_consolidated 之后的消息）           │
│   - 当前用户消息 + 运行时上下文                               │
└──────────────────────────────────────────────────────────────┘
                              │
                              │ 定期巩固
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                         短期记忆                              │
│                   (Short-term Memory)                         │
│   Session.messages 中已巩固但仍在文件中的原始对话              │
│   - 可通过 get_history(max_messages=N) 获取                    │
│   - 占用上下文窗口时触发巩固                                   │
└──────────────────────────────────────────────────────────────┘
                              │
                              │ 归档总结
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                         长期记忆                              │
│                   (Long-term Memory)                          │
│   MEMORY.md + HISTORY.md                                      │
│   - MEMORY.md: 每次 LLM 调用都加载                              │
│   - HISTORY.md: 按需 grep 检索                                  │
└──────────────────────────────────────────────────────────────┘
```

| 记忆类型 | 存储位置 | 生命周期 | 加载方式 |
|----------|----------|----------|----------|
| **工作记忆** | LLM 上下文窗口 | 单次对话 | 每次调用构建 |
| **短期记忆** | sessions/*.jsonl | 会话周期 | 按需加载 |
| **长期记忆** | memory/*.md | 永久 | 启动时加载 |

---

## 3. LLM 调用时的记忆串联机制

### 3.1 记忆检索流程

当 Agent 需要调用 LLM 时，记忆的检索和注入流程如下：

```
┌─────────────────────────────────────────────────────────────────┐
│                    1. AgentLoop._process_message()              │
│   - 获取或创建 Session                                           │
│   - 调用 memory_consolidator.maybe_consolidate_by_tokens()      │
│   - 获取会话历史：session.get_history(max_messages=0)           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    2. ContextBuilder.build_messages()           │
│   - 调用 build_system_prompt(skill_names)                       │
│     ├── _get_identity()          # 身份定义                    │
│     ├── _load_bootstrap_files()  # 引导文件                    │
│     ├── memory.get_memory_context()  # 长期记忆               │
│     └── skills.load_skills_for_context()  # 常驻技能          │
│   - 构建运行时上下文                                              │
│   - 组装历史消息 + 当前消息                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    3. AgentLoop._run_agent_loop()               │
│   - 调用 provider.chat_with_retry(messages=..., tools=...)      │
│   - 获取 LLM 响应                                                  │
│   - 执行工具调用（如有）                                          │
│   - 迭代直到完成或达到最大迭代次数                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    4. AgentLoop._save_turn()                    │
│   - 保存新消息到 Session.messages                                │
│   - 截断过长的工具结果                                           │
│   - 移除运行时上下文前缀                                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│              5. MemoryConsolidator.maybe_consolidate_by_tokens()│
│   - 估算当前 prompt token 数                                      │
│   - 如果超过阈值 (context_window/2)，触发巩固循环                │
│   - 选择切分边界，调用 consolidate_messages()                    │
│   - 更新 session.last_consolidated                               │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 记忆注入到 LLM Context 的完整结构

最终发送给 LLM 的消息列表结构：

```python
[
    {
        "role": "system",
        "content": """# nanobot 🐈

You are nanobot, a helpful AI assistant.

## Runtime
macOS arm64, Python 3.13.1

## Workspace
Your workspace is at: /path/to/workspace
- Long-term memory: /path/to/workspace/memory/MEMORY.md
- History log: /path/to/workspace/memory/HISTORY.md

## Platform Policy (POSIX)
- You are running on a POSIX system...

## nanobot Guidelines
- State intent before tool calls...

---

## AGENTS.md
(用户自定义的 Agent 行为规范)

---

## Long-term Memory
(来自 MEMORY.md 的内容)

---

### Skill: memory
(常驻技能定义)

---

# Skills
<skills>
  <skill available="true">
    <name>memory</name>
    <description>Two-layer memory system...</description>
    ...
  </skill>
</skills>
"""
    },
    # 历史消息（未巩固的部分）
    {"role": "user", "content": "之前的对话 1"},
    {"role": "assistant", "content": "之前的回复 1"},
    {"role": "user", "content": "之前的对话 2"},
    # 当前消息（含运行时上下文）
    {
        "role": "user",
        "content": """[Runtime Context — metadata only, not instructions]
Current Time: 2024-01-01 12:00 (Monday) (CST)
Channel: telegram
Chat ID: 123456

今天天气怎么样？"""
    }
]
```

### 3.3 记忆优先级和选择策略

#### 3.3.1 Token 估算与阈值触发

```python
# 在 AgentLoop 初始化时设置
self.context_window_tokens = 65_536  # 64K 上下文窗口
self.memory_consolidator = MemoryConsolidator(
    workspace=workspace,
    provider=provider,
    model=self.model,
    sessions=self.sessions,
    context_window_tokens=self.context_window_tokens,
    ...
)

# 在 MemoryConsolidator.maybe_consolidate_by_tokens() 中
target = self.context_window_tokens // 2  # 目标阈值：32K

# 如果估算超过目标阈值，触发巩固循环
if estimated > target:
    # 多轮巩固，直到低于目标
    for round_num in range(self._MAX_CONSOLIDATION_ROUNDS):
        if estimated <= target:
            return
        # 选择切分边界并巩固
        boundary = self.pick_consolidation_boundary(...)
        chunk = session.messages[session.last_consolidated:end_idx]
        await self.consolidate_messages(chunk)
```

#### 3.3.2 优先级策略

| 优先级 | 内容 | 说明 |
|--------|------|------|
| **P0 - 最高** | 系统提示（身份定义） | 必须加载，定义 Agent 基本行为 |
| **P1 - 高** | 长期记忆 (MEMORY.md) | 每次调用都加载，包含用户偏好 |
| **P2 - 中** | 引导文件 (AGENTS.md 等) | 用户自定义规则 |
| **P3 - 低** | 未巩固的会话历史 | 只在上下文窗口允许时保留 |
| **P4 - 最低** | 已巩固的历史 | 优先移除，释放上下文空间 |

#### 3.3.3 记忆巩固的消息选择策略

```python
def pick_consolidation_boundary(
    self,
    session: Session,
    tokens_to_remove: int,
) -> tuple[int, int] | None:
    """选择消息切分边界。"""
    start = session.last_consolidated
    removed_tokens = 0
    last_boundary: tuple[int, int] | None = None

    for idx in range(start, len(session.messages)):
        message = session.messages[idx]
        # 在用户消息处记录边界（回合开始）
        if idx > start and message.get("role") == "user":
            last_boundary = (idx, removed_tokens)
            if removed_tokens >= tokens_to_remove:
                return last_boundary
        removed_tokens += estimate_message_tokens(message)

    return last_boundary
```

**切分策略要点**：
- 只在完整的"用户 - 助手"回合处切分
- 避免切断工具调用的连续性
- 从 `last_consolidated` 位置开始累加 token

---

## 4. 提示词加载机制

### 4.1 提示词类型

nanobot 在 LLM 调用时加载的提示词分为以下几类：

| 类型 | 来源 | 内容 | 加载时机 |
|------|------|------|----------|
| **系统提示** | ContextBuilder.build_system_prompt() | 身份定义 + 引导文件 + 记忆 + 技能 | 每次 LLM 调用 |
| **用户提示** | 当前消息 + 运行时上下文 | 用户输入 + 时间/渠道元数据 | 每次 LLM 调用 |
| **历史提示** | Session.get_history() | 未巩固的对话历史 | 每次 LLM 调用 |
| **工具提示** | ToolRegistry.get_definitions() | 工具定义 (JSON Schema) | 每次 LLM 调用 |

### 4.2 系统提示的组成结构

```python
def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
    parts = [self._get_identity()]  # 1. 身份定义

    # 2. 引导文件
    bootstrap = self._load_bootstrap_files()
    if bootstrap:
        parts.append(bootstrap)

    # 3. 长期记忆
    memory = self.memory.get_memory_context()
    if memory:
        parts.append(f"# Memory\n\n{memory}")

    # 4. 常驻技能（always=True）
    always_skills = self.skills.get_always_skills()
    if always_skills:
        always_content = self.skills.load_skills_for_context(always_skills)
        if always_content:
            parts.append(f"# Active Skills\n\n{always_content}")

    # 5. 技能摘要（所有可用技能）
    skills_summary = self.skills.build_skills_summary()
    if skills_summary:
        parts.append(f"""# Skills
The following skills extend your capabilities...
{skills_summary}""")

    return "\n\n---\n\n".join(parts)
```

### 4.3 提示词加载流程和执行顺序

```
┌─────────────────────────────────────────────────────────────────┐
│  启动阶段                                                        │
│  1. AgentLoop 初始化                                             │
│     - 创建 ContextBuilder                                        │
│     - 创建 MemoryStore                                           │
│     - 创建 SkillsLoader                                          │
│     - 创建 MemoryConsolidator                                    │
│     - 注册默认工具                                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  消息处理阶段                                                    │
│  2. AgentLoop._process_message()                                │
│     - 获取/创建 Session                                          │
│     - 触发记忆巩固（如需要）                                      │
│     - 设置工具上下文                                             │
│     - 获取会话历史：history = session.get_history()             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  上下文构建阶段                                                  │
│  3. ContextBuilder.build_messages()                             │
│     - build_system_prompt():                                     │
│       ├── _get_identity()                                        │
│       ├── _load_bootstrap_files()                                │
│       ├── memory.get_memory_context()                            │
│       ├── skills.get_always_skills()                             │
│       └── skills.build_skills_summary()                          │
│     - _build_runtime_context(): 时间、渠道、聊天 ID              │
│     - _build_user_content(): 用户消息 + 媒体内容                 │
│     - 组装完整消息列表                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  LLM 调用阶段                                                     │
│  4. AgentLoop._run_agent_loop()                                 │
│     - 获取工具定义：tool_defs = self.tools.get_definitions()    │
│     - 调用 LLM: provider.chat_with_retry(messages, tools)        │
│     - 处理响应（工具调用/最终回复）                               │
│     - 迭代执行直到完成                                           │
└─────────────────────────────────────────────────────────────────┘
```

### 4.4 触发提示词加载的事件

| 事件类型 | 触发时机 | 说明 |
|----------|----------|------|
| **入站消息** | 用户发送消息 | 最常见的触发方式 |
| **系统消息** | 后台任务/定时任务 | 通过 system 渠道触发 |
| **CLI 输入** | 命令行交互 | 直接调用 process_direct() |
| **/new 命令** | 用户请求新会话 | 触发记忆归档后重新加载 |
| **Token 阈值** | 会话历史过大 | 自动触发记忆巩固 |

### 4.5 运行时上下文注入

运行时上下文是一个特殊的元数据块，在每次 LLM 调用前注入到用户消息中：

```python
@staticmethod
def _build_runtime_context(channel: str | None, chat_id: str | None) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
    tz = time.strftime("%Z") or "UTC"
    lines = [f"Current Time: {now} ({tz})"]
    if channel and chat_id:
        lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
    return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n".join(lines)
```

**输出示例**：
```
[Runtime Context — metadata only, not instructions]
Current Time: 2024-01-01 12:00 (Monday) (CST)
Channel: telegram
Chat ID: 123456
```

**设计意图**：
- 使用明确标签标记这是元数据，不是指令
- 告诉 LLM 这部分是参考信息，不应作为指令执行
- 提供时间、渠道等信息，帮助 LLM 理解当前上下文

---

## 5. 代码实现细节

### 5.1 关键代码文件和函数

#### 5.1.1 MemoryStore (nanobot/agent/memory.py)

```python
class MemoryStore:
    """两层记忆系统：MEMORY.md + HISTORY.md"""

    def __init__(self, workspace: Path):
        self.memory_dir = ensure_dir(workspace / "memory")
        self.memory_file = self.memory_dir / "MEMORY.md"
        self.history_file = self.memory_dir / "HISTORY.md"

    def read_long_term(self) -> str:
        """读取长期记忆"""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8")
        return ""

    def append_history(self, entry: str) -> None:
        """追加历史条目"""
        with open(self.history_file, "a", encoding="utf-8") as f:
            f.write(entry.rstrip() + "\n\n")

    async def consolidate(
        self,
        messages: list[dict],
        provider: LLMProvider,
        model: str,
    ) -> bool:
        """记忆巩固：调用 LLM 总结对话并更新记忆"""
        current_memory = self.read_long_term()
        prompt = f"""Process this conversation and call the save_memory tool...

Current Long-term Memory:
{current_memory or "(empty)"}

Conversation to Process:
{self._format_messages(messages)}"""

        response = await provider.chat_with_retry(
            messages=[
                {"role": "system", "content": "You are a memory consolidation agent..."},
                {"role": "user", "content": prompt},
            ],
            tools=_SAVE_MEMORY_TOOL,
            model=model,
            tool_choice="required",  # 强制使用工具
        )

        # 保存 LLM 返回的记忆更新
        args = _normalize_save_memory_args(response.tool_calls[0].arguments)
        if entry := args.get("history_entry"):
            self.append_history(_ensure_text(entry))
        if update := args.get("memory_update"):
            self.write_long_term(_ensure_text(update))
```

#### 5.1.2 MemoryConsolidator (nanobot/agent/memory.py)

```python
class MemoryConsolidator:
    """记忆巩固策略层"""

    _MAX_CONSOLIDATION_ROUNDS = 5

    async def maybe_consolidate_by_tokens(self, session: Session) -> None:
        """基于 token 阈值的记忆巩固"""
        if not session.messages or self.context_window_tokens <= 0:
            return

        lock = self.get_lock(session.key)
        async with lock:
            target = self.context_window_tokens // 2

            for round_num in range(self._MAX_CONSOLIDATION_ROUNDS):
                estimated, source = self.estimate_session_prompt_tokens(session)
                if estimated <= target:
                    return

                boundary = self.pick_consolidation_boundary(
                    session, max(1, estimated - target)
                )
                if boundary is None:
                    return

                chunk = session.messages[session.last_consolidated:boundary[0]]
                if not chunk:
                    return

                logger.info("Token consolidation round {} for {}: {}/{}",
                           round_num, session.key, estimated, self.context_window_tokens)

                await self.consolidate_messages(chunk)
                session.last_consolidated = boundary[0]
                self.sessions.save(session)
```

#### 5.1.3 ContextBuilder (nanobot/agent/context.py)

```python
class ContextBuilder:
    """上下文构建器"""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)

    def build_system_prompt(self, skill_names: list[str] | None = None) -> str:
        parts = [self._get_identity()]

        bootstrap = self._load_bootstrap_files()
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            parts.append(f"# Active Skills\n\n{
                self.skills.load_skills_for_context(always_skills)}")

        skills_summary = self.skills.build_skills_summary()
        if skills_summary:
            parts.append(f"# Skills\n\n{skills_summary}")

        return "\n\n---\n\n".join(parts)

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
    ) -> list[dict[str, Any]]:
        runtime_ctx = self._build_runtime_context(channel, chat_id)
        user_content = self._build_user_content(current_message, media)

        # 合并运行时上下文和用户内容
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content

        return [
            {"role": "system", "content": self.build_system_prompt(skill_names)},
            *history,
            {"role": "user", "content": merged},
        ]
```

#### 5.1.4 AgentLoop (nanobot/agent/loop.py)

```python
class AgentLoop:
    """Agent 核心循环"""

    def __init__(self, bus: MessageBus, provider: LLMProvider, workspace: Path, ...):
        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()

        self.memory_consolidator = MemoryConsolidator(
            workspace=workspace,
            provider=provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
        )

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        # 获取或创建会话
        session = self.sessions.get_or_create(msg.session_key)

        # 处理斜杠命令
        if msg.content.strip().lower() == "/new":
            await self.memory_consolidator.archive_unconsolidated(session)
            session.clear()
            return OutboundMessage(..., content="New session started.")

        # 记忆巩固
        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

        # 获取会话历史
        history = session.get_history(max_messages=0)

        # 构建消息上下文
        initial_messages = self.context.build_messages(
            history=history,
            current_message=msg.content,
            media=msg.media,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        # 运行 Agent 循环
        final_content, _, all_msgs = await self._run_agent_loop(
            initial_messages, on_progress=_bus_progress,
        )

        # 保存回合并再次巩固
        self._save_turn(session, all_msgs, 1 + len(history))
        self.sessions.save(session)
        await self.memory_consolidator.maybe_consolidate_by_tokens(session)

        return OutboundMessage(..., content=final_content)
```

### 5.2 数据流和调用链

```
用户消息
    │
    ▼
MessageBus.consume_inbound()
    │
    ▼
AgentLoop._dispatch(msg)
    │
    ▼
AgentLoop._process_message(msg)
    │
    ├──→ SessionManager.get_or_create(key)
    │       └──→ 从磁盘加载或创建新 Session
    │
    ├──→ MemoryConsolidator.maybe_consolidate_by_tokens(session)
    │       ├──→ estimate_session_prompt_tokens()
    │       ├──→ pick_consolidation_boundary()
    │       └──→ consolidate_messages(chunk)
    │               └──→ MemoryStore.consolidate()
    │                       └──→ LLM.chat_with_retry()
    │
    ├──→ ContextBuilder.build_messages(...)
    │       ├──→ build_system_prompt()
    │       │       ├──→ _get_identity()
    │       │       ├──→ _load_bootstrap_files()
    │       │       ├──→ memory.get_memory_context()
    │       │       └──→ skills.load_skills_for_context()
    │       ├──→ _build_runtime_context()
    │       └──→ _build_user_content()
    │
    ├──→ AgentLoop._run_agent_loop(messages)
    │       ├──→ provider.chat_with_retry()
    │       ├──→ ToolRegistry.execute()
    │       └──→ context.add_assistant_message() / add_tool_result()
    │
    └──→ _save_turn(session, messages, skip)
            └──→ session.messages.append(...)
```

### 5.3 配置项和可扩展点

#### 5.3.1 可配置项

| 配置项 | 位置 | 默认值 | 说明 |
|--------|------|--------|------|
| `context_window_tokens` | AgentLoop 初始化 | 65,536 | LLM 上下文窗口大小 |
| `max_iterations` | AgentLoop 初始化 | 40 | 工具调用最大迭代次数 |
| `workspace` | AgentLoop 初始化 | - | 工作空间路径 |
| `model` | AgentLoop 初始化 | 提供商默认 | LLM 模型名称 |
| `consolidation_model` | MemoryConsolidator | 同主模型 | 记忆巩固用模型 |

#### 5.3.2 可扩展点

1. **自定义记忆存储后端**
   ```python
   # 可以继承 MemoryStore 实现不同的存储后端
   class DatabaseMemoryStore(MemoryStore):
       def read_long_term(self) -> str:
           # 从数据库读取
           return db.query("SELECT content FROM memory WHERE key='long_term'")

       def append_history(self, entry: str) -> None:
           # 写入数据库
           db.insert("history", {"content": entry, "timestamp": now()})
   ```

2. **自定义记忆巩固策略**
   ```python
   # 可以继承 MemoryConsolidator 实现不同的巩固策略
   class TimeBasedConsolidator(MemoryConsolidator):
       async def maybe_consolidate_by_tokens(self, session: Session) -> None:
           # 基于时间而不是 token 数量触发巩固
           if session.should_consolidate_by_time():
               await self.archive_unconsolidated(session)
   ```

3. **自定义提示词模板**
   ```python
   # 可以继承 ContextBuilder 定制系统提示
   class CustomContextBuilder(ContextBuilder):
       def build_system_prompt(self, skill_names=None) -> str:
           # 添加自定义的系统提示部分
           parts = [self._get_identity()]
           parts.append(self._load_custom_instructions())
           parts.append(self.memory.get_memory_context())
           return "\n\n---\n\n".join(parts)
   ```

4. **自定义技能加载**
   ```python
   # 可以在 workspace/skills/ 目录下添加自定义技能
   skills/
   └── my-custom-skill/
       └── SKILL.md
   ```

5. **引导文件扩展**
   ```python
   # 可以在工作空间根目录添加自定义引导文件
   workspace/
   ├── AGENTS.md      # Agent 行为规范
   ├── SOUL.md        # 个性设定
   ├── USER.md        # 用户偏好
   ├── TOOLS.md       # 工具使用说明
   └── CUSTOM.md      # 自定义规则
   ```

---

## 6. 总结与可扩展点

### 6.1 设计亮点

1. **两层记忆架构**
   - MEMORY.md 存储重要事实，每次调用都加载
   - HISTORY.md 记录对话摘要，按需 grep 检索
   - 平衡了完整性和效率

2. **自动记忆巩固**
   - 基于 token 阈值自动触发
   - 多轮渐进式巩固，避免一次性处理过多
   - 使用 LLM 进行智能总结，而非简单截断

3. **追加式会话存储**
   - JSONL 格式，高效追加写入
   - 会话历史不可变，避免 LLM 缓存失效
   - last_consolidated 追踪已处理消息

4. **模块化设计**
   - MemoryStore 负责存储
   - MemoryConsolidator 负责策略
   - ContextBuilder 负责组装
   - 各组件职责清晰，易于扩展

### 6.2 潜在改进方向

1. **向量记忆检索**
   - 当前 MEMORY.md 是全量加载，可以考虑使用向量数据库
   - 基于相似度检索相关记忆，减少 token 消耗

2. **多级记忆优先级**
   - 可以为 MEMORY.md 中的不同部分设置不同优先级
   - 高频使用的记忆优先保留，低频的可以压缩

3. **增量巩固**
   - 当前是批量巩固，可以实现实时增量巩固
   - 每条重要消息立即提取到长期记忆

4. **记忆版本控制**
   - 为 MEMORY.md 添加版本历史
   - 支持回滚和对比不同版本的记忆

### 6.3 核心代码统计

| 模块 | 代码行数 | 核心函数 |
|------|----------|----------|
| memory.py | ~690 行 | consolidate(), maybe_consolidate_by_tokens() |
| context.py | ~540 行 | build_system_prompt(), build_messages() |
| manager.py | ~480 行 | get_or_create(), save(), _load() |
| loop.py | ~980 行 | _process_message(), _run_agent_loop() |

### 6.4 记忆系统调用时序图

```
用户                    AgentLoop              SessionManager          MemoryConsolidator         LLM
 │                          │                        │                        │                     │
 │── 发送消息 ────────────→ │                        │                        │                     │
 │                          │── get_or_create() ───→│                        │                     │
 │                          │←─ Session ────────────│                        │                     │
 │                          │                        │                        │                     │
 │                          │── maybe_consolidate_by_tokens()                │                     │
 │                          │                        │                        │                     │
 │                          │───┐ 估算 token                                                 │                     │
 │                          │    │ 超过阈值？                                                │                     │
 │                          │←───┘ 是 → pick_boundary() → consolidate_messages()            │                     │
 │                          │                        │                        │                     │
 │                          │                        │                        │── save_memory 工具调用 ──→ │
 │                          │                        │                        │←─ 记忆更新 ───────────── │
 │                          │                        │                        │                     │
 │                          │                        │                        │                     │
 │                          │── build_messages() ──→│                        │                     │
 │                          │←─ 完整消息列表 ────────│                        │                     │
 │                          │                        │                        │                     │
 │                          │── chat_with_retry(messages, tools) ────────────────────────────────────→ │
 │                          │←─ LLM 响应 (content/tool_calls) ───────────────────────────────────── │
 │                          │                        │                        │                     │
 │                          │── execute_tool()                               │                     │
 │                          │── _save_turn() ──────→│                        │                     │
 │                          │                        │── save() ────────────→│                     │
 │                          │                        │                        │                     │
 │                          │── maybe_consolidate_by_tokens() (再次检查)      │                     │
 │                          │                        │                        │                     │
 │←─ 最终回复 ──────────────│                        │                        │                     │
```

---

## 附录：关键文件路径

```
nanobot/
├── agent/
│   ├── memory.py          # 核心记忆实现
│   ├── context.py         # 上下文构建器
│   ├── loop.py            # Agent 核心循环
│   ├── skills.py          # 技能加载器
│   └── tools/
│       ├── registry.py    # 工具注册表
│       └── ...
├── session/
│   └── manager.py         # 会话管理器
├── templates/
│   ├── memory/
│   │   └── MEMORY.md      # 长期记忆模板
│   ├── AGENTS.md          # Agent 引导文件
│   ├── SOUL.md            # 个性设定模板
│   ├── USER.md            # 用户偏好模板
│   └── TOOLS.md           # 工具使用模板
└── skills/
    └── memory/
        └── SKILL.md       # 记忆使用技能说明
```

---

**报告生成时间**: 2024-01-XX
**分析基于版本**: nanobot main 分支
**分析文件**: memory.py, context.py, loop.py, manager.py, skills.py, registry.py

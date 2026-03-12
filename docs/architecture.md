# nanobot 架构文档

## 项目概述

**nanobot** 是一个超轻量级个人 AI 助手框架，支持多种聊天渠道（Telegram、WhatsApp、飞书、钉钉等）。

- **PyPI**: [nanobot-ai](https://pypi.org/project/nanobot-ai/)
- **Python 版本**: >= 3.11
- **许可证**: MIT

---

## 目录结构

```
nanobot/
├── nanobot/                 # 主程序包
│   ├── agent/              # AI Agent 核心
│   │   ├── __init__.py
│   │   ├── context.py      # 上下文构建器
│   │   ├── loop.py         # Agent 主循环（核心引擎）
│   │   ├── memory.py       # 记忆管理
│   │   ├── skills.py       # 技能系统
│   │   ├── subagent.py     # 子 Agent 管理
│   │   └── tools/          # 工具集
│   │       ├── __init__.py
│   │       ├── base.py     # 工具基类
│   │       ├── cron.py     # 定时任务工具
│   │       ├── filesystem.py  # 文件系统工具
│   │       ├── mcp.py      # MCP 协议支持
│   │       ├── message.py  # 消息工具
│   │       ├── registry.py # 工具注册表
│   │       ├── shell.py    # Shell 执行工具
│   │       ├── spawn.py    # 进程生成工具
│   │       └── web.py      # 网页搜索/抓取工具
│   │
│   ├── channels/           # 聊天渠道实现
│   │   ├── __init__.py
│   │   ├── base.py        # 渠道基类
│   │   ├── manager.py     # 渠道管理器
│   │   ├── registry.py    # 渠道注册表
│   │   ├── telegram.py    # Telegram
│   │   ├── whatsapp.py    # WhatsApp
│   │   ├── feishu.py      # 飞书
│   │   ├── dingtalk.py    # 钉钉
│   │   ├── discord.py     # Discord
│   │   ├── slack.py       # Slack
│   │   ├── matrix.py      # Matrix
│   │   ├── qq.py          # QQ
│   │   ├── wecom.py       # 企业微信
│   │   └── email.py       # Email
│   │
│   ├── providers/          # LLM 提供商
│   │   ├── __init__.py
│   │   ├── base.py        # 提供商基类
│   │   ├── litellm_provider.py  # LiteLLM 支持
│   │   ├── azure_openai_provider.py  # Azure OpenAI
│   │   ├── openai_codex_provider.py  # OpenAI Codex (OAuth)
│   │   ├── custom_provider.py  # 自定义兼容端点
│   │   ├── registry.py    # 提供商注册表
│   │   └── transcription.py  # 语音转写
│   │
│   ├── bus/               # 消息总线
│   │   ├── __init__.py
│   │   ├── events.py      # 事件定义
│   │   └── queue.py       # 消息队列
│   │
│   ├── config/            # 配置管理
│   │   ├── __init__.py
│   │   ├── loader.py      # 配置加载器
│   │   ├── paths.py       # 路径工具
│   │   └── schema.py      # Pydantic 配置模型
│   │
│   ├── cron/              # 定时任务服务
│   │   ├── __init__.py
│   │   ├── service.py
│   │   └── types.py
│   │
│   ├── heartbeat/         # 心跳服务
│   │   ├── __init__.py
│   │   └── service.py
│   │
│   ├── session/           # 会话管理
│   │   ├── __init__.py
│   │   └── manager.py
│   │
│   ├── cli/               # 命令行接口
│   │   ├── __init__.py
│   │   └── commands.py    # 主 CLI 入口
│   │
│   ├── bridge/            # WhatsApp 桥接服务 (Node.js)
│   │   ├── package.json
│   │   └── src/
│   │       ├── index.ts
│   │       ├── server.ts
│   │       └── whatsapp.ts
│   │
│   ├── templates/         # 模板文件
│   │   └── memory/
│   │
│   ├── skills/            # 技能定义
│   │   └── skill-creator/
│   │
│   ├── utils/             # 工具函数
│   │   └── helpers.py
│   │
│   ├── __init__.py        # 包入口（版本、logo）
│   ├── __main__.py        # 模块入口
│   └── pyproject.toml     # 项目配置
│
├── tests/                 # 测试目录
├── bridge/                # 独立桥接服务源码
├── case/                  # 演示案例（GIF）
├── docker-compose.yml     # Docker 部署配置
├── Dockerfile             # Docker 镜像构建
├── pyproject.toml         # Python 项目配置
├── README.md              # 项目说明
├── COMMUNICATION.md       # 社区交流
└── SECURITY.md            # 安全政策
```

---

## 核心入口

### 1. 命令行入口

**入口文件**: `nanobot/cli/commands.py`

运行方式:
```bash
# 直接命令
nanobot

# Python 模块方式
python -m nanobot
```

入口流程:
```
nanobot/__main__.py
    ↓
nanobot/cli/commands.py (app = typer.Typer())
```

### 2. 主要 CLI 命令

| 命令 | 说明 |
|------|------|
| `nanobot` | 交互式 CLI 对话 |
| `nanobot agent -m "消息"` | 发送单条消息 |
| `nanobot gateway` | 启动网关服务（多频道模式） |
| `nanobot onboard` | 初始化配置和工作空间 |
| `nanobot status` | 查看配置和状态 |
| `nanobot channels status` | 查看渠道状态 |
| `nanobot channels login` | WhatsApp 二维码登录 |
| `nanobot provider login <provider>` | OAuth 认证（如 openai-codex） |

---

## 架构组件

### 核心处理流程

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户消息                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    渠道层 (Channels)                             │
│   Telegram | WhatsApp | Feishu | DingTalk | Discord | Slack    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    消息总线 (MessageBus)                         │
│              内部事件队列，协调各组件通信                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                  Agent 循环 (AgentLoop)                          │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │  1. 接收消息 → 2. 构建上下文 → 3. 调用 LLM → 4. 执行工具    │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────┼─────────────────────┐
        ↓                     ↓                     ↓
┌───────────────┐    ┌────────────────┐   ┌────────────────┐
│  上下文构建    │    │    记忆系统     │   │   工具注册表    │
│ ContextBuilder│    │   Memory       │   │  ToolRegistry  │
└───────────────┘    └────────────────┘   └────────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                   LLM 提供商 (Providers)                         │
│   OpenAI | Azure | LiteLLM | Custom | GitHub Copilot           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────┼─────────────────────┐
        ↓                     ↓                     ↓
┌───────────────┐    ┌────────────────┐   ┌────────────────┐
│  文件系统工具  │    │   Web 搜索工具  │   │  Shell 执行工具 │
│  定时任务工具  │    │   MCP 协议工具  │   │  消息发送工具  │
│  子 Agent 工具 │    │   进程生成工具  │   │                │
└───────────────┘    └────────────────┘   └────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    响应返回                                      │
│          渠道管理器 → 具体渠道 → 用户                            │
└─────────────────────────────────────────────────────────────────┘
```

### 关键组件说明

| 组件 | 文件位置 | 说明 |
|------|----------|------|
| **AgentLoop** | `nanobot/agent/loop.py` | 核心处理引擎，负责消息处理、LLM 调用、工具执行循环 |
| **MessageBus** | `nanobot/bus/queue.py` | 内部消息队列，处理 Inbound/Outbound 事件 |
| **ChannelManager** | `nanobot/channels/manager.py` | 管理多个聊天渠道的启动/停止/路由 |
| **ToolRegistry** | `nanobot/agent/tools/registry.py` | 工具注册和调度中心 |
| **SessionManager** | `nanobot/session/manager.py` | 会话状态和历史管理 |
| **MemoryConsolidator** | `nanobot/agent/memory.py` | 长期记忆整合和检索 |
| **SubagentManager** | `nanobot/agent/subagent.py` | 子 Agent 创建和管理 |
| **CronService** | `nanobot/cron/service.py` | 定时任务调度服务 |
| **HeartbeatService** | `nanobot/heartbeat/service.py` | 定期任务触发服务 |

---

## 工具系统 (Tools)

### 内置工具列表

| 工具 | 说明 |
|------|------|
| `cron` | 创建/管理定时任务 |
| `message` | 发送消息到指定渠道 |
| `shell` | 执行 Shell 命令 |
| `spawn` | 后台进程管理 |
| `read_file` | 读取文件内容 |
| `write_file` | 写入文件内容 |
| `edit_file` | 编辑文件（支持 diff） |
| `list_dir` | 列出目录内容 |
| `web_search` | 网络搜索（Brave API） |
| `web_fetch` | 网页内容抓取 |
| `mcp` | Model Context Protocol 支持 |
| `subagent` | 创建/管理子 Agent |

---

## 支持的渠道 (Channels)

| 渠道 | 配置项 | 说明 |
|------|--------|------|
| **WhatsApp** | `channels.whatsapp` | 通过 Node.js 桥接服务连接 |
| **Telegram** | `channels.telegram` | Bot API，支持群聊@提及 |
| **飞书 (Feishu)** | `channels.feishu` | WebSocket 长连接 |
| **钉钉 (DingTalk)** | `channels.dingtalk` | Stream 模式 |
| **Discord** | `channels.discord` | Gateway WebSocket |
| **Slack** | `channels.slack` | Socket Mode |
| **Matrix** | `channels.matrix` | 支持 E2EE 加密 |
| **QQ** | `channels.qq` | QQ 机器人 |
| **企业微信 (WeCom)** | `channels.wecom` | 企业微信应用 |
| **Email** | `channels.email` | IMAP 收件 + SMTP 发件 |

---

## 支持的 LLM 提供商 (Providers)

| 提供商 | 配置名 | 认证方式 |
|--------|--------|----------|
| **OpenAI** | `openai` | API Key |
| **Azure OpenAI** | `azure_openai` | API Key + Endpoint |
| **OpenAI Codex** | `openai_codex` | OAuth |
| **GitHub Copilot** | `github_copilot` | OAuth (自动触发) |
| **Anthropic** | `anthropic` | API Key |
| **Ollama** | `ollama` | 本地部署 |
| **Custom** | `custom` | 兼容 OpenAI 端点 |

通过 LiteLLM 支持更多提供商：Groq、Bedrock、Gemini 等。

---

## 配置管理

### 配置文件位置

- **macOS/Linux**: `~/.nanobot/config.json`
- **工作空间**: `~/.nanobot/workspace/`

### 配置结构 (Schema)

```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-sonnet-4-20250514",
      "temperature": 0.7,
      "maxTokens": 4096,
      "contextWindowTokens": 65536,
      "workspace": "~/.nanobot/workspace"
    }
  },
  "providers": {
    "anthropic": { "api_key": "..." },
    "openai": { "api_key": "..." }
  },
  "channels": {
    "telegram": {
      "enabled": false,
      "token": "...",
      "allow_from": []
    },
    "whatsapp": {
      "enabled": false,
      "bridge_url": "ws://localhost:3001"
    }
  },
  "gateway": {
    "port": 8000,
    "heartbeat": {
      "enabled": true,
      "interval_s": 3600
    }
  },
  "tools": {
    "exec": { "allowed": ["*"] },
    "web": { "search": { "api_key": "" } },
    "restrict_to_workspace": false
  }
}
```

---

## 启动方式

### 1. 初始化配置

```bash
nanobot onboard
```

创建默认配置文件和工作空间。

### 2. 交互式对话

```bash
nanobot agent
# 或
nanobot agent -m "Hello!"
```

### 3. 启动网关服务

```bash
nanobot gateway
# 指定端口
nanobot gateway -p 9000
```

### 4. Docker 部署

```bash
docker-compose up -d
```

---

## 依赖项

### 核心依赖

| 包 | 用途 |
|----|------|
| `typer` | CLI 框架 |
| `litellm` | LLM 统一接口 |
| `pydantic` | 配置验证 |
| `prompt_toolkit` | 交互式输入 |
| `rich` | 终端美化 |
| `loguru` | 日志 |
| `mcp` | Model Context Protocol |
| `websockets` | WebSocket 支持 |
| `httpx` | HTTP 客户端 |

### 渠道依赖

- `dingtalk-stream` - 钉钉
- `python-telegram-bot` - Telegram
- `lark-oapi` - 飞书
- `slack-sdk` - Slack
- `python-socketio` - Matrix

---

## 开发相关

### 运行测试

```bash
pytest tests/
```

### 代码风格

```bash
ruff check nanobot/
```

### 构建发布

```bash
pip install build
python -m build
twine upload dist/*
```

---

## 参考链接

- GitHub: https://github.com/HKUDS/nanobot
- PyPI: https://pypi.org/project/nanobot-ai/
- 文档：项目 README.md

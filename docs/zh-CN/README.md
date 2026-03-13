<!--
来源：README.md
翻译日期：2026-03-13
-->

<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: 超轻量级个人 AI 助手</h1>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/Feishu-群聊-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="Feishu"></a>
    <a href="./COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-群聊-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-社区-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
</div>

🐈 **nanobot** 是一个受 [OpenClaw](https://github.com/openclaw/openclaw) 启发的**超轻量级**个人 AI 助手。

⚡️ 以比 OpenClaw **少 99% 的代码行数** 提供核心 agent 功能。

📏 实时代码行数：运行 `bash core_agent_lines.sh` 随时验证。

## 📢 动态

- **2026-03-08** 🚀 发布 **v0.1.4.post4** — 一个专注于可靠性的发布，包含更安全的默认设置、更好的多实例支持、更稳固的 MCP，以及主要的渠道和提供商改进。详情请见 [发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post4)。
- **2026-03-07** 🚀 Azure OpenAI 提供商、WhatsApp 媒体、QQ 群聊，以及更多 Telegram/飞书优化。
- **2026-03-06** 🪄 更轻量的提供商、更智能的媒体处理，以及更稳固的记忆和 CLI 兼容性。
- **2026-03-05** ⚡️ Telegram 草稿流式传输、MCP SSE 支持，以及更广泛的渠道可靠性修复。
- **2026-03-04** 🛠️ 依赖清理、更安全的文件读取，以及另一轮测试和 Cron 修复。
- **2026-03-03** 🧠 更清晰的用户消息合并、更安全的 multimodal 保存，以及更强的 Cron 保护。
- **2026-03-02** 🛡️ 更安全的默认访问控制、更稳固的 Cron 重载，以及更清晰的 Matrix 媒体处理。
- **2026-03-01** 🌐 Web 代理支持、更智能的 Cron 提醒，以及飞书富文本解析改进。
- **2026-02-28** 🚀 发布 **v0.1.4.post3** — 更清晰的上下文、更强化的会话历史，以及更智能的 agent。详情请见 [发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post3)。
- **2026-02-27** 🧠 实验性思考模式支持、钉钉媒体消息、飞书和 QQ 渠道修复。
- **2026-02-26** 🛡️ 会话中毒修复、WhatsApp 去重、Windows 路径保护、Mistral 兼容性。

<details>
<summary>更早的动态</summary>

- **2026-02-25** 🧹 新 Matrix 渠道、更清晰的会话上下文、自动工作区模板同步。
- **2026-02-24** 🚀 发布 **v0.1.4.post2** — 一个专注于可靠性发布的版本，重新设计的心跳、提示缓存优化，以及强化的提供商和渠道稳定性。详情请见 [发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post2)。
- **2026-02-23** 🔧 虚拟工具调用心跳、提示缓存优化、Slack mrkdwn 修复。
- **2026-02-22** 🛡️ Slack 主题隔离、Discord 打字修复、agent 可靠性改进。
- **2026-02-21** 🎉 发布 **v0.1.4.post1** — 新提供商、跨渠道媒体支持，以及重大稳定性改进。详情请见 [发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post1)。
- **2026-02-20** 🐦 飞书现在可以接收多模态文件。底层更可靠的记忆。
- **2026-02-19** ✨ Slack 现在发送文件、Discord 拆分长消息，子 agent 在 CLI 模式下工作。
- **2026-02-18** ⚡️ nanobot 现在支持 VolcEngine、MCP 自定义认证头，以及 Anthropic 提示缓存。
- **2026-02-17** 🎉 发布 **v0.1.4** — MCP 支持、进度流式传输、新提供商，以及多个渠道改进。详情请见 [发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4)。
- **2026-02-16** 🦞 nanobot 现在集成 [ClawHub](https://clawhub.ai) 技能 — 搜索和安装公共 agent 技能。
- **2026-02-15** 🔑 nanobot 现在支持 OpenAI Codex 提供商，支持 OAuth 登录。
- **2026-02-14** 🔌 nanobot 现在支持 MCP！详情请见 [MCP 部分](#mcp-模型上下文协议)。
- **2026-02-13** 🎉 发布 **v0.1.3.post7** — 包括安全性强化和多项改进。**请升级到最新版本以解决安全问题**。详情请见 [发布说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post7)。
- **2026-02-12** 🧠 重新设计的记忆系统 — 更少的代码，更可靠。加入 [讨论](https://github.com/HKUDS/nanobot/discussions/566)！
- **2026-02-11** ✨ 增强的 CLI 体验，添加 MiniMax 支持！
- **2026-02-10** 🎉 发布 **v0.1.3.post6** 带有改进！查看 [说明](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post6) 和我们的 [路线图](https://github.com/HKUDS/nanobot/discussions/431)。
- **2026-02-09** 💬 添加 Slack、Email 和 QQ 支持 — nanobot 现在支持多个聊天平台！
- **2026-02-08** 🔧 重构提供商 — 添加新 LLM 提供商现在只需 2 个简单步骤！查看 [这里](#providers)。
- **2026-02-07** 🚀 发布 **v0.1.3.post5** 带有 Qwen 支持和几项关键改进！详情见 [这里](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post5)。
- **2026-02-06** ✨ 添加 Moonshot/Kimi 提供商、Discord 集成，以及增强的安全性强化！
- **2026-02-05** ✨ 添加飞书渠道、DeepSeek 提供商，以及增强的定时任务支持！
- **2026-02-04** 🚀 发布 **v0.1.3.post4** 带有多提供商和 Docker 支持！详情见 [这里](https://github.com/HKUDS/nanobot/releases/tag/v0.1.3.post4)。
- **2026-02-03** ⚡ 集成 vLLM 以获取本地 LLM 支持，并改进自然语言任务调度！
- **2026-02-02** 🎉 nanobot 正式启动！欢迎尝试 🐈 nanobot！

</details>

## nanobot 的主要特点：

🪶 **超轻量级**: OpenClaw 的超轻量实现 — 小 99%，显著更快。

🔬 **适合研究**: 清晰、易读的代码，易于理解、修改和扩展用于研究。

⚡️ **闪电般快速**: 极少的占用意味着更快的启动、更低的资源使用和更快的迭代。

💎 **易于使用**: 一键部署，随时可用。

## 🏗️ 架构

<p align="center">
  <img src="nanobot_arch.png" alt="nanobot 架构" width="800">
</p>

## 目录

- [动态](#-动态)
- [主要特点](#nanobot-的主要特点)
- [架构](#️-架构)
- [功能](#-功能)
- [安装](#-安装)
- [快速开始](#-快速开始)
- [聊天应用](#-聊天应用)
- [Agent 社交网络](#-agent-社交网络)
- [配置](#️-配置)
- [多实例](#-多实例)
- [CLI 参考](#-cli-参考)
- [Docker](#-docker)
- [Linux 服务](#-linux-服务)
- [项目结构](#-项目结构)
- [贡献和路线图](#-贡献--路线图)
- [Star 历史](#-star-历史)

## ✨ 功能

<table align="center">
  <tr align="center">
    <th><p align="center">📈 24/7 实时市场分析</p></th>
    <th><p align="center">🚀 全栈软件工程师</p></th>
    <th><p align="center">📅 智能日常任务管理器</p></th>
    <th><p align="center">📚 个人知识助手</p></th>
  </tr>
  <tr>
    <td align="center"><p align="center"><img src="case/search.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/code.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/scedule.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="case/memory.gif" width="180" height="400"></p></td>
  </tr>
  <tr>
    <td align="center">发现 • 洞察 • 趋势</td>
    <td align="center">开发 • 部署 • 扩展</td>
    <td align="center">调度 • 自动化 • 组织</td>
    <td align="center">学习 • 记忆 • 推理</td>
  </tr>
</table>

## 📦 安装

**从源码安装**（最新功能，推荐用于开发）

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

**使用 [uv](https://github.com/astral-sh/uv) 安装**（稳定、快速）

```bash
uv tool install nanobot-ai
```

**从 PyPI 安装**（稳定）

```bash
pip install nanobot-ai
```

### 更新到最新版本

**PyPI / pip**

```bash
pip install -U nanobot-ai
nanobot --version
```

**uv**

```bash
uv tool upgrade nanobot-ai
nanobot --version
```

**使用 WhatsApp？** 升级后重新构建本地桥接服务：

```bash
rm -rf ~/.nanobot/bridge
nanobot channels login
```

## 🚀 快速开始

> [!TIP]
> 在 `~/.nanobot/config.json` 中设置你的 API 密钥。
> 获取 API 密钥：[OpenRouter](https://openrouter.ai/keys)（全球）· [Brave Search](https://brave.com/search/api/)（可选，用于网络搜索）

**1. 初始化**

```bash
nanobot onboard
```

**2. 配置** (`~/.nanobot/config.json`)

将这些**两部分**添加或合并到你的配置中（其他选项有默认值）。

*设置你的 API 密钥*（例如 OpenRouter，推荐全球用户使用）：
```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

*设置你的模型*（可选地锁定提供商 — 默认为自动检测）：
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

**3. 聊天**

```bash
nanobot agent
```

就是这样！你可以在 2 分钟内拥有一个可用的 AI 助手。

## 💬 聊天应用

将 nanobot 连接到你喜欢的聊天平台。

| 渠道 | 你需要的 |
|---------|---------------|
| **Telegram** | 来自 @BotFather 的 Bot 令牌 |
| **Discord** | Bot 令牌 + 消息内容意图 |
| **WhatsApp** | 二维码扫描 |
| **飞书** | App ID + App Secret |
| **Mochat** | Claw 令牌（自动设置可用） |
| **钉钉** | App Key + App Secret |
| **Slack** | Bot 令牌 + 应用级令牌 |
| **Email** | IMAP/SMTP 凭据 |
| **QQ** | App ID + App Secret |
| **企业微信** | Bot ID + Bot Secret |

（详细配置说明请参考英文原版 README.md）

## 🤖 Agent 社交网络

nanobot 支持 agent 之间的社交网络，允许多个 agent 相互交流和协作。

（详细内容请参考英文原版 README.md）

## ⚙️ 配置

nanobot 使用 `~/.nanobot/config.json` 进行配置。

（详细配置选项请参考英文原版 README.md）

## 🔄 多实例

nanobot 支持在同一台机器上运行多个实例，每个实例使用不同的配置和渠道。

（详细内容请参考英文原版 README.md）

## 🖥️ CLI 参考

nanobot 提供多个 CLI 命令：

- `nanobot onboard` - 初始化配置
- `nanobot agent` - 启动 agent
- `nanobot gateway` - 启动网关
- `nanobot channels` - 渠道管理
- `nanobot cron` - 定时任务管理

（详细命令说明请参考英文原版 README.md）

## 🐳 Docker

nanobot 可以通过 Docker 部署：

```bash
docker run -d \
  -v ~/.nanobot:/root/.nanobot \
  -e OPENROUTER_API_KEY=your_key \
  hkuds/nanobot:latest
```

（详细 Docker 部署说明请参考英文原版 README.md）

## 🐧 Linux 服务

在 Linux 上，你可以将 nanobot 注册为系统服务：

```bash
sudo systemctl edit --force nanobot
```

（详细系统服务配置说明请参考英文原版 README.md）

## 📁 项目结构

```
nanobot/
├── nanobot/             # 主程序包
│   ├── agent/          # AI Agent 核心
│   ├── channels/       # 聊天渠道
│   ├── providers/      # LLM 提供商
│   ├── bus/            # 消息总线
│   ├── config/         # 配置管理
│   ├── cron/           # 定时任务
│   ├── heartbeat/      # 心跳服务
│   ├── session/        # 会话管理
│   ├── cli/            # 命令行接口
│   ├── bridge/         # WhatsApp 桥接 (Node.js)
│   ├── templates/      # 模板文件
│   └── skills/         # 技能系统
├── docs/               # 文档
├── tests/              # 测试
└── scripts/            # 辅助脚本
```

## 🤝 贡献 & 路线图

欢迎贡献！请查看我们的 [贡献指南](https://github.com/HKUDS/nanobot/blob/main/CONTRIBUTING.md) 和 [路线图](https://github.com/HKUDS/nanobot/discussions/431)。

## ⭐ Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=HKUDS/nanobot&type=Date)](https://star-history.com/#HKUDS/nanobot&Date)

---

## English Original

For detailed configuration examples, complete feature descriptions, and the latest updates, please refer to the English original README.md:

```markdown
<div align="center">
  <img src="nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: Ultra-Lightweight Personal AI Assistant</h1>
  ...
```

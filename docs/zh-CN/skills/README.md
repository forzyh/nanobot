<!--
来源：nanobot/skills/README.md
翻译日期：2026-03-13
-->

# nanobot 技能

此目录包含扩展 nanobot 功能的内置技能。

## 技能格式

每个技能是一个目录，包含一个 `SKILL.md` 文件，其中有：
- YAML 前导元数据（名称、描述、元数据）
- Agent 的 Markdown 说明

## 归属

这些技能改编自 [OpenClaw](https://github.com/openclaw/openclaw) 的技能系统。
技能格式和元数据结构遵循 OpenClaw 的约定以保持兼容性。

## 可用技能

| 技能 | 描述 |
|-------|-------------|
| `github` | 使用 `gh` CLI 与 GitHub 交互 |
| `weather` | 使用 wttr.in 和 Open-Meteo 获取天气信息 |
| `summarize` | 总结 URL、文件和 YouTube 视频 |
| `tmux` | 远程控制 tmux 会话 |
| `clawhub` | 从 ClawHub 注册表搜索和安装技能 |
| `skill-creator` | 创建新技能 |

---

## 英文原版

```markdown
# nanobot Skills

This directory contains built-in skills that extend nanobot's capabilities.

## Skill Format

Each skill is a directory containing a `SKILL.md` file with:
- YAML frontmatter (name, description, metadata)
- Markdown instructions for the agent

## Attribution

These skills are adapted from [OpenClaw](https://github.com/openclaw/openclaw)'s skill system.
The skill format and metadata structure follow OpenClaw's conventions to maintain compatibility.

## Available Skills

| Skill | Description |
|-------|-------------|
| `github` | Interact with GitHub using the `gh` CLI |
| `weather` | Get weather info using wttr.in and Open-Meteo |
| `summarize` | Summarize URLs, files, and YouTube videos |
| `tmux` | Remote-control tmux sessions |
| `clawhub` | Search and install skills from ClawHub registry |
| `skill-creator` | Create new skills |
```

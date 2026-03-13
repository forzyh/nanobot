<!--
来源：nanobot/skills/clawhub/SKILL.md
翻译日期：2026-03-13
-->

---
name: clawhub
description: 从 ClawHub 搜索和安装 agent 技能，ClawHub 是公共技能注册表。
homepage: https://clawhub.ai
metadata: {"nanobot":{"emoji":"🦞"}}
---

# Clawhub

用于 AI agent 的公共技能注册表。支持自然语言搜索（向量搜索）。

## 何时使用

当用户要求以下任何内容时，使用此技能：
- "找一个...的技能"
- "搜索技能"
- "安装一个技能"
- "有哪些可用技能？"
- "更新我的技能"

## 搜索

```bash
npx --yes clawhub@latest search "web scraping" --limit 5
```

## 安装

```bash
npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace
```

将 `<slug>` 替换为搜索结果中的技能名称。这会将技能放置到 `~/.nanobot/workspace/skills/` 中，nanobot 从那里自动加载工作区技能。始终包含 `--workdir`。

## 更新

```bash
npx --yes clawhub@latest update --all --workdir ~/.nanobot/workspace
```

## 列出已安装

```bash
npx --yes clawhub@latest list --workdir ~/.nanobot/workspace
```

## 说明

- 需要 Node.js（`npx` 随 Node.js 一起提供）
- 搜索和安装无需 API 密钥
- 登录（`npx --yes clawhub@latest login`）仅在发布时需要
- `--workdir ~/.nanobot/workspace` 很关键 —— 没有它，技能会安装到当前目录而不是 nanobot 工作区
- 安装后，提醒用户启动新会话以加载技能

---

## 英文原版

```markdown
# Clawhub

Public skill registry for AI agents. Search by natural language (vector search).

## When to use

Use this skill when the user asks any of:
- "find a skill for …"
- "search for skills"
- "install a skill"
- "what skills are available?"
- "update my skills"

## Search

```bash
npx --yes clawhub@latest search "web scraping" --limit 5
```

## Install

```bash
npx --yes clawhub@latest install <slug> --workdir ~/.nanobot/workspace
```

Replace `<slug>` with the skill name from search results. This places the skill into `~/.nanobot/workspace/skills/`, where nanobot loads workspace skills from. Always include `--workdir`.

## Update

```bash
npx --yes clawhub@latest update --all --workdir ~/.nanobot/workspace
```

## List installed

```bash
npx --yes clawhub@latest list --workdir ~/.nanobot/workspace
```

## Notes

- Requires Node.js (`npx` comes with it).
- No API key needed for search and install.
- Login (`npx --yes clawhub@latest login`) is only required for publishing.
- `--workdir ~/.nanobot/workspace` is critical — without it, skills install to the current directory instead of the nanobot workspace.
- After install, remind the user to start a new session to load the skill.
```

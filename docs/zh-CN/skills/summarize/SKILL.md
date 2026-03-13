<!--
来源：nanobot/skills/summarize/SKILL.md
翻译日期：2026-03-13
-->

---
name: summarize
description: 总结或从 URL、播客和本地文件提取文本/转录（非常适合"转录这个 YouTube/视频"的回退方案）。
homepage: https://summarize.sh
metadata: {"nanobot":{"emoji":"🧾","requires":{"bins":["summarize"]},"install":[{"id":"brew","kind":"brew","formula":"steipete/tap/summarize","bins":["summarize"],"label":"Install summarize (brew)"}]}}
---

# Summarize

用于总结 URL、本地文件和 YouTube 链接的快速 CLI 工具。

## 何时使用（触发短语）

当用户要求以下任何内容时，立即使用此技能：
- "使用 summarize.sh"
- "这个链接/视频是关于什么的？"
- "总结这个 URL/文章"
- "转录这个 YouTube/视频"（尽最大努力提取转录；无需 `yt-dlp`）

## 快速开始

```bash
summarize "https://example.com" --model google/gemini-3-flash-preview
summarize "/path/to/file.pdf" --model google/gemini-3-flash-preview
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto
```

## YouTube：总结 vs 转录

尽最大努力转录（仅限 URL）：

```bash
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto --extract-only
```

如果用户要求转录但内容太大，首先返回一个紧凑的总结，然后询问要扩展哪个部分/时间范围。

## 模型 + 密钥

为你的提供商设置 API 密钥：
- OpenAI: `OPENAI_API_KEY`
- Anthropic: `ANTHROPIC_API_KEY`
- xAI: `XAI_API_KEY`
- Google: `GEMINI_API_KEY`（别名：`GOOGLE_GENERATIVE_AI_API_KEY`、`GOOGLE_API_KEY`）

如果未设置，默认模型为 `google/gemini-3-flash-preview`。

## 有用的标志

- `--length short|medium|long|xl|xxl|<chars>`
- `--max-output-tokens <count>`
- `--extract-only`（仅限 URL）
- `--json`（机器可读）
- `--firecrawl auto|off|always`（回退提取）
- `--youtube auto`（如果设置了 `APIFY_API_TOKEN`，使用 Apify 回退）

## 配置

可选配置文件：`~/.summarize/config.json`

```json
{ "model": "openai/gpt-5.2" }
```

可选服务：
- `FIRECRAWL_API_KEY` 用于被阻止的网站
- `APIFY_API_TOKEN` 用于 YouTube 回退

---

## 英文原版

```markdown
# Summarize

Fast CLI to summarize URLs, local files, and YouTube links.

## When to use (trigger phrases)

Use this skill immediately when the user asks any of:
- "use summarize.sh"
- "what's this link/video about?"
- "summarize this URL/article"
- "transcribe this YouTube/video" (best-effort transcript extraction; no `yt-dlp` needed)

## Quick start

```bash
summarize "https://example.com" --model google/gemini-3-flash-preview
summarize "/path/to/file.pdf" --model google/gemini-3-flash-preview
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto
```

## YouTube: summary vs transcript

Best-effort transcript (URLs only):

```bash
summarize "https://youtu.be/dQw4w9WgXcQ" --youtube auto --extract-only
```

If the user asked for a transcript but it's huge, return a tight summary first, then ask which section/time range to expand.

## Model + keys

Set the API key for your chosen provider:
- OpenAI: `OPENAI_API_KEY`
- Anthropic: `ANTHROPIC_API_KEY`
- xAI: `XAI_API_KEY`
- Google: `GEMINI_API_KEY` (aliases: `GOOGLE_GENERATIVE_AI_API_KEY`, `GOOGLE_API_KEY`)

Default model is `google/gemini-3-flash-preview` if none is set.

## Useful flags

- `--length short|medium|long|xl|xxl|<chars>`
- `--max-output-tokens <count>`
- `--extract-only` (URLs only)
- `--json` (machine readable)
- `--firecrawl auto|off|always` (fallback extraction)
- `--youtube auto` (Apify fallback if `APIFY_API_TOKEN` set)

## Config

Optional config file: `~/.summarize/config.json`

```json
{ "model": "openai/gpt-5.2" }
```

Optional services:
- `FIRECRAWL_API_KEY` for blocked sites
- `APIFY_API_TOKEN` for YouTube fallback
```

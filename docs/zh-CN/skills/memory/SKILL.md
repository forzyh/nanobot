<!--
来源：nanobot/skills/memory/SKILL.md
翻译日期：2026-03-13
-->

---
name: memory
description: 具有 grep 式检索的双层记忆系统。
always: true
---

# 记忆

## 结构

- `memory/MEMORY.md` — 长期事实（偏好设置、项目背景、关系）。始终加载到你的上下文中。
- `memory/HISTORY.md` — 追加式事件日志。不加载到上下文中。使用 grep 风格工具或内存过滤器搜索。每个条目以 [YYYY-MM-DD HH:MM] 开头。

## 搜索过去事件

根据文件大小选择搜索方法：

- 小的 `memory/HISTORY.md`：使用 `read_file`，然后在内存中搜索
- 大或长期存在的 `memory/HISTORY.md`：使用 `exec` 工具进行定向搜索

示例：
- **Linux/macOS：** `grep -i "keyword" memory/HISTORY.md`
- **Windows：** `findstr /i "keyword" memory\HISTORY.md`
- **跨平台 Python：** `python -c "from pathlib import Path; text = Path('memory/HISTORY.md').read_text(encoding='utf-8'); print('\n'.join([l for l in text.splitlines() if 'keyword' in l.lower()][-20:]))"`

对于大型历史文件，优先使用定向命令行搜索。

## 何时更新 MEMORY.md

使用 `edit_file` 或 `write_file` 立即写入重要事实：
- 用户偏好（"我喜欢深色模式"）
- 项目背景（"API 使用 OAuth2"）
- 关系（"Alice 是项目负责人"）

## 自动整合

当会话变大时，旧会话会自动总结并追加到 HISTORY.md。长期事实会提取到 MEMORY.md。你不需要管理这个。

---

## 英文原版

```markdown
# Memory

## Structure

- `memory/MEMORY.md` — Long-term facts (preferences, project context, relationships). Always loaded into your context.
- `memory/HISTORY.md` — Append-only event log. NOT loaded into context. Search it with grep-style tools or in-memory filters. Each entry starts with [YYYY-MM-DD HH:MM].

## Search Past Events

Choose the search method based on file size:

- Small `memory/HISTORY.md`: use `read_file`, then search in-memory
- Large or long-lived `memory/HISTORY.md`: use the `exec` tool for targeted search

Examples:
- **Linux/macOS:** `grep -i "keyword" memory/HISTORY.md`
- **Windows:** `findstr /i "keyword" memory\HISTORY.md`
- **Cross-platform Python:** `python -c "from pathlib import Path; text = Path('memory/HISTORY.md').read_text(encoding='utf-8'); print('\n'.join([l for l in text.splitlines() if 'keyword' in l.lower()][-20:]))"`

Prefer targeted command-line search for large history files.

## When to Update MEMORY.md

Write important facts immediately using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")

## Auto-consolidation

Old conversations are automatically summarized and appended to HISTORY.md when the session grows large. Long-term facts are extracted to MEMORY.md. You don't need to manage this.
```

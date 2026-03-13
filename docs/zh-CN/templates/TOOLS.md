<!--
来源：nanobot/templates/TOOLS.md
翻译日期：2026-03-13
-->

# 工具使用说明

工具签名将通过函数调用自动提供。
本文档记录了非显而易见的约束和使用模式。

## exec — 安全限制

- 命令有可配置的超时时间（默认 60 秒）
- 危险命令会被阻止（rm -rf、格式化、dd、关机等）
- 输出被截断为 10,000 个字符
- `restrictToWorkspace` 配置可以限制文件访问范围到工作区

## cron — 定时提醒

- 请参考 cron 技能获取使用说明。

---

## 英文原版

```markdown
# Tool Usage Notes

Tool signatures are provided automatically via function calling.
This file documents non-obvious constraints and usage patterns.

## exec — Safety Limits

- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- `restrictToWorkspace` config can limit file access to the workspace

## cron — Scheduled Reminders

- Please refer to cron skill for usage.
```

<!--
来源：nanobot/skills/cron/SKILL.md
翻译日期：2026-03-13
-->

---
name: cron
description: 设置提醒和周期性任务。
---

# Cron

使用 `cron` 工具来设置提醒或周期性任务。

## 三种模式

1. **提醒** - 消息直接发送给用户
2. **任务** - 消息是任务描述，agent 执行并发送结果
3. **一次性** - 在特定时间运行一次，然后自动删除

## 示例

固定提醒：
```
cron(action="add", message="该休息了！", every_seconds=1200)
```

动态任务（agent 每次执行）：
```
cron(action="add", message="检查 HKUDS/nanobot GitHub 星标数并报告", every_seconds=600)
```

一次性定时任务（从当前时间计算 ISO 日期时间）：
```
cron(action="add", message="提醒我开会", at="<ISO datetime>")
```

时区感知 cron：
```
cron(action="add", message="晨间站会", cron_expr="0 9 * * 1-5", tz="America/Vancouver")
```

列出/移除：
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## 时间表达式

| 用户说 | 参数 |
|-----------|------------|
| 每 20 分钟 | every_seconds: 1200 |
| 每小时 | every_seconds: 3600 |
| 每天早上 8 点 | cron_expr: "0 8 * * *" |
| 工作日下午 5 点 | cron_expr: "0 17 * * 1-5" |
| 温哥华时间每天早上 9 点 | cron_expr: "0 9 * * *", tz: "America/Vancouver" |
| 在特定时间 | at: ISO 日期时间字符串（从当前时间计算）|

## 时区

使用 `tz` 和 `cron_expr` 在特定 IANA 时区进行调度。如果没有 `tz`，使用服务器的本地时区。

---

## 英文原版

```markdown
# Cron

Use the `cron` tool to schedule reminders or recurring tasks.

## Three Modes

1. **Reminder** - message is sent directly to user
2. **Task** - message is a task description, agent executes and sends result
3. **One-time** - runs once at a specific time, then auto-deletes

## Examples

Fixed reminder:
```
cron(action="add", message="Time to take a break!", every_seconds=1200)
```

Dynamic task (agent executes each time):
```
cron(action="add", message="Check HKUDS/nanobot GitHub stars and report", every_seconds=600)
```

One-time scheduled task (compute ISO datetime from current time):
```
cron(action="add", message="Remind me about the meeting", at="<ISO datetime>")
```

Timezone-aware cron:
```
cron(action="add", message="Morning standup", cron_expr="0 9 * * 1-5", tz="America/Vancouver")
```

List/remove:
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## Time Expressions

| User says | Parameters |
|-----------|------------|
| every 20 minutes | every_seconds: 1200 |
| every hour | every_seconds: 3600 |
| every day at 8am | cron_expr: "0 8 * * *" |
| weekdays at 5pm | cron_expr: "0 17 * * 1-5" |
| 9am Vancouver time daily | cron_expr: "0 9 * * *", tz: "America/Vancouver" |
| at a specific time | at: ISO datetime string (compute from current time) |

## Timezone

Use `tz` with `cron_expr` to schedule in a specific IANA timezone. Without `tz`, the server's local timezone is used.
```

<!--
来源：nanobot/skills/github/SKILL.md
翻译日期：2026-03-13
-->

---
name: github
description: "使用 `gh` CLI 与 GitHub 交互。使用 `gh issue`、`gh pr`、`gh run` 和 `gh api` 处理 issue、PR、CI 运行和高级查询。"
metadata: {"nanobot":{"emoji":"🐙","requires":{"bins":["gh"]},"install":[{"id":"brew","kind":"brew","formula":"gh","bins":["gh"],"label":"Install GitHub CLI (brew)"},{"id":"apt","kind":"apt","package":"gh","bins":["gh"],"label":"Install GitHub CLI (apt)"}]}}
---

# GitHub 技能

使用 `gh` CLI 与 GitHub 交互。如果不在 git 目录中，始终指定 `--repo owner/repo`，或直接使用 URL。

## Pull Requests

检查 PR 的 CI 状态：
```bash
gh pr checks 55 --repo owner/repo
```

列出最近的工作流运行：
```bash
gh run list --repo owner/repo --limit 10
```

查看运行并查看哪些步骤失败：
```bash
gh run view <run-id> --repo owner/repo
```

仅查看失败步骤的日志：
```bash
gh run view <run-id> --repo owner/repo --log-failed
```

## API 高级查询

`gh api` 命令可用于访问其他子命令不可用的数据。

获取特定字段的 PR：
```bash
gh api repos/owner/repo/pulls/55 --jq '.title, .state, .user.login'
```

## JSON 输出

大多数命令支持 `--json` 获取结构化输出。你可以使用 `--jq` 进行过滤：

```bash
gh issue list --repo owner/repo --json number,title --jq '.[] | "\(.number): \(.title)"'
```

---

## 英文原版

```markdown
# GitHub Skill

Use the `gh` CLI to interact with GitHub. Always specify `--repo owner/repo` when not in a git directory, or use URLs directly.

## Pull Requests

Check CI status on a PR:
```bash
gh pr checks 55 --repo owner/repo
```

List recent workflow runs:
```bash
gh run list --repo owner/repo --limit 10
```

View a run and see which steps failed:
```bash
gh run view <run-id> --repo owner/repo
```

View logs for failed steps only:
```bash
gh run view <run-id> --repo owner/repo --log-failed
```

## API for Advanced Queries

The `gh api` command is useful for accessing data not available through other subcommands.

Get PR with specific fields:
```bash
gh api repos/owner/repo/pulls/55 --jq '.title, .state, .user.login'
```

## JSON Output

Most commands support `--json` for structured output.  You can use `--jq` to filter:

```bash
gh issue list --repo owner/repo --json number,title --jq '.[] | "\(.number): \(.title)"'
```
```

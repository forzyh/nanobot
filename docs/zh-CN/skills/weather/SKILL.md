<!--
来源：nanobot/skills/weather/SKILL.md
翻译日期：2026-03-13
-->

---
name: weather
description: 获取当前天气和预报（无需 API 密钥）。
homepage: https://wttr.in/:help
metadata: {"nanobot":{"emoji":"🌤️","requires":{"bins":["curl"]}}}
---

# 天气

两项免费服务，无需 API 密钥。

## wttr.in（主要）

快速一行命令：
```bash
curl -s "wttr.in/London?format=3"
# 输出：London: ⛅️ +8°C
```

紧凑格式：
```bash
curl -s "wttr.in/London?format=%l:+%c+%t+%h+%w"
# 输出：London: ⛅️ +8°C 71% ↙5km/h
```

完整预报：
```bash
curl -s "wttr.in/London?T"
```

格式代码：`%c` 天气状况 · `%t` 温度 · `%h` 湿度 · `%w` 风力 · `%l` 位置 · `%m` 月亮

提示：
- URL 编码空格：`wttr.in/New+York`
- 机场代码：`wttr.in/JFK`
- 单位：`?m`（公制）`?u`（美制）
- 仅限今天：`?1` · 仅限当前：`?0`
- PNG 格式：`curl -s "wttr.in/Berlin.png" -o /tmp/weather.png`

## Open-Meteo（备用，JSON）

免费，无需密钥，适合程序化使用：
```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.12&current_weather=true"
```

查找城市的坐标，然后查询。返回包含温度、风速、天气代码的 JSON。

文档：https://open-meteo.com/en/docs

---

## 英文原版

```markdown
# Weather

Two free services, no API keys needed.

## wttr.in (primary)

Quick one-liner:
```bash
curl -s "wttr.in/London?format=3"
# Output: London: ⛅️ +8°C
```

Compact format:
```bash
curl -s "wttr.in/London?format=%l:+%c+%t+%h+%w"
# Output: London: ⛅️ +8°C 71% ↙5km/h
```

Full forecast:
```bash
curl -s "wttr.in/London?T"
```

Format codes: `%c` condition · `%t` temp · `%h` humidity · `%w` wind · `%l` location · `%m` moon

Tips:
- URL-encode spaces: `wttr.in/New+York`
- Airport codes: `wttr.in/JFK`
- Units: `?m` (metric) `?u` (USCS)
- Today only: `?1` · Current only: `?0`
- PNG: `curl -s "wttr.in/Berlin.png" -o /tmp/weather.png`

## Open-Meteo (fallback, JSON)

Free, no key, good for programmatic use:
```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.12&current_weather=true"
```

Find coordinates for a city, then query. Returns JSON with temp, windspeed, weathercode.

Docs: https://open-meteo.com/en/docs
```

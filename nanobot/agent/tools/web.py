# =============================================================================
# nanobot Web 工具
# 文件路径：nanobot/agent/tools/web.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了两个 Web 相关的 Agent 工具：
# 1. WebSearchTool - 使用 Brave Search API 搜索网络
# 2. WebFetchTool - 抓取并提取 URL 内容（HTML → markdown/text）
#
# 什么是 WebSearchTool？
# --------------------
# WebSearchTool 使用 Brave Search API 进行网络搜索：
# - 返回搜索结果（标题、URL、摘要）
# - 支持自定义结果数量（1-10）
# - 需要配置 BRAVE_API_KEY
#
# 什么是 WebFetchTool？
# -------------------
# WebFetchTool 抓取 URL 并提取可读内容：
# - 使用 Readability 库提取主要内容
# - 支持 markdown 和 text 两种模式
# - 自动处理 HTML 标签和实体编码
# - 支持 JSON、HTML 等内容类型检测
#
# 安全机制：
# ---------
# 1. URL 验证：必须是 http/https 协议
# 2. 重定向限制：最多 5 次重定向（防止 DoS）
# 3. 输出截断：限制最大字符数（默认 50000）
# 4. 代理支持：可选配置 HTTP 代理
#
# 使用示例：
# --------
# # 搜索网络
# {"query": "Python 3.10 new features", "count": 5}
#
# # 抓取网页
# {"url": "https://example.com/article", "extractMode": "markdown"}
# =============================================================================

"""Web tools: web_search and web_fetch."""
# Web 工具：网络搜索和网页抓取

import html
import json
import os
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool

# 共享常量
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_2) AppleWebKit/537.36"  # 用户代理
MAX_REDIRECTS = 5  # 限制重定向次数，防止 DoS 攻击


def _strip_tags(text: str) -> str:
    """
    移除 HTML 标签并解码实体。

    处理流程：
    --------
    1. 移除 <script> 标签及其内容
    2. 移除 <style> 标签及其内容
    3. 移除所有其他 HTML 标签
    4. 解码 HTML 实体（如 &amp; → &）

    Args:
        text: HTML 文本

    Returns:
        str: 纯文本内容
    """
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.I)
    text = re.sub(r'<style[\s\S]*?</style>', '', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    return html.unescape(text).strip()


def _normalize(text: str) -> str:
    """
    规范化空白字符。

    处理流程：
    --------
    1. 将连续的空格/制表符替换为单个空格
    2. 将连续的 3 个以上换行替换为 2 个换行
    3. 去除首尾空白

    Args:
        text: 文本内容

    Returns:
        str: 规范化后的文本
    """
    text = re.sub(r'[ \t]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def _validate_url(url: str) -> tuple[bool, str]:
    """
    验证 URL：必须是 http(s) 协议且有有效域名。

    Args:
        url: 要验证的 URL

    Returns:
        tuple[bool, str]: (是否有效，错误消息)

    验证规则：
    --------
    1. 协议必须是 http 或 https
    2. 必须有有效的域名（netloc）
    """
    try:
        p = urlparse(url)
        if p.scheme not in ('http', 'https'):
            return False, f"Only http/https allowed, got '{p.scheme or 'none'}'"
        if not p.netloc:
            return False, "Missing domain"
        return True, ""
    except Exception as e:
        return False, str(e)


class WebSearchTool(Tool):
    """
    使用 Brave Search API 搜索网络的工具。

    这个工具让 Agent 能够：
    1. 搜索网络获取最新信息
    2. 返回搜索结果（标题、URL、摘要）
    3. 支持自定义结果数量（1-10）

    属性说明：
    --------
    name: str
        工具名称："web_search"

    description: str
        工具描述

    parameters: dict
        参数 schema：query（必填）、count（可选，1-10）

    _init_api_key: str | None
        初始化时传入的 API Key（优先使用）

    max_results: int
        默认返回结果数量，默认 5 条

    proxy: str | None
        HTTP 代理（可选）

    使用示例：
    --------
    >>> tool = WebSearchTool(max_results=5)
    >>> result = await tool.execute(query="Python 3.10 new features", count=3)
    >>> print(result)
    Results for: Python 3.10 new features

    1. Python 3.10 Features You Should Know
       https://example.com/python-310
       Learn about pattern matching, union types...
    """

    def __init__(self, api_key: str | None = None, max_results: int = 5, proxy: str | None = None):
        """
        初始化 WebSearchTool。

        Args:
            api_key: Brave Search API Key（可选，默认从环境变量读取）
            max_results: 默认返回结果数量，默认 5 条
            proxy: HTTP 代理（可选）
        """
        self._init_api_key = api_key  # 初始化时传入的 API Key
        self.max_results = max_results  # 默认结果数量
        self.proxy = proxy  # 代理

    @property
    def api_key(self) -> str:
        """
        获取 API Key（在调用时解析，以便获取环境变量/配置变更）。

        Returns:
            str: API Key 字符串
        """
        return self._init_api_key or os.environ.get("BRAVE_API_KEY", "")

    async def execute(self, query: str, count: int | None = None, **kwargs: Any) -> str:
        """
        执行网络搜索。

        Args:
            query: 搜索查询字符串
            count: 返回结果数量（可选，默认使用 max_results，范围 1-10）
            **kwargs: 其他参数

        Returns:
            str: 搜索结果或错误信息

        搜索流程：
        --------
        1. 检查 API Key 是否配置
        2. 限制结果数量在 1-10 范围内
        3. 发送 GET 请求到 Brave Search API
        4. 解析 JSON 响应，提取搜索结果
        5. 格式化输出（标题、URL、摘要）

        错误处理：
        --------
        - API Key 未配置：返回配置提示
        - ProxyError: 返回代理错误信息
        - 其他异常：返回错误信息
        """
        if not self.api_key:
            return (
                "Error: Brave Search API key not configured. Set it in "
                "~/.nanobot/config.json under tools.web.search.apiKey "
                "(or export BRAVE_API_KEY), then restart the gateway."
            )

        try:
            # 限制结果数量在 1-10 范围内
            n = min(max(count or self.max_results, 1), 10)
            logger.debug("WebSearch: {}", "proxy enabled" if self.proxy else "direct connection")
            async with httpx.AsyncClient(proxy=self.proxy) as client:
                r = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": n},
                    headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                    timeout=10.0
                )
                r.raise_for_status()

            # 提取搜索结果
            results = r.json().get("web", {}).get("results", [])[:n]
            if not results:
                return f"No results for: {query}"

            # 格式化输出
            lines = [f"Results for: {query}\n"]
            for i, item in enumerate(results, 1):
                lines.append(f"{i}. {item.get('title', '')}\n   {item.get('url', '')}")
                if desc := item.get("description"):
                    lines.append(f"   {desc}")
            return "\n".join(lines)
        except httpx.ProxyError as e:
            logger.error("WebSearch proxy error: {}", e)
            return f"Proxy error: {e}"
        except Exception as e:
            logger.error("WebSearch error: {}", e)
            return f"Error: {e}"


class WebFetchTool(Tool):
    """
    使用 Readability 抓取并提取 URL 内容的工具。

    这个工具让 Agent 能够：
    1. 抓取网页内容
    2. 提取可读内容（移除导航、广告等噪声）
    3. 支持 markdown 和 text 两种输出模式
    4. 自动检测内容类型（JSON、HTML、其他）

    属性说明：
    --------
    name: str
        工具名称："web_fetch"

    description: str
        工具描述

    parameters: dict
        参数 schema：url（必填）、extractMode（可选）、maxChars（可选）

    max_chars: int
        最大返回字符数，默认 50000

    proxy: str | None
        HTTP 代理（可选）

    使用示例：
    --------
    >>> tool = WebFetchTool(max_chars=50000)
    >>> result = await tool.execute(url="https://example.com/article", extractMode="markdown")
    >>> print(result)
    {"url": "...", "title": "...", "text": "...", ...}
    """

    name = "web_fetch"
    description = "Fetch URL and extract readable content (HTML → markdown/text)."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
            "extractMode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
            "maxChars": {"type": "integer", "minimum": 100}
        },
        "required": ["url"]
    }

    def __init__(self, max_chars: int = 50000, proxy: str | None = None):
        """
        初始化 WebFetchTool。

        Args:
            max_chars: 最大返回字符数，默认 50000
            proxy: HTTP 代理（可选）
        """
        self.max_chars = max_chars  # 最大字符数
        self.proxy = proxy  # 代理

    async def execute(self, url: str, extractMode: str = "markdown", maxChars: int | None = None, **kwargs: Any) -> str:
        """
        抓取并提取 URL 内容。

        Args:
            url: 要抓取的 URL
            extractMode: 提取模式（"markdown" 或 "text"），默认 "markdown"
            maxChars: 最大字符数（可选，默认使用初始化设置）
            **kwargs: 其他参数

        Returns:
            str: JSON 格式的结果（包含 url、finalUrl、status、extractor、text 等字段）

        抓取流程：
        --------
        1. URL 验证：检查协议和域名
        2. 发送 HTTP GET 请求（带 User-Agent）
        3. 检测内容类型：
           - application/json: 直接返回 JSON
           - text/html: 使用 Readability 提取
           - 其他：返回原始文本
        4. 提取主要内容（移除导航、广告等）
        5. 转换为 markdown 或纯文本
        6. 截断过长内容

        错误处理：
        --------
        - URL 验证失败：返回 JSON 错误
        - ProxyError: 返回代理错误
        - 其他异常：返回错误信息
        """
        from readability import Document

        max_chars = maxChars or self.max_chars
        is_valid, error_msg = _validate_url(url)
        if not is_valid:
            return json.dumps({"error": f"URL validation failed: {error_msg}", "url": url}, ensure_ascii=False)

        try:
            logger.debug("WebFetch: {}", "proxy enabled" if self.proxy else "direct connection")
            async with httpx.AsyncClient(
                follow_redirects=True,
                max_redirects=MAX_REDIRECTS,
                timeout=30.0,
                proxy=self.proxy,
            ) as client:
                r = await client.get(url, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()

            ctype = r.headers.get("content-type", "")

            if "application/json" in ctype:
                # JSON 内容：直接返回
                text, extractor = json.dumps(r.json(), indent=2, ensure_ascii=False), "json"
            elif "text/html" in ctype or r.text[:256].lower().startswith(("<!doctype", "<html")):
                # HTML 内容：使用 Readability 提取
                doc = Document(r.text)
                content = self._to_markdown(doc.summary()) if extractMode == "markdown" else _strip_tags(doc.summary())
                text = f"# {doc.title()}\n\n{content}" if doc.title() else content
                extractor = "readability"
            else:
                # 其他内容：返回原始文本
                text, extractor = r.text, "raw"

            # 截断过长内容
            truncated = len(text) > max_chars
            if truncated: text = text[:max_chars]

            return json.dumps({"url": url, "finalUrl": str(r.url), "status": r.status_code,
                              "extractor": extractor, "truncated": truncated, "length": len(text), "text": text}, ensure_ascii=False)
        except httpx.ProxyError as e:
            logger.error("WebFetch proxy error for {}: {}", url, e)
            return json.dumps({"error": f"Proxy error: {e}", "url": url}, ensure_ascii=False)
        except Exception as e:
            logger.error("WebFetch error for {}: {}", url, e)
            return json.dumps({"error": str(e), "url": url}, ensure_ascii=False)

    def _to_markdown(self, html: str) -> str:
        """
        将 HTML 转换为 markdown。

        转换规则：
        --------
        1. 链接：<a href="url">text</a> → [text](url)
        2. 标题：<h1-h6>text</h1-h6> → # text（根据级别）
        3. 列表项：<li>text</li> → - text
        4. 块级元素：</p|div|section|article> → 双换行
        5. 换行/分隔符：<br|hr> → 单换行

        Args:
            html: HTML 文本

        Returns:
            str: Markdown 格式文本
        """
        # 转换链接、标题、列表
        text = re.sub(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
                      lambda m: f'[{_strip_tags(m[2])}]({m[1]})', html, flags=re.I)
        text = re.sub(r'<h([1-6])[^>]*>([\s\S]*?)</h\1>',
                      lambda m: f'\n{"#" * int(m[1])} {_strip_tags(m[2])}\n', text, flags=re.I)
        text = re.sub(r'<li[^>]*>([\s\S]*?)</li>', lambda m: f'\n- {_strip_tags(m[1])}', text, flags=re.I)
        text = re.sub(r'</(p|div|section|article)>', '\n\n', text, flags=re.I)
        text = re.sub(r'<(br|hr)\s*/?>', '\n', text, flags=re.I)
        return _normalize(_strip_tags(text))

# =============================================================================
# nanobot CLI 命令行模块入口
# 文件路径：nanobot/cli/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这是 nanobot 命令行界面（CLI）模块的入口文件。
#
# 什么是 CLI？
# ----------
# CLI（Command Line Interface）是命令行界面，用户通过输入命令与程序交互。
# nanobot 提供了多种命令行命令：
#
# 可用命令：
# --------
# 1. nanobot onboard
#    初始化配置和工作空间（首次使用时运行）
#
# 2. nanobot agent [-m "消息"]
#    与 Agent 直接交互
#    -m 参数：发送单条消息
#    不加参数：进入交互模式
#
# 3. nanobot gateway
#    启动网关模式（服务器模式）
#    用于连接 Telegram、WhatsApp 等外部平台
#
# 4. nanobot status
#    显示 nanobot 状态（配置、模型、API 密钥等）
#
# 5. nanobot channels status
#    显示渠道状态（哪些渠道已启用）
#
# 6. nanobot channels login
#    通过二维码连接设备（WhatsApp）
#
# 7. nanobot provider login <provider>
#    使用 OAuth 认证登录提供商
#
# 使用示例：
# --------
# # 首次使用，初始化配置
# nanobot onboard
#
# # 与 Agent 对话
# nanobot agent -m "你好，请帮我写个 Python 文件"
#
# # 进入交互模式
# nanobot agent
#
# # 启动网关（连接 Telegram 等）
# nanobot gateway
# =============================================================================

"""CLI module for nanobot."""
# nanobot 的命令行界面模块

# =============================================================================
# nanobot 会话管理模块入口
# 文件路径：nanobot/session/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这是 nanobot 会话管理模块的入口文件，用于导出 Session 和 SessionManager 类。
#
# 什么是会话（Session）？
# --------------------
# 会话是 Agent 与用户之间的一次完整对话过程。
# 每次对话的历史记录都保存在会话中，让 Agent 能够：
# 1. 记住之前聊了什么（上下文）
# 2. 理解代词引用（"它"、"这个"指什么）
# 3. 保持对话连贯性
#
# 为什么需要会话管理？
# ------------------
# 1. 多用户支持：每个用户有独立的会话
# 2. 多渠道支持：Telegram、WhatsApp 等渠道的会话隔离
# 3. 持久化存储：会话数据保存到磁盘，重启后不丢失
# 4. 记忆管理：会话历史可以巩固为长期记忆
#
# 会话密钥（Session Key）：
# ---------------------
# 格式："{channel}:{chat_id}"
# 示例：
# - "telegram:123456" - Telegram 用户 123456
# - "whatsapp:+8613800138000" - WhatsApp 用户
# - "cli:direct" - 命令行交互
#
# 使用示例：
# --------
# from nanobot.session import SessionManager, Session
#
# # 创建会话管理器
# manager = SessionManager(workspace=Path("/workspace"))
#
# # 获取或创建会话
# session = manager.get_or_create("telegram:123456")
#
# # 添加消息到会话
# session.messages.append({"role": "user", "content": "Hello"})
#
# # 保存会话
# manager.save(session)
# =============================================================================

"""Session management module."""
# 会话管理模块：管理用户对话历史

from nanobot.session.manager import Session, SessionManager

__all__ = ["SessionManager", "Session"]

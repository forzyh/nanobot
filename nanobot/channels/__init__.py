# =============================================================================
# nanobot 聊天渠道模块入口
# 文件路径：nanobot/channels/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这是 nanobot 聊天渠道模块的入口文件，用于导出 BaseChannel 和 ChannelManager 类。
#
# 什么是渠道（Channel）？
# --------------------
# 渠道是 nanobot 与用户交互的平台，如：
# - Telegram: 流行的即时通讯软件
# - Discord: 游戏和社区聊天平台
# - WhatsApp: 全球最常用的通讯应用
# - 飞书（Feishu）: 企业协作平台
# - 钉钉（DingTalk）: 企业通讯应用
# - Slack: 团队协作工具
# - 微信（WeChat）: 通过 wechaty 支持
# - QQ: 腾讯 QQ
# - 邮件（Email）: 电子邮件
# - Matrix: 去中心化通讯协议
#
# 渠道模块的作用：
# --------------
# 1. 接收消息：从各平台接收用户消息
# 2. 发送消息：将 Agent 回复发送到各平台
# 3. 媒体处理：处理图片、音频、视频等媒体文件
# 4. 格式转换：将各平台的消息格式统一为标准格式
#
# 架构设计：
# ---------
#   Telegram  ─┐
#   Discord  ──┤
#   WhatsApp ──┼→ ChannelManager → MessageBus → Agent
#   Feishu  ───┤
#   ...       ─┘
#
# 使用示例：
# --------
# from nanobot.channels import ChannelManager, BaseChannel
#
# # 创建渠道管理器
# manager = ChannelManager(config, message_bus)
#
# # 启动所有已启用的渠道
# await manager.start_all()
#
# # 停止所有渠道
# await manager.stop_all()
# =============================================================================

"""Chat channels module with plugin architecture."""
# 聊天渠道模块：支持插件架构的多平台聊天集成

from nanobot.channels.base import BaseChannel
from nanobot.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]

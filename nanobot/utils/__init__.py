# =============================================================================
# nanobot 工具函数模块入口
# 文件路径：nanobot/utils/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这是 nanobot 工具函数模块的入口文件，导出常用的辅助函数。
#
# 什么是工具函数？
# --------------
# 工具函数是通用的、可复用的辅助函数，用于简化常见操作。
# 它们不是核心业务逻辑，但在多个地方都会用到。
#
# 导出的函数：
# ----------
# ensure_dir: 确保目录存在，不存在则创建
#
# 使用示例：
# --------
# from nanobot.utils import ensure_dir
#
# # 确保目录存在
# config_dir = ensure_dir(Path.home() / ".nanobot")
#
# # 等价于：
# # config_dir = Path.home() / ".nanobot"
# # if not config_dir.exists():
# #     config_dir.mkdir(parents=True, exist_ok=True)
# =============================================================================

"""Utility functions for nanobot."""
# nanobot 的工具函数模块

from nanobot.utils.helpers import ensure_dir

__all__ = ["ensure_dir"]

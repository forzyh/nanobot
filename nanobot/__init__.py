# =============================================================================
# nanobot 包入口文件
# 文件路径：nanobot/__init__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这是 Python 包的入口文件。当你导入 nanobot 包时，这个文件会首先被执行。
# 它定义了两个重要的全局变量：
# - __version__: 包的版本号
# - __logo__: 包的 logo（一个猫的 emoji）
#
# Python 包结构说明：
# ------------------
# 在 Python 中，一个目录要成为"包"（package），必须包含 __init__.py 文件。
# 当执行 import nanobot 时，Python 会：
# 1. 找到 nanobot 目录
# 2. 执行 nanobot/__init__.py
# 3. 让这个文件中定义的变量可以通过 nanobot.xxx 访问
#
# 例如：
#   from nanobot import __version__  # 导入版本号
#   from nanobot import __logo__     # 导入 logo
# =============================================================================

"""
nanobot - A lightweight AI agent framework
nanobot - 一个轻量级的 AI 代理框架
"""

# 版本号：使用语义化版本控制（Semantic Versioning）
# 格式：主版本号。次版本号。修订号。后版本号
# 0.1.4.post4 表示：
# - 0: 主版本号（重大变更）
# - 1: 次版本号（新功能）
# - 4: 修订号（bug 修复）
# - post4: 后发布版本 4（文档、配置等不影响代码的变更）
__version__ = "0.1.4.post4"

# Logo：使用 emoji 作为项目的视觉标识
# 🐈（猫）是 nanobot 的吉祥物
# 在命令行输出、日志、帮助信息中都会显示这个 logo
__logo__ = "🐈"

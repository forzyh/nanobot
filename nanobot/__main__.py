# =============================================================================
# nanobot 模块入口文件
# 文件路径：nanobot/__main__.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件让 nanobot 包可以像命令行程序一样运行：
#
#   python -m nanobot
#
# 当你在命令行中执行上面的命令时，Python 会：
# 1. 找到 nanobot 包
# 2. 查找 nanobot/__main__.py 文件
# 3. 执行这个文件中的代码
#
# 这种设计模式的好处：
# ------------------
# 1. 符合 Python 标准惯例
# 2. 用户不需要记住具体的命令行路径
# 3. 可以 pip install 后直接用 nanobot 命令运行
#
# 实际执行流程：
# ------------
# python -m nanobot
#     ↓
# 执行 nanobot/__main__.py
#     ↓
# 从 nanobot.cli.commands 导入 app
#     ↓
# 调用 app() 启动命令行程序
# =============================================================================

"""
Entry point for running nanobot as a module: python -m nanobot
作为模块运行 nanobot 的入口点：python -m nanobot
"""

# 从命令行模块导入应用实例
# nanobot.cli.commands 是命令行界面的主模块
# app 是 typer.Typer() 实例，是所有命令行命令的容器
from nanobot.cli.commands import app

# Python 入口判断
# if __name__ == "__main__": 的含义：
# - 当文件被直接运行时，__name__ 的值是 "__main__"
# - 当文件被导入时，__name__ 的值是文件名（不含.py）
#
# 这是一种 Python 惯用法，确保只有直接运行时才执行 app()
# 如果是被导入，则不会执行
if __name__ == "__main__":
    # 启动命令行应用
    # app() 会：
    # 1. 解析命令行参数（如 --help、--version、agent、gateway 等）
    # 2. 根据参数调用对应的命令函数
    # 3. 执行用户请求的操作
    app()

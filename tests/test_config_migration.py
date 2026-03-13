# =============================================================================
# nanobot 配置迁移测试
# 文件路径：tests/test_config_migration.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 nanobot 配置迁移功能的单元测试。
# 主要测试配置文件从旧版格式（memoryWindow）迁移到新版格式
# （contextWindowTokens）的功能。
#
# 测试的核心功能：
# -------------------------
# 1. 配置加载：测试旧版配置的加载和迁移
# 2. 配置保存：测试新版配置的保存格式
# 3. onboard 刷新：测试 onboard 命令对旧版配置的处理
#
# 关键测试场景：
# --------
# 1. 加载包含 memoryWindow 的旧版配置
#    - 验证 maxTokens 被保留
#    - 验证 memoryWindow 被转换为 contextWindowTokens
#    - 验证 should_warn_deprecated_memory_window 标志被设置
# 2. 保存配置
#    - 验证保存时使用 contextWindowTokens
#    - 验证不再保存 memoryWindow 字段
# 3. onboard 刷新旧版配置
#    - 验证用户选择保留配置时进行迁移
#    - 验证迁移后的配置格式正确
#
# 配置字段说明：
# --------
# - memoryWindow（旧版）：记忆窗口大小，表示保留多少轮对话
# - contextWindowTokens（新版）：上下文窗口令牌数，更精确地控制上下文大小
# - maxTokens：最大生成令牌数，控制单次响应的最大长度
#
# 使用示例：
# --------
# pytest tests/test_config_migration.py -v           # 运行所有测试
# pytest tests/test_config_migration.py::test_load_config_keeps_max_tokens_and_warns_on_legacy_memory_window -v
# =============================================================================

import json

from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.loader import load_config, save_config

runner = CliRunner()


def test_load_config_keeps_max_tokens_and_warns_on_legacy_memory_window(tmp_path) -> None:
    """测试加载包含 memoryWindow 的旧版配置。

    验证当配置文件中包含旧版 memoryWindow 字段时：
    1. maxTokens 值被正确保留
    2. contextWindowTokens 使用默认值（65,536）
    3. should_warn_deprecated_memory_window 标志被设置为 True，
       用于后续提示用户迁移配置
    """
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "maxTokens": 1234,
                        "memoryWindow": 42,  # 旧版字段
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.agents.defaults.max_tokens == 1234
    assert config.agents.defaults.context_window_tokens == 65_536  # 使用默认值
    assert config.agents.defaults.should_warn_deprecated_memory_window is True


def test_save_config_writes_context_window_tokens_but_not_memory_window(tmp_path) -> None:
    """测试保存配置时使用新版字段格式。

    验证 save_config 函数：
    1. 保留 maxTokens 字段
    2. 保存 contextWindowTokens 字段
    3. 不再保存旧版的 memoryWindow 字段
    """
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "maxTokens": 2222,
                        "memoryWindow": 30,  # 旧版字段
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    defaults = saved["agents"]["defaults"]

    assert defaults["maxTokens"] == 2222
    assert defaults["contextWindowTokens"] == 65_536
    assert "memoryWindow" not in defaults  # 旧版字段不应被保存


def test_onboard_refresh_rewrites_legacy_config_template(tmp_path, monkeypatch) -> None:
    """测试 onboard 刷新时重写旧版配置模板。

    验证当用户选择保留现有配置（输入"n"）时：
    1. onboard 命令执行配置迁移
    2. 迁移后的配置使用 contextWindowTokens 字段
    3. 迁移后的配置不再包含 memoryWindow 字段
    4. 原有的 maxTokens 值被保留
    """
    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "maxTokens": 3333,
                        "memoryWindow": 50,  # 旧版字段
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr("nanobot.cli.commands.get_workspace_path", lambda: workspace)

    result = runner.invoke(app, ["onboard"], input="n\n")  # 用户选择保留配置

    assert result.exit_code == 0
    assert "contextWindowTokens" in result.stdout  # 输出中提到新字段名
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    defaults = saved["agents"]["defaults"]
    assert defaults["maxTokens"] == 3333  # 原有值被保留
    assert defaults["contextWindowTokens"] == 65_536
    assert "memoryWindow" not in defaults  # 旧版字段被移除

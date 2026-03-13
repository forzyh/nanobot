# =============================================================================
# nanobot CLI 命令测试
# 文件路径：tests/test_commands.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件实现了对 nanobot 命令行接口（CLI）命令的单元测试。
# 主要测试 onboard、agent、gateway 等命令的功能和配置处理逻辑。
#
# 测试的核心功能：
# -------------------------
# 1. onboard 命令：初始化和配置 nanobot 环境
# 2. agent 命令：运行 Agent 循环处理用户请求
# 3. gateway 命令：启动网关服务
# 4. 配置加载和保存：测试配置的读写和迁移
# 5. 工作区路径处理：测试工作区路径的解析和覆盖
# 6. 提供商识别：测试不同模型前缀的自动识别
#
# 关键测试场景：
# --------
# 1. 全新安装的 onboard 流程
# 2. 已存在配置时的 onboard 流程（用户选择覆盖或保留）
# 3. 已存在工作区时的 onboard 流程（不重新创建但添加缺失模板）
# 4. 配置模型名称前缀识别（github-copilot、openai-codex、ollama 等）
# 5. agent 命令的配置和工作区路径处理
# 6. agent 命令的已弃用配置警告（memoryWindow -> contextWindowTokens）
# 7. gateway 命令的工作区和端口配置
# 8. gateway 命令的 cron 存储路径配置
#
# 使用示例：
# --------
# pytest tests/test_commands.py -v           # 运行所有测试
# pytest tests/test_commands.py::test_onboard_fresh_install -v  # 运行特定测试
# =============================================================================

import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from nanobot.cli.commands import app
from nanobot.config.schema import Config
from nanobot.providers.litellm_provider import LiteLLMProvider
from nanobot.providers.openai_codex_provider import _strip_model_prefix
from nanobot.providers.registry import find_by_model

runner = CliRunner()


class _StopGateway(RuntimeError):
    """自定义异常，用于在测试中停止 gateway 命令的执行。

    这个异常用于中断 gateway 的无限循环，方便测试验证。
    """
    pass


@pytest.fixture
def mock_paths():
    """模拟配置和工作区路径以实现测试隔离。

    这个 fixture 创建临时目录并模拟相关路径函数，
    确保测试不会修改真实的配置文件。

    Yields:
        tuple: (config_file, workspace_dir) 临时配置文件和工作区路径
    """
    with patch("nanobot.config.loader.get_config_path") as mock_cp, \
         patch("nanobot.config.loader.save_config") as mock_sc, \
         patch("nanobot.config.loader.load_config") as mock_lc, \
         patch("nanobot.cli.commands.get_workspace_path") as mock_ws:

        base_dir = Path("./test_onboard_data")
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir()

        config_file = base_dir / "config.json"
        workspace_dir = base_dir / "workspace"

        mock_cp.return_value = config_file
        mock_ws.return_value = workspace_dir
        mock_sc.side_effect = lambda config: config_file.write_text("{}")

        yield config_file, workspace_dir

        # 清理测试数据
        if base_dir.exists():
            shutil.rmtree(base_dir)


def test_onboard_fresh_install(mock_paths):
    """测试全新安装的 onboard 流程。

    验证当没有现有配置时，onboard 命令应该：
    1. 创建新的配置文件
    2. 创建工作区目录
    3. 创建必要的模板文件（AGENTS.md、MEMORY.md）
    """
    config_file, workspace_dir = mock_paths

    result = runner.invoke(app, ["onboard"])

    assert result.exit_code == 0
    assert "Created config" in result.stdout
    assert "Created workspace" in result.stdout
    assert "nanobot is ready" in result.stdout
    assert config_file.exists()
    assert (workspace_dir / "AGENTS.md").exists()
    assert (workspace_dir / "memory" / "MEMORY.md").exists()


def test_onboard_existing_config_refresh(mock_paths):
    """测试已存在配置时的 onboard 流程（用户选择保留）。

    验证当配置已存在且用户选择不覆盖时：
    1. 保留现有配置值
    2. 刷新配置（加载 - 合并 - 保存）
    3. 工作区模板仍然被创建
    """
    config_file, workspace_dir = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="n\n")  # 用户选择 n（不覆盖）

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "existing values preserved" in result.stdout
    assert workspace_dir.exists()
    assert (workspace_dir / "AGENTS.md").exists()


def test_onboard_existing_config_overwrite(mock_paths):
    """测试已存在配置时的 onboard 流程（用户选择覆盖）。

    验证当配置已存在且用户选择覆盖时：
    1. 配置被重置为默认值
    2. 工作区模板被创建
    """
    config_file, workspace_dir = mock_paths
    config_file.write_text('{"existing": true}')

    result = runner.invoke(app, ["onboard"], input="y\n")  # 用户选择 y（覆盖）

    assert result.exit_code == 0
    assert "Config already exists" in result.stdout
    assert "Config reset to defaults" in result.stdout
    assert workspace_dir.exists()


def test_onboard_existing_workspace_safe_create(mock_paths):
    """测试已存在工作区时的 onboard 流程。

    验证当工作区已存在时：
    1. 不重新创建工作区目录
    2. 仍然添加缺失的模板文件（AGENTS.md）
    """
    config_file, workspace_dir = mock_paths
    workspace_dir.mkdir(parents=True)
    config_file.write_text("{}")

    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    assert "Created workspace" not in result.stdout  # 不应重新创建工作区
    assert "Created AGENTS.md" in result.stdout  # 但应创建模板文件
    assert (workspace_dir / "AGENTS.md").exists()


def test_config_matches_github_copilot_codex_with_hyphen_prefix():
    """测试 GitHub Copilot Codex 模型名称识别（带连字符前缀）。

    验证配置能够正确识别 "github-copilot/gpt-5.3-codex" 格式的模型名称，
    并提取正确的提供商名称。
    """
    config = Config()
    config.agents.defaults.model = "github-copilot/gpt-5.3-codex"

    assert config.get_provider_name() == "github_copilot"


def test_config_matches_openai_codex_with_hyphen_prefix():
    """测试 OpenAI Codex 模型名称识别（带连字符前缀）。

    验证配置能够正确识别 "openai-codex/gpt-5.1-codex" 格式的模型名称。
    """
    config = Config()
    config.agents.defaults.model = "openai-codex/gpt-5.1-codex"

    assert config.get_provider_name() == "openai_codex"


def test_config_matches_explicit_ollama_prefix_without_api_key():
    """测试 Ollama 模型名称识别（无需 API 密钥）。

    验证配置能够正确识别 "ollama/llama3.2" 格式的模型名称，
    并使用默认的本地 API 地址。
    """
    config = Config()
    config.agents.defaults.model = "ollama/llama3.2"

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434"


def test_config_explicit_ollama_provider_uses_default_localhost_api_base():
    """测试显式指定 Ollama 提供商时使用默认本地 API 地址。

    验证当显式指定 provider="ollama" 时，自动使用默认的本地地址。
    """
    config = Config()
    config.agents.defaults.provider = "ollama"
    config.agents.defaults.model = "llama3.2"

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434"


def test_config_auto_detects_ollama_from_local_api_base():
    """测试从本地 API 地址自动识别 Ollama 提供商。

    验证当 provider="auto" 且配置了 Ollama 的默认地址时，
    系统能够自动识别为 Ollama 提供商。
    """
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "llama3.2"}},
            "providers": {"ollama": {"apiBase": "http://localhost:11434"}},
        }
    )

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434"


def test_config_prefers_ollama_over_vllm_when_both_local_providers_configured():
    """测试当同时配置 Ollama 和 vLLM 时优先选择 Ollama。

    验证当两个本地提供商都配置时，系统优先选择 Ollama。
    """
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "llama3.2"}},
            "providers": {
                "vllm": {"apiBase": "http://localhost:8000"},
                "ollama": {"apiBase": "http://localhost:11434"},
            },
        }
    )

    assert config.get_provider_name() == "ollama"
    assert config.get_api_base() == "http://localhost:11434"


def test_config_falls_back_to_vllm_when_ollama_not_configured():
    """测试当未配置 Ollama 时回退到 vLLM。

    验证当只有 vLLM 配置时，系统正确识别并使用 vLLM。
    """
    config = Config.model_validate(
        {
            "agents": {"defaults": {"provider": "auto", "model": "llama3.2"}},
            "providers": {
                "vllm": {"apiBase": "http://localhost:8000"},
            },
        }
    )

    assert config.get_provider_name() == "vllm"
    assert config.get_api_base() == "http://localhost:8000"


def test_find_by_model_prefers_explicit_prefix_over_generic_codex_keyword():
    """测试模型查找优先使用显式前缀而非通用 codex 关键字。

    验证 find_by_model 函数能够正确解析带显式前缀的模型名称。
    """
    spec = find_by_model("github-copilot/gpt-5.3-codex")

    assert spec is not None
    assert spec.name == "github_copilot"


def test_litellm_provider_canonicalizes_github_copilot_hyphen_prefix():
    """测试 LiteLLM 提供商规范化 GitHub Copilot 连字符前缀。

    验证 LiteLLMProvider 将连字符前缀转换为下划线前缀。
    """
    provider = LiteLLMProvider(default_model="github-copilot/gpt-5.3-codex")

    resolved = provider._resolve_model("github-copilot/gpt-5.3-codex")

    assert resolved == "github_copilot/gpt-5.3-codex"


def test_openai_codex_strip_prefix_supports_hyphen_and_underscore():
    """测试 OpenAI Codex 支持连字符和下划线前缀。

    验证 _strip_model_prefix 函数能够处理两种前缀格式。
    """
    assert _strip_model_prefix("openai-codex/gpt-5.1-codex") == "gpt-5.1-codex"
    assert _strip_model_prefix("openai_codex/gpt-5.1-codex") == "gpt-5.1-codex"


@pytest.fixture
def mock_agent_runtime(tmp_path):
    """模拟 agent 命令依赖以进行聚焦的 CLI 测试。

    这个 fixture 模拟 agent 命令运行时所需的依赖，
    包括配置、消息总线、AgentLoop 等，使测试能够专注于 CLI 逻辑。

    Args:
        tmp_path: pytest 提供的临时目录

    Yields:
        dict: 包含模拟对象的字典，供测试使用
    """
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "default-workspace")
    cron_dir = tmp_path / "data" / "cron"

    with patch("nanobot.config.loader.load_config", return_value=config) as mock_load_config, \
         patch("nanobot.config.paths.get_cron_dir", return_value=cron_dir), \
         patch("nanobot.cli.commands.sync_workspace_templates") as mock_sync_templates, \
         patch("nanobot.cli.commands._make_provider", return_value=object()), \
         patch("nanobot.cli.commands._print_agent_response") as mock_print_response, \
         patch("nanobot.bus.queue.MessageBus"), \
         patch("nanobot.cron.service.CronService"), \
         patch("nanobot.agent.loop.AgentLoop") as mock_agent_loop_cls:

        agent_loop = MagicMock()
        agent_loop.channels_config = None
        agent_loop.process_direct = AsyncMock(return_value="mock-response")
        agent_loop.close_mcp = AsyncMock(return_value=None)
        mock_agent_loop_cls.return_value = agent_loop

        yield {
            "config": config,
            "load_config": mock_load_config,
            "sync_templates": mock_sync_templates,
            "agent_loop_cls": mock_agent_loop_cls,
            "agent_loop": agent_loop,
            "print_response": mock_print_response,
        }


def test_agent_help_shows_workspace_and_config_options():
    """测试 agent 命令帮助显示工作区和配置选项。

    验证 agent 命令的帮助信息包含 --workspace 和 --config 选项。
    """
    result = runner.invoke(app, ["agent", "--help"])

    assert result.exit_code == 0
    assert "--workspace" in result.stdout
    assert "-w" in result.stdout
    assert "--config" in result.stdout
    assert "-c" in result.stdout


def test_agent_uses_default_config_when_no_workspace_or_config_flags(mock_agent_runtime):
    """测试在没有指定路径标志时使用默认配置。

    验证当没有传入 --workspace 或 --config 标志时，
    agent 命令使用默认配置路径和工作区。
    """
    result = runner.invoke(app, ["agent", "-m", "hello"])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (None,)  # 使用默认配置路径
    assert mock_agent_runtime["sync_templates"].call_args.args == (
        mock_agent_runtime["config"].workspace_path,
    )
    assert mock_agent_runtime["agent_loop_cls"].call_args.kwargs["workspace"] == (
        mock_agent_runtime["config"].workspace_path
    )
    mock_agent_runtime["agent_loop"].process_direct.assert_awaited_once()
    mock_agent_runtime["print_response"].assert_called_once_with("mock-response", render_markdown=True)


def test_agent_uses_explicit_config_path(mock_agent_runtime, tmp_path: Path):
    """测试使用显式配置路径。

    验证当传入 -c 标志时，agent 命令使用指定的配置文件路径。
    """
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}")

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (config_path.resolve(),)


def test_agent_config_sets_active_path(monkeypatch, tmp_path: Path) -> None:
    """测试配置设置活动路径。

    验证当传入配置文件路径时，set_config_path 被正确调用。
    """
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    seen: dict[str, Path] = {}

    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: config_file.parent / "cron")
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())
    monkeypatch.setattr("nanobot.cron.service.CronService", lambda _store: object())

    class _FakeAgentLoop:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def process_direct(self, *_args, **_kwargs) -> str:
            return "ok"

        async def close_mcp(self) -> None:
            return None

    monkeypatch.setattr("nanobot.agent.loop.AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr("nanobot.cli.commands._print_agent_response", lambda *_args, **_kwargs: None)

    result = runner.invoke(app, ["agent", "-m", "hello", "-c", str(config_file)])

    assert result.exit_code == 0
    assert seen["config_path"] == config_file.resolve()


def test_agent_overrides_workspace_path(mock_agent_runtime):
    """测试 agent 命令覆盖工作区路径。

    验证当传入 -w 标志时，agent 命令使用指定的工作区路径。
    """
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(app, ["agent", "-m", "hello", "-w", str(workspace_path)])

    assert result.exit_code == 0
    assert mock_agent_runtime["config"].agents.defaults.workspace == str(workspace_path)
    assert mock_agent_runtime["sync_templates"].call_args.args == (workspace_path,)
    assert mock_agent_runtime["agent_loop_cls"].call_args.kwargs["workspace"] == workspace_path


def test_agent_workspace_override_wins_over_config_workspace(mock_agent_runtime, tmp_path: Path):
    """测试工作区命令行覆盖优先于配置文件。

    验证当同时指定配置文件和工作区标志时，
    命令行工作区标志优先于配置文件中的设置。
    """
    config_path = tmp_path / "agent-config.json"
    config_path.write_text("{}")
    workspace_path = Path("/tmp/agent-workspace")

    result = runner.invoke(
        app,
        ["agent", "-m", "hello", "-c", str(config_path), "-w", str(workspace_path)],
    )

    assert result.exit_code == 0
    assert mock_agent_runtime["load_config"].call_args.args == (config_path.resolve(),)
    assert mock_agent_runtime["config"].agents.defaults.workspace == str(workspace_path)
    assert mock_agent_runtime["sync_templates"].call_args.args == (workspace_path,)
    assert mock_agent_runtime["agent_loop_cls"].call_args.kwargs["workspace"] == workspace_path


def test_agent_warns_about_deprecated_memory_window(mock_agent_runtime):
    """测试 agent 命令对已弃用 memory_window 配置的警告。

    验证当配置使用旧版 memoryWindow 时，
    系统提示用户迁移到 contextWindowTokens。
    """
    mock_agent_runtime["config"].agents.defaults.memory_window = 100

    result = runner.invoke(app, ["agent", "-m", "hello"])

    assert result.exit_code == 0
    assert "memoryWindow" in result.stdout
    assert "contextWindowTokens" in result.stdout


def test_gateway_uses_workspace_from_config_by_default(monkeypatch, tmp_path: Path) -> None:
    """测试 gateway 默认使用配置中的工作区路径。

    验证 gateway 命令在没有指定 --workspace 标志时，
    使用配置文件中定义的工作区路径。
    """
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    seen: dict[str, Path] = {}

    monkeypatch.setattr(
        "nanobot.config.loader.set_config_path",
        lambda path: seen.__setitem__("config_path", path),
    )
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr(
        "nanobot.cli.commands.sync_workspace_templates",
        lambda path: seen.__setitem__("workspace", path),
    )
    monkeypatch.setattr(
        "nanobot.cli.commands._make_provider",
        lambda _config: (_ for _ in ()).throw(_StopGateway("stop")),
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGateway)
    assert seen["config_path"] == config_file.resolve()
    assert seen["workspace"] == Path(config.agents.defaults.workspace)


def test_gateway_workspace_option_overrides_config(monkeypatch, tmp_path: Path) -> None:
    """测试 gateway 命令行工作区覆盖配置文件设置。

    验证当传入 --workspace 标志时，gateway 命令使用该路径
    而不是配置文件中的路径。
    """
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    override = tmp_path / "override-workspace"
    seen: dict[str, Path] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr(
        "nanobot.cli.commands.sync_workspace_templates",
        lambda path: seen.__setitem__("workspace", path),
    )
    monkeypatch.setattr(
        "nanobot.cli.commands._make_provider",
        lambda _config: (_ for _ in ()).throw(_StopGateway("stop")),
    )

    result = runner.invoke(
        app,
        ["gateway", "--config", str(config_file), "--workspace", str(override)],
    )

    assert isinstance(result.exception, _StopGateway)
    assert seen["workspace"] == override
    assert config.workspace_path == override


def test_gateway_warns_about_deprecated_memory_window(monkeypatch, tmp_path: Path) -> None:
    """测试 gateway 命令对已弃用 memory_window 配置的警告。

    验证当配置使用旧版 memoryWindow 时，
    gateway 命令提示用户迁移到 contextWindowTokens。
    """
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.memory_window = 100

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr(
        "nanobot.cli.commands._make_provider",
        lambda _config: (_ for _ in ()).throw(_StopGateway("stop")),
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGateway)
    assert "memoryWindow" in result.stdout
    assert "contextWindowTokens" in result.stdout

def test_gateway_uses_config_directory_for_cron_store(monkeypatch, tmp_path: Path) -> None:
    """测试 gateway 使用配置目录存储 cron 任务。

    验证 gateway 命令的 cron 服务使用配置目录下的 cron 子目录
    作为任务存储路径。
    """
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "config-workspace")
    seen: dict[str, Path] = {}

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.config.paths.get_cron_dir", lambda: config_file.parent / "cron")
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr("nanobot.cli.commands._make_provider", lambda _config: object())
    monkeypatch.setattr("nanobot.bus.queue.MessageBus", lambda: object())
    monkeypatch.setattr("nanobot.session.manager.SessionManager", lambda _workspace: object())

    class _StopCron:
        def __init__(self, store_path: Path) -> None:
            seen["cron_store"] = store_path
            raise _StopGateway("stop")

    monkeypatch.setattr("nanobot.cron.service.CronService", _StopCron)

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGateway)
    assert seen["cron_store"] == config_file.parent / "cron" / "jobs.json"


def test_gateway_uses_configured_port_when_cli_flag_is_missing(monkeypatch, tmp_path: Path) -> None:
    """测试 gateway 在没有 CLI 标志时使用配置中的端口。

    验证当没有传入 --port 标志时，gateway 命令使用配置文件中定义的端口。
    """
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.gateway.port = 18791

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr(
        "nanobot.cli.commands._make_provider",
        lambda _config: (_ for _ in ()).throw(_StopGateway("stop")),
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file)])

    assert isinstance(result.exception, _StopGateway)
    assert "port 18791" in result.stdout


def test_gateway_cli_port_overrides_configured_port(monkeypatch, tmp_path: Path) -> None:
    """测试 gateway 命令行端口覆盖配置文件设置。

    验证当传入 --port 标志时，gateway 命令使用该端口
    而不是配置文件中的端口。
    """
    config_file = tmp_path / "instance" / "config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}")

    config = Config()
    config.gateway.port = 18791

    monkeypatch.setattr("nanobot.config.loader.set_config_path", lambda _path: None)
    monkeypatch.setattr("nanobot.config.loader.load_config", lambda _path=None: config)
    monkeypatch.setattr("nanobot.cli.commands.sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr(
        "nanobot.cli.commands._make_provider",
        lambda _config: (_ for _ in ()).throw(_StopGateway("stop")),
    )

    result = runner.invoke(app, ["gateway", "--config", str(config_file), "--port", "18792"])

    assert isinstance(result.exception, _StopGateway)
    assert "port 18792" in result.stdout

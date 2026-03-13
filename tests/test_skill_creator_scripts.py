# =============================================================================
# nanobot 技能创建器脚本测试
# 文件路径：tests/test_skill_creator_scripts.py
#
# 这个文件的作用是什么？
# -------------------------
# 这个文件测试了技能创建器（skill-creator）的三个核心脚本功能：
# 1. init_skill - 初始化技能目录结构
# 2. package_skill - 打包技能为 .skill 归档文件
# 3. quick_validate - 验证技能目录是否符合规范
#
# 测试的核心功能：
# -------------------------
# - 测试 init_skill 脚本能否正确创建技能目录和必需文件
# - 测试 quick_validate 脚本能否正确验证技能描述、拒绝占位符内容
# - 测试 quick_validate 脚本能否拒绝根目录下的非法文件
# - 测试 package_skill 脚本能否正确打包技能为 .skill 文件
# - 测试 package_skill 脚本能否检测并拒绝符号链接（安全考虑）
#
# 关键测试场景：
# -------------------------
# 1. 正常场景：创建技能目录并验证文件结构
# 2. 正常场景：验证有效的技能创建器目录
# 3. 异常场景：拒绝包含 TODO 占位符描述的 skill
# 4. 异常场景：拒绝根目录包含不允许文件的 skill
# 5. 正常场景：打包技能并验证归档内容
# 6. 安全场景：拒绝包含符号链接的技能（防止目录遍历攻击）
#
# 使用示例：
# -------------------------
# 运行测试：pytest tests/test_skill_creator_scripts.py -v
#
# 相关模块：
# - nanobot/skills/skill-creator/scripts/init_skill.py
# - nanobot/skills/skill-creator/scripts/package_skill.py
# - nanobot/skills/skill-creator/scripts/quick_validate.py
# =============================================================================

import importlib
import shutil
import sys
import zipfile
from pathlib import Path


# 设置脚本目录路径，将技能创建器脚本目录添加到 Python 路径
# 这样可以导入 init_skill、package_skill、quick_validate 模块
SCRIPT_DIR = Path("nanobot/skills/skill-creator/scripts").resolve()
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# 导入技能创建器的三个核心脚本模块
init_skill = importlib.import_module("init_skill")
package_skill = importlib.import_module("package_skill")
quick_validate = importlib.import_module("quick_validate")


def test_init_skill_creates_expected_files(tmp_path: Path) -> None:
    """
    测试 init_skill 函数能否正确创建技能目录和预期文件

    验证点：
    - 技能目录路径正确
    - SKILL.md 描述文件存在
    - scripts/example.py 示例脚本存在
    - references/api_reference.md 参考文档存在
    - assets/example_asset.txt 示例资源文件存在
    """
    # 调用 init_skill 创建 demo-skill，包含 scripts、references、assets 三个子目录
    skill_dir = init_skill.init_skill(
        "demo-skill",
        tmp_path,
        ["scripts", "references", "assets"],
        include_examples=True,
    )

    # 验证技能目录路径正确
    assert skill_dir == tmp_path / "demo-skill"
    # 验证 SKILL.md 描述文件存在
    assert (skill_dir / "SKILL.md").exists()
    # 验证 scripts 目录下的示例脚本存在
    assert (skill_dir / "scripts" / "example.py").exists()
    # 验证 references 目录下的 API 参考文档存在
    assert (skill_dir / "references" / "api_reference.md").exists()
    # 验证 assets 目录下的示例资源文件存在
    assert (skill_dir / "assets" / "example_asset.txt").exists()


def test_validate_skill_accepts_existing_skill_creator() -> None:
    """
    测试 validate_skill 函数能够接受有效的技能目录

    验证点：
    - nanobot/skills/skill-creator 目录本身是一个有效的技能
    - 验证函数返回 valid=True
    """
    # 验证现有的技能创建器目录（它本身就是一个有效的技能）
    valid, message = quick_validate.validate_skill(
        Path("nanobot/skills/skill-creator").resolve()
    )

    # 验证应该通过
    assert valid, message


def test_validate_skill_rejects_placeholder_description(tmp_path: Path) -> None:
    """
    测试 validate_skill 函数能够拒绝包含占位符描述的技能

    验证点：
    - 当 SKILL.md 中的 description 字段包含 "[TODO: fill me in]" 时
    - 验证函数应返回 valid=False
    - 错误消息应包含 "TODO placeholder"
    """
    # 创建一个临时技能目录
    skill_dir = tmp_path / "placeholder-skill"
    skill_dir.mkdir()
    # 创建包含占位符描述的 SKILL.md 文件
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: placeholder-skill\n"
        'description: "[TODO: fill me in]"\n'  # 占位符描述
        "---\n"
        "# Placeholder\n",
        encoding="utf-8",
    )

    # 验证应该失败，因为描述包含 TODO 占位符
    valid, message = quick_validate.validate_skill(skill_dir)

    # 验证不通过
    assert not valid
    # 错误消息应提示 TODO 占位符问题
    assert "TODO placeholder" in message


def test_validate_skill_rejects_root_files_outside_allowed_dirs(tmp_path: Path) -> None:
    """
    测试 validate_skill 函数能够拒绝根目录包含非法文件的技能

    验证点：
    - 技能根目录只允许特定的文件和目录（SKILL.md、scripts、references、assets 等）
    - 当根目录包含 README.md 等不允许的文件时
    - 验证函数应返回 valid=False
    - 错误消息应包含 "Unexpected file or directory in skill root"
    """
    # 创建一个临时技能目录
    skill_dir = tmp_path / "bad-root-skill"
    skill_dir.mkdir()
    # 创建有效的 SKILL.md 文件
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: bad-root-skill\n"
        "description: Valid description\n"
        "---\n"
        "# Skill\n",
        encoding="utf-8",
    )
    # 在根目录创建不允许的 README.md 文件
    (skill_dir / "README.md").write_text("extra\n", encoding="utf-8")

    # 验证应该失败，因为根目录包含不允许的文件
    valid, message = quick_validate.validate_skill(skill_dir)

    # 验证不通过
    assert not valid
    # 错误消息应提示根目录包含意外文件
    assert "Unexpected file or directory in skill root" in message


def test_package_skill_creates_archive(tmp_path: Path) -> None:
    """
    测试 package_skill 函数能否正确打包技能为 .skill 归档文件

    验证点：
    - 归档文件路径正确（.skill 扩展名）
    - 归档文件存在
    - 归档包含 SKILL.md 文件
    - 归档包含 scripts 目录下的文件
    """
    # 创建技能目录
    skill_dir = tmp_path / "package-me"
    skill_dir.mkdir()
    # 创建 SKILL.md 文件
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: package-me\n"
        "description: Package this skill.\n"
        "---\n"
        "# Skill\n",
        encoding="utf-8",
    )
    # 创建 scripts 目录和脚本文件
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "helper.py").write_text("print('ok')\n", encoding="utf-8")

    # 打包技能到 dist 目录
    archive_path = package_skill.package_skill(skill_dir, tmp_path / "dist")

    # 验证归档文件路径正确
    assert archive_path == (tmp_path / "dist" / "package-me.skill")
    # 验证归档文件存在
    assert archive_path.exists()
    # 验证归档内容
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = set(archive.namelist())
    # 验证 SKILL.md 在归档中
    assert "package-me/SKILL.md" in names
    # 验证脚本文件在归档中
    assert "package-me/scripts/helper.py" in names


def test_package_skill_rejects_symlink(tmp_path: Path) -> None:
    """
    测试 package_skill 函数能够拒绝包含符号链接的技能（安全特性）

    验证点：
    - 符号链接可能导致目录遍历攻击
    - 当技能目录包含符号链接时
    - 打包函数应返回 None
    - 不应生成 .skill 文件
    """
    # 创建技能目录
    skill_dir = tmp_path / "symlink-skill"
    skill_dir.mkdir()
    # 创建 SKILL.md 文件
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: symlink-skill\n"
        "description: Reject symlinks during packaging.\n"
        "---\n"
        "# Skill\n",
        encoding="utf-8",
    )
    # 创建 scripts 目录
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir()
    # 在技能目录外创建一个目标文件
    target = tmp_path / "outside.txt"
    target.write_text("secret\n", encoding="utf-8")
    # 创建指向技能目录外文件的符号链接
    link = scripts_dir / "outside.txt"

    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        # 如果系统不支持符号链接，跳过测试
        return

    # 打包应该失败，因为包含符号链接
    archive_path = package_skill.package_skill(skill_dir, tmp_path / "dist")

    # 验证打包函数返回 None
    assert archive_path is None
    # 验证没有生成 .skill 文件
    assert not (tmp_path / "dist" / "symlink-skill.skill").exists()

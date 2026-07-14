"""
扩展打包系统 — .pycoder-ext 格式

类似 VS Code 的 .vsix 格式。

.pycoder-ext 是 zip 格式，包含:
  extension/
    manifest.json       ← 必填: 扩展元数据
    extension.py        ← 必填: 扩展代码
    config.json         ← 可选: 默认配置
    assets/             ← 可选: 图标等资源
    README.md           ← 可选
    CHANGELOG.md        ← 可选

打包: pack(source_dir) → .pycoder-ext
解包: unpack(archive, target_dir)
验证: validate(manifest) → errors[]
发布: 生成发布 zip 供 GitHub/市场使用
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 打包格式常量 ──

PACKAGE_EXT = ".pycoder-ext"
MANIFEST_FILE = "manifest.json"
MAIN_FILE = "extension.py"
REQUIRED_FILES = {MANIFEST_FILE, MAIN_FILE}
OPTIONAL_FILES = {"config.json", "README.md", "CHANGELOG.md", "icon.png", "icon.svg"}
ASSETS_DIR = "assets"

# ── Manifest Schema 校验 ──

MANIFEST_SCHEMA = {
    "required": ["id", "name", "version", "description", "author"],
    "optional": [
        "publisher",
        "license",
        "homepage",
        "repository",
        "categories",
        "tags",
        "icon",
        "activationEvents",
        "contributes",
        "engines",
        "extensionDependencies",
        "capabilities",
        "badges",
        "markdown",
    ],
}


def validate_manifest(manifest: dict) -> list[str]:
    """验证扩展 manifest 的合法性，返回错误列表"""
    errors = []

    # 必填字段
    for field in MANIFEST_SCHEMA["required"]:
        if field not in manifest or not manifest[field]:
            errors.append(f"缺少必填字段: {field}")

    # ID 格式: publisher.name
    ext_id = manifest.get("id", "")
    if ext_id and ("." not in ext_id or " " in ext_id):
        errors.append(f"扩展 ID 格式无效: '{ext_id}' (需要 publisher.name 格式)")

    # 版本号格式
    version = manifest.get("version", "")
    if version and not _is_valid_version(version):
        errors.append(f"版本号格式无效: '{version}' (需要 semver，如 1.0.0)")

    # engines 校验
    engines = manifest.get("engines", {})
    if engines and "pycoder" not in engines:
        errors.append("engines 中缺少 pycoder 版本声明")

    # activationEvents 格式
    activation_events = manifest.get("activationEvents", [])
    if isinstance(activation_events, list):
        valid_prefixes = ("onCommand:", "onLanguage:", "onView:", "onStartupFinished", "*")
        for event in activation_events:
            if not any(event.startswith(p) for p in valid_prefixes):
                errors.append(f"无效的 activationEvent: '{event}'")

    # contributes 校验
    contributes = manifest.get("contributes", {})
    if contributes:
        if not isinstance(contributes, dict):
            errors.append("contributes 必须是对象")
        else:
            # commands
            for cmd in contributes.get("commands", []):
                if "command" not in cmd:
                    errors.append("contributes.commands 中的项目缺少 'command' 字段")
                if "title" not in cmd:
                    errors.append("contributes.commands 中的项目缺少 'title' 字段")

    return errors


def _is_valid_version(version: str) -> bool:
    """简易 semver 校验"""
    import re

    return bool(re.match(r"^\d+\.\d+\.\d+", version))


# ── 打包 ──


def pack(source_dir: str | Path, output_path: str | Path | None = None) -> str:
    """
    打包扩展目录为 .pycoder-ext 文件。

    Args:
        source_dir: 包含 extension/ 子目录的源目录
        output_path: 输出路径（可选，默认在源目录同级生成）

    Returns:
        生成的 .pycoder-ext 文件路径
    """
    source = Path(source_dir)
    if not source.is_dir():
        raise NotADirectoryError(f"源目录不存在: {source}")

    # 检查 extension 子目录 或 直接在源目录下
    ext_dir = source / "extension"
    if not ext_dir.exists():
        ext_dir = source  # 直接使用源目录

    # 校验必需文件
    manifest_file = ext_dir / MANIFEST_FILE
    if not manifest_file.exists():
        raise FileNotFoundError(f"缺少 {MANIFEST_FILE}")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    errors = validate_manifest(manifest)
    if errors:
        sep = "\n  "
        raise ValueError(f"Manifest 校验失败:\n  {sep.join(errors)}")

    # 确定输出路径
    if output_path is None:
        ext_id = manifest.get("id", ext_dir.name)
        version = manifest.get("version", "0.0.0")
        output_path = source.parent / f"{ext_id}-{version}{PACKAGE_EXT}"
    output = Path(output_path)

    # 打包为 zip
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in ext_dir.rglob("*"):
            if file_path.is_file():
                arcname = str(file_path.relative_to(ext_dir))
                zf.write(file_path, arcname)

    logger.info("extension_packed output=%s size=%d bytes", output, output.stat().st_size)
    return str(output)


# ── 解包 ──


def unpack(archive: str | Path, target_dir: str | Path | None = None) -> str:
    """
    解包 .pycoder-ext 文件到目标目录。

    Args:
        archive: .pycoder-ext 文件路径
        target_dir: 目标目录（可选，默认在扩展目录下）

    Returns:
        解包后的目录路径
    """
    archive_path = Path(archive)
    if not archive_path.exists():
        raise FileNotFoundError(f"打包文件不存在: {archive}")

    # 读取 manifest 以获取 ext_id
    manifest_data = None
    with zipfile.ZipFile(archive_path, "r") as zf:
        if MANIFEST_FILE in zf.namelist():
            manifest_data = json.loads(zf.read(MANIFEST_FILE).decode("utf-8"))

    ext_id = manifest_data.get("id", archive_path.stem) if manifest_data else archive_path.stem

    # 目标目录
    if target_dir is None:
        from pycoder.extensions.manager import EXTENSIONS_DIR

        target_dir = EXTENSIONS_DIR / ext_id.replace("/", "_")
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    # 解包
    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(target)

    logger.info("extension_unpacked ext=%s target=%s", ext_id, target)
    return str(target)


# ── 从已安装扩展打包 ──


def pack_installed(ext_id: str, output_path: str | Path | None = None) -> str:
    """从已安装的扩展重新打包"""
    from pycoder.extensions.manager import EXTENSIONS_DIR

    ext_dir = EXTENSIONS_DIR / ext_id.replace("/", "_")
    if not ext_dir.exists():
        raise FileNotFoundError(f"扩展未安装: {ext_id}")
    return pack(ext_dir, output_path)


# ── 生成扩展脚手架 ──


def scaffold(ext_id: str, name: str, description: str = "", author: str = "") -> str:
    """
    生成一个扩展的脚手架（目录 + 基础文件）。

    Args:
        ext_id: 扩展 ID，格式 publisher.name
        name: 扩展显示名称
        description: 描述
        author: 作者

    Returns:
        扩展目录路径
    """
    from pycoder.extensions.manager import EXTENSIONS_DIR

    target = EXTENSIONS_DIR / ext_id.replace("/", "_")
    target.mkdir(parents=True, exist_ok=True)

    # manifest.json
    manifest = {
        "id": ext_id,
        "name": name,
        "version": "0.1.0",
        "description": description or "PyCoder 扩展",
        "author": author or "anonymous",
        "publisher": author or "anonymous",
        "license": "MIT",
        "engines": {"pycoder": ">=0.5.0"},
        "categories": ["Other"],
        "tags": [],
        "activationEvents": ["onStartupFinished"],
        "contributes": {
            "commands": [],
            "settings": [],
            "keybindings": [],
        },
        "icon": "",
        "homepage": "",
        "repository": "",
    }

    (target / MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # extension.py 模板
    code = f'''"""
{name} — {description}
"""
from __future__ import annotations

name = "{name}"
version = "0.1.0"


def activate(api):
    """扩展激活时调用"""
    api.info("{ext_id} 已激活")
    # TODO: 注册命令、设置等


def deactivate():
    """扩展停用时调用"""
    pass


# TODO: 在这里添加你的扩展功能
'''
    (target / MAIN_FILE).write_text(code, encoding="utf-8")

    # README.md
    readme = f"""# {name}

{description}

## 功能

- 功能 1
- 功能 2

## 配置

此扩展提供以下设置：

...（在 manifest.json 的 contributes.settings 中声明）

## 命令

...（在 manifest.json 的 contributes.commands 中声明）
"""
    (target / "README.md").write_text(readme, encoding="utf-8")

    logger.info("extension_scaffold_created ext=%s path=%s", ext_id, target)
    return str(target)

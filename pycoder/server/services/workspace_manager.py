"""
工作区管理器 — 多根工作区、pycoder.json、AI 规则、项目脚手架

对标 VS Code .code-workspace / .vscode/ 体系，提供:
- pycoder.json 工作区文件的读写
- 多根文件夹管理（添加/删除/排序）
- AI 规则注入（.pycoder/rules.md）
- 项目脚手架模板

架构：
    workspace_manager.WorkspaceManager  — 单例，核心服务层
    Router                               — 挂接到 FastAPI 的 REST 端点
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


class WorkspaceFolder:
    """工作区内的一个根文件夹"""

    def __init__(self, path: str, name: str = "") -> None:
        self.path: str = path
        self.name: str = name or Path(path).name

    def to_dict(self) -> dict:
        return {"path": self.path, "name": self.name}

    @classmethod
    def from_dict(cls, d: dict) -> WorkspaceFolder:
        return cls(path=d.get("path", ""), name=d.get("name", ""))


class WorkspaceConfig:
    """pycoder.json 完整结构"""

    def __init__(self) -> None:
        self.name: str = ""
        self.description: str = ""
        self.version: str = "1.0.0"
        self.folders: list[WorkspaceFolder] = []
        self.ai: dict[str, Any] = {}
        self.settings: dict[str, Any] = {}
        self.tasks: dict[str, str] = {}

    def to_dict(self) -> dict:
        return {
            "$schema": "https://pycoder.ai/schemas/workspace.json",
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "folders": [f.to_dict() for f in self.folders],
            "ai": self.ai,
            "settings": self.settings,
            "tasks": self.tasks,
        }

    @classmethod
    def from_dict(cls, d: dict) -> WorkspaceConfig:
        obj = cls()
        obj.name = d.get("name", "")
        obj.description = d.get("description", "")
        obj.version = d.get("version", "1.0.0")
        obj.folders = [WorkspaceFolder.from_dict(f) for f in d.get("folders", [])]
        obj.ai = d.get("ai", {})
        obj.settings = d.get("settings", {})
        obj.tasks = d.get("tasks", {})
        return obj


# ══════════════════════════════════════════════════════════
# 工作区管理器
# ══════════════════════════════════════════════════════════


class WorkspaceManager:
    """工作区管理器（单例）

    管理 .pycoder/pycoder.json 的读写、多根文件夹、AI 规则、历史记录。
    """

    _instance: WorkspaceManager | None = None
    _initialized: bool = False

    def __new__(cls) -> WorkspaceManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._config: WorkspaceConfig = WorkspaceConfig()
        self._workspace_root: Path = Path.cwd().resolve()
        self._pycoder_dir: Path = self._workspace_root / ".pycoder"
        self._config_file: Path = self._pycoder_dir / "pycoder.json"
        self._rules_file: Path = self._pycoder_dir / "rules.md"
        self._load()
        self._initialized = True

    # ── 初始化与持久化 ──────────────────────────────────

    def initialize(self, root: str | Path) -> None:
        """初始化或切换工作区根目录"""
        self._workspace_root = Path(root).resolve()
        self._pycoder_dir = self._workspace_root / ".pycoder"
        self._config_file = self._pycoder_dir / "pycoder.json"
        self._rules_file = self._pycoder_dir / "rules.md"
        self._load()

    def _load(self) -> None:
        """从 pycoder.json 加载配置"""
        if self._config_file.exists():
            try:
                raw = self._config_file.read_text(encoding="utf-8")
                data = json.loads(raw)
                self._config = WorkspaceConfig.from_dict(data)
                logger.info(
                    "workspace_config_loaded path=%s folders=%d",
                    self._config_file,
                    len(self._config.folders),
                )
            except (json.JSONDecodeError, OSError, ValueError) as e:
                logger.warning(
                    "workspace_config_load_failed path=%s error=%s", self._config_file, e
                )
                self._config = WorkspaceConfig()
        else:
            # 默认配置：以根目录为唯一文件夹
            self._config = WorkspaceConfig()
            self._config.name = self._workspace_root.name
            self._config.folders = [WorkspaceFolder(path=".", name=self._workspace_root.name)]
            logger.info("workspace_config_created_default path=%s", self._config_file)

    def save(self) -> dict:
        """保存配置到 pycoder.json"""
        self._pycoder_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._config_file.write_text(
                json.dumps(self._config.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("workspace_config_saved path=%s", self._config_file)
            return {"success": True, "path": str(self._config_file)}
        except OSError as e:
            logger.error("workspace_config_save_failed error=%s", e)
            return {"success": False, "error": str(e)}

    # ── 配置读取 ────────────────────────────────────────

    def get_config(self) -> dict:
        """获取完整配置"""
        return self._config.to_dict()

    def get_name(self) -> str:
        return self._config.name or self._workspace_root.name

    def get_root(self) -> str:
        return str(self._workspace_root)

    # ── 文件夹管理 ──────────────────────────────────────

    def list_folders(self) -> list[dict]:
        """列出所有工作区根文件夹"""
        return [f.to_dict() for f in self._config.folders]

    def add_folder(self, path: str, name: str = "") -> dict:
        """添加文件夹到工作区"""
        resolved = Path(path).resolve()
        if not resolved.is_dir():
            return {"success": False, "error": f"目录不存在: {path}"}
        rel = self._to_relative(resolved)
        # 去重
        for f in self._config.folders:
            if Path(f.path).resolve() == resolved:
                return {"success": False, "error": f"文件夹已存在: {rel}"}
        folder = WorkspaceFolder(path=rel, name=name or resolved.name)
        self._config.folders.append(folder)
        self.save()
        return {"success": True, "folder": folder.to_dict()}

    def remove_folder(self, path: str) -> dict:
        """从工作区移除文件夹"""
        resolved = Path(path).resolve()
        before = len(self._config.folders)
        self._config.folders = [
            f for f in self._config.folders if Path(f.path).resolve() != resolved
        ]
        if len(self._config.folders) == before:
            return {"success": False, "error": f"文件夹不在工作区中: {path}"}
        self.save()
        return {"success": True, "folders": self.list_folders()}

    def reorder_folders(self, paths: list[str]) -> dict:
        """重新排序根文件夹"""
        path_set = set(paths)
        existing = {str(Path(f.path).resolve()) for f in self._config.folders}
        if path_set != existing:
            return {"success": False, "error": "文件夹列表不匹配"}
        # 按新顺序重建
        path_map = {str(Path(f.path).resolve()): f for f in self._config.folders}
        self._config.folders = []
        for p in paths:
            resolved = str(Path(p).resolve())
            if resolved in path_map:
                self._config.folders.append(path_map[resolved])
        self.save()
        return {"success": True, "folders": self.list_folders()}

    # ── AI 规则 ─────────────────────────────────────────

    def get_rules(self) -> str:
        """读取 AI 规则文件内容"""
        if self._rules_file.exists():
            try:
                return self._rules_file.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning("rules_read_failed error=%s", e)
        return ""

    def save_rules(self, content: str) -> dict:
        """保存 AI 规则到 .pycoder/rules.md"""
        self._pycoder_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._rules_file.write_text(content, encoding="utf-8")
            logger.info("rules_saved path=%s", self._rules_file)
            return {"success": True, "path": str(self._rules_file)}
        except OSError as e:
            return {"success": False, "error": str(e)}

    def build_ai_context_prompt(self) -> str:
        """构建 AI 上下文提示词：规则 + 工作区描述"""
        parts: list[str] = []
        # 工作区描述
        if self._config.description:
            parts.append(f"## 项目描述\n{self._config.description}")
        # AI 规则
        rules = self.get_rules()
        if rules:
            parts.append(f"## 项目 AI 规则\n{rules}")
        # AI 配置
        ai_cfg = self._config.ai
        if ai_cfg:
            lines = ["## AI 配置"]
            if "model" in ai_cfg:
                lines.append(f"- 推荐模型: {ai_cfg['model']}")
            if "temperature" in ai_cfg:
                lines.append(f"- Temperature: {ai_cfg['temperature']}")
            if "context_files" in ai_cfg:
                lines.append("- 上下文文件:")
                for cf in ai_cfg["context_files"]:
                    lines.append(f"  - {cf}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)

    # ── 设置 ────────────────────────────────────────────

    def get_settings(self) -> dict:
        return dict(self._config.settings)

    def update_settings(self, settings: dict) -> dict:
        self._config.settings.update(settings)
        self.save()
        return {"success": True, "settings": self._config.settings}

    def update_name(self, name: str) -> dict:
        self._config.name = name
        self.save()
        return {"success": True, "name": name}

    def update_description(self, desc: str) -> dict:
        self._config.description = desc
        self.save()
        return {"success": True, "description": desc}

    # ── 项目脚手架 ──────────────────────────────────────

    def scaffold_project(self, name: str, template: str = "basic") -> dict:
        """从模板创建新项目骨架"""
        target = self._workspace_root / name
        if target.exists():
            return {"success": False, "error": f"目标目录已存在: {name}"}

        templates = {
            "basic": {
                "files": {
                    "README.md": f"# {name}\n\n项目描述\n",
                    ".gitignore": "__pycache__/\n*.pyc\n.venv/\n.env\n",
                    "src/__init__.py": "",
                    "src/main.py": '"""入口文件"""\n\ndef main():\n    print("Hello from {name}")\n\n\nif __name__ == "__main__":\n    main()\n',
                    "tests/__init__.py": "",
                    "tests/test_main.py": '"""测试"""\n\ndef test_placeholder():\n    assert True\n',
                    "pyproject.toml": f'[project]\nname = "{name}"\nversion = "0.1.0"\ndescription = ""\nrequires-python = ">=3.11"\n',
                },
            },
            "fastapi": {
                "files": {
                    "README.md": f"# {name}\n\nFastAPI 项目\n",
                    ".gitignore": "__pycache__/\n*.pyc\n.venv/\n.env\n",
                    "src/__init__.py": "",
                    "src/main.py": '"""FastAPI 入口"""\n\nfrom fastapi import FastAPI\n\napp = FastAPI(title="{name}")\n\n\n@app.get("/")\nasync def root():\n    return {{"message": "Hello from {name}"}}\n',
                    "src/routers/__init__.py": "",
                    "src/models/__init__.py": "",
                    "tests/__init__.py": "",
                    "tests/test_main.py": '"""测试"""\n\ndef test_placeholder():\n    assert True\n',
                    "pyproject.toml": f'[project]\nname = "{name}"\nversion = "0.1.0"\ndependencies = ["fastapi", "uvicorn"]\nrequires-python = ">=3.11"\n',
                },
            },
            "react": {
                "files": {
                    "README.md": f"# {name}\n\nReact 项目\n",
                    ".gitignore": "node_modules/\ndist/\n.env\n",
                    "package.json": json.dumps(
                        {
                            "name": name,
                            "version": "0.1.0",
                            "private": True,
                            "scripts": {"dev": "vite", "build": "vite build"},
                        }
                    ),
                    "src/main.tsx": 'import React from "react";\nimport ReactDOM from "react-dom/client";\n\nfunction App() {{\n  return <h1>Hello from {name}</h1>;\n}}\n\nReactDOM.createRoot(document.getElementById("root")!).render(<App />);\n',
                    "index.html": '<!DOCTYPE html>\n<html><head><meta charset="UTF-8" /></head><body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body></html>\n',
                    "vite.config.ts": 'import {{ defineConfig }} from "vite";\nexport default defineConfig({{}});\n',
                },
            },
        }

        tpl = templates.get(template, templates["basic"])
        try:
            for rel_path, content in tpl["files"].items():
                full = target / rel_path
                full.parent.mkdir(parents=True, exist_ok=True)
                # 替换占位符
                rendered = content.replace("{name}", name)
                full.write_text(rendered, encoding="utf-8")
            # 自动注册为工作区文件夹
            self.add_folder(str(target), name=name)
            return {"success": True, "path": str(target), "files": list(tpl["files"].keys())}
        except OSError as e:
            return {"success": False, "error": str(e)}

    # ── 工具方法 ────────────────────────────────────────

    def _to_relative(self, resolved: Path) -> str:
        """将绝对路径转为相对工作区根的路径"""
        try:
            return str(resolved.relative_to(self._workspace_root)).replace("\\", "/")
        except ValueError:
            return str(resolved).replace("\\", "/")


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════


def get_workspace_manager() -> WorkspaceManager:
    """获取工作区管理器单例"""
    return WorkspaceManager()

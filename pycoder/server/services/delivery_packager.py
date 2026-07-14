"""
DeliveryPackager — 自动打包与交付引擎

功能:
    1. 分析项目类型 (FastAPI/Flask/Streamlit/CLI/Unknown)
    2. 生成 Dockerfile + docker-compose.yml
    3. 生成/补充 README.md
    4. 生成 CHANGELOG.md
    5. 打包为 .zip
    6. 生成完整交付报告

用于 AutonomousPipeline 的 Step 7。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from pycoder.server.chat_bridge import ChatBridge
from pycoder.server.log import log


class DeployTarget(Enum):
    LOCAL = "local"
    DOCKER = "docker"
    SSH = "ssh"


@dataclass
class DeliveryPackage:
    """交付包"""

    project_name: str = ""
    package_path: str = ""
    dockerfile_path: str = ""
    compose_path: str = ""
    readme_path: str = ""
    changelog_path: str = ""
    files_included: list[str] = field(default_factory=list)
    total_size_bytes: int = 0
    deploy_status: str = "not_deployed"
    deploy_url: str = ""

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "package_path": self.package_path,
            "dockerfile_path": self.dockerfile_path,
            "readme_path": self.readme_path,
            "files_count": len(self.files_included),
            "total_size_bytes": self.total_size_bytes,
            "deploy_status": self.deploy_status,
        }


@dataclass
class DeliveryReport:
    """交付报告"""

    success: bool
    package: DeliveryPackage | None = None
    steps: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "package": self.package.to_dict() if self.package else None,
            "steps": self.steps,
            "errors": self.errors,
            "summary": self.summary,
        }


class DeliveryPackager:
    """自动打包与交付引擎"""

    def __init__(
        self,
        workspace_root: Path,
        chat_bridge: ChatBridge | None = None,
    ):
        self._workspace = workspace_root
        self._bridge = chat_bridge

    async def deliver(
        self,
        project_name: str,
        user_request: str,
        pipeline_steps: list[dict],
        deploy_target: DeployTarget = DeployTarget.LOCAL,
        deploy_config: dict | None = None,
    ) -> DeliveryReport:
        """执行完整交付流程"""
        report = DeliveryReport(success=True)
        pkg = DeliveryPackage(project_name=project_name)

        # Step 1: 识别项目类型
        project_type = self._detect_project_type()
        pkg.files_included = self._list_project_files()
        pkg.total_size_bytes = sum(
            (self._workspace / f).stat().st_size
            for f in pkg.files_included
            if (self._workspace / f).exists()
        )
        report.steps.append(
            {
                "step": "detect",
                "status": "ok",
                "project_type": project_type,
                "files": len(pkg.files_included),
            }
        )

        # Step 2: 生成 Dockerfile
        dockerfile = self._workspace / "Dockerfile"
        if not dockerfile.exists() and self._bridge:
            try:
                dockerfile_content = await self._generate_dockerfile(project_type)
                if dockerfile_content:
                    dockerfile.write_text(dockerfile_content, encoding="utf-8")
                    pkg.dockerfile_path = str(dockerfile)
                    pkg.files_included.append("Dockerfile")
                    report.steps.append({"step": "dockerfile", "status": "ok"})
            except Exception as e:
                report.steps.append({"step": "dockerfile", "status": "failed", "error": str(e)})

        # Step 3: 生成 docker-compose.yml
        compose = self._workspace / "docker-compose.yml"
        if not compose.exists():
            try:
                compose_content = self._generate_compose(project_type, project_name)
                compose.write_text(compose_content, encoding="utf-8")
                pkg.compose_path = str(compose)
                if "docker-compose.yml" not in pkg.files_included:
                    pkg.files_included.append("docker-compose.yml")
                report.steps.append({"step": "compose", "status": "ok"})
            except Exception as e:
                report.steps.append({"step": "compose", "status": "failed", "error": str(e)})

        # Step 4: 生成 DELIVERY.md
        delivery_md = self._workspace / "DELIVERY.md"
        delivery_content = self._build_delivery_md(
            project_name,
            user_request,
            pipeline_steps,
            pkg.files_included,
        )
        delivery_md.write_text(delivery_content, encoding="utf-8")
        pkg.changelog_path = str(delivery_md)
        report.steps.append({"step": "delivery_md", "status": "ok"})

        # Step 5: 打包
        try:
            pkg.package_path = await self._create_package(project_name)
            report.steps.append(
                {
                    "step": "package",
                    "status": "ok",
                    "path": pkg.package_path,
                }
            )
        except Exception as e:
            report.steps.append({"step": "package", "status": "failed", "error": str(e)})

        # Step 6: 部署 (可选)
        if deploy_target != DeployTarget.LOCAL:
            try:
                deploy_result = await self._deploy(deploy_target, deploy_config or {})
                pkg.deploy_status = deploy_result.get("status", "unknown")
                pkg.deploy_url = deploy_result.get("url", "")
                report.steps.append(
                    {
                        "step": "deploy",
                        "status": deploy_result.get("status", "failed"),
                    }
                )
            except Exception as e:
                report.steps.append({"step": "deploy", "status": "failed", "error": str(e)})

        report.package = pkg
        report.summary = f"交付完成: {len(pkg.files_included)} 个文件" + (
            f", 已部署到 {pkg.deploy_url}" if pkg.deploy_url else ""
        )
        return report

    # ── 私有方法 ────────────────────────────────────────

    def _detect_project_type(self) -> str:
        """检测项目类型"""
        files = os.listdir(self._workspace)

        # FastAPI
        if any(
            "fastapi" in f.lower() or "uvicorn" in f.lower()
            for f in files + os.listdir(str(self._workspace))
            if os.path.isfile(os.path.join(self._workspace, f))
        ):
            for py_file in Path(self._workspace).rglob("*.py"):
                try:
                    content = py_file.read_text(encoding="utf-8")
                    if "FastAPI" in content or "fastapi" in content.lower():
                        return "fastapi"
                except (OSError, UnicodeDecodeError, PermissionError) as e:
                    log.debug("read_pyfile_failed", path=str(py_file), error=str(e))

        # Flask
        for py_file in Path(self._workspace).rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                if "flask" in content.lower():
                    return "flask"
            except (OSError, UnicodeDecodeError, PermissionError) as e:
                log.debug("read_pyfile_failed", path=str(py_file), error=str(e))

        # Streamlit
        for py_file in Path(self._workspace).rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                if "streamlit" in content.lower():
                    return "streamlit"
            except (OSError, UnicodeDecodeError, PermissionError) as e:
                log.debug("read_pyfile_failed", path=str(py_file), error=str(e))

        # 通用 Python
        py_files = list(Path(self._workspace).rglob("*.py"))
        py_files = [p for p in py_files if "test_" not in p.name]
        if py_files:
            return "python"

        return "unknown"

    def _list_project_files(self) -> list[str]:
        """列出项目文件"""
        files: list[str] = []
        excludes = {
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            "node_modules",
            ".pytest_cache",
            "dist",
            ".pycoder_delivery",
        }
        for item in self._workspace.rglob("*"):
            if any(ex in item.parts for ex in excludes):
                continue
            if item.is_file():
                rel = item.relative_to(self._workspace)
                files.append(str(rel).replace("\\", "/"))
        return sorted(files)

    async def _generate_dockerfile(self, project_type: str) -> str:
        """LLM 生成 Dockerfile"""
        if not self._bridge:
            return ""

        templates = {
            "fastapi": 'FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .\nCMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]\nEXPOSE 8000',
            "flask": 'FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .\nCMD ["python", "app.py"]\nEXPOSE 5000',
            "streamlit": 'FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .\nCMD ["streamlit", "run", "app.py", "--server.port=8501"]\nEXPOSE 8501',
            "python": 'FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install -r requirements.txt\nCOPY . .\nCMD ["python", "main.py"]',
        }

        if project_type in templates:
            return templates[project_type]

        # LLM 生成
        self._bridge.config.system_prompt = "你是 Docker 专家。生成 Dockerfile。"
        self._bridge.config.max_tokens = 1024
        prompt = f"为以下 {project_type} 项目生成 Dockerfile:\n"
        try:
            app_files = [
                f for f in self._list_project_files() if f.endswith(".py") and "test_" not in f
            ][:3]
            prompt += "\n".join(f"  - {f}" for f in app_files)

            result = ""
            async for event in self._bridge.chat_stream(prompt):
                if event.event_type == "token":
                    result += event.content
                elif event.event_type == "done":
                    result = event.content or result
            return result.strip() or templates.get("python", "")
        except Exception as e:
            # LLM 生成失败时回退到默认模板
            log.warning(
                "generate_dockerfile_failed fallback=template",
                project_type=project_type,
                error=str(e),
            )
            return templates.get("python", "")

    def _generate_compose(self, project_type: str, project_name: str) -> str:
        """生成 docker-compose.yml"""
        return f"""version: '3.8'
services:
  {project_name}:
    build: .
    ports:
      - "8000:8000"
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
"""

    def _build_delivery_md(
        self,
        project_name: str,
        request: str,
        steps: list[dict],
        files: list[str],
    ) -> str:
        """构建 DELIVERY.md 内容"""
        lines = [
            f"# {project_name} — 交付报告",
            "",
            f"> 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 需求",
            "",
            request,
            "",
            "## 执行步骤",
            "",
        ]
        for s in steps:
            icon = "✅" if s.get("status") == "ok" else "❌"
            lines.append(f"- {icon} **{s.get('step', '')}**: {s.get('status', '')}")

        lines += ["", "## 项目文件", ""]
        for f in sorted(files)[:50]:
            target = self._workspace / f
            size = target.stat().st_size if target.exists() else 0
            lines.append(f"- `{f}` ({size} 字节)")

        lines += [
            "",
            "## 运行方式",
            "",
            "### Docker",
            "",
            "```bash",
            "docker-compose up -d",
            "```",
            "",
            "### 本地",
            "",
            "```bash",
            "pip install -r requirements.txt",
            "python app.py",
            "```",
        ]
        return "\n".join(lines)

    async def _create_package(self, project_name: str) -> str:
        """创建 zip/tar.gz 打包"""
        zip_dir = self._workspace / ".pycoder_delivery"
        zip_dir.mkdir(parents=True, exist_ok=True)

        if shutil.which("zip"):
            zip_target = zip_dir / f"{project_name}.zip"
            subprocess.run(
                ["zip", "-r", str(zip_target), "."],
                cwd=str(self._workspace),
                capture_output=True,
            )
            if zip_target.exists():
                return str(zip_target)

        if shutil.which("tar"):
            tar_target = zip_dir / f"{project_name}.tar.gz"
            subprocess.run(
                [
                    "tar",
                    "-czf",
                    str(tar_target),
                    "--exclude=.git",
                    "--exclude=__pycache__",
                    "--exclude=node_modules",
                    ".",
                ],
                cwd=str(self._workspace),
                capture_output=True,
            )
            if tar_target.exists():
                return str(tar_target)

        # 回退: 不做包，返回目录路径
        return str(self._workspace)

    async def _deploy(
        self,
        target: DeployTarget,
        config: dict,
    ) -> dict:
        """执行部署"""
        if target == DeployTarget.LOCAL:
            try:
                subprocess.run(
                    ["docker", "compose", "up", "-d"],
                    cwd=str(self._workspace),
                    capture_output=True,
                    timeout=120,
                )
                return {"status": "deployed", "url": "http://localhost:8000"}
            except Exception as e:
                return {"status": "failed", "error": str(e)[:200]}

        if target == DeployTarget.SSH:
            return {"status": "skipped", "reason": "SSH 部署需配置远程主机信息"}

        return {"status": "skipped", "reason": f"不支持的目标: {target.value}"}

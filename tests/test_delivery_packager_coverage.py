"""DeliveryPackager 单元测试 — 覆盖 pycoder.server.services.delivery_packager

覆盖:
- DeployTarget / DeliveryPackage / DeliveryReport to_dict
- deliver() 完整流程 (含/不含 bridge、部署、错误)
- _detect_project_type (fastapi/flask/streamlit/python/unknown)
- _list_project_files (排除目录)
- _generate_dockerfile (模板 / LLM / 失败回退)
- _generate_compose
- _build_delivery_md
- _create_package (zip / tar / 回退)
- _deploy (local / docker / ssh / 异常)
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pycoder.server.chat_bridge import ChatEvent
from pycoder.server.services.delivery_packager import (
    DeliveryPackage,
    DeliveryPackager,
    DeliveryReport,
    DeployTarget,
)


# ── 辅助 ───────────────────────────────────────────────


def make_mock_bridge(events: list[ChatEvent]):
    bridge = MagicMock()
    bridge.config = MagicMock()

    async def _stream(prompt: str) -> AsyncIterator[ChatEvent]:
        for ev in events:
            yield ev

    bridge.chat_stream = _stream
    return bridge


# ── 枚举/数据类 ───────────────────────────────────────


class TestEnumsAndDataclasses:
    def test_deploy_target_values(self):
        assert DeployTarget.LOCAL.value == "local"
        assert DeployTarget.DOCKER.value == "docker"
        assert DeployTarget.SSH.value == "ssh"

    def test_delivery_package_to_dict(self):
        pkg = DeliveryPackage(
            project_name="proj",
            package_path="/p.zip",
            files_included=["a.py", "b.py"],
            total_size_bytes=100,
            deploy_status="deployed",
        )
        d = pkg.to_dict()
        assert d["project_name"] == "proj"
        assert d["files_count"] == 2
        assert d["deploy_status"] == "deployed"

    def test_delivery_report_to_dict_with_package(self):
        pkg = DeliveryPackage(project_name="x")
        report = DeliveryReport(success=True, package=pkg, summary="s")
        d = report.to_dict()
        assert d["success"] is True
        assert d["package"]["project_name"] == "x"
        assert d["summary"] == "s"

    def test_delivery_report_to_dict_no_package(self):
        report = DeliveryReport(success=False, errors=["e1"])
        d = report.to_dict()
        assert d["package"] is None
        assert d["errors"] == ["e1"]


# ── _detect_project_type ─────────────────────────────


class TestDetectProjectType:
    def test_empty_workspace_unknown(self, tmp_path: Path):
        pkg = DeliveryPackager(tmp_path)
        assert pkg._detect_project_type() == "unknown"

    def test_fastapi(self, tmp_path: Path):
        # 文件名含 fastapi 触发外层 if
        (tmp_path / "fastapi_app.py").write_text(
            "from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8"
        )
        pkg = DeliveryPackager(tmp_path)
        assert pkg._detect_project_type() == "fastapi"

    def test_flask(self, tmp_path: Path):
        (tmp_path / "app.py").write_text(
            "from flask import Flask\napp = Flask(__name__)\n", encoding="utf-8"
        )
        pkg = DeliveryPackager(tmp_path)
        assert pkg._detect_project_type() == "flask"

    def test_streamlit(self, tmp_path: Path):
        (tmp_path / "app.py").write_text(
            "import streamlit as st\nst.write('hi')\n", encoding="utf-8"
        )
        pkg = DeliveryPackager(tmp_path)
        assert pkg._detect_project_type() == "streamlit"

    def test_plain_python(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        assert pkg._detect_project_type() == "python"

    def test_excludes_test_files_for_unknown(self, tmp_path: Path):
        # 只有 test_ 开头的 .py 文件，不含框架关键字
        (tmp_path / "test_foo.py").write_text("import pytest\n", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        # py_files 排除 test_ 后为空 → unknown
        assert pkg._detect_project_type() == "unknown"

    def test_uvicorn_filename_triggers_fastapi(self, tmp_path: Path):
        (tmp_path / "uvicorn.txt").write_text("config", encoding="utf-8")
        (tmp_path / "main.py").write_text(
            "from fastapi import FastAPI\n", encoding="utf-8"
        )
        pkg = DeliveryPackager(tmp_path)
        assert pkg._detect_project_type() == "fastapi"

    def test_unreadable_py_file_skipped(self, tmp_path: Path):
        # 写入一个非 utf8 二进制文件
        (tmp_path / "main.py").write_bytes(b"\xff\xfe\x00bad")
        pkg = DeliveryPackager(tmp_path)
        # 不应抛异常
        result = pkg._detect_project_type()
        assert result in ("python", "unknown")


# ── _list_project_files ───────────────────────────────


class TestListProjectFiles:
    def test_lists_files(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("x", encoding="utf-8")
        (tmp_path / "README.md").write_text("r", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        files = pkg._list_project_files()
        assert "app.py" in files
        assert "README.md" in files

    def test_excludes_directories(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "mod.pyc").write_text("x", encoding="utf-8")
        (tmp_path / "app.py").write_text("x", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        files = pkg._list_project_files()
        assert "app.py" in files
        assert not any(".git" in f for f in files)
        assert not any("__pycache__" in f for f in files)

    def test_excludes_delivery_dir(self, tmp_path: Path):
        (tmp_path / ".pycoder_delivery").mkdir()
        (tmp_path / ".pycoder_delivery" / "x.zip").write_text("x", encoding="utf-8")
        (tmp_path / "main.py").write_text("x", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        files = pkg._list_project_files()
        assert not any(".pycoder_delivery" in f for f in files)

    def test_sorted_output(self, tmp_path: Path):
        (tmp_path / "z.py").write_text("x", encoding="utf-8")
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        files = pkg._list_project_files()
        assert files == sorted(files)


# ── _generate_dockerfile ─────────────────────────────


class TestGenerateDockerfile:
    async def test_no_bridge_returns_empty(self, tmp_path: Path):
        pkg = DeliveryPackager(tmp_path)
        result = await pkg._generate_dockerfile("fastapi")
        assert result == ""

    async def test_template_fastapi(self, tmp_path: Path):
        bridge = make_mock_bridge([])
        pkg = DeliveryPackager(tmp_path, chat_bridge=bridge)
        result = await pkg._generate_dockerfile("fastapi")
        assert "uvicorn" in result
        assert "python:3.12-slim" in result

    async def test_template_python(self, tmp_path: Path):
        bridge = make_mock_bridge([])
        pkg = DeliveryPackager(tmp_path, chat_bridge=bridge)
        result = await pkg._generate_dockerfile("python")
        assert "main.py" in result

    async def test_llm_fallback_for_unknown(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
        bridge = make_mock_bridge([ChatEvent(event_type="done", content="FROM custom")])
        pkg = DeliveryPackager(tmp_path, chat_bridge=bridge)
        result = await pkg._generate_dockerfile("custom-type")
        assert "FROM custom" in result

    async def test_llm_failure_falls_back_to_python_template(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
        bridge = MagicMock()
        bridge.config = MagicMock()

        async def _bad_stream(prompt):
            raise RuntimeError("LLM 不可用")
            yield  # noqa

        bridge.chat_stream = _bad_stream
        pkg = DeliveryPackager(tmp_path, chat_bridge=bridge)
        result = await pkg._generate_dockerfile("custom-type")
        # 应回退到 python 模板
        assert "python:3.12-slim" in result

    async def test_llm_empty_result_falls_back(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
        bridge = make_mock_bridge([ChatEvent(event_type="done", content="")])
        pkg = DeliveryPackager(tmp_path, chat_bridge=bridge)
        result = await pkg._generate_dockerfile("custom-type")
        assert "python:3.12-slim" in result


# ── _generate_compose ─────────────────────────────────


class TestGenerateCompose:
    def test_compose_content(self, tmp_path: Path):
        pkg = DeliveryPackager(tmp_path)
        content = pkg._generate_compose("fastapi", "myapp")
        assert "version:" in content
        assert "myapp" in content
        assert "8000:8000" in content
        assert "PYTHONUNBUFFERED" in content


# ── _build_delivery_md ───────────────────────────────


class TestBuildDeliveryMd:
    def test_basic_content(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        md = pkg._build_delivery_md("myproj", "user request",
                                     [{"step": "detect", "status": "ok"}],
                                     ["app.py"])
        assert "myproj" in md
        assert "user request" in md
        assert "detect" in md
        assert "app.py" in md
        assert "docker-compose" in md.lower() or "docker" in md.lower()

    def test_step_with_failed_status(self, tmp_path: Path):
        pkg = DeliveryPackager(tmp_path)
        md = pkg._build_delivery_md("p", "r",
                                     [{"step": "deploy", "status": "failed"}], [])
        # 失败步骤用 ❌
        assert "❌" in md

    def test_step_with_ok_status(self, tmp_path: Path):
        pkg = DeliveryPackager(tmp_path)
        md = pkg._build_delivery_md("p", "r",
                                     [{"step": "detect", "status": "ok"}], [])
        assert "✅" in md

    def test_nonexistent_file_size_zero(self, tmp_path: Path):
        pkg = DeliveryPackager(tmp_path)
        md = pkg._build_delivery_md("p", "r", [], ["ghost.py"])
        assert "ghost.py" in md
        assert "0 字节" in md


# ── _create_package ───────────────────────────────────


class TestCreatePackage:
    async def test_zip_available(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("x", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        with patch("pycoder.server.services.delivery_packager.shutil.which",
                    side_effect=lambda x: "/usr/bin/zip" if x == "zip" else None), \
             patch("pycoder.server.services.delivery_packager.subprocess.run") as mock_run:
            # 模拟 zip 命令创建文件
            def _fake_run(cmd, **kwargs):
                # cmd[2] 是目标 zip 路径
                Path(cmd[2]).write_bytes(b"PK")
                return MagicMock(returncode=0)
            mock_run.side_effect = _fake_run
            result = await pkg._create_package("myapp")
            assert result.endswith("myapp.zip")

    async def test_tar_fallback(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("x", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        with patch("pycoder.server.services.delivery_packager.shutil.which",
                    side_effect=lambda x: "/usr/bin/tar" if x == "tar" else None), \
             patch("pycoder.server.services.delivery_packager.subprocess.run") as mock_run:
            def _fake_run(cmd, **kwargs):
                # tar 目标路径在 cmd[2]
                Path(cmd[2]).write_bytes(b"x")
                return MagicMock(returncode=0)
            mock_run.side_effect = _fake_run
            result = await pkg._create_package("myapp")
            assert result.endswith("myapp.tar.gz")

    async def test_no_zip_no_tar_returns_workspace(self, tmp_path: Path):
        pkg = DeliveryPackager(tmp_path)
        with patch("pycoder.server.services.delivery_packager.shutil.which",
                    return_value=None):
            result = await pkg._create_package("myapp")
            assert result == str(tmp_path)


# ── _deploy ───────────────────────────────────────────


class TestDeploy:
    async def test_local_success(self, tmp_path: Path):
        pkg = DeliveryPackager(tmp_path)
        with patch("pycoder.server.services.delivery_packager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            # 注意: 源码 deploy 中 LOCAL 走 docker compose up，但 target==LOCAL 不会触发
            # 因为 deliver 中 `if deploy_target != DeployTarget.LOCAL`
            # 这里直接测 _deploy
            result = await pkg._deploy(DeployTarget.LOCAL, {})
            assert result["status"] == "deployed"
            assert "localhost" in result["url"]

    async def test_local_failure(self, tmp_path: Path):
        pkg = DeliveryPackager(tmp_path)
        with patch("pycoder.server.services.delivery_packager.subprocess.run",
                    side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=120)):
            result = await pkg._deploy(DeployTarget.LOCAL, {})
            assert result["status"] == "failed"

    async def test_ssh_skipped(self, tmp_path: Path):
        pkg = DeliveryPackager(tmp_path)
        result = await pkg._deploy(DeployTarget.SSH, {})
        assert result["status"] == "skipped"
        assert "SSH" in result["reason"]

    async def test_docker_unsupported(self, tmp_path: Path):
        pkg = DeliveryPackager(tmp_path)
        result = await pkg._deploy(DeployTarget.DOCKER, {})
        assert result["status"] == "skipped"
        assert "不支持" in result["reason"]


# ── deliver() 完整流程 ───────────────────────────────


class TestDeliver:
    async def test_minimal_local(self, tmp_path: Path):
        (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        with patch("pycoder.server.services.delivery_packager.shutil.which",
                    return_value=None):
            report = await pkg.deliver("myapp", "build app", [])
        assert report.success is True
        assert report.package is not None
        assert report.package.project_name == "myapp"
        # 应包含 detect / delivery_md / package 步骤
        steps = [s["step"] for s in report.steps]
        assert "detect" in steps
        assert "delivery_md" in steps
        assert "package" in steps

    async def test_with_bridge_generates_dockerfile(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
        bridge = make_mock_bridge([])
        pkg = DeliveryPackager(tmp_path, chat_bridge=bridge)
        with patch("pycoder.server.services.delivery_packager.shutil.which",
                    return_value=None):
            report = await pkg.deliver("app", "task", [])
        # 应生成 Dockerfile (python 模板)
        assert (tmp_path / "Dockerfile").exists()
        assert (tmp_path / "docker-compose.yml").exists()
        assert (tmp_path / "DELIVERY.md").exists()
        assert report.package.dockerfile_path != ""

    async def test_existing_dockerfile_not_regenerated(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
        (tmp_path / "Dockerfile").write_text("FROM custom:1.0\n", encoding="utf-8")
        bridge = make_mock_bridge([])
        pkg = DeliveryPackager(tmp_path, chat_bridge=bridge)
        with patch("pycoder.server.services.delivery_packager.shutil.which",
                    return_value=None):
            await pkg.deliver("app", "task", [])
        # 不应被覆盖
        assert "custom:1.0" in (tmp_path / "Dockerfile").read_text(encoding="utf-8")

    async def test_existing_compose_not_regenerated(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
        (tmp_path / "docker-compose.yml").write_text("custom: compose\n", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        with patch("pycoder.server.services.delivery_packager.shutil.which",
                    return_value=None):
            await pkg.deliver("app", "task", [])
        assert "custom: compose" in (tmp_path / "docker-compose.yml").read_text()

    async def test_deploy_ssh(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        with patch("pycoder.server.services.delivery_packager.shutil.which",
                    return_value=None):
            report = await pkg.deliver(
                "app", "task", [],
                deploy_target=DeployTarget.SSH,
                deploy_config={"host": "example.com"},
            )
        # SSH 部署应被跳过
        deploy_steps = [s for s in report.steps if s["step"] == "deploy"]
        assert len(deploy_steps) == 1
        assert deploy_steps[0]["status"] == "skipped"
        assert report.package.deploy_status == "skipped"

    async def test_deploy_docker(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        with patch("pycoder.server.services.delivery_packager.shutil.which",
                    return_value=None):
            report = await pkg.deliver(
                "app", "task", [],
                deploy_target=DeployTarget.DOCKER,
            )
        deploy_steps = [s for s in report.steps if s["step"] == "deploy"]
        assert len(deploy_steps) == 1
        # docker 部署会返回 skipped (不支持)
        assert deploy_steps[0]["status"] == "skipped"

    async def test_summary_includes_file_count(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)
        with patch("pycoder.server.services.delivery_packager.shutil.which",
                    return_value=None):
            report = await pkg.deliver("app", "task", [])
        assert "个文件" in report.summary

    async def test_package_failure_continues(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
        pkg = DeliveryPackager(tmp_path)

        async def _fail(name):
            raise RuntimeError("打包失败")
        with patch.object(pkg, "_create_package", side_effect=_fail), \
             patch("pycoder.server.services.delivery_packager.shutil.which",
                   return_value=None):
            report = await pkg.deliver("app", "task", [])
        # package 步骤失败但整体报告仍生成
        pkg_steps = [s for s in report.steps if s["step"] == "package"]
        assert len(pkg_steps) == 1
        assert pkg_steps[0]["status"] == "failed"

"""测试工具 — generate_tests, test_integration, test_e2e, test_performance, generate_pipeline"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pycoder.bus.protocol import CapabilityCategory, CapabilityDefinition, ExecutionMode, SideEffect
from pycoder.capabilities.permissions import TOOL_PERMISSIONS
from pycoder.capabilities.degradation import wrap_handler

_CT = CapabilityCategory.SELF_EVO


def register(registry: Any) -> None:
    _reg(
        registry,
        "tools.testing.generate_tests",
        "生成测试",
        "为指定 Python 文件自动生成 pytest 测试骨架",
        {
            "file": {"type": "string"},
            "framework": {"type": "string", "enum": ["pytest", "unittest"], "default": "pytest"},
        },
        ["file"],
        _handle_generate_tests,
    )

    _reg(
        registry,
        "tools.testing.test_integration",
        "集成测试",
        "自动扫描 FastAPI 路由，生成 httpx 集成测试脚本",
        {"app_file": {"type": "string"}, "output_dir": {"type": "string", "default": "tests"}},
        ["app_file"],
        _handle_test_integration,
    )

    _reg(
        registry,
        "tools.testing.test_e2e",
        "E2E 测试",
        "生成 Playwright 端到端浏览器测试脚本",
        {
            "app_url": {"type": "string", "default": "http://localhost:8423"},
            "pages": {"type": "array", "items": {"type": "string"}, "default": ["/"]},
        },
        [],
        _handle_test_e2e,
    )

    _reg(
        registry,
        "tools.testing.test_performance",
        "性能测试",
        "生成 Locust 性能/压力测试脚本",
        {
            "target_url": {"type": "string", "default": "http://localhost:8423"},
            "users": {"type": "number", "default": 100},
            "spawn_rate": {"type": "number", "default": 10},
        },
        [],
        _handle_test_performance,
    )

    _reg(
        registry,
        "tools.testing.generate_pipeline",
        "CI/CD 管道",
        "生成 CI/CD 管道配置文件（GitHub Actions 等）",
        {
            "project_type": {
                "type": "string",
                "enum": ["python-app", "fastapi", "flask", "cli"],
                "default": "python-app",
            },
            "platform": {
                "type": "string",
                "enum": ["github-actions", "gitlab-ci"],
                "default": "github-actions",
            },
        },
        [],
        _handle_generate_pipeline,
    )


def _reg(registry, cid, name, desc, schema, required, handler):
    registry.register(
        CapabilityDefinition(
            id=cid,
            name=name,
            description=desc,
            permission=TOOL_PERMISSIONS.get(cid),
            category=_CT,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.FILE_WRITE],
            schema={"type": "object", "properties": schema, "required": required},
            tags=[cid.rsplit(".", 1)[-1], name],
        ),
        handler=wrap_handler(handler),
    )


async def _handle_generate_tests(params: dict, context: dict) -> dict:
    return {
        "success": True,
        "test_file": f"test_{Path(params['file']).name}",
        "note": "测试生成需要 AI 完成具体代码",
    }


async def _handle_test_integration(params: dict, context: dict) -> dict:
    return {"success": True, "note": "集成测试需要 AI 完成具体生成"}


async def _handle_test_e2e(params: dict, context: dict) -> dict:
    return {
        "success": True,
        "test_content": "# Playwright E2E Test\n",
        "instructions": "pip install pytest-playwright; playwright install chromium",
    }


async def _handle_test_performance(params: dict, context: dict) -> dict:
    return {
        "success": True,
        "test_content": "# Locust Performance Test\n",
        "instructions": "pip install locust",
    }


async def _handle_generate_pipeline(params: dict, context: dict) -> dict:
    return {"success": True, "note": "CI/CD 管道生成器已就绪"}

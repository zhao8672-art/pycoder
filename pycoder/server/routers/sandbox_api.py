"""P1-4: 沙箱 API — 暴露沙箱选择与执行能力

端点:
- GET  /api/sandbox/status        - 当前沙箱后端与 Docker 可用性
- GET  /api/sandbox/check-docker  - 重新检测 Docker 可用性
- POST /api/sandbox/execute       - 通过统一入口执行代码
- POST /api/sandbox/select        - 切换沙箱后端（修改全局选择器）
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pycoder.adapters.sandbox_selector import (
    SandboxSelector,
    check_docker_available,
    execute_code,
    get_selector,
    reset_selector,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


# ── Pydantic 模型 ──────────────────────────────────────


class SandboxStatusResponse(BaseModel):
    backend: str
    docker_available: bool
    reason: str
    image: str = ""


class ExecuteRequest(BaseModel):
    code: str
    timeout: int = Field(default=30, ge=1, le=300)
    prefer: Literal["auto", "docker", "subprocess"] = "auto"


class ExecuteResponse(BaseModel):
    success: bool
    stdout: str = ""
    stderr: str = ""
    error_type: str = ""
    error_message: str = ""
    execution_time: float = 0.0
    sandbox_backend: str
    sandbox_reason: str = ""


class SelectRequest(BaseModel):
    prefer: Literal["auto", "docker", "subprocess"]
    docker_image: str | None = None
    docker_required: bool | None = None


# ── 端点 ──────────────────────────────────────────────


@router.get("/status", response_model=SandboxStatusResponse)
async def get_status() -> SandboxStatusResponse:
    """获取当前沙箱后端状态"""
    selector = get_selector()
    info = await selector.select()
    return SandboxStatusResponse(
        backend=info.backend,
        docker_available=info.docker_available,
        reason=info.reason,
        image=info.image,
    )


@router.get("/check-docker")
async def check_docker_endpoint() -> dict:
    """重新检测 Docker 可用性（清空缓存）"""
    from pycoder.adapters.sandbox_selector import invalidate_docker_cache

    invalidate_docker_cache()
    available, reason = await check_docker_available()
    return {
        "docker_available": available,
        "reason": reason,
    }


@router.post("/execute", response_model=ExecuteResponse)
async def execute_endpoint(req: ExecuteRequest) -> ExecuteResponse:
    """通过统一入口执行代码（自动选择沙箱）"""
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="代码不能为空")

    if req.prefer != "auto":
        # 临时覆盖偏好
        selector = SandboxSelector(
            prefer=req.prefer,
        )
        sandbox, info = await selector.get_sandbox()
        result = await sandbox.execute(req.code, timeout=req.timeout)
    else:
        result, info = await execute_code(req.code, timeout=req.timeout)

    return ExecuteResponse(
        success=result.success,
        stdout=result.stdout,
        stderr=result.stderr,
        error_type=result.error_type,
        error_message=result.error_message,
        execution_time=result.execution_time,
        sandbox_backend=info.backend,
        sandbox_reason=info.reason,
    )


@router.post("/select")
async def select_backend(req: SelectRequest) -> dict:
    """切换全局沙箱选择器偏好"""
    reset_selector()
    # 创建新的全局选择器
    global _selector
    from pycoder.adapters import sandbox_selector as _sel_mod

    _sel_mod._selector = SandboxSelector(
        prefer=req.prefer,
        docker_image=req.docker_image,
        docker_required=req.docker_required,
    )
    info = await _sel_mod._selector.select(force_check=True)
    return {
        "success": True,
        "backend": info.backend,
        "docker_available": info.docker_available,
        "reason": info.reason,
        "image": info.image,
    }

"""
Docker 沙箱执行器 API 路由

端点:
    POST /api/sandbox/execute    — 在沙箱中执行代码
    POST /api/sandbox/command    — 在沙箱中执行 Shell 命令
    POST /api/sandbox/build-test — 构建并测试项目
    GET  /api/sandbox/status     — 获取沙箱池状态
    POST /api/sandbox/cleanup    — 清理所有沙箱容器
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pycoder.safety.sandbox_executor import (
    DockerNotAvailableError,
    SandboxMemoryError,
    SandboxPool,
    SandboxTimeoutError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])

# ──────────────────────────────────────────────
# 全局沙箱池（模块级单例）
# ──────────────────────────────────────────────

_sandbox_pool: SandboxPool | None = None


def _get_pool() -> SandboxPool:
    """获取或创建全局沙箱池实例"""
    global _sandbox_pool
    if _sandbox_pool is None:
        _sandbox_pool = SandboxPool(max_containers=10, warm_containers=2, max_concurrent=5)
        logger.info("沙箱池已初始化: max=%d warm=%d concurrent=%d", 10, 2, 5)
    return _sandbox_pool


# ──────────────────────────────────────────────
# 请求模型
# ──────────────────────────────────────────────


class ExecuteRequest(BaseModel):
    """沙箱代码执行请求"""

    code: str = Field(..., description="要执行的代码内容")
    language: str = Field(default="python", description="编程语言: python/JavaScript/TypeScript/bash")
    files: dict[str, str] | None = Field(default=None, description="额外文件映射 {文件名: 内容}")
    timeout: float | None = Field(default=None, description="超时时间（秒），None 使用默认值")
    network_enabled: bool = Field(default=False, description="是否启用网络访问（默认禁用）")


class CommandRequest(BaseModel):
    """沙箱命令执行请求"""

    command: str = Field(..., description="要执行的 Shell 命令")
    cwd: str | None = Field(default=None, description="工作目录（相对于沙箱工作目录）")
    timeout: float | None = Field(default=None, description="超时时间（秒），None 使用默认值")


class BuildTestRequest(BaseModel):
    """构建测试请求"""

    project_path: str = Field(..., description="项目目录路径（宿主机绝对路径）")
    test_command: str = Field(..., description="测试命令，如 'pytest' 或 'npm test'")
    timeout: float | None = Field(default=None, description="超时时间（秒），None 使用默认值")


# ──────────────────────────────────────────────
# 响应模型
# ──────────────────────────────────────────────


class ExecuteResponse(BaseModel):
    """沙箱执行响应"""

    success: bool = Field(..., description="是否执行成功")
    output: str = Field(default="", description="标准输出")
    error: str = Field(default="", description="错误信息")
    exit_code: int = Field(default=-1, description="退出码")
    duration_ms: float = Field(default=0.0, description="执行耗时（毫秒）")
    killed_by_timeout: bool = Field(default=False, description="是否因超时被杀")
    killed_by_memory: bool = Field(default=False, description="是否因内存超限被杀")
    memory_used_mb: float = Field(default=0.0, description="内存使用量（MB）")


class StatusResponse(BaseModel):
    """沙箱池状态响应"""

    docker_available: bool = Field(default=False, description="Docker 是否可用")
    stats: dict[str, Any] = Field(default_factory=dict, description="池统计信息")


class CleanupResponse(BaseModel):
    """清理响应"""

    success: bool = Field(default=True, description="是否清理成功")
    message: str = Field(default="", description="清理结果消息")


# ──────────────────────────────────────────────
# 端点实现
# ──────────────────────────────────────────────


@router.post("/execute", response_model=ExecuteResponse)
async def execute_code(req: ExecuteRequest) -> ExecuteResponse:
    """
    在 Docker 沙箱中安全执行代码

    支持 Python、JavaScript、TypeScript、Bash 等语言。
    默认禁用网络访问，提供内存和 CPU 限制，超时自动终止。
    """
    if not req.code or not req.code.strip():
        raise HTTPException(status_code=400, detail="代码内容不能为空")

    pool = _get_pool()

    try:
        async with pool.acquire() as executor:
            try:
                result = await executor.execute(
                    code=req.code,
                    language=req.language,
                    files=req.files,
                    timeout=req.timeout,
                    network_enabled=req.network_enabled,
                )
            except SandboxTimeoutError as e:
                raise HTTPException(status_code=408, detail=str(e)) from e
            except SandboxMemoryError as e:
                raise HTTPException(status_code=413, detail=str(e)) from e

    except DockerNotAvailableError as e:
        raise HTTPException(status_code=503, detail=f"Docker 服务不可用: {e.reason}") from e

    return ExecuteResponse(
        success=result.success,
        output=result.output,
        error=result.error,
        exit_code=result.exit_code,
        duration_ms=round(result.duration_ms, 2),
        killed_by_timeout=result.killed_by_timeout,
        killed_by_memory=result.killed_by_memory,
        memory_used_mb=round(result.memory_used_mb, 2),
    )


@router.post("/command", response_model=ExecuteResponse)
async def execute_command(req: CommandRequest) -> ExecuteResponse:
    """
    在 Docker 沙箱中执行 Shell 命令

    在隔离容器中执行任意 Shell 命令，适用于文件操作、包安装等场景。
    """
    if not req.command or not req.command.strip():
        raise HTTPException(status_code=400, detail="命令不能为空")

    pool = _get_pool()

    try:
        async with pool.acquire() as executor:
            try:
                result = await executor.execute_command(
                    command=req.command,
                    cwd=req.cwd,
                    timeout=req.timeout,
                )
            except SandboxTimeoutError as e:
                raise HTTPException(status_code=408, detail=str(e)) from e
            except SandboxMemoryError as e:
                raise HTTPException(status_code=413, detail=str(e)) from e

    except DockerNotAvailableError as e:
        raise HTTPException(status_code=503, detail=f"Docker 服务不可用: {e.reason}") from e

    return ExecuteResponse(
        success=result.success,
        output=result.output,
        error=result.error,
        exit_code=result.exit_code,
        duration_ms=round(result.duration_ms, 2),
        killed_by_timeout=result.killed_by_timeout,
        killed_by_memory=result.killed_by_memory,
        memory_used_mb=round(result.memory_used_mb, 2),
    )


@router.post("/build-test", response_model=ExecuteResponse)
async def build_and_test(req: BuildTestRequest) -> ExecuteResponse:
    """
    在 Docker 沙箱中构建并测试项目

    将项目文件复制到隔离容器中，执行构建和测试命令。
    适用于 CI/CD 场景的安全构建验证。
    """
    if not req.project_path or not req.project_path.strip():
        raise HTTPException(status_code=400, detail="项目路径不能为空")
    if not req.test_command or not req.test_command.strip():
        raise HTTPException(status_code=400, detail="测试命令不能为空")

    pool = _get_pool()

    try:
        async with pool.acquire() as executor:
            try:
                result = await executor.build_and_test(
                    project_path=req.project_path,
                    test_command=req.test_command,
                    timeout=req.timeout,
                )
            except SandboxTimeoutError as e:
                raise HTTPException(status_code=408, detail=str(e)) from e
            except SandboxMemoryError as e:
                raise HTTPException(status_code=413, detail=str(e)) from e

    except DockerNotAvailableError as e:
        raise HTTPException(status_code=503, detail=f"Docker 服务不可用: {e.reason}") from e

    return ExecuteResponse(
        success=result.success,
        output=result.output,
        error=result.error,
        exit_code=result.exit_code,
        duration_ms=round(result.duration_ms, 2),
        killed_by_timeout=result.killed_by_timeout,
        killed_by_memory=result.killed_by_memory,
        memory_used_mb=round(result.memory_used_mb, 2),
    )


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """获取沙箱池状态和统计信息"""
    pool = _get_pool()
    stats = pool.get_stats()

    return StatusResponse(
        docker_available=stats.docker_available,
        stats=stats.to_dict(),
    )


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_all() -> CleanupResponse:
    """清理所有沙箱容器，释放资源"""
    pool = _get_pool()

    try:
        await pool.cleanup()
        logger.info("沙箱池已清理")
        return CleanupResponse(
            success=True,
            message="所有沙箱容器已清理",
        )
    except Exception as e:
        logger.error("清理沙箱池失败: %s", e)
        raise HTTPException(status_code=500, detail=f"清理失败: {e}") from e
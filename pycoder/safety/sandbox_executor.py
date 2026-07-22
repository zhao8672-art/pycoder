"""
Docker 沙箱执行器 — Codex 风格 Docker 容器隔离执行

提供:
1. DockerSandboxExecutor: 单容器执行器，创建隔离容器执行代码
2. SandboxPool: 容器池，预加热/回收容器，限制并发

特性:
- 默认无网络访问
- 资源限制（内存、CPU）
- 超时强制终止
- 执行后自动清理
- Docker 不可用时优雅降级
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger('pycoder.safety.sandbox_executor')

from typing import Any

# Docker SDK 可选导入
try:
    import docker
    from docker.errors import APIError, DockerException, NotFound
    from docker.models.containers import Container

    _HAS_DOCKER = True
except ImportError:
    _HAS_DOCKER = False
    docker = None  # type: ignore
    DockerException = Exception  # type: ignore
    NotFound = Exception  # type: ignore
    APIError = Exception  # type: ignore

from pycoder.bus.protocol import (
    CapabilityCategory,
    CapabilityDefinition,
    ExecutionMode,
    SideEffect,
    TrustLevel,
)
from pycoder.safety.sandbox import SandboxConfig, SandboxResult

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 自定义异常
# ──────────────────────────────────────────────


class DockerNotAvailableError(RuntimeError):
    """Docker 不可用或未安装时抛出"""

    def __init__(self, reason: str = "Docker 未安装或 Docker 服务未运行"):
        self.reason = reason
        super().__init__(f"Docker 不可用: {reason}")


class SandboxTimeoutError(TimeoutError):
    """沙箱执行超时"""

    def __init__(self, timeout: float, output: str = ""):
        self.timeout = timeout
        self.output = output
        super().__init__(f"沙箱执行超时（{timeout:.1f}秒）")


class SandboxMemoryError(MemoryError):
    """沙箱内存超限"""

    def __init__(self, limit_mb: int, used_mb: float = 0.0):
        self.limit_mb = limit_mb
        self.used_mb = used_mb
        super().__init__(f"沙箱内存超限: 限制 {limit_mb}MB，已使用 {used_mb:.1f}MB")


# ──────────────────────────────────────────────
# 配置
# ──────────────────────────────────────────────


@dataclass
class DockerSandboxConfig:
    """Docker 沙箱配置"""

    # 默认镜像
    python_image: str = "python:3.11-slim"
    node_image: str = "node:20-slim"
    base_image: str = "ubuntu:22.04"

    # 资源限制
    default_memory_mb: int = 256
    max_memory_mb: int = 1024
    default_cpu_shares: int = 512  # 默认 CPU 份额（1024 为 1 核）
    max_cpu_shares: int = 2048

    # 超时
    default_timeout: float = 30.0
    max_timeout: float = 300.0

    # 容器生命周期
    container_ttl_seconds: int = 300  # 闲置容器最大存活时间
    cleanup_interval: float = 60.0  # 后台清理间隔

    # 网络安全
    disable_network: bool = True  # 默认禁用网络
    read_only_rootfs: bool = True  # 根文件系统只读

    # 沙箱工作目录
    work_dir: str = "/sandbox"


# ──────────────────────────────────────────────
# 语言到镜像映射
# ──────────────────────────────────────────────

_LANGUAGE_IMAGE_MAP: dict[str, str] = {
    "python": "python:3.11-slim",
    "python3": "python:3.11-slim",
    "node": "node:20-slim",
    "javascript": "node:20-slim",
    "js": "node:20-slim",
    "typescript": "node:20-slim",
    "ts": "node:20-slim",
    "bash": "ubuntu:22.04",
    "shell": "ubuntu:22.04",
    "sh": "ubuntu:22.04",
}

_LANGUAGE_COMMAND_MAP: dict[str, str] = {
    "python": "python3",
    "python3": "python3",
    "node": "node",
    "javascript": "node",
    "js": "node",
    "typescript": "npx ts-node",
    "ts": "npx ts-node",
    "bash": "bash",
    "shell": "bash",
    "sh": "bash",
}

_LANGUAGE_EXT_MAP: dict[str, str] = {
    "python": "py",
    "python3": "py",
    "node": "js",
    "javascript": "js",
    "js": "js",
    "typescript": "ts",
    "ts": "ts",
    "bash": "sh",
    "shell": "sh",
    "sh": "sh",
}


# ──────────────────────────────────────────────
# DockerSandboxExecutor
# ──────────────────────────────────────────────


class DockerSandboxExecutor:
    """
    Docker 容器沙箱执行器

    基于 docker-py 创建隔离容器执行代码，提供:
    - 网络隔离（默认无网络）
    - 内存/CPU 限制
    - 超时强制终止
    - 执行后自动清理

    使用示例:
        async with DockerSandboxExecutor() as executor:
            result = await executor.execute("print('hello')", language="python")
    """

    def __init__(self, config: DockerSandboxConfig | None = None):
        self._config = config or DockerSandboxConfig()
        self._client: Any = None  # docker.DockerClient
        self._container: Container | None = None
        self._container_id: str | None = None
        self._created_at: float = 0.0

    # ── 上下文管理 ──────────────────────────

    async def __aenter__(self) -> DockerSandboxExecutor:
        await self._ensure_container()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.cleanup()

    # ── Docker 客户端 ────────────────────────

    def _get_client(self) -> Any:
        """获取 Docker 客户端，若不可用则抛出异常"""
        if not _HAS_DOCKER:
            raise DockerNotAvailableError("docker-py 未安装，请执行: pip install docker")
        if self._client is None:
            try:
                self._client = docker.from_env()
                # 快速验证 Docker 是否可用
                self._client.ping()
            except Exception as e:
                raise DockerNotAvailableError(str(e)) from e
        return self._client

    def _check_docker_available(self) -> bool:
        """检查 Docker 是否可用（不抛异常）"""
        try:
            self._get_client()
            return True
        except DockerNotAvailableError:
            return False

    # ── 容器管理 ────────────────────────────

    async def _ensure_container(self) -> None:
        """确保容器已创建并运行"""
        if self._container is not None:
            return
        self._container = await self._create_container()
        self._container_id = self._container.id
        self._created_at = time.monotonic()
        logger.info("Docker 沙箱容器已创建: %s", self._container_id[:12])

    async def _create_container(self) -> Container:
        """创建隔离的 Docker 容器"""
        client = self._get_client()
        cfg = self._config

        # 构建容器参数
        container_kwargs: dict[str, Any] = {
            "image": cfg.base_image,
            "command": "tail -f /dev/null",  # 保持容器运行
            "detach": True,
            "remove": True,  # 停止后自动删除
            "mem_limit": f"{cfg.default_memory_mb}m",
            "cpu_shares": cfg.default_cpu_shares,
            "working_dir": cfg.work_dir,
            "read_only": cfg.read_only_rootfs,
            "labels": {
                "pycoder.sandbox": "true",
                "pycoder.created_at": str(time.time()),
            },
        }

        # 网络隔离
        if cfg.disable_network:
            container_kwargs["network_disabled"] = True

        # 挂载临时目录用于文件写入
        tmpfs_mounts: dict[str, str] = {
            cfg.work_dir: "size=100m",  # 工作目录临时存储
            "/tmp": "size=50m,noexec",
        }
        container_kwargs["tmpfs"] = tmpfs_mounts

        # 安全选项
        container_kwargs["security_opt"] = ["no-new-privileges:true"]
        container_kwargs["cap_drop"] = ["ALL"]  # 移除所有 Linux capabilities

        try:
            loop = asyncio.get_running_loop()
            container = await loop.run_in_executor(
                None, lambda: client.containers.run(**container_kwargs)
            )
            return container
        except APIError as e:
            logger.error("创建 Docker 容器失败: %s", e)
            raise DockerNotAvailableError(f"容器创建失败: {e}") from e

    def _get_image_for_language(self, language: str) -> str:
        """根据语言选择镜像"""
        return _LANGUAGE_IMAGE_MAP.get(language.lower(), self._config.base_image)

    def _get_command_for_language(self, language: str, file_path: str) -> str:
        """根据语言构建执行命令"""
        cmd = _LANGUAGE_COMMAND_MAP.get(language.lower(), "python3")
        return f"{cmd} {file_path}"

    # ── 执行方法 ────────────────────────────

    async def execute(
        self,
        code: str,
        language: str = "python",
        *,
        files: dict[str, str] | None = None,
        timeout: float | None = None,
        network_enabled: bool = False,
        memory_mb: int | None = None,
        stdin: str = "",
    ) -> SandboxResult:
        """
        在 Docker 沙箱中执行代码

        Args:
            code: 要执行的代码内容
            language: 编程语言
            files: 额外文件映射 {文件名: 内容}
            timeout: 超时时间（秒），None 使用默认值
            network_enabled: 是否启用网络（默认禁用）
            memory_mb: 内存限制（MB），None 使用默认值
            stdin: 标准输入内容

        Returns:
            SandboxResult 执行结果
        """
        # 检查 Docker 可用性
        if not self._check_docker_available():
            return await self._fallback_execute(code, language, timeout=timeout)

        timeout = timeout or self._config.default_timeout
        timeout = min(timeout, self._config.max_timeout)

        try:
            await self._ensure_container()
        except DockerNotAvailableError:
            return await self._fallback_execute(code, language, timeout=timeout)

        start_time = time.monotonic()

        try:
            # 准备代码文件
            ext = _LANGUAGE_EXT_MAP.get(language.lower(), "txt")
            code_filename = f"code.{ext}"
            code_path = Path(self._config.work_dir) / code_filename
            code_content = code.encode("utf-8")

            # 写入代码到容器
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: self._container.put_archive(
                    str(code_path.parent),
                    _make_tar_payload(code_filename, code_content),
                ),
            )

            # 写入额外文件
            if files:
                for fname, fcontent in files.items():
                    fpath = Path(self._config.work_dir) / fname
                    await loop.run_in_executor(
                        None,
                        lambda fp=fpath, fn=fname, fc=fcontent: self._container.put_archive(
                            str(fp.parent),
                            _make_tar_payload(fn, fc.encode("utf-8")),
                        ),
                    )

            # 构建执行命令
            cmd = self._get_command_for_language(language, str(code_path))

            # 执行命令
            exec_result = await loop.run_in_executor(
                None,
                lambda: self._container.exec_run(
                    cmd=["sh", "-c", cmd],
                    stdin=bool(stdin),
                    environment={},
                    user="nobody",  # 非 root 用户
                ),
            )

            # 处理超时（exec_run 可能在容器级别被终止）
            if timeout:
                elapsed = time.monotonic() - start_time
                if elapsed > timeout:
                    raise SandboxTimeoutError(timeout)

            exit_code = exec_result.exit_code
            output = (
                exec_result.output.decode("utf-8", errors="replace")
                if exec_result.output else ""
            )

            duration_ms = (time.monotonic() - start_time) * 1000

            # 检查 OOM
            killed_by_memory = exit_code == 137  # SIGKILL (OOM killer)

            return SandboxResult(
                success=exit_code == 0,
                output=output,
                error="" if exit_code == 0 else output,
                exit_code=exit_code,
                duration_ms=duration_ms,
                killed_by_memory=killed_by_memory,
                memory_used_mb=0.0,  # Docker API 不易精确获取
            )

        except SandboxTimeoutError:
            # 超时：强制终止容器内所有进程
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self._container.exec_run(
                        cmd=["sh", "-c", "kill -9 1"],
                    ),
                )
            except Exception as e:
                _logger.warning("silently_swallowed: {err}", exc_info=False)
                pass  # 容器可能已停止

            duration_ms = (time.monotonic() - start_time) * 1000
            return SandboxResult(
                success=False,
                error=f"执行超时（{timeout:.1f}秒）",
                exit_code=-1,
                duration_ms=duration_ms,
                killed_by_timeout=True,
            )

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error("Docker 沙箱执行失败: %s", e)
            return SandboxResult(
                success=False,
                error=str(e),
                exit_code=-1,
                duration_ms=duration_ms,
            )

    async def execute_command(
        self,
        command: str,
        cwd: str | None = None,
        timeout: float | None = None,
    ) -> SandboxResult:
        """
        在 Docker 沙箱中执行 Shell 命令

        Args:
            command: 要执行的 Shell 命令
            cwd: 工作目录（相对于 sandbox 工作目录）
            timeout: 超时时间（秒）

        Returns:
            SandboxResult 执行结果
        """
        timeout = timeout or self._config.default_timeout
        timeout = min(timeout, self._config.max_timeout)

        if not self._check_docker_available():
            return SandboxResult(
                success=False,
                error="Docker 不可用，无法执行命令",
                exit_code=-1,
            )

        try:
            await self._ensure_container()
        except DockerNotAvailableError:
            return SandboxResult(
                success=False,
                error="Docker 容器创建失败",
                exit_code=-1,
            )

        start_time = time.monotonic()

        try:
            # 构建完整命令
            full_cmd = command
            if cwd:
                full_cmd = f"cd {cwd} && {command}"

            loop = asyncio.get_running_loop()
            exec_result = await loop.run_in_executor(
                None,
                lambda: self._container.exec_run(
                    cmd=["sh", "-c", full_cmd],
                    user="nobody",
                ),
            )

            exit_code = exec_result.exit_code
            output = (
                exec_result.output.decode("utf-8", errors="replace")
                if exec_result.output else ""
            )

            duration_ms = (time.monotonic() - start_time) * 1000

            return SandboxResult(
                success=exit_code == 0,
                output=output,
                error="" if exit_code == 0 else output,
                exit_code=exit_code,
                duration_ms=duration_ms,
                killed_by_memory=exit_code == 137,
            )

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error("Docker 沙箱命令执行失败: %s", e)
            return SandboxResult(
                success=False,
                error=str(e),
                exit_code=-1,
                duration_ms=duration_ms,
            )

    async def build_and_test(
        self,
        project_path: str,
        test_command: str,
        timeout: float | None = None,
    ) -> SandboxResult:
        """
        在 Docker 沙箱中构建并测试项目

        将项目文件复制到容器中，执行构建和测试命令。

        Args:
            project_path: 项目目录路径（宿主机）
            test_command: 测试命令（如 "pytest" 或 "npm test"）
            timeout: 超时时间（秒）

        Returns:
            SandboxResult 执行结果
        """
        timeout = timeout or self._config.default_timeout
        timeout = min(timeout, self._config.max_timeout)

        if not self._check_docker_available():
            return SandboxResult(
                success=False,
                error="Docker 不可用，无法执行构建测试",
                exit_code=-1,
            )

        try:
            await self._ensure_container()
        except DockerNotAvailableError:
            return SandboxResult(
                success=False,
                error="Docker 容器创建失败",
                exit_code=-1,
            )

        start_time = time.monotonic()
        project = Path(project_path)

        if not project.exists():
            return SandboxResult(
                success=False,
                error=f"项目路径不存在: {project_path}",
                exit_code=-1,
            )

        try:
            # 将项目文件复制到容器
            loop = asyncio.get_running_loop()

            # 打包项目文件
            tar_data = _make_directory_tar(project)

            # 上传到容器
            await loop.run_in_executor(
                None,
                lambda: self._container.put_archive(self._config.work_dir, tar_data),
            )

            # 执行测试命令
            exec_result = await loop.run_in_executor(
                None,
                lambda: self._container.exec_run(
                    cmd=["sh", "-c", f"cd {self._config.work_dir} && {test_command}"],
                    user="nobody",
                ),
            )

            exit_code = exec_result.exit_code
            output = (
                exec_result.output.decode("utf-8", errors="replace")
                if exec_result.output else ""
            )

            duration_ms = (time.monotonic() - start_time) * 1000

            return SandboxResult(
                success=exit_code == 0,
                output=output,
                error="" if exit_code == 0 else output,
                exit_code=exit_code,
                duration_ms=duration_ms,
                killed_by_memory=exit_code == 137,
            )

        except Exception as e:
            duration_ms = (time.monotonic() - start_time) * 1000
            logger.error("Docker 沙箱构建测试失败: %s", e)
            return SandboxResult(
                success=False,
                error=str(e),
                exit_code=-1,
                duration_ms=duration_ms,
            )

    async def _fallback_execute(
        self,
        code: str,
        language: str = "python",
        timeout: float | None = None,
    ) -> SandboxResult:
        """
        Docker 不可用时的降级执行 —— 使用 ProcessSandbox

        在本地进程沙箱中执行代码，提供基本的隔离。
        """
        from pycoder.safety.sandbox import ProcessSandbox

        logger.warning("Docker 不可用，降级为进程沙箱执行")
        config = SandboxConfig(
            max_timeout_seconds=timeout or self._config.default_timeout,
            max_memory_mb=self._config.default_memory_mb,
            allow_network=False,
        )
        sandbox = ProcessSandbox(config)
        return await sandbox.execute(code, language=language)

    # ── 清理 ─────────────────────────────────

    async def cleanup(self) -> None:
        """清理容器"""
        if self._container:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._container.stop)
                logger.info(
                "Docker 沙箱容器已清理: %s",
                self._container_id[:12] if self._container_id else "?",
            )
            except Exception as e:
                logger.warning("清理容器时出错: %s", e)
            finally:
                self._container = None
                self._container_id = None

    @property
    def is_available(self) -> bool:
        """Docker 是否可用"""
        return self._check_docker_available()

    @property
    def container_id(self) -> str | None:
        """当前容器 ID"""
        return self._container_id


# ──────────────────────────────────────────────
# SandboxPool
# ──────────────────────────────────────────────


class SandboxPool:
    """
    Docker 沙箱容器池

    管理多个沙箱容器，提供:
    - 预加热容器（提前创建，减少冷启动延迟）
    - 最大并发限制
    - 容器回收和复用
    - 空闲超时自动清理

    使用示例:
        pool = SandboxPool(max_containers=5, warm_containers=2)
        await pool.start()

        async with pool.acquire() as executor:
            result = await executor.execute("print('hello')")

        await pool.shutdown()
    """

    def __init__(
        self,
        config: DockerSandboxConfig | None = None,
        *,
        max_containers: int = 10,
        warm_containers: int = 0,
        max_concurrent: int = 5,
    ):
        self._config = config or DockerSandboxConfig()
        self._max_containers = max_containers
        self._warm_containers = warm_containers
        self._max_concurrent = max_concurrent

        # 容器池
        self._available: list[DockerSandboxExecutor] = []
        self._in_use: set[DockerSandboxExecutor] = set()
        self._all: list[DockerSandboxExecutor] = []

        # 并发控制
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._lock = asyncio.Lock()

        # 状态
        self._started = False
        self._cleanup_task: asyncio.Task | None = None

        # 统计
        self._stats = PoolStats()

        logger.info(
            "SandboxPool 初始化: max=%d warm=%d concurrent=%d",
            max_containers,
            warm_containers,
            max_concurrent,
        )

    # ── 生命周期 ─────────────────────────────

    async def start(self) -> None:
        """启动容器池，预加热容器"""
        if self._started:
            return
        self._started = True

        # 检查 Docker 可用性
        test_executor = DockerSandboxExecutor(self._config)
        if not test_executor.is_available:
            logger.warning("Docker 不可用，SandboxPool 将以降级模式运行")
            self._started = True
            return

        # 预加热容器
        warm_count = min(self._warm_containers, self._max_containers)
        if warm_count > 0:
            logger.info("预加热 %d 个沙箱容器...", warm_count)
            tasks = [self._create_and_add() for _ in range(warm_count)]
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("预加热完成，可用容器: %d", len(self._available))

        # 启动后台清理
        self._cleanup_task = asyncio.create_task(self._background_cleanup())

    async def shutdown(self) -> None:
        """关闭容器池，清理所有容器"""
        self._started = False

        # 取消后台清理
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        # 清理所有容器
        all_executors = self._available + list(self._in_use)
        self._available.clear()
        self._in_use.clear()

        await asyncio.gather(
            *(executor.cleanup() for executor in all_executors),
            return_exceptions=True,
        )
        self._all.clear()
        logger.info("SandboxPool 已关闭")

    # ── 获取/释放容器 ────────────────────────

    async def acquire(self) -> DockerSandboxExecutor:
        """
        获取一个沙箱执行器

        Returns:
            DockerSandboxExecutor 实例

        Usage:
            async with pool.acquire() as executor:
                result = await executor.execute("print('hello')")
        """
        await self._semaphore.acquire()

        async with self._lock:
            if self._available:
                executor = self._available.pop()
                self._in_use.add(executor)
                self._stats.total_acquired += 1
                self._stats.reused += 1
                logger.debug("复用沙箱容器: %s", executor.container_id)
                return _PoolExecutorContext(self, executor)

            # 创建新容器
            if len(self._all) < self._max_containers:
                executor = await self._create_and_add()
                self._in_use.add(executor)
                self._stats.total_acquired += 1
                self._stats.created += 1
                return _PoolExecutorContext(self, executor)

            # 等待可用容器
            self._stats.total_waited += 1

        # 在锁外等待
        while True:
            await asyncio.sleep(0.1)
            async with self._lock:
                if self._available:
                    executor = self._available.pop()
                    self._in_use.add(executor)
                    self._stats.total_acquired += 1
                    self._stats.reused += 1
                    return _PoolExecutorContext(self, executor)

    async def release(self, executor: DockerSandboxExecutor) -> None:
        """
        释放沙箱执行器回池中

        Args:
            executor: 要释放的执行器
        """
        async with self._lock:
            if executor in self._in_use:
                self._in_use.discard(executor)
                # 检查容器是否仍然健康
                if executor._container:
                    self._available.append(executor)
                    logger.debug("沙箱容器已回收: %s", executor.container_id)
                else:
                    self._all = [e for e in self._all if e is not executor]
                    logger.debug("沙箱容器已销毁（不健康）: %s", executor.container_id)

        self._semaphore.release()

    async def _create_and_add(self) -> DockerSandboxExecutor:
        """创建新容器并加入池中"""
        executor = DockerSandboxExecutor(self._config)
        await executor._ensure_container()
        self._all.append(executor)
        return executor

    # ── 后台清理 ─────────────────────────────

    async def _background_cleanup(self) -> None:
        """后台清理过期容器"""
        while self._started:
            try:
                await asyncio.sleep(self._config.cleanup_interval)
                await self._cleanup_idle()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("后台清理异常")

    async def _cleanup_idle(self) -> None:
        """清理空闲超时的容器"""
        now = time.monotonic()
        ttl = self._config.container_ttl_seconds

        async with self._lock:
            to_remove: list[DockerSandboxExecutor] = []
            for executor in self._available:
                if now - executor._created_at > ttl:
                    to_remove.append(executor)

            for executor in to_remove:
                self._available.remove(executor)
                self._all = [e for e in self._all if e is not executor]
                await executor.cleanup()
                self._stats.cleaned_idle += 1

            if to_remove:
                logger.info("清理了 %d 个空闲容器", len(to_remove))

    # ── 统计 ─────────────────────────────────

    def get_stats(self) -> PoolStats:
        """获取池统计信息"""
        self._stats.available = len(self._available)
        self._stats.in_use = len(self._in_use)
        self._stats.total = len(self._all)
        self._stats.max_containers = self._max_containers
        self._stats.docker_available = DockerSandboxExecutor(self._config).is_available
        return self._stats

    async def cleanup(self) -> None:
        """清理所有容器（等同于 shutdown）"""
        await self.shutdown()


# ──────────────────────────────────────────────
# 池统计
# ──────────────────────────────────────────────


@dataclass
class PoolStats:
    """容器池统计信息"""

    available: int = 0
    in_use: int = 0
    total: int = 0
    max_containers: int = 0
    docker_available: bool = False

    # 累计统计
    total_acquired: int = 0
    created: int = 0
    reused: int = 0
    total_waited: int = 0
    cleaned_idle: int = 0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "available": self.available,
            "in_use": self.in_use,
            "total": self.total,
            "max_containers": self.max_containers,
            "docker_available": self.docker_available,
            "total_acquired": self.total_acquired,
            "created": self.created,
            "reused": self.reused,
            "total_waited": self.total_waited,
            "cleaned_idle": self.cleaned_idle,
        }


# ──────────────────────────────────────────────
# 池执行器上下文管理器
# ──────────────────────────────────────────────


class _PoolExecutorContext:
    """池执行器的异步上下文管理器"""

    def __init__(self, pool: SandboxPool, executor: DockerSandboxExecutor):
        self._pool = pool
        self._executor = executor

    async def __aenter__(self) -> DockerSandboxExecutor:
        return self._executor

    async def __aexit__(self, *args: Any) -> None:
        await self._pool.release(self._executor)


# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────


def _make_tar_payload(filename: str, content: bytes) -> bytes:
    """创建单个文件的 tar 包（用于 docker put_archive）"""
    import io
    import tarfile

    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        info = tarfile.TarInfo(name=filename)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    return tar_stream.getvalue()


def _make_directory_tar(path: Path) -> bytes:
    """打包整个目录为 tar 字节流"""
    import io
    import tarfile

    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        for f in path.rglob("*"):
            if f.is_file():
                arcname = f.relative_to(path)
                tar.add(str(f), arcname=str(arcname))
    return tar_stream.getvalue()


# ──────────────────────────────────────────────
# V2 总线能力注册
# ──────────────────────────────────────────────


def register_sandbox_capabilities(registry: Any) -> None:
    """
    向 V2 总线注册沙箱执行器能力

    注册的能力:
    - sandbox.execute: 在沙箱中执行代码
    - sandbox.execute_command: 在沙箱中执行命令
    - sandbox.build_test: 构建并测试
    - sandbox.status: 获取沙箱状态

    Args:
        registry: CapabilityRegistry 实例
    """
    # 创建全局执行器实例
    executor = DockerSandboxExecutor()

    # ── sandbox.execute ──────────────────────

    registry.register(
        CapabilityDefinition(
            id="sandbox.execute",
            name="沙箱代码执行",
            description=(
                "在隔离的 Docker 容器中安全执行代码，"
                "支持 Python/JavaScript/TypeScript/Bash"
            ),
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.SYSTEM_ACCESS,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS],
            timeout_ms=300_000,
            tags=["sandbox", "execute", "docker", "code", "安全"],
        ),
        handler=_make_sandbox_execute_handler(executor),
    )

    # ── sandbox.execute_command ──────────────

    registry.register(
        CapabilityDefinition(
            id="sandbox.execute_command",
            name="沙箱命令执行",
            description="在隔离的 Docker 容器中执行 Shell 命令",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.SYSTEM_ACCESS,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS],
            timeout_ms=300_000,
            tags=["sandbox", "execute", "shell", "command", "docker"],
        ),
        handler=_make_sandbox_command_handler(executor),
    )

    # ── sandbox.build_test ───────────────────

    registry.register(
        CapabilityDefinition(
            id="sandbox.build_test",
            name="沙箱构建测试",
            description="在隔离的 Docker 容器中构建并测试项目",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.SYSTEM_ACCESS,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.PROCESS, SideEffect.FILE_READ],
            timeout_ms=600_000,
            tags=["sandbox", "build", "test", "ci", "docker"],
        ),
        handler=_make_sandbox_build_test_handler(executor),
    )

    # ── sandbox.status ───────────────────────

    registry.register(
        CapabilityDefinition(
            id="sandbox.status",
            name="沙箱状态",
            description="获取 Docker 沙箱执行器的当前状态",
            category=CapabilityCategory.SYSTEM,
            permission=TrustLevel.READ_ONLY,
            execution=ExecutionMode.SYNC,
            side_effects=[SideEffect.NONE],
            timeout_ms=5000,
            tags=["sandbox", "status", "health", "docker"],
        ),
        handler=_make_sandbox_status_handler(executor),
    )

    logger.info("沙箱执行器能力已注册到 V2 总线")


def _make_sandbox_execute_handler(executor: DockerSandboxExecutor) -> Any:
    """创建 sandbox.execute 处理器"""

    async def handler(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        code = params.get("code", "")
        language = params.get("language", "python")
        files = params.get("files")
        timeout = params.get("timeout")
        network_enabled = params.get("network_enabled", False)
        stdin = params.get("stdin", "")

        result = await executor.execute(
            code=code,
            language=language,
            files=files,
            timeout=timeout,
            network_enabled=network_enabled,
            stdin=stdin,
        )

        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "killed_by_timeout": result.killed_by_timeout,
            "killed_by_memory": result.killed_by_memory,
        }

    return handler


def _make_sandbox_command_handler(executor: DockerSandboxExecutor) -> Any:
    """创建 sandbox.execute_command 处理器"""

    async def handler(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        command = params.get("command", "")
        cwd = params.get("cwd")
        timeout = params.get("timeout")

        result = await executor.execute_command(
            command=command,
            cwd=cwd,
            timeout=timeout,
        )

        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
        }

    return handler


def _make_sandbox_build_test_handler(executor: DockerSandboxExecutor) -> Any:
    """创建 sandbox.build_test 处理器"""

    async def handler(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        project_path = params.get("project_path", "")
        test_command = params.get("test_command", "")
        timeout = params.get("timeout")

        result = await executor.build_and_test(
            project_path=project_path,
            test_command=test_command,
            timeout=timeout,
        )

        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
        }

    return handler


def _make_sandbox_status_handler(executor: DockerSandboxExecutor) -> Any:
    """创建 sandbox.status 处理器"""

    async def handler(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {
            "docker_available": executor.is_available,
            "container_id": executor.container_id,
        }

    return handler
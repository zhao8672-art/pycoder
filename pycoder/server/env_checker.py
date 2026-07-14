"""
环境能力检测器 — 自动检测本地环境支持，实现优雅降级

检测范围:
  - Docker daemon 可用性
  - kubectl 和 K8s 集群连接
  - alembic / 数据库迁移工具
  - Node.js / npm
  - Git
  - 系统包管理器

使用方式:
    checker = get_env_checker()
    caps = checker.get_capabilities()  # 获取所有能力状态
    if checker.has("docker"):
        # 执行 Docker 操作
    else:
        # 降级到本地模式
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EnvCapability:
    """单个环境能力"""

    name: str
    available: bool = False
    version: str = ""
    error: str = ""
    checked_at: float = 0.0
    hint: str = ""  # 降级提示


@dataclass
class EnvCapabilities:
    """环境能力清单"""

    docker: EnvCapability = field(default_factory=lambda: EnvCapability(name="docker"))
    kubectl: EnvCapability = field(default_factory=lambda: EnvCapability(name="kubectl"))
    alembic: EnvCapability = field(default_factory=lambda: EnvCapability(name="alembic"))
    node: EnvCapability = field(default_factory=lambda: EnvCapability(name="node"))
    git: EnvCapability = field(default_factory=lambda: EnvCapability(name="git"))
    make: EnvCapability = field(default_factory=lambda: EnvCapability(name="make"))
    curl: EnvCapability = field(default_factory=lambda: EnvCapability(name="curl"))
    docker_compose: EnvCapability = field(
        default_factory=lambda: EnvCapability(name="docker_compose"),
    )

    def to_dict(self) -> dict:
        result = {}
        for name, cap in self.__dict__.items():
            if isinstance(cap, EnvCapability):
                result[name] = {
                    "available": cap.available,
                    "version": cap.version,
                    "hint": cap.hint,
                }
        return result

    def summary(self) -> list[dict]:
        """返回适合前端展示的概要列表"""
        return [
            {
                "name": cap.name,
                "available": cap.available,
                "version": cap.version,
                "hint": cap.hint,
            }
            for cap in self.__dict__.values()
            if isinstance(cap, EnvCapability)
        ]


class EnvChecker:
    """环境能力检测器，带缓存"""

    _CACHE_TTL = 30.0  # 缓存有效期（秒）

    def __init__(self):
        self._cache: EnvCapabilities | None = None
        self._last_checked = 0.0

    def has(self, name: str) -> bool:
        """快速检查某个能力是否可用"""
        caps = self.get_capabilities()
        return getattr(caps, name, EnvCapability(name="")).available

    def _check_binary(self, name: str, version_flag: str = "--version") -> EnvCapability:
        """通用：检测二进制工具是否存在并获取版本"""
        cap = EnvCapability(name=name)
        path = shutil.which(name)
        if not path:
            cap.available = False
            cap.hint = f"未找到 {name}，请安装后重试"
            return cap

        try:
            r = subprocess.run(
                [name, version_flag],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0:
                cap.available = True
                cap.version = r.stdout.strip().split("\n")[0][:50]
            else:
                cap.available = False
                cap.error = r.stderr.strip()[:100]
                cap.hint = f"{name} 存在但执行失败: {cap.error}"
        except FileNotFoundError:
            cap.available = False
            cap.hint = f"未找到 {name}"
        except subprocess.TimeoutExpired:
            cap.available = False
            cap.hint = f"{name} 超时"
        except Exception as e:
            cap.available = False
            cap.error = str(e)[:100]

        return cap

    def _check_docker(self) -> EnvCapability:
        """检测 Docker daemon 是否可访问"""
        cap = EnvCapability(name="docker")
        path = shutil.which("docker")
        if not path:
            cap.hint = "Docker 未安装，容器功能将降级为本地执行"
            return cap

        try:
            r = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                cap.available = True
                cap.version = f"Docker {r.stdout.strip()}"
            else:
                cap.hint = "Docker daemon 未运行，容器功能将降级为本地执行"
        except subprocess.TimeoutExpired:
            cap.hint = "Docker daemon 响应超时，容器功能将降级为本地执行"
        except Exception as e:
            cap.hint = f"Docker 不可用: {str(e)[:60]}，降级为本地执行"

        return cap

    def _check_docker_compose(self) -> EnvCapability:
        """检测 docker compose 插件"""
        cap = EnvCapability(name="docker_compose")
        # docker compose 是 Docker CLI 插件
        if not shutil.which("docker"):
            cap.hint = "Docker Compose 不可用（Docker 未安装）"
            return cap
        try:
            r = subprocess.run(
                ["docker", "compose", "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                cap.available = True
                cap.version = r.stdout.strip()[:50]
            else:
                cap.hint = "Docker Compose 不可用，多容器部署将降级为单容器或本地"
        except Exception:
            cap.hint = "Docker Compose 不可用"
        return cap

    def get_capabilities(self, force: bool = False) -> EnvCapabilities:
        """获取环境能力清单（带缓存）"""
        now = time.time()
        if self._cache is not None and not force and (now - self._last_checked) < self._CACHE_TTL:
            return self._cache

        caps = EnvCapabilities()

        # 并行检测所有能力
        caps.docker = self._check_docker()
        caps.docker_compose = self._check_docker_compose()
        caps.kubectl = self._check_binary("kubectl")
        caps.alembic = self._check_binary("alembic")
        caps.node = self._check_binary("node", "--version")
        caps.git = self._check_binary("git")
        caps.make = self._check_binary("make")
        caps.curl = self._check_binary("curl")

        # 补充降级提示
        if not caps.kubectl.available:
            caps.kubectl.hint = caps.kubectl.hint or "kubectl 未安装，K8s 部署功能将不可用"
        if not caps.alembic.available:
            caps.alembic.hint = (
                caps.alembic.hint or "alembic 未安装，数据库迁移功能将降级为手动 SQL"
            )

        self._cache = caps
        self._last_checked = now
        return caps


# 全局单例
_checker: EnvChecker | None = None


def get_env_checker() -> EnvChecker:
    """获取全局环境检测器"""
    global _checker
    if _checker is None:
        _checker = EnvChecker()
    return _checker

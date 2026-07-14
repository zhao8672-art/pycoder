"""
虚拟环境管理器 — 自动创建/切换/检测 Python venv

功能:
- 自动检测当前 venv/conda/poetry 环境
- 创建新 venv (含依赖安装)
- 激活/切换 venv
- 列出系统中的所有 venv
- 与 pycoder 项目启动集成
"""

from __future__ import annotations

import os
import subprocess
import sys
import venv
from dataclasses import dataclass, field
from pathlib import Path

# ── 数据模型 ──────────────────────────────────────────────


@dataclass
class VirtualEnv:
    """虚拟环境描述"""

    name: str
    path: Path
    env_type: str  # "venv" | "conda" | "poetry" | "pipenv" | "virtualenv"
    python_version: str = ""
    python_path: str = ""
    packages: list[str] = field(default_factory=list)
    active: bool = False

    def activate_script(self) -> Path | None:
        """获取激活脚本路径"""
        if self.env_type == "venv" or self.env_type == "virtualenv":
            if sys.platform == "win32":
                script = self.path / "Scripts" / "activate"
            else:
                script = self.path / "bin" / "activate"
            return script if script.exists() else None
        return None

    def python_exe(self) -> Path | None:
        """获取 Python 可执行文件路径"""
        if sys.platform == "win32":
            exe = self.path / "Scripts" / "python.exe"
        else:
            exe = self.path / "bin" / "python"
        return exe if exe.exists() else None


# ── 环境检测 ─────────────────────────────────────────────


def detect_current_venv() -> VirtualEnv:
    """检测当前活跃的虚拟环境"""
    venv_path = os.environ.get("VIRTUAL_ENV")
    conda_env = os.environ.get("CONDA_DEFAULT_ENV")
    os.environ.get("POETRY_ACTIVE")

    if venv_path:
        path = Path(venv_path)
        return VirtualEnv(
            name=path.name,
            path=path,
            env_type="venv",
            python_version=sys.version.split()[0],
            python_path=sys.executable,
            active=True,
        )

    if conda_env:
        conda_prefix = os.environ.get("CONDA_PREFIX", "")
        return VirtualEnv(
            name=conda_env,
            path=Path(conda_prefix) if conda_prefix else Path(),
            env_type="conda",
            python_version=sys.version.split()[0],
            python_path=sys.executable,
            active=True,
        )

    # 系统 Python（不是虚拟环境）
    return VirtualEnv(
        name="system",
        path=Path(sys.prefix),
        env_type="system",
        python_version=sys.version.split()[0],
        python_path=sys.executable,
        active=False,
    )


def list_venvs(search_paths: list[str | Path] = None) -> list[VirtualEnv]:
    """
    列出系统中所有虚拟环境。

    扫描路径:
    - 当前工作目录
    - 常用 venv 目录 (~/venvs, ~/.venvs, ~/miniconda3/envs, ~/anaconda3/envs)
    """
    if search_paths is None:
        search_paths = [
            Path.cwd(),
            Path.home() / "venvs",
            Path.home() / ".venvs",
            Path.home() / "miniconda3" / "envs",
            Path.home() / "anaconda3" / "envs",
        ]

    venvs = []
    seen = set()

    # 当前活跃环境
    current = detect_current_venv()
    if current.env_type != "system":
        venvs.append(current)
        seen.add(str(current.path))

    # 扫描目录
    for base in search_paths:
        base = Path(base)
        if not base.exists():
            continue

        if base.name == "envs":
            # conda envs 目录
            for d in base.iterdir():
                if d.is_dir() and str(d) not in seen:
                    venvs.append(
                        VirtualEnv(
                            name=d.name,
                            path=d,
                            env_type="conda",
                        )
                    )
                    seen.add(str(d))
        else:
            # 查找 .venv / venv / .*env 等
            for pattern in [".venv", "venv", ".env", "*env*"]:
                for d in base.rglob(pattern):
                    if d.is_dir() and str(d) not in seen:
                        py_exe = (
                            d / "Scripts" / "python.exe"
                            if sys.platform == "win32"
                            else d / "bin" / "python"
                        )
                        if py_exe.exists():
                            venvs.append(
                                VirtualEnv(
                                    name=(
                                        d.parent.name + "/" + d.name if d.parent != base else d.name
                                    ),
                                    path=d,
                                    env_type="venv",
                                    python_path=str(py_exe),
                                )
                            )
                            seen.add(str(d))

    return venvs


# ── 创建 venv ────────────────────────────────────────────


def create_venv(
    name: str = ".venv",
    path: str | Path = None,
    python: str = None,
    requirements: str | Path = None,
    packages: list[str] = None,
) -> VirtualEnv:
    """
    创建新的虚拟环境。

    Args:
        name: 环境名称（默认 .venv）
        path: 创建路径（默认当前目录）
        python: Python 解释器路径（默认当前 Python）
        requirements: requirements.txt 路径
        packages: 要安装的包列表

    Returns:
        创建的虚拟环境描述
    """
    if path is None:
        path = Path.cwd()
    path = Path(path)
    venv_path = path / name

    if venv_path.exists():
        raise FileExistsError(f"虚拟环境已存在: {venv_path}")

    # 创建 venv
    builder = venv.EnvBuilder(
        with_pip=True,
        upgrade_deps=True,
        clear=False,
    )
    builder.create(str(venv_path))

    # 确定 pip 路径
    if sys.platform == "win32":
        pip = str(venv_path / "Scripts" / "pip.exe")
        py = str(venv_path / "Scripts" / "python.exe")
    else:
        pip = str(venv_path / "bin" / "pip")
        py = str(venv_path / "bin" / "python")

    # 安装依赖
    installed = []

    if requirements:
        req_path = Path(requirements)
        if req_path.exists():
            result = subprocess.run(
                [pip, "install", "-r", str(req_path)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                installed.append(f"requirements: {req_path.name}")

    if packages:
        result = subprocess.run(
            [pip, "install"] + list(packages),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            installed.extend(packages)

    return VirtualEnv(
        name=name,
        path=venv_path,
        env_type="venv",
        python_path=py,
        packages=installed,
        active=False,
    )


# ── 依赖安装 ─────────────────────────────────────────────


def install_package(
    package: str,
    venv_path: str | Path | None = None,
    upgrade: bool = False,
) -> dict:
    """
    在指定或当前 venv 中安装包。

    Returns:
        {"success": bool, "package": str, "output": str}
    """
    if venv_path:
        venv_path = Path(venv_path)
        if sys.platform == "win32":
            pip = str(venv_path / "Scripts" / "pip.exe")
        else:
            pip = str(venv_path / "bin" / "pip")
    else:
        pip = [sys.executable, "-m", "pip"]

    cmd = [pip, "install"]
    if upgrade:
        cmd.append("--upgrade")
    cmd.append(package)

    if isinstance(pip, list):
        cmd = pip + ["install"] + (["--upgrade"] if upgrade else []) + [package]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {
            "success": result.returncode == 0,
            "package": package,
            "output": result.stdout[-2000:] + result.stderr[-1000:],
        }
    except Exception as e:
        return {"success": False, "package": package, "output": str(e)}


def install_requirements(
    req_file: str | Path,
    venv_path: str | Path | None = None,
) -> dict:
    """安装 requirements.txt"""
    req_file = Path(req_file)
    if not req_file.exists():
        return {"success": False, "error": f"文件不存在: {req_file}"}

    if venv_path:
        venv_path = Path(venv_path)
        if sys.platform == "win32":
            pip = str(venv_path / "Scripts" / "pip.exe")
        else:
            pip = str(venv_path / "bin" / "pip")
    else:
        pip = [sys.executable, "-m", "pip"]

    cmd = [pip, "install", "-r", str(req_file)]
    if isinstance(pip, list):
        cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return {
            "success": result.returncode == 0,
            "output": result.stdout[-3000:],
            "error": result.stderr[-1000:] if result.stderr else "",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── 环境切换（生成 shell 命令） ────────────────────────────


def get_activate_command(venv: VirtualEnv) -> str:
    """生成激活命令"""
    if venv.env_type == "venv" or venv.env_type == "virtualenv":
        if sys.platform == "win32":
            return f"{venv.path}\\Scripts\\activate"
        return f"source {venv.path}/bin/activate"
    elif venv.env_type == "conda":
        return f"conda activate {venv.name}"
    elif venv.env_type == "poetry":
        return "poetry shell"
    return "# 系统 Python，无需激活"


def switch_venv(venv: VirtualEnv) -> dict:
    """
    在当前进程中切换到指定 venv（修改 sys.path 和环境变量）。
    注意：这不会完全切换到新 venv（已加载的模块不受影响），
    主要供子进程使用。
    """
    if not venv.python_exe():
        return {"success": False, "error": f"venv 没有有效的 Python 解释器: {venv.path}"}

    # 设置环境变量（供后续子进程使用）
    os.environ["VIRTUAL_ENV"] = str(venv.path)

    # 修改 PATH
    if sys.platform == "win32":
        bin_dir = str(venv.path / "Scripts")
    else:
        bin_dir = str(venv.path / "bin")

    paths = os.environ.get("PATH", "").split(os.pathsep)
    paths = [p for p in paths if "Scripts" not in p and "bin" not in p or venv.name not in p]
    os.environ["PATH"] = bin_dir + os.pathsep + os.pathsep.join(paths)

    return {
        "success": True,
        "name": venv.name,
        "path": str(venv.path),
        "python": str(venv.python_exe()),
        "activate_cmd": get_activate_command(venv),
    }

"""
PyCoder Python 生态工具集

- env_detector: 环境检测
- jupyter: Jupyter Notebook 集成
- venv_manager: 虚拟环境管理
"""

from pycoder.python.env_detector import EnvironmentInfo, detect_environment, print_env_info
from pycoder.python.jupyter import JupyterNotebook, NotebookCell, find_notebooks, scan_notebooks
from pycoder.python.venv_manager import (
    VirtualEnv,
    create_venv,
    detect_current_venv,
    install_package,
    install_requirements,
    list_venvs,
)

__all__ = [
    "detect_environment",
    "print_env_info",
    "EnvironmentInfo",
    "JupyterNotebook",
    "NotebookCell",
    "find_notebooks",
    "scan_notebooks",
    "VirtualEnv",
    "create_venv",
    "detect_current_venv",
    "list_venvs",
    "install_package",
    "install_requirements",
]

"""
代码格式化 API — 支持 black/isort/ruff + 自动检测 Python
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api")


@router.post("/format")
async def format_code(req: dict):
    """格式化 Python 代码（支持 black/isort/ruff），Ctrl+S 保存时调用"""
    code = req.get("code", "")
    style = req.get("style", "black")
    if not code:
        return {"success": False, "error": "缺少 code 参数"}

    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
    with tf as f:
        f.write(code)
        tmp_path = f.name

    try:
        if style == "isort":
            r = subprocess.run(
                [sys.executable, "-m", "isort", tmp_path],
                capture_output=True,
                text=True,
                timeout=15,
            )
        elif style == "ruff":
            r = subprocess.run(
                [sys.executable, "-m", "ruff", "format", tmp_path],
                capture_output=True,
                text=True,
                timeout=15,
            )
        else:
            r = subprocess.run(
                [sys.executable, "-m", "black", "--quiet", tmp_path],
                capture_output=True,
                text=True,
                timeout=15,
            )

        if r.returncode == 0:
            formatted = Path(tmp_path).read_text(encoding="utf-8")
            return {"success": True, "formatted": formatted, "style": style}
        else:
            # 格式化失败，返回原始代码
            return {
                "success": True,
                "formatted": code,
                "style": style,
                "warning": "格式化工具执行失败，已返回原始代码",
            }
    except FileNotFoundError:
        return {
            "success": True,
            "formatted": code,
            "style": style,
            "warning": f"{style} 未安装 (pip install {style})，已返回原始代码",
        }
    except Exception as e:
        return {
            "success": True,
            "formatted": code,
            "style": style,
            "warning": f"格式化异常: {str(e)[:100]}",
        }
    finally:
        Path(tmp_path).unlink(missing_ok=True)

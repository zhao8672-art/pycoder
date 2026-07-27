"""
代码格式化 API — 支持 black/isort/ruff + 自动检测 Python

P1 修复: subprocess.run 包装在 asyncio.to_thread 中，避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api")


def _format_sync(code: str, style: str) -> dict:
    """同步执行格式化（在线程池中调用）"""
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


@router.post("/format")
async def format_code(req: dict):
    """格式化 Python 代码（支持 black/isort/ruff），Ctrl+S 保存时调用"""
    code = req.get("code", "")
    style = req.get("style", "black")
    if not code:
        return {"success": False, "error": "缺少 code 参数"}

    # P1 修复: 在线程池中执行同步 subprocess，避免阻塞事件循环
    return await asyncio.to_thread(_format_sync, code, style)

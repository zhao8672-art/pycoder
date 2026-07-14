"""
文件上传/下载 API — 拖拽上传支持

端点:
    POST /api/files/upload  — 上传文件到工作区
    POST /api/files/upload/batch — 批量上传
    GET  /api/files/download/<path> — 下载工作区文件
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from pycoder.server.routers.files import get_workspace_root

router = APIRouter(prefix="/api/file-transfer")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    target_dir: str = Form(default=""),
):
    """上传文件到工作区指定目录（支持拖拽）"""
    root = get_workspace_root()
    target = (root / target_dir).resolve() if target_dir else root
    # M8: 用 is_relative_to 替代字符串前缀匹配
    if not target.is_relative_to(root):
        raise HTTPException(400, "路径穿越拒绝")

    target.mkdir(parents=True, exist_ok=True)
    # 安全：只取 basename 防止 filename 中的路径穿越
    safe_name = Path(file.filename).name
    file_path = target / safe_name
    content = await file.read()
    file_path.write_bytes(content)

    return {
        "success": True,
        "filename": safe_name,
        "path": str(file_path.relative_to(root)).replace("\\", "/"),
        "size": len(content),
        "message": f"文件已上传: {safe_name}",
    }


@router.post("/upload/batch")
async def upload_files(
    files: list[UploadFile] = File(...),
    target_dir: str = Form(default=""),
):
    """批量上传多个文件"""
    results = []
    root = get_workspace_root()
    target = (root / target_dir).resolve() if target_dir else root
    # M8: 用 is_relative_to 替代字符串前缀匹配
    if not target.is_relative_to(root):
        raise HTTPException(400, "路径穿越拒绝")
    target.mkdir(parents=True, exist_ok=True)

    for file in files:
        # 安全：只取 basename 防止 filename 中的路径穿越
        safe_name = Path(file.filename).name
        file_path = target / safe_name
        content = await file.read()
        file_path.write_bytes(content)
        results.append(
            {
                "filename": safe_name,
                "size": len(content),
                "success": True,
            }
        )

    return {"success": True, "files": results, "count": len(results)}


@router.get("/download/{file_path:path}")
async def download_file(file_path: str):
    """从工作区下载文件"""
    root = get_workspace_root()
    target = (root / file_path).resolve()
    # M8: 用 is_relative_to 替代字符串前缀匹配
    if not target.is_relative_to(root):
        raise HTTPException(400, "路径穿越拒绝")
    if not target.exists():
        raise HTTPException(404, f"文件不存在: {file_path}")
    if target.is_dir():
        raise HTTPException(400, "不能下载目录")
    return FileResponse(str(target), filename=target.name)

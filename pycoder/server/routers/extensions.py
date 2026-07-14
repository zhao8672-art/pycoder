"""扩展市场 API — 完整 CRUD + 贡献模型 + 沙箱执行 + 命令面板"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from pycoder.extensions.commands import get_command_palette, register_builtin_commands
from pycoder.extensions.manager import ExtensionManager
from pycoder.extensions.marketplace import get_seed_extensions, search_extensions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/extensions")
_manager = ExtensionManager()

# 确保内置命令已注册
register_builtin_commands()


@router.get("/search")
async def search_ext(
    q: str = "",
    category: str = "",
    limit: int = 50,
    offset: int = 0,
):
    """搜索可用的扩展（支持分页）"""
    result = await search_extensions(q, category, limit, offset)
    # 标记已安装
    for ext in result["extensions"]:
        ext_id = ext.get("id", "")
        ext["installed"] = _manager.is_installed(ext_id)
        if ext["installed"]:
            ext["enabled"] = _manager.is_enabled(ext_id)
    return result


@router.get("/installed")
async def list_installed():
    """列出已安装的扩展"""
    exts = _manager.get_installed()
    return {"extensions": exts, "total": len(exts)}


@router.get("/recommended")
async def list_recommended():
    """列出推荐的扩展（种子数据 + 标记已安装状态）"""
    exts = list(get_seed_extensions())
    for ext in exts:
        ext_id = ext.get("id", "")
        ext["installed"] = _manager.is_installed(ext_id)
        if ext["installed"]:
            ext["enabled"] = _manager.is_enabled(ext_id)
    return {"extensions": exts}


@router.post("/install")
async def install_extension(req: dict):
    """安装扩展 — 含来源安全校验"""
    ext_id = req.get("id", "")
    if not ext_id:
        raise HTTPException(400, "id is required")

    if _manager.is_installed(ext_id):
        return {"success": False, "id": ext_id, "error": "already installed"}

    # 从缓存/搜索中获取完整数据
    ext_data = req.copy()
    try:
        result = await search_extensions("")
        for e in result.get("extensions", []):
            if e.get("id") == ext_id:
                ext_data = {**e, **req}
                break
    except Exception as e:
        # GitHub 不可用，用 req 中的基础数据
        logger.debug("extension_search_failed error=%s", e)

    # 种子扩展：从 _SEED_PACKAGES 补全元数据
    from pycoder.extensions.manager import _SEED_PACKAGES

    if ext_id in _SEED_PACKAGES:
        seed = _SEED_PACKAGES[ext_id]
        ext_data.setdefault("name", seed["manifest"].get("name", ext_id))
        ext_data.setdefault("version", seed["manifest"].get("version", "1.0.0"))
        ext_data.setdefault("category", seed["manifest"].get("category", "unknown"))
        ext_data.setdefault("is_seed", True)

    try:
        ok = await _manager.install(ext_id, ext_data)
        return {"success": ok, "id": ext_id, "name": ext_data.get("name", ext_id)}
    except PermissionError as e:
        raise HTTPException(403, detail=str(e)) from e


@router.post("/uninstall")
async def uninstall_extension(req: dict):
    """卸载扩展"""
    ext_id = req.get("id", "")
    ok = _manager.uninstall(ext_id)
    return {"success": ok, "id": ext_id}


@router.post("/enable")
async def enable_extension(req: dict):
    """启用扩展"""
    ext_id = req.get("id", "")
    ok = _manager.enable(ext_id)
    return {"success": ok, "id": ext_id}


@router.post("/disable")
async def disable_extension(req: dict):
    """禁用扩展"""
    ext_id = req.get("id", "")
    ok = _manager.disable(ext_id)
    return {"success": ok, "id": ext_id}


@router.post("/update")
async def update_extension(req: dict):
    """更新扩展"""
    ext_id = req.get("id", "")
    ok = _manager.update(ext_id)
    return {"success": ok, "id": ext_id}


@router.get("/config/{ext_id}")
async def get_config(ext_id: str, key: str | None = None):
    """获取扩展配置"""
    val = _manager.get_config(ext_id, key)
    return {"config": val}


@router.post("/config/{ext_id}")
async def set_config(ext_id: str, req: dict):
    """设置扩展配置"""
    key = req.get("key", "")
    value = req.get("value")
    ok = _manager.set_config(ext_id, key, value)
    return {"success": ok}


@router.get("/verify/{ext_id}")
async def verify_extension(ext_id: str):
    """验证扩展是否真实安装（检查代码文件是否存在）"""
    import json
    from pathlib import Path

    target = Path.home() / ".pycoder" / "extensions" / ext_id.replace("/", "_")
    if not target.exists():
        return {"installed": False, "id": ext_id, "reason": "directory missing"}
    files = [f.name for f in target.iterdir() if f.is_file()]
    manifest_json = target / "manifest.json"
    manifest = (
        json.loads(manifest_json.read_text(encoding="utf-8")) if manifest_json.exists() else {}
    )
    return {
        "installed": True,
        "id": ext_id,
        "name": manifest.get("name", "?"),
        "version": manifest.get("version", "?"),
        "files": files,
        "code_size": sum((target / f).stat().st_size for f in files if (target / f).is_file()),
    }


@router.post("/run")
async def run_extension_function(req: dict):
    """
    执行已安装扩展的函数（使用 ExtensionSandbox，支持 async）

    请求体: {id, function, args?}
    """
    ext_id = req.get("id", "")
    func_name = req.get("function", "name")
    func_args = req.get("args", {})

    if not ext_id:
        raise HTTPException(400, "id is required")

    if not _manager.is_enabled(ext_id):
        return {"success": False, "error": f"扩展已禁用: {ext_id}"}

    result = await _manager.execute_extension_function(ext_id, func_name, func_args)
    return result


# ══════════════════════════════════════════════════════════
# 新端点: 贡献模型 + 沙箱 + 命令面板 + 打包
# ══════════════════════════════════════════════════════════


@router.get("/details/{ext_id}")
async def get_extension_details(ext_id: str):
    """获取扩展完整详情（含贡献点、沙箱状态、可用函数）"""
    details = _manager.get_extension_details(ext_id)
    if details is None:
        raise HTTPException(404, f"扩展未安装: {ext_id}")
    return details


@router.get("/stats")
async def get_extension_stats():
    """获取扩展系统统计"""
    return _manager.get_stats()


@router.post("/activate")
async def activate_extension(req: dict):
    """激活扩展（加载到 ExtensionHost，async）"""
    ext_id = req.get("id", "")
    if not ext_id:
        raise HTTPException(400, "id is required")
    ok = await _manager.activate_extension(ext_id)
    return {"success": ok, "id": ext_id}


@router.post("/deactivate")
async def deactivate_extension(req: dict):
    """停用扩展（从 ExtensionHost 卸载）"""
    ext_id = req.get("id", "")
    if not ext_id:
        raise HTTPException(400, "id is required")
    ok = _manager.deactivate_extension(ext_id)
    return {"success": ok, "id": ext_id}


@router.post("/activate-all")
async def activate_all_extensions():
    """激活所有已启用的扩展（async）"""
    results = await _manager.activate_all()
    return {
        "success": True,
        "activated": sum(1 for v in results.values() if v),
        "total": len(results),
        "details": results,
    }


@router.get("/commands")
async def list_commands(q: str = ""):
    """列出所有注册的命令（命令面板数据源）"""
    palette = get_command_palette()
    commands = palette.search(q)
    categories = palette.get_all_categories()
    stats = palette.get_stats()
    return {
        "commands": commands,
        "total": len(commands),
        "categories": categories,
        "stats": stats,
    }


@router.post("/commands/execute")
async def execute_command(req: dict):
    """执行一个注册的命令"""
    command_id = req.get("id", "")
    args = req.get("args", [])
    kwargs = req.get("kwargs", {})
    if not command_id:
        raise HTTPException(400, "id is required")
    try:
        from pycoder.extensions.commands import get_command_palette

        palette = get_command_palette()
        result = palette.execute(command_id, *args, **kwargs)
        result_str = str(result) if result is not None else None
        return {"success": True, "id": command_id, "result": result_str}
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        return {"success": False, "id": command_id, "error": str(e)}


@router.post("/scaffold")
async def scaffold_extension(req: dict):
    """创建扩展脚手架"""
    ext_id = req.get("id", "")
    name = req.get("name", "")
    description = req.get("description", "")
    author = req.get("author", "")
    if not ext_id:
        raise HTTPException(400, "id is required (格式: publisher.name)")
    path = _manager.scaffold_extension(ext_id, name, description, author)
    return {"success": True, "id": ext_id, "path": path}


@router.post("/refresh")
async def refresh_marketplace():
    """强制刷新扩展市场缓存（从 GitHub/npm/PyPI 实时拉取）"""
    from pycoder.extensions.marketplace import force_refresh

    result = await force_refresh()
    return result


@router.get("/cache-status")
async def cache_status():
    """获取扩展市场缓存状态"""
    from pycoder.extensions.marketplace import get_cache_status

    return get_cache_status()


@router.post("/pack/{ext_id}")
async def pack_extension(ext_id: str):
    """将已安装扩展打包为 .pycoder-ext"""
    if not _manager.is_installed(ext_id):
        raise HTTPException(404, f"扩展未安装: {ext_id}")
    from pycoder.extensions.packaging import pack_installed

    try:
        output = pack_installed(ext_id)
        from pathlib import Path

        fsize = Path(output).stat().st_size
        return {"success": True, "id": ext_id, "path": output, "size": fsize}
    except (FileNotFoundError, ValueError, OSError) as e:
        return {"success": False, "error": str(e)}


@router.post("/install-from-pack")
async def install_from_pack(req: dict):
    """从 .pycoder-ext 文件安装扩展"""
    file_path = req.get("path", "")
    if not file_path:
        raise HTTPException(400, "path is required")
    from pathlib import Path

    from pycoder.extensions.packaging import unpack

    try:
        target = unpack(file_path)
        # 读取 manifest 获取 ext_id
        manifest_path = Path(target) / "manifest.json"
        import json

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ext_id = manifest.get("id", Path(target).name)
        ext_data = {
            "id": ext_id,
            "name": manifest.get("name", ext_id),
            "version": manifest.get("version", "0.0.0"),
            "path": target,
            "installed": True,
            "enabled": True,
        }
        _manager._installed[ext_id] = ext_data
        _manager._save()
        return {"success": True, "id": ext_id, "path": target}
    except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError) as e:
        return {"success": False, "error": str(e)}


@router.get("/settings")
async def list_all_settings(ext_id: str | None = None):
    """列出全局设置或指定扩展的设置"""
    from pycoder.extensions.contributions import get_settings_registry

    reg = get_settings_registry()
    settings = reg.list_settings(ext_id)
    return {"settings": settings, "total": len(settings)}


@router.post("/settings")
async def update_setting(req: dict):
    """更新设置值"""
    key = req.get("key", "")
    value = req.get("value")
    if not key:
        raise HTTPException(400, "key is required")
    from pycoder.extensions.contributions import get_settings_registry

    reg = get_settings_registry()
    ok = reg.set(key, value)
    return {"success": ok, "key": key, "value": value}

"""
Environment, config and mobile routes.
Extracted from rest_routes.py for modularity.
"""

from __future__ import annotations

import time

from fastapi import APIRouter

from pycoder.python.env_detector import detect_environment
from pycoder.server.log import log

router = APIRouter()


@router.get("/api/env")
async def get_env():
    info = detect_environment()
    return {
        "python_version": info.python_version,
        "venv_type": info.venv_type,
        "venv_path": info.venv_path,
        "package_manager": info.package_manager,
        "project_type": info.project_type,
        "frameworks": info.frameworks,
        "has_jupyter": info.has_jupyter,
        "project_structure": info.project_structure,
        "git_info": info.git_info,
    }


@router.post("/api/config/setup")
async def config_setup(req: dict):
    from pycoder.providers.setup_wizard import set_api_key

    provider = req.get("provider") or req.get("key_provider") or ""
    api_key = req.get("api_key") or req.get("key") or ""
    result = set_api_key(provider, api_key)
    return result


@router.get("/api/config/keys")
async def config_keys():
    from pycoder.providers.setup_wizard import check_all_keys

    return {"providers": check_all_keys()}


@router.get("/api/model/config")
async def get_model_config():
    from pycoder.python.model_config import get_model_config as get_config
    from pycoder.python.model_config import load_config

    config = load_config()
    model_config = get_config()
    return {
        "success": True,
        "config": {
            "default_model": config.get("provider", {}).get("default_model", "deepseek-chat"),
            "temperature": model_config.temperature,
            "max_tokens": model_config.max_tokens,
            "top_p": model_config.top_p,
            "frequency_penalty": model_config.frequency_penalty,
            "presence_penalty": model_config.presence_penalty,
            "system_prompt": model_config.system_prompt,
        },
    }


@router.post("/api/model/config")
async def update_model_config(req: dict):
    from pycoder.python.model_config import update_model_config as update_config

    result = update_config(**req)
    return result


@router.get("/api/mobile/status")
async def get_mobile_status():
    """
    获取移动端状态（iOS/Android/Web）

    降级方案：如果模块不可用，返回离线状态说明
    """
    try:
        from pycoder.python.mobile_integration import get_mobile_status as get_status

        status = await get_status()
    except (ImportError, AttributeError, ModuleNotFoundError) as e:
        # 模块暂未实现或加载失败
        log.warning("mobile_integration_error", error=str(e))
        status = {
            "ios": {"status": "offline", "reason": "module_not_available"},
            "android": {"status": "offline", "reason": "module_not_available"},
            "web": {"status": "offline", "reason": "module_not_available"},
        }
    except Exception as e:
        # 其他异常（网络、数据库等）
        log.error("mobile_status_error", error=str(e))
        status = {
            "ios": {"status": "error", "reason": "internal_error"},
            "android": {"status": "error", "reason": "internal_error"},
            "web": {"status": "error", "reason": "internal_error"},
        }

    return {"success": True, "platforms": status, "timestamp": time.time()}


@router.post("/api/mobile/quick")
async def mobile_quick_config(req: dict):
    # Mobile quick config - placeholder, module not yet implemented
    return {"success": True, "message": "Mobile quick config received", "data": req}


# ══════════════════════════════════════════════════════════
# Skills 自动发现
# ══════════════════════════════════════════════════════════


@router.get("/api/skills")
async def list_skills():
    """列出所有可用的 Skills（项目级 + 用户级）"""
    from pycoder.prompts.skills_loader import discover_skills

    skills = discover_skills()
    return {"skills": skills, "total": len(skills)}


@router.get("/api/skills/{name}")
async def get_skill(name: str):
    """按名称获取单个 Skill 详情"""
    from pycoder.prompts.skills_loader import get_skill

    skill = get_skill(name)
    if skill:
        return {"skill": skill}
    return {"error": f"Skill '{name}' not found"}, 404


# ══════════════════════════════════════════════════════════
# 权限策略
# ══════════════════════════════════════════════════════════


@router.get("/api/permissions")
async def get_permissions():
    """获取当前权限策略"""
    from pycoder.server.permission_policy import get_permission_policy

    policy = get_permission_policy()
    return {"policy": policy.to_dict()}


@router.post("/api/permissions")
async def update_permissions(req: dict):
    """更新权限策略"""
    from pycoder.server.permission_policy import update_permission_policy

    policy = update_permission_policy(req)
    return {"success": True, "policy": policy.to_dict()}


@router.post("/api/model/default")
async def set_default_model(req: dict):
    from pycoder.python.model_config import update_model_config

    result = update_model_config(default_model=req.get("model", ""))
    return {"success": result.get("success", False), "message": "默认模型已更新"}

"""
Environment, config and mobile routes.
Extracted from rest_routes.py for modularity.
"""

from __future__ import annotations

import time

from fastapi import APIRouter

from pycoder.core.services.log import log
from pycoder.python.env_detector import detect_environment

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
    """设置 API Key + 可选默认模型"""
    from pycoder.providers.auth import PROVIDER_DEFS
    from pycoder.providers.setup_wizard import set_api_key
    from pycoder.server.chat_bridge import _detect_provider

    provider = req.get("provider") or req.get("key_provider") or ""
    api_key = req.get("api_key") or req.get("key") or ""
    default_model = req.get("default_model", "")
    model = req.get("model", "")

    # ── 日志: 记录保存请求的原始数据 ──
    import logging

    _log = logging.getLogger(__name__)
    _log.info(
        "config_setup provider=%s key_len=%d key_prefix=%s model=%s",
        provider,
        len(api_key),
        api_key[:12] if api_key else "(empty)",
        model,
    )

    # ── 后端安全网: 根据 model 自动纠错 provider ──
    if model and provider:
        model_provider = _detect_provider(model)
        if model_provider != provider and model_provider in PROVIDER_DEFS:
            _log.warning(
                "provider_auto_correct: frontend=%s -> corrected=%s (model=%s)",
                provider,
                model_provider,
                model,
            )
            provider = model_provider

    # ── 空 Key 校验 ──
    if not api_key:
        _log.warning("config_setup_rejected: empty api_key provider=%s", provider)
        return {"success": False, "error": "API Key 不能为空"}

    result = set_api_key(provider, api_key)
    _log.info("config_setup_result success=%s provider=%s", result.get("success"), provider)
    if default_model:
        from pycoder.config.settings import get_config_path, save_config

        cfg = {}
        cfg_path = get_config_path()
        if cfg_path.exists():
            import json

            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["default_model"] = default_model
        save_config(cfg)
        result["default_model"] = default_model
    return result


@router.get("/api/config/keys")
async def config_keys():
    """获取所有 Provider 的 Key 配置状态（简化版）"""
    from pycoder.providers.auth import PROVIDER_DEFS, get_model_manager

    mgr = get_model_manager()
    detected = mgr.get_all_keys()
    providers = []
    for pid, defs in PROVIDER_DEFS.items():
        has = pid in detected
        key_preview = ""
        if has:
            k = detected[pid]
            key_preview = f"{k[:10]}...{k[-4:]}" if len(k) > 14 else "****"
        providers.append(
            {
                "id": pid,
                "name": defs["name"],
                "has_key": has,
                "key_preview": key_preview,
                "recommended_model": defs["recommended_model"],
                "register_url": defs["register_url"],
                "free_trial": defs.get("free_trial", ""),
                "price_summary": defs.get("price_summary", ""),
            }
        )
    return {
        "providers": providers,
        "any_key": len(detected) > 0,
    }


@router.get("/api/config/status")
async def config_status():
    """一键获取完整配置状态（供设置面板使用）"""
    from pycoder.providers.auth import PROVIDER_DEFS, get_model_manager

    mgr = get_model_manager()
    detected = mgr.get_all_keys()
    models = mgr.get_available_models()

    providers = []
    for pid, defs in PROVIDER_DEFS.items():
        has = pid in detected
        providers.append(
            {
                "id": pid,
                "name": defs["name"],
                "has_key": has,
                "recommended_model": defs["recommended_model"],
                "register_url": defs["register_url"],
                "free_trial": defs.get("free_trial", ""),
            }
        )

    recommended_id, recommended_provider = mgr.recommend()
    user_model = mgr.load_model_preference()

    return {
        "success": True,
        "providers": providers,
        "has_any_key": len(detected) > 0,
        "recommended_model": recommended_id,
        "recommended_provider": recommended_provider,
        "user_selected_model": user_model or None,
        "models": models,
        "total_models": len(models),
    }


@router.get("/api/models")
async def list_models():
    """列出所有可用模型及其完整信息（含可用性、API Base、定价等）"""
    from pycoder.providers.auth import get_model_manager

    mgr = get_model_manager()
    models = mgr.get_available_models()
    return {
        "models": models,
        "total": len(models),
        "recommended_model": mgr.recommend()[0],
    }


@router.post("/api/model/select")
async def select_model(req: dict):
    """用户选择默认模型（持久化到配置文件）"""
    from pycoder.providers.auth import get_model_manager

    model_id = req.get("model", "")
    if not model_id:
        return {"success": False, "error": "请指定 model ID"}
    mgr = get_model_manager()
    result = mgr.save_model_preference(model_id)
    return result


@router.get("/api/model/current")
async def get_current_model():
    """获取当前生效的模型配置"""
    from pycoder.providers.auth import ALL_MODELS, get_model_manager

    mgr = get_model_manager()
    user_model = mgr.load_model_preference()
    recommended_id, provider = mgr.recommend()
    effective_model = user_model or recommended_id
    info = ALL_MODELS.get(effective_model)
    custom_api_base = mgr.get_custom_api_base(effective_model)
    return {
        "success": True,
        "model": {
            "id": effective_model,
            "name": info.name if info else effective_model,
            "provider": provider,
            "api_base": custom_api_base or (info.api_base if info else ""),
            "context_window": info.context_window if info else 0,
            "user_selected": bool(user_model),
        },
        "available_models": mgr.get_available_models(),
    }


@router.post("/api/model/custom-api-base")
async def set_custom_api_base(req: dict):
    """设置自定义 API Base URL（允许用户使用任意兼容的 API 端点）"""
    from pycoder.providers.auth import get_model_manager

    model_id = req.get("model", "")
    api_base = req.get("api_base", "")
    if not model_id or not api_base:
        return {"success": False, "error": "请指定 model 和 api_base"}
    mgr = get_model_manager()
    return mgr.save_custom_api_base(model_id, api_base)


@router.get("/api/model/custom-api-bases")
async def get_custom_api_bases():
    """获取所有自定义 API Base URL"""
    from pycoder.providers.auth import get_model_manager

    mgr = get_model_manager()
    return {"success": True, "custom_api_bases": mgr.get_all_custom_api_bases()}


@router.post("/api/config/validate-key")
async def validate_api_key(req: dict):
    """验证 API Key 是否有效"""
    from pycoder.providers.auth import get_model_manager

    provider = req.get("provider", "")
    api_key = req.get("api_key", "")
    if not provider or not api_key:
        return {"success": False, "error": "需指定 provider 和 api_key"}
    mgr = get_model_manager()
    valid = await mgr.validate_key(provider, api_key)
    return {"success": valid, "provider": provider}


@router.post("/api/config/quick-setup")
async def quick_setup(req: dict):
    """一键配置：自动验证 API Key → 保存 → 设置默认模型

    请求体:
        - provider: 提供商 ID（如 "deepseek"），传 "auto" 或留空则自动探测
        - api_key:  API Key
        - model_id: 可选，用户当前选中的模型 ID。若指定，将从此模型的
                    注册信息（ALL_MODELS）反查 provider，作为优先候选，
                    避免 key 前缀猜测导致的 provider 错配（如 Agnes 被误判）。

    返回:
        - success: 是否成功
        - provider / provider_name / model_id: 成功时的配置信息
        - error / register_url: 失败时的错误和注册地址
        - tried: 自动探测时尝试过的 provider 列表
    """
    import logging

    from pycoder.providers.auth import ALL_MODELS, PROVIDER_DEFS, get_model_manager
    from pycoder.providers.setup_wizard import set_api_key

    _log = logging.getLogger(__name__)

    provider = (req.get("provider") or "").strip().lower() or "auto"
    api_key = (req.get("api_key") or req.get("key") or "").strip()
    model_id = (req.get("model") or req.get("model_id") or "").strip()

    if not api_key:
        return {"success": False, "error": "API Key 不能为空"}

    mgr = get_model_manager()
    tried: list[str] = []

    # ── 防错机制 1：若指定了 model_id，从 ALL_MODELS 反查真实 provider ──
    # 避免字符串前缀匹配的陷阱（如 "Agnes-2.5-Flash" 大写 A 不匹配 'agnes'）
    model_provider: str | None = None
    if model_id:
        info = ALL_MODELS.get(model_id)
        if info and info.provider in PROVIDER_DEFS:
            model_provider = info.provider
            _log.info(
                "quick_setup_model_inferred_provider model=%s -> provider=%s",
                model_id,
                model_provider,
            )
        else:
            _log.warning(
                "quick_setup_model_not_found model=%s (will fall back to provider detection)",
                model_id,
            )

    # ── 防错机制 2：若用户传了 provider 但与 model_id 反查结果冲突，以 model 为准 ──
    if (
        model_provider
        and provider not in ("", "auto")
        and provider != model_provider
    ):
        _log.warning(
            "quick_setup_provider_conflict user=%s model_says=%s -> using model's provider",
            provider,
            model_provider,
        )
        provider = model_provider

    # ── 自动探测：构建候选 provider 优先级列表 ──
    if provider in ("", "auto"):
        # 候选顺序：model 反查 > key 前缀启发 > 全部按 priority
        candidates: list[str] = []
        if model_provider:
            candidates.append(model_provider)
        if api_key.startswith("sk-"):
            # sk- 前缀常见于 DeepSeek / OpenAI / OpenRouter
            for p in ("deepseek", "openai", "openrouter"):
                if p not in candidates:
                    candidates.append(p)
        # 补齐：剩余 provider 按 priority 排序
        for p in sorted(
            PROVIDER_DEFS.keys(),
            key=lambda x: PROVIDER_DEFS[x].get("priority", 99),
        ):
            if p not in candidates:
                candidates.append(p)

        validated_provider: str | None = None
        for p in candidates:
            tried.append(p)
            try:
                if await mgr.validate_key(p, api_key):
                    validated_provider = p
                    break
            except (RuntimeError, OSError) as e:
                _log.warning("quick_setup_validate_error provider=%s err=%s", p, e)
                continue

        if not validated_provider:
            return {
                "success": False,
                "error": "无法验证此 API Key。请确认 Key 是否正确，或手动选择提供商。",
                "tried": tried,
            }
        provider = validated_provider

    # ── 指定 provider：直接验证 ──
    elif provider not in PROVIDER_DEFS:
        return {
            "success": False,
            "error": f"不支持的提供商: {provider}",
            "supported": list(PROVIDER_DEFS.keys()),
        }
    else:
        try:
            is_valid = await mgr.validate_key(provider, api_key)
        except (RuntimeError, OSError) as e:
            _log.warning("quick_setup_validate_error provider=%s err=%s", provider, e)
            is_valid = False

        if not is_valid:
            defs = PROVIDER_DEFS.get(provider, {})
            return {
                "success": False,
                "error": (
                    f"API Key 验证失败。请确认 Key 来自 {defs.get('name', provider)}，"
                    "且未过期或被限制。"
                ),
                "register_url": defs.get("register_url", ""),
                "provider": provider,
            }

    # ── 验证通过：保存 Key + 设默认模型 ──
    # 默认模型优先级：用户当前选中的 model_id（且 provider 一致）> provider 推荐模型
    defs = PROVIDER_DEFS[provider]
    save_result = set_api_key(provider, api_key, set_default=True)
    target_model = (
        model_id
        if (
            model_id
            and ALL_MODELS.get(model_id)
            and ALL_MODELS[model_id].provider == provider
        )
        else defs["recommended_model"]
    )
    mgr.save_model_preference(target_model)

    _log.info(
        "quick_setup_success provider=%s model=%s key_prefix=%s...%s",
        provider,
        target_model,
        api_key[:12],
        api_key[-4:],
    )

    return {
        "success": True,
        "provider": provider,
        "provider_name": defs["name"],
        "model_id": target_model,
        "model_name": mgr.get_model_info(target_model).name
        if mgr.get_model_info(target_model)
        else target_model,
        "message": f"✅ 配置成功！已自动切换到 {target_model}",
        "saved": save_result.get("success", False),
    }


@router.get("/api/config/guide")
async def config_guide(provider: str = ""):
    """获取配置引导信息"""
    from pycoder.providers.auth import PROVIDER_DEFS

    if provider:
        defs = PROVIDER_DEFS.get(provider)
        if not defs:
            return {"success": False, "error": f"未知 provider: {provider}"}
        return {
            "provider": provider,
            "name": defs["name"],
            "register_url": defs["register_url"],
            "env_var": defs["env_vars"][0],
            "free_trial": defs.get("free_trial", ""),
            "recommended_model": defs["recommended_model"],
        }
    # 返回所有 provider 配置引导
    return {
        "providers": [
            {
                "provider": pid,
                "name": defs["name"],
                "register_url": defs["register_url"],
                "env_var": defs["env_vars"][0],
                "free_trial": defs.get("free_trial", ""),
                "recommended_model": defs["recommended_model"],
            }
            for pid, defs in PROVIDER_DEFS.items()
        ]
    }


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

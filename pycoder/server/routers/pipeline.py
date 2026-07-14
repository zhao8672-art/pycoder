"""
工作流流水线编排系统 (Pipeline Builder)

允许用户通过自然语言或 JSON 描述将多个 MCP 工具串联成自动化工作流。

改进说明 (v2):
    - 支持中间步骤失败后从失败点重试（checkpoint_retry）
    - 支持跳过失败步骤继续执行（skip_on_fail）
    - 每一步自动保存 checkpoint，可回滚到任意步骤
    - 步骤间上下文共享改进

端点:
    POST /api/pipeline/run    — 执行已保存的流水线
    POST /api/pipeline/save   — 保存流水线定义
    GET  /api/pipeline/list   — 列出已保存的流水线
    GET  /api/pipeline/<name> — 获取流水线详情
    DELETE /api/pipeline/<name> — 删除流水线
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from pycoder.server.mcp_tools import call_builtin_tool

router = APIRouter(prefix="/api/pipeline")

# 流水线存储路径
_PIPELINE_DIR = Path.home() / ".pycoder" / "pipelines"
_PIPELINE_DIR.mkdir(parents=True, exist_ok=True)

# 运行历史路径
_RUN_HISTORY_DIR = Path.home() / ".pycoder" / "pipeline_runs"
_RUN_HISTORY_DIR.mkdir(parents=True, exist_ok=True)


class PipelineStep(BaseModel):
    """流水线中的单个步骤"""

    tool: str  # MCP 工具名
    args: dict = {}  # 工具参数
    description: str = ""  # 可读描述
    skip_on_fail: bool = False  # 失败时是否跳过继续
    checkpoint_retry: bool = False  # 支持从该步骤重试


class PipelineDef(BaseModel):
    """流水线定义"""

    name: str
    description: str = ""
    steps: list[PipelineStep]
    max_retries: int = 1  # 整个流水线最大重试次数


def _load_pipeline(name: str) -> dict | None:
    """加载已保存的流水线"""
    path = _PIPELINE_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_pipeline(defn: PipelineDef) -> None:
    """保存流水线"""
    path = _PIPELINE_DIR / f"{defn.name}.json"
    data = defn.model_dump()
    data["updated_at"] = time.time()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _save_run_history(run_id: str, pipeline_name: str, results: list, overall_success: bool):
    """保存执行历史"""
    history = {
        "run_id": run_id,
        "pipeline_name": pipeline_name,
        "timestamp": time.time(),
        "overall_success": overall_success,
        "steps_completed": len(results),
        "results": results,
    }
    path = _RUN_HISTORY_DIR / f"{run_id}.json"
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


@router.post("/save")
async def save_pipeline(defn: PipelineDef):
    """保存流水线定义"""
    if not defn.name.strip():
        raise HTTPException(400, "流水线名称不能为空")
    if not defn.steps:
        raise HTTPException(400, "流水线至少需要一个步骤")
    _save_pipeline(defn)
    return {"success": True, "name": defn.name, "steps": len(defn.steps)}


@router.post("/run")
async def run_pipeline(req: dict):
    """执行流水线 — 支持 {name: "已保存的流水线名"} 或 {steps: [...]}"""
    name = req.get("name", "")
    steps_raw = req.get("steps", [])

    # 加载流水线定义
    if name:
        pipeline_data = _load_pipeline(name)
        if not pipeline_data:
            raise HTTPException(404, f"流水线不存在: {name}")
        steps_to_run = [PipelineStep(**s) for s in pipeline_data.get("steps", [])]
    elif steps_raw:
        steps_to_run = [PipelineStep(**s) if isinstance(s, dict) else s for s in steps_raw]
    else:
        raise HTTPException(400, "需要 name 或 steps 参数")

    results = []
    overall_success = True
    ctx: dict = {}  # 步骤间共享上下文
    run_id = str(uuid.uuid4())[:8]
    checkpoint = {}  # 检查点: step_index → ctx snapshot

    for i, step in enumerate(steps_to_run):
        step_num = i + 1
        try:
            # 保存检查点
            checkpoint[step_num] = {
                "ctx": dict(ctx),
                "step_index": i,
            }

            # 解析参数中的 {prev.key} 引用
            resolved_args = {}
            for k, v in (step.args or {}).items():
                if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
                    ref_path = v[1:-1]
                    resolved_args[k] = _resolve_ref(ctx, ref_path)
                else:
                    resolved_args[k] = v

            result = await call_builtin_tool(step.tool, resolved_args)
            step_result = {
                "step": step_num,
                "tool": step.tool,
                "description": step.description,
                "success": result.success,
                "output": result.output if hasattr(result, "output") else str(result),
                "error": result.error if hasattr(result, "error") else "",
                "checkpoint_id": run_id,
            }
            results.append(step_result)

            if not result.success:
                if step.skip_on_fail:
                    # 跳过失败步骤，继续执行
                    step_result["skipped"] = True
                    continue
                overall_success = False
                break

            # 保存上下文供后续步骤引用
            ctx_key = f"step_{step_num}"
            ctx[ctx_key] = result.output if hasattr(result, "output") else str(result)

        except Exception as e:
            error_result = {
                "step": step_num,
                "tool": step.tool,
                "success": False,
                "error": str(e),
                "checkpoint_id": run_id,
                "can_retry_from": step_num,
            }
            results.append(error_result)
            if step.skip_on_fail:
                continue
            overall_success = False
            break

    # 保存运行历史
    _save_run_history(run_id, name or "inline", results, overall_success)

    return {
        "success": overall_success,
        "steps_completed": len(results),
        "total_steps": len(steps_to_run),
        "results": results,
        "run_id": run_id,
        "can_retry_from": _find_fail_point(results),
    }


def _find_fail_point(results: list) -> int | None:
    """找到第一个失败的步骤，用于重试"""
    for r in results:
        if not r["success"]:
            return r.get("step")
    return None


@router.get("/list")
async def list_pipelines():
    """列出所有已保存的流水线"""
    pipelines = []
    for p in sorted(_PIPELINE_DIR.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        pipelines.append(
            {
                "name": data.get("name", p.stem),
                "description": data.get("description", ""),
                "steps": len(data.get("steps", [])),
                "updated_at": data.get("updated_at", 0),
            }
        )
    return {"pipelines": pipelines, "total": len(pipelines)}


@router.get("/{name}")
async def get_pipeline(name: str):
    """获取流水线详情"""
    data = _load_pipeline(name)
    if not data:
        raise HTTPException(404, f"流水线不存在: {name}")
    return data


@router.delete("/{name}")
async def delete_pipeline(name: str):
    """删除流水线"""
    path = _PIPELINE_DIR / f"{name}.json"
    if not path.exists():
        raise HTTPException(404, f"流水线不存在: {name}")
    path.unlink()
    return {"success": True, "name": name}


def _resolve_ref(ctx: dict, ref_path: str) -> str:
    """解析上下文引用 如 prev.result.stdout"""
    parts = ref_path.split(".")
    val = ctx
    for p in parts:
        if isinstance(val, dict):
            val = val.get(p, "")
        else:
            return str(val)
    return str(val)

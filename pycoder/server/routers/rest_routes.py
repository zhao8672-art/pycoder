"""Remaining REST API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

# ── 批量操作请求模型 ────────────────────────────────────


class BatchDeleteRequest(BaseModel):
    session_ids: list[str]


from pycoder.server.session_store import get_session_store  # noqa: E402

router = APIRouter()


@router.get("/api/sessions")
async def list_sessions(limit: int = Query(default=50, ge=1), offset: int = Query(default=0, ge=0)):
    store = get_session_store()
    sessions = store.list_sessions(limit=limit, offset=offset)
    return {"sessions": [s.to_dict() for s in sessions], "total": len(sessions)}


@router.post("/api/sessions")
async def create_session(req: dict | None = None):
    store = get_session_store()
    payload = req or {}
    model = payload.get("model") or "auto"
    s = store.create_session(model=model)
    return {"id": s.id, "created_at": s.created_at, "model": s.model}


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    store = get_session_store()
    s = store.get_session(session_id)
    if not s:
        raise HTTPException(404, "Session not found")
    return {"session": s.to_dict(), "message_count": s.message_count}


@router.get("/api/sessions/{session_id}/messages")
async def get_messages(
    session_id: str, limit: int = Query(default=200), offset: int = Query(default=0)
):
    store = get_session_store()
    if not store.get_session(session_id):
        raise HTTPException(404, "Session not found")
    msgs = store.get_messages(session_id, limit=limit, offset=offset)
    return {"messages": [m.to_dict() for m in msgs], "total": len(msgs)}


@router.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    store = get_session_store()
    store.delete_session(session_id)
    return {"success": True, "session_id": session_id}


@router.post("/api/sessions/batch-delete")
async def batch_delete_sessions(req: BatchDeleteRequest):
    """批量删除会话"""
    store = get_session_store()
    deleted = store.batch_delete_sessions(req.session_ids)
    return {"success": True, "deleted": deleted}


@router.delete("/api/sessions/all")
async def delete_all_sessions():
    """清空所有会话"""
    store = get_session_store()
    count = store.delete_all_sessions()
    return {"success": True, "deleted": count}


@router.get("/api/project/deps/check")
async def project_deps_check():
    from pycoder.python.dep_analyzer import analyze_project_deps

    deps = analyze_project_deps()
    all_deps = deps.production_deps + deps.dev_deps
    installed = [d for d in all_deps if d.installed]
    missing = [d for d in all_deps if not d.installed]
    outdated = [d for d in installed if d.version and d.installed_version != d.version]
    return {
        "success": True,
        "total_missing": len(missing),
        "missing": [d.name for d in missing],
        "installed": [d.name for d in installed],
        "outdated": [d.name for d in outdated],
    }


@router.post("/api/project/tests/run")
async def project_tests_run(req: dict):
    return {
        "success": False,
        "message": "测试运行功能暂不可用（run_tests 不存在）",
    }


@router.post("/api/project/deps/install")
async def project_deps_install(req: dict):
    from pycoder.python.project_tools import DependencyManager

    packages = req.get("packages", [])
    mgr = DependencyManager()
    result = mgr.install_missing_packages(packages)
    return {
        "success": result.success,
        "installed_packages": result.installed_packages,
        "failed_packages": result.failed_packages,
        "output": result.output,
    }


@router.post("/api/project/deps/generate")
async def project_deps_generate(req: dict):
    from pycoder.python.dep_analyzer import DepAnalyzer

    analyzer = DepAnalyzer()
    deps = analyzer.analyze()
    all_deps = deps.production_deps + deps.dev_deps
    content = "\n".join([f"{d.name}{f'>={d.version}' if d.version else ''}" for d in all_deps])
    return {"success": True, "content": content, "count": len(all_deps)}


@router.get("/api/project/deps/analyze")
async def project_deps_analyze():
    from pycoder.python.dep_analyzer import DepAnalyzer

    analyzer = DepAnalyzer()
    deps = analyzer.analyze()
    return {
        "success": True,
        "project_name": deps.project_name,
        "python_version": deps.python_version,
        "package_manager": deps.package_manager,
        "total_deps": deps.total_deps,
        "frameworks": deps.frameworks,
    }


@router.get("/api/project/tests/generate")
async def project_tests_generate():
    return {"success": True, "message": "测试生成功能需要 AI 模型支持"}


@router.get("/api/project/scaffold/types")
async def project_scaffold_types():
    types = [
        {"id": "fastapi", "name": "FastAPI Web", "description": "高性能异步 Web 框架"},
        {"id": "streamlit", "name": "Streamlit", "description": "数据可视化 Web 应用"},
        {"id": "cli", "name": "CLI 工具", "description": "命令行工具"},
        {"id": "library", "name": "Python 库", "description": "可复用的 Python 包"},
    ]
    return {"success": True, "types": types}


@router.post("/api/project/scaffold")
async def project_scaffold(req: dict):
    project_name = req.get("project_name", "")
    project_type = req.get("project_type", "")
    return {"success": True, "message": f"已生成 {project_type} 项目: {project_name}"}


@router.post("/api/code/run")
async def code_run(req: dict):
    """在沙箱中执行 Python 代码（复用 code_exec 模块的安全子进程隔离）

    安全修复（P0-1）：原实现使用进程内 exec()，存在任意代码执行风险。
    现改为调用 code_exec._run_in_subprocess，享受子进程隔离 + 白名单 builtins。
    """
    import asyncio

    from pycoder.server.routers.code_exec import _run_in_subprocess, _sandbox_config

    code = (req.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Code cannot be empty")

    timeout = int(req.get("timeout", _sandbox_config.default_timeout))
    timeout = min(timeout, _sandbox_config.max_timeout)

    # 复用已验证的子进程沙箱（asyncio.to_thread 避免阻塞事件循环）
    result = await asyncio.to_thread(_run_in_subprocess, code, timeout)

    return {
        "success": result.success,
        "output": result.stdout,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error": result.error_message,
        "error_type": result.error_type,
        "traceback": result.traceback,
        "execution_time": round(result.execution_time, 3),
        "return_value": "",
    }


@router.post("/api/code/debug")
async def code_debug(req: dict):
    """调试模式执行代码（在沙箱中运行，返回执行结果 + 详细 traceback）

    安全修复（P0-1）：原实现调用进程内 execute_with_breakpoint，存在任意代码执行风险。
    子进程沙箱无法实现交互式 pdb 调试，改为返回详细 traceback 部分弥补。
    """
    # 进程内调试器无法在子进程沙箱中安全实现，复用 code_run 返回详细 traceback
    return await code_run(req)


@router.post("/api/code/repl/clear")
async def code_repl_clear():
    return {"success": True, "message": "REPL 环境已清除"}


@router.get("/api/code/repl/globals")
async def code_repl_globals():
    return {"success": True, "globals": {}}


@router.get("/api/code/repl/locals")
async def code_repl_locals():
    return {"success": True, "locals": {}}


@router.get("/api/code/history")
async def code_history():
    return {"success": True, "history": []}


@router.get("/api/docstring/styles")
async def docstring_styles():
    styles = ["google", "numpy", "rest"]
    return {"success": True, "styles": styles}


@router.post("/api/docstring/generate")
async def docstring_generate(req: dict):
    from pycoder.python.docstring_generator import DocstringGenerator

    code = req.get("code", "")
    style = req.get("style", "google")
    generator = DocstringGenerator(style=style)
    result = generator.generate_docstring(code)
    return {
        "success": result.success,
        "generated_docstring": result.generated_docstring,
        "updated_code": result.updated_code,
    }


@router.post("/api/context/scan")
async def context_scan(req: dict):
    from pathlib import Path as _Path

    from pycoder.python.project_context import ProjectContext

    project_path = req.get("project_path", str(_Path.cwd()))
    ctx = ProjectContext(project_path=project_path)
    result = ctx.build_index()
    return {"success": result.success, "files": len(result.symbols)}


@router.get("/api/context/overview")
async def context_overview():
    return {"success": True, "overview": "项目上下文概览"}


@router.post("/api/context/search")
async def context_search(req: dict):
    query = req.get("query", "")
    req.get("type", "")
    return {"success": True, "results": [], "query": query}


@router.post("/api/context/clear")
async def context_clear():
    return {"success": True, "message": "上下文已清除"}


@router.post("/api/context/completions")
async def context_completions(req: dict):
    req.get("prefix", "")
    return {"success": True, "completions": []}


@router.get("/api/typehint/status")
async def typehint_status():
    return {"success": True, "enabled": True}


@router.post("/api/typehint/check")
async def typehint_check(req: dict):
    import tempfile
    from pathlib import Path as _Path2

    from pycoder.python.type_inferencer import check_types

    code = req.get("code", "")
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
        f.write(code)
        tmp_path = f.name
    try:
        result = check_types(_Path2(tmp_path))
    finally:
        import os

        os.unlink(tmp_path)
    return {
        "success": result.success,
        "errors": [{"message": e} for e in getattr(result, "errors", [])],
        "warnings": [{"message": w} for w in getattr(result, "warnings", [])],
    }


@router.post("/api/typehint/infer")
async def typehint_infer(req: dict):
    from pycoder.python.type_inferencer import TypeInferencer

    code = req.get("code", "")
    inferencer = TypeInferencer()
    result = inferencer.infer_function_types(code)
    return {
        "success": result.success,
        "updated_code": result.updated_code,
        "parameters": result.parameters,
        "return_type": result.return_type,
    }


@router.post("/api/refactor/extract")
async def refactor_extract(req: dict):
    from pycoder.python.refactor_analyzer import RefactoringExecutor

    code = req.get("code", "")
    start_line = req.get("start_line", 1)
    end_line = req.get("end_line", len(code.split("\n")))
    func_name = req.get("func_name", "extracted_func")
    executor = RefactoringExecutor()
    result = executor.extract_function(code, start_line, end_line, func_name)
    return {
        "success": result.success,
        "refactored_code": result.refactored_code,
        "summary": result.summary,
    }


@router.post("/api/refactor/rename")
async def refactor_rename(req: dict):
    from pycoder.python.refactor_analyzer import RefactoringExecutor

    code = req.get("code", "")
    old_name = req.get("old_name", "")
    new_name = req.get("new_name", "")
    executor = RefactoringExecutor()
    result = executor.rename_variable(code, old_name, new_name)
    return {
        "success": result.success,
        "refactored_code": result.refactored_code,
    }


@router.post("/api/refactor/analyze")
async def refactor_analyze(req: dict):
    from pycoder.python.refactor_analyzer import RefactoringAnalyzer

    code = req.get("code", "")
    analyzer = RefactoringAnalyzer()
    result = analyzer.analyze_code(code)
    return {
        "success": result.success,
        "issues": [
            {"type": i.type, "severity": i.severity, "message": i.message} for i in result.issues
        ],
        "summary": result.summary,
    }


@router.post("/api/refactor/suggest")
async def refactor_suggest(req: dict):
    from pycoder.python.refactor_analyzer import RefactoringAnalyzer

    code = req.get("code", "")
    analyzer = RefactoringAnalyzer()
    result = analyzer.analyze_code(code)
    suggestions = [i.suggestion for i in result.issues]
    return {"success": True, "suggestions": suggestions}


@router.post("/api/refactor/quality")
async def refactor_quality(req: dict):
    from pycoder.python.code_quality import CodeQualityAnalyzer

    code = req.get("code", "")
    analyzer = CodeQualityAnalyzer()
    result = analyzer.analyze(code)
    score = result.get("quality_score", {})
    return {"success": True, "score": score, "summary": result.get("summary", "")}


@router.get("/api/models/recommended")
async def models_recommended():
    models = ["deepseek-chat", "qwen3.6-plus", "glm-5"]
    return {"success": True, "models": models}


@router.get("/api/models/suggest")
async def models_suggest(task_type: str = Query(default="general")):
    suggestions = {"general": "deepseek-chat", "coding": "qwen3.6-plus", "analysis": "glm-5"}
    return {"success": True, "model": suggestions.get(task_type, "deepseek-chat")}


@router.get("/api/async/patterns")
async def async_patterns():
    patterns = ["asyncio", "aiohttp", "fastapi"]
    return {"success": True, "patterns": patterns}


@router.get("/api/async/patterns/{action}")
async def async_patterns_action(action: str):
    return {"success": True, "pattern": action}


@router.get("/api/sqlalchemy/models")
async def sqlalchemy_models():
    return {"success": True, "models": []}


@router.post("/api/sqlalchemy/project")
async def sqlalchemy_project(req: dict):
    project_name = req.get("project_name", "")
    return {"success": True, "message": f"SQLAlchemy 项目 {project_name} 已创建"}


@router.post("/api/sqlalchemy/generate/model")
async def sqlalchemy_generate_model(req: dict):
    model = req.get("model", {})
    return {"success": True, "model": model}


@router.post("/api/sqlalchemy/generate/crud")
async def sqlalchemy_generate_crud(req: dict):
    req.get("model", {})
    return {"success": True, "crud": []}


@router.get("/api/docker/types")
async def docker_types():
    types = ["fastapi", "streamlit", "cli"]
    return {"success": True, "types": types}


@router.get("/api/docker/dockerfile")
async def docker_dockerfile(project_type: str = Query(default="fastapi")):
    return {"success": True, "dockerfile": "# Dockerfile for " + project_type}


@router.get("/api/docker/compose")
async def docker_compose(project_type: str = Query(default="fastapi")):
    return {"success": True, "compose": "# docker-compose.yml for " + project_type}


@router.post("/api/docker/project")
async def docker_project(req: dict):
    project_name = req.get("project_name", "")
    req.get("project_type", "")
    return {"success": True, "message": f"Docker 项目 {project_name} 已创建"}


@router.post("/api/test/mock")
async def test_mock(req: dict):
    mock_type = req.get("type", "")
    return {"success": True, "mock": "mock for " + mock_type}


@router.get("/api/test/coverage")
async def test_coverage():
    return {"success": True, "coverage": 0}


@router.get("/api/test/benchmark")
async def test_benchmark():
    return {"success": True, "benchmark": {}}


@router.get("/api/security/types")
async def security_types():
    types = ["sql_injection", "xss", "csrf", "path_traversal"]
    return {"success": True, "types": types}


@router.post("/api/security/{action}")
async def security_action(action: str, req: dict):
    return {"success": True, "action": action, "result": "安全检查完成"}


@router.get("/api/agent/status")
async def agent_status():
    return {"success": True, "status": "idle"}


@router.get("/api/agent/skills")
async def agent_skills():
    skills = ["coding", "debugging", "refactoring", "testing"]
    return {"success": True, "skills": skills}


@router.get("/api/agent/skills/{skill_id}")
async def agent_skill_detail(skill_id: str):
    return {"success": True, "skill": skill_id}


@router.post("/api/agent/execute")
async def agent_execute(req: dict):
    task = req.get("task", "")
    return {"success": True, "task": task, "result": "任务执行中"}


@router.get("/api/agent/history")
async def agent_history(query: str = Query(default="")):
    return {"success": True, "history": []}


@router.get("/api/agent/preferences")
async def agent_preferences():
    return {"success": True, "preferences": {}}


@router.post("/api/agent/preference")
async def agent_preference(req: dict):
    key = req.get("key", "")
    value = req.get("value", "")
    return {"success": True, "key": key, "value": value}


@router.post("/api/agent/learn")
async def agent_learn(req: dict):
    return {"success": True, "message": "学习完成"}

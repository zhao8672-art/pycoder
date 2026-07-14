"""
AutonomousPipeline — 全自主开发流水线引擎

将 SDLC 完整闭环串联为 7 步自动流水线：
    Step1: TaskDecomposer → 需求分解
    Step2: Agent编码 → LLM+工具循环执行
    Step3: QualityGuard → 质量审查
    Step4: TestGenerator → 测试生成
    Step5: RunFix → 自动修复循环
    Step6: Acceptance → 验收测试
    Step7: Delivery → 打包交付

特性:
    - 自带 Agent 工具循环（不依赖 agent_orchestrator/team_orchestrator）
    - 统一使用 get_workspace_root() 作为工作区
    - 状态持久化，支持断点续跑
    - 进度实时推送（AsyncIterator）
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from pycoder.core.di import registry
from pycoder.core.ports.llm_provider import LLMProvider
from pycoder.server.chat_handler import _get_api_key_for_model
from pycoder.server.log import log

logger = log  # alias for backward compatibility

# ══════════════════════════════════════════════════════════
# 学习引擎集成（不影响主流程）
# ══════════════════════════════════════════════════════════


def _record_pipeline_learning(run) -> None:
    """记录流水线经验到 LearningEngine"""
    try:
        from pycoder.capabilities.self_evo.learning import get_learning_engine

        engine = get_learning_engine()
        status_str = "unknown"
        if hasattr(run, "status"):
            st = run.status
            status_str = st.value if hasattr(st, "value") else str(st)
        report = getattr(run, "report", {})
        quality = report.get("score", 0) if isinstance(report, dict) else 0
        engine.on_pipeline_complete(
            {
                "run_id": getattr(run, "id", ""),
                "status": status_str,
                "request": getattr(run, "request", ""),
                "quality_score": quality,
                "tokens_used": 0,
                "review_rounds": 0,
            }
        )
    except (ImportError, AttributeError, KeyError, ValueError, TypeError) as e:
        log.debug("record_pipeline_learning_failed", error=str(e))


# ══════════════════════════════════════════════════════════
# 常量配置
# ══════════════════════════════════════════════════════════

MAX_AGENT_ITERATIONS = 20  # Agent 工具循环最大迭代次数
TOOL_TIMEOUT = 60  # 工具执行超时 (秒)
MAX_FIX_ROUNDS = 3  # 验收不通过最大修复轮次
MAX_TEST_RETRIES = 3  # 测试失败最大重试
MAX_CONTEXT_TOKENS = 800_000  # DeepSeek 1M 窗口安全阈值（预留 20% 余量）

# 扩展的命令白名单 — 加入开发常用工具
ALLOWED_COMMANDS: list[str] = [
    # 语言运行时
    "python",
    "python3",
    "node",
    "npm",
    "npx",
    "go",
    "rustc",
    "cargo",
    "java",
    "javac",
    # 包管理
    "pip",
    "pip3",
    "uv",
    "uvx",
    "poetry",
    "conda",
    # 版本控制
    "git",
    # 测试
    "pytest",
    "coverage",
    "tox",
    "nox",
    # 代码质量
    "ruff",
    "black",
    "isort",
    "mypy",
    "pylint",
    "flake8",
    # Web 框架
    "uvicorn",
    "fastapi",
    "flask",
    "gunicorn",
    "streamlit",
    # 容器
    "docker",
    "docker-compose",
    # 系统工具
    "ls",
    "dir",
    "echo",
    "cat",
    "type",
    "pwd",
    "cd",
    "mkdir",
    "cp",
    "copy",
    "mv",
    "move",
    "rm",
    "del",
    "curl",
    "wget",
    "ping",
    "nslookup",
    # 打包
    "zip",
    "tar",
    "gzip",
    # Windows
    "where",
    "findstr",
    "tasklist",
    "netstat",
]

# Agent 系统提示词
PIPELINE_AGENT_PROMPT = """你是 PyCoder 全自主开发 Agent。直接输出代码文件。

## 输出规则（关键）
每生成一个文件，用以下格式:
```python:文件路径
完整代码
```

例如:
```python:backend/app.py
from fastapi import FastAPI
app = FastAPI()
```

## 工作方式
1. 我告诉你任务
2. 你输出代码文件（一个或多个）
3. 我确认并告诉你继续
4. **全部完成时，最后回复: 完成**

## 编码规范
- 完整可运行代码，禁止占位符
- Python: PEP 8 + type hints + 中文注释

## 长上下文保护（重要）
- **禁止截断** 函数、类、完整文件
- 上下文容量不足时，分多轮输出，绝不省略代码逻辑
- 每轮结束后标注「继续」或「完成」
- 确保每个文件独立完整可运行"""


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


class PipelineStatus(Enum):
    PENDING = "pending"
    DECOMPOSING = "decomposing"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    TESTING = "testing"
    FIXING = "fixing"
    ACCEPTING = "accepting"
    DELIVERING = "delivering"
    DONE = "done"
    FAILED = "failed"


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """单个步骤的执行结果"""

    name: str
    status: StepStatus = StepStatus.PENDING
    started_at: float = 0.0
    completed_at: float = 0.0
    output: dict = field(default_factory=dict)
    error: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if self.completed_at and self.started_at:
            return (self.completed_at - self.started_at) * 1000
        return 0.0


@dataclass
class PipelineRun:
    """一次完整流水线执行"""

    id: str = field(default_factory=lambda: f"pipeline-{uuid.uuid4().hex[:8]}")
    request: str = ""
    status: PipelineStatus = PipelineStatus.PENDING
    steps: list[StepResult] = field(default_factory=list)
    project_name: str = ""
    work_dir: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    progress: int = 0
    report: dict = field(default_factory=dict)
    error: str = ""
    snapshot_id: str = ""  # 最新版本快照编号
    snapshot_history: list[str] = field(default_factory=list)  # 快照时间线
    context_pool: dict = field(
        default_factory=lambda: {  # 全局上下文池
            "user_origin_command": "",
            "pre_all_output": [],
            "code_version_snapshot": "",
        }
    )
    _cancel_flag: bool = field(default=False, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "request": self.request[:200],
            "status": self.status.value,
            "project_name": self.project_name,
            "work_dir": self.work_dir,
            "progress": self.progress,
            "snapshot_id": self.snapshot_id,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status.value,
                    "duration_ms": round(s.duration_ms),
                    "error": s.error[:200] if s.error else "",
                    "output_keys": list(s.output.keys()),
                }
                for s in self.steps
            ],
            "report": self.report,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


# ══════════════════════════════════════════════════════════
# 公共工具函数
# ══════════════════════════════════════════════════════════


def _get_workspace() -> Path:
    """获取统一工作区根目录"""
    from pycoder.server.routers.files import get_workspace_root

    return get_workspace_root()


async def _execute_agent_tool(tool_name: str, params: dict, workspace: Path) -> str:
    """执行单个 Agent 工具 — 委托到共享 agent_tools 模块"""
    from pycoder.server.services.agent_tools import execute_agent_tool

    return await execute_agent_tool(
        tool_name,
        params,
        workspace,
        timeout=TOOL_TIMEOUT,
        allowed_commands=ALLOWED_COMMANDS,
    )


def _parse_tool_calls(response_text: str) -> list[dict]:
    """解析 LLM 响应中的工具调用 — 委托到共享 agent_tools 模块"""
    from pycoder.server.services.agent_tools import parse_tool_calls

    return parse_tool_calls(response_text)


def _parse_files_from_response(text: str) -> list[dict]:
    """从 LLM 响应中解析 FILE:...```END 块"""
    files: list[dict] = []
    pattern = re.compile(r"```FILE:(.+?)\n(.*?)```END", re.DOTALL)
    for m in pattern.finditer(text):
        path = m.group(1).strip()
        content = m.group(2)
        files.append({"path": path, "content": content})
    return files


def _parse_code_blocks(text: str) -> list[dict]:
    """通用代码块解析 — 从 LLM 响应提取带路径的代码块"""
    files: list[dict] = []

    # 格式1: ```语言:路径\ncode\n```
    for m in re.finditer(r"```(\w+):(\S+?\.\w+)\s*\n(.*?)```", text, re.DOTALL):
        files.append({"path": m.group(2).strip(), "content": m.group(3)})

    # 格式2: # 文件: path 或 # file: path 标题行 + 紧跟代码块
    for m in re.finditer(
        r"(?:#\s*(?:文件|file|FILE)[=: ]*\s*(\S+\.\w+))\s*\n\s*```(?:\w+)?\n(.*?)```",
        text,
        re.DOTALL,
    ):
        p, c = m.group(1).strip(), m.group(2)
        if not any(f["path"] == p for f in files):
            files.append({"path": p, "content": c})

    # 格式3: [WRITE path] + 代码块
    for m in re.finditer(
        r"\[WRITE\s+(\S+?\.\w+)\]\s*\n\s*```(?:\w+)?\n(.*?)```",
        text,
        re.DOTALL,
    ):
        p, c = m.group(1).strip(), m.group(2)
        if not any(f["path"] == p for f in files):
            files.append({"path": p, "content": c})

    # 格式4: ## 创建/生成 xxx.py + 代码块
    for m in re.finditer(
        r"#{2,4}\s*(?:创建|生成|文件|新建|编写).*?[：:]\s*`?(\S+\.\w+)`?\s*\n\s*```(?:\w+)?\n(.*?)```",
        text,
        re.DOTALL,
    ):
        p, c = m.group(1).strip(), m.group(2)
        if not any(f["path"] == p for f in files):
            files.append({"path": p, "content": c})

    return files


def _extract_all_files(text: str) -> list[dict]:
    """组合所有解析器提取文件"""
    files = _parse_files_from_response(text)
    code_files = _parse_code_blocks(text)
    existing = {f["path"] for f in files}
    for cf in code_files:
        if cf["path"] not in existing:
            files.append(cf)
    return files


def _write_extracted_files(files: list[dict], workspace: Path) -> list[str]:
    """将解析出的文件写入工作区磁盘"""
    written: list[str] = []
    for f in files:
        target = (workspace / f["path"]).resolve()
        if target.is_relative_to(workspace):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f["content"], encoding="utf-8")
            written.append(f["path"])
            log.info("pipeline_wrote_file", file=f["path"])
    return written


# ══════════════════════════════════════════════════════════
# 完成信号检测（多语言支持）
# ══════════════════════════════════════════════════════════

_COMPLETION_PATTERNS = [
    # 中文变体
    r"^完成[！!。.]?",
    r"^总结[：:].*",
    r"^所有任务已完成",
    r"^任务完成",
    # 英文变体
    r"^done[.!]?$",
    r"^all tasks? (are )?complete",
    r"^i have (finished|completed)",
    r"^everything is done",
    r"^the (task|project|work) is (done|complete)",
    r"^no (more|further) (tasks?|actions?)",
    # 通用结束标记
    r"^.*(?:---|===)\s*(?:finish|end|summary|总结|完成)\s*(?:---|===)",
]


def _is_completion_signal(text: str) -> bool:
    """检测 LLM 响应是否为完成信号（多语言支持）"""
    clean = text.strip()
    lower = clean.lower()

    # 1. 精确模式匹配（覆盖中英文常见变体）
    import re as _re

    for pat in _COMPLETION_PATTERNS:
        if _re.match(pat, clean) or _re.match(pat, lower):
            return True

    # 2. 按行检查第一行是否短完成信号
    first_line = clean.split("\n")[0].strip()
    first_lower = first_line.lower()
    short_signals = [
        "完成",
        "done",
        "done.",
        "总结",
        "summary",
        "finished",
        "all done",
        "completed",
        "complete",
        "任务已完成",
    ]
    if any(first_lower == s for s in short_signals):
        return True
    if any(first_lower.startswith(s) for s in short_signals):
        return True

    # 3. 检查是否包含"no more"语义 + 无新的工具调用
    if ("no more" in lower or "nothing else" in lower) and len(clean) < 200:
        return True

    return False


# ══════════════════════════════════════════════════════════
# Agent 工具循环
# ══════════════════════════════════════════════════════════


async def _agent_loop(
    llm,
    task: str,
    system_prompt: str,
    workspace: Path,
    max_iterations: int = MAX_AGENT_ITERATIONS,
) -> tuple[str, list[str]]:
    """
    执行 Agent 工具循环: LLM ↔ 代码生成/工具调用

    FIX: 兼容 DeepSeek 直接输出 Markdown 代码块的行为。
    当 LLM 不输出 JSON 工具调用时:
      1. 自动提取代码块写入磁盘
      2. 告知 LLM 已接收，让其继续
      3. 循环直到 LLM 输出 "完成" 或 "DONE"
    """
    llm.config.system_prompt = system_prompt
    llm.config.max_tokens = 16384
    llm.config.enable_cache = True

    all_files_written: list[str] = []
    response_text = ""
    iteration = 0
    completed = False

    prompt = task
    while iteration < max_iterations and not completed:
        iteration += 1

        response_text = ""
        async for event in llm.chat_stream(prompt):
            if event.event_type == "token":
                response_text += event.content
            elif event.event_type == "done":
                response_text = event.content or response_text
                break
            elif event.event_type == "error":
                return f"Agent 错误: {event.content}", all_files_written

        # FIX: 多语言完成信号检测 — 不限于中文
        if _is_completion_signal(response_text):
            files = _extract_all_files(response_text)
            if files:
                written = _write_extracted_files(files, workspace)
                all_files_written.extend(written)
            break

        # 优先检查 JSON 工具调用
        tool_calls = _parse_tool_calls(response_text)
        if tool_calls:
            results: list[str] = []
            for tc in tool_calls:
                result = await _execute_agent_tool(
                    tc["name"],
                    tc.get("params", {}),
                    workspace,
                )
                results.append(f"🔧 {tc['name']}: {result[:2000]}")
                llm.add_message("assistant", f"工具 {tc['name']} 结果:\n{result[:1000]}")
                if tc["name"] == "write_file":
                    all_files_written.append(tc["params"].get("path", "unknown"))
            prompt = (
                f"工具执行结果:\n{'; '.join(results)}\n\n" f"继续完成剩余任务。全部完成请回复: 完成"
            )
        else:
            # DeepSeek 常见行为: 直接输出 Markdown 代码块
            files = _extract_all_files(response_text)
            if files:
                written = _write_extracted_files(files, workspace)
                all_files_written.extend(written)
                file_list = ", ".join(f["path"] for f in files)
                llm.add_message("assistant", f"已生成文件: {file_list}")
                prompt = (
                    f"✅ 已接收文件: {file_list}\n\n" f"请继续生成剩余代码。全部完成请回复: 完成"
                )
            else:
                prompt = "请继续任务。全部完成请回复: 完成"

    # 最终检查
    files = _extract_all_files(response_text)
    if files:
        written = _write_extracted_files(files, workspace)
        all_files_written.extend(written)

    return response_text, all_files_written


def _infer_project_name(desc: str) -> str:
    """从需求描述推断项目名"""
    keywords = {
        "用户": "user-system",
        "图书": "library-system",
        "博客": "blog-system",
        "订单": "order-system",
        "商品": "product-system",
        "股票": "stock-monitor",
        "API": "api-service",
        "爬虫": "crawler",
        "数据": "data-pipeline",
        "聊天": "chat-app",
        "仪表盘": "dashboard",
        "监控": "monitor",
    }
    for kw, name in keywords.items():
        if kw in desc:
            return name
    # 取前几个中文/英文词
    words = re.findall(r"[\u4e00-\u9fff]{2,}", desc)
    return words[0] if words else "my-project"


# ══════════════════════════════════════════════════════════
# 核心流水线引擎
# ══════════════════════════════════════════════════════════


class AutonomousPipeline:
    """全自主开发流水线引擎"""

    def __init__(
        self,
        workspace_root: str | Path | None = None,
        model: str = "deepseek-chat",
        api_key: str | None = None,
    ):
        self._workspace = (Path(workspace_root) if workspace_root else _get_workspace()).resolve()
        self._model = model
        self._api_key = api_key if api_key is not None else _get_api_key_for_model(model)
        self._runs: dict[str, PipelineRun] = {}
        self._active_run: PipelineRun | None = None
        self._agent_bus = None

    @property
    def workspace(self) -> Path:
        return self._workspace

    # ── 长上下文保护 ────────────────────────────────────

    async def _check_context_size(self, files: list[str]) -> bool:
        """检查文件总大小是否超过 Token 安全阈值"""
        total_chars = 0
        for rel_path in files:
            target = self._workspace / rel_path
            if target.exists() and target.is_file():
                try:
                    total_chars += target.stat().st_size
                except OSError:
                    continue
        estimated_tokens = total_chars // 4  # 粗略估算
        return estimated_tokens > MAX_CONTEXT_TOKENS

    def _split_code_task(self, files: list[str], batch_size: int = 10) -> list[list[str]]:
        """将大批文件拆分为多个批次"""
        batches = []
        for i in range(0, len(files), batch_size):
            batches.append(files[i : i + batch_size])
        return batches

    # ── 总线消息发布 ────────────────────────────────────

    async def _publish_bus_message(
        self,
        run: PipelineRun,
        msg_type: str,
        flow_stage: str,
        content: str = "",
        danger_level: str = "l0_none",
        finish_flag: bool = False,
        exception_info: dict | None = None,
        attach_list: list[dict] | None = None,
    ):
        """发布标准化 BusMessage 到 AgentBus（静默失败，不影响主流程）"""
        try:
            from pycoder.server.services.agent_bus import (
                BusMessage,
                DangerLevel,
                FlowStage,
                MessageType,
            )

            _bus = getattr(self, "_agent_bus", None)
            if _bus is None:
                return

            stage_enum = FlowStage.REQUIREMENT
            for s in FlowStage:
                if s.value == flow_stage:
                    stage_enum = s
                    break

            level_enum = DangerLevel.L0_NONE
            for d in DangerLevel:
                if d.value == danger_level:
                    level_enum = d
                    break

            type_enum = MessageType.INFO
            for t in MessageType:
                if t.value == msg_type:
                    type_enum = t
                    break

            msg = BusMessage(
                from_agent="pipeline",
                to_agent="*",
                msg_type=type_enum,
                flow_stage=stage_enum,
                danger_level=level_enum,
                content=content,
                finish_flag=finish_flag,
                context_pool={
                    "user_origin_command": run.request,
                    "code_version_snapshot": run.snapshot_id,
                },
            )
            if exception_info:
                msg.exception_info = exception_info
            if attach_list:
                msg.attach_list = attach_list

            await _bus.send(msg)
        except Exception as e:
            logger.debug("bus_send_failed: %s", e)

    # ── 主入口 ──────────────────────────────────────────

    async def run(
        self,
        user_request: str,
        run_id: str | None = None,
        agent_bus=None,  # 可选注入 AgentBus
    ) -> AsyncIterator[dict]:
        """
        执行完整自主开发流水线

        Yields events:
            {type: "phase", phase: str, message: str, progress: int}
            {type: "task", tasks: [...]}
            {type: "agent_start", role: str, task: str}
            {type: "agent_done", role: str, files: [...]}
            {type: "quality_report", report: {...}}
            {type: "test_result", result: {...}}
            {type: "fix_round", round: int, status: str}
            {type: "acceptance", passed: bool}
            {type: "delivery", package: {...}}
            {type: "done", run_id: str, report: {...}}
            {type: "error", message: str, step: str}
        """
        # 初始化或恢复运行
        if run_id and run_id in self._runs:
            run = self._runs[run_id]
        else:
            run = PipelineRun(request=user_request, work_dir=str(self._workspace))
            self._runs[run.id] = run

        self._active_run = run
        self._agent_bus = agent_bus
        run.project_name = _infer_project_name(user_request)
        # 初始化上下文池
        run.context_pool["user_origin_command"] = user_request

        try:
            yield {
                "type": "pipeline_start",
                "run_id": run.id,
                "request": user_request[:200],
                "project_name": run.project_name,
                "workspace": str(self._workspace),
            }
            await self._publish_bus_message(
                run,
                "task_assign",
                "requirement",
                content=f"启动全自主开发: {user_request[:200]}",
            )

            # ── Step 1: 需求分解 ──
            step1 = await self._step_decompose(run)
            run.steps.append(step1)
            if step1.status == StepStatus.FAILED:
                run.status = PipelineStatus.FAILED
                yield {"type": "error", "message": step1.error, "step": "decompose"}
                await self._publish_bus_message(
                    run,
                    "task_result",
                    "requirement",
                    content=f"需求分解失败: {step1.error[:200]}",
                    danger_level="l1_blocking",
                )
                return

            yield {
                "type": "phase",
                "phase": "decompose",
                "message": "需求已分解",
                "tasks": step1.output.get("tasks", []),
                "progress": 10,
            }
            await self._publish_bus_message(
                run,
                "task_result",
                "requirement",
                content=f"需求分解完成，{len(step1.output.get('tasks', []))} 个子任务",
                finish_flag=True,
            )

            # ── Step 2: Agent 编码 ──
            step2 = await self._step_execute(run)
            run.steps.append(step2)
            files_created = step2.output.get("files_created", [])
            yield {
                "type": "phase",
                "phase": "execute",
                "message": f"Agent编码完成: {len(files_created)} 个文件",
                "files": files_created,
                "progress": 45,
            }
            await self._publish_bus_message(
                run,
                "task_result",
                "coding",
                content=f"编码完成，{len(files_created)} 个文件",
                finish_flag=True,
                attach_list=[{"attach_type": "source", "files": files_created}],
            )

            # ── Step 3: 质量审查 ──
            step3 = await self._step_review(run)
            run.steps.append(step3)
            if step3.status != StepStatus.SKIPPED:
                yield {
                    "type": "quality_report",
                    "report": step3.output.get("report", {}),
                    "progress": 55,
                }
                await self._publish_bus_message(
                    run,
                    "review",
                    "reviewing",
                    content=f"质量审查完成: 评分 {step3.output.get('report', {}).get('score', 'N/A')}",
                    finish_flag=True,
                )

            # ── Step 4: 测试生成 ──
            step4 = await self._step_testgen(run)
            run.steps.append(step4)
            if step4.status != StepStatus.SKIPPED:
                yield {
                    "type": "test_result",
                    "result": step4.output.get("result", {}),
                    "progress": 65,
                }
                await self._publish_bus_message(
                    run,
                    "task_result",
                    "reviewing",
                    content="测试生成完成",
                    finish_flag=True,
                )

            # ── Step 5: 自动修复 ──
            if step3.output.get("files_need_fix") or not step4.output.get("result", {}).get(
                "success", True
            ):
                step5 = await self._step_fixloop(run)
                run.steps.append(step5)
                yield {
                    "type": "phase",
                    "phase": "fix",
                    "message": f"修复完成: {step5.output.get('rounds', 0)} 轮",
                    "progress": 75,
                }
                await self._publish_bus_message(
                    run,
                    "review_fix",
                    "fixing",
                    content=f"自动修复完成: {step5.output.get('rounds', 0)} 轮",
                    finish_flag=True,
                )
            else:
                run.steps.append(
                    StepResult(
                        name="fix",
                        status=StepStatus.SKIPPED,
                        output={"reason": "所有检查通过，无需修复"},
                    )
                )

            # ── Step 6: 验收测试 ──
            step6 = await self._step_accept(run)
            run.steps.append(step6)

            # 验收不通过 → 自动修复循环
            fix_rounds = 0
            while (
                step6.status == StepStatus.FAILED
                and fix_rounds < MAX_FIX_ROUNDS
                and not run._cancel_flag
            ):
                fix_rounds += 1
                yield {
                    "type": "fix_round",
                    "round": fix_rounds,
                    "reason": step6.output.get("reason", "验收不通过"),
                    "progress": 78,
                }
                await self._publish_bus_message(
                    run,
                    "review_fix",
                    "fixing",
                    content=f"第 {fix_rounds} 轮修复 (验收不通过: {step6.output.get('reason', '')[:100]})",
                )

                fix_step = await self._step_fixloop(
                    run,
                    extra_context=step6.output.get("suggestions", ""),
                )
                step6 = await self._step_accept(run)
                run.steps.append(fix_step)

            run.steps[-1] = step6  # 更新最终验收结果
            passed = step6.status == StepStatus.OK
            yield {
                "type": "acceptance",
                "passed": passed,
                "report": step6.output.get("report", {}),
                "progress": 85,
            }
            await self._publish_bus_message(
                run,
                "task_result",
                "reviewing",
                content=f"验收{'通过' if passed else '未通过'}",
                danger_level="l0_none" if passed else "l2_major",
                finish_flag=True,
            )

            # ── Step 7: 打包交付 ──
            step7 = await self._step_deliver(run)
            run.steps.append(step7)
            pkg = step7.output.get("package", {})
            yield {"type": "delivery", "package": pkg, "progress": 95}
            await self._publish_bus_message(
                run,
                "deliver",
                "delivering",
                content="交付包已生成",
                finish_flag=True,
            )

            # ── 完成 ──
            run.status = PipelineStatus.DONE
            run.completed_at = time.time()
            run.progress = 100
            run.report = self._build_report(run)
            yield {"type": "done", "run_id": run.id, "report": run.report, "progress": 100}
            await self._publish_bus_message(
                run,
                "task_result",
                "delivering",
                content=f"全自主开发流水线完成: {run.project_name}",
                danger_level="l0_none",
                finish_flag=True,
            )

            # ── 学习引擎集成：记录流水线经验 ──
            _record_pipeline_learning(run)

        except Exception as e:
            run.status = PipelineStatus.FAILED
            run.error = str(e)
            log.error("pipeline_error", error=str(e))
            # ── 异常分级处理 ──
            try:
                from pycoder.server.services.exception_handler import (
                    ExceptionClassifier,
                )

                classification = ExceptionClassifier.classify(str(e))
                await self._publish_bus_message(
                    run,
                    "task_result",
                    run.status.value,
                    content=f"流水线异常: {str(e)[:200]}",
                    danger_level=classification.level.value,
                    exception_info={
                        "is_exception": True,
                        "exception_desc": str(e)[:500],
                        "rollback_snapshot_id": run.snapshot_id,
                    },
                )
            except Exception as e:
                logger.debug("error_event_send_failed: %s", e)
            # ── 学习引擎集成：记录失败 ──
            _record_pipeline_learning(run)
            yield {"type": "error", "message": str(e), "step": run.status.value}
        finally:
            self._active_run = None

    # ── 步骤查找辅助 ────────────────────────────────────

    def _find_step(self, run: PipelineRun, name: str) -> StepResult | None:
        """按名称查找步骤（从后往前，优先返回最近的匹配）"""
        for s in reversed(run.steps):
            if s.name == name:
                return s
        return None

    # ── Step 1: 需求分解 ────────────────────────────────

    async def _step_decompose(self, run: PipelineRun) -> StepResult:
        """使用 LLM 或保底逻辑分解需求"""
        step = StepResult(name="decompose", status=StepStatus.RUNNING)
        step.started_at = time.time()
        run.status = PipelineStatus.DECOMPOSING

        try:
            from pycoder.server.services.task_decomposer import (
                _fallback_decomposition,
                decompose_task,
            )

            if self._api_key:
                llm = registry.resolve(LLMProvider)
                llm.configure(model=self._model, api_key=self._api_key)
                try:
                    tasks = await decompose_task(run.request, llm)
                    await llm.close()
                except Exception as e:
                    # LLM 任务分解可能因网络/解析/模型失败，回退到规则分解
                    log.warning("decompose_task_failed fallback=rule_based", error=str(e))
                    tasks = _fallback_decomposition(run.request)
            else:
                tasks = _fallback_decomposition(run.request)

            tasks_data = [
                {
                    "id": t.id,
                    "title": t.title,
                    "description": t.description,
                    "assigned_role": t.assigned_role,
                    "depends_on": list(t.depends_on),
                    "deliverables": t.deliverables,
                }
                for t in tasks
            ]

            step.status = StepStatus.OK
            step.output = {
                "tasks": tasks_data,
                "task_count": len(tasks),
                "project_name": run.project_name,
            }
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)

        step.completed_at = time.time()
        return step

    # ── Step 2: Agent 编码 ──────────────────────────────

    async def _step_execute(self, run: PipelineRun) -> StepResult:
        """Agent 编码 — 使用工具循环执行所有开发任务"""
        step = StepResult(name="execute", status=StepStatus.RUNNING)
        step.started_at = time.time()
        run.status = PipelineStatus.EXECUTING
        run.progress = 15

        decompose_step = self._find_step(run, "decompose")
        tasks = decompose_step.output.get("tasks", []) if decompose_step else []
        all_files: list[str] = []

        if not tasks:
            step.status = StepStatus.FAILED
            step.error = "无任务可执行"
            step.completed_at = time.time()
            return step

        # 角色定义
        role_prompts = {
            "architect": "你是架构师。设计项目结构、API端点、数据模型。输出完整的架构设计。",
            "developer": "你是全栈开发者。根据架构设计编写完整可运行代码。"
            "使用工具: read_file查看文件, write_file输出代码, list_files查看结构。",
            "qa": "你是QA工程师。为项目编写测试用例并运行pytest。"
            "使用工具: write_file写测试, run_command运行pytest。",
            "devops": "你是DevOps工程师。生成Dockerfile、docker-compose.yml、README.md。",
            "pm": "你是项目经理。协调整体进度。",
        }

        # 按依赖顺序执行
        executed: set[str] = set()
        max_rounds = 20
        round_num = 0

        while len(executed) < len(tasks) and round_num < max_rounds:
            round_num += 1
            available = [
                t
                for t in tasks
                if t["id"] not in executed
                and all(dep in executed for dep in t.get("depends_on", []))
            ]
            if not available:
                # 可能存在循环依赖，执行剩余所有任务
                available = [t for t in tasks if t["id"] not in executed]
                if not available:
                    break

            for task in available:
                if run._cancel_flag:
                    break

                role = task["assigned_role"]
                role_desc = role_prompts.get(role, "你是开发者。完成编码任务。")

                task_prompt = f"""任务: {task['title']}
描述: {task['description']}
交付物: {', '.join(task.get('deliverables', []))}

请:
1. 先用 list_files 查看当前项目结构
2. 用 write_file 输出完整的代码文件
3. 每个文件输出完整代码，不使用占位符
4. 完成后输出总结"""
                llm = None
                try:
                    llm = registry.resolve(LLMProvider)
                    llm.configure(
                        model="deepseek-reasoner" if role == "architect" else self._model,
                        api_key=self._api_key,
                    )
                    _, files = await _agent_loop(
                        llm,
                        task_prompt,
                        PIPELINE_AGENT_PROMPT + "\n\n" + role_desc,
                        self._workspace,
                        max_iterations=12,
                    )
                    all_files.extend(files)
                finally:
                    if llm is not None:
                        await llm.close()

                executed.add(task["id"])

            run.progress = 15 + int(30 * len(executed) / max(len(tasks), 1))

        step.status = StepStatus.OK
        step.output = {
            "files_created": list(set(all_files)),
            "tasks_completed": len(executed),
            "tasks_total": len(tasks),
        }
        step.completed_at = time.time()

        # ── 创建编码完成快照 ──
        try:
            from pycoder.server.services.version_snapshot import SnapshotManager

            snap_mgr = SnapshotManager(self._workspace)
            snap = await snap_mgr.create_snapshot(
                label=f"编码完成: {run.project_name}",
                pipeline_step="execute",
                parent_id=run.snapshot_id if run.snapshot_id else None,
            )
            run.snapshot_id = snap.id
            run.snapshot_history.append(snap.id)
            run.context_pool["code_version_snapshot"] = snap.id
        except Exception as e:
            log.debug("snapshot_creation_failed", error=str(e))

        return step

    # ── Step 3: 质量审查 ────────────────────────────────

    async def _step_review(self, run: PipelineRun) -> StepResult:
        """代码质量审查"""
        step = StepResult(name="review", status=StepStatus.RUNNING)
        step.started_at = time.time()
        run.status = PipelineStatus.REVIEWING

        prev_output = run.steps[-1].output if run.steps else {}
        files = prev_output.get("files_created", [])
        if not files:
            step.status = StepStatus.SKIPPED
            step.completed_at = time.time()
            return step

        try:
            from pycoder.server.services.quality_guard import QualityGuard

            guard = QualityGuard(workspace_root=self._workspace)
            all_scores: list[int] = []
            files_need_fix: list[str] = []

            for fpath in files:
                if not fpath.endswith(".py"):
                    continue
                report = await guard.check(fpath)
                all_scores.append(report.score)
                if not report.is_pass(min_score=60):
                    files_need_fix.append(fpath)

            avg_score = int(sum(all_scores) / len(all_scores)) if all_scores else 100
            step.status = StepStatus.OK
            step.output = {
                "report": {
                    "average_score": avg_score,
                    "files_checked": len(all_scores),
                    "files_need_fix": files_need_fix,
                },
                "files_need_fix": files_need_fix,
            }
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)

        step.completed_at = time.time()
        return step

    # ── Step 4: 测试生成 ────────────────────────────────

    async def _step_testgen(self, run: PipelineRun) -> StepResult:
        """智能测试生成"""
        step = StepResult(name="testgen", status=StepStatus.RUNNING)
        step.started_at = time.time()
        run.status = PipelineStatus.TESTING

        prev_output = run.steps[-1].output if run.steps else {}
        files = prev_output.get("files_created", [])
        py_files = [f for f in files if f.endswith(".py") and "test_" not in f]
        if not py_files:
            step.status = StepStatus.SKIPPED
            step.completed_at = time.time()
            return step

        try:
            from pycoder.server.services.test_generator import TestGenerator

            gen = TestGenerator(workspace_root=self._workspace)

            all_results: list[dict] = []
            for fpath in py_files[:5]:  # 最多测试5个文件
                result = gen.generate(fpath)
                all_results.append(
                    {
                        "file": fpath,
                        "success": result.success,
                        "test_count": result.test_count,
                        "passed": result.passed,
                        "failed": result.failed,
                        "coverage": result.coverage_percent,
                    }
                )

            overall = all(r["success"] for r in all_results)
            step.status = StepStatus.OK
            step.output = {
                "result": {
                    "success": overall,
                    "files_tested": len(all_results),
                    "total_tests": sum(r["test_count"] for r in all_results),
                    "total_passed": sum(r["passed"] for r in all_results),
                    "total_failed": sum(r["failed"] for r in all_results),
                    "details": all_results,
                },
            }
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)

        step.completed_at = time.time()
        return step

    # ── Step 5: 自动修复 ────────────────────────────────

    async def _step_fixloop(
        self,
        run: PipelineRun,
        extra_context: str = "",
    ) -> StepResult:
        """自动修复循环 — 遍历所有步骤收集需要修复的文件"""
        step = StepResult(name="fix", status=StepStatus.RUNNING)
        step.started_at = time.time()
        run.status = PipelineStatus.FIXING

        # FIX: 遍历所有步骤收集 files_need_fix，而非只看 run.steps[-1]
        files_need_fix: list[str] = []
        for s in run.steps:
            sfx = s.output.get("files_need_fix", [])
            if sfx:
                files_need_fix.extend(sfx)
        files_need_fix = list(set(files_need_fix))

        # 如果没有任何需修复文件但有验收失败的额外上下文，
        # 则从 execute 步骤获取所有生成的文件尝试修复
        if not files_need_fix and extra_context:
            for s in run.steps:
                if s.name == "execute":
                    files_need_fix = s.output.get("files_created", [])
                    break
            files_need_fix = [f for f in files_need_fix if f.endswith(".py")]

        if not files_need_fix:
            step.status = StepStatus.SKIPPED
            step.completed_at = time.time()
            return step

        # ── 创建修复前快照 ──
        try:
            from pycoder.server.services.version_snapshot import SnapshotManager

            snap_mgr = SnapshotManager(self._workspace)
            pre_snap = await snap_mgr.create_snapshot(
                label=f"修复前: {run.project_name}",
                pipeline_step="fix_before",
                parent_id=run.snapshot_id if run.snapshot_id else None,
            )
            step.metadata["pre_fix_snapshot"] = pre_snap.id
        except Exception as e:
            logger.debug("pre_fix_snapshot_failed: %s", e)

        fixed_count = 0

        fixed_count = 0
        for fpath in files_need_fix[:3]:  # 最多修3个
            if run._cancel_flag:
                break
            target = self._workspace / fpath
            if not target.exists():
                continue
            try:
                code = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError, PermissionError) as e:
                log.debug("read_source_failed", path=str(target), error=str(e))
                continue

            fix_prompt = f"""修复以下文件的代码质量问题:

文件: {fpath}
当前代码:
```python
{code[:6000]}
```

额外反馈: {extra_context}

请修复所有发现的问题，使用 write_file 输出修复后的完整代码。"""
            llm = registry.resolve(LLMProvider)
            try:
                llm.configure(model=self._model, api_key=self._api_key)
                _, files = await _agent_loop(
                    llm,
                    fix_prompt,
                    PIPELINE_AGENT_PROMPT,
                    self._workspace,
                    max_iterations=8,
                )
                fixed_count += 1
            finally:
                if llm is not None:
                    await llm.close()

        step.status = StepStatus.OK
        step.output = {"rounds": 1, "files_fixed": fixed_count}
        step.completed_at = time.time()

        # ── 创建修复后快照 ──
        try:
            from pycoder.server.services.version_snapshot import SnapshotManager

            snap_mgr = SnapshotManager(self._workspace)
            post_snap = await snap_mgr.create_snapshot(
                label=f"修复后: {run.project_name}",
                pipeline_step="fix_after",
                parent_id=run.snapshot_id if run.snapshot_id else None,
            )
            run.snapshot_id = post_snap.id
            run.snapshot_history.append(post_snap.id)
            run.context_pool["code_version_snapshot"] = post_snap.id
            step.metadata["post_fix_snapshot"] = post_snap.id
        except Exception as e:
            logger.debug("post_fix_snapshot_failed: %s", e)

        return step

    # ── Step 6: 验收测试 ────────────────────────────────

    async def _step_accept(self, run: PipelineRun) -> StepResult:
        """验收测试 — 检查需求是否满足"""
        step = StepResult(name="accept", status=StepStatus.RUNNING)
        step.started_at = time.time()
        run.status = PipelineStatus.ACCEPTING

        # 获取所有生成的文件
        execute_step = self._find_step(run, "execute")
        files = execute_step.output.get("files_created", []) if execute_step else []

        if not files:
            step.status = StepStatus.FAILED
            step.error = "无生成文件可验收"
            step.completed_at = time.time()
            return step

        try:
            # 基本验收: 文件存在 + 可导入/可运行
            issues: list[str] = []
            for fpath in files:
                target = self._workspace / fpath
                if not target.exists():
                    issues.append(f"文件缺失: {fpath}")
                    continue

                if fpath.endswith(".py"):
                    try:
                        code = target.read_text(encoding="utf-8")
                        compile(code, fpath, "exec")
                    except SyntaxError as e:
                        issues.append(f"语法错误 {fpath}: {e.msg}")

            # LLM 验收 (如果有 API Key)
            if self._api_key and files:
                llm = registry.resolve(LLMProvider)
                llm.configure(model=self._model, api_key=self._api_key)
                try:
                    file_list = "\n".join(f"  - {f}" for f in files[:15])
                    prompt = f"""请验收以下项目:

原始需求: {run.request}

生成的文件:
{file_list}

请逐项检查是否满足需求。输出 JSON:
{{"passed": true/false, "issues": ["问题1", "问题2"], "score": 0-100}}"""

                    llm.config.system_prompt = "你是项目验收专家。"
                    llm.config.max_tokens = 2048
                    result = ""
                    async for event in llm.chat_stream(prompt):
                        if event.event_type == "token":
                            result += event.content
                        elif event.event_type == "done":
                            result = event.content or result

                    # 解析验收结果
                    try:
                        cleaned = result.strip()
                        if cleaned.startswith("```"):
                            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
                        verdict = json.loads(cleaned)
                        if not verdict.get("passed", True):
                            issues.extend(verdict.get("issues", []))
                    except (json.JSONDecodeError, Exception):
                        pass  # 解析失败不影响
                finally:
                    await llm.close()

            passed = len(issues) == 0
            step.status = StepStatus.OK if passed else StepStatus.FAILED
            step.output = {
                "report": {
                    "passed": passed,
                    "files_checked": len(files),
                    "issues": issues,
                    "suggestions": issues,
                },
                "reason": "; ".join(issues) if issues else "验收通过",
                "suggestions": "; ".join(issues) if issues else "",
            }
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)

        step.completed_at = time.time()
        return step

    # ── Step 7: 打包交付 ────────────────────────────────

    async def _step_deliver(self, run: PipelineRun) -> StepResult:
        """打包交付"""
        step = StepResult(name="deliver", status=StepStatus.RUNNING)
        step.started_at = time.time()
        run.status = PipelineStatus.DELIVERING

        try:
            # 收集所有生成的文件
            all_files: list[str] = []
            for s in run.steps:
                files = s.output.get("files_created", [])
                all_files.extend(files)
            all_files = list(set(all_files))

            # 生成 README.md (如果没有)
            readme_path = self._workspace / "README.md"
            if not readme_path.exists() and self._api_key:
                await self._generate_readme(run, all_files)

            # 生成 DELIVERY.md
            delivery_md = self._workspace / "DELIVERY.md"
            delivery_content = self._build_delivery_md(run, all_files)
            delivery_md.write_text(delivery_content, encoding="utf-8")

            # 尝试创建 zip 包
            zip_path = ""
            try:
                zip_dir = self._workspace / ".pycoder_delivery"
                zip_dir.mkdir(parents=True, exist_ok=True)
                zip_target = zip_dir / f"{run.project_name}.zip"
                if shutil.which("zip"):
                    subprocess.run(
                        ["zip", "-r", str(zip_target), "."],
                        cwd=str(self._workspace),
                        capture_output=True,
                    )
                elif shutil.which("tar"):
                    subprocess.run(
                        ["tar", "-czf", f"{zip_target.with_suffix('.tar.gz')}", "."],
                        cwd=str(self._workspace),
                        capture_output=True,
                    )
                zip_path = str(zip_target)
            except (subprocess.SubprocessError, OSError) as e:
                log.debug("delivery_zip_failed", error=str(e))

            step.status = StepStatus.OK
            step.output = {
                "package": {
                    "project_name": run.project_name,
                    "files_count": len(all_files),
                    "workspace": str(self._workspace),
                    "zip_path": zip_path or "未生成 (缺少打包工具)",
                    "delivery_md": str(delivery_md),
                },
            }
        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)

        step.completed_at = time.time()
        return step

    # ── 辅助方法 ────────────────────────────────────────

    async def _generate_readme(
        self,
        run: PipelineRun,
        files: list[str],
    ) -> None:
        """LLM 生成 README.md"""
        llm = registry.resolve(LLMProvider)
        try:
            llm.configure(model=self._model, api_key=self._api_key)
            file_list = "\n".join(f"  - {f}" for f in files[:20])
            prompt = f"""请为以下项目生成完整的 README.md:

项目名: {run.project_name}
项目描述: {run.request}

生成的文件:
{file_list}

README 必须包含:
- 项目简介
- 安装步骤
- 使用方法
- API 文档 (如果有)
- 项目结构"""
            llm.config.system_prompt = "你是技术文档撰写专家。"
            llm.config.max_tokens = 4096
            result = ""
            async for event in llm.chat_stream(prompt):
                if event.event_type == "token":
                    result += event.content
                elif event.event_type == "done":
                    result = event.content or result

            readme = self._workspace / "README.md"
            readme.write_text(result, encoding="utf-8")
        finally:
            await llm.close()

    def _build_delivery_md(self, run: PipelineRun, files: list[str]) -> str:
        """构建交付文档"""
        lines = [
            f"# {run.project_name} — 交付报告",
            "",
            f"> 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"> 流水线ID: {run.id}",
            "",
            "## 需求",
            run.request,
            "",
            "## 执行步骤",
        ]
        for s in run.steps:
            icon = (
                "✅"
                if s.status == StepStatus.OK
                else "⚠️" if s.status == StepStatus.FAILED else "⏭️"
            )
            lines.append(f"- {icon} **{s.name}**: {s.status.value} ({s.duration_ms:.0f}ms)")
            if s.error:
                lines.append(f"  - 错误: {s.error[:100]}")

        lines += [
            "",
            "## 生成文件",
        ]
        for f in sorted(files):
            target = self._workspace / f
            size = target.stat().st_size if target.exists() else 0
            lines.append(f"- `{f}` ({size} 字节)")

        lines += [
            "",
            "## 质量报告",
        ]
        review = next((s for s in run.steps if s.name == "review"), None)
        if review and review.status != StepStatus.SKIPPED:
            lines.append(f"平均评分: {review.output.get('report', {}).get('average_score', 'N/A')}")
            lines.append(f"需修复文件: {review.output.get('files_need_fix', [])}")

        test_gen = next((s for s in run.steps if s.name == "testgen"), None)
        if test_gen and test_gen.status != StepStatus.SKIPPED:
            tr = test_gen.output.get("result", {})
            lines.append(f"测试: {tr.get('total_passed', 0)}/{tr.get('total_tests', 0)} 通过")

        accept = next((s for s in run.steps if s.name == "accept"), None)
        if accept:
            lines.append(f"验收: {'通过' if accept.status == StepStatus.OK else '未通过'}")

        return "\n".join(lines)

    def _build_report(self, run: PipelineRun) -> dict:
        """构建最终报告"""
        total_files = 0
        for s in run.steps:
            total_files += len(s.output.get("files_created", []))

        return {
            "run_id": run.id,
            "project_name": run.project_name,
            "request": run.request[:200],
            "steps_count": len(run.steps),
            "total_files": total_files,
            "duration_seconds": round(
                (run.completed_at - run.created_at) if run.completed_at else 0, 1
            ),
            "status": run.status.value,
        }

    # ── 管理方法 ────────────────────────────────────────

    def list_runs(self, limit: int = 10) -> list[dict]:
        """列出最近的流水线执行记录"""
        runs = sorted(
            self._runs.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )
        return [r.to_dict() for r in runs[:limit]]

    def get_run(self, run_id: str) -> dict | None:
        """获取单次执行详情"""
        run = self._runs.get(run_id)
        return run.to_dict() if run else None

    def cancel_run(self, run_id: str) -> bool:
        """取消正在执行的流水线"""
        run = self._runs.get(run_id)
        if run and run.status not in (PipelineStatus.DONE, PipelineStatus.FAILED):
            run._cancel_flag = True
            return True
        return False


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

_pipeline: AutonomousPipeline | None = None


def get_pipeline() -> AutonomousPipeline:
    """获取 AutonomousPipeline 全局单例"""
    global _pipeline
    if _pipeline is None:
        _pipeline = AutonomousPipeline()
    return _pipeline

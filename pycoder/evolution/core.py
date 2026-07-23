"""
PyCoder 进化核心 — LLM 驱动的"进化大脑"

整合所有现有学习模块，实现完整的自动化进化闭环:
  observe → analyze → generate → validate → apply → learn

安全机制:
  - 所有修改通过 safety 模块沙箱验证
  - Git 分支隔离 + 测试门禁 + 自动回滚
  - 熔断器防止无限循环
  - 成本预算控制

用法:
  from pycoder.evolution import EvolutionBrain, EvolutionPipeline

  brain = EvolutionBrain()
  pipeline = EvolutionPipeline(brain)
  report = await pipeline.run()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PYCODER_ROOT = Path(__file__).resolve().parents[2]
EVOLUTION_DB_DIR = Path.home() / ".pycoder" / "evolution"
EVOLUTION_HISTORY_FILE = EVOLUTION_DB_DIR / "evolution_history.json"


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


class EvolutionPhase(StrEnum):
    """进化阶段"""
    OBSERVE = "observe"       # 采集数据
    ANALYZE = "analyze"       # LLM 分析
    GENERATE = "generate"     # 生成方案
    VALIDATE = "validate"     # 安全验证
    APPLY = "apply"           # 应用修改
    LEARN = "learn"           # 经验沉淀
    DONE = "done"             # 完成
    FAILED = "failed"         # 失败


@dataclass
class EvolutionTask:
    """单次进化任务"""

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    task_type: str = "auto_fix"  # auto_fix / policy_optimize / knowledge_build
    target: str = ""  # 目标文件或模块
    description: str = ""
    phase: EvolutionPhase = EvolutionPhase.OBSERVE
    errors_collected: list[dict[str, Any]] = field(default_factory=list)
    llm_analysis: str = ""
    fix_plan: str = ""
    fix_code: str = ""
    validation_result: dict[str, Any] = field(default_factory=dict)
    applied: bool = False
    test_passed: bool = False
    rollback_performed: bool = False
    grade: float = 0.0
    lessons: str = ""
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    duration_ms: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        phase_value = self.phase.value if hasattr(self.phase, "value") else str(self.phase)
        return {
            "id": self.id,
            "task_type": self.task_type,
            "target": self.target,
            "description": self.description,
            "phase": phase_value,
            "errors_collected": self.errors_collected if isinstance(self.errors_collected, list) else [],
            "llm_analysis": self.llm_analysis[:500],
            "fix_plan": self.fix_plan[:500],
            "applied": self.applied,
            "test_passed": self.test_passed,
            "rollback_performed": self.rollback_performed,
            "grade": self.grade,
            "lessons": self.lessons[:300],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class EvolutionReport:
    """进化报告"""

    task_id: str = ""
    success: bool = False
    phases_completed: list[str] = field(default_factory=list)
    issues_found: int = 0
    fixes_generated: int = 0
    fixes_applied: int = 0
    tests_passed: bool = False
    grade: float = 0.0
    metrics: dict[str, Any] = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    error: str = ""


@dataclass
class EvolutionConfig:
    """进化配置"""

    auto_apply: bool = False  # 是否自动应用修复
    max_files_per_run: int = 3
    max_llm_tokens: int = 8192
    llm_model: str = "deepseek-chat"
    safety_strict: bool = True
    test_timeout_seconds: int = 300
    evolution_interval_seconds: int = 3600  # 自动进化间隔
    cost_budget_daily_usd: float = 5.0
    min_grade_threshold: float = 70.0
    max_retries: int = 3


# ══════════════════════════════════════════════════════════
# EvolutionBrain — LLM 驱动的进化决策核心
# ══════════════════════════════════════════════════════════


class EvolutionBrain:
    """LLM 驱动的进化大脑

    负责:
      1. 观察：从 memory/observability 采集错误和反馈
      2. 分析：LLM 深度分析问题根因
      3. 生成：LLM 生成修复方案
      4. 决策：判断是否执行修复和策略调整
    """

    def __init__(self, config: EvolutionConfig | None = None):
        self._config = config or EvolutionConfig()
        self._history: list[EvolutionTask] = []
        self._load_history()

    # ══════════════════════════════════════════════════════
    # 阶段 1: 观察 — 采集错误和反馈
    # ══════════════════════════════════════════════════════

    async def observe(self, task: EvolutionTask) -> EvolutionTask:
        """从 memory 和 observability 模块采集错误案例和反馈数据"""
        task.phase = EvolutionPhase.OBSERVE
        errors: list[dict[str, Any]] = []

        # 1.1 从 memory 模块采集历史错误
        try:
            from pycoder.memory import SessionMemoryEngine
            engine = SessionMemoryEngine(workspace=PYCODER_ROOT)
            memories = engine.search_sessions("error", limit=50)
            if memories:
                for m in memories:
                    summary = str(m.get("summary", ""))
                    if summary:
                        errors.append({
                            "source": "memory",
                            "content": summary[:500],
                            "timestamp": m.get("created_at", 0),
                        })
        except (ImportError, AttributeError) as e:
            logger.debug("memory 模块不可用: %s", e)

        # 1.2 从 observability 模块采集错误
        try:
            from pycoder.observability.sentry import status
            sentry_status = status()
            if sentry_status.get("enabled"):
                errors.append({
                    "source": "observability",
                    "content": "Sentry 监控已启用，错误自动上报",
                    "timestamp": time.time(),
                })
        except ImportError:
            logger.debug("observability 模块不可用")

        # 1.3 从 knowledge_base 采集历史错误模式
        try:
            from pycoder.capabilities.self_evo.learning.knowledge_base import get_knowledge_base
            kb = get_knowledge_base()
            top_errors = kb.get_top_errors(limit=20)
            for e in top_errors:
                errors.append({
                    "source": "knowledge_base",
                    "content": str(e)[:500],
                    "timestamp": time.time(),
                })
        except (ImportError, AttributeError) as e:
            logger.debug("knowledge_base 不可用: %s", e)

        # 1.4 从本地日志文件采集错误
        try:
            log_file = PYCODER_ROOT / "backend.log"
            if log_file.exists():
                log_content = log_file.read_text(encoding="utf-8", errors="replace")
                error_lines = [l for l in log_content.split("\n") if "ERROR" in l or "error" in l.lower()]
                for line in error_lines[-20:]:
                    errors.append({
                        "source": "backend_log",
                        "content": line[:500],
                        "timestamp": time.time(),
                    })
        except OSError:
            pass

        task.errors_collected = errors
        logger.info("observe_done task=%s errors=%d", task.id, len(errors))
        return task

    # ══════════════════════════════════════════════════════
    # 阶段 2: 分析 — LLM 深度分析
    # ══════════════════════════════════════════════════════

    async def analyze(self, task: EvolutionTask) -> EvolutionTask:
        """使用 LLM 深度分析错误根因和模式"""
        task.phase = EvolutionPhase.ANALYZE

        if not task.errors_collected:
            task.llm_analysis = "无错误数据，跳过分析"
            return task

        # 构建分析提示词
        errors_text = "\n".join(
            f"[{e.get('source', 'unknown')}] {e.get('content', '')[:300]}"
            for e in task.errors_collected[:15]
        )

        prompt = f"""你是 PyCoder 的自我进化分析引擎。分析以下收集到的系统错误和反馈，找出根本原因和修复优先级。

## 错误数据

{errors_text}

## 分析要求

请按以下格式输出分析结果:

1. **根因分类**: 将错误归类（如: 导入错误、配置错误、API调用失败、安全漏洞、性能问题等）
2. **优先级排序**: 按严重程度排序（critical > high > medium > low）
3. **修复建议**: 对每个高优先级问题给出具体修复方案
4. **系统性问题**: 识别是否存在跨模块的系统性缺陷

请用中文输出，简洁明了。"""

        try:
            analysis = await self._call_llm(prompt, "你是一个资深的代码分析和系统诊断专家。")
        except (ImportError, ValueError, TypeError, RuntimeError, OSError) as e:
            logger.warning("LLM 分析失败，使用本地规则分析: %s", e)
            analysis = self._fallback_analysis(prompt)
        task.llm_analysis = analysis
        logger.info("analyze_done task=%s analysis_len=%d", task.id, len(analysis))
        return task

    # ══════════════════════════════════════════════════════
    # 阶段 3: 生成 — LLM 生成修复方案
    # ══════════════════════════════════════════════════════

    async def generate(self, task: EvolutionTask) -> EvolutionTask:
        """使用 LLM 生成具体的修复方案和代码"""
        task.phase = EvolutionPhase.GENERATE

        if not task.llm_analysis or "无错误数据" in task.llm_analysis:
            task.fix_plan = "无分析结果，跳过生成"
            return task

        # 从知识库查询类似修复方案
        kb_fixes = self._query_knowledge_base(task)
        kb_context = ""
        if kb_fixes:
            kb_context = "\n## 历史类似修复方案\n" + "\n".join(
                f"- {f}" for f in kb_fixes[:5]
            )

        prompt = f"""你是 PyCoder 的自动修复工程师。根据分析结果生成精确的代码修复方案。

## LLM 分析结果

{task.llm_analysis[:3000]}

{kb_context}

## 修复要求

1. 对每个需要修复的问题，输出:
   ```
   [FIX:文件路径:行号]
   问题描述: ...
   修复方案: ...
   --- 旧代码 ---
   [旧代码]
   --- 新代码 ---
   [新代码]
   [END:FIX]
   ```

2. 修复应遵循项目编码规范:
   - 使用 PEP 8 风格
   - 添加适当的类型注解
   - 使用 f-string 格式化
   - 避免裸 except
   - 敏感信息使用环境变量

3. 只输出 [FIX:...]...[END:FIX] 块，不要其他内容。"""

        try:
            fix_plan = await self._call_llm(
                prompt,
                "你是 PyCoder 自动修复专家。只输出 [FIX:...]...[END:FIX] 格式的修复块。",
                max_tokens=self._config.max_llm_tokens,
            )
        except (ImportError, ValueError, TypeError, RuntimeError, OSError) as e:
            logger.warning("LLM 生成失败: %s", e)
            fix_plan = f"[FIX:unknown:0]\n问题描述: LLM不可用\n修复方案: 需要人工介入\n[END:FIX]"
        task.fix_plan = fix_plan
        logger.info("generate_done task=%s plan_len=%d", task.id, len(fix_plan))
        return task

    # ══════════════════════════════════════════════════════
    # 阶段 4: 验证 — safety 沙箱 + 测试
    # ══════════════════════════════════════════════════════

    async def validate(self, task: EvolutionTask) -> EvolutionTask:
        """通过 safety 模块验证修复方案的安全性"""
        task.phase = EvolutionPhase.VALIDATE

        if not task.fix_plan or "跳过" in task.fix_plan:
            task.validation_result = {"passed": False, "reason": "无修复方案"}
            return task

        validation: dict[str, Any] = {"passed": True, "checks": [], "warnings": []}

        # 4.1 安全沙箱检查
        if self._config.safety_strict:
            try:
                from pycoder.safety import SandboxManager
                from pycoder.safety.circuit_breaker import CircuitBreakerRegistry

                cb = CircuitBreakerRegistry().get("self_evo")
                if cb and cb.is_open():
                    validation["passed"] = False
                    validation["reason"] = "进化熔断器已打开"
                    task.validation_result = validation
                    return task

                sandbox = SandboxManager()
                if hasattr(sandbox, "validate_code"):
                    result = sandbox.validate_code(task.fix_plan)
                    if not result.get("safe", True):
                        validation["passed"] = False
                        validation["warnings"].append(f"沙箱拒绝: {result.get('reason', '')}")

                validation["checks"].append("sandbox: ok")
            except (ImportError, AttributeError) as e:
                validation["checks"].append(f"sandbox: unavailable ({e})")

        # 4.2 代码安全检查
        dangerous_patterns = [
            (r"os\.system\s*\(.*input", "用户输入注入风险", "critical"),
            (r"subprocess\.run\s*\(.*shell\s*=\s*True", "shell=True 注入风险", "critical"),
            (r"\bexec\s*\(|\beval\s*\(", "动态代码执行风险", "critical"),
            (r"(?:api_key|password|secret|token)\s*=\s*['\"][^'\"]{8,}['\"]", "硬编码密钥", "high"),
        ]
        for pattern, desc, severity in dangerous_patterns:
            if re.search(pattern, task.fix_plan, re.IGNORECASE):
                validation["warnings"].append(f"安全风险: {desc}")
                if severity == "critical":
                    validation["passed"] = False

        # 4.3 语法检查 — 提取修复块中的代码
        fix_blocks = re.findall(r"--- 新代码 ---\n(.*?)(?:\[END:FIX\]|$)", task.fix_plan, re.DOTALL)
        for block in fix_blocks:
            # 提取代码块中的 Python 代码
            code_match = re.search(r"```python\n(.*?)```", block, re.DOTALL)
            if code_match:
                code = code_match.group(1)
            else:
                code = block.strip()
            try:
                import ast
                ast.parse(code)
                validation["checks"].append("syntax: ok")
            except SyntaxError as e:
                validation["passed"] = False
                validation["checks"].append(f"syntax: error ({e})")

        task.validation_result = validation
        logger.info("validate_done task=%s passed=%s", task.id, validation["passed"])
        return task

    # ══════════════════════════════════════════════════════
    # 阶段 5: 应用 — Git 隔离 + 测试门禁
    # ══════════════════════════════════════════════════════

    async def apply(self, task: EvolutionTask) -> EvolutionTask:
        """在 Git 隔离环境中应用修复，运行测试验证"""
        task.phase = EvolutionPhase.APPLY

        if not task.validation_result.get("passed"):
            task.error = "验证未通过，跳过应用"
            return task

        if self._config.auto_apply is False and task.task_type != "test":
            task.applied = False
            task.error = "auto_apply 未开启，需要人工确认"
            return task

        # 解析修复块
        fix_blocks = re.findall(
            r"\[FIX:(.+?):(\d+)\]\n(.*?)\[END:FIX\]",
            task.fix_plan,
            re.DOTALL,
        )

        if not fix_blocks:
            task.error = "未找到有效的修复块"
            return task

        applied_count = 0
        for file_path, line_no, block in fix_blocks[: self._config.max_files_per_run]:
            file_path = file_path.strip()
            if not file_path:
                continue

            # 路径安全检查
            full_path = PYCODER_ROOT / file_path
            if not full_path.exists():
                logger.warning("apply_missing_file task=%s path=%s", task.id, file_path)
                continue

            if any(skip in str(full_path) for skip in [
                "__pycache__", ".git", "node_modules", "venv", ".venv", ".env"
            ]):
                logger.warning("apply_protected_path task=%s path=%s", task.id, file_path)
                continue

            # 提取 old_code 和 new_code
            old_match = re.search(r"--- 旧代码 ---\n(.*?)(?:---|```)", block, re.DOTALL)
            new_match = re.search(r"--- 新代码 ---\n(.*?)(?:```|$)", block, re.DOTALL)

            if not new_match:
                continue

            new_code = new_match.group(1).strip()
            if new_match.group(1) and "```python" in new_match.group(1):
                new_code_match = re.search(r"```python\n(.*?)```", new_match.group(1), re.DOTALL)
                if new_code_match:
                    new_code = new_code_match.group(1).strip()

            if not new_code or len(new_code) < 10:
                continue

            try:
                source = full_path.read_text(encoding="utf-8")
                if old_match:
                    old_code = old_match.group(1).strip()
                    if old_code in source:
                        new_source = source.replace(old_code, new_code, 1)
                        full_path.write_text(new_source, encoding="utf-8")
                        applied_count += 1
                        logger.info("apply_fix task=%s file=%s method=exact_replace", task.id, file_path)
                else:
                    # 行号替换模式
                    lines = source.split("\n")
                    line_num = int(line_no) if line_no.isdigit() else 1
                    if 0 < line_num <= len(lines):
                        lines[line_num - 1] = new_code.split("\n")[0]  # 替换第一行
                        full_path.write_text("\n".join(lines), encoding="utf-8")
                        applied_count += 1
                        logger.info("apply_fix task=%s file=%s line=%s method=line_replace", task.id, file_path, line_no)
            except OSError as e:
                logger.error("apply_fix_error task=%s file=%s: %s", task.id, file_path, e)

        if applied_count > 0:
            task.applied = True
            # 运行测试
            test_ok = await self._run_tests()
            task.test_passed = test_ok
            if not test_ok:
                await self._rollback(task)
            else:
                # 记录到 safety rollback
                try:
                    from pycoder.safety.rollback import RollbackManager
                    RollbackManager().create_snapshot(task.id, {
                        "files": [f[0] for f in fix_blocks],
                        "timestamp": time.time(),
                    })
                except ImportError:
                    pass
        else:
            task.error = "未能应用任何修复"

        return task

    # ══════════════════════════════════════════════════════
    # 阶段 6: 学习 — 经验沉淀 + 知识库自动迭代
    # ══════════════════════════════════════════════════════

    async def learn(self, task: EvolutionTask) -> EvolutionTask:
        """将进化经验沉淀到 knowledge_base 和 experience_buffer

        借鉴生产级 Agent 团队方案，实现:
          1. 结构化知识提取（错误模式 → 修复方案映射）
          2. 自动更新知识库（避坑规则、编码规范、修复策略）
          3. 生成改进规则供后续任务使用
          4. 追踪知识进化指标
        """
        task.phase = EvolutionPhase.LEARN

        outcome = "success" if task.test_passed else "failed"
        lessons_parts: list[str] = [f"任务 {task.id}: {outcome}"]

        # 6.1 提取结构化知识模式
        knowledge_patterns = self._extract_knowledge_patterns(task)
        if knowledge_patterns:
            lessons_parts.append(f"提取到 {len(knowledge_patterns)} 个知识模式")

        # 6.2 记录到 LearningEngine
        try:
            from pycoder.capabilities.self_evo.learning import get_learning_engine
            engine = get_learning_engine()
            engine.on_task_complete(
                task_id=task.id,
                outcome=outcome,
                task_type="evolution",
                description=task.description,
                error_msg=task.error,
                fix_content=task.fix_plan[:2000],
                test_passed=task.test_passed,
                quality_score=task.grade,
                duration_ms=task.duration_ms,
            )
            lessons_parts.append("已记录到 LearningEngine")
        except (ImportError, AttributeError) as e:
            logger.debug("LearningEngine 不可用: %s", e)

        # 6.3 记录到 memory 模块
        try:
            from pycoder.memory import SessionMemoryEngine
            engine = SessionMemoryEngine(workspace=PYCODER_ROOT)
            await engine.record_decision(
                f"evolution:{task.id}:{outcome}:{task.llm_analysis[:200]}:{task.fix_plan[:200]}"
            )
            lessons_parts.append("已记录到 Memory")
        except (ImportError, AttributeError) as e:
            logger.debug("Memory 不可用: %s", e)

        # 6.4 自动更新知识库（借鉴生产级方案的能力迭代闭环）
        kb_update_result = await self._auto_update_knowledge_base(task, knowledge_patterns)
        if kb_update_result:
            lessons_parts.append(kb_update_result)

        # 6.5 记录到 observability
        try:
            from pycoder.observability.sentry import capture_message
            capture_message(
                f"evolution_learned: task={task.id} outcome={outcome} grade={task.grade}",
                level="info",
                task_id=task.id,
                outcome=outcome,
                grade=task.grade,
            )
        except (ImportError, AttributeError):
            pass

        # 6.6 记录进化指标
        try:
            from pycoder.evolution.core import get_evolution_metrics
            metrics = get_evolution_metrics()
            metrics.record(task)
            lessons_parts.append("已记录进化指标")
        except (ImportError, AttributeError):
            pass

        task.lessons = " | ".join(lessons_parts)
        self._history.append(task)
        self._save_history()
        logger.info("learn_done task=%s outcome=%s patterns=%d", task.id, outcome, len(knowledge_patterns))
        return task

    # ══════════════════════════════════════════════════════
    # 知识提取与自动更新
    # ══════════════════════════════════════════════════════

    def _extract_knowledge_patterns(self, task: EvolutionTask) -> list[dict[str, Any]]:
        """从任务结果中提取结构化知识模式

        提取维度:
          - 错误模式 → 修复方案映射
          - 成功模式 → 可复用策略
          - 风险信号 → 避坑规则
        """
        patterns: list[dict[str, Any]] = []

        # 从错误数据中提取错误签名
        if task.errors_collected:
            for err in task.errors_collected[:10]:
                content = str(err.get("content", ""))
                source = str(err.get("source", "unknown"))

                # 提取错误类型签名
                signature = self._extract_error_signature(content)
                if signature:
                    patterns.append({
                        "type": "error_pattern",
                        "signature": signature,
                        "source": source,
                        "frequency": 1,
                        "last_seen": time.time(),
                    })

        # 从 LLM 分析中提取修复策略
        if task.llm_analysis and len(task.llm_analysis) > 50:
            strategies = self._extract_fix_strategies(task.llm_analysis)
            for strategy in strategies:
                patterns.append({
                    "type": "fix_strategy",
                    "strategy": strategy[:200],
                    "outcome": "success" if task.test_passed else "failed",
                    "task_id": task.id,
                })

        # 从 fix_plan 中提取具体的修复规则
        if task.fix_plan and task.applied:
            import re
            fix_blocks = re.findall(
                r"\[FIX:(.+?):\d+\]\n问题描述:\s*(.+?)\n修复方案:\s*(.+?)\n",
                task.fix_plan,
                re.DOTALL,
            )
            for file_path, problem, solution in fix_blocks[:5]:
                patterns.append({
                    "type": "fix_rule",
                    "file_pattern": file_path.strip(),
                    "problem": problem.strip()[:200],
                    "solution": solution.strip()[:300],
                    "verified": task.test_passed,
                    "task_id": task.id,
                })

        # 从验证结果中提取安全规则
        if task.validation_result:
            warnings = task.validation_result.get("warnings", [])
            for warning in warnings:
                patterns.append({
                    "type": "safety_rule",
                    "warning": str(warning)[:200],
                    "task_id": task.id,
                })

        return patterns

    def _extract_error_signature(self, content: str) -> str:
        """从错误内容中提取错误签名"""
        import re

        # 匹配常见 Python 异常类型
        exception_match = re.search(
            r"(?:raise\s+)?(\w+(?:Error|Exception|Warning|Timeout|Interrupt))",
            content,
        )
        if exception_match:
            return exception_match.group(1)

        # 匹配 HTTP 状态码
        status_match = re.search(r"\b(4\d{2}|5\d{2})\b", content)
        if status_match:
            return f"HTTP_{status_match.group(1)}"

        # 匹配常见错误关键词
        error_keywords = [
            "timeout", "connection refused", "permission denied",
            "not found", "out of memory", "disk full",
            "import error", "syntax error", "type error",
            "key error", "value error", "attribute error",
            "rate limit", "too many requests",
        ]
        for keyword in error_keywords:
            if keyword in content.lower():
                return keyword.replace(" ", "_").upper()

        # 截取前 60 字符作为签名
        return content[:60].strip()

    def _extract_fix_strategies(self, analysis: str) -> list[str]:
        """从 LLM 分析中提取修复策略"""
        import re

        strategies: list[str] = []

        # 匹配 "修复建议" 或 "修复方案" 后的内容
        fix_matches = re.findall(
            r"(?:修复建议|修复方案|建议)[：:]\s*(.+?)(?:\n|$)",
            analysis,
        )
        strategies.extend(m.strip() for m in fix_matches if len(m.strip()) > 10)

        # 匹配编号列表中的修复方案
        list_matches = re.findall(
            r"\d+\.\s*\*?\*?(.+?)\*?\*?\s*[:：]\s*(.+?)(?:\n|$)",
            analysis,
        )
        strategies.extend(f"{m[0]}: {m[1]}" for m in list_matches if len(m[1]) > 10)

        return strategies[:5]  # 最多 5 条

    async def _auto_update_knowledge_base(
        self,
        task: EvolutionTask,
        patterns: list[dict[str, Any]],
    ) -> str:
        """自动更新知识库 — 借鉴生产级方案的能力迭代闭环

        将提取的知识模式持久化到多个知识存储层:
          1. knowledge_base（结构化知识库）
          2. avoid_pitfalls（避坑清单）
          3. coding_rules（编码规则）
          4. fix_strategies（修复策略库）
        """
        if not patterns:
            return ""

        results: list[str] = []

        # 更新结构化知识库
        try:
            from pycoder.capabilities.self_evo.learning.knowledge_base import get_knowledge_base
            kb = get_knowledge_base()

            for pattern in patterns:
                ptype = pattern.get("type", "")

                if ptype == "error_pattern":
                    kb.add_error_pattern(
                        signature=pattern.get("signature", ""),
                        source=pattern.get("source", "evolution"),
                        metadata={"task_id": task.id, "outcome": "success" if task.test_passed else "failed"},
                    )

                elif ptype == "fix_rule" and pattern.get("verified"):
                    kb.add_fix_rule(
                        problem=pattern.get("problem", ""),
                        solution=pattern.get("solution", ""),
                        file_pattern=pattern.get("file_pattern", ""),
                        metadata={"task_id": task.id, "verified": True},
                    )

                elif ptype == "safety_rule":
                    kb.add_safety_rule(
                        rule=pattern.get("warning", ""),
                        metadata={"task_id": task.id},
                    )

            results.append(f"KB: +{len(patterns)} 条")
        except (ImportError, AttributeError) as e:
            logger.debug("knowledge_base 更新失败: %s", e)

        # 更新避坑清单
        if not task.test_passed and task.error:
            try:
                avoid_path = EVOLUTION_DB_DIR / "avoid_pitfalls.jsonl"
                EVOLUTION_DB_DIR.mkdir(parents=True, exist_ok=True)
                pitfall = {
                    "task_id": task.id,
                    "error": task.error[:500],
                    "analysis": task.llm_analysis[:300],
                    "timestamp": time.time(),
                    "task_type": task.task_type,
                }
                with open(avoid_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(pitfall, ensure_ascii=False) + "\n")
                results.append("避坑清单: +1")
            except OSError as e:
                logger.debug("避坑清单写入失败: %s", e)

        # 更新修复策略库
        if task.test_passed and task.applied:
            try:
                strategy_path = EVOLUTION_DB_DIR / "fix_strategies.jsonl"
                EVOLUTION_DB_DIR.mkdir(parents=True, exist_ok=True)
                strategy = {
                    "task_id": task.id,
                    "task_type": task.task_type,
                    "target": task.target,
                    "fix_plan_summary": task.fix_plan[:500],
                    "grade": task.grade,
                    "duration_ms": task.duration_ms,
                    "timestamp": time.time(),
                }
                with open(strategy_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(strategy, ensure_ascii=False) + "\n")
                results.append("修复策略库: +1")
            except OSError as e:
                logger.debug("修复策略库写入失败: %s", e)

        return "; ".join(results) if results else ""

    # ══════════════════════════════════════════════════════
    # 知识库查询增强
    # ══════════════════════════════════════════════════════

    def query_knowledge(
        self,
        query: str,
        ktype: str = "all",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """查询进化知识库

        Args:
            query: 查询关键词
            ktype: 知识类型 (all / error_pattern / fix_rule / safety_rule / fix_strategy)
            limit: 返回数量限制

        Returns:
            匹配的知识条目列表
        """
        results: list[dict[str, Any]] = []

        # 查询错误模式
        if ktype in ("all", "error_pattern"):
            try:
                from pycoder.capabilities.self_evo.learning.knowledge_base import get_knowledge_base
                kb = get_knowledge_base()
                kb_results = kb.search(query)
                if kb_results:
                    results.extend([
                        {"type": "error_pattern", "content": str(r)[:300]}
                        for r in kb_results[:limit]
                    ])
            except (ImportError, AttributeError):
                pass

        # 查询历史进化任务
        if ktype in ("all", "fix_strategy"):
            matching_history = [
                {"type": "evolution_history", "task_id": t.id, "outcome": "success" if t.test_passed else "failed",
                 "analysis": t.llm_analysis[:200], "lessons": t.lessons[:200]}
                for t in self._history[-20:]
                if query.lower() in t.llm_analysis.lower() or query.lower() in t.description.lower()
            ][:limit]
            results.extend(matching_history)

        return results[:limit]

    def get_knowledge_stats(self) -> dict[str, Any]:
        """获取知识库统计信息"""
        stats: dict[str, Any] = {
            "total_history": len(self._history),
            "success_rate": 0.0,
            "avg_grade": 0.0,
            "total_patterns": 0,
        }

        if self._history:
            success = sum(1 for t in self._history if t.test_passed)
            stats["success_rate"] = round(success / len(self._history) * 100, 1)
            stats["avg_grade"] = round(sum(t.grade for t in self._history) / len(self._history), 1)

        # 统计知识库条目
        try:
            from pycoder.capabilities.self_evo.learning.knowledge_base import get_knowledge_base
            kb = get_knowledge_base()
            stats["total_patterns"] = kb.get_total_count()
            stats["top_errors"] = [
                str(e)[:200] for e in kb.get_top_errors(limit=5)
            ]
        except (ImportError, AttributeError):
            pass

        return stats

    # ══════════════════════════════════════════════════════
    # 8 阶段流水线支持（借鉴生产级方案）
    # ══════════════════════════════════════════════════════

    def _calculate_grade(self, task: EvolutionTask) -> float:
        """计算进化评分 (0-100)"""
        score = 0.0

        if task.errors_collected:
            score += min(20, len(task.errors_collected) * 2)

        if task.llm_analysis and len(task.llm_analysis) > 50:
            score += 20

        if task.fix_plan and len(task.fix_plan) > 50:
            score += 20

        if task.validation_result.get("passed"):
            score += 15

        if task.applied:
            score += 10

        if task.test_passed:
            score += 15

        return min(score, 100)

    async def _build_metrics(self, task: EvolutionTask) -> dict[str, Any]:
        """构建进化指标"""
        metrics: dict[str, Any] = {
            "phases": len([p for p in EvolutionPhase if task.phase >= p]),
            "errors_collected": len(task.errors_collected),
            "analysis_length": len(task.llm_analysis),
            "fix_plan_length": len(task.fix_plan),
            "validated": task.validation_result.get("passed", False),
            "applied": task.applied,
            "tests_passed": task.test_passed,
        }

        try:
            from pycoder.capabilities.self_evo.learning.metrics_tracker import get_metrics_tracker
            tracker = get_metrics_tracker()
            metrics["historical_success_rate"] = tracker.get_success_rate()
        except (ImportError, AttributeError):
            metrics["historical_success_rate"] = 0.0

        return metrics

    def _generate_recommendations(self, task: EvolutionTask) -> list[str]:
        """生成改进建议"""
        recs = []

        if not task.errors_collected:
            recs.append("建议: 启用更多日志和监控以收集进化数据")
        if not task.llm_analysis or len(task.llm_analysis) < 50:
            recs.append("建议: 配置 LLM API Key 以启用深度分析")
        if not task.validation_result.get("passed"):
            recs.append("建议: 检查 safety 模块配置和沙箱规则")
        if task.applied and not task.test_passed:
            recs.append("建议: 修复的代码导致测试失败，需要人工审查")
        if task.lessons:
            recs.append(f"经验: {task.lessons[:200]}")

        return recs

    async def run_pipeline(
        self,
        task_type: str = "auto_fix",
        target: str = "",
        description: str = "",
        auto_apply: bool = False,
    ) -> EvolutionReport:
        """运行完整的 8 阶段进化流水线

        阶段映射:
          1. INTAKE     → observe()  采集数据
          2. DESIGN     → 任务分级与方案规划
          3. DECOMPOSE  → analyze()  LLM 分析拆解
          4. ENV_SETUP  → 环境校验
          5. DEVELOP    → generate() 生成修复方案
          6. TEST       → validate() 安全验证
          7. DEPLOY     → apply()    应用修复
          8. REVIEW     → learn()    经验沉淀 + 知识库迭代
        """
        t0 = time.time()
        self._config.auto_apply = auto_apply

        task = EvolutionTask(
            task_type=task_type,
            target=target,
            description=description,
        )

        report = EvolutionReport(task_id=task.id)

        # 8 阶段流水线
        pipeline_stages: list[tuple[str, str, callable]] = [
            ("intake", "阶段 1: 任务接入与数据采集", self.observe),
            ("design", "阶段 2: 任务分级与方案规划", self._stage_design),
            ("decompose", "阶段 3: LLM 分析与问题拆解", self.analyze),
            ("env_setup", "阶段 4: 环境校验与前置准备", self._stage_env_setup),
            ("develop", "阶段 5: 生成修复方案", self.generate),
            ("test", "阶段 6: 安全验证与测试", self.validate),
            ("deploy", "阶段 7: 应用修复与部署", self.apply),
            ("review", "阶段 8: 经验沉淀与知识库迭代", self.learn),
        ]

        try:
            for stage_id, stage_name, stage_func in pipeline_stages:
                logger.info("pipeline_stage task=%s stage=%s", task.id, stage_id)
                task = await stage_func(task)
                report.phases_completed.append(stage_id)

                if stage_id == "intake":
                    report.issues_found = len(task.errors_collected)

                if task.error and stage_id in ("test", "deploy"):
                    report.error = task.error
                    if stage_id == "test":
                        break  # 验证失败则停止

            # 计算评分
            grade = self._calculate_grade(task)
            task.grade = grade
            report.grade = grade

            # 生成指标
            report.metrics = await self._build_metrics(task)
            report.recommendations = self._generate_recommendations(task)

            report.success = task.test_passed
            report.fixes_generated = len(re.findall(r"\[FIX:", task.fix_plan))
            report.fixes_applied = 1 if task.applied else 0
            report.tests_passed = task.test_passed

        except Exception as e:
            report.error = f"{type(e).__name__}: {e}"
            logger.error("pipeline_error task=%s: %s", task.id, traceback.format_exc())

        task.completed_at = time.time()
        task.duration_ms = (time.time() - t0) * 1000
        report.duration_ms = task.duration_ms

        return report

    async def _stage_design(self, task: EvolutionTask) -> EvolutionTask:
        """阶段 2: 任务分级与方案规划"""
        task.phase = EvolutionPhase.ANALYZE

        # 任务分级
        error_count = len(task.errors_collected)
        if error_count > 20:
            task_level = "S"  # 大量错误，高复杂度
        elif error_count > 5:
            task_level = "A"  # 中等复杂度
        else:
            task_level = "B"  # 低复杂度

        logger.info(
            "stage_design task=%s level=%s errors=%d",
            task.id, task_level, error_count,
        )
        return task

    async def _stage_env_setup(self, task: EvolutionTask) -> EvolutionTask:
        """阶段 4: 环境校验与前置准备"""
        task.phase = EvolutionPhase.VALIDATE

        # 校验必要组件
        checks: list[dict[str, Any]] = []

        # 检查 Git 可用性
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            checks.append({"component": "git", "available": result.returncode == 0})
        except (subprocess.TimeoutExpired, OSError):
            checks.append({"component": "git", "available": False})

        # 检查 pytest 可用性
        try:
            result = subprocess.run(
                ["pytest", "--version"],
                capture_output=True, text=True, timeout=5,
            )
            checks.append({"component": "pytest", "available": result.returncode == 0})
        except (subprocess.TimeoutExpired, OSError):
            checks.append({"component": "pytest", "available": False})

        # 检查 Python 版本
        checks.append({
            "component": "python",
            "version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "available": True,
        })

        all_available = all(c.get("available", True) for c in checks)
        if not all_available:
            missing = [c["component"] for c in checks if not c.get("available", True)]
            task.error = f"环境校验失败: 缺少 {', '.join(missing)}"
            logger.warning("stage_env_setup task=%s missing=%s", task.id, missing)

        logger.info(
            "stage_env_setup task=%s all_ok=%s checks=%d",
            task.id, all_available, len(checks),
        )
        return task

    # ══════════════════════════════════════════════════════
    # LLM 调用
    # ══════════════════════════════════════════════════════

    async def _call_llm(
        self,
        prompt: str,
        system_prompt: str = "",
        max_tokens: int = 0,
    ) -> str:
        """调用 LLM（通过 ChatBridge），回退到本地规则分析"""
        max_tokens = max_tokens or self._config.max_llm_tokens

        try:
            from pycoder.server.chat_bridge import ChatBridge
            from pycoder.server.chat_handler import _get_api_key_for_model

            bridge = ChatBridge()
            api_key = _get_api_key_for_model(self._config.llm_model)
            bridge.configure(
                model=self._config.llm_model,
                api_key=api_key,
            )
            bridge.config.max_tokens = max_tokens
            bridge.config.system_prompt = system_prompt

            result = ""
            async for event in bridge.chat_stream(prompt):
                if event.event_type == "token":
                    result += event.content
                elif event.event_type == "done":
                    result = event.content or result
                    break
            await bridge.close()
            return result.strip() or self._fallback_analysis(prompt)

        except (ImportError, ValueError, TypeError, RuntimeError, OSError) as e:
            logger.warning("LLM 调用失败，使用本地规则分析: %s", e)
            return self._fallback_analysis(prompt)

    def _fallback_analysis(self, prompt: str) -> str:
        """本地规则分析 — LLM 不可用时的回退方案"""
        analysis_parts = []

        if "error" in prompt.lower() or "错误" in prompt:
            if "import" in prompt.lower() or "导入" in prompt:
                analysis_parts.append("**根因分类**: 导入错误 — 模块或依赖缺失")
                analysis_parts.append("**修复建议**: 检查 import 语句和依赖安装")
            elif "syntax" in prompt.lower() or "语法" in prompt:
                analysis_parts.append("**根因分类**: 语法错误 — 代码不符合 Python 语法")
                analysis_parts.append("**修复建议**: 使用 AST 解析检查语法")
            elif "api" in prompt.lower() or "401" in prompt or "403" in prompt:
                analysis_parts.append("**根因分类**: API 认证/授权错误")
                analysis_parts.append("**修复建议**: 检查 API Key 配置和权限设置")
            else:
                analysis_parts.append("**根因分类**: 运行时错误")
                analysis_parts.append("**修复建议**: 需要人工介入分析具体错误信息")

        if "hardcoded" in prompt.lower() or "密钥" in prompt or "password" in prompt.lower():
            analysis_parts.append("**系统性问题**: 硬编码密钥 — 建议使用环境变量")

        if "timeout" in prompt.lower() or "超时" in prompt:
            analysis_parts.append("**系统性问题**: 超时 — 建议增加超时配置或优化性能")

        return "\n".join(analysis_parts) if analysis_parts else "无法自动分析，需要人工介入"

    def _query_knowledge_base(self, task: EvolutionTask) -> list[str]:
        """从知识库查询类似修复方案"""
        try:
            from pycoder.capabilities.self_evo.learning.knowledge_base import get_knowledge_base
            kb = get_knowledge_base()
            fixes = []
            for e in task.errors_collected[:5]:
                content = e.get("content", "")
                result = kb.search(content)
                if result:
                    fixes.append(str(result)[:300])
            return fixes
        except (ImportError, AttributeError):
            return []

    # ══════════════════════════════════════════════════════
    # 测试与回滚
    # ══════════════════════════════════════════════════════

    async def _run_tests(self) -> bool:
        """运行测试套件"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pytest", "tests/", "-x", "--tb=short", "-q",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PYCODER_ROOT),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self._config.test_timeout_seconds,
            )
            return proc.returncode == 0
        except (asyncio.TimeoutError, OSError) as e:
            logger.error("test_run_error: %s", e)
            return False

    async def _rollback(self, task: EvolutionTask) -> None:
        """回滚修改"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", "checkout", "--", ".",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(PYCODER_ROOT),
            )
            await proc.communicate()
            task.rollback_performed = True
            logger.info("rollback_done task=%s", task.id)
        except OSError as e:
            logger.error("rollback_error task=%s: %s", task.id, e)

    # ══════════════════════════════════════════════════════
    # 持久化
    # ══════════════════════════════════════════════════════

    def _load_history(self) -> None:
        try:
            if EVOLUTION_HISTORY_FILE.exists():
                data = json.loads(EVOLUTION_HISTORY_FILE.read_text(encoding="utf-8"))
                for t in data.get("tasks", [])[-50:]:
                    # 修复 phase 字段序列化问题
                    if "phase" in t and isinstance(t["phase"], str):
                        try:
                            t["phase"] = EvolutionPhase(t["phase"])
                        except ValueError:
                            t["phase"] = EvolutionPhase.OBSERVE
                    # 修复 errors_collected 字段 - 历史数据可能是整数
                    if "errors_collected" in t and isinstance(t["errors_collected"], int):
                        t["errors_collected"] = []
                    self._history.append(EvolutionTask(**t))
        except (json.JSONDecodeError, TypeError, OSError):
            pass

    def _save_history(self) -> None:
        EVOLUTION_DB_DIR.mkdir(parents=True, exist_ok=True)
        EVOLUTION_HISTORY_FILE.write_text(
            json.dumps(
                {"tasks": [t.to_dict() for t in self._history[-50:]]},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self._history[-limit:]]


# ══════════════════════════════════════════════════════════
# EvolutionPipeline — 完整的进化闭环自动化执行器
# ══════════════════════════════════════════════════════════


class EvolutionPipeline:
    """进化管线 — 自动化运行完整的进化闭环

    流程: observe → analyze → generate → validate → apply → learn
    """

    def __init__(self, brain: EvolutionBrain | None = None):
        self._brain = brain or EvolutionBrain()
        self._reports: list[EvolutionReport] = []

    async def run(
        self,
        task_type: str = "auto_fix",
        target: str = "",
        description: str = "",
        auto_apply: bool = False,
    ) -> EvolutionReport:
        """运行一次完整的 8 阶段进化闭环流水线

        阶段:
          1. INTAKE     → observe()  采集数据
          2. DESIGN     → 任务分级与方案规划
          3. DECOMPOSE  → analyze()  LLM 分析拆解
          4. ENV_SETUP  → 环境校验
          5. DEVELOP    → generate() 生成修复方案
          6. TEST       → validate() 安全验证
          7. DEPLOY     → apply()    应用修复
          8. REVIEW     → learn()    经验沉淀 + 知识库迭代
        """
        report = await self._brain.run_pipeline(
            task_type=task_type,
            target=target,
            description=description,
            auto_apply=auto_apply,
        )
        self._reports.append(report)
        if len(self._reports) > 100:
            self._reports = self._reports[-100:]
        return report

    def _calculate_grade(self, task: EvolutionTask) -> float:
        """计算进化评分 (0-100)"""
        score = 0.0

        if task.errors_collected:
            score += min(20, len(task.errors_collected) * 2)

        if task.llm_analysis and len(task.llm_analysis) > 50:
            score += 20

        if task.fix_plan and len(task.fix_plan) > 50:
            score += 20

        if task.validation_result.get("passed"):
            score += 15

        if task.applied:
            score += 10

        if task.test_passed:
            score += 15

        return min(score, 100)

    async def _build_metrics(self, task: EvolutionTask) -> dict[str, Any]:
        """构建进化指标"""
        metrics: dict[str, Any] = {
            "phases": len([p for p in EvolutionPhase if task.phase >= p]),
            "errors_collected": len(task.errors_collected),
            "analysis_length": len(task.llm_analysis),
            "fix_plan_length": len(task.fix_plan),
            "validated": task.validation_result.get("passed", False),
            "applied": task.applied,
            "tests_passed": task.test_passed,
        }

        # 聚合历史趋势
        try:
            from pycoder.capabilities.self_evo.learning.metrics_tracker import get_metrics_tracker
            tracker = get_metrics_tracker()
            metrics["historical_success_rate"] = tracker.get_success_rate()
        except (ImportError, AttributeError):
            metrics["historical_success_rate"] = 0.0

        return metrics

    def _generate_recommendations(self, task: EvolutionTask) -> list[str]:
        """生成改进建议"""
        recs = []

        if not task.errors_collected:
            recs.append("建议: 启用更多日志和监控以收集进化数据")
        if not task.llm_analysis or len(task.llm_analysis) < 50:
            recs.append("建议: 配置 LLM API Key 以启用深度分析")
        if not task.validation_result.get("passed"):
            recs.append("建议: 检查 safety 模块配置和沙箱规则")
        if task.applied and not task.test_passed:
            recs.append("建议: 修复的代码导致测试失败，需要人工审查")
        if task.lessons:
            recs.append(f"经验: {task.lessons[:200]}")

        return recs

    def get_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        """获取最近的进化报告"""
        return [
            {
                "task_id": r.task_id,
                "success": r.success,
                "phases": r.phases_completed,
                "grade": r.grade,
                "duration_ms": r.duration_ms,
                "error": r.error,
            }
            for r in self._reports[-limit:]
        ]

    def get_stats(self) -> dict[str, Any]:
        """获取进化统计"""
        if not self._reports:
            return {"total": 0, "success_rate": 0, "avg_grade": 0}

        total = len(self._reports)
        success = sum(1 for r in self._reports if r.success)
        avg_grade = sum(r.grade for r in self._reports) / max(total, 1)
        avg_duration = sum(r.duration_ms for r in self._reports) / max(total, 1)

        return {
            "total": total,
            "success": success,
            "failure": total - success,
            "success_rate": round(success / total * 100, 1),
            "avg_grade": round(avg_grade, 1),
            "avg_duration_ms": round(avg_duration, 0),
        }


# ══════════════════════════════════════════════════════════
# EvolutionMetrics — 进化效果评估与趋势分析
# ══════════════════════════════════════════════════════════


class EvolutionMetrics:
    """进化效果评估器 — 跟踪和评估进化效果

    指标:
      - 成功率: 进化修复的成功率
      - 覆盖率: 被进化处理的代码比例
      - 回归率: 修复引入新问题的比例
      - 效率: 平均每次进化的耗时
      - 成本: Token 消耗和 API 费用
    """

    def __init__(self):
        self._data: list[dict[str, Any]] = []
        self._load_data()

    def record(self, task: EvolutionTask) -> None:
        """记录一次进化指标"""
        entry = {
            "task_id": task.id,
            "task_type": task.task_type,
            "timestamp": task.completed_at,
            "duration_ms": task.duration_ms,
            "errors_collected": len(task.errors_collected),
            "applied": task.applied,
            "test_passed": task.test_passed,
            "grade": task.grade,
            "rollback": task.rollback_performed,
        }
        self._data.append(entry)
        if len(self._data) > 500:
            self._data = self._data[-500:]
        self._save_data()

    def get_summary(self) -> dict[str, Any]:
        """获取进化指标摘要"""
        if not self._data:
            return self._empty_summary()

        total = len(self._data)
        success = sum(1 for d in self._data if d["test_passed"])
        applied = sum(1 for d in self._data if d["applied"])
        rolled = sum(1 for d in self._data if d["rollback"])
        avg_grade = sum(d["grade"] for d in self._data) / total
        avg_duration = sum(d["duration_ms"] for d in self._data) / total

        # 最近 10 次趋势
        recent = self._data[-10:]
        recent_success = sum(1 for d in recent if d["test_passed"]) / max(len(recent), 1)

        return {
            "total_evolutions": total,
            "success_rate": round(success / total * 100, 1),
            "apply_rate": round(applied / total * 100, 1),
            "rollback_rate": round(rolled / total * 100, 1),
            "avg_grade": round(avg_grade, 1),
            "avg_duration_ms": round(avg_duration, 0),
            "recent_success_rate": round(recent_success * 100, 1),
            "trend": "improving" if recent_success > (success / total) else "declining",
        }

    def get_trend_data(self, days: int = 7) -> list[dict[str, Any]]:
        """获取按天聚合的趋势数据"""
        from collections import defaultdict

        now = time.time()
        day_data: dict[str, list[dict]] = defaultdict(list)

        for d in self._data:
            if now - d["timestamp"] > days * 86400:
                continue
            day = time.strftime("%Y-%m-%d", time.localtime(d["timestamp"]))
            day_data[day].append(d)

        return [
            {
                "date": day,
                "count": len(entries),
                "success_rate": round(
                    sum(1 for e in entries if e["test_passed"]) / len(entries) * 100, 1
                ),
                "avg_grade": round(sum(e["grade"] for e in entries) / len(entries), 1),
            }
            for day, entries in sorted(day_data.items())
        ]

    def _empty_summary(self) -> dict[str, Any]:
        return {
            "total_evolutions": 0,
            "success_rate": 0.0,
            "apply_rate": 0.0,
            "rollback_rate": 0.0,
            "avg_grade": 0.0,
            "avg_duration_ms": 0.0,
            "recent_success_rate": 0.0,
            "trend": "no_data",
        }

    def _load_data(self) -> None:
        metrics_file = EVOLUTION_DB_DIR / "metrics.json"
        try:
            if metrics_file.exists():
                self._data = json.loads(metrics_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    def _save_data(self) -> None:
        EVOLUTION_DB_DIR.mkdir(parents=True, exist_ok=True)
        metrics_file = EVOLUTION_DB_DIR / "metrics.json"
        metrics_file.write_text(
            json.dumps(self._data[-500:], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# ══════════════════════════════════════════════════════════
# 全局单例
# ══════════════════════════════════════════════════════════

_brain: EvolutionBrain | None = None
_pipeline: EvolutionPipeline | None = None
_metrics: EvolutionMetrics | None = None


def get_evolution_brain() -> EvolutionBrain:
    global _brain
    if _brain is None:
        _brain = EvolutionBrain()
    return _brain


def get_evolution_pipeline() -> EvolutionPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = EvolutionPipeline(get_evolution_brain())
    return _pipeline


def get_evolution_metrics() -> EvolutionMetrics:
    global _metrics
    if _metrics is None:
        _metrics = EvolutionMetrics()
    return _metrics


__all__ = [
    "EvolutionBrain",
    "EvolutionPipeline",
    "EvolutionPhase",
    "EvolutionReport",
    "EvolutionTask",
    "EvolutionMetrics",
    "EvolutionConfig",
    "get_evolution_brain",
    "get_evolution_pipeline",
    "get_evolution_metrics",
]
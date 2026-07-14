"""
执行铁律引擎 — 借鉴好运助手执行策略，核验所有 Agent 操作的安全/编码/规范。

包含:
  - 5 步标准工作法（诊断→计划→执行→验证→收尾）
  - 执行铁律（编码/备份/安全）
  - 共享状态系统（任务状态/验证合约/预算/追踪）

用法:
  from pycoder.server.services.execution_rules import ExecutionRules, SharedState

  rules = ExecutionRules()
  rules.validate_code_safety(content)           # 编码 / BOM / 硬编码密钥检测
  rules.create_backup(file_path)                 # 修改前 .bak 备份
  rules.check_port_available(port)               # netstat 端口检测

  state = SharedState(task_id="TASK-001")
  state.update("executing", {"step": "code_gen"})
  state.save()
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pycoder.server.log import log

# ══════════════════════════════════════════════════════════
# 第 1 部分：执行铁律引擎
# ══════════════════════════════════════════════════════════


class ExecutionRules:
    """执行铁律引擎 — 所有 Agent 操作必须通过的基础校验"""

    # 硬编码密钥检测正则
    _SECRET_PATTERNS: list[tuple[str, str]] = [
        (
            r"(?:api[_-]?key|apikey|secret|token|password)" r'\s*[:=]\s*["\']([^"\']{8,})["\']',
            "硬编码API密钥",
        ),
        (r"(?:-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----)", "硬编码私钥"),
        (r'(?:mongodb://|mysql://|postgres://|redis://)[^\s\'"]+', "硬编码数据库连接串"),
        (r"(?:AKIA[0-9A-Z]{16})", "可能硬编码AWS密钥"),
    ]

    # 不安全的 Python 模式
    _UNSAFE_PATTERNS: list[tuple[str, str]] = [
        (r"\bos\.system\(", "os.system() 应使用 subprocess"),
        (r"\beval\(", "eval() 存在代码注入风险"),
        (r"\bexec\(", "exec() 存在代码注入风险"),
        (r"\b__import__\(", "__import__() 动态导入风险"),
        (r"pickle\.loads?\(", "pickle 反序列化风险"),
    ]

    def __init__(self, workspace: str | Path | None = None):
        self._workspace = Path(workspace or os.getcwd()).resolve()
        self._backup_dir = self._workspace / ".pycoder_backups"
        self.violations: list[dict] = []

    # ─── 文件编码铁律 ───
    @staticmethod
    def check_bom(file_path: str | Path) -> bool:
        """检查文件是否为 UTF-8 无 BOM，返回 True 表示通过"""
        p = Path(file_path)
        if not p.exists():
            return True
        with open(p, "rb") as f:
            head = f.read(3)
        return head[:3] != b"\xef\xbb\xbf"

    @staticmethod
    def strip_bom(file_path: str | Path) -> bool:
        """移除 BOM 头，返回 True 表示执行了清理"""
        p = Path(file_path)
        if not p.exists():
            return False
        with open(p, "rb") as f:
            data = f.read()
        if data[:3] == b"\xef\xbb\xbf":
            content = data[3:].decode("utf-8")
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(content)
            return True
        return False

    # ─── 备份铁律 ───
    def create_backup(self, file_path: str | Path) -> Path | None:
        """修改关键文件前创建 .bak 备份"""
        p = Path(file_path)
        if not p.is_absolute():
            p = self._workspace / p
        if not p.exists():
            return None
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        bak = self._backup_dir / f"{p.name}.{ts}.bak"
        shutil.copy2(p, bak)
        return bak

    def restore_backup(self, original: str | Path) -> Path | None:
        """恢复最近一次备份"""
        p = Path(original)
        if not p.is_absolute():
            p = self._workspace / p
        pattern = f"{p.name}.*.bak"
        backups = sorted(
            self._backup_dir.glob(pattern),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )
        if backups:
            shutil.copy2(backups[0], p)
            return backups[0]
        return None

    # ─── 安全铁律 ───
    def validate_code_safety(self, code: str, file_path: str = "") -> list[dict]:
        """扫描代码安全问题，返回违规列表"""
        issues: list[dict] = []
        for i, line in enumerate(code.splitlines(), 1):
            for pattern, desc in self._SECRET_PATTERNS:
                m = re.search(pattern, line, re.IGNORECASE)
                if m:
                    # 跳过注释行
                    stripped = line.strip()
                    if stripped.startswith("#") or stripped.startswith("//"):
                        continue
                    issues.append(
                        {
                            "line": i,
                            "severity": "high",
                            "category": "security",
                            "description": desc,
                            "suggestion": f"请使用环境变量或配置文件管理 {desc.split('硬编码')[-1].strip('密钥')}",
                            "file": file_path,
                        }
                    )
            for pattern, desc in self._UNSAFE_PATTERNS:
                if re.search(pattern, line):
                    stripped = line.strip()
                    if stripped.startswith("#") or stripped.startswith("//"):
                        continue
                    issues.append(
                        {
                            "line": i,
                            "severity": "medium",
                            "category": "security",
                            "description": desc,
                            "suggestion": f"替换 {desc.split()[0]} 调用",
                            "file": file_path,
                        }
                    )
        self.violations.extend(issues)
        return issues

    # ─── 进程/端口铁律 ───
    @staticmethod
    def check_port_available(port: int) -> tuple[bool, list[str]]:
        """检查端口是否空闲 (Windows netstat)"""
        try:
            if os.name == "nt":
                r = subprocess.run(
                    ["netstat", "-ano"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    encoding="utf-8",
                    errors="replace",
                )
                occupied: list[str] = []
                for line in r.stdout.splitlines():
                    if f":{port}" in line and "LISTENING" in line:
                        occupied.append(line.strip())
                return len(occupied) == 0, occupied
            else:
                r = subprocess.run(
                    ["lsof", "-i", f":{port}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    encoding="utf-8",
                    errors="replace",
                )
                occupied = [line for line in r.stdout.splitlines() if "LISTEN" in line]
                return len(occupied) == 0, occupied
        except (subprocess.SubprocessError, OSError) as e:
            log.debug("check_port_available_failed", port=port, error=str(e))
            return True, []  # 检查失败时放行

    # ─── JSON 验证铁律 ───
    @staticmethod
    def validate_json(file_path: str | Path) -> tuple[bool, str]:
        """验证 JSON 文件完整性"""
        p = Path(file_path)
        if not p.exists():
            return False, f"文件不存在: {file_path}"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return (
                True,
                f"有效 JSON，顶层键: {list(data.keys()) if isinstance(data, dict) else 'array'}",
            )
        except json.JSONDecodeError as e:
            return False, f"JSON 解析失败: {e}"
        except Exception as e:
            return False, f"读取失败: {e}"

    # ─── 执行报告 ───
    def get_violations_report(self) -> str:
        """生成违规报告"""
        if not self.violations:
            return "✅ 无违规"
        lines = ["## 🔒 执行铁律违规报告"]
        for v in self.violations:
            lines.append(
                f"- [{v['severity'].upper()}] {v['file']}:{v['line']} - "
                f"{v['description']} → {v['suggestion']}"
            )
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# 第 2 部分：共享状态系统
# ══════════════════════════════════════════════════════════

SHARED_STATE_DIR = Path(
    os.environ.get(
        "PYCODER_SHARED_STATE",
        str(Path.home() / ".pycoder" / "shared"),
    )
)


@dataclass
class TaskState:
    """任务状态（对标好运助手 shared/{taskId}.json）"""

    task_id: str
    # pending | analyzing | planning | executing | verifying | done | failed
    status: str = "pending"
    title: str = ""
    steps: list[dict] = field(default_factory=list)
    progress: int = 0  # 0-100
    completed_items: list[str] = field(default_factory=list)
    pending_items: list[str] = field(default_factory=list)
    context: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float = 0.0


@dataclass
class ValidationContract:
    """验证合约（对标好运助手 shared/contracts/{taskId}.json）"""

    task_id: str
    criteria: list[dict] = field(default_factory=list)  # [{name, check, weight}]
    status: str = "pending"  # pending | passed | failed
    score: float = 0.0
    created_by: str = "hermes"
    created_at: float = field(default_factory=time.time)


@dataclass
class BudgetTracker:
    """预算追踪（对标好运助手 shared/budgets/{workflowId}.json）"""

    workflow_id: str
    token_limit: int = 100000
    tokens_used: int = 0
    cost_limit_usd: float = 5.0
    cost_used: float = 0.0
    status: str = "active"  # active | warning | exceeded


class SharedState:
    """共享状态管理器"""

    def __init__(self, task_id: str | None = None):
        self.task_id = task_id or f"TASK-{uuid.uuid4().hex[:8]}"
        SHARED_STATE_DIR.mkdir(parents=True, exist_ok=True)
        (SHARED_STATE_DIR / "contracts").mkdir(exist_ok=True)
        (SHARED_STATE_DIR / "budgets").mkdir(exist_ok=True)
        (SHARED_STATE_DIR / "traces").mkdir(exist_ok=True)
        (SHARED_STATE_DIR / "workflow_checkpoints").mkdir(exist_ok=True)

    # ─── 任务状态 ───
    def _task_path(self) -> Path:
        return SHARED_STATE_DIR / f"{self.task_id}.json"

    def get_task(self) -> TaskState:
        """读取任务状态"""
        p = self._task_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return TaskState(**data)
        return TaskState(task_id=self.task_id)

    def save_task(self, state: TaskState) -> None:
        """保存任务状态"""
        state.updated_at = time.time()
        data = {
            "task_id": state.task_id,
            "status": state.status,
            "title": state.title,
            "steps": state.steps,
            "progress": state.progress,
            "completed_items": state.completed_items,
            "pending_items": state.pending_items,
            "context": state.context,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "completed_at": state.completed_at,
        }
        self._task_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def update_task(self, status: str = "", **kwargs) -> TaskState:
        """更新任务状态"""
        state = self.get_task()
        if status:
            state.status = status
        for k, v in kwargs.items():
            if hasattr(state, k):
                setattr(state, k, v)
        state.updated_at = time.time()
        if state.status == "done":
            state.completed_at = time.time()
            state.progress = 100
        self.save_task(state)
        return state

    def add_step(self, step_name: str, step_status: str = "pending") -> None:
        """添加执行步骤"""
        state = self.get_task()
        state.steps.append(
            {
                "name": step_name,
                "status": step_status,
                "timestamp": time.time(),
            }
        )
        self.save_task(state)

    # ─── 验证合约 ───
    def create_contract(self, criteria: list[dict]) -> ValidationContract:
        """创建验证合约"""
        contract = ValidationContract(task_id=self.task_id, criteria=criteria)
        p = SHARED_STATE_DIR / "contracts" / f"{self.task_id}.json"
        p.write_text(
            json.dumps(
                {
                    "task_id": contract.task_id,
                    "criteria": contract.criteria,
                    "status": contract.status,
                    "score": contract.score,
                    "created_by": contract.created_by,
                    "created_at": contract.created_at,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return contract

    def get_contract(self) -> ValidationContract | None:
        """获取验证合约"""
        p = SHARED_STATE_DIR / "contracts" / f"{self.task_id}.json"
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        return ValidationContract(**data)

    # ─── 预算追踪 ───
    def track_budget(self, workflow_id: str, tokens: int, cost: float) -> BudgetTracker:
        """记录并检查预算"""
        p = SHARED_STATE_DIR / "budgets" / f"{workflow_id}.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            tracker = BudgetTracker(**data)
        else:
            tracker = BudgetTracker(workflow_id=workflow_id)
        tracker.tokens_used += tokens
        tracker.cost_used += cost
        if tracker.cost_used >= tracker.cost_limit_usd:
            tracker.status = "exceeded"
        elif tracker.cost_used >= tracker.cost_limit_usd * 0.8:
            tracker.status = "warning"
        p.parent.mkdir(exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "workflow_id": tracker.workflow_id,
                    "token_limit": tracker.token_limit,
                    "tokens_used": tracker.tokens_used,
                    "cost_limit_usd": tracker.cost_limit_usd,
                    "cost_used": tracker.cost_used,
                    "status": tracker.status,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return tracker

    # ─── 工作流检查点 ───
    def save_checkpoint(self, stage: str, data: dict) -> Path:
        """保存工作流检查点"""
        dp = SHARED_STATE_DIR / "workflow_checkpoints"
        dp.mkdir(exist_ok=True)
        p = dp / f"{self.task_id}_{stage}.json"
        p.write_text(
            json.dumps(
                {"stage": stage, "data": data, "timestamp": time.time()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return p

    def load_checkpoint(self, stage: str) -> dict | None:
        """加载工作流检查点"""
        p = SHARED_STATE_DIR / "workflow_checkpoints" / f"{self.task_id}_{stage}.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    # ─── 追踪日志 ───
    def trace(self, event: str, data: dict) -> None:
        """写入追踪日志"""
        p = SHARED_STATE_DIR / "traces" / f"{self.task_id}.ndjson"
        p.parent.mkdir(exist_ok=True)
        entry = {
            "task_id": self.task_id,
            "event": event,
            "timestamp": time.time(),
            "data": data,
        }
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ══════════════════════════════════════════════════════════
# 第 3 部分：5 步标准工作法
# ══════════════════════════════════════════════════════════

FIVE_STEP_WORKFLOW = {
    "1_diagnose": {
        "name": "诊断阶段",
        "description": "不急于修改，先确认根因",
        "checks": [
            "复现问题（直接调用 API / 执行函数）",
            "检查代码路径（分支是否覆盖完整）",
            "检查运行环境（进程/端口/缓存/字节码）",
            "确认根因后开始修复",
        ],
    },
    "2_plan": {
        "name": "计划阶段",
        "description": "明确优先级",
        "checks": [
            "P0: 功能不可用 / 配置损坏 → 立即修复",
            "P1: 功能不完整 / 质量缺陷 → 本周修复",
            "P2: 优化 / 增强 → 规划后修复",
        ],
    },
    "3_execute": {
        "name": "执行阶段",
        "description": "一次改到底",
        "checks": [
            "修改代码",
            "验证语法（python -c compile, JSON.parse）",
            "清除缓存（__pycache__）",
            "kill 旧进程（netstat 确认端口空闲）",
            "重新启动服务",
            "测试功能",
        ],
    },
    "4_verify": {
        "name": "验证阶段",
        "description": "多维度确认",
        "checks": [
            "API 测试（curl / Invoke-RestMethod）",
            "进程检查（Get-Process / ps）",
            "端口检查（netstat -ano）",
            "配置确认（Gateway config.get）",
        ],
    },
    "5_finalize": {
        "name": "收尾阶段",
        "description": "闭环",
        "checks": [
            "提交（git add <文件> 明确指定，不用 -A）",
            "清理临时文件",
            "输出执行报告",
        ],
    },
}

# 5 种典型失败模式
FAILURE_MODES: list[dict] = [
    {
        "id": 1,
        "scenario": "AI对话返回null",
        "root_cause": "非核心路径缺少return语句",
        "prevention": "检查所有代码路径",
    },
    {
        "id": 2,
        "scenario": "修改后仍返回null",
        "root_cause": "旧进程堆积，加载旧字节码",
        "prevention": "kill旧进程 + 清__pycache__",
    },
    {
        "id": 3,
        "scenario": "配置文件Agent列表为0",
        "root_cause": "JSON文件被截断损坏",
        "prevention": "改后验证JSON语法",
    },
    {
        "id": 4,
        "scenario": "Agent提示词薄弱",
        "root_cause": "提示词文件太短，缺乏核心流程",
        "prevention": "核心Agent≥400行提示词",
    },
    {
        "id": 5,
        "scenario": "git add误添加",
        "root_cause": "-A误加node_modules等大目录",
        "prevention": "精确指定文件路径，不用-A",
    },
]


__all__ = [
    "ExecutionRules",
    "SharedState",
    "TaskState",
    "ValidationContract",
    "BudgetTracker",
    "FIVE_STEP_WORKFLOW",
    "FAILURE_MODES",
    "SHARED_STATE_DIR",
]

# PyCoder 功能优化升级方案

> 生成时间: 2026-07-29 | 基于 8 项功能补足/升级需求

## 一、现状分析摘要

| # | 升级点 | 现有模块 | 差距 |
|---|--------|----------|------|
| 1 | 自动化测试执行 | `capabilities/tools/testing.py` (仅生成测试代码) | 缺少 `run_tests` 执行+结果捕获 |
| 2 | 项目结构感知 | `io/file_indexer.py` (单文件索引) | 缺少项目级虚拟索引+增量缓存 |
| 3 | 长对话回顾 | `ai/dialog/state_tracker.py` (意图追踪) | 缺少关键决策点快照+上下文摘要 |
| 4 | 智能命令执行 | `capabilities/tools/shell.py` (单命令) | 缺少命令序列/任务管道 |
| 5 | 错误智能分类 | `self_evo/learning/error_classifier.py` (基础分类) | 缺少错误模式库+根因推断链 |
| 6 | 跨平台环境感知 | `core/shell_translator.py` (30+命令映射) | 未集成到所有命令生成路径 |
| 7 | 性能瓶颈提示 | `python/code_quality.py` (质量分析) | 缺少生成代码后自动告警 |
| 8 | 安全审查深度 | `ai/security/composite_scanner.py` (扫描器) | 缺少代码生成时自动插入 sanitize_check |

## 二、实施方案 (分 3 期)

### 第一期: 高价值、低风险 (P0)

#### 1.1 run_tests 工具 — 自动化测试执行闭环

**目标**: 新增 `tools.testing.run_tests` 工具，自动扫描并执行测试，返回结构化结果

**实现方案**:

```
pycoder/capabilities/tools/testing.py  (修改)
  └── 新增 register: "tools.testing.run_tests"
      ├── 参数: test_path (可选, 默认 tests/), pattern (默认 test_*.py), verbose, timeout
      └── handler: _handle_run_tests
          ├── 调用 asyncio.create_subprocess_exec 执行 pytest
          ├── 解析 pytest 输出 (JSON 报告格式)
          └── 返回 RunTestResult {passed, failed, errors, warnings, duration, failure_details[]}

pycoder/capabilities/tools/test_runner.py  (新建)
  └── class TestRunner
      ├── async run(test_path, pattern, timeout) -> TestRunResult
      ├── _parse_pytest_output(output) -> TestRunResult
      ├── _parse_junit_xml(xml_path) -> TestRunResult  (备用解析)
      └── _extract_failure_details(traceback) -> FailureDetail[]
```

**数据结构**:
```python
@dataclass
class TestRunResult:
    success: bool
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration: float
    failure_details: list[FailureDetail]

@dataclass
class FailureDetail:
    test_name: str
    file_path: str
    line_number: int
    error_type: str
    error_message: str
    traceback: str
```

**安全控制**: 
- 超时限制 (默认 120s, 上限 600s)
- 沙箱内执行 (复用现有 sandbox_selector)
- 禁止执行非测试文件 (验证文件名匹配 pattern)

---

#### 1.2 项目虚拟文件索引 — 增量缓存

**目标**: 维护项目级文件索引，支持快速定位和增量更新

**实现方案**:

```
pycoder/io/project_index.py  (新建)
  └── class ProjectIndex
      ├── _index: dict[str, FileSummary]  (path → 摘要)
      ├── _symbol_index: dict[str, list[str]]  (符号名 → [文件路径])
      ├── _config_index: dict[str, Any]  (配置文件缓存)
      ├── scan_project(root_dir) -> int  (扫描整个项目)
      ├── update_file(path) -> None  (增量更新单个文件)
      ├── remove_file(path) -> None
      ├── find_symbol(name) -> list[str]  (按符号名查找文件)
      ├── find_file(pattern) -> list[str]  (按文件名模式查找)
      ├── get_summary(path) -> FileSummary | None
      ├── export_summary() -> dict  (导出索引摘要供 AI 上下文使用)
      └── persist(cache_path) / load(cache_path)  (SQLite 持久化)

pycoder/io/file_indexer.py  (修改)
  └── FileIndexer 复用现有 index_file() 逻辑
```

**数据结构**:
```python
@dataclass
class FileSummary:
    path: str
    module: str  # 模块名 (如 pycoder.server.app)
    size: int
    content_hash: str
    symbols: list[SymbolDef]  # 复用现有 SymbolDef
    imports: list[str]  # 导入的模块
    config_items: dict[str, Any]  # 配置项 (如果是配置文件)
    last_indexed: float
```

**缓存策略**:
- 内存缓存 + SQLite 持久化 (`.pycoder/project_index.db`)
- 文件内容哈希比对，未变则跳过
- 对话启动时增量加载 (仅扫描有变更的文件)

---

#### 1.3 跨平台命令适配全链路集成

**目标**: 将现有 `ShellTranslator` 集成到所有命令生成和执行路径

**实现方案**:

```
pycoder/brain/chat_handler.py  (修改)
  └── 在 _execute_tool_call 之前自动调用 translate_to_current_platform()

pycoder/capabilities/tools/shell.py  (修改)
  └── 在 handler 执行前自动翻译命令

pycoder/brain/context_builder.py  (修改)
  └── 注入 os_type 环境变量到系统提示词
```

**集成点**:
1. AI 生成命令 → 执行前自动翻译 (shell.py handler)
2. 系统提示词注入 `os_type=Windows` (context_builder.py)
3. 文件路径自动适配 (`/` → `\` on Windows)

**风险**: 低 — ShellTranslator 已完善，只需调用

---

### 第二期: 中等价值、中等风险 (P1)

#### 2.1 关键决策点快照 — 长对话回顾

**目标**: 每次重大修改后自动记录变更摘要，支持上下文回顾

**实现方案**:

```
pycoder/ai/dialog/decision_snapshot.py  (新建)
  └── class DecisionSnapshotManager
      ├── _snapshots: list[DecisionSnapshot]
      ├── record(file, change_type, description, reason) -> DecisionSnapshot
      ├── get_recent(n=5) -> list[DecisionSnapshot]
      ├── get_context_summary() -> str  (生成上下文摘要文本)
      ├── get_affected_files() -> set[str]
      └── persist(session_id) / load(session_id)

pycoder/ai/dialog/state_tracker.py  (修改)
  └── DialogState 新增 decision_snapshots 字段

pycoder/brain/chat_handler.py  (修改)
  └── 每次文件修改后调用 snapshot_manager.record()
  └── 回复末尾附带 get_context_summary() (如果检测到长对话)
```

**数据结构**:
```python
@dataclass
class DecisionSnapshot:
    timestamp: float
    file_path: str
    change_type: str  # "create" | "modify" | "delete" | "refactor"
    description: str  # 简短描述 (如 "修复了 run_tests 超时问题")
    reason: str  # 修改原因
    diff_stats: dict  # {added: 10, removed: 5, modified: 3}
```

**触发条件**:
- 文件写入/创建/删除操作后自动记录
- 每隔 10 轮对话生成一次上下文摘要
- 用户请求 "回顾" 时输出完整决策历史

---

#### 2.2 命令序列/任务管道 — 多步骤执行

**目标**: 支持按顺序执行多个命令，处理失败重试

**实现方案**:

```
pycoder/capabilities/tools/task_pipeline.py  (新建)
  └── class TaskPipeline
      ├── async execute(steps: list[PipelineStep]) -> PipelineResult
      ├── _execute_step(step) -> StepResult
      ├── _handle_failure(step, error) -> bool  (返回是否重试)
      └── _rollback(executed_steps) -> None  (失败回滚)

pycoder/capabilities/tools/shell.py  (修改)
  └── 新增 register: "tools.shell.run_pipeline"
```

**数据结构**:
```python
@dataclass
class PipelineStep:
    command: str
    description: str = ""
    timeout: int = 60
    retries: int = 0
    retry_delay: float = 1.0
    continue_on_failure: bool = False
    working_dir: str = ""

@dataclass
class PipelineResult:
    success: bool
    executed: int
    failed: int
    results: list[StepResult]
    total_duration: float

@dataclass
class StepResult:
    step_index: int
    command: str
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    attempts: int
```

**安全控制**:
- 每个步骤独立超时
- 命令白名单校验 (复用 shell_translator)
- 最大步骤数限制 (默认 20)
- 禁止 `rm -rf /` 等危险操作

---

#### 2.3 错误模式库增强 — 智能根因推断

**目标**: 扩展现有 ErrorClassifier，增加错误模式库和根因推断链

**实现方案**:

```
pycoder/capabilities/self_evo/learning/error_classifier.py  (修改)
  └── 新增 _ERROR_PATTERN_DB: dict[str, ErrorPattern]
  └── 新增 infer_root_cause(error_msg, context) -> RootCauseAnalysis
  └── 新增 get_fix_template(error_type) -> str | None

pycoder/capabilities/self_evo/learning/error_patterns.py  (新建)
  └── ERROR_PATTERN_DB: 50+ 常见 Python 错误模式
  └── ROOT_CAUSE_CHAINS: 错误关联链 (如 DLL load failed → 缺少 VC++ 运行库)
```

**数据结构**:
```python
@dataclass
class ErrorPattern:
    error_type: str  # 如 "ModuleNotFoundError"
    signature: str  # 正则匹配模式
    category: ErrorCategory
    root_causes: list[str]  # 可能的根因
    fix_templates: list[str]  # 修复模板
    related_errors: list[str]  # 关联错误
    platform_specific: bool  # 是否平台相关
    examples: list[str]  # 错误示例

@dataclass
class RootCauseAnalysis:
    primary_cause: str
    confidence: float
    secondary_causes: list[str]
    recommended_fixes: list[str]
    error_chain: list[str]  # 错误推断链
```

**错误模式库覆盖**:
- ImportError / ModuleNotFoundError → 缺少依赖/虚拟环境问题
- DLL load failed → 缺少 Visual C++ 运行库
- PermissionError → 文件权限/占用问题
- FileNotFoundError → 路径问题/工作目录
- TypeError → 类型不匹配/None 值
- RecursionError → 无限递归/终止条件缺失
- TimeoutError → 网络超时/死锁
- OSError → 系统资源/端口占用

---

### 第三期: 锦上添花 (P2)

#### 3.1 性能瓶颈提示 — 代码生成后告警

**目标**: 在生成代码后自动检测性能问题并提示

**实现方案**:

```
pycoder/ai/analysis/perf_advisor.py  (新建)
  └── class PerformanceAdvisor
      ├── analyze_code(code, language="python") -> list[PerfWarning]
      ├── _check_patterns(code) -> list[PerfWarning]  (AST 模式匹配)
      └── _RULES: list[PerfRule]  (性能规则库)

pycoder/brain/chat_handler.py  (修改)
  └── 代码生成后调用 perf_advisor.analyze_code()
  └── 检测到问题时在回复末尾添加 "性能注意" 告警框
```

**检测规则**:
- 循环内重复 I/O (文件读取/网络请求)
- 循环内重复对象创建 (如 `pygame.mixer.Sound`)
- `time.delay()` / `time.sleep()` 在主循环中
- 未使用列表推导式 (可优化场景)
- 字符串拼接 (应使用 join)
- 全局变量频繁访问
- 未使用缓存的高频计算

**数据结构**:
```python
@dataclass
class PerfWarning:
    line: int
    pattern: str  # 检测到的模式
    severity: str  # "high" | "medium" | "low"
    suggestion: str  # 优化建议
    code_snippet: str  # 问题代码片段

@dataclass
class PerfRule:
    name: str
    pattern: str  # AST 匹配模式
    severity: str
    suggestion: str
    example_fix: str  # 修复示例
```

---

#### 3.2 安全审查自动插入 — sanitize_check

**目标**: 生成涉及文件路径、网络请求、命令字符串拼接的代码时自动插入安全检查

**实现方案**:

```
pycoder/ai/security/code_sanitizer.py  (新建)
  └── class CodeSanitizer
      ├── sanitize_code(code, context) -> SanitizeResult
      ├── _check_path_traversal(code) -> list[SecurityWarning]
      ├── _check_sql_injection(code) -> list[SecurityWarning]
      ├── _check_command_injection(code) -> list[SecurityWarning]
      ├── _check_ssrf(code) -> list[SecurityWarning]
      └── _insert_sanitizers(code, warnings) -> str  (自动插入安全检查代码)

pycoder/brain/chat_handler.py  (修改)
  └── 代码生成后调用 code_sanitizer.sanitize_code()
  └── 检测到风险时在回复中添加 "安全提示" 并提供修复版代码
```

**检测项**:
- 路径遍历: `open(user_input)` → 插入 `Path(user_input).resolve().is_relative_to(base_dir)` 检查
- SQL 注入: `cursor.execute(f"SELECT ... {user_input}")` → 改为参数化查询
- 命令注入: `subprocess.run(f"cmd {user_input}")` → 改为列表参数
- SSRF: `requests.get(user_url)` → 插入 URL 白名单检查
- XSS: `html.render(user_input)` → 插入转义

**数据结构**:
```python
@dataclass
class SecurityWarning:
    line: int
    vulnerability_type: str  # "path_traversal" | "sql_injection" | ...
    severity: str  # "critical" | "high" | "medium"
    description: str
    original_code: str
    fixed_code: str  # 修复后的代码
    cwe_id: str  # CWE 编号 (如 CWE-22)

@dataclass
class SanitizeResult:
    is_safe: bool
    warnings: list[SecurityWarning]
    sanitized_code: str  # 包含安全检查的代码
```

---

## 三、实施优先级与排期

| 期次 | 升级点 | 优先级 | 预计工作量 | 依赖关系 |
|------|--------|--------|------------|----------|
| **第一期** | 1.1 run_tests 工具 | P0 | 中 | 无 |
| **第一期** | 1.2 项目虚拟文件索引 | P0 | 中 | 无 |
| **第一期** | 1.3 跨平台命令适配全链路 | P0 | 低 | 无 |
| **第二期** | 2.1 关键决策点快照 | P1 | 中 | 无 |
| **第二期** | 2.2 命令序列/任务管道 | P1 | 中 | 1.3 |
| **第二期** | 2.3 错误模式库增强 | P1 | 中 | 无 |
| **第三期** | 3.1 性能瓶颈提示 | P2 | 低 | 无 |
| **第三期** | 3.2 安全审查自动插入 | P2 | 中 | 无 |

## 四、测试策略

每项升级需配套测试:

1. **单元测试**: `tests/test_<module_name>.py`
2. **集成测试**: 验证与现有系统的交互
3. **回归测试**: 确保不影响现有功能

测试覆盖率目标: >= 80% (与项目规范一致)

## 五、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| run_tests 执行恶意代码 | 安全风险 | 复用沙箱执行，超时限制 |
| 项目索引内存占用 | 性能 | 增量缓存 + SQLite 持久化 |
| 命令管道误操作 | 数据丢失 | 回滚机制 + 确认提示 |
| 性能告警误报 | 用户体验 | 仅显示 high/critical 级别 |
| 安全审查过度拦截 | 开发效率 | 仅提示不阻断 |

## 六、验收标准

1. `run_tests` 工具可执行 pytest 并返回结构化结果
2. 项目索引可在 <1s 内定位任意文件/符号
3. AI 生成的命令自动适配当前平台 (0 个 Linux 专有命令泄漏)
4. 长对话 (>20 轮) 可回顾所有关键决策点
5. 命令管道可执行 5+ 步骤序列，失败时自动重试
6. 错误分类准确率 > 80% (基于 50+ 错误模式库)
7. 性能告警误报率 < 10%
8. 安全审查覆盖 OWASP Top 10 核心漏洞类型

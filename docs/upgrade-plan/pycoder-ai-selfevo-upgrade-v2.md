# PyCoder AI 深度优化升级方案 — 真实做项目 + 自我进化

> 版本: v2.0 | 日期: 2026-07-23 | 基于: 100+ 条执行日志深度分析  
> 目标: 从"工具调用机"升级为"自主项目经理 + 自我进化引擎"

---

## 一、从日志中诊断出的 6 个核心断裂点

通过逆向分析 100+ 条 AI 执行日志（`task_grader level=LIGHT score=18 max_iter=7`）
和逐行审计 `chat_bridge.py`/`chat_handler.py`/`task_grader.py`/`agent_loop.py`，
发现当前 AI 管线的 6 个关键断裂点：

```
┌──── 断裂点 ────────────────────────────────────────────┐
│                                                         │
│  1. 任务分级永远 LIGHT — context={"mode":"tool"} 只有                   
│     一个空 mode 字段，task_grader 无法计算真实难度         │
│                                                         │
│  2. 无项目级上下文 — AI 每次对话从零开始，不知道              │
│     创建了什么文件、做了什么修改                            │
│                                                         │
│  3. 自我进化是空壳 — self_evo_code_scan 仅检测               
│     __import__ 违规，无真正的代码优化能力                   │
│                                                         │
│  4. Agent 团队闲置 — UnifiedAgentLoop 已实现但
│     chat_handler 从不路由到它                             │
│                                                         │
│  5. 无验证-修复闭环 — AI 写代码→下一轮，从不               │
│     编写→测试→失败→修复→再测试                            │
│                                                         │
│  6. 记忆不联动 — live_learner 记录观察但系统              
│     提示词不反馈历史成功模式                               │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 二、逐断裂点修复方案

### 2.1 🔴 断裂点 1: 任务分级永远 LIGHT → 动态上下文注入

**现状**:

```python
# chat_bridge.py L476
grader.assess(message, context={"mode": effective_mode})  # ← 空壳！
# task_grader 拿到空 context，files=0, deps=0, lines=0 → score=18
# → LIGHT → max_iter=7 → 复杂项目根本没机会完成
```

**修复**:

```python
# 注入项目真实数据作为计算上下文
_context = {
    "mode": effective_mode,
    "files": len(tool_args_get_all_files_in_workspace()),
    "dependencies": len(parse_requirements_txt()),
    "domain": _nlu_result.task_category,
    "lines": estimate_codebase_lines(),
}
grader.assess(message, context=_context)
# → score 40-60 → MEDIUM → max_iter=25 → 足够完成真实项目
```

**改动**: `chat_bridge.py` 第 476 行，+15 行  
**预期效果**: 复杂任务从 7 轮 → 25 轮，有足够轮次完成项目

---

### 2.2 🔴 断裂点 2: 无项目级上下文 → ProjectState 追踪器

**现状**: AI 创建了文件但下一轮不知道刚才做了什么

**方案**: 新建 `pycoder/server/services/project_state.py`

```
ProjectState
├─ created_files: list[str]        # 本轮创建的文件列表
├─ modified_files: list[str]       # 本轮修改的文件
├─ todo_items: list[str]           # 剩余待办
├─ current_phase: str              # 设计/编码/测试/交付
├─ phase_progress: float(0-100)    # 当前阶段进度
├─ inject_to_prompt() → str        # 生成上下文注入块
└─ save_checkpoint() → dict        # 断点续做
```

**注入到 System Prompt**:

```
📊 项目进度
├─ 阶段: 编码 (60%)
├─ 已创建: app/main.py, app/models.py, tests/test_api.py
├─ 待完成: [x] 数据库模型 [ ] API路由 [ ] 单元测试
└─ 当前步骤: 实现 /api/users 端点
```

**改动**: `chat_handler.py` 第 406 行，+5 行（注入到 system_prompt 前）

---

### 2.3 🟡 断裂点 3: 自我进化空壳 → True Self-Evo 引擎

**现状**: `self_evo_code_scan` 只查 `__import__` 用法，无真正价值

**方案**: 重写 `pycoder/capabilities/self_evo/` 为真实进化管线：

```
SelfEvo.run_cycle()
  ├─ 1. SCAN: 扫描代码库 → 按 PYLINT/BANDIT/mypy 规则
  ├─ 2. PRIORITIZE: 排序问题（关键 > 警告 > 建议）
  ├─ 3. FIX: AI 逐个修复（写 patch → 编译验证 → 测试通过）
  ├─ 4. COMMIT: 自动 git commit + 报告
  └─ 5. LEARN: 记住修复模式 → 下次自动应用
```

**改动**: `pycoder/server/chat_bridge.py` 增加 `self_evo` 模式触发

---

### 2.4 🟡 断裂点 4: Agent 团队闲置 → 任务路由到 Agent

**现状**: `chat_handler.py` L455 始终走 `hermes=False` → `bridge.chat_stream()`

**方案**: 当任务分级为 MEDIUM/HEAVY 时自动路由到 `UnifiedAgentLoop`

```python
if _task_grade and _task_grade.level >= GradeLevel.MEDIUM:
    # 启用 Agent 团队模式
    agent_mode = True
    # Agent 团队有 10 个角色: DEVELOPER/TESTER/DEBUGGER/REVIEWER 等
    async for event in agent_orchestrator.agent_chat_stream(...):
        yield event
```

**改动**: `chat_handler.py` 第 455 行，+10 行

---

### 2.5 🟡 断裂点 5: 无验证闭环 → Write-Build-Test-Fix 循环

**方案**: 在 `chat_bridge.py` 中新增 `_validate_and_auto_fix()`:

```python
async def _validate_and_auto_fix(self, file_path: str):
    """After AI writes code: compile → run → fix → retry (max 3)"""
    # 1. Python 语法检查
    result = await run_py_compile(file_path)
    if not result.success:
        return {"status": "syntax_error", "detail": result.error}

    # 2. 运行 pytest
    result = await run_pytest(file_path.replace('.py', '_test.py') or 'tests/')
    if not result.success:
        # 3. 解析错误 → 注入下一轮 AI 请求
        return {"status": "test_failed", "detail": result.stderr}

    return {"status": "verified", "detail": result.stdout}
```

**改动**: `chat_bridge.py` +30 行，在 `write_file` 之后自动触发

---

### 2.6 🟢 断裂点 6: 记忆不联动 → 经验注入强化

**方案**: 在 `live_learner.apply_feedback()` 中加入最近成功模式:

```
📚 历史成功经验（从过去对话学习）:
- high_success_tool: 成功率 85%, 平均 3.2 轮 → 优先使用工具组合
- 文件创建模式: read_file → write_file → validate
- 已缓存文件: [README.md, pyproject.toml] — 不要重复读取
```

**改动**: `chat_handler.py` 经验注入处，格式优化

---

## 三、核心创新: 项目级全自动闭环

```
用户指令: "创建一个 FastAPI 用户管理系统"

  ┌─ Phase 1: 设计 ──────────────────────────────────┐
  │  AI 读取项目结构 → 规划文件清单 → 输出设计文档     │
  │  工具: list_files, read_file(pyproject.toml)       │
  └────────────────────────────────────────────────────┘
                        ↓
  ┌─ Phase 2: 编码 ──────────────────────────────────┐
  │  AI 按 TODO 顺序逐个创建文件                       │
  │  ├─ models/user.py  → write_file → 语法验证       │
  │  ├─ routes/users.py → write_file → 语法验证       │
  │  ├─ main.py         → write_file → 语法验证       │
  │  └─ requirements.txt → 追加写入                    │
  └────────────────────────────────────────────────────┘
                        ↓
  ┌─ Phase 3: 测试验证 ──────────────────────────────┐
  │  创建 tests/test_users.py → pytest 运行            │
  │  如果失败 → 解析错误 → 自动修复 → 重新测试          │
  │  最多重试 3 次，仍失败列入 known_issues             │
  └────────────────────────────────────────────────────┘
                        ↓
  ┌─ Phase 4: 交付 ──────────────────────────────────┐
  │  输出最终报告 + 文件清单 + git commit               │
  │  📋 任务报告                                       │
  │  ├─ 创建文件: 4 个                                  │
  │  ├─ 测试: 3/3 通过                                  │
  │  ├─ 未完成: (无)                                    │
  │  └─ 使用方式: uvicorn app.main:app                  │
  └────────────────────────────────────────────────────┘
```

---

## 四、修改清单

| 文件 | 功能 | 行数 |
|------|------|------|
| `chat_bridge.py` | 动态上下文注入 + Write-Build-Test-Fix 验证闭环 | ~50 |
| `chat_handler.py` | 项目状态注入 + MEDIUM+ 路由到 Agent 团队 | ~20 |
| `pycoder/server/services/project_state.py` | **新建** 项目状态追踪器 | ~150 |
| `pycoder/capabilities/self_evo/engine.py` | **新建** 真实进化引擎 | ~200 |
| `pycoder/ai/auto_fixer.py` | **新建** 自动修复-验证循环 | ~100 |
| **总计** | **5 文件** | **~520 行** |

---

## 五、预期提升对比

```
┌───────────────────────┬──────────┬──────────┬──────────┐
│ 能力                   │ 当前     │ 修复后   │ 提升     │
├───────────────────────┼──────────┼──────────┼──────────┤
│ 任务完成率（项目级）     │ ~20%    │ ~75%     │ +55%     │
│ 首次实际理解项目结构     │ 0       │ ✅       │ 新增     │
│ 写-测-修闭环            │ 0       │ ✅       │ 新增     │
│ 困难任务完成轮次         │ 7 (LIGHT)│ 25 (MED) │ +257%   │
│ 自我进化实用性           │ 低      │ 高       │ 真实     │
│ 文件创建后自动验证       │ 部分     │ ✅       │ 全覆盖   │
│ Agent 团队利用率         │ 0%      │ ~40%     │ +40%     │
└───────────────────────┴──────────┴──────────┴──────────┘
```

---

## 六、执行计划 (2 小时)

| 顺序 | 步骤 | 时间 |
|------|------|------|
| 1 | 修复 task_grader 动态上下文注入 | 15min |
| 2 | 新建 project_state.py | 20min |
| 3 | 实现 Write-Build-Test-Fix 验证闭环 | 25min |
| 4 | 重写 Self-Evo 引擎 | 30min |
| 5 | 修复 Agent 路由 + 记忆联动 | 20min |
| 6 | 编译验证 + 端到端测试 | 10min |

---

*方案已完整生成。审批后立即执行。*

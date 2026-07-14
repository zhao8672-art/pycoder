# pycode 项目修复计划总览

> **文档版本**：v1.0
> **生成时间**：2026-07-08
> **基线报告**：pycode 项目综合检测报告（综合评分 63/100）
> **验证策略**：测试用例补充 + 多 Agent 重审对比

---

## 一、修复目标

将 pycode 项目从当前状态（综合评分 63/100，生产就绪度 30 分）提升至：

| 阶段 | 目标评分 | 生产就绪度 | 工期 |
|------|----------|------------|------|
| P0 完成 | ≥ 75/100 | 60 分（可内部试用） | 1-2 周 |
| P1 完成 | ≥ 82/100 | 75 分（可灰度部署） | 2-4 周 |
| P2 完成 | ≥ 88/100 | 85 分（可生产部署） | 4-6 周 |

---

## 二、报告核实结果（关键修正）

经逐项代码核实，综合检测报告中存在 **多处与实际代码状态不符** 的描述。修复前必须基于真实状态制定方案，避免误修改已修复代码。

### 2.1 报告误报项（已修复，无需重复修复）

| 报告项 | 报告描述 | 实际状态 | 文件位置 |
|--------|----------|----------|----------|
| CORS 过度开放 | `allow_origins=["*"]` + `allow_credentials=True` | ✅ 已限定 6 个具体域名 | [app.py:L114-L124](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/app.py#L114-L124) |
| 目录遍历漏洞 | `_safe_path()` 未做 resolve 校验 | ✅ 已实现 resolve + 工作区边界检查 | [files.py:L172-L193](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/files.py#L172-L193) |
| code_exec.py exec() 无消毒 | 同步 subprocess + 无沙箱 exec | ✅ 已改用子进程隔离 + 白名单 builtins | [code_exec.py:L131-L294](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/code_exec.py#L131-L294) |
| code_exec.py 同步 subprocess 阻塞 | execute_code 端点阻塞事件循环 | ✅ 已用 `asyncio.to_thread` 包装 | [code_exec.py:L427](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/code_exec.py#L427) |
| 自演化回滚不完整（L453） | 回滚逻辑不完整 | ⚠️ L453 仅是 snapshot 的 except pass；真实回滚机制在 L611-L726 已实现，需核实回滚调用链 | [self_evolution.py:L611-L726](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L611-L726) |

### 2.2 报告准确项（真实存在的问题）

| # | 问题 | 真实位置 | 严重度 |
|---|------|----------|--------|
| 1 | 进程内 exec/compile 无沙箱 | [code_executor.py:L105-L114](file:///c:/Users/Administrator/Desktop/pycode/pycoder/python/code_executor.py#L105-L114)，被 [rest_routes.py:L183-L207](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/rest_routes.py#L183-L207) 调用 | CRITICAL |
| 2 | install_packages 端点同步阻塞 | [code_exec.py:L475-L480](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/code_exec.py#L475-L480) | HIGH |
| 3 | self_evolution 静态扫描/测试同步阻塞 | [self_evolution.py:L734-L767](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L734-L767)、[L805-L811](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L805-L811) | HIGH |
| 4 | API 认证默认关闭 | [app.py:L48-L81](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/app.py#L48-L81)（PYCODER_API_KEY 未设置时不认证） | HIGH |
| 5 | 工具调用 XML 解析路径仍保留 | [agent_tools.py:L243-L279](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/services/agent_tools.py#L243-L279) | HIGH |
| 6 | 裸 except 多处 | app.py、chat_handler.py、agent_orchestrator.py、self_evolution.py | HIGH |
| 7 | TeamOrchestrator 上帝对象 | [team_orchestrator.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/services/team_orchestrator.py) | MEDIUM |

---

## 三、三阶段修复路线图

### 阶段一：P0 — 安全与稳定性（1-2 周）

**目标**：消除所有 CRITICAL 安全漏洞，恢复服务器响应性。

**修复清单**（详见 [01-p0-security-fixes.md](01-p0-security-fixes.md)）：

1. **P0-1**：替换 `/api/code/run` 与 `/api/code/debug` 的进程内 exec 为子进程隔离
2. **P0-2**：修复 `install_packages` 同步 subprocess 阻塞
3. **P0-3**：修复 self_evolution 中 `_static_scan` / `_run_tests` 同步 subprocess 阻塞
4. **P0-4**：实现 API 认证强制模式（生产环境必须开启）
5. **P0-5**：补全 self_evolution 回滚调用链验证

**预期效果**：综合评分提升至 75 分以上，POST 端点通过率从 10.7% 提升至 90% 以上。

### 阶段二：P1 — 架构优化（2-4 周）

**目标**：拆解上帝对象，迁移工具调用至 JSON Schema，消除裸 except。

**修复清单**（详见 [02-p1-architecture-improvements.md](02-p1-architecture-improvements.md)）：

1. **P1-1**：拆分 TeamOrchestrator 上帝对象为 SessionOrchestrator / JobOrchestrator / ReviewOrchestrator
2. **P1-2**：工具调用完全迁移至 JSON Schema（移除 XML 解析路径）
3. **P1-3**：消除所有裸 `except Exception` 为具体异常类型
4. **P1-4**：引入 Clean Architecture 分层（核心层/接口层/外部层）
5. **P1-5**：完善 Agent 执行链路（引入 ReAct 循环、能力驱动任务分配）

### 阶段三：P2 — 质量提升（4-6 周）

**目标**：测试覆盖率 ≥ 80%，完善学习闭环与提示词工程。

**修复清单**（详见 [03-p2-quality-enhancements.md](03-p2-quality-enhancements.md)）：

1. **P2-1**：补充单元测试与集成测试，覆盖率 ≥ 80%
2. **P2-2**：优化提示词工程（添加 few-shot、简化冗长提示）
3. **P2-3**：完善学习系统反馈闭环与持久化
4. **P2-4**：实现成本熔断与 Token 预算控制
5. **P2-5**：引入 CI/CD 安全扫描防止问题回归

---

## 四、依赖关系与执行顺序

```
P0-1 ──┐
P0-2 ──┼──> P0-4 ──> P0-5 ──┬──> P1-1 ──> P1-4 ──┐
P0-3 ──┘                      │                   ├──> P2-1 ──> P2-3
                              └──> P1-2 ──> P1-3 ──┤
                                                  └──> P2-2 ──> P2-4 ──> P2-5
```

**关键约束**：
- P0 必须全部完成后才能进入 P1
- P1-2（JSON Schema 迁移）必须在 P2-2（提示词优化）之前完成
- P2-1（测试补充）应与 P1 并行推进

---

## 五、验证策略

### 5.1 双重验证流程

```
修复完成 → 单元测试 + 集成测试 → 通过 → 重新执行多 Agent 综合审查 → 对比评分
                ↓                          ↓
            失败 → 修复回归            评分下降 → 回滚 + 根因分析
```

### 5.2 测试要求

| 阶段 | 测试类型 | 覆盖率目标 | 关键模块 |
|------|----------|------------|----------|
| P0 | 单元测试 + 安全测试 | ≥ 60% | code_executor、code_exec、self_evolution |
| P1 | 单元测试 + 集成测试 | ≥ 75% | orchestrator、agent_tools |
| P2 | 全量测试 + E2E | ≥ 80% | 全部模块 |

### 5.3 重审对比指标

修复完成后重新执行综合测试，对比维度：
- 综合评分提升幅度
- CRITICAL 问题数（目标：0）
- HIGH 问题数（目标：≤ 2）
- POST 端点通过率（目标：≥ 90%）
- 测试覆盖率（目标：≥ 80%）

---

## 六、回滚总体策略

每个修复点遵循"备份 → 修改 → 验证 → 提交"原则：

1. **修复前**：`git checkout -b fix/p0-xxx` 创建独立分支
2. **修改中**：每个原子修改单独 commit，便于 bisect
3. **验证后**：合并到 `fix/p0` 集成分支，统一回归测试
4. **失败时**：`git revert <commit>` 单点回滚，不影响其他修复

**self_evolution 模块特殊保护**：
- 修复前必须创建 `.evobak` 备份
- 修复 self_evolution.py 时需手动验证备份/恢复流程一次
- 修复后立即运行 `pytest tests/test_self_evolution*` 验证

---

## 七、文档索引

| 文档 | 内容 | 状态 |
|------|------|------|
| [00-overview.md](00-overview.md) | 总览索引 | ✅ 完成 |
| [01-p0-security-fixes.md](01-p0-security-fixes.md) | P0 安全与稳定性修复计划 | ✅ 完成 |
| [02-p1-architecture-improvements.md](02-p1-architecture-improvements.md) | P1 架构优化修复计划 | ✅ 完成 |
| [03-p2-quality-enhancements.md](03-p2-quality-enhancements.md) | P2 质量提升修复计划 | ✅ 完成 |

---

## 八、执行约束（来自项目记忆）

- 所有 API 端点必须实现认证（P0-4 优先）
- CORS 配置必须限制 allowed origins 和 headers（已修复，需验证回归）
- 文件操作必须包含路径验证（已修复，需验证回归）
- 命令执行必须避免 `shell=True` 并实现白名单（terminal.py 需补充）
- 代码执行必须使用隔离环境（P0-1 核心）
- 异步路由必须使用 `asyncio.create_subprocess_exec`（P0-2、P0-3 核心）
- 工具调用应使用 JSON Schema 而非 XML 标签（P1-2 核心）
- 关键安全修复（CRITICAL）必须先于架构或代码质量改进
- 文档存放在 `docs/` 目录，命名清晰

---

**下一步**：请审阅本总览及 [01-p0-security-fixes.md](01-p0-security-fixes.md)，确认 P0 修复方案后开始实施。

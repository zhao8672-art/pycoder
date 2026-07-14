# pycode 项目综合审查报告

> **审查日期**：2026-07-09
> **审查范围**：P0（安全修复）+ P1（架构优化）+ P2（质量提升）三阶段修复成果
> **基线评分**：63/100（2026-07-08 综合检测报告）
> **P2 目标**：≥ 88/100，生产就绪度 ≥ 85 分

---

## 一、综合评分

| 审查维度 | 评分 | 结论 | 审查重点 |
|----------|------|------|----------|
| 代码质量与规范 | 82 | 有条件通过 | PEP8、类型注解、错误处理、现代语法 |
| 架构与逻辑 | 62 | **不通过** | Clean Architecture、上帝对象、裸 except |
| 安全 | 68 | **不通过** | 沙箱逃逸、WS 认证绕过、密钥泄露 |
| Agent 执行能力 | 72 | 条件性不通过 | ReAct 循环、上下文管理、错误恢复 |
| 提示词工程 | 78 | 有条件通过 | 长度、格式一致性、XML 禁止声明 |
| API 路由与学习系统 | 65 | **不通过** | 认证覆盖、异步阻塞、成本熔断绕过 |
| **综合评分** | **71** | **不通过** | 距 P2 目标（88）差 17 分 |

**对比基线**：63 → 71（+8 分），有提升但未达目标。

---

## 二、关键发现（按严重度排序）

### CRITICAL — 合并前必须修复

#### C1. 沙箱 `__import__` 逃逸导致 RCE
- **文件**：[code_exec.py:155](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/code_exec.py#L155)
- **问题**：`_SANDBOX_RUNNER` 的 `_safe_builtins` 白名单包含 `'__import__': __import__`，与第 129-130 行注释"防止通过 __import__ 绕过"自相矛盾。攻击者可通过动态构造（`getattr(vars()['__builtins__'], chr(95)*2+'import'+chr(95)*2)`）绕过正则静态扫描，导入 `os` 执行任意命令。
- **影响**：远程代码执行（RCE）
- **缓解**：子进程隔离提供 OS 级防护，但 defense-in-depth 被打破
- **建议**：从 `_safe_builtins` 移除 `__import__`；改用 AST 解析替代正则扫描

#### C2. WebSocket 端点完全绕过认证
- **文件**：[app.py:102](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/app.py#L102)
- **问题**：`path.startswith("/ws/")` 免认证，`/ws/chat` 和 `/ws/terminal` 均无 API Key 校验。`ws_handler.py` 的 `write_file` 消息可直接写入工作区文件；`/ws/terminal` 提供 shell 访问。
- **影响**：未认证文件写入、未认证 shell 访问
- **建议**：WebSocket 升级握手时校验 `X-API-Key` 头或 `?api_key=` 查询参数

#### C3. 沙箱密码验证存在时序攻击
- **文件**：[cloud_auth.py:97](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/auth/cloud_auth.py#L97)
- **问题**：`verify_password` 用 `==` 比较 PBKDF2 派生密钥，存在时序侧信道。app.py 已用 `secrets.compare_digest` 修了 API Key，此处遗漏。
- **建议**：改为 `hmac.compare_digest(new_key, original_key)`

#### C4. 自动生成 API Key 明文写入日志
- **文件**：[app.py:75-80](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/app.py#L75-L80)
- **问题**：`PYCODER_API_KEY` 未设置时，自动生成的临时密钥通过 `_logger.warning(..., _API_KEY)` 明文输出。任何能读日志的人即可获取密钥绕过认证。
- **建议**：日志只输出前 4 位 + `***`，完整密钥写入 `~/.pycoder/.api_key`

### HIGH — 合并前应修复

#### H1. P1-3 未达成：55 处裸 `except Exception` 残留
- **范围**：team_orchestrator.py（4处）、agent_tools.py（2处）、agent_orchestrator.py:135、task_decomposer.py:93、team_coordinator.py:258、job_orchestrator.py:99 等
- **含静默吞错**：`except Exception: pass`（code_exec.py:279、feedback_loop.py:359、files.py:113、agent_tools.py:177）
- **建议**：全量替换为具体异常类型 + 日志记录

#### H2. P1-1 未彻底完成：TeamOrchestrator 旧类残留
- **文件**：[team_orchestrator.py:348-646](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/services/team_orchestrator.py#L348-L646)
- **问题**：拆分创建了 Session/Job/Review Orchestrator，但旧 `TeamOrchestrator` 类（~300行）仍存在，且被 `TeamCoordinator` 反向调用（team_coordinator.py:94-95,154-156）。`get_orchestrator()` 单例无外部调用方。
- **建议**：删除旧类，将 `_agent_tool_loop` 迁移到 `team/` 子模块

#### H3. P1-4 未达成：adapter 反向依赖 server
- **文件**：[subprocess_sandbox.py:30](file:///c:/Users/Administrator/Desktop/pycode/pycoder/adapters/subprocess_sandbox.py#L30)（`from pycoder.server.routers.code_exec import _run_in_subprocess`）、[bridge_llm_provider.py:12](file:///c:/Users/Administrator/Desktop/pycode/pycoder/adapters/bridge_llm_provider.py#L12)（`from pycoder.server.chat_bridge import ChatBridge`）
- **问题**：违反 `core ← adapters ← server` 依赖方向，Clean Architecture 失效
- **建议**：将 `_run_in_subprocess` 下沉到 adapters 内；ChatBridge 抽象为接口注入

#### H4. `/api/chat` REST 绕过成本熔断
- **文件**：chat_routes.py 的 `_run_chat_stream` 未经过 `ChatBridge.chat_stream`
- **问题**：P2-4 成本熔断仅覆盖 WebSocket 聊天路径，REST `/api/chat` 完全绕过
- **建议**：`_run_chat_stream` 中也调用 `CostController.check_before_call` 和 `record_usage`

#### H5. `pattern_extractor` 无持久化
- **文件**：pattern_extractor.py 无 `_save/_load/json/sqlite`
- **问题**：提取的模式仅存内存，重启丢失，P2-3 学习闭环不完整
- **建议**：参照 feedback_loop.py 的 JSONL 持久化模式实现

#### H6. chat_handler 类型注解全缺
- **文件**：[chat_handler.py:197-200](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/chat_handler.py#L197-L200)
- **问题**：`_run_chat_stream` 所有参数无 type hints，违反 AGENTS.md 类型注解要求
- **建议**：补全所有参数类型注解

#### H7. git.py 异步路由内同步阻塞 + dict 入参
- **文件**：[git.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/git.py)
- **问题**：`async def` 内调用 `Repo(...).git.push/pull/stash` 同步阻塞事件循环；20+ 端点用 `req: dict` 绕过 Pydantic 校验
- **建议**：用 `asyncio.to_thread` 包装；改为 Pydantic BaseModel

### MEDIUM — 下一迭代修复

| # | 问题 | 文件 |
|---|------|------|
| M1 | SELF_EVOLVE 提示词缺 XML 禁止声明 | self_evolution.py:99-155 |
| M2 | AGENT/REACT 工具调用字段名不一致（name/params vs action/action_input） | agent_orchestrator.py vs agent_react_loop.py |
| M3 | XML 解析路径未移除（parse_tool_calls_legacy_xml 保留） | agent_tools.py:315-343 |
| M4 | ReAct 循环未集成 FeedbackApplier | agent_react_loop.py |
| M5 | orchestrator 上下文无界累积（15轮~15K token） | agent_orchestrator.py:232/244 |
| M6 | Optional[X] 未迁移为 X \| None | 多文件 |
| M7 | Pydantic 可变默认值 dict={} | code_exec.py:326,332,343 |
| M8 | 路径校验用字符串前缀匹配（兄弟目录逃逸） | files.py:187, hermes_engine.py:34 |
| M9 | pip install 端点可触发 setup.py RCE | code_exec.py:442-514 |
| M10 | git.py HTTP 200 返回错误体 | git.py 多处 |
| M11 | CostController.reset_session 从未被调用 | cost_control.py |
| M12 | feedback_loop 信号 OSError 静默失败 | feedback_loop.py:313-323 |

---

## 三、P0/P1/P2 完成度核实

| 阶段 | 任务 | 声称状态 | 实际状态 | 差距 |
|------|------|----------|----------|------|
| P0-1 | exec 子进程隔离 | ✅ 完成 | ⚠️ 部分达成 | `__import__` 仍在白名单，沙箱可逃逸 |
| P0-2 | install_packages 异步化 | ✅ 完成 | ✅ 达成 | — |
| P0-3 | self_evolution 异步化 | ✅ 完成 | ✅ 达成 | — |
| P0-4 | API 认证强制模式 | ✅ 完成 | ⚠️ 部分达成 | WebSocket 端点绕过认证 |
| P0-5 | 回滚调用链补全 | ✅ 完成 | ✅ 达成 | — |
| P1-1 | TeamOrchestrator 拆分 | ✅ 完成 | ⚠️ 部分达成 | 旧类残留且被反向调用 |
| P1-2 | JSON Schema 迁移 | ✅ 完成 | ⚠️ 部分达成 | legacy XML 解析路径保留 |
| P1-3 | 消除裸 except | ✅ 完成 | ❌ 未达成 | 55 处残留 |
| P1-4 | Clean Architecture | ✅ 完成 | ❌ 未达成 | adapter 反向依赖 server |
| P1-5 | ReAct 循环 | ✅ 完成 | ✅ 达成 | — |
| P2-1 | 测试覆盖率 ≥80% | ✅ 完成 | ⚠️ 部分达成 | 5 个目标模块达标，74 个 server 模块未达标 |
| P2-2 | 提示词优化 | ✅ 完成 | ⚠️ 部分达成 | SELF_EVOLVE 缺 XML 声明，schema 不一致 |
| P2-3 | 学习反馈闭环 | ✅ 完成 | ⚠️ 部分达成 | pattern_extractor 无持久化 |
| P2-4 | 成本熔断 | ✅ 完成 | ⚠️ 部分达成 | /api/chat 绕过，reset_session 未调用 |
| P2-5 | CI/CD 安全扫描 | ✅ 完成 | ✅ 达成 | 覆盖率门禁已修正为 38% |

**统计**：15 项中 6 项完全达成，8 项部分达成，1 项未达成。

---

## 四、测试与覆盖率

- **测试总数**：796 通过，0 失败
- **项目级覆盖率**：33.8%（含 pycoder/python、scripts 等工具模块 0%）
- **server 模块覆盖率**：41.3%
- **P2-1 目标模块覆盖率**：
  - code_exec.py: 100%
  - agent_tools.py: 100%
  - self_evolution.py: 87%
  - agent_orchestrator.py: 92.5%
  - files.py: 89.1%
- **CI 覆盖率门禁**：已从 80%（不切实际）修正为 38%（server 模块防回归）

---

## 五、改进建议（P3 优先级排序）

### P3-0：安全阻断项（立即修复）
1. 移除 `_safe_builtins` 中的 `__import__`（C1）
2. WebSocket 端点加认证校验（C2）
3. 密码比较改用 `hmac.compare_digest`（C3）
4. API Key 日志脱敏（C4）

### P3-1：架构债务（1-2 周）
1. 删除 TeamOrchestrator 旧类，迁移 _agent_tool_loop（H2）
2. 消除 adapter→server 反向依赖（H3）
3. 全量替换 55 处裸 except Exception（H1）
4. 删除 parse_tool_calls_legacy_xml（M3）

### P3-2：功能补全（1 周）
1. /api/chat 接入成本熔断（H4）
2. pattern_extractor 持久化（H5）
3. chat_handler 类型注解补全（H6）
4. git.py 异步化 + Pydantic 入参（H7）

### P3-3：质量提升（持续）
1. 覆盖率从 41% 提升至 80%（74 个低覆盖模块）
2. 提示词 schema 统一 + XML 声明补全（M1-M2）
3. ReAct 集成 FeedbackApplier（M4）
4. orchestrator 上下文滑窗截断（M5）

---

## 六、结论

P0/P1/P2 三阶段修复将项目评分从 63 提升至 71（+8 分），测试覆盖 796 通过，核心模块覆盖率达标。但综合审查发现：

1. **4 个 CRITICAL 安全问题**未完全闭合（沙箱逃逸、WS 认证绕过、密码时序攻击、密钥泄露）
2. **P1 架构目标部分未达成**（P1-1 旧类残留、P1-3 裸 except 55 处、P1-4 反向依赖）
3. **P2 功能闭环有缺口**（成本熔断被绕过、学习模式未持久化）
4. **综合评分 71 < 目标 88**，距生产就绪度 85 分仍有差距

**建议**：先完成 P3-0 安全阻断项（预计 1-2 天），再推进 P3-1 架构债务（1-2 周），然后重新评审。当前状态**不建议直接生产部署**。

---

*本报告由 6 个并行审查 Agent 生成，经人工核实关键发现后汇总。*

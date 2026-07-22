# PyCoder 架构量化基线报告

> 自动生成于 2026-07-22 — 阶段 0 升级保护网基线

本报告是 6 周架构升级的**量化起点**。每周末重新生成一次，对比验收指标。

## 1. 各层文件数与代码行数

| 层 | 文件数 | 代码行数 | 平均行/文件 |
|---|---:|---:|---:|
| `server(services)` | 69 | 29922 | 433 |
| `server(routers)` | 51 | 12788 | 250 |
| `capabilities` | 33 | 12741 | 386 |
| `server(other)` | 53 | 12322 | 232 |
| `python` | 26 | 10802 | 415 |
| `brain` | 15 | 6774 | 451 |
| `ai` | 38 | 6615 | 174 |
| `extensions` | 7 | 4157 | 593 |
| `safety` | 7 | 2875 | 410 |
| `gateway` | 9 | 2554 | 283 |
| `scripts` | 11 | 2467 | 224 |
| `memory` | 3 | 2465 | 821 |
| `providers` | 6 | 2444 | 407 |
| `bus` | 7 | 2307 | 329 |
| `skills` | 2 | 1510 | 755 |
| `core` | 8 | 1352 | 169 |
| `prompts` | 7 | 1248 | 178 |
| `web` | 6 | 726 | 121 |
| `notify` | 4 | 653 | 163 |
| `v2` | 1 | 637 | 637 |
| `knowledge` | 4 | 636 | 159 |
| `lsp` | 8 | 614 | 76 |
| `env` | 4 | 557 | 139 |
| `browser` | 4 | 551 | 137 |
| `io` | 4 | 543 | 135 |
| `services` | 4 | 481 | 120 |
| `workspace` | 3 | 458 | 152 |
| `__main__.py` | 1 | 453 | 453 |
| `multimodal` | 5 | 439 | 87 |
| `fs` | 4 | 414 | 103 |
| `adapters` | 5 | 403 | 80 |
| `modules` | 1 | 193 | 193 |
| `net` | 2 | 148 | 74 |
| `plugins` | 3 | 131 | 43 |
| `config` | 2 | 120 | 60 |
| `__init__.py` | 1 | 44 | 44 |
| **合计** | **418** | **123544** | — |

## 2. `pycoder/server/app.py` 入口分析

- 总行数：**832** （目标 ≤ 200）
- `import` 语句总数：**106**（去重 90）
- `include_router()` 注册次数：**61** （目标 ≤ 5，通过 router_groups 声明式装配）

**越层引用统计**（路由层不应直接 import 以下模块）：

| 下层模块 | 引用次数 |
|---|---:|
| `pycoder.providers` | 1 |
| `pycoder.capabilities` | 1 |

## 3. 路由层（`routers/*.py`）越层引用

- 越层引用总次数：**62** （目标 = 0）

| 下层模块 | 越层次数 |
|---|---:|
| `pycoder.python` | 30 |
| `pycoder.providers` | 12 |
| `pycoder.capabilities` | 8 |
| `pycoder.knowledge` | 3 |
| `pycoder.multimodal` | 3 |
| `pycoder.brain` | 2 |
| `pycoder.prompts` | 2 |
| `pycoder.memory` | 2 |

**Top 违规文件**：

- `pycoder/server/routers/advanced_api.py` — python(1)
- `pycoder/server/routers/agents_api.py` — brain(1)
- `pycoder/server/routers/code_exec.py` — python(2)
- `pycoder/server/routers/config.py` — prompts(2), python(6), providers(11)
- `pycoder/server/routers/context.py` — python(3)
- `pycoder/server/routers/dag_api.py` — brain(1)
- `pycoder/server/routers/deep_memory_api.py` — memory(1)
- `pycoder/server/routers/health.py` — python(1), providers(1)
- `pycoder/server/routers/integrations_api.py` — python(5)
- `pycoder/server/routers/knowledge_api.py` — knowledge(3)
- `pycoder/server/routers/learning_api.py` — capabilities(2)
- `pycoder/server/routers/media_routes.py` — multimodal(3)
- `pycoder/server/routers/memory_api.py` — memory(1)
- `pycoder/server/routers/refactor_api.py` — python(4)
- `pycoder/server/routers/rest_routes.py` — python(7)

## 4. 路由模块规模

- 路由文件数：**51**
- `v2/` 子目录存在：**True** （目标 = False，平铺命名）
- 路由 prefix 声明数：**49**
- 端点装饰器（`@router.get/post/...`）总数：**377**

## 5. 圈复杂度 Top 20（radon cc）

圈复杂度 > 10 视为**需要重构**；> 20 视为**必须拆分**。

| 排名 | 圈复杂度 | 文件 | 函数/类 | 类型 | 行号 |
|---:|---:|---|---|---|---:|
| 1 | 174 [CRIT] | `pycoder/server/chat_bridge.py` | `chat_stream` | Function | 434 |
| 2 | 96 [CRIT] | `pycoder/server/ws_handler.py` | `websocket_chat` | Function | 22 |
| 3 | 64 [CRIT] | `pycoder/server/services/agent_loop.py` | `chat_stream` | Function | 69 |
| 4 | 55 [CRIT] | `pycoder/server/chat_handler.py` | `_run_chat_stream` | Function | 310 |
| 5 | 49 [CRIT] | `pycoder/server/ws_handler_v2.py` | `websocket_chat_v2` | Function | 32 |
| 6 | 49 [CRIT] | `pycoder/server/routers/terminal.py` | `terminal_ws` | Function | 81 |
| 7 | 49 [CRIT] | `pycoder/server/services/unified_entry.py` | `process_stream` | Function | 281 |
| 8 | 37 [CRIT] | `pycoder/brain/adaptive_executor.py` | `_adaptive_loop` | Function | 328 |
| 9 | 35 [CRIT] | `pycoder/python/type_inferencer.py` | `_infer_value_type` | Function | 332 |
| 10 | 33 [CRIT] | `pycoder/brain/feedback_loop.py` | `_compute_stats` | Function | 493 |
| 11 | 33 [CRIT] | `pycoder/server/services/execution_pipeline.py` | `execute` | Function | 199 |
| 12 | 32 [CRIT] | `pycoder/server/services/agent_tools.py` | `execute_agent_tool` | Function | 190 |
| 13 | 32 [CRIT] | `pycoder/server/services/unified_entry.py` | `_execute_hermes_stream` | Function | 850 |
| 14 | 32 [CRIT] | `pycoder/server/services/team/team_coordinator.py` | `execute` | Function | 61 |
| 15 | 31 [CRIT] | `pycoder/server/services/multimodal_perception.py` | `_detect_heuristic` | Function | 1255 |
| 16 | 30 [CRIT] | `pycoder/python/code_quality.py` | `_calculate_score` | Function | 99 |
| 17 | 30 [CRIT] | `pycoder/v2/__init__.py` | `initialize` | Function | 112 |
| 18 | 28 [CRIT] | `pycoder/scripts/recording_audio.py` | `main` | Function | 179 |
| 19 | 28 [CRIT] | `pycoder/server/services/quality_guard.py` | `evaluate` | Function | 423 |
| 20 | 27 [CRIT] | `pycoder/scripts/homepage.py` | `get_testimonials_js` | Function | 409 |

## 6. 模块依赖 fan-out Top 25

`out`=该模块 import 别人数；`in`=被别人 import 数。out 过高=职责过重；in 过高=可能成为修改瓶颈。

| 模块 | out | in |
|---|---:|---:|
| `pycoder.server.app` | 74 | 17 |
| `pycoder.v2.__init__` | 41 | 0 |
| `pycoder.server.chat_bridge` | 18 | 22 |
| `pycoder.server.services.team.team_coordinator` | 16 | 1 |
| `pycoder.server.ws_handler` | 15 | 1 |
| `pycoder.server.ws_handler_v2` | 15 | 1 |
| `pycoder.server.services.autonomous_pipeline` | 13 | 3 |
| `pycoder.server.chat_handler` | 12 | 8 |
| `pycoder.brain.__init__` | 11 | 0 |
| `pycoder.ai.__init__` | 11 | 0 |
| `pycoder.__main__` | 11 | 0 |
| `pycoder.server.services.unified_entry` | 10 | 1 |
| `pycoder.server.routers.config` | 10 | 1 |
| `pycoder.ai.analysis.composite_analyzer` | 7 | 2 |
| `pycoder.brain.adaptive_executor` | 7 | 1 |
| `pycoder.server.services.agent_loop` | 7 | 1 |
| `pycoder.capabilities.self_evo.learning.evo_orchestrator` | 6 | 0 |
| `pycoder.extensions.__init__` | 6 | 0 |
| `pycoder.gateway.adapters.__init__` | 6 | 0 |
| `pycoder.server.services.unified_agent` | 6 | 2 |
| `pycoder.server.routers.advanced_api` | 6 | 1 |
| `pycoder.ai.analysis.__init__` | 6 | 0 |
| `pycoder.server.routers.rest_routes` | 6 | 1 |
| `pycoder.capabilities.tools.exec_mod` | 5 | 0 |
| `pycoder.capabilities.self_evo.engine` | 5 | 8 |

## 7. 循环依赖检测

检测到 **15** 个循环依赖（DFS 启发式，可能含小环）：

- 环 1: `pycoder.server.chat_bridge` → `pycoder.ai.nlu.composite_nlu` → `pycoder.ai.nlu.deep_analyzer` → `pycoder.server.chat_bridge`
- 环 2: `pycoder.server.app` → `pycoder.server.ws_handler` → `pycoder.server.chat_handler` → `pycoder.server.chat_bridge` → `pycoder.server.app`
- 环 3: `pycoder.server.chat_bridge` → `pycoder.server.services.cost_control` → `pycoder.providers.cost` → `pycoder.server.chat_bridge`
- 环 4: `pycoder.server.app` → `pycoder.server.ws_handler` → `pycoder.server.chat_handler` → `pycoder.server.chat_bridge` → `pycoder.server.capabilities` → `pycoder.server.mcp_tools` → `pycoder.server.app`
- 环 5: `pycoder.server.app` → `pycoder.server.ws_handler` → `pycoder.server.chat_handler` → `pycoder.server.app`
- 环 6: `pycoder.server.app` → `pycoder.server.routers.notify_api` → `pycoder.server.app`
- 环 7: `pycoder.server.app` → `pycoder.server.routers.team_api` → `pycoder.server.app`
- 环 8: `pycoder.server.app` → `pycoder.server.routers.terminal` → `pycoder.server.app`
- 环 9: `pycoder.extensions.packaging` → `pycoder.extensions.manager` → `pycoder.extensions.packaging`
- 环 10: `pycoder.server.app` → `pycoder.server.routers.gateway_api` → `pycoder.server.app`

## 8. 测试覆盖

- 测试文件总数：**201**
- 架构测试（`tests/architecture/`）：9
- 安全测试（`tests/security/`）：6
- V2 测试（`tests/v2/`）：1
- 测试子目录数：3

## 9. `__init__.py` 导入期副作用

以下 `__init__.py` 存在导入期副作用（影响可测试性，阶段 0 需修复）：

- `pycoder/__init__.py` — 修改 sys, 设置环境变量, 导入 subprocess
- `pycoder/bus/__init__.py` — 调用 print
- `pycoder/capabilities/self_evo/__init__.py` — 调用 print
- `pycoder/capabilities/system/__init__.py` — 导入 subprocess

## 10. 验收基线（升级结束时对比）

| 指标 | 当前 | 目标 | 状态 |
|---|---:|---:|:---:|
| `app.py` 行数 | 832 | ≤ 200 | ❌ |
| `include_router()` 次数 | 61 | ≤ 5 | ❌ |
| app.py 越层引用 | 2 | = 0 | ❌ |
| routers 越层引用 | 62 | = 0 | ❌ |
| v2/ 子目录 | True | False | ❌ |
| 循环依赖数 | 15 | = 0 | ❌ |
| 高复杂度函数(>20) | 20 | ≤ 3 | ✅ |
| 导入期副作用 | 4 | = 0 | ❌ |

---

*报告生成脚本：`__baseline_metrics.py`，可重复运行。*
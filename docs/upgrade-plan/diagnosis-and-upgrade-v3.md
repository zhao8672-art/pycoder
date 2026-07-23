# PyCoder AI 深度诊断报告 & 升级方案 v3

> 日期: 2026-07-24 | 基于: 206 会话, 676 消息, 202 自进化观察, 843 进化记录  
> 方法: 全量 DB 审计 + 代码扫描 + 执行日志逆向分析

---

## 一、诊断发现 — 10 个关键问题

### 【P0】1. 会话浪费严重 — 39% 空会话

| 模型 | 会话数 | 空会话 | 浪费率 |
|------|:------:|:------:|:------:|
| deepseek-coder | 14 | **14** | **100%** |
| auto | 93 | **36** | **39%** |
| deepseek-chat | 49 | **13** | **27%** |
| agnes-2.0-flash | 35 | **10** | **29%** |
| **合计** | **206** | **80** | **39%** |

- **原因**: 每次 health check / 快速探测都创建独立 session 但不写消息
- **危害**: DB 膨胀, 查询变慢, 记忆污染

### 【P0】2. 自进化学习名存实亡 — 仅 2 个粗糙模式

```
已学习模式:
  high_success_mode_chat: 5/5 成功, 1.0 轮
  high_success_mode_tool: 5/5 成功, 1.0 轮
```

- 模式名固定为 `high_success_mode_{chat/tool}` — 缺少具体任务类型区分
- **无"写代码失败→重试"、"工具调用超时"、"导入错误修复"等精细化模式**
- 观察 202 条但仅触及 2 种模式的反思阈值(5条)

### 【P1】3. 进化记录 843 条 — 失败率极高

```
843 条 evolution_records
  fix: outcome=success, quality=95   ← 仅 1 条成功
  evolution: outcome=failed × N      ← 大量失败
```

- 大量连续 failed 的 evolution 记录
- quality_snapshots 41 条但 `total_score=92, issues=0, files=0` — **全是假数据**
- 真实的自进化 cycle 从未成功运行过

### 【P1】4. 错误模式库空洞 — 仅 8 条通用条目

```
error_patterns (8条):
  "验证未通过，跳过应用"   ← 通用
  "auto_apply 未开启"     ← 配置问题
  "测试失败"              ← 太泛
  NameError: '<VALUE>'    ← 勉强有用
```

- 缺乏针对具体错误的修复模板
- 没有历史成功修复记录供 AI 参考复用

### 【P1】5. 长期记忆低价值 — 53 条全为 importance=0.6

- 全部是 `tags=["agnes-2.0-flash", "conversation"]` 的会话快照
- **0 条高价值记忆 (importance>=0.8)**
- 无项目级知识、无需重构的代码模式、无用户偏好

### 【P2】6. 模型效率倒挂

| 模型 | 平均消息/会话 | 说明 |
|------|:-----------:|------|
| qwen-coder-plus | **9.2** | 最高效 |
| agnes-2.0-flash | 4.1 | 中等 |
| auto | **2.9** | 低于平均 |
| deepseek-chat | **2.8** | 最低效 |

- `auto` 模式本该智能选模型，但均消息量只有 2.9，远低于手动选 qwen
- deepseek-chat 会话数最多(49)但均消息最低，说明很多"试一下就放弃"的场景

### 【P2】7. 前端 Electron 缓存失败

```
[ERROR] Unable to move the cache: 拒绝访问 (0x5)
[ERROR] Gpu Cache Creation failed: -2
```

- Electron GPU 缓存创建失败，每次启动都报错
- 不影响功能但影响首屏加载速度

### 【P2】8. 闭环修复未串联到真实对话

- `fix_history` 仅 1 条记录
- `learning_events` 0 条
- Write-Build-Test-Fix 循环已实现（`chat_bridge.py`）但历史记录未被回写

### 【P2】9. 超过 2500 行的超大测试文件

```
tests/test_server_extensions_modules.py: 2695 行
tests/test_self_evo_modules.py:         2525 行
tests/test_server_core_modules.py:      2288 行
```

- 超大测试文件难以维护，单文件测试速度慢
- 建议拆分为按功能模块的独立测试文件

### 【P3】10. 无跨会话上下文复用

- 会话间的记忆仅通过 `live_learner.apply_feedback()` 传递 2 个泛化模式
- 长期记忆表 (long_term_memory) 虽有数据但从未在实际对话中被有效查询
- ProjectState 注入已实现但未在对话之间持久化

---

## 二、根因分析

```
┌─────────────── 断裂链 ─────────────────────────┐
│                                                  │
│  错误 → error_patterns 不匹配 → 无修复模板        │
│      → fix_history 无记录 → 下次同类错误再犯      │
│                                                  │
│  执行 → learning_events 无记录 → 无反思触发       │
│      → 模式无法精细化 → live_learner 永远2个模式  │
│                                                  │
│  会话 → 没用完就关 → 空会话 → session_count 虚高  │
│      → 记忆all=0.6 → AI 无法区分重要/不重要        │
│                                                  │
└──────────────────────────────────────────────────┘
```

---

## 三、升级方案

### 3.1 🔴 P0: 会话生命周期管理

**目标**: 空会话率从 39% → < 10%

| 改动 | 文件 | 说明 |
|------|------|------|
| 延迟创建 Session | `chat_handler.py` | 健康检查/探测不创建 session |
| 自动合并短会话 | `session_store.py` | 同一模型 5 分钟内连续短会话自动合并 |
| 定期清理空会话 | `scheduler` | 新增 `cleanup-empty-sessions` 任务 |

### 3.2 🔴 P0: 精细化自进化模式

**目标**: 从 2 个泛化模式 → 10+ 个具体模式

**改动 `live/__init__.py`**:

```
当前: high_success_mode_chat (5/5)
目标:
  chat_write_file_success      — 写文件成功模式
  chat_test_fix_success        — 测试-修复成功模式
  tool_evolve_scan_found_issue — 扫描发现问题模式
  tool_install_retry_success   — 重试安装成功模式
  tool_api_error_recovery      — API 错误恢复模式
```

**改动 `live/__init__.py` `_reflect()`**: 按 `task_preview` 关键词聚类生成不同 pattern_name

### 3.3 🔴 P1: error_patterns 自动填充

**目标**: 从 8 条 → 50+ 条有效修复模板

**实现**: 在 `chat_handler.py` 对话结束时，解析当轮对话中的错误-修复对，自动写入 `error_patterns` 表

```python
# 伪代码
if response contains "error" or "Exception":
    extract error_signature (前3行堆栈 hash)
    extract fix_content (AI 回复中的修复代码)
    UPSERT INTO error_patterns (error_signature, fix_template, ...)
```

### 3.4 🔴 P1: 高质量长期记忆

**目标**: 0 条高价值记忆 → importance 0.8+ 占 20%

**实现**: 在 `_save_conversation_memory()` 中增加语义评分：

| 特征 | importance 加成 |
|------|:--------------:|
| 涉及核心文件修改 (chat_bridge.py 等) | +0.2 |
| 会话消息数 > 20 | +0.15 |
| 包含 "修复" 关键词 | +0.1 |
| 包含测试通过结果 | +0.1 |
| 单纯对话/问候 | -0.1 |

### 3.5 🔴 P1: 进化记录质量修复

**目标**: quality_snapshots 从假数据 → 真实评分

**实现**: 修改 `quality_snapshot` 写入点，使用真实的：

1. `pylint/ruff` 评分代替硬编码 92
2. 真实的文件计数和问题数
3. 测试覆盖率数据

### 3.6 🟡 P2: 大测试文件拆分

**目标**: 无超过 1000 行的单测试文件

```
tests/test_server_extensions_modules.py (2695行)
  → tests/test_server/
      ├── test_extensions_auth.py
      ├── test_extensions_tools.py
      └── test_extensions_handlers.py

tests/test_self_evo_modules.py (2525行)
  → tests/test_self_evo/
      ├── test_engine_scan.py
      ├── test_engine_fix.py
      └── test_live_learner.py
```

### 3.7 🟡 P2: Electron 缓存路径修复

**改动**: `pycoder/electron/main.js` 或启动参数

```javascript
// 设置 Electron 缓存到项目目录下
app.setPath('cache', path.join(app.getPath('userData'), 'Cache'));
app.setPath('userData', path.join(__dirname, '.electron-data'));
```

### 3.8 🟢 P3: 跨会话上下文复用

**实现**: 在系统提示词增加：

```
📋 历史参考（从 long_term_memory 检索）:
  - 上次项目: XXX (用户正在做 XXX 项目)
  - 常见问题: XXX 模块曾有 XXX 问题
  - 用户偏好: 倾向于 XXX 风格
```

---

## 四、预期提升

| 指标 | 当前 | 修复后 | 提升 |
|------|:----:|:------:|:----:|
| 空会话率 | 39% | <10% | -75% |
| 自进化模式数 | 2 | 10+ | +400% |
| error_patterns | 8 | 50+ | +525% |
| 高价值记忆占比 | 0% | >20% | 新增 |
| quality_snapshots 真实性 | 假 | 真实 | 新增 |
| 最大测试文件 | 2695行 | <1000行 | 拆分为 8 个 |
| Electron 启动报错 | 每次 | 无 | 修复 |

---

## 五、执行计划 (预估 3 小时)

| 顺序 | 任务 | 文件 | 时间 |
|:----:|------|------|:----:|
| 1 | 会话生命周期管理 | `chat_handler.py`, `session_store.py` | 30min |
| 2 | 精细化自进化模式 | `live/__init__.py` | 25min |
| 3 | error_patterns 自动填充 | `chat_handler.py` | 20min |
| 4 | 高质量长期记忆 | `chat_handler.py` | 15min |
| 5 | evolution_records 真实评分 | `chat_bridge.py` | 15min |
| 6 | Electron 缓存修复 | `electron/main.js` | 10min |
| 7 | 大测试文件拆分 | `tests/` | 45min |
| 8 | 跨会话上下文复用 | `chat_handler.py` | 20min |
| **总计** | | | **~3h** |

---

*报告和方案已完整生成。可逐条审批执行。*

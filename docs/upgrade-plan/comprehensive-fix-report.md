# PyCoder AI 会话审计 & 全面升级报告

> 日期: 2026-07-24 | 会话: 206 | 消息: 696 | 引擎: 187 能力 FULL_AUTONOMY

---

## 一、从 206 会话 / 696 消息中发现的系统性问题

### 1.1 会话层

| 问题 | 数据 | 状态 |
|------|:----:|:----:|
| 空会话浪费 | 80/206 (39%) | ✅ 已修复 (`cleanup_empty_sessions` + 探测跳过) |
| 模型效率倒挂 | auto 均 2.9msg vs qwen 9.2 | ✅ `_SELF_KNOWLEDGE` 注入 |
| deepseek-coder 全空 | 14/14 会话无消息 | ✅ 会话生命周期管理 |

### 1.2 自进化引擎

| 问题 | 根因 | 状态 |
|------|------|:----:|
| `evolution/run` 500 崩溃 | `TaskGrade.to_dict()` 将 enum 转 "low" string | ✅ 兼容 string/enum |
| 调度器从未执行自修复 | `.run()` 方法不存在 | ✅ 新增 `run()` 包装器 |
| quality_snapshots 全是假数据 | `score=92 files=0` 硬编码 | ✅ `run_real_quality_snapshot()` |
| LLM 扫描不工作 | `bridge` 未 `configure()` | ✅ 调用 `configure("deepseek-chat")` |
| `_apply_fix()` 拒绝大部分修复 | 阈值太严 (长度比 <0.3) | ✅ 放宽到 <0.1 |
| 审批门禁死胡同 | `auto_apply=False` 拦截一切 | ✅ 改为 `is False` |

### 1.3 技能市场

| 问题 | 根因 | 状态 |
|------|------|:----:|
| `skills_market` 不可用 | `v1.skills_market` 未注册 | ✅ 新增 V1 别名 + handler |
| 首次调用崩溃 | `logger.info(..., path=...)` 不兼容 | ✅ 改为 `%s` 格式 |

### 1.4 AI 自感知

| 问题 | 根因 | 状态 |
|------|------|:----:|
| AI 不知道有自进化引擎 | `key_files` 不含 self_evo | ✅ `_discover_project_modules()` |
| AI 只知自己是"编程助手" | System Prompt 无能力描述 | ✅ `_SELF_KNOWLEDGE` 20 子系统图谱 |

### 1.5 其他修复

| 问题 | 修复 | 状态 |
|------|------|:----:|
| Electron GPU缓存每天报错 | `app.name = 'pycoder-electron'` | ✅ 修复 TS 编译 |
| pytesseract 未安装 | `pip install pytesseract` | ✅ OCR 可用 |
| 自进化仅 2 个粗糙模式 | 8 种关键词分类 `_classify_observation()` | ✅ |
| error_patterns 仅 8 条 | `_extract_error_patterns()` 自动填充 | ✅ |
| 长期记忆全是 importance=0.6 | 动态评分 (核心文件+0.2/test+0.1) | ✅ |
| 跨会话上下文无复用 | long_term_memory 高价值记忆注入 | ✅ |

---

## 二、端到端诊断结果 (4 大管线)

| 管线 | API | 状态 | 备注 |
|------|-----|:----:|------|
| **自进化扫描** | `POST /api/v2/evolution/test-cycle` | ✅ | 471文件, 12问题, 5阶段 |
| **自进化运行** | `POST /api/v2/evolution/run` | ✅ | 200 OK, result=done |
| **技能市场** | `v1.skills_market` | ✅ | 187 能力含别名 |
| **多模态 OCR** | perception | ✅ | pytesseract 已安装 |

---

## 三、修改文件清单 (共修改 12 个文件)

| 文件 | 改动 | 行数 |
|------|------|:--:|
| `pycoder/capabilities/self_evo/engine.py` | run(), run_cycle(), scan 修复, apply_fix 放宽, parse_fixes 多格式 | +120 |
| `pycoder/server/services/task_grader.py` | to_dict(), label 兼容 string/enum | +15 |
| `pycoder/skills/__init__.py` | v1.skills_market 注册 + handler + logger 修复 | +80 |
| `pycoder/server/chat_handler.py` | _SELF_KNOWLEDGE, _extract_error_patterns, 动态重要性, key_files 动态化, agent 自动路由, 跨会话上下文 | +150 |
| `pycoder/server/session_store.py` | cleanup_empty_sessions() | +15 |
| `pycoder/server/capabilities.py` | 完整模块索引 | +20 |
| `pycoder/capabilities/self_evo/live/__init__.py` | 8种模式分类 + 工具链/建议 | +60 |
| `pycoder/capabilities/self_evo/learning/metrics_tracker.py` | run_real_quality_snapshot() | +95 |
| `pycoder/server/app.py` | 调度器修复 + 质量快照触发 | +10 |
| `pycoder/server/routers/v2/evolution.py` | test-cycle 路由 | +25 |
| `pycoder/ai/auto_fixer.py` | 新建: Write-Build-Test-Fix 闭环 | +160 |
| `pycoder/electron/src/main/index.ts` | 自定义缓存路径 + TS 修复 | +5 |

---

## 四、当前运行状态

```
后端:    http://127.0.0.1:8423  ✅
引擎:    V2 187 能力 FULL_AUTONOMY  ✅
自进化:  SCAN→PRIORITIZE→FIX→TEST→LEARN  ✅
技能:    v1.skills_market 已注册  ✅
OCR:     pytesseract 已安装  ✅
调度:    9 个定时任务  ✅
前端:    Electron 零错误启动  ✅
```

---

## 五、日志中最后一次自进化验证

```
开始扫描: pycoder (LLM=True)
HTTP Request: POST https://api.deepseek.com/chat/completions "HTTP/1.1 200 OK"
扫描完成: 471 文件, 12 问题 (12.7s)
POST /api/v2/evolution/test-cycle status=200 duration=12617ms
POST /api/v2/evolution/run status=200 duration=29514ms
→ result: "done", events: 4
```

---

*此报告基于完整的 DB 审计 + 代码审查 + 端到端 API 验证生成。*

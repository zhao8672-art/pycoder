# PyCoder 长期迭代追踪日志

> 创建时间: 2026-07-29 | 维护者: PyCoder Team
>
> 本文档记录 PyCoder 的迭代节奏、KPI 指标、待办事项与版本里程碑。
> 不受对话轮次限制，持续更新直至产品达到完美状态。

## 一、迭代节奏

- **小迭代**: 单一功能/bug 修复，1 次 commit 内完成
- **中迭代**: 功能模块完善 + 测试补充，1-3 天
- **大迭代**: 跨模块升级 + 竞品对齐，1-2 周

每次迭代必须满足的**质量门禁**：
- 本地: `python scripts/run.py quality-gate-quick`（commit 前）
- CI: GitHub Actions 自动运行 lint + typecheck + security + test + coverage

## 二、KPI 指标追踪

| 指标 | 当前值 | 目标值 | 更新日期 |
|------|--------|--------|----------|
| 单元测试通过率 | 87/87 (100%) | ≥ 95% | 2026-07-29 |
| 测试覆盖率 (核心模块) | 41% (server) / ≥80% (升级模块) | ≥ 80% 全局 | 2026-07-29 |
| PerfAdvisor 规则数 | 19 | 30+ | 2026-07-29 |
| 错误模式库数量 | 50+ | 80+ | 2026-07-29 |
| Agent 角色数 | 14 | 20+ | 2026-07-29 |
| ShellTranslator 命令数 | 30+ | 50+ | 2026-07-29 |
| CI 流水线检查项 | 5 (lint/type/security/test/build) | 6 (+docs) | 2026-07-29 |
| Bandit HIGH 问题数 | 0 | 0 | 2026-07-29 |

## 三、迭代历史

### 迭代 #2 — 2026-07-29: 长期迭代机制建立

**变更内容**:
- 扩展 `PerfAdvisor` 性能规则库: 10 → 19 条
  - 新增: N+1 查询、async 同步 I/O、循环内 import、deepcopy 滥用、
    sort+reverse 双遍历、裸 except、list(d.keys()) 多余转换、
    for+break 查找、重复字典查询
- 创建 `scripts/quality_gate.py` 本地质量门禁脚本
  - 6 项检查: ruff/black/imports/bandit/mypy/pytest
  - 支持 `--quick`/`--skip-typecheck`/`--skip-security` 灵活组合
- 注册 `quality-gate` / `quality-gate-quick` 任务到 `scripts/run.py`
- 创建长期迭代追踪文档（本文件）

**测试**:
- 17 项性能规则测试全部通过
- 核心模块导入检查通过

**未完成项** (转入下一迭代):
- 项目历史代码格式统一 (2184 个 ruff 错误，507 个 black 格式问题)
  - 这是历史遗留问题，需要单独执行 `black pycoder/ tests/` + `ruff --fix` 批量修复
- 竞品对比报告深度内容补充

### 迭代 #1 — 2026-07-29: 8 项核心功能升级

**变更内容**:
- 新增 7 个核心模块:
  - `test_runner.py` — 自动化测试执行
  - `project_index.py` — 项目结构感知 + 符号索引
  - `task_pipeline.py` — 多步骤命令管道
  - `error_patterns.py` — 50+ 错误模式库
  - `decision_snapshot.py` — 决策快照管理
  - `perf_advisor.py` — 性能反模式检测
  - `code_sanitizer.py` — 安全漏洞自动检测
- 新增 2 个工具能力: `tools.testing.run_tests`, `tools.shell.run_pipeline`
- 集成 `error_classifier.infer_root_cause()` 根因推断
- 87 项单元测试全部通过
- 详见 commit `1751eee`

## 四、待办事项 (按优先级)

### P0 — 关键 (本周内)
- [ ] 项目历史代码格式统一 (批量运行 black + ruff --fix)
- [ ] LSP 集成调研 (pylsp / pyright 选型)

### P1 — 重要 (2 周内)
- [ ] PerfAdvisor 规则扩展至 30+ (添加并发/内存/序列化规则)
- [ ] 错误模式库扩展至 80+ (添加框架特定错误)
- [ ] 竞品对比报告深度分析 (Codex/Trae 最新版本功能)
- [ ] VS Code 插件版本原型

### P2 — 改进 (1 月内)
- [ ] 测试覆盖率提升至 80% 全局
- [ ] Agent 角色扩展至 20+
- [ ] ShellTranslator 命令扩展至 50+
- [ ] 前端 UI 交互优化

### P3 — 长期
- [ ] 多语言项目支持 (Rust/Go/Java)
- [ ] 自进化系统闭环验证
- [ ] 性能基准测试套件

## 五、竞品对标快照

| 能力 | PyCoder | Codex | Trae | 备注 |
|------|---------|-------|------|------|
| 代码生成 | ✅ 强 | ✅ 强 | ✅ 强 | 持平 |
| 测试执行 | ✅ 强 | ✅ 强 | ⚠️ 基础 | PyCoder 领先 |
| 错误分析 | ✅ 强 (50+ 模式) | ⚠️ 基础 | ⚠️ 基础 | PyCoder 领先 |
| 性能分析 | ✅ 中 (19 规则) | ✅ 强 | ⚠️ 基础 | 需扩展至 30+ |
| 安全审查 | ✅ 强 | ✅ 强 | ⚠️ 基础 | PyCoder 领先 |
| 自进化 | ✅ 独有 | ❌ 无 | ❌ 无 | PyCoder 独有 |
| Agent 团队 | ✅ 14 角色 | ⚠️ 基础 | ⚠️ 基础 | PyCoder 领先 |
| 记忆系统 | ✅ 4 层 | ⚠️ 基础 | ⚠️ 基础 | PyCoder 领先 |
| IDE 集成 | ⚠️ Electron | ✅ VS Code | ✅ VS Code | **主要差距** |
| 开源 | ✅ 完全开源 | ❌ 闭源 | ❌ 闭源 | PyCoder 领先 |

## 六、迭代触发条件

自动触发下一迭代的条件（满足任一即触发）：
1. 新增/修改核心模块代码
2. 测试失败率 > 0
3. Bandit 发现新的 HIGH 严重度问题
4. 覆盖率下降超过 2%
5. 竞品发布新功能

## 七、质量门禁命令速查

```bash
# 本地快速预检查 (commit 前)
python scripts/run.py quality-gate-quick

# 本地全量质量门禁
python scripts/run.py quality-gate

# 仅运行测试
python scripts/run.py test-fast

# 仅 lint
python scripts/run.py lint

# CI 模拟 (本地)
python -m pytest tests/ -m "not slow" --cov=pycoder --cov-fail-under=80
python -m ruff check pycoder/ tests/
python -m bandit -r pycoder/ -ii
```

---

*本文档由 PyCoder 长期迭代机制维护，每次迭代后更新。*

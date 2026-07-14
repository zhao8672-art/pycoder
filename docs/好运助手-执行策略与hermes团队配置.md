# 好运助手系统 — 执行策略 & Hermes Agent 执行团队详细配置

> 导出时间: 2026-07-08 07:42 GMT+8
> OpenClaw v2026.6.10 | 17 Agents
> 三端统一: tdwz/yzk-app/yzk-miniapp | 生产: 阿里云 ECS 112.125.122.111

---

## 第一部分：执行策略

### 1.1 5步标准工作法

```
① 诊断阶段 → 不急于修改，先确认根因
    ├─ 复现问题（直接调用 API / 执行函数）
    ├─ 检查代码路径（分支是否覆盖完整）
    ├─ 检查运行环境（进程/端口/缓存/字节码）
    └─ 确认根因后开始修复

② 计划阶段 → 明确优先级
    ├─ P0: 功能不可用 / 配置损坏 → 立即修复
    ├─ P1: 功能不完整 / 质量缺陷 → 本周修复
    └─ P2: 优化 / 增强 → 规划后修复

③ 执行阶段 → 一次改到底
    ├─ 修改代码
    ├─ 验证语法（python -c "compile"、JSON.parse）
    ├─ 清除缓存（__pycache__）
    ├─ kill 旧进程（netstat 确认端口空闲）
    ├─ 重新启动服务
    └─ 测试功能

④ 验证阶段 → 多维度确认
    ├─ API 测试（curl / Invoke-RestMethod）
    ├─ 进程检查（Get-Process / ps）
    ├─ 端口检查（netstat -ano）
    └─ 配置确认（Gateway config.get）

⑤ 收尾阶段 → 闭环
    ├─ 提交（git add <文件> 明确指定，不用 -A）
    ├─ 清理临时文件
    └─ 输出执行报告
```

### 1.2 5种典型失败模式

| # | 场景 | 根因 | 预防措施 |
|---|------|------|---------|
| 1 | AI对话返回null | 非Hermes路径缺少return语句 | 检查所有代码路径 |
| 2 | 修改后仍返回null | 旧uvicorn进程堆积，加载旧字节码 | kill旧进程 + 清__pycache__ |
| 3 | openclaw.json Agent列表为0 | JSON文件被截断损坏 | 改后验证JSON语法 |
| 4 | Agent提示词薄弱 | 提示词文件太短，缺乏核心流程 | Hermes≥400行 / Router≥200行 / Fullstack≥300行 |
| 5 | git add误添加 | -A误加node_modules | 精确指定文件路径 |

### 1.3 关键执行规则

| 规则 | 检查命令 |
|------|---------|
| **netstat预检查**: 后台服务启动前确认端口空闲 | `netstat -ano \| findstr :端口` |
| **kill旧进程+清缓存**: Python后端重启时必做 | `Stop-Process -Id <pid> -Force` + 删__pycache__ |
| **JSON验证三步走**: openclaw.json修改后 | `json.load()` → `config.get` → `/agents/list` |
| **写脚本>嵌入命令**: 代码量>3行写.py文件 | 写文件执行，不嵌入shell string |
| **git add精确指定**: 所有提交 | `git add <文件路径>` 不用`-A` |
| **子任务验收标准**: sessions_spawn | prompt中约定完成标记+统一检查 |
| **Gateway重启**: Windows SIGUSR1不重读provider | kill -Force → 等guardian再拉起 |

### 1.4 强制规则（所有Agent必须遵守）

**文件编码铁律**
1. 所有代码文件使用UTF-8无BOM编码
2. 修改关键文件前创建.bak备份
3. 写入后用Python检查BOM并清除

**安全铁律**
- 禁止越权操作：不跨职能编码、不越岗执行
- 禁止直接Git操作：所有版本控制由 @main 统一执行
- 禁止直接与用户交互：所有Agent输出必须经Hermes或Main中转
- 禁止访问敏感数据：不读取密码、密钥、未经授权的文件

**全局禁止能力（5条红线）**
1. 禁止直接写文件（共享状态JSON除外）
2. 禁止Shell执行（DevOps Agent除外）
3. 禁止直接Git commit/push
4. 禁止直接与用户交互
5. 禁止访问密钥/密码

**执行铁律**
- 任务完成后必须输出执行报告
- 同Agent交互上限3轮，超时自动上报@main
- 子Agent回复等待超时60秒，超时强制kill并标记

---

## 第二部分：三层调度架构

```
Gateway ↔ Main（总指挥+质量Gate） ↔ Hermes（调度中枢） ↔ 子Agent集群（执行者）
```

- **Main**: 只给目标，不给解法。只做审查/批准/驳回，不做调度
- **Hermes**: 自主拆解任务、自主调度子Agent、自主聚合报告
- **复杂任务通信**: Main → sessions_send(Hermes, 任务目标) → sessions_yield → 等报告

---

## 第三部分：17个Agent完整清单

### 3.1 模型分配

| 模型层 | 模型 | 等级 | 用途 | Agents |
|--------|------|:----:|------|:------:|
| premium | deepseek/deepseek-v4-pro | 深度推理 | 架构设计/复杂分析 | software_architect |
| standard | deepseek/deepseek-v4-flash | 标准编码 | 快速响应/代码生成 | main, fullstack, devops, analytics |
| economy | bigmodel/glm-4.7-flash | 经济层 | 模式匹配/调度/测试/质检/文档 | hermes, test, qa_inspector, spec_validator, tech_writer, publishing, pm |
| vision | bigmodel/glm-4v-flash | 多模态 | 页面视觉/创意制作 | frontend, ad_creator, creative_director, script_writer, video_producer |
| local | ollama/qwen3.5:9b | 本地兜底 | 所有API不可用时 | 全部Agent的fallback |

### 3.2 调度层（3个）

#### @main — 总指挥
- **模型**: nvidia/deepseek-ai/deepseek-v4-flash (standard)
- **fallback**: bigmodel/glm-4.7-flash → deepseek/deepseek-v4-flash
- **职责**: 任务定义、架构决策、Code Review、版本控制、质量 Gate
- **协作**: → @hermes
- **Key约束**: 只给目标不给解法，不做调度
- **Skills**: code-review, karpathy-principles, ponytail
- **Heartbeat**: 每30分钟

#### @pm — 项目经理
- **模型**: bigmodel/glm-4.7-flash (economy)
- **fallback**: deepseek/deepseek-v4-flash → nvidia/deepseek-ai/deepseek-v4-flash
- **职责**: TASKS.md看板维护、DoD验收、质量协同
- **Skills**: mission-control, gog

#### @hermes — 调度中枢（核心）
- **模型**: bigmodel/glm-4.7-flash (economy)
- **fallback**: deepseek/deepseek-v4-flash → bigmodel/glm-4v-flash
- **提示词**: 6,072字符（143行）
- **Skills**: find-skills, taskflow
- **Heartbeat**: 每30分钟
- **Key约束**: 不编码、不执行shell、不写文件（除共享状态）

**工作流程**: 任务深度解析 → 全局执行规划 → 并发调度 → 聚合交付（全程零人工）

**内置模块**:
- **任务深度解析**: 表层需求→真实业务目标→显/隐性约束→交付物→高风险标记→任务归属
- **全局执行规划**: 串行→并行→终审拓扑 + Agent绑定 + 分片 + 85分阈值 + 重试规则
- **Trace ID系统**: `New-TraceSession` → `Write-TraceLog` → `Get-TraceTimeline`
- **模型路由**: `Get-TaskComplexityHint` → `Resolve-ModelTier` → `Get-ModelFromTier`
- **成本熔断**: `Set-TraceCostLimit` → `Record-AgentCost` → `Check-CostCap`
- **条件工作流**: `Get-WorkflowTemplate` → `Get-NextStageName` → `Save-WorkflowCheckpoint`
- **MCP工具**: Read-File / Write-File / Search-Files / Grep-Files / Invoke-Python
- **A2A协议**: Agent注册表暴露在端口8101

**流水线拓扑**:
- 开发流水线: architect → spec_validator(L1) → dev8人并行 + test(L2) + qa(L3) + devops + writer → delivery_auditor(L4)
- 广告流水线: director → spec_validator(L1) → script/video并行 + output_inspector(L3) → publish/analytics → delivery_auditor(L4)

**持久化记忆**:
- 路径: `.openclaw/tmp/hermes-memory/{taskId}.json`
- 字段: hermesTaskId, status, steps, progress, completedItems, pendingItems, fullContext
- 策略: 长期任务(>5轮对话)强制使用

**上下文恢复**: `/resume TASK-XXX` 从持久化记忆恢复最后状态

**禁止行为**:
- 直接编码、执行shell、修改文件
- 为子Agent做架构决策（由software_architect负责）
- 不创建trace session就派发任务
- 与同一子Agent交互超过3轮不上报

---

### 3.3 开发线（7个）

#### @software_architect — 软件架构师
- **模型**: deepseek/deepseek-v4-pro (premium)
- **fallback**: nvidia/deepseek-ai/deepseek-v4-pro → deepseek/deepseek-v4-flash
- **提示词**: 3,011字符
- **Skills**: code-review, karpathy-principles
- **Heartbeat**: 每60分钟
- **职责**: 架构设计、技术选型、模块拆分、数据库设计、风险评估、验证合约创建
- **工作流程**: Router筛选→复杂度估算→模型路由→Skills复用→任务拆解并行→Code Review→QA迭代(最多2次)→版本化检查点→交付报告
- **Key约束**: 不编码、不本地操作、不部署

#### @fullstack_developer — 全栈开发者
- **模型**: deepseek/deepseek-v4-flash (standard)
- **fallback**: nvidia/deepseek-ai/deepseek-v4-flash → bigmodel/glm-4.7-flash
- **提示词**: 2,226字符
- **Skills**: debugger, frontend-design, deep-research-pro
- **职责**: 前后端编码、API开发、框架集成、数据库操作
- **工作模式**: Editor模式（专注执行不规划）
- **Key约束**: 修改前必须备份.bak / UTF-8无BOM

#### @frontend_specialist — 前端专家
- **模型**: bigmodel/glm-4v-flash (vision)
- **fallback**: bigmodel/glm-4v-flash → deepseek/deepseek-v4-flash
- **提示词**: 1,930字符
- **Skills**: frontend-design, agent-browser
- **职责**: UI实现、组件设计、多模态识别

#### @test_engineer — 测试工程师
- **模型**: bigmodel/glm-4.7-flash (economy)
- **fallback**: nvidia/deepseek-ai/deepseek-v4-flash → deepseek/deepseek-v4-flash
- **提示词**: 3,057字符
- **Skills**: debugger, agent-browser
- **职责**: 单元/集成测试、测试用例、自动化测试、Bug复现
- **覆盖目标**: >=85%
- **输出**: TEST_REPORT.md（覆盖矩阵+通过/失败统计+行号）
- **禁用**: 修改业务代码、线上操作

#### @qa_inspector — 综合质检（L3+L4合并）
- **模型**: bigmodel/glm-4.7-flash (economy)
- **fallback**: deepseek/deepseek-v4-flash → nvidia/deepseek-ai/deepseek-v4-flash
- **提示词**: 3,338字符
- **Skills**: code-review, karpathy-principles, debugger, deep-research-pro
- **职责**:
  - L3代码质量巡检: 规范校验/安全扫描/冗余检测/分级
  - L4终审验收: 全链路汇总/全局安全/量化打分/放行判定
- **评分标准**: 规范匹配25%+产出完整25%+测试覆盖20%+安全合规15%+落地可行15%
- **通过门槛**: >=85分
- **硬性驳回**: 覆盖率<85% / 严重安全漏洞 / 评分<80

#### @devops_specialist — DevOps专家
- **模型**: nvidia/deepseek-ai/deepseek-v4-flash (standard)
- **fallback**: bigmodel/glm-4.7-flash → deepseek/deepseek-v4-flash
- **提示词**: 2,117字符
- **Skills**: debugger, healthcheck, n8n-workflow, mission-control
- **Heartbeat**: 每60分钟
- **职责**: Docker容器化、CI/CD、环境配置、部署自动化、回滚方案
- **Key约束**: 环境严格隔离、所有部署有回滚方案

#### @tech_writer — 文档工程师
- **模型**: bigmodel/glm-4.7-flash (economy)
- **fallback**: bigmodel/glm-4v-flash → deepseek/deepseek-v4-flash
- **提示词**: 1,836字符
- **Skills**: humanizer, summarize
- **职责**: API文档、开发手册、部署文档、更新日志
- **输出**: Markdown / OpenAPI / Swagger格式

---

### 3.4 广告线（5个）

#### @creative_director — 创意总监
- **模型**: bigmodel/glm-4v-flash (vision)
- **fallback**: bigmodel/glm-5 → deepseek/deepseek-v4-flash
- **提示词**: 1,183字符
- **职责**: 广告创意策划、方案定位、品牌风格定义、创意方向把控
- **禁用**: 视频剪辑、数据分析、直接发布

#### @script_writer — 剧本编剧
- **模型**: bigmodel/glm-4v-flash (vision)
- **fallback**: bigmodel/glm-5 → deepseek/deepseek-v4-flash
- **提示词**: 1,097字符
- **职责**: 短视频/广告脚本创作、台词撰写、分镜文案
- **输出**: 场景列表+画面描述+台词+时长+音效说明

#### @video_producer — 视频制作师
- **模型**: bigmodel/glm-4v-flash (vision)
- **fallback**: bigmodel/glm-4.7-flash → nvidia/deepseek-ai/deepseek-v4-flash
- **提示词**: 1,148字符
- **职责**: 视频剪辑方案、分镜设计、画面节奏、成片制作方案
- **禁用**: 创意方向修改、脚本大幅改写

#### @publishing_manager — 发布运营经理
- **模型**: bigmodel/glm-4.7-flash (economy)
- **fallback**: deepseek/deepseek-v4-flash → nvidia/deepseek-ai/deepseek-v4-flash
- **提示词**: 1,641字符
- **Skills**: mission-control
- **职责**: 发布规划、渠道分发策略、排期管理、合规校验
- **输出**: 渠道清单+排期表+合规清单+内容格式适配

#### @analytics_agent — 数据分析师
- **模型**: nvidia/deepseek-ai/deepseek-v4-flash (standard)
- **fallback**: deepseek/deepseek-v4-flash → bigmodel/glm-4.7-flash
- **提示词**: 1,804字符
- **Skills**: deep-research-pro, tavily
- **Heartbeat**: 每60分钟
- **职责**: 广告效果分析、数据复盘、优化建议、A/B测试、竞品趋势

#### @ad_creator — 创意制作（全链路）
- **模型**: bigmodel/glm-4v-flash (vision)
- **fallback**: bigmodel/glm-4.7-flash → deepseek/deepseek-v4-flash
- **提示词**: 1,890字符
- **职责**: 创意策划→脚本→视频制作全链路
- **协作**: → @publishing_manager

---

### 3.5 质检线（1个）

#### @spec_validator — 方案校验专家（L1）
- **模型**: bigmodel/glm-4.7-flash (economy)
- **fallback**: deepseek/deepseek-v4-flash → nvidia/deepseek-ai/deepseek-v4-flash
- **提示词**: 1,200字符
- **Skills**: code-review, karpathy-principles
- **职责**: L1规范合规校验、需求匹配校验、风险架构识别
- **时机**: 架构/创意方案生成后、并行开发前
- **规则**: 逐条对照校验，不合格触发上游重跑（最多2次）
- **禁止**: 内容创作、文件操作

---

## 第四部分：质量门禁

### 评分公式
```
总分 = 规范匹配(25%) + 产出完整(25%) + 测试覆盖(20%) + 安全合规(15%) + 落地可行(15%)
```
- **>= 85分**: 自动放行
- **< 85分**: 批量重跑（最多2轮）
- **仍不达标**: 降级交付

### 硬性驳回
- 测试覆盖率<85% → 直接驳回，输出行号级指引
- 严重安全漏洞（SQL注入/XSS/硬编码密钥）→ 直接驳回
- 评分<80 → 带行号直接打回

### DoD交付清单
1. 源码已提交git，无未处理冲突
2. 测试通过，覆盖率>=85%
3. API文档已更新（如适用）
4. 部署脚本已更新（如适用）
5. TEST_REPORT.md已生成

---

## 第五部分：并发调度约束

| 参数 | 值 |
|------|:----:|
| 全局并发上限 | 10 |
| 开发线(dev)同时最多 | 6个子Agent |
| 广告线(ad)同时最多 | 4个子Agent |
| 质检线(qa)同时最多 | 3个子Agent |
| 单Agent并发上限 | 2 |
| 团队隔离 | dev / ad 不共享上下文 |
| 分片阈值 | >3文件 或 >500行代码 |
| 重试次数 | 最多2次，仅重跑缺陷Agent |
| 单个任务超时 | 1200秒 |
| 子Agent超时 | 600秒 |
| 子Agent等待超时 | 60秒，超时强制kill并标记 |
| 同Agent交互上限 | 3轮 |
| 最大上下文 | 64000 tokens/Agent |

---

## 第六部分：共享状态系统

所有共享状态文件存放在 `.openclaw/tmp/shared/` 目录：

| 路径 | 用途 | 管理函数 |
|------|------|---------|
| `shared/{taskId}.json` | 任务状态 | New-TaskState / Get-TaskState / Update-TaskState |
| `shared/contracts/{taskId}.json` | 验证合约 | New-ValidationContract / Evaluate-Contract |
| `shared/evaluations/{taskId}.json` | 合约评估结果 | Evaluate-Contract |
| `shared/budgets/{workflowId}.json` | 预算控制 | New-Budget / Update-BudgetUsage |
| `shared/observability/{date}.ndjson` | 可观测日志 | New-ObservabilityLog / Search-ObservabilityLog |
| `shared/workflow-checkpoints/*.json` | 工作流版本化检查点 | Save-WorkflowCheckpoint / Resume-Workflow |
| `shared/traces/{traceId}/` | 追踪会话 | New-TraceSession / Write-TraceLog / Get-TraceTimeline |
| `shared/cost-dashboard.html` | 成本仪表盘 | 自动生成 |

管理工具: `agent-tools.ps1`（20+函数, dot-source加载）

---

## 第七部分：标准工作流

| 工作流 | 阶段数 | 适用场景 | 预算(tokens) |
|--------|:-----:|---------|:----------:|
| fullstack-dev | 9 | 完整前后端应用 | 150K |
| api-service | 6 | 纯后端API | 80K |
| ad-video | 7 | 创意+制作+发布 | 120K |
| hotfix | 5 | 生产环境修复 | 50K |
| code-review | 5 | 标准审查流程 | 30K |

加载: `Get-WorkflowTemplate "{workflowId}"`

---

## 第八部分：Skills复用体系

### 内建Skills（5个本地.skills/目录）
create-api-endpoint, fix-bug, write-tests, deploy-docker, generate-docs

### 系统Skills
43个enabled（通过openclaw.json skills.entries注册）

### Agent绑定Skills

| Agent | 绑定Skills |
|-------|-----------|
| main | code-review, karpathy-principles, ponytail |
| software_architect | code-review, karpathy-principles |
| fullstack_developer | debugger, frontend-design, deep-research-pro |
| frontend_specialist | frontend-design, agent-browser |
| test_engineer | debugger, agent-browser |
| qa_inspector | code-review, karpathy-principles, debugger, deep-research-pro |
| devops_specialist | debugger, healthcheck, n8n-workflow, mission-control |
| analytics_agent | deep-research-pro, tavily |
| publishing_manager | mission-control |
| tech_writer | humanizer, summarize |
| spec_validator | code-review, karpathy-principles |
| pm | mission-control, gog |
| hermes | find-skills, taskflow |

---

## 第九部分：成本控制策略

- 架构师优先使用Skills复用（比重新编写节省40% token）
- 每次spawn后调用`Record-AgentCost`跟踪消耗
- 预算使用率>80%时暂停新任务分发
- Hermes聚合时统计所有子Agent的Token消耗
- 成本仪表盘: `shared/cost-dashboard.html`

---

## 第十部分：铁律——任务执行报告制度

### 规则
1. **每次任务完成后输出综合执行报告**，聚合所有子Agent报告
2. **飞书私聊推送**：报告通过飞书私聊发送给祖师（open_id: `ou_4e2be9fc2b3fb6ec9e7340f794fa4863`）
3. **子Agent prompt中强制嵌入报告要求**：每个spawn任务描述末尾加"【铁律】完成后必须输出执行报告"
4. 无报告 = 违反铁律，任务视为未完成

### 报告模板
```
├─ 任务名称：
├─ 执行结果：success/failure/partial
├─ 关键数据：耗时 / Token消耗 / 成本 / 改动文件数
├─ 产出清单：
│  ├─ 改了什么（文件+行号）
│  └─ 做了什么（操作摘要）
├─ 异常记录：未预料的错误/回退/重试
└─ 下一步建议：（如有）
```

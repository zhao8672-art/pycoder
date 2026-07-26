# PyCoder API 路径规范

**版本**: v1.0
**生效日期**: 2026-07-26

---

## 一、API 版本策略

PyCoder 采用**双版本并存**策略：
- **V1**: `/api/*` — 稳定版本，向后兼容
- **V2**: `/api/v2/*` — 增强版本，新增能力总线

---

## 二、API 路径分类

### 2.1 核心 API（无版本前缀）

| 路径前缀 | 模块 | 说明 |
|----------|------|------|
| `/api/health` | 健康检查 | 服务存活/就绪检查 |
| `/api/capabilities` | V1 能力 | 旧版能力注册表 |
| `/api/skills` | 技能市场 | 技能安装/管理 |
| `/api/memory` | 记忆系统 | 会话/迭代记忆 |
| `/api/evolution` | 进化引擎 | 自进化闭环 |
| `/api/lifecycle` | 生命周期 | 项目管理闭环 |
| `/api/files` | 文件操作 | 读写/搜索 |
| `/api/code` | 代码执行 | 安全代码执行 |
| `/api/git` | Git 操作 | 版本控制 |
| `/api/chat` | AI 对话 | LLM 交互 |
| `/api/agent` / `/api/agents` | 代理系统 | Agent 调度 |
| `/api/dashboard` | 仪表盘 | 系统状态 |
| `/api/extensions` | 扩展管理 | 插件/扩展 |
| `/api/learning` | 学习系统 | 经验积累 |
| `/api/scheduler` | 调度器 | 定时任务 |
| `/api/context` | 上下文 | 项目上下文 |
| `/api/visualize` | 可视化 | 结构展示 |
| `/api/knowledge` | 知识库 | 知识图谱 |
| `/api/impact` | 影响分析 | 变更影响 |
| `/api/refactor` | 重构 | 代码重构 |
| `/api/recommendations` | 推荐 | 智能推荐 |
| `/api/security` | 安全 | 安全检查 |
| `/api/autonomous` | 自主执行 | 自主任务 |
| `/api/dag` | DAG | 任务编排 |
| `/api/workspaces` | 工作区 | 多工作区 |
| `/api/browser` | 浏览器AI | 浏览器集成 |
| `/api/cloud` | 云服务 | 云端能力 |
| `/api/gateway` | 网关 | API 网关 |
| `/api/env` | 环境 | 环境变量 |
| `/api/dependencies` | 依赖 | 依赖分析 |
| `/api/file-transfer` | 文件传输 | 大文件传输 |
| `/api/permissions` | 权限 | 权限管理 |
| `/api/guard` | 守护 | 守护进程 |
| `/api/format` | 格式化 | 代码格式化 |
| `/api/diff` | 差异 | 代码差异 |
| `/api/diff-list` | 差异列表 | 差异列表 |
| `/api/rules` | 规则 | 规则引擎 |
| `/api/debug` | 调试 | 调试工具 |
| `/api/tasks` | 任务 | 任务管理 |
| `/api/sessions` | 会话 | 会话管理 |
| `/api/reports` | 报告 | 报告生成 |
| `/api/models` | 模型 | AI 模型 |

### 2.2 V2 API（推荐使用）

| 路径前缀 | 模块 | 说明 |
|----------|------|------|
| `/api/v2/capabilities` | V2 能力总线 | 192 个能力（统一管理） |
| `/api/v2/evolution` | V2 进化 | 增强进化引擎 |
| `/api/v2/evolution/core` | 进化核心 | 核心进化逻辑 |
| `/api/v2/skills` | V2 技能 | 技能市场 V2 |
| `/api/v2/pipeline` | 管道 | 进化/AI 管道 |
| `/api/v2/trust` | 信任级别 | 信任度管理 |
| `/api/v2/lifecycle` | V2 生命周期 | 增强版 |
| `/api/v2/status` | 系统状态 | V2 状态 |
| `/api/v2/stats` | 统计信息 | V2 统计 |
| `/api/v2/health` | 健康检查 | V2 健康 |
| `/api/v2/shared` | 共享数据 | 跨模块共享 |

---

## 三、认证规范

所有 V2 API 端点必须使用 API Key 认证：
```http
X-API-Key: <your-api-key>
```

**API Key 获取**：
- 环境变量：`PYCODER_API_KEY`
- 配置文件：`~/.pycoder/.api_key`
- 临时模式：服务启动时自动生成（保存在 `~/.pycoder/.api_key`）

---

## 四、错误响应格式

### 4.1 标准错误响应

```json
{
  "success": false,
  "error": {
    "code": "ERR_CODE",
    "message": "人类可读的错误描述",
    "details": { /* 可选 */ },
    "request_id": "uuid"
  },
  "timestamp": "2026-07-26T10:00:00Z"
}
```

### 4.2 标准成功响应

```json
{
  "success": true,
  "data": { /* 实际数据 */ },
  "timestamp": "2026-07-26T10:00:00Z"
}
```

### 4.3 HTTP 状态码规范

| 状态码 | 含义 | 使用场景 |
|--------|------|----------|
| 200 | OK | 成功 |
| 201 | Created | 资源创建成功 |
| 204 | No Content | 成功无返回体 |
| 400 | Bad Request | 请求参数错误 |
| 401 | Unauthorized | 缺少/无效认证 |
| 403 | Forbidden | 权限不足 |
| 404 | Not Found | 资源不存在 |
| 409 | Conflict | 资源冲突 |
| 422 | Unprocessable | 数据验证失败 |
| 429 | Too Many | 限流 |
| 500 | Internal | 服务错误 |
| 503 | Service Unavailable | 服务暂不可用 |

---

## 五、API 文档

- **OpenAPI 文档**: `GET /openapi.json`
- **Swagger UI**: `GET /docs` (待集成)
- **ReDoc**: `GET /redoc` (待集成)

---

## 六、迁移指南

### 6.1 V1 → V2 迁移

| V1 路径 | V2 路径 | 状态 |
|---------|---------|------|
| `/api/capabilities` | `/api/v2/capabilities` | 推荐迁移 |
| `/api/evolution/status` | `/api/v2/evolution/core/status` | 推荐迁移 |
| `/api/skills` | `/api/v2/skills` | 推荐迁移 |
| `/api/agent/status` | `/api/v2/pipeline/stats` | 推荐迁移 |

### 6.2 向后兼容原则

- V1 API 至少保留 6 个月
- 重大变更通过 API Key 白名单控制
- 弃用 API 在响应头添加 `Deprecation` 警告

---

## 七、API 命名约定

### 7.1 资源命名
- 使用复数名词：`/api/skills`、`/api/sessions`
- 嵌套资源：`/api/skills/{id}/reviews`
- 避免动词：使用 HTTP 方法表达动作

### 7.2 HTTP 方法
- `GET`: 获取资源
- `POST`: 创建资源
- `PUT`: 全量更新
- `PATCH`: 部分更新
- `DELETE`: 删除资源

### 7.3 查询参数
- 使用 snake_case：`?user_id=xxx&limit=10`
- 分页参数：`offset` + `limit`
- 过滤参数：`filter_field=value`

---

## 八、限流策略

| 端点类型 | 限制 |
|----------|------|
| 公共端点 | 100 req/min |
| 写入端点 | 30 req/min |
| AI 端点 | 10 req/min |
| 管理端点 | 60 req/min |

超出限流返回 HTTP 429。

---

## 九、安全规范

1. **所有 API 必须认证**（除 `/api/health`）
2. **路径遍历防护**：所有文件操作必须验证路径
3. **输入验证**：使用 Pydantic 模型验证请求体
4. **SQL 注入防护**：使用参数化查询
5. **CORS**：生产环境限制允许来源
6. **审计日志**：所有写操作记录审计日志

---

## 十、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0 | 2026-07-26 | 初始版本，定义 API 规范 |

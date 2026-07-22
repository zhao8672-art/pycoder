# PyCoder 应用测试计划

> 测试日期: 2026-07-22
> 测试版本: 0.5.0
> 测试环境: Windows 11 / Python 3.14.3 / FastAPI + Electron 32
> 测试执行: AI Test Engineer

## 1. 测试目标

全面验证 PyCoder 桌面 AI 编程助手的质量，覆盖：
- 功能正确性（核心 API 模块）
- 性能指标（响应时间、并发能力）
- 兼容性（不同客户端环境）
- 安全性（认证、注入、越权）

## 2. 测试范围

### 2.1 已识别的业务域（共 11 大类，300+ 端点）

| 业务域 | 端点示例 | 测试优先级 |
|---|---|---|
| 健康检查 | /api/health | P0 |
| 模型管理 | /api/models, /api/model/select | P0 |
| 会话管理 | /api/sessions, /api/chat | P0 |
| 文件操作 | /api/files/* | P0 |
| Git 集成 | /api/git/* | P0 |
| 代码执行 | /api/code/exec | P0 |
| 扩展管理 | /api/extensions/* | P1 |
| 技能系统 | /api/skills/* | P1 |
| 自主代理 | /api/autonomous/* | P1 |
| 沙箱执行 | /api/sandbox/* | P1 |
| 自演化 | /api/v2/evolution/* | P2 |

### 2.2 测试排除范围

- 外部 API 调用（DeepSeek、Agnes 等需要真实 API Key）
- 需要付费的服务（GitHub API）
- 真实浏览器/文件系统的破坏性操作

## 3. 测试策略

### 3.1 功能测试
- 黑盒测试，按业务域分组
- 验证 HTTP 状态码、响应内容、参数校验
- 错误处理路径覆盖

### 3.2 性能测试
- 单端点响应时间（10 次取 P50/P95/P99）
- 并发能力（10/50/100 并发）
- 内存占用监控
- 慢请求检测

### 3.3 兼容性测试
- HTTP 方法：GET / POST / PUT / DELETE
- 错误响应格式：JSON / 状态码
- 跨域 CORS 处理
- 大文件/大数据量处理

### 3.4 安全性测试
- API Key 认证绕过测试
- 路径遍历攻击
- SQL 注入
- XSS 攻击载荷
- 限流测试
- 输入验证

## 4. 通过标准

| 维度 | 标准 |
|---|---|
| 功能 | 核心 API 通过率 ≥ 95% |
| 性能 | P95 响应时间 < 1000ms |
| 兼容 | 错误格式一致性 100% |
| 安全 | 无 Critical 级别漏洞 |

## 5. 测试工具

- PowerShell (Invoke-WebRequest) — 主测试
- Python (asyncio) — 并发测试
- 自研测试脚本 — 综合测试

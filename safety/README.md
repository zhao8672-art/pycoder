# PyCoder Safety / Sandbox Module

PyCoder 的安全代码执行沙箱在 `pycoder/safety/` 子包中, **不**在仓库根.

## 真实位置

| 文件 | 用途 | 大小 |
|------|------|------|
| `pycoder/safety/sandbox.py` | 沙箱抽象层 + Docker 适配 | 11 KB |
| `pycoder/safety/sandbox_executor.py` | 沙箱执行器 (40 KB 完整实现) | 41 KB |
| `pycoder/safety/permission.py` | 权限系统 (用户/角色/能力) | 19 KB |
| `pycoder/safety/audit.py` | 审计日志 | 11 KB |
| `pycoder/safety/circuit_breaker.py` | 熔断器 | 8 KB |
| `pycoder/safety/rollback.py` | 操作回滚 | 7 KB |

## Docker 集成

- Docker 可用时: `pycoder/adapters/sandbox_selector.py` 自动选择 Docker 沙箱
- 不可用时: 降级到 subprocess + resource limits
- 配置文件: `docker-compose.yml` (仓库根) ← Docker 编排
- 镜像环境变量: `PYCODER_DOCKER_IMAGE` (默认 `python:3.12-slim`)

## API 端点

- `GET  /api/sandbox/status` — 当前沙箱状态 (Docker / Subprocess)
- `GET  /api/sandbox/check-docker` — 检查 Docker 可用性
- `POST /api/sandbox/execute` — 在沙箱中执行代码
- `POST /api/sandbox/select` — 手动选择沙箱后端

# PyCoder Observability / Sentry Module

PyCoder 的错误监控系统在 `pycoder/observability/` 子包中, **不**在仓库根.

## 真实位置

| 文件 | 用途 | 大小 |
|------|------|------|
| `pycoder/observability/sentry.py` | Sentry 集成 (条件加载 + 5 API) | 7 KB |
| `pycoder/observability/__init__.py` | 模块导出 | 1 KB |

## 依赖

```toml
# requirements.txt / requirements.in (已声明)
sentry-sdk[fastapi,httpx]~=2.10.0
```

## API

- `init_sentry(dsn=..., environment=...)` — 初始化 (无 DSN 时静默返回 False)
- `capture_exception(exc, **context)` — 捕获异常
- `capture_message(msg, level)` — 捕获消息事件
- `set_user(user_id, **attrs)` — 设置用户上下文
- `set_context(name, data)` — 设置请求上下文
- `add_breadcrumb(category, message, **data)` — 添加面包屑

## 启用方法

```bash
# 1. 安装依赖
pip install 'sentry-sdk[fastapi,httpx]>=2.10.0'

# 2. 设置 DSN (从 sentry.io 项目设置获取)
export SENTRY_DSN=https://xxx@sentry.io/123

# 3. 在应用启动时调用
from pycoder.observability import init_sentry
init_sentry()  # 自动读取 SENTRY_DSN

# 4. 验证
from pycoder.observability import status
print(status())
# {'available': True, 'initialized': True, ...}
```

## 默认行为

**未设置 SENTRY_DSN 时**: init_sentry() 静默返回 False, 不会发送任何数据, 也不会产生网络调用. 这是"开箱即用零开销"的设计.

# PyCoder Memory Module

PyCoder 的持久化记忆系统在 `pycoder/memory/` 子包中, **不**在仓库根目录 (为了符合 PEP 328 命名空间包规范).

## 真实位置

| 文件 | 用途 | 大小 |
|------|------|------|
| `pycoder/memory/deep_memory.py` | 长期记忆 + 向量检索 (chroma/sqlite) | 71 KB |
| `pycoder/memory/persistent_memory.py` | 跨会话持久化 (用户偏好/历史) | 15 KB |
| `pycoder/memory/session_memory.py` | 会话级记忆 | 11 KB |
| `pycoder/memory/__init__.py` | 模块导出 | 5 KB |

## 数据库依赖

```toml
# pyproject.toml [project.dependencies] (经 requirements.txt 自动同步)
sqlite3   # 内置, 无需安装
aiosqlite # 异步 SQLite
```

## API 端点

- `GET  /api/memory/sessions` — 列出所有会话
- `GET  /api/memory/session/{id}` — 读取会话记忆
- `POST /api/memory/search` — 向量检索 (查询最相关的历史片段)

## 验证 (一次性)

```python
from pycoder.memory import deep_memory, persistent_memory
print(deep_memory.__file__)   # 确认模块真实加载
print(persistent_memory.__file__)
```

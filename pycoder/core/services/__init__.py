"""P2-D: 核心基础服务层 — 跨层共享的通用服务

将原 `pycoder/server/services/` 中的基础设施服务（无业务逻辑、无 HTTP 依赖）
下沉到 core 层，解决 brain/capabilities/ai 等层对 server 层的非法依赖。

设计原则:
  - 仅包含纯 Python 基础设施（无 FastAPI/HTTP 依赖）
  - 不依赖任何业务层模块
  - 可被任意上层模块引用

迁移清单:
  - task_grader.py: 任务难度自适应分级（原 server/services/task_grader.py）
  - audit_logger.py: 全链路审计日志（原 server/services/audit_logger.py）
"""

from __future__ import annotations

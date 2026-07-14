"""P1-4: Clean Architecture 核心层 — 业务逻辑接口定义

本包定义核心业务的抽象接口（Port / Protocol），不依赖任何具体实现。

依赖方向（Clean Architecture）：
    interfaces (API/WebSocket) → core ← external (LLM/Storage/Sandbox)

子模块：
    ports/       — 核心接口定义（Protocol）
    adapters/    — 具体适配器实现（依赖外部库）

迁移策略：
- 现有代码不强制迁移，继续工作
- 新代码应优先依赖 core.ports 中的接口，而非具体实现
- 路由层可通过 FastAPI Depends() 注入接口实现
"""

from __future__ import annotations

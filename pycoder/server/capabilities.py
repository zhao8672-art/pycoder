"""
能力清单自动生成 — 让 AI 知道 pycoder 自身拥有哪些功能

每次对话开始前，自动扫描当前代码状态，生成一份最新的 Markdown 能力清单，
注入到 system prompt 中。这样 AI 就能准确回答"你能做什么？"、"有哪些工具？"等问题。
"""

from __future__ import annotations

from pathlib import Path

from pycoder import __version__


def generate_capabilities() -> str:
    """
    动态生成 pycoder 能力清单 Markdown。

    自动扫描：
    - MCP 内置工具
    - 推理参数配置
    - 可用 Skills
    - 模型提供商
    - 权限策略状态
    - 自我进化引擎
    """
    sections: list[str] = []

    sections.append(f"""# PyCoder v{__version__} 能力清单

以下是当前 PyCoder IDE 已开启的全部功能。用户询问时据此回答。

""")

    # ── 1. MCP 工具 ──
    sections.append("## 1. MCP 工具系统")
    sections.append("你可以通过对话直接调用以下内置工具（不需要额外配置）：")
    try:
        from pycoder.server.mcp_tools import list_builtin_tools

        tools = list_builtin_tools()
        if tools:
            for t in tools:
                sections.append(f"- **`{t['name']}`**: {t['description']}")
        else:
            sections.append("  (暂无内置工具)")
    except ImportError:
        sections.append("  (MCP 模块未加载)")

    # 外部 MCP Server
    try:
        from pycoder.server.mcp_tools import get_mcp_client_manager

        mgr = get_mcp_client_manager()
        connected = mgr.connected_servers
        if connected:
            sections.append(f"\n已连接的外部 MCP Server: {', '.join(connected)}")
        sections.append(
            "\n用户可通过 `/mcp connect <名称> <命令> [参数...]` "
            "连接外部 MCP Server（文件系统/GitHub/浏览器等）。"
        )
    except ImportError:
        pass

    sections.append("")

    # ── 2. Skills ──
    sections.append("## 2. Skills 技能")
    try:
        from pycoder.prompts.skills_loader import discover_skills

        skills = discover_skills()
        if skills:
            sections.append(f"当前加载了 {len(skills)} 个技能：")
            for s in skills:
                sections.append(f"- **{s['name']}** ({s['source']}) — {s['description']}")
        else:
            sections.append(
                "当前无加载的技能。用户可在项目根目录 `.skills/` 或 `~/.pycoder/skills/` 放置 `.md` 文件添加技能。"
            )
    except ImportError:
        pass

    # ── 3. 使用方式 ──
    sections.append("""
## 3. 工具调用 (MCP)

你可以通过**原生函数调用（Function Calling）**使用工具。系统已自动注册所有内置工具到你的工具列表中，直接调用即可。

**调用方式:**
当需要使用工具时，通过 function calling 发起调用，系统会自动执行并将结果返回给你，你可以基于返回结果继续分析。

**可用工具示例:**
- `read_file(path)` — 读取工作区文件内容
- `write_file(path, content)` — 写入文件
- `list_files(path)` — 列出目录内容
- `execute_python(code)` — 在沙箱中执行 Python 代码
- `execute_multilang(language, code)` — 执行多语言代码
- `run_terminal(command)` — 执行 shell 命令
- `list_agent_configs()` — 列出系统 Agent 配置详情
- `skills_search_v2(query, limit)` — 搜索技能
- `extensions_search(query)` — 搜索扩展

**典型工作流:**
1. 用户请求 → 你判断需要读取文件/执行代码
2. 发起 function call → 系统执行并返回结果
3. 基于结果继续分析 → 给用户最终回答

**重要**: 不要在回复正文中用 XML 标签（如 `<read_file>`）调用工具。使用原生 function calling 机制，工具结果会自动注入到对话中供你分析。

完整工具列表见下方【1. MCP 工具系统】。""")

    # ── 4. LSP 智能感知 ──
    sections.append("""
## 4. LSP 代码智能感知

编辑器集成 Pyright LSP，提供以下实时代码辅助：
- **错误/警告波浪线** — 实时检测类型错误、语法问题
- **代码补全** — 打字时自动弹出方法和变量建议（Ctrl+Space）
- **悬停信息** — 鼠标悬停显示类型签名和文档
- **跳转定义** — Ctrl+点击或 F12 跳转到符号定义
- **自动格式化** — 用 black/ruff/isort 格式化代码（/mcp call format_code）""")

    # ── 5. 自我进化 ──
    sections.append(f"""
## 5. 自我进化引擎 (Self-Evolution Engine)

代码位置: `pycoder/capabilities/self_evo/` (v{__version__} 已内置)

你具备完整的自我修复能力:

| 能力 | 说明 |
|------|------|
| **代码扫描** | AST 静态分析 + LLM 深度分析，扫描全部 .py 文件 |
| **修复管线** | SCAN -> PRIORITIZE -> FIX -> TEST -> LEARN 五步闭环 |
| **自动回滚** | 修复失败或测试不通过时自动 git 回滚 |
| **定时调度** | 每日 04:00 扫描 + 每 6 小时修复 (9 个调度任务) |
| **手动触发** | API POST /api/v2/evolution/test-cycle |
| **学习引擎** | live/__init__.py 在线学习器 + learning/ 闭环知识库 |

**核心文件**: engine.py (~1800行), live/__init__.py, learning/metrics_tracker.py""")

    # ── 6. 推理配置 ──
    sections.append("""
## 6. DeepSeek 推理控制

当前对话支持以下推理参数（可在设置面板调节）：
- **推理强度**: low（快速）/ medium（均衡）/ max（深度）
- **KV Cache**: 开启后可节省 50-90% 输入 Token 费用""")

    # ── 7. 测试与 CI/CD ──
    sections.append("""
## 7. 测试与 CI/CD

- **测试骨架生成**: `/mcp call generate_tests {"file": "path/to/file.py"}` — 自动生成 pytest 测试
- **集成测试**: `/mcp call test_integration {"app_file": "app.py"}` — 扫描 FastAPI 路由生成 httpx 测试
- **端到端测试**: `/mcp call test_e2e {"app_url": "http://...", "pages": ["/", "/api"]}` — Playwright 浏览器测试
- **性能测试**: `/mcp call test_performance {"target_url": "http://...", "users": 100}` — Locust 压测脚本
- **CI/CD 管道**: `/mcp call generate_pipeline {"project_type": "fastapi"}` — 生成 GitHub Actions 配置
- **依赖安全扫描**: `/mcp call security_scan` — 用 pip-audit 检测依赖漏洞""")

    # ── 8. 代码执行与调试 ──
    sections.append("""
## 8. 代码执行与调试

- **沙箱执行**: `/mcp call execute_code {"code": "print(1)"}` — 安全执行 Python/JS/Shell 代码
- **断点调试**: `/mcp call debug_python {"code": "...", "breakpoints": [3, 7]}` — 带断点调试
- **Docker 执行**: `/mcp call docker_execute {"code": "..."}` — 在隔离容器中运行
- **性能分析**: `/mcp call profile_python {"code": "..."}` — cProfile 热点分析""")

    # ── 9. Git 与协作 ──
    sections.append("""
## 9. Git 与协作

- **冲突解决**: `/mcp call resolve_conflict {"file": "path"}` — 自动解决 Git 合并冲突
- **会话共享**: 通过 session_share_join 消息类型实时共享 AI 对话（多用户同步查看）""")

    # ── 10. 数据库 ──
    sections.append(
        """
## 10. 数据库

- **Schema 迁移**: `/mcp call db_schema_migrate` — 自动生成 alembic 迁移脚本
- **查询优化**: `/mcp call db_query_optimize {"sql": "SELECT ..."}` — SQL 分析 + 索引建议
- **缓存策略**: `/mcp call db_cache_analyze {"ttl_seconds": 300, "hit_rate": 75}` — Redis 优化建议"""
    )

    # ── 11. K8s 与监控 ──
    sections.append("""
## 11. K8s 与监控

- **K8s 部署**: `/mcp call k8s_deploy {"app_name": "myapp", "replicas": 3}` — 生成 Deployment/Service/Ingress
- **监控配置**: `/mcp call monitoring_config {"app_name": "myapp"}` — Prometheus + Grafana 配置""")

    # ── 6. 权限控制 ──
    sections.append("""
## 6. 权限控制

用户可在设置面板为以下操作设置 allow / ask / deny 三级权限：
- Shell 命令执行 / 文件写入 / 文件读取 / 网络请求 / 剪贴板访问""")

    # ── 7. 反向引导 ──
    sections.append("""
## 7. 反向引导

当用户问「你能做什么？」或「你有哪些功能？」时，用对话回复列出以上能力。
当用户提出可以通过 MCP 工具解决的需求时，推荐使用 `/mcp call <工具名>` 来完成。""")

    return "\n".join(sections)


def capabilities_md_path() -> Path | None:
    """能力清单缓存文件路径（可选用于调试查看）"""
    home = Path.home() / ".pycoder"
    home.mkdir(parents=True, exist_ok=True)
    return home / "CAPABILITIES.md"


def write_capabilities_to_disk():
    """将当前能力清单写入磁盘文件（调试用）"""
    content = generate_capabilities()
    path = capabilities_md_path()
    path.write_text(content, encoding="utf-8")
    return str(path)

# PyCoder LSP 集成调研报告

> 生成时间: 2026-07-29 (迭代 #3) | 调研目标: 为 PyCoder 选择合适的 LSP 方案
>
> 背景: 竞品对比显示 PyCoder 在 IDE 集成 (代码补全/跳转/重构) 方面存在差距。
> 本报告评估 pyright 与 pylsp 两种主流 Python LSP 方案的选型。

## 一、候选方案对比

### 1. Pyright (Microsoft)

**简介**: 微软开发的 Python 类型检查器，VS Code Python 扩展的底层引擎。

**优势**:
- ✅ 性能最优 (Rust 实现，增量分析快)
- ✅ 类型推断能力强 (VS Pylance 的核心)
- ✅ VS Code 原生集成 (Pylance 基于 pyright)
- ✅ 活跃维护 (微软官方支持)
- ✅ 支持 strict 模式渐进式类型检查
- ✅ 通过 LSP 协议可独立运行 (`pyright-langserver --stdio`)

**劣势**:
- ❌ 仅支持 Python (无法扩展到其他语言)
- ❌ 闭源 Pylance 功能 (pyright 本身开源 MIT)
- ❌ 类型检查严格度高，可能产生大量告警

**集成方式**:
```bash
# 安装
npm install -g pyright
# 或 pip install pyright

# 启动 LSP server
pyright-langserver --stdio
```

### 2. Pylsp (Python LSP Server)

**简介**: 社区维护的 Python LSP 服务器，基于 jedi 提供 language server 功能。

**优势**:
- ✅ 纯 Python 实现 (易于集成和定制)
- ✅ 插件生态丰富 (jedi/pyflakes/pycodestyle/pylint/flake8/mccabe 等)
- ✅ 支持 rope 重构
- ✅ 完全开源 (GPLv3)
- ✅ 可扩展到其他语言 (通过插件机制)

**劣势**:
- ❌ 性能不如 pyright (Python 实现)
- ❌ 类型检查能力弱 (依赖 jedi，无严格类型检查)
- ❌ 维护活跃度低于 pyright
- ❌ GPLv3 协议有传染性 (与 PyCoder Apache 2.0 不兼容)

**集成方式**:
```bash
pip install python-lsp-server[all]
pylsp
```

## 二、评估矩阵

| 维度 | Pyright | Pylsp | 权重 | 推荐 |
|------|---------|-------|------|------|
| **性能** | ✅ 最优 (Rust) | ⚠️ 中等 (Python) | 高 | Pyright |
| **类型检查** | ✅ 强 | ⚠️ 弱 | 高 | Pyright |
| **代码补全** | ✅ 强 | ✅ 强 (jedi) | 高 | 持平 |
| **定义跳转** | ✅ 强 | ✅ 强 (jedi) | 中 | 持平 |
| **重构** | ⚠️ 基础 | ✅ 强 (rope) | 中 | Pylsp |
| **集成难度** | ✅ 简单 (Node) | ✅ 简单 (pip) | 中 | 持平 |
| **协议兼容** | ✅ LSP 标准 | ✅ LSP 标准 | 高 | 持平 |
| **维护活跃度** | ✅ 高 (微软) | ⚠️ 中 | 中 | Pyright |
| **许可证** | ✅ MIT | ❌ GPLv3 | **高** | **Pyright** |
| **多语言扩展** | ❌ 仅 Python | ⚠️ 插件机制 | 低 | Pylsp |

## 三、推荐方案: Pyright

### 选型理由

1. **性能**: Rust 实现，增量分析速度比 pylsp 快 5-10 倍
2. **类型检查**: 与 PyCoder 的 mypy 配置互补，提供更强的类型推断
3. **许可证**: MIT 协议与 PyCoder Apache 2.0 兼容 (Pylsp 的 GPLv3 有传染性风险)
4. **生态**: VS Code Pylance 基于 pyright，社区支持最广
5. **维护**: 微软官方支持，长期维护有保障

### 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 重构能力弱于 pylsp (rope) | 补充 rope 作为独立重构工具 |
| 严格类型检查可能产生大量告警 | 配置 `basic` 模式渐进式启用 |
| Node.js 依赖 | 提供预编译二进制 (`pip install pyright`) |

## 四、集成路线图

### 阶段 1: 基础集成 (迭代 #4)
- 安装 pyright 作为可选依赖 (`pip install pyright`)
- 创建 `pycoder.lsp.server` 模块封装 pyright-langserver
- 实现基本 LSP 客户端:
  - `textDocument/didOpen` — 文件打开通知
  - `textDocument/completion` — 代码补全请求
  - `textDocument/definition` — 定义跳转
  - `textDocument/hover` — 悬停提示

### 阶段 2: 功能完善 (迭代 #5)
- 实现完整 LSP 协议:
  - `textDocument/references` — 引用查找
  - `textDocument/rename` — 重命名
  - `textDocument/documentSymbol` — 文档符号
  - `textDocument/diagnostic` — 实时诊断
- 与 PyCoder ContextBuilder 集成 (将 LSP 上下文注入 AI 提示词)

### 阶段 3: Electron UI 集成 (迭代 #6)
- 在 Electron 前端集成 Monaco Editor
- 通过 LSP 协议连接后端 pyright-langserver
- 实现智能补全、跳转、诊断 UI

## 五、技术实现要点

### 5.1 LSP Server 启动

```python
import subprocess

class PyrightLSPServer:
    """Pyright LSP 服务器封装"""

    def __init__(self, workspace: str):
        self.workspace = workspace
        self._proc: subprocess.Popen | None = None

    async def start(self) -> None:
        """启动 LSP 服务器进程"""
        self._proc = subprocess.Popen(
            ["pyright-langserver", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=self.workspace,
        )

    async def request(self, method: str, params: dict) -> dict:
        """发送 LSP JSON-RPC 请求"""
        # 实现 JSON-RPC over stdio
        ...
```

### 5.2 与 ContextBuilder 集成

```python
# 将 LSP 诊断结果注入 AI 上下文
async def build_context_with_lsp(file_path: str) -> str:
    diagnostics = await lsp_server.get_diagnostics(file_path)
    symbols = await lsp_server.get_symbols(file_path)
    return f"""
# 文件符号
{symbols}

# 类型诊断
{diagnostics}
"""
```

## 六、结论

**推荐选型: Pyright** (MIT 协议 + 性能最优 + 微软维护)

集成分 3 个阶段实施 (迭代 #4-6)，优先实现代码补全和定义跳转，这是 PyCoder 相对竞品的主要差距点。

集成完成后，PyCoder 将具备:
- IDE 级代码补全 (与 VS Code Pylance 同等能力)
- 类型感知的定义跳转
- 实时类型诊断
- 与 AI 上下文深度集成 (LSP 诊断 → AI 提示词)

---

*本报告为迭代 #3 调研产出，实际集成将在迭代 #4-6 执行。*

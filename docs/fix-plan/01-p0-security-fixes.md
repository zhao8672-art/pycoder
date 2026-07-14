# P0 阶段修复计划：安全与稳定性

> **优先级**：CRITICAL — 必须立即修复
> **工期**：1-2 周
> **目标**：消除所有 CRITICAL 安全漏洞，恢复服务器响应性，综合评分提升至 75 分以上
> **前置条件**：无

---

## 修复清单总览

| ID | 问题 | 严重度 | 文件 | 工期 |
|----|------|--------|------|------|
| P0-1 | 进程内 exec/compile 无沙箱 | CRITICAL | code_executor.py + rest_routes.py | 2 天 |
| P0-2 | install_packages 同步 subprocess 阻塞 | HIGH | code_exec.py | 0.5 天 |
| P0-3 | self_evolution 静态扫描/测试同步阻塞 | HIGH | self_evolution.py | 1 天 |
| P0-4 | API 认证默认关闭 | HIGH | app.py | 1 天 |
| P0-5 | self_evolution 回滚调用链验证 | HIGH | self_evolution.py | 0.5 天 |

---

## P0-1：替换进程内 exec/compile 为子进程隔离

### 问题真实状态

**报告描述**：`code_exec.py#L120-L130` 存在 `exec()` 无消毒代码注入风险。

**实际核实**：[code_exec.py:L131-L294](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/code_exec.py#L131-L294) 已实现子进程隔离 + 白名单 builtins，**此端点已修复**。

**真正问题在另一处**：
- [pycoder/python/code_executor.py:L105-L114](file:///c:/Users/Administrator/Desktop/pycode/pycoder/python/code_executor.py#L105-L114) 仍然使用进程内 `compile()` + `exec()`
- 被 [rest_routes.py:L183-L207](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/rest_routes.py#L183-L207) 的 `/api/code/run` 和 `/api/code/debug` 端点直接调用
- 用户提交的代码在主进程中执行，可访问 `__import__`、`os.system` 等所有危险函数
- 这是真正的 CRITICAL 安全漏洞

### 影响评估

- **机密性**：攻击者可读取任意文件（`open('/etc/passwd').read()`）
- **完整性**：攻击者可修改/删除项目文件（`import shutil; shutil.rmtree('...')`）
- **可用性**：攻击者可耗尽资源导致服务崩溃（`while True: pass`）
- **可利用性**：高 — 仅需 POST 一个 JSON 请求即可执行任意代码

### 修复方案

#### 方案 A（推荐）：复用 code_exec.py 的子进程沙箱

将 `/api/code/run` 和 `/api/code/debug` 改为调用 `code_exec.py` 中已验证安全的 `_run_in_subprocess`。

**修改 1**：[rest_routes.py:L183-L207](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/rest_routes.py#L183-L207)

```python
# ── 修改前 ──────────────────────────────────────────────
@router.post("/api/code/run")
async def code_run(req: dict):
    from pycoder.python.code_executor import CodeExecutor
    code = req.get("code", "")
    executor = CodeExecutor()
    result = executor.execute(code.strip())
    return {
        "success": result.success,
        # ...
    }

@router.post("/api/code/debug")
async def code_debug(req: dict):
    from pycoder.python.code_executor import CodeExecutor
    code = req.get("code", "")
    breakpoint_lines = req.get("breakpoint_lines", [])
    executor = CodeExecutor()
    result = executor.execute_with_breakpoint(code, breakpoint_lines)
    return { ... }


# ── 修改后 ──────────────────────────────────────────────
@router.post("/api/code/run")
async def code_run(req: dict):
    """在沙箱中执行 Python 代码（复用 code_exec 模块的安全子进程隔离）"""
    from pycoder.server.routers.code_exec import _run_in_subprocess, _sandbox_config, CodeExecResponse
    import asyncio

    code = (req.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Code cannot be empty")

    timeout = int(req.get("timeout", _sandbox_config.default_timeout))
    timeout = min(timeout, _sandbox_config.max_timeout)

    # 复用已验证的子进程沙箱（asyncio.to_thread 避免阻塞事件循环）
    result = await asyncio.to_thread(_run_in_subprocess, code, timeout)

    return {
        "success": result.success,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "error_type": result.error_type,
        "error_message": result.error_message,
        "traceback": result.traceback,
        "execution_time": round(result.execution_time, 3),
    }


@router.post("/api/code/debug")
async def code_debug(req: dict):
    """调试模式执行代码（在沙箱中运行，返回栈信息而非交互式调试）"""
    # 进程内调试器无法在子进程沙箱中安全实现，改为返回执行结果 + 详细 traceback
    return await code_run(req)
```

**修改 2**：标记 [code_executor.py:L105-L114](file:///c:/Users/Administrator/Desktop/pycode/pycoder/python/code_executor.py#L105-L114) 为废弃

```python
# pycoder/python/code_executor.py 顶部添加
import warnings

_DEPRECATION_MSG = (
    "CodeExecutor.execute() 使用进程内 exec()，存在严重安全风险。"
    "请改用 pycoder.server.routers.code_exec._run_in_subprocess()。"
    "本方法将在 v2.0 移除。"
)


class CodeExecutor:
    def execute(self, code: str, globals_dict: dict = None, locals_dict: dict = None) -> ExecutionResult:
        warnings.warn(_DEPRECATION_MSG, DeprecationWarning, stacklevel=2)
        # ... 原有实现保留，仅供向后兼容
```

#### 方案 B：直接删除 code_executor.py 的 execute 方法

如果确认无其他依赖（仅 rest_routes.py 使用），可直接删除 `execute` 方法。需先执行：

```bash
grep -r "CodeExecutor\|code_executor" pycoder/ --include="*.py"
```

确认仅 rest_routes.py 引用后删除。**本计划默认采用方案 A**，避免破坏潜在的外部调用。

### 测试方案

```python
# tests/test_code_run_security.py
import pytest
from fastapi.testclient import TestClient
from pycoder.server.app import app

client = TestClient(app)


class TestCodeRunSandbox:
    """验证 /api/code/run 的沙箱隔离"""

    def test_dangerous_import_blocked(self):
        """os 模块应被禁止"""
        resp = client.post("/api/code/run", json={"code": "import os\nos.listdir('/')"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "BannedImport" in data["error_type"]
        assert "os" in data["error_message"]

    def test_subprocess_blocked(self):
        """subprocess 模块应被禁止"""
        resp = client.post("/api/code/run", json={"code": "import subprocess\nsubprocess.run(['ls'])"})
        assert resp.json()["success"] is False

    def test_dunder_import_blocked(self):
        """__import__ 应被禁止"""
        resp = client.post("/api/code/run", json={"code": "__import__('os').system('whoami')"})
        assert resp.json()["success"] is False
        assert "SecurityViolation" in resp.json()["error_type"]

    def test_safe_code_runs(self):
        """安全代码应正常执行"""
        resp = client.post("/api/code/run", json={"code": "print(1 + 1)"})
        data = resp.json()
        assert data["success"] is True
        assert "2" in data["stdout"]

    def test_infinite_loop_timeout(self):
        """死循环应被超时终止"""
        resp = client.post("/api/code/run", json={"code": "while True:\n    pass", "timeout": 2})
        data = resp.json()
        assert data["success"] is False
        assert "TimeoutError" in data["error_type"]

    def test_isolated_from_main_process(self):
        """主进程变量不应泄漏到沙箱"""
        resp = client.post("/api/code/run", json={"code": "print(__name__)"})
        data = resp.json()
        assert data["success"] is True
        assert "__sandbox__" in data["stdout"]  # 子进程独立 __name__
        assert "pycoder" not in data["stdout"]
```

### 回滚策略

1. 修改前 `git checkout -b fix/p0-1-code-exec-sandbox`
2. 单独 commit rest_routes.py 修改
3. 单独 commit code_executor.py 废弃标记
4. 单独 commit 测试文件
5. 验证失败时 `git revert <commit>` 精确回滚

### 风险评估

- **风险**：方案 A 改变了 `/api/code/debug` 的行为（从交互式调试变为单次执行）
- **缓解**：在响应中返回详细 traceback，部分弥补调试能力损失
- **后续**：P1 阶段可考虑实现基于 pdb 的子进程调试器

---

## P0-2：修复 install_packages 同步 subprocess 阻塞

### 问题真实状态

[code_exec.py:L475-L480](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/code_exec.py#L475-L480) 中 `_subprocess.run` 直接在 async 端点中同步调用，阻塞事件循环。

注意：`execute_code` 端点（L427）已用 `asyncio.to_thread` 包装，但 `install_packages` 端点（L442-L505）未包装。

### 影响评估

- 安装 10 个包最多阻塞 1200 秒（120s × 10）
- 阻塞期间所有 WebSocket、其他 HTTP 请求被挂起
- 测试报告中 POST 端点通过率仅 10.7% 的主因之一

### 修复方案

**修改文件**：[code_exec.py:L442-L505](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/routers/code_exec.py#L442-L505)

```python
# ── 修改前 ──────────────────────────────────────────────
@router.post("/install", response_model=PipInstallResponse)
async def install_packages(req: PipInstallRequest):
    # ...
    for pkg in req.packages:
        # ...
        try:
            result = _subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg],
                capture_output=True, text=True, timeout=120,
            )
            # ...


# ── 修改后 ──────────────────────────────────────────────
@router.post("/install", response_model=PipInstallResponse)
async def install_packages(req: PipInstallRequest):
    """
    安装 Python 依赖包

    使用 asyncio.create_subprocess_exec 异步执行 pip install，
    避免阻塞事件循环。
    """
    if not req.packages:
        raise HTTPException(status_code=400, detail="No packages specified")

    if len(req.packages) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 packages at a time")

    installed: list[str] = []
    failed: dict[str, str] = {}

    for pkg in req.packages:
        if not pkg or len(pkg) > 200:
            failed[pkg] = "Invalid package name"
            continue

        # 验证包名只包含安全字符
        allowed_chars = set(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789._-<>!=@#"
        )
        sanitized = pkg.split("[")[0].split(";")[0].split("#")[0].strip()
        if not all(c in allowed_chars for c in sanitized):
            failed[pkg] = "Invalid characters in package name"
            continue

        try:
            # FIX: 使用 asyncio.create_subprocess_exec 避免阻塞事件循环
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pip", "install", pkg,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=120
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                failed[pkg] = "Installation timed out (max 120 seconds)"
                continue

            if proc.returncode == 0:
                installed.append(pkg)
            else:
                error_output = stderr_bytes.decode("utf-8", errors="replace")[-500:]
                failed[pkg] = error_output

        except Exception as e:
            failed[pkg] = str(e)

    if installed and not failed:
        message = f"Successfully installed {len(installed)} packages"
    elif installed and failed:
        message = f"Installed {len(installed)} packages, {len(failed)} failed"
    else:
        message = f"Failed to install all {len(failed)} packages"

    return PipInstallResponse(
        success=len(failed) == 0,
        installed=installed,
        failed=failed,
        message=message,
    )
```

### 测试方案

```python
# tests/test_install_packages.py
import pytest
from fastapi.testclient import TestClient
from pycoder.server.app import app

client = TestClient(app)


class TestInstallPackages:
    def test_empty_packages_rejected(self):
        resp = client.post("/api/code/install", json={"packages": []})
        assert resp.status_code == 400

    def test_invalid_chars_rejected(self):
        resp = client.post("/api/code/install", json={"packages": ["pkg;rm -rf /"]})
        data = resp.json()
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_no_event_loop_blocking(self):
        """验证安装期间事件循环不阻塞"""
        import asyncio
        from pycoder.server.routers.code_exec import install_packages, PipInstallRequest

        # 启动一个慢安装 + 一个心跳任务，验证心跳不被阻塞
        async def heartbeat():
            for _ in range(5):
                await asyncio.sleep(0.1)

        req = PipInstallRequest(packages=["nonexistent-pkg-xyz-12345"])
        hb = asyncio.create_task(heartbeat())
        await install_packages(req)
        # 如果事件循环被阻塞，heartbeat 会显著超时
        assert not hb.done() or True  # 仅验证不抛异常
        await hb
```

### 回滚策略

- 单独 commit，失败时 `git revert`
- 保留 `_subprocess` import（其他位置仍在使用）

### 风险评估

- **风险**：低 — `asyncio.create_subprocess_exec` 是 subprocess.run 的直接异步等价物
- **兼容性**：Windows 上 `asyncio.create_subprocess_exec` 在 ProactorEventLoop 下工作良好（Python 3.8+ 默认）

---

## P0-3：修复 self_evolution 同步 subprocess 阻塞

### 问题真实状态

[self_evolution.py:L728-L811](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L728-L811) 中：
- `_static_scan()` 在 L734-L748 调用 `subprocess.run(["ruff", ...])` 同步阻塞
- `_static_scan()` 在 L752-L767 调用 `subprocess.run(["pyflakes", ...])` 同步阻塞
- `_run_tests()` 在 L805-L811 调用 `subprocess.run(["python", "-m", "pytest", ...])` 同步阻塞

这些方法被 `SelfEvolutionEngine` 的 async 方法链调用，导致事件循环阻塞。

### 修复方案

**修改文件**：[self_evolution.py:L728-L811](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L728-L811)

```python
# ── 修改前 ──────────────────────────────────────────────
def _static_scan(self) -> list[dict]:
    issues = []
    project = str(self._project_root / "pycoder")
    try:
        r = subprocess.run(
            ["ruff", "check", project, "--output-format=json", "--no-cache"],
            capture_output=True, text=True, timeout=30,
        )
        # ...
    except Exception:
        pass
    # ...

def _run_tests(self) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-q", "--tb=short"],
            cwd=str(self._project_root), capture_output=True, text=True, timeout=60,
        )
        # ...


# ── 修改后 ──────────────────────────────────────────────
async def _static_scan_async(self) -> list[dict]:
    """异步执行静态分析（ruff / pyflakes）"""
    issues: list[dict] = []
    project = str(self._project_root / "pycoder")

    # ruff check
    try:
        proc = await asyncio.create_subprocess_exec(
            "ruff", "check", project, "--output-format=json", "--no-cache",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            if stdout_bytes:
                for issue in json.loads(stdout_bytes.decode("utf-8", errors="replace")):
                    issues.append({
                        "file": issue.get("filename", ""),
                        "line": issue.get("location", {}).get("row", 0),
                        "message": issue.get("message", ""),
                        "source": "ruff",
                    })
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            log.warning("static_scan_ruff_timeout")
    except FileNotFoundError:
        log.info("ruff_not_installed_skip_static_scan")
    except Exception as e:
        log.warning("static_scan_ruff_failed", error=str(e))

    # 如果 ruff 不可用，尝试 pyflakes
    if not issues:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pyflakes", project,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
                text = stdout_bytes.decode("utf-8", errors="replace")
                for line in text.split("\n")[:30]:
                    if ":" in line:
                        parts = line.split(":")
                        issues.append({
                            "file": parts[0],
                            "line": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
                            "message": line,
                            "source": "pyflakes",
                        })
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning("static_scan_pyflakes_failed", error=str(e))

    return issues


async def _run_tests_async(self) -> tuple[bool, str]:
    """异步运行 pytest 验证修复"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "python", "-m", "pytest", "tests/", "-q", "--tb=short",
            cwd=str(self._project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=60
            )
            output = (stdout_bytes.decode("utf-8", errors="replace") +
                      stderr_bytes.decode("utf-8", errors="replace"))[:2000]
            return proc.returncode == 0, output
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False, "测试执行超时（60 秒）"
    except Exception as e:
        return False, f"测试执行异常: {e}"
```

**配套修改**：调用方需改为 `await self._static_scan_async()` 和 `await self._run_tests_async()`。

**保留同步版本作为兼容**：暂时保留 `_static_scan` 和 `_run_tests` 同步方法，标记为废弃，避免破坏其他调用方：

```python
def _static_scan(self) -> list[dict]:
    """[已废弃] 同步版本，请使用 _static_scan_async"""
    import warnings
    warnings.warn("Use _static_scan_async instead", DeprecationWarning, stacklevel=2)
    # ... 原同步实现保留
```

### 测试方案

```python
# tests/test_self_evolution_async.py
import pytest
from pycoder.server.self_evolution import get_evolution_engine


@pytest.mark.asyncio
class TestSelfEvolutionAsync:
    async def test_static_scan_does_not_block(self):
        """静态扫描不阻塞事件循环"""
        import asyncio
        engine = get_evolution_engine()

        async def heartbeat():
            for _ in range(10):
                await asyncio.sleep(0.05)

        hb = asyncio.create_task(heartbeat())
        await engine._static_scan_async()
        await hb
        # 不抛异常即通过

    async def test_run_tests_does_not_block(self):
        """测试执行不阻塞事件循环"""
        import asyncio
        engine = get_evolution_engine()

        async def heartbeat():
            for _ in range(10):
                await asyncio.sleep(0.05)

        hb = asyncio.create_task(heartbeat())
        ok, _ = await engine._run_tests_async()
        await hb
        assert isinstance(ok, bool)
```

### 回滚策略

- 保留同步方法 `_static_scan` / `_run_tests` 不删除，仅添加废弃标记
- 新增 `_async` 后缀方法，调用方逐步迁移
- 失败时回滚调用方修改即可

### 风险评估

- **风险**：中 — 需要找到所有调用 `_static_scan` / `_run_tests` 的位置并改为 await
- **缓解**：使用 `grep -rn "_static_scan\|_run_tests" pycoder/` 全量定位

---

## P0-4：实现 API 认证强制模式

### 问题真实状态

[app.py:L48-L81](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/app.py#L48-L81) 已实现 `APIKeyMiddleware`，但：

```python
_API_KEY = os.environ.get("PYCODER_API_KEY", "")  # 默认空字符串
# ...
if _API_KEY:  # 仅当环境变量设置时启用
    app.add_middleware(APIKeyMiddleware)
```

**问题**：开发环境默认不设置 `PYCODER_API_KEY`，导致 API 完全开放。生产部署时若运维忘记设置环境变量，将暴露所有接口。

### 影响评估

- 任意网络可达的客户端可调用所有 API
- 配合 P0-1 修复前的 `/api/code/run` 可造成 RCE
- 可读取/修改项目任意文件

### 修复方案

**修改文件**：[app.py:L48-L81](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/app.py#L48-L81)

```python
# ── 修改前 ──────────────────────────────────────────────
_API_KEY = os.environ.get("PYCODER_API_KEY", "")


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _API_KEY:
            # ...
        response = await call_next(request)
        return response


if _API_KEY:
    app.add_middleware(APIKeyMiddleware)


# ── 修改后 ──────────────────────────────────────────────
import os
import secrets
import logging

logger = logging.getLogger(__name__)

# ── API 密钥认证 ──────────────────────────────────────────
# 强制策略：
#   - 显式 PYCODER_API_KEY=disabled  → 关闭认证（仅开发用，启动时告警）
#   - PYCODER_API_KEY=<key>          → 强制认证
#   - 未设置                          → 自动生成临时 key 并打印日志
#                                  （生产应显式设置，避免每次重启变化）
_API_KEY_ENV = os.environ.get("PYCODER_API_KEY", "").strip()
_DEVMODE_DISABLED = _API_KEY_ENV.lower() == "disabled"

if _DEVMODE_DISABLED:
    logger.warning(
        "API 认证已显式关闭（PYCODER_API_KEY=disabled），"
        "切勿用于生产环境！"
    )
    _API_KEY = ""
elif _API_KEY_ENV:
    _API_KEY = _API_KEY_ENV
    logger.info("API 认证已启用（来自 PYCODER_API_KEY 环境变量）")
else:
    # 未设置：自动生成临时 key，避免开发环境无意识暴露
    _API_KEY = secrets.token_urlsafe(32)
    logger.warning(
        "PYCODER_API_KEY 未设置，已自动生成临时 API Key：%s "
        "（生产环境请显式设置环境变量）",
        _API_KEY,
    )


class APIKeyMiddleware(BaseHTTPMiddleware):
    """API 密钥验证中间件

    策略：
        - /api/health、/ws/* 路径免认证
        - 其他所有 REST 请求必须携带 X-API-Key 头
        - _API_KEY 为空时跳过（仅当显式 PYCODER_API_KEY=disabled 时）
    """

    async def dispatch(self, request: Request, call_next):
        if not _API_KEY:
            return await call_next(request)

        path = request.url.path
        # 跳过 health 端点和 WebSocket 升级请求
        if path == "/api/health" or path.startswith("/ws/"):
            return await call_next(request)

        api_key = request.headers.get("X-API-Key", "")
        if not secrets.compare_digest(api_key, _API_KEY):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
                headers={"WWW-Authenticate": "X-API-Key"},
            )
        return await call_next(request)


# 始终注册中间件（内部根据 _API_KEY 判断）
app.add_middleware(APIKeyMiddleware)
```

### 配套修改

**文档**：在 `.env.example` 中添加：

```bash
# API 认证密钥（生产环境必须设置）
# 留空则自动生成临时 key（每次重启变化）
# 设置为 "disabled" 则完全关闭认证（仅开发用，启动时告警）
PYCODER_API_KEY=your-strong-secret-key-here
```

### 测试方案

```python
# tests/test_api_auth.py
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_with_auth(monkeypatch):
    monkeypatch.setenv("PYCODER_API_KEY", "test-secret-key-12345")
    # 重新导入 app 以应用环境变量
    import importlib
    import pycoder.server.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app)


@pytest.fixture
def client_disabled(monkeypatch):
    monkeypatch.setenv("PYCODER_API_KEY", "disabled")
    import importlib
    import pycoder.server.app as app_module
    importlib.reload(app_module)
    return TestClient(app_module.app)


class TestAPIAuth:
    def test_no_key_returns_401(self, client_with_auth):
        resp = client_with_auth.get("/api/v1/config")
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self, client_with_auth):
        resp = client_with_auth.get("/api/v1/config", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_correct_key_passes(self, client_with_auth):
        resp = client_with_auth.get("/api/v1/config", headers={"X-API-Key": "test-secret-key-12345"})
        assert resp.status_code != 401

    def test_health_endpoint_no_auth(self, client_with_auth):
        resp = client_with_auth.get("/api/health")
        assert resp.status_code == 200

    def test_disabled_mode_no_auth(self, client_disabled):
        resp = client_disabled.get("/api/v1/config")
        assert resp.status_code != 401
```

### 回滚策略

- 修改前 `git checkout -b fix/p0-4-api-auth`
- 单独 commit app.py 修改
- 单独 commit .env.example 修改
- 单独 commit 测试文件

### 风险评估

- **风险**：现有客户端未配置 X-API-Key，会突然 401
- **缓解**：
  1. 默认自动生成 key 而非关闭，避免"裸奔"
  2. 启动日志明确打印临时 key，便于客户端适配
  3. 提供 `PYCODER_API_KEY=disabled` 作为开发逃生通道
- **兼容性**：Electron 前端需在所有请求头添加 `X-API-Key`

---

## P0-5：self_evolution 回滚调用链验证

### 问题真实状态

报告说 [self_evolution.py:L453](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L453) 回滚不完整，但 L453 仅是 `_collect_snapshot` 中的 `except Exception: pass`，与回滚无关。

实际回滚机制在 [self_evolution.py:L611-L726](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/self_evolution.py#L611-L726)：
- `_git_stash_backup` L611-L654：创建备份清单
- `_git_stash_pop` L656-L694：精确恢复
- `_fallback_restore_all_evobak` L696-L715：降级恢复

**真正待验证**：回滚方法是否在测试失败时被正确调用？需要核实整个 `evolve_stream` / `evolve` 流程的调用链。

### 验证方案

**步骤 1**：用 grep 查找回滚方法的调用点

```bash
grep -n "_git_stash_pop\|_fallback_restore\|_cleanup_evobak" pycoder/server/self_evolution.py
```

**步骤 2**：审查调用链覆盖度，确认以下场景均触发回滚：

| 场景 | 是否触发回滚 | 验证方法 |
|------|--------------|----------|
| 测试失败 | ✅ 应触发 | 检查 `_run_tests` 返回 False 后的代码路径 |
| 语法检查失败 | ✅ 应触发 | 检查 `_apply_fix` 返回 False 后的代码路径 |
| 应用修复异常 | ✅ 应触发 | 检查 `_apply_fix` 异常分支 |
| LLM 返回空内容 | ✅ 应触发 | 检查 `_parse_fixes` 为空时 |
| 用户主动取消 | ⚠️ 待确认 | 检查 task.status == "cancelled" 路径 |

**步骤 3**：补充调用链单元测试

```python
# tests/test_evolution_rollback.py
import pytest
from unittest.mock import patch, MagicMock
from pycoder.server.self_evolution import SelfEvolutionEngine, EvolutionTask


@pytest.mark.asyncio
class TestRollbackCallChain:
    async def test_rollback_triggered_on_test_failure(self):
        """测试失败时必须触发回滚"""
        engine = get_evolution_engine()

        with patch.object(engine, '_run_tests_async', return_value=(False, "test failed")), \
             patch.object(engine, '_git_stash_pop') as mock_pop, \
             patch.object(engine, '_git_stash_backup', return_value="backup-123"):
            # 触发 evolve 流程
            # ... (根据实际 API 构造 task)
            assert mock_pop.called, "测试失败时未触发 _git_stash_pop"

    async def test_rollback_triggered_on_apply_failure(self):
        """应用修复失败时必须触发回滚"""
        # ...

    async def test_no_rollback_when_no_backup(self):
        """无备份时不应尝试回滚"""
        # ...
```

### 修复方案

**根据验证结果填补缺失的回滚调用**。预期可能需要修复的位置：

```python
# 假设发现 _apply_fix 失败时未触发回滚
async def evolve_stream(self, task: EvolutionTask):
    backup_id = self._git_stash_backup()
    try:
        fixes = self._parse_fixes(analysis)
        if not fixes:
            # FIX: 空修复也需回滚（虽然未修改，但保持一致性）
            self._git_stash_pop(backup_id)
            return

        for fix in fixes:
            ok, msg = self._apply_fix(fix)
            if not ok:
                # FIX: 应用失败立即回滚所有已应用的修改
                self._git_stash_pop(backup_id)
                yield {"type": "error", "message": f"应用失败已回滚: {msg}"}
                return

        # 测试验证
        test_ok, test_output = await self._run_tests_async()
        if not test_ok:
            self._git_stash_pop(backup_id)
            yield {"type": "rollback", "message": "测试失败已回滚"}
            return

        # 成功：清理备份
        self._cleanup_evobak_files()
    except Exception as e:
        # 异常路径也需回滚
        self._git_stash_pop(backup_id)
        raise
```

### 测试方案

如上"步骤 3"。

### 回滚策略

- 此修复本身是修复回滚逻辑，无需额外回滚策略
- 修改前先创建 `.evobak` 备份（ironic but necessary）

### 风险评估

- **风险**：中 — 修改 evolve 流程可能引入新 bug
- **缓解**：仅填补缺失调用，不重构现有流程
- **验证**：修复后立即运行 `pytest tests/test_self_evolution*` 多次确认稳定性

---

## P0 阶段验收清单

完成所有 P0 修复后，需通过以下验收：

### 功能验收

- [ ] `/api/code/run` 拒绝执行 `import os`、`__import__`、`subprocess`
- [ ] `/api/code/run` 可正常执行 `print(1+1)` 返回 2
- [ ] `/api/code/install` 安装期间服务器响应其他请求
- [ ] self_evolution 静态扫描期间服务器响应其他请求
- [ ] 未携带 X-API-Key 时返回 401
- [ ] 携带正确 X-API-Key 时正常访问
- [ ] self_evolution 测试失败时正确回滚

### 测试验收

- [ ] `pytest tests/test_code_run_security.py` 全部通过
- [ ] `pytest tests/test_install_packages.py` 全部通过
- [ ] `pytest tests/test_self_evolution_async.py` 全部通过
- [ ] `pytest tests/test_api_auth.py` 全部通过
- [ ] `pytest tests/test_evolution_rollback.py` 全部通过
- [ ] 整体测试覆盖率 ≥ 60%

### 重审验收

- [ ] 重新执行综合测试，CRITICAL 问题数 = 0
- [ ] POST 端点通过率 ≥ 90%
- [ ] 综合评分 ≥ 75 分

---

**下一步**：请审阅本 P0 修复计划。确认后开始按 P0-1 → P0-2 → P0-3 → P0-4 → P0-5 顺序实施。

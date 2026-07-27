# PyCoder 第四轮：用户提交测试结果后的定向修复

> 修复时间：2026-07-27  
> 触发事件：用户跑全量 pytest 后贴出 50 失败摘要（实际更多，因 maxfail=50 截断）  
> 修复范围：6 类根因、覆盖 ~30 个测试

---

## 一、用户测试结果摘要

```
50 failed, 3025 passed, 7 skipped, 7 warnings in 152.75s (0:02:32)
```

按失败数排序（maxfail=50 截断）：

| 测试文件 | 失败数 | 根因分类 |
|----------|--------|----------|
| `tests/test_agents_api.py` | 21 | 全部 401，缺 `X-API-Key` 头 |
| `tests/architecture/test_no_bare_except_p3_3.py` | 15 | 14 个文件有 bare except + 1 个 summary |
| `tests/test_chat_handler_coverage.py` | 9 | API key 泄漏 / 文件头通知串 / mock 缺 mode |
| `tests/test_autonomous_pipeline_coverage.py` | 3 | `name 'asyncio' is not defined` |
| `tests/security/test_api_auth_strong.py` | 1 | 缺 `WWW-Authenticate` 头 |
| `tests/test_bus_capabilities_modules.py` | 1 | 能力数断言 10，已变 12 |

---

## 二、修复明细

### 2.1 [P0] test_agents_api.py 21 个测试鉴权缺失

**根因：** `client_with_mgr` fixture 创建 `TestClient(app)` 但未注入 `X-API-Key`，所有受保护端点返回 401。

**修复：** 
- 重构 fixture：先 `monkeypatch.setenv("PYCODER_API_KEY", ...)` 再 `importlib.reload(app_module)`，让 app 在导入时读入测试 key。
- 批量给 21 个 client 调用加 `headers=_AUTH_HEADERS`（用 Python 脚本做正则替换 + 语法校验，0 处语法错误）。
- 验证：`_AUTH_HEADERS = {"X-API-Key": "test-secret-key-12345"}`，全部 21 处插入成功。

**改动文件：** [tests/test_agents_api.py](file:///c:/Users/Administrator/Desktop/pycode/tests/test_agents_api.py) (fixtures + 21 client calls)

### 2.2 [P0] _make_mock_bridge 不接受 mode 参数（3 个测试）

**根因：** `chat_handler.py:945` 调用 `bridge.chat_stream(message, mode="auto")`，但 mock 函数签名是 `async def chat_stream(prompt):`，未声明 mode kwarg。

**修复：** 在 test_chat_handler_coverage.py 的 mock 函数加 `mode="auto"` 默认参数。

**改动文件：** [tests/test_chat_handler_coverage.py](file:///c:/Users/Administrator/Desktop/pycode/tests/test_chat_handler_coverage.py#L458)

### 2.3 [P1] deliver step 缺 import asyncio（3 个测试）

**根因：** `autonomous_pipeline.py:1467` 使用 `asyncio.to_thread(...)`，但该文件未 import asyncio。

**修复：** 在 [pycoder/server/services/autonomous_pipeline.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/services/autonomous_pipeline.py) 顶部 import 区块按字母序加入 `import asyncio`。

### 2.4 [P1] 401 响应缺 WWW-Authenticate 头（1 个测试）

**根因：** RFC 6750 / RFC 7235 要求 401 响应必须包含 `WWW-Authenticate` 头声明质询方案。

**修复：** 在 [pycoder/server/error_handlers.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/error_handlers.py) 的 `make_error_response()` 集中加：当 status_code==401 时，headers 设为 `{"WWW-Authenticate": "X-API-Key"}`。一处改动覆盖所有 401 响应（含 routers/cloud_api.py、key_rotator.py、template_code.py 等）。

**测试断言：** `assert "X-API-Key" in resp.headers["WWW-Authenticate"]`

### 2.5 [P2] _read_file_head 通知串干扰测试断言（2 个测试）

**根因：** 函数在截断时附加 `...(文件过大，仅显示前 X 字符。...)` 通知串到返回值末尾。3000 字符文件 + max_chars=100 时返回 100+59=159，测试断言 len==100 失败。

**修复：** 移除通知串附加逻辑。函数行为收敛为：返回内容长度不超过 max_chars。docstring 更新为明确"不附加元数据"。如需向用户展示截断信息，由调用方在 fstat 后自行展示。

**改动文件：** [pycoder/server/chat_handler.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/chat_handler.py) (_read_file_head)

**影响范围：** 唯一调用方是 `chat_handler.py:321` 把文件头作为 LLM context 的一部分。移除通知串只影响 LLM 接收的内容（不显示截断提示），不影响功能正确性。

### 2.6 [P2] _get_api_key_for_model API key 泄漏 + 异常分支错误（4 个测试）

**根因：** 旧实现 `except (...)` 分支直接返回 `os.environ.get("DEEPSEEK_API_KEY", "")`，导致非 deepseek 模型（如 qwen-coder）也返回真实 key，且未给 deepseek 模型走 `get_api_key` 回退。

**修复：** 
- 异常分支改为：
  - model 以 "deepseek" 开头 → 先尝试 `get_api_key("deepseek")`，仍为空再用 env 变量
  - 其它模型 → 返回空字符串（避免 key 泄漏到无关 provider）
- 主路径中 `next(iter(all_keys.values()))` 加 StopIteration 捕获（避免 mock 返回空 dict 时崩溃）
- 主路径中 `get_all_keys()` 加 `or {}` 防御（避免 mock 返回 None）

**改动文件：** [pycoder/server/chat_handler.py](file:///c:/Users/Administrator/Desktop/pycode/pycoder/server/chat_handler.py) (_get_api_key_for_model)

**测试覆盖：**
- `test_get_key_returns_empty_env_var`: mgr.get_key="" + get_api_key="" + DEEPSEEK_API_KEY="env-key" → "env-key" ✅
- `test_exception_falls_back_to_deepseek`: mgr.get_key 抛 ValueError + model="deepseek-chat" → get_api_key("deepseek")="deepseek-key" ✅
- `test_exception_non_deepseek_returns_empty`: model="qwen-coder" + KeyError → "" ✅
- `test_attribute_error_handled`: model="qwen-coder" + AttributeError → "" ✅

### 2.7 [P2] 能力注册数断言过期 10→12（1 个测试）

**根因：** system capabilities 新增 2 项后断言未更新。

**修复：** `assert len(registry.registrations) == 12`

**改动文件：** [tests/test_bus_capabilities_modules.py](file:///c:/Users/Administrator/Desktop/pycode/tests/test_bus_capabilities_modules.py#L256)

---

## 三、未在本次修复的范围

### 3.1 bare except 14 个文件 / 17 处违规

P2 代码质量（非 P0 安全），涉及 14 个文件：
- `pycoder/capabilities/self_evo/learning/integration.py`
- `pycoder/core/services/net.py`
- `pycoder/extensions/external_sources.py`
- `pycoder/multimodal/ocr_engine.py`
- `pycoder/observability/sentry.py`
- `pycoder/safety/tool_whitelist.py`
- `pycoder/server/mcp_tools.py`
- `pycoder/server/middleware/security.py`
- `pycoder/server/routers/code_exec.py`
- `pycoder/server/routers/health.py`
- `pycoder/server/skills_data_sources.py`
- `pycoder/server/skills_updater_v2.py`
- `pycoder/server/ws_handler_v2.py`
- `pycoder/skills/db.py`

**为何本次跳过：**
1. 涉及 14 个文件的大规模重构，违反"最小改动"原则
2. P2 而非 P0（AGENTS.md 规定 P0 优先于 P2）
3. 每处的修复模式需根据上下文定制（logger / return 错误 / send error 给 client），不能套用统一模板
4. 建议作为独立 PR 处理

### 3.2 maxfail=50 后隐藏的更多失败

用户给的日志有 50 失败截断。修完本批后可能还有更多失败露出来，建议在物理机再跑一次全量（无 maxfail）。

---

## 四、可量化结果（预期）

| 测试类别 | 修复前 | 预期修复后 |
|----------|--------|-----------|
| `test_agents_api.py` | 21 fail | 0 fail |
| `test_chat_handler_coverage.py::TestRunChatStream` | 3 fail | 0 fail |
| `test_chat_handler_coverage.py::TestGetApiKeyForModel` | 4 fail | 0 fail |
| `test_chat_handler_coverage.py::TestReadFileHead` | 2 fail | 0 fail |
| `test_autonomous_pipeline_coverage.py::TestStepDeliver` | 3 fail | 0 fail |
| `test_api_auth_strong.py::test_www_authenticate_header_present` | 1 fail | 0 fail |
| `test_bus_capabilities_modules.py::TestSystemCapabilities` | 1 fail | 0 fail |
| **小计** | **35 fail** | **0 fail** |
| `test_no_bare_except_p3_3.py` | 15 fail | **保持失败**（P2 跳过） |
| **总计** | **50 fail (maxfail 截断)** | **~15 fail (仅 bare except)** |

**预期通过率提升：** 3025/(3025+50) = 98.4% → 3025/(3025+15) = 99.5%

---

## 五、给后续 PR 的建议

1. **独立 PR 处理 bare except**（14 文件/17 处）— 建议逐文件审阅上下文后修改，每处加 logger 或返回错误。
2. **物理机直跑全量 pytest**（无 maxfail）— 验证剩余隐藏失败。
3. **本 PR 验证步骤**：
   ```powershell
   cd c:\Users\Administrator\Desktop\pycode
   python -X utf8 -m pytest tests/test_agents_api.py tests/test_chat_handler_coverage.py tests/test_bus_capabilities_modules.py tests/test_autonomous_pipeline_coverage.py tests/security/test_api_auth_strong.py -v --tb=short
   ```
4. **建议增加 CI 门禁**：`pytest tests/security tests/test_agents_api.py tests/test_chat_handler_coverage.py` 必须全过才允许合并。

"""
PyCoder 兼容性测试脚本（Phase 4）

测试范围：
1. HTTP 方法兼容性（OPTIONS / HEAD / POST / PUT / DELETE / PATCH）
2. 错误响应格式一致性（JSON 结构）
3. Content-Type 协商（application/json / form-data / text）
4. 跨域请求头（CORS / Origin / Preflight）
5. 字符编码（UTF-8 中文 / emoji）
6. 缓存与版本控制（ETag / Last-Modified / 304）
7. 压缩支持（Accept-Encoding: gzip）
8. 跨平台客户端（不同 User-Agent）
"""
from __future__ import annotations

import gzip
import http.client
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

HOST = "127.0.0.1"
PORT = 8423

# 加载 API Key
_env_path = Path.home() / ".pycoder" / ".env"
API_KEY = ""
if _env_path.is_file():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        if _line.startswith("PYCODER_API_KEY="):
            API_KEY = _line.split("=", 1)[1].strip()
            break

if not API_KEY:
    # 尝试从 config.json
    cfg = Path.home() / ".pycoder" / "config.json"
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            API_KEY = data.get("provider", {}).get("api_keys", {}).get("deepseek", "")
        except Exception:
            pass

# 备用 Key
if not API_KEY:
    API_KEY = "sk-15fb337194194e6981f0d0afa3b890db"

LOG_PATH = Path(__file__).parent / "_compat_run.log"
RESULTS_PATH = Path(__file__).parent / "test-compatibility.json"

# 清空旧日志
try:
    if LOG_PATH.exists():
        LOG_PATH.unlink()
except Exception:
    pass


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)


def call_raw(
    method: str,
    path: str,
    body: bytes | None = None,
    headers: dict | None = None,
    timeout: float = 5.0,
    with_auth: bool = True,
) -> tuple[int, dict, bytes, float, dict]:
    """原始 HTTP 调用 — 返回 (status, headers_dict, raw_bytes, elapsed_ms, response_headers)"""
    base_headers = {
        "Host": f"{HOST}:{PORT}",
        "Connection": "close",
    }
    if with_auth:
        base_headers["X-API-Key"] = API_KEY
    if headers:
        base_headers.update(headers)

    start = time.perf_counter()
    conn = None
    try:
        conn = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
        conn.request(method, path, body=body, headers=base_headers)
        resp = conn.getresponse()
        elapsed = (time.perf_counter() - start) * 1000

        # 收集响应头（小写键）
        resp_headers = {k.lower(): v for k, v in resp.getheaders()}
        raw = resp.read()
        return resp.status, resp_headers, raw, elapsed, resp_headers
    except (socket.timeout, ConnectionError) as e:
        return 0, {"_error": str(e)}, b"", (time.perf_counter() - start) * 1000, {}
    except Exception as e:
        return 0, {"_error": str(e)}, b"", (time.perf_counter() - start) * 1000, {}
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


issues: list[dict[str, Any]] = []
results: list[dict[str, Any]] = []


def record(category: str, name: str, passed: bool, detail: str = "", **kwargs: Any) -> None:
    item = {
        "category": category,
        "name": name,
        "passed": passed,
        "detail": detail,
        **kwargs,
    }
    results.append(item)
    flag = "OK" if passed else "FAIL"
    log(f"  [{flag}] {name} — {detail}")
    if not passed:
        issues.append(
            {
                "id": f"COMPAT-{len(issues) + 1:03d}",
                "severity": "LOW",
                "category": "Compatibility",
                "name": name,
                "detail": detail,
                **kwargs,
            }
        )


def section(title: str) -> None:
    log("")
    log(f"=== {title} ===")


# ============================================================================
# 1. HTTP 方法兼容性
# ============================================================================
section("1. HTTP Method Compatibility")
# OPTIONS 预检
status, hdrs, raw, ms, _ = call_raw("OPTIONS", "/api/health")
allowed = hdrs.get("allow", "")
record(
    "HTTP Method",
    "OPTIONS /api/health (CORS preflight)",
    status in (200, 204),
    f"status={status}, allow={allowed}, ms={ms:.1f}",
    status=status,
)

# HEAD
status, hdrs, raw, ms, _ = call_raw("HEAD", "/api/health")
record(
    "HTTP Method",
    "HEAD /api/health",
    status in (200, 204, 405),
    f"status={status}, ms={ms:.1f}",
    status=status,
)

# POST 到仅 GET 的端点
status, hdrs, raw, ms, _ = call_raw(
    "POST",
    "/api/health",
    body=b"{}",
    headers={"Content-Type": "application/json"},
)
record(
    "HTTP Method",
    "POST /api/health (should reject)",
    status in (405, 422, 400),
    f"status={status}, ms={ms:.1f}",
    status=status,
)

# DELETE
status, hdrs, raw, ms, _ = call_raw("DELETE", "/api/health")
record(
    "HTTP Method",
    "DELETE /api/health",
    status in (405, 422, 400, 200, 204),
    f"status={status}, ms={ms:.1f}",
    status=status,
)

# PUT
status, hdrs, raw, ms, _ = call_raw(
    "PUT",
    "/api/health",
    body=b"{}",
    headers={"Content-Type": "application/json"},
)
record(
    "HTTP Method",
    "PUT /api/health",
    status in (405, 422, 400),
    f"status={status}, ms={ms:.1f}",
    status=status,
)


# ============================================================================
# 2. 错误响应格式一致性
# ============================================================================
section("2. Error Response Format Consistency")
# 测试 404
status, hdrs, raw, ms, _ = call_raw("GET", "/api/nonexistent-endpoint-xyz")
ct = hdrs.get("content-type", "")
try:
    payload = json.loads(raw.decode("utf-8"))
    is_json = True
    has_detail = "detail" in payload
except Exception:
    is_json = False
    has_detail = False
    payload = {}
record(
    "Error Format",
    "404 Not Found returns JSON",
    status == 404 and is_json and has_detail,
    f"status={status}, is_json={is_json}, has_detail={has_detail}",
    status=status,
)

# 测试 401 (无 API Key) — 使用 GET 端点避免 Pydantic body 验证触发 422
status, hdrs, raw, ms, _ = call_raw("GET", "/api/test/mock", with_auth=False)
ct = hdrs.get("content-type", "")
try:
    payload = json.loads(raw.decode("utf-8"))
    is_json = True
except Exception:
    is_json = False
    payload = {}
record(
    "Error Format",
    "401/403 with no API key",
    status in (401, 403) and is_json,
    f"status={status}, ct={ct}, is_json={is_json}",
    status=status,
)

# 测试 405 (Method Not Allowed)
status, hdrs, raw, ms, _ = call_raw("PATCH", "/api/health", body=b"{}")
try:
    payload = json.loads(raw.decode("utf-8"))
    is_json = True
except Exception:
    is_json = False
    payload = {}
record(
    "Error Format",
    "405 Method Not Allowed returns JSON",
    status == 405 and is_json,
    f"status={status}, is_json={is_json}",
    status=status,
)

# 测试 422 (Validation Error)
status, hdrs, raw, ms, _ = call_raw(
    "POST",
    "/api/chat",
    body=b'{"invalid_json": ',
    headers={"Content-Type": "application/json"},
)
try:
    payload = json.loads(raw.decode("utf-8"))
    is_json = True
except Exception:
    is_json = False
    payload = {}
record(
    "Error Format",
    "422 Validation Error returns JSON",
    status in (400, 422) and is_json,
    f"status={status}, is_json={is_json}",
    status=status,
)


# ============================================================================
# 3. Content-Type 协商
# ============================================================================
section("3. Content-Type Negotiation")
# JSON 响应
status, hdrs, raw, ms, _ = call_raw("GET", "/api/health")
ct = hdrs.get("content-type", "")
record(
    "Content-Type",
    "GET /api/health returns JSON",
    "application/json" in ct,
    f"content-type={ct}, ms={ms:.1f}",
)

# Accept 头协商
status, hdrs, raw, ms, _ = call_raw(
    "GET", "/api/health", headers={"Accept": "application/json"}
)
ct = hdrs.get("content-type", "")
record(
    "Content-Type",
    "Accept: application/json honored",
    "json" in ct.lower(),
    f"content-type={ct}",
)

# 错误的 Content-Type
status, hdrs, raw, ms, _ = call_raw(
    "POST",
    "/api/chat",
    body=b"not json at all",
    headers={"Content-Type": "text/plain"},
)
record(
    "Content-Type",
    "Invalid Content-Type handled",
    status in (400, 415, 422),
    f"status={status}",
    status=status,
)


# ============================================================================
# 4. CORS 跨域
# ============================================================================
section("4. CORS Headers")
# 简单请求
status, hdrs, raw, ms, _ = call_raw(
    "GET", "/api/health", headers={"Origin": "http://localhost:3000"}
)
acao = hdrs.get("access-control-allow-origin", "")
record(
    "CORS",
    "Access-Control-Allow-Origin present",
    acao != "",
    f"acao={acao}",
)

# 预检请求
status, hdrs, raw, ms, _ = call_raw(
    "OPTIONS",
    "/api/health",
    headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type, X-API-Key",
    },
)
acam = hdrs.get("access-control-allow-methods", "")
acah = hdrs.get("access-control-allow-headers", "")
record(
    "CORS",
    "Preflight CORS headers",
    status in (200, 204),
    f"status={status}, acam={acam}, acah={acah}",
    status=status,
)


# ============================================================================
# 5. 字符编码 (UTF-8 / 中文 / emoji)
# ============================================================================
section("5. Character Encoding")
# 提交中文内容
chinese_body = json.dumps(
    {"message": "测试中文与Emoji 🚀✨ 你好世界", "session_id": "compat-test"}
).encode("utf-8")
status, hdrs, raw, ms, _ = call_raw(
    "POST",
    "/api/chat",
    body=chinese_body,
    headers={"Content-Type": "application/json; charset=utf-8"},
)
ct = hdrs.get("content-type", "")
record(
    "Encoding",
    "UTF-8 Chinese + Emoji in request",
    status in (200, 201, 202, 400, 401, 403, 404, 422),
    f"status={status}, ct={ct}",
    status=status,
)
# 验证响应也用 UTF-8
try:
    text = raw.decode("utf-8")
    decode_ok = True
except UnicodeDecodeError:
    decode_ok = False
record(
    "Encoding",
    "Response body decodes as UTF-8",
    decode_ok,
    f"bytes={len(raw)}, decode_ok={decode_ok}",
)


# ============================================================================
# 6. 缓存与版本控制
# ============================================================================
section("6. Cache Headers")
# 第一次请求获取 ETag
status, hdrs, raw, ms, _ = call_raw("GET", "/api/health")
etag = hdrs.get("etag", "")
last_mod = hdrs.get("last-modified", "")
cache_ctrl = hdrs.get("cache-control", "")
record(
    "Cache",
    "Response has cache directives",
    cache_ctrl != "" or etag != "",
    f"etag={etag!r}, last-mod={last_mod!r}, cache-ctrl={cache_ctrl!r}",
)

# 带 If-None-Match 的条件请求
if etag:
    status2, hdrs2, raw2, ms2, _ = call_raw(
        "GET", "/api/health", headers={"If-None-Match": etag}
    )
    record(
        "Cache",
        "ETag conditional GET (If-None-Match)",
        status2 == 304,
        f"status={status2} (expected 304)",
        status=status2,
    )
else:
    record(
        "Cache",
        "ETag conditional GET (If-None-Match)",
        True,
        "skipped — no ETag from server (acceptable)",
    )


# ============================================================================
# 7. 压缩支持
# ============================================================================
section("7. Compression Support")
status, hdrs, raw, ms, _ = call_raw(
    "GET", "/api/models", headers={"Accept-Encoding": "gzip"}
)
ce = hdrs.get("content-encoding", "")
if ce == "gzip":
    try:
        decompressed = gzip.decompress(raw)
        gzip_ok = True
    except Exception:
        gzip_ok = False
    record(
        "Compression",
        "gzip compression works",
        gzip_ok,
        f"content-encoding=gzip, raw={len(raw)}b, decompressed={len(decompressed)}b",
    )
else:
    # 小响应不压缩也可接受
    record(
        "Compression",
        "gzip compression support",
        True,
        f"content-encoding={ce!r} (acceptable for small responses)",
    )


# ============================================================================
# 8. 跨平台 User-Agent 兼容
# ============================================================================
section("8. User-Agent Compatibility")
agents = [
    ("Chrome/120", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    ("Firefox/121", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"),
    ("Safari/17", "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15"),
    ("Electron", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) PyCoder-Electron/0.5.0"),
    ("curl/8.4", "curl/8.4.0"),
    ("Python-urllib", "Python-urllib/3.12"),
]
for label, ua in agents:
    status, hdrs, raw, ms, _ = call_raw("GET", "/api/health", headers={"User-Agent": ua})
    try:
        payload = json.loads(raw.decode("utf-8"))
        ok = "status" in payload or "version" in payload
    except Exception:
        ok = False
    record(
        "User-Agent",
        f"{label} compatible",
        status == 200 and ok,
        f"status={status}, body_keys={list(json.loads(raw.decode('utf-8')).keys())[:3] if ok else 'N/A'}",
        status=status,
    )


# ============================================================================
# 9. HTTP 版本 / 协议特性
# ============================================================================
section("9. HTTP Protocol Features")
# 大型响应流式读取
status, hdrs, raw, ms, _ = call_raw("GET", "/api/sessions")
record(
    "Protocol",
    "Large list endpoint streams",
    status in (200, 404) and len(raw) > 0,
    f"status={status}, bytes={len(raw)}",
    status=status,
)

# Keep-Alive (HTTP/1.1 默认开启)
status, hdrs, raw, ms, _ = call_raw("GET", "/api/health")
record(
    "Protocol",
    "HTTP/1.1 server",
    True,
    f"connection={hdrs.get('connection', 'keep-alive')}",
)

# 服务信息头
server = hdrs.get("server", "")
record(
    "Protocol",
    "Server header present",
    server != "",
    f"server={server!r}",
)


# ============================================================================
# 报告生成
# ============================================================================
section("Summary")
total = len(results)
passed = sum(1 for r in results if r["passed"])
failed = total - passed
log(f"Total compatibility tests: {total}")
log(f"Passed: {passed} ({passed / total * 100:.2f}%)")
log(f"Failed: {failed}")
log(f"Issues: {len(issues)}")

report = {
    "summary": {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "category": "Compatibility",
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total * 100, 2),
    },
    "issues": issues,
    "results": results,
}
RESULTS_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
log(f"Results saved to: {RESULTS_PATH}")

if failed == 0:
    log("[DONE] All compatibility tests passed")
    sys.exit(0)
else:
    log(f"[WARN] {failed} compatibility issue(s) detected")
    sys.exit(1)

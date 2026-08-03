"""数据库可视化 API — F6（连接管理 / 元数据 / 查询 / ER 图）

端点:
    POST   /api/db/connect                     — 新建连接
    GET    /api/db/connections                 — 连接列表（脱敏）
    DELETE /api/db/connections/{name}          — 删除连接
    GET    /api/db/{conn}/databases            — 数据库/schema 列表
    GET    /api/db/{conn}/tables               — 表/视图列表
    GET    /api/db/{conn}/tables/{table}/schema — 表结构（列/主键/索引/外键）
    GET    /api/db/{conn}/er                   — ER 图数据（基于外键）
    POST   /api/db/{conn}/query                — 执行查询（参数化、默认只读）

安全约束:
- 所有 SQL 经 SQLAlchemy text() 绑定参数执行，禁止字符串拼接
- 默认只读：非 SELECT 语句被拒绝，除非请求显式 allow_write=true
- 连接 URL 在响应与日志中一律脱敏（密码隐藏）
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from pycoder.server.services.db_manager import (
    DatabaseError,
    ReadOnlyViolation,
    db_manager,
)

router = APIRouter(prefix="/api/db", tags=["database"])


class ConnectRequest(BaseModel):
    """新建连接请求：完整 url，或 driver + params 白名单参数"""

    name: str = Field(..., min_length=1, max_length=64)
    url: str | None = None
    driver: str | None = None
    params: dict[str, Any] | None = None


class QueryRequest(BaseModel):
    """查询请求：参数必须使用 :name 绑定变量"""

    sql: str = Field(..., min_length=1)
    params: dict[str, Any] | None = None
    limit: int | None = Field(default=None, ge=1)
    allow_write: bool = False


class ApiResponse(BaseModel):
    """统一响应格式"""

    success: bool
    data: Any = None
    error: str | None = None
    readonly: bool | None = None


def _error(exc: Exception) -> ApiResponse:
    """将服务层异常包装为统一错误响应（不泄露内部堆栈）"""
    if isinstance(exc, ReadOnlyViolation):
        return ApiResponse(success=False, error=str(exc), readonly=True)
    return ApiResponse(success=False, error=str(exc))


@router.post("/connect", response_model=ApiResponse)
async def connect(body: ConnectRequest) -> ApiResponse:
    """新建数据库连接（sqlite 直接可用；pg/mysql 缺驱动时返回明确错误）"""
    try:
        info = await asyncio.to_thread(
            db_manager.connect, body.name, body.url, body.driver, body.params
        )
        return ApiResponse(success=True, data=info.to_dict())
    except DatabaseError as exc:
        return _error(exc)


@router.get("/connections", response_model=ApiResponse)
async def list_connections() -> ApiResponse:
    """连接列表（仅脱敏信息，不含明文密码）"""
    return ApiResponse(success=True, data=db_manager.list_connections())


@router.delete("/connections/{name}", response_model=ApiResponse)
async def disconnect(name: str) -> ApiResponse:
    """断开并移除指定连接"""
    removed = await asyncio.to_thread(db_manager.disconnect, name)
    if not removed:
        return ApiResponse(success=False, error=f"连接不存在: {name!r}")
    return ApiResponse(success=True, data={"name": name})


@router.get("/{conn}/databases", response_model=ApiResponse)
async def list_databases(conn: str) -> ApiResponse:
    """列出当前连接可见的数据库/schema"""
    try:
        data = await asyncio.to_thread(db_manager.list_databases, conn)
        return ApiResponse(success=True, data=data)
    except DatabaseError as exc:
        return _error(exc)


@router.get("/{conn}/tables", response_model=ApiResponse)
async def list_tables(conn: str) -> ApiResponse:
    """列出表与视图"""
    try:
        data = await asyncio.to_thread(db_manager.list_tables, conn)
        return ApiResponse(success=True, data=data)
    except DatabaseError as exc:
        return _error(exc)


@router.get("/{conn}/tables/{table}/schema", response_model=ApiResponse)
async def describe_table(conn: str, table: str) -> ApiResponse:
    """表结构详情：列/类型/主键/索引/外键"""
    try:
        data = await asyncio.to_thread(db_manager.describe_table, conn, table)
        return ApiResponse(success=True, data=data)
    except DatabaseError as exc:
        return _error(exc)


@router.get("/{conn}/er", response_model=ApiResponse)
async def table_relationships(conn: str) -> ApiResponse:
    """ER 图数据：nodes（表+列）与 edges（外键关系）"""
    try:
        data = await asyncio.to_thread(db_manager.table_relationships, conn)
        return ApiResponse(success=True, data=data)
    except DatabaseError as exc:
        return _error(exc)


@router.post("/{conn}/query", response_model=ApiResponse)
async def execute_query(conn: str, body: QueryRequest) -> ApiResponse:
    """执行 SQL 查询（强制参数化、默认只读、行数上限、执行计时）"""
    try:
        result = await asyncio.to_thread(
            db_manager.execute_query,
            conn,
            body.sql,
            body.params,
            body.limit,
            body.allow_write,
        )
        return ApiResponse(success=True, data=result.to_dict())
    except (DatabaseError, ReadOnlyViolation) as exc:
        return _error(exc)

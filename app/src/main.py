"""
FastAPI 应用入口 - Item CRUD API

启动方式:
    uvicorn src.main:app --reload

API 文档:
    http://localhost:8000/docs
    http://localhost:8000/redoc
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.database import init_db
from src.routers.items import router as item_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动时初始化数据库"""
    init_db()
    yield


app = FastAPI(
    title="Item API",
    description="Item 管理系统 - FastAPI + SQLAlchemy + SQLite",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置 - 允许所有来源（开发环境）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(item_router)


@app.get("/")
async def root():
    """API 首页"""
    return {
        "name": "Item API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok"}

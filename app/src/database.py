"""
数据库连接与会话管理
SQLAlchemy 2.0 async + sync 双模式
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# SQLite 数据库文件
DATABASE_URL = "sqlite:///./app.db"

# 创建引擎 (sync)
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite 多线程支持
    echo=True,  # 开发时开启 SQL 日志
)

# Session 工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


def get_db():
    """FastAPI 依赖: 获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """创建所有表"""
    from src.models import __all_models  # noqa: F401 - 注册模型
    Base.metadata.create_all(bind=engine)
    print("✅ 数据库表已创建")

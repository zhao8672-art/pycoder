def generate_fastapi_crud(project_dir: Path, context: dict) -> None:
    """生成 FastAPI CRUD 项目模板"""
    _write_crud_core_files(project_dir, context)
    _write_crud_models(project_dir, context)
    _write_crud_schemas(project_dir, context)
    _write_crud_routes(project_dir, context)
    _write_crud_services(project_dir, context)


def _write_crud_core_files(project_dir: Path, context: dict) -> None:
    """写入 CRUD 项目核心文件"""
    _write_crud_main(project_dir, context)
    _write_crud_database(project_dir, context)


def _write_crud_models(project_dir: Path, context: dict) -> None:
    """写入 CRUD 数据模型"""
    _write_crud_base_model(project_dir, context)
    _write_crud_item_model(project_dir, context)


def _write_crud_schemas(project_dir: Path, context: dict) -> None:
    """写入 CRUD 数据模式"""
    _write_crud_base_schema(project_dir, context)
    _write_crud_item_schema(project_dir, context)


def _write_crud_routes(project_dir: Path, context: dict) -> None:
    """写入 CRUD 路由"""
    _write_crud_item_routes(project_dir, context)


def _write_crud_services(project_dir: Path, context: dict) -> None:
    """写入 CRUD 服务"""
    _write_crud_item_service(project_dir, context)


def _write_crud_main(project_dir: Path, context: dict) -> None:
    """写入 CRUD 主应用"""
    content = f'''"""
FastAPI CRUD 项目主应用
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import items

app = FastAPI(title="{context.get('project_name', 'CRUD API')}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(items.router, prefix="/api/items", tags=["items"])


@app.get("/")
async def root():
    return {{"message": "Welcome to {context.get('project_name', 'CRUD API')}"}}
'''
    _write_file(project_dir / "main.py", content)


def _write_crud_database(project_dir: Path, context: dict) -> None:
    """写入 CRUD 数据库配置"""
    content = '''"""
数据库配置
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./crud.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''
    _write_file(project_dir / "database.py", content)


def _write_crud_base_model(project_dir: Path, context: dict) -> None:
    """写入 CRUD 基础模型"""
    content = '''"""
基础模型
"""
from sqlalchemy import Column, Integer, DateTime
from sqlalchemy.sql import func

from database import Base


class BaseModel(Base):
    __abstract__ = True

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
'''
    _write_file(project_dir / "models" / "base.py", content)


def _write_crud_item_model(project_dir: Path, context: dict) -> None:
    """写入 CRUD 条目模型"""
    content = '''"""
条目模型
"""
from sqlalchemy import Column, String, Text, Boolean

from models.base import BaseModel


class Item(BaseModel):
    __tablename__ = "items"

    title = Column(String, index=True, nullable=False)
    description = Column(Text)
    is_completed = Column(Boolean, default=False)
'''
    _write_file(project_dir / "models" / "item.py", content)


def _write_crud_base_schema(project_dir: Path, context: dict) -> None:
    """写入 CRUD 基础模式"""
    content = '''"""
基础模式
"""
from pydantic import BaseModel
from datetime import datetime


class BaseSchema(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True
'''
    _write_file(project_dir / "schemas" / "base.py", content)


def _write_crud_item_schema(project_dir: Path, context: dict) -> None:
    """写入 CRUD 条目模式"""
    content = '''"""
条目模式
"""
from pydantic import BaseModel, Field
from typing import Optional

from schemas.base import BaseSchema


class ItemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class ItemUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    is_completed: Optional[bool] = None


class ItemResponse(BaseSchema):
    title: str
    description: Optional[str] = None
    is_completed: bool = False
'''
    _write_file(project_dir / "schemas" / "item.py", content)


def _write_crud_item_routes(project_dir: Path, context: dict) -> None:
    """写入 CRUD 条目路由"""
    content = '''"""
条目路由
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.item import Item
from schemas.item import ItemCreate, ItemUpdate, ItemResponse

router = APIRouter()


@router.get("/", response_model=List[ItemResponse])
def list_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """获取条目列表"""
    items = db.query(Item).offset(skip).limit(limit).all()
    return items


@router.post("/", response_model=ItemResponse, status_code=201)
def create_item(item: ItemCreate, db: Session = Depends(get_db)):
    """创建条目"""
    db_item = Item(**item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


@router.get("/{item_id}", response_model=ItemResponse)
def get_item(item_id: int, db: Session = Depends(get_db)):
    """获取单个条目"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    return item


@router.put("/{item_id}", response_model=ItemResponse)
def update_item(item_id: int, item: ItemUpdate, db: Session = Depends(get_db)):
    """更新条目"""
    db_item = db.query(Item).filter(Item.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="条目不存在")

    for key, value in item.model_dump(exclude_unset=True).items():
        setattr(db_item, key, value)

    db.commit()
    db.refresh(db_item)
    return db_item


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db)):
    """删除条目"""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")

    db.delete(item)
    db.commit()
'''
    _write_file(project_dir / "routes" / "items.py", content)


def _write_crud_item_service(project_dir: Path, context: dict) -> None:
    """写入 CRUD 条目服务"""
    content = '''"""
条目服务
"""
from sqlalchemy.orm import Session

from models.item import Item
from schemas.item import ItemCreate, ItemUpdate


class ItemService:
    """条目服务"""

    @staticmethod
    def get_all(db: Session, skip: int = 0, limit: int = 100) -> list[Item]:
        """获取所有条目"""
        return db.query(Item).offset(skip).limit(limit).all()

    @staticmethod
    def get_by_id(db: Session, item_id: int) -> Item | None:
        """根据 ID 获取条目"""
        return db.query(Item).filter(Item.id == item_id).first()

    @staticmethod
    def create(db: Session, item_data: ItemCreate) -> Item:
        """创建条目"""
        item = Item(**item_data.model_dump())
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def update(db: Session, item_id: int, item_data: ItemUpdate) -> Item | None:
        """更新条目"""
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return None

        for key, value in item_data.model_dump(exclude_unset=True).items():
            setattr(item, key, value)

        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def delete(db: Session, item_id: int) -> bool:
        """删除条目"""
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            return False

        db.delete(item)
        db.commit()
        return True
'''
    _write_file(project_dir / "services" / "item_service.py", content)


def _write_file(path: Path, content: str) -> None:
    """写入文件并创建父目录"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
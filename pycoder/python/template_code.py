"""
代码模板生成模块

提供各类项目模板的代码生成功能。

公共 API (测试契约):
    generate_fastapi_crud(project_dir, entity_name="item") -> list[str]
    generate_fastapi_auth(project_dir, entity_name="user") -> list[str]
    generate_streamlit_dashboard(project_dir, dashboard_name="数据看板") -> list[str]
    generate_scaffold_project(project_dir, template_name="fastapi-crud",
                              entity_name="item") -> list[str]

返回值: 生成文件的相对路径列表 (POSIX 风格, 如 "src/main.py")。
"""

from __future__ import annotations

from pathlib import Path


# ── 工具函数 ──────────────────────────────────────────────


def _write_file(root: Path, rel: str, content: str) -> str:
    """写入文件并返回 POSIX 相对路径。

    Args:
        root: 项目根目录
        rel: 相对路径 (如 "src/main.py"), 可使用 `/` 或 `\\`
        content: 文件内容

    Returns:
        规范化后的 POSIX 相对路径 (统一用 `/` 分隔)
    """
    rel_posix = rel.replace("\\", "/")
    path = root / rel_posix
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return rel_posix


def _pluralize(word: str) -> str:
    """简单英文复数: item→items, product→products, user→users, category→categories."""
    if not word:
        return word
    low = word.lower()
    if low.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    if low.endswith("y") and len(low) >= 2 and low[-2] not in "aeiou":
        return word[:-1] + "ies"
    return word + "s"


def _capitalize(word: str) -> str:
    """首字母大写: item → Item, product → Product."""
    return word[:1].upper() + word[1:]


# ── FastAPI CRUD 项目模板 ─────────────────────────────────


def generate_fastapi_crud(
    project_dir: Path, entity_name: str = "item"
) -> list[str]:
    """生成 FastAPI CRUD 项目模板。

    Args:
        project_dir: 目标项目根目录
        entity_name: 实体名 (单数, 如 "item", "product", "book")

    Returns:
        生成文件的相对路径列表 (POSIX 风格)
    """
    created: list[str] = []
    created.append(_write_src_init(project_dir))
    created.append(_write_crud_database(project_dir))
    created.append(_write_crud_models_init(project_dir))
    created.append(_write_crud_model(project_dir, entity_name))
    created.append(_write_crud_schemas_init(project_dir))
    created.append(_write_crud_schema(project_dir, entity_name))
    created.append(_write_crud_routers_init(project_dir))
    created.append(_write_crud_router(project_dir, entity_name))
    created.append(_write_crud_main(project_dir, entity_name))
    created.append(_write_crud_tests_init(project_dir))
    created.append(_write_crud_test_file(project_dir, entity_name))
    created.append(_write_crud_requirements(project_dir))
    created.append(_write_crud_readme(project_dir, entity_name))
    return created


def _write_src_init(project_dir: Path) -> str:
    return _write_file(project_dir, "src/__init__.py", '"""应用包"""\n')


def _write_crud_database(project_dir: Path) -> str:
    content = '''"""数据库连接与会话管理"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./app.db"

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI 依赖: 提供数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''
    return _write_file(project_dir, "src/database.py", content)


def _write_crud_models_init(project_dir: Path) -> str:
    return _write_file(project_dir, "src/models/__init__.py", "")


def _write_crud_model(project_dir: Path, entity_name: str) -> str:
    Entity = _capitalize(entity_name)
    table = _pluralize(entity_name.lower())
    content = f'''"""{Entity} 数据模型"""
from sqlalchemy import Column, Integer, String, DateTime

from src.database import Base


class {Entity}Model(Base):
    """{Entity} ORM 模型"""

    __tablename__ = "{table}"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False, index=True)
    description = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=__import__("datetime").datetime.utcnow)

    def __repr__(self) -> str:
        return f"<{Entity}Model(id={{self.id}}, name={{self.name}})>"
'''
    return _write_file(project_dir, f"src/models/{entity_name}.py", content)


def _write_crud_schemas_init(project_dir: Path) -> str:
    return _write_file(project_dir, "src/schemas/__init__.py", "")


def _write_crud_schema(project_dir: Path, entity_name: str) -> str:
    Entity = _capitalize(entity_name)
    content = f'''"""{Entity} Pydantic Schema"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class {Entity}Base(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: Optional[str] = Field(None, max_length=256)


class {Entity}Create({Entity}Base):
    """创建请求体"""
    pass


class {Entity}Update(BaseModel):
    """更新请求体 (所有字段可选)"""
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    description: Optional[str] = Field(None, max_length=256)


class {Entity}Response({Entity}Base):
    """响应模型 (含 id 与时间戳)"""
    id: int
    created_at: datetime

    model_config = {{"from_attributes": True}}


class PaginatedResponse(BaseModel):
    """分页响应"""
    items: list[{Entity}Response]
    total: int
    page: int
    page_size: int
'''
    return _write_file(project_dir, f"src/schemas/{entity_name}.py", content)


def _write_crud_routers_init(project_dir: Path) -> str:
    return _write_file(project_dir, "src/routers/__init__.py", "")


def _write_crud_router(project_dir: Path, entity_name: str) -> str:
    Entity = _capitalize(entity_name)
    plural = _pluralize(entity_name.lower())
    content = f'''"""{Entity} 路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.database import get_db
from src.models.{entity_name} import {Entity}Model
from src.schemas.{entity_name} import (
    {Entity}Create,
    {Entity}Response,
    {Entity}Update,
    PaginatedResponse,
)

router = APIRouter()


@router.get("/", response_model=PaginatedResponse)
async def list_{plural}(
    page: int = 1, page_size: int = 20, db: Session = Depends(get_db)
):
    """获取 {Entity} 列表 (分页)"""
    offset = (page - 1) * page_size
    items = db.query({Entity}Model).offset(offset).limit(page_size).all()
    total = db.query({Entity}Model).count()
    return PaginatedResponse(
        items=items, total=total, page=page, page_size=page_size
    )


@router.get("/{{{entity_name}_id}}", response_model={Entity}Response)
async def get_{entity_name}({entity_name}_id: int, db: Session = Depends(get_db)):
    """获取单个 {Entity}"""
    item = db.query({Entity}Model).filter({Entity}Model.id == {entity_name}_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="{Entity} not found")
    return item


@router.post("/", response_model={Entity}Response, status_code=201)
async def create_{entity_name}(payload: {Entity}Create, db: Session = Depends(get_db)):
    """创建 {Entity}"""
    item = {Entity}Model(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{{{entity_name}_id}}", response_model={Entity}Response)
async def update_{entity_name}(
    {entity_name}_id: int, payload: {Entity}Update, db: Session = Depends(get_db)
):
    """更新 {Entity}"""
    item = db.query({Entity}Model).filter({Entity}Model.id == {entity_name}_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="{Entity} not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/{{{entity_name}_id}}", status_code=204)
async def delete_{entity_name}({entity_name}_id: int, db: Session = Depends(get_db)):
    """删除 {Entity}"""
    item = db.query({Entity}Model).filter({Entity}Model.id == {entity_name}_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="{Entity} not found")
    db.delete(item)
    db.commit()
'''
    return _write_file(project_dir, f"src/routers/{plural}.py", content)


def _write_crud_main(project_dir: Path, entity_name: str) -> str:
    Entity = _capitalize(entity_name)
    plural = _pluralize(entity_name.lower())
    content = f'''"""FastAPI {Entity} API 主入口"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.database import Base, engine
from src.routers import {plural}

# 自动建表 (开发环境用)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="{Entity} API",
    description="{Entity} CRUD REST API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """健康检查"""
    return {{"status": "ok", "service": "{Entity} API"}}


app.include_router({plural}.router, prefix="/api/{plural}", tags=["{plural}"])
'''
    return _write_file(project_dir, "src/main.py", content)


def _write_crud_tests_init(project_dir: Path) -> str:
    return _write_file(project_dir, "tests/__init__.py", "")


def _write_crud_test_file(project_dir: Path, entity_name: str) -> str:
    Entity = _capitalize(entity_name)
    plural = _pluralize(entity_name.lower())
    content = f'''"""{Entity} API 自动化测试"""
import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    """健康检查端点"""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_{entity_name}(client):
    """创建 {Entity}"""
    resp = client.post(f"/api/{plural}/", json={{"name": "test-{entity_name}"}})
    assert resp.status_code == 201
    assert resp.json()["name"] == "test-{entity_name}"


def test_list_{plural}(client):
    """获取 {Entity} 列表"""
    resp = client.get("/api/{plural}/")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
'''
    return _write_file(project_dir, f"tests/test_{plural}.py", content)


def _write_crud_requirements(project_dir: Path) -> str:
    content = (
        "fastapi>=0.115.0\n"
        "uvicorn[standard]>=0.34.0\n"
        "sqlalchemy>=2.0\n"
        "pydantic>=2.0\n"
    )
    return _write_file(project_dir, "requirements.txt", content)


def _write_crud_readme(project_dir: Path, entity_name: str) -> str:
    Entity = _capitalize(entity_name)
    content = f'''# {Entity} API

基于 FastAPI 的 {Entity} CRUD REST API 项目。

## 快速开始

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload
```

访问 http://localhost:8000/docs 查看 API 文档。

## API 端点

- `GET    /api/{_pluralize(entity_name)}/`       — 分页列表
- `GET    /api/{_pluralize(entity_name)}/{{id}}`  — 单个 {Entity}
- `POST   /api/{_pluralize(entity_name)}/`       — 创建
- `PUT    /api/{_pluralize(entity_name)}/{{id}}`  — 更新
- `DELETE /api/{_pluralize(entity_name)}/{{id}}`  — 删除

## 运行测试

```bash
pytest tests/ -v
```
'''
    return _write_file(project_dir, "README.md", content)


# ── FastAPI 认证项目模板 ─────────────────────────────────


def generate_fastapi_auth(
    project_dir: Path, entity_name: str = "user"
) -> list[str]:
    """生成 FastAPI JWT 认证项目模板。

    Args:
        project_dir: 目标项目根目录
        entity_name: 用户实体名 (默认 "user")

    Returns:
        生成文件的相对路径列表
    """
    created: list[str] = []
    created.append(_write_src_init(project_dir))
    created.append(_write_auth_config(project_dir))
    created.append(_write_auth_database(project_dir))
    created.append(_write_crud_models_init(project_dir))
    created.append(_write_auth_user_model(project_dir))
    created.append(_write_crud_schemas_init(project_dir))
    created.append(_write_auth_user_schema(project_dir))
    created.append(_write_auth_service(project_dir))
    created.append(_write_crud_routers_init(project_dir))
    created.append(_write_auth_router(project_dir))
    created.append(_write_auth_main(project_dir))
    created.append(_write_auth_env(project_dir))
    created.append(_write_crud_tests_init(project_dir))
    created.append(_write_auth_test_file(project_dir))
    created.append(_write_auth_requirements(project_dir))
    created.append(_write_auth_readme(project_dir))
    return created


def _write_auth_config(project_dir: Path) -> str:
    content = '''"""应用配置 (从环境变量读取)"""
import os

SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
    os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
)
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./auth.db")
'''
    return _write_file(project_dir, "src/config.py", content)


def _write_auth_database(project_dir: Path) -> str:
    content = '''"""数据库连接"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from src.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
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
    return _write_file(project_dir, "src/database.py", content)


def _write_auth_user_model(project_dir: Path) -> str:
    content = '''"""User 数据模型"""
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from src.database import Base


class User(Base):
    """用户表"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128), unique=True, nullable=False, index=True)
    hashed_password = Column(String(256), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=__import__("datetime").datetime.utcnow)
'''
    return _write_file(project_dir, "src/models/user.py", content)


def _write_auth_user_schema(project_dir: Path) -> str:
    content = '''"""User Pydantic Schema"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: EmailStr


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)


class UserResponse(UserBase):
    id: int
    is_active: bool
    is_superuser: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None
'''
    return _write_file(project_dir, "src/schemas/user.py", content)


def _write_auth_service(project_dir: Path) -> str:
    """JWT 认证服务 (核心: 验证/哈希/Token 生成/当前用户提取)。"""
    content = '''"""认证服务: 密码哈希 + JWT Token"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from src.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, SECRET_KEY
from src.database import get_db
from src.models.user import User
from src.schemas.user import TokenData

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与哈希是否匹配"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """生成密码哈希"""
    return pwd_context.hash(password)


def authenticate_user(
    db: Session, username: str, password: str
) -> Optional[User]:
    """根据用户名+密码验证用户"""
    user = db.query(User).filter(User.username == username).first()
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(
    data: dict, expires_delta: Optional[timedelta] = None
) -> str:
    """生成 JWT access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """从 JWT Token 解析当前用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    user = (
        db.query(User)
        .filter(User.username == token_data.username)
        .first()
    )
    if user is None:
        raise credentials_exception
    return user
'''
    return _write_file(project_dir, "src/auth.py", content)


def _write_auth_router(project_dir: Path) -> str:
    content = '''"""认证路由: 注册 / 登录 / 当前用户"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from src.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    get_password_hash,
)
from src.database import get_db
from src.models.user import User
from src.schemas.user import Token, UserCreate, UserResponse

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(payload: UserCreate, db: Session = Depends(get_db)):
    """用户注册"""
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """用户登录 (返回 JWT)"""
    user = authenticate_user(db, form.username, form.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username})
    return Token(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return current_user
'''
    return _write_file(project_dir, "src/routers/auth.py", content)


def _write_auth_main(project_dir: Path) -> str:
    content = '''"""FastAPI 认证项目主应用"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.database import Base, engine
from src.routers import auth

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Auth API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Welcome to Auth API"}


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
'''
    return _write_file(project_dir, "src/main.py", content)


def _write_auth_env(project_dir: Path) -> str:
    content = (
        'SECRET_KEY=change-me-in-production\n'
        'DATABASE_URL=sqlite:///./auth.db\n'
        'JWT_ALGORITHM=HS256\n'
        'ACCESS_TOKEN_EXPIRE_MINUTES=30\n'
    )
    return _write_file(project_dir, ".env", content)


def _write_auth_test_file(project_dir: Path) -> str:
    content = '''"""认证 API 测试"""
import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_register_and_login(client):
    # 注册
    resp = client.post(
        "/api/auth/register",
        json={
            "username": "alice",
            "email": "alice@example.com",
            "password": "secret-password-123",
        },
    )
    assert resp.status_code == 201
    # 登录
    resp = client.post(
        "/api/auth/login",
        data={"username": "alice", "password": "secret-password-123"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_me_unauthorized(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
'''
    return _write_file(project_dir, "tests/test_auth.py", content)


def _write_auth_requirements(project_dir: Path) -> str:
    content = (
        "fastapi>=0.115.0\n"
        "uvicorn[standard]>=0.34.0\n"
        "sqlalchemy>=2.0\n"
        "pydantic>=2.0\n"
        "pydantic[email]>=2.0\n"
        "python-jose[cryptography]>=3.3\n"
        "passlib[bcrypt]>=1.7\n"
        "python-multipart>=0.0.9\n"
    )
    return _write_file(project_dir, "requirements.txt", content)


def _write_auth_readme(project_dir: Path) -> str:
    content = '''# Auth API

基于 FastAPI 的 JWT 认证项目 (注册/登录/当前用户)。

## 快速开始

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload
```

## API

- `POST /api/auth/register` — 注册
- `POST /api/auth/login`    — 登录 (返回 JWT)
- `GET  /api/auth/me`       — 当前登录用户 (需 Bearer Token)

## 测试

```bash
pytest tests/ -v
```
'''
    return _write_file(project_dir, "README.md", content)


# ── Streamlit 数据看板模板 ───────────────────────────────


def generate_streamlit_dashboard(
    project_dir: Path, dashboard_name: str = "数据看板"
) -> list[str]:
    """生成 Streamlit 数据看板项目模板。

    Args:
        project_dir: 目标项目根目录
        dashboard_name: 看板标题 (默认 "数据看板")

    Returns:
        生成文件的相对路径列表
    """
    created: list[str] = []
    created.append(_write_streamlit_app(project_dir, dashboard_name))
    created.append(_write_streamlit_analysis_page(project_dir))
    created.append(_write_streamlit_requirements(project_dir))
    created.append(_write_streamlit_readme(project_dir, dashboard_name))
    return created


def _write_streamlit_app(project_dir: Path, dashboard_name: str) -> str:
    content = f'''"""Streamlit 主应用: {dashboard_name}"""
import streamlit as st
import pandas as pd
import numpy as np


st.set_page_config(
    page_title="{dashboard_name}",
    page_icon="📊",
    layout="wide",
)

st.title("{dashboard_name}")
st.markdown("基于 Streamlit 的数据可视化看板示例。")

# 生成示例数据
np.random.seed(42)
data = pd.DataFrame(
    {{
        "日期": pd.date_range("2026-01-01", periods=30),
        "销售额": np.random.randint(100, 1000, size=30),
        "访问量": np.random.randint(500, 5000, size=30),
    }}
)

# 关键指标
col1, col2, col3 = st.columns(3)
col1.metric("总销售额", f"{{data['销售额'].sum()}} 元")
col2.metric("总访问量", f"{{data['访问量'].sum()}}")
col3.metric("平均转化率", f"{{data['销售额'].sum() / data['访问量'].sum():.2%}}")

# 趋势图
st.subheader("趋势")
st.line_chart(data.set_index("日期"))

# 原始数据
st.subheader("原始数据")
st.dataframe(data)
'''
    return _write_file(project_dir, "app.py", content)


def _write_streamlit_analysis_page(project_dir: Path) -> str:
    content = '''"""数据分析页 — 上传 CSV 进行分析"""
import streamlit as st
import pandas as pd

st.set_page_config(page_title="数据分析", page_icon="🔬", layout="wide")
st.title("数据分析")
st.markdown("上传 CSV 文件进行交互式数据分析。")

uploaded = st.file_uploader("选择 CSV 文件", type=["csv"])
if uploaded is not None:
    df = pd.read_csv(uploaded)
    st.subheader("数据预览")
    st.dataframe(df.head())

    st.subheader("描述统计")
    st.write(df.describe())

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        col = st.selectbox("选择列进行可视化", numeric_cols)
        st.bar_chart(df[col])
else:
    st.info("请上传 CSV 文件以开始分析。")
'''
    return _write_file(project_dir, "pages/analysis.py", content)


def _write_streamlit_requirements(project_dir: Path) -> str:
    content = (
        "streamlit>=1.30\n"
        "pandas>=2.0\n"
        "numpy>=1.24\n"
        "plotly>=5.18\n"
    )
    return _write_file(project_dir, "requirements.txt", content)


def _write_streamlit_readme(project_dir: Path, dashboard_name: str) -> str:
    content = f'''# {dashboard_name}

基于 Streamlit 的数据看板示例项目。

## 快速开始

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 页面

- `app.py`             — 主看板
- `pages/analysis.py`  — 数据分析 (上传 CSV)
'''
    return _write_file(project_dir, "README.md", content)


# ── 统一脚手架入口 ───────────────────────────────────────


def generate_scaffold_project(
    project_dir: Path,
    template_name: str = "fastapi-crud",
    entity_name: str = "item",
) -> list[str]:
    """根据模板名一键生成项目结构 (统一入口)。

    Args:
        project_dir: 目标项目根目录
        template_name: 模板名 (fastapi-crud / fastapi-auth /
                       streamlit-dashboard); 未知则回退到 fastapi-crud
        entity_name: 实体名 (仅对 fastapi-crud / fastapi-auth 有效)

    Returns:
        生成文件的相对路径列表
    """
    name = (template_name or "fastapi-crud").lower().strip()
    if name in ("fastapi-auth", "auth", "fastapi-jwt", "fastapi-jwt-auth"):
        return generate_fastapi_auth(project_dir, entity_name="user")
    if name in (
        "streamlit-dashboard",
        "streamlit",
        "dashboard",
        "数据看板",
    ):
        return generate_streamlit_dashboard(project_dir)
    # 默认 / 未知模板 → fastapi-crud
    return generate_fastapi_crud(project_dir, entity_name=entity_name)


__all__ = [
    "generate_fastapi_auth",
    "generate_fastapi_crud",
    "generate_scaffold_project",
    "generate_streamlit_dashboard",
]

"""项目模板代码生成 — FastAPI CRUD / Auth / Streamlit Dashboard / Scaffold

提供:
- generate_fastapi_crud: 生成 FastAPI CRUD 项目
- generate_fastapi_auth: 生成 FastAPI 认证系统项目
- generate_streamlit_dashboard: 生成 Streamlit 数据看板
- generate_scaffold_project: 根据模板名分发到对应生成器
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════
# 公共 API — 生成器函数（写入磁盘，返回文件路径列表）
# ══════════════════════════════════════════════════════════


def generate_fastapi_crud(target_dir: Path, entity_name: str = "item") -> list[str]:
    """生成 FastAPI CRUD 项目脚手架

    Args:
        target_dir: 目标目录
        entity_name: 实体名称（默认 "item"）

    Returns:
        生成的文件相对路径列表
    """
    target_dir = Path(target_dir)
    entity_cap = entity_name.capitalize()
    entity_plural = entity_name + "s"

    files: dict[str, str] = {}

    # __init__.py 文件
    files["src/__init__.py"] = ""
    files["src/models/__init__.py"] = ""
    files["src/routers/__init__.py"] = ""
    files["src/schemas/__init__.py"] = ""
    files["tests/__init__.py"] = ""

    # database.py
    files["src/database.py"] = '''"""数据库连接"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./app.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''

    # models/{entity}.py
    files[f"src/models/{entity_name}.py"] = f'''"""{entity_cap} 模型"""
from sqlalchemy import Column, Integer, String, Float, DateTime
from src.database import Base
from datetime import datetime


class {entity_cap}Model(Base):
    __tablename__ = "{entity_plural}"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(String(500), nullable=True)
    price = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
'''

    # schemas/{entity}.py
    files[f"src/schemas/{entity_name}.py"] = f'''"""{entity_cap} Schema"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class {entity_cap}Create(BaseModel):
    name: str
    description: Optional[str] = None
    price: float = 0.0


class {entity_cap}Update(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None


class {entity_cap}Response(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    price: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    size: int
    pages: int
'''

    # routers/{entity_plural}.py
    files[f"src/routers/{entity_plural}.py"] = f'''"""{entity_cap} 路由"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from src.database import get_db
from src.models.{entity_name} import {entity_cap}Model
from src.schemas.{entity_name} import {entity_cap}Create, {entity_cap}Update, {entity_cap}Response

router = APIRouter(prefix="/{entity_plural}", tags=["{entity_plural}"])


@router.get("/", response_model=List[{entity_cap}Response])
def list_{entity_plural}(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query({entity_cap}Model).offset(skip).limit(limit).all()


@router.get("/{{item_id}}", response_model={entity_cap}Response)
def get_{entity_name}(item_id: int, db: Session = Depends(get_db)):
    item = db.query({entity_cap}Model).filter({entity_cap}Model.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="{entity_cap} not found")
    return item


@router.post("/", response_model={entity_cap}Response, status_code=201)
def create_{entity_name}(item: {entity_cap}Create, db: Session = Depends(get_db)):
    db_item = {entity_cap}Model(**item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


@router.put("/{{item_id}}", response_model={entity_cap}Response)
def update_{entity_name}(item_id: int, item: {entity_cap}Update, db: Session = Depends(get_db)):
    db_item = db.query({entity_cap}Model).filter({entity_cap}Model.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="{entity_cap} not found")
    for key, value in item.model_dump(exclude_unset=True).items():
        setattr(db_item, key, value)
    db.commit()
    db.refresh(db_item)
    return db_item


@router.delete("/{{item_id}}")
def delete_{entity_name}(item_id: int, db: Session = Depends(get_db)):
    db_item = db.query({entity_cap}Model).filter({entity_cap}Model.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="{entity_cap} not found")
    db.delete(db_item)
    db.commit()
    return {{"message": "{entity_cap} deleted"}}
'''

    # main.py
    files["src/main.py"] = f'''"""{entity_cap} API — FastAPI 应用入口"""
from fastapi import FastAPI
from src.database import engine, Base
from src.routers import {entity_plural}

Base.metadata.create_all(bind=engine)

app = FastAPI(title="{entity_cap} API", version="1.0.0")
app.include_router({entity_plural}.router, prefix="/api")


@app.get("/health")
def health():
    return {{"status": "ok"}}
'''

    # tests/test_{entity_plural}.py
    files[f"tests/test_{entity_plural}.py"] = f'''"""{entity_cap} API 测试"""
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {{"status": "ok"}}


def test_create_{entity_name}():
    response = client.post("/api/{entity_plural}/", json={{"name": "Test {entity_cap}", "price": 9.99}})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test {entity_cap}"
    return data["id"]


def test_list_{entity_plural}():
    response = client.get("/api/{entity_plural}/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
'''

    # requirements.txt
    files["requirements.txt"] = """fastapi>=0.100.0
uvicorn[standard]>=0.22.0
sqlalchemy>=2.0.0
pydantic>=2.0.0
pytest>=7.0.0
httpx>=0.24.0
"""

    # README.md
    files["README.md"] = f"""# {entity_cap} API

基于 FastAPI 的 {entity_cap} CRUD REST API。

## 启动

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload
```

## API 文档

- Swagger: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
"""

    # 写入所有文件
    return _write_files(target_dir, files)


def generate_fastapi_auth(target_dir: Path) -> list[str]:
    """生成 FastAPI 认证系统项目脚手架

    Args:
        target_dir: 目标目录

    Returns:
        生成的文件相对路径列表
    """
    target_dir = Path(target_dir)
    files: dict[str, str] = {}

    # __init__.py 文件
    files["src/__init__.py"] = ""
    files["src/models/__init__.py"] = ""
    files["src/routers/__init__.py"] = ""
    files["src/schemas/__init__.py"] = ""
    files["tests/__init__.py"] = ""

    # config.py
    files["src/config.py"] = '''"""应用配置"""
import os

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")
'''

    # database.py
    files["src/database.py"] = '''"""数据库连接"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from src.config import DATABASE_URL

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''

    # models/user.py
    files["src/models/user.py"] = '''"""User 模型"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from src.database import Base
from datetime import datetime


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
'''

    # schemas/user.py
    files["src/schemas/user.py"] = '''"""User Schema"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str
'''

    # auth.py
    files["src/auth.py"] = '''"""认证工具函数"""
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from src.config import SECRET_KEY, ALGORITHM

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """获取密码哈希"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=30))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str):
    """获取当前用户（简化版）"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
'''

    # routers/auth.py
    files["src/routers/auth.py"] = '''"""认证路由"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from src.database import get_db
from src.models.user import User
from src.schemas.user import UserCreate, UserResponse, Token, LoginRequest
from src.auth import verify_password, get_password_hash, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=UserResponse, status_code=201)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """用户注册"""
    existing = db.query(User).filter(
        (User.username == user_data.username) | (User.email == user_data.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名或邮箱已存在")
    user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(login_data: LoginRequest, db: Session = Depends(get_db)):
    """用户登录"""
    user = db.query(User).filter(User.username == login_data.username).first()
    if not user or not verify_password(login_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
def get_me(token: str = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取当前用户信息"""
    payload = get_current_user(token)
    if not payload:
        raise HTTPException(status_code=401, detail="无效令牌")
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user
'''

    # main.py
    files["src/main.py"] = '''"""FastAPI 认证系统入口"""
from fastapi import FastAPI
from src.database import engine, Base
from src.routers import auth

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Auth API", version="1.0.0")
app.include_router(auth.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
'''

    # .env
    files[".env"] = """SECRET_KEY=dev-secret-key-change-in-production
DATABASE_URL=sqlite:///./app.db
"""

    # tests/test_auth.py
    files["tests/test_auth.py"] = '''"""认证 API 测试"""
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_register():
    response = client.post("/api/auth/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpass123",
    })
    assert response.status_code == 201


def test_login():
    response = client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "testpass123",
    })
    assert response.status_code == 200
    assert "access_token" in response.json()
'''

    # requirements.txt
    files["requirements.txt"] = """fastapi>=0.100.0
uvicorn[standard]>=0.22.0
sqlalchemy>=2.0.0
pydantic>=2.0.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.6
pytest>=7.0.0
httpx>=0.24.0
"""

    # README.md
    files["README.md"] = """# Auth API

基于 FastAPI 的 JWT 认证系统。

## 启动

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload
```
"""

    return _write_files(target_dir, files)


def generate_streamlit_dashboard(target_dir: Path) -> list[str]:
    """生成 Streamlit 数据看板项目脚手架

    Args:
        target_dir: 目标目录

    Returns:
        生成的文件相对路径列表
    """
    target_dir = Path(target_dir)
    files: dict[str, str] = {}

    # app.py
    files["app.py"] = '''"""Streamlit 数据看板"""
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="数据看板", layout="wide")
st.title("📊 数据看板")

st.sidebar.header("导航")
page = st.sidebar.radio("选择页面", ["概览", "数据分析"])

if page == "概览":
    st.header("概览")
    st.metric("总数据量", 1000)
    st.metric("今日新增", 50)
elif page == "数据分析":
    st.header("数据分析")
    st.write("请上传数据文件进行分析")
'''

    # pages/analysis.py
    files["pages/analysis.py"] = '''"""数据分析页面"""
import streamlit as st
import pandas as pd

st.title("📈 数据分析")

uploaded_file = st.file_uploader("上传 CSV 文件", type=["csv"])
if uploaded_file:
    df = pd.read_csv(uploaded_file)
    st.dataframe(df)
    st.line_chart(df.select_dtypes(include=["number"]))
'''

    # requirements.txt
    files["requirements.txt"] = """streamlit>=1.25.0
pandas>=2.0.0
numpy>=1.24.0
"""

    # README.md
    files["README.md"] = """# Streamlit 数据看板

基于 Streamlit 的数据可视化看板。

## 启动

```bash
pip install -r requirements.txt
streamlit run app.py
```
"""

    return _write_files(target_dir, files)


def generate_scaffold_project(
    target_dir: Path,
    template_name: str = "fastapi-crud",
    entity_name: str = "item",
) -> list[str]:
    """根据模板名分发到对应生成器

    Args:
        target_dir: 目标目录
        template_name: 模板名称（fastapi-crud / fastapi-auth / streamlit-dashboard）
        entity_name: 实体名称（默认 "item"）

    Returns:
        生成的文件相对路径列表
    """
    target_dir = Path(target_dir)

    if template_name == "fastapi-crud":
        return generate_fastapi_crud(target_dir, entity_name)
    elif template_name == "fastapi-auth":
        return generate_fastapi_auth(target_dir)
    elif template_name == "streamlit-dashboard":
        return generate_streamlit_dashboard(target_dir)
    else:
        # 未知模板回退到 fastapi-crud
        return generate_fastapi_crud(target_dir, entity_name)


# ══════════════════════════════════════════════════════════
# 内部辅助
# ══════════════════════════════════════════════════════════


def _write_files(target_dir: Path, files: dict[str, str]) -> list[str]:
    """将文件字典写入磁盘

    Args:
        target_dir: 目标目录
        files: {相对路径: 内容} 字典

    Returns:
        已写入的文件路径列表
    """
    created: list[str] = []
    for rel_path, content in files.items():
        full_path = target_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        created.append(rel_path)
    return created


def _generate_fastapi_auth_code(
    *,
    use_async: bool = True,
    use_sqlalchemy: bool = True,
    include_oauth2: bool = True,
    include_refresh_token: bool = True,
    include_email_verification: bool = False,
    include_password_reset: bool = False,
    include_two_factor: bool = False,
    include_social_login: bool = False,
    output_dir: str = ".",
) -> dict[str, str]:
    """生成 FastAPI 认证系统完整代码（高级版，返回代码字典）

    Args:
        use_async: 是否使用异步
        use_sqlalchemy: 是否使用 SQLAlchemy
        include_oauth2: 是否包含 OAuth2
        include_refresh_token: 是否包含刷新令牌
        include_email_verification: 是否包含邮箱验证
        include_password_reset: 是否包含密码重置
        include_two_factor: 是否包含双因素认证
        include_social_login: 是否包含社交登录
        output_dir: 输出目录

    Returns:
        {文件名: 代码内容} 字典
    """
    files = {}

    # 生成各层代码
    files.update(_generate_auth_models(use_sqlalchemy, include_email_verification, include_two_factor))
    files.update(_generate_auth_schemas(include_refresh_token, include_email_verification, include_password_reset, include_two_factor))
    files.update(_generate_auth_utils(use_async, include_refresh_token))
    files.update(_generate_auth_service(use_async, include_refresh_token, include_email_verification, include_password_reset, include_two_factor))
    files.update(_generate_auth_router(use_async, include_oauth2, include_refresh_token, include_email_verification, include_password_reset, include_two_factor, include_social_login))
    files.update(_generate_auth_dependencies(use_async))
    files.update(_generate_auth_init())

    return files


def _generate_auth_models(
    use_sqlalchemy: bool,
    include_email_verification: bool,
    include_two_factor: bool,
) -> dict[str, str]:
    """生成认证模型"""
    if not use_sqlalchemy:
        return {}

    code = '''"""
认证模型
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """用户模型"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
'''

    if include_email_verification:
        code += """
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verification_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_verification_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
"""

    if include_two_factor:
        code += """
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    two_factor_secret: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    backup_codes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
"""

    code += '''
    # 关系
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
'''

    if include_email_verification:
        code += """
    @property
    def is_email_verified(self) -> bool:
        return self.email_verified
"""

    code += '''
    def __repr__(self) -> str:
        return f"<User {self.username}>"


class RefreshToken(Base):
    """刷新令牌模型"""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # 关系
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and not self.is_expired
'''

    return {"models.py": code}


def _generate_auth_schemas(
    include_refresh_token: bool,
    include_email_verification: bool,
    include_password_reset: bool,
    include_two_factor: bool,
) -> dict[str, str]:
    """生成认证 Schema"""
    code = '''"""
认证 Schema
"""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field, EmailStr, validator


class Token(BaseModel):
    """令牌响应"""
    access_token: str
    token_type: str = "bearer"
'''

    if include_refresh_token:
        code += """    refresh_token: Optional[str] = None
"""

    code += '''

class TokenPayload(BaseModel):
    """令牌载荷"""
    sub: str
    exp: int
    type: str = "access"


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)


class RegisterRequest(BaseModel):
    """注册请求"""
    username: str = Field(..., min_length=3, max_length=50, pattern="^[a-zA-Z0-9_]+$")
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)
    full_name: Optional[str] = Field(None, max_length=100)

    @validator("username")
    def validate_username(cls, v):
        if not v.isalnum() and "_" not in v:
            raise ValueError("用户名只能包含字母、数字和下划线")
        return v


class UserResponse(BaseModel):
    """用户响应"""
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    is_superuser: bool
    created_at: datetime
'''

    if include_email_verification:
        code += """    email_verified: bool = False
"""

    if include_two_factor:
        code += """    two_factor_enabled: bool = False
"""

    code += '''
    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """用户信息更新"""
    full_name: Optional[str] = Field(None, max_length=100)
    email: Optional[EmailStr] = None
'''

    if include_email_verification:
        code += '''

class EmailVerificationRequest(BaseModel):
    """邮箱验证请求"""
    token: str


class ResendVerificationRequest(BaseModel):
    """重新发送验证邮件请求"""
    email: EmailStr
'''

    if include_password_reset:
        code += '''

class PasswordResetRequest(BaseModel):
    """密码重置请求"""
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """密码重置确认"""
    token: str
    new_password: str = Field(..., min_length=6, max_length=128)
'''

    if include_two_factor:
        code += '''

class TwoFactorSetupResponse(BaseModel):
    """双因素认证设置响应"""
    secret: str
    qr_code_url: str


class TwoFactorVerifyRequest(BaseModel):
    """双因素认证验证请求"""
    code: str = Field(..., min_length=6, max_length=6)


class TwoFactorLoginRequest(BaseModel):
    """双因素登录请求"""
    username: str
    password: str
    two_factor_code: str = Field(..., min_length=6, max_length=6)
'''

    return {"schemas.py": code}


def _generate_auth_utils(
    use_async: bool,
    include_refresh_token: bool,
) -> dict[str, str]:
    """生成认证工具函数"""
    code = '''"""
认证工具函数
"""

from datetime import datetime, timedelta
from typing import Optional, Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """获取密码哈希"""
    return pwd_context.hash(password)


def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """创建访问令牌"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "type": "access",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
'''

    if include_refresh_token:
        code += '''

def create_refresh_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """创建刷新令牌"""
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "type": "refresh",
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
'''

    code += '''

def decode_token(token: str) -> Optional[dict[str, Any]]:
    """解码令牌"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def generate_reset_token() -> str:
    """生成重置令牌"""
    import secrets
    return secrets.token_urlsafe(32)


def generate_verification_token() -> str:
    """生成验证令牌"""
    import secrets
    return secrets.token_urlsafe(32)
'''

    return {"utils.py": code}


def _generate_auth_service(
    use_async: bool,
    include_refresh_token: bool,
    include_email_verification: bool,
    include_password_reset: bool,
    include_two_factor: bool,
) -> dict[str, str]:
    """生成认证服务"""
    code = '''"""
认证服务
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import User, RefreshToken
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    UserResponse,
    Token,
)
from app.utils.auth import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_reset_token,
    generate_verification_token,
)
from app.core.config import settings


class AuthService:
    """认证服务"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(self, request: RegisterRequest) -> UserResponse:
        """用户注册"""
        # 检查用户名是否已存在
        query = select(User).where(User.username == request.username)
        result = await self.db.execute(query)
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在",
            )

        # 检查邮箱是否已存在
        query = select(User).where(User.email == request.email)
        result = await self.db.execute(query)
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="邮箱已被注册",
            )

        # 创建用户
        user = User(
            username=request.username,
            email=request.email,
            hashed_password=get_password_hash(request.password),
            full_name=request.full_name,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        return UserResponse.model_validate(user)

    async def login(self, request: LoginRequest) -> Token:
        """用户登录"""
        # 查找用户
        query = select(User).where(User.username == request.username)
        result = await self.db.execute(query)
        user = result.scalar_one_or_none()

        if not user or not verify_password(request.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="账户已被禁用",
            )

        # 创建令牌
        access_token = create_access_token(subject=str(user.id))
'''

    if include_refresh_token:
        code += """
        refresh_token = create_refresh_token(subject=str(user.id))

        # 保存刷新令牌
        db_refresh_token = RefreshToken(
            token=refresh_token,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        self.db.add(db_refresh_token)
        await self.db.commit()

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
        )
"""
    else:
        code += """
        return Token(access_token=access_token)
"""

    if include_refresh_token:
        code += """
    async def refresh(self, refresh_token: str) -> Token:
        \"\"\"刷新令牌\"\"\"
        # 验证刷新令牌
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="无效的刷新令牌",
            )

        # 查找数据库中的令牌
        query = select(RefreshToken).where(
            RefreshToken.token == refresh_token,
            RefreshToken.is_revoked == False,
        )
        result = await self.db.execute(query)
        db_token = result.scalar_one_or_none()

        if not db_token or db_token.is_expired:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="刷新令牌已过期或已撤销",
            )

        # 撤销旧令牌
        db_token.is_revoked = True

        # 创建新令牌
        user_id = payload["sub"]
        new_access_token = create_access_token(subject=user_id)
        new_refresh_token = create_refresh_token(subject=user_id)

        # 保存新刷新令牌
        new_db_token = RefreshToken(
            token=new_refresh_token,
            user_id=int(user_id),
            expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        )
        self.db.add(new_db_token)
        await self.db.commit()

        return Token(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
        )

    async def logout(self, refresh_token: str) -> None:
        \"\"\"登出 - 撤销刷新令牌\"\"\"
        query = select(RefreshToken).where(RefreshToken.token == refresh_token)
        result = await self.db.execute(query)
        db_token = result.scalar_one_or_none()

        if db_token:
            db_token.is_revoked = True
            await self.db.commit()
"""

    if include_email_verification:
        code += """
    async def send_verification_email(self, user_id: int) -> None:
        \"\"\"发送验证邮件\"\"\"
        query = select(User).where(User.id == user_id)
        result = await self.db.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if user.email_verified:
            raise HTTPException(status_code=400, detail="邮箱已验证")

        token = generate_verification_token()
        user.email_verification_token = token
        user.email_verification_sent_at = datetime.utcnow()
        await self.db.commit()

        # TODO: 发送邮件
        # await send_email(user.email, "验证邮箱", f"验证链接: ...")

    async def verify_email(self, token: str) -> None:
        \"\"\"验证邮箱\"\"\"
        query = select(User).where(User.email_verification_token == token)
        result = await self.db.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=400, detail="无效的验证令牌")

        user.email_verified = True
        user.email_verification_token = None
        await self.db.commit()
"""

    if include_password_reset:
        code += """
    async def request_password_reset(self, email: str) -> None:
        \"\"\"请求密码重置\"\"\"
        query = select(User).where(User.email == email)
        result = await self.db.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            # 不暴露用户是否存在
            return

        reset_token = generate_reset_token()
        # TODO: 保存重置令牌并发送邮件
        # await send_email(user.email, "密码重置", f"重置链接: ...")

    async def reset_password(self, token: str, new_password: str) -> None:
        \"\"\"重置密码\"\"\"
        # TODO: 验证重置令牌并更新密码
        pass
"""

    if include_two_factor:
        code += """
    async def setup_two_factor(self, user_id: int) -> dict:
        \"\"\"设置双因素认证\"\"\"
        import pyotp

        query = select(User).where(User.id == user_id)
        result = await self.db.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        secret = pyotp.random_base32()
        user.two_factor_secret = secret
        await self.db.commit()

        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(user.email, issuer_name="PyCoder")

        return {
            "secret": secret,
            "qr_code_url": provisioning_uri,
        }

    async def verify_two_factor(self, user_id: int, code: str) -> bool:
        \"\"\"验证双因素认证码\"\"\"
        import pyotp

        query = select(User).where(User.id == user_id)
        result = await self.db.execute(query)
        user = result.scalar_one_or_none()

        if not user or not user.two_factor_secret:
            return False

        totp = pyotp.TOTP(user.two_factor_secret)
        return totp.verify(code)
"""

    return {"service.py": code}


def _generate_auth_router(
    use_async: bool,
    include_oauth2: bool,
    include_refresh_token: bool,
    include_email_verification: bool,
    include_password_reset: bool,
    include_two_factor: bool,
    include_social_login: bool,
) -> dict[str, str]:
    """生成认证路由"""
    code = '''"""
认证 API 路由
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from app.dependencies import get_current_user, get_db
from app.models.auth import User
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    UserResponse,
    Token,
    UserUpdate,
)
from app.services.auth import AuthService


router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    request: RegisterRequest,
    db=Depends(get_db),
):
    """用户注册"""
    service = AuthService(db)
    return await service.register(request)


@router.post("/login", response_model=Token)
async def login(
    request: LoginRequest,
    db=Depends(get_db),
):
    """用户登录"""
    service = AuthService(db)
    return await service.login(request)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """获取当前用户信息"""
    return UserResponse.model_validate(current_user)


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """更新当前用户信息"""
    if data.full_name is not None:
        current_user.full_name = data.full_name
    if data.email is not None:
        current_user.email = data.email
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)
'''

    if include_refresh_token:
        code += '''

@router.post("/refresh", response_model=Token)
async def refresh_token(
    refresh_token: str,
    db=Depends(get_db),
):
    """刷新令牌"""
    service = AuthService(db)
    return await service.refresh(refresh_token)


@router.post("/logout", status_code=204)
async def logout(
    refresh_token: str,
    db=Depends(get_db),
):
    """登出"""
    service = AuthService(db)
    await service.logout(refresh_token)
'''

    if include_email_verification:
        code += '''

@router.post("/verify-email", status_code=204)
async def verify_email(
    token: str,
    db=Depends(get_db),
):
    """验证邮箱"""
    service = AuthService(db)
    await service.verify_email(token)


@router.post("/resend-verification", status_code=204)
async def resend_verification(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """重新发送验证邮件"""
    service = AuthService(db)
    await service.send_verification_email(current_user.id)
'''

    if include_password_reset:
        code += '''

@router.post("/password-reset-request", status_code=204)
async def request_password_reset(
    email: str,
    db=Depends(get_db),
):
    """请求密码重置"""
    service = AuthService(db)
    await service.request_password_reset(email)


@router.post("/password-reset", status_code=204)
async def reset_password(
    token: str,
    new_password: str,
    db=Depends(get_db),
):
    """重置密码"""
    service = AuthService(db)
    await service.reset_password(token, new_password)
'''

    if include_two_factor:
        code += '''

@router.post("/2fa/setup")
async def setup_two_factor(
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """设置双因素认证"""
    service = AuthService(db)
    return await service.setup_two_factor(current_user.id)


@router.post("/2fa/verify")
async def verify_two_factor(
    code: str,
    current_user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """验证双因素认证码"""
    service = AuthService(db)
    result = await service.verify_two_factor(current_user.id, code)
    if not result:
        raise HTTPException(status_code=400, detail="验证码无效")
    return {"verified": True}
'''

    if include_social_login:
        code += '''

@router.get("/oauth2/{provider}")
async def oauth2_login(provider: str):
    """OAuth2 登录"""
    # TODO: 实现 OAuth2 登录
    raise HTTPException(status_code=501, detail="OAuth2 登录尚未实现")


@router.get("/oauth2/{provider}/callback")
async def oauth2_callback(provider: str, code: str, state: str):
    """OAuth2 回调"""
    # TODO: 实现 OAuth2 回调
    raise HTTPException(status_code=501, detail="OAuth2 回调尚未实现")
'''

    return {"router.py": code}


def _generate_auth_dependencies(use_async: bool) -> dict[str, str]:
    """生成认证依赖"""
    code = '''"""
认证依赖
"""

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.auth import User
from app.utils.auth import decode_token


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """获取当前用户"""
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的访问令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = int(payload["sub"])
    query = select(User).where(User.id == user_id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账户已被禁用",
        )

    return user


async def get_current_active_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    """获取当前超级用户"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足",
        )
    return current_user


async def get_optional_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """获取当前用户（可选）"""
    if not token:
        return None

    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return None

    user_id = int(payload["sub"])
    query = select(User).where(User.id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()
'''

    return {"dependencies.py": code}


def _generate_auth_init() -> dict[str, str]:
    """生成认证模块 __init__.py"""
    code = '''"""
认证模块
"""

from .models import User, RefreshToken
from .schemas import (
    LoginRequest,
    RegisterRequest,
    UserResponse,
    UserUpdate,
    Token,
)
from .service import AuthService
from .router import router
from .dependencies import get_current_user, get_current_active_superuser, get_optional_user


__all__ = [
    "User",
    "RefreshToken",
    "LoginRequest",
    "RegisterRequest",
    "UserResponse",
    "UserUpdate",
    "Token",
    "AuthService",
    "router",
    "get_current_user",
    "get_current_active_superuser",
    "get_optional_user",
]
'''

    return {"__init__.py": code}

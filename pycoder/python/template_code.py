"""
模板代码生成器 — 内置完整可运行的项目代码

每个模板生成的是可以直接 pip install + uvicorn/streamlit 启动的完整项目。
代码来自 FastAPI/Streamlit 官方最新最佳实践，SQLAlchemy 2.0 + Pydantic v2。
"""

from pathlib import Path


def _write(file_path: Path, content: str) -> None:
    """写入文件并自动创建父目录"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")


def generate_fastapi_crud(project_path: Path, entity_name: str = "item") -> list[str]:
    """生成一个可完整运行的 FastAPI CRUD 项目"""
    entity_lower = entity_name.lower()
    entity_title = entity_name.capitalize()
    created = []

    # 预创建所有子目录
    for d in ["src", "src/models", "src/routers", "src/schemas", "tests"]:
        (project_path / d).mkdir(parents=True, exist_ok=True)

    p = project_path  # shorthand

    # ── src/__init__.py ──
    _write(p / "src" / "__init__.py", "")
    created.append("src/__init__.py")

    # ── src/database.py ──
    db_code = '''"""
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
'''
    (project_path / "src" / "database.py").write_text(db_code, encoding="utf-8")
    created.append("src/database.py")

    # ── src/models/__init__.py ──
    models_init = f"""from src.models.{entity_lower} import {entity_title}Model
__all_models = [{entity_title}Model]
"""
    (project_path / "src" / "models" / "__init__.py").write_text(models_init, encoding="utf-8")
    created.append("src/models/__init__.py")

    # ── src/models/item.py ──
    model_code = f'''"""
{entity_title} 数据模型 - SQLAlchemy ORM
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from src.database import Base


class {entity_title}Model(Base):
    """{entity_title} 模型"""
    __tablename__ = "{entity_lower}s"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(200), nullable=False, index=True, comment="标题")
    description = Column(Text, nullable=True, comment="描述")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def __repr__(self) -> str:
        return f"<{entity_title} {{self.id}}: {{self.title}}>"
'''
    (project_path / "src" / "models" / f"{entity_lower}.py").write_text(
        model_code, encoding="utf-8"
    )
    created.append(f"src/models/{entity_lower}.py")

    # ── src/schemas/__init__.py ──
    (project_path / "src" / "schemas" / "__init__.py").write_text("", encoding="utf-8")
    created.append("src/schemas/__init__.py")

    # ── src/schemas/item.py ──
    schema_code = f'''"""
{entity_title} Pydantic Schema - 请求/响应 模型
Pydantic v2 风格
"""
from datetime import datetime
from pydantic import BaseModel, Field


class {entity_title}Create(BaseModel):
    """创建 {entity_title} 请求"""
    title: str = Field(..., min_length=1, max_length=200, description="{entity_title} 标题")
    description: str | None = Field(None, description="{entity_title} 描述")


class {entity_title}Update(BaseModel):
    """更新 {entity_title} 请求 (全部可选)"""
    title: str | None = Field(None, min_length=1, max_length=200, description="{entity_title} 标题")
    description: str | None = Field(None, description="{entity_title} 描述")
    is_active: bool | None = Field(None, description="是否启用")


class {entity_title}Response(BaseModel):
    """{entity_title} 响应"""
    id: int
    title: str
    description: str | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {{"from_attributes": True}}


class PaginatedResponse(BaseModel):
    """分页响应"""
    total: int
    page: int
    page_size: int
    items: list[{entity_title}Response]
'''
    (project_path / "src" / "schemas" / f"{entity_lower}.py").write_text(
        schema_code, encoding="utf-8"
    )
    created.append(f"src/schemas/{entity_lower}.py")

    # ── src/routers/__init__.py ──
    (project_path / "src" / "routers" / "__init__.py").write_text("", encoding="utf-8")
    created.append("src/routers/__init__.py")

    # ── src/routers/items.py ──
    router_code = f'''"""
{entity_title} CRUD 路由 - FastAPI
完整的增删改查 + 分页 + 搜索
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from src.database import get_db
from src.models.{entity_lower} import {entity_title}Model
from src.schemas.{entity_lower} import (
    {entity_title}Create,
    {entity_title}Update,
    {entity_title}Response,
    PaginatedResponse,
)

router = APIRouter(prefix="/{entity_lower}s", tags=["{entity_title}"])


@router.get("", response_model=PaginatedResponse)
async def list_{entity_lower}s(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    search: str | None = Query(None, description="搜索关键词"),
    active_only: bool = Query(False, description="仅显示启用的"),
    db: Session = Depends(get_db),
):
    """获取 {entity_title} 列表 (分页+搜索)"""
    query = db.query({entity_title}Model)

    # 搜索
    if search:
        query = query.filter(
            or_(
                {entity_title}Model.title.contains(search),
                {entity_title}Model.description.contains(search),
            )
        )

    # 过滤
    if active_only:
        query = query.filter({entity_title}Model.is_active.is_(True))

    # 总数
    total = query.count()

    # 分页
    items = query.order_by({entity_title}Model.created_at.desc()) \\
                 .offset((page - 1) * page_size) \\
                 .limit(page_size) \\
                 .all()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get("/{{{entity_lower}_id}}", response_model={entity_title}Response)
async def get_{entity_lower}(
    {entity_lower}_id: int,
    db: Session = Depends(get_db),
):
    """获取单个 {entity_title}"""
    item = db.query({entity_title}Model).filter({entity_title}Model.id == {entity_lower}_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="{entity_title} 不存在")
    return item


@router.post("", response_model={entity_title}Response, status_code=201)
async def create_{entity_lower}(
    data: {entity_title}Create,
    db: Session = Depends(get_db),
):
    """创建 {entity_title}"""
    item = {entity_title}Model(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{{{entity_lower}_id}}", response_model={entity_title}Response)
async def update_{entity_lower}(
    {entity_lower}_id: int,
    data: {entity_title}Update,
    db: Session = Depends(get_db),
):
    """更新 {entity_title} (部分更新)"""
    item = db.query({entity_title}Model).filter({entity_title}Model.id == {entity_lower}_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="{entity_title} 不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)

    db.commit()
    db.refresh(item)
    return item


@router.delete("/{{{entity_lower}_id}}")
async def delete_{entity_lower}(
    {entity_lower}_id: int,
    db: Session = Depends(get_db),
):
    """删除 {entity_title}"""
    item = db.query({entity_title}Model).filter({entity_title}Model.id == {entity_lower}_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="{entity_title} 不存在")

    db.delete(item)
    db.commit()
    return {{"message": "{entity_title} 已删除", "id": {entity_lower}_id}}
'''
    (project_path / "src" / "routers" / f"{entity_lower}s.py").write_text(
        router_code, encoding="utf-8"
    )
    created.append(f"src/routers/{entity_lower}s.py")

    # ── src/main.py ──
    main_code = f'''"""
FastAPI 应用入口 - {entity_title} CRUD API

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
from src.routers.{entity_lower}s import router as {entity_lower}_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期: 启动时初始化数据库"""
    init_db()
    yield


app = FastAPI(
    title="{entity_title} API",
    description="{entity_title} 管理系统 - FastAPI + SQLAlchemy + SQLite",
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
app.include_router({entity_lower}_router)


@app.get("/")
async def root():
    """API 首页"""
    return {{
        "name": "{entity_title} API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
    }}


@app.get("/health")
async def health():
    """健康检查"""
    return {{"status": "ok"}}
'''
    (project_path / "src" / "main.py").write_text(main_code, encoding="utf-8")
    created.append("src/main.py")

    # ── tests/__init__.py ──
    (project_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    created.append("tests/__init__.py")

    # ── tests/test_api.py ──
    test_code = f'''"""
{entity_title} API 测试
运行: pytest tests/ -v
"""
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_health():
    """健康检查"""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_{entity_lower}():
    """创建测试"""
    resp = client.post("/{entity_lower}s", json={{"title": "测试{entity_title}"}})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "测试{entity_title}"
    assert data["id"] is not None
    return data


def test_list_{entity_lower}s():
    """列表测试"""
    resp = client.get("/{entity_lower}s")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


def test_get_{entity_lower}():
    """详情测试"""
    created = test_create_{entity_lower}()
    resp = client.get(f"/{entity_lower}s/{{created['id']}}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_update_{entity_lower}():
    """更新测试"""
    created = test_create_{entity_lower}()
    resp = client.put(f"/{entity_lower}s/{{created['id']}}", json={{"title": "更新标题"}})
    assert resp.status_code == 200
    assert resp.json()["title"] == "更新标题"


def test_delete_{entity_lower}():
    """删除测试"""
    created = test_create_{entity_lower}()
    resp = client.delete(f"/{entity_lower}s/{{created['id']}}")
    assert resp.status_code == 200
'''
    (project_path / "tests" / f"test_{entity_lower}s.py").write_text(test_code, encoding="utf-8")
    created.append(f"tests/test_{entity_lower}s.py")

    # ── requirements.txt ──
    req = """fastapi>=0.110.0
uvicorn[standard]>=0.29.0
sqlalchemy>=2.0.30
pydantic>=2.7.0
pytest>=8.0.0
httpx>=0.27.0
"""
    (project_path / "requirements.txt").write_text(req, encoding="utf-8")
    created.append("requirements.txt")

    # ── README.md ──
    readme = f"""# {entity_title} API

{entity_title} 管理系统 - FastAPI + SQLAlchemy + SQLite

## 快速开始

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload
```

## API 文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 测试

```bash
pytest tests/ -v
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /{entity_lower}s | 获取列表 (分页+搜索) |
| GET | /{entity_lower}s/{{id}} | 获取详情 |
| POST | /{entity_lower}s | 创建 |
| PUT | /{entity_lower}s/{{id}} | 更新 |
| DELETE | /{entity_lower}s/{{id}} | 删除 |
"""
    (project_path / "README.md").write_text(readme, encoding="utf-8")
    created.append("README.md")

    return created


def generate_fastapi_auth(project_path: Path) -> list[str]:
    """生成 FastAPI + JWT 完整认证系统"""
    created = []
    for d in ["src", "src/models", "src/schemas", "src/routers", "tests"]:
        (project_path / d).mkdir(parents=True, exist_ok=True)

    # ── src/__init__.py ──
    (project_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    created.append("src/__init__.py")

    # ── src/config.py ──
    config_code = '''"""
应用配置
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用设置 - 从环境变量读取"""
    app_name: str = "PyCoder Auth API"
    debug: bool = True

    # 数据库
    database_url: str = "sqlite:///./auth.db"

    # JWT
    secret_key: str = "your-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    model_config = {"env_file": ".env"}


settings = Settings()
'''
    (project_path / "src" / "config.py").write_text(config_code, encoding="utf-8")
    created.append("src/config.py")

    # ── src/database.py ──
    db_code = '''"""
数据库连接
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from src.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from src.models.user import User  # noqa: F401
    Base.metadata.create_all(bind=engine)
'''
    (project_path / "src" / "database.py").write_text(db_code, encoding="utf-8")
    created.append("src/database.py")

    # ── src/models/__init__.py ──
    (project_path / "src" / "models" / "__init__.py").write_text(
        'from src.models.user import User\n__all__ = ["User"]\n', encoding="utf-8"
    )
    created.append("src/models/__init__.py")

    # ── src/models/user.py ──
    user_model = '''"""
User 模型
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from src.database import Base


class User(Base):
    """用户模型"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
'''
    (project_path / "src" / "models" / "user.py").write_text(user_model, encoding="utf-8")
    created.append("src/models/user.py")

    # ── src/schemas/__init__.py ──
    (project_path / "src" / "schemas" / "__init__.py").write_text("", encoding="utf-8")
    created.append("src/schemas/__init__.py")

    # ── src/schemas/user.py ──
    schema_user = '''"""
User Pydantic Schemas
"""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=6)


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: str | None = None
'''
    (project_path / "src" / "schemas" / "user.py").write_text(schema_user, encoding="utf-8")
    created.append("src/schemas/user.py")

    # ── src/auth.py ──
    auth_code = '''"""
JWT 认证工具
"""
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from src.config import settings
from src.database import get_db
from src.models.user import User
from src.schemas.user import TokenData

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """获取密码哈希"""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """创建 JWT Token"""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """获取当前登录用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无法验证凭证",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user
'''
    (project_path / "src" / "auth.py").write_text(auth_code, encoding="utf-8")
    created.append("src/auth.py")

    # ── src/routers/__init__.py ──
    (project_path / "src" / "routers" / "__init__.py").write_text("", encoding="utf-8")
    created.append("src/routers/__init__.py")

    # ── src/routers/auth.py ──
    auth_router = '''"""
认证路由 - 注册/登录/当前用户
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from src.database import get_db
from src.models.user import User
from src.schemas.user import UserCreate, UserLogin, UserResponse, Token
from src.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    get_current_user,
)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: UserCreate, db: Session = Depends(get_db)):
    """用户注册"""
    # 检查用户名是否已存在
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="邮箱已注册")

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=get_password_hash(data.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(data: UserLogin, db: Session = Depends(get_db)):
    """用户登录"""
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="用户已被禁用")

    token = create_access_token(data={"sub": user.username})
    return Token(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户"""
    return current_user
'''
    (project_path / "src" / "routers" / "auth.py").write_text(auth_router, encoding="utf-8")
    created.append("src/routers/auth.py")

    # ── src/main.py ──
    main_code = '''"""
FastAPI 应用入口 - JWT 认证系统
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.database import init_db
from src.routers.auth import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="PyCoder Auth API",
    description="JWT 认证系统 - FastAPI + SQLAlchemy + JWT",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": "PyCoder Auth API",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}
'''
    (project_path / "src" / "main.py").write_text(main_code, encoding="utf-8")
    created.append("src/main.py")

    # ── .env ──
    env_code = """SECRET_KEY=change-this-to-a-random-secret-key-in-production
DEBUG=true
DATABASE_URL=sqlite:///./auth.db
"""
    (project_path / ".env").write_text(env_code, encoding="utf-8")
    created.append(".env")

    # ── tests ──
    (project_path / "tests" / "__init__.py").write_text("", encoding="utf-8")
    created.append("tests/__init__.py")

    test_code = '''"""
Auth API 测试
"""
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_register():
    resp = client.post("/api/auth/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "test123456",
    })
    assert resp.status_code == 201
    assert resp.json()["username"] == "testuser"


def test_login():
    resp = client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "test123456",
    })
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_me():
    login = client.post("/api/auth/login", json={
        "username": "testuser",
        "password": "test123456",
    })
    token = login.json()["access_token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "testuser"
'''
    (project_path / "tests" / "test_auth.py").write_text(test_code, encoding="utf-8")
    created.append("tests/test_auth.py")

    # ── requirements.txt ──
    req = """fastapi>=0.110.0
uvicorn[standard]>=0.29.0
sqlalchemy>=2.0.30
pydantic>=2.7.0
pydantic-settings>=2.2.0
pydantic[email]>=2.7.0
python-jose[cryptography]>=3.3.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.9
pytest>=8.0.0
httpx>=0.27.0
"""
    (project_path / "requirements.txt").write_text(req, encoding="utf-8")
    created.append("requirements.txt")

    readme = """# PyCoder Auth API

JWT 认证系统 - FastAPI + SQLAlchemy + JWT

## 快速开始

```bash
pip install -r requirements.txt
uvicorn src.main:app --reload
```

## API 端点

| 方法 | 路径 | 说明 | 认证 |
|------|------|------|------|
| POST | /api/auth/register | 注册 | ❌ |
| POST | /api/auth/login | 登录 → JWT Token | ❌ |
| GET | /api/auth/me | 当前用户信息 | ✅ Bearer |

## 测试

```bash
pytest tests/ -v
```
"""
    (project_path / "README.md").write_text(readme, encoding="utf-8")
    created.append("README.md")

    return created


def generate_streamlit_dashboard(project_path: Path) -> list[str]:
    """生成 Streamlit 数据看板"""
    created = []

    # 预创建子目录 (pages 目录必须先创建才能写入 pages/analysis.py)
    for d in ["pages"]:
        (project_path / d).mkdir(parents=True, exist_ok=True)

    app_code = '''"""
Streamlit 数据看板 - 多页面
启动: streamlit run app.py
"""
import streamlit as st

# 页面配置 - 必须是第一条 st 命令
st.set_page_config(
    page_title="数据看板",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def main():
    """主看板页面"""
    st.title("📊 数据看板")

    # 顶部指标卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总用户", "1,234", "+5.6%")
    with col2:
        st.metric("活跃用户", "890", "+3.2%")
    with col3:
        st.metric("总收入", "¥45,678", "+12.3%")
    with col4:
        st.metric("转化率", "3.45%", "-0.8%")

    # 图表区域
    st.subheader("📈 趋势图")
    tab1, tab2, tab3 = st.tabs(["折线图", "柱状图", "饼图"])

    with tab1:
        _line_chart_tab()
    with tab2:
        _bar_chart_tab()
    with tab3:
        import pandas as pd

        data = pd.DataFrame({
            "分类": ["A类", "B类", "C类", "D类"],
            "占比": [35, 28, 22, 15],
        })
        st.bar_chart(data.set_index("分类"))

    # 数据表格
    st.subheader("📋 数据明细")
    with st.expander("查看详细数据", expanded=False):
        import pandas as pd
        import numpy as np

        df = pd.DataFrame(
            np.random.randn(10, 5),
            columns=["指标A", "指标B", "指标C", "指标D", "指标E"],
        )
        st.dataframe(df, use_container_width=True)
        csv = df.to_csv(index=False)
        st.download_button(
            label="📥 下载 CSV",
            data=csv,
            file_name="data.csv",
            mime="text/csv",
        )


def _line_chart_tab():
    """折线图"""
    import pandas as pd
    import numpy as np

    chart_data = pd.DataFrame(
        np.random.randn(30, 3),
        columns=["收入", "支出", "利润"],
    )
    st.line_chart(chart_data)


def _bar_chart_tab():
    """柱状图"""
    import pandas as pd

    data = pd.DataFrame({
        "月份": ["1月", "2月", "3月", "4月", "5月", "6月"],
        "销售额": [120, 180, 150, 200, 170, 230],
    })
    st.bar_chart(data.set_index("月份"))


if __name__ == "__main__":
    main()
'''
    (project_path / "app.py").write_text(app_code, encoding="utf-8")
    created.append("app.py")

    page_code = '''"""
Streamlit 多页面 - 第二页
"""
import streamlit as st

st.set_page_config(page_title="数据分析", page_icon="🔍", layout="wide")
st.title("🔍 数据分析")

uploaded_file = st.file_uploader("上传数据文件 (CSV)", type=["csv"])
if uploaded_file:
    import pandas as pd
    df = pd.read_csv(uploaded_file)
    st.subheader("数据预览")
    st.dataframe(df.head(100), use_container_width=True)

    st.subheader("统计摘要")
    st.dataframe(df.describe(), use_container_width=True)

    col1, col2 = st.columns(2)
    with col1:
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        if numeric_cols:
            x_col = st.selectbox("X 轴", numeric_cols)
            y_col = st.selectbox("Y 轴", numeric_cols, index=min(1, len(numeric_cols) - 1))
            st.scatter_chart(df, x=x_col, y=y_col)
else:
    st.info("请上传 CSV 文件开始分析")
'''
    (project_path / "pages" / "analysis.py").write_text(page_code, encoding="utf-8")
    created.append("pages/analysis.py")

    req = """streamlit>=1.35.0
pandas>=2.2.0
numpy>=1.26.0
openpyxl>=3.1.0
"""
    (project_path / "requirements.txt").write_text(req, encoding="utf-8")
    created.append("requirements.txt")

    readme = """# 数据看板

Streamlit 多页面数据看板

## 启动

```bash
pip install -r requirements.txt
streamlit run app.py
```
"""
    (project_path / "README.md").write_text(readme, encoding="utf-8")
    created.append("README.md")

    return created


def generate_scaffold_project(
    project_path: Path, template_name: str, entity_name: str = "item"
) -> list[str]:
    """根据模板名称生成完整项目代码"""
    generators = {
        "fastapi-crud": lambda: generate_fastapi_crud(project_path, entity_name),
        "fastapi-auth": lambda: generate_fastapi_auth(project_path),
        "streamlit-dashboard": lambda: generate_streamlit_dashboard(project_path),
    }

    gen = generators.get(template_name)
    if gen:
        return gen()

    # 默认: FastAPI CRUD
    return generate_fastapi_crud(project_path, entity_name)

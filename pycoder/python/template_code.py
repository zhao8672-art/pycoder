"""模板代码生成器 — 提供 FastAPI CRUD、认证、Streamlit 仪表盘等脚手架生成功能。"""

from __future__ import annotations

from pathlib import Path


def generate_fastapi_auth(
    target_dir=None,
    *,
    use_async: bool = True,
    include_refresh: bool = True,
    include_password_reset: bool = True,
    include_email_verification: bool = True,
    include_2fa: bool = False,
    include_oauth: bool = False,
    include_social_login: bool = False,
    include_mfa: bool = False,
    include_session_management: bool = False,
    include_api_keys: bool = False,
    include_audit_log: bool = False,
    include_rate_limit: bool = False,
    include_account_locking: bool = False,
    include_password_history: bool = False,
    include_device_tracking: bool = False,
    include_consent_management: bool = False,
    include_privacy_settings: bool = False,
    include_data_export: bool = False,
    include_account_deletion: bool = False,
    output_format: str = "fastapi",
) -> str:
    """生成完整的 FastAPI 认证代码。

    当提供 ``target_dir`` 时,会创建完整的 FastAPI 认证项目结构
    (包含 models、routers、auth、config 等文件) 并返回生成的文件相对路径列表。
    不提供 ``target_dir`` 时,返回原始的认证代码字符串 (向后兼容)。

    Args:
        target_dir: 目标目录 (Path 或 str)。若提供则将代码写入文件。
        use_async: 是否使用异步路由
        include_refresh: 是否包含令牌刷新
        include_password_reset: 是否包含密码重置
        include_email_verification: 是否包含邮箱验证
        include_2fa: 是否包含双因素认证
        include_oauth: 是否包含 OAuth
        include_social_login: 是否包含社交登录
        include_mfa: 是否包含多因素认证
        include_session_management: 是否包含会话管理
        include_api_keys: 是否包含 API 密钥
        include_audit_log: 是否包含审计日志
        include_rate_limit: 是否包含速率限制
        include_account_locking: 是否包含账户锁定
        include_password_history: 是否包含密码历史
        include_device_tracking: 是否包含设备追踪
        include_consent_management: 是否包含同意管理
        include_privacy_settings: 是否包含隐私设置
        include_data_export: 是否包含数据导出
        include_account_deletion: 是否包含账户删除
        output_format: 输出格式

    Returns:
        若提供 ``target_dir`` 则返回文件相对路径列表;否则返回完整代码字符串。
    """
    parts = []

    # 1. 生成核心认证模型
    parts.append(_generate_auth_models())

    # 2. 生成密码工具
    parts.append(_generate_password_utils())

    # 3. 生成 JWT 工具
    parts.append(_generate_jwt_utils(include_refresh))

    # 4. 生成认证服务
    parts.append(_generate_auth_service(
        include_password_reset, include_email_verification,
        include_account_locking, include_password_history,
    ))

    # 5. 生成路由
    parts.append(_generate_auth_routes(
        use_async, include_refresh, include_password_reset,
        include_email_verification,
    ))

    # 6. 生成可选的增强功能
    if include_2fa:
        parts.append(_generate_2fa_support())
    if include_oauth:
        parts.append(_generate_oauth_support())
    if include_social_login:
        parts.append(_generate_social_login_support())
    if include_mfa:
        parts.append(_generate_mfa_support())
    if include_session_management:
        parts.append(_generate_session_management())
    if include_api_keys:
        parts.append(_generate_api_keys_support())
    if include_audit_log:
        parts.append(_generate_auth_audit_log())
    if include_rate_limit:
        parts.append(_generate_auth_rate_limit())
    if include_device_tracking:
        parts.append(_generate_device_tracking())
    if include_consent_management:
        parts.append(_generate_consent_management())
    if include_privacy_settings:
        parts.append(_generate_privacy_settings())
    if include_data_export:
        parts.append(_generate_data_export())
    if include_account_deletion:
        parts.append(_generate_account_deletion())

    full_code = "\n\n".join(parts)

    # 向后兼容:未提供 target_dir 时,直接返回代码字符串
    if target_dir is None:
        return full_code

    # 提供 target_dir 时,写入完整项目结构
    return _write_fastapi_auth_project(target_dir)


def _write_fastapi_auth_project(target_dir) -> list:
    """将 FastAPI 认证项目写入 target_dir 目录。"""
    base = Path(target_dir)
    base.mkdir(parents=True, exist_ok=True)

    # 创建目录结构
    (base / "src").mkdir(exist_ok=True)
    (base / "src" / "models").mkdir(exist_ok=True)
    (base / "src" / "schemas").mkdir(exist_ok=True)
    (base / "src" / "routers").mkdir(exist_ok=True)
    (base / "tests").mkdir(exist_ok=True)

    files: dict = {
        "src/__init__.py": '"""FastAPI 认证模块。"""\n',
        "src/config.py": (
            '"""应用配置。"""\n'
            "import os\n"
            "\n"
            'SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")\n'
            'ALGORITHM: str = os.getenv("ALGORITHM", "HS256")\n'
            "ACCESS_TOKEN_EXPIRE_MINUTES: int = int("
            'os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))\n'
            'DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./app.db")\n'
        ),
        "src/database.py": (
            '"""数据库连接与 Session 管理。"""\n'
            "from sqlalchemy import create_engine\n"
            "from sqlalchemy.orm import declarative_base, sessionmaker\n"
            "\n"
            "from src.config import DATABASE_URL\n"
            "\n"
            "engine = create_engine("
            'DATABASE_URL, connect_args={"check_same_thread": False})\n'
            "SessionLocal = sessionmaker("
            "autocommit=False, autoflush=False, bind=engine)\n"
            "Base = declarative_base()\n"
            "\n"
            "\n"
            "def get_db():\n"
            '    """FastAPI 依赖:提供数据库 Session."""\n'
            "    db = SessionLocal()\n"
            "    try:\n"
            "        yield db\n"
            "    finally:\n"
            "        db.close()\n"
        ),
        "src/models/__init__.py": (
            '"""SQLAlchemy 模型集合。"""\n'
            "from src.models.user import UserModel\n"
            "\n"
            '__all__ = ["UserModel"]\n'
        ),
        "src/models/user.py": (
            '"""用户 ORM 模型。"""\n'
            "from datetime import datetime\n"
            "\n"
            "from sqlalchemy import Boolean, Column, DateTime, Integer, String\n"
            "\n"
            "from src.database import Base\n"
            "\n"
            "\n"
            "class UserModel(Base):\n"
            '    __tablename__ = "users"\n'
            "\n"
            "    id = Column(Integer, primary_key=True, index=True)\n"
            "    email = Column(String(255), unique=True, index=True, nullable=False)\n"
            "    hashed_password = Column(String(255), nullable=False)\n"
            "    full_name = Column(String(255), nullable=True)\n"
            "    is_active = Column(Boolean, default=True)\n"
            "    is_verified = Column(Boolean, default=False)\n"
            "    created_at = Column(DateTime, default=datetime.utcnow)\n"
            "\n"
            "    def __repr__(self) -> str:\n"
            '        return f"<User {self.email}>"\n'
        ),
        "src/schemas/__init__.py": (
            '"""Pydantic 数据模型集合。"""\n'
            "from src.schemas.user import (\n"
            "    UserCreate,\n"
            "    UserLogin,\n"
            "    UserResponse,\n"
            "    UserUpdate,\n"
            ")\n"
            "\n"
            '__all__ = ["UserCreate", "UserLogin", "UserResponse", "UserUpdate"]\n'
        ),
        "src/schemas/user.py": (
            '"""用户相关 Pydantic 模型。"""\n'
            "from datetime import datetime\n"
            "from typing import Optional\n"
            "\n"
            "from pydantic import BaseModel, EmailStr\n"
            "\n"
            "\n"
            "class UserCreate(BaseModel):\n"
            "    email: EmailStr\n"
            "    password: str\n"
            "    full_name: Optional[str] = None\n"
            "\n"
            "\n"
            "class UserLogin(BaseModel):\n"
            "    email: EmailStr\n"
            "    password: str\n"
            "\n"
            "\n"
            "class UserUpdate(BaseModel):\n"
            "    full_name: Optional[str] = None\n"
            "    is_active: Optional[bool] = None\n"
            "\n"
            "\n"
            "class UserResponse(BaseModel):\n"
            "    id: int\n"
            "    email: str\n"
            "    full_name: Optional[str] = None\n"
            "    is_active: bool\n"
            "    is_verified: bool\n"
            "    created_at: datetime\n"
            "\n"
            "    class Config:\n"
            "        from_attributes = True\n"
        ),
        "src/auth.py": (
            '"""认证核心:密码哈希、JWT 与当前用户解析。"""\n'
            "from datetime import datetime, timedelta\n"
            "from typing import Optional\n"
            "\n"
            "from fastapi import Depends, HTTPException, status\n"
            "from fastapi.security import OAuth2PasswordBearer\n"
            "from jose import JWTError, jwt\n"
            "from passlib.context import CryptContext\n"
            "from sqlalchemy.orm import Session\n"
            "\n"
            "from src.config import ALGORITHM, SECRET_KEY\n"
            "from src.database import get_db\n"
            "from src.models.user import UserModel\n"
            "\n"
            'pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")\n'
            'oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")\n'
            "\n"
            "\n"
            "def verify_password(plain_password: str, hashed_password: str) -> bool:\n"
            '    """校验明文密码与哈希是否匹配。"""\n'
            "    return pwd_context.verify(plain_password, hashed_password)\n"
            "\n"
            "\n"
            "def get_password_hash(password: str) -> str:\n"
            '    """生成密码哈希。"""\n'
            "    return pwd_context.hash(password)\n"
            "\n"
            "\n"
            "def create_access_token(\n"
            "    data: dict,\n"
            "    expires_delta: Optional[timedelta] = None,\n"
            ") -> str:\n"
            '    """创建 JWT 访问令牌。"""\n'
            "    to_encode = data.copy()\n"
            "    expire = datetime.utcnow() + (\n"
            "        expires_delta or timedelta(minutes=30)\n"
            "    )\n"
            '    to_encode.update({"exp": expire})\n'
            "    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)\n"
            "\n"
            "\n"
            "def get_current_user(\n"
            "    token: str = Depends(oauth2_scheme),\n"
            "    db: Session = Depends(get_db),\n"
            ") -> UserModel:\n"
            '    """根据 JWT 解析当前登录用户。"""\n'
            "    credentials_exception = HTTPException(\n"
            "        status_code=status.HTTP_401_UNAUTHORIZED,\n"
            '        detail="Could not validate credentials",\n'
            "        headers={\"WWW-Authenticate\": \"Bearer\"},\n"
            "    )\n"
            "    try:\n"
            "        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])\n"
            '        email: Optional[str] = payload.get("sub")\n'
            "        if email is None:\n"
            "            raise credentials_exception\n"
            "    except JWTError:\n"
            "        raise credentials_exception\n"
            "\n"
            "    user = (\n"
            "        db.query(UserModel)\n"
            "        .filter(UserModel.email == email)\n"
            "        .first()\n"
            "    )\n"
            "    if user is None:\n"
            "        raise credentials_exception\n"
            "    return user\n"
        ),
        "src/routers/__init__.py": '"""API 路由集合。"""\n',
        "src/routers/auth.py": (
            '"""认证相关路由:register、login、get_me。"""\n'
            "from fastapi import APIRouter, Depends, HTTPException, status\n"
            "from fastapi.security import OAuth2PasswordRequestForm\n"
            "from sqlalchemy.orm import Session\n"
            "\n"
            "from src.auth import (\n"
            "    create_access_token,\n"
            "    get_current_user,\n"
            "    get_password_hash,\n"
            "    verify_password,\n"
            ")\n"
            "from src.database import get_db\n"
            "from src.models.user import UserModel\n"
            "from src.schemas.user import UserCreate, UserResponse\n"
            "\n"
            'router = APIRouter(prefix="/auth", tags=["auth"])\n'
            "\n"
            "\n"
            "@router.post(\n"
            '    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED,\n'
            ")\n"
            "def register(\n"
            "    user_in: UserCreate,\n"
            "    db: Session = Depends(get_db),\n"
            ") -> UserModel:\n"
            '    """注册新用户。"""\n'
            "    existing = (\n"
            "        db.query(UserModel)\n"
            "        .filter(UserModel.email == user_in.email)\n"
            "        .first()\n"
            "    )\n"
            "    if existing:\n"
            '        raise HTTPException(status_code=400, detail="Email already registered")\n'
            "    user = UserModel(\n"
            "        email=user_in.email,\n"
            "        hashed_password=get_password_hash(user_in.password),\n"
            "        full_name=user_in.full_name,\n"
            "    )\n"
            "    db.add(user)\n"
            "    db.commit()\n"
            "    db.refresh(user)\n"
            "    return user\n"
            "\n"
            "\n"
            "@router.post(\"/login\")\n"
            "def login(\n"
            "    form_data: OAuth2PasswordRequestForm = Depends(),\n"
            "    db: Session = Depends(get_db),\n"
            ") -> dict:\n"
            '    """用户登录并返回 access_token。"""\n'
            "    user = (\n"
            "        db.query(UserModel)\n"
            "        .filter(UserModel.email == form_data.username)\n"
            "        .first()\n"
            "    )\n"
            "    if not user or not verify_password(form_data.password, user.hashed_password):\n"
            "        raise HTTPException(\n"
            "            status_code=status.HTTP_401_UNAUTHORIZED,\n"
            '            detail="Incorrect email or password",\n'
            "            headers={\"WWW-Authenticate\": \"Bearer\"},\n"
            "        )\n"
            "    if not user.is_active:\n"
            '        raise HTTPException(status_code=400, detail="Inactive user")\n'
            "    token = create_access_token({\"sub\": user.email})\n"
            '    return {"access_token": token, "token_type": "bearer"}\n'
            "\n"
            "\n"
            "@router.get(\"/me\", response_model=UserResponse)\n"
            "def get_me(\n"
            "    current_user: UserModel = Depends(get_current_user),\n"
            ") -> UserModel:\n"
            '    """获取当前登录用户信息。"""\n'
            "    return current_user\n"
        ),
        "src/main.py": (
            '"""FastAPI 认证服务入口。"""\n'
            "from fastapi import FastAPI\n"
            "\n"
            "from src.database import Base, engine\n"
            "from src.routers import auth\n"
            "\n"
            "# 创建所有表\n"
            "Base.metadata.create_all(bind=engine)\n"
            "\n"
            'app = FastAPI(title="FastAPI Auth Service", version="1.0.0")\n'
            "\n"
            "app.include_router(auth.router)\n"
            "\n"
            "\n"
            '@app.get("/health")\n'
            "def health() -> dict:\n"
            '    """健康检查。"""\n'
            '    return {"status": "ok"}\n'
        ),
        ".env": (
            "SECRET_KEY=your-secret-key-change-me\n"
            'ALGORITHM="HS256"\n'
            "ACCESS_TOKEN_EXPIRE_MINUTES=30\n"
            "DATABASE_URL=sqlite:///./app.db\n"
        ),
        "tests/__init__.py": '"""测试包。"""\n',
        "tests/test_auth.py": (
            '"""认证路由测试。"""\n'
            "from fastapi.testclient import TestClient\n"
            "\n"
            "from src.main import app\n"
            "\n"
            "client = TestClient(app)\n"
            "\n"
            "\n"
            "def test_health() -> None:\n"
            "    response = client.get(\"/health\")\n"
            "    assert response.status_code == 200\n"
            '    assert response.json()["status"] == "ok"\n'
            "\n"
            "\n"
            "def test_register() -> None:\n"
            "    response = client.post(\n"
            '        "/auth/register",\n'
            '        json={"email": "test@example.com", "password": "secret123"},\n'
            "    )\n"
            "    assert response.status_code in (200, 201, 400)\n"
            "\n"
            "\n"
            "def test_login() -> None:\n"
            "    response = client.post(\n"
            '        "/auth/login",\n'
            '        data={"username": "test@example.com", "password": "secret123"},\n'
            "    )\n"
            "    assert response.status_code in (200, 401)\n"
            "\n"
            "\n"
            "def test_get_me_unauthorized() -> None:\n"
            "    response = client.get(\"/auth/me\")\n"
            "    assert response.status_code == 401\n"
        ),
        "requirements.txt": (
            "fastapi>=0.110.0\n"
            "uvicorn[standard]>=0.27.0\n"
            "sqlalchemy>=2.0.0\n"
            "pydantic[email]>=2.5.0\n"
            "python-jose[cryptography]>=3.3.0\n"
            "passlib[bcrypt]>=1.7.4\n"
            "python-multipart>=0.0.9\n"
            "pytest>=7.4.0\n"
            "httpx>=0.25.0\n"
        ),
        "README.md": (
            "# FastAPI Auth Service\n"
            "\n"
            "基于 FastAPI 的认证服务脚手架,包含注册、登录、当前用户查询等接口。\n"
            "\n"
            "## 功能特性\n"
            "\n"
            "- 邮箱 + 密码注册\n"
            "- JWT 访问令牌\n"
            "- bcrypt 密码哈希\n"
            "- 当前登录用户信息查询\n"
            "\n"
            "## 快速开始\n"
            "\n"
            "```bash\n"
            "pip install -r requirements.txt\n"
            "cp .env .env.local  # 可选,自定义环境变量\n"
            "uvicorn src.main:app --reload\n"
            "```\n"
            "\n"
            "## API 文档\n"
            "\n"
            "启动后访问 <http://localhost:8000/docs>\n"
            "\n"
            "## 测试\n"
            "\n"
            "```bash\n"
            "pytest\n"
            "```\n"
        ),
    }

    written: list = []
    for rel_path, content in files.items():
        file_path = base / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        written.append(rel_path)
    return written


def _pluralize(word: str) -> str:
    """简单英语名词复数化 (支持 -y → -ies 规则)。"""
    if not word:
        return word
    if word.endswith("y") and len(word) > 1 and word[-2] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith("s") or word.endswith("x") or word.endswith("ch") or word.endswith("sh"):
        return word + "es"
    return word + "s"


def _title_case(word: str) -> str:
    """将 snake/camel 转成 TitleCase (如 'item' -> 'Item', 'blog_post' -> 'BlogPost')."""
    if not word:
        return word
    parts = word.replace("-", "_").split("_")
    return "".join(p[:1].upper() + p[1:] for p in parts if p)


def generate_fastapi_crud(target_dir, entity_name: str = "item") -> list:
    """生成 FastAPI CRUD 项目脚手架。

    创建标准分层结构 ``src/{models,schemas,routers}`` + ``tests`` 目录,
    包含 entity 模型、Schema、CRUD 路由、入口与测试。

    Args:
        target_dir: 目标目录 (Path 或 str)。
        entity_name: 实体名 (默认 ``"item"``)。复数形式将自动推导。

    Returns:
        创建的文件相对路径列表 (相对于 ``target_dir``)。
    """
    base = Path(target_dir)
    base.mkdir(parents=True, exist_ok=True)

    # 创建目录结构
    (base / "src").mkdir(exist_ok=True)
    (base / "src" / "models").mkdir(exist_ok=True)
    (base / "src" / "schemas").mkdir(exist_ok=True)
    (base / "src" / "routers").mkdir(exist_ok=True)
    (base / "tests").mkdir(exist_ok=True)

    entity = entity_name
    plural = _pluralize(entity)
    Entity = _title_case(entity)

    files: dict = {
        "src/__init__.py": '"""FastAPI 应用源码包。"""\n',
        "src/database.py": (
            '"""数据库连接与 Session 管理。"""\n'
            "from sqlalchemy import create_engine\n"
            "from sqlalchemy.orm import declarative_base, sessionmaker\n"
            "\n"
            'DATABASE_URL = "sqlite:///./app.db"\n'
            "engine = create_engine("
            'DATABASE_URL, connect_args={"check_same_thread": False})\n'
            "SessionLocal = sessionmaker("
            "autocommit=False, autoflush=False, bind=engine)\n"
            "Base = declarative_base()\n"
            "\n"
            "\n"
            "def get_db():\n"
            '    """FastAPI 依赖:提供数据库 Session."""\n'
            "    db = SessionLocal()\n"
            "    try:\n"
            "        yield db\n"
            "    finally:\n"
            "        db.close()\n"
        ),
        "src/models/__init__.py": (
            '"""SQLAlchemy ORM 模型集合。"""\n'
            f"from src.models.{entity} import {Entity}Model\n"
            "\n"
            f'__all__ = ["{Entity}Model"]\n'
        ),
        f"src/models/{entity}.py": (
            f'"""{Entity} ORM 模型。"""\n'
            "from datetime import datetime\n"
            "\n"
            "from sqlalchemy import Boolean, Column, DateTime, Integer, String\n"
            "\n"
            "from src.database import Base\n"
            "\n"
            "\n"
            f"class {Entity}Model(Base):\n"
            f'    __tablename__ = "{plural}"\n'
            "\n"
            "    id = Column(Integer, primary_key=True, index=True)\n"
            "    name = Column(String(255), nullable=False, index=True)\n"
            "    description = Column(String(1000), nullable=True)\n"
            "    is_active = Column(Boolean, default=True)\n"
            "    created_at = Column(DateTime, default=datetime.utcnow)\n"
            "    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)\n"
            "\n"
            "    def __repr__(self) -> str:\n"
            f'        return f"<{Entity} {{self.name}}>"\n'
        ),
        "src/schemas/__init__.py": (
            '"""Pydantic 数据模型集合。"""\n'
            f"from src.schemas.{entity} import (\n"
            f"    {Entity}Create,\n"
            f"    {Entity}Update,\n"
            f"    {Entity}Response,\n"
            "    PaginatedResponse,\n"
            ")\n"
            "\n"
            f'__all__ = ["{Entity}Create", "{Entity}Update", "{Entity}Response", "PaginatedResponse"]\n'
        ),
        f"src/schemas/{entity}.py": (
            f'"""{Entity} 相关 Pydantic 模型。"""\n'
            "from datetime import datetime\n"
            "from typing import Generic, List, Optional, TypeVar\n"
            "\n"
            "from pydantic import BaseModel\n"
            "\n"
            "T = TypeVar(\"T\")\n"
            "\n"
            "\n"
            f"class {Entity}Create(BaseModel):\n"
            "    name: str\n"
            "    description: Optional[str] = None\n"
            "    is_active: bool = True\n"
            "\n"
            "\n"
            f"class {Entity}Update(BaseModel):\n"
            "    name: Optional[str] = None\n"
            "    description: Optional[str] = None\n"
            "    is_active: Optional[bool] = None\n"
            "\n"
            "\n"
            f"class {Entity}Response(BaseModel):\n"
            "    id: int\n"
            "    name: str\n"
            "    description: Optional[str] = None\n"
            "    is_active: bool\n"
            "    created_at: datetime\n"
            "    updated_at: Optional[datetime] = None\n"
            "\n"
            "    class Config:\n"
            "        from_attributes = True\n"
            "\n"
            "\n"
            "class PaginatedResponse(BaseModel, Generic[T]):\n"
            "    \"\"\"分页响应通用结构。\"\"\"\n"
            "\n"
            "    items: List[T]\n"
            "    total: int\n"
            "    page: int\n"
            "    page_size: int\n"
            "\n"
            "    @property\n"
            "    def total_pages(self) -> int:\n"
            "        if self.page_size <= 0:\n"
            "            return 0\n"
            "        return (self.total + self.page_size - 1) // self.page_size\n"
        ),
        "src/routers/__init__.py": '"""API 路由集合。"""\n',
        f"src/routers/{plural}.py": (
            f'"""{Entity} CRUD 路由。"""\n'
            "from typing import List, Optional\n"
            "\n"
            "from fastapi import APIRouter, Depends, HTTPException, Query, status\n"
            "from sqlalchemy.orm import Session\n"
            "\n"
            f"from src.database import get_db\n"
            f"from src.models.{entity} import {Entity}Model\n"
            f"from src.schemas.{entity} import (\n"
            f"    {Entity}Create,\n"
            f"    {Entity}Response,\n"
            f"    {Entity}Update,\n"
            "    PaginatedResponse,\n"
            ")\n"
            "\n"
            f'router = APIRouter(prefix="/{plural}", tags=["{plural}"])\n'
            "\n"
            "\n"
            "@router.get(\"\", response_model=PaginatedResponse[" + Entity + "Response])\n"
            f"def list_{plural}(\n"
            "    page: int = Query(1, ge=1),\n"
            "    page_size: int = Query(20, ge=1, le=100),\n"
            "    db: Session = Depends(get_db),\n"
            ") -> dict:\n"
            f'    """分页获取 {Entity} 列表。"""\n'
            "    total = db.query(" + Entity + "Model).count()\n"
            "    items = (\n"
            "        db.query(" + Entity + "Model)\n"
            "        .order_by(" + Entity + "Model.id)\n"
            "        .offset((page - 1) * page_size)\n"
            "        .limit(page_size)\n"
            "        .all()\n"
            "    )\n"
            "    return {\n"
            '        "items": items,\n'
            '        "total": total,\n'
            '        "page": page,\n'
            '        "page_size": page_size,\n'
            "    }\n"
            "\n"
            "\n"
            "@router.get(\"/{item_id}\", response_model=" + Entity + "Response)\n"
            "def get_" + entity + "(\n"
            "    item_id: int,\n"
            "    db: Session = Depends(get_db),\n"
            ") -> " + Entity + "Model:\n"
            f'    """获取单个 {Entity} 详情。"""\n'
            f"    obj = db.query({Entity}Model).filter({Entity}Model.id == item_id).first()\n"
            f"    if not obj:\n"
            f'        raise HTTPException(status_code=404, detail="{Entity} not found")\n'
            "    return obj\n"
            "\n"
            "\n"
            f"@router.post(\"\", response_model={Entity}Response, status_code=status.HTTP_201_CREATED)\n"
            f"def create_{entity}(\n"
            f"    payload: {Entity}Create,\n"
            "    db: Session = Depends(get_db),\n"
            ") -> " + Entity + "Model:\n"
            f'    """创建新 {Entity}。"""\n'
            f"    obj = {Entity}Model(**payload.model_dump())\n"
            "    db.add(obj)\n"
            "    db.commit()\n"
            "    db.refresh(obj)\n"
            "    return obj\n"
            "\n"
            "\n"
            f"@router.put(\"/{{item_id}}\", response_model={Entity}Response)\n"
            f"def update_{entity}(\n"
            "    item_id: int,\n"
            f"    payload: {Entity}Update,\n"
            "    db: Session = Depends(get_db),\n"
            ") -> " + Entity + "Model:\n"
            f'    """更新 {Entity}。"""\n'
            f"    obj = db.query({Entity}Model).filter({Entity}Model.id == item_id).first()\n"
            f"    if not obj:\n"
            f'        raise HTTPException(status_code=404, detail="{Entity} not found")\n'
            "    for key, value in payload.model_dump(exclude_unset=True).items():\n"
            "        setattr(obj, key, value)\n"
            "    db.commit()\n"
            "    db.refresh(obj)\n"
            "    return obj\n"
            "\n"
            "\n"
            f"@router.delete(\"/{{item_id}}\", status_code=status.HTTP_204_NO_CONTENT)\n"
            f"def delete_{entity}(\n"
            "    item_id: int,\n"
            "    db: Session = Depends(get_db),\n"
            ") -> None:\n"
            f'    """删除 {Entity}。"""\n'
            f"    obj = db.query({Entity}Model).filter({Entity}Model.id == item_id).first()\n"
            f"    if not obj:\n"
            f'        raise HTTPException(status_code=404, detail="{Entity} not found")\n'
            "    db.delete(obj)\n"
            "    db.commit()\n"
        ),
        "src/main.py": (
            f'"""{Entity} API 服务入口。"""\n'
            "from fastapi import FastAPI\n"
            "\n"
            "from src.database import Base, engine\n"
            f"from src.routers import {plural}\n"
            "\n"
            "# 创建所有表\n"
            "Base.metadata.create_all(bind=engine)\n"
            "\n"
            f'app = FastAPI(title="{Entity} API", version="1.0.0")\n'
            "\n"
            f"app.include_router({plural}.router)\n"
            "\n"
            "\n"
            '@app.get("/health")\n'
            "def health() -> dict:\n"
            '    """健康检查。"""\n'
            '    return {"status": "ok"}\n'
        ),
        "tests/__init__.py": '"""测试包。"""\n',
        f"tests/test_{plural}.py": (
            f'"""{Entity} API 测试。"""\n'
            "from fastapi.testclient import TestClient\n"
            "\n"
            "from src.main import app\n"
            "\n"
            "client = TestClient(app)\n"
            "\n"
            "\n"
            "def test_health() -> None:\n"
            "    response = client.get(\"/health\")\n"
            "    assert response.status_code == 200\n"
            '    assert response.json()["status"] == "ok"\n'
            "\n"
            "\n"
            f"def test_create_{entity}() -> None:\n"
            "    response = client.post(\n"
            f'        "/{plural}",\n'
            '        json={"name": "test", "description": "demo"},\n'
            "    )\n"
            "    assert response.status_code in (200, 201)\n"
            "    body = response.json()\n"
            f'    assert body["name"] == "test"\n'
            "\n"
            "\n"
            f"def test_list_{plural}() -> None:\n"
            f"    response = client.get(\"/{plural}\")\n"
            "    assert response.status_code == 200\n"
            "    body = response.json()\n"
            "    assert \"items\" in body\n"
            "    assert \"total\" in body\n"
        ),
        "requirements.txt": (
            "fastapi>=0.110.0\n"
            "uvicorn[standard]>=0.27.0\n"
            "sqlalchemy>=2.0.0\n"
            "pydantic>=2.5.0\n"
            "pytest>=7.4.0\n"
            "httpx>=0.25.0\n"
        ),
        "README.md": (
            f"# {Entity} API\n"
            "\n"
            f"基于 FastAPI 的 {Entity} CRUD 服务脚手架,提供开箱即用的 RESTful 接口。\n"
            "\n"
            "## 功能特性\n"
            "\n"
            f"- {Entity} 列表分页查询\n"
            f"- {Entity} 详情查询\n"
            f"- {Entity} 创建 / 更新 / 删除\n"
            "- 健康检查接口\n"
            "\n"
            "## 快速开始\n"
            "\n"
            "```bash\n"
            "pip install -r requirements.txt\n"
            "uvicorn src.main:app --reload\n"
            "```\n"
            "\n"
            "## API 文档\n"
            "\n"
            "启动后访问 <http://localhost:8000/docs>\n"
            "\n"
            "## 测试\n"
            "\n"
            "```bash\n"
            "pytest\n"
            "```\n"
        ),
    }

    written: list = []
    for rel_path, content in files.items():
        file_path = base / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        written.append(rel_path)
    return written


def generate_streamlit_dashboard(target_dir) -> list:
    """生成 Streamlit 数据看板项目脚手架。

    包含主入口 ``app.py``、``pages/analysis.py`` 多页应用、依赖与说明文档。

    Args:
        target_dir: 目标目录 (Path 或 str)。

    Returns:
        创建的文件相对路径列表 (相对于 ``target_dir``)。
    """
    base = Path(target_dir)
    base.mkdir(parents=True, exist_ok=True)

    # 关键:必须显式创建 pages 目录,否则 write_text 会失败
    (base / "pages").mkdir(exist_ok=True)

    files: dict = {
        "app.py": (
            '"""Streamlit 数据看板主入口。"""\n'
            "from datetime import datetime\n"
            "\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "import streamlit as st\n"
            "\n"
            'st.set_page_config(\n'
            '    page_title="数据看板",\n'
            '    page_icon="📊",\n'
            '    layout="wide",\n'
            ")\n"
            "\n"
            'st.title("📊 数据看板")\n'
            'st.caption(f"更新时间: {datetime.now().strftime(\'%Y-%m-%d %H:%M:%S\')}")\n'
            "\n"
            "# 侧边栏筛选\n"
            "with st.sidebar:\n"
            '    st.header("筛选条件")\n'
            "    n_points = st.slider(\"数据点数量\", min_value=10, max_value=1000, value=100)\n"
            "    seed = st.number_input(\"随机种子\", min_value=0, value=42, step=1)\n"
            "\n"
            "# 生成示例数据\n"
            "rng = np.random.default_rng(int(seed))\n"
            "df = pd.DataFrame(\n"
            "    {\n"
            '        "x": np.arange(n_points),\n'
            '        "y": rng.normal(loc=0.0, scale=1.0, size=n_points).cumsum(),\n'
            "    }\n"
            ")\n"
            "\n"
            "col1, col2, col3 = st.columns(3)\n"
            "col1.metric(\"数据点数\", len(df))\n"
            'col2.metric("Y 均值", f"{df[\'y\'].mean():.2f}")\n'
            'col3.metric("Y 标准差", f"{df[\'y\'].std():.2f}")\n'
            "\n"
            'st.subheader("趋势图")\n'
            "st.line_chart(df, x=\"x\", y=\"y\")\n"
            "\n"
            'st.subheader("原始数据")\n'
            "st.dataframe(df, use_container_width=True)\n"
        ),
        "pages/analysis.py": (
            '"""数据分析子页面。"""\n'
            "from typing import Optional\n"
            "\n"
            "import numpy as np\n"
            "import pandas as pd\n"
            "import streamlit as st\n"
            "\n"
            'st.set_page_config(\n'
            '    page_title="数据分析",\n'
            '    page_icon="🔬",\n'
            '    layout="wide",\n'
            ")\n"
            "\n"
            'st.title("🔬 数据分析")\n'
            'st.write("在此页面上传 CSV/Excel 文件进行探索性数据分析。")\n'
            "\n"
            "uploaded = st.file_uploader(\n"
            '    "上传数据文件",\n'
            '    type=["csv", "xlsx", "xls"],\n'
            '    help="支持 CSV 与 Excel 格式",\n'
            ")\n"
            "\n"
            "if uploaded is not None:\n"
            "    try:\n"
            "        if uploaded.name.endswith(\".csv\"):\n"
            "            df = pd.read_csv(uploaded)\n"
            "        else:\n"
            "            df = pd.read_excel(uploaded)\n"
            "    except Exception as exc:\n"
            '        st.error(f"读取文件失败: {exc}")\n'
            "        st.stop()\n"
            "\n"
            '    st.success(f"成功加载 {len(df)} 行 × {len(df.columns)} 列")\n'
            "\n"
            '    st.subheader("数据预览")\n'
            "    st.dataframe(df.head(100), use_container_width=True)\n"
            "\n"
            '    st.subheader("统计描述")\n'
            "    st.dataframe(df.describe(include=\"all\").T, use_container_width=True)\n"
            "\n"
            "    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()\n"
            "    if numeric_cols:\n"
            '        st.subheader("分布图")\n'
            "        target: Optional[str] = st.selectbox(\"选择列\", numeric_cols)\n"
            "        if target:\n"
            "            st.bar_chart(df[target])\n"
            "            st.line_chart(df[target])\n"
            "    else:\n"
            '        st.info("未检测到数值型列,无法绘制分布图。")\n'
            "else:\n"
            '    st.info("👆 请先上传数据文件")\n'
        ),
        "requirements.txt": (
            "streamlit>=1.30.0\n"
            "pandas>=2.0.0\n"
            "numpy>=1.24.0\n"
            "openpyxl>=3.1.0\n"
            "matplotlib>=3.7.0\n"
        ),
        "README.md": (
            "# Streamlit 数据看板\n"
            "\n"
            "基于 Streamlit 的多页数据看板脚手架,主页面展示核心指标,\n"
            "`pages/analysis.py` 提供交互式数据分析。\n"
            "\n"
            "## 功能特性\n"
            "\n"
            "- 主页面:指标卡 + 趋势图\n"
            "- 分析子页:CSV/Excel 上传、统计描述、分布图\n"
            "- 多页应用结构 (Streamlit Pages)\n"
            "\n"
            "## 快速开始\n"
            "\n"
            "```bash\n"
            "pip install -r requirements.txt\n"
            "streamlit run app.py\n"
            "```\n"
            "\n"
            "## 项目结构\n"
            "\n"
            "```\n"
            ".\n"
            "├── app.py                 # 主入口\n"
            "├── pages/\n"
            "│   └── analysis.py       # 数据分析子页面\n"
            "├── requirements.txt\n"
            "└── README.md\n"
            "```\n"
        ),
    }

    written: list = []
    for rel_path, content in files.items():
        file_path = base / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        written.append(rel_path)
    return written


def generate_scaffold_project(
    target_dir,
    template_name: str,
    entity_name: str = "item",
) -> list:
    """根据模板名称分派到具体的脚手架生成器。

    支持以下 ``template_name``:

    - ``"fastapi-crud"`` → :func:`generate_fastapi_crud`
    - ``"fastapi-auth"`` → :func:`generate_fastapi_auth`
    - ``"streamlit-dashboard"`` → :func:`generate_streamlit_dashboard`
    - 其它或未知值 → fallback 到 ``"fastapi-crud"``

    Args:
        target_dir: 目标目录 (Path 或 str)。
        template_name: 模板名称。
        entity_name: 实体名 (默认 ``"item"``)。

    Returns:
        创建的文件相对路径列表 (相对于 ``target_dir``)。
    """
    if template_name == "fastapi-crud":
        return generate_fastapi_crud(target_dir, entity_name=entity_name)
    if template_name == "fastapi-auth":
        return generate_fastapi_auth(target_dir)
    if template_name == "streamlit-dashboard":
        return generate_streamlit_dashboard(target_dir)
    # 未知模板默认 fallback 到 fastapi-crud
    return generate_fastapi_crud(target_dir, entity_name=entity_name)


def _generate_auth_models() -> str:
    """生成认证相关的 Pydantic 模型"""
    return """
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenPayload(BaseModel):
    sub: str
    exp: int

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    is_active: bool
    created_at: datetime

class ChangePassword(BaseModel):
    old_password: str
    new_password: str
"""


def _generate_password_utils() -> str:
    """生成密码哈希和验证工具"""
    return """
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)
"""


def _generate_jwt_utils(include_refresh: bool) -> str:
    """生成 JWT 令牌工具"""
    lines = [
        "from datetime import datetime, timedelta",
        "from jose import JWTError, jwt",
        "from typing import Optional",
        "",
        "SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key')",
        "ALGORITHM = 'HS256'",
        "ACCESS_TOKEN_EXPIRE_MINUTES = 30",
        "",
        "def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:",
        "    to_encode = data.copy()",
        "    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))",
        "    to_encode.update({'exp': expire})",
        "    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)",
        "",
        "def verify_token(token: str) -> Optional[dict]:",
        "    try:",
        "        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])",
        "        return payload",
        "    except JWTError:",
        "        return None",
    ]
    if include_refresh:
        lines.extend([
            "",
            "REFRESH_TOKEN_EXPIRE_DAYS = 7",
            "",
            "def create_refresh_token(data: dict) -> str:",
            "    to_encode = data.copy()",
            "    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)",
            "    to_encode.update({'exp': expire, 'type': 'refresh'})",
            "    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)",
        ])
    return "\n".join(lines)


def _generate_auth_service(
    include_password_reset: bool,
    include_email_verification: bool,
    include_account_locking: bool,
    include_password_history: bool,
) -> str:
    """生成认证服务"""
    lines = [
        "class AuthService:",
        '    """认证服务"""',
        "",
        "    def __init__(self, db: Session):",
        "        self.db = db",
        "",
        "    def register(self, user_in: UserCreate) -> User:",  # 简化版
        "        user = User(",
        "            email=user_in.email,",
        "            hashed_password=hash_password(user_in.password),",
        "            full_name=user_in.full_name,",
        "        )",
        "        self.db.add(user)",
        "        self.db.commit()",
        "        self.db.refresh(user)",
        "        return user",
        "",
        "    def authenticate(self, email: str, password: str) -> Optional[User]:",
        "        user = self.db.query(User).filter(User.email == email).first()",
        "        if not user or not verify_password(password, user.hashed_password):",
        "            return None",
        "        return user",
    ]
    if include_password_reset:
        lines.extend([
            "",
            "    def create_password_reset_token(self, email: str) -> Optional[str]:",
            "        user = self.db.query(User).filter(User.email == email).first()",
            "        if not user:",
            "            return None",
            "        return create_access_token({'sub': user.email}, timedelta(hours=1))",
            "",
            "    def reset_password(self, token: str, new_password: str) -> bool:",
            "        payload = verify_token(token)",
            "        if not payload:",
            "            return False",
            "        user = self.db.query(User).filter(User.email == payload['sub']).first()",
            "        if not user:",
            "            return False",
            "        user.hashed_password = hash_password(new_password)",
            "        self.db.commit()",
            "        return True",
        ])
    if include_email_verification:
        lines.extend([
            "",
            "    def verify_email(self, token: str) -> bool:",
            "        payload = verify_token(token)",
            "        if not payload:",
            "            return False",
            "        user = self.db.query(User).filter(User.email == payload['sub']).first()",
            "        if not user:",
            "            return False",
            "        user.is_verified = True",
            "        self.db.commit()",
            "        return True",
        ])
    if include_account_locking:
        lines.extend([
            "",
            "    MAX_LOGIN_ATTEMPTS = 5",
            "",
            "    def check_account_locked(self, email: str) -> bool:",
            "        user = self.db.query(User).filter(User.email == email).first()",
            "        if not user or not user.locked_until:",
            "            return False",
            "        return user.locked_until > datetime.utcnow()",
            "",
            "    def record_login_attempt(self, email: str, success: bool):",
            "        user = self.db.query(User).filter(User.email == email).first()",
            "        if not user:",
            "            return",
            "        if not success:",
            "            user.login_attempts = (user.login_attempts or 0) + 1",
            "            if user.login_attempts >= self.MAX_LOGIN_ATTEMPTS:",
            "                user.locked_until = datetime.utcnow() + timedelta(minutes=30)",
            "        else:",
            "            user.login_attempts = 0",
            "            user.locked_until = None",
            "        self.db.commit()",
        ])
    if include_password_history:
        lines.extend([
            "",
            "    def check_password_history(self, user_id: int, new_password: str) -> bool:",
            "        history = self.db.query(PasswordHistory).filter(",
            "            PasswordHistory.user_id == user_id",
            "        ).order_by(PasswordHistory.created_at.desc()).limit(5).all()",
            "        for entry in history:",
            "            if verify_password(new_password, entry.hashed_password):",
            "                return False",
            "        return True",
        ])
    return "\n".join(lines)


def _generate_auth_routes(
    use_async: bool, include_refresh: bool,
    include_password_reset: bool, include_email_verification: bool,
) -> str:
    """生成认证路由"""
    async_def = "async def" if use_async else "def"
    lines = [
        "router = APIRouter(prefix='/auth', tags=['auth'])",
        "",
        "@router.post('/register', response_model=UserResponse)",
        f"{async_def} register(user_in: UserCreate, db: Session = Depends(get_db)):",
        "    service = AuthService(db)",
        "    user = service.register(user_in)",
        "    return user",
        "",
        "@router.post('/login', response_model=Token)",
        f"{async_def} login(credentials: UserLogin, db: Session = Depends(get_db)):",
        "    service = AuthService(db)",
        "    user = service.authenticate(credentials.email, credentials.password)",
        "    if not user:",
        "        raise HTTPException(status_code=401, detail='Invalid credentials')",
        "    access_token = create_access_token({'sub': user.email})",
        "    return Token(access_token=access_token)",
    ]
    if include_refresh:
        lines.extend([
            "",
            "@router.post('/refresh', response_model=Token)",
            f"{async_def} refresh(token: str, db: Session = Depends(get_db)):",
            "    payload = verify_token(token)",
            "    if not payload or payload.get('type') != 'refresh':",
            "        raise HTTPException(status_code=401, detail='Invalid refresh token')",
            "    access_token = create_access_token({'sub': payload['sub']})",
            "    return Token(access_token=access_token)",
        ])
    if include_password_reset:
        lines.extend([
            "",
            "@router.post('/password-reset/request')",
            f"{async_def} request_password_reset(email: str, db: Session = Depends(get_db)):",
            "    service = AuthService(db)",
            "    token = service.create_password_reset_token(email)",
            "    if token:",
            "        # Send email with token",
            "        pass",
            "    return {'message': 'If email exists, reset link sent'}",
            "",
            "@router.post('/password-reset/confirm')",
            f"{async_def} confirm_password_reset(token: str, new_password: str, db: Session = Depends(get_db)):",
            "    service = AuthService(db)",
            "    if service.reset_password(token, new_password):",
            "        return {'message': 'Password reset successful'}",
            "    raise HTTPException(status_code=400, detail='Invalid or expired token')",
        ])
    if include_email_verification:
        lines.extend([
            "",
            "@router.post('/verify-email')",
            f"{async_def} verify_email(token: str, db: Session = Depends(get_db)):",
            "    service = AuthService(db)",
            "    if service.verify_email(token):",
            "        return {'message': 'Email verified successfully'}",
            "    raise HTTPException(status_code=400, detail='Invalid verification token')",
        ])
    return "\n".join(lines)


def _generate_2fa_support() -> str:
    """生成双因素认证支持"""
    return """
# Two-Factor Authentication
import pyotp
import qrcode

class TwoFactorAuth:
    def __init__(self):
        self.totp = pyotp.TOTP(pyotp.random_base32())

    def get_provisioning_uri(self, email: str, issuer: str = "PyCoder") -> str:
        return self.totp.provisioning_uri(email, issuer_name=issuer)

    def verify_code(self, code: str) -> bool:
        return self.totp.verify(code)
"""


def _generate_oauth_support() -> str:
    """生成 OAuth 支持"""
    return """
# OAuth Support
from authlib.integrations.starlette_client import OAuth

oauth = OAuth()
oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'},
)
"""


def _generate_social_login_support() -> str:
    """生成社交登录支持"""
    return """
# Social Login Support
SOCIAL_PROVIDERS = {
    'google': {'authorize_url': 'https://accounts.google.com/o/oauth2/v2/auth'},
    'github': {'authorize_url': 'https://github.com/login/oauth/authorize'},
    'microsoft': {'authorize_url': 'https://login.microsoftonline.com/common/oauth2/v2.0/authorize'},
}

async def social_login(provider: str, code: str, db: Session):
    if provider not in SOCIAL_PROVIDERS:
        raise HTTPException(status_code=400, detail='Unsupported provider')
    # Exchange code for token and get user info
    # Create or link user account
    pass
"""


def _generate_mfa_support() -> str:
    """生成多因素认证支持"""
    return """
# Multi-Factor Authentication
class MFAManager:
    def __init__(self):
        self.methods = ['totp', 'sms', 'email']

    def setup_method(self, user_id: int, method: str):
        if method == 'totp':
            return self._setup_totp(user_id)
        elif method == 'sms':
            return self._setup_sms(user_id)
        elif method == 'email':
            return self._setup_email(user_id)

    def verify(self, user_id: int, method: str, code: str) -> bool:
        # Verify MFA code
        pass
"""


def _generate_session_management() -> str:
    """生成会话管理"""
    return """
# Session Management
class SessionManager:
    def __init__(self, redis_client):
        self.redis = redis_client

    def create_session(self, user_id: int) -> str:
        session_id = str(uuid.uuid4())
        self.redis.setex(f"session:{session_id}", 3600, str(user_id))
        return session_id

    def validate_session(self, session_id: str) -> Optional[int]:
        data = self.redis.get(f"session:{session_id}")
        return int(data) if data else None

    def revoke_session(self, session_id: str):
        self.redis.delete(f"session:{session_id}")

    def list_active_sessions(self, user_id: int) -> list:
        # List all active sessions for a user
        pass
"""


def _generate_api_keys_support() -> str:
    """生成 API 密钥支持"""
    return """
# API Key Management
class APIKeyManager:
    def __init__(self, db: Session):
        self.db = db

    def create_key(self, user_id: int, name: str) -> str:
        key = f"pk_{secrets.token_urlsafe(32)}"
        api_key = APIKey(user_id=user_id, name=name, key_hash=hash_password(key))
        self.db.add(api_key)
        self.db.commit()
        return key

    def validate_key(self, key: str) -> Optional[int]:
        # Hash and compare with stored keys
        pass

    def revoke_key(self, key_id: int):
        api_key = self.db.query(APIKey).get(key_id)
        if api_key:
            api_key.is_active = False
            self.db.commit()
"""


def _generate_auth_audit_log() -> str:
    """生成认证审计日志"""
    return """
# Authentication Audit Log
class AuthAuditLog:
    __tablename__ = "auth_audit_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    action = Column(String(50))  # login, logout, password_change, etc.
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    success = Column(Boolean)
    details = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
"""


def _generate_auth_rate_limit() -> str:
    """生成认证速率限制"""
    return """
# Authentication Rate Limiting
AUTH_RATE_LIMITS = {
    'login': '5/minute',
    'register': '3/hour',
    'password_reset': '2/hour',
    'verify_email': '5/hour',
}
"""


def _generate_device_tracking() -> str:
    """生成设备追踪"""
    return """
# Device Tracking
class DeviceTracker:
    def __init__(self, db: Session):
        self.db = db

    def record_device(self, user_id: int, device_info: dict):
        device = UserDevice(
            user_id=user_id,
            device_id=device_info.get('device_id'),
            device_name=device_info.get('device_name'),
            device_type=device_info.get('device_type'),
            ip_address=device_info.get('ip_address'),
        )
        self.db.add(device)
        self.db.commit()

    def get_user_devices(self, user_id: int) -> list:
        return self.db.query(UserDevice).filter(UserDevice.user_id == user_id).all()
"""


def _generate_consent_management() -> str:
    """生成同意管理"""
    return """
# Consent Management
class ConsentManager:
    def __init__(self, db: Session):
        self.db = db

    def record_consent(self, user_id: int, consent_type: str, granted: bool):
        consent = UserConsent(
            user_id=user_id,
            consent_type=consent_type,
            granted=granted,
        )
        self.db.add(consent)
        self.db.commit()

    def get_consent(self, user_id: int, consent_type: str) -> Optional[bool]:
        consent = self.db.query(UserConsent).filter(
            UserConsent.user_id == user_id,
            UserConsent.consent_type == consent_type,
        ).first()
        return consent.granted if consent else None
"""


def _generate_privacy_settings() -> str:
    """生成隐私设置"""
    return """
# Privacy Settings
class PrivacySettings:
    def __init__(self, db: Session):
        self.db = db

    def get_settings(self, user_id: int) -> dict:
        settings = self.db.query(UserPrivacy).filter(UserPrivacy.user_id == user_id).first()
        return settings.to_dict() if settings else self._default_settings()

    def update_settings(self, user_id: int, settings: dict):
        privacy = self.db.query(UserPrivacy).filter(UserPrivacy.user_id == user_id).first()
        if not privacy:
            privacy = UserPrivacy(user_id=user_id)
            self.db.add(privacy)
        for key, value in settings.items():
            setattr(privacy, key, value)
        self.db.commit()
"""


def _generate_data_export() -> str:
    """生成数据导出"""
    return """
# Data Export
class DataExporter:
    def __init__(self, db: Session):
        self.db = db

    def export_user_data(self, user_id: int) -> dict:
        user = self.db.query(User).get(user_id)
        return {
            'profile': user.to_dict(),
            'activity': self._get_activity(user_id),
            'settings': self._get_settings(user_id),
        }

    def request_export(self, user_id: int) -> str:
        export_id = str(uuid.uuid4())
        # Queue export job
        return export_id
"""


def _generate_account_deletion() -> str:
    """生成账户删除"""
    return """
# Account Deletion
class AccountDeletion:
    def __init__(self, db: Session):
        self.db = db

    def request_deletion(self, user_id: int) -> str:
        deletion_token = create_access_token({'sub': str(user_id), 'type': 'deletion'}, timedelta(hours=24))
        # Send confirmation email
        return deletion_token

    def confirm_deletion(self, token: str) -> bool:
        payload = verify_token(token)
        if not payload or payload.get('type') != 'deletion':
            return False
        user_id = int(payload['sub'])
        user = self.db.query(User).get(user_id)
        if user:
            user.is_active = False
            user.scheduled_deletion = datetime.utcnow() + timedelta(days=30)
            self.db.commit()
            return True
        return False
"""

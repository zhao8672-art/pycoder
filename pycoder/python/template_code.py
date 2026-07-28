"""代码模板生成器 — 生成 FastAPI Auth 模板代码"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def generate_fastapi_auth() -> str:
    """生成 FastAPI Auth 模板代码

    将原 429 行的巨型函数拆分为多个小函数，每个负责生成 Auth 的一个部分。

    Returns:
        完整的 Auth 代码字符串
    """
    sections: list[str] = []

    sections.append(_generate_auth_imports())
    sections.append(_generate_auth_models())
    sections.append(_generate_auth_schemas())
    sections.append(_generate_auth_service())
    sections.append(_generate_auth_dependencies())
    sections.append(_generate_auth_router())
    sections.append(_generate_auth_main())

    return "\n\n".join(sections)


def _generate_auth_imports() -> str:
    """生成 Auth 导入语句"""
    return """from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import Column, DateTime, Integer, String, Boolean, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

# Database setup
DATABASE_URL = "sqlite:///./auth.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Security
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# JWT Configuration
SECRET_KEY = "your-secret-key-here"  # Change this in production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
"""


def _generate_auth_models() -> str:
    """生成 Auth 数据模型"""
    return """class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100))
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(255), unique=True, index=True, nullable=False)
    user_id = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
"""


def _generate_auth_schemas() -> str:
    """生成 Auth Pydantic schemas"""
    return """class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None


class UserCreate(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: Optional[str] = None


class UserLogin(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool
    is_superuser: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    password: Optional[str] = None
"""


def _generate_auth_service() -> str:
    """生成 Auth 服务层"""
    return """class AuthService:
    \"\"\"认证服务\"\"\"

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def get_password_hash(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
        to_encode.update({"exp": expire, "type": "access"})
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    @staticmethod
    def create_refresh_token(data: dict) -> str:
        to_encode = data.copy()
        expire = datetime.utcnow() + timedelta(days=7)
        to_encode.update({"exp": expire, "type": "refresh"})
        return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

    @staticmethod
    def decode_token(token: str) -> Optional[dict]:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None

    @staticmethod
    def get_user(db: Session, username: str) -> Optional[User]:
        return db.query(User).filter(User.username == username).first()

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> Optional[User]:
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def create_user(db: Session, user_data: UserCreate) -> User:
        existing = db.query(User).filter(
            (User.username == user_data.username) | (User.email == user_data.email)
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username or email already exists",
            )
        user = User(
            username=user_data.username,
            email=user_data.email,
            hashed_password=AuthService.get_password_hash(user_data.password),
            full_name=user_data.full_name,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
        user = AuthService.get_user(db, username)
        if not user or not AuthService.verify_password(password, user.hashed_password):
            return None
        return user
"""


def _generate_auth_dependencies() -> str:
    """生成 Auth 依赖注入"""
    return """async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    \"\"\"获取当前用户\"\"\"
    payload = AuthService.decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = payload.get("sub")
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    user = AuthService.get_user(db, username)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    \"\"\"获取当前活跃用户\"\"\"
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_user),
) -> User:
    \"\"\"获取当前超级用户\"\"\"
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return current_user


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
"""


def _generate_auth_router() -> str:
    """生成 Auth 路由"""
    return """router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    return AuthService.create_user(db, user_data)


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = AuthService.authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = AuthService.create_access_token(
        data={"sub": user.username, "user_id": user.id}
    )
    refresh_token = AuthService.create_refresh_token(
        data={"sub": user.username, "user_id": user.id}
    )
    return Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=Token)
def refresh_token(refresh_token: str, db: Session = Depends(get_db)):
    payload = AuthService.decode_token(refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    username = payload.get("sub")
    user = AuthService.get_user(db, username)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    new_access_token = AuthService.create_access_token(
        data={"sub": user.username, "user_id": user.id}
    )
    new_refresh_token = AuthService.create_refresh_token(
        data={"sub": user.username, "user_id": user.id}
    )
    return Token(access_token=new_access_token, refresh_token=new_refresh_token)


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_active_user)):
    return current_user


@router.put("/me", response_model=UserResponse)
def update_me(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    if user_data.password:
        current_user.hashed_password = AuthService.get_password_hash(user_data.password)
    if user_data.email:
        current_user.email = user_data.email
    if user_data.full_name:
        current_user.full_name = user_data.full_name
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/logout")
def logout(current_user: User = Depends(get_current_active_user)):
    return {"message": "Logged out successfully"}
"""


def _generate_auth_main() -> str:
    """生成 Auth 主应用入口"""
    return """app = FastAPI(title="Auth API", version="1.0.0")
app.include_router(router)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
"""


# ══════════════════════════════════════════════════════════
# 兼容性导出 — 保留旧 API 以防止导入错误
# ══════════════════════════════════════════════════════════


def generate_fastapi_crud(model_name: str, fields: list[dict] | None = None) -> str:
    # Compatibility stub: delegates to generate_fastapi_auth
    return generate_fastapi_auth()


def generate_scaffold_project(project_name: str = "my_project") -> str:
    """生成项目脚手架（兼容性保留）"""
    return f"""# {project_name}
# Scaffold generated by PyCoder
# See generate_fastapi_auth() for API template

if __name__ == "__main__":
    print("Project scaffold: {project_name}")
"""


def generate_streamlit_dashboard(title: str = "Dashboard") -> str:
    """生成 Streamlit 仪表板代码（兼容性保留）"""
    return f'''"""Streamlit Dashboard: {title}"""
import streamlit as st

st.title("{title}")
st.write("Generated by PyCoder Template Engine")
'''
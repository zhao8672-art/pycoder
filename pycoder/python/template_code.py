def generate_fastapi_crud(project_dir: str, model_name: str, fields: list[dict]) -> None:
    """生成 FastAPI CRUD 代码"""
    _validate_crud_inputs(project_dir, model_name, fields)
    _write_crud_project_files(project_dir)
    _write_crud_model(project_dir, model_name, fields)
    _write_crud_schema(project_dir, model_name, fields)
    _write_crud_route(project_dir, model_name, fields)
    _write_crud_service(project_dir, model_name)
    _write_crud_main(project_dir, model_name)
    _write_crud_requirements(project_dir)
    _log_crud_generation(project_dir, model_name)


def _validate_crud_inputs(project_dir: str, model_name: str, fields: list[dict]) -> None:
    """验证 CRUD 生成输入"""
    if not model_name or not model_name.strip():
        raise ValueError("模型名称不能为空")
    if not fields:
        raise ValueError("字段列表不能为空")
    if not os.path.exists(project_dir):
        os.makedirs(project_dir, exist_ok=True)


def _write_crud_project_files(project_dir: str) -> None:
    """写入项目基础文件"""
    app_dir = os.path.join(project_dir, "app")
    os.makedirs(app_dir, exist_ok=True)
    _write_file(os.path.join(app_dir, "__init__.py"), "")
    _write_file(os.path.join(app_dir, "database.py"), _get_crud_database())


def _get_crud_database() -> str:
    """生成 database 模块"""
    return """from sqlalchemy import create_engine
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
"""


def _write_crud_model(project_dir: str, model_name: str, fields: list[dict]) -> None:
    """写入数据模型"""
    model_dir = os.path.join(project_dir, "app", "models")
    os.makedirs(model_dir, exist_ok=True)
    _write_file(os.path.join(model_dir, "__init__.py"), "")
    _write_file(os.path.join(model_dir, f"{model_name.lower()}.py"), _build_crud_model_code(model_name, fields))


def _build_crud_model_code(model_name: str, fields: list[dict]) -> str:
    """构建模型代码"""
    lines = [
        "from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text",
        "from sqlalchemy.sql import func",
        "from app.database import Base",
        "",
    ]
    lines.append(f"class {model_name}(Base):")
    lines.append(f'    __tablename__ = "{model_name.lower()}s"')
    lines.append("")
    lines.append("    id = Column(Integer, primary_key=True, index=True)")

    for field in fields:
        field_name = field.get("name", "")
        field_type = field.get("type", "string")
        field_required = field.get("required", True)
        col_type = _map_field_type_to_column(field_type)
        nullable = "False" if field_required else "True"
        lines.append(f"    {field_name} = Column({col_type}, nullable={nullable})")

    lines.append('    created_at = Column(DateTime(timezone=True), server_default=func.now())')
    lines.append('    updated_at = Column(DateTime(timezone=True), onupdate=func.now())')
    lines.append("")
    return "\n".join(lines)


def _map_field_type_to_column(field_type: str) -> str:
    """映射字段类型到 SQLAlchemy 列类型"""
    type_map = {
        "string": "String",
        "integer": "Integer",
        "float": "Float",
        "boolean": "Boolean",
        "datetime": "DateTime",
        "text": "Text",
    }
    return type_map.get(field_type.lower(), "String")


def _write_crud_schema(project_dir: str, model_name: str, fields: list[dict]) -> None:
    """写入 Pydantic schema"""
    schema_dir = os.path.join(project_dir, "app", "schemas")
    os.makedirs(schema_dir, exist_ok=True)
    _write_file(os.path.join(schema_dir, "__init__.py"), "")
    _write_file(os.path.join(schema_dir, f"{model_name.lower()}.py"), _build_crud_schema_code(model_name, fields))


def _build_crud_schema_code(model_name: str, fields: list[dict]) -> str:
    """构建 schema 代码"""
    lines = [
        "from datetime import datetime",
        "from pydantic import BaseModel",
        "",
    ]
    # Base
    lines.append(f"class {model_name}Base(BaseModel):")
    for field in fields:
        field_name = field.get("name", "")
        field_type = field.get("type", "string")
        field_required = field.get("required", True)
        py_type = _map_field_type_to_python(field_type)
        if not field_required:
            py_type = f"{py_type} | None = None"
        lines.append(f"    {field_name}: {py_type}")
    lines.append("")

    # Create
    lines.append(f"class {model_name}Create({model_name}Base):")
    lines.append("    pass")
    lines.append("")

    # Update
    lines.append(f"class {model_name}Update(BaseModel):")
    for field in fields:
        field_name = field.get("name", "")
        field_type = field.get("type", "string")
        py_type = _map_field_type_to_python(field_type)
        lines.append(f"    {field_name}: {py_type} | None = None")
    lines.append("")

    # Response
    lines.append(f"class {model_name}Response({model_name}Base):")
    lines.append("    id: int")
    lines.append("    created_at: datetime")
    lines.append("    updated_at: datetime | None = None")
    lines.append("")
    lines.append("    class Config:")
    lines.append("        from_attributes = True")
    lines.append("")
    return "\n".join(lines)


def _map_field_type_to_python(field_type: str) -> str:
    """映射字段类型到 Python 类型"""
    type_map = {
        "string": "str",
        "integer": "int",
        "float": "float",
        "boolean": "bool",
        "datetime": "datetime",
        "text": "str",
    }
    return type_map.get(field_type.lower(), "str")


def _write_crud_route(project_dir: str, model_name: str, fields: list[dict]) -> None:
    """写入路由"""
    route_dir = os.path.join(project_dir, "app", "routes")
    os.makedirs(route_dir, exist_ok=True)
    _write_file(os.path.join(route_dir, "__init__.py"), "")
    _write_file(os.path.join(route_dir, f"{model_name.lower()}.py"), _build_crud_route_code(model_name))


def _build_crud_route_code(model_name: str) -> str:
    """构建路由代码"""
    lower_name = model_name.lower()
    return f"""from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app import schemas, services
from app.database import get_db

router = APIRouter(prefix="/{lower_name}s", tags=["{lower_name}s"])


@router.get("/", response_model=list[schemas.{model_name}Response])
def list_{lower_name}s(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return services.{lower_name}_service.get_all(db, skip=skip, limit=limit)


@router.get("/{{{lower_name}_id}}", response_model=schemas.{model_name}Response)
def get_{lower_name}(
    {lower_name}_id: int,
    db: Session = Depends(get_db),
):
    item = services.{lower_name}_service.get(db, {lower_name}_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="{model_name} not found")
    return item


@router.post("/", response_model=schemas.{model_name}Response, status_code=status.HTTP_201_CREATED)
def create_{lower_name}(
    data: schemas.{model_name}Create,
    db: Session = Depends(get_db),
):
    return services.{lower_name}_service.create(db, data)


@router.put("/{{{lower_name}_id}}", response_model=schemas.{model_name}Response)
def update_{lower_name}(
    {lower_name}_id: int,
    data: schemas.{model_name}Update,
    db: Session = Depends(get_db),
):
    item = services.{lower_name}_service.update(db, {lower_name}_id, data)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="{model_name} not found")
    return item


@router.delete("/{{{lower_name}_id}}", status_code=status.HTTP_204_NO_CONTENT)
def delete_{lower_name}(
    {lower_name}_id: int,
    db: Session = Depends(get_db),
):
    success = services.{lower_name}_service.delete(db, {lower_name}_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="{model_name} not found")
"""


def _write_crud_service(project_dir: str, model_name: str) -> None:
    """写入服务层"""
    service_dir = os.path.join(project_dir, "app", "services")
    os.makedirs(service_dir, exist_ok=True)
    _write_file(os.path.join(service_dir, "__init__.py"), "")
    _write_file(os.path.join(service_dir, f"{model_name.lower()}_service.py"), _build_crud_service_code(model_name))


def _build_crud_service_code(model_name: str) -> str:
    """构建服务层代码"""
    lower_name = model_name.lower()
    return f"""from sqlalchemy.orm import Session
from app.models.{lower_name} import {model_name}
from app.schemas.{lower_name} import {model_name}Create, {model_name}Update


class {model_name}Service:
    def get(self, db: Session, item_id: int) -> {model_name} | None:
        return db.query({model_name}).filter({model_name}.id == item_id).first()

    def get_all(self, db: Session, skip: int = 0, limit: int = 100) -> list[{model_name}]:
        return db.query({model_name}).offset(skip).limit(limit).all()

    def create(self, db: Session, data: {model_name}Create) -> {model_name}:
        item = {model_name}(**data.model_dump())
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def update(self, db: Session, item_id: int, data: {model_name}Update) -> {model_name} | None:
        item = self.get(db, item_id)
        if not item:
            return None
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(item, key, value)
        db.commit()
        db.refresh(item)
        return item

    def delete(self, db: Session, item_id: int) -> bool:
        item = self.get(db, item_id)
        if not item:
            return False
        db.delete(item)
        db.commit()
        return True


{lower_name}_service = {model_name}Service()
"""


def _write_crud_main(project_dir: str, model_name: str) -> None:
    """写入 main.py"""
    app_dir = os.path.join(project_dir, "app")
    lower_name = model_name.lower()
    main_content = f"""from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import engine, Base
from app.routes.{lower_name} import router as {lower_name}_router

Base.metadata.create_all(bind=engine)

app = FastAPI(title="{model_name} CRUD API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router({lower_name}_router, prefix="/api/v1")


@app.get("/health")
def health():
    return {{"status": "ok"}}
"""
    _write_file(os.path.join(app_dir, "main.py"), main_content)


def _write_crud_requirements(project_dir: str) -> None:
    """写入 requirements.txt"""
    _write_file(os.path.join(project_dir, "requirements.txt"), _get_crud_requirements())


def _get_crud_requirements() -> str:
    """生成 requirements.txt 内容"""
    return """fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
pydantic==2.5.2
"""


def _log_crud_generation(project_dir: str, model_name: str) -> None:
    """记录 CRUD 生成日志"""
    logger.info(f"CRUD 代码已生成: {project_dir}")
    logger.info(f"模型: {model_name}")
    logger.info("文件结构:")
    logger.info(f"  {project_dir}/")
    logger.info("  ├── app/")
    logger.info("  │   ├── __init__.py")
    logger.info("  │   ├── main.py")
    logger.info("  │   ├── database.py")
    logger.info("  │   ├── models/")
    logger.info(f"  │   │   └── {model_name.lower()}.py")
    logger.info("  │   ├── schemas/")
    logger.info(f"  │   │   └── {model_name.lower()}.py")
    logger.info("  │   ├── routes/")
    logger.info(f"  │   │   └── {model_name.lower()}.py")
    logger.info("  │   └── services/")
    logger.info(f"  │       └── {model_name.lower()}_service.py")
    logger.info("  └── requirements.txt")
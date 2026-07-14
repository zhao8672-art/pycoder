"""
template_code.py 模块单元测试 — 覆盖率目标 >=95%

测试策略:
- generate_fastapi_crud: 默认 / 自定义 entity_name, 验证所有生成的文件
- generate_fastapi_auth: 验证生成的项目结构
- generate_streamlit_dashboard: 验证 pages 目录创建 (bug 修复点)
- generate_scaffold_project: 各 template_name 分支 + 默认 fallback
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pycoder.python import template_code as tc_mod
from pycoder.python.template_code import (
    generate_fastapi_crud,
    generate_fastapi_auth,
    generate_streamlit_dashboard,
    generate_scaffold_project,
)


# ── generate_fastapi_crud ──────────────────────────────────


class TestGenerateFastapiCrud:
    def test_default_entity(self, tmp_path):
        result = generate_fastapi_crud(tmp_path)
        # 验证所有预期文件
        assert "src/__init__.py" in result
        assert "src/database.py" in result
        assert "src/models/__init__.py" in result
        assert "src/models/item.py" in result
        assert "src/schemas/__init__.py" in result
        assert "src/schemas/item.py" in result
        assert "src/routers/__init__.py" in result
        assert "src/routers/items.py" in result
        assert "src/main.py" in result
        assert "tests/__init__.py" in result
        assert "tests/test_items.py" in result
        assert "requirements.txt" in result
        assert "README.md" in result
        # 验证文件确实存在
        assert (tmp_path / "src" / "main.py").exists()
        assert (tmp_path / "requirements.txt").exists()
        # 验证内容包含 entity
        main_content = (tmp_path / "src" / "main.py").read_text(encoding="utf-8")
        assert "Item API" in main_content

    def test_custom_entity(self, tmp_path):
        result = generate_fastapi_crud(tmp_path, entity_name="product")
        assert "src/models/product.py" in result
        assert "src/schemas/product.py" in result
        assert "src/routers/products.py" in result
        assert "tests/test_products.py" in result
        # 验证内容使用自定义 entity
        main_content = (tmp_path / "src" / "main.py").read_text(encoding="utf-8")
        assert "Product API" in main_content
        model_content = (tmp_path / "src" / "models" / "product.py").read_text(encoding="utf-8")
        assert "ProductModel" in model_content
        assert "products" in model_content  # __tablename__

    def test_creates_all_directories(self, tmp_path):
        generate_fastapi_crud(tmp_path)
        # 验证所有目录都已创建
        assert (tmp_path / "src").is_dir()
        assert (tmp_path / "src" / "models").is_dir()
        assert (tmp_path / "src" / "routers").is_dir()
        assert (tmp_path / "src" / "schemas").is_dir()
        assert (tmp_path / "tests").is_dir()

    def test_router_content_has_all_methods(self, tmp_path):
        generate_fastapi_crud(tmp_path)
        router_content = (tmp_path / "src" / "routers" / "items.py").read_text(encoding="utf-8")
        assert "@router.get" in router_content
        assert "@router.post" in router_content
        assert "@router.put" in router_content
        assert "@router.delete" in router_content

    def test_schema_content(self, tmp_path):
        generate_fastapi_crud(tmp_path)
        schema_content = (tmp_path / "src" / "schemas" / "item.py").read_text(encoding="utf-8")
        assert "ItemCreate" in schema_content
        assert "ItemUpdate" in schema_content
        assert "ItemResponse" in schema_content
        assert "PaginatedResponse" in schema_content

    def test_test_file_content(self, tmp_path):
        generate_fastapi_crud(tmp_path)
        test_content = (tmp_path / "tests" / "test_items.py").read_text(encoding="utf-8")
        assert "test_health" in test_content
        assert "test_create_item" in test_content
        assert "test_list_items" in test_content

    def test_requirements_content(self, tmp_path):
        generate_fastapi_crud(tmp_path)
        req_content = (tmp_path / "requirements.txt").read_text(encoding="utf-8")
        assert "fastapi" in req_content
        assert "uvicorn" in req_content
        assert "sqlalchemy" in req_content

    def test_readme_content(self, tmp_path):
        generate_fastapi_crud(tmp_path)
        readme_content = (tmp_path / "README.md").read_text(encoding="utf-8")
        assert "Item API" in readme_content
        assert "uvicorn" in readme_content


# ── generate_fastapi_auth ──────────────────────────────────


class TestGenerateFastapiAuth:
    def test_generates_all_files(self, tmp_path):
        result = generate_fastapi_auth(tmp_path)
        assert "src/__init__.py" in result
        assert "src/config.py" in result
        assert "src/database.py" in result
        assert "src/models/__init__.py" in result
        assert "src/models/user.py" in result
        assert "src/schemas/__init__.py" in result
        assert "src/schemas/user.py" in result
        assert "src/auth.py" in result
        assert "src/routers/__init__.py" in result
        assert "src/routers/auth.py" in result
        assert "src/main.py" in result
        assert ".env" in result
        assert "tests/__init__.py" in result
        assert "tests/test_auth.py" in result
        assert "requirements.txt" in result
        assert "README.md" in result
        # 验证文件存在
        assert (tmp_path / "src" / "auth.py").exists()
        assert (tmp_path / ".env").exists()

    def test_creates_directories(self, tmp_path):
        generate_fastapi_auth(tmp_path)
        assert (tmp_path / "src").is_dir()
        assert (tmp_path / "src" / "models").is_dir()
        assert (tmp_path / "src" / "routers").is_dir()
        assert (tmp_path / "src" / "schemas").is_dir()
        assert (tmp_path / "tests").is_dir()

    def test_auth_content(self, tmp_path):
        generate_fastapi_auth(tmp_path)
        auth_content = (tmp_path / "src" / "auth.py").read_text(encoding="utf-8")
        assert "verify_password" in auth_content
        assert "get_password_hash" in auth_content
        assert "create_access_token" in auth_content
        assert "get_current_user" in auth_content

    def test_router_content(self, tmp_path):
        generate_fastapi_auth(tmp_path)
        router_content = (tmp_path / "src" / "routers" / "auth.py").read_text(encoding="utf-8")
        assert "register" in router_content
        assert "login" in router_content
        assert "get_me" in router_content

    def test_config_content(self, tmp_path):
        generate_fastapi_auth(tmp_path)
        config_content = (tmp_path / "src" / "config.py").read_text(encoding="utf-8")
        assert "secret_key" in config_content
        assert "algorithm" in config_content

    def test_env_content(self, tmp_path):
        generate_fastapi_auth(tmp_path)
        env_content = (tmp_path / ".env").read_text(encoding="utf-8")
        assert "SECRET_KEY" in env_content
        assert "DATABASE_URL" in env_content


# ── generate_streamlit_dashboard ────────────────────────────


class TestGenerateStreamlitDashboard:
    def test_generates_all_files(self, tmp_path):
        result = generate_streamlit_dashboard(tmp_path)
        assert "app.py" in result
        assert "pages/analysis.py" in result
        assert "requirements.txt" in result
        assert "README.md" in result
        # 验证文件存在
        assert (tmp_path / "app.py").exists()
        assert (tmp_path / "pages" / "analysis.py").exists()
        # 验证 pages 目录已创建 (bug 修复点)
        assert (tmp_path / "pages").is_dir()

    def test_app_content(self, tmp_path):
        generate_streamlit_dashboard(tmp_path)
        app_content = (tmp_path / "app.py").read_text(encoding="utf-8")
        assert "streamlit" in app_content
        assert "set_page_config" in app_content
        assert "数据看板" in app_content

    def test_pages_content(self, tmp_path):
        generate_streamlit_dashboard(tmp_path)
        pages_content = (tmp_path / "pages" / "analysis.py").read_text(encoding="utf-8")
        assert "数据分析" in pages_content
        assert "file_uploader" in pages_content

    def test_requirements_content(self, tmp_path):
        generate_streamlit_dashboard(tmp_path)
        req_content = (tmp_path / "requirements.txt").read_text(encoding="utf-8")
        assert "streamlit" in req_content
        assert "pandas" in req_content
        assert "numpy" in req_content

    def test_pages_directory_creation_bugfix(self, tmp_path):
        # 这是 bug 修复点的回归测试:
        # 在修复前, generate_streamlit_dashboard 不会创建 pages 目录,
        # 导致 (tmp_path / "pages" / "analysis.py").write_text 失败
        result = generate_streamlit_dashboard(tmp_path)
        assert "pages/analysis.py" in result
        assert (tmp_path / "pages" / "analysis.py").exists()


# ── generate_scaffold_project ─────────────────────────────


class TestGenerateScaffoldProject:
    def test_fastapi_crud_template(self, tmp_path):
        result = generate_scaffold_project(tmp_path, "fastapi-crud", "item")
        assert "src/__init__.py" in result
        assert "src/main.py" in result
        assert "src/database.py" in result

    def test_fastapi_crud_template_custom_entity(self, tmp_path):
        result = generate_scaffold_project(tmp_path, "fastapi-crud", "product")
        assert "src/models/product.py" in result
        assert "src/routers/products.py" in result

    def test_fastapi_auth_template(self, tmp_path):
        result = generate_scaffold_project(tmp_path, "fastapi-auth", "item")
        assert "src/auth.py" in result
        assert "src/models/user.py" in result
        assert "src/routers/auth.py" in result

    def test_streamlit_dashboard_template(self, tmp_path):
        result = generate_scaffold_project(tmp_path, "streamlit-dashboard", "item")
        assert "app.py" in result
        assert "pages/analysis.py" in result

    def test_unknown_template_falls_back_to_fastapi_crud(self, tmp_path):
        result = generate_scaffold_project(tmp_path, "nonexistent-template", "item")
        # 默认 fallback 到 fastapi-crud
        assert "src/main.py" in result
        assert "src/database.py" in result

    def test_default_entity(self, tmp_path):
        # entity_name 默认 "item"
        result = generate_scaffold_project(tmp_path, "fastapi-crud")
        assert "src/models/item.py" in result

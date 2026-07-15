"""
多框架项目脚手架生成器 — 按模板生成项目结构

模板支持: FastAPI, Flask, Django, Express, Spring Boot, 自定义
用法: from pycoder.python.scaffold_generator import ScaffoldGenerator
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path.home() / ".pycoder" / "templates"

FASTAPI_TEMPLATE = {
    "description": "FastAPI 异步 Web 应用",
    "files": {
        "main.py": (
            '"""FastAPI 应用入口"""\n'
            "from fastapi import FastAPI\n"
            "from routers import items, users\n\n"
            'app = FastAPI(title="My API", version="0.1.0")\n'
            'app.include_router(items.router, prefix="/api/items")\n'
            'app.include_router(users.router, prefix="/api/users")\n\n'
            '@app.get("/api/health")\n'
            "async def health():\n"
            '    return {"status": "ok"}\n'
        ),
        "routers/__init__.py": "",
        "routers/items.py": (
            '"""Items 路由"""\n'
            "from fastapi import APIRouter, HTTPException\n"
            "from pydantic import BaseModel\n\n"
            "router = APIRouter()\n\n"
            "class Item(BaseModel):\n"
            "    name: str\n"
            "    price: float\n\n"
            '@router.get("/")\n'
            "async def list_items():\n"
            '    return {"items": []}\n\n'
            '@router.post("/")\n'
            "async def create_item(item: Item):\n"
            '    return {"item": item.model_dump()}\n'
        ),
        "routers/users.py": (
            '"""Users 路由"""\n'
            "from fastapi import APIRouter\n\n"
            "router = APIRouter()\n\n"
            '@router.get("/")\n'
            "async def list_users():\n"
            '    return {"users": []}\n'
        ),
        "models/__init__.py": "",
        "config.py": (
            '"""配置管理"""\n'
            "import os\n"
            'DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///app.db")\n'
        ),
        "requirements.txt": (
            "fastapi>=0.115.0\nuvicorn>=0.34.0\n" "pydantic>=2.0\nsqlalchemy>=2.0\n"
        ),
    },
}

FLASK_TEMPLATE = {
    "description": "Flask 传统 Web 应用",
    "files": {
        "app.py": (
            '"""Flask 应用入口"""\n'
            "from flask import Flask, jsonify\n\n"
            "app = Flask(__name__)\n\n"
            '@app.route("/api/health")\n'
            "def health():\n"
            '    return jsonify({"status": "ok"})\n\n'
            "if __name__ == '__main__':\n"
            "    app.run(debug=True, port=5000)\n"
        ),
        "routes/__init__.py": "",
        "routes/items.py": (
            '"""Items 路由"""\n'
            "from flask import Blueprint, request, jsonify\n\n"
            "bp = Blueprint('items', __name__, url_prefix='/api/items')\n\n"
            "@bp.route('/', methods=['GET'])\n"
            "def list_items():\n"
            '    return jsonify({"items": []})\n\n'
            "@bp.route('/', methods=['POST'])\n"
            "def create_item():\n"
            "    data = request.get_json()\n"
            '    return jsonify({"item": data}), 201\n'
        ),
        "requirements.txt": "flask>=3.0\npython-dotenv>=1.0\n",
    },
}

DJANGO_TEMPLATE = {
    "description": "Django 全栈 Web 应用",
    "files": {
        "manage.py": (
            "#!/usr/bin/env python\n"
            '"""Django 管理入口"""\n'
            "import os, sys\n\n"
            "def main():\n"
            '    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")\n'
            "    from django.core.management import execute_from_command_line\n"
            "    execute_from_command_line(sys.argv)\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        ),
        "config/__init__.py": "",
        "config/settings.py": (
            '"""Django 配置"""\n'
            "from pathlib import Path\n"
            "import os\n"
            "BASE_DIR = Path(__file__).resolve().parent.parent\n"
            'SECRET_KEY = os.environ.get("DJANGO_KEY", "dev-only")\n'
            "DEBUG = True\n"
            'ALLOWED_HOSTS = ["*"]\n'
            "INSTALLED_APPS = [\n"
            "    'django.contrib.admin',\n"
            "    'django.contrib.auth',\n"
            "    'django.contrib.contenttypes',\n"
            "    'django.contrib.sessions',\n"
            "    'django.contrib.messages',\n"
            "]\n"
            "MIDDLEWARE = [\n"
            "    'django.middleware.security.SecurityMiddleware',\n"
            "    'django.contrib.sessions.middleware.SessionMiddleware',\n"
            "    'django.middleware.common.CommonMiddleware',\n"
            "]\n"
            'ROOT_URLCONF = "config.urls"\n'
            "DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'\n"
        ),
        "config/urls.py": (
            '"""URL 配置"""\n' "from django.urls import path\n\n" "urlpatterns = []\n"
        ),
        "requirements.txt": "django>=5.0\n",
    },
}

EXPRESS_TEMPLATE = {
    "description": "Express.js Node.js Web 应用",
    "files": {
        "package.json": (
            '{"name":"my-app","version":"1.0.0","main":"index.js",'
            '"scripts":{"start":"node index.js"},"dependencies":{"express":"^4.21"}}\n'
        ),
        "index.js": (
            "const express = require('express');\n"
            "const app = express();\n"
            "app.use(express.json());\n\n"
            "app.get('/api/health', (req, res) => {\n"
            "  res.json({status:'ok'});\n"
            "});\n\n"
            "const port = process.env.PORT || 3000;\n"
            "app.listen(port, () => console.log(`Running on port ${port}`));\n"
        ),
    },
}

TEMPLATES = {
    "fastapi": FASTAPI_TEMPLATE,
    "flask": FLASK_TEMPLATE,
    "django": DJANGO_TEMPLATE,
    "express": EXPRESS_TEMPLATE,
}


@dataclass
class ScaffoldResult:
    success: bool
    project_dir: str = ""
    framework: str = ""
    files_created: int = 0
    error: str = ""


class ScaffoldGenerator:
    """多框架脚手架生成器"""

    def __init__(self):
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

    def list_templates(self) -> list[dict]:
        """列出所有可用模板"""
        result = []
        for name, tmpl in TEMPLATES.items():
            result.append(
                {
                    "name": name,
                    "description": tmpl["description"],
                    "file_count": len(tmpl["files"]),
                }
            )
        # 加载自定义模板
        for f in sorted(TEMPLATE_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                result.append(
                    {
                        "name": f.stem,
                        "description": data.get("description", "自定义模板"),
                        "file_count": len(data.get("files", {})),
                        "custom": True,
                    }
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
                logger.debug("load_custom_template_failed file=%s error=%s", f, e)
        return result

    def generate(
        self,
        framework: str,
        target_dir: str = "",
        project_name: str = "my-project",
    ) -> ScaffoldResult:
        """生成项目脚手架"""
        template = TEMPLATES.get(framework)
        if not template:
            # 尝试加载自定义模板
            custom_path = TEMPLATE_DIR / f"{framework}.json"
            if custom_path.exists():
                try:
                    data = json.loads(custom_path.read_text(encoding="utf-8"))
                    template = data
                except Exception as e:
                    return ScaffoldResult(success=False, error=f"模板加载失败: {e}")
            else:
                return ScaffoldResult(
                    success=False,
                    error=f"未知框架: {framework}。可用: {', '.join(TEMPLATES)}",
                )

        root = Path(target_dir or os.getcwd()) / project_name
        count = 0
        try:
            for file_path, content in template["files"].items():
                full_path = root / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(content, encoding="utf-8")
                count += 1

            return ScaffoldResult(
                success=True,
                project_dir=str(root),
                framework=framework,
                files_created=count,
            )
        except Exception as e:
            return ScaffoldResult(success=False, error=str(e))

    def save_template(self, name: str, description: str, files: dict) -> bool:
        """保存自定义模板"""
        data = {"description": description, "files": files}
        path = TEMPLATE_DIR / f"{name}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True

    def delete_template(self, name: str) -> bool:
        """删除自定义模板"""
        path = TEMPLATE_DIR / f"{name}.json"
        if path.exists():
            path.unlink()
            return True
        return False


_generator: ScaffoldGenerator | None = None


def get_scaffold_generator() -> ScaffoldGenerator:
    global _generator
    if _generator is None:
        _generator = ScaffoldGenerator()
    return _generator

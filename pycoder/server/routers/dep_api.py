"""Dependencies API — parse requirements.txt / pyproject.toml"""
import logging
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["dependencies"])


@router.get("/dependencies")
async def list_dependencies():
    """Parse project dependencies from requirements files"""
    deps = []
    project = Path.cwd()

    # Parse pyproject.toml
    pyproject = project / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8")
            # Extract [tool.poetry.dependencies] or [project]
            import re
            in_deps = False
            in_dev = False
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("[project]"):
                    in_deps = True
                    in_dev = False
                    continue
                if line.startswith("[tool.poetry.group.dev.dependencies]"):
                    in_dev = True
                    continue
                if line.startswith("[") and not line.startswith("[project"):
                    in_deps = False
                    in_dev = False
                    continue
                if (in_deps or in_dev) and "=" in line and not line.startswith("#"):
                    match = re.match(r'^"?([a-zA-Z][a-zA-Z0-9._-]*)"?\s*[=~^!]', line)
                    if match:
                        deps.append({
                            "name": match.group(1),
                            "version": line.split("=")[-1].strip().strip('"').strip("'"),
                            "latest": "",
                            "type": "dev" if in_dev else "runtime",
                            "description": "",
                        })
        except (OSError, re.error, ValueError) as e:
            logger.debug("parse_pyproject_failed: %s", e)
            pass

    # Parse requirements.txt
    req_file = project / "requirements.txt"
    if req_file.exists():
        try:
            for line in req_file.read_text(encoding="utf-8").split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("==")
                name = parts[0].split(">")[0].split("<")[0].split("~")[0].strip()
                version = parts[1].strip() if len(parts) > 1 else ""
                if name and not any(d["name"] == name for d in deps):
                    deps.append({
                        "name": name,
                        "version": version,
                        "latest": "",
                        "type": "runtime",
                        "description": "",
                    })
        except (OSError, ValueError) as e:
            logger.debug("parse_requirements_failed: %s", e)
            pass

    return {"dependencies": deps, "total": len(deps)}

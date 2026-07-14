"""
MCP 数据库/测试/K8s/监控工具（从 mcp_tools.py 拆分）

在 mcp_tools.py 中 import 此模块即可注册这些工具。
"""

from __future__ import annotations

import os
from pathlib import Path

from pycoder.server.mcp_tools import _register

# ══════════════════════════════════════════════════════════
# 数据库工具链
# ══════════════════════════════════════════════════════════


async def _handle_db_schema_migrate(args: dict) -> dict:
    """自动生成 alembic schema migration 脚本"""
    models_file = args.get("models_file", "")
    message = args.get("message", "auto_migration")
    try:
        import subprocess as _sp
        import sys as _sys

        alembic_dir = Path(os.getcwd()) / "migrations"
        if not alembic_dir.exists():
            r1 = _sp.run(
                [_sys.executable, "-m", "alembic", "init", "migrations"],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=os.getcwd(),
            )
            if r1.returncode != 0:
                return {"success": False, "error": f"alembic init 失败: {r1.stderr[:500]}"}

        if models_file:
            models_path = Path(models_file)
            if models_path.exists():
                import importlib.util as _util

                spec = _util.spec_from_file_location("models", models_path)
                if spec and spec.loader:
                    _util.module_from_spec(spec)
                    spec.loader.exec_module(_util.module_from_spec(spec))

        r2 = _sp.run(
            [_sys.executable, "-m", "alembic", "revision", "--autogenerate", "-m", message],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=os.getcwd(),
        )
        if r2.returncode != 0:
            return {"success": False, "error": f"迁移生成失败: {r2.stderr[:500]}"}

        version_dir = alembic_dir / "versions"
        new_files = sorted(version_dir.glob("*.py"))[-1:] if version_dir.exists() else []
        return {
            "success": True,
            "output": r2.stdout[:1000],
            "migration_file": str(new_files[0]) if new_files else "",
        }
    except FileNotFoundError:
        return {"success": False, "error": "alembic 未安装 (pip install alembic)"}
    except Exception as e:
        return {"success": False, "error": str(e)}


_register(
    name="db_schema_migrate",
    description="检测 SQLAlchemy 模型变更，自动生成 alembic 数据库迁移脚本",
    input_schema={
        "type": "object",
        "properties": {
            "models_file": {"type": "string", "description": "模型定义文件路径 (自动检测)"},
            "message": {"type": "string", "description": "迁移描述", "default": "auto_migration"},
        },
    },
    handler=_handle_db_schema_migrate,
)


async def _handle_db_query_optimize(args: dict) -> dict:
    """分析 SQL 查询，给出索引和优化建议"""
    sql = args.get("sql", "")
    db_type = args.get("db_type", "postgresql")
    if not sql:
        return {"success": False, "error": "缺少 SQL 参数"}

    suggestions = []
    sql_upper = sql.upper()
    if "SELECT *" in sql_upper:
        suggestions.append(
            {"type": "warning", "detail": "使用 SELECT * 会传输不需要的列", "severity": "medium"}
        )
    if "WHERE" in sql_upper and "ORDER BY" in sql_upper:
        suggestions.append(
            {"type": "info", "detail": "ORDER BY 应与 WHERE 条件使用联合索引", "severity": "low"}
        )
    if "NOT IN" in sql_upper:
        suggestions.append(
            {"type": "warning", "detail": "NOT IN 通常比 NOT EXISTS 慢", "severity": "medium"}
        )
    if "LIKE '%" in sql or 'LIKE "%' in sql:
        suggestions.append(
            {"type": "warning", "detail": "前缀模糊查询无法使用索引", "severity": "high"}
        )
    if "SELECT " in sql_upper and "WHERE" not in sql_upper:
        suggestions.append(
            {"type": "warning", "detail": "无 WHERE 条件的全表扫描", "severity": "high"}
        )

    return {
        "success": True,
        "suggestions": suggestions,
        "db_type": db_type,
        "summary": f"发现 {sum(1 for s in suggestions if s['severity'] == 'high')} 个高风险项",
    }


_register(
    name="db_query_optimize",
    description="分析 SQL 查询语句，检测典型性能陷阱，给出索引和优化建议",
    input_schema={
        "type": "object",
        "properties": {
            "sql": {"type": "string", "description": "要分析的 SQL 语句"},
            "db_type": {
                "type": "string",
                "enum": ["postgresql", "mysql", "sqlite"],
                "default": "postgresql",
            },
        },
        "required": ["sql"],
    },
    handler=_handle_db_query_optimize,
)


async def _handle_db_cache_analyze(args: dict) -> dict:
    """分析 Redis 缓存策略并给出建议"""
    ttl_seconds = args.get("ttl_seconds", 0)
    hit_rate = args.get("hit_rate", None)
    suggestions = []

    if ttl_seconds and ttl_seconds < 10:
        suggestions.append(
            {
                "type": "warning",
                "detail": f"TTL 仅 {ttl_seconds}s，可能导致缓存雪崩",
                "severity": "high",
            }
        )
    if hit_rate is not None and hit_rate < 50:
        suggestions.append(
            {
                "type": "warning",
                "detail": f"缓存命中率仅 {hit_rate}%，低于健康线",
                "severity": "critical",
            }
        )
    elif hit_rate is not None and hit_rate < 80:
        suggestions.append(
            {
                "type": "warning",
                "detail": f"缓存命中率 {hit_rate}%，建议优化缓存策略",
                "severity": "high",
            }
        )

    return {"success": True, "suggestions": suggestions}


_register(
    name="db_cache_analyze",
    description="分析 Redis 缓存策略（TTL/命中率），给出优化建议",
    input_schema={
        "type": "object",
        "properties": {
            "cache_pattern": {"type": "string", "description": "缓存键模式"},
            "ttl_seconds": {"type": "number", "description": "TTL 秒数", "default": 0},
            "hit_rate": {"type": "number", "description": "缓存命中率百分比 (0-100)"},
        },
    },
    handler=_handle_db_cache_analyze,
)


# ══════════════════════════════════════════════════════════
# K8s / 监控
# ══════════════════════════════════════════════════════════


async def _handle_k8s_deploy(args: dict) -> dict:
    """生成 Kubernetes 部署配置"""
    app_name = args.get("app_name", "pycoder")
    image = args.get("image", "pycoder:latest")
    replicas = args.get("replicas", 3)
    cpu_limit = args.get("cpu_limit", "500m")
    memory_limit = args.get("memory_limit", "512Mi")
    port = args.get("port", 8423)

    files = {}
    files["deployment.yaml"] = f"""apiVersion: apps/v1
kind: Deployment
metadata:
  name: {app_name}
  labels:
    app: {app_name}
spec:
  replicas: {replicas}
  selector:
    matchLabels:
      app: {app_name}
  template:
    metadata:
      labels:
        app: {app_name}
    spec:
      containers:
      - name: {app_name}
        image: {image}
        ports:
        - containerPort: {port}
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "{cpu_limit}"
            memory: "{memory_limit}"
        livenessProbe:
          httpGet:
            path: /api/health
            port: {port}
          initialDelaySeconds: 10
          periodSeconds: 15
---
apiVersion: v1
kind: Service
metadata:
  name: {app_name}-service
spec:
  selector:
    app: {app_name}
  ports:
  - port: {port}
    targetPort: {port}
  type: ClusterIP
"""
    files["ingress.yaml"] = f"""apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {app_name}-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  ingressClassName: nginx
  rules:
  - host: {app_name}.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: {app_name}-service
            port:
              number: {port}
"""
    return {
        "success": True,
        "files": files,
        "apply_commands": [f"kubectl apply -f {fname}" for fname in files],
    }


_register(
    name="k8s_deploy",
    description="生成 Kubernetes Deployment/Service/Ingress YAML 配置",
    input_schema={
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "default": "pycoder"},
            "image": {"type": "string", "default": "pycoder:latest"},
            "replicas": {"type": "number", "default": 3},
            "cpu_limit": {"type": "string", "default": "500m"},
            "memory_limit": {"type": "string", "default": "512Mi"},
            "port": {"type": "number", "default": 8423},
        },
    },
    handler=_handle_k8s_deploy,
)


async def _handle_monitoring_config(args: dict) -> dict:
    """生成 Prometheus + Grafana 监控配置"""
    app_name = args.get("app_name", "pycoder")
    port = args.get("port", 8423)
    files = {}

    files["prometheus.yml"] = f"""global:
  scrape_interval: 15s
  evaluation_interval: 15s
scrape_configs:
  - job_name: '{app_name}'
    static_configs:
      - targets: ['localhost:{port}']
        labels:
          app: {app_name}
    metrics_path: '/api/health'
"""
    return {
        "success": True,
        "files": files,
        "instructions": "启动: prometheus --config.file=prometheus.yml",
    }


_register(
    name="monitoring_config",
    description="生成 Prometheus 抓取配置",
    input_schema={
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "default": "pycoder"},
            "port": {"type": "number", "default": 8423},
        },
    },
    handler=_handle_monitoring_config,
)

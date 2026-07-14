"""覆盖率测试: pycoder/server/mcp_tools_db.py

目标: 行覆盖率 >= 95%

覆盖内容:
  - _handle_db_schema_migrate (alembic init/revision, models_file 加载, 异常分支)
  - _handle_db_query_optimize (各种 SQL 模式检测)
  - _handle_db_cache_analyze (TTL/命中率 阈值分支)
  - _handle_k8s_deploy (YAML 模板生成)
  - _handle_monitoring_config (Prometheus 配置生成)
  - 模块导入即触发 _register 调用

测试策略:
  - 直接调用 _handle_* 异步处理器
  - mock subprocess.run 模拟 alembic 命令
  - 用 tmp_path 隔离文件系统副作用
  - importlib 加载真实模型文件以覆盖 exec_module 分支
"""
from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

# 导入即触发 _register 调用 — 覆盖模块级注册代码
from pycoder.server import mcp_tools_db


# ══════════════════════════════════════════════════════════
# 模块加载 / 工具注册
# ══════════════════════════════════════════════════════════

class TestModuleImport:
    """导入模块时所有 _register 调用应已执行"""

    def test_handlers_attached(self):
        from pycoder.server.mcp_tools import _builtin_tools
        # 5 个工具应已注册
        for name in ("db_schema_migrate", "db_query_optimize",
                     "db_cache_analyze", "k8s_deploy", "monitoring_config"):
            assert name in _builtin_tools


# ══════════════════════════════════════════════════════════
# _handle_db_schema_migrate
# ══════════════════════════════════════════════════════════

class TestDbSchemaMigrate:
    """数据库 schema 迁移工具"""

    async def test_alembic_init_failure(self, tmp_path, monkeypatch):
        """migrations 目录不存在 + alembic init 失败 → 返回失败"""
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=1, stderr="init err", stdout="")
        monkeypatch.setattr(subprocess, "run", fake_run)

        r = await mcp_tools_db._handle_db_schema_migrate({"message": "init"})

        assert r["success"] is False
        assert "alembic init 失败" in r["error"]

    async def test_alembic_init_success_then_revision(self, tmp_path, monkeypatch):
        """migrations 目录不存在 → init 成功 → revision 成功 → 返回最新迁移文件"""
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))

        version_dir = tmp_path / "migrations" / "versions"
        version_dir.mkdir(parents=True)
        (version_dir / "abc123.py").write_text("# migration", encoding="utf-8")

        def fake_run(cmd, **kwargs):
            if "init" in cmd:
                # 模拟 alembic init 创建 migrations 目录
                (tmp_path / "migrations").mkdir(exist_ok=True)
                return SimpleNamespace(returncode=0, stderr="", stdout="init ok")
            return SimpleNamespace(returncode=0, stderr="", stdout="revision done")
        monkeypatch.setattr(subprocess, "run", fake_run)

        r = await mcp_tools_db._handle_db_schema_migrate({"message": "auto"})

        assert r["success"] is True
        assert "revision done" in r["output"]
        assert r["migration_file"].endswith("abc123.py")

    async def test_revision_failure(self, tmp_path, monkeypatch):
        """revision 失败 → 返回失败"""
        # 提前创建 migrations 目录跳过 init
        (tmp_path / "migrations").mkdir()
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=1, stderr="revision err", stdout="")
        monkeypatch.setattr(subprocess, "run", fake_run)

        r = await mcp_tools_db._handle_db_schema_migrate({"message": "x"})

        assert r["success"] is False
        assert "迁移生成失败" in r["error"]

    async def test_revision_success_no_versions_dir(self, tmp_path, monkeypatch):
        """revision 成功但 versions 目录不存在 → 返回空 migration_file"""
        (tmp_path / "migrations").mkdir()
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stderr="", stdout="ok")
        monkeypatch.setattr(subprocess, "run", fake_run)

        r = await mcp_tools_db._handle_db_schema_migrate({})

        assert r["success"] is True
        assert r["migration_file"] == ""

    async def test_with_models_file(self, tmp_path, monkeypatch):
        """提供 models_file 且文件存在 → 触发 importlib 加载分支"""
        (tmp_path / "migrations").mkdir()
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))

        # 创建一个简单的 models 文件（可被 exec_module 执行）
        models_file = tmp_path / "models.py"
        models_file.write_text("class Model: pass\n", encoding="utf-8")

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stderr="", stdout="ok")
        monkeypatch.setattr(subprocess, "run", fake_run)

        r = await mcp_tools_db._handle_db_schema_migrate({"models_file": str(models_file)})

        assert r["success"] is True

    async def test_with_nonexistent_models_file(self, tmp_path, monkeypatch):
        """models_file 路径不存在 → 跳过模型加载分支"""
        (tmp_path / "migrations").mkdir()
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))

        def fake_run(cmd, **kwargs):
            return SimpleNamespace(returncode=0, stderr="", stdout="ok")
        monkeypatch.setattr(subprocess, "run", fake_run)

        r = await mcp_tools_db._handle_db_schema_migrate(
            {"models_file": str(tmp_path / "nope.py")},
        )

        assert r["success"] is True

    async def test_alembic_not_installed(self, tmp_path, monkeypatch):
        """subprocess.run 抛 FileNotFoundError → 返回未安装错误"""
        (tmp_path / "migrations").mkdir()
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))

        def boom(*a, **k):
            raise FileNotFoundError("alembic not found")
        monkeypatch.setattr(subprocess, "run", boom)

        r = await mcp_tools_db._handle_db_schema_migrate({})

        assert r["success"] is False
        assert "alembic 未安装" in r["error"]

    async def test_generic_exception(self, tmp_path, monkeypatch):
        """其他异常 → 返回错误字符串"""
        (tmp_path / "migrations").mkdir()
        monkeypatch.setattr("os.getcwd", lambda: str(tmp_path))

        def boom(*a, **k):
            raise RuntimeError("disk full")
        monkeypatch.setattr(subprocess, "run", boom)

        r = await mcp_tools_db._handle_db_schema_migrate({})

        assert r["success"] is False
        assert "disk full" in r["error"]


# ══════════════════════════════════════════════════════════
# _handle_db_query_optimize
# ══════════════════════════════════════════════════════════

class TestDbQueryOptimize:
    """SQL 查询优化建议工具"""

    async def test_missing_sql(self):
        r = await mcp_tools_db._handle_db_query_optimize({})
        assert r["success"] is False
        assert "缺少 SQL 参数" in r["error"]

    async def test_select_star_warning(self):
        r = await mcp_tools_db._handle_db_query_optimize({"sql": "SELECT * FROM users"})
        assert r["success"] is True
        types_ = [s["type"] for s in r["suggestions"]]
        assert "warning" in types_

    async def test_where_order_by_info(self):
        sql = "SELECT id FROM users WHERE id = 1 ORDER BY id"
        r = await mcp_tools_db._handle_db_query_optimize({"sql": sql})
        details = [s["detail"] for s in r["suggestions"]]
        assert any("ORDER BY" in d for d in details)

    async def test_not_in_warning(self):
        r = await mcp_tools_db._handle_db_query_optimize({"sql": "SELECT * FROM t WHERE id NOT IN (1,2)"})
        details = [s["detail"] for s in r["suggestions"]]
        assert any("NOT IN" in d for d in details)

    async def test_like_prefix_warning(self):
        r = await mcp_tools_db._handle_db_query_optimize({"sql": "SELECT * FROM t WHERE name LIKE '%abc'"})
        details = [s["detail"] for s in r["suggestions"]]
        assert any("前缀模糊" in d for d in details)

    async def test_like_double_quote(self):
        r = await mcp_tools_db._handle_db_query_optimize({'sql': 'SELECT * FROM t WHERE name LIKE "%abc"'})
        details = [s["detail"] for s in r["suggestions"]]
        assert any("前缀模糊" in d for d in details)

    async def test_full_scan_warning(self):
        """SELECT 但无 WHERE → 高风险全表扫描"""
        r = await mcp_tools_db._handle_db_query_optimize({"sql": "SELECT id FROM users"})
        details = [s["detail"] for s in r["suggestions"]]
        assert any("全表扫描" in d for d in details)

    async def test_summary_high_risk_count(self):
        """summary 字段统计高风险数"""
        sql = "SELECT * FROM t WHERE name LIKE '%abc'"
        r = await mcp_tools_db._handle_db_query_optimize({"sql": sql})
        assert "高风险项" in r["summary"]

    async def test_db_type_passthrough(self):
        r = await mcp_tools_db._handle_db_query_optimize({"sql": "SELECT 1", "db_type": "mysql"})
        assert r["db_type"] == "mysql"


# ══════════════════════════════════════════════════════════
# _handle_db_cache_analyze
# ══════════════════════════════════════════════════════════

class TestDbCacheAnalyze:
    """Redis 缓存分析工具"""

    async def test_default_no_suggestions(self):
        r = await mcp_tools_db._handle_db_cache_analyze({})
        assert r["success"] is True
        assert r["suggestions"] == []

    async def test_low_ttl_warning(self):
        r = await mcp_tools_db._handle_db_cache_analyze({"ttl_seconds": 5})
        assert len(r["suggestions"]) == 1
        assert r["suggestions"][0]["severity"] == "high"
        assert "缓存雪崩" in r["suggestions"][0]["detail"]

    async def test_zero_ttl_no_warning(self):
        """ttl=0 时不触发警告（falsy）"""
        r = await mcp_tools_db._handle_db_cache_analyze({"ttl_seconds": 0})
        assert r["suggestions"] == []

    async def test_hit_rate_critical(self):
        """命中率 < 50 → critical"""
        r = await mcp_tools_db._handle_db_cache_analyze({"hit_rate": 30})
        assert r["suggestions"][0]["severity"] == "critical"
        assert "30%" in r["suggestions"][0]["detail"]

    async def test_hit_rate_high_severity(self):
        """50 <= 命中率 < 80 → high"""
        r = await mcp_tools_db._handle_db_cache_analyze({"hit_rate": 60})
        assert r["suggestions"][0]["severity"] == "high"

    async def test_hit_rate_healthy(self):
        """命中率 >= 80 → 无警告"""
        r = await mcp_tools_db._handle_db_cache_analyze({"hit_rate": 90})
        assert r["suggestions"] == []

    async def test_boundary_hit_rate_50(self):
        """边界值 50 → high (elif 分支)"""
        r = await mcp_tools_db._handle_db_cache_analyze({"hit_rate": 50})
        assert r["suggestions"][0]["severity"] == "high"

    async def test_boundary_hit_rate_80(self):
        """边界值 80 → 健康"""
        r = await mcp_tools_db._handle_db_cache_analyze({"hit_rate": 80})
        assert r["suggestions"] == []

    async def test_ttl_and_low_hit_rate(self):
        """TTL 低 + 命中率低 → 两条建议"""
        r = await mcp_tools_db._handle_db_cache_analyze({"ttl_seconds": 5, "hit_rate": 30})
        assert len(r["suggestions"]) == 2


# ══════════════════════════════════════════════════════════
# _handle_k8s_deploy
# ══════════════════════════════════════════════════════════

class TestK8sDeploy:
    """K8s 部署配置生成"""

    async def test_default_args(self):
        r = await mcp_tools_db._handle_k8s_deploy({})
        assert r["success"] is True
        assert "deployment.yaml" in r["files"]
        assert "ingress.yaml" in r["files"]
        # 默认值
        assert "name: pycoder" in r["files"]["deployment.yaml"]
        assert "replicas: 3" in r["files"]["deployment.yaml"]
        # apply_commands 列表
        assert len(r["apply_commands"]) == 2
        assert all(c.startswith("kubectl apply -f") for c in r["apply_commands"])

    async def test_custom_args(self):
        r = await mcp_tools_db._handle_k8s_deploy({
            "app_name": "myapp",
            "image": "myimg:v1",
            "replicas": 5,
            "cpu_limit": "1000m",
            "memory_limit": "1Gi",
            "port": 8080,
        })
        assert r["success"] is True
        dep = r["files"]["deployment.yaml"]
        assert "name: myapp" in dep
        assert "image: myimg:v1" in dep
        assert "replicas: 5" in dep
        assert 'cpu: "1000m"' in dep
        assert 'memory: "1Gi"' in dep
        assert "containerPort: 8080" in dep
        ing = r["files"]["ingress.yaml"]
        assert "name: myapp-ingress" in ing
        assert "myapp.example.com" in ing


# ══════════════════════════════════════════════════════════
# _handle_monitoring_config
# ══════════════════════════════════════════════════════════

class TestMonitoringConfig:
    """Prometheus 配置生成"""

    async def test_default(self):
        r = await mcp_tools_db._handle_monitoring_config({})
        assert r["success"] is True
        assert "prometheus.yml" in r["files"]
        assert "pycoder" in r["files"]["prometheus.yml"]
        assert "8423" in r["files"]["prometheus.yml"]
        assert "prometheus --config.file" in r["instructions"]

    async def test_custom(self):
        r = await mcp_tools_db._handle_monitoring_config({
            "app_name": "svc", "port": 9090,
        })
        assert r["success"] is True
        cfg = r["files"]["prometheus.yml"]
        assert "svc" in cfg
        assert "9090" in cfg

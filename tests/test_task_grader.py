"""TaskGrader 任务难度分级器测试 — Codex 风格动态算力分配"""

from __future__ import annotations

import pytest

from pycoder.server.services.task_grader import (
    HEAVY_CONFIG,
    LEVEL_CONFIG_MAP,
    LIGHT_CONFIG,
    MEDIUM_CONFIG,
    TaskGrade,
    TaskGrader,
)


class TestTaskGrader:
    """TaskGrader 单元测试"""

    @pytest.fixture
    def grader(self) -> TaskGrader:
        """创建 TaskGrader 实例"""
        return TaskGrader()

    # ── 基础测试 ──

    def test_create_grader(self, grader: TaskGrader) -> None:
        """创建分级器实例"""
        assert isinstance(grader, TaskGrader)

    # ── 难度分级测试 ──

    def test_grade_light_task(self, grader: TaskGrader) -> None:
        """简单任务 → LIGHT"""
        result = grader.grade("fix a typo in README")
        assert result.level == "LIGHT"
        assert result.max_steps == LIGHT_CONFIG.max_steps
        assert result.temperature == LIGHT_CONFIG.temperature
        assert result.max_tokens == LIGHT_CONFIG.max_tokens
        assert result.reasoning_depth == "fast"
        assert result.score < 15

    def test_grade_medium_task(self, grader: TaskGrader) -> None:
        """中等任务 → MEDIUM"""
        medium_desc = "add a new API endpoint with database CRUD operations and user authentication"
        result = grader.grade(medium_desc)
        assert result.level == "MEDIUM"
        assert result.max_steps == MEDIUM_CONFIG.max_steps
        assert result.temperature == MEDIUM_CONFIG.temperature
        assert result.max_tokens == MEDIUM_CONFIG.max_tokens
        assert result.reasoning_depth == "standard"
        assert 15 <= result.score < 50

    def test_grade_heavy_task(self, grader: TaskGrader) -> None:
        """重量级任务 → HEAVY"""
        heavy_desc = (
            "migrate the entire distributed microservice architecture "
            "to Kubernetes with enterprise deployment pipeline"
        )
        result = grader.grade(heavy_desc)
        assert result.level == "HEAVY"
        assert result.max_steps == HEAVY_CONFIG.max_steps
        assert result.temperature == HEAVY_CONFIG.temperature
        assert result.max_tokens == HEAVY_CONFIG.max_tokens
        assert result.reasoning_depth == "deep"
        assert result.score >= 50

    def test_grade_empty(self, grader: TaskGrader) -> None:
        """空任务 → 默认级别（评分 0，应归为 LIGHT）"""
        result = grader.grade("")
        assert result.level == "LIGHT"
        assert result.score == 0
        assert result.max_steps == LIGHT_CONFIG.max_steps

    # ── 关键词评分测试 ──

    def test_grade_by_keywords(self, grader: TaskGrader) -> None:
        """验证关键词评分机制"""
        # 包含 HEAVY 关键词 "architecture" + "distributed" + "migrate" + "microservice" → HEAVY
        heavy_desc = (
            "migrate the enterprise architecture to a distributed "
            "microservice system with Kubernetes cluster deployment"
        )
        heavy = grader.grade(heavy_desc)
        assert heavy.level == "HEAVY"
        assert "architecture" in heavy.detected_types

        # 包含 MEDIUM 关键词 "api" + "refactor" → MEDIUM 或 HEAVY
        medium = grader.grade("refactor the user API endpoints")
        assert medium.level in ("MEDIUM", "HEAVY")
        assert "refactor" in medium.detected_types

        # 包含 LIGHT 关键词 "simple" + "fix typo" → LIGHT
        light = grader.grade("simple fix typo in comment")
        assert light.level == "LIGHT"
        assert light.score < 15

        # 纯中文关键词测试
        light_cn = grader.grade("修复拼写错误")
        assert light_cn.level == "LIGHT"

        medium_cn = grader.grade("添加用户认证和登录接口")
        assert medium_cn.level in ("MEDIUM", "HEAVY")

        heavy_cn = grader.grade("重构整个微服务架构，迁移到 Kubernetes 集群")
        assert heavy_cn.level == "HEAVY"

    # ── 配置获取测试 ──

    def test_get_grade_config(self) -> None:
        """获取指定级别的配置"""
        # LIGHT 配置
        config = LEVEL_CONFIG_MAP["LIGHT"]
        assert config.level == "LIGHT"
        assert config.label == "轻量"
        assert config.min_steps == 5
        assert config.max_steps == 10
        assert config.temperature == 0.3
        assert config.max_tokens == 4096
        assert config.reasoning_depth == "fast"

        # MEDIUM 配置
        config = LEVEL_CONFIG_MAP["MEDIUM"]
        assert config.level == "MEDIUM"
        assert config.label == "中等"
        assert config.min_steps == 15
        assert config.max_steps == 25
        assert config.temperature == 0.2
        assert config.max_tokens == 8192
        assert config.reasoning_depth == "standard"

        # HEAVY 配置
        config = LEVEL_CONFIG_MAP["HEAVY"]
        assert config.level == "HEAVY"
        assert config.label == "重量级"
        assert config.min_steps == 30
        assert config.max_steps == 120
        assert config.temperature == 0.15
        assert config.max_tokens == 16384
        assert config.reasoning_depth == "deep"

    # ── 步数估算测试 ──

    def test_estimate_steps(self) -> None:
        """估算各级别步数"""
        test_cases = [
            (LIGHT_CONFIG, (5, 10)),
            (MEDIUM_CONFIG, (15, 25)),
            (HEAVY_CONFIG, (30, 120)),
        ]

        for config, (expected_min, expected_max) in test_cases:
            grade = TaskGrade(
                level=config.level,
                max_steps=config.max_steps,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                reasoning_depth=config.reasoning_depth,
                description=config.description,
            )
            assert grade.max_steps == expected_max

            # 构造最低分和最高分场景验证步数范围
            light_grade = TaskGrade(
                level="LIGHT",
                max_steps=LIGHT_CONFIG.max_steps,
                temperature=LIGHT_CONFIG.temperature,
                max_tokens=LIGHT_CONFIG.max_tokens,
                reasoning_depth=LIGHT_CONFIG.reasoning_depth,
                description=LIGHT_CONFIG.description,
            )
            assert light_grade.max_steps >= LIGHT_CONFIG.min_steps

            heavy_grade = TaskGrade(
                level="HEAVY",
                max_steps=HEAVY_CONFIG.max_steps,
                temperature=HEAVY_CONFIG.temperature,
                max_tokens=HEAVY_CONFIG.max_tokens,
                reasoning_depth=HEAVY_CONFIG.reasoning_depth,
                description=HEAVY_CONFIG.description,
            )
            assert heavy_grade.max_steps >= HEAVY_CONFIG.min_steps

    # ── 附加测试 ──

    def test_grade_result_has_all_fields(self, grader: TaskGrader) -> None:
        """分级结果包含所有必要字段"""
        result = grader.grade("add a new feature for user dashboard")
        assert result.level in ("LIGHT", "MEDIUM", "HEAVY")
        assert result.max_steps > 0
        assert 0.0 < result.temperature <= 1.0
        assert result.max_tokens > 0
        assert result.reasoning_depth in ("fast", "standard", "deep")
        assert isinstance(result.description, str) and len(result.description) > 0
        assert 0 <= result.score <= 100
        assert isinstance(result.detected_types, list)

    def test_grade_to_dict(self, grader: TaskGrader) -> None:
        """分级结果可序列化为字典"""
        result = grader.grade("optimize database queries")
        d = result.to_dict()
        assert d["level"] == result.level
        assert d["max_steps"] == result.max_steps
        assert d["temperature"] == result.temperature
        assert d["score"] == result.score
        assert d["detected_types"] == result.detected_types

    def test_get_execution_params(self, grader: TaskGrader) -> None:
        """获取执行参数"""
        grade = grader.grade("create a REST API endpoint")
        params = grader.get_execution_params(grade)
        assert params["level"] == grade.level
        assert params["max_steps"] == grade.max_steps
        assert params["temperature"] == grade.temperature
        assert params["max_tokens"] == grade.max_tokens
        assert "stop_sequences" in params
        assert "top_p" in params
        assert "frequency_penalty" in params

    def test_task_type_detection(self, grader: TaskGrader) -> None:
        """任务类型检测"""
        # Bug 修复
        result = grader.grade("fix a bug in the login handler")
        assert "bug_fix" in result.detected_types

        # 新功能
        result = grader.grade("add a new feature for exporting reports")
        assert "feature" in result.detected_types

        # 重构
        result = grader.grade("refactor the database layer")
        assert "refactor" in result.detected_types

        # 迁移
        result = grader.grade("migrate from SQLite to PostgreSQL")
        assert "migration" in result.detected_types

        # 架构设计
        result = grader.grade("design the system architecture")
        assert "architecture" in result.detected_types
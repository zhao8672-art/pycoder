"""TaskGrader 任务难度分级器测试 — Codex 风格动态算力分配"""

from __future__ import annotations

import pytest

from pycoder.server.services.task_grader import (
    GRADE_CONFIG,
    SCORE_THRESHOLDS,
    GradeLevel,
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

    def test_default_weights(self, grader: TaskGrader) -> None:
        """默认权重和为 1.0"""
        total = sum(grader._weights.values())
        assert abs(total - 1.0) < 0.01

    # ── 难度分级测试 ──

    def test_grade_light_task(self, grader: TaskGrader) -> None:
        """简单任务 → LIGHT"""
        result = grader.assess("fix a typo in README")
        assert result.level == GradeLevel.LIGHT
        assert 5 <= result.max_iterations <= 10
        assert result.temperature == 0.3
        assert result.max_tokens == 2048
        assert result.score < 35

    def test_grade_medium_task(self, grader: TaskGrader) -> None:
        """中等任务 → MEDIUM（使用上下文增强评分）"""
        result = grader.assess(
            "add a new API endpoint with database CRUD operations and user authentication",
            context={"files": 4, "dependencies": 3, "domain": "backend"},
        )
        assert result.level == GradeLevel.MEDIUM
        assert 15 <= result.max_iterations <= 25
        assert result.temperature == 0.2
        assert result.max_tokens == 4096
        assert 35 <= result.score < 70

    def test_grade_heavy_task(self, grader: TaskGrader) -> None:
        """重量级任务 → HEAVY（使用上下文增强评分）"""
        result = grader.assess(
            "migrate the entire distributed microservice architecture "
            "to Kubernetes with enterprise deployment pipeline",
            context={"files": 15, "dependencies": 8, "domain": "architecture", "scope": "architecture"},
        )
        assert result.level == GradeLevel.HEAVY
        assert 30 <= result.max_iterations <= 120
        assert result.temperature == 0.15
        assert result.max_tokens == 8192
        assert result.score >= 70

    def test_grade_empty(self, grader: TaskGrader) -> None:
        """空任务 → 默认级别（评分 0，应归为 LIGHT）"""
        result = grader.assess("")
        assert result.level == GradeLevel.LIGHT
        assert result.score < 35

    def test_grade_with_context(self, grader: TaskGrader) -> None:
        """带上下文的评估"""
        result = grader.assess(
            "实现用户认证模块",
            context={"files": 5, "dependencies": 3, "domain": "security"},
        )
        assert result.level in (GradeLevel.MEDIUM, GradeLevel.HEAVY)
        assert result.dimensions  # 应包含各维度得分

    # ── 关键词评分测试 ──

    def test_grade_security_task(self, grader: TaskGrader) -> None:
        """安全类任务应有较高评分"""
        result = grader.assess("实现 JWT 认证和 RBAC 权限控制，防止 XSS 攻击")
        # 安全领域基础分较高
        assert result.dimensions["domain_expertise"] >= 40

    def test_grade_architecture_task(self, grader: TaskGrader) -> None:
        """架构类任务 + 上下文 → HEAVY"""
        result = grader.assess(
            "重构整个微服务架构，设计新的分布式系统架构",
            context={"files": 20, "dependencies": 10, "domain": "architecture", "scope": "architecture"},
        )
        assert result.level == GradeLevel.HEAVY

    def test_grade_bug_fix_task(self, grader: TaskGrader) -> None:
        """Bug 修复 → LIGHT 或 MEDIUM"""
        result = grader.assess("修复登录页面的一个拼写错误")
        assert result.level in (GradeLevel.LIGHT, GradeLevel.MEDIUM)

    def test_grade_chinese_task(self, grader: TaskGrader) -> None:
        """中文任务描述 + 上下文"""
        result = grader.assess(
            "添加用户认证和登录接口，包括数据库迁移",
            context={"files": 3, "dependencies": 4, "domain": "backend"},
        )
        assert result.level in (GradeLevel.MEDIUM, GradeLevel.HEAVY)

    # ── 配置测试 ──

    def test_grade_config_light(self) -> None:
        """LIGHT 级别配置"""
        config = GRADE_CONFIG[GradeLevel.LIGHT]
        assert config["max_iterations"] == (5, 10)
        assert config["temperature"] == 0.3
        assert config["max_tokens"] == 2048
        assert config["label"] == "简单"

    def test_grade_config_medium(self) -> None:
        """MEDIUM 级别配置"""
        config = GRADE_CONFIG[GradeLevel.MEDIUM]
        assert config["max_iterations"] == (15, 25)
        assert config["temperature"] == 0.2
        assert config["max_tokens"] == 4096
        assert config["label"] == "中等"

    def test_grade_config_heavy(self) -> None:
        """HEAVY 级别配置"""
        config = GRADE_CONFIG[GradeLevel.HEAVY]
        assert config["max_iterations"] == (30, 120)
        assert config["temperature"] == 0.15
        assert config["max_tokens"] == 8192
        assert config["label"] == "复杂"

    def test_score_thresholds(self) -> None:
        """评分阈值"""
        assert SCORE_THRESHOLDS[GradeLevel.LIGHT] == (0.0, 35.0)
        assert SCORE_THRESHOLDS[GradeLevel.MEDIUM] == (35.0, 70.0)
        assert SCORE_THRESHOLDS[GradeLevel.HEAVY] == (70.0, 100.0)

    # ── 序列化测试 ──

    def test_grade_to_dict(self, grader: TaskGrader) -> None:
        """分级结果可序列化为字典"""
        result = grader.assess("optimize database queries")
        d = result.to_dict()
        assert d["level"] == result.level.name
        assert d["max_iterations"] == result.max_iterations
        assert d["temperature"] == result.temperature
        assert d["score"] == round(result.score, 1)
        assert "dimensions" in d
        assert "reasoning" in d

    def test_grade_result_has_all_fields(self, grader: TaskGrader) -> None:
        """分级结果包含所有必要字段"""
        result = grader.assess("add a new feature for user dashboard")
        assert result.level in (GradeLevel.LIGHT, GradeLevel.MEDIUM, GradeLevel.HEAVY)
        assert result.max_iterations > 0
        assert 0.0 < result.temperature <= 1.0
        assert result.max_tokens > 0
        assert isinstance(result.score, float)
        assert 0 <= result.score <= 100
        assert isinstance(result.dimensions, dict)
        assert len(result.dimensions) == 5  # 5 个维度
        assert isinstance(result.reasoning, list)
        assert len(result.reasoning) > 0  # 至少有一条理由

    # ── 统计测试 ──

    def test_get_stats(self, grader: TaskGrader) -> None:
        """获取统计信息"""
        grader.assess("task 1")
        grader.assess("task 2")
        stats = grader.get_stats()
        assert stats["total_assessments"] == 2
        assert "level_distribution" in stats
        assert "average_score" in stats

    # ── 权重调整测试 ──

    def test_set_weights_valid(self, grader: TaskGrader) -> None:
        """设置有效权重"""
        new_weights = {
            "code_volume": 0.30,
            "dep_complexity": 0.20,
            "domain_expertise": 0.20,
            "change_scope": 0.15,
            "constraints": 0.15,
        }
        grader.set_weights(new_weights)
        assert grader._weights == new_weights

    def test_set_weights_invalid(self, grader: TaskGrader) -> None:
        """设置无效权重（总和不为 1.0）"""
        with pytest.raises(ValueError):
            grader.set_weights({"code_volume": 0.5, "dep_complexity": 0.3})

    # ── 维度评分测试 ──

    def test_score_code_volume_with_files(self, grader: TaskGrader) -> None:
        """带文件数的代码量评分"""
        score = grader._score_code_volume("test", {"files": 8})
        assert score >= 60  # 8 文件应得较高分

    def test_score_code_volume_no_files(self, grader: TaskGrader) -> None:
        """无文件数的代码量评分"""
        score = grader._score_code_volume("fix typo", {})
        assert 20 <= score <= 40  # 基础分加少量关键词

    def test_score_dep_complexity(self, grader: TaskGrader) -> None:
        """依赖复杂度评分"""
        score = grader._score_dep_complexity(
            "集成 Redis 和 Kafka 消息队列", {"dependencies": 4}
        )
        assert score >= 30

    def test_score_domain_expertise(self, grader: TaskGrader) -> None:
        """领域专业性评分"""
        score = grader._score_domain_expertise(
            "使用 PyTorch 训练深度学习模型", {}
        )
        assert score >= 50  # machine_learning 领域

    def test_score_change_scope(self, grader: TaskGrader) -> None:
        """变更范围评分"""
        score = grader._score_change_scope("架构重构整个项目", {})
        assert score >= 70

    def test_score_constraints(self, grader: TaskGrader) -> None:
        """约束条件评分"""
        score = grader._score_constraints(
            "高性能 低延迟 高并发 安全 加密", {}
        )
        assert score >= 50

    # ── GradeLevel 枚举测试 ──

    def test_grade_level_values(self) -> None:
        """GradeLevel 枚举值"""
        assert GradeLevel.LIGHT == 1
        assert GradeLevel.MEDIUM == 2
        assert GradeLevel.HEAVY == 3

    def test_grade_level_comparison(self) -> None:
        """GradeLevel 可比较"""
        assert GradeLevel.LIGHT < GradeLevel.MEDIUM
        assert GradeLevel.MEDIUM < GradeLevel.HEAVY
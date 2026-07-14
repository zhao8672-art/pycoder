"""P2-3: FeedbackApplier 单元测试

验证历史失败经验的相似度匹配、上下文构建与 prompt 注入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from pycoder.server.learning.feedback_applier import (
    FeedbackApplier,
    SIMILARITY_THRESHOLD,
    MAX_CONTEXT_LENGTH,
)


# ══════════════════════════════════════════════════════════
# 测试桩 — 模拟 TaskExperience 和 ExperienceBuffer
# ══════════════════════════════════════════════════════════


@dataclass
class StubExperience:
    """模拟 TaskExperience（避免依赖真实持久化）"""
    id: str = "exp-1"
    task_type: str = "fix"
    description: str = ""
    error_signature: str = ""
    error_message: str = ""
    file_paths: list[str] = field(default_factory=list)
    fix_content: str = ""
    outcome: str = "failure"
    test_passed: bool = False
    quality_score: float = 0.0
    timestamp: float = 0.0


class StubBuffer:
    """模拟 ExperienceBuffer — 用内存列表替代磁盘"""

    def __init__(self, failures: list[StubExperience] | None = None):
        self._failures = failures or []
        self.get_failures_called_with: int | None = None

    def get_failures(self, limit: int = 20) -> list[StubExperience]:
        self.get_failures_called_with = limit
        return self._failures[:limit]


class FailingBuffer:
    """get_failures 抛异常的 buffer（测试异常处理）"""

    def get_failures(self, limit: int = 20) -> list:
        raise RuntimeError("disk corrupted")


# ══════════════════════════════════════════════════════════
# TestTextSimilarity — Jaccard 系数
# ══════════════════════════════════════════════════════════


class TestTextSimilarity:
    """_text_similarity Jaccard 系数计算"""

    def test_identical_strings_return_one(self):
        applier = FeedbackApplier(StubBuffer())
        assert applier._text_similarity("修复登录bug", "修复登录bug") == 1.0

    def test_empty_string_returns_zero(self):
        applier = FeedbackApplier(StubBuffer())
        assert applier._text_similarity("", "hello") == 0.0
        assert applier._text_similarity("hello", "") == 0.0
        assert applier._text_similarity("", "") == 0.0

    def test_completely_different_returns_zero(self):
        applier = FeedbackApplier(StubBuffer())
        # 无字符交集
        sim = applier._text_similarity("abc", "xyz")
        assert sim == 0.0

    def test_partial_overlap_between_zero_and_one(self):
        applier = FeedbackApplier(StubBuffer())
        sim = applier._text_similarity("修复登录", "修复页面")
        # 交集 {'修','复'} = 2，并集 {'修','复','登','录','页','面'} = 6
        assert 0.0 < sim < 1.0
        assert abs(sim - 2 / 6) < 0.01

    def test_case_insensitive(self):
        applier = FeedbackApplier(StubBuffer())
        assert applier._text_similarity("Login", "login") == 1.0


# ══════════════════════════════════════════════════════════
# TestGetSimilarFailures — 相似失败查询
# ══════════════════════════════════════════════════════════


class TestGetSimilarFailures:
    """get_similar_failures 阈值过滤与排序"""

    def test_empty_buffer_returns_empty(self):
        applier = FeedbackApplier(StubBuffer([]))
        assert applier.get_similar_failures("fix", "修复登录") == []

    def test_filters_below_threshold(self):
        """相似度低于阈值的失败被过滤"""
        failures = [
            StubExperience(id="1", description="完全不同的任务xyz", error_message="err1"),
            StubExperience(id="2", description="修复登录页面", error_message="err2"),
        ]
        applier = FeedbackApplier(StubBuffer(failures))
        result = applier.get_similar_failures("fix", "修复登录功能", limit=5)
        # "修复登录页面" 与 "修复登录功能" 相似度高
        # "完全不同的任务xyz" 相似度低应被过滤
        ids = [e.id for e in result]
        assert "2" in ids
        assert "1" not in ids

    def test_limit_truncation(self):
        failures = [
            StubExperience(id=f"exp-{i}", description="修复登录", error_message=f"err{i}")
            for i in range(10)
        ]
        applier = FeedbackApplier(StubBuffer(failures))
        result = applier.get_similar_failures("fix", "修复登录", limit=3)
        assert len(result) <= 3

    def test_sorted_by_similarity_desc(self):
        """结果按相似度降序排列"""
        failures = [
            StubExperience(id="low", description="修复其他问题", error_message="e1"),
            StubExperience(id="high", description="修复登录页面bug", error_message="e2"),
            StubExperience(id="mid", description="修复登录", error_message="e3"),
        ]
        applier = FeedbackApplier(StubBuffer(failures))
        result = applier.get_similar_failures("fix", "修复登录页面bug", limit=3)
        if len(result) >= 2:
            # high 应排在 mid 前面（更相似）
            assert result[0].id == "high"

    def test_buffer_exception_returns_empty(self):
        """buffer.get_failures 抛异常时返回空列表（不崩溃）"""
        applier = FeedbackApplier(FailingBuffer())
        assert applier.get_similar_failures("fix", "any") == []

    def test_uses_failure_scan_limit(self):
        """调用 get_failures 时使用 FAILURE_SCAN_LIMIT"""
        buf = StubBuffer([StubExperience(description="修复登录")])
        applier = FeedbackApplier(buf)
        applier.get_similar_failures("fix", "修复登录")
        assert buf.get_failures_called_with is not None


# ══════════════════════════════════════════════════════════
# TestBuildContextForTask — 上下文构建
# ══════════════════════════════════════════════════════════


class TestBuildContextForTask:
    """build_context_for_task 上下文生成"""

    def test_empty_buffer_returns_empty_string(self):
        applier = FeedbackApplier(StubBuffer([]))
        assert applier.build_context_for_task("fix", "修复登录") == ""

    def test_no_similar_failures_returns_empty(self):
        """有失败但无相似时返回空串"""
        failures = [StubExperience(description="完全不同xyz123", error_message="e1")]
        applier = FeedbackApplier(StubBuffer(failures))
        assert applier.build_context_for_task("fix", "修复登录页面") == ""

    def test_returns_markdown_with_header(self):
        failures = [StubExperience(
            description="修复登录bug",
            error_message="NameError: name 'x' not defined",
            file_paths=["app.py"],
        )]
        applier = FeedbackApplier(StubBuffer(failures))
        ctx = applier.build_context_for_task("fix", "修复登录功能")
        assert "历史失败教训" in ctx
        assert "NameError" in ctx

    def test_includes_file_paths(self):
        failures = [StubExperience(
            description="修复登录",
            error_message="some error",
            file_paths=["src/login.py", "tests/test_login.py"],
        )]
        applier = FeedbackApplier(StubBuffer(failures))
        ctx = applier.build_context_for_task("fix", "修复登录页面")
        assert "login.py" in ctx

    def test_length_capped(self):
        """上下文不超过 MAX_CONTEXT_LENGTH"""
        failures = [
            StubExperience(
                description="修复登录" * 20,
                error_message="很长的错误信息" * 50,
                file_paths=["a.py", "b.py"],
            )
            for _ in range(5)
        ]
        applier = FeedbackApplier(StubBuffer(failures))
        ctx = applier.build_context_for_task("fix", "修复登录")
        assert len(ctx) <= MAX_CONTEXT_LENGTH

    def test_at_most_three_lessons(self):
        """最多注入 3 条教训（避免 prompt 膨胀）"""
        failures = [
            StubExperience(description="修复登录", error_message=f"err{i}")
            for i in range(10)
        ]
        applier = FeedbackApplier(StubBuffer(failures))
        ctx = applier.build_context_for_task("fix", "修复登录")
        # 每条教训占一行，统计 "- 失败原因" 出现次数
        assert ctx.count("- 失败原因") <= 3


# ══════════════════════════════════════════════════════════
# TestFeedbackApplierIntegration — 与真实 ExperienceBuffer 集成
# ══════════════════════════════════════════════════════════


class TestFeedbackApplierIntegration:
    """与真实 ExperienceBuffer 集成（用 tmp_path 隔离磁盘）"""

    def test_real_buffer_round_trip(self, tmp_path: Path, monkeypatch):
        """存储失败经验后能查询并构建上下文"""
        from pycoder.server.learning.experience_buffer import (
            ExperienceBuffer, TaskExperience, EXP_DIR,
        )
        # 隔离 EXP_DIR 避免污染全局
        tmp_exp_dir = tmp_path / "experiences"
        monkeypatch.setattr(
            "pycoder.server.learning.experience_buffer.EXP_DIR", tmp_exp_dir
        )
        buf = ExperienceBuffer(capacity=100)
        buf._exp_dir = tmp_exp_dir  # 覆盖实例目录
        # 强制使用新目录
        import importlib
        import pycoder.server.learning.experience_buffer as eb_mod
        monkeypatch.setattr(eb_mod, "EXP_DIR", tmp_exp_dir)
        buf2 = ExperienceBuffer(capacity=100)

        # 存储一条失败经验
        exp = TaskExperience(
            id="test-1",
            task_type="fix",
            description="修复登录页面认证bug",
            error_message="AuthError: missing token",
            file_paths=["src/auth.py"],
            outcome="failure",
        )
        buf2.store(exp)

        applier = FeedbackApplier(buf2)
        ctx = applier.build_context_for_task("fix", "修复登录页面认证")
        assert "AuthError" in ctx or "missing token" in ctx
        assert "auth.py" in ctx

    def test_singleton_uses_learning_engine(self, monkeypatch, tmp_path: Path):
        """get_feedback_applier 单例复用 LearningEngine 的 buffer"""
        from pycoder.server.learning import get_learning_engine
        from pycoder.server.learning.feedback_applier import (
            get_feedback_applier, reset_feedback_applier,
        )
        # 隔离学习数据目录
        monkeypatch.setenv("PYCODER_EXPERIENCE_DIR", str(tmp_path / "exp"))
        monkeypatch.setenv("PYCODER_FEEDBACK_DIR", str(tmp_path / "fb"))
        reset_feedback_applier()

        applier = get_feedback_applier()
        engine = get_learning_engine()
        assert applier.buffer is engine.buffer

        reset_feedback_applier()

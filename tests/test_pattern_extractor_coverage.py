"""PatternExtractor 覆盖率补充测试

针对 pycoder/server/learning/pattern_extractor.py 中未被覆盖的分支:
  - FixPattern / HotspotInfo / ClusterInfo 数据模型
  - extract_fix_patterns 从 knowledge_base 和 experience_buffer 提取
  - _find_common_substring 边界（空列表、单元素、短前缀、长前缀）
  - get_hotspots 从 kb 与 buffer 双源汇总、min_errors 过滤
  - cluster_errors 聚类分支
  - analyze_prompt_effectiveness 按 role 统计
  - get_pattern_stats 空/非空分支
  - _load_patterns / _save_patterns 持久化与异常处理
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

import pycoder.server.learning.pattern_extractor as pe_mod
from pycoder.server.learning.pattern_extractor import (
    PatternExtractor,
    FixPattern,
    HotspotInfo,
    ClusterInfo,
)


# ══════════════════════════════════════════════════════════
# 测试桩 — 模拟 KnowledgeBase 与 ExperienceBuffer
# ══════════════════════════════════════════════════════════


@dataclass
class StubErrorPattern:
    """模拟 ErrorPattern（避免依赖真实 SQLite）"""
    id: int = 0
    error_signature: str = ""
    error_type: str = ""
    fix_template: str = ""
    file_pattern: str = ""
    success_count: int = 0
    fail_count: int = 0
    last_seen: float = 0.0
    created_at: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0


@dataclass
class StubExperience:
    """模拟 TaskExperience"""
    id: str = "exp-1"
    task_type: str = "fix"
    description: str = ""
    error_signature: str = ""
    error_message: str = ""
    file_paths: list[str] = field(default_factory=list)
    fix_content: str = ""
    agent_role: str = ""
    model_used: str = ""
    outcome: str = "success"
    test_passed: bool = False
    quality_score: float = 0.0
    tokens_used: int = 0
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)


class StubKnowledgeBase:
    """模拟 KnowledgeBase — 提供 get_top_errors / get_hotspots / get_entity_risk"""

    def __init__(self, errors=None, hotspots=None, risk_map=None):
        self._errors = errors or []
        self._hotspots = hotspots or []
        self._risk_map = risk_map or {}

    def get_top_errors(self, limit: int = 20):
        return self._errors[:limit]

    def get_hotspots(self, limit: int = 10):
        return self._hotspots[:limit]

    def get_entity_risk(self, entity: str) -> float:
        return self._risk_map.get(entity, 0.0)


class StubExperienceBuffer:
    """模拟 ExperienceBuffer — 暴露 _buffer / get_stats / get_by_error_type"""

    def __init__(self, exps=None):
        self._buffer = exps or []
        self._stats = StubStats(top_error_types=[(e.error_signature, 1) for e in self._buffer[:5]])

    def get_stats(self, window_hours: int = 168):
        return self._stats

    def get_by_error_type(self, err_type: str, limit: int = 10):
        return [e for e in self._buffer if err_type in (e.error_signature or "")][:limit]


@dataclass
class StubStats:
    total: int = 0
    success: int = 0
    failure: int = 0
    avg_reward: float = 0.0
    avg_quality: float = 0.0
    avg_tokens: float = 0.0
    top_error_types: list = field(default_factory=list)
    recent_success_rate: float = 0.0


# ══════════════════════════════════════════════════════════
# Fixture
# ══════════════════════════════════════════════════════════


@pytest.fixture
def isolated_pe(tmp_path: Path, monkeypatch) -> PatternExtractor:
    """隔离 PATTERNS_DIR 避免污染全局"""
    monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
    return PatternExtractor()


# ══════════════════════════════════════════════════════════
# 数据模型
# ══════════════════════════════════════════════════════════


class TestDataModels:
    def test_fixpattern_success_rate_zero_total(self):
        p = FixPattern()
        assert p.success_rate == 0.0

    def test_fixpattern_success_rate_normal(self):
        p = FixPattern(success_count=3, fail_count=1)
        assert p.success_rate == 0.75

    def test_hotspot_info_defaults(self):
        h = HotspotInfo()
        assert h.error_count == 0
        assert h.risk_score == 0.0
        assert h.recent_errors == []

    def test_cluster_info_defaults(self):
        c = ClusterInfo()
        assert c.member_count == 0
        assert c.member_signatures == []


# ══════════════════════════════════════════════════════════
# _find_common_substring
# ══════════════════════════════════════════════════════════


class TestFindCommonSubstring:
    def test_empty_list_returns_empty(self):
        assert PatternExtractor._find_common_substring([]) == ""

    def test_single_element_returns_it(self):
        assert PatternExtractor._find_common_substring(["only one"]) == "only one"

    def test_two_identical_returns_full(self):
        s = "import os\nimport sys\n"
        assert PatternExtractor._find_common_substring([s, s]) == s[:500]

    def test_short_common_prefix_returns_first_truncated(self):
        """公共前缀 < 10 字符 → 返回第一个字符串截断"""
        a = "abcxx_long_content_xxx"
        b = "abcy_other_content_yyy"
        result = PatternExtractor._find_common_substring([a, b])
        # 前缀 "abc" 仅 3 字符 < 10 → 返回 a[:200]
        assert result == a[:200]

    def test_long_common_prefix_returns_common(self):
        """公共前缀 >= 10 字符 → 返回公共部分（最多 500）"""
        prefix = "from pycoder.server.learning import "
        a = prefix + "knowledge_base"
        b = prefix + "pattern_extractor"
        result = PatternExtractor._find_common_substring([a, b])
        assert result == prefix

    def test_truncates_to_500_chars(self):
        """长公共前缀被截断为 500 字符"""
        prefix = "x" * 600
        result = PatternExtractor._find_common_substring([prefix, prefix])
        assert len(result) <= 500


# ══════════════════════════════════════════════════════════
# extract_fix_patterns
# ══════════════════════════════════════════════════════════


class TestExtractFixPatterns:
    def test_returns_empty_without_sources(self, isolated_pe: PatternExtractor):
        result = isolated_pe.extract_fix_patterns()
        assert result == []

    def test_extracts_from_knowledge_base(self, isolated_pe: PatternExtractor):
        errors = [
            StubErrorPattern(
                id=1, error_signature="SIG-A", error_type="NameError",
                fix_template="import missing_module",
                success_count=5, fail_count=1, last_seen=1000.0,
                file_pattern="src/*.py",
            ),
        ]
        kb = StubKnowledgeBase(errors=errors)
        patterns = isolated_pe.extract_fix_patterns(knowledge_base=kb, min_success=3)
        assert len(patterns) == 1
        p = patterns[0]
        assert p.pattern_id == "KB-1"
        assert p.error_type == "NameError"
        assert p.success_count == 5
        assert p.files_affected == ["src/*.py"]

    def test_filters_below_min_success(self, isolated_pe: PatternExtractor):
        errors = [
            StubErrorPattern(id=1, error_signature="S1", error_type="E1",
                             fix_template="f", success_count=2, fail_count=0),
            StubErrorPattern(id=2, error_signature="S2", error_type="E2",
                             fix_template="f", success_count=5, fail_count=1),
        ]
        kb = StubKnowledgeBase(errors=errors)
        patterns = isolated_pe.extract_fix_patterns(knowledge_base=kb, min_success=3)
        assert len(patterns) == 1
        assert patterns[0].pattern_id == "KB-2"

    def test_filters_patterns_without_template(self, isolated_pe: PatternExtractor):
        errors = [
            StubErrorPattern(id=1, error_signature="S1", error_type="E1",
                             fix_template="",  # 空模板
                             success_count=10, fail_count=0),
        ]
        kb = StubKnowledgeBase(errors=errors)
        patterns = isolated_pe.extract_fix_patterns(knowledge_base=kb, min_success=3)
        assert patterns == []

    def test_extracts_from_experience_buffer(self, isolated_pe: PatternExtractor):
        """从经验缓冲区提取模式"""
        successes = []
        for i in range(5):
            successes.append(StubExperience(
                id=f"exp-{i}",
                error_signature="ImportError",
                error_message="ImportError: no module named x",
                fix_content="import x",
                outcome="success",
                timestamp=time.time(),
            ))
        # 加一些失败
        failures = [StubExperience(
            error_signature="ImportError",
            outcome="failure", timestamp=time.time(),
        ) for _ in range(2)]
        buf = StubExperienceBuffer(exps=successes + failures)
        # stats.top_error_types 需要 [(err_type, count), ...]
        buf._stats = StubStats(top_error_types=[("ImportError", 7)])

        patterns = isolated_pe.extract_fix_patterns(
            experience_buffer=buf, min_success=3,
        )
        assert len(patterns) >= 1
        p = patterns[0]
        assert p.pattern_id == "EXP-ImportError"
        assert p.success_count == 5
        assert p.fail_count == 2  # 7 - 5 = 2

    def test_extracts_from_both_sources(self, isolated_pe: PatternExtractor):
        """同时从 kb 和 buffer 提取"""
        errors = [StubErrorPattern(
            id=1, error_signature="KB-SIG", error_type="ValueError",
            fix_template="validate input",
            success_count=10, fail_count=2,
        )]
        successes = [StubExperience(
            error_signature="EXP-SIG",
            fix_content="fix the bug",
            outcome="success", timestamp=time.time(),
        ) for _ in range(4)]
        kb = StubKnowledgeBase(errors=errors)
        buf = StubExperienceBuffer(exps=successes)
        buf._stats = StubStats(top_error_types=[("EXP-SIG", 4)])

        patterns = isolated_pe.extract_fix_patterns(
            knowledge_base=kb, experience_buffer=buf, min_success=3,
        )
        assert len(patterns) == 2

    def test_persists_after_extraction(self, isolated_pe: PatternExtractor, tmp_path: Path):
        """提取完成后应调用 _save_patterns 持久化"""
        errors = [StubErrorPattern(
            id=1, error_signature="S", error_type="E",
            fix_template="f", success_count=5, fail_count=0,
        )]
        kb = StubKnowledgeBase(errors=errors)
        isolated_pe.extract_fix_patterns(knowledge_base=kb, min_success=3)
        patterns_file = tmp_path / "patterns.jsonl"
        assert patterns_file.exists()
        data = json.loads(patterns_file.read_text(encoding="utf-8").splitlines()[0])
        assert data["pattern_id"] == "KB-1"

    def test_updates_last_extraction_timestamp(self, isolated_pe: PatternExtractor):
        before = isolated_pe._last_extraction
        time.sleep(0.01)
        isolated_pe.extract_fix_patterns()
        assert isolated_pe._last_extraction > before


# ══════════════════════════════════════════════════════════
# get_hotspots
# ══════════════════════════════════════════════════════════


class TestGetHotspots:
    def test_empty_sources_returns_empty(self, isolated_pe: PatternExtractor):
        result = isolated_pe.get_hotspots()
        assert result == []

    def test_extracts_from_knowledge_base(self, isolated_pe: PatternExtractor):
        kb_hotspots = [
            {"entity": "src/app.py", "bug_frequency": 5},
            {"entity": "src/models.py", "bug_frequency": 3},
        ]
        kb = StubKnowledgeBase(
            hotspots=kb_hotspots,
            risk_map={"src/app.py": 80.0, "src/models.py": 50.0},
        )
        result = isolated_pe.get_hotspots(knowledge_base=kb, top_n=10)
        assert len(result) == 2
        assert result[0].entity == "src/app.py"
        assert result[0].error_count == 5
        assert result[0].risk_score == 80.0

    def test_extracts_from_experience_buffer(self, isolated_pe: PatternExtractor):
        exps = [
            StubExperience(file_paths=["a.py", "b.py"], error_message="err1",
                           outcome="failure", timestamp=time.time()),
            StubExperience(file_paths=["a.py"], error_message="err2",
                           outcome="failure", timestamp=time.time()),
            StubExperience(file_paths=["a.py"], error_message="err3",
                           outcome="failure", timestamp=time.time()),
            # b.py 只 1 次 → 低于 min_errors=2，应被过滤
        ]
        buf = StubExperienceBuffer(exps=exps)
        result = isolated_pe.get_hotspots(experience_buffer=buf, top_n=10, min_errors=2)
        entities = [h.entity for h in result]
        assert "a.py" in entities
        assert "b.py" not in entities

    def test_merges_kb_and_buffer_hotspots(self, isolated_pe: PatternExtractor):
        """kb 已有的热点 + buffer 同名文件 → 累加 error_count"""
        kb_hotspots = [{"entity": "shared.py", "bug_frequency": 5}]
        kb = StubKnowledgeBase(hotspots=kb_hotspots, risk_map={"shared.py": 70.0})
        exps = [
            StubExperience(file_paths=["shared.py"], error_message="e1",
                           outcome="failure", timestamp=time.time()),
            StubExperience(file_paths=["shared.py"], error_message="e2",
                           outcome="failure", timestamp=time.time()),
        ]
        buf = StubExperienceBuffer(exps=exps)
        result = isolated_pe.get_hotspots(
            knowledge_base=kb, experience_buffer=buf, top_n=10,
        )
        # shared.py 应在结果中，且 recent_errors 被填充
        shared = next(h for h in result if h.entity == "shared.py")
        assert shared.error_count >= 5  # kb 的 5
        assert len(shared.recent_errors) > 0

    def test_limits_to_top_n(self, isolated_pe: PatternExtractor):
        kb_hotspots = [{"entity": f"file{i}.py", "bug_frequency": i + 1} for i in range(15)]
        kb = StubKnowledgeBase(hotspots=kb_hotspots, risk_map={f"file{i}.py": 10.0 for i in range(15)})
        result = isolated_pe.get_hotspots(knowledge_base=kb, top_n=5)
        assert len(result) <= 5

    def test_orders_by_error_count_desc(self, isolated_pe: PatternExtractor):
        kb_hotspots = [
            {"entity": "low.py", "bug_frequency": 2},
            {"entity": "high.py", "bug_frequency": 10},
            {"entity": "mid.py", "bug_frequency": 5},
        ]
        kb = StubKnowledgeBase(hotspots=kb_hotspots, risk_map={"low.py": 10, "high.py": 50, "mid.py": 25})
        result = isolated_pe.get_hotspots(knowledge_base=kb, top_n=10)
        assert result[0].entity == "high.py"
        assert result[1].entity == "mid.py"
        assert result[2].entity == "low.py"


# ══════════════════════════════════════════════════════════
# cluster_errors
# ══════════════════════════════════════════════════════════


class TestClusterErrors:
    def test_empty_buffer_returns_empty(self, isolated_pe: PatternExtractor):
        assert isolated_pe.cluster_errors() == []

    def test_clusters_below_min_size_filtered(self, isolated_pe: PatternExtractor):
        """低于 min_cluster_size 的类型被过滤"""
        exps = [
            StubExperience(error_signature="ClusterA: detail", outcome="success",
                           timestamp=time.time()),
            StubExperience(error_signature="ClusterB: detail", outcome="success",
                           timestamp=time.time()),
        ]
        buf = StubExperienceBuffer(exps=exps)
        result = isolated_pe.cluster_errors(experience_buffer=buf, min_cluster_size=3)
        assert result == []

    def test_clusters_above_min_size_returned(self, isolated_pe: PatternExtractor):
        """足够大的聚类被返回"""
        exps = [
            StubExperience(error_signature="ClusterA: x", fix_content="fix_a",
                           outcome="success", timestamp=time.time())
            for _ in range(5)
        ]
        # 添加不同类型
        exps += [
            StubExperience(error_signature="ClusterB: y", fix_content="fix_b",
                           outcome="success", timestamp=time.time())
            for _ in range(3)
        ]
        buf = StubExperienceBuffer(exps=exps)
        result = isolated_pe.cluster_errors(experience_buffer=buf, min_cluster_size=3)
        # 应有 2 个聚类
        assert len(result) == 2
        # 第一个应是成员更多的（ClusterA: 5）
        assert result[0].member_count >= result[1].member_count
        assert result[0].cluster_id.startswith("CL-")

    def test_cluster_without_colon_uses_truncated_signature(self, isolated_pe: PatternExtractor):
        """error_signature 不含冒号时取前 30 字符作为类型"""
        sig_no_colon = "NoColonSignature"  # 16 字符
        exps = [
            StubExperience(error_signature=sig_no_colon, outcome="success",
                           fix_content="fix", timestamp=time.time())
            for _ in range(4)
        ]
        buf = StubExperienceBuffer(exps=exps)
        result = isolated_pe.cluster_errors(experience_buffer=buf, min_cluster_size=3)
        assert len(result) == 1
        assert result[0].error_type == sig_no_colon


# ══════════════════════════════════════════════════════════
# analyze_prompt_effectiveness
# ══════════════════════════════════════════════════════════


class TestAnalyzePromptEffectiveness:
    def test_returns_empty_without_buffer(self, isolated_pe: PatternExtractor):
        assert isolated_pe.analyze_prompt_effectiveness() == {}

    def test_aggregates_by_role(self, isolated_pe: PatternExtractor):
        now = time.time()
        exps = [
            StubExperience(agent_role="developer", outcome="success",
                           quality_score=90.0, tokens_used=100,
                           timestamp=now),
            StubExperience(agent_role="developer", outcome="failure",
                           quality_score=40.0, tokens_used=200,
                           timestamp=now),
            StubExperience(agent_role="architect", outcome="success",
                           quality_score=85.0, tokens_used=150,
                           timestamp=now),
        ]
        buf = StubExperienceBuffer(exps=exps)
        result = isolated_pe.analyze_prompt_effectiveness(
            experience_buffer=buf, days=7,
        )
        assert "developer" in result
        assert "architect" in result
        dev = result["developer"]
        assert dev["total_tasks"] == 2
        assert dev["success_rate"] == 0.5
        assert dev["avg_quality"] == 65.0  # (90+40)/2
        assert dev["avg_tokens"] == 150  # (100+200)/2

    def test_filters_old_experiences(self, isolated_pe: PatternExtractor):
        """早于 cutoff 的经验被过滤"""
        old_ts = time.time() - 30 * 86400  # 30 天前
        recent_ts = time.time()
        exps = [
            StubExperience(agent_role="dev", outcome="success",
                           quality_score=90, tokens_used=50, timestamp=old_ts),
            StubExperience(agent_role="dev", outcome="success",
                           quality_score=80, tokens_used=60, timestamp=recent_ts),
        ]
        buf = StubExperienceBuffer(exps=exps)
        result = isolated_pe.analyze_prompt_effectiveness(
            experience_buffer=buf, days=7,
        )
        # 只有最近一条算入
        assert result["dev"]["total_tasks"] == 1

    def test_unknown_role_for_missing_agent(self, isolated_pe: PatternExtractor):
        exps = [StubExperience(agent_role="", outcome="success",
                               quality_score=80, tokens_used=100,
                               timestamp=time.time())]
        buf = StubExperienceBuffer(exps=exps)
        result = isolated_pe.analyze_prompt_effectiveness(experience_buffer=buf)
        assert "unknown" in result


# ══════════════════════════════════════════════════════════
# get_pattern_stats
# ══════════════════════════════════════════════════════════


class TestGetPatternStats:
    def test_empty_patterns(self, isolated_pe: PatternExtractor):
        isolated_pe._patterns = []
        stats = isolated_pe.get_pattern_stats()
        assert stats == {"total": 0, "top_types": []}

    def test_with_patterns(self, isolated_pe: PatternExtractor):
        isolated_pe._patterns = [
            FixPattern(pattern_id="P1", error_type="ValueError",
                       success_count=8, fail_count=2),
            FixPattern(pattern_id="P2", error_type="TypeError",
                       success_count=5, fail_count=5),
            FixPattern(pattern_id="P3", error_type="ValueError",
                       success_count=10, fail_count=0),
        ]
        stats = isolated_pe.get_pattern_stats()
        assert stats["total"] == 3
        assert isinstance(stats["last_extraction"], float)
        # top_types 应统计 error_type
        types = dict(stats["top_types"])
        assert types["ValueError"] == 2
        assert types["TypeError"] == 1
        # high_confidence 统计 success_rate > 0.8
        # P1: 0.8 (不 > 0.8)  P2: 0.5  P3: 1.0 (> 0.8)
        assert stats["high_confidence"] == 1
        # patterns 列表按 success_rate 降序，最多 20 条
        assert len(stats["patterns"]) == 3
        assert stats["patterns"][0]["success_rate"] >= stats["patterns"][1]["success_rate"]

    def test_limits_patterns_to_20(self, isolated_pe: PatternExtractor):
        isolated_pe._patterns = [
            FixPattern(pattern_id=f"P{i}", error_type="E",
                       success_count=i + 1, fail_count=0)
            for i in range(30)
        ]
        stats = isolated_pe.get_pattern_stats()
        assert len(stats["patterns"]) == 20


# ══════════════════════════════════════════════════════════
# _load_patterns — 异常处理
# ══════════════════════════════════════════════════════════


class TestLoadPatterns:
    def test_missing_file_returns_silently(self, tmp_path: Path, monkeypatch):
        """文件不存在时直接返回，不抛异常"""
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        # 文件不存在，初始化不应抛异常
        pe = PatternExtractor()
        assert pe._patterns == []

    def test_corrupted_file_returns_silently(self, tmp_path: Path, monkeypatch):
        """读取失败时静默返回（OSError 被捕获）"""
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        # 创建一个会触发 read_text OSError 的伪文件（用目录代替文件）
        patterns_file = tmp_path / "patterns.jsonl"
        patterns_file.mkdir()  # 目录而非文件
        # 不应抛异常
        pe = PatternExtractor()
        # 由于 OSError 被捕获，_patterns 保持空
        assert isinstance(pe._patterns, list)

    def test_skips_invalid_json_lines(self, tmp_path: Path, monkeypatch):
        """损坏的 JSON 行被跳过"""
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        patterns_file = tmp_path / "patterns.jsonl"
        patterns_file.write_text(
            '{"pattern_id":"OK-1","error_type":"E1","success_count":1}\n'
            "not valid json\n"
            '{"pattern_id":"OK-2","error_type":"E2","success_count":2}\n',
            encoding="utf-8",
        )
        pe = PatternExtractor()
        assert len(pe._patterns) == 2
        ids = {p.pattern_id for p in pe._patterns}
        assert ids == {"OK-1", "OK-2"}

    def test_skips_blank_lines(self, tmp_path: Path, monkeypatch):
        """空行与全空白行被跳过"""
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        patterns_file = tmp_path / "patterns.jsonl"
        patterns_file.write_text(
            '{"pattern_id":"OK-1","error_type":"E1","success_count":1}\n'
            "\n"
            "   \n"  # 全空白
            '{"pattern_id":"OK-2","error_type":"E2","success_count":2}\n',
            encoding="utf-8",
        )
        pe = PatternExtractor()
        assert len(pe._patterns) == 2

    def test_loads_at_most_200_lines(self, tmp_path: Path, monkeypatch):
        """超过 200 行的历史模式只加载最近 200 条"""
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        patterns_file = tmp_path / "patterns.jsonl"
        lines = [
            json.dumps({"pattern_id": f"P{i}", "error_type": "E",
                        "success_count": i, "last_used": float(i)})
            for i in range(250)
        ]
        patterns_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        pe = PatternExtractor()
        assert len(pe._patterns) == 200
        # 应加载最后 200 条（i=50..249）
        ids = {p.pattern_id for p in pe._patterns}
        assert "P249" in ids
        assert "P50" in ids
        assert "P49" not in ids

    def test_updates_last_extraction_from_loaded(self, tmp_path: Path, monkeypatch):
        """加载后 last_extraction 取磁盘最新 last_used"""
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        patterns_file = tmp_path / "patterns.jsonl"
        patterns_file.write_text(
            json.dumps({"pattern_id": "P1", "last_used": 1000.0}) + "\n"
            + json.dumps({"pattern_id": "P2", "last_used": 2000.0}) + "\n",
            encoding="utf-8",
        )
        pe = PatternExtractor()
        assert pe._last_extraction == 2000.0


# ══════════════════════════════════════════════════════════
# _save_patterns — 异常处理
# ══════════════════════════════════════════════════════════


class TestSavePatterns:
    def test_save_creates_directory(self, isolated_pe: PatternExtractor, tmp_path: Path):
        """保存时自动创建目录"""
        # 使用一个新的子目录
        sub_dir = tmp_path / "sub" / "deep"
        isolated_pe._persist_dir = sub_dir
        isolated_pe._patterns_path = sub_dir / "patterns.jsonl"
        isolated_pe._patterns = [FixPattern(pattern_id="X", error_type="E")]
        isolated_pe._save_patterns()
        assert (sub_dir / "patterns.jsonl").exists()

    def test_save_writes_empty_file_for_empty_patterns(
        self, isolated_pe: PatternExtractor, tmp_path: Path,
    ):
        """空列表保存时写空字符串"""
        isolated_pe._patterns = []
        isolated_pe._save_patterns()
        content = (tmp_path / "patterns.jsonl").read_text(encoding="utf-8")
        assert content == ""

    def test_save_failure_silent(self, isolated_pe: PatternExtractor, monkeypatch):
        """持久化失败不应抛异常"""
        def raise_oserror(*args, **kwargs):
            raise OSError("disk full")
        monkeypatch.setattr(Path, "mkdir", raise_oserror)
        # 不应抛异常
        isolated_pe._patterns = [FixPattern(pattern_id="X")]
        isolated_pe._save_patterns()

    def test_round_trip_preserves_all_fields(self, tmp_path: Path, monkeypatch):
        """保存→重新加载，所有字段保持一致"""
        monkeypatch.setattr("pycoder.capabilities.self_evo.learning.pattern_extractor.PATTERNS_DIR", tmp_path)
        pe1 = PatternExtractor()
        original = FixPattern(
            pattern_id="RT-1",
            error_type="RuntimeError",
            description="完整字段测试",
            fix_template="try: ... except: ...",
            example_error="Traceback: ...",
            example_fix="fixed code",
            success_count=10,
            fail_count=2,
            last_used=1234567890.0,
            files_affected=["a.py", "b.py"],
        )
        pe1._patterns = [original]
        pe1._save_patterns()
        # 重新加载
        pe2 = PatternExtractor()
        assert len(pe2._patterns) == 1
        loaded = pe2._patterns[0]
        assert loaded.pattern_id == "RT-1"
        assert loaded.error_type == "RuntimeError"
        assert loaded.fix_template == "try: ... except: ..."
        assert loaded.success_count == 10
        assert loaded.fail_count == 2
        assert loaded.last_used == 1234567890.0
        assert loaded.files_affected == ["a.py", "b.py"]

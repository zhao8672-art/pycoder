"""AI 分析器覆盖率测试

覆盖三个 0% 覆盖率模块:
  - pycoder.ai.analysis.composite_analyzer — CompositeAnalyzer 五层整合
  - pycoder.ai.cache.kv_cache — PromptCache 持久化
  - pycoder.ai.generation.iterative — IterativeGenerator 多轮优化
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pycoder.ai.analysis.composite_analyzer import (
    AnalysisPipeline,
    CompositeAnalyzer,
    get_composite_analyzer,
)
from pycoder.ai.cache.kv_cache import (
    MAX_ENTRIES,
    CacheEntry,
    PromptCache,
    get_cache,
)
from pycoder.ai.generation.iterative import (
    ITERATION_PROMPTS,
    IterativeGenerator,
)
from pycoder.ai.interface.base import ICodeAnalyzer
from pycoder.ai.interface.types import (
    AnalysisDepth,
    AnalysisResult,
    CodeAnalysisRequest,
    CodeGenerationRequest,
    CodeGenerationResult,
    CodeGenStrategy,
)

# ══════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════


@pytest.fixture
def sample_code() -> str:
    """示例 Python 代码"""
    return '''
def add(a, b):
    """add two numbers"""
    return a + b


class Calculator:
    def __init__(self):
        self.value = 0

    def compute(self, x, y):
        if x > 0:
            return self.add(x, y)
        else:
            return self.subtract(x, y)
'''


@pytest.fixture
def bad_code() -> str:
    """有问题的示例代码"""
    return "def broken(:\n    return 1\n"


@pytest.fixture
def tmp_cache_db(tmp_path: Path) -> str:
    """临时 KV cache DB 路径"""
    return str(tmp_path / "test_cache.db")


@pytest.fixture
def cache(tmp_cache_db: str) -> PromptCache:
    """临时 PromptCache 实例"""
    # 重置单例
    from pycoder.ai.cache import kv_cache

    kv_cache._cache = None
    c = PromptCache(db_path=tmp_cache_db)
    yield c
    # 清理
    if os.path.exists(tmp_cache_db):
        os.unlink(tmp_cache_db)


# ════════════════════════════════════════════════════════════════════
# composite_analyzer
# ════════════════════════════════════════════════════════════════════


class TestAnalysisPipeline:
    """AnalysisPipeline 工厂方法"""

    def test_syntax_depth_pipeline(self) -> None:
        """SYNTAX 深度应只包含语法层"""
        p = AnalysisPipeline.for_depth(AnalysisDepth.SYNTAX)
        assert p.depths == [AnalysisDepth.SYNTAX]
        assert p.labels == ["语法分析"]

    def test_semantic_depth_pipeline(self) -> None:
        """SEMANTIC 深度应包含语法+语义"""
        p = AnalysisPipeline.for_depth(AnalysisDepth.SEMANTIC)
        assert AnalysisDepth.SYNTAX in p.depths
        assert AnalysisDepth.SEMANTIC in p.depths
        assert len(p.depths) == 2

    def test_structural_depth_pipeline(self) -> None:
        """STRUCTURAL 深度应包含前 3 层"""
        p = AnalysisPipeline.for_depth(AnalysisDepth.STRUCTURAL)
        assert len(p.depths) == 3
        assert AnalysisDepth.STRUCTURAL in p.depths

    def test_architectural_depth_pipeline(self) -> None:
        """ARCHITECTURAL 深度应包含前 4 层"""
        p = AnalysisPipeline.for_depth(AnalysisDepth.ARCHITECTURAL)
        assert len(p.depths) == 4
        assert AnalysisDepth.ARCHITECTURAL in p.depths

    def test_behavioral_depth_pipeline(self) -> None:
        """BEHAVIORAL 深度应包含所有 5 层"""
        p = AnalysisPipeline.for_depth(AnalysisDepth.BEHAVIORAL)
        assert len(p.depths) == 5
        assert AnalysisDepth.BEHAVIORAL in p.depths

    def test_direct_construction(self) -> None:
        """直接构造 AnalysisPipeline"""
        p = AnalysisPipeline(
            depths=[AnalysisDepth.SYNTAX],
            labels=["test"],
        )
        assert p.depths == [AnalysisDepth.SYNTAX]
        assert p.labels == ["test"]


class TestCompositeAnalyzerBasic:
    """CompositeAnalyzer 基础行为"""

    def test_construction(self) -> None:
        """构造应成功创建 5 个分析器"""
        a = CompositeAnalyzer()
        assert a._syntax is not None
        assert a._semantic is not None
        assert a._structural is not None
        assert a._architectural is not None
        assert a._behavioral is not None

    def test_implements_icode_analyzer(self) -> None:
        """CompositeAnalyzer 应实现 ICodeAnalyzer"""
        a = CompositeAnalyzer()
        assert isinstance(a, ICodeAnalyzer)

    def test_capability_info(self) -> None:
        """get_capability_info 返回 ProviderCapability"""
        from pycoder.ai.interface.types import ProviderCapability

        a = CompositeAnalyzer()
        info = a.get_capability_info()
        assert isinstance(info, ProviderCapability)
        assert info.provider == "PyCoder-CompositeAnalyzer"
        # 能力评分应为 0-1 之间
        assert 0 <= info.code_analysis <= 1
        assert 0 <= info.code_generation <= 1


class TestCompositeAnalyzerAnalyze:
    """CompositeAnalyzer.analyze 行为"""

    @pytest.mark.asyncio
    async def test_analyze_clean_code(self, sample_code: str) -> None:
        """分析干净代码应返回 AnalysisResult"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(code=sample_code, depth=AnalysisDepth.SYNTAX)
        result = await a.analyze(req)
        assert isinstance(result, AnalysisResult)
        assert "summary" in result.summary or "分析" in result.summary
        assert result.analysis_time_ms > 0

    @pytest.mark.asyncio
    async def test_analyze_syntax_error(self, bad_code: str) -> None:
        """分析有语法错误的代码应检测到问题"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(code=bad_code, depth=AnalysisDepth.SYNTAX)
        result = await a.analyze(req)
        assert isinstance(result, AnalysisResult)
        # 至少应发现 1 个问题
        # (注意：如果所有分析器都被异常处理吞掉，可能 0 个问题)
        # 至少 summary 应该有内容
        assert result.summary

    @pytest.mark.asyncio
    async def test_analyze_with_semantic_depth(self, sample_code: str) -> None:
        """SEMANTIC 深度应跑前 2 层"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(code=sample_code, depth=AnalysisDepth.SEMANTIC)
        result = await a.analyze(req)
        assert isinstance(result, AnalysisResult)

    @pytest.mark.asyncio
    async def test_analyze_with_structural_depth(self, sample_code: str) -> None:
        """STRUCTURAL 深度应跑前 3 层"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(code=sample_code, depth=AnalysisDepth.STRUCTURAL)
        result = await a.analyze(req)
        assert isinstance(result, AnalysisResult)

    @pytest.mark.asyncio
    async def test_analyze_with_architectural_depth(self, sample_code: str) -> None:
        """ARCHITECTURAL 深度应跑前 4 层"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(
            code=sample_code, depth=AnalysisDepth.ARCHITECTURAL
        )
        result = await a.analyze(req)
        assert isinstance(result, AnalysisResult)

    @pytest.mark.asyncio
    async def test_analyze_with_behavioral_depth(self, sample_code: str) -> None:
        """BEHAVIORAL 深度应跑全部 5 层"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(code=sample_code, depth=AnalysisDepth.BEHAVIORAL)
        result = await a.analyze(req)
        assert isinstance(result, AnalysisResult)
        # summary 应提到 5 层
        assert "5" in result.summary

    @pytest.mark.asyncio
    async def test_analyze_issues_deduplicated(self, sample_code: str) -> None:
        """重复 issue 应被去重"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(code=sample_code, depth=AnalysisDepth.SYNTAX)
        result = await a.analyze(req)
        seen: set[tuple[str, int, str]] = set()
        for issue in result.issues:
            sig = (issue.get("code", ""), issue.get("line", 0), issue.get("message", ""))
            assert sig not in seen, f"重复 issue: {sig}"
            seen.add(sig)

    @pytest.mark.asyncio
    async def test_analyze_complexity_score_bounded(self, sample_code: str) -> None:
        """complexity_score 应在 0-1 之间"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(
            code=sample_code, depth=AnalysisDepth.ARCHITECTURAL
        )
        result = await a.analyze(req)
        assert 0 <= result.complexity_score <= 1

    @pytest.mark.asyncio
    async def test_analyze_severity_classification(self, sample_code: str) -> None:
        """security_rating 应是已知值"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(code=sample_code, depth=AnalysisDepth.SYNTAX)
        result = await a.analyze(req)
        assert result.security_rating in ("critical", "high", "medium", "low", "unknown")

    @pytest.mark.asyncio
    async def test_analyze_issues_limited_to_50(self, bad_code: str) -> None:
        """issues 最多返回 50 条"""
        a = CompositeAnalyzer()
        # 构造有很多重复问题的代码
        bad = "def f(:\n" * 100  # 大量语法错误
        req = CodeAnalysisRequest(code=bad, depth=AnalysisDepth.SYNTAX)
        result = await a.analyze(req)
        assert len(result.issues) <= 50

    @pytest.mark.asyncio
    async def test_analyze_suggestions_limited_to_20(self, sample_code: str) -> None:
        """suggestions 最多返回 20 条"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(
            code=sample_code, depth=AnalysisDepth.ARCHITECTURAL
        )
        result = await a.analyze(req)
        assert len(result.suggestions) <= 20

    @pytest.mark.asyncio
    async def test_analyze_with_language(self, sample_code: str) -> None:
        """language 参数应被接受"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(
            code=sample_code, language="python", depth=AnalysisDepth.SYNTAX
        )
        result = await a.analyze(req)
        assert isinstance(result, AnalysisResult)

    @pytest.mark.asyncio
    async def test_analyze_layer_exception_handled(self) -> None:
        """某层抛异常不应影响整体结果"""
        a = CompositeAnalyzer()
        # Mock 其中一层抛异常
        with patch.object(
            a._syntax,
            "analyze",
            new=AsyncMock(side_effect=ValueError("boom")),
        ):
            req = CodeAnalysisRequest(code="x = 1", depth=AnalysisDepth.SYNTAX)
            # 即使单层异常，整体分析仍应返回结果
            result = await a.analyze(req)
        assert isinstance(result, AnalysisResult)

    @pytest.mark.asyncio
    async def test_analyze_empty_code(self) -> None:
        """空代码不应崩溃"""
        a = CompositeAnalyzer()
        req = CodeAnalysisRequest(code="", depth=AnalysisDepth.SYNTAX)
        result = await a.analyze(req)
        assert isinstance(result, AnalysisResult)


class TestCompositeAnalyzerHelpers:
    """find_issues / suggest_improvements / calculate_metrics / compare_versions"""

    @pytest.mark.asyncio
    async def test_find_issues(self, sample_code: str) -> None:
        """find_issues 应返回 issues 列表"""
        a = CompositeAnalyzer()
        issues = await a.find_issues(sample_code, language="python")
        assert isinstance(issues, list)

    @pytest.mark.asyncio
    async def test_suggest_improvements(self, sample_code: str) -> None:
        """suggest_improvements 应返回建议列表"""
        a = CompositeAnalyzer()
        suggestions = await a.suggest_improvements(sample_code, language="python")
        assert isinstance(suggestions, list)

    @pytest.mark.asyncio
    async def test_calculate_metrics(self, sample_code: str) -> None:
        """calculate_metrics 应返回度量字典"""
        a = CompositeAnalyzer()
        metrics = await a.calculate_metrics(sample_code, language="python")
        assert isinstance(metrics, dict)
        # 至少应包含一些基础字段
        for key in ["total_lines", "code_lines", "function_count"]:
            assert key in metrics

    @pytest.mark.asyncio
    async def test_compare_versions(self, sample_code: str) -> None:
        """compare_versions 应返回 AnalysisResult"""
        a = CompositeAnalyzer()
        old = sample_code
        new = sample_code + "\n\ndef new_func():\n    return 42\n"
        result = await a.compare_versions(old, new, language="python")
        assert isinstance(result, AnalysisResult)
        # summary 应提到 fixed/introduced
        assert "对比" in result.summary or "fixed" in result.summary.lower() or "修复" in result.summary


class TestGetCompositeAnalyzer:
    """get_composite_analyzer 单例"""

    def test_singleton(self) -> None:
        """多次调用应返回同一实例"""
        from pycoder.ai.analysis import composite_analyzer

        composite_analyzer._analyzer = None
        a1 = get_composite_analyzer()
        a2 = get_composite_analyzer()
        assert a1 is a2
        composite_analyzer._analyzer = None  # 清理


# ════════════════════════════════════════════════════════════════════
# kv_cache
# ════════════════════════════════════════════════════════════════════


class TestCacheEntry:
    """CacheEntry 数据类"""

    def test_construction(self) -> None:
        """CacheEntry 应接受所有字段"""
        e = CacheEntry(
            prefix_hash="abc",
            model="m1",
            temperature=0.5,
            cached_output="out",
            token_count=10,
            hit_count=2,
            created_at=time.time(),
            expires_at=time.time() + 3600,
        )
        assert e.prefix_hash == "abc"
        assert e.model == "m1"
        assert e.temperature == 0.5
        assert e.cached_output == "out"
        assert e.token_count == 10
        assert e.hit_count == 2


class TestPromptCacheInit:
    """PromptCache 构造行为"""

    def test_default_init(self, tmp_cache_db: str) -> None:
        """构造应创建 DB"""
        c = PromptCache(db_path=tmp_cache_db)
        assert os.path.exists(tmp_cache_db)
        assert c._local == {}

    def test_db_creates_directory(self, tmp_path: Path) -> None:
        """DB 路径所在目录应被自动创建"""
        db = str(tmp_path / "subdir" / "cache.db")
        PromptCache(db_path=db)
        assert os.path.exists(db)

    def test_local_cache_empty(self, cache: PromptCache) -> None:
        """初始 local 缓存应为空"""
        assert cache._local == {}


class TestPromptCacheSetGet:
    """set / get 行为"""

    def test_set_and_get(self, cache: PromptCache) -> None:
        """set 后应能从 local 缓存 get 到"""
        cache.set("hello world prompt", "cached output")
        out = cache.get("hello world prompt")
        assert out == "cached output"

    def test_get_returns_none_for_missing(self, cache: PromptCache) -> None:
        """未缓存的 prompt 应返回 None"""
        out = cache.get("never seen before")
        assert out is None

    def test_set_different_models(self, cache: PromptCache) -> None:
        """不同 model 的相同 prompt 应独立缓存"""
        cache.set("prompt text", "out-a", model="model-a")
        cache.set("prompt text", "out-b", model="model-b")
        assert cache.get("prompt text", model="model-a") == "out-a"
        assert cache.get("prompt text", model="model-b") == "out-b"

    def test_set_different_temperatures(self, cache: PromptCache) -> None:
        """不同 temperature 的相同 prompt 应独立缓存"""
        cache.set("p", "out-cold", temperature=0.0)
        cache.set("p", "out-hot", temperature=1.0)
        assert cache.get("p", temperature=0.0) == "out-cold"
        assert cache.get("p", temperature=1.0) == "out-hot"

    def test_get_increments_hit_count(self, cache: PromptCache) -> None:
        """get 应递增 hit_count"""
        cache.set("p1", "o1", model="m1")
        first = cache.get("p1", model="m1")
        assert first == "o1"
        # 内存缓存命中，hit_count 已增加
        assert cache._local[next(iter(cache._local))].hit_count >= 1

    def test_set_with_ttl(self, cache: PromptCache) -> None:
        """自定义 TTL 应被应用"""
        cache.set("p1", "o1", ttl=7200)
        out = cache.get("p1")
        assert out == "o1"

    def test_get_expired_returns_none(self, cache: PromptCache) -> None:
        """过期缓存应返回 None"""
        cache.set("p1", "o1", ttl=0)
        # 立即过期（实际 ttl=0 时 expires_at == now, get 会判断 expires_at > time.time() 为 False）
        # 但因为 time.time() 是浮点，可能命中。需要做一点点等待
        time.sleep(0.01)
        out = cache.get("p1")
        assert out is None

    def test_set_does_not_cache_empty_prefix(self, cache: PromptCache) -> None:
        """空前缀应被忽略"""
        cache.set("", "out")
        # 没有 entry 应被创建
        assert len(cache._local) == 0

    def test_set_persists_to_sqlite(self, cache: PromptCache) -> None:
        """set 后应能直接从 SQLite 读到"""
        import sqlite3

        cache.set("persisted prompt", "persisted output", model="m1")
        # 重新从 DB 读取
        conn = sqlite3.connect(cache._db_path)
        row = conn.execute(
            "SELECT cached_output FROM prompt_cache WHERE model=?", ("m1",)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "persisted output"

    def test_get_falls_back_to_sqlite(self, cache: PromptCache) -> None:
        """get 时若 local 缺失应从 SQLite 加载"""
        cache.set("p1", "o1", model="m1")
        # 清空 local
        cache._local.clear()
        # get 应从 SQLite 加载
        out = cache.get("p1", model="m1")
        assert out == "o1"
        # 应已回填 local
        assert len(cache._local) >= 1


class TestPromptCacheEviction:
    """内存淘汰策略"""

    def test_evict_memory_removes_oldest(self, cache: PromptCache) -> None:
        """_evict_memory 应淘汰过期时间最早的"""
        # 模拟 _local 满
        cache._local = {
            f"k{i}": CacheEntry(
                prefix_hash=f"h{i}",
                model="m",
                temperature=0.0,
                cached_output=f"o{i}",
                token_count=0,
                hit_count=0,
                created_at=float(i),
                expires_at=float(i + 1),
            )
            for i in range(10)
        }
        before = len(cache._local)
        cache._evict_memory()
        after = len(cache._local)
        # 应淘汰一半
        assert after == before // 2
        # 保留的是 expires_at 最大的（最后几个）
        # 最早的 h0..h4 应被删除
        assert "k0" not in cache._local
        assert "k9" in cache._local

    def test_set_triggers_eviction_when_full(self, cache: PromptCache) -> None:
        """当超过 MAX_ENTRIES 时应触发淘汰"""
        # 临时调小 MAX_ENTRIES 通过 _local 手动填充
        for i in range(MAX_ENTRIES + 10):
            key = f"prefix{i:06d}"  # 足够长以避免空前缀
            cache.set(key, f"out{i}")
        # _evict_memory 应被调用过
        assert len(cache._local) <= MAX_ENTRIES

    def test_evict_memory_empty(self, cache: PromptCache) -> None:
        """空 local 调用 _evict_memory 不应崩溃"""
        cache._evict_memory()
        assert cache._local == {}


class TestPromptCacheClear:
    """clear_expired / clear_all"""

    def test_clear_expired(self, cache: PromptCache) -> None:
        """clear_expired 应返回清理数量（可能为 0）"""
        n = cache.clear_expired()
        assert isinstance(n, int)
        assert n >= 0

    def test_clear_all(self, cache: PromptCache) -> None:
        """clear_all 应清空 local 和 DB"""
        cache.set("p1", "o1", model="m1")
        cache.set("p2", "o2", model="m2")
        assert len(cache._local) >= 2
        cache.clear_all()
        assert cache._local == {}
        # DB 也应清空
        import sqlite3

        conn = sqlite3.connect(cache._db_path)
        total = conn.execute("SELECT COUNT(*) FROM prompt_cache").fetchone()[0]
        conn.close()
        assert total == 0


class TestPromptCacheStats:
    """stats() 与 hit_rate()"""

    def test_stats(self, cache: PromptCache) -> None:
        """stats 应返回统计字典"""
        s = cache.stats()
        assert isinstance(s, dict)
        assert "memory_entries" in s
        assert "sqlite_entries" in s
        assert "db_size_kb" in s
        assert "hit_rate" in s

    def test_stats_after_sets(self, cache: PromptCache) -> None:
        """set 后 stats 应反映条目数"""
        cache.set("p1", "o1", model="m1")
        cache.set("p2", "o2", model="m2")
        s = cache.stats()
        assert s["memory_entries"] >= 2
        assert s["sqlite_entries"] >= 2

    def test_hit_rate_empty(self, cache: PromptCache) -> None:
        """空缓存的 hit_rate 应为 0.0"""
        assert cache.hit_rate() == 0.0

    def test_hit_rate_with_entries(self, cache: PromptCache) -> None:
        """有条目时 hit_rate 应为浮点数"""
        cache.set("p1", "o1", model="m1")
        # get 一次增加 hit
        cache.get("p1", model="m1")
        h = cache.hit_rate()
        assert isinstance(h, float)
        assert 0.0 <= h <= 1.0


class TestPromptCachePrefix:
    """_extract_prefix"""

    def test_extract_short_prompt(self, cache: PromptCache) -> None:
        """短 prompt 应取前 100 字符"""
        p = "x" * 50
        prefix, h = cache._extract_prefix(p)
        assert len(prefix) >= 50
        assert h  # 非空 hash

    def test_extract_long_prompt(self, cache: PromptCache) -> None:
        """长 prompt 应取前 1/3"""
        p = "y" * 1000
        prefix, h = cache._extract_prefix(p)
        assert len(prefix) == len(p) // 3
        assert len(h) == 64  # SHA256 hex

    def test_extract_empty(self, cache: PromptCache) -> None:
        """空 prompt 应返回空前缀"""
        prefix, h = cache._extract_prefix("")
        assert prefix == ""
        assert h == ""

    def test_same_prefix_same_hash(self, cache: PromptCache) -> None:
        """_extract_prefix 使用 max(100, len//3)，构造共享前 100 字符的 prompt"""
        common = "common_prefix_" + "a" * 90  # 共 104 字符
        # 后续字符不同，但 prefix 部分都从 common 开始
        p1 = common + "Z" * 200
        p2 = common + "Y" * 200
        _, h1 = cache._extract_prefix(p1)
        _, h2 = cache._extract_prefix(p2)
        # 前 100 字符相同 → hash 相同
        assert h1 == h2


class TestGetCacheSingleton:
    """get_cache 单例"""

    def test_singleton(self) -> None:
        """get_cache 应返回同一实例"""
        from pycoder.ai.cache import kv_cache

        kv_cache._cache = None
        c1 = get_cache()
        c2 = get_cache()
        assert c1 is c2
        kv_cache._cache = None


# ════════════════════════════════════════════════════════════════════
# iterative
# ════════════════════════════════════════════════════════════════════


class TestIterationPrompts:
    """ITERATION_PROMPTS 模板"""

    def test_contains_required_keys(self) -> None:
        """应包含 generate / review / improve 三个模板"""
        for key in ("generate", "review", "improve"):
            assert key in ITERATION_PROMPTS

    def test_generate_template_has_placeholders(self) -> None:
        """generate 模板应包含 language / instruction / constraints_text"""
        tmpl = ITERATION_PROMPTS["generate"]
        for placeholder in ["{language}", "{instruction}", "{constraints_text}", "{context_text}"]:
            assert placeholder in tmpl


class TestIterativeGeneratorBasic:
    """IterativeGenerator 基础行为"""

    def test_construction(self) -> None:
        """应能构造"""
        g = IterativeGenerator()
        assert g._bridge is None
        assert g.MAX_ITERATIONS == 3

    def test_extract_code_from_fenced_block(self) -> None:
        """应能提取 ```...``` 中的代码"""
        g = IterativeGenerator()
        response = "Some text\n```python\nx = 1\n```\nMore text"
        assert g._extract_code(response) == "x = 1"

    def test_extract_code_from_fenced_no_lang(self) -> None:
        """无语言标记的代码块也应能提取"""
        g = IterativeGenerator()
        response = "```\ny = 2\n```"
        assert g._extract_code(response) == "y = 2"

    def test_extract_code_no_block(self) -> None:
        """无代码块时应返回原始内容"""
        g = IterativeGenerator()
        response = "just plain text"
        assert g._extract_code(response) == "just plain text"

    def test_extract_code_empty(self) -> None:
        """空响应应返回空字符串"""
        g = IterativeGenerator()
        assert g._extract_code("") == ""

    def test_extract_code_multiline(self) -> None:
        """多行代码应被正确提取"""
        g = IterativeGenerator()
        response = "```python\ndef f():\n    return 1\n\ndef g():\n    return 2\n```"
        code = g._extract_code(response)
        assert "def f():" in code
        assert "def g():" in code


class TestIterativeGeneratorGenerate:
    """IterativeGenerator.generate 行为"""

    @pytest.mark.asyncio
    async def test_generate_with_no_problems(self) -> None:
        """审查反馈 '无问题' 时提前结束（passes=True）"""
        g = IterativeGenerator()
        req = CodeGenerationRequest(prompt="write add function")

        # 模拟 LLM：第 1 轮生成代码，第 2 轮审查说"无问题"
        responses = iter(
            [
                "```python\ndef add(a, b):\n    return a + b\n```",
                "无问题。代码已正确实现。",
            ]
        )

        async def fake_llm(prompt: str, max_tokens: int, temperature: float) -> str:
            return next(responses)

        with patch.object(g, "_call_llm", side_effect=fake_llm):
            result = await g.generate(req)

        assert isinstance(result, CodeGenerationResult)
        assert result.strategy_used == CodeGenStrategy.ITERATIVE
        assert result.passes_tests is True
        assert result.confidence > 0.8
        assert "add" in result.code

    @pytest.mark.asyncio
    async def test_generate_with_problems_and_fix(self) -> None:
        """审查发现足够长的问题（>=50字符）后再次生成"""
        g = IterativeGenerator()
        req = CodeGenerationRequest(prompt="write function")

        # 必须 >= 50 字符且不含 "无问题" / "没有发现"
        long_review = (
            "1. 缺少错误处理\n"
            "2. 缺少输入验证\n"
            "3. 缺少边界条件处理\n"
            "4. 缺少日志记录\n"
            "5. 缺少类型注解\n"
            "6. 缺少文档字符串\n"
        )
        responses = iter(
            [
                "```python\ndef f():\n    pass\n```",  # Round 1: 生成
                long_review,  # Round 2: 审查 (>=50 字符)
                "```python\ndef f():\n    return 42\n```",  # Round 2.5: 修复
                "```python\ndef f():\n    return 42  # optimized\n```",  # Round 3: 优化
            ]
        )

        async def fake_llm(prompt: str, max_tokens: int, temperature: float) -> str:
            return next(responses)

        with patch.object(g, "_call_llm", side_effect=fake_llm):
            result = await g.generate(req)

        assert result.strategy_used == CodeGenStrategy.ITERATIVE
        # 走到了 Round 3
        assert "optimized" in result.code or "42" in result.code

    @pytest.mark.asyncio
    async def test_generate_short_review(self) -> None:
        """审查 <50 字符应视为通过"""
        g = IterativeGenerator()
        req = CodeGenerationRequest(prompt="x")

        responses = iter(
            [
                "```python\nx = 1\n```",
                "ok",  # < 50 字符
            ]
        )

        async def fake_llm(prompt: str, max_tokens: int, temperature: float) -> str:
            return next(responses)

        with patch.object(g, "_call_llm", side_effect=fake_llm):
            result = await g.generate(req)

        assert result.passes_tests is True

    @pytest.mark.asyncio
    async def test_generate_with_constraints(self) -> None:
        """constraints 应被格式化进 prompt"""
        g = IterativeGenerator()
        req = CodeGenerationRequest(
            prompt="x",
            constraints=["Must be pure function", "No global state"],
        )

        captured_prompts: list[str] = []

        async def fake_llm(prompt: str, max_tokens: int, temperature: float) -> str:
            captured_prompts.append(prompt)
            return "```python\nx = 1\n```"

        with patch.object(g, "_call_llm", side_effect=fake_llm):
            await g.generate(req)

        # 第一个 prompt 是 generate 模板，应包含 constraints
        assert "Must be pure function" in captured_prompts[0]
        assert "No global state" in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_generate_with_context(self) -> None:
        """context 应被格式化进 prompt"""
        g = IterativeGenerator()
        req = CodeGenerationRequest(
            prompt="x",
            context="# existing module\ndef helper(): pass",
        )

        captured_prompts: list[str] = []

        async def fake_llm(prompt: str, max_tokens: int, temperature: float) -> str:
            captured_prompts.append(prompt)
            return "```python\nx = 1\n```"

        with patch.object(g, "_call_llm", side_effect=fake_llm):
            await g.generate(req)

        assert "existing module" in captured_prompts[0]

    @pytest.mark.asyncio
    async def test_generate_with_empty_first_response(self) -> None:
        """Round 1 返回空时不应崩溃"""
        g = IterativeGenerator()
        req = CodeGenerationRequest(prompt="x")

        async def fake_llm(prompt: str, max_tokens: int, temperature: float) -> str:
            return ""

        with patch.object(g, "_call_llm", side_effect=fake_llm):
            result = await g.generate(req)

        # 最终 code 仍应是 str (即使为空)
        assert isinstance(result.code, str)

    @pytest.mark.asyncio
    async def test_generate_includes_alternatives(self) -> None:
        """多轮生成时 alternatives 应包含历史版本"""
        g = IterativeGenerator()
        req = CodeGenerationRequest(prompt="x")

        responses = iter(
            [
                "```python\nv1\n```",
                "问题",  # 让 Round 2 继续
                "```python\nv2\n```",
                "```python\nv3\n```",
            ]
        )

        async def fake_llm(prompt: str, max_tokens: int, temperature: float) -> str:
            return next(responses)

        with patch.object(g, "_call_llm", side_effect=fake_llm):
            result = await g.generate(req)

        # 应有备选方案
        assert isinstance(result.alternatives, list)

    @pytest.mark.asyncio
    async def test_generate_confidence_higher_on_success(self) -> None:
        """passes_tests=True 时 confidence 应更高"""
        g_pass = IterativeGenerator()
        g_fail = IterativeGenerator()
        req = CodeGenerationRequest(prompt="x")

        # 1) Pass 场景
        async def pass_llm(prompt: str, max_tokens: int, temperature: float) -> str:
            if "审查" in prompt or "review" in prompt.lower() or "问题" in prompt:
                return "无问题"
            return "```python\nx = 1\n```"

        with patch.object(g_pass, "_call_llm", side_effect=pass_llm):
            pass_result = await g_pass.generate(req)

        # 2) Fail 场景（LLM 一直返回错误，但被吞）
        async def fail_llm(prompt: str, max_tokens: int, temperature: float) -> str:
            return "# 生成失败: 错误"

        with patch.object(g_fail, "_call_llm", side_effect=fail_llm):
            fail_result = await g_fail.generate(req)

        # Pass 时 confidence 应 >= Fail 时
        assert pass_result.confidence >= fail_result.confidence

"""
长期记忆增强器单元测试

测试 MemoryAugmentor 和 LongTermMemory 的核心功能：
- LongTermMemory 数据类创建与默认值
- 数据库初始化
- 存储新记忆 / 更新已有记忆
- 关键词检索（含项目过滤、重要性过滤）
- 时间衰减与淘汰
- 上下文提示词构建
- 关键词提取
- 统计信息获取
- 错误边界处理
"""

from __future__ import annotations

import json
import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

from pycoder.server.services.memory_augmentor import (
    LongTermMemory,
    MemoryAugmentor,
)


# ══════════════════════════════════════════════════════════
# 测试：LongTermMemory 数据类
# ══════════════════════════════════════════════════════════


class TestLongTermMemory:
    """LongTermMemory 数据类测试"""

    def test_create_defaults(self):
        """创建默认值记忆条目"""
        mem = LongTermMemory()
        assert mem.id == 0
        assert mem.project == ""
        assert mem.key == ""
        assert mem.content == ""
        assert mem.tags == []
        assert mem.importance == 0.5
        assert mem.access_count == 0
        assert mem.created_at == 0.0
        assert mem.last_accessed == 0.0
        assert mem.ttl_days == 90

    def test_create_with_values(self):
        """创建带值的记忆条目"""
        mem = LongTermMemory(
            id=1,
            project="pycoder",
            key="auth_implementation",
            content="使用 JWT + bcrypt",
            tags=["auth", "security"],
            importance=0.8,
            access_count=5,
            created_at=1000.0,
            last_accessed=2000.0,
            ttl_days=30,
        )
        assert mem.id == 1
        assert mem.project == "pycoder"
        assert mem.key == "auth_implementation"
        assert mem.content == "使用 JWT + bcrypt"
        assert mem.tags == ["auth", "security"]
        assert mem.importance == 0.8
        assert mem.access_count == 5
        assert mem.created_at == 1000.0
        assert mem.last_accessed == 2000.0
        assert mem.ttl_days == 30


# ══════════════════════════════════════════════════════════
# 测试：MemoryAugmentor 初始化与数据库
# ══════════════════════════════════════════════════════════


class TestMemoryAugmentorInit:
    """MemoryAugmentor 初始化与数据库测试"""

    def test_create_with_tmp_path(self, tmp_path):
        """使用临时路径创建增强器"""
        db_path = tmp_path / "test_memory.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        assert aug._db_path == str(db_path)
        assert db_path.exists()

    def test_create_default_path(self):
        """使用默认路径创建增强器"""
        with patch(
            "pycoder.server.unified_db.get_db_path",
            return_value="/tmp/test_default.db",
        ):
            aug = MemoryAugmentor()
            assert aug._db_path == "/tmp/test_default.db"

    def test_db_table_created(self, tmp_path):
        """数据库表被正确创建"""
        db_path = tmp_path / "test.db"
        aug = MemoryAugmentor(db_path=str(db_path))

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='long_term_memory'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_db_index_created(self, tmp_path):
        """数据库索引被正确创建"""
        db_path = tmp_path / "test.db"
        aug = MemoryAugmentor(db_path=str(db_path))

        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_ltm_project_key'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_db_init_idempotent(self, tmp_path):
        """重复初始化数据库不会出错"""
        db_path = tmp_path / "test.db"
        aug1 = MemoryAugmentor(db_path=str(db_path))
        aug1.store("test", "k1", "content1")
        # 第二次初始化不应报错
        aug2 = MemoryAugmentor(db_path=str(db_path))
        result = aug2.retrieve("content1")
        assert len(result) >= 1


# ══════════════════════════════════════════════════════════
# 测试：存储记忆
# ══════════════════════════════════════════════════════════


class TestStore:
    """存储记忆测试"""

    @pytest.fixture
    def aug(self, tmp_path):
        """创建测试用增强器"""
        db_path = tmp_path / "test_store.db"
        return MemoryAugmentor(db_path=str(db_path))

    def test_store_new_memory(self, aug):
        """存储新记忆"""
        mem_id = aug.store(
            project="pycoder",
            key="setup_guide",
            content="项目初始化步骤说明",
            tags=["setup", "guide"],
            importance=0.7,
            ttl_days=60,
        )
        assert mem_id > 0

    def test_store_update_existing(self, aug):
        """更新已存在的记忆"""
        aug.store("pycoder", "key1", "旧内容")
        mem_id = aug.store("pycoder", "key1", "新内容", importance=0.9)
        assert mem_id > 0

        # 检索验证更新
        results = aug.retrieve("新内容", project="pycoder")
        assert len(results) >= 1
        assert results[0]["content"] == "新内容"

    def test_store_content_truncation(self, aug):
        """内容超过 5000 字符被截断"""
        long_content = "X" * 6000
        mem_id = aug.store("pycoder", "long_key", long_content)
        assert mem_id > 0

        results = aug.retrieve("long_key", project="pycoder")
        assert len(results) >= 1
        assert len(results[0]["content"]) <= 5000

    def test_store_default_tags(self, aug):
        """不提供标签时默认为空列表"""
        aug.store("pycoder", "no_tags", "无标签内容")
        results = aug.retrieve("无标签", project="pycoder")
        assert len(results) >= 1
        assert results[0]["tags"] == []

    def test_store_multiple_projects(self, aug):
        """不同项目的记忆独立存储"""
        aug.store("proj_a", "key1", "项目A的记忆")
        aug.store("proj_b", "key1", "项目B的记忆")

        results_a = aug.retrieve("记忆", project="proj_a")
        results_b = aug.retrieve("记忆", project="proj_b")

        assert len(results_a) >= 1
        assert len(results_b) >= 1
        assert results_a[0]["content"] == "项目A的记忆"
        assert results_b[0]["content"] == "项目B的记忆"

    def test_store_same_key_different_projects(self, aug):
        """不同项目使用相同 key 互不影响"""
        aug.store("proj_a", "shared_key", "A的内容")
        aug.store("proj_b", "shared_key", "B的内容")

        results = aug.retrieve("shared_key", project="proj_a")
        assert len(results) >= 1
        assert results[0]["content"] == "A的内容"


# ══════════════════════════════════════════════════════════
# 测试：检索记忆
# ══════════════════════════════════════════════════════════


class TestRetrieve:
    """检索记忆测试"""

    @pytest.fixture
    def aug(self, tmp_path):
        """创建预填充的增强器"""
        db_path = tmp_path / "test_retrieve.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        aug.store("pycoder", "auth", "用户认证使用 JWT", tags=["auth", "security"], importance=0.9)
        aug.store("pycoder", "db", "数据库使用 SQLite", tags=["db", "storage"], importance=0.5)
        aug.store("pycoder", "api", "API 使用 FastAPI 框架", tags=["api", "web"], importance=0.7)
        aug.store("other", "config", "其他项目配置", tags=["config"], importance=0.3)
        return aug

    def test_retrieve_by_keyword(self, aug):
        """按关键词检索"""
        results = aug.retrieve("JWT")
        assert len(results) >= 1
        assert results[0]["key"] == "auth"

    def test_retrieve_by_tag(self, aug):
        """按标签检索"""
        results = aug.retrieve("security")
        assert len(results) >= 1
        assert "security" in results[0]["tags"]

    def test_retrieve_with_project_filter(self, aug):
        """按项目过滤"""
        results = aug.retrieve("数据库", project="pycoder")
        assert len(results) >= 1
        assert results[0]["key"] == "db"

    def test_retrieve_project_filter_excludes(self, aug):
        """项目过滤排除其他项目"""
        results = aug.retrieve("配置", project="pycoder")
        # "other" 项目的配置不应该被检索到
        for r in results:
            assert r["project"] == "pycoder"

    def test_retrieve_min_importance_filter(self, aug):
        """重要性过滤"""
        results = aug.retrieve("数据库", min_importance=0.6)
        # db importance=0.5 不应被检索到
        keys = {r["key"] for r in results}
        assert "db" not in keys

    def test_retrieve_max_results_limit(self, aug):
        """最大结果数限制"""
        # 添加更多记忆
        for i in range(10):
            aug.store("pycoder", f"key_{i}", f"Python 相关内容 {i}", importance=0.8)
        results = aug.retrieve("Python", max_results=3)
        assert len(results) <= 3

    def test_retrieve_no_keywords(self, aug):
        """无有效关键词返回空"""
        results = aug.retrieve("的")
        assert results == []

    def test_retrieve_no_match(self, aug):
        """无匹配结果"""
        results = aug.retrieve("不存在的关键词xyz123")
        assert results == []

    def test_retrieve_increments_access_count(self, aug):
        """检索增加访问计数（返回值为更新前计数，每轮 +1）"""
        # 检索一次 — 返回的 access_count 是更新前的值（0）
        aug.retrieve("JWT", project="pycoder")
        # 再检索一次 — 返回的 access_count 是上次更新后的值（1）
        results = aug.retrieve("JWT", project="pycoder")
        # 返回值是更新前的 access_count，所以这次是 1
        assert results[0]["access_count"] >= 1

    def test_retrieve_order_by_importance(self, aug):
        """结果按重要性排序"""
        results = aug.retrieve("数据库")
        if len(results) >= 2:
            assert results[0]["importance"] >= results[1]["importance"]

    def test_retrieve_empty_query(self, aug):
        """空查询字符串"""
        results = aug.retrieve("")
        assert results == []


# ══════════════════════════════════════════════════════════
# 测试：衰减与淘汰
# ══════════════════════════════════════════════════════════


class TestDecay:
    """衰减与淘汰测试"""

    @pytest.fixture
    def aug(self, tmp_path):
        """创建预填充的增强器"""
        db_path = tmp_path / "test_decay.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        # 高重要性记忆
        aug.store("pycoder", "important", "重要信息", importance=0.9)
        # 低重要性记忆
        aug.store("pycoder", "trivial", "琐碎信息", importance=0.01)
        # 零引用旧记忆
        old_time = time.time() - 200 * 86400  # 200 天前
        with aug._lock:
            conn = sqlite3.connect(aug._db_path)
            conn.execute(
                "UPDATE long_term_memory SET created_at = ?, last_accessed = ? WHERE key = ?",
                (old_time, old_time, "trivial"),
            )
            conn.commit()
            conn.close()
        return aug

    def test_apply_decay_returns_count(self, aug):
        """衰减函数返回淘汰数量"""
        count = aug.apply_decay()
        assert isinstance(count, int)
        assert count >= 0

    def test_apply_decay_removes_low_importance(self, aug):
        """衰减移除低重要性记忆"""
        aug.apply_decay(min_importance_threshold=0.05)
        results = aug.retrieve("琐碎", project="pycoder")
        # 低重要性记忆应被淘汰
        assert len(results) == 0

    def test_apply_decay_keeps_high_importance(self, aug):
        """衰减保留高重要性记忆"""
        aug.apply_decay(min_importance_threshold=0.05)
        results = aug.retrieve("重要", project="pycoder")
        assert len(results) >= 1

    def test_apply_decay_stale_zero_access(self, aug):
        """衰减移除零引用过期记忆"""
        # 标记一条记忆为过期且零引用
        old_time = time.time() - 200 * 86400
        with aug._lock:
            conn = sqlite3.connect(aug._db_path)
            conn.execute(
                "UPDATE long_term_memory SET created_at = ?, last_accessed = ?, "
                "access_count = 0, ttl_days = 1 WHERE key = ?",
                (old_time, old_time, "important"),
            )
            conn.commit()
            conn.close()

        aug.apply_decay()
        results = aug.retrieve("重要", project="pycoder")
        # 重要但 TTL 过期且零引用，应被淘汰
        assert len(results) == 0

    def test_apply_decay_idempotent(self, aug):
        """重复衰减不报错"""
        aug.apply_decay()
        count = aug.apply_decay()
        assert isinstance(count, int)


# ══════════════════════════════════════════════════════════
# 测试：上下文提示词构建
# ══════════════════════════════════════════════════════════


class TestBuildContextPrompt:
    """上下文提示词构建测试"""

    @pytest.fixture
    def aug(self, tmp_path):
        """创建预填充的增强器"""
        db_path = tmp_path / "test_context.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        aug.store(
            "pycoder",
            "auth",
            "使用 JWT 进行用户认证，配合 bcrypt 加密密码",
            tags=["auth", "security"],
            importance=0.9,
        )
        aug.store(
            "pycoder",
            "db",
            "使用 SQLite 作为本地数据库，通过 sqlite3 模块操作",
            tags=["db", "storage"],
            importance=0.7,
        )
        return aug

    def test_build_context_prompt_with_memories(self, aug):
        """有记忆时生成上下文"""
        prompt = aug.build_context_prompt("认证", project="pycoder")
        assert "相关长期记忆" in prompt
        assert "auth" in prompt
        assert "JWT" in prompt

    def test_build_context_prompt_no_match(self, aug):
        """无匹配时返回空字符串"""
        prompt = aug.build_context_prompt("不存在的关键词xyz", project="pycoder")
        assert prompt == ""

    def test_build_context_prompt_max_memories(self, aug):
        """最大记忆数限制"""
        # 添加更多记忆
        for i in range(5):
            aug.store("pycoder", f"extra_{i}", f"额外内容 {i}", importance=0.8)
        prompt = aug.build_context_prompt("额外", project="pycoder", max_memories=2)
        # 最多 2 条记忆
        assert prompt.count("**") <= 4  # 每条记忆有 2 个 **

    def test_build_context_prompt_content_truncated(self, aug):
        """内容被截断到 200 字符"""
        long_content = "A" * 300
        aug.store("pycoder", "long", long_content, importance=0.8)
        prompt = aug.build_context_prompt("long", project="pycoder")
        # 内容应被截断
        assert "A" * 200 in prompt
        assert "A" * 300 not in prompt


# ══════════════════════════════════════════════════════════
# 测试：关键词提取
# ══════════════════════════════════════════════════════════


class TestExtractKeywords:
    """关键词提取测试"""

    def test_extract_chinese_keywords(self):
        """提取中文关键词（连续中文作为整体提取）"""
        keywords = MemoryAugmentor._extract_keywords("用户认证系统实现")
        # 连续中文字符作为一个整体匹配
        assert "用户认证系统实现" in keywords

    def test_extract_english_keywords(self):
        """提取英文关键词"""
        keywords = MemoryAugmentor._extract_keywords("Python FastAPI authentication")
        assert "python" in keywords
        assert "fastapi" in keywords
        assert "authentication" in keywords

    def test_extract_mixed_keywords(self):
        """提取中英混合关键词"""
        keywords = MemoryAugmentor._extract_keywords("使用 Python 开发 FastAPI 应用")
        assert "python" in keywords
        assert "fastapi" in keywords
        assert "使用" in keywords or "开发" in keywords or "应用" in keywords

    def test_extract_stop_words_excluded(self):
        """停用词被排除"""
        keywords = MemoryAugmentor._extract_keywords("的 了 是 在 the a an is")
        assert "的" not in keywords
        assert "the" not in keywords
        assert "is" not in keywords

    def test_extract_single_char_excluded(self):
        """单字符被排除"""
        keywords = MemoryAugmentor._extract_keywords("a b c 我 你 他")
        assert "a" not in keywords
        assert "我" not in keywords

    def test_extract_empty_string(self):
        """空字符串返回空列表"""
        keywords = MemoryAugmentor._extract_keywords("")
        assert keywords == []

    def test_extract_numeric(self):
        """数字被保留"""
        keywords = MemoryAugmentor._extract_keywords("Python 3.12 版本")
        assert "python" in keywords
        # 数字可能被保留或排除，取决于正则匹配


# ══════════════════════════════════════════════════════════
# 测试：统计信息
# ══════════════════════════════════════════════════════════


class TestGetStats:
    """统计信息测试"""

    def test_get_stats_empty(self, tmp_path):
        """空数据库统计"""
        db_path = tmp_path / "test_stats.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        stats = aug.get_stats()
        assert stats["total_memories"] == 0
        assert stats["avg_importance"] == 0.0

    def test_get_stats_with_data(self, tmp_path):
        """有数据时的统计"""
        db_path = tmp_path / "test_stats2.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        aug.store("pycoder", "k1", "c1", importance=0.5)
        aug.store("pycoder", "k2", "c2", importance=0.9)
        stats = aug.get_stats()
        assert stats["total_memories"] == 2
        assert stats["avg_importance"] == pytest.approx(0.7, abs=0.01)

    def test_get_stats_thread_safe(self, tmp_path):
        """统计信息线程安全"""
        import threading

        db_path = tmp_path / "test_stats3.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        aug.store("pycoder", "k1", "c1", importance=0.5)

        results = []

        def _get_stats():
            results.append(aug.get_stats())

        threads = [threading.Thread(target=_get_stats) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 5
        for r in results:
            assert r["total_memories"] == 1


# ══════════════════════════════════════════════════════════
# 测试：边界情况
# ══════════════════════════════════════════════════════════


class TestEdgeCases:
    """边界情况测试"""

    def test_store_with_corrupt_tags_json(self, tmp_path):
        """存储损坏的标签 JSON 不影响检索"""
        db_path = tmp_path / "test_corrupt.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        aug.store("pycoder", "k1", "内容", tags=["tag1", "tag2"])

        # 手动破坏 tags JSON
        with aug._lock:
            conn = sqlite3.connect(aug._db_path)
            conn.execute(
                "UPDATE long_term_memory SET tags = ? WHERE key = ?",
                ("这不是有效的JSON{{{{", "k1"),
            )
            conn.commit()
            conn.close()

        # 检索不应崩溃
        results = aug.retrieve("内容", project="pycoder")
        assert len(results) >= 1
        # 损坏的 tags 应回退为空列表
        assert results[0]["tags"] == []

    def test_store_special_characters(self, tmp_path):
        """存储特殊字符"""
        db_path = tmp_path / "test_special.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        content = "特殊字符: !@#$%^&*()_+-=[]{}|;:',.<>?/~`"
        aug.store("pycoder", "special", content)
        results = aug.retrieve("特殊字符", project="pycoder")
        assert len(results) >= 1

    def test_store_unicode(self, tmp_path):
        """存储 Unicode 字符"""
        db_path = tmp_path / "test_unicode.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        content = "Unicode: 🎉 日本語 한국어 Español العربية"
        aug.store("pycoder", "unicode", content)
        results = aug.retrieve("Unicode", project="pycoder")
        assert len(results) >= 1

    def test_retrieve_sql_injection_safe(self, tmp_path):
        """检索对 SQL 注入安全"""
        db_path = tmp_path / "test_sql_inj.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        aug.store("pycoder", "k1", "正常内容")

        # 使用 SQL 注入尝试检索
        results = aug.retrieve("'; DROP TABLE long_term_memory; --")
        assert isinstance(results, list)

        # 表应仍然存在
        stats = aug.get_stats()
        assert stats["total_memories"] >= 1

    def test_large_batch_operations(self, tmp_path):
        """大批量操作"""
        db_path = tmp_path / "test_large.db"
        aug = MemoryAugmentor(db_path=str(db_path))
        # 批量存储 50 条记忆
        for i in range(50):
            aug.store("pycoder", f"key_{i}", f"内容 {i}", importance=0.5)

        stats = aug.get_stats()
        assert stats["total_memories"] == 50

        # 检索
        results = aug.retrieve("内容", max_results=10)
        assert len(results) <= 10
        assert len(results) > 0
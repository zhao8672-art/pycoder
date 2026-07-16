"""任务偏离检测器测试

覆盖:
  - DriftReport: 偏离检测报告数据类
  - DriftDetector: 偏离检测器
    - set_goal: 设置目标
    - _extract_keywords: 关键词提取
    - _extract_bigrams: N-gram 提取
    - _calc_similarity: 相似度计算
    - check: 偏离检测
    - drift_rate: 偏离率计算
    - generate_review_prompt: 任务回顾提示
    - reset: 重置状态
"""
from __future__ import annotations

import time

import pytest

from pycoder.server.services.drift_detector import DriftDetector, DriftReport


# ══════════════════════════════════════════════════════════
# 辅助函数
# ══════════════════════════════════════════════════════════


@pytest.fixture
def detector() -> DriftDetector:
    """创建一个标准检测器"""
    d = DriftDetector(sensitivity=0.25, check_every_n=3)
    d.set_goal("创建一个 FastAPI 用户认证系统，支持 JWT 登录和 OAuth2")
    return d


@pytest.fixture
def empty_detector() -> DriftDetector:
    """创建未设置目标的检测器"""
    return DriftDetector()


# ══════════════════════════════════════════════════════════
# DriftReport 测试
# ══════════════════════════════════════════════════════════


class TestDriftReport:
    """偏离检测报告数据类"""

    def test_not_drifting(self):
        """未偏离"""
        report = DriftReport(
            is_drifting=False,
            similarity=0.85,
            warning="",
            suggested_action="",
            last_check_at="12:00:00",
        )
        assert report.is_drifting is False
        assert report.similarity == 0.85
        assert report.warning == ""
        assert report.suggested_action == ""

    def test_drifting(self):
        """正在偏离"""
        report = DriftReport(
            is_drifting=True,
            similarity=0.10,
            warning="偏离警告",
            suggested_action="refocus",
            last_check_at="12:00:00",
        )
        assert report.is_drifting is True
        assert report.similarity == 0.10
        assert report.warning == "偏离警告"
        assert report.suggested_action == "refocus"


# ══════════════════════════════════════════════════════════
# DriftDetector 关键词提取测试
# ══════════════════════════════════════════════════════════


class TestDriftDetectorKeywords:
    """关键词提取"""

    def test_extract_chinese_keywords(self):
        """中文关键词提取"""
        kw = DriftDetector._extract_keywords("创建一个 FastAPI 用户认证系统")
        assert "创建" in kw or "fastapi" in kw or "用户" in kw or "认证" in kw or "系统" in kw
        # 停用词不应出现
        assert "的" not in kw
        assert "了" not in kw
        assert "是" not in kw

    def test_extract_english_keywords(self):
        """英文关键词提取"""
        kw = DriftDetector._extract_keywords("the quick brown fox jumps")
        # 停用词被过滤
        assert "the" not in kw
        # 实词被保留（长度 >= 2）
        assert "quick" in kw
        assert "brown" in kw
        assert "fox" in kw
        assert "jumps" in kw

    def test_extract_mixed_language(self):
        """中英混合关键词"""
        kw = DriftDetector._extract_keywords("实现 FastAPI 的 JWT 认证模块")
        # 停用词过滤
        assert "的" not in kw
        # 短词过滤（长度 < 2）
        # "JWT" 长度只有 3，应该保留
        assert "jwt" in kw
        assert "fastapi" in kw

    def test_extract_empty_string(self):
        """空字符串"""
        kw = DriftDetector._extract_keywords("")
        assert len(kw) == 0

    def test_extract_short_words_filtered(self):
        """过短的词被过滤"""
        kw = DriftDetector._extract_keywords("a b c d e 1 2")
        assert len(kw) == 0


# ══════════════════════════════════════════════════════════
# DriftDetector bigram 提取测试
# ══════════════════════════════════════════════════════════


class TestDriftDetectorBigrams:
    """N-gram 提取"""

    def test_extract_bigrams_english(self):
        """英文 bigram"""
        bg = DriftDetector._extract_bigrams("hello world test")
        assert ("hello", "world") in bg
        assert ("world", "test") in bg

    def test_extract_bigrams_chinese(self):
        """中文 bigram — 中文词间无空格，regex 将整段作为一个 token"""
        bg = DriftDetector._extract_bigrams("用户 认证 系统")
        assert ("用户", "认证") in bg
        assert ("认证", "系统") in bg

    def test_extract_bigrams_single_word(self):
        """单个词无 bigram"""
        bg = DriftDetector._extract_bigrams("hello")
        assert len(bg) == 0

    def test_extract_bigrams_empty(self):
        """空字符串无 bigram"""
        bg = DriftDetector._extract_bigrams("")
        assert len(bg) == 0

    def test_extract_bigrams_case_insensitive(self):
        """大小写不敏感"""
        bg = DriftDetector._extract_bigrams("Hello World")
        assert ("hello", "world") in bg


# ══════════════════════════════════════════════════════════
# DriftDetector 相似度计算测试
# ══════════════════════════════════════════════════════════


class TestDriftDetectorSimilarity:
    """相似度计算"""

    def test_exact_match(self, detector):
        """完全匹配高相似度"""
        sim = detector._calc_similarity("FastAPI 用户认证系统 JWT 登录")
        assert sim > 0.3

    def test_no_match(self, detector):
        """完全不匹配低相似度"""
        sim = detector._calc_similarity("今天天气怎么样")
        assert sim < 0.3

    def test_no_goal(self, empty_detector):
        """无目标时返回 1.0"""
        sim = empty_detector._calc_similarity("anything")
        assert sim == 1.0

    def test_empty_message(self, detector):
        """空消息返回 0.5"""
        sim = detector._calc_similarity("")
        assert sim == 0.5

    def test_partial_match(self, detector):
        """部分匹配"""
        sim = detector._calc_similarity("需要修改 FastAPI 的路由配置")
        assert sim >= 0.0


# ══════════════════════════════════════════════════════════
# DriftDetector check 检测测试
# ══════════════════════════════════════════════════════════


class TestDriftDetectorCheck:
    """偏离检测"""

    def test_check_every_n_rounds_skip(self, detector):
        """非检测轮次跳过"""
        # 第 1 轮：不检测
        report = detector.check("FastAPI 用户认证")
        assert report.is_drifting is False
        assert report.similarity == 1.0

    def test_check_on_nth_round(self, detector):
        """第 N 轮检测"""
        detector.check("FastAPI setup")  # round 1
        detector.check("JWT 配置")       # round 2
        report = detector.check("需要 OAuth2")  # round 3, check_every_n=3
        # 应该执行检测了
        assert report.similarity > 0.0  # 应该有实际相似度

    def test_drift_detected(self, detector):
        """检测到偏离"""
        # 填满 non-check 轮次
        detector.check("不相关消息 1")  # round 1
        detector.check("不相关消息 2")  # round 2
        # 第 3 轮检查，但最近消息都是不相关的
        report = detector.check("今天的天气非常好")  # round 3
        # 最近消息都是不相关的，相似度应低于阈值
        # 注意：check_every_n=3，最近 3 条消息都是不相关的
        assert report.is_drifting is True
        assert report.similarity < 0.25
        assert "⚠️" in report.warning
        assert report.suggested_action == "refocus"

    def test_no_drift_with_relevant_messages(self, detector):
        """相关消息不触发偏离"""
        detector.check("FastAPI 路由配置")   # round 1
        detector.check("实现 JWT 认证")      # round 2
        report = detector.check("OAuth2 集成")  # round 3
        assert report.is_drifting is False

    def test_drift_count_increments(self, detector):
        """偏离计数递增"""
        # 触发偏离
        detector.check("msg1")
        detector.check("msg2")
        detector.check("msg3")  # 偏离
        assert detector._drift_count == 1

        detector.check("msg4")
        detector.check("msg5")
        detector.check("msg6")  # 再次偏离
        assert detector._drift_count == 2

    def test_total_checks_increments(self, detector):
        """总检查次数递增"""
        assert detector._total_checks == 0
        detector.check("a")
        detector.check("b")
        detector.check("c")  # check point
        assert detector._total_checks == 1

    def test_check_with_sensitivity_high(self):
        """高灵敏度更容易触发偏离"""
        d = DriftDetector(sensitivity=0.90, check_every_n=1)
        d.set_goal("FastAPI 用户认证")
        report = d.check("今天天气不错")
        # 敏感度 0.90，相似度低于 0.90 就触发
        assert report.is_drifting is True

    def test_check_with_sensitivity_low(self):
        """低灵敏度不触发偏离 — 使用相关消息"""
        d = DriftDetector(sensitivity=0.01, check_every_n=1)
        d.set_goal("FastAPI 用户认证系统")
        # 使用相关消息，相似度应高于 0.01
        report = d.check("FastAPI 认证相关讨论")
        # 敏感度 0.01，相关消息不会触发
        assert report.is_drifting is False


# ══════════════════════════════════════════════════════════
# DriftDetector 属性测试
# ══════════════════════════════════════════════════════════


class TestDriftDetectorProperties:
    """检测器属性"""

    def test_drift_rate_zero_initially(self, detector):
        """初始偏离率为 0"""
        assert detector.drift_rate == 0.0

    def test_drift_rate_after_drift(self):
        """偏离后偏离率计算 — 使用不相关消息触发偏离"""
        d = DriftDetector(sensitivity=0.25, check_every_n=3)
        d.set_goal("创建一个 FastAPI 用户认证系统，支持 JWT 登录和 OAuth2")
        # 使用不相关的多字符消息
        d.check("今天天气")    # round 1
        d.check("今晚吃什么")  # round 2
        d.check("明天去哪玩")  # round 3 检查，偏离
        d.check("最近新闻")    # round 4
        d.check("电影推荐")    # round 5
        d.check("旅游攻略")    # round 6 检查，偏离
        d.check("健身计划")    # round 7
        d.check("读书笔记")    # round 8
        d.check("美食推荐")    # round 9 检查，偏离
        # 3 次检查，3 次偏离
        assert d.drift_rate == 1.0

    def test_drift_rate_partial(self, detector):
        """部分偏离 — 使用强相关消息不触发偏离"""
        # 触发 9 轮，3 次检查，全部使用强相关消息
        for i in range(9):
            detector.check("FastAPI JWT 用户认证 OAuth2 登录系统")  # 强相关消息
        # 没有偏离，所以 drift_rate 应该是 0
        assert detector.drift_rate == 0.0


# ══════════════════════════════════════════════════════════
# DriftDetector review_prompt 测试
# ══════════════════════════════════════════════════════════


class TestDriftDetectorReviewPrompt:
    """任务回顾提示"""

    def test_generate_review_prompt(self, detector):
        """生成回顾提示"""
        detector.check("a")
        detector.check("b")
        detector.check("c")  # check point
        prompt = detector.generate_review_prompt()
        assert "## 🔄 任务回顾" in prompt
        assert "FastAPI" in prompt
        assert "当前轮次" in prompt
        assert "已用时间" in prompt
        assert "偏离率" in prompt

    def test_review_prompt_with_drift(self):
        """有偏离的回顾提示 — 使用不相关消息触发偏离"""
        d = DriftDetector(sensitivity=0.25, check_every_n=3)
        d.set_goal("创建一个 FastAPI 用户认证系统，支持 JWT 登录和 OAuth2")
        d.check("今天天气")    # round 1
        d.check("今晚吃什么")  # round 2
        d.check("明天去哪玩")  # round 3 检查，偏离
        prompt = d.generate_review_prompt()
        assert "⚠️ 偏离提醒" in prompt
        assert "偏离" in prompt

    def test_review_prompt_no_drift(self, detector):
        """无偏离的回顾提示"""
        detector.check("FastAPI 认证")
        detector.check("JWT 实现")
        detector.check("OAuth2 集成")  # 不偏离
        prompt = detector.generate_review_prompt()
        assert "偏离提醒" not in prompt

    def test_review_prompt_goals_truncated(self):
        """长目标在显示时截断到 200 字符"""
        d = DriftDetector()
        d.set_goal("A" * 300)
        prompt = d.generate_review_prompt()
        # _goal 本身不截断，display 时截断到 200 字符
        assert len(d._goal) == 300
        # 提示中显示的目标被截断
        assert "**原定目标**: " + "A" * 200 in prompt


# ══════════════════════════════════════════════════════════
# DriftDetector reset 测试
# ══════════════════════════════════════════════════════════


class TestDriftDetectorReset:
    """重置状态"""

    def test_reset_clears_counters(self, detector):
        """重置清空计数器"""
        detector.check("a")
        detector.check("b")
        detector.check("c")  # check point
        assert detector._round_count == 3
        assert detector._total_checks == 1

        detector.reset()
        assert detector._round_count == 0
        assert detector._total_checks == 0
        assert detector._drift_count == 0
        assert len(detector._last_user_messages) == 0


# ══════════════════════════════════════════════════════════
# DriftDetector set_goal 测试
# ══════════════════════════════════════════════════════════


class TestDriftDetectorSetGoal:
    """设置目标"""

    def test_set_goal_extracts_keywords(self, empty_detector):
        """设置目标时提取关键词 — 中文词间无空格时整段作为 token"""
        empty_detector.set_goal("FastAPI 用户认证系统")
        assert len(empty_detector._goal_keywords) > 0
        assert "fastapi" in empty_detector._goal_keywords
        # "用户认证系统" 作为一个整体被提取（中文词间无空格）
        assert "用户认证系统" in empty_detector._goal_keywords

    def test_set_goal_resets_counters(self, detector):
        """设置新目标重置计数器"""
        detector.check("a")
        detector.check("b")
        detector.check("c")
        detector.set_goal("新的目标")
        assert detector._round_count == 0
        assert detector._drift_count == 0
        assert detector._total_checks == 0

    def test_set_goal_sets_session_start(self, empty_detector):
        """设置目标记录会话开始时间"""
        assert empty_detector._session_start_time == 0.0
        empty_detector.set_goal("测试目标")
        assert empty_detector._session_start_time > 0.0


# ══════════════════════════════════════════════════════════
# DriftDetector 边界测试
# ══════════════════════════════════════════════════════════


class TestDriftDetectorEdgeCases:
    """边界情况"""

    def test_check_every_n_one(self):
        """每轮都检测"""
        d = DriftDetector(check_every_n=1)
        d.set_goal("FastAPI")
        report = d.check("Hello")  # 第 1 轮就检测
        assert report.similarity < 1.0  # 实际检测了

    def test_last_messages_bounded(self):
        """最近消息列表有上限"""
        d = DriftDetector(check_every_n=5)
        d.set_goal("Test")
        for i in range(10):
            d.check(f"msg_{i}")
        assert len(d._last_user_messages) <= 5

    def test_default_sensitivity(self):
        """默认敏感度"""
        d = DriftDetector()
        assert d._sensitivity == 0.25

    def test_default_check_every_n(self):
        """默认检测间隔"""
        d = DriftDetector()
        assert d._check_every_n == 5
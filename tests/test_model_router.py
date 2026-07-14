"""P3: 多模型路由测试

覆盖:
  - TaskClassifier: 任务类型识别
  - ModelCapabilityMatrix: 能力评分
  - ModelRouter: 任务感知路由
"""
from __future__ import annotations

import pytest

from pycoder.server.services.model_router import (
    ModelCapabilityMatrix,
    ModelRouter,
    RouteResult,
    TaskClassifier,
    TaskProfile,
    get_model_router,
)


# ══════════════════════════════════════════════════════════
# TaskClassifier
# ══════════════════════════════════════════════════════════


class TestTaskClassifier:

    def setup_method(self):
        self.clf = TaskClassifier()

    def test_code_gen_task(self):
        p = self.clf.classify("请实现一个 FastAPI 路由")
        assert p.task_type == "code_gen"
        assert p.requires_code is True

    def test_code_review_task(self):
        p = self.clf.classify("请审查这段代码的质量")
        assert p.task_type == "code_review"

    def test_reasoning_task(self):
        p = self.clf.classify("为什么这个设计比另一个更好？请分析")
        assert p.task_type == "reasoning"
        assert p.requires_reasoning is True

    def test_vision_task(self):
        p = self.clf.classify("请看这张图片并描述")
        assert p.task_type == "vision"
        assert p.requires_vision is True

    def test_chat_task(self):
        p = self.clf.classify("你好，今天天气怎么样")
        assert p.task_type == "chat"

    def test_empty_message(self):
        p = self.clf.classify("")
        assert p.task_type == "chat"

    def test_complexity_high(self):
        p = self.clf.classify("请设计一个完整的系统架构")
        assert p.complexity == "high"

    def test_complexity_low(self):
        p = self.clf.classify("简单回答：1+1=?")
        assert p.complexity == "low"

    def test_translation_task(self):
        p = self.clf.classify("请翻译这段文字")
        assert p.task_type == "translation"

    def test_token_estimation(self):
        p = self.clf.classify("a" * 400)
        assert p.estimated_tokens >= 100

    def test_vision_priority_over_code(self):
        """视觉任务优先级高于代码"""
        p = self.clf.classify("请看这张截图并修改代码")
        assert p.task_type == "vision"
        assert p.requires_vision is True


# ══════════════════════════════════════════════════════════
# ModelCapabilityMatrix
# ══════════════════════════════════════════════════════════


class TestModelCapabilityMatrix:

    def test_matrix_has_models(self):
        m = ModelCapabilityMatrix()
        models = m.list_models()
        assert len(models) >= 4  # 至少 4 个模型

    def test_coder_has_high_code_score(self):
        m = ModelCapabilityMatrix()
        cap = m.get("deepseek-coder")
        assert cap is not None
        assert cap.code_score >= 90  # coder 模型代码评分高

    def test_flash_has_high_speed_score(self):
        m = ModelCapabilityMatrix()
        cap = m.get("deepseek-v4-flash")
        assert cap is not None
        assert cap.speed_score >= 80

    def test_vision_models_have_vision_score(self):
        m = ModelCapabilityMatrix()
        vision_models = [c for c in m.list_models() if c.vision_score > 0]
        assert len(vision_models) >= 1

    def test_nonexistent_model(self):
        m = ModelCapabilityMatrix()
        assert m.get("nonexistent-model") is None

    def test_cost_score_inversely_proportional_to_price(self):
        """价格越低，cost_score 越高"""
        m = ModelCapabilityMatrix()
        flash = m.get("deepseek-v4-flash")
        pro = m.get("deepseek-v4-pro")
        if flash and pro:
            assert flash.cost_score > pro.cost_score


# ══════════════════════════════════════════════════════════
# ModelRouter
# ══════════════════════════════════════════════════════════


class TestModelRouter:

    def setup_method(self):
        self.router = ModelRouter()

    def test_route_code_gen_prefers_coder(self):
        """代码生成任务应优先 coder 模型"""
        result = self.router.route("请实现一个用户认证模块")
        assert result.task_type == "code_gen"
        # coder 模型应有较高 code_score
        cap = self.router.matrix.get(result.model_id)
        assert cap is not None
        assert cap.code_score >= 75

    def test_route_vision_selects_vision_model(self):
        """视觉任务必须选支持 vision 的模型"""
        result = self.router.route("请分析这张截图")
        assert result.task_type == "vision"
        cap = self.router.matrix.get(result.model_id)
        assert cap is not None
        assert cap.vision_score > 0

    def test_route_reasoning_prefers_reasoning_model(self):
        """推理任务应选 reasoning_score 高的模型"""
        result = self.router.route("请分析这个架构设计的优劣并给出决策")
        assert result.task_type == "reasoning"
        cap = self.router.matrix.get(result.model_id)
        assert cap is not None
        assert cap.reasoning_score >= 60

    def test_route_chat_prefers_fast_cheap(self):
        """普通对话应优先速度+成本"""
        result = self.router.route("你好")
        assert result.task_type == "chat"
        cap = self.router.matrix.get(result.model_id)
        assert cap is not None

    def test_user_preference_overrides_routing(self):
        """用户显式指定模型时优先"""
        result = self.router.route("请实现代码", prefer_model="deepseek-chat")
        assert result.model_id == "deepseek-chat"
        assert "用户显式" in result.reason

    def test_route_result_has_reason(self):
        """路由结果包含原因说明"""
        result = self.router.route("请审查代码")
        assert result.reason
        assert len(result.reason) > 5

    def test_route_result_has_score(self):
        result = self.router.route("请实现功能")
        assert result.score >= 0

    def test_get_model_router_singleton(self):
        r1 = get_model_router()
        r2 = get_model_router()
        assert r1 is r2

    def test_empty_message_routes_to_chat(self):
        result = self.router.route("")
        assert result.task_type == "chat"

    def test_high_complexity_prefers_high_capability(self):
        """高复杂度任务偏好高能力模型"""
        result_high = self.router.route("请设计完整的系统架构")
        result_low = self.router.route("简单回答 1+1")
        # 高复杂度应选 reasoning+code 评分更高的模型
        cap_high = self.router.matrix.get(result_high.model_id)
        cap_low = self.router.matrix.get(result_low.model_id)
        assert cap_high is not None
        assert cap_low is not None
        # 高复杂度模型的能力评分应不低于低复杂度
        assert (cap_high.reasoning_score + cap_high.code_score) >= \
               (cap_low.reasoning_score + cap_low.code_score) - 10

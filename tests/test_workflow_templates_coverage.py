"""
workflow_templates.py 模块单元测试 — 覆盖率目标 ≥80%

覆盖内容:
  - WorkflowStage / WorkflowTemplate 数据类构造与默认值
  - WORKFLOW_TEMPLATES 字典完整性与关键字段
  - get_workflow / list_workflows / estimate_budget 便捷函数
  - get_workflow_stages_parallel_map 并行阶段分组算法（含合并分组、串行阶段、未知工作流）
"""

from __future__ import annotations

import pytest

from pycoder.server.services.workflow_templates import (
    WORKFLOW_TEMPLATES,
    WorkflowStage,
    WorkflowTemplate,
    estimate_budget,
    get_workflow,
    get_workflow_stages_parallel_map,
    list_workflows,
)


# ── 数据类 ──

def test_workflow_stage_defaults():
    """WorkflowStage 默认值: deliverables/parallel_with 空列表, timeout 300, retries 2"""
    stage = WorkflowStage(name="阶段", agent_role="dev", description="测试")
    assert stage.name == "阶段"
    assert stage.agent_role == "dev"
    assert stage.description == "测试"
    assert stage.deliverables == []
    assert stage.parallel_with == []
    assert stage.timeout_seconds == 300
    assert stage.max_retries == 2


def test_workflow_stage_custom_fields():
    """WorkflowStage 自定义字段全部生效"""
    stage = WorkflowStage(
        name="实现",
        agent_role="developer",
        description="编码",
        deliverables=["a.py"],
        parallel_with=["测试"],
        timeout_seconds=600,
        max_retries=5,
    )
    assert stage.deliverables == ["a.py"]
    assert stage.parallel_with == ["测试"]
    assert stage.timeout_seconds == 600
    assert stage.max_retries == 5


def test_workflow_template_defaults():
    """WorkflowTemplate 必填字段与默认 required_deliverables"""
    tmpl = WorkflowTemplate(
        id="x",
        name="N",
        description="D",
        stages=[],
        token_budget=100,
        cost_budget_usd=1.0,
        total_timeout=60,
        max_concurrent_agents=1,
    )
    assert tmpl.required_deliverables == []
    assert tmpl.stages == []


# ── 预定义模板 ──

def test_workflow_templates_keys():
    """WORKFLOW_TEMPLATES 至少包含四个预定义工作流"""
    expected = {"fullstack-dev", "api-service", "hotfix", "code-review"}
    assert expected.issubset(WORKFLOW_TEMPLATES.keys())


def test_fullstack_dev_template_structure():
    """fullstack-dev 模板有 9 个阶段、并行阶段包含代码实现与测试编写"""
    tmpl = get_workflow("fullstack-dev")
    assert tmpl is not None
    assert tmpl.id == "fullstack-dev"
    assert len(tmpl.stages) == 9
    impl = next(s for s in tmpl.stages if s.name == "代码实现(并行)")
    test_stage = next(s for s in tmpl.stages if s.name == "测试编写")
    assert "测试编写" in impl.parallel_with
    assert "代码实现(并行)" in test_stage.parallel_with
    assert tmpl.token_budget == 150000
    assert tmpl.cost_budget_usd == 5.0
    assert tmpl.max_concurrent_agents == 6
    assert "README.md" in tmpl.required_deliverables


def test_api_service_template():
    tmpl = get_workflow("api-service")
    assert tmpl is not None
    assert len(tmpl.stages) == 6
    assert tmpl.token_budget == 80000
    assert tmpl.cost_budget_usd == 3.0


def test_hotfix_template():
    tmpl = get_workflow("hotfix")
    assert tmpl is not None
    assert len(tmpl.stages) == 5
    assert tmpl.token_budget == 50000
    assert tmpl.max_concurrent_agents == 2


def test_code_review_template():
    tmpl = get_workflow("code-review")
    assert tmpl is not None
    assert len(tmpl.stages) == 5
    assert tmpl.token_budget == 30000
    # 所有阶段都是 qa 角色
    assert all(s.agent_role == "qa" for s in tmpl.stages)


def test_get_workflow_unknown_returns_none():
    """get_workflow 对未知 ID 返回 None"""
    assert get_workflow("not-exist") is None


# ── list_workflows ──

def test_list_workflows_returns_summary_list():
    """list_workflows 返回所有模板的概要字典"""
    items = list_workflows()
    assert isinstance(items, list)
    assert len(items) == len(WORKFLOW_TEMPLATES)
    first = items[0]
    assert {"id", "name", "description", "stages", "token_budget", "cost_usd"} <= set(first)
    ids = [it["id"] for it in items]
    assert "fullstack-dev" in ids


# ── estimate_budget ──

def test_estimate_budget_default_scale():
    """estimate_budget 默认 scale=1.0 返回原始预算"""
    est = estimate_budget("api-service")
    assert est["workflow"] == "后端 API 服务"
    assert est["token_budget"] == 80000
    assert est["cost_estimate_usd"] == 3.0
    assert est["total_timeout_seconds"] == 900
    assert est["max_concurrent_agents"] == 4


def test_estimate_budget_scaled():
    """estimate_budget 按比例缩放 token 与成本（取整与四舍五入）"""
    est = estimate_budget("fullstack-dev", scale=2.0)
    assert est["token_budget"] == 300000
    assert est["cost_estimate_usd"] == 10.0


def test_estimate_budget_fractional():
    """estimate_budget 小数 scale 测试四舍五入"""
    est = estimate_budget("hotfix", scale=0.333)
    # 2.0 * 0.333 = 0.666 → round 至 0.67
    assert est["cost_estimate_usd"] == round(2.0 * 0.333, 2)


def test_estimate_budget_unknown_workflow():
    """estimate_budget 未知工作流返回 error 字典"""
    est = estimate_budget("does-not-exist")
    assert "error" in est
    assert "does-not-exist" in est["error"]


# ── get_workflow_stages_parallel_map ──

def test_parallel_map_fullstack_dev_groups_parallel_stages():
    """fullstack-dev 的并行阶段应被合并为同一组"""
    groups = get_workflow_stages_parallel_map("fullstack-dev")
    assert isinstance(groups, list)
    # 找到包含 '代码实现(并行)' 的组
    impl_group = next(g for g in groups if "代码实现(并行)" in g)
    assert "测试编写" in impl_group  # 应在同一组
    # 阶段数量 = 9 个阶段被全部覆盖
    seen = {name for group in groups for name in group}
    assert len(seen) == 9


def test_parallel_map_serial_workflow():
    """code-review 所有阶段串行, 每个阶段自成一组"""
    groups = get_workflow_stages_parallel_map("code-review")
    assert len(groups) == 5
    # 每组只有一个阶段
    assert all(len(g) == 1 for g in groups)


def test_parallel_map_unknown_workflow_returns_empty():
    """未知工作流返回空列表"""
    assert get_workflow_stages_parallel_map("nope") == []


def test_parallel_map_preserves_stage_order():
    """阶段在结果中的相对顺序与定义顺序一致"""
    tmpl = get_workflow("api-service")
    groups = get_workflow_stages_parallel_map("api-service")
    expected_names = [s.name for s in tmpl.stages]
    actual_order = []
    for g in groups:
        for name in expected_names:
            if name in g and name not in actual_order:
                actual_order.append(name)
    # api-service 没有并行阶段, 顺序应一致
    assert actual_order == expected_names


def test_parallel_map_dedupes_seen_stages():
    """已处理的阶段不会被重复加入结果"""
    tmpl = get_workflow("fullstack-dev")
    groups = get_workflow_stages_parallel_map("fullstack-dev")
    flat = [name for g in groups for name in g]
    # 没有重复
    assert len(flat) == len(set(flat))
    # 包含所有阶段
    assert len(flat) == len(tmpl.stages)


def test_workflow_stage_deliverables_independent():
    """每个 WorkflowStage 的 deliverables 列表是独立实例（field(default_factory) 验证）"""
    s1 = WorkflowStage(name="a", agent_role="r", description="d")
    s2 = WorkflowStage(name="b", agent_role="r", description="d")
    s1.deliverables.append("x")
    assert s2.deliverables == []
    assert "x" not in s2.deliverables

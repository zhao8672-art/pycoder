"""
对 pycoder/server 服务层模块的综合单元测试。

覆盖模块:
  9.  services/task_tracker.py       — 任务追踪器
  10. services/task_decomposer.py    — 任务分解器
  11. services/context_orchestrator.py — 上下文编排器
  12. services/source_tracer.py      — 信息溯源与事实校验
  13. services/patch_aggregator.py   — 缺陷聚合器
  14. recommendation/engine.py       — 推荐引擎
  15. sync/cloud_sync_engine.py      — 云端同步引擎
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════
# 9. services/task_tracker.py 测试
# ═══════════════════════════════════════════════════════════════


class TestTaskPhase:
    """TaskPhase 枚举测试"""

    def test_all_phases_exist(self):
        """所有阶段枚举值存在"""
        from pycoder.server.services.task_tracker import TaskPhase

        assert TaskPhase.INIT.value == "init"
        assert TaskPhase.ANALYZING.value == "analyzing"
        assert TaskPhase.PLANNING.value == "planning"
        assert TaskPhase.EXECUTING.value == "executing"
        assert TaskPhase.VERIFYING.value == "verifying"
        assert TaskPhase.DONE.value == "done"
        assert TaskPhase.FAILED.value == "failed"
        assert TaskPhase.IDLE.value == "idle"

    def test_phase_count(self):
        """阶段总数正确"""
        from pycoder.server.services.task_tracker import TaskPhase

        assert len(TaskPhase) == 8


class TestTaskAnchor:
    """TaskAnchor 数据类测试"""

    def test_create_anchor(self):
        """创建 TaskAnchor"""
        from pycoder.server.services.task_tracker import TaskAnchor

        anchor = TaskAnchor(
            goal="创建 FastAPI 应用",
            parameters={"lang": "python"},
            current_phase="init",
            completed_steps=[],
            next_step="解析需求",
            last_decision="",
            drift_warnings=[],
        )
        assert anchor.goal == "创建 FastAPI 应用"
        assert anchor.current_phase == "init"

    def test_to_prompt_basic(self):
        """to_prompt 生成基本锚点文本"""
        from pycoder.server.services.task_tracker import TaskAnchor

        anchor = TaskAnchor(
            goal="创建 FastAPI 应用",
            parameters={"lang": "python", "framework": "fastapi"},
            current_phase="executing",
            completed_steps=["分析需求", "设计架构"],
            next_step="实现 API 端点",
            last_decision="使用 FastAPI",
            drift_warnings=[],
        )
        prompt = anchor.to_prompt()
        assert "创建 FastAPI 应用" in prompt
        assert "executing" in prompt
        assert "lang=python" in prompt

    def test_to_prompt_with_drift_warnings(self):
        """to_prompt 包含偏离警告"""
        from pycoder.server.services.task_tracker import TaskAnchor

        anchor = TaskAnchor(
            goal="创建认证系统",
            parameters={},
            current_phase="executing",
            completed_steps=[],
            next_step="",
            last_decision="",
            drift_warnings=["用户偏离了原定目标"],
        )
        prompt = anchor.to_prompt()
        assert "⚠️ 偏离提醒" in prompt
        assert "偏离了原定目标" in prompt

    def test_to_prompt_truncation(self):
        """to_prompt 超长文本截断"""
        from pycoder.server.services.task_tracker import TaskAnchor

        anchor = TaskAnchor(
            goal="x" * 500,
            parameters={f"k{i}": f"v{i}" for i in range(20)},
            current_phase="executing",
            completed_steps=["step" + str(i) for i in range(20)],
            next_step="y" * 400,
            last_decision="z" * 300,
            drift_warnings=["w" * 200 for _ in range(5)],
        )
        prompt = anchor.to_prompt(max_length=200)
        assert len(prompt) <= 200


class TestSubTask:
    """SubTask 数据类测试"""

    def test_create_subtask(self):
        """创建 SubTask"""
        from pycoder.server.services.task_tracker import SubTask

        st = SubTask(id="st-01", description="实现 API 端点")
        assert st.id == "st-01"
        assert st.description == "实现 API 端点"
        assert st.status == "pending"
        assert st.priority == 5
        assert st.retries == 0
        assert st.max_retries == 2

    def test_create_subtask_with_priority(self):
        """SubTask 自定义优先级"""
        from pycoder.server.services.task_tracker import SubTask

        st = SubTask(id="st-02", description="紧急修复", priority=1)
        assert st.priority == 1


class TestTaskTracker:
    """TaskTracker 类测试"""

    @pytest.fixture
    def tracker(self):
        """创建 TaskTracker 实例"""
        from pycoder.server.services.task_tracker import TaskTracker

        return TaskTracker()

    def test_init_state(self, tracker):
        """初始状态检查"""
        from pycoder.server.services.task_tracker import TaskPhase

        assert tracker._goal == ""
        assert tracker._phase == TaskPhase.IDLE
        assert tracker._subtasks == []
        assert tracker._completed_steps == []
        assert tracker.is_active is False

    def test_initialize_creates_task(self, tracker):
        """initialize 创建新任务"""
        from pycoder.server.services.task_tracker import TaskPhase

        anchor = tracker.initialize("创建认证系统", {"lang": "python"})
        assert tracker._goal == "创建认证系统"
        assert tracker._parameters == {"lang": "python"}
        assert tracker._phase == TaskPhase.INIT
        assert tracker.is_active is True
        assert anchor is not None
        assert anchor.goal == "创建认证系统"

    def test_initialize_returns_anchor(self, tracker):
        """initialize 返回 TaskAnchor"""
        anchor = tracker.initialize("测试任务")
        from pycoder.server.services.task_tracker import TaskAnchor

        assert isinstance(anchor, TaskAnchor)

    def test_initialize_generates_task_id(self, tracker):
        """initialize 生成任务 ID"""
        tracker.initialize("测试任务")
        assert len(tracker._task_id) > 0
        assert len(tracker._task_id) == 12

    def test_set_phase(self, tracker):
        """set_phase 手动设置阶段"""
        from pycoder.server.services.task_tracker import TaskPhase

        tracker.initialize("任务")
        tracker.set_phase(TaskPhase.EXECUTING)
        assert tracker._phase == TaskPhase.EXECUTING

    def test_set_next_step(self, tracker):
        """set_next_step 设置下一步"""
        tracker.initialize("任务")
        tracker.set_next_step("编写测试")
        assert tracker._next_step == "编写测试"

    def test_record_decision(self, tracker):
        """record_decision 记录决策"""
        tracker.initialize("任务")
        tracker.record_decision("使用 FastAPI")
        assert tracker._last_decision == "使用 FastAPI"
        assert len(tracker._decisions) == 1

    def test_add_subtask(self, tracker):
        """add_subtask 添加子任务"""
        tracker.initialize("主任务")
        st = tracker.add_subtask("子任务1", priority=3)
        assert st.id == "st-01"
        assert st.description == "子任务1"
        assert st.priority == 3
        assert len(tracker._subtasks) == 1

    def test_add_multiple_subtasks(self, tracker):
        """添加多个子任务"""
        tracker.initialize("主任务")
        st1 = tracker.add_subtask("子任务1")
        st2 = tracker.add_subtask("子任务2")
        assert st1.id == "st-01"
        assert st2.id == "st-02"
        assert len(tracker._subtasks) == 2

    def test_start_subtask(self, tracker):
        """start_subtask 启动子任务"""
        tracker.initialize("主任务")
        st = tracker.add_subtask("子任务1")
        tracker.start_subtask(st.id)
        assert st.status == "active"
        assert st.started_at > 0

    def test_start_subtask_not_found(self, tracker):
        """start_subtask 不存在的子任务不抛异常"""
        tracker.initialize("主任务")
        tracker.start_subtask("nonexistent")
        # 不抛异常即通过

    def test_complete_subtask_success(self, tracker):
        """complete_subtask 成功完成子任务"""
        tracker.initialize("主任务")
        st = tracker.add_subtask("子任务1")
        tracker.start_subtask(st.id)
        tracker.complete_subtask(st.id, success=True)
        assert st.status == "done"
        assert len(tracker._completed_steps) == 1

    def test_complete_subtask_failure(self, tracker):
        """complete_subtask 子任务失败（达到最大重试次数）"""
        tracker.initialize("主任务")
        st = tracker.add_subtask("子任务1")
        st.max_retries = 0  # 不允许重试，直接标记失败
        tracker.start_subtask(st.id)
        tracker.complete_subtask(st.id, success=False)
        assert st.status == "failed"

    def test_complete_subtask_retry(self, tracker):
        """complete_subtask 失败后重试"""
        tracker.initialize("主任务")
        st = tracker.add_subtask("子任务1")
        st.retries = 0
        st.max_retries = 3
        tracker.complete_subtask(st.id, success=False)
        assert st.retries == 1
        assert st.status == "pending"

    def test_complete_subtask_max_retries(self, tracker):
        """complete_subtask 达到最大重试次数"""
        tracker.initialize("主任务")
        st = tracker.add_subtask("子任务1")
        st.retries = 2
        st.max_retries = 2
        tracker.complete_subtask(st.id, success=False)
        assert st.status == "failed"

    def test_progress_percent_without_subtasks(self, tracker):
        """无子任务时基于阶段估算进度"""
        from pycoder.server.services.task_tracker import TaskPhase

        tracker.initialize("任务")
        tracker.set_phase(TaskPhase.EXECUTING)
        assert tracker.progress_percent == 60

    def test_progress_percent_with_subtasks(self, tracker):
        """有子任务时按完成比例计算进度"""
        tracker.initialize("任务")
        tracker.add_subtask("子1")
        tracker.add_subtask("子2")
        tracker.add_subtask("子3")
        tracker._subtasks[0].status = "done"
        tracker._subtasks[1].status = "done"
        # 2/3 = 66%
        assert tracker.progress_percent == 66

    def test_progress_percent_all_done(self, tracker):
        """全部子任务完成进度 100%"""
        tracker.initialize("任务")
        tracker.add_subtask("子1")
        tracker._subtasks[0].status = "done"
        assert tracker.progress_percent == 100

    def test_elapsed_seconds_initial(self, tracker):
        """初始时 elapsed_seconds 为 0"""
        assert tracker.elapsed_seconds == 0

    def test_elapsed_seconds_after_init(self, tracker):
        """初始化后 elapsed_seconds 大于 0"""
        tracker.initialize("任务")
        assert tracker.elapsed_seconds >= 0

    def test_is_active_phases(self, tracker):
        """各阶段活跃状态"""
        from pycoder.server.services.task_tracker import TaskPhase

        tracker.initialize("任务")
        assert tracker.is_active is True

        tracker.set_phase(TaskPhase.DONE)
        assert tracker.is_active is False

        tracker.set_phase(TaskPhase.FAILED)
        assert tracker.is_active is False

    def test_add_drift_warning(self, tracker):
        """add_drift_warning 添加偏离警告"""
        tracker.initialize("任务")
        tracker.add_drift_warning("偏离目标")
        assert len(tracker._drift_warnings) == 1
        assert "偏离目标" in tracker._drift_warnings[0]

    def test_add_drift_warning_max_limit(self, tracker):
        """add_drift_warning 最多保留 10 条"""
        tracker.initialize("任务")
        for i in range(15):
            tracker.add_drift_warning(f"警告{i}")
        assert len(tracker._drift_warnings) == 10

    def test_mark_complete_success(self, tracker):
        """mark_complete 成功标记"""
        from pycoder.server.services.task_tracker import TaskPhase

        tracker.initialize("任务")
        anchor = tracker.mark_complete(success=True)
        assert tracker._phase == TaskPhase.DONE
        assert anchor is not None

    def test_mark_complete_failure(self, tracker):
        """mark_complete 失败标记"""
        from pycoder.server.services.task_tracker import TaskPhase

        tracker.initialize("任务")
        anchor = tracker.mark_complete(success=False)
        assert tracker._phase == TaskPhase.FAILED

    def test_get_anchor_returns_task_anchor(self, tracker):
        """get_anchor 返回 TaskAnchor"""
        tracker.initialize("任务")
        from pycoder.server.services.task_tracker import TaskAnchor

        anchor = tracker.get_anchor()
        assert isinstance(anchor, TaskAnchor)

    def test_get_status_returns_dict(self, tracker):
        """get_status 返回字典"""
        tracker.initialize("测试任务")
        status = tracker.get_status()
        assert isinstance(status, dict)
        assert status["task_id"] == tracker._task_id
        assert status["goal"] == "测试任务"
        assert "phase" in status
        assert "progress_percent" in status
        assert "elapsed_seconds" in status
        assert "subtasks" in status


# ═══════════════════════════════════════════════════════════════
# 10. services/task_decomposer.py 测试
# ═══════════════════════════════════════════════════════════════


class TestParseDecompositionJson:
    """_parse_decomposition_json 函数测试"""

    def test_valid_json_parses_tasks(self):
        """有效 JSON 正确解析"""
        from pycoder.server.services.task_decomposer import _parse_decomposition_json

        valid_json = json.dumps(
            {
                "project_name": "test",
                "description": "desc",
                "tech_stack_required": ["python"],
                "tasks": [
                    {
                        "title": "架构设计",
                        "description": "设计架构",
                        "assigned_role": "architect",
                        "depends_on": [],
                        "deliverables": ["docs/arch.md"],
                    },
                    {
                        "title": "开发",
                        "description": "编码",
                        "assigned_role": "developer",
                        "depends_on": ["架构设计"],
                        "deliverables": ["app.py"],
                    },
                ],
            }
        )
        tasks = _parse_decomposition_json(valid_json)
        assert len(tasks) == 2
        assert tasks[0].title == "架构设计"
        assert tasks[0].assigned_role == "architect"
        assert tasks[1].title == "开发"
        assert tasks[1].assigned_role == "developer"

    def test_invalid_json_returns_empty(self):
        """无效 JSON 返回空列表"""
        from pycoder.server.services.task_decomposer import _parse_decomposition_json

        tasks = _parse_decomposition_json("这不是 JSON")
        assert tasks == []

    def test_empty_json_returns_empty(self):
        """空 JSON 返回空列表"""
        from pycoder.server.services.task_decomposer import _parse_decomposition_json

        tasks = _parse_decomposition_json("{}")
        assert tasks == []

    def test_json_with_markdown_code_block(self):
        """清理 markdown 代码块后解析"""
        from pycoder.server.services.task_decomposer import _parse_decomposition_json

        valid_json = json.dumps(
            {
                "tasks": [
                    {"title": "任务1", "description": "desc", "assigned_role": "developer",
                     "depends_on": [], "deliverables": []}
                ]
            }
        )
        wrapped = f"```json\n{valid_json}\n```"
        tasks = _parse_decomposition_json(wrapped)
        assert len(tasks) == 1
        assert tasks[0].title == "任务1"


class TestFallbackDecomposition:
    """_fallback_decomposition 函数测试"""

    def test_web_project_decomposition(self):
        """Web 项目分解包含架构/后端/前端/QA/DevOps"""
        from pycoder.server.services.task_decomposer import _fallback_decomposition

        tasks = _fallback_decomposition("创建一个 Web 网站")
        titles = [t.title for t in tasks]
        assert "系统架构设计" in titles
        assert "后端开发" in titles
        assert "前端开发" in titles
        assert "编写测试用例" in titles
        assert "Docker 化与部署配置" in titles

    def test_python_script_decomposition(self):
        """Python 脚本分解"""
        from pycoder.server.services.task_decomposer import _fallback_decomposition

        tasks = _fallback_decomposition("写一个 Python 脚本")
        titles = [t.title for t in tasks]
        assert "Python 模块开发" in titles

    def test_db_project_decomposition(self):
        """数据库项目分解"""
        from pycoder.server.services.task_decomposer import _fallback_decomposition

        tasks = _fallback_decomposition("创建一个数据库系统")
        titles = [t.title for t in tasks]
        assert "数据库设计与实现" in titles

    def test_generic_project_decomposition(self):
        """通用项目分解"""
        from pycoder.server.services.task_decomposer import _fallback_decomposition

        tasks = _fallback_decomposition("随便做点什么")
        titles = [t.title for t in tasks]
        assert "代码开发" in titles

    def test_all_tasks_have_ids(self):
        """所有任务都有 ID"""
        from pycoder.server.services.task_decomposer import _fallback_decomposition

        tasks = _fallback_decomposition("创建 Web 应用")
        for t in tasks:
            assert t.id is not None
            assert len(t.id) > 0

    def test_task_dependencies_use_ids(self):
        """任务依赖使用 ID 而非标题"""
        from pycoder.server.services.task_decomposer import _fallback_decomposition

        tasks = _fallback_decomposition("创建 Web 应用")
        dev_tasks = [t for t in tasks if t.assigned_role == "developer"]
        for t in dev_tasks:
            if t.depends_on:
                for dep_id in t.depends_on:
                    assert any(ot.id == dep_id for ot in tasks)


class TestTaskNode:
    """TaskNode 数据类测试"""

    def test_create_node(self):
        """创建 TaskNode"""
        from pycoder.server.services.agent_definitions import create_task
        from pycoder.server.services.task_decomposer import TaskNode

        task = create_task(title="测试任务", description="desc", assigned_role="developer")
        node = TaskNode(task=task)
        assert node.task.title == "测试任务"
        assert node.level == 0
        assert node.children == []

    def test_to_dict(self):
        """to_dict 返回字典"""
        from pycoder.server.services.agent_definitions import create_task
        from pycoder.server.services.task_decomposer import TaskNode

        task = create_task(title="测试任务", description="desc", assigned_role="developer")
        node = TaskNode(task=task, level=2, children=["child1"])
        d = node.to_dict()
        assert d["task_id"] == task.id
        assert d["title"] == "测试任务"
        assert d["level"] == 2
        assert d["children"] == ["child1"]


class TestTaskDAG:
    """TaskDAG 数据类测试"""

    def test_create_empty_dag(self):
        """创建空 DAG"""
        from pycoder.server.services.task_decomposer import TaskDAG

        dag = TaskDAG()
        assert dag.nodes == {}
        assert dag.edges == []
        assert dag.parallel_groups == []
        assert dag.total_levels == 0

    def test_max_parallel_count_empty(self):
        """空 DAG 最大并行数为 1"""
        from pycoder.server.services.task_decomposer import TaskDAG

        dag = TaskDAG()
        assert dag.max_parallel_count() == 1

    def test_to_dict(self):
        """to_dict 返回字典"""
        from pycoder.server.services.task_decomposer import TaskDAG

        dag = TaskDAG()
        d = dag.to_dict()
        assert d["nodes"] == {}
        assert d["edges"] == []
        assert d["parallel_groups"] == []
        assert d["total_levels"] == 0


class TestBuildTaskDAG:
    """build_task_dag 函数测试"""

    def test_single_task_dag(self):
        """单个任务构建 DAG"""
        from pycoder.server.services.agent_definitions import create_task
        from pycoder.server.services.task_decomposer import build_task_dag

        task = create_task(title="任务1", description="desc", assigned_role="developer")
        dag = build_task_dag([task])
        assert len(dag.nodes) == 1
        assert dag.total_levels == 1
        assert len(dag.parallel_groups) == 1
        assert len(dag.parallel_groups[0]) == 1

    def test_sequential_tasks_dag(self):
        """顺序任务构建 DAG"""
        from pycoder.server.services.agent_definitions import create_task
        from pycoder.server.services.task_decomposer import build_task_dag

        t1 = create_task(title="架构", description="desc", assigned_role="architect")
        t2 = create_task(
            title="开发", description="desc", assigned_role="developer", depends_on=[t1.id]
        )
        t3 = create_task(title="测试", description="desc", assigned_role="qa", depends_on=[t2.id])
        dag = build_task_dag([t1, t2, t3])
        assert dag.total_levels == 3
        assert len(dag.parallel_groups) == 3

    def test_parallel_tasks_dag(self):
        """并行任务构建 DAG"""
        from pycoder.server.services.agent_definitions import create_task
        from pycoder.server.services.task_decomposer import build_task_dag

        t1 = create_task(title="架构", description="desc", assigned_role="architect")
        t2 = create_task(title="后端", description="desc", assigned_role="developer", depends_on=[t1.id])
        t3 = create_task(title="前端", description="desc", assigned_role="developer", depends_on=[t1.id])
        dag = build_task_dag([t1, t2, t3])
        assert dag.total_levels == 2
        # 第二层有两个并行任务
        assert len(dag.parallel_groups[1]) == 2
        assert dag.max_parallel_count() == 2

    def test_dag_edges_recorded(self):
        """DAG 依赖边正确记录"""
        from pycoder.server.services.agent_definitions import create_task
        from pycoder.server.services.task_decomposer import build_task_dag

        t1 = create_task(title="架构", description="desc", assigned_role="architect")
        t2 = create_task(title="开发", description="desc", assigned_role="developer", depends_on=[t1.id])
        dag = build_task_dag([t1, t2])
        assert len(dag.edges) == 1
        assert dag.edges[0] == (t1.id, t2.id)


# ═══════════════════════════════════════════════════════════════
# 11. services/context_orchestrator.py 测试
# ═══════════════════════════════════════════════════════════════


class TestContextOrchestrator:
    """ContextOrchestrator 类测试"""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """每个测试前重置全局单例"""
        from pycoder.server.services.context_orchestrator import reset_orchestrator

        reset_orchestrator()
        yield
        reset_orchestrator()

    def test_init_defaults(self):
        """初始化默认值"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(project="test")
        assert orch.project == "test"
        assert orch.tracker is not None
        assert orch.context_mgr is not None
        assert orch.drift is not None
        assert orch.memory is not None
        assert orch.metrics is not None

    def test_get_orchestrator_singleton(self):
        """get_orchestrator 返回同一实例"""
        from pycoder.server.services.context_orchestrator import (
            get_orchestrator,
            reset_orchestrator,
        )

        reset_orchestrator()
        o1 = get_orchestrator("proj1")
        o2 = get_orchestrator("proj2")
        assert o1 is o2

    def test_reset_orchestrator(self):
        """reset_orchestrator 重置单例"""
        from pycoder.server.services.context_orchestrator import (
            get_orchestrator,
            reset_orchestrator,
        )

        o1 = get_orchestrator("proj1")
        reset_orchestrator()
        o2 = get_orchestrator("proj2")
        assert o1 is not o2

    def test_start_task_initializes_tracker(self):
        """start_task 初始化任务追踪器"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(project="test")
        result = orch.start_task("创建认证系统")
        assert "anchor" in result
        assert "memory_context" in result
        assert "status" in result
        assert orch.tracker.is_active is True

    def test_get_anchor_returns_string(self):
        """get_anchor 返回字符串"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(project="test")
        orch.start_task("创建认证系统")
        anchor = orch.get_anchor()
        assert isinstance(anchor, str)
        assert len(anchor) > 0

    @pytest.mark.asyncio
    async def test_process_user_message(self):
        """process_user_message 处理用户消息"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(project="test")
        orch.start_task("创建认证系统")
        result = await orch.process_user_message("我需要 JWT 认证")
        assert "anchor" in result
        assert "memory_context" in result
        assert "window_summary" in result
        assert "drift_report" in result
        assert "status" in result
        assert "events" in result

    @pytest.mark.asyncio
    async def test_process_user_message_auto_initializes(self):
        """无活跃任务时自动初始化"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(project="test")
        result = await orch.process_user_message("这是一个较长的用户消息，超过十个字符")
        assert orch.tracker.is_active is True

    def test_add_assistant_response(self):
        """add_assistant_response 记录 AI 响应"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(project="test")
        orch.start_task("测试")
        # Mock _DECISION_KEYWORDS 避免依赖 DriftDetector 内部实现
        orch.drift._DECISION_KEYWORDS = MagicMock(search=MagicMock(return_value=False))
        orch.add_assistant_response("AI 的回复内容")
        # 不抛异常即通过

    def test_record_anchor_feedback(self):
        """record_anchor_feedback 记录反馈"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(project="test")
        orch.start_task("测试")
        orch.record_anchor_feedback(True)
        orch.record_anchor_feedback(False)
        # 不抛异常即通过

    def test_collect_user_feedback(self):
        """collect_user_feedback 收集用户反馈"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(project="test")
        orch.collect_user_feedback(5, "很好")
        # 不抛异常即通过

    def test_get_context_health(self):
        """get_context_health 返回字典"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(project="test")
        orch.start_task("测试")
        health = orch.get_context_health()
        assert isinstance(health, dict)
        assert "continuity_score" in health
        assert "anchor_hit_rate" in health
        assert "drift_rate" in health
        assert "task_status" in health

    @pytest.mark.asyncio
    async def test_end_session(self):
        """end_session 返回报告"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(project="test")
        orch.start_task("测试")
        report = await orch.end_session()
        assert isinstance(report, dict)
        assert "metrics" in report
        assert "stats" in report
        assert "summary" in report

    def test_set_ws_callback(self):
        """set_ws_callback 注册回调"""
        from pycoder.server.services.context_orchestrator import ContextOrchestrator

        orch = ContextOrchestrator(project="test")

        async def dummy_callback(event):
            pass

        orch.set_ws_callback(dummy_callback)
        assert orch._ws_callback is not None


# ═══════════════════════════════════════════════════════════════
# 12. services/source_tracer.py 测试
# ═══════════════════════════════════════════════════════════════


class TestClaim:
    """Claim 数据类测试"""

    def test_create_claim(self):
        """创建 Claim"""
        from pycoder.server.services.source_tracer import Claim

        c = Claim(
            text="test.py",
            category="file",
            verified=True,
            confidence="high",
            source="用户输入",
            evidence="文件存在",
        )
        assert c.text == "test.py"
        assert c.category == "file"
        assert c.verified is True
        assert c.confidence == "high"

    def test_to_dict(self):
        """to_dict 返回字典"""
        from pycoder.server.services.source_tracer import Claim

        c = Claim(text="test.py", category="file", verified=None, confidence="medium")
        d = c.to_dict()
        assert d["text"] == "test.py"
        assert d["category"] == "file"
        assert d["verified"] is None


class TestTraceResult:
    """TraceResult 数据类测试"""

    def test_create_empty(self):
        """创建空 TraceResult"""
        from pycoder.server.services.source_tracer import TraceResult

        tr = TraceResult()
        assert tr.claims == []
        assert tr.unverified_count == 0
        assert tr.verified_count == 0
        assert tr.failed_count == 0
        assert tr.risk_score == 0.0

    def test_to_dict(self):
        """to_dict 返回字典"""
        from pycoder.server.services.source_tracer import TraceResult, Claim

        tr = TraceResult(
            claims=[Claim(text="test", category="file", verified=True, confidence="high")],
            verified_count=1,
            risk_score=10.0,
        )
        d = tr.to_dict()
        assert d["verified_count"] == 1
        assert d["risk_score"] == 10.0
        assert len(d["claims"]) == 1


class TestSourceTracer:
    """SourceTracer 类测试"""

    @pytest.fixture
    def tracer(self):
        """创建 SourceTracer 实例"""
        from pycoder.server.services.source_tracer import SourceTracer

        return SourceTracer()

    def test_trace_empty_text(self, tracer):
        """空文本追踪返回空结果"""
        result = tracer.trace("")
        assert len(result.claims) == 0
        assert result.risk_score == 0.0

    def test_trace_file_references(self, tracer):
        """追踪文件引用"""
        result = tracer.trace("在 src/main.py 中修改代码")
        file_claims = [c for c in result.claims if c.category == "file"]
        assert len(file_claims) >= 1

    def test_trace_import_statements(self, tracer):
        """追踪 import 声明"""
        result = tracer.trace("使用 fastapi 和 pydantic 开发")
        import_claims = [c for c in result.claims if c.category == "import"]
        assert len(import_claims) >= 1

    def test_trace_api_routes(self, tracer):
        """追踪 API 路由"""
        result = tracer.trace("在 /api/ /users 接口中添加认证")
        api_claims = [c for c in result.claims if c.category == "api"]
        assert len(api_claims) >= 1

    def test_trace_dependencies(self, tracer):
        """追踪依赖声明"""
        result = tracer.trace("使用 fastapi>=0.100.0 版本")
        dep_claims = [c for c in result.claims if c.category == "dependency"]
        assert len(dep_claims) >= 1

    def test_trace_numbers(self, tracer):
        """追踪数字/端口声明"""
        result = tracer.trace("在 8423 端口")
        num_claims = [c for c in result.claims if c.category == "number"]
        assert len(num_claims) >= 1

    def test_trace_risk_score_increases_with_claims(self, tracer):
        """声明越多风险分越高"""
        result = tracer.trace("在 src/main.py 使用 fastapi 在 /api 端口 8423")
        assert result.risk_score > 0

    def test_filter_common_import_words(self, tracer):
        """过滤常见非模块词"""
        result = tracer.trace("使用 pip 安装 python 包")
        common_words = {"pip", "python", "npm", "node", "git"}
        import_claims = [c for c in result.claims if c.category == "import"]
        for claim in import_claims:
            assert claim.text.lower() not in common_words

    def test_tag_unverifiable(self, tracer):
        """tag_unverifiable 标记无来源声明"""
        from pycoder.server.services.source_tracer import CROSS_VERIFY_CATEGORIES

        result = tracer.trace("在 /api/test 使用 fastapi>=1.0.0 在 3000 端口")
        tagged = tracer.tag_unverifiable(result)
        any_unverifiable = any(c.confidence == "unverifiable" for c in tagged.claims)
        # 至少有一个未验证的声明
        assert any_unverifiable or tagged.unverified_count > 0

    def test_get_source_tracer_singleton(self):
        """get_source_tracer 返回同一实例"""
        from pycoder.server.services.source_tracer import get_source_tracer

        t1 = get_source_tracer()
        t2 = get_source_tracer()
        assert t1 is t2


class TestFactChecker:
    """FactChecker 类测试"""

    @pytest.fixture
    def checker(self, tmp_path: Path):
        """创建 FactChecker 实例"""
        from pycoder.server.services.source_tracer import FactChecker

        return FactChecker(workspace=tmp_path)

    def test_init_with_workspace(self, tmp_path: Path):
        """带工作区初始化"""
        from pycoder.server.services.source_tracer import FactChecker

        checker = FactChecker(workspace=tmp_path)
        assert checker._workspace == tmp_path

    @pytest.mark.asyncio
    async def test_verify_claim_unknown_category(self, checker):
        """验证未知类别声明"""
        from pycoder.server.services.source_tracer import Claim

        claim = Claim(text="test", category="unknown", verified=None, confidence="low")
        result = await checker.verify_claim(claim)
        assert result.confidence == "unverifiable"

    @pytest.mark.asyncio
    async def test_verify_file_exists(self, checker, tmp_path: Path):
        """验证文件存在"""
        from pycoder.server.services.source_tracer import Claim

        test_file = tmp_path / "test.py"
        test_file.write_text("# test")
        claim = Claim(text="test.py", category="file", verified=None, confidence="medium")
        result = await checker.verify_claim(claim)
        assert result.verified is True
        assert result.confidence == "high"

    @pytest.mark.asyncio
    async def test_verify_file_not_exists(self, checker):
        """验证文件不存在"""
        from pycoder.server.services.source_tracer import Claim

        claim = Claim(text="nonexistent.py", category="file", verified=None, confidence="medium")
        result = await checker.verify_claim(claim)
        assert result.verified is False

    @pytest.mark.asyncio
    async def test_verify_import_local(self, checker, tmp_path: Path):
        """验证本地模块导入"""
        from pycoder.server.services.source_tracer import Claim

        (tmp_path / "mymodule.py").write_text("# test")
        claim = Claim(text="mymodule", category="import", verified=None, confidence="medium")
        result = await checker.verify_claim(claim)
        assert result.verified is True

    @pytest.mark.asyncio
    async def test_verify_import_builtin(self, checker):
        """验证内置模块导入"""
        from pycoder.server.services.source_tracer import Claim

        claim = Claim(text="json", category="import", verified=None, confidence="medium")
        result = await checker.verify_claim(claim)
        # json 是内置模块，应该验证通过
        assert result.verified is True

    @pytest.mark.asyncio
    async def test_verify_import_not_found(self, checker):
        """验证不存在的模块导入"""
        from pycoder.server.services.source_tracer import Claim

        claim = Claim(
            text="nonexistent_module_xyz", category="import", verified=None, confidence="medium"
        )
        result = await checker.verify_claim(claim)
        assert result.verified is False

    @pytest.mark.asyncio
    async def test_verify_dependency_in_requirements(self, checker, tmp_path: Path):
        """验证依赖在 requirements.txt 中"""
        from pycoder.server.services.source_tracer import Claim

        (tmp_path / "requirements.txt").write_text("fastapi>=0.100.0\npydantic==2.0.0\n")
        claim = Claim(text="fastapi>=0.100.0", category="dependency", verified=None, confidence="medium")
        result = await checker.verify_claim(claim)
        assert result.verified is True

    @pytest.mark.asyncio
    async def test_verify_api_route(self, checker, tmp_path: Path):
        """验证 API 路由"""
        from pycoder.server.services.source_tracer import Claim

        pycoder_dir = tmp_path / "pycoder"
        pycoder_dir.mkdir()
        (pycoder_dir / "app.py").write_text("@router.get('/api/users')\n")
        claim = Claim(text="/api/users", category="api", verified=None, confidence="low")
        result = await checker.verify_claim(claim)
        assert result.verified is True

    @pytest.mark.asyncio
    async def test_verify_claims_batch(self, checker):
        """批量验证声明"""
        from pycoder.server.services.source_tracer import Claim

        claims = [
            Claim(text="test.py", category="file", verified=None, confidence="medium"),
            Claim(text="json", category="import", verified=None, confidence="medium"),
        ]
        results = await checker.verify_claims(claims)
        assert len(results) == 2
        # json 应该验证通过
        assert results[1].verified is True

    @pytest.mark.asyncio
    async def test_verify_trace(self, checker):
        """验证 TraceResult"""
        from pycoder.server.services.source_tracer import Claim, TraceResult

        claims = [Claim(text="json", category="import", verified=None, confidence="medium")]
        trace = TraceResult(claims=claims)
        result = await checker.verify_trace(trace)
        assert result.verified_count >= 0
        assert isinstance(result.risk_score, (int, float))

    def test_get_fact_checker_singleton(self, tmp_path: Path):
        """get_fact_checker 返回实例"""
        from pycoder.server.services.source_tracer import get_fact_checker

        checker = get_fact_checker(workspace=tmp_path)
        assert checker is not None


class TestCrossValidator:
    """CrossValidator 类测试"""

    def test_cross_verify_low_confidence_flags(self):
        """低置信度关键声明被标记"""
        from pycoder.server.services.source_tracer import Claim, CrossValidator

        validator = CrossValidator()
        claims = [
            Claim(
                text="fastapi>=0.100.0",
                category="dependency",
                verified=True,
                confidence="low",
            )
        ]
        result = validator.cross_verify(claims)
        assert "交叉确认" in result[0].reason

    def test_cross_verify_high_confidence_not_flagged(self):
        """高置信度不被标记"""
        from pycoder.server.services.source_tracer import Claim, CrossValidator

        validator = CrossValidator()
        claims = [
            Claim(
                text="fastapi",
                category="dependency",
                verified=True,
                confidence="high",
            )
        ]
        result = validator.cross_verify(claims)
        assert "多源确认" not in result[0].reason

    def test_cross_verify_non_critical_not_flagged(self):
        """非关键类别不被标记"""
        from pycoder.server.services.source_tracer import Claim, CrossValidator

        validator = CrossValidator()
        claims = [
            Claim(
                text="test.py",
                category="file",
                verified=True,
                confidence="low",
            )
        ]
        result = validator.cross_verify(claims)
        assert "多源确认" not in result[0].reason

    def test_get_cross_validator_singleton(self):
        """get_cross_validator 返回同一实例"""
        from pycoder.server.services.source_tracer import get_cross_validator

        v1 = get_cross_validator()
        v2 = get_cross_validator()
        assert v1 is v2


# ═══════════════════════════════════════════════════════════════
# 13. services/patch_aggregator.py 测试
# ═══════════════════════════════════════════════════════════════


class TestAggregatedDefect:
    """AggregatedDefect 数据类测试"""

    def test_create_defect(self):
        """创建缺陷条目"""
        from pycoder.server.services.patch_aggregator import AggregatedDefect

        defect = AggregatedDefect(
            file_path="src/main.py",
            line_range=(10, 15),
            severity="l1_blocking",
            source="quality_guard",
            description="空指针异常",
            fix_suggestion="添加 null 检查",
        )
        assert defect.file_path == "src/main.py"
        assert defect.line_range == (10, 15)
        assert defect.severity == "l1_blocking"
        assert defect.source == "quality_guard"

    def test_create_defect_defaults(self):
        """缺陷默认值"""
        from pycoder.server.services.patch_aggregator import AggregatedDefect

        defect = AggregatedDefect(file_path="test.py")
        assert defect.line_range is None
        assert defect.severity == "l2_major"
        assert defect.source == "unknown"


class TestPatchEntry:
    """PatchEntry 数据类测试"""

    def test_create_patch_entry(self):
        """创建补丁条目"""
        from pycoder.server.services.patch_aggregator import PatchEntry

        entry = PatchEntry(
            file_path="src/main.py",
            search="old code",
            replace="new code",
            defect_refs=["def1", "def2"],
            status="pending",
        )
        assert entry.file_path == "src/main.py"
        assert entry.search == "old code"
        assert entry.replace == "new code"
        assert entry.defect_refs == ["def1", "def2"]
        assert entry.status == "pending"


class TestPatchReport:
    """PatchReport 数据类测试"""

    def test_create_empty_report(self):
        """创建空报告"""
        from pycoder.server.services.patch_aggregator import PatchReport

        report = PatchReport()
        assert report.total_defects == 0
        assert report.l1_count == 0
        assert report.l2_count == 0
        assert report.l3_count == 0
        assert report.patches == []
        assert report.has_blocking is False


class TestPatchAggregator:
    """PatchAggregator 类测试"""

    def test_aggregate_empty(self):
        """空输入聚合"""
        from pycoder.server.services.patch_aggregator import PatchAggregator

        agg = PatchAggregator()
        report = agg.aggregate()
        assert report.total_defects == 0
        assert report.has_blocking is False

    def test_aggregate_quality_report(self):
        """质量报告聚合"""
        from pycoder.server.services.patch_aggregator import PatchAggregator

        agg = PatchAggregator()
        quality_report = {
            "issues": [
                {
                    "file": "src/main.py",
                    "line": 10,
                    "severity": "error",
                    "message": "空指针异常",
                    "suggestion": "添加 null 检查",
                },
                {
                    "file": "src/utils.py",
                    "line": 20,
                    "severity": "warning",
                    "message": "未使用的变量",
                    "suggestion": "删除变量",
                },
            ]
        }
        report = agg.aggregate(quality_report=quality_report)
        assert report.total_defects == 2
        assert report.l1_count == 1
        assert report.l2_count == 1
        assert report.has_blocking is True

    def test_aggregate_test_result(self):
        """测试结果聚合"""
        from pycoder.server.services.patch_aggregator import PatchAggregator

        agg = PatchAggregator()
        test_result = {
            "failures": [
                {"file": "test_main.py", "message": "AssertionError: 预期 1, 实际 2"},
            ]
        }
        report = agg.aggregate(test_result=test_result)
        assert report.total_defects == 1
        assert report.l2_count == 1

    def test_aggregate_acceptance_result(self):
        """验收结果聚合"""
        from pycoder.server.services.patch_aggregator import PatchAggregator

        agg = PatchAggregator()
        acceptance_result = {
            "passed": False,
            "report": {
                "items": [
                    {
                        "file": "src/main.py",
                        "passed": False,
                        "reason": "功能不完整",
                        "name": "认证功能",
                    }
                ]
            },
        }
        report = agg.aggregate(acceptance_result=acceptance_result)
        assert report.total_defects == 1

    def test_aggregate_multiple_sources(self):
        """多源聚合"""
        from pycoder.server.services.patch_aggregator import PatchAggregator

        agg = PatchAggregator()
        quality = {"issues": [{"file": "a.py", "severity": "error", "message": "E1"}]}
        test = {"failures": [{"file": "b.py", "message": "T1"}]}
        acceptance = {
            "passed": False,
            "report": {"items": [{"file": "c.py", "passed": False, "reason": "A1"}]},
        }
        report = agg.aggregate(quality, test, acceptance)
        assert report.total_defects == 3
        assert "src" in report.summary.lower() or "缺陷" in report.summary

    def test_generate_patches(self):
        """生成补丁"""
        from pycoder.server.services.patch_aggregator import PatchAggregator, PatchReport, AggregatedDefect

        agg = PatchAggregator()
        report = PatchReport()
        report.grouped_by_file = {
            "src/main.py": [
                AggregatedDefect(
                    file_path="src/main.py",
                    severity="l1_blocking",
                    source="quality_guard",
                    description="空指针异常",
                )
            ]
        }
        report.l1_count = 1
        patches = agg.generate_patches(report)
        assert len(patches) >= 1
        assert patches[0].file_path == "src/main.py"


class TestAggregateDefects:
    """aggregate_defects 便捷函数测试"""

    def test_returns_patch_report(self):
        """返回 PatchReport 实例"""
        from pycoder.server.services.patch_aggregator import PatchReport, aggregate_defects

        report = aggregate_defects()
        assert isinstance(report, PatchReport)

    def test_with_quality_report(self):
        """带质量报告"""
        from pycoder.server.services.patch_aggregator import aggregate_defects

        quality = {"issues": [{"file": "a.py", "severity": "error", "message": "问题"}]}
        report = aggregate_defects(quality_report=quality)
        assert report.total_defects == 1


# ═══════════════════════════════════════════════════════════════
# 14. recommendation/engine.py 测试
# ═══════════════════════════════════════════════════════════════


class TestRecommendationEngine:
    """RecommendationEngine 类测试"""

    @pytest.fixture
    def mock_session(self):
        """创建 mock 数据库会话"""
        session = MagicMock()
        session.query.return_value = session
        session.filter.return_value = session
        session.order_by.return_value = session
        session.limit.return_value = session
        session.all.return_value = []
        session.first.return_value = None
        return session

    def test_init_with_session(self, mock_session):
        """使用外部会话初始化"""
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(db_session=mock_session)
        assert engine.db is mock_session

    def test_init_with_none_creates_own_db(self):
        """db_session=None 时自动创建自有数据库"""
        with patch("sqlalchemy.create_engine") as mock_engine:
            with patch("sqlalchemy.orm.sessionmaker") as mock_sessionmaker:
                from pycoder.server.recommendation.engine import RecommendationEngine

                mock_engine.return_value = MagicMock()
                mock_sessionmaker.return_value = MagicMock()
                engine = RecommendationEngine(db_session=None)
                assert engine._own_engine is not None

    @pytest.mark.asyncio
    async def test_get_similar_skills_empty(self, mock_session):
        """获取相似技能（空结果）"""
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(db_session=mock_session)
        mock_session.all.return_value = []
        results = await engine.get_similar_skills("skill-123")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_similar_skills_error(self, mock_session):
        """获取相似技能异常处理"""
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(db_session=mock_session)
        mock_session.filter.side_effect = Exception("DB error")
        results = await engine.get_similar_skills("skill-123")
        assert results == []

    @pytest.mark.asyncio
    async def test_find_similar_users_empty(self, mock_session):
        """查找相似用户（空结果）"""
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(db_session=mock_session)
        mock_session.all.return_value = []
        results = await engine.find_similar_users("user-123")
        assert results == []

    @pytest.mark.asyncio
    async def test_recommend_from_similar_users_empty(self, mock_session):
        """从相似用户推荐（空结果）"""
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(db_session=mock_session)
        results = await engine.recommend_from_similar_users("user-123")
        assert results == []

    @pytest.mark.asyncio
    async def test_get_trending_skills_empty(self, mock_session):
        """获取热门技能（空结果）"""
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(db_session=mock_session)
        mock_session.all.return_value = []
        results = await engine.get_trending_skills()
        assert results == []

    @pytest.mark.asyncio
    async def test_get_personalized_recommendations_empty(self, mock_session):
        """个性化推荐（空结果）"""
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(db_session=mock_session)
        mock_session.first.return_value = None
        results = await engine.get_personalized_recommendations("user-123")
        assert results == []

    @pytest.mark.asyncio
    async def test_track_user_behavior_success(self, mock_session):
        """追踪用户行为成功"""
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(db_session=mock_session)
        # Mock UserBehavior 返回
        mock_behavior = MagicMock()
        mock_behavior.total_views = 5
        mock_behavior.total_clicks = 3
        mock_behavior.total_ratings = 2
        mock_behavior.avg_rating_score = 4.0
        mock_session.first.return_value = mock_behavior
        result = await engine.track_user_behavior("user-123", "skill-1", "view")
        assert result["success"] is True
        assert result["action"] == "view"

    @pytest.mark.asyncio
    async def test_track_user_behavior_error(self, mock_session):
        """追踪用户行为异常"""
        from pycoder.server.recommendation.engine import RecommendationEngine

        engine = RecommendationEngine(db_session=mock_session)
        mock_session.add.side_effect = Exception("DB write error")
        result = await engine.track_user_behavior("user-123", "skill-1", "view")
        assert result["success"] is False


# ═══════════════════════════════════════════════════════════════
# 15. sync/cloud_sync_engine.py 测试
# ═══════════════════════════════════════════════════════════════


class TestSyncEnums:
    """同步枚举类型测试"""

    def test_sync_action_values(self):
        """SyncAction 枚举值"""
        from pycoder.server.sync.cloud_sync_engine import SyncAction

        assert SyncAction.UPLOAD.value == "upload"
        assert SyncAction.DOWNLOAD.value == "download"
        assert SyncAction.CONFLICT.value == "conflict"

    def test_sync_status_values(self):
        """SyncStatus 枚举值"""
        from pycoder.server.sync.cloud_sync_engine import SyncStatus

        assert SyncStatus.PENDING.value == "pending"
        assert SyncStatus.SUCCESS.value == "success"
        assert SyncStatus.FAILED.value == "failed"

    def test_conflict_resolution_values(self):
        """ConflictResolution 枚举值"""
        from pycoder.server.sync.cloud_sync_engine import ConflictResolution

        assert ConflictResolution.LOCAL_WINS.value == "local_wins"
        assert ConflictResolution.REMOTE_WINS.value == "remote_wins"
        assert ConflictResolution.MANUAL.value == "manual"


class TestCloudSyncEngine:
    """CloudSyncEngine 类测试"""

    @pytest.fixture
    def mock_session(self):
        """创建 mock 数据库会话"""
        session = MagicMock()
        session.query.return_value = session
        session.filter.return_value = session
        session.order_by.return_value = session
        session.limit.return_value = session
        session.all.return_value = []
        session.first.return_value = None
        return session

    def test_init_defaults(self, mock_session):
        """初始化默认值"""
        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine

        engine = CloudSyncEngine(session=mock_session)
        assert engine.session is mock_session
        assert engine.local_db is None
        assert engine.is_syncing is False

    def test_init_with_local_db(self, mock_session):
        """带本地数据库初始化"""
        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine

        local_mock = MagicMock()
        engine = CloudSyncEngine(session=mock_session, local_db_session=local_mock)
        assert engine.local_db is local_mock

    @pytest.mark.asyncio
    async def test_upload_ratings_empty(self, mock_session):
        """上传空评分列表"""
        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine

        engine = CloudSyncEngine(session=mock_session)
        result = await engine.upload_ratings("user-1", "device-1", [])
        assert result["success"] is True
        assert result["uploaded"] == 0

    @pytest.mark.asyncio
    async def test_upload_ratings_error(self, mock_session):
        """上传评分异常"""
        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine

        engine = CloudSyncEngine(session=mock_session)
        mock_session.add.side_effect = Exception("DB error")
        result = await engine.upload_ratings(
            "user-1",
            "device-1",
            [{"skill_id": "s1", "rating": 4, "timestamp": "2026-07-01T00:00:00"}],
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_download_ratings_empty(self, mock_session):
        """下载评分（空结果）"""
        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine

        engine = CloudSyncEngine(session=mock_session)
        mock_session.all.return_value = []
        result = await engine.download_ratings("user-1", "device-1")
        assert result["success"] is True
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_download_ratings_error(self, mock_session):
        """下载评分异常"""
        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine

        engine = CloudSyncEngine(session=mock_session)
        mock_session.filter.side_effect = Exception("DB error")
        result = await engine.download_ratings("user-1", "device-1")
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_resolve_conflict_not_found(self, mock_session):
        """解决冲突（评分不存在）"""
        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine, ConflictResolution

        engine = CloudSyncEngine(session=mock_session)
        mock_session.first.return_value = None
        result = await engine.resolve_conflict(
            "user-1", "skill-1", ConflictResolution.LOCAL_WINS
        )
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_resolve_conflict_local_wins(self, mock_session):
        """解决冲突（本地版本优先）"""
        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine, ConflictResolution

        engine = CloudSyncEngine(session=mock_session)
        mock_rating = MagicMock()
        mock_session.first.return_value = mock_rating
        result = await engine.resolve_conflict(
            "user-1", "skill-1", ConflictResolution.LOCAL_WINS
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_resolve_conflict_remote_wins(self, mock_session):
        """解决冲突（远程版本优先）"""
        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine, ConflictResolution

        engine = CloudSyncEngine(session=mock_session)
        mock_rating = MagicMock()
        mock_session.first.return_value = mock_rating
        result = await engine.resolve_conflict(
            "user-1", "skill-1", ConflictResolution.REMOTE_WINS
        )
        assert result["success"] is True

    def test_has_conflict_time_difference(self):
        """冲突检测：时间差在阈值内"""
        from datetime import UTC, datetime, timedelta

        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine

        engine = CloudSyncEngine(session=MagicMock())
        now = datetime.now(UTC)
        close = now + timedelta(seconds=20)
        assert engine._has_conflict(now, close) is True

    def test_has_conflict_no_difference(self):
        """冲突检测：时间相同"""
        from datetime import UTC, datetime

        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine

        engine = CloudSyncEngine(session=MagicMock())
        now = datetime.now(UTC)
        assert engine._has_conflict(now, now) is False

    def test_has_conflict_large_difference(self):
        """冲突检测：时间差超过阈值"""
        from datetime import UTC, datetime, timedelta

        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine

        engine = CloudSyncEngine(session=MagicMock())
        now = datetime.now(UTC)
        far = now + timedelta(hours=1)
        assert engine._has_conflict(now, far) is False

    @pytest.mark.asyncio
    async def test_get_sync_status(self, mock_session):
        """获取同步状态"""
        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine

        engine = CloudSyncEngine(session=mock_session)
        mock_session.all.return_value = []
        result = await engine.get_sync_status("user-1")
        assert result["success"] is True
        assert "last_sync" in result
        assert "upload_count" in result
        assert "download_count" in result
        assert "conflict_count" in result
        assert "is_syncing" in result

    def test_conflict_threshold_constant(self):
        """冲突阈值常量"""
        from pycoder.server.sync.cloud_sync_engine import CloudSyncEngine

        assert CloudSyncEngine.CONFLICT_THRESHOLD == 30
"""
10 角色专业 Agent 团队单元测试 — 覆盖 SpecializedAgentTeam 核心功能

测试范围:
  - SpecializedAgentTeam 初始化
  - 10 角色 Agent 创建（Architect, Developer, Tester, Debugger, Reviewer,
    Security, DevOps, Documenter, Optimizer, Orchestrator）
  - Agent 角色属性（name, description, capabilities, tools）
  - Team 创建与角色分配
  - 任务分配与执行
  - 任务进度跟踪
  - Agent 能力列表
  - 角色验证
"""

from __future__ import annotations

import pytest

from pycoder.brain.specialized_agents import (
    AgentProfile,
    AgentRole,
    SpecializedAgentTeam,
    Team,
    TeamTask,
    get_agent_team,
)

# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def team_mgr() -> SpecializedAgentTeam:
    """创建 SpecializedAgentTeam 实例"""
    return SpecializedAgentTeam()


@pytest.fixture
def basic_team(team_mgr: SpecializedAgentTeam) -> Team:
    """创建包含三个角色的基础团队"""
    return team_mgr.create_team(
        "test-team",
        [AgentRole.ARCHITECT, AgentRole.DEVELOPER, AgentRole.TESTER],
    )


# ── AgentRole 枚举测试 ───────────────────────────────────


class TestAgentRole:
    """AgentRole 枚举测试"""

    def test_all_roles_exist(self) -> None:
        """测试 10 个角色全部存在"""
        roles = list(AgentRole)
        assert len(roles) == 14  # 14 角色团队
        assert AgentRole.ARCHITECT in roles
        assert AgentRole.DEVELOPER in roles
        assert AgentRole.TESTER in roles
        assert AgentRole.DEBUGGER in roles
        assert AgentRole.REVIEWER in roles
        assert AgentRole.SECURITY in roles
        assert AgentRole.DEVOPS in roles
        assert AgentRole.DOCUMENTER in roles
        assert AgentRole.OPTIMIZER in roles
        assert AgentRole.ORCHESTRATOR in roles

    def test_role_values(self) -> None:
        """测试角色值正确"""
        assert AgentRole.ARCHITECT.value == "architect"
        assert AgentRole.DEVELOPER.value == "developer"
        assert AgentRole.TESTER.value == "tester"
        assert AgentRole.DEBUGGER.value == "debugger"
        assert AgentRole.REVIEWER.value == "reviewer"
        assert AgentRole.SECURITY.value == "security"
        assert AgentRole.DEVOPS.value == "devops"
        assert AgentRole.DOCUMENTER.value == "documenter"
        assert AgentRole.OPTIMIZER.value == "optimizer"
        assert AgentRole.ORCHESTRATOR.value == "orchestrator"

    def test_role_from_string(self) -> None:
        """测试从字符串创建角色"""
        assert AgentRole("architect") == AgentRole.ARCHITECT
        assert AgentRole("developer") == AgentRole.DEVELOPER
        assert AgentRole("tester") == AgentRole.TESTER

    def test_role_from_string_invalid(self) -> None:
        """测试无效角色字符串"""
        with pytest.raises(ValueError):
            AgentRole("invalid_role")


# ── AgentProfile 测试 ────────────────────────────────────


class TestAgentProfile:
    """AgentProfile 数据类测试"""

    def test_create_profile(self) -> None:
        """测试创建 AgentProfile"""
        profile = AgentProfile(
            role=AgentRole.ARCHITECT,
            name="架构师",
            description="系统设计",
            system_prompt="你是一个架构师",
            allowed_tools=["tool1", "tool2"],
            temperature=0.5,
            max_tokens=4096,
            priority=8,
        )
        assert profile.role == AgentRole.ARCHITECT
        assert profile.name == "架构师"
        assert profile.description == "系统设计"
        assert profile.system_prompt == "你是一个架构师"
        assert profile.allowed_tools == ["tool1", "tool2"]
        assert profile.temperature == 0.5
        assert profile.max_tokens == 4096
        assert profile.priority == 8

    def test_default_values(self) -> None:
        """测试默认值"""
        profile = AgentProfile(
            role=AgentRole.DEVELOPER,
            name="开发者",
            description="开发",
            system_prompt="系统提示",
        )
        assert profile.allowed_tools == []
        assert profile.temperature == 0.3
        assert profile.max_tokens == 8192
        assert profile.priority == 5

    def test_to_dict(self) -> None:
        """测试转换为字典"""
        profile = AgentProfile(
            role=AgentRole.TESTER,
            name="测试者",
            description="测试",
            system_prompt="提示词",
            allowed_tools=["pytest"],
            temperature=0.3,
            max_tokens=8192,
            priority=7,
        )
        d = profile.to_dict()
        assert d["role"] == "tester"
        assert d["name"] == "测试者"
        assert d["description"] == "测试"
        assert d["system_prompt"] == "提示词"
        assert d["allowed_tools"] == ["pytest"]
        assert d["temperature"] == 0.3
        assert d["max_tokens"] == 8192
        assert d["priority"] == 7


# ── SpecializedAgentTeam 初始化测试 ──────────────────────


class TestSpecializedAgentTeamInit:
    """SpecializedAgentTeam 初始化测试"""

    def test_init(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试初始化"""
        assert team_mgr._profiles is not None
        assert len(team_mgr._profiles) == 14  # 14 角色团队
        assert team_mgr._active_teams == {}

    def test_get_all_roles(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试获取所有角色"""
        roles = team_mgr.get_all_roles()
        assert len(roles) == 14  # 14 角色团队
        assert AgentRole.ARCHITECT in roles
        assert AgentRole.ORCHESTRATOR in roles

    def test_get_all_profiles(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试获取所有角色配置"""
        profiles = team_mgr.get_all_profiles()
        assert len(profiles) == 14  # 14 角色团队
        for p in profiles:
            assert isinstance(p, AgentProfile)
            assert p.name
            assert p.description
            assert p.system_prompt


# ── 10 角色 Agent 创建测试 ────────────────────────────────


class TestAllRoleProfiles:
    """10 个角色 Agent 配置测试"""

    def test_architect_profile(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试架构师配置"""
        profile = team_mgr.get_agent(AgentRole.ARCHITECT)
        assert profile.name == "系统架构师"
        assert "架构" in profile.description
        assert "SOLID" in profile.system_prompt
        assert "read_file" in profile.allowed_tools
        assert profile.temperature == 0.2
        assert profile.priority == 10

    def test_developer_profile(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试开发工程师配置"""
        profile = team_mgr.get_agent(AgentRole.DEVELOPER)
        assert profile.name == "开发工程师"
        assert "代码" in profile.description
        assert "PEP 8" in profile.system_prompt
        assert "write_file" in profile.allowed_tools
        assert profile.temperature == 0.3
        assert profile.priority == 8

    def test_tester_profile(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试测试工程师配置"""
        profile = team_mgr.get_agent(AgentRole.TESTER)
        assert profile.name == "测试工程师"
        assert "测试" in profile.description
        assert "pytest" in profile.system_prompt
        assert "execute_shell" in profile.allowed_tools
        assert profile.temperature == 0.3
        assert profile.priority == 7

    def test_debugger_profile(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试调试专家配置"""
        profile = team_mgr.get_agent(AgentRole.DEBUGGER)
        assert profile.name == "调试专家"
        assert "Bug" in profile.description
        assert "堆栈跟踪" in profile.system_prompt
        assert "execute_python" in profile.allowed_tools
        assert profile.temperature == 0.2
        assert profile.priority == 9

    def test_reviewer_profile(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试代码审查员配置"""
        profile = team_mgr.get_agent(AgentRole.REVIEWER)
        assert profile.name == "代码审查员"
        assert "审查" in profile.description
        assert "项目规范" in profile.system_prompt
        assert "search_code" in profile.allowed_tools
        assert profile.temperature == 0.2
        assert profile.priority == 6

    def test_security_profile(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试安全专家配置"""
        profile = team_mgr.get_agent(AgentRole.SECURITY)
        assert profile.name == "安全专家"
        assert "安全" in profile.description
        assert "OWASP" in profile.system_prompt
        assert "hard" in profile.system_prompt.lower() or "密钥" in profile.system_prompt
        assert profile.temperature == 0.1
        assert profile.priority == 9

    def test_devops_profile(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试运维工程师配置"""
        profile = team_mgr.get_agent(AgentRole.DEVOPS)
        assert profile.name == "运维工程师"
        assert "CI/CD" in profile.description or "部署" in profile.description
        assert "Dockerfile" in profile.system_prompt
        assert "write_file" in profile.allowed_tools
        assert profile.temperature == 0.3
        assert profile.priority == 7

    def test_documenter_profile(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试文档工程师配置"""
        profile = team_mgr.get_agent(AgentRole.DOCUMENTER)
        assert profile.name == "文档工程师"
        assert "文档" in profile.description
        assert "docstring" in profile.system_prompt
        assert "write_file" in profile.allowed_tools
        assert profile.temperature == 0.4
        assert profile.priority == 4

    def test_optimizer_profile(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试性能优化师配置"""
        profile = team_mgr.get_agent(AgentRole.OPTIMIZER)
        assert profile.name == "性能优化师"
        assert "性能" in profile.description
        assert "profiling" in profile.system_prompt
        assert "execute_python" in profile.allowed_tools
        assert profile.temperature == 0.2
        assert profile.priority == 6

    def test_orchestrator_profile(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试团队协调者配置"""
        profile = team_mgr.get_agent(AgentRole.ORCHESTRATOR)
        assert profile.name == "团队协调者"
        assert "协调" in profile.description or "分解" in profile.description
        assert "子任务" in profile.system_prompt
        assert "list_files" in profile.allowed_tools
        assert profile.temperature == 0.3
        assert profile.priority == 10

    def test_all_profiles_have_valid_tools(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试所有角色配置都有有效工具"""
        for role in AgentRole:
            profile = team_mgr.get_agent(role)
            assert isinstance(profile.allowed_tools, list)
            assert len(profile.allowed_tools) > 0, f"{role} 缺少工具"

    def test_all_profiles_have_valid_temperature(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试所有角色温度参数在有效范围"""
        for role in AgentRole:
            profile = team_mgr.get_agent(role)
            assert 0.0 <= profile.temperature <= 1.0, f"{role} 温度无效"

    def test_all_profiles_have_valid_priority(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试所有角色优先级在有效范围"""
        for role in AgentRole:
            profile = team_mgr.get_agent(role)
            assert 1 <= profile.priority <= 10, f"{role} 优先级无效"


# ── 角色获取/验证测试 ─────────────────────────────────────


class TestGetAgent:
    """角色获取测试"""

    def test_get_agent_valid(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试获取有效角色"""
        profile = team_mgr.get_agent(AgentRole.ARCHITECT)
        assert isinstance(profile, AgentProfile)
        assert profile.role == AgentRole.ARCHITECT

    def test_get_agent_invalid(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试获取无效角色抛出异常"""
        # 传入非 AgentRole 类型的值，应触发 ValueError
        with pytest.raises(ValueError, match="未知角色"):
            team_mgr.get_agent("invalid_role")  # type: ignore


# ── Team 创建与角色分配测试 ───────────────────────────────


class TestTeamCreation:
    """Team 创建测试"""

    def test_create_team(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试创建团队"""
        team = team_mgr.create_team(
            "my-team",
            [AgentRole.ARCHITECT, AgentRole.DEVELOPER],
        )
        assert team.name == "my-team"
        assert len(team.roles) == 2
        assert AgentRole.ARCHITECT in team.roles
        assert AgentRole.DEVELOPER in team.roles

    def test_create_team_all_roles(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试创建包含所有角色的团队"""
        all_roles = list(AgentRole)
        team = team_mgr.create_team("full-team", all_roles)
        assert len(team.roles) == 14  # 14 角色团队

    def test_create_team_registers_in_manager(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试创建的团队在管理器中注册"""
        team_mgr.create_team("registered-team", [AgentRole.TESTER])
        assert "registered-team" in team_mgr.list_teams()

    def test_get_team(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试获取已创建的团队"""
        team_mgr.create_team("get-me", [AgentRole.DEBUGGER])
        team = team_mgr.get_team("get-me")
        assert team is not None
        assert team.name == "get-me"

    def test_get_team_not_found(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试获取不存在的团队"""
        team = team_mgr.get_team("nonexistent")
        assert team is None

    def test_list_teams(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试列出所有团队"""
        team_mgr.create_team("team-a", [AgentRole.ARCHITECT])
        team_mgr.create_team("team-b", [AgentRole.DEVELOPER])
        teams = team_mgr.list_teams()
        assert "team-a" in teams
        assert "team-b" in teams
        assert len(teams) == 2

    def test_disband_team(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试解散团队"""
        team_mgr.create_team("temp-team", [AgentRole.REVIEWER])
        assert team_mgr.disband_team("temp-team") is True
        assert "temp-team" not in team_mgr.list_teams()
        assert team_mgr.get_team("temp-team") is None

    def test_disband_nonexistent_team(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试解散不存在的团队"""
        assert team_mgr.disband_team("ghost-team") is False


class TestTeamMembers:
    """Team 成员测试"""

    def test_members_property(self, basic_team: Team) -> None:
        """测试团队成员属性"""
        members = basic_team.members
        assert len(members) == 3
        roles = [m.role for m in members]
        assert AgentRole.ARCHITECT in roles
        assert AgentRole.DEVELOPER in roles
        assert AgentRole.TESTER in roles

    def test_members_return_profiles(self, basic_team: Team) -> None:
        """测试成员返回 AgentProfile 实例"""
        members = basic_team.members
        for m in members:
            assert isinstance(m, AgentProfile)


# ── 任务分配测试 ─────────────────────────────────────────


class TestTaskAssignment:
    """任务分配测试"""

    def test_assign_task_with_string(self, basic_team: Team) -> None:
        """测试用字符串描述分配任务"""
        task = basic_team.assign_task(AgentRole.DEVELOPER, "实现登录功能")
        assert isinstance(task, TeamTask)
        assert task.assigned_role == AgentRole.DEVELOPER
        assert task.description == "实现登录功能"
        assert task.status == "pending"
        assert task.task_id != ""

    def test_assign_task_with_team_task(self, basic_team: Team) -> None:
        """测试分配已有 TeamTask 对象"""
        existing = TeamTask(
            task_id="custom-id",
            description="自定义任务",
            status="pending",
        )
        task = basic_team.assign_task(AgentRole.TESTER, existing)
        assert task.task_id == "custom-id"
        assert task.assigned_role == AgentRole.TESTER

    def test_assign_task_with_agent_profile(self, basic_team: Team) -> None:
        """测试用 AgentProfile 分配任务"""
        profile = basic_team.profiles[AgentRole.ARCHITECT]
        task = basic_team.assign_task(profile, "设计架构")
        assert task.assigned_role == AgentRole.ARCHITECT

    def test_assign_task_tracks_progress(self, basic_team: Team) -> None:
        """测试任务分配后进度跟踪"""
        task = basic_team.assign_task(AgentRole.DEVELOPER, "写代码")
        progress = basic_team.get_progress()
        assert task.task_id in progress["tasks"]
        assert progress["tasks"][task.task_id]["status"] == "pending"

    def test_assign_multiple_tasks(self, basic_team: Team) -> None:
        """测试分配多个任务"""
        basic_team.assign_task(AgentRole.ARCHITECT, "任务1")
        basic_team.assign_task(AgentRole.DEVELOPER, "任务2")
        basic_team.assign_task(AgentRole.TESTER, "任务3")

        progress = basic_team.get_progress()
        assert progress["total_tasks"] == 3
        assert progress["pending"] == 3


# ── 任务执行测试 ─────────────────────────────────────────


class TestTaskExecution:
    """任务执行测试"""

    @pytest.mark.asyncio
    async def test_execute_parallel(self, basic_team: Team) -> None:
        """测试并行执行任务"""
        t1 = basic_team.assign_task(AgentRole.ARCHITECT, "架构设计")
        t2 = basic_team.assign_task(AgentRole.DEVELOPER, "功能开发")
        t3 = basic_team.assign_task(AgentRole.TESTER, "编写测试")

        results = await basic_team.execute_parallel([t1, t2, t3])
        assert len(results) == 3
        assert all(r is not None for r in results.values())
        assert t1.status == "done"
        assert t2.status == "done"
        assert t3.status == "done"

    @pytest.mark.asyncio
    async def test_execute_parallel_empty(self, basic_team: Team) -> None:
        """测试并行执行空任务列表"""
        results = await basic_team.execute_parallel([])
        assert results == {}

    @pytest.mark.asyncio
    async def test_execute_sequential(self, basic_team: Team) -> None:
        """测试顺序执行任务"""
        t1 = basic_team.assign_task(AgentRole.ARCHITECT, "第一步")
        t2 = basic_team.assign_task(AgentRole.DEVELOPER, "第二步")

        results = await basic_team.execute_sequential([t1, t2])
        assert len(results) == 2
        assert t1.status == "done"
        assert t2.status == "done"

    @pytest.mark.asyncio
    async def test_execute_result_contains_role_info(self, basic_team: Team) -> None:
        """测试执行结果包含角色信息"""
        task = basic_team.assign_task(AgentRole.DEBUGGER, "修复 bug")
        results = await basic_team.execute_parallel([task])
        result = list(results.values())[0]
        assert "debugger" in str(result).lower()


# ── 任务进度跟踪测试 ─────────────────────────────────────


class TestTaskProgress:
    """任务进度跟踪测试"""

    def test_initial_progress(self, basic_team: Team) -> None:
        """测试初始进度"""
        progress = basic_team.get_progress()
        assert progress["team_name"] == "test-team"
        assert progress["total_tasks"] == 0
        assert progress["done"] == 0
        assert progress["failed"] == 0
        assert progress["running"] == 0
        assert progress["pending"] == 0
        assert progress["progress_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_progress_after_execution(self, basic_team: Team) -> None:
        """测试执行后的进度"""
        t1 = basic_team.assign_task(AgentRole.DEVELOPER, "任务1")
        t2 = basic_team.assign_task(AgentRole.TESTER, "任务2")

        await basic_team.execute_parallel([t1, t2])

        progress = basic_team.get_progress()
        assert progress["total_tasks"] == 2
        assert progress["done"] == 2
        assert progress["progress_pct"] == 100.0

    @pytest.mark.asyncio
    async def test_progress_tasks_detail(self, basic_team: Team) -> None:
        """测试进度中的任务详情"""
        task = basic_team.assign_task(AgentRole.ARCHITECT, "架构任务")
        await basic_team.execute_parallel([task])

        progress = basic_team.get_progress()
        task_detail = progress["tasks"][task.task_id]
        assert task_detail["status"] == "done"
        assert task_detail["role"] == "architect"

    def test_cancel_task(self, basic_team: Team) -> None:
        """测试取消任务"""
        task = basic_team.assign_task(AgentRole.DEVELOPER, "可取消的任务")
        assert basic_team.cancel_task(task.task_id) is True

        progress = basic_team.get_progress()
        assert progress["tasks"][task.task_id]["status"] == "cancelled"

    def test_cancel_nonexistent_task(self, basic_team: Team) -> None:
        """测试取消不存在的任务"""
        assert basic_team.cancel_task("fake-id") is False


# ── Agent 自动选角测试 ───────────────────────────────────


class TestAgentSelection:
    """Agent 自动选角测试"""

    def test_select_agents_for_architecture(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试根据架构描述选角"""
        agents = team_mgr.select_agents("设计系统架构和模块划分")
        roles = [a.role for a in agents]
        assert AgentRole.ARCHITECT in roles

    def test_select_agents_for_development(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试根据开发描述选角"""
        agents = team_mgr.select_agents("编写代码实现用户认证功能")
        roles = [a.role for a in agents]
        assert AgentRole.DEVELOPER in roles

    def test_select_agents_for_testing(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试根据测试描述选角"""
        agents = team_mgr.select_agents("编写 pytest 测试用例验证覆盖率")
        roles = [a.role for a in agents]
        assert AgentRole.TESTER in roles

    def test_select_agents_for_debugging(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试根据调试描述选角"""
        agents = team_mgr.select_agents("修复 crash bug 和异常堆栈跟踪")
        roles = [a.role for a in agents]
        assert AgentRole.DEBUGGER in roles

    def test_select_agents_for_review(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试根据审查描述选角"""
        agents = team_mgr.select_agents("代码审查 review 检查代码质量")
        roles = [a.role for a in agents]
        assert AgentRole.REVIEWER in roles

    def test_select_agents_for_security(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试根据安全描述选角"""
        agents = team_mgr.select_agents("安全审计发现 SQL 注入漏洞需要加密")
        roles = [a.role for a in agents]
        assert AgentRole.SECURITY in roles

    def test_select_agents_for_devops(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试根据运维描述选角"""
        agents = team_mgr.select_agents("docker 容器部署 CI/CD pipeline")
        roles = [a.role for a in agents]
        assert AgentRole.DEVOPS in roles

    def test_select_agents_for_documentation(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试根据文档描述选角"""
        agents = team_mgr.select_agents("编写 API 文档和 docstring 注释")
        roles = [a.role for a in agents]
        assert AgentRole.DOCUMENTER in roles

    def test_select_agents_for_optimization(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试根据优化描述选角"""
        agents = team_mgr.select_agents("性能优化分析瓶颈引入缓存")
        roles = [a.role for a in agents]
        assert AgentRole.OPTIMIZER in roles

    def test_select_agents_for_orchestration(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试根据协调描述选角"""
        agents = team_mgr.select_agents("任务编排调度协调分配工作流程规划")
        roles = [a.role for a in agents]
        assert AgentRole.ORCHESTRATOR in roles

    def test_select_agents_no_match(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试无匹配关键词"""
        agents = team_mgr.select_agents("xyz abc 123")
        assert agents == []

    def test_select_agents_returns_profiles(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试返回 AgentProfile 列表"""
        agents = team_mgr.select_agents("编写代码并测试")
        for agent in agents:
            assert isinstance(agent, AgentProfile)

    def test_select_agents_sorted_by_score(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试按相关度排序"""
        agents = team_mgr.select_agents("开发代码实现测试验证")
        # 开发者有更多匹配关键词，应在前面
        if len(agents) >= 2:
            # 第一个应该是最匹配的
            assert agents[0].role in (AgentRole.DEVELOPER, AgentRole.TESTER)

    def test_select_agents_multi_match(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试多角色匹配"""
        agents = team_mgr.select_agents(
            "设计架构，编写代码，编写测试，修复 bug，审查代码，安全检查，部署上线，编写文档，优化性能，协调任务"
        )
        assert len(agents) >= 5  # 至少匹配多个角色


# ── TeamTask 数据类测试 ──────────────────────────────────


class TestTeamTask:
    """TeamTask 数据类测试"""

    def test_create_team_task(self) -> None:
        """测试创建 TeamTask"""
        task = TeamTask(
            task_id="task-001",
            description="测试任务",
            assigned_role=AgentRole.DEVELOPER,
        )
        assert task.task_id == "task-001"
        assert task.description == "测试任务"
        assert task.assigned_role == AgentRole.DEVELOPER
        assert task.status == "pending"
        assert task.dependencies == []
        assert task.result is None
        assert task.error is None

    def test_team_task_defaults(self) -> None:
        """测试 TeamTask 默认值"""
        task = TeamTask(task_id="t1", description="d1")
        assert task.assigned_role is None
        assert task.status == "pending"
        assert task.dependencies == []

    def test_team_task_with_dependencies(self) -> None:
        """测试带依赖的 TeamTask"""
        task = TeamTask(
            task_id="t2",
            description="依赖任务",
            dependencies=["t1", "t0"],
        )
        assert "t1" in task.dependencies
        assert "t0" in task.dependencies


# ── 全局实例测试 ─────────────────────────────────────────


class TestGlobalAgentTeam:
    """全局 Agent 团队管理器测试"""

    def test_get_agent_team_singleton(self) -> None:
        """测试单例"""
        mgr1 = get_agent_team()
        mgr2 = get_agent_team()
        assert mgr1 is mgr2

    def test_get_agent_team_creates_instance(self) -> None:
        """测试首次调用创建实例"""
        import pycoder.brain.specialized_agents as mod

        mod._agent_team = None
        mgr = get_agent_team()
        assert isinstance(mgr, SpecializedAgentTeam)


# ── 角色能力列表测试 ─────────────────────────────────────


class TestAgentCapabilities:
    """Agent 能力列表测试"""

    def test_architect_capabilities(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试架构师能力"""
        profile = team_mgr.get_agent(AgentRole.ARCHITECT)
        assert "read_file" in profile.allowed_tools
        assert "search_code" in profile.allowed_tools
        assert "list_files" in profile.allowed_tools

    def test_developer_capabilities(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试开发者能力"""
        profile = team_mgr.get_agent(AgentRole.DEVELOPER)
        assert "write_file" in profile.allowed_tools
        assert "create_file" in profile.allowed_tools
        assert "execute_shell" in profile.allowed_tools

    def test_security_capabilities(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试安全专家能力"""
        profile = team_mgr.get_agent(AgentRole.SECURITY)
        assert "read_file" in profile.allowed_tools
        assert "search_code" in profile.allowed_tools
        assert "execute_shell" in profile.allowed_tools

    def test_debugger_capabilities(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试调试专家能力"""
        profile = team_mgr.get_agent(AgentRole.DEBUGGER)
        assert "execute_python" in profile.allowed_tools
        assert "write_file" in profile.allowed_tools

    def test_orchestrator_capabilities(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试协调者能力"""
        profile = team_mgr.get_agent(AgentRole.ORCHESTRATOR)
        assert "read_file" in profile.allowed_tools
        assert "list_files" in profile.allowed_tools

    def test_all_roles_have_read_file(self, team_mgr: SpecializedAgentTeam) -> None:
        """测试所有角色都有 read_file 能力"""
        for role in AgentRole:
            profile = team_mgr.get_agent(role)
            assert "read_file" in profile.allowed_tools, f"{role} 缺少 read_file"


# ── 角色验证测试 ─────────────────────────────────────────


class TestRoleValidation:
    """角色验证测试"""

    def test_valid_role_strings(self) -> None:
        """测试有效角色字符串"""
        valid = ["architect", "developer", "tester", "debugger", "reviewer",
                 "security", "devops", "documenter", "optimizer", "orchestrator"]
        for v in valid:
            role = AgentRole(v)
            assert isinstance(role, AgentRole)

    def test_invalid_role_raises(self) -> None:
        """测试无效角色抛出异常"""
        with pytest.raises(ValueError):
            AgentRole("superhero")

    def test_role_equality(self) -> None:
        """测试角色相等性"""
        assert AgentRole.ARCHITECT == AgentRole("architect")
        assert AgentRole.DEVELOPER != AgentRole.TESTER

    def test_role_in_team_validation(self, basic_team: Team) -> None:
        """测试角色是否在团队中"""
        assert AgentRole.ARCHITECT in basic_team.roles
        assert AgentRole.DEVELOPER in basic_team.roles
        assert AgentRole.TESTER in basic_team.roles
        assert AgentRole.SECURITY not in basic_team.roles

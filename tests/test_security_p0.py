"""测试 P0 安全增强模块

覆盖:
- pycoder.providers.key_rotator.KeyRotator — 多 Key 轮询/失效/冷却/禁用
- pycoder.safety.tool_whitelist.ToolWhitelist — 三模式/通配符/参数校验/审计
- pycoder.adapters.docker_sandbox.DockerSandbox._build_security_args — defense-in-depth 标志
- pycoder.safety.sandbox.CodeSandbox — DeprecationWarning
"""

from __future__ import annotations

import time
import warnings

import pytest

from pycoder.providers.key_rotator import (
    DEFAULT_COOLDOWN_SECONDS,
    FAILURE_STATUS_CODES,
    KeyRotator,
    KeyState,
    get_key_rotator,
    reset_key_rotator,
)
from pycoder.safety.tool_whitelist import (
    ParamSchema,
    ToolWhitelist,
    WhitelistMode,
    get_tool_whitelist,
    reset_tool_whitelist,
)

# ═══════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════


@pytest.fixture
def clean_rotator() -> KeyRotator:
    """每个测试用例都使用干净的 KeyRotator"""
    reset_key_rotator()
    rotator = KeyRotator()
    rotator.clear()
    yield rotator
    rotator.clear()
    reset_key_rotator()


@pytest.fixture
def clean_whitelist() -> ToolWhitelist:
    """每个测试用例都使用干净的 ToolWhitelist"""
    reset_tool_whitelist()
    wl = ToolWhitelist()
    yield wl
    reset_tool_whitelist()


# ═══════════════════════════════════════════════
# 1. KeyState 测试
# ═══════════════════════════════════════════════


class TestKeyState:
    """KeyState 数据类测试"""

    def test_default_available(self) -> None:
        """新 Key 应默认可用"""
        state = KeyState(key="sk-test123456789012", provider="deepseek")
        assert state.is_available is True
        assert state.failed_count == 0
        assert state.disabled is False

    def test_masked_shows_only_prefix_suffix(self) -> None:
        """脱敏应只显示前4后4"""
        state = KeyState(key="sk-abcdef1234567890", provider="deepseek")
        masked = state.masked
        assert "sk-a" in masked
        assert "7890" in masked
        assert "abcdef123456" not in masked

    def test_masked_short_key(self) -> None:
        """短 Key 应脱敏为 ***"""
        state = KeyState(key="short", provider="glm")
        assert state.masked == "***"

    def test_mark_failed_increments_count(self) -> None:
        """mark_failed 应增加失败计数"""
        state = KeyState(key="sk-test123456789012", provider="deepseek")
        state.mark_failed(401)
        assert state.failed_count == 1
        assert state.last_failed_at > 0

    def test_mark_failed_disables_after_5(self) -> None:
        """连续失败5次应永久禁用"""
        state = KeyState(key="sk-test123456789012", provider="deepseek")
        for _ in range(5):
            state.mark_failed(401)
        assert state.disabled is True
        assert state.is_available is False

    def test_is_available_false_during_cooldown(self) -> None:
        """冷却期内应不可用"""
        state = KeyState(
            key="sk-test123456789012",
            provider="deepseek",
            cooldown_seconds=60.0,
        )
        state.mark_failed(401)
        assert state.is_available is False  # 冷却期内

    def test_is_available_true_after_cooldown(self) -> None:
        """冷却期后应恢复可用"""
        state = KeyState(
            key="sk-test123456789012",
            provider="deepseek",
            cooldown_seconds=0.01,  # 10ms 冷却
        )
        state.mark_failed(401)
        time.sleep(0.02)  # 等待冷却过期
        assert state.is_available is True

    def test_mark_success_resets(self) -> None:
        """mark_success 应重置失败计数"""
        state = KeyState(key="sk-test123456789012", provider="deepseek")
        state.mark_failed(401)
        state.mark_failed(401)
        state.mark_success()
        assert state.failed_count == 0
        assert state.is_available is True


# ═══════════════════════════════════════════════
# 2. KeyRotator 测试
# ═══════════════════════════════════════════════


class TestKeyRotator:
    """KeyRotator 多 Key 轮换测试"""

    def test_add_key(self, clean_rotator: KeyRotator) -> None:
        """添加 Key 应能查询到"""
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        keys = clean_rotator.get_keys("deepseek")
        assert len(keys) == 1
        assert "sk-key1-1234567890" in keys

    def test_add_duplicate_key_ignored(self, clean_rotator: KeyRotator) -> None:
        """重复 Key 应被忽略"""
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        assert len(clean_rotator.get_keys("deepseek")) == 1

    def test_add_multiple_keys(self, clean_rotator: KeyRotator) -> None:
        """可添加多个 Key"""
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        clean_rotator.add_key("deepseek", "sk-key2-1234567890")
        clean_rotator.add_key("deepseek", "sk-key3-1234567890")
        assert len(clean_rotator.get_keys("deepseek")) == 3

    def test_get_key_returns_none_when_empty(self, clean_rotator: KeyRotator) -> None:
        """无 Key 时应返回 None"""
        assert clean_rotator.get_key("deepseek") is None

    def test_round_robin_strategy(self, clean_rotator: KeyRotator) -> None:
        """轮询策略应依次返回"""
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        clean_rotator.add_key("deepseek", "sk-key2-1234567890")
        clean_rotator.add_key("deepseek", "sk-key3-1234567890")

        k1 = clean_rotator.get_key("deepseek", strategy="round_robin")
        k2 = clean_rotator.get_key("deepseek", strategy="round_robin")
        k3 = clean_rotator.get_key("deepseek", strategy="round_robin")
        k4 = clean_rotator.get_key("deepseek", strategy="round_robin")

        # 应轮询 1→2→3→1
        assert k1 != k2 != k3
        assert k4 == k1  # 循环

    def test_random_strategy(self, clean_rotator: KeyRotator) -> None:
        """随机策略应从可用 Key 中选择"""
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        clean_rotator.add_key("deepseek", "sk-key2-1234567890")
        for _ in range(10):
            key = clean_rotator.get_key("deepseek", strategy="random")
            assert key in ("sk-key1-1234567890", "sk-key2-1234567890")

    def test_mark_failed_skips_key(self, clean_rotator: KeyRotator) -> None:
        """标记失效后应跳过该 Key"""
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        clean_rotator.add_key("deepseek", "sk-key2-1234567890")

        # 标记 key1 失效
        clean_rotator.mark_failed("deepseek", "sk-key1-1234567890", 401)

        # 后续应只用 key2
        for _ in range(5):
            key = clean_rotator.get_key("deepseek")
            assert key == "sk-key2-1234567890"

    def test_mark_failed_returns_none_when_all_failed(self, clean_rotator: KeyRotator) -> None:
        """所有 Key 失效时应返回 None"""
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        clean_rotator.mark_failed("deepseek", "sk-key1-1234567890", 401)

        assert clean_rotator.get_key("deepseek") is None

    def test_mark_success_recovers_key(self, clean_rotator: KeyRotator) -> None:
        """mark_success 应恢复 Key"""
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        clean_rotator.mark_failed("deepseek", "sk-key1-1234567890", 401)
        assert clean_rotator.get_key("deepseek") is None

        clean_rotator.mark_success("deepseek", "sk-key1-1234567890")
        assert clean_rotator.get_key("deepseek") is not None

    def test_should_rotate(self, clean_rotator: KeyRotator) -> None:
        """should_rotate 应识别 401/403/429"""
        assert clean_rotator.should_rotate(401) is True
        assert clean_rotator.should_rotate(403) is True
        assert clean_rotator.should_rotate(429) is True
        assert clean_rotator.should_rotate(200) is False
        assert clean_rotator.should_rotate(500) is False

    def test_permanent_disable_after_5_failures(self, clean_rotator: KeyRotator) -> None:
        """连续失败5次应永久禁用"""
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        for _ in range(5):
            clean_rotator.mark_failed("deepseek", "sk-key1-1234567890", 401)

        # 即使冷却期过，仍不可用
        states = clean_rotator._states["deepseek"]
        assert states[0].disabled is True

    def test_get_status(self, clean_rotator: KeyRotator) -> None:
        """get_status 应返回所有 Key 状态"""
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        clean_rotator.add_key("glm", "sk-key2-1234567890")
        status = clean_rotator.get_status()
        assert "deepseek" in status
        assert "glm" in status
        assert len(status["deepseek"]) == 1

    def test_remove_key(self, clean_rotator: KeyRotator) -> None:
        """remove_key 应移除指定 Key"""
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        clean_rotator.remove_key("deepseek", "sk-key1-1234567890")
        assert clean_rotator.get_keys("deepseek") == []

    def test_singleton(self) -> None:
        """KeyRotator 应为单例"""
        r1 = KeyRotator()
        r2 = KeyRotator()
        assert r1 is r2

    def test_get_key_rotator_singleton(self) -> None:
        """get_key_rotator 应返回单例"""
        reset_key_rotator()
        r1 = get_key_rotator()
        r2 = get_key_rotator()
        assert r1 is r2
        r1.clear()
        reset_key_rotator()


# ═══════════════════════════════════════════════
# 3. ToolWhitelist 测试
# ═══════════════════════════════════════════════


class TestToolWhitelist:
    """ToolWhitelist 工具白名单测试"""

    def test_allow_all_mode(self, clean_whitelist: ToolWhitelist) -> None:
        """allow_all 模式应允许所有工具"""
        clean_whitelist.set_mode(WhitelistMode.ALLOW_ALL)
        ok, _ = clean_whitelist.is_allowed("any.tool", {})
        assert ok is True

    def test_deny_all_mode(self, clean_whitelist: ToolWhitelist) -> None:
        """deny_all 模式应拒绝所有工具"""
        clean_whitelist.set_mode(WhitelistMode.DENY_ALL)
        ok, reason = clean_whitelist.is_allowed("any.tool", {})
        assert ok is False
        assert "deny_all" in reason

    def test_allowlist_exact_match(self, clean_whitelist: ToolWhitelist) -> None:
        """allowlist 模式应精确匹配工具名"""
        clean_whitelist.add_allowed("files.read")
        ok, _ = clean_whitelist.is_allowed("files.read", {})
        assert ok is True

    def test_allowlist_not_in_list(self, clean_whitelist: ToolWhitelist) -> None:
        """不在白名单的工具应被拒绝"""
        clean_whitelist.set_mode(WhitelistMode.ALLOWLIST)
        clean_whitelist.add_allowed("files.read")
        ok, reason = clean_whitelist.is_allowed("files.delete", {})
        assert ok is False
        assert "不在白名单" in reason

    def test_wildcard_match(self, clean_whitelist: ToolWhitelist) -> None:
        """通配符应匹配多个工具"""
        clean_whitelist.set_mode(WhitelistMode.ALLOWLIST)
        clean_whitelist.add_allowed("search.*")
        assert clean_whitelist.is_allowed("search.web", {})[0] is True
        assert clean_whitelist.is_allowed("search.code", {})[0] is True
        assert clean_whitelist.is_allowed("files.read", {})[0] is False

    def test_wildcard_question_mark(self, clean_whitelist: ToolWhitelist) -> None:
        """? 应匹配单个字符"""
        clean_whitelist.set_mode(WhitelistMode.ALLOWLIST)
        clean_whitelist.add_allowed("file?.read")
        assert clean_whitelist.is_allowed("file1.read", {})[0] is True
        assert clean_whitelist.is_allowed("file2.read", {})[0] is True
        # ? 不匹配多点
        assert clean_whitelist.is_allowed("file12.read", {})[0] is False

    def test_denied_overrides_allowed(self, clean_whitelist: ToolWhitelist) -> None:
        """黑名单优先级高于白名单"""
        clean_whitelist.add_allowed("tools.*")
        clean_whitelist.add_denied("tools.exec")
        ok, reason = clean_whitelist.is_allowed("tools.exec", {})
        assert ok is False
        assert "黑名单" in reason

    def test_param_validation_pass(self, clean_whitelist: ToolWhitelist) -> None:
        """参数校验通过"""
        clean_whitelist.add_allowed("files.write")
        clean_whitelist._config.param_schemas["files.write"] = ParamSchema(
            patterns={"path": "^/tmp/"}
        )
        ok, _ = clean_whitelist.is_allowed("files.write", {"path": "/tmp/test.txt"})
        assert ok is True

    def test_param_validation_fail(self, clean_whitelist: ToolWhitelist) -> None:
        """参数校验失败应拒绝"""
        clean_whitelist.add_allowed("files.write")
        clean_whitelist._config.param_schemas["files.write"] = ParamSchema(
            patterns={"path": "^/tmp/"}
        )
        ok, reason = clean_whitelist.is_allowed("files.write", {"path": "/etc/passwd"})
        assert ok is False
        assert "不匹配" in reason

    def test_param_validation_optional_missing(self, clean_whitelist: ToolWhitelist) -> None:
        """可选参数缺失不应报错"""
        clean_whitelist.add_allowed("files.write")
        clean_whitelist._config.param_schemas["files.write"] = ParamSchema(
            patterns={"path": "^/tmp/", "content": ".*"}
        )
        # 缺少 content 参数，应通过
        ok, _ = clean_whitelist.is_allowed("files.write", {"path": "/tmp/test.txt"})
        assert ok is True

    def test_audit_log_records_denials(self, clean_whitelist: ToolWhitelist) -> None:
        """审计日志应记录拒绝事件"""
        clean_whitelist.set_mode(WhitelistMode.DENY_ALL)
        clean_whitelist.is_allowed("any.tool", {"arg1": "value"})
        log = clean_whitelist.get_audit_log()
        assert len(log) >= 1
        assert log[-1]["allowed"] is False
        assert log[-1]["tool"] == "any.tool"

    def test_audit_log_records_allow(self, clean_whitelist: ToolWhitelist) -> None:
        """审计日志应记录允许事件"""
        clean_whitelist.set_mode(WhitelistMode.ALLOW_ALL)
        clean_whitelist.is_allowed("any.tool", {})
        log = clean_whitelist.get_audit_log()
        assert len(log) >= 1
        assert log[-1]["allowed"] is True

    def test_audit_log_max_100(self, clean_whitelist: ToolWhitelist) -> None:
        """审计日志应保留最近 100 条"""
        clean_whitelist.set_mode(WhitelistMode.ALLOW_ALL)
        for i in range(150):
            clean_whitelist.is_allowed(f"tool.{i}", {})
        log = clean_whitelist.get_audit_log(last_n=200)
        assert len(log) == 100

    def test_get_stats(self, clean_whitelist: ToolWhitelist) -> None:
        """get_stats 应返回统计"""
        clean_whitelist.add_allowed("files.read")
        clean_whitelist.add_denied("system.shutdown")
        clean_whitelist.is_allowed("files.read", {})  # allow
        clean_whitelist.is_allowed("system.shutdown", {})  # deny
        stats = clean_whitelist.get_stats()
        assert stats["mode"] == "allow_all"
        assert stats["allowed_tools_count"] == 1
        assert stats["denied_tools_count"] == 1
        assert stats["audit_total"] == 2
        assert stats["audit_allowed"] == 1
        assert stats["audit_denied"] == 1

    def test_load_from_dict(self, clean_whitelist: ToolWhitelist) -> None:
        """从字典加载配置"""
        clean_whitelist.load_from_dict(
            {
                "mode": "allowlist",
                "allowed_tools": ["files.read", "search.*"],
                "denied_tools": ["system.shutdown"],
                "param_schemas": {"files.write": {"path": "^/tmp/"}},
            }
        )
        assert clean_whitelist.config.mode == WhitelistMode.ALLOWLIST
        assert "files.read" in clean_whitelist.config.allowed_tools
        assert "system.shutdown" in clean_whitelist.config.denied_tools
        assert "files.write" in clean_whitelist.config.param_schemas

    def test_load_from_dict_invalid_mode(self, clean_whitelist: ToolWhitelist) -> None:
        """无效模式应回退到 allow_all（默认）"""
        clean_whitelist.load_from_dict({"mode": "invalid_mode"})
        assert clean_whitelist.config.mode == WhitelistMode.ALLOW_ALL

    def test_singleton(self) -> None:
        """ToolWhitelist 应为单例"""
        reset_tool_whitelist()
        w1 = get_tool_whitelist()
        w2 = get_tool_whitelist()
        assert w1 is w2
        reset_tool_whitelist()


# ═══════════════════════════════════════════════
# 4. ParamSchema 测试
# ═══════════════════════════════════════════════


class TestParamSchema:
    """参数模式校验测试"""

    def test_validate_pass(self) -> None:
        """匹配模式应通过"""
        schema = ParamSchema(patterns={"path": "^/tmp/"})
        ok, _ = schema.validate({"path": "/tmp/test"})
        assert ok is True

    def test_validate_fail(self) -> None:
        """不匹配模式应失败"""
        schema = ParamSchema(patterns={"path": "^/tmp/"})
        ok, err = schema.validate({"path": "/etc/passwd"})
        assert ok is False
        assert "path" in err

    def test_validate_missing_optional(self) -> None:
        """缺失的可选参数不报错"""
        schema = ParamSchema(patterns={"path": "^/tmp/", "content": ".*"})
        ok, _ = schema.validate({"path": "/tmp/test"})
        assert ok is True

    def test_validate_empty_patterns(self) -> None:
        """空模式应总是通过"""
        schema = ParamSchema()
        ok, _ = schema.validate({"any": "value"})
        assert ok is True


# ═══════════════════════════════════════════════
# 5. DockerSandbox 安全参数测试
# ═══════════════════════════════════════════════


class TestDockerSandboxSecurity:
    """DockerSandbox defense-in-depth 安全参数测试"""

    def test_security_args_contains_cap_drop_all(self) -> None:
        """安全参数应包含 --cap-drop=ALL"""
        from pycoder.adapters.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox()
        args = sandbox._build_security_args()
        assert "--cap-drop=ALL" in args

    def test_security_args_contains_no_new_privileges(self) -> None:
        """安全参数应包含 --security-opt=no-new-privileges"""
        from pycoder.adapters.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox()
        args = sandbox._build_security_args()
        assert "--security-opt=no-new-privileges" in args

    def test_security_args_contains_user_nobody(self) -> None:
        """安全参数应包含 --user nobody:nogroup"""
        from pycoder.adapters.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox()
        args = sandbox._build_security_args()
        assert "--user" in args
        idx = args.index("--user")
        assert args[idx + 1] == "nobody:nogroup"

    def test_security_args_contains_pids_limit(self) -> None:
        """安全参数应包含 --pids-limit"""
        from pycoder.adapters.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox()
        args = sandbox._build_security_args()
        # --pids-limit=64 或 --pids-limit 64 两种格式都可
        assert any(a.startswith("--pids-limit") for a in args)

    def test_security_args_contains_ulimit(self) -> None:
        """安全参数应包含 --ulimit nofile"""
        from pycoder.adapters.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox()
        args = sandbox._build_security_args()
        assert "--ulimit" in args
        idx = args.index("--ulimit")
        assert "nofile" in args[idx + 1]

    def test_security_args_contains_memory_swap_zero(self) -> None:
        """安全参数应包含 --memory-swap=0（禁止swap）"""
        from pycoder.adapters.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox()
        args = sandbox._build_security_args()
        assert "--memory-swap=0" in args

    def test_security_args_contains_network_none(self) -> None:
        """安全参数应包含 --network=none"""
        from pycoder.adapters.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox()
        args = sandbox._build_security_args()
        assert "--network=none" in args

    def test_security_args_contains_read_only(self) -> None:
        """安全参数应包含 --read-only"""
        from pycoder.adapters.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox()
        args = sandbox._build_security_args()
        assert "--read-only" in args

    def test_custom_memory_reflected(self) -> None:
        """自定义内存限制应反映到参数"""
        from pycoder.adapters.docker_sandbox import DockerSandbox

        sandbox = DockerSandbox(max_memory="1g")
        args = sandbox._build_security_args()
        assert "--memory=1g" in args


# ═══════════════════════════════════════════════
# 6. CodeSandbox DeprecationWarning 测试
# ═══════════════════════════════════════════════


class TestCodeSandboxDeprecation:
    """CodeSandbox 弃用警告测试"""

    def test_deprecation_warning_emitted(self) -> None:
        """实例化 CodeSandbox 应发出 DeprecationWarning"""
        from pycoder.safety.sandbox import CodeSandbox

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            CodeSandbox(timeout=1.0)
            assert len(w) >= 1
            assert any(issubclass(wi.category, DeprecationWarning) for wi in w)

    def test_deprecated_flag_set(self) -> None:
        """CodeSandbox 应有 _DEPRECATED = True 标记"""
        from pycoder.safety.sandbox import CodeSandbox

        assert CodeSandbox._DEPRECATED is True

    def test_deprecation_message_mentions_alternatives(self) -> None:
        """弃用消息应提及替代方案"""
        from pycoder.safety.sandbox import CodeSandbox

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            CodeSandbox(timeout=1.0)
            deprecations = [wi for wi in w if issubclass(wi.category, DeprecationWarning)]
            assert len(deprecations) >= 1
            msg = str(deprecations[0].message)
            assert "SubprocessSandbox" in msg or "DockerSandbox" in msg


# ═══════════════════════════════════════════════
# 7. 集成测试
# ═══════════════════════════════════════════════


class TestIntegration:
    """P0 安全增强集成测试"""

    def test_key_rotator_with_whitelist_workflow(
        self, clean_rotator: KeyRotator, clean_whitelist: ToolWhitelist
    ) -> None:
        """集成场景：Key 轮换 + 工具白名单协同工作"""
        # 1. 配置多个 Key
        clean_rotator.add_key("deepseek", "sk-key1-1234567890")
        clean_rotator.add_key("deepseek", "sk-key2-1234567890")

        # 2. 配置白名单
        clean_whitelist.add_allowed("files.read")
        clean_whitelist.add_denied("system.shutdown")

        # 3. 模拟 LLM 调用：用轮换的 Key 调用允许的工具
        key = clean_rotator.get_key("deepseek")
        assert key is not None

        ok, _ = clean_whitelist.is_allowed("files.read", {"path": "/tmp/test"})
        assert ok is True

        # 4. 模拟 Key 失效
        clean_rotator.mark_failed("deepseek", key, 401)

        # 5. 下次调用应自动切换 Key
        new_key = clean_rotator.get_key("deepseek")
        assert new_key is not None
        assert new_key != key

        # 6. 拒绝危险工具
        ok, reason = clean_whitelist.is_allowed("system.shutdown", {})
        assert ok is False
        assert "黑名单" in reason

    def test_failure_status_codes_constant(self) -> None:
        """FAILURE_STATUS_CODES 应包含 401/403/429"""
        assert 401 in FAILURE_STATUS_CODES
        assert 403 in FAILURE_STATUS_CODES
        assert 429 in FAILURE_STATUS_CODES

    def test_default_cooldown_seconds(self) -> None:
        """默认冷却时间应为 300 秒（5分钟）"""
        assert DEFAULT_COOLDOWN_SECONDS == 300.0

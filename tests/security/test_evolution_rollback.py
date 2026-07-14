"""P0-5 测试：验证 self_evolution 回滚调用链完整性

原 evolve() 方法存在两个回滚缺陷：
1. 全部 _apply_fix 失败时仍运行测试 → 测试通过会误判为"进化成功"
2. 异常路径未触发回滚 → 已应用的破坏性修改残留

已迁移至 V2 引擎，回滚机制从 _git_stash_pop 改为 _snapshot_rollback。

本测试覆盖以下场景：
- 测试失败时触发 _snapshot_rollback
- 全部 apply 失败时触发 _snapshot_rollback（新增）
- 部分失败但测试通过时不回滚（保持现有行为）
- 异常路径在 backup_ref 已创建时触发 _snapshot_rollback（新增）
- 异常路径在 backup_ref 为空时不抛错（新增）
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_engine(tmp_path: Path):
    """构造测试用 SelfEvolutionEngine 实例（V2 引擎）

    使用 tmp_path 作为项目根目录，避免污染真实项目。
    V2 引擎位于 pycoder.capabilities.self_evo.engine，V1 shim 继承自此。
    """
    from pycoder.server.self_evolution import SelfEvolutionEngine
    return SelfEvolutionEngine(project_root=tmp_path)


async def _collect_events(gen) -> list[dict]:
    """收集 async generator 所有 yield 的事件"""
    events = []
    async for event in gen:
        events.append(event)
    return events


@pytest.mark.asyncio
class TestRollbackCallChain:
    """验证回滚调用链在所有失败路径均被触发（V2: _snapshot_rollback）"""

    async def test_rollback_triggered_on_test_failure(self, tmp_path: Path):
        """测试失败时必须触发 _snapshot_rollback"""
        engine = _make_engine(tmp_path)

        # Mock 各阶段方法（V2 引擎使用 _snapshot_backup/_snapshot_rollback）
        engine._scan_project = AsyncMock(return_value="analysis content long enough")
        engine._parse_fixes = MagicMock(return_value=[
            {"file": "pycoder/foo.py", "modified": "x = 1\n", "original": "x = 0\n"}
        ])
        engine._apply_fix = AsyncMock(return_value=(True, ""))
        engine._run_tests_async = AsyncMock(return_value=(False, "test failed"))
        engine._snapshot_backup = AsyncMock(return_value="backup-123")
        engine._snapshot_rollback = AsyncMock(return_value=None)
        engine._record_learning = MagicMock()

        events = await _collect_events(engine.evolve(task_type="fix"))

        # 必须触发回滚
        assert engine._snapshot_rollback.called, "测试失败时未触发 _snapshot_rollback"
        engine._snapshot_rollback.assert_called_once_with("backup-123")
        # 应有 rolled_back 事件
        assert any(e["type"] == "rolled_back" for e in events), "缺少 rolled_back 事件"

    async def test_rollback_triggered_when_all_apply_fail(self, tmp_path: Path):
        """全部 _apply_fix 失败时必须触发回滚，且不应运行测试"""
        engine = _make_engine(tmp_path)

        engine._scan_project = AsyncMock(return_value="analysis content long enough")
        engine._parse_fixes = MagicMock(return_value=[
            {"file": "pycoder/a.py", "modified": "x = 1\n", "original": "x = 0\n"},
            {"file": "pycoder/b.py", "modified": "y = 1\n", "original": "y = 0\n"},
        ])
        # 所有 fix 应用失败
        engine._apply_fix = AsyncMock(return_value=(False, "syntax error"))
        engine._run_tests_async = AsyncMock(return_value=(True, "all pass"))
        engine._snapshot_backup = AsyncMock(return_value="backup-456")
        engine._snapshot_rollback = AsyncMock(return_value=None)
        engine._record_learning = MagicMock()

        events = await _collect_events(engine.evolve(task_type="fix"))

        # 必须触发回滚
        assert engine._snapshot_rollback.called, "全部 apply 失败时未触发 _snapshot_rollback"
        # 关键：不应运行测试（避免"未修改任何文件 → 测试通过 → 误判成功"）
        assert not engine._run_tests_async.called, (
            "全部 apply 失败时仍调用了 _run_tests_async，可能导致虚假成功"
        )
        # 应有 rolled_back 事件
        assert any(e["type"] == "rolled_back" for e in events), "缺少 rolled_back 事件"

    async def test_no_rollback_when_partial_failure_and_tests_pass(self, tmp_path: Path):
        """部分 fix 失败但测试通过时不应回滚（保持现有行为）"""
        engine = _make_engine(tmp_path)

        engine._scan_project = AsyncMock(return_value="analysis content long enough")
        engine._parse_fixes = MagicMock(return_value=[
            {"file": "pycoder/a.py", "modified": "x = 1\n", "original": "x = 0\n"},
            {"file": "pycoder/b.py", "modified": "y = 1\n", "original": "y = 0\n"},
        ])
        # 第一个成功，第二个失败
        engine._apply_fix = AsyncMock(side_effect=[(True, ""), (False, "syntax error")])
        # 测试通过（因为第一个修复成功应用）
        engine._run_tests_async = AsyncMock(return_value=(True, "all pass"))
        engine._snapshot_backup = AsyncMock(return_value="backup-789")
        engine._snapshot_rollback = AsyncMock(return_value=None)
        engine._record_learning = MagicMock()

        events = await _collect_events(engine.evolve(task_type="fix"))

        # 测试通过 → 不应回滚
        assert not engine._snapshot_rollback.called, "测试通过时不应触发回滚"
        # 应有 done 事件
        assert any(e["type"] == "done" for e in events), "缺少 done 事件"

    async def test_rollback_triggered_on_exception_after_backup(self, tmp_path: Path):
        """异常路径在 backup_ref 已创建后必须触发回滚

        场景：阶段 3 备份已创建，但 _apply_fix 抛异常
        """
        engine = _make_engine(tmp_path)

        engine._scan_project = AsyncMock(return_value="analysis content long enough")
        engine._parse_fixes = MagicMock(return_value=[
            {"file": "pycoder/a.py", "modified": "x = 1\n", "original": "x = 0\n"},
        ])
        # _apply_fix 抛异常
        engine._apply_fix = AsyncMock(side_effect=RuntimeError("disk full"))
        engine._run_tests_async = AsyncMock()
        engine._snapshot_backup = AsyncMock(return_value="backup-exc-1")
        engine._snapshot_rollback = AsyncMock(return_value=None)
        engine._record_learning = MagicMock()

        events = await _collect_events(engine.evolve(task_type="fix"))

        # 异常路径必须触发回滚（backup_ref 已在 _snapshot_backup 后设置）
        assert engine._snapshot_rollback.called, "异常路径未触发 _snapshot_rollback"
        engine._snapshot_rollback.assert_called_once_with("backup-exc-1")
        # 不应运行测试
        assert not engine._run_tests_async.called
        # 应有 error 事件
        assert any(e["type"] == "error" for e in events), "缺少 error 事件"

    async def test_rollback_triggered_on_exception_in_test_phase(self, tmp_path: Path):
        """异常路径在测试阶段抛异常时也必须回滚"""
        engine = _make_engine(tmp_path)

        engine._scan_project = AsyncMock(return_value="analysis content long enough")
        engine._parse_fixes = MagicMock(return_value=[
            {"file": "pycoder/a.py", "modified": "x = 1\n", "original": "x = 0\n"},
        ])
        engine._apply_fix = AsyncMock(return_value=(True, ""))
        # _run_tests_async 抛异常
        engine._run_tests_async = AsyncMock(side_effect=RuntimeError("pytest crashed"))
        engine._snapshot_backup = AsyncMock(return_value="backup-exc-2")
        engine._snapshot_rollback = AsyncMock(return_value=None)
        engine._record_learning = MagicMock()

        events = await _collect_events(engine.evolve(task_type="fix"))

        # 测试阶段异常后必须回滚
        assert engine._snapshot_rollback.called, "测试阶段异常时未触发 _snapshot_rollback"
        engine._snapshot_rollback.assert_called_once_with("backup-exc-2")

    async def test_no_rollback_when_exception_before_backup(self, tmp_path: Path):
        """异常路径在 backup_ref 未创建时不应尝试回滚

        场景：_scan_project 抛异常，此时 backup_ref 仍为空字符串
        """
        engine = _make_engine(tmp_path)

        engine._scan_project = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        engine._snapshot_backup = AsyncMock()
        engine._snapshot_rollback = AsyncMock()
        engine._record_learning = MagicMock()

        events = await _collect_events(engine.evolve(task_type="fix"))

        # backup 未创建 → 不应尝试回滚
        assert not engine._snapshot_backup.called, "扫描阶段不应创建备份"
        assert not engine._snapshot_rollback.called, "无备份时不应尝试回滚"
        # 应有 error 事件
        assert any(e["type"] == "error" for e in events), "缺少 error 事件"

    async def test_exception_in_rollback_does_not_swallow_original_error(self, tmp_path: Path):
        """回滚本身抛异常时不应吞掉原始错误"""
        engine = _make_engine(tmp_path)

        engine._scan_project = AsyncMock(return_value="analysis content long enough")
        engine._parse_fixes = MagicMock(return_value=[
            {"file": "pycoder/a.py", "modified": "x = 1\n", "original": "x = 0\n"},
        ])
        engine._apply_fix = AsyncMock(side_effect=RuntimeError("original error"))
        engine._snapshot_backup = AsyncMock(return_value="backup-err")
        # 回滚本身抛异常
        engine._snapshot_rollback = AsyncMock(side_effect=OSError("restore failed"))
        engine._run_tests_async = AsyncMock()
        engine._record_learning = MagicMock()

        events = await _collect_events(engine.evolve(task_type="fix"))

        # 仍应尝试回滚
        assert engine._snapshot_rollback.called
        # 应有 error 事件（包含原始错误信息）
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert "original error" in error_events[0]["message"]


@pytest.mark.asyncio
class TestRollbackStatsConsistency:
    """验证回滚统计在异常路径下的一致性（V2 引擎）"""

    async def test_exception_path_increments_rolled_back_not_failed(self, tmp_path: Path):
        """异常路径触发回滚时，rolled_back 计数应增加，failed 不应增加"""
        engine = _make_engine(tmp_path)

        engine._scan_project = AsyncMock(return_value="analysis content long enough")
        engine._parse_fixes = MagicMock(return_value=[
            {"file": "pycoder/a.py", "modified": "x = 1\n", "original": "x = 0\n"},
        ])
        engine._apply_fix = AsyncMock(side_effect=RuntimeError("boom"))
        engine._snapshot_backup = AsyncMock(return_value="backup-stats")
        engine._snapshot_rollback = AsyncMock(return_value=None)
        engine._record_learning = MagicMock()

        initial_failed = engine._stats.failed
        initial_rolled_back = engine._stats.rolled_back

        await _collect_events(engine.evolve(task_type="fix"))

        # 异常路径触发回滚 → rolled_back 应 +1，failed 不应增加
        assert engine._stats.rolled_back == initial_rolled_back + 1
        assert engine._stats.failed == initial_failed


class TestRollbackMethodCoverage:
    """验证 _snapshot_rollback 在所有回滚路径中被正确调用（V2 引擎）"""

    def test_snapshot_rollback_is_called_in_all_rollback_paths(self, tmp_path: Path):
        """静态检查：evolve 方法源码中 _snapshot_rollback 应出现在多个回滚分支"""
        import inspect
        from pycoder.server.self_evolution import SelfEvolutionEngine

        source = inspect.getsource(SelfEvolutionEngine.evolve)

        # V2 引擎回滚场景：全部 apply 失败、测试失败、异常路径
        assert "apply_failures == len(fixes)" in source, "缺少全部 apply 失败的回滚分支"
        assert "test_ok" in source, "缺少测试失败的回滚分支"
        assert "task.backup_ref" in source, "缺少异常路径的回滚分支"

        # _snapshot_rollback 应在多处出现（V2 替换了原来的 _git_stash_pop）
        rollback_count = source.count("_snapshot_rollback")
        assert rollback_count >= 3, (
            f"_snapshot_rollback 仅出现 {rollback_count} 次，应至少 3 次"
            "（apply 全失败 + 测试失败 + 异常路径）"
        )

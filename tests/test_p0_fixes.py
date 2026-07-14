"""
测试P0修复 - 验证问题#1和#2的修复是否有效
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_p0_fix1_code_exec_async_no_blocking():
    """
    FIX #1: 验证 /api/code/exec 不阻塞事件循环

    原问题：async def execute_code() 直接调用 _run_in_subprocess()（同步），阻塞事件循环
    修复：使用 await asyncio.to_thread(_run_in_subprocess, ...)

    验证方法：并发提交两个请求，确保并行执行而非串行
    """
    from pycoder.server.routers.code_exec import execute_code, CodeExecRequest

    # Mock _run_in_subprocess 让其返回指定延迟的结果
    # 第一个请求延迟2秒，第二个请求延迟1秒
    delays = [2.0, 1.0]
    call_count = [0]

    def mock_subprocess(code: str, timeout: int):
        """模拟耗时的 subprocess 调用（同步函数）

        asyncio.to_thread 期望 sync 可调用对象；async 函数传入会返回
        coroutine 而非结果，故此处必须为 sync + time.sleep。
        """
        import time as _time
        idx = call_count[0]
        call_count[0] += 1
        delay = delays[idx] if idx < len(delays) else 1.0
        print(f"[Mock] 开始执行（延迟{delay}s）")
        _time.sleep(delay)

        class Result:
            success = True
            stdout = f"Done after {delay}s"
            stderr = ""
            error_type = ""
            error_message = ""
            traceback = ""
            execution_time = delay

        return Result()

    with patch("pycoder.server.routers.code_exec._run_in_subprocess", new=mock_subprocess):
        # 并发提交两个请求
        import time
        start = time.time()

        results = await asyncio.gather(
            execute_code(CodeExecRequest(code="sleep 2", timeout=10)),
            execute_code(CodeExecRequest(code="print('fast')", timeout=10)),
        )

        elapsed = time.time() - start
        print(f"\n✅ 两个请求并行执行完成")
        print(f"   第1个请求延迟: 2.0s")
        print(f"   第2个请求延迟: 1.0s")
        print(f"   总耗时: {elapsed:.1f}s")
        print(f"   预期: ~2.1s（并行）vs ~3s（串行）")

        # 如果是真正的并行，总耗时应该约为 max(2, 1) = 2 秒
        # 如果是串行阻塞，总耗时应该约为 2 + 1 = 3 秒
        assert elapsed < 2.5, f"❌ 请求被阻塞了！总耗时{elapsed:.1f}s (预期 < 2.5s)"
        assert results[0].success
        assert results[1].success
        print("✅ FIX #1 验证成功：代码执行不阻塞事件循环")


@pytest.mark.asyncio
async def test_p0_fix2_mobile_status_fallback():
    """
    FIX #2: 验证 /api/mobile/status 优雅降级

    原问题：模块 pycoder.python.mobile_integration 不可用时导致 ImportError
    修复：使用 try/except 捕获异常，返回离线状态

    验证方法：
    1. 模块函数抛异常 → 降级返回离线状态
    2. 模块正常可用时，返回正常状态
    """
    from pycoder.server.routers.config import get_mobile_status

    # Test 1: 底层函数抛 ImportError → 降级返回离线状态
    print("\n[Test 1] 模块不可用时的降级处理")
    # 注意：config.py 内部 `from ... import get_mobile_status as get_status`
    # 会绑定当前模块属性，故须 patch mobile_integration 模块的属性。
    # 使用 AsyncMock 因 get_status() 被 await。
    with patch(
        "pycoder.python.mobile_integration.get_mobile_status",
        new=AsyncMock(side_effect=ImportError("Not found")),
    ):
        result = await get_mobile_status()

        assert result["success"] is True
        assert "platforms" in result
        print(f"✅ 降级返回: {result['platforms']['ios']['status']}")
        assert result["platforms"]["ios"]["status"] in ["offline", "error"]

    # Test 2: 模块存在时，返回正常状态
    print("\n[Test 2] 模块正常可用时的返回")

    from pycoder.python.mobile_integration import get_mobile_status as real_get_status
    status = await real_get_status()

    assert "ios" in status
    assert status["ios"]["status"] == "connected"
    print(f"✅ 正常返回: {status['ios']}")
    print("✅ FIX #2 验证成功：移动API健壮性提升")


if __name__ == "__main__":
    # 运行所有测试
    pytest.main([__file__, "-v", "-s"])

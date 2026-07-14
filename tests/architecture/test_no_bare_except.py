"""P1-3 测试：确保关键文件无裸 except Exception: pass

裸 ``except Exception: pass`` 会吞掉所有异常，导致问题难以排查。
P1-3 修复后应全部替换为具体异常类型 + 日志记录。

允许的边界兜底：
- ``except Exception as e:`` + log.xxx(...)（明确记录日志）
- WebSocket / API 边界层保留 catch-all（但必须 send error 给客户端）
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


# 匹配 ``except Exception:`` 后紧跟 ``pass``（中间可有空白）
BARE_EXCEPT_PASS_PATTERN = re.compile(
    r'except\s+Exception\s*:\s*\n\s*pass',
    re.MULTILINE,
)

# 匹配 ``except Exception as e:`` 后紧跟 ``pass``（中间可有空白）
EXCEPT_AS_PASS_PATTERN = re.compile(
    r'except\s+Exception\s+as\s+\w+\s*:\s*\n\s*pass',
    re.MULTILINE,
)


# P1-3 计划清单中列出的关键文件
CRITICAL_FILES = [
    "pycoder/server/app.py",
    "pycoder/server/chat_handler.py",
    "pycoder/server/services/agent_orchestrator.py",
    "pycoder/server/self_evolution.py",
]


@pytest.mark.parametrize("file_path", CRITICAL_FILES)
def test_no_bare_except_pass_in_critical_files(file_path):
    """关键文件中不应有 except Exception: pass 或 except Exception as e: pass"""
    path = Path(file_path)
    if not path.exists():
        pytest.skip(f"{file_path} 不存在")
    content = path.read_text(encoding="utf-8")

    bare_matches = BARE_EXCEPT_PASS_PATTERN.findall(content)
    as_matches = EXCEPT_AS_PASS_PATTERN.findall(content)
    total = len(bare_matches) + len(as_matches)

    assert total == 0, (
        f"{file_path} 中仍存在 {total} 处 except Exception: pass\n"
        f"  - except Exception: pass: {len(bare_matches)}\n"
        f"  - except Exception as e: pass: {len(as_matches)}\n"
        f"应替换为具体异常类型 + 日志记录"
    )


def test_self_evolution_specific_lines_fixed():
    """验证 P1-3 计划清单中提到的 self_evolution 关键位置已修复

    V1 的 self_evolution.py 已迁移为 V2 引擎的向后兼容 shim，
    具体异常处理在 pycoder/capabilities/self_evo/engine.py 中。
    """
    content = Path("pycoder/capabilities/self_evo/engine.py").read_text(encoding="utf-8")

    # V2 引擎中的具体异常处理
    assert "except (OSError, UnicodeDecodeError)" in content, \
        "_collect_snapshot file read 应使用具体异常"
    assert "except FileNotFoundError" in content, \
        "_run_ruff 应使用具体异常"
    assert "except (json.JSONDecodeError, OSError)" in content, \
        "_validate_evolution_token 应使用具体异常"


def test_chat_handler_specific_lines_fixed():
    """验证 chat_handler.py 关键位置已添加 logger"""
    content = Path("pycoder/server/chat_handler.py").read_text(encoding="utf-8")
    assert "logger = logging.getLogger(__name__)" in content
    assert "logger.warning(" in content
    # 不应再有 traceback.print_exc()（应改用 logger）
    assert "traceback.print_exc()" not in content


def test_agent_orchestrator_execute_tool_uses_specific_exceptions():
    """验证 _execute_tool 使用具体异常类型

    _execute_tool 已从 agent_orchestrator.py（兼容层）迁移到 agent_tools.py，
    实际异常处理在 agent_tools.py:execute_agent_tool 中。
    """
    content = Path("pycoder/server/services/agent_tools.py").read_text(encoding="utf-8")
    # 同步 subprocess.run 的超时异常为 subprocess.TimeoutExpired
    assert "subprocess.TimeoutExpired" in content
    assert "FileNotFoundError" in content
    assert "PermissionError" in content


def test_app_list_skills_uses_specific_exceptions():
    """验证 list_skills 使用具体异常类型"""
    content = Path("pycoder/server/app.py").read_text(encoding="utf-8")
    # list_skills 应使用 JSONDecodeError + OSError 而非 Exception
    assert "except (json.JSONDecodeError, OSError, ValueError)" in content

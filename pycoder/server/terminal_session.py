"""
持久化终端会话 — 保持环境变量/工作目录/命令历史
"""

from __future__ import annotations

import os
import time
from pathlib import Path


class TerminalSession:
    """单个终端会话，保持完整上下文"""

    def __init__(self, session_id: str):
        self.id = session_id
        self.cwd = os.getcwd()
        self.env: dict[str, str] = dict(os.environ)
        self.history: list[dict] = []
        self.created_at = time.time()
        self.last_active = time.time()

    def run(self, command: str) -> dict:
        """在会话上下文中执行命令"""
        import subprocess

        self.last_active = time.time()
        self.history.append(
            {
                "command": command,
                "timestamp": time.time(),
            }
        )

        try:
            r = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self.cwd,
                env=self.env,
            )
            result = {
                "success": r.returncode == 0,
                "output": r.stdout[:5000],
                "error": r.stderr[:1000],
                "exit_code": r.returncode,
                "cwd": self.cwd,
            }
            # 解析 cd 命令更新工作目录
            if command.strip().startswith("cd "):
                new_dir = command.strip()[3:].strip().strip('"').strip("'")
                if new_dir == "..":
                    self.cwd = str(Path(self.cwd).parent)
                elif os.path.isabs(new_dir):
                    self.cwd = new_dir
                else:
                    self.cwd = str(Path(self.cwd) / new_dir)
            self.history[-1]["output"] = result.get("output", "")[:200]
        except subprocess.TimeoutExpired:
            result = {"success": False, "error": "命令超时", "cwd": self.cwd}
        except Exception as e:
            result = {"success": False, "error": str(e), "cwd": self.cwd}

        return result

    def set_env(self, key: str, value: str):
        self.env[key] = value

    def export_env(self) -> str:
        return "\n".join(f"export {k}={v}" for k, v in self.env.items())

    def get_history(self, limit: int = 20) -> list[dict]:
        return self.history[-limit:]


class TerminalSessionManager:
    """持久化终端会话管理器"""

    def __init__(self):
        self._sessions: dict[str, TerminalSession] = {}

    def create(self, session_id: str = "") -> TerminalSession:
        sid = session_id or str(int(time.time()))[-8:]
        session = TerminalSession(sid)
        self._sessions[sid] = session
        return session

    def get(self, session_id: str) -> TerminalSession | None:
        if session_id not in self._sessions and len(self._sessions) < 10:
            return self.create(session_id)
        return self._sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        return [
            {
                "id": s.id,
                "cwd": s.cwd,
                "history_count": len(s.history),
                "created_at": s.created_at,
            }
            for s in self._sessions.values()
        ]

    def run(self, session_id: str, command: str) -> dict:
        session = self.get(session_id)
        if not session:
            session = self.create(session_id)
        return session.run(command)

    def cleanup(self, max_age: float = 3600):
        now = time.time()
        for sid, s in list(self._sessions.items()):
            if now - s.last_active > max_age:
                del self._sessions[sid]


_terminal_mgr: TerminalSessionManager | None = None


def get_terminal_manager() -> TerminalSessionManager:
    global _terminal_mgr
    if _terminal_mgr is None:
        _terminal_mgr = TerminalSessionManager()
    return _terminal_mgr

"""API Key 轮换管理器 — 多 Key 轮询 + 自动失效检测

特性:
- 每个 provider 支持配置多个 API Key（list）
- 轮询 (round-robin) 或随机选择 Key，分散请求压力
- 自动检测 401/403 失效，标记并切换到下一个 Key
- 失效 Key 冷却期（默认 5 分钟）后自动重试
- 线程安全的单例模式

用法:
    from pycoder.providers.key_rotator import KeyRotator

    rotator = KeyRotator()
    rotator.add_key("deepseek", "sk-key1")
    rotator.add_key("deepseek", "sk-key2")

    key = rotator.get_key("deepseek")  # 轮询返回
    rotator.mark_failed("deepseek", key, status_code=401)  # 标记失效
    key2 = rotator.get_key("deepseek")  # 自动切换到下一个
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)


# 失效冷却时间（秒）
DEFAULT_COOLDOWN_SECONDS = 300.0
"""失效 Key 的冷却期，超过此时间后自动重试"""

# 触发失效的 HTTP 状态码
FAILURE_STATUS_CODES = {401, 403, 429}
"""标记 Key 失效的状态码（401未授权/403禁止/429限流）"""


@dataclass
class KeyState:
    """单个 API Key 的状态"""

    key: str
    """API Key 值"""

    provider: str
    """所属 provider"""

    failed_count: int = 0
    """连续失败次数"""

    last_failed_at: float = 0.0
    """最后失败时间戳"""

    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
    """冷却期（秒）"""

    disabled: bool = False
    """是否永久禁用（连续失败超过阈值）"""

    def __post_init__(self) -> None:
        """敏感数据脱敏的 repr"""
        self._masked = self._mask()

    def _mask(self) -> str:
        """脱敏显示（只显示前4后4）"""
        if len(self.key) <= 12:
            return "***"
        return f"{self.key[:4]}...{self.key[-4:]}"

    @property
    def masked(self) -> str:
        """脱敏后的 Key（用于日志）"""
        return self._masked

    @property
    def is_available(self) -> bool:
        """是否可用（未禁用且冷却期已过）"""
        if self.disabled:
            return False
        if self.failed_count == 0:
            return True
        # 冷却期内不可用
        elapsed = time.monotonic() - self.last_failed_at
        return elapsed >= self.cooldown_seconds

    def mark_failed(self, status_code: int = 401) -> None:
        """标记失败"""
        self.failed_count += 1
        self.last_failed_at = time.monotonic()
        # 连续失败 5 次永久禁用
        if self.failed_count >= 5:
            self.disabled = True
            logger.warning(
                "key_disabled provider=%s key=%s failed_count=%d",
                self.provider,
                self.masked,
                self.failed_count,
            )
        else:
            logger.info(
                "key_marked_failed provider=%s key=%s status=%d failed_count=%d",
                self.provider,
                self.masked,
                status_code,
                self.failed_count,
            )

    def mark_success(self) -> None:
        """标记成功（重置失败计数）"""
        if self.failed_count > 0:
            self.failed_count = 0
            self.last_failed_at = 0.0
            logger.debug("key_recovered provider=%s key=%s", self.provider, self.masked)


class KeyRotator:
    """API Key 轮换管理器（线程安全单例）

    支持:
    - 每个 provider 多个 Key
    - 轮询 (round-robin) 或随机选择
    - 失效检测 + 冷却 + 自动恢复
    - 永久禁用连续失败的 Key
    """

    _instance: KeyRotator | None = None
    _lock = threading.Lock()

    def __new__(cls) -> KeyRotator:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._states: dict[str, list[KeyState]] = {}
        """provider → KeyState 列表"""
        self._rr_index: dict[str, int] = {}
        """provider → 轮询索引"""
        self._mutex = threading.Lock()

    # ── Key 管理 ──

    def add_key(
        self,
        provider: str,
        key: str,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        """添加一个 Key 到 provider 的轮换池"""
        with self._mutex:
            if provider not in self._states:
                self._states[provider] = []
                self._rr_index[provider] = 0
            # 去重
            for state in self._states[provider]:
                if state.key == key:
                    return  # 已存在
            self._states[provider].append(
                KeyState(key=key, provider=provider, cooldown_seconds=cooldown_seconds)
            )
            logger.debug(
                "key_added provider=%s key=%s total=%d",
                provider,
                key[:4] + "..." + key[-4:],
                len(self._states[provider]),
            )

    def remove_key(self, provider: str, key: str) -> None:
        """移除指定 Key"""
        with self._mutex:
            if provider not in self._states:
                return
            self._states[provider] = [s for s in self._states[provider] if s.key != key]
            if not self._states[provider]:
                del self._states[provider]
                self._rr_index.pop(provider, None)

    def clear(self) -> None:
        """清空所有 Key（用于测试）"""
        with self._mutex:
            self._states.clear()
            self._rr_index.clear()

    def get_keys(self, provider: str) -> list[str]:
        """获取 provider 的所有 Key（包括失效的）"""
        with self._mutex:
            if provider not in self._states:
                return []
            return [s.key for s in self._states[provider]]

    def get_available_keys(self, provider: str) -> list[str]:
        """获取 provider 的所有可用 Key（不包括失效/冷却中的）"""
        with self._mutex:
            if provider not in self._states:
                return []
            return [s.key for s in self._states[provider] if s.is_available]

    # ── Key 选择 ──

    def get_key(
        self,
        provider: str,
        strategy: Literal["round_robin", "random"] = "round_robin",
    ) -> str | None:
        """获取一个可用的 Key

        Args:
            provider: provider 名称
            strategy: 选择策略
                - "round_robin": 轮询（默认）
                - "random": 随机

        Returns:
            API Key 字符串，若无可用 Key 返回 None
        """
        with self._mutex:
            states = self._states.get(provider, [])
            if not states:
                return None

            available = [s for s in states if s.is_available]
            if not available:
                logger.warning(
                    "no_available_key provider=%s total=%d all_failed=%d",
                    provider,
                    len(states),
                    sum(1 for s in states if s.failed_count > 0),
                )
                return None

            if strategy == "random":
                return random.choice(available).key

            # round_robin
            idx = self._rr_index.get(provider, 0) % len(available)
            self._rr_index[provider] = (idx + 1) % len(available)
            return available[idx].key

    # ── 失效检测 ──

    def mark_failed(self, provider: str, key: str, status_code: int = 401) -> None:
        """标记 Key 失败（自动切换到下一个）"""
        with self._mutex:
            states = self._states.get(provider, [])
            for state in states:
                if state.key == key:
                    state.mark_failed(status_code)
                    return

    def mark_success(self, provider: str, key: str) -> None:
        """标记 Key 调用成功（重置失败计数）"""
        with self._mutex:
            states = self._states.get(provider, [])
            for state in states:
                if state.key == key:
                    state.mark_success()
                    return

    def should_rotate(self, status_code: int) -> bool:
        """判断 HTTP 状态码是否应触发 Key 轮换"""
        return status_code in FAILURE_STATUS_CODES

    # ── 状态查询 ──

    def get_status(self) -> dict[str, list[dict]]:
        """获取所有 Key 的状态（用于调试/监控）"""
        with self._mutex:
            result: dict[str, list[dict]] = {}
            for provider, states in self._states.items():
                result[provider] = [
                    {
                        "key": s.masked,
                        "available": s.is_available,
                        "failed_count": s.failed_count,
                        "disabled": s.disabled,
                        "last_failed_at": s.last_failed_at,
                    }
                    for s in states
                ]
            return result

    def get_provider_status(self, provider: str) -> list[dict]:
        """获取指定 provider 的 Key 状态"""
        return self.get_status().get(provider, [])


# ── 模块级单例 ──

_rotator: KeyRotator | None = None


def get_key_rotator() -> KeyRotator:
    """获取全局 KeyRotator 单例"""
    global _rotator
    if _rotator is None:
        _rotator = KeyRotator()
    return _rotator


def reset_key_rotator() -> None:
    """重置单例（用于测试）"""
    global _rotator
    if _rotator is not None:
        _rotator.clear()
    _rotator = None

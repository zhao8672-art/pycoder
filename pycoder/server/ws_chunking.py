"""WebSocket 消息分块与重组 — 解决大消息传输限制

职责:
    1. 将超出单帧大小限制的消息切分为多个分块
    2. 接收端按 id 重组分块, 自动处理乱序与缺失
    3. 校验单条消息的总大小上限, 防止恶意超长消息

设计原则:
    - 无状态切分: chunk_message 只关心输入数据
    - 状态化重组: MessageChunker 按 chunk_id 维护分片缓冲区
    - 失败安全: 任何校验失败返回 None 或抛 ValueError

WebSocket 帧格式:
    原始消息过大 (超过 chunk_size 字节) 时切分为:
    {
        "type": "chunk",
        "id": "<uuid>",      # 消息唯一标识
        "seq": 0,            # 分块序号 (从 0 开始)
        "total": 3,          # 分块总数
        "data": "base64..."  # 该分块的载荷 (base64 编码)
    }
"""
from __future__ import annotations

import base64
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class ChunkConfig:
    """分块配置"""

    chunk_size: int = 16384
    max_message_size: int = 4 * 1024 * 1024  # 4 MiB

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError(f"chunk_size must be positive, got {self.chunk_size}")
        if self.max_message_size <= 0:
            raise ValueError(
                f"max_message_size must be positive, got {self.max_message_size}"
            )
        if self.chunk_size > self.max_message_size:
            raise ValueError("chunk_size cannot exceed max_message_size")


_DEFAULT_CONFIG = ChunkConfig()


def _encode_payload(payload: bytes) -> str:
    """将字节载荷编码为 base64 字符串, 便于在 JSON 中传输"""
    return base64.b64encode(payload).decode("ascii")


def _decode_payload(encoded: str) -> bytes:
    """从 base64 字符串还原字节载荷"""
    try:
        return base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError(f"invalid base64 chunk payload: {exc}") from exc


def _serialize_message(data: dict) -> bytes:
    """将 dict 序列化为 UTF-8 JSON 字节流"""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def chunk_message(data: dict, config: ChunkConfig | None = None) -> list[dict]:
    """将消息切分为 WebSocket 分块

    当消息的 JSON 序列化结果不超过 chunk_size 时, 返回单条 "passthrough" 消息;
    否则按 chunk_size 切分为多个分块, 每块格式:
        {"type": "chunk", "id": ..., "seq": i, "total": N, "data": "..."}

    Args:
        data: 待发送的消息字典
        config: 分块配置 (None 使用默认)

    Returns:
        分块消息列表; 单条 passthrough 消息时长度=1 且 type=passthrough

    Raises:
        ValueError: 序列化后超过 max_message_size
    """
    cfg = config or _DEFAULT_CONFIG
    payload = _serialize_message(data)
    total_size = len(payload)

    if total_size > cfg.max_message_size:
        raise ValueError(
            f"message size {total_size} exceeds max_message_size {cfg.max_message_size}"
        )

    if total_size <= cfg.chunk_size:
        # 小消息直接透传, 不带分块元信息
        return [{"type": "passthrough", "data": data}]

    chunk_id = uuid.uuid4().hex
    encoded = _encode_payload(payload)
    total = (len(encoded) + cfg.chunk_size - 1) // cfg.chunk_size

    chunks: list[dict] = []
    for seq in range(total):
        start = seq * cfg.chunk_size
        end = start + cfg.chunk_size
        chunks.append(
            {
                "type": "chunk",
                "id": chunk_id,
                "seq": seq,
                "total": total,
                "data": encoded[start:end],
            }
        )
    return chunks


def reassemble_chunks(chunks: list[dict], config: ChunkConfig | None = None) -> dict | None:
    """按 id 重组分块消息

    Args:
        chunks: 分块消息列表 (可乱序)
        config: 分块配置 (None 使用默认)

    Returns:
        重组后的原始消息字典; 若分块不完整 (缺块/格式错误) 返回 None

    Raises:
        ValueError: 任一分块结构非法或超过 max_message_size
    """
    cfg = config or _DEFAULT_CONFIG
    if not chunks:
        return None

    first = chunks[0]
    if first.get("type") != "chunk":
        return None

    chunk_id = first.get("id")
    total = first.get("total")
    if not chunk_id or not isinstance(total, int) or total <= 0:
        return None

    by_seq: dict[int, str] = {}
    for c in chunks:
        if c.get("type") != "chunk" or c.get("id") != chunk_id:
            return None
        seq = c.get("seq")
        if not isinstance(seq, int) or seq < 0 or seq >= total:
            return None
        if c.get("total") != total:
            return None
        if "data" not in c or not isinstance(c["data"], str):
            return None
        if seq in by_seq:
            return None  # 重复 seq
        by_seq[seq] = c["data"]

    if len(by_seq) != total:
        return None

    encoded = "".join(by_seq[i] for i in range(total))
    payload = _decode_payload(encoded)
    if len(payload) > cfg.max_message_size:
        raise ValueError(
            f"reassembled message size {len(payload)} exceeds max_message_size "
            f"{cfg.max_message_size}"
        )

    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"reassembled payload is not valid JSON: {exc}") from exc


@dataclass
class _Pending:
    """待重组的分片缓冲区"""

    total: int
    received: set[int] = field(default_factory=set)
    pieces: dict[int, str] = field(default_factory=dict)
    created_at: float = 0.0


class MessageChunker:
    """WebSocket 分块重组器 — 按 chunk id 维护多个并发消息的缓冲区

    用法:
        chunker = MessageChunker()
        for chunk in incoming_chunks:
            chunker.add(chunk)
            msg = chunker.get_complete()
            if msg is not None:
                handle(msg)
    """

    def __init__(self, config: ChunkConfig | None = None) -> None:
        self._config = config or _DEFAULT_CONFIG
        self._pending: dict[str, _Pending] = defaultdict(lambda: _Pending(total=0))

    def add(self, chunk: dict) -> None:
        """接收一个分块并存入对应 id 的缓冲区

        Args:
            chunk: 形如 {"type": "chunk", "id": ..., "seq": i, "total": N, "data": "..."}

        Raises:
            ValueError: 分块结构非法
        """
        if chunk.get("type") != "chunk":
            raise ValueError("chunk must have type='chunk'")
        chunk_id = chunk.get("id")
        seq = chunk.get("seq")
        total = chunk.get("total")
        data = chunk.get("data")
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError("chunk missing 'id'")
        if not isinstance(seq, int) or seq < 0:
            raise ValueError(f"invalid chunk seq={seq!r}")
        if not isinstance(total, int) or total <= 0:
            raise ValueError(f"invalid chunk total={total!r}")
        if seq >= total:
            raise ValueError(f"chunk seq={seq} >= total={total}")
        if not isinstance(data, str):
            raise ValueError("chunk 'data' must be a string")

        pending = self._pending[chunk_id]
        pending.total = total
        pending.received.add(seq)
        pending.pieces[seq] = data

    def get_complete(self) -> dict | None:
        """从任意已完成的缓冲区取出一条完整消息并移除该缓冲区

        Returns:
            重组后的字典; 无已完成消息时返回 None

        Raises:
            ValueError: 重组失败 (JSON 解析错误 / 超过 max_message_size)
        """
        for chunk_id in list(self._pending.keys()):
            pending = self._pending[chunk_id]
            if len(pending.received) != pending.total:
                continue

            encoded = "".join(pending.pieces[i] for i in range(pending.total))
            payload = _decode_payload(encoded)
            if len(payload) > self._config.max_message_size:
                del self._pending[chunk_id]
                raise ValueError(
                    f"reassembled message size {len(payload)} exceeds "
                    f"max_message_size {self._config.max_message_size}"
                )
            try:
                msg = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                del self._pending[chunk_id]
                raise ValueError(f"reassembled payload is not valid JSON: {exc}") from exc
            del self._pending[chunk_id]
            return msg
        return None

    def pending_count(self) -> int:
        """当前待重组的消息数"""
        return len(self._pending)

    def has_complete(self) -> bool:
        """是否存在已收齐所有分块的消息"""
        for pending in self._pending.values():
            if len(pending.received) == pending.total:
                return True
        return False

    def clear(self) -> None:
        """清空所有缓冲区"""
        self._pending.clear()


__all__ = [
    "ChunkConfig",
    "chunk_message",
    "reassemble_chunks",
    "MessageChunker",
]

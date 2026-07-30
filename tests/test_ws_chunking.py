"""WebSocket 消息分块与重组测试"""
from __future__ import annotations

import base64

import pytest

from pycoder.server.ws_chunking import (
    ChunkConfig,
    MessageChunker,
    chunk_message,
    reassemble_chunks,
)

# ════════════════════════════════════════════════════════
# ChunkConfig 测试
# ════════════════════════════════════════════════════════


class TestChunkConfig:
    """ChunkConfig 数据类测试"""

    def test_default_values(self) -> None:
        cfg = ChunkConfig()
        assert cfg.chunk_size == 16384
        assert cfg.max_message_size == 4 * 1024 * 1024

    def test_custom_values(self) -> None:
        cfg = ChunkConfig(chunk_size=512, max_message_size=1024)
        assert cfg.chunk_size == 512
        assert cfg.max_message_size == 1024

    def test_invalid_chunk_size(self) -> None:
        with pytest.raises(ValueError, match="chunk_size must be positive"):
            ChunkConfig(chunk_size=0)

    def test_invalid_max_size(self) -> None:
        with pytest.raises(ValueError, match="max_message_size must be positive"):
            ChunkConfig(max_message_size=0)

    def test_chunk_size_exceeds_max(self) -> None:
        with pytest.raises(ValueError, match="chunk_size cannot exceed max_message_size"):
            ChunkConfig(chunk_size=2048, max_message_size=1024)


# ════════════════════════════════════════════════════════
# chunk_message 测试
# ════════════════════════════════════════════════════════


class TestChunkMessage:
    """chunk_message 切分函数测试"""

    def test_small_message_passthrough(self) -> None:
        """小消息直接透传"""
        data = {"type": "ping", "value": 42}
        chunks = chunk_message(data)
        assert len(chunks) == 1
        assert chunks[0]["type"] == "passthrough"
        assert chunks[0]["data"] == data

    def test_large_message_split(self) -> None:
        """大消息被切分为多块"""
        cfg = ChunkConfig(chunk_size=128, max_message_size=1024 * 1024)
        data = {"type": "blob", "text": "x" * 4096}
        chunks = chunk_message(data, cfg)
        assert len(chunks) > 1
        for c in chunks:
            assert c["type"] == "chunk"
            assert c["total"] == len(chunks)
            assert "id" in c
            assert 0 <= c["seq"] < c["total"]
            assert isinstance(c["data"], str)

    def test_message_exceeds_max_size_raises(self) -> None:
        """序列化结果超过 max_message_size 时抛错"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=128)
        data = {"text": "x" * 1024}
        with pytest.raises(ValueError, match="exceeds max_message_size"):
            chunk_message(data, cfg)

    def test_chunks_in_order(self) -> None:
        """分块按 seq 升序输出"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        data = {"text": "y" * 1000}
        chunks = chunk_message(data, cfg)
        for i, c in enumerate(chunks):
            assert c["seq"] == i

    def test_chunk_data_is_base64(self) -> None:
        """分块 data 字段是合法 base64"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        data = {"text": "z" * 500}
        chunks = chunk_message(data, cfg)
        for c in chunks:
            base64.b64decode(c["data"].encode("ascii"), validate=True)

    def test_all_chunks_share_same_id(self) -> None:
        """同一消息的所有分块 id 相同"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        data = {"text": "a" * 500}
        chunks = chunk_message(data, cfg)
        ids = {c["id"] for c in chunks}
        assert len(ids) == 1


# ════════════════════════════════════════════════════════
# reassemble_chunks 测试
# ════════════════════════════════════════════════════════


class TestReassembleChunks:
    """reassemble_chunks 重组函数测试"""

    def test_round_trip_in_order(self) -> None:
        """按顺序分块后能正确重组"""
        cfg = ChunkConfig(chunk_size=128, max_message_size=1024 * 1024)
        original = {"type": "blob", "payload": "x" * 2048, "n": 12345}
        chunks = chunk_message(original, cfg)
        # chunk_message 切出的是分块, 直接重组
        result = reassemble_chunks(chunks, cfg)
        assert result == original

    def test_round_trip_out_of_order(self) -> None:
        """乱序分块也能正确重组"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        original = {"text": "b" * 1000}
        chunks = chunk_message(original, cfg)
        shuffled = list(reversed(chunks))
        result = reassemble_chunks(shuffled, cfg)
        assert result == original

    def test_incomplete_chunks_returns_none(self) -> None:
        """缺块时返回 None"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        original = {"text": "c" * 1000}
        chunks = chunk_message(original, cfg)
        # 去掉最后一块
        truncated = chunks[:-1]
        result = reassemble_chunks(truncated, cfg)
        assert result is None

    def test_empty_chunks_returns_none(self) -> None:
        """空列表返回 None"""
        assert reassemble_chunks([]) is None

    def test_non_chunk_returns_none(self) -> None:
        """非分块消息 (type != 'chunk') 返回 None"""
        chunks = [{"type": "passthrough", "data": {"x": 1}}]
        assert reassemble_chunks(chunks) is None

    def test_missing_id_returns_none(self) -> None:
        """缺少 id 字段返回 None"""
        chunks = [{"type": "chunk", "seq": 0, "total": 1, "data": "AA=="}]
        assert reassemble_chunks(chunks) is None

    def test_invalid_total_returns_none(self) -> None:
        """非法 total 字段返回 None"""
        chunks = [
            {"type": "chunk", "id": "x", "seq": 0, "total": 0, "data": "AA=="},
        ]
        assert reassemble_chunks(chunks) is None

    def test_oversize_reassembly_raises(self) -> None:
        """重组后超过 max_message_size 抛错"""
        # 先用宽松限制切分, 然后用更严格限制重组
        loose = ChunkConfig(chunk_size=64, max_message_size=8 * 1024)
        original = {"text": "d" * 500}
        chunks = chunk_message(original, loose)
        # 用更小的 max_message_size 重组
        strict = ChunkConfig(chunk_size=64, max_message_size=64)
        with pytest.raises(ValueError, match="exceeds max_message_size"):
            reassemble_chunks(chunks, strict)

    def test_corrupted_base64_raises(self) -> None:
        """非法的 base64 载荷抛错"""
        chunks = [
            {"type": "chunk", "id": "x", "seq": 0, "total": 1, "data": "!!!not-base64!!!"}
        ]
        with pytest.raises(ValueError, match="invalid base64"):
            reassemble_chunks(chunks)

    def test_mismatched_id_returns_none(self) -> None:
        """不同 id 的分块混在一起返回 None"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        original = {"text": "e" * 500}
        chunks_a = chunk_message(original, cfg)
        chunks_b = chunk_message({"other": True}, cfg)
        # 拼接不同 id 的分块
        mixed = chunks_a + chunks_b[:1]
        result = reassemble_chunks(mixed, cfg)
        assert result is None

    def test_duplicate_seq_returns_none(self) -> None:
        """同一 seq 重复出现返回 None"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        original = {"text": "f" * 500}
        chunks = chunk_message(original, cfg)
        # 复制首块
        dup = [chunks[0]] + chunks
        result = reassemble_chunks(dup, cfg)
        assert result is None

    def test_invalid_json_raises(self) -> None:
        """重组结果不是合法 JSON 抛错"""
        bad = base64.b64encode(b"not-json").decode("ascii")
        chunks = [{"type": "chunk", "id": "x", "seq": 0, "total": 1, "data": bad}]
        with pytest.raises(ValueError, match="not valid JSON"):
            reassemble_chunks(chunks)


# ════════════════════════════════════════════════════════
# MessageChunker 测试
# ════════════════════════════════════════════════════════


class TestMessageChunker:
    """MessageChunker 状态化重组器测试"""

    def test_get_complete_returns_none_initially(self) -> None:
        chunker = MessageChunker()
        assert chunker.get_complete() is None
        assert chunker.pending_count() == 0

    def test_feed_in_order(self) -> None:
        """按序输入分块, get_complete 返回重组结果"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        original = {"text": "g" * 500}
        chunks = chunk_message(original, cfg)
        chunker = MessageChunker(cfg)
        for c in chunks:
            chunker.add(c)
        assert chunker.has_complete() is True
        result = chunker.get_complete()
        assert result == original
        # 缓冲区应已清空
        assert chunker.pending_count() == 0

    def test_feed_out_of_order(self) -> None:
        """乱序输入也能重组"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        original = {"text": "h" * 500}
        chunks = chunk_message(original, cfg)
        chunker = MessageChunker(cfg)
        for c in reversed(chunks):
            chunker.add(c)
        result = chunker.get_complete()
        assert result == original

    def test_partial_returns_none(self) -> None:
        """未收齐所有分块时 get_complete 返回 None"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        original = {"text": "i" * 500}
        chunks = chunk_message(original, cfg)
        chunker = MessageChunker(cfg)
        for c in chunks[:-1]:
            chunker.add(c)
        assert chunker.get_complete() is None
        assert chunker.has_complete() is False
        assert chunker.pending_count() == 1

    def test_multiple_concurrent_messages(self) -> None:
        """同时跟踪多条消息的缓冲区"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        m1 = {"id": 1, "text": "j" * 400}
        m2 = {"id": 2, "text": "k" * 400}
        c1 = chunk_message(m1, cfg)
        c2 = chunk_message(m2, cfg)
        chunker = MessageChunker(cfg)
        # 交叉喂入
        for a, b in zip(c1, c2, strict=True):
            chunker.add(a)
            chunker.add(b)
        assert chunker.pending_count() == 2
        results: list[dict] = []
        for _ in range(2):
            r = chunker.get_complete()
            assert r is not None
            results.append(r)
        assert m1 in results
        assert m2 in results
        assert chunker.pending_count() == 0

    def test_invalid_chunk_type_raises(self) -> None:
        chunker = MessageChunker()
        with pytest.raises(ValueError, match="type='chunk'"):
            chunker.add({"type": "passthrough", "data": {}})

    def test_invalid_seq_raises(self) -> None:
        chunker = MessageChunker()
        with pytest.raises(ValueError, match="invalid chunk seq"):
            chunker.add({"type": "chunk", "id": "a", "seq": -1, "total": 2, "data": "AA=="})

    def test_seq_out_of_range_raises(self) -> None:
        chunker = MessageChunker()
        with pytest.raises(ValueError, match="seq=5 >= total=2"):
            chunker.add({"type": "chunk", "id": "a", "seq": 5, "total": 2, "data": "AA=="})

    def test_invalid_total_raises(self) -> None:
        chunker = MessageChunker()
        with pytest.raises(ValueError, match="invalid chunk total"):
            chunker.add({"type": "chunk", "id": "a", "seq": 0, "total": 0, "data": "AA=="})

    def test_invalid_data_raises(self) -> None:
        chunker = MessageChunker()
        with pytest.raises(ValueError, match="data' must be a string"):
            chunker.add({"type": "chunk", "id": "a", "seq": 0, "total": 1, "data": 123})

    def test_clear(self) -> None:
        chunker = MessageChunker()
        chunker.add({"type": "chunk", "id": "a", "seq": 0, "total": 3, "data": "AA=="})
        chunker.add({"type": "chunk", "id": "b", "seq": 0, "total": 2, "data": "AA=="})
        assert chunker.pending_count() == 2
        chunker.clear()
        assert chunker.pending_count() == 0

    def test_oversize_reassembly_raises_and_clears(self) -> None:
        """重组结果超限时抛错并清空对应缓冲区"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024)
        original = {"text": "l" * 800}
        chunks = chunk_message(original, cfg)
        # 切完后再用更严格的 max_message_size 重组
        strict = ChunkConfig(chunk_size=64, max_message_size=64)
        chunker = MessageChunker(strict)
        for c in chunks:
            chunker.add(c)
        with pytest.raises(ValueError, match="exceeds max_message_size"):
            chunker.get_complete()
        # 缓冲区应已清空
        assert chunker.pending_count() == 0


# ════════════════════════════════════════════════════════
# 集成测试
# ════════════════════════════════════════════════════════


class TestChunkingIntegration:
    """chunk_message + reassemble 集成测试"""

    def test_chinese_payload(self) -> None:
        """中文字符负载正确切分与重组"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        original = {"msg": "你好世界！" * 200}
        chunks = chunk_message(original, cfg)
        result = reassemble_chunks(chunks, cfg)
        assert result == original

    def test_nested_structure(self) -> None:
        """嵌套结构正确处理"""
        cfg = ChunkConfig(chunk_size=64, max_message_size=1024 * 1024)
        original = {
            "type": "tree",
            "children": [{"name": f"node_{i}", "value": i * 2} for i in range(100)],
        }
        chunks = chunk_message(original, cfg)
        result = reassemble_chunks(chunks, cfg)
        assert result == original

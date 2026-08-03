"""F3: 语音输入 STT API 单元测试

不依赖真实 faster-whisper 模型: 通过 monkeypatch 替换推理函数,
覆盖依赖缺失 (501) / 非法内容类型 (400) / 大小超限 (400) /
时长超限 (400) / multipart 成功 (200) / base64 JSON 成功 (200)。
"""

from __future__ import annotations

import base64
import io
import wave

import pytest
from fastapi.testclient import TestClient

from pycoder.server.routers import voice_api


def _make_wav_bytes(duration_ms: int = 500, rate: int = 16000) -> bytes:
    """生成指定时长的 16-bit 单声道静音 WAV 字节"""
    frames = b"\x00\x00" * int(rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return buf.getvalue()


@pytest.fixture
def client():
    """仅挂载 voice 路由的独立 FastAPI 测试客户端 (无需 API Key)"""
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(voice_api.router)
    return TestClient(app)


def test_transcribe_returns_501_without_faster_whisper(client, monkeypatch):
    """faster-whisper 缺失时应返回 501 + 明确错误信息"""

    def _raise_unavailable(data: bytes, suffix: str, language: str | None = None):
        raise voice_api.VoiceEngineUnavailableError("未安装 faster-whisper, 后端语音识别不可用")

    monkeypatch.setattr(voice_api, "transcribe_audio_bytes", _raise_unavailable)
    resp = client.post(
        "/api/voice/transcribe",
        files={"file": ("sample.wav", _make_wav_bytes(), "audio/wav")},
    )
    assert resp.status_code == 501
    assert "faster-whisper" in resp.json()["detail"]


def test_transcribe_rejects_invalid_content_type(client):
    """非音频内容类型应返回 400"""
    resp = client.post(
        "/api/voice/transcribe",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 400
    assert "不支持" in resp.json()["detail"]


def test_transcribe_rejects_oversized(client):
    """超过大小上限的音频应返回 400"""
    big = b"\x00" * ((voice_api.MAX_AUDIO_SIZE_MB + 1) * 1024 * 1024)
    resp = client.post(
        "/api/voice/transcribe",
        files={"file": ("big.wav", big, "audio/wav")},
    )
    assert resp.status_code == 400
    assert "过大" in resp.json()["detail"]


def test_transcribe_rejects_overlong_wav(client):
    """超过时长上限的 WAV 应返回 400 (推理前拦截)"""
    wav = _make_wav_bytes(duration_ms=voice_api.MAX_DURATION_MS + 1000)
    resp = client.post(
        "/api/voice/transcribe",
        files={"file": ("long.wav", wav, "audio/wav")},
    )
    assert resp.status_code == 400
    assert "过长" in resp.json()["detail"]


def test_transcribe_rejects_empty_audio(client):
    """空音频应返回 400"""
    resp = client.post(
        "/api/voice/transcribe",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    assert resp.status_code == 400
    assert "为空" in resp.json()["detail"]


def test_transcribe_rejects_bad_request_type(client):
    """既非 multipart 也非 JSON 的请求应返回 415"""
    resp = client.post(
        "/api/voice/transcribe",
        content=b"raw-bytes",
        headers={"content-type": "text/plain"},
    )
    assert resp.status_code == 415


def test_transcribe_rejects_invalid_base64(client):
    """非法 base64 的 JSON 请求应返回 400"""
    resp = client.post(
        "/api/voice/transcribe",
        json={"audio_base64": "not!valid!base64!@#$"},
    )
    assert resp.status_code == 400
    assert "base64" in resp.json()["detail"]


def test_transcribe_success_with_mock_engine(client, monkeypatch):
    """mock faster-whisper 成功路径: multipart 上传返回 text/language/duration_ms"""

    def _fake_transcribe(data: bytes, suffix: str, language: str | None = None):
        assert data  # 确认收到了音频字节
        assert suffix == ".wav"
        return voice_api.TranscribeResponse(text="你好世界", language="zh", duration_ms=500)

    monkeypatch.setattr(voice_api, "transcribe_audio_bytes", _fake_transcribe)
    resp = client.post(
        "/api/voice/transcribe",
        files={"file": ("sample.wav", _make_wav_bytes(), "audio/wav")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "你好世界"
    assert data["language"] == "zh"
    assert data["duration_ms"] == 500


def test_transcribe_success_base64_json(client, monkeypatch):
    """mock faster-whisper 成功路径: JSON base64 提交 + 指定语言"""

    def _fake_transcribe(data: bytes, suffix: str, language: str | None = None):
        assert language == "zh"  # 语言参数透传
        return voice_api.TranscribeResponse(text="hello", language="zh", duration_ms=500)

    monkeypatch.setattr(voice_api, "transcribe_audio_bytes", _fake_transcribe)
    wav_b64 = base64.b64encode(_make_wav_bytes()).decode("ascii")
    resp = client.post(
        "/api/voice/transcribe",
        json={"audio_base64": wav_b64, "content_type": "audio/wav", "language": "zh"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "hello"
    assert data["language"] == "zh"
    assert "duration_ms" in data


def test_transcribe_all_allowed_types(client, monkeypatch):
    """所有允许的音频类型应通过类型校验 (mock 引擎)"""

    def _fake_transcribe(data: bytes, suffix: str, language: str | None = None):
        return voice_api.TranscribeResponse(text="ok", language="zh", duration_ms=0)

    monkeypatch.setattr(voice_api, "transcribe_audio_bytes", _fake_transcribe)
    for content_type in sorted(voice_api.ALLOWED_AUDIO_TYPES):
        resp = client.post(
            "/api/voice/transcribe",
            files={"file": ("audio.bin", b"\x00" * 64, content_type)},
        )
        assert resp.status_code == 200, f"类型 {content_type} 应被接受"


def test_transcribe_infers_type_from_extension(client, monkeypatch):
    """content_type 为 octet-stream 时应按扩展名推断音频类型"""

    def _fake_transcribe(data: bytes, suffix: str, language: str | None = None):
        assert suffix == ".webm"
        return voice_api.TranscribeResponse(text="ok", language="zh", duration_ms=0)

    monkeypatch.setattr(voice_api, "transcribe_audio_bytes", _fake_transcribe)
    resp = client.post(
        "/api/voice/transcribe",
        files={"file": ("voice.webm", b"\x00" * 64, "application/octet-stream")},
    )
    assert resp.status_code == 200

"""F3: 语音输入 STT API — 双层语音识别方案的后端兜底层

端点:
- POST /api/voice/transcribe   - 音频转文字 (multipart 文件上传 或 JSON base64)

设计要点:
- faster-whisper 为可选依赖: 延迟 import, 未安装时返回 501 + 明确错误信息,
  不影响其他 API; 安装方式见 pyproject.toml [voice] 可选依赖
- 推理在独立线程执行 (asyncio.to_thread), 避免阻塞事件循环
- 防滥用: 限制音频大小 (25MB) 与时长 (默认 120s), 校验内容类型
- 前端默认优先使用浏览器 Web Speech API, 本端点仅在其不可用时兜底
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import logging
import os
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile as StarletteUploadFile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["voice"])

# 允许上传的音频内容类型 (浏览器 MediaRecorder 常产出 audio/webm / audio/ogg)
ALLOWED_AUDIO_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/webm",
    "video/webm",  # 部分浏览器 MediaRecorder 报告为 video/webm
    "audio/ogg",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/x-m4a",
}

# 扩展名 -> 内容类型 (客户端不携带 content_type 或为 octet-stream 时推断)
_EXT_CONTENT_TYPES = {
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}

# 内容类型 -> 临时文件后缀 (faster-whisper 经 PyAV/ffmpeg 解码, 后缀辅助探测格式)
_CONTENT_TYPE_SUFFIX = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
}

MAX_AUDIO_SIZE_MB = 25  # 单文件大小上限
MAX_DURATION_MS = 120_000  # 音频时长上限: 2 分钟
# Whisper 模型规格, 可用环境变量覆盖 (tiny/base/small/medium/large-v3)
_DEFAULT_MODEL = os.getenv("PYCODER_WHISPER_MODEL", "base")


class TranscribeResponse(BaseModel):
    """语音转写结果"""

    text: str = Field(..., description="识别出的文本")
    language: str = Field(..., description="识别出的语言代码 (如 zh/en)")
    duration_ms: int = Field(..., description="音频时长 (毫秒)")


class VoiceEngineUnavailableError(RuntimeError):
    """语音引擎不可用 (faster-whisper 未安装或模型加载失败)"""


# ── 模型单例 (首次请求时懒加载) ─────────────────────────────
_model_lock = threading.Lock()
_model: Any | None = None


def _get_model(model_name: str) -> Any:
    """获取全局 WhisperModel 单例, 未安装依赖时抛出 VoiceEngineUnavailableError"""
    global _model
    with _model_lock:
        if _model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise VoiceEngineUnavailableError(
                    "未安装 faster-whisper, 后端语音识别不可用。"
                    "可执行 `pip install faster-whisper` 或 `pip install pycoder[voice]` 启用"
                ) from exc
            try:
                _model = WhisperModel(model_name, device="auto", compute_type="default")
            except Exception as exc:  # 模型下载/加载失败 (网络/磁盘等)
                raise VoiceEngineUnavailableError(f"语音模型加载失败: {exc}") from exc
    return _model


def _wav_duration_ms(data: bytes) -> int | None:
    """从 WAV 头部读取时长 (毫秒); 非 WAV 或解析失败返回 None"""
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            rate = wf.getframerate()
            if rate > 0:
                return int(wf.getnframes() / rate * 1000)
    except (wave.Error, EOFError):
        return None
    return None


def transcribe_audio_bytes(
    data: bytes,
    suffix: str,
    language: str | None = None,
) -> TranscribeResponse:
    """同步执行 faster-whisper 推理 (应经 asyncio.to_thread 在线程池中调用)

    Args:
        data: 音频原始字节
        suffix: 临时文件后缀 (辅助解码器探测格式)
        language: 指定语言代码, None 表示自动检测

    Returns:
        TranscribeResponse — 文本/语言/时长

    Raises:
        VoiceEngineUnavailableError: faster-whisper 未安装或模型不可用
    """
    model = _get_model(_DEFAULT_MODEL)
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name
        options: dict[str, Any] = {}
        if language:
            options["language"] = language
        segments, info = model.transcribe(tmp_path, **options)
        text = "".join(seg.text for seg in segments).strip()
        duration_s = float(getattr(info, "duration", 0.0) or 0.0)
        duration_ms = int(duration_s * 1000) or (_wav_duration_ms(data) or 0)
        detected = getattr(info, "language", None) or language or "unknown"
        return TranscribeResponse(text=text, language=detected, duration_ms=duration_ms)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                logger.debug("voice_temp_cleanup_failed path=%s", tmp_path)


# ── 请求解析与校验 ─────────────────────────────────────────


async def _extract_audio(request: Request) -> tuple[bytes, str, str | None, str | None]:
    """从请求中提取音频字节

    支持两种提交方式:
    - multipart/form-data: 字段 file (UploadFile), 可选字段 language
    - application/json: {"audio_base64": str, "content_type"?: str, "language"?: str}

    Returns:
        (音频字节, 内容类型, 文件名, 语言代码)
    """
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype == "multipart/form-data":
        form = await request.form()
        upload = form.get("file")
        # 注意: request.form() 返回 starlette.datastructures.UploadFile,
        # 不能用 fastapi.UploadFile (其子类) 做 isinstance 判断
        if not isinstance(upload, StarletteUploadFile):
            raise HTTPException(status_code=400, detail="multipart 请求缺少 file 字段")
        language = form.get("language")
        return (
            await upload.read(),
            upload.content_type or "",
            upload.filename,
            language if isinstance(language, str) else None,
        )
    if ctype == "application/json":
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="JSON 请求体解析失败") from exc
        if not isinstance(body, dict) or "audio_base64" not in body:
            raise HTTPException(status_code=400, detail="JSON 请求缺少 audio_base64 字段")
        try:
            data = base64.b64decode(str(body["audio_base64"]), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail="audio_base64 解码失败") from exc
        language = body.get("language")
        return (
            data,
            str(body.get("content_type") or ""),
            body.get("filename") if isinstance(body.get("filename"), str) else None,
            language if isinstance(language, str) else None,
        )
    raise HTTPException(
        status_code=415,
        detail=f"不支持的请求类型: {ctype or '(空)'}。请使用 multipart/form-data 或 application/json",
    )


def _resolve_audio_type(content_type: str, filename: str | None) -> str:
    """归一化音频类型: 空或 octet-stream 时按扩展名推断"""
    ctype = content_type.split(";")[0].strip().lower()
    if ctype and ctype != "application/octet-stream":
        return ctype
    if filename:
        ext = Path(filename).suffix.lower()
        if ext in _EXT_CONTENT_TYPES:
            return _EXT_CONTENT_TYPES[ext]
    return ctype


def _validate_audio(content_type: str, size: int) -> None:
    """校验音频类型与大小, 不满足时抛出 HTTPException(400)"""
    if content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的音频类型: {content_type or '(空)'}。"
            f"允许: {', '.join(sorted(ALLOWED_AUDIO_TYPES))}",
        )
    if size == 0:
        raise HTTPException(status_code=400, detail="音频内容为空")
    if size > MAX_AUDIO_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"音频过大: {size / 1024 / 1024:.1f}MB > {MAX_AUDIO_SIZE_MB}MB",
        )


# ── 端点 ──────────────────────────────────────────────


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(request: Request) -> TranscribeResponse:
    """音频转文字 (faster-whisper 本地推理)

    - 依赖未安装/模型不可用时返回 501
    - 类型/大小/时长校验失败返回 400
    """
    data, raw_type, filename, language = await _extract_audio(request)
    content_type = _resolve_audio_type(raw_type, filename)
    _validate_audio(content_type, len(data))
    # WAV 可在推理前校验时长; 其他格式无法零依赖解析, 由大小上限兜底
    if (duration := _wav_duration_ms(data)) is not None and duration > MAX_DURATION_MS:
        raise HTTPException(
            status_code=400,
            detail=f"音频过长: {duration / 1000:.1f}s > {MAX_DURATION_MS // 1000}s",
        )
    try:
        return await asyncio.to_thread(
            transcribe_audio_bytes,
            data,
            _CONTENT_TYPE_SUFFIX[content_type],
            language,
        )
    except VoiceEngineUnavailableError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("voice_transcribe_failed")
        raise HTTPException(status_code=500, detail=f"语音识别失败: {exc}") from exc

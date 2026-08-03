/**
 * F3: 语音输入服务 — 双层 STT 方案
 *
 * 方案A (优先): 浏览器 Web Speech API (webkitSpeechRecognition)
 *   - 实时转写 (interim + final), 零后端依赖
 * 方案B (兜底): getUserMedia + MediaRecorder 录音
 *   - 停止后上传 POST /api/voice/transcribe (后端 faster-whisper)
 *
 * 自动探测可用方案, 暴露 start/stop/onResult 接口。
 */
import { getApiBase, getApiKey } from './config';

/** 语音输入状态 */
export type VoiceState = 'idle' | 'recording' | 'recognizing';

/** 实际使用的识别方案 */
export type VoiceMethod = 'web-speech' | 'backend-whisper';

/** 事件回调 */
export interface VoiceInputHandlers {
  /** 识别结果回调: text 为本次会话累计文本, isFinal 表示最终结果 */
  onResult?: (text: string, isFinal: boolean) => void;
  /** 错误回调 (用户可读的中文信息) */
  onError?: (message: string) => void;
  /** 状态变化回调 */
  onStateChange?: (state: VoiceState) => void;
}

/** Web Speech API 的最小类型定义 (TS DOM lib 未内置 webkitSpeechRecognition) */
interface SpeechRecognitionResultItem {
  transcript: string;
}

interface SpeechRecognitionResultLike {
  isFinal: boolean;
  0: SpeechRecognitionResultItem;
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}

interface SpeechRecognitionErrorEventLike {
  error: string;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

/** 获取 SpeechRecognition 构造函数 (浏览器/Electron 内核差异) */
function getSpeechRecognitionCtor(): (new () => SpeechRecognitionLike) | null {
  const w = window as unknown as Record<string, unknown>;
  const ctor = (w.SpeechRecognition || w.webkitSpeechRecognition) as
    | (new () => SpeechRecognitionLike)
    | undefined;
  return ctor ?? null;
}

/** 探测当前环境可用的语音输入方案 (A 优先, B 兜底, null 表示均不可用) */
export function detectVoiceMethod(): VoiceMethod | null {
  if (typeof window !== 'undefined' && getSpeechRecognitionCtor()) {
    return 'web-speech';
  }
  // TS DOM lib 将 mediaDevices 标记为必有, 但运行时需防御性判断 (如非安全上下文)
  const mediaDevices =
    typeof navigator !== 'undefined'
      ? (navigator.mediaDevices as MediaDevices | undefined)
      : undefined;
  if (mediaDevices && typeof mediaDevices.getUserMedia === 'function' && typeof MediaRecorder !== 'undefined') {
    return 'backend-whisper';
  }
  return null;
}

/** MediaRecorder 首选的音频编码 (按浏览器支持度回退) */
const PREFERRED_MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg'];

function pickRecorderMimeType(): string {
  for (const t of PREFERRED_MIME_TYPES) {
    if (MediaRecorder.isTypeSupported(t)) {
      return t;
    }
  }
  return '';
}

/** 根据 blob 的 MIME 类型推断文件名后缀 */
function blobExtension(mimeType: string): string {
  if (mimeType.includes('ogg')) return 'ogg';
  if (mimeType.includes('mpeg') || mimeType.includes('mp3')) return 'mp3';
  if (mimeType.includes('wav')) return 'wav';
  return 'webm';
}

/**
 * 语音输入控制器
 *
 * 用法:
 *   const voice = new VoiceInput({ onResult, onError, onStateChange });
 *   await voice.start();  // 自动选择方案并开始
 *   await voice.stop();   // 停止 (方案B 在此刻上传识别)
 */
export class VoiceInput {
  private handlers: VoiceInputHandlers;
  private recognition: SpeechRecognitionLike | null = null;
  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private chunks: Blob[] = [];
  private method: VoiceMethod | null = null;
  /** 会话内已确认的文本片段 (方案A 跨多次 result 事件累计) */
  private committedText = '';
  /** 是否为主动停止 (区分 onend 的触发来源) */
  private stopping = false;

  constructor(handlers: VoiceInputHandlers = {}) {
    this.handlers = handlers;
  }

  /** 当前使用的方案 (未开始为 null) */
  get activeMethod(): VoiceMethod | null {
    return this.method;
  }

  /** 是否正在进行语音输入 */
  get active(): boolean {
    return this.method !== null;
  }

  /** 开始语音输入, 返回实际使用的方案 */
  async start(): Promise<VoiceMethod> {
    if (this.method) {
      throw new Error('语音输入已在进行中');
    }
    const method = detectVoiceMethod();
    if (!method) {
      throw new Error('当前环境不支持语音输入 (无 SpeechRecognition 与麦克风录制能力)');
    }
    this.committedText = '';
    this.stopping = false;
    if (method === 'web-speech') {
      this.startWebSpeech();
    } else {
      await this.startRecorder();
    }
    this.method = method;
    this.setState('recording');
    return method;
  }

  /** 停止语音输入; 方案B 会在停止后自动上传并回调识别结果 */
  async stop(): Promise<void> {
    this.stopping = true;
    if (this.recognition) {
      // stop() 触发 onend 完成清理; 已确认文本由 onresult(final) 回调
      this.recognition.stop();
      return;
    }
    if (this.recorder && this.recorder.state !== 'inactive') {
      // stop() 触发 onstop → 释放麦克风并上传识别
      this.recorder.stop();
      return;
    }
    this.cleanup();
  }

  /** 中止语音输入, 不上传不回调结果 */
  dispose(): void {
    this.stopping = true;
    if (this.recognition) {
      this.recognition.onresult = null;
      this.recognition.onerror = null;
      this.recognition.onend = null;
      try {
        this.recognition.abort();
      } catch {
        // 忽略 abort 异常
      }
      this.recognition = null;
    }
    if (this.recorder) {
      this.recorder.ondataavailable = null;
      this.recorder.onstop = null;
      this.recorder.onerror = null;
      if (this.recorder.state !== 'inactive') {
        try {
          this.recorder.stop();
        } catch {
          // 忽略 stop 异常
        }
      }
      this.recorder = null;
    }
    this.releaseStream();
    this.method = null;
  }

  // ── 方案A: Web Speech API ─────────────────────────────

  private startWebSpeech(): void {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) {
      throw new Error('SpeechRecognition 不可用');
    }
    const rec = new Ctor();
    rec.lang = 'zh-CN';
    rec.continuous = true;
    rec.interimResults = true;

    rec.onresult = (event) => {
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          this.committedText += result[0].transcript;
        } else {
          interim += result[0].transcript;
        }
      }
      // 实时转写: 累计文本 = 已确认 + 当前中间结果
      const text = this.committedText + interim;
      this.handlers.onResult?.(text, interim === '');
    };

    rec.onerror = (event) => {
      const message =
        event.error === 'not-allowed' || event.error === 'service-not-allowed'
          ? '麦克风权限被拒绝, 请在系统设置中允许麦克风访问'
          : `语音识别出错: ${event.error}`;
      this.handlers.onError?.(message);
      this.cleanup();
    };

    rec.onend = () => {
      // 非主动停止(如浏览器超时) 时, 将已有文本作为最终结果提交
      if (!this.stopping && this.committedText) {
        this.handlers.onResult?.(this.committedText, true);
      }
      this.cleanup();
    };

    try {
      rec.start();
    } catch (err) {
      this.cleanup();
      throw new Error(`无法启动语音识别: ${(err as Error).message}`);
    }
    this.recognition = rec;
  }

  // ── 方案B: MediaRecorder + 后端 whisper ───────────────

  private async startRecorder(): Promise<void> {
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      throw new Error(`无法访问麦克风: ${(err as Error).message}`);
    }
    this.stream = stream;
    this.chunks = [];

    const mimeType = pickRecorderMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    recorder.ondataavailable = (e: BlobEvent) => {
      if (e.data.size > 0) {
        this.chunks.push(e.data);
      }
    };
    recorder.onerror = () => {
      this.handlers.onError?.('录音失败');
      this.cleanup();
    };
    recorder.onstop = () => {
      this.releaseStream();
      this.recorder = null;
      this.setState('recognizing');
      void this.uploadAndRecognize();
    };
    recorder.start();
    this.recorder = recorder;
  }

  /** 上传录音到后端 /api/voice/transcribe 并回调结果 */
  private async uploadAndRecognize(): Promise<void> {
    try {
      const blob = new Blob(this.chunks, {
        type: this.chunks[0]?.type || 'audio/webm',
      });
      this.chunks = [];
      if (blob.size === 0) {
        this.handlers.onError?.('未录到音频');
        return;
      }
      const base = await getApiBase();
      const apiKey = await getApiKey();
      const form = new FormData();
      const ext = blobExtension(blob.type);
      form.append('file', new File([blob], `voice.${ext}`, { type: blob.type }));
      const headers: Record<string, string> = {};
      if (apiKey) {
        headers['X-API-Key'] = apiKey;
      }
      const res = await fetch(`${base}/api/voice/transcribe`, {
        method: 'POST',
        body: form,
        headers,
      });
      if (!res.ok) {
        const detail = await res
          .json()
          .then((d: { detail?: string }) => d.detail)
          .catch(() => undefined);
        if (res.status === 501) {
          this.handlers.onError?.(
            detail || '后端未安装 faster-whisper, 请执行 pip install faster-whisper 后重试',
          );
        } else {
          this.handlers.onError?.(detail || `语音识别失败 (HTTP ${res.status})`);
        }
        return;
      }
      const data = (await res.json()) as { text?: string };
      const text = (data.text || '').trim();
      if (text) {
        this.handlers.onResult?.(text, true);
      } else {
        this.handlers.onError?.('未识别到语音内容');
      }
    } catch (err) {
      this.handlers.onError?.(`语音识别请求失败: ${(err as Error).message}`);
    } finally {
      this.cleanup();
    }
  }

  // ── 内部工具 ─────────────────────────────────────────

  private releaseStream(): void {
    if (this.stream) {
      for (const track of this.stream.getTracks()) {
        track.stop();
      }
      this.stream = null;
    }
  }

  private cleanup(): void {
    this.recognition = null;
    this.recorder = null;
    this.releaseStream();
    this.method = null;
    this.setState('idle');
  }

  private setState(state: VoiceState): void {
    this.handlers.onStateChange?.(state);
  }
}

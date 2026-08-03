/**
 * F3: 语音输入按钮 — 聊天输入区的麦克风入口
 *
 * 状态: idle (🎤) → recording (🔴 脉冲动画) → recognizing (⏳ 识别中)
 * 识别文本通过 onTranscript 回调交给父组件填入输入框;
 * 环境不支持 (无 SpeechRecognition 且无麦克风录制能力) 时不渲染, 不影响布局。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { detectVoiceMethod, VoiceInput, VoiceState } from '../services/voiceInput';

interface Props {
  /** 识别结果回调: text 为本次会话累计文本 (方案A 含实时中间结果) */
  onTranscript: (text: string) => void;
  /** 录音会话开始前的回调 (父组件可借此记录输入框基线内容) */
  onSessionStart?: () => void;
  /** 外部禁用 (如 AI 生成中) */
  disabled?: boolean;
}

/** 错误提示的展示时长 (毫秒) */
const ERROR_DISPLAY_MS = 4000;

export const VoiceInputButton: React.FC<Props> = ({ onTranscript, onSessionStart, disabled }) => {
  const [state, setState] = useState<VoiceState>('idle');
  const [error, setError] = useState('');
  // 挂载时探测一次即可, 运行期间能力不会变化
  const [supported] = useState(() => detectVoiceMethod() !== null);
  const voiceRef = useRef<VoiceInput | null>(null);
  const errorTimerRef = useRef<number | null>(null);

  // 卸载时释放麦克风/识别器, 并清理错误提示计时器
  useEffect(() => {
    return () => {
      voiceRef.current?.dispose();
      voiceRef.current = null;
      if (errorTimerRef.current !== null) {
        window.clearTimeout(errorTimerRef.current);
      }
    };
  }, []);

  const showError = useCallback((message: string) => {
    setError(message);
    if (errorTimerRef.current !== null) {
      window.clearTimeout(errorTimerRef.current);
    }
    errorTimerRef.current = window.setTimeout(() => setError(''), ERROR_DISPLAY_MS);
  }, []);

  const handleClick = useCallback(async () => {
    if (state === 'idle') {
      onSessionStart?.();
      const voice = new VoiceInput({
        onResult: (text) => onTranscript(text),
        onError: showError,
        onStateChange: setState,
      });
      voiceRef.current = voice;
      try {
        await voice.start();
      } catch (err) {
        showError((err as Error).message);
        voiceRef.current = null;
      }
      return;
    }
    // recording 状态下点击 = 停止 (方案B 停止后自动上传识别)
    await voiceRef.current?.stop();
  }, [state, onTranscript, onSessionStart, showError]);

  if (!supported) {
    return null;
  }

  const title =
    error ||
    (state === 'recording'
      ? '录音中, 点击停止'
      : state === 'recognizing'
        ? '正在识别...'
        : '语音输入 (点击开始说话)');

  return (
    <button
      type="button"
      className={`btn-voice${state === 'recording' ? ' btn-voice-recording' : ''}${error ? ' btn-voice-error' : ''}`}
      onClick={handleClick}
      disabled={disabled || state === 'recognizing'}
      title={title}
      aria-label={title}
    >
      {state === 'recording' ? '⏺' : state === 'recognizing' ? '⏳' : '🎤'}
    </button>
  );
};

/**
 * Chat Store — AI 对话消息、会话、流式状态、进度报告
 */
import { create } from 'zustand';
import type { ChatMessage, ModelInfo } from '../types';

interface SessionItem {
    id: string;
    model?: string;
    title?: string;
    updated_at?: number;
}

/** Agent 进度信息 */
export interface AgentProgress {
    phase: string;
    stage: string;
    current_step: number;
    total_steps: number;
    percent: number;
    elapsed_seconds: number;
    eta_seconds: number;
    milestones: Array<{ step: string; status: string }>;
}

/** 后台插件事件 */
export interface PluginEvent {
    plugin_id: string;
    plugin_name: string;
    action: 'start' | 'done' | 'skip' | 'error';
    duration_ms: number;
    error?: string;
}

interface ChatState {
    messages: ChatMessage[];
    isStreaming: boolean;
    sessions: SessionItem[];
    activeSessionId: string | null;
    currentModel: string;
    models: ModelInfo[];
    reasoningEffort: string;
    enableCache: boolean;
    tokenCount: number;
    estimatedCost: number;

    // V2 AI-Centric 引擎状态
    v2Engine: boolean;
    v2Capabilities: number;
    v2TrustLevel: string;

    // 进度报告与静默插件执行
    agentProgress: AgentProgress | null;
    pluginEvents: PluginEvent[];

    addMessage: (msg: ChatMessage) => void;
    updateLastMessage: (content: string) => void;
    setStreaming: (streaming: boolean) => void;
    clearChat: () => void;
    setSessions: (sessions: SessionItem[]) => void;
    setActiveSession: (sessionId: string | null) => void;
    setCurrentModel: (model: string) => void;
    setModels: (models: ModelInfo[]) => void;
    setReasoningEffort: (effort: string) => void;
    setEnableCache: (enable: boolean) => void;
    updateSessionModel: (sessionId: string, model: string) => void;
    addTokenUsage: (tokens: number) => void;
    resetUsage: () => void;
    // V2 引擎状态
    setV2Engine: (enabled: boolean, capabilities: number, trustLevel: string) => void;
    // 进度与插件事件
    setAgentProgress: (progress: AgentProgress | null) => void;
    addPluginEvent: (event: PluginEvent) => void;
    clearAgentEvents: () => void;
}

export const useChatStore = create<ChatState>((set) => ({
    messages: [],
    isStreaming: false,
    sessions: [],
    activeSessionId: null,
    currentModel: 'deepseek-chat',
    models: [],
    reasoningEffort: 'medium',
    enableCache: true,
    tokenCount: 0,
    estimatedCost: 0,
    // V2 AI-Centric 引擎
    v2Engine: false,
    v2Capabilities: 0,
    v2TrustLevel: '',
    // 进度报告与静默插件执行
    agentProgress: null,
    pluginEvents: [],

    addMessage: (msg) => set((s) => ({ messages: [...s.messages, msg] })),
    updateLastMessage: (content) => set((s) => {
        const msgs = [...s.messages];
        if (msgs.length > 0) msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], content };
        return { messages: msgs };
    }),
    setStreaming: (streaming) => set({ isStreaming: streaming }),
    clearChat: () => set({ messages: [], tokenCount: 0, estimatedCost: 0 }),
    setSessions: (sessions) => set({ sessions }),
    setActiveSession: (sessionId) => set({ activeSessionId: sessionId }),
    setCurrentModel: (model) => set({ currentModel: model }),
    setModels: (models) => set({ models }),
    setReasoningEffort: (effort) => set({ reasoningEffort: effort }),
    setEnableCache: (enable) => set({ enableCache: enable }),
    updateSessionModel: (sessionId, model) => set((s) => ({
        sessions: s.sessions.map((session) =>
            session.id === sessionId ? { ...session, model } : session,
        ),
    })),
    addTokenUsage: (tokens) => set((s) => ({
        tokenCount: s.tokenCount + tokens,
        // deepseek-chat: ¥0.14/1M input, ¥0.28/1M output → avg ¥0.21/1M
        estimatedCost: s.estimatedCost + (tokens * 0.00000021),
    })),
    resetUsage: () => set({ tokenCount: 0, estimatedCost: 0 }),
    setV2Engine: (enabled, capabilities, trustLevel) => set({
        v2Engine: enabled,
        v2Capabilities: capabilities,
        v2TrustLevel: trustLevel,
    }),
    // 进度报告与静默插件执行
    setAgentProgress: (progress) => set({ agentProgress: progress }),
    addPluginEvent: (event) => set((s) => ({
        pluginEvents: [...s.pluginEvents.slice(-19), event],  // 最多保留20条
    })),
    clearAgentEvents: () => set({ agentProgress: null, pluginEvents: [] }),
}));

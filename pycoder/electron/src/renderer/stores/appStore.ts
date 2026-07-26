/**
 * App Store — 兼容层，从子 Store 重新导出
 *
 * 新组件建议直接导入子 store:
 *   import { useUIStore } from './uiStore';
 *   import { useChatStore } from './chatStore';
 *   import { useEditorStore } from './editorStore';
 *   import { useGitStore } from './gitStore';
 *   import { useBackendStore } from './backendStore';
 */

export { useUIStore } from './uiStore';
export { useChatStore } from './chatStore';
export { useEditorStore } from './editorStore';
export { useGitStore } from './gitStore';
export { useBackendStore } from './backendStore';

// ── 兼容层：保留 useAppStore 供旧组件使用 ──
import { useUIStore } from './uiStore';
import { useChatStore } from './chatStore';
import { useEditorStore } from './editorStore';
import { useGitStore } from './gitStore';
import { useBackendStore } from './backendStore';
import type { WSConnectionManager } from '../services/websocket';
import type { BackendStatus } from '../types';

interface LegacyAppState {
  // 委托到子 store
  theme: 'dark' | 'light';
  toggleTheme: () => void;
  setTheme: (theme: 'dark' | 'light') => void;
  layout: ReturnType<typeof useUIStore.getState>['layout'];
  setLayout: (layout: Partial<ReturnType<typeof useUIStore.getState>['layout']>) => void;
  toggleSidebar: () => void;
  toggleAIPanel: () => void;
  toggleBottomPanel: () => void;
  activeSidebar: string | null;
  setActiveSidebar: (view: string | null) => void;
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (open: boolean) => void;
  evoPanelOpen: boolean;
  toggleEvoPanel: () => void;
  browserPanelOpen: boolean;
  toggleBrowserPanel: () => void;
  activeGroup: string;
  setActiveGroup: (group: string) => void;
  bottomPanel: string;
  setBottomPanel: (panel: string) => void;

  chatMessages: import('../types').ChatMessage[];
  isStreaming: boolean;
  addMessage: (msg: import('../types').ChatMessage) => void;
  updateLastMessage: (content: string) => void;
  setStreaming: (streaming: boolean) => void;
  clearChat: () => void;
  sessions: Array<{ id: string; model?: string; title?: string; updated_at?: number }>;
  activeSessionId: string | null;
  setSessions: (sessions: Array<{ id: string; model?: string; title?: string; updated_at?: number }>) => void;
  setActiveSession: (sessionId: string | null) => void;
  currentModel: string;
  models: import('../types').ModelInfo[];
  setCurrentModel: (model: string) => void;
  setModels: (models: import('../types').ModelInfo[]) => void;
  reasoningEffort: string;
  enableCache: boolean;
  setReasoningEffort: (effort: string) => void;
  setEnableCache: (enable: boolean) => void;
  updateSessionModel: (sessionId: string, model: string) => void;

  fileTree: import('../types').FileEntry | null;
  projectRoot: string;
  setFileTree: (tree: import('../types').FileEntry | null) => void;
  setProjectRoot: (root: string) => void;
  openTabs: import('../types').EditorTab[];
  activeTabId: string | null;
  openFile: (tab: import('../types').EditorTab) => void;
  closeTab: (tabId: string) => void;
  setActiveTab: (tabId: string) => void;
  updateTabContent: (tabId: string, content: string) => void;

  pendingDiffs: import('../types').DiffFile[];
  setPendingDiffs: (diffs: import('../types').DiffFile[]) => void;
  gitStatus: import('../types').GitStatus | null;
  setGitStatus: (status: import('../types').GitStatus | null) => void;
  autoCommitEnabled: boolean;
  commitMsgMode: 'auto' | 'confirm' | 'manual';
  setAutoCommitEnabled: (enabled: boolean) => void;
  setCommitMsgMode: (mode: 'auto' | 'confirm' | 'manual') => void;

  // 原生字段（委托到 backendStore）
  backendStatus: BackendStatus;
  backendUrl: string;
  wsClient: WSConnectionManager | null;
  setBackendStatus: (status: BackendStatus) => void;
  setWsClient: (client: WSConnectionManager | null) => void;
}

// 构建一次完整的合并状态（供 getState 使用）
function buildLegacyState(): LegacyAppState {
  const be = useBackendStore.getState();
  return { ...buildCoreState(), ...buildBackendState(be) };
}

// 核心状态构建（复用）
function buildCoreState(): Omit<LegacyAppState, 'backendStatus' | 'backendUrl' | 'wsClient' | 'setBackendStatus' | 'setWsClient'> {
  const ui = useUIStore.getState();
  const chat = useChatStore.getState();
  const editor = useEditorStore.getState();
  const git = useGitStore.getState();

  return {
    theme: ui.theme,
    toggleTheme: ui.toggleTheme,
    setTheme: ui.setTheme,
    layout: ui.layout,
    setLayout: ui.setLayout,
    toggleSidebar: ui.toggleSidebar,
    toggleAIPanel: ui.toggleAIPanel,
    toggleBottomPanel: ui.toggleBottomPanel,
    activeSidebar: ui.activeSidebar,
    setActiveSidebar: ui.setActiveSidebar as (view: string | null) => void,
    commandPaletteOpen: ui.commandPaletteOpen,
    setCommandPaletteOpen: ui.setCommandPaletteOpen,
    evoPanelOpen: ui.evoPanelOpen,
    toggleEvoPanel: ui.toggleEvoPanel,
    browserPanelOpen: ui.browserPanelOpen,
    toggleBrowserPanel: ui.toggleBrowserPanel,
    activeGroup: ui.activeGroup,
    setActiveGroup: ui.setActiveGroup as (group: string) => void,
    bottomPanel: ui.bottomPanel,
    setBottomPanel: ui.setBottomPanel as (panel: string) => void,

    chatMessages: chat.messages,
    isStreaming: chat.isStreaming,
    addMessage: chat.addMessage,
    updateLastMessage: chat.updateLastMessage,
    setStreaming: chat.setStreaming,
    clearChat: chat.clearChat,
    sessions: chat.sessions,
    activeSessionId: chat.activeSessionId,
    setSessions: chat.setSessions,
    setActiveSession: chat.setActiveSession,
    currentModel: chat.currentModel,
    models: chat.models,
    setCurrentModel: chat.setCurrentModel,
    setModels: chat.setModels,
    reasoningEffort: chat.reasoningEffort,
    enableCache: chat.enableCache,
    setReasoningEffort: chat.setReasoningEffort,
    setEnableCache: chat.setEnableCache,
    updateSessionModel: chat.updateSessionModel,

    fileTree: editor.fileTree,
    projectRoot: editor.projectRoot,
    setFileTree: editor.setFileTree,
    setProjectRoot: editor.setProjectRoot,
    openTabs: editor.openTabs,
    activeTabId: editor.activeTabId,
    openFile: editor.openFile,
    closeTab: editor.closeTab,
    setActiveTab: editor.setActiveTab,
    updateTabContent: editor.updateTabContent,

    pendingDiffs: git.pendingDiffs,
    setPendingDiffs: git.setPendingDiffs,
    gitStatus: git.gitStatus,
    setGitStatus: git.setGitStatus,
    autoCommitEnabled: git.autoCommitEnabled,
    commitMsgMode: git.commitMsgMode,
    setAutoCommitEnabled: git.setAutoCommitEnabled,
    setCommitMsgMode: git.setCommitMsgMode,
  };
}

function buildBackendState(be: ReturnType<typeof useBackendStore.getState>) {
  return {
    backendStatus: be.backendStatus,
    backendUrl: be.backendUrl,
    wsClient: be.wsClient,
    setBackendStatus: be.setBackendStatus,
    setWsClient: be.setWsClient,
  };
}

/** 兼容 hook：获取所有 store 的合并状态（字段名映射） */
export const useAppStore = <T = LegacyAppState>(selector?: (state: LegacyAppState) => T): T => {
  const ui = useUIStore();
  const chat = useChatStore();
  const editor = useEditorStore();
  const git = useGitStore();
  const be = useBackendStore();

  const all: LegacyAppState = buildLegacyStateFromHooks({ ui, chat, editor, git, be });

  if (selector) return selector(all);
  return all as unknown as T;
};

// getState() 支持（从子 store 同步读取，替代旧的 zustand create））
useAppStore.getState = (): LegacyAppState => buildLegacyState();

// 内部辅助 —— 从 hook 返回值构建
// 注意：使用 any 避免 zustand 6+ ReturnType 推断为 unknown 的连锁问题
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function buildLegacyStateFromHooks(stores: {
  ui: any;
  chat: any;
  editor: any;
  git: any;
  be: any;
}): LegacyAppState {
  const { ui, chat, editor, git, be } = stores;
  return {
    theme: ui.theme, toggleTheme: ui.toggleTheme, setTheme: ui.setTheme,
    layout: ui.layout, setLayout: ui.setLayout,
    toggleSidebar: ui.toggleSidebar, toggleAIPanel: ui.toggleAIPanel,
    toggleBottomPanel: ui.toggleBottomPanel,
    activeSidebar: ui.activeSidebar, setActiveSidebar: ui.setActiveSidebar as any,
    commandPaletteOpen: ui.commandPaletteOpen, setCommandPaletteOpen: ui.setCommandPaletteOpen,
    evoPanelOpen: ui.evoPanelOpen, toggleEvoPanel: ui.toggleEvoPanel,
    browserPanelOpen: ui.browserPanelOpen, toggleBrowserPanel: ui.toggleBrowserPanel,
    activeGroup: ui.activeGroup, setActiveGroup: ui.setActiveGroup as any,
    bottomPanel: ui.bottomPanel, setBottomPanel: ui.setBottomPanel as any,
    chatMessages: chat.messages, isStreaming: chat.isStreaming,
    addMessage: chat.addMessage, updateLastMessage: chat.updateLastMessage,
    setStreaming: chat.setStreaming, clearChat: chat.clearChat,
    sessions: chat.sessions, activeSessionId: chat.activeSessionId,
    setSessions: chat.setSessions, setActiveSession: chat.setActiveSession,
    currentModel: chat.currentModel, models: chat.models,
    setCurrentModel: chat.setCurrentModel, setModels: chat.setModels,
    reasoningEffort: chat.reasoningEffort, enableCache: chat.enableCache,
    setReasoningEffort: chat.setReasoningEffort, setEnableCache: chat.setEnableCache,
    updateSessionModel: chat.updateSessionModel,
    fileTree: editor.fileTree, projectRoot: editor.projectRoot,
    setFileTree: editor.setFileTree, setProjectRoot: editor.setProjectRoot,
    openTabs: editor.openTabs, activeTabId: editor.activeTabId,
    openFile: editor.openFile, closeTab: editor.closeTab,
    setActiveTab: editor.setActiveTab, updateTabContent: editor.updateTabContent,
    pendingDiffs: git.pendingDiffs, setPendingDiffs: git.setPendingDiffs,
    gitStatus: git.gitStatus, setGitStatus: git.setGitStatus,
    autoCommitEnabled: git.autoCommitEnabled, commitMsgMode: git.commitMsgMode,
    setAutoCommitEnabled: git.setAutoCommitEnabled, setCommitMsgMode: git.setCommitMsgMode,
    backendStatus: be.backendStatus, backendUrl: be.backendUrl,
    wsClient: be.wsClient, setBackendStatus: be.setBackendStatus,
    setWsClient: be.setWsClient,
  };
}

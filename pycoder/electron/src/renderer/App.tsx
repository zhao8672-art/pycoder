import React, { useEffect, useState, useCallback, lazy, Suspense } from 'react';
import { ActivityBar } from './components/ActivityBar';
import { Sidebar } from './components/Sidebar';
import { EditorTabs } from './components/EditorTabs';
import { MonacoEditor } from './components/MonacoEditor';
import { AIPanel } from './components/AIPanel';
import { StatusBar } from './components/StatusBar';
import { ProjectStatusBar } from './components/ProjectStatusBar';
import { DiffPreview } from './components/DiffPreview';
import { EvolutionPanel } from './components/EvolutionPanel';
import { CommandPalette } from './components/CommandPalette';
import { ErrorBoundary } from './components/ErrorBoundary';
import { MenuBar } from './components/MenuBar';
import WelcomeScreen from './components/WelcomeScreen';
import { BrowserPanel } from './components/BrowserPanel';
import { MobileLayout } from './components/MobileLayout';
import { Resizer } from './components/common/Resizer';
import { WSConnectionRegistry } from './services/wsConnectionRegistry';
import { BackendAPI } from './services/backend';
import { useIsMobile } from './services/detectMobile';
import { getLanguageFromPath } from './utils/language';
import { useUIStore } from './stores/uiStore';
import { useChatStore } from './stores/chatStore';
import { useEditorStore } from './stores/editorStore';
import { useGitStore } from './stores/gitStore';
import { useBackendStore } from './stores/backendStore';

// ── 底部面板懒加载（P1-3） ──
const TerminalPanel = lazy(() => import('./components/TerminalPanel'));
const OutputPanel = lazy(() => import('./components/OutputPanel'));
const ProblemsPanel = lazy(() => import('./components/ProblemsPanel'));
const PythonRunnerPanel = lazy(() => import('./components/PythonRunnerPanel'));
const TestGenPanel = lazy(() => import('./components/TestGenPanel'));
const RunFixPanel = lazy(() => import('./components/RunFixPanel'));
const DebugPanel = lazy(() => import('./components/DebugPanel'));
const WebPreview = lazy(() => import('./components/WebPreview'));
const ImageViewer = lazy(() => import('./components/ImageViewer'));
const ChatHistorySearch = lazy(() => import('./components/ChatHistorySearch'));
const DependencyManager = lazy(() => import('./components/DependencyManager'));
const ThemeManager = lazy(() => import('./components/ThemeManager'));

/** 底部面板加载占位 */
const PanelFallback = () => <div className="panel-state panel-loading"><div className="loading-spinner" /></div>;

const AppInner: React.FC = () => {
  // ── 按需订阅各 Store（替代 useAppStore() 全量订阅） ──
  const theme = useUIStore((s) => s.theme);
  const activeSidebar = useUIStore((s) => s.activeSidebar);
  const activeGroup = useUIStore((s) => s.activeGroup);
  const layout = useUIStore((s) => s.layout);
  const setLayout = useUIStore((s) => s.setLayout);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const toggleAIPanel = useUIStore((s) => s.toggleAIPanel);
  const toggleBottomPanel = useUIStore((s) => s.toggleBottomPanel);
  const setCommandPaletteOpen = useUIStore((s) => s.setCommandPaletteOpen);
  const evoPanelOpen = useUIStore((s) => s.evoPanelOpen);
  const toggleEvoPanel = useUIStore((s) => s.toggleEvoPanel);
  const browserPanelOpen = useUIStore((s) => s.browserPanelOpen);
  const toggleBrowserPanel = useUIStore((s) => s.toggleBrowserPanel);
  const bottomPanel = useUIStore((s) => s.bottomPanel);
  const toggleTheme = useUIStore((s) => s.toggleTheme);

  const openTabs = useEditorStore((s) => s.openTabs);
  const activeTabId = useEditorStore((s) => s.activeTabId);
  const updateTabContent = useEditorStore((s) => s.updateTabContent);

  const backendStatus = useBackendStore((s) => s.backendStatus);
  const setBackendStatus = useBackendStore((s) => s.setBackendStatus);
  const wsClient = useBackendStore((s) => s.wsClient);

  const [wsReady, setWsReady] = useState(false);
  const [backendConnecting, setBackendConnecting] = useState(true);

  // ── 应用主题 ──
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // ── WS 连接初始化（替代模块顶层 IIFE） ──
  useEffect(() => {
    WSConnectionRegistry.getInstance().then((client) => {
      useBackendStore.getState().setWsClient(client);
      setWsReady(true);
    });
    return () => {
      WSConnectionRegistry.disconnect();
    };
  }, []);

  // ── 后端健康检查与数据初始化 ──
  useEffect(() => {
    let healthRetries = 0;
    let cancelled = false;

    const checkBackend = async () => {
      if (cancelled) return;
      const health = await BackendAPI.health();
      if (health?.status === 'ok') {
        healthRetries = 0;
        setBackendStatus('running');
        setBackendConnecting(false);

        const [modelsRes, envRes, gitRes, sessionsRes] = await Promise.all([
          BackendAPI.models(),
          BackendAPI.env(),
          BackendAPI.git.status(),
          BackendAPI.sessions.list(),
        ]);

        if (cancelled) return;

        if (modelsRes?.models) {
          useChatStore.getState().setModels(modelsRes.models);
          const recommended = modelsRes.recommended_model || modelsRes.models[0]?.id || 'deepseek-chat';
          useChatStore.getState().setCurrentModel(recommended);
        }
        if (envRes?.workspace && window.electronAPI) {
          window.electronAPI.getFileTree(envRes.workspace, 4).then((tree) => {
            if (!cancelled) useEditorStore.getState().setFileTree(tree);
          });
          BackendAPI.workspace.manage.init(envRes.workspace).catch(() => {});
        }

        const restoreRes = await BackendAPI.workspace.restore();
        if (restoreRes?.restored && window.electronAPI && !cancelled) {
          const tree = await window.electronAPI.getFileTree(restoreRes.path, 4);
          if (tree) {
            useEditorStore.getState().setProjectRoot(restoreRes.path);
            useEditorStore.getState().setFileTree(tree);
          }
          BackendAPI.workspace.manage.init(restoreRes.path).catch(() => {});
        }

        if (gitRes) useGitStore.getState().setGitStatus(gitRes);
        if (sessionsRes?.sessions) {
          useChatStore.getState().setSessions(sessionsRes.sessions);
          const firstId = sessionsRes.sessions[0]?.id || null;
          useChatStore.getState().setActiveSession(firstId);
        }

        wsClient?.connect();
      } else {
        healthRetries++;
        const delay = Math.min(2000 * Math.pow(2, healthRetries - 1), 30000);
        setTimeout(checkBackend, delay);
      }
    };
    checkBackend();
    return () => {
      cancelled = true;
      wsClient?.disconnect();
    };
  }, [wsClient]);

  // ── Electron 菜单事件 ──
  useEffect(() => {
    if (window.electronAPI) {
      const unsubs = [
        window.electronAPI.onMenuEvent('menu:open-project', async () => {
          const result = await window.electronAPI?.openProject();
          if (result?.success && result.path) {
            useEditorStore.getState().setProjectRoot(result.path);
            const tree = await window.electronAPI?.getFileTree(result.path, 4);
            if (tree) useEditorStore.getState().setFileTree(tree);
          }
        }),
        window.electronAPI.onMenuEvent('menu:open-file', async () => {
          const result = await window.electronAPI?.openFile();
          if (result?.success && result.content) {
            useEditorStore.getState().openFile({
              id: result.path!,
              filePath: result.path!,
              fileName: result.name!,
              content: result.content,
              isDirty: false,
              language: getLanguageFromPath(result.path!),
            });
          }
        }),
        window.electronAPI.onMenuEvent('menu:new-chat', () => {
          useChatStore.getState().clearChat();
        }),
        window.electronAPI.onMenuEvent('backend:status', (status: string) => {
          useBackendStore.getState().setBackendStatus(status as any);
        }),
      ];
      return () => unsubs.forEach((fn) => fn?.());
    }
  }, []);

  // ── 键盘快捷键 ──
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(true);
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault();
        toggleSidebar();
      }
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'a') {
        e.preventDefault();
        toggleAIPanel();
      }
      if ((e.ctrlKey || e.metaKey) && e.key === '`') {
        e.preventDefault();
        toggleBottomPanel();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [setCommandPaletteOpen, toggleSidebar, toggleAIPanel, toggleBottomPanel]);

  // ── 面板拖拽 ──
  const handleSidebarResize = useCallback((delta: number) => {
    setLayout({ sidebarWidth: Math.max(150, Math.min(400, layout.sidebarWidth + delta)) });
  }, [layout.sidebarWidth, setLayout]);

  const handleAIPanelResize = useCallback((delta: number) => {
    setLayout({ aiPanelWidth: Math.max(200, Math.min(600, layout.aiPanelWidth - delta)) });
  }, [layout.aiPanelWidth, setLayout]);

  const handleBottomPanelResize = useCallback((delta: number) => {
    setLayout({ bottomPanelHeight: Math.max(80, Math.min(500, layout.bottomPanelHeight - delta)) });
  }, [layout.bottomPanelHeight, setLayout]);

  const activeTab = openTabs.find((t) => t.id === activeTabId);
  const sidebarVisible = layout.sidebarOpen;

  return (
    <div className="app-root">
      {backendConnecting ? (
        <div className="app-loading">
          <div className="loading-logo">PyCoder IDE</div>
          <div className="loading-subtitle">Python AI 编程助手</div>
          <div className="loading-spinner" />
          <div className="loading-status">
            {backendStatus === 'stopped' || backendStatus === 'starting'
              ? '正在连接后端服务...'
              : backendStatus === 'error' || backendStatus === 'crashed'
                ? '后端服务异常，正在重试...'
                : '正在初始化...'}
          </div>
          {(backendStatus === 'error' || backendStatus === 'crashed') && (
            <button
              className="loading-retry-btn"
              onClick={() => {
                setBackendConnecting(true);
                setBackendStatus('stopped');
                window.location.reload();
              }}
            >
              重新加载
            </button>
          )}
        </div>
      ) : (
        <>
          <MenuBar />
          <ProjectStatusBar />
          <div className="app-main">
            <ActivityBar />
            {sidebarVisible && (
              <>
                <Sidebar />
                <Resizer direction="horizontal" onResize={handleSidebarResize} />
              </>
            )}
            <div className="editor-area">
              {openTabs.length > 0 && <EditorTabs />}
              <div className="editor-content">
                {browserPanelOpen ? (
                  <BrowserPanel />
                ) : activeTab ? (
                  <MonacoEditor
                    key={activeTab.id}
                    filePath={activeTab.filePath}
                    content={activeTab.content}
                    language={activeTab.language}
                    wsClient={wsClient}
                    onCodeReplaced={(newCode: string) => updateTabContent(activeTab.id, newCode)}
                  />
                ) : (
                  <WelcomeScreen />
                )}
              </div>
              <DiffPreview wsClient={wsClient} />
              {layout.bottomPanelOpen && (
                <>
                  <Resizer direction="vertical" onResize={handleBottomPanelResize} />
                  <div className="bottom-panel" style={{ height: `${layout.bottomPanelHeight}px` }}>
                    <Suspense fallback={<PanelFallback />}>
                      {bottomPanel === 'terminal' && <TerminalPanel />}
                      {bottomPanel === 'output' && <OutputPanel />}
                      {bottomPanel === 'problems' && <ProblemsPanel />}
                      {bottomPanel === 'runner' && <PythonRunnerPanel />}
                      {bottomPanel === 'testgen' && <TestGenPanel />}
                      {bottomPanel === 'runfix' && <RunFixPanel />}
                      {bottomPanel === 'debug' && <DebugPanel />}
                      {bottomPanel === 'preview' && <WebPreview />}
                      {bottomPanel === 'images' && <ImageViewer />}
                      {bottomPanel === 'search' && <ChatHistorySearch wsClient={wsClient} />}
                      {bottomPanel === 'deps' && <DependencyManager />}
                      {bottomPanel === 'theme' && <ThemeManager />}
                    </Suspense>
                  </div>
                </>
              )}
            </div>
            {layout.aiPanelOpen && (
              <>
                <Resizer direction="horizontal" onResize={handleAIPanelResize} />
                <AIPanel wsClient={wsClient} />
              </>
            )}
            {evoPanelOpen && <EvolutionPanel />}
          </div>
          <StatusBar />
          <CommandPalette />
        </>
      )}
    </div>
  );
};

const App: React.FC = () => {
  // F4 移动端支持：移动 UA / 窄屏触摸环境渲染 MobileLayout，否则桌面三栏布局
  const mobile = useIsMobile();
  return (
    <ErrorBoundary>
      {mobile ? <MobileLayout /> : <AppInner />}
    </ErrorBoundary>
  );
};

export default App;
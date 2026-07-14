import React, { useEffect, useState, useCallback, useRef } from 'react';
import { ActivityBar } from './components/ActivityBar';
import { Sidebar } from './components/Sidebar';
import { EditorTabs } from './components/EditorTabs';
import { MonacoEditor } from './components/MonacoEditor';
import { AIPanel } from './components/AIPanel';
import { StatusBar } from './components/StatusBar';
import { TerminalPanel } from './components/TerminalPanel';
import { DiffPreview } from './components/DiffPreview';
import { EvolutionPanel } from './components/EvolutionPanel';
import { WebPreview } from './components/WebPreview';
import { ImageViewer } from './components/ImageViewer';
import { ChatHistorySearch } from './components/ChatHistorySearch';
import { DependencyManager } from './components/DependencyManager';
import { ThemeManager } from './components/ThemeManager';
import { CommandPalette } from './components/CommandPalette';
import { ErrorBoundary } from './components/ErrorBoundary';
import { MenuBar } from './components/MenuBar';
import WelcomeScreen from './components/WelcomeScreen';
import { OutputPanel } from './components/OutputPanel';
import { ProblemsPanel } from './components/ProblemsPanel';
import { PythonRunnerPanel } from './components/PythonRunnerPanel';
import { TestGenPanel } from './components/TestGenPanel';
import { RunFixPanel } from './components/RunFixPanel';
import { DebugPanel } from './components/DebugPanel';
import { BrowserPanel } from './components/BrowserPanel';
import { useAppStore } from './stores/appStore';
import { BackendAPI } from './services/backend';
import { WSConnectionManager } from './services/websocket';
import { getWsUrl, getApiKey } from './services/config';
import { getLanguageFromPath } from './utils/language';

let wsClient: WSConnectionManager | null = null;

(async () => {
  // V2: 使用 AI-Centric WebSocket 端点
  const [url, apiKey] = await Promise.all([getWsUrl('/ws/chat/v2'), getApiKey()]);
  const wsUrl = apiKey ? `${url}?api_key=${encodeURIComponent(apiKey)}` : url;
  wsClient = new WSConnectionManager(wsUrl);

  // 认证失败时重新获取 api_key 并重建连接 URL
  wsClient.onAuthFail = async () => {
    console.warn('[WS] 认证失败，尝试重新获取 API Key...');
    const freshKey = await getApiKey();
    if (freshKey) {
      const newUrl = `${url}?api_key=${encodeURIComponent(freshKey)}`;
      wsClient = new WSConnectionManager(newUrl);
      wsClient.onAuthFail = wsClient.onAuthFail; // 保留回调
      wsClient.connect();
      useAppStore.getState().setWsClient(wsClient);
    } else {
      // 无 Key 则普通重连（后端可能关闭了认证）
      wsClient.connect();
    }
  };

  wsClient.connect();
  const check = () => {
    if (useAppStore.getState().wsClient === null) {
      useAppStore.getState().setWsClient(wsClient);
    }
  };
  setTimeout(check, 100);
})();



const Resizer: React.FC<{
  direction: 'horizontal' | 'vertical';
  onResize: (delta: number) => void;
}> = ({ direction, onResize }) => {
  const [isDragging, setIsDragging] = useState(false);
  const startRef = useRef(0);

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
    startRef.current = direction === 'horizontal' ? e.clientX : e.clientY;
    document.body.style.cursor = direction === 'horizontal' ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
    document.body.style.pointerEvents = 'none';
  };

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      e.preventDefault();
      const current = direction === 'horizontal' ? e.clientX : e.clientY;
      const delta = current - startRef.current;
      onResize(delta);
      startRef.current = current;
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.body.style.pointerEvents = '';
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.body.style.pointerEvents = '';
    };
  }, [isDragging, onResize, direction]);

  return (
    <div
      className={`resizer ${direction === 'vertical' ? 'resizer-vertical' : ''} ${isDragging ? 'dragging' : ''}`}
      onMouseDown={handleMouseDown}
    />
  );
};

const AppInner: React.FC = () => {
  const {
    activeSidebar,
    activeGroup,
    layout,
    setLayout,
    toggleSidebar,
    toggleAIPanel,
    toggleBottomPanel,
    setCommandPaletteOpen,
    evoPanelOpen,
    toggleEvoPanel,
    browserPanelOpen,
    toggleBrowserPanel,
    activeTabId,
    openTabs,
    bottomPanel,
    updateTabContent,
    setBackendStatus,
    setModels,
    setFileTree,
    setGitStatus,
    setSessions,
    setActiveSession,
    theme,
    toggleTheme,
  } = useAppStore();

  // 应用主题到 document 元素
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    let healthRetries = 0;
    const checkBackend = async () => {
      const health = await BackendAPI.health();
      if (health?.status === 'ok') {
        healthRetries = 0;
        setBackendStatus('running');

        const [modelsRes, envRes, gitRes, sessionsRes] = await Promise.all([
          BackendAPI.models(),
          BackendAPI.env(),
          BackendAPI.git.status(),
          BackendAPI.sessions.list(),
        ]);

        if (modelsRes?.models) {
          setModels(modelsRes.models);
          const recommended = modelsRes.recommended_model || modelsRes.models[0]?.id || 'deepseek-chat';
          useAppStore.getState().setCurrentModel(recommended);
        }
        if (envRes?.workspace && window.electronAPI) {
          window.electronAPI.getFileTree(envRes.workspace, 4).then(setFileTree);
        }

        // 自动恢复上次工作区
        const restoreRes = await BackendAPI.workspace.restore();
        if (restoreRes?.restored && window.electronAPI) {
          const tree = await window.electronAPI.getFileTree(restoreRes.path, 4);
          if (tree) {
            useAppStore.getState().setProjectRoot(restoreRes.path);
            setFileTree(tree);
          }
        }

        if (gitRes) setGitStatus(gitRes);
        if (sessionsRes?.sessions) {
          setSessions(sessionsRes.sessions);
          const firstId = sessionsRes.sessions[0]?.id || null;
          setActiveSession(firstId);
        }

        wsClient?.connect();
      } else {
        healthRetries++;
        // 指数退避: 2s → 4s → 8s → 16s (上限30s)
        const delay = Math.min(2000 * Math.pow(2, healthRetries - 1), 30000);
        setTimeout(checkBackend, delay);
      }
    };
    checkBackend();
    return () => { wsClient?.disconnect(); };
  }, []);

  useEffect(() => {
    if (window.electronAPI) {
      const unsubs = [
        window.electronAPI.onMenuEvent('menu:open-project', async () => {
          const result = await window.electronAPI?.openProject();
          if (result?.success && result.path) {
            useAppStore.getState().setProjectRoot(result.path);
            const tree = await window.electronAPI?.getFileTree(result.path, 4);
            if (tree) useAppStore.getState().setFileTree(tree);
          }
        }),
        window.electronAPI.onMenuEvent('menu:open-file', async () => {
          const result = await window.electronAPI?.openFile();
          if (result?.success && result.content) {
            useAppStore.getState().openFile({
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
          useAppStore.getState().clearChat();
        }),
        window.electronAPI.onMenuEvent('backend:status', (status: string) => {
          useAppStore.getState().setBackendStatus(status as any);
        }),
      ];
      return () => unsubs.forEach((fn) => fn?.());
    }
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

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
      <MenuBar />
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
    </div>
  );
};

const App: React.FC = () => (
  <ErrorBoundary>
    <AppInner />
  </ErrorBoundary>
);

export default App;
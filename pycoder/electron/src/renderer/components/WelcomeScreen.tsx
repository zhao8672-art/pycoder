import React from 'react';
import { useUIStore } from '../stores/uiStore';
import { useEditorStore } from '../stores/editorStore';

const WelcomeScreen: React.FC = () => {
  const { setActiveSidebar, setLayout, toggleAIPanel, toggleEvoPanel, toggleBottomPanel, setBottomPanel, setCommandPaletteOpen } = useUIStore();
  const { setProjectRoot, setFileTree } = useEditorStore();

  const shortcuts = [
    { key: 'Ctrl+K', label: '命令面板', description: '快速访问所有功能' },
    { key: 'Ctrl+B', label: '文件浏览器', description: '浏览和管理项目文件' },
    { key: 'Ctrl+Shift+A', label: 'AI 对话', description: '打开 AI 编程助手面板' },
    { key: 'Ctrl+`', label: '终端面板', description: '执行命令和查看输出' },
  ];

  const quickActions = [
    {
      icon: '\u{1F4C2}',
      title: '打开项目',
      description: '浏览和管理项目文件',
      action: () => {
        setActiveSidebar('files');
        setLayout({ sidebarOpen: true });
      },
    },
    {
      icon: '\u{1F4AC}',
      title: 'AI 对话',
      description: '与 AI 助手交流代码问题',
      action: () => toggleAIPanel(),
    },
    {
      icon: '\u26A1',
      title: '快速命令',
      description: '搜索命令、文件和符号',
      action: () => setCommandPaletteOpen(true),
    },
    {
      icon: '\u{1F9EC}',
      title: '自我进化',
      description: 'AI 自主修复和升级代码',
      action: () => toggleEvoPanel(),
    },
    {
      icon: '\u{1F465}',
      title: 'Agent 团队',
      description: '多 Agent 协同开发',
      action: () => {
        setActiveSidebar('team');
        setLayout({ sidebarOpen: true });
      },
    },
    {
      icon: '\u{1F9E9}',
      title: '技能市场',
      description: '发现和安装 AI 技能',
      action: () => {
        setActiveSidebar('skills');
        setLayout({ sidebarOpen: true });
      },
    },
    {
      icon: '\u25B6',
      title: '运行终端',
      description: '执行命令和查看输出',
      action: () => {
        setBottomPanel('terminal');
        toggleBottomPanel();
      },
    },
    {
      icon: '\u{1F527}',
      title: '打开文件',
      description: '快速打开本地文件',
      action: async () => {
        if (window.electronAPI) {
          const result = await window.electronAPI.openFile();
          if (result?.success && result.content) {
            useEditorStore.getState().openFile({
              id: result.path!,
              filePath: result.path!,
              fileName: result.name!,
              content: result.content,
              isDirty: false,
              language: (await import('../utils/language')).getLanguageFromPath(result.path!),
            });
          }
        }
      },
    },
  ];

  const recentProjects: Array<{ name: string; path: string; icon: string }> = [
    { name: 'pycode', path: 'C:\\Users\\Administrator\\Desktop\\pycode', icon: '\u{1F40D}' },
    { name: 'yzkapp', path: 'C:\\Users\\Administrator\\Desktop\\yzkapp', icon: '\u{1F4D0}' },
    { name: 'milaweb', path: 'C:\\Users\\Administrator\\Desktop\\milaweb', icon: '\u{1F310}' },
  ];

  return (
    <div className="welcome-screen">
      <div className="welcome-hero">
        <div className="welcome-logo">
          <div className="welcome-icon-wrapper">{'\u{1F40D}'}</div>
          <h1>PyCoder IDE</h1>
        </div>
        <p className="welcome-subtitle">Python 开发者原生的 AI 编程 IDE</p>
        <p className="welcome-tagline">智能编码 · AI 驱动 · 极速开发</p>
      </div>

      <div className="welcome-section">
        <div className="welcome-section-title">快速开始</div>
        <div className="welcome-actions">
          {quickActions.map((action) => (
            <button
              key={action.title}
              className="welcome-action-card"
              onClick={action.action}
              title={action.description}
            >
              <span className="action-icon">{action.icon}</span>
              <div className="action-content">
                <span className="action-title">{action.title}</span>
                <span className="action-desc">{action.description}</span>
              </div>
            </button>
          ))}
        </div>
      </div>

      {recentProjects.length > 0 && (
        <div className="welcome-section">
          <div className="welcome-section-title">最近项目</div>
          <div className="welcome-recent">
            {recentProjects.map((proj) => (
              <div
                key={proj.path}
                className="welcome-recent-item"
                onClick={() => {
                  if (window.electronAPI) {
                    window.electronAPI.getFileTree(proj.path, 4).then((tree: any) => {
                      if (tree) {
                        setProjectRoot(proj.path);
                        setFileTree(tree);
                      }
                    });
                  }
                }}
              >
                <span className="welcome-recent-icon">{proj.icon}</span>
                <div className="welcome-recent-info">
                  <span className="welcome-recent-name">{proj.name}</span>
                  <span className="welcome-recent-path">{proj.path}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="welcome-section">
        <div className="welcome-section-title">常用快捷键</div>
        <div className="welcome-shortcuts">
          {shortcuts.map((shortcut) => (
            <div key={shortcut.key} className="shortcut-item">
              <kbd>{shortcut.key}</kbd>
              <div className="shortcut-info">
                <span className="shortcut-label">{shortcut.label}</span>
                <span className="shortcut-desc">{shortcut.description}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default WelcomeScreen;
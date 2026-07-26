import React from 'react';
import { useUIStore } from '../stores/uiStore';
import { useAppStore } from '../stores/appStore';
import { t } from '../../locales';
import { Icon } from './common/Icon';
import type { IconName } from './common/Icon';

interface ActivityItem {
  id: string;
  icon: IconName;
  label: string;
  tooltip: string;
  badge?: number;
  action: 'sidebar' | 'toggle-ai' | 'toggle-evo' | 'toggle-browser' | 'toggle-bottom' | 'command-palette';
  sidebarView?: string;
}

const GROUP_CORE: ActivityItem[] = [
  { id: 'files', icon: 'folder', label: '文件', tooltip: 'fileManager', action: 'sidebar', sidebarView: 'files' },
  { id: 'workspace', icon: 'folder-open', label: '工作区', tooltip: 'workspaceManager', action: 'sidebar', sidebarView: 'workspace' },
  { id: 'search', icon: 'search', label: '搜索', tooltip: 'searchInFiles', action: 'sidebar', sidebarView: 'search' },
  { id: 'git', icon: 'git', label: 'Git', tooltip: 'versionControl', action: 'sidebar', sidebarView: 'git' },
  { id: 'ai', icon: 'bot', label: 'AI', tooltip: 'aiAssistant', action: 'toggle-ai' },
];

const GROUP_AI_TOOLS: ActivityItem[] = [
  { id: 'team', icon: 'team', label: '团队', tooltip: 'aiAgentTeam', action: 'sidebar', sidebarView: 'team' },
  { id: 'evolution', icon: 'evolution', label: '进化', tooltip: 'evolutionEngine', action: 'toggle-evo' },
  { id: 'skills', icon: 'puzzle', label: '技能', tooltip: 'skillsMarket', action: 'sidebar', sidebarView: 'skills' },
  { id: 'extensions', icon: 'extensions', label: '扩展', tooltip: 'extensionsManager', action: 'sidebar', sidebarView: 'extensions' },
  { id: 'snippets', icon: 'snippets', label: '片段', tooltip: 'snippetsManager', action: 'sidebar', sidebarView: 'snippets' },
];

const GROUP_UTILITIES: ActivityItem[] = [
  { id: 'browser', icon: 'browser', label: '浏览', tooltip: 'builtinBrowser', action: 'toggle-browser' },
  { id: 'terminal', icon: 'run', label: '运行', tooltip: 'terminalRunner', action: 'toggle-bottom' },
  { id: 'command', icon: 'command', label: '命令', tooltip: 'commandPalette', action: 'command-palette' },
];

const GROUP_SYSTEM: ActivityItem[] = [
  { id: 'cloud', icon: 'cloud', label: '云', tooltip: 'pycoderCloud', action: 'sidebar', sidebarView: 'cloud' },
  { id: 'settings', icon: 'settings', label: '设置', tooltip: 'settings', action: 'sidebar', sidebarView: 'settings' },
];

export const ActivityBar: React.FC = () => {
  const {
    activeSidebar,
    layout,
    toggleSidebar,
    toggleAIPanel,
    toggleBottomPanel,
    setActiveSidebar,
    setCommandPaletteOpen,
    evoPanelOpen,
    toggleEvoPanel,
    toggleBrowserPanel,
    browserPanelOpen,
  } = useUIStore();
  const { gitStatus } = useAppStore();

  const gitChangeCount = gitStatus?.changes?.length || 0;

  const handleItemClick = (item: ActivityItem) => {
    switch (item.action) {
      case 'toggle-ai':
        toggleAIPanel();
        return;
      case 'toggle-evo':
        toggleEvoPanel();
        return;
      case 'toggle-browser':
        toggleBrowserPanel();
        return;
      case 'toggle-bottom':
        toggleBottomPanel();
        return;
      case 'command-palette':
        setCommandPaletteOpen(true);
        return;
      case 'sidebar':
      default:
        if (item.sidebarView === 'git') {
          if (activeSidebar === 'git' || activeSidebar === 'github' || activeSidebar === 'diff' || activeSidebar === 'branches' || activeSidebar === 'upload') {
            toggleSidebar();
          } else {
            setActiveSidebar('git');
            useUIStore.getState().setLayout({ sidebarOpen: true });
          }
        } else if (activeSidebar === item.sidebarView && layout.sidebarOpen) {
          toggleSidebar();
        } else {
          setActiveSidebar(item.sidebarView!);
          useUIStore.getState().setLayout({ sidebarOpen: true });
        }
        return;
    }
  };

  const isActive = (item: ActivityItem): boolean => {
    switch (item.action) {
      case 'toggle-ai':
        return layout.aiPanelOpen;
      case 'toggle-evo':
        return evoPanelOpen;
      case 'toggle-browser':
        return browserPanelOpen;
      case 'toggle-bottom':
        return layout.bottomPanelOpen;
      case 'sidebar':
        if (item.sidebarView === 'git') {
          return layout.sidebarOpen && ['git', 'github', 'diff', 'branches', 'upload'].includes(activeSidebar || '');
        }
        return layout.sidebarOpen && activeSidebar === item.sidebarView;
      default:
        return false;
    }
  };

  const renderGroup = (items: ActivityItem[]) =>
    items.map((item) => (
      <button
        key={item.id}
        role="tab"
        aria-selected={isActive(item)}
        className={`activity-btn ${isActive(item) ? 'active' : ''}`}
        onClick={() => handleItemClick(item)}
        title={t(`activity.${item.tooltip}`, item.tooltip)}
      >
        <span className="activity-icon" aria-hidden="true"><Icon name={item.icon} size={18} /></span>
        <span className="activity-label">{t(`activity.${item.label}`, item.label)}</span>
        {item.id === 'git' && gitChangeCount > 0 && (
          <span className="activity-badge">{gitChangeCount}</span>
        )}
      </button>
    ));

  return (
    <div className="activity-bar" role="navigation" aria-label={t('activity.sidebar', '侧边栏导航')}>
      <div className="activity-bar-main" role="tablist">
        <div className="activity-group">{renderGroup(GROUP_CORE)}</div>
        <div className="activity-divider" />
        <div className="activity-group">{renderGroup(GROUP_AI_TOOLS)}</div>
        <div className="activity-divider" />
        <div className="activity-group">{renderGroup(GROUP_UTILITIES)}</div>
      </div>
      <div className="activity-bar-bottom">
        <div className="activity-group">{renderGroup(GROUP_SYSTEM)}</div>
      </div>
    </div>
  );
};

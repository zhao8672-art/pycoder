import React from 'react';
import { useAppStore } from '../stores/appStore';
import { FileTree } from './FileTree';
import { SearchPanel } from './SearchPanel';
import { GitPanel } from './GitPanel';
import { GitHubPanel } from './GitHubPanel';
import { SettingsPanel } from './SettingsPanel';
import { SkillsMarket } from './SkillsMarket';
import { TeamPanel } from './TeamPanel';
import { CloudPanel } from './CloudPanel';
import { ExtensionsPanel } from './ExtensionsPanel';
import { DropZone } from './DropZone';
import { DiffView } from './DiffView';
import { GitBranchGraph } from './GitBranchGraph';
import { SnippetsPanel } from './SnippetsPanel';

export const Sidebar: React.FC = () => {
  const { activeSidebar, toggleSidebar, wsClient, layout } = useAppStore();

  const itemConfig: Record<string, { label: string; icon: string }> = {
    files: { label: '文件资源管理器', icon: '📁' },
    search: { label: '搜索', icon: '🔍' },
    git: { label: 'Git', icon: '📦' },
    github: { label: 'GitHub', icon: '🐙' },
    diff: { label: '差异对比', icon: '📊' },
    branches: { label: '分支管理', icon: '🌿' },
    upload: { label: '文件上传', icon: '📤' },
    skills: { label: '技能市场', icon: '🧩' },
    extensions: { label: '扩展管理', icon: '🧰' },
    snippets: { label: '代码片段', icon: '📋' },
    team: { label: '团队协作', icon: '👥' },
    cloud: { label: 'PyCoder Cloud', icon: '☁️' },
    settings: { label: '设置', icon: '⚙' },
  };

  const config = itemConfig[activeSidebar] || itemConfig.files;

  const renderContent = () => {
    switch (activeSidebar) {
      case 'files':
        return <FileTree />;
      case 'search':
        return <SearchPanel />;
      case 'git':
        return <GitPanel />;
      case 'github':
        return <GitHubPanel />;
      case 'diff':
        return <DiffView />;
      case 'branches':
        return <GitBranchGraph />;
      case 'upload':
        return <DropZone />;
      case 'snippets':
        return <SnippetsPanel />;
      case 'skills':
        return wsClient ? <SkillsMarket wsClient={wsClient} /> : <div className="sidebar-placeholder">WebSocket 未连接</div>;
      case 'extensions':
        return <ExtensionsPanel />;
      case 'team':
        return wsClient ? <TeamPanel wsClient={wsClient} /> : <div className="sidebar-placeholder">WebSocket 未连接</div>;
      case 'cloud':
        return wsClient ? <CloudPanel wsClient={wsClient} /> : <div className="sidebar-placeholder">WebSocket 未连接</div>;
      case 'settings':
        return <SettingsPanel />;
      default:
        return <FileTree />;
    }
  };

  return (
    <div className="sidebar" style={{ width: `${layout.sidebarWidth}px` }}>
      <div className="sidebar-header">
        <span className="sidebar-icon">{config.icon}</span>
        <span className="sidebar-title">{config.label}</span>
        <button className="sidebar-close-btn" onClick={toggleSidebar}>
          ✕
        </button>
      </div>
      <div className="sidebar-content">
        {renderContent()}
      </div>
    </div>
  );
};
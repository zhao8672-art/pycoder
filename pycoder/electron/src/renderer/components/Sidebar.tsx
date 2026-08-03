import React, { Suspense, lazy } from 'react';
import { useAppStore } from '../stores/appStore';
import { FileTree } from './FileTree';
import { WorkspacePanel } from './WorkspacePanel';
import { SearchPanel } from './SearchPanel';
import { GitPanel } from './GitPanel';
import { GitHubPanel } from './GitHubPanel';
import { DropZone } from './DropZone';
import { DiffView } from './DiffView';
import { GitBranchGraph } from './GitBranchGraph';
import { SnippetsPanel } from './SnippetsPanel';

// 懒加载重量级面板
const SkillsMarketV2 = lazy(() => import('./skills-v2/SkillsMarketV2'));
const ExtensionsPanel = lazy(() => import('./ExtensionsPanel'));
const SettingsPanel = lazy(() => import('./SettingsPanel'));
const TeamPanel = lazy(() => import('./TeamPanel'));
const CloudPanel = lazy(() => import('./CloudPanel'));
const DatabasePanel = lazy(() => import('./DatabasePanel'));

// 懒加载骨架屏
const PanelSkeleton = () => (
  <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
    {Array.from({ length: 6 }).map((_, i) => (
      <div key={i} style={{
        height: 60, borderRadius: 6,
        background: 'linear-gradient(90deg, var(--bg-secondary) 25%, var(--bg-tertiary) 50%, var(--bg-secondary) 75%)',
        backgroundSize: '200% 100%',
        animation: 'shimmer 1.5s infinite',
      }} />
    ))}
    <style>{`@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>
  </div>
);

export const Sidebar: React.FC = () => {
  const { activeSidebar, toggleSidebar, wsClient, layout } = useAppStore();

  const itemConfig: Record<string, { label: string; icon: string }> = {
    files: { label: '文件资源管理器', icon: '📁' },
    workspace: { label: '工作区管理', icon: '📂' },
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
    database: { label: '数据库', icon: '🗄️' },
    settings: { label: '设置', icon: '⚙' },
  };

  const config = itemConfig[activeSidebar] || itemConfig.files;

  const renderContent = () => {
    switch (activeSidebar) {
      case 'files':
        return <FileTree />;
      case 'workspace':
        return <WorkspacePanel />;
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
        return <Suspense fallback={<PanelSkeleton />}><SkillsMarketV2 /></Suspense>;
      case 'extensions':
        return <Suspense fallback={<PanelSkeleton />}><ExtensionsPanel /></Suspense>;
      case 'team':
        return wsClient ? <Suspense fallback={<PanelSkeleton />}><TeamPanel wsClient={wsClient} /></Suspense> : <div className="sidebar-placeholder">WebSocket 未连接</div>;
      case 'cloud':
        return wsClient ? <Suspense fallback={<PanelSkeleton />}><CloudPanel wsClient={wsClient} /></Suspense> : <div className="sidebar-placeholder">WebSocket 未连接</div>;
      case 'database':
        return <Suspense fallback={<PanelSkeleton />}><DatabasePanel /></Suspense>;
      case 'settings':
        return <Suspense fallback={<PanelSkeleton />}><SettingsPanel /></Suspense>;
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
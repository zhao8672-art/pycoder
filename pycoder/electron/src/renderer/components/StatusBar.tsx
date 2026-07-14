import React from 'react';
import { useAppStore, useUIStore, useChatStore } from '../stores/appStore';
import { t } from '../../locales';

const BOTTOM_TABS = [
  { id: 'terminal', icon: '\u25B6', label: '\u7EC8\u7AEF' },
  { id: 'output', icon: '\u{1F4DC}', label: '\u8F93\u51FA' },
  { id: 'problems', icon: '\u26A0', label: '\u95EE\u9898' },
  { id: 'runner', icon: '\u{1F40D}', label: 'Python' },
  { id: 'testgen', icon: '\u{1F9EA}', label: '\u6D4B\u8BD5' },
  { id: 'runfix', icon: '\u{1F504}', label: '\u4FEE\u590D' },
  { id: 'debug', icon: '\u{1F41B}', label: '\u8C03\u8BD5' },
  { id: 'preview', icon: '\u{1F310}', label: '\u9884\u89C8' },
  { id: 'images', icon: '\u{1F5BC}', label: '\u56FE\u7247' },
  { id: 'search', icon: '\u{1F50D}', label: '\u68C0\u7D22' },
  { id: 'deps', icon: '\u{1F4E6}', label: '\u4F9D\u8D56' },
  { id: 'theme', icon: '\u{1F3A8}', label: '\u4E3B\u9898' },
] as const;

export const StatusBar: React.FC = () => {
  const { backendStatus, currentModel, gitStatus } = useAppStore();
  const { bottomPanel, setBottomPanel, layout, toggleBottomPanel, theme, toggleTheme } = useUIStore();
  const { tokenCount, estimatedCost, v2Engine, v2Capabilities, v2TrustLevel } = useChatStore();
  const formattedTokens = tokenCount >= 1000 ? `${(tokenCount / 1000).toFixed(1)}k` : String(tokenCount);
  const formattedCost = `¥${estimatedCost.toFixed(2)}`;

  const statusColor: Record<string, string> = {
    running: 'var(--accent-green)',
    starting: 'var(--accent-yellow)',
    stopped: 'var(--accent-red)',
    crashed: 'var(--accent-red)',
    error: 'var(--accent-red)',
  };

  const statusText: Record<string, string> = {
    running: t('status.connected', '\u5DF2\u8FDE\u63A5'),
    starting: t('status.connecting', '\u8FDE\u63A5\u4E2D...'),
    stopped: t('status.disconnected', '\u672A\u8FDE\u63A5'),
    crashed: t('status.crashed', '\u5DF2\u5D29\u6E83'),
    error: t('status.error', '\u9519\u8BEF'),
  };

  const modifiedCount = gitStatus?.changes?.filter((c: any) => c.status === 'M' || c.status === 'MM').length || 0;
  const addedCount = gitStatus?.changes?.filter((c: any) => c.status === 'A' || c.status === '??').length || 0;

  return (
    <div className="status-bar" role="status" aria-label={t('status.bar', '\u72B6\u6001\u680F')}>
      <div className="status-left">
        <span className="status-item">
          <span
            className="status-dot"
            style={{
              background: statusColor[backendStatus],
              color: statusColor[backendStatus],
              animation: backendStatus === 'running' ? 'pulse 2s ease-in-out infinite' : undefined,
            }}
            aria-hidden="true"
          />
          {statusText[backendStatus]}
        </span>

        {currentModel && (
          <>
            <span className="status-divider" aria-hidden="true" />
            <span className="status-item" style={{ color: 'var(--accent-primary)' }}>
              {'\u{1F916}'} {currentModel}
            </span>
          </>
        )}

        {/* V2 AI-Centric 引擎指示器 */}
        {v2Engine && (
          <>
            <span className="status-divider" aria-hidden="true" />
            <span className="status-item" style={{ color: 'var(--accent-green)' }} title={`V2 引擎 | ${v2Capabilities} 个能力 | 信任级别: ${v2TrustLevel}`}>
              ⚡ V2 {v2Capabilities > 0 ? `(${v2Capabilities})` : ''}
            </span>
          </>
        )}

        {/* AI 用量 */}
        <span className="status-divider" aria-hidden="true" />
        <span className="status-item status-mono">Token：{formattedTokens}</span>
        <span className="status-item status-mono">{formattedCost}</span>

        {gitStatus?.branch && (
          <>
            <span className="status-divider" aria-hidden="true" />
            <span className="status-item">
              {'\uE0A0'} {gitStatus.branch}
            </span>
            {modifiedCount > 0 && (
              <span className="status-git-badge modified" aria-label={`${modifiedCount} \u4E2A\u6587\u4EF6\u5DF2\u4FEE\u6539`}>
                {modifiedCount} M
              </span>
            )}
            {addedCount > 0 && (
              <span className="status-git-badge added" aria-label={`${addedCount} \u4E2A\u6587\u4EF6\u5DF2\u6DFB\u52A0`}>
                {addedCount} A
              </span>
            )}
          </>
        )}
      </div>

      <div className="status-right">
        <button
          className="theme-toggle"
          onClick={toggleTheme}
          title={theme === 'dark' ? t('status.switchToLight', '\u5207\u6362\u660E\u4EAE\u4E3B\u9898') : t('status.switchToDark', '\u5207\u6362\u6697\u8272\u4E3B\u9898')}
          aria-label={theme === 'dark' ? t('status.switchToLight', '\u5207\u6362\u660E\u4EAE\u4E3B\u9898') : t('status.switchToDark', '\u5207\u6362\u6697\u8272\u4E3B\u9898')}
        >
          {theme === 'dark' ? '\u2600\uFE0F' : '\u{1F319}'}
        </button>

        <span className="status-divider" aria-hidden="true" />

        <div className="status-bottom-tabs">
          {BOTTOM_TABS.map((tab) => (
            <button
              key={tab.id}
              className={`status-tab ${bottomPanel === tab.id ? 'active' : ''}`}
              onClick={() => {
                setBottomPanel(tab.id);
                if (!layout.bottomPanelOpen) {
                  toggleBottomPanel();
                }
              }}
              title={t(`status.${tab.label}`, tab.label)}
              aria-label={t(`status.${tab.label}`, tab.label)}
            >
              <span className="status-tab-icon" aria-hidden="true">{tab.icon}</span>
              <span className="status-tab-label">{t(`status.${tab.label}`, tab.label)}</span>
            </button>
          ))}
        </div>

        <span className="status-divider" aria-hidden="true" />

        <button
          className={`status-tab bottom-toggle ${layout.bottomPanelOpen ? 'active' : ''}`}
          onClick={toggleBottomPanel}
          aria-label={t('status.togglePanel', '\u5E95\u90E8\u9762\u677F')}
          title={t('status.togglePanel', '\u5E95\u90E8\u9762\u677F')}
        >
          {layout.bottomPanelOpen ? '\u25BC' : '\u25B2'}
        </button>
      </div>
    </div>
  );
};

/**
 * ProjectStatusBar — 项目路径状态指示器
 *
 * 功能:
 * - 启动时自动检测项目路径
 * - 状态栏显示当前项目路径和检测状态
 * - 手动选择项目目录
 * - 配置默认项目路径
 * - 错误提示与操作指引
 * - 历史工作区快速切换
 */
import React, { useState, useEffect, useCallback } from 'react';
import { BackendAPI } from '../services/backend';

type DetectStatus = 'detecting' | 'detected' | 'uncertain' | 'not_found' | 'manual' | 'error';

interface WorkspaceState {
  projectPath: string;
  projectName: string;
  status: DetectStatus;
  confidence: number;
  method: string;
  indicators: string[];
  suggestions: string[];
  elapsedMs: number;
  isTemp: boolean;
}

export const ProjectStatusBar: React.FC = () => {
  const [ws, setWs] = useState<WorkspaceState>({
    projectPath: '',
    projectName: '',
    status: 'detecting',
    confidence: 0,
    method: '',
    indicators: [],
    suggestions: [],
    elapsedMs: 0,
    isTemp: false,
  });
  const [showPanel, setShowPanel] = useState(false);
  const [history, setHistory] = useState<string[]>([]);
  const [defaultPath, setDefaultPath] = useState('');
  const [manualPath, setManualPath] = useState('');
  const [showManualInput, setShowManualInput] = useState(false);

  // ── 自动检测 ──
  const runDetection = useCallback(async () => {
    setWs(prev => ({ ...prev, status: 'detecting' }));
    try {
      const result = await BackendAPI.workspace.detect();
      if (result) {
        const status: DetectStatus =
          result.status === 'detected' ? 'detected' :
          result.status === 'uncertain' ? 'uncertain' : 'not_found';
        setWs({
          projectPath: result.project_path,
          projectName: result.name,
          status,
          confidence: result.confidence,
          method: result.method,
          indicators: result.indicators || [],
          suggestions: result.suggestions || [],
          elapsedMs: result.elapsed_ms,
          isTemp: false,
        });
      } else {
        setWs(prev => ({ ...prev, status: 'error' }));
      }
    } catch {
      setWs(prev => ({ ...prev, status: 'error' }));
    }
  }, []);

  const loadHistory = useCallback(async () => {
    try {
      const h = await BackendAPI.workspace.history();
      if (h) setHistory(h.workspaces || []);
    } catch { /* ignore */ }
  }, []);

  const loadConfig = useCallback(async () => {
    try {
      const c = await BackendAPI.workspace.getConfig();
      if (c) setDefaultPath(c.default_project_path || '');
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    runDetection();
    loadHistory();
    loadConfig();
  }, [runDetection, loadHistory, loadConfig]);

  // ── 手动设置 ──
  const handleSetPath = async (path: string, saveDefault: boolean = false) => {
    try {
      const result = await BackendAPI.workspace.setDetectPath(path, saveDefault);
      if (result) {
        setWs({
          projectPath: result.project_path,
          projectName: result.name,
          status: 'manual',
          confidence: result.confidence,
          method: result.method,
          indicators: result.indicators || [],
          suggestions: [],
          elapsedMs: 0,
          isTemp: false,
        });
        setShowPanel(false);
        setShowManualInput(false);
        setManualPath('');
        loadHistory();
        loadConfig();
      }
    } catch { /* ignore */ }
  };

  const handleSaveDefault = async () => {
    if (ws.projectPath) {
      await handleSetPath(ws.projectPath, true);
    }
  };

  // ── 状态指示器 ──
  const getStatusIcon = (): string => {
    switch (ws.status) {
      case 'detecting': return '⏳';
      case 'detected': return '✅';
      case 'uncertain': return '⚠️';
      case 'not_found': return '❌';
      case 'manual': return '📌';
      case 'error': return '🔴';
      default: return '❓';
    }
  };

  const getMethodLabel = (): string => {
    const labels: Record<string, string> = {
      startup_arg: '启动参数',
      user_config: '用户配置',
      electron: '前端选择',
      history: '历史记录',
      git: 'Git 仓库',
      indicator: '项目标识',
      heuristic: '启发式',
      manual: '手动指定',
      fallback: '默认路径',
    };
    return labels[ws.method] || ws.method;
  };

  const getStatusColor = (): string => {
    switch (ws.status) {
      case 'detecting': return '#f0ad4e';
      case 'detected': case 'manual': return '#5cb85c';
      case 'uncertain': return '#f0ad4e';
      case 'not_found': case 'error': return '#d9534f';
      default: return '#999';
    }
  };

  return (
    <>
      {/* ── 状态栏 ── */}
      <div className="psb-bar" onClick={() => { setShowPanel(!showPanel); loadHistory(); loadConfig(); }}>
        <span className="psb-icon" style={{ color: getStatusColor() }}>{getStatusIcon()}</span>
        <span className="psb-label">
          {ws.status === 'detecting' ? '检测中...' :
           ws.status === 'error' ? '检测失败' :
           ws.projectName || '无项目'}
        </span>
        {ws.projectPath && ws.status !== 'detecting' && (
          <span className="psb-path" title={ws.projectPath}>{ws.projectPath}</span>
        )}
        {ws.confidence > 0 && ws.status !== 'detecting' && (
          <span className="psb-confidence">
            {ws.confidence >= 0.8 ? '高' : ws.confidence >= 0.4 ? '中' : '低'}置信度
          </span>
        )}
        <span className="psb-arrow">{showPanel ? '▲' : '▼'}</span>
      </div>

      {/* ── 弹出面板 ── */}
      {showPanel && (
        <div className="psb-panel">
          <div className="psb-panel-header">
            <span>项目工作区</span>
            <button className="psb-btn psb-btn-sm" onClick={runDetection}>🔄 重新检测</button>
          </div>

          {/* ── 当前状态 ── */}
          <div className="psb-section">
            <div className="psb-status-row">
              <span className="psb-status-badge" style={{ background: getStatusColor() }}>
                {getStatusIcon()} {ws.status === 'detecting' ? '检测中' :
                 ws.status === 'detected' ? '已检测' :
                 ws.status === 'uncertain' ? '不确定' :
                 ws.status === 'not_found' ? '未找到' :
                 ws.status === 'manual' ? '已指定' : '错误'}
              </span>
              <span className="psb-method">方法: {getMethodLabel()}</span>
              {ws.elapsedMs > 0 && <span className="psb-elapsed">{ws.elapsedMs.toFixed(0)}ms</span>}
            </div>

            <div className="psb-field">
              <label>项目路径</label>
              <code className="psb-path-full">{ws.projectPath || '(未检测)'}</code>
            </div>

            {ws.indicators.length > 0 && (
              <div className="psb-field">
                <label>标识文件</label>
                <div className="psb-tags">
                  {ws.indicators.map(ind => (
                    <span key={ind} className="psb-tag">{ind}</span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* ── 建议 ── */}
          {ws.suggestions.length > 0 && (
            <div className="psb-section psb-suggestions">
              <label>建议</label>
              {ws.suggestions.map((s, i) => (
                <div key={i} className="psb-suggestion-item">{s}</div>
              ))}
            </div>
          )}

          {/* ── 手动指定路径 ── */}
          <div className="psb-section">
            <label>手动指定项目路径</label>
            {showManualInput ? (
              <div className="psb-input-row">
                <input
                  className="psb-input"
                  placeholder="输入项目根目录路径..."
                  value={manualPath}
                  onChange={e => setManualPath(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleSetPath(manualPath); }}
                />
                <button className="psb-btn" onClick={() => handleSetPath(manualPath)}>确认</button>
                <button className="psb-btn psb-btn-cancel" onClick={() => { setShowManualInput(false); setManualPath(''); }}>取消</button>
              </div>
            ) : (
              <button className="psb-btn" onClick={() => setShowManualInput(true)}>📂 浏览目录...</button>
            )}
          </div>

          {/* ── 默认路径配置 ── */}
          <div className="psb-section">
            <label>默认项目路径</label>
            <div className="psb-config-row">
              {defaultPath ? (
                <>
                  <code className="psb-default-path">{defaultPath}</code>
                  <button className="psb-btn psb-btn-sm" onClick={() => handleSetPath(defaultPath, false)}>
                    切换
                  </button>
                </>
              ) : (
                <span className="psb-muted">未配置（自动检测优先）</span>
              )}
            </div>
            {ws.projectPath && ws.projectPath !== defaultPath && (
              <button className="psb-btn psb-btn-sm" onClick={handleSaveDefault}>
                📌 设为默认路径
              </button>
            )}
          </div>

          {/* ── 历史记录 ── */}
          {history.length > 0 && (
            <div className="psb-section">
              <label>最近工作区</label>
              <div className="psb-history-list">
                {history.slice(0, 5).map((h, i) => (
                  <div
                    key={i}
                    className={`psb-history-item ${h === ws.projectPath ? 'active' : ''}`}
                    onClick={() => handleSetPath(h)}
                  >
                    <span className="psb-history-icon">📁</span>
                    <span className="psb-history-path">{h}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <style>{`
        .psb-bar {
          display: flex; align-items: center; gap: 6px;
          padding: 3px 8px; cursor: pointer;
          background: var(--bg-tertiary, #f0f0f0);
          border-bottom: 1px solid var(--border-color, #ddd);
          font-size: 12px; user-select: none;
          transition: background .15s;
        }
        .psb-bar:hover { background: var(--bg-hover, #e4e4e4); }
        .psb-icon { font-size: 13px; }
        .psb-label { font-weight: 600; color: var(--text-primary, #333); }
        .psb-path {
          flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
          color: var(--text-secondary, #666); font-family: 'Consolas', monospace;
          font-size: 11px;
        }
        .psb-confidence {
          font-size: 10px; padding: 1px 5px; border-radius: 3px;
          background: var(--bg-secondary, #e8e8e8);
          color: var(--text-secondary, #666);
        }
        .psb-arrow { font-size: 10px; color: var(--text-muted, #999); }

        .psb-panel {
          position: absolute; top: 26px; left: 0; right: 0; z-index: 1000;
          max-height: 480px; overflow-y: auto;
          background: var(--bg-primary, #fff);
          border: 1px solid var(--border-color, #ddd);
          border-top: none; box-shadow: 0 4px 12px rgba(0,0,0,.1);
          padding: 12px; display: flex; flex-direction: column; gap: 12px;
        }
        .psb-panel-header {
          display: flex; justify-content: space-between; align-items: center;
          font-weight: 600; font-size: 13px;
        }
        .psb-section {
          display: flex; flex-direction: column; gap: 6px;
        }
        .psb-section label {
          font-size: 11px; font-weight: 600; text-transform: uppercase;
          color: var(--text-secondary, #666); letter-spacing: .5px;
        }
        .psb-status-row {
          display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
        }
        .psb-status-badge {
          padding: 2px 8px; border-radius: 3px; font-size: 11px;
          color: #fff; font-weight: 600;
        }
        .psb-method { font-size: 11px; color: var(--text-secondary, #666); }
        .psb-elapsed { font-size: 10px; color: var(--text-muted, #999); }
        .psb-field { display: flex; flex-direction: column; gap: 2px; }
        .psb-path-full {
          font-size: 11px; font-family: 'Consolas', monospace;
          padding: 4px 6px; background: var(--bg-tertiary, #f5f5f5);
          border-radius: 3px; word-break: break-all;
          color: var(--text-primary, #333);
        }
        .psb-tags { display: flex; flex-wrap: wrap; gap: 4px; }
        .psb-tag {
          font-size: 10px; padding: 1px 6px; border-radius: 3px;
          background: var(--accent-color, #0078d4); color: #fff;
          font-family: 'Consolas', monospace;
        }
        .psb-suggestions {
          background: #fff8e1; border: 1px solid #ffe082;
          border-radius: 4px; padding: 8px;
        }
        .psb-suggestion-item {
          font-size: 11px; color: #795548; line-height: 1.5;
          padding-left: 4px;
        }
        .psb-input-row {
          display: flex; gap: 4px;
        }
        .psb-input {
          flex: 1; padding: 5px 8px; border: 1px solid var(--border-color, #ddd);
          border-radius: 3px; font-size: 12px;
          font-family: 'Consolas', monospace;
          background: var(--bg-primary, #fff);
          color: var(--text-primary, #333);
        }
        .psb-btn {
          padding: 4px 10px; border: 1px solid var(--border-color, #ddd);
          border-radius: 3px; cursor: pointer; font-size: 12px;
          background: var(--bg-primary, #fff);
          color: var(--text-primary, #333);
          white-space: nowrap;
        }
        .psb-btn:hover { background: var(--bg-hover, #e8e8e8); }
        .psb-btn-sm { padding: 2px 6px; font-size: 11px; }
        .psb-btn-cancel { color: #d32; }
        .psb-config-row {
          display: flex; align-items: center; gap: 6px;
        }
        .psb-default-path {
          font-size: 11px; font-family: 'Consolas', monospace;
          padding: 2px 6px; background: var(--bg-tertiary, #f5f5f5);
          border-radius: 3px; flex: 1; overflow: hidden;
          text-overflow: ellipsis; white-space: nowrap;
          color: var(--text-primary, #333);
        }
        .psb-muted { font-size: 11px; color: var(--text-muted, #999); font-style: italic; }
        .psb-history-list { display: flex; flex-direction: column; gap: 2px; }
        .psb-history-item {
          display: flex; align-items: center; gap: 6px;
          padding: 4px 6px; border-radius: 3px; cursor: pointer;
          font-size: 11px; transition: background .1s;
        }
        .psb-history-item:hover { background: var(--bg-hover, #e8e8e8); }
        .psb-history-item.active {
          background: color-mix(in srgb, var(--accent-color, #0078d4) 10%, transparent);
          font-weight: 600;
        }
        .psb-history-icon { font-size: 13px; }
        .psb-history-path {
          flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
          font-family: 'Consolas', monospace; font-size: 11px;
          color: var(--text-secondary, #666);
        }
      `}</style>
    </>
  );
};

export default ProjectStatusBar;
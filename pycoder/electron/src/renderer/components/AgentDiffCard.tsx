import React from 'react';

interface DiffLine {
  type: 'add' | 'del' | 'ctx';
  text: string;
}

interface TestResult {
  passed: number;
  total: number;
  coverage: string;
  duration: string;
}

interface Props {
  title?: string;
  filename?: string;
  stats?: string;
  lines: DiffLine[];
  testResult?: TestResult;
  onApply?: () => void;
  onRevert?: () => void;
}

/**
 * AI Agent Diff 预览卡片
 * 含代码差异 + 测试结果 + 操作按钮
 */
export const AgentDiffCard: React.FC<Props> = ({
  title = '重构完成！已执行以下变更：',
  filename,
  stats,
  lines,
  testResult,
  onApply,
  onRevert,
}) => (
  <div className="agent-diff-card">
    <div className="agent-thinking-avatar" />
    <div className="agent-diff-content">
      {/* 标题 */}
      {title && <div className="diff-card-title">✅ {title}</div>}

      {/* Diff 代码块 */}
      <div className="diff-code-block">
        {filename && (
          <div className="diff-code-header">
            <span className="diff-filename">{filename}</span>
            {stats && <span className="diff-stats">{stats}</span>}
          </div>
        )}
        <div className="diff-code-lines">
          {lines.map((line, i) => (
            <div key={i} className={`diff-line diff-${line.type}`}>
              <span className="diff-prefix">{line.type === 'add' ? '+' : line.type === 'del' ? '-' : ' '}</span>
              <span className="diff-text">{line.text}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 测试结果 */}
      {testResult && (
        <div className="diff-test-result">
          <span className="test-icon">🧪</span>
          <div className="test-info">
            <span className="test-title">测试通过 · {testResult.passed}/{testResult.total}</span>
            <span className="test-detail">覆盖率 {testResult.coverage} · 耗时 {testResult.duration}</span>
          </div>
        </div>
      )}

      {/* 操作按钮 */}
      <div className="diff-actions">
        {onApply && (
          <button className="diff-btn diff-btn-apply" onClick={onApply}>
            ✓ 全部应用
          </button>
        )}
        {onRevert && (
          <button className="diff-btn diff-btn-revert" onClick={onRevert}>
            ✗ 撤销
          </button>
        )}
      </div>
    </div>
  </div>
);

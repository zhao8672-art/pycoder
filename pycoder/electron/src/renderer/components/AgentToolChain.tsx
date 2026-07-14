import React from 'react';

interface ToolCall {
  tool: string;
  args: string;
  duration: string;
  status?: 'running' | 'done' | 'error';
}

interface Props {
  calls: ToolCall[];
}

/**
 * AI Agent 多工具调用链
 * 展示 edit_file → search_code → run_test 等工具的顺序执行
 */
export const AgentToolChain: React.FC<Props> = ({ calls }) => (
  <div className="agent-tool-chain">
    <div className="agent-thinking-avatar" />
    <div className="agent-tool-list">
      {calls.map((call, i) => (
        <div key={i} className={`agent-tool-call status-${call.status || 'done'}`}>
          <span className="tool-call-icon">{getToolIcon(call.tool)}</span>
          <span className="tool-call-name">{call.tool}</span>
          <span className="tool-call-args">{call.args}</span>
          <span className="tool-call-time">{call.duration}</span>
        </div>
      ))}
    </div>
  </div>
);

function getToolIcon(tool: string): string {
  if (tool.includes('read') || tool.includes('file')) return '📄';
  if (tool.includes('search') || tool.includes('find')) return '🔍';
  if (tool.includes('test') || tool.includes('run')) return '▶';
  if (tool.includes('edit') || tool.includes('write')) return '✏️';
  if (tool.includes('lint') || tool.includes('check')) return '✓';
  return '🔧';
}

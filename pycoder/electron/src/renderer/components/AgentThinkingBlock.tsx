import React from 'react';

interface ThinkingStep {
  text: string;
  status: 'done' | 'active' | 'pending';
}

interface Props {
  steps: ThinkingStep[];
  isThinking?: boolean;
}

/**
 * AI Agent 思考过程可视化
 * 展示 Chain-of-Thought 推理步骤，带脉冲动画指示器
 */
export const AgentThinkingBlock: React.FC<Props> = ({ steps, isThinking = false }) => (
  <div className="agent-thinking-block">
    <div className="agent-thinking-avatar" />
    <div className="agent-thinking-content">
      <div className="agent-thinking-header">
        <span className={`agent-thinking-dot ${isThinking ? 'pulsing' : ''}`} />
        <span className="agent-thinking-label">
          {isThinking ? 'AI 正在思考...' : '思考过程'}
        </span>
      </div>
      {steps.map((step, i) => (
        <div key={i} className={`agent-thinking-step step-${step.status}`}>
          {i + 1}. {step.text}
          {step.status === 'active' && <span className="step-dots">···</span>}
        </div>
      ))}
    </div>
  </div>
);

/**
 * AgentProgressBar — AI 执行进度展示组件
 *
 * 独立于主对话消息列表的进度报告区域，展示:
 * - 当前执行阶段描述
 * - 已完成/总步骤数 + 百分比进度条
 * - 预计剩余时间
 * - 关键里程碑完成状态
 *
 * 设计原则:
 * - 仅在 isStreaming 或 hasProgress 时渲染
 * - 不插入 chatMessages，保持消息列表纯净
 * - 后台插件事件以轻量标签形式展示在进度条下方
 * - 可折叠以节省空间
 */

import React, { useState } from 'react';
import type { AgentProgress, PluginEvent } from '../stores/chatStore';

interface Props {
    progress: AgentProgress | null;
    pluginEvents: PluginEvent[];
    isStreaming: boolean;
    onClear?: () => void;
}

/** 阶段图标映射 */
const PHASE_ICONS: Record<string, string> = {
    intent: '🔍',
    route: '🔄',
    llm: '🧠',
    plugin: '🔧',
    merge: '📋',
    done: '✅',
};

/** 里程碑状态映射 */
const MILESTONE_STATUS: Record<string, { icon: string; className: string }> = {
    done: { icon: '✅', className: 'ms-done' },
    active: { icon: '⏳', className: 'ms-active' },
    pending: { icon: '○', className: 'ms-pending' },
    error: { icon: '❌', className: 'ms-error' },
};

/** 格式化秒数为可读字符串 */
function formatDuration(seconds: number): string {
    if (seconds < 60) return `${seconds}s`;
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}m${s}s`;
}

export const AgentProgressBar: React.FC<Props> = ({
    progress,
    pluginEvents,
    isStreaming,
    onClear,
}) => {
    const [collapsed, setCollapsed] = useState(false);

    // 没有进度且没有流式时不渲染
    if (!progress && !isStreaming && pluginEvents.length === 0) {
        return null;
    }

    const pct = progress?.percent ?? 0;
    const phaseIcon = PHASE_ICONS[progress?.phase ?? ''] ?? '⚙️';
    const stageText = progress?.stage ?? '准备中...';
    const currentStep = progress?.current_step ?? 0;
    const totalSteps = progress?.total_steps ?? 0;
    const milestones = progress?.milestones ?? [];

    // 最近的插件事件（显示最新的2条）
    const recentPlugins = pluginEvents.slice(-2);

    const pluginActionLabel: Record<string, string> = {
        start: '进行中',
        done: '完成',
        error: '失败',
        skip: '跳过',
    };

    return (
        <div className={`agent-progress-bar ${collapsed ? 'collapsed' : ''}`}>
            {/* ── 头部: 进度概览 + 折叠按钮 ── */}
            <div className="apb-header" onClick={() => setCollapsed(!collapsed)}>
                <div className="apb-header-left">
                    <span className="apb-phase-icon">{phaseIcon}</span>
                    <span className="apb-stage-text">{stageText}</span>
                    <span className="apb-step-count">
                        {currentStep}/{totalSteps}
                    </span>
                </div>
                <div className="apb-header-right">
                    <span className="apb-percent">{pct}%</span>
                    {progress && progress.eta_seconds > 0 && (
                        <span className="apb-eta">剩余 {formatDuration(progress.eta_seconds)}</span>
                    )}
                    <span className="apb-collapse-icon">{collapsed ? '▶' : '▼'}</span>
                    {onClear && !isStreaming && (
                        <button
                            className="apb-clear-btn"
                            onClick={(e) => { e.stopPropagation(); onClear(); }}
                            title="清除进度"
                        >
                            ✕
                        </button>
                    )}
                </div>
            </div>

            {!collapsed && (
                <>
                    {/* ── 进度条 ── */}
                    <div className="apb-bar-track">
                        <div
                            className={`apb-bar-fill ${pct >= 100 ? 'apb-done' : ''}`}
                            style={{ width: `${pct}%` }}
                        />
                    </div>

                    {/* ── 时间信息 ── */}
                    {progress && (
                        <div className="apb-time-info">
                            <span>已用: {formatDuration(progress.elapsed_seconds)}</span>
                            {progress.eta_seconds > 0 && (
                                <span>预计剩余: {formatDuration(progress.eta_seconds)}</span>
                            )}
                        </div>
                    )}

                    {/* ── 里程碑列表 ── */}
                    {milestones.length > 0 && (
                        <div className="apb-milestones">
                            {milestones.map((ms, i) => {
                                const st = MILESTONE_STATUS[ms.status] ?? MILESTONE_STATUS.pending;
                                return (
                                    <div key={i} className={`apb-milestone ${st.className}`}>
                                        <span className="apb-ms-icon">{st.icon}</span>
                                        <span className="apb-ms-text">{ms.step}</span>
                                    </div>
                                );
                            })}
                        </div>
                    )}

                    {/* ── 后台插件事件（轻量标签，不在消息主列表显示） ── */}
                    {recentPlugins.length > 0 && (
                        <div className="apb-plugins">
                            {recentPlugins.map((pe, i) => {
                                const label = pluginActionLabel[pe.action] ?? pe.action;
                                const isErr = pe.action === 'error';
                                const icon = pe.action === 'done' ? '✅'
                                    : pe.action === 'start' ? '⚙️'
                                        : pe.action === 'error' ? '❌' : '⏭️';
                                return (
                                    <div key={i} className={`apb-plugin-item ${isErr ? 'apb-plugin-error' : ''}`}>
                                        <span className="apb-plugin-icon">{icon}</span>
                                        <span className="apb-plugin-name">{pe.plugin_name}</span>
                                        <span className="apb-plugin-action">{label}</span>
                                        {pe.duration_ms > 0 && (
                                            <span className="apb-plugin-time">
                                                {pe.duration_ms >= 1000
                                                    ? `${(pe.duration_ms / 1000).toFixed(1)}s`
                                                    : `${pe.duration_ms}ms`}
                                            </span>
                                        )}
                                    </div>
                                );
                            })}
                            {pluginEvents.length > 2 && (
                                <div className="apb-plugin-more">
                                    +{pluginEvents.length - 2} 个事件
                                </div>
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
    );
};

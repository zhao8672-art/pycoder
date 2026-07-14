/**
 * StatusBar 组件测试
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';

// Mock stores
vi.mock('../stores/appStore', () => ({
    useAppStore: (selector?: any) => {
        const state = {
            backendStatus: 'running',
            currentModel: 'deepseek-chat',
            gitStatus: { branch: 'master', changes: [], ahead: 0, behind: 0 },
        };
        return selector ? selector(state) : state;
    },
    useUIStore: (selector?: any) => {
        const state = {
            bottomPanel: 'terminal',
            layout: { bottomPanelOpen: false },
            theme: 'dark',
            setBottomPanel: vi.fn(),
            toggleBottomPanel: vi.fn(),
            toggleTheme: vi.fn(),
        };
        return selector ? selector(state) : state;
    },
}));

// Mock locales
vi.mock('../../locales', () => ({
    t: (key: string, fallback?: string) => fallback || key,
}));

describe('StatusBar', () => {
    it('renders backend status', async () => {
        const { StatusBar } = await import('./StatusBar');
        render(React.createElement(StatusBar));

        expect(screen.getByText('已连接')).toBeInTheDocument();
    });

    it('renders model name', async () => {
        const { StatusBar } = await import('./StatusBar');
        render(React.createElement(StatusBar));

        expect(screen.getByText(/deepseek-chat/)).toBeInTheDocument();
    });
});

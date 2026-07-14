/**
 * WelcomeScreen 组件测试
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';

vi.mock('../stores/appStore', () => ({
    useAppStore: (selector?: any) => {
        const state = {
            setCommandPaletteOpen: vi.fn(),
            toggleSidebar: vi.fn(),
            setActiveSidebar: vi.fn(),
            setLayout: vi.fn(),
            toggleAIPanel: vi.fn(),
        };
        return selector ? selector(state) : state;
    },
}));

describe('WelcomeScreen', () => {
    it('renders title', async () => {
        const WelcomeScreen = (await import('./WelcomeScreen')).default;
        render(React.createElement(WelcomeScreen));

        expect(screen.getByText('PyCoder IDE')).toBeInTheDocument();
    });

    it('renders quick actions', async () => {
        const WelcomeScreen = (await import('./WelcomeScreen')).default;
        render(React.createElement(WelcomeScreen));

        expect(screen.getByText('打开项目')).toBeInTheDocument();
        expect(screen.getByText('AI 对话')).toBeInTheDocument();
    });

    it('renders keyboard shortcuts', async () => {
        const WelcomeScreen = (await import('./WelcomeScreen')).default;
        render(React.createElement(WelcomeScreen));

        expect(screen.getByText('Ctrl+K')).toBeInTheDocument();
        expect(screen.getByText('Ctrl+B')).toBeInTheDocument();
    });
});

/**
 * EditorTabs 组件测试 — 标签页渲染、关闭、恢复
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';

// Mock zustand stores
vi.mock('../stores/appStore', () => ({
    useAppStore: (selector?: any) => {
        const state = {
            openTabs: [
                { id: '1', fileName: 'test.py', filePath: '/test.py', content: '', isDirty: false, language: 'python' },
                { id: '2', fileName: 'main.ts', filePath: '/main.ts', content: '', isDirty: true, language: 'typescript' },
            ],
            activeTabId: '1',
            closedTabs: [],
        };
        return selector ? selector(state) : state;
    },
    useEditorStore: (selector?: any) => {
        const state = {
            openTabs: [
                { id: '1', fileName: 'test.py', filePath: '/test.py', content: '', isDirty: false, language: 'python' },
                { id: '2', fileName: 'main.ts', filePath: '/main.ts', content: '', isDirty: true, language: 'typescript' },
            ],
            activeTabId: '1',
            closedTabs: [],
            setActiveTab: vi.fn(),
            closeTab: vi.fn(),
            restoreClosedTab: vi.fn(),
        };
        return selector ? selector(state) : state;
    },
}));

describe('EditorTabs', () => {
    it('renders all tabs', async () => {
        const { EditorTabs } = await import('./EditorTabs');
        render(React.createElement(EditorTabs));

        expect(screen.getByText('test.py')).toBeInTheDocument();
        expect(screen.getByText('main.ts')).toBeInTheDocument();
    });

    it('shows dirty indicator for modified files', async () => {
        const { EditorTabs } = await import('./EditorTabs');
        render(React.createElement(EditorTabs));

        // main.ts has isDirty=true
        const mainTab = screen.getByText('main.ts');
        expect(mainTab.closest('.editor-tab')).toHaveClass('dirty');
    });
});

/**
 * UI Store — 布局、主题、面板状态
 */
import { create } from 'zustand';

interface LayoutState {
    sidebarWidth: number;
    aiPanelWidth: number;
    bottomPanelHeight: number;
    sidebarOpen: boolean;
    aiPanelOpen: boolean;
    bottomPanelOpen: boolean;
}

interface UIState {
    // 主题
    theme: 'dark' | 'light';

    // 布局
    layout: LayoutState;

    // 侧边栏
    activeSidebar: string | null;
    bottomPanel: string;

    // 命令面板
    commandPaletteOpen: boolean;

    // 进化面板
    evoPanelOpen: boolean;
    browserPanelOpen: boolean;

    // 活动组
    activeGroup: string;

    // Actions
    setTheme: (theme: 'dark' | 'light') => void;
    toggleTheme: () => void;
    setLayout: (layout: Partial<LayoutState>) => void;
    setActiveSidebar: (view: string | null) => void;
    setBottomPanel: (panel: string) => void;
    toggleSidebar: () => void;
    toggleAIPanel: () => void;
    toggleBottomPanel: () => void;
    setCommandPaletteOpen: (open: boolean) => void;
    toggleEvoPanel: () => void;
    toggleBrowserPanel: () => void;
    setActiveGroup: (group: string) => void;
}

const DEFAULT_LAYOUT: LayoutState = {
    sidebarWidth: 240,
    aiPanelWidth: 360,
    bottomPanelHeight: 200,
    sidebarOpen: true,
    aiPanelOpen: false,
    bottomPanelOpen: false,
};

const loadLayout = (): LayoutState => {
    try {
        const saved = localStorage.getItem('pycoder-layout');
        if (saved) return { ...DEFAULT_LAYOUT, ...JSON.parse(saved) };
    } catch { /* ignore */ }
    return DEFAULT_LAYOUT;
};

const saveLayout = (layout: LayoutState) => {
    try { localStorage.setItem('pycoder-layout', JSON.stringify(layout)); } catch { /* ignore */ }
};

export const useUIStore = create<UIState>((set) => ({
    theme: typeof localStorage !== 'undefined' && localStorage.getItem('pycoder-theme') === 'light' ? 'light' : 'dark',
    layout: loadLayout(),
    activeSidebar: 'files',
    bottomPanel: 'terminal',
    commandPaletteOpen: false,
    evoPanelOpen: false,
    browserPanelOpen: false,
    activeGroup: 'code',

    setTheme: (theme) => {
        try { localStorage.setItem('pycoder-theme', theme); } catch { /* ignore */ }
        set({ theme });
    },
    toggleTheme: () => set((s) => {
        const newTheme = s.theme === 'dark' ? 'light' : 'dark';
        try { localStorage.setItem('pycoder-theme', newTheme); } catch { /* ignore */ }
        return { theme: newTheme };
    }),
    setLayout: (partial) => set((s) => {
        const newLayout = { ...s.layout, ...partial };
        saveLayout(newLayout);
        return { layout: newLayout };
    }),
    setActiveSidebar: (view) => set({ activeSidebar: view }),
    setBottomPanel: (panel) => set({ bottomPanel: panel }),
    toggleSidebar: () => set((s) => {
        const newLayout = { ...s.layout, sidebarOpen: !s.layout.sidebarOpen };
        saveLayout(newLayout);
        return { layout: newLayout };
    }),
    toggleAIPanel: () => set((s) => {
        const newLayout = { ...s.layout, aiPanelOpen: !s.layout.aiPanelOpen };
        saveLayout(newLayout);
        return { layout: newLayout };
    }),
    toggleBottomPanel: () => set((s) => {
        const newLayout = { ...s.layout, bottomPanelOpen: !s.layout.bottomPanelOpen };
        saveLayout(newLayout);
        return { layout: newLayout };
    }),
    setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
    toggleEvoPanel: () => set((s) => ({ evoPanelOpen: !s.evoPanelOpen })),
    toggleBrowserPanel: () => set((s) => ({ browserPanelOpen: !s.browserPanelOpen })),
    setActiveGroup: (group) => set({ activeGroup: group }),
}));

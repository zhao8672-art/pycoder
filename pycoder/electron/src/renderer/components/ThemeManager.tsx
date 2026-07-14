/** Theme + Monaco Settings Manager — dark/light toggle + Vim/Emacs modes */
import React, { useState, useEffect } from 'react';

export const ThemeManager: React.FC = () => {
    const [theme, setThemeState] = useState<'dark' | 'light'>(
        (localStorage.getItem('pycoder-theme') as any) || 'dark'
    );
    const [fontSize, setFontSize] = useState(
        parseInt(localStorage.getItem('pycoder-fontsize') || '13')
    );
    const [editorMode, setEditorMode] = useState(
        localStorage.getItem('pycoder-editor-mode') || 'default'
    );

    useEffect(() => {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('pycoder-theme', theme);
    }, [theme]);

    useEffect(() => {
        localStorage.setItem('pycoder-fontsize', String(fontSize));
        localStorage.setItem('pycoder-editor-mode', editorMode);
    }, [fontSize, editorMode]);

    const themes = [
        { id: 'dark' as const, icon: '🌙', label: '暗色' },
        { id: 'light' as const, icon: '☀️', label: '明亮' },
    ];
    const modes = [
        { id: 'default', label: 'VS Code', desc: '默认快捷键' },
        { id: 'vim', label: 'Vim', desc: 'hjkl 导航, ESC 切换模式' },
        { id: 'emacs', label: 'Emacs', desc: 'C-f/b/n/p 移动' },
    ];

    return (
        <div className="theme-manager">
            <div className="tm-section">
                <h4>🎨 主题</h4>
                <div className="tm-themes">
                    {themes.map(t => (
                        <button key={t.id} className={`tm-theme-btn ${theme === t.id ? 'active' : ''}`}
                            onClick={() => setThemeState(t.id)}>
                            {t.icon} {t.label}
                        </button>
                    ))}
                </div>
            </div>

            <div className="tm-section">
                <h4>🔤 字体大小</h4>
                <div className="tm-fontsize">
                    <button onClick={() => setFontSize(s => Math.max(s - 1, 10))}>A-</button>
                    <span>{fontSize}px</span>
                    <button onClick={() => setFontSize(s => Math.min(s + 1, 22))}>A+</button>
                </div>
            </div>

            <div className="tm-section">
                <h4>⌨️ 编辑器键位</h4>
                <div className="tm-modes">
                    {modes.map(m => (
                        <button key={m.id} className={`tm-mode-btn ${editorMode === m.id ? 'active' : ''}`}
                            onClick={() => setEditorMode(m.id)}
                            title={m.desc}>
                            {m.label}
                        </button>
                    ))}
                </div>
            </div>
        </div>
    );
};

export function getEditorModeConfig(mode: string): Record<string, any> {
    if (mode === 'vim') return { 'editor.defaultMode': 'vim' };
    if (mode === 'emacs') return { 'editor.defaultMode': 'emacs' };
    return {};
}

/**
 * useKeyboardShortcuts — 全局键盘快捷键注册 Hook
 *
 * 提供统一的快捷键注册、冲突检测和命令面板展示。
 */
import { useEffect, useCallback } from 'react';

export interface Shortcut {
  /** 快捷键组合，如 "Ctrl+K" */
  keys: string;
  /** 描述 */
  description: string;
  /** 分类 */
  category: string;
  /** 执行回调 */
  action: () => void;
  /** 作用域 */
  scope?: 'global' | 'editor' | 'terminal';
}

/** 解析快捷键字符串为修饰键和主键 */
function parseShortcut(keys: string): { ctrl: boolean; shift: boolean; alt: boolean; meta: boolean; key: string } {
  const parts = keys.toLowerCase().split('+');
  return {
    ctrl: parts.includes('ctrl'),
    shift: parts.includes('shift'),
    alt: parts.includes('alt'),
    meta: parts.includes('meta') || parts.includes('cmd'),
    key: parts.filter(p => !['ctrl', 'shift', 'alt', 'meta', 'cmd'].includes(p)).join('+'),
  };
}

export function useKeyboardShortcuts(shortcuts: Shortcut[]) {
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // 输入框内不触发快捷键
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

    for (const sc of shortcuts) {
      const parsed = parseShortcut(sc.keys);
      if (
        e.ctrlKey === parsed.ctrl &&
        e.shiftKey === parsed.shift &&
        e.altKey === parsed.alt &&
        e.metaKey === parsed.meta &&
        e.key.toLowerCase() === parsed.key
      ) {
        e.preventDefault();
        sc.action();
        return;
      }
    }
  }, [shortcuts]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);
}

/** 生成快捷键列表（供命令面板展示） */
export function getShortcutList(shortcuts: Shortcut[]): Shortcut[] {
  return [...shortcuts].sort((a, b) => a.category.localeCompare(b.category));
}
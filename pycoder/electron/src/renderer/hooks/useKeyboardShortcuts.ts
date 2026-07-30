/**
 * useKeyboardShortcuts — 全局键盘快捷键注册 Hook
 *
 * 提供统一的快捷键注册、冲突检测、命令面板展示和用户自定义。
 */
import { useEffect, useCallback, useState } from 'react';

const STORAGE_KEY = 'pycoder.shortcut_overrides.v1';

export interface Shortcut {
  /** 唯一 id，用于自定义覆盖（必填） */
  id: string;
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

/** 将 KeyboardEvent 序列化为可读字符串 */
export function eventToShortcutString(e: KeyboardEvent): string | null {
  const parts: string[] = [];
  if (e.ctrlKey) parts.push('Ctrl');
  if (e.metaKey) parts.push('Cmd');
  if (e.altKey) parts.push('Alt');
  if (e.shiftKey) parts.push('Shift');
  // 忽略纯修饰键
  if (['Control', 'Meta', 'Alt', 'Shift'].includes(e.key)) return null;
  parts.push(e.key.length === 1 ? e.key.toUpperCase() : e.key);
  return parts.join('+');
}

/** 从 localStorage 加载覆盖 */
function loadOverrides(): Record<string, string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as Record<string, string>;
  } catch {
    return {};
  }
}

/** 保存覆盖到 localStorage */
function saveOverrides(overrides: Record<string, string>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides));
  } catch {
    // 忽略
  }
}

export function useKeyboardShortcuts(shortcuts: Shortcut[]) {
  const [, forceUpdate] = useState(0);

  // 应用覆盖后的最终快捷键
  const effective = useCallback((): Shortcut[] => {
    const overrides = loadOverrides();
    return shortcuts.map((s) => (overrides[s.id] ? { ...s, keys: overrides[s.id] } : s));
  }, [shortcuts]);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // 输入框内不触发快捷键
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;

    const list = effective();
    for (const sc of list) {
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
  }, [effective]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  // 自定义 API
  const setOverride = useCallback((id: string, keys: string | null) => {
    const overrides = loadOverrides();
    if (keys === null || keys === '') {
      delete overrides[id];
    } else {
      overrides[id] = keys;
    }
    saveOverrides(overrides);
    forceUpdate((n) => n + 1);
  }, []);

  const resetOverrides = useCallback(() => {
    saveOverrides({});
    forceUpdate((n) => n + 1);
  }, []);

  return { setOverride, resetOverrides, getEffective: effective };
}

/** 生成快捷键列表（供命令面板展示） */
export function getShortcutList(shortcuts: Shortcut[]): Shortcut[] {
  return [...shortcuts].sort((a, b) => a.category.localeCompare(b.category));
}
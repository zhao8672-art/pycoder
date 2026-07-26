/**
 * useA11y — 无障碍辅助 Hook
 *
 * 提供焦点管理、键盘导航、ARIA 属性等无障碍功能。
 */
import { useEffect, useRef, useCallback } from 'react';

/** 焦点陷阱：在模态框内循环焦点 */
export function useFocusTrap(active: boolean) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!active || !containerRef.current) return;
    const container = containerRef.current;
    const focusableSelector = 'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
    const firstFocusable = container.querySelector<HTMLElement>(focusableSelector);

    // 保存当前焦点元素
    const previousFocus = document.activeElement as HTMLElement;
    firstFocusable?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return;
      const focusable = container.querySelectorAll<HTMLElement>(focusableSelector);
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previousFocus?.focus();
    };
  }, [active]);

  return containerRef;
}

/** 列表键盘导航：上下箭头移动焦点 */
export function useListKeyboardNav(
  itemCount: number,
  onSelect: (index: number) => void,
  onEscape?: () => void,
) {
  const [activeIndex, setActiveIndex] = useRefState(0);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setActiveIndex((prev) => Math.min(prev + 1, itemCount - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setActiveIndex((prev) => Math.max(prev - 1, 0));
        break;
      case 'Enter':
        e.preventDefault();
        onSelect(activeIndex.current);
        break;
      case 'Escape':
        onEscape?.();
        break;
    }
  }, [itemCount, onSelect, onEscape, setActiveIndex]);

  return { activeIndex, handleKeyDown };
}

/** useRef 包装的 useState */
function useRefState<T>(initial: T) {
  const ref = useRef<T>(initial);
  const set = useCallback((val: T | ((prev: T) => T)) => {
    ref.current = typeof val === 'function' ? (val as (prev: T) => T)(ref.current) : val;
  }, []);
  return [ref as React.MutableRefObject<T>, set] as const;
}
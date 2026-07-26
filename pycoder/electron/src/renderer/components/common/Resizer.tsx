/**
 * Resizer — 通用面板拖拽调整器
 *
 * 从 App.tsx 中提取，支持水平和垂直方向。
 * 拖拽期间禁用 body 的 pointer-events 和 user-select，防止编辑器干扰。
 */
import React, { useEffect, useState, useRef } from 'react';

interface ResizerProps {
  direction: 'horizontal' | 'vertical';
  onResize: (delta: number) => void;
}

export const Resizer: React.FC<ResizerProps> = ({ direction, onResize }) => {
  const [isDragging, setIsDragging] = useState(false);
  const startRef = useRef(0);

  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setIsDragging(true);
    startRef.current = direction === 'horizontal' ? e.clientX : e.clientY;
    document.body.style.cursor = direction === 'horizontal' ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
    document.body.style.pointerEvents = 'none';
  };

  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      e.preventDefault();
      const current = direction === 'horizontal' ? e.clientX : e.clientY;
      const delta = current - startRef.current;
      onResize(delta);
      startRef.current = current;
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.body.style.pointerEvents = '';
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.body.style.pointerEvents = '';
    };
  }, [isDragging, onResize, direction]);

  return (
    <div
      className={`resizer ${direction === 'vertical' ? 'resizer-vertical' : ''} ${isDragging ? 'dragging' : ''}`}
      onMouseDown={handleMouseDown}
    />
  );
};
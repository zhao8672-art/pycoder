/**
 * Toast 通知系统 — 轻量级全局通知
 *
 * 用法:
 *   import { toast } from '../services/toast';
 *   toast.success('操作成功');
 *   toast.error('保存失败');
 */
import React, { useState, useCallback, useEffect, useRef, createContext, useContext } from 'react';
import { createRoot } from 'react-dom/client';

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface ToastItem {
    id: number;
    type: ToastType;
    message: string;
    duration: number;
}

let toastId = 0;
let setToastsFn: React.Dispatch<React.SetStateAction<ToastItem[]>> | null = null;

// Toast 渲染器
const ToastContainer: React.FC = () => {
    const [toasts, setToasts] = useState<ToastItem[]>([]);
    setToastsFn = setToasts;

    return (
        <div className= "toast-container" >
        {
            toasts.map((t) => (
                <ToastItemComponent key= { t.id } item = { t } />
      ))
        }
        </div>
  );
};

const ToastItemComponent: React.FC<{ item: ToastItem }> = ({ item }) => {
    const [visible, setVisible] = useState(false);

    useEffect(() => {
        requestAnimationFrame(() => setVisible(true));
        const timer = setTimeout(() => {
            setVisible(false);
            setTimeout(() => {
                setToastsFn?.((prev) => prev.filter((x) => x.id !== item.id));
            }, 300);
        }, item.duration);
        return () => clearTimeout(timer);
    }, [item]);

    const icons: Record<ToastType, string> = {
        success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️',
    };

    return (
        <div
      className= {`toast-item toast-${item.type} ${visible ? 'toast-visible' : ''}`
}
role = "alert"
    >
    <span className="toast-icon" > { icons[item.type]} </span>
        < span className = "toast-message" > { item.message } </span>
            </div>
  );
};

// Toast API
export const toast = {
    success: (msg: string, duration = 3000) => addToast('success', msg, duration),
    error: (msg: string, duration = 4000) => addToast('error', msg, duration),
    warning: (msg: string, duration = 3500) => addToast('warning', msg, duration),
    info: (msg: string, duration = 3000) => addToast('info', msg, duration),
};

function addToast(type: ToastType, message: string, duration: number) {
    const id = ++toastId;
    setToastsFn?.((prev) => [...prev, { id, type, message, duration }]);
}

// 初始化 Toast 容器（在应用根节点注入）
let _init = false;
export function initToast() {
    if (_init) return;
    _init = true;
    const container = document.createElement('div');
    container.id = 'toast-root';
    document.body.appendChild(container);
    const root = createRoot(container);
    root.render(React.createElement(ToastContainer));
}

/**
 * 移动端检测 — F4 移动端支持
 *
 * 判定策略（双重）：
 *   1. 移动设备 UA（手机/平板浏览器）
 *   2. 窄屏 + 触摸环境（触屏设备拖窄窗口）
 *
 * 桌面端拖窄窗口由 layout.css 既有 @media 规则做局部适配，
 * 不整体切换到移动布局，避免桌面用户工作区被意外替换。
 */
import { useEffect, useState } from 'react';

/** 移动设备 UA 特征 */
const MOBILE_UA_RE =
    /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini|Mobile/i;

/** 触发移动布局的屏幕宽度阈值（px），与 layout.css 的 768px 断点一致 */
export const MOBILE_BREAKPOINT = 768;

/** 是否为移动设备 UA */
export function isMobileUA(): boolean {
    return MOBILE_UA_RE.test(navigator.userAgent);
}

/** 是否为窄屏触摸环境 */
export function isNarrowTouchScreen(): boolean {
    const hasTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;
    return window.innerWidth <= MOBILE_BREAKPOINT && hasTouch;
}

/** 是否应使用移动端布局（App.tsx 顶层据此切换 MobileLayout） */
export function isMobile(): boolean {
    return isMobileUA() || isNarrowTouchScreen();
}

/** 响应式 Hook：窗口尺寸变化时重新评估（旋转屏幕/拖窗口均可生效） */
export function useIsMobile(): boolean {
    const [mobile, setMobile] = useState<boolean>(isMobile);
    useEffect(() => {
        const onResize = () => setMobile(isMobile());
        window.addEventListener('resize', onResize);
        return () => window.removeEventListener('resize', onResize);
    }, []);
    return mobile;
}

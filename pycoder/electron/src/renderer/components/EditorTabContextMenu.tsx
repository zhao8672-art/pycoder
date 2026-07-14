/** EditorTab right-click context menu */
import React, { useEffect, useRef } from 'react';

interface Props {
    x: number; y: number;
    tabId: string; fileName: string;
    onClose: () => void;
    onCloseOthers: () => void;
    onCloseRight: () => void;
    onCloseAll: () => void;
    onClose: () => void;
}

export const EditorTabContextMenu: React.FC<Props> = ({
    x, y, tabId, fileName,
    onClose, onCloseOthers, onCloseRight, onCloseAll,
    ...props
}) => {
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const h = () => props.onClose();
        document.addEventListener('click', h);
        return () => document.removeEventListener('click', h);
    }, []);

    return (
        <div className="tab-context-menu" style={{ left: x, top: y }} ref={ref}>
            <div className="tcm-item" onClick={onClose}>关闭</div>
            <div className="tcm-item" onClick={onCloseOthers}>关闭其他</div>
            <div className="tcm-item" onClick={onCloseRight}>关闭右侧</div>
            <div className="tcm-sep" />
            <div className="tcm-item" onClick={onCloseAll}>关闭全部</div>
        </div>
    );
};

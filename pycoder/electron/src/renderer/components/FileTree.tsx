/**
 * FileTree — 文件资源管理器（虚拟化版本）
 *
 * 使用 @tanstack/react-virtual 优化大项目性能。
 * 将嵌套树展平为列表，仅渲染可见节点。
 */
import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useAppStore, useEditorStore } from '../stores/appStore';
import type { FileEntry } from '../types';
import { BackendAPI } from '../services/backend';
import { getLanguageFromPath } from '../utils/language';

const FILE_ICONS: Record<string, string> = {
  '.py': '🐍', '.js': '🟨', '.ts': '🔷', '.tsx': '⚛️',
  '.jsx': '⚛️', '.json': '📋', '.md': '📝', '.html': '🌐',
  '.css': '🎨', '.yaml': '📄', '.yml': '📄', '.toml': '⚙️',
  '.txt': '📃', '.gitignore': '🙈',
};

function getFileIcon(name: string): string {
  const ext = name.substring(name.lastIndexOf('.'));
  return FILE_ICONS[ext] || '📄';
}

interface FlatNode {
  id: string;
  name: string;
  depth: number;
  isDir: boolean;
  expanded: boolean;
  entry: FileEntry;
}

/** 将树展平为列表，仅包含展开的节点 */
function flattenTree(
  children: FileEntry[] | undefined,
  expandedDirs: Set<string>,
  depth: number,
): FlatNode[] {
  if (!children) return [];
  const result: FlatNode[] = [];
  for (const child of children) {
    const nodeId = child.path || child.name;
    const isDir = child.type === 'dir';
    result.push({
      id: nodeId, name: child.name, depth,
      isDir, expanded: expandedDirs.has(nodeId), entry: child,
    });
    if (isDir && expandedDirs.has(nodeId)) {
      result.push(...flattenTree(child.children, expandedDirs, depth + 1));
    }
  }
  return result;
}

export const FileTree: React.FC = () => {
  const { projectRoot, setProjectRoot } = useAppStore();
  const { openFile, fileTree, setFileTree } = useEditorStore();
  const [tree, setTree] = useState<FileEntry | null>(fileTree);
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const parentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (window.electronAPI) {
      const root = projectRoot || undefined;
      window.electronAPI.getFileTree(root, 4).then((t: FileEntry) => {
        setTree(t);
        setFileTree(t);
        if (t?.children) {
          const initial = new Set<string>();
          for (const c of t.children) {
            if (c.type === 'dir') initial.add(c.path || c.name);
          }
          setExpandedDirs(initial);
        }
      });
    }
  }, [projectRoot, setFileTree]);

  const flatNodes = useMemo(
    () => flattenTree(tree?.children, expandedDirs, 0),
    [tree, expandedDirs],
  );

  const virtualizer = useVirtualizer({
    count: flatNodes.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 26,
    overscan: 20,
  });

  const handleOpenFolder = async () => {
    const folder = await window.electronAPI?.openFolderDialog();
    if (folder) {
      await BackendAPI.workspace.switch(folder);
      setProjectRoot(folder);
      const treeData = await window.electronAPI?.getFileTree(folder, 4);
      if (treeData) {
        setTree(treeData);
        setFileTree(treeData);
      }
    }
  };

  const handleFileClick = useCallback(async (entry: FileEntry) => {
    if (entry.type === 'file') {
      const res = await BackendAPI.files.read(entry.path || entry.name);
      if (res?.content !== undefined) {
        openFile({
          id: entry.path || entry.name,
          filePath: entry.path || entry.name,
          fileName: entry.name,
          content: res.content,
          isDirty: false,
          language: getLanguageFromPath(entry.name),
        });
      }
    }
  }, [openFile]);

  const toggleDir = (nodeId: string) => {
    setExpandedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  };

  if (!tree) {
    return <div className="sidebar-placeholder">加载文件树中...</div>;
  }

  return (
    <div className="file-tree">
      <div className="filetree-toolbar">
        <span className="filetree-workspace" title={projectRoot}>
          {projectRoot?.split('\\').pop()?.split('/').pop()}
        </span>
        <button className="filetree-open-btn" onClick={handleOpenFolder} title="打开文件夹">📂</button>
      </div>
      <div ref={parentRef} style={{ flex: 1, overflow: 'auto' }}>
        <div style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }}>
          {virtualizer.getVirtualItems().map((virtualItem) => {
            const node = flatNodes[virtualItem.index];
            if (!node) return null;
            return (
              <div
                key={node.id}
                className={`tree-node ${node.isDir ? 'tree-dir' : 'tree-file'}`}
                style={{
                  position: 'absolute', top: 0, left: 0, width: '100%',
                  height: `${virtualItem.size}px`,
                  transform: `translateY(${virtualItem.start}px)`,
                  paddingLeft: `${node.depth * 16 + 8}px`,
                  cursor: 'pointer', display: 'flex', alignItems: 'center',
                  gap: 4, fontSize: 13,
                }}
                onClick={() => {
                  if (node.isDir) toggleDir(node.id);
                  else handleFileClick(node.entry);
                }}
              >
                <span className="tree-icon">
                  {node.isDir ? (node.expanded ? '📂' : '📁') : getFileIcon(node.name)}
                </span>
                <span className="tree-name" style={{
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                }}>
                  {node.name}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

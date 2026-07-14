/**
 * 文件扩展名 → 编程语言/编辑器模式 映射
 * App.tsx 和 FileTree.tsx 共享使用
 */

const LANGUAGE_MAP: Record<string, string> = {
    '.py': 'python',
    '.js': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    '.jsx': 'javascript',
    '.json': 'json',
    '.html': 'html',
    '.css': 'css',
    '.md': 'markdown',
    '.yaml': 'yaml',
    '.yml': 'yaml',
    '.toml': 'toml',
    '.xml': 'xml',
    '.sql': 'sql',
    '.sh': 'shell',
    '.bash': 'shell',
    '.rb': 'ruby',
    '.go': 'go',
    '.rs': 'rust',
    '.java': 'java',
};

/**
 * 根据文件路径获取对应的 Monaco 语言标识
 */
export function getLanguageFromPath(filePath: string): string {
    const ext = filePath.substring(filePath.lastIndexOf('.'));
    return LANGUAGE_MAP[ext] || 'plaintext';
}

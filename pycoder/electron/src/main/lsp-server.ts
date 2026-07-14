/**
 * Pyright LSP Server 管理器
 *
 * 在 Electron 主进程中管理 Pyright 子进程，通过 stdio 双向通信。
 * 渲染进程通过 IPC 间接使用 LSP，无需直接访问子进程。
 */

import { ChildProcess, spawn } from 'child_process';
import { EventEmitter } from 'events';
import path from 'path';

export interface LSPDiagnostic {
    uri: string;
    line: number;
    column: number;
    endLine: number;
    endColumn: number;
    message: string;
    severity: 'error' | 'warning' | 'info';
}

export interface LSPCompletionItem {
    label: string;
    kind: string;
    detail: string;
    insertText: string;
}

interface PendingRequest {
    resolve: (value: any) => void;
    reject: (err: Error) => void;
    timer: NodeJS.Timeout;
}

const LSP_TIMEOUT_MS = 10000;

/**
 * 管理 Pyright LSP Server 子进程的生命周期和 JSON-RPC 通信
 */
export class LSPProcessManager extends EventEmitter {
    private process: ChildProcess | null = null;
    private requestId = 1;
    private pending = new Map<number, PendingRequest>();
    private buffer = '';
    private ready = false;
    private rootUri = '';
    private serverInitialized = false;

    get isReady(): boolean {
        return this.serverInitialized;
    }

    get isRunning(): boolean {
        return this.process !== null && !this.process.killed;
    }

    /**
     * 启动 Pyright LSP Server
     */
    async start(rootUri: string): Promise<boolean> {
        this.rootUri = rootUri;
        this.buffer = '';

        try {
            this.process = spawn('pyright-langserver', ['--stdio'], {
                stdio: ['pipe', 'pipe', 'pipe'],
                windowsHide: true,
            });

            this.process.stdout?.on('data', (data: Buffer) => {
                this.buffer += data.toString('utf-8');
                this.processBuffer();
            });

            this.process.stderr?.on('data', (data: Buffer) => {
                // Pyright 的日志输出到 stderr，不影响功能
                const text = data.toString('utf-8').trim();
                if (text) console.log(`[LSP stderr] ${text}`);
            });

            this.process.on('error', (err) => {
                console.error('[LSP] Process error:', err.message);
                this.emit('error', err);
            });

            this.process.on('exit', (code) => {
                console.log(`[LSP] Process exited with code ${code}`);
                this.process = null;
                this.serverInitialized = false;
                this.emit('exit', code);
            });

            // 发送 initialize 请求
            const initResult = await this.sendRequest('initialize', {
                processId: process.pid,
                rootUri: rootUri,
                capabilities: {
                    textDocument: {
                        completion: { completionItem: { snippetSupport: true } },
                        hover: { contentFormat: ['markdown', 'plaintext'] },
                        definition: true,
                        references: true,
                        documentSymbol: true,
                        formatting: { dynamicRegistration: true },
                        codeAction: { dynamicRegistration: true },
                        publishDiagnostics: { relatedInformation: true },
                    },
                    workspace: {
                        workspaceFolders: true,
                    },
                },
            });

            if (!initResult) return false;

            // 发送 initialized 通知
            this.sendNotification('initialized', {});

            this.serverInitialized = true;
            this.emit('ready');
            console.log('[LSP] Pyright server initialized');
            return true;
        } catch (err) {
            console.error('[LSP] Failed to start:', err);
            return false;
        }
    }

    /**
     * 打开文档（textDocument/didOpen）
     */
    async openDocument(uri: string, text: string): Promise<void> {
        if (!this.isRunning) return;
        this.sendNotification('textDocument/didOpen', {
            textDocument: { uri, languageId: 'python', version: 1, text },
        });
    }

    /**
     * 变更文档（textDocument/didChange）
     */
    async changeDocument(uri: string, text: string, version: number): Promise<void> {
        if (!this.isRunning) return;
        this.sendNotification('textDocument/didChange', {
            textDocument: { uri, version },
            contentChanges: [{ text }],
        });
    }

    /**
     * 关闭文档（textDocument/didClose）
     */
    async closeDocument(uri: string): Promise<void> {
        if (!this.isRunning) return;
        this.sendNotification('textDocument/didClose', {
            textDocument: { uri },
        });
    }

    /**
     * 获取代码补全
     */
    async getCompletions(uri: string, line: number, column: number): Promise<LSPCompletionItem[]> {
        if (!this.isRunning) return [];
        const result = await this.sendRequest('textDocument/completion', {
            textDocument: { uri },
            position: { line, character: column },
            context: { triggerKind: 1 },
        });
        if (!result) return [];
        const items = result.items || [];
        return items.map((item: any) => ({
            label: item.label,
            kind: this.completionKindToString(item.kind || 0),
            detail: item.detail || '',
            insertText: item.textEdit?.newText || item.insertText || item.label,
        }));
    }

    /**
     * 获取悬停信息
     */
    async getHover(uri: string, line: number, column: number): Promise<string | null> {
        if (!this.isRunning) return null;
        const result = await this.sendRequest('textDocument/hover', {
            textDocument: { uri },
            position: { line, character: column },
        });
        if (!result) return null;
        if (typeof result.contents === 'string') return result.contents;
        if (Array.isArray(result.contents)) return result.contents.join('\n');
        if (result.contents?.value) return result.contents.value;
        return null;
    }

    /**
     * 跳转到定义
     */
    async goToDefinition(uri: string, line: number, column: number) {
        if (!this.isRunning) return null;
        const result = await this.sendRequest('textDocument/definition', {
            textDocument: { uri },
            position: { line, character: column },
        });
        if (!result) return null;
        const loc = Array.isArray(result) ? result[0] : result;
        return loc ? { uri: loc.uri, line: loc.range.start.line, column: loc.range.start.character } : null;
    }

    /**
     * 列出文档符号
     */
    async getDocumentSymbols(uri: string): Promise<any[]> {
        if (!this.isRunning) return [];
        const result = await this.sendRequest('textDocument/documentSymbol', {
            textDocument: { uri },
        });
        return Array.isArray(result) ? result : [];
    }

    /**
     * 关闭 LSP 连接
     */
    async shutdown(): Promise<void> {
        await this.sendRequest('shutdown', {}).catch(() => { });
        this.sendNotification('exit', {});
        this.serverInitialized = false;
        if (this.process) {
            this.process.kill();
            this.process = null;
        }
    }

    // ── JSON-RPC 通信 ──

    private sendRequest(method: string, params: any): Promise<any> {
        return new Promise((resolve, reject) => {
            const id = this.requestId++;
            const msg = JSON.stringify({ jsonrpc: '2.0', id, method, params });

            const timer = setTimeout(() => {
                this.pending.delete(id);
                reject(new Error(`LSP request "${method}" timed out after ${LSP_TIMEOUT_MS}ms`));
            }, LSP_TIMEOUT_MS);

            this.pending.set(id, { resolve, reject, timer });
            this.process?.stdin?.write(`Content-Length: ${Buffer.byteLength(msg, 'utf-8')}\r\n\r\n${msg}`);
        });
    }

    private sendNotification(method: string, params: any): void {
        const msg = JSON.stringify({ jsonrpc: '2.0', method, params });
        this.process?.stdin?.write(`Content-Length: ${Buffer.byteLength(msg, 'utf-8')}\r\n\r\n${msg}`);
    }

    private processBuffer(): void {
        const lines = this.buffer.split('\n');
        this.buffer = lines.pop() || '';

        const messages: string[] = [];
        let contentLength = -1;
        let collecting = false;
        let currentMsg = '';

        for (const line of lines) {
            const trimmed = line.trim();

            if (collecting) {
                currentMsg += (currentMsg ? '\n' : '') + trimmed;
                if (Buffer.byteLength(currentMsg, 'utf-8') >= contentLength) {
                    messages.push(currentMsg);
                    collecting = false;
                    contentLength = -1;
                    currentMsg = '';
                }
                continue;
            }

            const headerMatch = trimmed.match(/^content-length:\s*(\d+)$/i);
            if (headerMatch) {
                contentLength = parseInt(headerMatch[1], 10);
                collecting = true;
                currentMsg = '';
            }
        }

        for (const msg of messages) {
            try {
                const data = JSON.parse(msg);
                this.handleMessage(data);
            } catch {
                // ignore parse errors
            }
        }
    }

    private handleMessage(data: any): void {
        // 响应
        if (data.id != null && this.pending.has(data.id)) {
            const pending = this.pending.get(data.id)!;
            clearTimeout(pending.timer);
            this.pending.delete(data.id);
            if (data.error) {
                pending.reject(new Error(data.error.message || 'LSP error'));
            } else {
                pending.resolve(data.result);
            }
            return;
        }

        // 通知（如诊断结果）
        if (data.method === 'textDocument/publishDiagnostics') {
            const diagnostics: LSPDiagnostic[] = (data.params.diagnostics || []).map((d: any) => ({
                uri: data.params.uri,
                line: d.range.start.line,
                column: d.range.start.character,
                endLine: d.range.end.line,
                endColumn: d.range.end.character,
                message: d.message,
                severity: d.severity === 1 ? 'error' : d.severity === 2 ? 'warning' : 'info',
            }));
            this.emit('diagnostics', data.params.uri, diagnostics);
        }
    }

    private completionKindToString(kind: number): string {
        const map: Record<number, string> = {
            1: 'Text', 2: 'Method', 3: 'Function', 4: 'Constructor',
            5: 'Field', 6: 'Variable', 7: 'Class', 8: 'Interface',
            9: 'Module', 10: 'Property', 11: 'Unit', 12: 'Value',
            13: 'Enum', 14: 'Keyword', 15: 'Snippet', 16: 'Color',
            17: 'File', 18: 'Reference', 19: 'Folder', 20: 'EnumMember',
            21: 'Constant', 22: 'Struct', 23: 'Event', 24: 'Operator',
            25: 'TypeParameter',
        };
        return map[kind] || 'Text';
    }
}

// 全局单例
let instance: LSPProcessManager | null = null;

export function getLSPProcessManager(): LSPProcessManager {
    if (!instance) {
        instance = new LSPProcessManager();
    }
    return instance;
}

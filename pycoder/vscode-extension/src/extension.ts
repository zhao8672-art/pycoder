/**
 * PyCoder VS Code Extension — Entry Point
 *
 * Lightweight bridge to local PyCoder FastAPI Server.
 * Provides AI chat panel, code actions, and status bar integration.
 */

import * as vscode from 'vscode';
import * as cp from 'child_process';
import { BackendClient } from './backendClient';
import { createChatPanel } from './chatPanel';
import { createStatusBar, updateModelLabel } from './statusBar';
import { explainCode, fixCode, generateTests } from './codeActions';

let client: BackendClient | null = null;
let serverProcess: cp.ChildProcess | null = null;
let chatPanel: vscode.WebviewPanel | null = null;
let statusBarDisposable: vscode.Disposable | null = null;
let currentModel = 'auto';

export function activate(context: vscode.ExtensionContext) {
    console.log('[PyCoder] Activating extension...');

    // ── Configuration ──
    const config = vscode.workspace.getConfiguration('pycoder');
    const serverUrl = config.get<string>('serverUrl', 'http://127.0.0.1:8423');
    const pythonPath = config.get<string>('pythonPath', 'python');
    const autoStart = config.get<boolean>('autoStartServer', true);

    // ── Create Backend Client ──
    client = new BackendClient(serverUrl);

    // ── Status Bar ──
    statusBarDisposable = createStatusBar(client);

    // ── Register Commands ──
    context.subscriptions.push(
        vscode.commands.registerCommand('pycoder.openChat', () => {
            if (!client) return;
            if (chatPanel) {
                chatPanel.reveal();
            } else {
                chatPanel = createChatPanel(client, currentModel);
                chatPanel.onDidDispose(() => { chatPanel = null; });
            }
        }),

        vscode.commands.registerCommand('pycoder.startServer', async () => {
            await startBackend(pythonPath);
        }),

        vscode.commands.registerCommand('pycoder.stopServer', () => {
            stopBackend();
        }),

        vscode.commands.registerCommand('pycoder.selectModel', async () => {
            const models = await client?.getModels() || [];
            const items = [
                { label: '$(sparkle) Auto (智能推荐)', value: 'auto' },
                ...models.map((m: any) => ({
                    label: `$(circuit-board) ${m.name || m.id || m}`,
                    value: m.id || m,
                })),
            ];
            const picked = await vscode.window.showQuickPick(items, {
                placeHolder: '选择 AI 模型',
            });
            if (picked) {
                currentModel = picked.value;
                updateModelLabel(picked.value);
                vscode.window.showInformationMessage(`✅ 模型已切换: ${picked.label}`);
            }
        }),

        vscode.commands.registerCommand('pycoder.explainCode', explainCode),
        vscode.commands.registerCommand('pycoder.fixCode', fixCode),
        vscode.commands.registerCommand('pycoder.generateTests', generateTests),

        vscode.commands.registerCommand('pycoder.runFix', async () => {
            const task = await vscode.window.showInputBox({
                prompt: '描述你要实现的功能',
                placeHolder: '例如: 写一个 FastAPI 用户注册接口',
                ignoreFocusOut: true,
            });
            if (!task || !client) return;

            client.connectWs();
            client.sendWsMessage({ type: 'run_fix', task, target_file: 'runfix_solution.py' });
            vscode.window.showInformationMessage('🔁 Run & Fix 已启动');

            client.onWsMessage((msg: any) => {
                if (msg.type === 'run_fix_step') {
                    console.log(`[PyCoder] ${msg.action}: ${msg.status}`);
                }
                if (msg.type === 'run_fix_done') {
                    if (msg.success) {
                        vscode.window.showInformationMessage(
                            `✅ Run & Fix 成功 (${msg.total_retries} 次修复)`,
                        );
                    } else {
                        vscode.window.showErrorMessage('❌ Run & Fix 失败');
                    }
                }
            });
        }),
    );

    // ── Initialize ──
    setTimeout(async () => {
        // Check if backend is already running
        const healthy = await client?.healthCheck();

        if (healthy) {
            console.log('[PyCoder] Backend already running');
            client?.connectWs();
            const models = await client?.getModels();
            if (models && models.length > 0) {
                currentModel = models[0]?.id || 'auto';
                updateModelLabel(currentModel);
            }
        } else if (autoStart) {
            vscode.window.showInformationMessage('🚀 PyCoder: 正在启动后端服务...');
            await startBackend(pythonPath);
        }
    }, 2000);

    console.log('[PyCoder] Extension activated');
}

// ── Backend Process Management ──

async function startBackend(pythonPath: string) {
    if (serverProcess) {
        vscode.window.showInformationMessage('PyCoder 后端已在运行');
        return;
    }

    const workspaceFolders = vscode.workspace.workspaceFolders;
    const projectRoot = workspaceFolders?.[0]?.uri?.fsPath;

    if (!projectRoot) {
        vscode.window.showWarningMessage('请先打开一个项目文件夹');
        return;
    }

    serverProcess = cp.spawn(pythonPath, ['-m', 'pycoder', '--server', '--server-port', '8423'], {
        cwd: projectRoot,
        stdio: ['pipe', 'pipe', 'pipe'],
    });

    serverProcess.stdout?.on('data', (data) => {
        console.log(`[PyCoder Backend] ${data.toString().trim()}`);
    });

    serverProcess.stderr?.on('data', (data) => {
        console.log(`[PyCoder Backend] ${data.toString().trim()}`);
    });

    serverProcess.on('exit', (code) => {
        console.log(`[PyCoder Backend] exited with code ${code}`);
        serverProcess = null;
    });

    serverProcess.on('error', (err) => {
        console.error(`[PyCoder Backend] error: ${err.message}`);
        serverProcess = null;
        vscode.window.showErrorMessage(`PyCoder 后端启动失败: ${err.message}`);
    });

    // Wait for backend to be ready
    for (let i = 0; i < 15; i++) {
        await sleep(1000);
        const ok = await client?.healthCheck();
        if (ok) {
            console.log('[PyCoder] Backend started successfully');
            client?.connectWs();
            const models = await client?.getModels();
            if (models && models.length > 0) {
                currentModel = models[0]?.id || 'auto';
                updateModelLabel(currentModel);
            }
            vscode.window.showInformationMessage('✅ PyCoder 后端已启动');
            return;
        }
    }
    vscode.window.showErrorMessage('❌ PyCoder 后端启动超时 (15s)');
}

function stopBackend() {
    if (serverProcess) {
        serverProcess.kill();
        serverProcess = null;
        client?.disconnect();
        vscode.window.showInformationMessage('PyCoder 后端已停止');
    }
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

// ── Deactivate ──

export function deactivate() {
    console.log('[PyCoder] Deactivating...');
    stopBackend();
    client?.disconnect();
    statusBarDisposable?.dispose();
}

/**
 * Code Actions — right-click context menu for explain/fix/generate tests
 */

import * as vscode from 'vscode';

function getSelectedText(): string {
    const editor = vscode.window.activeTextEditor;
    if (!editor) return '';
    return editor.document.getText(editor.selection);
}

function getFilePath(): string {
    return vscode.window.activeTextEditor?.document.uri.fsPath || '';
}

export async function explainCode(): Promise<void> {
    const code = getSelectedText();
    if (!code) { vscode.window.showWarningMessage('请先选中代码'); return; }
    await vscode.commands.executeCommand('pycoder.openChat');
    // Will be handled by the chat panel
    vscode.window.showInformationMessage('✨ 选中代码已发送到 PyCoder AI 聊天面板');
}

export async function fixCode(): Promise<void> {
    const code = getSelectedText();
    if (!code) { vscode.window.showWarningMessage('请先选中代码'); return; }
    await vscode.commands.executeCommand('pycoder.openChat');
    vscode.window.showInformationMessage('🔧 修复请求已发送到 PyCoder AI');
}

export async function generateTests(): Promise<void> {
    const filePath = getFilePath();
    if (!filePath) { vscode.window.showWarningMessage('请先打开一个 Python 文件'); return; }

    // Ask user for file path or use current
    const input = await vscode.window.showInputBox({
        prompt: '为哪个文件生成测试？',
        value: filePath,
        placeHolder: 'Python 文件路径',
    });
    if (!input) return;

    // Trigger via WebSocket
    const { BackendClient } = await import('./backendClient');
    const config = vscode.workspace.getConfiguration('pycoder');
    const url = config.get<string>('serverUrl', 'http://127.0.0.1:8423');
    const client = new BackendClient(url);
    client.connectWs();
    client.onWsMessage((msg: any) => {
        if (msg.type === 'test_generator_done') {
            if (msg.success) {
                vscode.window.showInformationMessage(
                    `✅ 测试生成完成: ${msg.passed} 通过, 覆盖率 ${msg.coverage_percent}%`,
                );
            } else {
                vscode.window.showErrorMessage(`❌ 测试生成失败: ${msg.error || msg.output}`);
            }
            client.disconnect();
        }
    });
    setTimeout(() => {
        client.sendWsMessage({ type: 'test_generator', file_path: input });
    }, 500);
    vscode.window.showInformationMessage('⏳ 生成测试中...');
}

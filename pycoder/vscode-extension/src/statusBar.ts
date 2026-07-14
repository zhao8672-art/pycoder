/**
 * Status Bar — shows PyCoder backend connection status & model
 */

import * as vscode from 'vscode';
import { BackendClient } from './backendClient';

let statusItem: vscode.StatusBarItem;

export function createStatusBar(client: BackendClient): vscode.Disposable {
    statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusItem.command = 'pycoder.openChat';
    updateStatus('starting');
    statusItem.show();

    client.onStatusChange = (status) => updateStatus(status);
    return statusItem;
}

function updateStatus(status: string) {
    if (!statusItem) return;
    switch (status) {
        case 'connected':
            statusItem.text = '$(check) PyCoder';
            statusItem.tooltip = 'PyCoder AI — 已连接';
            statusItem.backgroundColor = undefined;
            break;
        case 'connecting':
            statusItem.text = '$(sync~spin) PyCoder';
            statusItem.tooltip = 'PyCoder AI — 连接中...';
            break;
        case 'disconnected':
        case 'starting':
            statusItem.text = '$(circle-slash) PyCoder';
            statusItem.tooltip = 'PyCoder AI — 未连接 (点击启动)';
            statusItem.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
            break;
    }
}

export function updateModelLabel(model: string) {
    if (statusItem) {
        statusItem.text = `$(check) PyCoder: ${model}`;
    }
}

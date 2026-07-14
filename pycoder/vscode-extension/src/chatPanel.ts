/**
 * Chat Panel — WebView for AI chat in VS Code
 */

import * as vscode from 'vscode';
import { BackendClient } from './backendClient';

export function createChatPanel(client: BackendClient, model: string): vscode.WebviewPanel {
    const panel = vscode.window.createWebviewPanel(
        'pycoderChat',
        'PyCoder AI Chat',
        vscode.ViewColumn.Beside,
        { enableScripts: true, retainContextWhenHidden: true },
    );

    let chatStreaming = false;
    const unsubs: (() => void)[] = [];

    panel.webview.html = getChatHtml();

    // Listen for WebSocket messages → forward to WebView
    unsubs.push(client.onWsMessage((msg: any) => {
        if (!panel.webview) return;
        if (msg.type === 'token') {
            panel.webview.postMessage({ type: 'token', data: msg.data || msg.content || '' });
        } else if (msg.type === 'reasoning') {
            panel.webview.postMessage({ type: 'reasoning', data: msg.data || msg.content || '' });
        } else if (msg.type === 'done') {
            chatStreaming = false;
            panel.webview.postMessage({ type: 'done', content: msg.content || '' });
        } else if (msg.type === 'error') {
            chatStreaming = false;
            panel.webview.postMessage({ type: 'error', message: msg.data || msg.message || 'Error' });
        }
    }));

    // Handle messages from WebView
    panel.webview.onDidReceiveMessage((msg: any) => {
        if (msg.type === 'chat' && msg.text && !chatStreaming) {
            chatStreaming = true;
            panel.webview.postMessage({ type: 'clearInput' });
            client.sendWsMessage({ type: 'message', message: msg.text, model });
        }
        if (msg.type === 'selectModel') {
            vscode.commands.executeCommand('pycoder.selectModel');
        }
    });

    panel.onDidDispose(() => {
        unsubs.forEach((fn) => fn());
        chatStreaming = false;
    });

    return panel;
}

function getChatHtml(): string {
    return `<!DOCTYPE html>
<html lang="zh">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#1e1e2e;color:#cdd6f4;height:100vh;display:flex;flex-direction:column}
#messages{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:8px}
.msg{padding:8px 12px;border-radius:8px;max-width:85%;line-height:1.5;font-size:13px;white-space:pre-wrap;word-break:break-word}
.msg-user{background:#45475a;align-self:flex-end}
.msg-ai{background:#313244;align-self:flex-start}
.msg-thinking{background:#1e1e2e;border-left:3px solid #f9e2af;font-size:12px;color:#a6adc8;font-style:italic}
.msg-error{background:#f38ba8;color:#1e1e2e;align-self:center;font-size:12px}
#input-area{display:flex;padding:8px;gap:6px;border-top:1px solid #45475a}
#input{flex:1;background:#313244;border:1px solid #45475a;border-radius:6px;padding:8px;color:#cdd6f4;font-size:13px;resize:none;font-family:inherit}
#input:focus{outline:none;border-color:#89b4fa}
#send-btn{background:#89b4fa;border:none;border-radius:6px;padding:8px 16px;color:#1e1e2e;font-weight:600;cursor:pointer;font-size:13px}
#send-btn:disabled{opacity:0.5;cursor:default}
#status-bar{display:flex;justify-content:space-between;padding:4px 12px;font-size:11px;color:#a6adc8;background:#181825}
</style>
</head>
<body>
<div id="messages"></div>
<div id="input-area">
<textarea id="input" placeholder="输入消息... (Enter 发送, Shift+Enter 换行)" rows="2"></textarea>
<button id="send-btn" onclick="send()">发送</button>
</div>
<div id="status-bar"><span>🧠 PyCoder AI</span><span id="status-text">就绪</span></div>
<script>
const vscode = acquireVsCodeApi();
let streaming = false;

function addMsg(html, cls) {
  const div = document.createElement('div');
  div.className = 'msg ' + cls;
  div.innerHTML = html;
  document.getElementById('messages').appendChild(div);
  div.scrollIntoView({behavior:'smooth'});
}

function updateLastMsg(text) {
  const msgs = document.getElementById('messages').children;
  for (let i = msgs.length-1; i >= 0; i--) {
    if (msgs[i].className.includes('msg-ai') || msgs[i].className.includes('msg-thinking')) {
      msgs[i].innerHTML = text;
      msgs[i].scrollIntoView({behavior:'smooth'});
      return;
    }
  }
}

function send() {
  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text || streaming) return;
  addMsg(escapeHtml(text), 'msg-user');
  vscode.postMessage({type:'chat', text});
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

document.getElementById('input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});

window.addEventListener('message', function(event) {
  const msg = event.data;
  if (msg.type === 'token') {
    streaming = true;
    document.getElementById('status-text').textContent = '生成中...';
    if (!document.querySelector('.msg-ai:last-child')) {
      addMsg('', 'msg-ai');
    }
    const aiMsgs = document.querySelectorAll('.msg-ai');
    aiMsgs[aiMsgs.length-1].innerHTML += escapeHtml(msg.data);
    aiMsgs[aiMsgs.length-1].scrollIntoView({behavior:'smooth'});
  } else if (msg.type === 'reasoning') {
    addMsg('🧠 ' + escapeHtml(msg.data), 'msg-thinking');
  } else if (msg.type === 'done') {
    streaming = false;
    document.getElementById('status-text').textContent = '就绪';
  } else if (msg.type === 'error') {
    streaming = false;
    document.getElementById('status-text').textContent = '错误';
    addMsg('❌ ' + escapeHtml(msg.message), 'msg-error');
  } else if (msg.type === 'clearInput') {
    document.getElementById('input').value = '';
  }
});
</script>
</body></html>`;
}
